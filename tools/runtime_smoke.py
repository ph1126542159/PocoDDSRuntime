#!/usr/bin/env python3
"""Start a packaged runtime, probe HTTP endpoints, and always stop its process tree."""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def free_port(host: str) -> int:
    with socket.socket() as listener:
        listener.bind((host, 0))
        return int(listener.getsockname()[1])


def parse_overrides(items: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for item in items:
        key, separator, value = item.partition("=")
        key = key.strip()
        if not separator or not key:
            raise ValueError(f"invalid --set value (expected KEY=VALUE): {item}")
        overrides[key] = value.strip()
    return overrides


def write_overlay(
    source: Path, destination: Path, host: str, port: int, overrides: dict[str, str]
) -> None:
    values = source.read_text(encoding="utf-8").splitlines()
    replacements = {
        "osp.web.server.host": host,
        "osp.web.server.port": str(port),
        "osp.web.server.securePort": "0",
        "logging.channels.file.path":
            (destination.parent / f"runtime-smoke-{port}-runtime.log").as_posix(),
    }
    replacements.update(overrides)
    seen: set[str] = set()
    output: list[str] = []
    for line in values:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in replacements:
            output.append(f"{key} = {replacements[key]}")
            seen.add(key)
        else:
            output.append(line)
    for key, value in replacements.items():
        if key not in seen:
            output.append(f"{key} = {value}")
    destination.write_text("\n".join(output) + "\n", encoding="utf-8", newline="\n")


def stop_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)


