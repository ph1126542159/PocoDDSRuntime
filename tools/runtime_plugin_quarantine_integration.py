#!/usr/bin/env python3
"""Verify plugin failure budgets, persistent quarantine, and recovery with a real Runtime."""

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


def args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--working-directory", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--plugin-id", required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args()


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def request(base: str, path: str, body: dict[str, object] | None = None) -> tuple[int, dict[str, object]]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Accept": "application/json", "X-PDR-Request-Id": f"quarantine-{time.time_ns()}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, headers=headers,
                                 method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=2) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        payload = error.read().decode()
        return error.code, json.loads(payload) if payload else {}


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
    raise TimeoutError("Runtime did not become live")


def stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
        process.wait(timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        process.kill()
        process.wait(timeout=5)


def find_plugin(payload: object, plugin_id: str) -> dict[str, object]:
    if isinstance(payload, dict):
        if payload.get("id") == plugin_id:
            return payload
        for value in payload.values():
            found = find_plugin(value, plugin_id)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = find_plugin(value, plugin_id)
            if found:
                return found
    return {}


def main() -> int:
    options = args()
    workspace = options.workspace.resolve()
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    persistence = workspace / "plugin-quarantine.json"
    overlay = workspace / "runtime.properties"
    port = free_port()
    overlay.write_text(options.config.read_text(encoding="utf-8") + "\n" + "\n".join([
        "osp.web.server.host = 127.0.0.1", f"osp.web.server.port = {port}",
        "osp.web.server.securePort = 0", "pdr.management.authentication.required = false",
        "pdr.plugins.quarantine.enabled = true", "pdr.plugins.quarantine.failureThreshold = 2",
        f"pdr.plugins.quarantine.path = {persistence.as_posix()}",
        "pdr.mqtt.count = 0", "pdr.ros.count = 0", "pdr.udp.count = 0",
    ]) + "\n", encoding="utf-8", newline="\n")
    environment = os.environ.copy()
    environment["PATH"] = os.pathsep.join([str(Path(item).resolve()) for item in options.path] +
                                           [environment.get("PATH", "")])
    base = f"http://127.0.0.1:{port}"
    log_path = workspace / "runtime.log"
    report: dict[str, object] = {"schemaVersion": 1, "passed": False}
    process: subprocess.Popen[bytes] | None = None
    log = None

    def launch(clear_cache: bool = False) -> subprocess.Popen[bytes]:
        if clear_cache:
            cache = options.working_directory.resolve() / "codeCache"
            if cache.exists():
                shutil.rmtree(cache)
        nonlocal log
        log = log_path.open("ab")
        option = f"/config-file={overlay}" if os.name == "nt" else f"--config-file={overlay}"
        child = subprocess.Popen([str(options.executable.resolve()), option],
            cwd=options.working_directory.resolve(), env=environment, stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            start_new_session=os.name != "nt")
        wait_live(base, child)
        return child

    try:
        process = launch(clear_cache=True)
        _, detail = request(base, "/api/v1/process-detail")
        first = find_plugin(detail, options.plugin_id)
        if first.get("quarantineConsecutiveFailures") != 1 or first.get("quarantined") is True:
            raise AssertionError(f"automatic failure was not recorded: {first}")
        failure_status, _ = request(base, "/api/v1/bundle-lifecycle",
                                    {"id": options.plugin_id, "action": "start"})
        _, detail = request(base, "/api/v1/process-detail")
        quarantined = find_plugin(detail, options.plugin_id)
        if failure_status >= 500 or quarantined.get("quarantined") is not True:
            raise AssertionError(f"second failure did not quarantine plugin: {failure_status}, {quarantined}")
        blocked_status, _ = request(base, "/api/v1/bundle-lifecycle",
                                    {"id": options.plugin_id, "action": "start"})
        if blocked_status != 409:
            raise AssertionError(f"quarantined start returned {blocked_status}, expected 409")
        stop(process); process = None
        if log: log.close(); log = None

        process = launch()
        _, detail = request(base, "/api/v1/process-detail")
        restored = find_plugin(detail, options.plugin_id)
        if restored.get("quarantined") is not True or restored.get("quarantineConsecutiveFailures") != 2:
            raise AssertionError(f"quarantine did not survive restart: {restored}")
        reset_status, _ = request(base, "/api/v1/bundle-lifecycle",
                                  {"id": options.plugin_id, "action": "reset-quarantine"})
        if reset_status != 200:
            raise AssertionError(f"quarantine reset returned {reset_status}")
        stop(process); process = None
        if log: log.close(); log = None

        persistence.write_text("{corrupt", encoding="utf-8")
        process = launch()
        _, detail = request(base, "/api/v1/process-detail")
        corrupt = find_plugin(detail, options.plugin_id)
        if corrupt.get("quarantineRecoveryRequired") is not True:
            raise AssertionError(f"corrupt persistence did not fail closed: {corrupt}")
        denied_status, _ = request(base, "/api/v1/bundle-lifecycle",
            {"id": options.plugin_id, "action": "reset-quarantine"})
        recovered_status, _ = request(base, "/api/v1/bundle-lifecycle",
            {"id": options.plugin_id, "action": "reset-quarantine", "confirmPersistenceRecovery": True})
        if denied_status < 400 or recovered_status != 200:
            raise AssertionError(f"recovery confirmation contract failed: {denied_status}, {recovered_status}")
        report.update({"passed": True, "failureStatus": failure_status,
                       "blockedStatus": blocked_status, "resetStatus": reset_status,
                       "recoveryDeniedStatus": denied_status,
                       "recoveryConfirmedStatus": recovered_status})
    except Exception as error:
        report["error"] = str(error)
    finally:
        if process is not None:
            stop(process)
        if log:
            log.close()
        options.report.parent.mkdir(parents=True, exist_ok=True)
        options.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
