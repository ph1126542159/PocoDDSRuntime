#!/usr/bin/env python3
"""Verify managed-process operator stop across an isolated Runtime restart."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from runtime_smoke import free_port, probe, stop_tree, write_overlay


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--bundle-repository", required=True, type=Path)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--hold-after-validation-seconds", type=float, default=0.0)
    args = parser.parse_args()
    if args.hold_after_validation_seconds < 0:
        parser.error("--hold-after-validation-seconds must be non-negative")
    return args


def copy_required_bundles(source: Path, destination: Path) -> None:
    prefixes = (
        "osp.core_", "osp.web_", "osp.web.server_", "poco.net_",
        "pdr.platform.health_", "pdr.platform.managementAuth_",
        "pdr.platform.processGraph_", "pdr.platform.systemMonitoring_",
        "pdr.webui.home_",
    )
    destination.mkdir(parents=True)
    for prefix in prefixes:
        matches = sorted(source.glob(prefix + "*.bndl"))
        if len(matches) != 1:
            raise RuntimeError(
                f"expected one bundle matching {prefix}*.bndl, found {len(matches)}"
            )
        shutil.copy2(matches[0], destination / matches[0].name)


def write_subprocess_configuration(
    destination: Path, process_root_name: str, event_path: Path, state_name: str
) -> None:
    relative_directory = f"processes/{process_root_name}"
    lines = [
        "subprocess.count = 1",
        "subprocess.supervisionIntervalMilliseconds = 50",
        "subprocess.desiredStatePersistence.enabled = true",
        f"subprocess.desiredStatePersistence.path = data/{state_name}",
        "subprocess.desiredStatePersistence.scrubIntervalMilliseconds = 100",
        "subprocess.0.enabled = true",
        "subprocess.0.name = durable-e2e-worker",
        "subprocess.0.location = local",
        "subprocess.0.required = false",
        "subprocess.0.dependency.count = 0",
        f"subprocess.0.path = {relative_directory}/dependency-fixture.exe",
        f"subprocess.0.workingDirectory = {relative_directory}",
        "subprocess.0.restartPolicy = never",
        "subprocess.0.argument.count = 5",
        "subprocess.0.argument.0 = --dependency-child",
        "subprocess.0.argument.1 = durable-e2e-worker",
        f"subprocess.0.argument.2 = {event_path.as_posix()}",
        "subprocess.0.argument.3 = -",
        "subprocess.0.argument.4 = 0",
    ]
    destination.write_text(
        "\n".join(lines) + "\n", encoding="utf-8", newline="\n"
    )


def post_json(url: str, body: dict[str, object], timeout: float) -> tuple[int, str]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace")


def node(graph: dict[str, object]) -> dict[str, object] | None:
    nodes = graph.get("nodes", [])
    if not isinstance(nodes, list):
        return None
    for value in nodes:
        if isinstance(value, dict) and value.get("name") == "durable-e2e-worker":
            return value
    return None


def require_persistence_status(
    graph: dict[str, object], generation: int, previous_available: bool
) -> dict[str, object]:
    value = graph.get("desiredStatePersistence")
    if not isinstance(value, dict):
        raise RuntimeError("process graph omitted desired-state persistence status")
    if (value.get("enabled") is not True or
            value.get("healthy") is not True or
            value.get("leaseHeld") is not True or
            value.get("recoveredFromPrevious") is not False or
            value.get("primaryValid") is not True or
            value.get("previousAvailable") is not previous_available or
            value.get("previousValid") is not previous_available or
            value.get("generation") != generation or
            not isinstance(value.get("lastIntegrityCheckEpochMicroseconds"), int) or
            value.get("lastIntegrityCheckEpochMicroseconds", 0) <= 0 or
            value.get("state") != "healthy" or
            value.get("integrityState") != "healthy"):
        raise RuntimeError(
            "process graph desired-state persistence status is incorrect: " +
            json.dumps(value, sort_keys=True)
        )
    return value


def wait_for_persistence_state(
    process: subprocess.Popen[bytes], url: str, timeout: float,
    integrity_state: str
) -> tuple[dict[str, object], dict[str, object]]:
    deadline = time.monotonic() + timeout
    last_observation = "no HTTP response"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Runtime exited with code {process.returncode}")
        try:
            status, body = probe(url, 0.5)
            last_observation = f"HTTP {status}: {body[:1000]}"
            if status == 200:
                graph = json.loads(body)
                persistence = graph.get("desiredStatePersistence")
                if (isinstance(persistence, dict) and
                        persistence.get("integrityState") == integrity_state):
                    return graph, persistence
        except (OSError, ValueError):
            pass
        time.sleep(0.05)
    raise RuntimeError(
        "timed out waiting for desired-state integrity state " +
        integrity_state + "; last=" + last_observation
    )


def health_component(body: str, name: str) -> dict[str, object] | None:
    document = json.loads(body)
    components = document.get("components", [])
    if not isinstance(components, list):
        return None
    for component in components:
        if isinstance(component, dict) and component.get("name") == name:
            return component
    return None


def wait_for_node(
    process: subprocess.Popen[bytes], url: str, timeout: float, predicate
) -> tuple[dict[str, object], dict[str, object]]:
    deadline = time.monotonic() + timeout
    last_observation = "no HTTP response"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Runtime exited with code {process.returncode}")
        try:
            status, body = probe(url, 0.5)
            last_observation = f"HTTP {status}: {body[:1000]}"
            if status == 200:
                graph = json.loads(body)
                current = node(graph)
                if current is not None and predicate(current):
                    return graph, current
        except (OSError, ValueError):
            pass
        time.sleep(0.05)
    raise RuntimeError(
        "timed out waiting for managed-process desired state; last=" +
        last_observation
    )


def main() -> int:
    args = parse_args()
    runtime = args.runtime.resolve()
    base_config = args.config.resolve()
    fixture = args.fixture.resolve()
    bundle_repository = args.bundle_repository.resolve()
    report_path = args.report.resolve()
    log_path = args.log.resolve()
    for required in (runtime, base_config, fixture):
        if not required.is_file():
            raise SystemExit(f"required file not found: {required}")
    if not bundle_repository.is_dir():
        raise SystemExit(f"bundle repository not found: {bundle_repository}")

    runtime_root = runtime.parent
    processes_root = runtime_root / "processes"
    data_root = runtime_root / "data"
    processes_root.mkdir(parents=True, exist_ok=True)
    data_root.mkdir(parents=True, exist_ok=True)
    process_workspace = Path(tempfile.mkdtemp(
        prefix="pdr-desired-state-e2e-", dir=processes_root
    )).resolve()
    state_name = f"process-desired-state-e2e-{uuid.uuid4().hex}.json"
    state_path = (data_root / state_name).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_bytes(b"")
    work = Path(tempfile.mkdtemp(
        prefix="process-desired-state-e2e-", dir=report_path.parent
    )).resolve()
    result: dict[str, object] = {
        "schemaVersion": 1,
        "passed": False,
        "runtime": str(runtime),
        "statePath": str(state_path),
    }
    process: subprocess.Popen[bytes] | None = None
    log_stream = None
    try:
        shutil.copy2(fixture, process_workspace / "dependency-fixture.exe")
        minimal_repository = work / "bundles"
        copy_required_bundles(bundle_repository, minimal_repository)
        subprocess_config = work / "pdr-subprocesses.properties"
        event_path = work / "events.log"
        write_subprocess_configuration(
            subprocess_config, process_workspace.name, event_path, state_name
        )
        port = free_port("127.0.0.1")
        overlay = work / "pdr-runtime.properties"
        write_overlay(base_config, overlay, "127.0.0.1", port, {
            "logging.channels.file.path": (work / "runtime-file.log").as_posix(),
            "osp.bundleRepository": minimal_repository.as_posix() + "/",
            "osp.codeCache": (work / "codeCache").as_posix(),
            "osp.data": (work / "data").as_posix(),
            "pdr.subprocess.configuration": subprocess_config.as_posix(),
            "pdr.subprocess.shutdownTimeoutMilliseconds": "1500",
            "pdr.management.audit.enabled": "false",
            "pdr.management.idempotency.persistence.enabled": "false",
            "pdr.management.tasks.persistence.enabled": "false",
            "pdr.plugins.quarantine.enabled": "false",
        })
        environment = os.environ.copy()
        environment["PATH"] = str(runtime_root) + os.pathsep + environment.get("PATH", "")
        option = f"/config-file={overlay}" if os.name == "nt" else f"--config-file={overlay}"
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        url = f"http://127.0.0.1:{port}/api/v1/process-dependencies"
        lifecycle_url = f"http://127.0.0.1:{port}/api/v1/process-lifecycle"
        health_detail_url = f"http://127.0.0.1:{port}/health/detail"
        health_ready_url = f"http://127.0.0.1:{port}/health/ready"

        def launch() -> subprocess.Popen[bytes]:
            nonlocal log_stream
            log_stream = log_path.open("ab")
            return subprocess.Popen(
                [str(runtime), option], cwd=work, env=environment,
                stdout=log_stream, stderr=subprocess.STDOUT,
                creationflags=creationflags, start_new_session=os.name != "nt",
            )

        process = launch()
        result["firstRuntimePid"] = process.pid
        first_graph, first_node = wait_for_node(
            process, url, args.timeout,
            lambda value: value.get("state") == "running" and
                value.get("desiredState") == "running",
        )
        first_process_id = first_node.get("processId")
        first_persistence = require_persistence_status(first_graph, 1, False)
        status, body = post_json(
            lifecycle_url,
            {"id": "durable-e2e-worker", "action": "stop"},
            5.0,
        )
        if status != 200:
            raise RuntimeError(f"process stop API returned HTTP {status}: {body}")
        stopped_graph, stopped_node = wait_for_node(
            process, url, args.timeout,
            lambda value: value.get("state") == "stopped" and
                value.get("desiredState") == "stopped" and
                not value.get("processId"),
        )
        stopped_persistence = require_persistence_status(stopped_graph, 2, True)

        state_path.write_text("{online-primary-corruption", encoding="utf-8")
        degraded_graph, degraded_persistence = wait_for_persistence_state(
            process, url, args.timeout, "primary-invalid"
        )
        degraded_node = node(degraded_graph)
        if (degraded_persistence.get("healthy") is not False or
                degraded_persistence.get("primaryValid") is not False or
                degraded_persistence.get("previousAvailable") is not True or
                degraded_persistence.get("previousValid") is not True or
                degraded_node is None or degraded_node.get("state") != "stopped"):
            raise RuntimeError("online integrity scrub did not publish primary corruption")
        health_status, health_body = probe(health_detail_url, 0.5)
        persistence_health = health_component(
            health_body, "desired-state-persistence"
        ) if health_status == 200 else None
        ready_status, ready_body = probe(health_ready_url, 0.5)
        if (persistence_health is None or
                persistence_health.get("status") != "DEGRADED" or
                persistence_health.get("code") !=
                "PDR-HEALTH-PROCESS-DESIRED-STATE-INTEGRITY" or
                ready_status != 503 or
                json.loads(ready_body).get("ready") is not False):
            raise RuntimeError("online desired-state corruption did not degrade health readiness")

        status, body = post_json(
            lifecycle_url,
            {"id": "durable-e2e-worker", "action": "start"},
            5.0,
        )
        if status != 200:
            raise RuntimeError(f"process repair start API returned HTTP {status}: {body}")
        repaired_graph, repaired_node = wait_for_node(
            process, url, args.timeout,
            lambda value: value.get("state") == "running" and
                value.get("desiredState") == "running",
        )
        repaired_persistence = require_persistence_status(
            repaired_graph, 3, True
        )
        status, body = post_json(
            lifecycle_url,
            {"id": "durable-e2e-worker", "action": "stop"},
            5.0,
        )
        if status != 200:
            raise RuntimeError(f"process final stop API returned HTTP {status}: {body}")
        final_stopped_graph, final_stopped_node = wait_for_node(
            process, url, args.timeout,
            lambda value: value.get("state") == "stopped" and
                value.get("desiredState") == "stopped" and
                not value.get("processId"),
        )
        final_stopped_persistence = require_persistence_status(
            final_stopped_graph, 4, True
        )
        first_shutdown = stop_tree(process, 10.0)
        process = None
        log_stream.close()
        log_stream = None
        if not first_shutdown.get("clean", False):
            raise RuntimeError("first isolated Runtime did not stop cleanly")
        result["firstShutdown"] = first_shutdown

        process = launch()
        result["secondRuntimePid"] = process.pid
        restored_graph, restored_node = wait_for_node(
            process, url, args.timeout,
            lambda value: value.get("state") == "stopped" and
                value.get("desiredState") == "stopped" and
                not value.get("processId"),
        )
        restored_persistence = require_persistence_status(restored_graph, 4, True)
        events = event_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if events.count("start:durable-e2e-worker") != 2:
            raise RuntimeError("stopped child was relaunched after Runtime restart")
        if not state_path.is_file() or not Path(str(state_path) + ".previous").is_file():
            raise RuntimeError("desired-state primary or recovery snapshot is missing")
        result.update({
            "firstProcessId": first_process_id,
            "firstGeneration": first_graph.get("generation"),
            "stoppedGeneration": stopped_graph.get("generation"),
            "restoredGeneration": restored_graph.get("generation"),
            "restoredState": restored_node.get("state"),
            "restoredDesiredState": restored_node.get("desiredState"),
            "launchCount": events.count("start:durable-e2e-worker"),
            "primarySnapshot": True,
            "previousSnapshot": True,
            "firstPersistence": first_persistence,
            "stoppedPersistence": stopped_persistence,
            "degradedPersistence": degraded_persistence,
            "persistenceHealth": persistence_health,
            "repairedProcessId": repaired_node.get("processId"),
            "repairedPersistence": repaired_persistence,
            "finalStoppedPersistence": final_stopped_persistence,
            "restoredPersistence": restored_persistence,
            "passed": True,
        })
        if args.hold_after_validation_seconds > 0:
            print(
                f"PROCESS_DESIRED_STATE_RUNTIME_READY port={port} "
                f"seconds={args.hold_after_validation_seconds:g}",
                flush=True,
            )
            try:
                time.sleep(args.hold_after_validation_seconds)
            except KeyboardInterrupt:
                print("PROCESS_DESIRED_STATE_RUNTIME_HOLD_INTERRUPTED", flush=True)
    except Exception as error:
        result["error"] = str(error)
    finally:
        if process is not None:
            result["finalShutdown"] = stop_tree(process, 10.0)
            if not result["finalShutdown"].get("clean", False):
                result["passed"] = False
                result["shutdownError"] = "final isolated Runtime did not stop cleanly"
        if log_stream is not None:
            log_stream.close()
        for candidate in (state_path, Path(str(state_path) + ".previous"),
                          Path(str(state_path) + ".new"),
                          Path(str(state_path) + ".lock")):
            if candidate.exists():
                if not candidate.is_file() or candidate.parent != data_root.resolve():
                    raise RuntimeError("refusing to remove unexpected desired-state path")
                candidate.unlink()
        if process_workspace.parent != processes_root.resolve():
            raise RuntimeError("refusing to remove unexpected process fixture path")
        if work.parent != report_path.parent.resolve():
            raise RuntimeError("refusing to remove unexpected integration work path")
        shutil.rmtree(process_workspace, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)
        report_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8", newline="\n",
        )

    if result["passed"]:
        print("PROCESS_DESIRED_STATE_RUNTIME_PASS stopApi=1 restart=1 stopped=1 relaunch=0 snapshots=2 onlineScrub=1 healthDegraded=1 scrubRepair=1")
        return 0
    print(
        "PROCESS_DESIRED_STATE_RUNTIME_FAIL " +
        str(result.get("error", result.get("shutdownError", "validation failed"))),
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
