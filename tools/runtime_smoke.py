#!/usr/bin/env python3
"""Start a packaged runtime, probe HTTP endpoints, and always stop its process tree."""

from __future__ import annotations

import argparse
import base64
import ctypes
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
import urllib.parse
import urllib.request
from ctypes import wintypes
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


def stop_tree(process: subprocess.Popen[bytes], timeout: float,
              force_requested: bool = False) -> dict[str, object]:
    started = time.monotonic()
    if process.poll() is not None:
        return {"mode": "already-exited", "exitCode": process.returncode,
                "clean": process.returncode == 0, "durationSeconds": 0.0}
    if force_requested:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)
        try:
            exit_code = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            exit_code = process.poll()
        return {"mode": "forced-requested", "exitCode": exit_code, "clean": False,
                "expected": True, "durationSeconds": round(time.monotonic() - started, 3)}
    if os.name == "nt":
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT)
            exit_code = process.wait(timeout=timeout)
            return {"mode": "graceful", "exitCode": exit_code, "clean": exit_code == 0,
                    "durationSeconds": round(time.monotonic() - started, 3)}
        except (OSError, subprocess.TimeoutExpired):
            pass
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        try:
            exit_code = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            exit_code = process.poll()
        return {"mode": "forced-timeout", "exitCode": exit_code, "clean": False,
                "durationSeconds": round(time.monotonic() - started, 3)}
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            exit_code = process.poll()
            return {"mode": "already-exited", "exitCode": exit_code,
                    "clean": exit_code == 0,
                    "durationSeconds": round(time.monotonic() - started, 3)}
        try:
            exit_code = process.wait(timeout=timeout)
            return {"mode": "graceful", "exitCode": exit_code, "clean": exit_code == 0,
                    "durationSeconds": round(time.monotonic() - started, 3)}
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            exit_code = process.wait(timeout=5)
            return {"mode": "forced-timeout", "exitCode": exit_code, "clean": False,
                    "durationSeconds": round(time.monotonic() - started, 3)}


def process_resources(process: subprocess.Popen[bytes]) -> tuple[int, int]:
    if os.name != "nt":
        status = Path(f"/proc/{process.pid}/status").read_text(encoding="utf-8")
        rss_line = next(line for line in status.splitlines() if line.startswith("VmRSS:"))
        return int(rss_line.split()[1]) * 1024, len(list(Path(f"/proc/{process.pid}/fd").iterdir()))

    class Counters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    handle = wintypes.HANDLE(process._handle)  # type: ignore[attr-defined]
    if not ctypes.windll.psapi.GetProcessMemoryInfo(  # type: ignore[attr-defined]
        handle, ctypes.byref(counters), counters.cb
    ):
        raise OSError("GetProcessMemoryInfo failed")
    count = wintypes.DWORD()
    if not ctypes.windll.kernel32.GetProcessHandleCount(  # type: ignore[attr-defined]
        handle, ctypes.byref(count)
    ):
        raise OSError("GetProcessHandleCount failed")
    return int(counters.WorkingSetSize), int(count.value)


