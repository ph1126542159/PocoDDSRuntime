#!/usr/bin/env python3
"""Verify durable lifecycle plans, startup crash recovery and cross-restart idempotency."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


TOKEN = "lifecycle-recovery-secret"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--seed-executable", type=Path, required=True)
    parser.add_argument("--working-directory", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args()


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def request(base: str, path: str, body: dict[str, object] | None = None,
            request_id: str | None = None) -> tuple[int, dict[str, object]]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Accept": "application/json", "Authorization": f"Bearer {TOKEN}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if request_id:
        headers["X-PDR-Request-Id"] = request_id
    incoming = urllib.request.Request(
        base + path, data=data, headers=headers,
        method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(incoming, timeout=10) as response:
            payload = response.read().decode()
            return response.status, json.loads(payload) if payload else {}
    except urllib.error.HTTPError as error:
        payload = error.read().decode()
        return error.code, json.loads(payload) if payload else {}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def wait_ready(base: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Runtime exited during startup: {process.returncode}")
        try:
            if request(base, "/health/ready")[0] == 200:
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.2)
    raise TimeoutError("Runtime did not become ready after lifecycle recovery")


def wait_live(base: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Runtime exited during startup: {process.returncode}")
        try:
            if request(base, "/health/live")[0] == 200:
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.2)
    raise TimeoutError("Runtime did not become live with pending recovery")


def stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
        process.wait(timeout=12)
    except (OSError, subprocess.TimeoutExpired):
        process.kill()
        process.wait(timeout=5)


def start(options: argparse.Namespace, overlay: Path, environment: dict[str, str],
          log_path: Path) -> tuple[subprocess.Popen[bytes], object]:
    option = f"/config-file={overlay}" if os.name == "nt" else f"--config-file={overlay}"
    log = log_path.open("wb")
    process = subprocess.Popen(
        [str(options.executable.resolve()), option],
        cwd=options.working_directory.resolve(), env=environment,
        stdout=log, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        start_new_session=os.name != "nt")
    return process, log


def seed(options: argparse.Namespace, database: Path, status: str,
         environment: dict[str, str],
         target: str = "pdr.service.schedulerRuntime") -> str:
    command = [str(options.seed_executable.resolve()),
               "--database", str(database), "--status", status,
               "--target", target,
               "--consumer", "pdr.service.outboxRuntime",
               "--consumer", "pdr.service.workflowRuntime"]
    result = subprocess.run(
        command, cwd=options.working_directory.resolve(), env=environment,
        check=False, capture_output=True, text=True, timeout=15)
    require(result.returncode == 0,
            f"journal seed failed: {result.returncode}, {result.stderr}")
    plan_id = result.stdout.strip()
    require(plan_id.startswith("maintenance-"),
            f"journal seed returned invalid plan ID: {result.stdout}")
    return plan_id


def main() -> int:
    options = parse_args()
    workspace = options.workspace.resolve()
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    database = workspace / "maintenance.sqlite"
    port = free_port()
    overlay = workspace / "runtime.properties"
    overlay.write_text(
        options.config.read_text(encoding="utf-8") + "\n" + "\n".join([
            "osp.web.server.host = 127.0.0.1",
            f"osp.web.server.port = {port}",
            "osp.web.server.securePort = 0",
            "pdr.management.authentication.required = true",
            "pdr.management.authentication.principals.count = 1",
            "pdr.management.authentication.principals.0.id = lifecycle-recovery-manager",
            "pdr.management.authentication.principals.0.tokenEnvironment = PDR_LIFECYCLE_RECOVERY_TOKEN",
            "pdr.management.authentication.principals.0.permissions = bundle.manage,resource.read",
            f"pdr.lifecycleRuntime.database = {database.as_posix()}",
            "pdr.mqtt.count = 0", "pdr.ros.count = 0", "pdr.udp.count = 0",
        ]) + "\n", encoding="utf-8", newline="\n")
    environment = os.environ.copy()
    environment["PDR_LIFECYCLE_RECOVERY_TOKEN"] = TOKEN
    environment["PATH"] = os.pathsep.join(
        [str(Path(item).resolve()) for item in options.path] +
        [str(options.working_directory.resolve()), environment.get("PATH", "")])
    cache = options.working_directory.resolve() / "codeCache"
    if cache.exists():
        shutil.rmtree(cache)

    report: dict[str, object] = {"schemaVersion": 1, "passed": False}
    processes: list[subprocess.Popen[bytes]] = []
    logs: list[object] = []
    try:
        drain_seed = seed(options, database, "draining", environment)
        restore_seed = seed(options, database, "restoring", environment)
        base = f"http://127.0.0.1:{port}"
        first, first_log = start(
            options, overlay, environment, workspace / "runtime-first.log")
        processes.append(first)
        logs.append(first_log)
        wait_ready(base, first)

        status, snapshot = request(base, "/api/v1/lifecycle-maintenance")
        plans = {str(item.get("id")): item for item in snapshot.get("plans", [])
                 if isinstance(item, dict)}
        require(status == 200 and
                plans.get(drain_seed, {}).get("status") == "rolledBack" and
                plans.get(drain_seed, {}).get("code") == "DRAIN_CRASH_RECOVERED" and
                plans.get(restore_seed, {}).get("status") == "restored" and
                plans.get(restore_seed, {}).get("code") == "RESTORE_CRASH_RECOVERED",
                f"startup crash recovery mismatch: {status}, {snapshot}")

        drain_body = {"action": "drain", "target": "pdr.service.schedulerRuntime",
                      "timeoutMilliseconds": 5000}
        drain_status, drain = request(base, "/api/v1/lifecycle-maintenance",
                                      drain_body, "durable-drain-1")
        durable_plan = drain.get("plan", {})
        require(drain_status == 200 and drain.get("succeeded") is True and
                isinstance(durable_plan, dict) and
                durable_plan.get("status") == "drained",
                f"durable drain failed: {drain_status}, {drain}")
        plan_id = str(durable_plan.get("id"))
        restore_body = {"action": "restore", "planId": plan_id}
        stop(first)
        first_log.close()
        require(first.returncode == 0, "first Runtime did not shut down cleanly")

        second, second_log = start(
            options, overlay, environment, workspace / "runtime-second.log")
        processes.append(second)
        logs.append(second_log)
        wait_ready(base, second)
        desired_status, desired_snapshot = request(
            base, "/api/v1/lifecycle-maintenance")
        desired_plans = {
            str(item.get("id")): item
            for item in desired_snapshot.get("plans", [])
            if isinstance(item, dict)
        }
        require(desired_status == 200 and
                desired_plans.get(plan_id, {}).get("status") == "drained" and
                desired_plans.get(plan_id, {}).get("desiredState") == "stopped" and
                desired_plans.get(plan_id, {}).get("code") == "DRAIN_COMPLETE",
                f"durable desired-stopped plan was not retained: "
                f"{desired_status}, {desired_snapshot}")
        blocked_status, blocked = request(
            base, "/api/v1/service-dependencies/impact?"
                  "action=start&target=pdr.service.workflowRuntime")
        require(blocked_status == 200 and blocked.get("allowed") is False and
                int(blocked.get("blockerCount", 0)) >= 1,
                f"desired-stopped topology was unexpectedly active: "
                f"{blocked_status}, {blocked}")
        restore_status, restored = request(
            base, "/api/v1/lifecycle-maintenance", restore_body,
            "durable-restore-1")
        require(restore_status == 200 and restored.get("succeeded") is True and
                restored.get("idempotentReplay") is False and
                restored.get("plan", {}).get("desiredState") == "active",
                f"durable desired-state restore failed: "
                f"{restore_status}, {restored}")
        replay_status, replay = request(
            base, "/api/v1/lifecycle-maintenance", drain_body,
            "durable-drain-1")
        require(replay_status == 200 and replay.get("idempotentReplay") is True and
                replay.get("plan", {}).get("id") == plan_id,
                f"cross-restart drain replay failed: {replay_status}, {replay}")
        impact_status, impact = request(
            base, "/api/v1/service-dependencies/impact?"
                  "action=stop&target=pdr.service.schedulerRuntime")
        require(impact_status == 200 and impact.get("allowed") is False,
                f"replayed drain mutated restored topology: {impact_status}, {impact}")
        restore_replay_status, restore_replay = request(
            base, "/api/v1/lifecycle-maintenance", restore_body,
            "durable-restore-1")
        require(restore_replay_status == 200 and
                restore_replay.get("idempotentReplay") is True,
                f"cross-restart restore replay failed: {restore_replay_status}, {restore_replay}")
        reuse_status, reuse = request(
            base, "/api/v1/lifecycle-maintenance",
            {**drain_body, "timeoutMilliseconds": 4000}, "durable-drain-1")
        require(reuse_status == 400 and
                reuse.get("code") == "LIFECYCLE_REQUEST_INVALID",
                f"durable request binding failed: {reuse_status}, {reuse}")
        final_status, final = request(base, "/api/v1/lifecycle-maintenance")
        require(final_status == 200 and int(final.get("planCount", 0)) >= 3,
                f"persisted plan history was lost: {final_status}, {final}")
        stop(second)
        second_log.close()
        require(second.returncode == 0, "second Runtime did not shut down cleanly")

        pending_database = workspace / "pending-maintenance.sqlite"
        pending_overlay = workspace / "pending-runtime.properties"
        pending_overlay.write_text(
            overlay.read_text(encoding="utf-8").replace(
                database.as_posix(), pending_database.as_posix()),
            encoding="utf-8", newline="\n")
        pending_plan = seed(
            options, pending_database, "draining", environment,
            target="missing.provider.bundle")
        third, third_log = start(
            options, pending_overlay, environment, workspace / "runtime-pending.log")
        processes.append(third)
        logs.append(third_log)
        wait_live(base, third)
        ready_status, _ = request(base, "/health/ready")
        pending_status, pending_snapshot = request(
            base, "/api/v1/lifecycle-maintenance")
        pending_plans = {
            str(item.get("id")): item for item in pending_snapshot.get("plans", [])
            if isinstance(item, dict)}
        require(ready_status == 503 and pending_status == 200 and
                pending_plans.get(pending_plan, {}).get("status") ==
                    "drainRecoveryPending" and
                pending_plans.get(pending_plan, {}).get("code") ==
                    "LIFECYCLE_CRASH_RECOVERY_INCOMPLETE",
                f"pending recovery health gate mismatch: {ready_status}, {pending_snapshot}")
        recovery_body = {"action": "recover", "planId": pending_plan}
        recovery_status, recovery = request(
            base, "/api/v1/lifecycle-maintenance", recovery_body,
            "manual-recover-1")
        recovery_replay_status, recovery_replay = request(
            base, "/api/v1/lifecycle-maintenance", recovery_body,
            "manual-recover-1")
        health_status, health = request(base, "/health/detail")
        components = {str(item.get("name")): item
                      for item in health.get("components", [])
                      if isinstance(item, dict)}
        lifecycle_health = components.get("lifecycle-maintenance", {})
        require(recovery_status == 503 and recovery.get("succeeded") is False and
                recovery_replay_status == 503 and
                recovery_replay.get("idempotentReplay") is True and
                health_status == 200 and
                lifecycle_health.get("code") ==
                    "PDR-HEALTH-LIFECYCLE-RECOVERY_PENDING",
                f"manual durable recovery retry mismatch: {recovery_status}, "
                f"{recovery}, {recovery_replay_status}, {recovery_replay}, {health}")
        stop(third)
        third_log.close()
        require(third.returncode == 0, "pending Runtime did not shut down cleanly")

        corrupt_database = workspace / "corrupt-maintenance.sqlite"
        corrupt_database.write_bytes(b"not-a-sqlite-database")
        corrupt_overlay = workspace / "corrupt-runtime.properties"
        corrupt_overlay.write_text(
            overlay.read_text(encoding="utf-8").replace(
                database.as_posix(), corrupt_database.as_posix()),
            encoding="utf-8", newline="\n")
        fourth, fourth_log = start(
            options, corrupt_overlay, environment,
            workspace / "runtime-corrupt-store.log")
        processes.append(fourth)
        logs.append(fourth_log)
        wait_live(base, fourth)
        corrupt_ready, _ = request(base, "/health/ready")
        corrupt_health_status, corrupt_health = request(base, "/health/detail")
        corrupt_components = {
            str(item.get("name")): item
            for item in corrupt_health.get("components", [])
            if isinstance(item, dict)
        }
        corrupt_lifecycle = corrupt_components.get(
            "lifecycle-maintenance", {})
        business_status, _ = request(base, "/api/v1/scheduled-tasks")
        lifecycle_status, lifecycle_unavailable = request(
            base, "/api/v1/lifecycle-maintenance")
        require(corrupt_ready == 503 and corrupt_health_status == 200 and
                corrupt_lifecycle.get("code") ==
                    "PDR-HEALTH-LIFECYCLE-DESIRED-STATE-UNAVAILABLE" and
                business_status == 404 and lifecycle_status == 404 and
                lifecycle_unavailable.get("code") ==
                    "LIFECYCLE_RESOURCE_NOT_FOUND",
                "corrupt desired-state store did not fail closed: "
                f"ready={corrupt_ready}, health={corrupt_health}, "
                f"business={business_status}, lifecycle="
                f"{lifecycle_status}/{lifecycle_unavailable}")
        stop(fourth)
        fourth_log.close()
        require(fourth.returncode == 0,
                "corrupt-store Runtime did not shut down cleanly")
        report.update({
            "passed": True,
            "drainCrashPlan": drain_seed,
            "restoreCrashPlan": restore_seed,
            "durablePlan": plan_id,
            "startupRecoveryVerified": True,
            "drainedRestartDesiredStateVerified": True,
            "desiredStoppedTopologyVerified": True,
            "explicitRestoreRequired": True,
            "crossRestartDrainReplayVerified": True,
            "crossRestartRestoreReplayVerified": True,
            "requestBindingPersisted": True,
            "replayHadNoLifecycleSideEffect": True,
            "pendingRecoveryPlan": pending_plan,
            "pendingRecoveryBlockedReadiness": True,
            "manualRecoveryReplayVerified": True,
            "corruptStoreFailedClosed": True,
            "corruptStoreBlockedReadiness": True,
            "corruptStoreBlockedBusinessBundles": True,
            "database": str(database),
        })
        print("RUNTIME_LIFECYCLE_RECOVERY_PASS startup=4 replay=3 "
              "recovery=2 desiredState=1 failClosed=1")
    except Exception as error:
        report["error"] = str(error)
    finally:
        for process in processes:
            stop(process)
        for log in logs:
            if not log.closed:
                log.close()
        report["cleanShutdown"] = all(
            process.returncode == 0 for process in processes)
        options.report.parent.mkdir(parents=True, exist_ok=True)
        options.report.write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report.get("passed") and report.get("cleanShutdown") else 1


if __name__ == "__main__":
    raise SystemExit(main())
