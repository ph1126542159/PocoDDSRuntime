#!/usr/bin/env python3
"""Run a process for a bounded soak period and report resource trends as JSON."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def windows_resources(process: subprocess.Popen[Any]) -> tuple[int, int]:
    class Counters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
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


def posix_resources(process: subprocess.Popen[Any]) -> tuple[int, int]:
    status = Path(f"/proc/{process.pid}/status").read_text(encoding="utf-8")
    match = next(line for line in status.splitlines() if line.startswith("VmRSS:"))
    rss = int(match.split()[1]) * 1024
    handles = len(list(Path(f"/proc/{process.pid}/fd").iterdir()))
    return rss, handles


def resources(process: subprocess.Popen[Any]) -> tuple[int, int]:
    return windows_resources(process) if os.name == "nt" else posix_resources(process)


def terminate(process: subprocess.Popen[Any]) -> None:
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
            os.killpg(process.pid, 15)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, 9)
            process.wait(timeout=5)


def health_status(url: str, timeout: float) -> tuple[bool, int | None, str]:
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(2048).decode("utf-8", errors="replace")
            return response.status == 200, response.status, body
    except urllib.error.HTTPError as error:
        return False, error.code, str(error)
    except (OSError, urllib.error.URLError) as error:
        return False, None, str(error)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, required=True, help="seconds")
    parser.add_argument("--interval", type=float, default=5.0, help="sample interval in seconds")
    parser.add_argument("--warmup", type=float, default=5.0, help="startup warmup in seconds")
    parser.add_argument("--cwd", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-rss-growth-mib", type=float, default=64.0)
    parser.add_argument("--max-handle-growth", type=int, default=32)
    parser.add_argument("--health-url", help="readiness/liveness URL probed at every sample")
    parser.add_argument("--health-timeout", type=float, default=2.0)
    parser.add_argument("--max-consecutive-health-failures", type=int, default=0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if (not args.command or args.duration <= 0 or args.interval <= 0 or args.warmup < 0 or
            args.health_timeout <= 0 or args.max_consecutive_health_failures < 0):
        parser.error(
            "a command, positive duration/interval/health-timeout and non-negative "
            "warmup/health-failure limit are required"
        )

    started = datetime.now(timezone.utc)
    process = subprocess.Popen(
        args.command,
        cwd=args.cwd,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        start_new_session=os.name != "nt",
    )
    samples: list[dict[str, Any]] = []
    violations: list[str] = []
    warmupDeadline = time.monotonic() + args.warmup
    while time.monotonic() < warmupDeadline and process.poll() is None:
        time.sleep(min(0.1, warmupDeadline - time.monotonic()))
    if process.poll() is not None:
        violations.append(f"process exited during warmup with code {process.returncode}")
    start = time.monotonic()
    deadline = start + args.duration
    consecutive_health_failures = 0
    maximum_consecutive_health_failures = 0
    total_health_failures = 0
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                violations.append(f"process exited early with code {process.returncode}")
                break
            rss, handles = resources(process)
            sample = {
                "elapsedSeconds": round(time.monotonic() - start, 3),
                "rssBytes": rss,
                "handles": handles,
            }
            if args.health_url:
                healthy, status, detail = health_status(args.health_url, args.health_timeout)
                sample.update({"healthy": healthy, "healthStatus": status})
                if not healthy:
                    sample["healthError"] = detail
                    consecutive_health_failures += 1
                    total_health_failures += 1
                    maximum_consecutive_health_failures = max(
                        maximum_consecutive_health_failures, consecutive_health_failures
                    )
                else:
                    consecutive_health_failures = 0
            samples.append(sample)
            time.sleep(min(args.interval, max(0.0, deadline - time.monotonic())))
        if process.poll() is None:
            rss, handles = resources(process)
            samples.append(
                {"elapsedSeconds": round(time.monotonic() - start, 3), "rssBytes": rss, "handles": handles}
            )
    finally:
        terminate(process)

    if not samples:
        violations.append("no resource samples were collected")
        first = last = {"rssBytes": 0, "handles": 0}
    else:
        first, last = samples[0], samples[-1]
    rss_growth = int(last["rssBytes"]) - int(first["rssBytes"])
    handle_growth = int(last["handles"]) - int(first["handles"])
    if rss_growth > args.max_rss_growth_mib * 1024 * 1024:
        violations.append(f"RSS growth exceeded limit: {rss_growth} bytes")
    if handle_growth > args.max_handle_growth:
        violations.append(f"handle growth exceeded limit: {handle_growth}")
    if maximum_consecutive_health_failures > args.max_consecutive_health_failures:
        violations.append(
            "consecutive health failures exceeded limit: "
            f"{maximum_consecutive_health_failures}"
        )

    report = {
        "schemaVersion": 1,
        "startedAt": started.isoformat(),
        "durationSeconds": args.duration,
        "warmupSeconds": args.warmup,
        "command": args.command,
        "sampleCount": len(samples),
        "rssGrowthBytes": rss_growth,
        "peakRssBytes": max((sample["rssBytes"] for sample in samples), default=0),
        "handleGrowth": handle_growth,
        "peakHandles": max((sample["handles"] for sample in samples), default=0),
        "healthUrl": args.health_url,
        "healthFailureCount": total_health_failures,
        "maximumConsecutiveHealthFailures": maximum_consecutive_health_failures,
        "passed": not violations,
        "violations": violations,
        "samples": samples,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8", newline="\n")
    print(
        f"SOAK_{'PASS' if report['passed'] else 'FAIL'} samples={len(samples)} "
        f"rssGrowth={rss_growth} handleGrowth={handle_growth} report={args.output}"
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