def probe(url: str, timeout: float, method: str = "GET", body: str | None = None,
          extra_headers: dict[str, str] | None = None) -> tuple[int, str]:
    data = body.encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json"}
    headers.update(extra_headers or {})
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
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
    parser.add_argument("--probe-delay", type=float, default=0.0,
                        help="seconds to wait after health readiness before other endpoints")
    parser.add_argument("--endpoint", action="append", default=["/health/live", "/health/ready"])
    parser.add_argument("--expect-status", action="append", default=[], metavar="ENDPOINT=STATUS",
                        help="override the expected HTTP status for an endpoint")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--log", type=Path, help="combined child stdout/stderr log")
    parser.add_argument("--path", action="append", default=[], help="directory prepended to PATH")
    parser.add_argument("--bearer-token-environment",
                        help="environment variable containing a Bearer token; never written to reports")
    parser.add_argument("--endpoint-bearer-token-environment", action="append", default=[],
                        metavar="ENDPOINT=ENV",
                        help="override the Bearer token for one GET endpoint")
    parser.add_argument("--endpoint-basic-credentials-environment", action="append", default=[],
                        metavar="ENDPOINT=ENV",
                        help="use username:password from an environment variable for one GET endpoint")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                        help="configuration property override; may be repeated")
    parser.add_argument("--require-log", action="append", default=[], metavar="REGEX",
                        help="regular expression that must appear in the runtime log")
    parser.add_argument("--forbid-log", action="append", default=[], metavar="REGEX",
                        help="regular expression that must not appear in the runtime log")
    parser.add_argument("--require-body", action="append", default=[], metavar="REGEX",
                        help="regular expression that must appear in an endpoint response")
    parser.add_argument("--forbid-body", action="append", default=[], metavar="REGEX",
                        help="regular expression that must not appear in endpoint responses")
    parser.add_argument("--clear-code-cache", action="store_true",
                        help="remove WORKING_DIRECTORY/codeCache before launch")
    parser.add_argument("--follow-html-assets", action="store_true",
                        help="fetch same-origin script and stylesheet assets referenced by HTML")
    parser.add_argument("--post", action="append", default=[], metavar="ENDPOINT=JSON",
                        help="POST JSON after startup probes; may be repeated in sequence")
    parser.add_argument("--post-delay", type=float, default=0.0,
                        help="seconds to wait after startup probes before POST actions")
    parser.add_argument("--post-interval", type=float, default=0.0,
                        help="seconds to monitor endpoints after each POST action")
    parser.add_argument("--post-interval-override", action="append", default=[],
                        metavar="INDEX=SECONDS",
                        help="override monitoring delay after one POST action")
    parser.add_argument("--post-health-interval", type=float, default=5.0,
                        help="endpoint/resource sampling interval during --post-interval")
    parser.add_argument("--post-expect-status", action="append", default=[],
                        metavar="INDEX:ENDPOINT=STATUS",
                        help="override an endpoint status while observing one POST action")
    parser.add_argument("--post-response-status", action="append", default=[],
                        metavar="INDEX=STATUS",
                        help="expected HTTP response status for one POST action")
    parser.add_argument("--post-omit-bearer", action="append", default=[], type=int,
                        metavar="INDEX", help="omit the configured Bearer token for one POST")
    parser.add_argument("--post-bearer-token-environment", action="append", default=[],
                        metavar="INDEX=ENV",
                        help="override one POST Bearer token from an environment variable")
    parser.add_argument("--post-request-id", action="append", default=[], metavar="INDEX=ID",
                        help="override the automatically generated management request ID")
    parser.add_argument("--post-omit-request-id", action="append", default=[], type=int,
                        metavar="INDEX", help="omit the management request ID for one POST")
    parser.add_argument("--sample-resources", action="store_true",
                        help="sample Runtime RSS and handles before, during and after POST actions")
    parser.add_argument("--resource-baseline-after-post", type=int, default=0, metavar="N",
                        help="evaluate growth after the Nth POST, excluding one-time lazy startup")
    parser.add_argument("--max-rss-growth-mib", type=float, default=64.0)
    parser.add_argument("--max-handle-growth", type=int, default=32)
    parser.add_argument("--shutdown-timeout", type=float, default=10.0,
                        help="seconds allowed for graceful Runtime shutdown")
    parser.add_argument("--allow-forced-shutdown", action="store_true",
                        help="do not fail when graceful shutdown times out or exits nonzero")
    parser.add_argument("--force-shutdown", action="store_true",
                        help="intentionally force process-tree termination for crash injection")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if (args.timeout <= 0 or args.stability_window < 0 or args.probe_delay < 0 or
            args.post_delay < 0 or
            args.post_interval < 0 or args.post_health_interval <= 0 or
            args.resource_baseline_after_post < 0 or args.shutdown_timeout <= 0):
        raise SystemExit(
            "--timeout, --post-health-interval and --shutdown-timeout must be positive; delays and "
            "--stability-window must be non-negative"
        )
    if args.resource_baseline_after_post > len(args.post):
        raise SystemExit("--resource-baseline-after-post cannot exceed the number of POST actions")
    post_interval_overrides: dict[int, float] = {}
    for item in args.post_interval_override:
        index_text, separator, seconds_text = item.partition("=")
        try:
            seconds = float(seconds_text)
        except ValueError:
            seconds = -1
        if (not separator or not index_text.isdigit() or int(index_text) < 1 or
                int(index_text) > len(args.post) or seconds < 0):
            raise SystemExit(f"invalid --post-interval-override value: {item}")
        post_interval_overrides[int(index_text)] = seconds
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
    endpoint_bearer_environments: dict[str, str] = {}
    for item in args.endpoint_bearer_token_environment:
        endpoint, separator, environment_name = item.partition("=")
        if not separator or not endpoint.startswith("/") or not environment_name:
            raise SystemExit(f"invalid --endpoint-bearer-token-environment value: {item}")
        endpoint_bearer_environments[endpoint] = environment_name
    endpoint_basic_environments: dict[str, str] = {}
    for item in args.endpoint_basic_credentials_environment:
        endpoint, separator, environment_name = item.partition("=")
        if not separator or not endpoint.startswith("/") or not environment_name:
            raise SystemExit(f"invalid --endpoint-basic-credentials-environment value: {item}")
        endpoint_basic_environments[endpoint] = environment_name
    conflicting_auth_endpoints = (
        endpoint_bearer_environments.keys() & endpoint_basic_environments.keys()
    )
    if conflicting_auth_endpoints:
        raise SystemExit(
            "one GET endpoint cannot use both Bearer and Basic credentials: " +
            ", ".join(sorted(conflicting_auth_endpoints))
        )
    post_expected_statuses: dict[tuple[int, str], int] = {}
    for item in args.post_expect_status:
        selector, separator, status_text = item.partition("=")
        index_text, colon, endpoint = selector.partition(":")
        if (not separator or not colon or not index_text.isdigit() or
                int(index_text) < 1 or not endpoint.startswith("/") or
                not status_text.isdigit()):
            raise SystemExit(f"invalid --post-expect-status value: {item}")
        post_expected_statuses[(int(index_text), endpoint)] = int(status_text)
    post_response_statuses: dict[int, int] = {}
    for item in args.post_response_status:
        index_text, separator, status_text = item.partition("=")
        if (not separator or not index_text.isdigit() or int(index_text) < 1 or
                not status_text.isdigit()):
            raise SystemExit(f"invalid --post-response-status value: {item}")
        post_response_statuses[int(index_text)] = int(status_text)
    if any(index > len(args.post) for index in post_response_statuses):
        raise SystemExit("--post-response-status index exceeds the number of POST actions")
    omitted_bearer_posts = set(args.post_omit_bearer)
    if any(index < 1 or index > len(args.post) for index in omitted_bearer_posts):
        raise SystemExit("--post-omit-bearer index is outside the POST action range")
    post_bearer_environments: dict[int, str] = {}
    for item in args.post_bearer_token_environment:
        index_text, separator, environment_name = item.partition("=")
        if (not separator or not index_text.isdigit() or int(index_text) < 1 or
                int(index_text) > len(args.post) or not environment_name):
            raise SystemExit(f"invalid --post-bearer-token-environment value: {item}")
        post_bearer_environments[int(index_text)] = environment_name
    if omitted_bearer_posts.intersection(post_bearer_environments):
        raise SystemExit("one POST cannot both omit and override its Bearer token")
    post_request_ids: dict[int, str] = {}
    for item in args.post_request_id:
        index_text, separator, request_id = item.partition("=")
        if (not separator or not index_text.isdigit() or int(index_text) < 1 or
                int(index_text) > len(args.post) or not request_id):
            raise SystemExit(f"invalid --post-request-id value: {item}")
        post_request_ids[int(index_text)] = request_id
    omitted_request_id_posts = set(args.post_omit_request_id)
    if any(index < 1 or index > len(args.post) for index in omitted_request_id_posts):
        raise SystemExit("--post-omit-request-id index is outside the POST action range")
    if omitted_request_id_posts.intersection(post_request_ids):
        raise SystemExit("one POST cannot both omit and override its request ID")
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
    request_headers: dict[str, str] = {}
    if args.bearer_token_environment:
        bearer_token = os.environ.get(args.bearer_token_environment, "")
        if not bearer_token:
            raise SystemExit(
                f"Bearer token environment is not set or empty: {args.bearer_token_environment}"
            )
        request_headers["Authorization"] = f"Bearer {bearer_token}"
        result["bearerAuthentication"] = True
    def headers_for_endpoint(endpoint: str) -> dict[str, str]:
        headers = dict(request_headers)
        environment_name = endpoint_bearer_environments.get(endpoint)
        if environment_name:
            token = os.environ.get(environment_name, "")
            if not token:
                raise RuntimeError(
                    f"Bearer token environment variable is missing or empty: {environment_name}"
                )
            headers["Authorization"] = f"Bearer {token}"
        basic_environment_name = endpoint_basic_environments.get(endpoint)
        if basic_environment_name:
            credentials = os.environ.get(basic_environment_name, "")
            if not credentials or ":" not in credentials:
                raise RuntimeError(
                    "Basic credentials environment variable must contain username:password: " +
                    basic_environment_name
                )
            encoded = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {encoded}"
        return headers
    if endpoint_bearer_environments:
        result["endpointBearerAuthentication"] = endpoint_bearer_environments
    if endpoint_basic_environments:
        result["endpointBasicAuthentication"] = endpoint_basic_environments
    if expected_statuses:
        result["expectedStatuses"] = expected_statuses
    process: subprocess.Popen[bytes] | None = None
    log_stream = None
    response_bodies: list[tuple[str, str]] = []
    resource_samples: list[dict[str, object]] = []
    last_committed_transaction_id = ""
    last_management_task_id = ""

    def sample_resources(stage: str) -> None:
        if not args.sample_resources or process is None:
            return
        rss, handles = process_resources(process)
        resource_samples.append({"stage": stage, "rssBytes": rss, "handles": handles})
    shutdown_failed = False
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
        business_probe_delay_applied = False
        last_error = "runtime did not answer"
        while pending and time.monotonic() < deadline:
            if process.poll() is not None:
                last_error = f"runtime exited with code {process.returncode}"
                break
            endpoint = pending[0]
            if (endpoint not in {"/health/live", "/health/ready"} and
                    not business_probe_delay_applied and args.probe_delay):
                settle_deadline = time.monotonic() + args.probe_delay
                while time.monotonic() < settle_deadline:
                    if process.poll() is not None:
                        raise RuntimeError(f"runtime exited with code {process.returncode}")
                    time.sleep(min(0.1, settle_deadline - time.monotonic()))
                business_probe_delay_applied = True
                result["probeDelaySeconds"] = args.probe_delay
            try:
                status, body = probe(f"http://{args.host}:{port}{endpoint}", min(1.0, args.timeout),
                                     extra_headers=headers_for_endpoint(endpoint))
                expected = expected_statuses.get(endpoint, 200)
                if status != expected:
                    last_error = f"{endpoint} returned HTTP {status}, expected {expected}"
                else:
                    result["probes"].append({"endpoint": endpoint, "status": status, "body": body[:2048]})
                    response_bodies.append((endpoint, body))
                    pending.pop(0)
                    continue
            except (OSError, urllib.error.URLError) as error:
                last_error = f"{endpoint}: {error}"
            time.sleep(0.2)
        if pending:
            raise RuntimeError(last_error)
        sample_resources("startup")
        if args.post_delay:
            post_deadline = time.monotonic() + args.post_delay
            while time.monotonic() < post_deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"runtime exited with code {process.returncode}")
                time.sleep(min(0.1, post_deadline - time.monotonic()))
        for post_index, item in enumerate(args.post, start=1):
            endpoint, separator, body = item.partition("=")
            if not separator or not endpoint.startswith("/"):
                raise ValueError(f"invalid --post value (expected /ENDPOINT=JSON): {item}")
            body = body.replace("${lastCommittedTransactionId}",
                                last_committed_transaction_id)
            body = body.replace("${lastManagementTaskId}", last_management_task_id)
            json.loads(body)
            post_headers = dict(request_headers)
            if post_index in omitted_bearer_posts:
                post_headers.pop("Authorization", None)
            elif post_index in post_bearer_environments:
                environment_name = post_bearer_environments[post_index]
                token = os.environ.get(environment_name, "")
                if not token:
                    raise RuntimeError(
                        f"POST Bearer token environment is not set or empty: {environment_name}"
                    )
                post_headers["Authorization"] = f"Bearer {token}"
            if post_index not in omitted_request_id_posts:
                post_headers["X-PDR-Request-Id"] = post_request_ids.get(
                    post_index, f"runtime-smoke-{port}-{post_index}"
                )
            status, response_body = probe(
                f"http://{args.host}:{port}{endpoint}", min(2.0, args.timeout), "POST", body,
                post_headers
            )
            result["probes"].append(
                {"endpoint": endpoint, "method": "POST", "status": status,
                 "body": response_body[:2048]}
            )
            response_bodies.append((endpoint, response_body))
            expected_post_status = post_response_statuses.get(post_index)
            if ((expected_post_status is None and (status < 200 or status >= 300)) or
                    (expected_post_status is not None and status != expected_post_status)):
                expected_text = ("2xx" if expected_post_status is None
                                 else str(expected_post_status))
                raise RuntimeError(
                    f"POST {endpoint} returned HTTP {status}, expected {expected_text}: "
                    f"{response_body[:256]}"
                )
            if status >= 200 and status < 300:
                try:
                    response_object = json.loads(response_body)
                    if (response_object.get("persisted") is True and
                            response_object.get("transactionId")):
                        last_committed_transaction_id = str(
                            response_object["transactionId"])
                    task = response_object.get("task")
                    if isinstance(task, dict) and task.get("id"):
                        last_management_task_id = str(task["id"])
                except (json.JSONDecodeError, TypeError):
                    pass
            sample_resources(f"post-{post_index}")
            observation_deadline = time.monotonic() + post_interval_overrides.get(
                post_index, args.post_interval)
            observation_sample = 0
            while time.monotonic() < observation_deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"runtime exited with code {process.returncode}")
                for observed_endpoint in dict.fromkeys(args.endpoint):
                    observed_status, observed_body = probe(
                        f"http://{args.host}:{port}{observed_endpoint}",
                        min(1.0, args.timeout),
                        extra_headers=headers_for_endpoint(observed_endpoint),
                    )
                    result["probes"].append(
                        {"endpoint": observed_endpoint, "method": "GET",
                         "stage": f"post-{post_index}-observe-{observation_sample + 1}",
                         "status": observed_status, "body": observed_body[:2048]}
                    )
                    response_bodies.append((observed_endpoint, observed_body))
                    expected = post_expected_statuses.get(
                        (post_index, observed_endpoint),
                        expected_statuses.get(observed_endpoint, 200),
                    )
                    if observed_status != expected:
                        detail = observed_body[:512]
                        if observed_endpoint == "/health/ready":
                            try:
                                _, detail_body = probe(
                                    f"http://{args.host}:{port}/health/detail",
                                    min(1.0, args.timeout),
                                    extra_headers=headers_for_endpoint("/health/detail"),
                                )
                                detail = detail_body[:1024]
                            except (OSError, urllib.error.URLError):
                                pass
                        raise RuntimeError(
                            f"{observed_endpoint} returned HTTP {observed_status}, expected "
                            f"{expected} after POST {post_index}: {detail}"
                        )
                observation_sample += 1
                sample_resources(f"post-{post_index}-observe-{observation_sample}")
                time.sleep(min(
                    args.post_health_interval,
                    max(0.0, observation_deadline - time.monotonic()),
                ))
        if args.post:
            result["posts"] = args.post
            result["postIntervalSeconds"] = args.post_interval
            result["postHealthIntervalSeconds"] = args.post_health_interval
        if args.follow_html_assets:
            origin = f"http://{args.host}:{port}"
            references: list[str] = []
            for source_endpoint, body in response_bodies:
                for reference in re.findall(
                    r'''(?:src|href)=["']([^"']+\.(?:js|css)(?:\?[^"']*)?)["']''', body):
                    references.append(urllib.parse.urljoin(origin + source_endpoint, reference))
            for asset_url in dict.fromkeys(references):
                parsed = urllib.parse.urlparse(asset_url)
                if parsed.hostname != args.host or parsed.port != port:
                    raise RuntimeError(f"refusing to fetch cross-origin HTML asset: {asset_url}")
                status, body = probe(asset_url, min(2.0, args.timeout),
                                     extra_headers=request_headers)
                if status != 200:
                    raise RuntimeError(f"HTML asset returned HTTP {status}: {asset_url}")
                endpoint = parsed.path + (f"?{parsed.query}" if parsed.query else "")
                result["probes"].append(
                    {"endpoint": endpoint, "status": status, "body": body[:2048]}
                )
                response_bodies.append((endpoint, body))
            result["followedHtmlAssets"] = len(references)
        response_content = "\n".join(body for _, body in response_bodies)
        missing_bodies = [
            pattern for pattern in args.require_body
            if re.search(pattern, response_content) is None
        ]
        if missing_bodies:
            raise RuntimeError(
                f"endpoint responses did not match required pattern(s): {missing_bodies}"
            )
        forbidden_bodies = [
            pattern for pattern in args.forbid_body
            if re.search(pattern, response_content) is not None
        ]
        if forbidden_bodies:
            raise RuntimeError(
                f"endpoint responses matched forbidden pattern(s): {forbidden_bodies}"
            )
        if args.require_body:
            result["requiredBodyPatterns"] = args.require_body
            result["requiredBodyMatches"] = {
                pattern: list(dict.fromkeys(
                    endpoint for endpoint, body in response_bodies
                    if re.search(pattern, body) is not None
                ))
                for pattern in args.require_body
            }
        if args.forbid_body:
            result["forbiddenBodyPatterns"] = args.forbid_body
        stability_deadline = time.monotonic() + args.stability_window
        while time.monotonic() < stability_deadline:
            if process.poll() is not None:
                raise RuntimeError(f"runtime exited with code {process.returncode}")
            for endpoint in dict.fromkeys(args.endpoint):
                status, body = probe(
                    f"http://{args.host}:{port}{endpoint}", min(1.0, args.timeout),
                    extra_headers=headers_for_endpoint(endpoint)
                )
                expected = expected_statuses.get(endpoint, 200)
                if status != expected:
                    detail = body[:512]
                    if endpoint == "/health/ready":
                        try:
                            _, detail_body = probe(
                                f"http://{args.host}:{port}/health/detail",
                                min(1.0, args.timeout),
                                extra_headers=headers_for_endpoint("/health/detail"),
                            )
                            detail = detail_body[:1024]
                        except (OSError, urllib.error.URLError):
                            pass
                    raise RuntimeError(
                        f"{endpoint} returned HTTP {status}, expected {expected} "
                        f"during stability window: {detail}"
                    )
            time.sleep(min(0.25, max(0.0, stability_deadline - time.monotonic())))
        sample_resources("stable")
        if resource_samples:
            baseline_index = 0
            if args.resource_baseline_after_post:
                post_stage = f"post-{args.resource_baseline_after_post}"
                matching_indices = [
                    index for index, sample in enumerate(resource_samples)
                    if sample["stage"] == post_stage or
                    str(sample["stage"]).startswith(post_stage + "-observe-")
                ]
                if not matching_indices:
                    raise RuntimeError(f"resource baseline sample missing after POST {args.resource_baseline_after_post}")
                baseline_index = matching_indices[-1]
            evaluated_samples = resource_samples[baseline_index:]
            rss_growth = int(evaluated_samples[-1]["rssBytes"]) - int(evaluated_samples[0]["rssBytes"])
            handle_growth = int(evaluated_samples[-1]["handles"]) - int(evaluated_samples[0]["handles"])
            result["resourceSamples"] = resource_samples
            result["resourceBaselineStage"] = evaluated_samples[0]["stage"]
            result["rssGrowthBytes"] = rss_growth
            result["handleGrowth"] = handle_growth
            result["peakRssBytes"] = max(int(sample["rssBytes"]) for sample in evaluated_samples)
            result["peakHandles"] = max(int(sample["handles"]) for sample in evaluated_samples)
            if rss_growth > args.max_rss_growth_mib * 1024 * 1024:
                raise RuntimeError(f"Runtime RSS growth exceeded limit: {rss_growth} bytes")
            if handle_growth > args.max_handle_growth:
                raise RuntimeError(f"Runtime handle growth exceeded limit: {handle_growth}")
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
        if args.forbid_log:
            if log_path is None:
                raise ValueError("--forbid-log requires --log or --report")
            if log_stream is not None:
                log_stream.flush()
            log_content = log_path.read_text(encoding="utf-8", errors="replace")
            present = [pattern for pattern in args.forbid_log if re.search(pattern, log_content)]
            if present:
                raise RuntimeError(f"runtime log matched forbidden pattern(s): {present}")
            result["forbiddenLogPatterns"] = args.forbid_log
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
            shutdown = stop_tree(process, args.shutdown_timeout, args.force_shutdown)
            result["shutdown"] = shutdown
            if (not shutdown["clean"] and not args.allow_forced_shutdown and
                    not args.force_shutdown):
                shutdown_failed = True
                result["passed"] = False
                result["shutdownError"] = (
                    f"Runtime shutdown was not clean: mode={shutdown['mode']} "
                    f"exitCode={shutdown['exitCode']}"
                )
        if log_stream is not None:
            log_stream.close()
        try:
            overlay.unlink(missing_ok=True)
        except OSError:
            pass
        if report_path:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        if shutdown_failed:
            print(f"RUNTIME_SMOKE_FAIL {result['shutdownError']}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
