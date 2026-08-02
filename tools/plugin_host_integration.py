#!/usr/bin/env python3
"""Exercise an isolated plugin host under the production launcher supervision chain."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", type=Path, required=True)
    parser.add_argument("--launcher", type=Path, required=True)
    parser.add_argument("--plugin-id", required=True)
    parser.add_argument("--bundle", type=Path, action="append", required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args()


def option(path: Path) -> str:
    return ("/config-file=" if os.name == "nt" else "--config-file=") + path.resolve().as_posix()


def read_state(path: Path) -> dict[str, object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def wait_running(state_file: Path, previous_pid: int = 0) -> dict[str, object]:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        state = read_state(state_file)
        pid = int(state.get("hostPid", 0))
        if state.get("state") == "running" and pid and pid != previous_pid:
            return state
        time.sleep(0.05)
    raise TimeoutError("isolated plugin host did not report a new running PID")


def kill_pid(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        os.kill(pid, signal.SIGKILL)


def stop_launcher(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
        process.wait(timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        kill_pid(process.pid)
        process.wait(timeout=5)


def main() -> int:
    args = parse_args()
    workspace = args.workspace.resolve()
    if workspace.exists():
        shutil.rmtree(workspace)
    bundles = workspace / "bundles"
    data = workspace / "data"
    launcher_bundles = workspace / "launcher-bundles"
    bundles.mkdir(parents=True)
    data.mkdir()
    launcher_bundles.mkdir()
    for source in args.bundle:
        shutil.copy2(source.resolve(), bundles / source.name)
    heartbeat = data / "plugin-host.heartbeat"
    state_file = data / "plugin-host-state.json"
    host_config = workspace / "plugin-host.properties"
    launcher_config = workspace / "launcher.properties"
    host_config.write_text("\n".join([
        f"pluginHost.pluginId = {args.plugin_id}", "pluginHost.allowedBundles =",
        f"pluginHost.heartbeatFile = {heartbeat.as_posix()}",
        f"pluginHost.stateFile = {state_file.as_posix()}",
        "pluginHost.heartbeatIntervalMilliseconds = 50",
        f"osp.bundleRepository = {bundles.as_posix()}",
        f"osp.codeCache = {(workspace / 'codeCache').as_posix()}",
        f"osp.data = {data.as_posix()}",
        "logging.loggers.root.channel = console", "logging.loggers.root.level = information",
        "logging.channels.console.class = ConsoleChannel",
    ]) + "\n", encoding="utf-8", newline="\n")
    launcher_config.write_text("\n".join([
        "relaunchDelay = 50", "restartBudget.maxRestarts = 3",
        "restartBudget.windowMilliseconds = 10000", f"watchdog.file = {heartbeat.as_posix()}",
        "watchdog.timeout = 1000", "watchdog.interval = 50",
        "watchdog.startupGraceMilliseconds = 3000", "watchdog.requireFile = true",
        "childArgument.count = 1", f"childArgument.0 = {option(host_config)}",
        "osp.bundleMonitor.enabled = false",
        f"osp.bundleRepository = {launcher_bundles.as_posix()}",
        "logging.loggers.root.channel = console",
        "logging.loggers.root.level = information", "logging.channels.console.class = ConsoleChannel",
    ] + (["resourceLimits.killProcessTreeOnExit = true",
          "resourceLimits.memoryBytes = 268435456", "resourceLimits.activeProcessLimit = 1",
          "resourceLimits.cpuRatePercent = 25"] if os.name == "nt" else [])) + "\n",
        encoding="utf-8", newline="\n")
    environment = os.environ.copy()
    environment["PATH"] = os.pathsep.join(
        [str(Path(item).resolve()) for item in args.path] + [environment.get("PATH", "")])
    log_path = workspace / "supervision.log"
    report: dict[str, object] = {"schemaVersion": 1, "passed": False}
    launcher: subprocess.Popen[bytes] | None = None
    log = None
    try:
        log = log_path.open("wb")
        launcher = subprocess.Popen([
            str(args.launcher.resolve()), option(launcher_config), str(args.host.resolve())],
            cwd=workspace, env=environment, stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            start_new_session=os.name != "nt")
        first = wait_running(state_file)
        first_pid = int(first["hostPid"])
        first_heartbeat = int(heartbeat.read_text(encoding="utf-8").strip())
        kill_pid(first_pid)
        second = wait_running(state_file, first_pid)
        second_pid = int(second["hostPid"])
        time.sleep(0.15)
        second_heartbeat = int(heartbeat.read_text(encoding="utf-8").strip())
        if first.get("pluginId") != args.plugin_id or second.get("pluginId") != args.plugin_id:
            raise AssertionError("plugin host state reported the wrong plugin")
        if second_heartbeat <= first_heartbeat:
            raise AssertionError("heartbeat did not advance after supervised restart")
        if os.name == "nt":
            log.flush()
            evidence = log_path.read_text(encoding="utf-8", errors="replace")
            if "Windows Job Object resource boundary configured." not in evidence:
                raise AssertionError("launcher did not confirm the Windows Job Object boundary")
        report.update({"passed": True, "firstHostPid": first_pid,
                       "secondHostPid": second_pid, "heartbeatAdvanced": True,
                       "resourceBoundary": "windows-job-object" if os.name == "nt" else "external"})
    except Exception as error:
        report["error"] = str(error)
    finally:
        if launcher is not None:
            stop_launcher(launcher)
            report["launcherExitCode"] = launcher.returncode
        if log: log.close()
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
