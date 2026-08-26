#!/usr/bin/env python3
"""Exercise transactional Bundle drain, fail-closed preflight, restore and idempotency."""

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


MANAGER_TOKEN = "lifecycle-manager-secret"
READER_TOKEN = "lifecycle-reader-secret"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
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


def request(base: str, path: str, token: str | None = None,
            body: dict[str, object] | None = None,
            request_id: str | None = None) -> tuple[int, dict[str, object]]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
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
    raise TimeoutError("Runtime did not become ready")


def stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
        process.wait(timeout=12)
    except (OSError, subprocess.TimeoutExpired):
        process.kill()
        process.wait(timeout=5)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    options = parse_args()
    workspace = options.workspace.resolve()
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    port = free_port()
    overlay = workspace / "runtime.properties"
    overlay.write_text(
        options.config.read_text(encoding="utf-8") + "\n" + "\n".join([
            "osp.web.server.host = 127.0.0.1",
            f"osp.web.server.port = {port}",
            "osp.web.server.securePort = 0",
            "pdr.management.authentication.required = true",
            "pdr.management.authentication.principals.count = 2",
            "pdr.management.authentication.principals.0.id = lifecycle-manager",
            "pdr.management.authentication.principals.0.tokenEnvironment = PDR_LIFECYCLE_MANAGER_TOKEN",
            "pdr.management.authentication.principals.0.permissions = bundle.manage,resource.read",
            "pdr.management.authentication.principals.1.id = lifecycle-reader",
            "pdr.management.authentication.principals.1.tokenEnvironment = PDR_LIFECYCLE_READER_TOKEN",
            "pdr.management.authentication.principals.1.permissions = resource.read",
            f"pdr.lifecycleRuntime.database = {(workspace / 'maintenance.sqlite').as_posix()}",
            "pdr.mqtt.count = 0", "pdr.ros.count = 0", "pdr.udp.count = 0",
        ]) + "\n", encoding="utf-8", newline="\n")

    environment = os.environ.copy()
    environment["PDR_LIFECYCLE_MANAGER_TOKEN"] = MANAGER_TOKEN
    environment["PDR_LIFECYCLE_READER_TOKEN"] = READER_TOKEN
    environment["PATH"] = os.pathsep.join(
        [str(Path(item).resolve()) for item in options.path] +
        [environment.get("PATH", "")])
    cache = options.working_directory.resolve() / "codeCache"
    if cache.exists():
        shutil.rmtree(cache)
    option = f"/config-file={overlay}" if os.name == "nt" else f"--config-file={overlay}"
    log_path = workspace / "runtime.log"
    log = log_path.open("wb")
    process = subprocess.Popen(
        [str(options.executable.resolve()), option],
        cwd=options.working_directory.resolve(), env=environment,
        stdout=log, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        start_new_session=os.name != "nt")
    base = f"http://127.0.0.1:{port}"
    report: dict[str, object] = {"schemaVersion": 1, "passed": False}
    try:
        wait_ready(base, process)
        status, initial = request(base, "/api/v1/lifecycle-maintenance", READER_TOKEN)
        participants = initial.get("participants", [])
        owners = {str(item.get("owner")) for item in participants if isinstance(item, dict)}
        require(status == 200 and owners == {
            "pdr.service.workflowRuntime", "pdr.service.outboxRuntime"},
            f"drain participant discovery mismatch: {status}, {owners}")

        denied_status, denied = request(
            base, "/api/v1/lifecycle-maintenance", READER_TOKEN,
            {"action": "drain", "target": "pdr.service.schedulerRuntime"}, "denied-1")
        require(denied_status == 403 and denied.get("code") == "LIFECYCLE_PERMISSION_DENIED",
                f"least privilege drain was not denied: {denied_status}, {denied}")
        missing_id_status, missing_id = request(
            base, "/api/v1/lifecycle-maintenance", MANAGER_TOKEN,
            {"action": "drain", "target": "pdr.service.schedulerRuntime"})
        require(missing_id_status == 428 and
                missing_id.get("code") == "LIFECYCLE_REQUEST_ID_REQUIRED",
                f"missing request ID was not rejected: {missing_id_status}, {missing_id}")

        preflight_status, preflight = request(
            base, "/api/v1/lifecycle-maintenance", MANAGER_TOKEN,
            {"action": "drain", "target": "pdr.service.resourceGovernor",
             "timeoutMilliseconds": 1000}, "preflight-1")
        preflight_plan = preflight.get("plan", {})
        preflight_consumers = set(map(
            str, preflight_plan.get("consumers", []))) \
            if isinstance(preflight_plan, dict) else set()
        require(preflight_status == 409 and
                isinstance(preflight_plan, dict) and
                preflight_plan.get("status") == "rolledBack" and
                preflight_plan.get("code") == "DRAIN_ROLLED_BACK" and
                preflight_consumers == {
                    "pdr.service.schedulerRuntime",
                    "pdr.service.workflowRuntime",
                    "pdr.service.outboxRuntime"},
                f"missing participant preflight did not fail closed: {preflight_status}, {preflight}")

        drain_body = {"action": "drain", "target": "pdr.service.schedulerRuntime",
                      "timeoutMilliseconds": 5000}
        drain_status, drained = request(
            base, "/api/v1/lifecycle-maintenance", MANAGER_TOKEN,
            drain_body, "drain-1")
        plan = drained.get("plan", {})
        consumers = set(map(str, plan.get("consumers", []))) if isinstance(plan, dict) else set()
        require(drain_status == 200 and drained.get("succeeded") is True and
                isinstance(plan, dict) and plan.get("status") == "drained" and
                plan.get("code") == "DRAIN_COMPLETE" and consumers == {
                    "pdr.service.workflowRuntime", "pdr.service.outboxRuntime"},
                f"transactional drain failed: {drain_status}, {drained}")
        plan_id = str(plan.get("id"))

        replay_status, replay = request(
            base, "/api/v1/lifecycle-maintenance", MANAGER_TOKEN,
            drain_body, "drain-1")
        require(replay_status == 200 and replay.get("idempotentReplay") is True and
                replay.get("plan", {}).get("id") == plan_id,
                f"drain idempotent replay failed: {replay_status}, {replay}")
        reuse_status, reuse = request(
            base, "/api/v1/lifecycle-maintenance", MANAGER_TOKEN,
            {**drain_body, "timeoutMilliseconds": 4000}, "drain-1")
        require(reuse_status == 400 and reuse.get("code") == "LIFECYCLE_REQUEST_INVALID",
                f"request ID input binding failed: {reuse_status}, {reuse}")

        impact_status, impact = request(
            base, "/api/v1/service-dependencies/impact?action=stop&target=pdr.service.schedulerRuntime",
            READER_TOKEN)
        require(impact_status == 200 and impact.get("allowed") is True and
                int(impact.get("blockerCount", -1)) == 0,
                f"drained Consumers still blocked Provider stop: {impact_status}, {impact}")

        restore_body = {"action": "restore", "planId": plan_id}
        restore_status, restored = request(
            base, "/api/v1/lifecycle-maintenance", MANAGER_TOKEN,
            restore_body, "restore-1")
        require(restore_status == 200 and restored.get("succeeded") is True and
                restored.get("plan", {}).get("status") == "restored" and
                restored.get("plan", {}).get("code") == "RESTORE_COMPLETE",
                f"maintenance restore failed: {restore_status}, {restored}")
        restore_replay_status, restore_replay = request(
            base, "/api/v1/lifecycle-maintenance", MANAGER_TOKEN,
            restore_body, "restore-1")
        require(restore_replay_status == 200 and
                restore_replay.get("idempotentReplay") is True,
                f"restore idempotent replay failed: {restore_replay_status}, {restore_replay}")

        final_status, final = request(base, "/api/v1/lifecycle-maintenance", READER_TOKEN)
        final_participants = final.get("participants", [])
        accepting = {
            str(item.get("owner")) for item in final_participants
            if isinstance(item, dict) and isinstance(item.get("drain"), dict) and
            item["drain"].get("state") == "accepting"
        }
        dependency_status, dependency = request(
            base, "/api/v1/service-dependencies?contract=pdr.scheduling", READER_TOKEN)
        health_status, health = request(base, "/health/detail")
        components = health.get("components", [])
        lifecycle_health = next((item for item in components if isinstance(item, dict) and
                                 item.get("name") == "lifecycle-maintenance"), {})
        require(final_status == 200 and accepting == owners,
                f"restored participants are not accepting: {final_status}, {accepting}")
        require(dependency_status == 200 and dependency.get("ready") is True and
                int(dependency.get("requiredBlocked", -1)) == 0,
                f"dependency readiness did not recover: {dependency_status}, {dependency}")
        require(health_status == 200 and lifecycle_health.get("status") == "UP",
                f"lifecycle health did not recover: {health_status}, {lifecycle_health}")

        report.update({
            "passed": True,
            "participantOwners": sorted(owners),
            "leastPrivilegeDenied": True,
            "requestIdRequired": True,
            "missingParticipantFailedClosed": True,
            "transitiveConsumerDiscoveryVerified": True,
            "drainPlanId": plan_id,
            "drainConsumers": sorted(consumers),
            "drainReplayVerified": True,
            "requestIdInputBindingVerified": True,
            "providerStopAdmissionCleared": True,
            "restoreVerified": True,
            "restoreReplayVerified": True,
            "participantsAcceptingAfterRestore": True,
            "dependencyReadinessRecovered": True,
            "healthUp": True,
            "log": str(log_path),
        })
        print("RUNTIME_LIFECYCLE_MAINTENANCE_PASS participants=2 drainConsumers=2 transitions=2")
    except Exception as error:
        report["error"] = str(error)
    finally:
        stop(process)
        log.close()
        report["cleanShutdown"] = process.returncode == 0
        options.report.parent.mkdir(parents=True, exist_ok=True)
        options.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report.get("passed") and report.get("cleanShutdown") else 1


if __name__ == "__main__":
    raise SystemExit(main())