def probe(url: str, timeout: float) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--working-directory", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="0 selects an unused local port")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--stability-window", type=float, default=1.0,
                        help="seconds endpoints must remain healthy after startup")
    parser.add_argument("--endpoint", action="append", default=["/health/live", "/health/ready"])
    parser.add_argument("--expect-status", action="append", default=[], metavar="ENDPOINT=STATUS",
                        help="override the expected HTTP status for an endpoint")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--log", type=Path, help="combined child stdout/stderr log")
    parser.add_argument("--path", action="append", default=[], help="directory prepended to PATH")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                        help="configuration property override; may be repeated")
    parser.add_argument("--require-log", action="append", default=[], metavar="REGEX",
                        help="regular expression that must appear in the runtime log")
    parser.add_argument("--require-body", action="append", default=[], metavar="REGEX",
                        help="regular expression that must appear in an endpoint response")
    parser.add_argument("--clear-code-cache", action="store_true",
                        help="remove WORKING_DIRECTORY/codeCache before launch")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.timeout <= 0 or args.stability_window < 0:
        raise SystemExit("--timeout must be positive and --stability-window non-negative")
    executable = args.executable.resolve()
    work = (args.working_directory or executable.parent).resolve()
    config = (args.config or work / "pdr-runtime.properties").resolve()
    port = args.port or free_port(args.host)
    expected_statuses: dict[str, int] = {}
    for item in args.expect_status:
        endpoint, separator, status_text = item.partition("=")
        if not separator or not endpoint.startswith("/") or not status_text.isdigit():
            raise SystemExit(f"invalid --expect-status value: {item}")
        expected_statuses[endpoint] = int(status_text)
    report_path = args.report.resolve() if args.report else None
    log_path = args.log.resolve() if args.log else (report_path.with_suffix(".log") if report_path else None)
    overlay = (report_path.parent if report_path else work) / f"runtime-smoke-{port}.properties"
    result: dict[str, object] = {
        "schemaVersion": 1,
        "executable": str(executable),
        "workingDirectory": str(work),
        "host": args.host,
        "port": port,
        "passed": False,
        "probes": [],
    }
    if expected_statuses:
        result["expectedStatuses"] = expected_statuses
    process: subprocess.Popen[bytes] | None = None
    log_stream = None
    try:
        if not executable.is_file():
            raise FileNotFoundError(f"runtime executable not found: {executable}")
        if not config.is_file():
            raise FileNotFoundError(f"runtime configuration not found: {config}")
        if args.clear_code_cache:
            code_cache = (work / "codeCache").resolve()
            if code_cache.parent != work or code_cache.name != "codeCache":
                raise RuntimeError(f"refusing to clear unexpected code cache path: {code_cache}")
            shutil.rmtree(code_cache, ignore_errors=True)
            result["codeCacheCleared"] = True
        overlay.parent.mkdir(parents=True, exist_ok=True)
        write_overlay(config, overlay, args.host, port, parse_overrides(args.set))
        option = f"/config-file={overlay}" if os.name == "nt" else f"--config-file={overlay}"
        environment = os.environ.copy()
        if args.path:
            search_path = os.pathsep.join(str(Path(item).resolve()) for item in args.path)
            environment["PATH"] = search_path + os.pathsep + environment.get("PATH", "")
            if os.name != "nt":
                loader_variable = "DYLD_LIBRARY_PATH" if sys.platform == "darwin" else "LD_LIBRARY_PATH"
                environment[loader_variable] = (
                    search_path + os.pathsep + environment.get(loader_variable, "")
                )
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        if log_path:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_stream = log_path.open("wb")
        process = subprocess.Popen(
            [str(executable), option],
            cwd=work,
            env=environment,
            stdout=log_stream or subprocess.DEVNULL,
            stderr=subprocess.STDOUT if log_stream else subprocess.DEVNULL,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
        result["pid"] = process.pid
        deadline = time.monotonic() + args.timeout
        pending = list(dict.fromkeys(args.endpoint))
        last_error = "runtime did not answer"
        while pending and time.monotonic() < deadline:
            if process.poll() is not None:
                last_error = f"runtime exited with code {process.returncode}"
                break
            endpoint = pending[0]
            try:
                status, body = probe(f"http://{args.host}:{port}{endpoint}", min(1.0, args.timeout))
                expected = expected_statuses.get(endpoint, 200)
                if status != expected:
                    last_error = f"{endpoint} returned HTTP {status}, expected {expected}"
                else:
                    result["probes"].append({"endpoint": endpoint, "status": status, "body": body[:2048]})
                    pending.pop(0)
                    continue
            except (OSError, urllib.error.URLError) as error:
                last_error = f"{endpoint}: {error}"
            time.sleep(0.2)
        if pending:
            raise RuntimeError(last_error)
        response_content = "\n".join(str(item["body"]) for item in result["probes"])
        missing_bodies = [
            pattern for pattern in args.require_body
            if re.search(pattern, response_content) is None
        ]
        if missing_bodies:
            raise RuntimeError(
                f"endpoint responses did not match required pattern(s): {missing_bodies}"
            )
        if args.require_body:
            result["requiredBodyPatterns"] = args.require_body
        stability_deadline = time.monotonic() + args.stability_window
        while time.monotonic() < stability_deadline:
            if process.poll() is not None:
                raise RuntimeError(f"runtime exited with code {process.returncode}")
            for endpoint in dict.fromkeys(args.endpoint):
                status, _ = probe(
                    f"http://{args.host}:{port}{endpoint}", min(1.0, args.timeout)
                )
                expected = expected_statuses.get(endpoint, 200)
                if status != expected:
                    raise RuntimeError(
                        f"{endpoint} returned HTTP {status}, expected {expected} "
                        "during stability window"
                    )
            time.sleep(min(0.25, max(0.0, stability_deadline - time.monotonic())))
        if args.require_log:
            if log_path is None:
                raise ValueError("--require-log requires --log or --report")
            if log_stream is not None:
                log_stream.flush()
            log_content = log_path.read_text(encoding="utf-8", errors="replace")
            missing = [pattern for pattern in args.require_log if re.search(pattern, log_content) is None]
            if missing:
                raise RuntimeError(f"runtime log did not match required pattern(s): {missing}")
            result["requiredLogPatterns"] = args.require_log
        result["passed"] = True
        result["stabilityWindowSeconds"] = args.stability_window
        result["durationSeconds"] = round(args.timeout - max(0.0, deadline - time.monotonic()), 3)
        print(f"RUNTIME_SMOKE_PASS pid={process.pid} port={port} endpoints={len(result['probes'])}")
        return 0
    except Exception as error:  # concise CLI boundary
        result["error"] = str(error)
        print(f"RUNTIME_SMOKE_FAIL {error}", file=sys.stderr)
        return 1
    finally:
        if process is not None:
            stop_tree(process)
        if log_stream is not None:
            log_stream.close()
        try:
            overlay.unlink(missing_ok=True)
        except OSError:
            pass
        if report_path:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    raise SystemExit(main())
