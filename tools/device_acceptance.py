#!/usr/bin/env python3
"""Collect and enforce runtime device acceptance evidence from /api/v1/devices."""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--minimum-success-delta", type=int, default=0)
    parser.add_argument("--minimum-reconnect-delta", type=int, default=0)
    parser.add_argument("--maximum-failed-delta", type=int, default=0)
    parser.add_argument("--maximum-consecutive-failures", type=int, default=0)
    parser.add_argument("--require-final-state", default="ready")
    parser.add_argument("--report", required=True, type=Path)
    return parser.parse_args()


def fetch(url: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"device inventory returned HTTP {response.status}")
        return json.loads(response.read().decode("utf-8"))


def select_device(inventory: dict[str, Any], device_id: str) -> dict[str, Any]:
    for device in inventory.get("devices", []):
        if device.get("id") == device_id:
            if not isinstance(device.get("diagnostics"), dict):
                raise RuntimeError(f"device {device_id} does not expose diagnostics")
            return device
    raise RuntimeError(f"device not found: {device_id}")


def counter(device: dict[str, Any], name: str) -> int:
    value = device["diagnostics"].get(name, 0)
    if not isinstance(value, int) or value < 0:
        raise RuntimeError(f"invalid diagnostics counter {name}: {value!r}")
    return value


def main() -> int:
    args = parse_args()
    if args.duration <= 0 or args.interval <= 0 or args.timeout <= 0:
        raise SystemExit("duration, interval and timeout must be positive")
    if min(args.minimum_success_delta, args.minimum_reconnect_delta,
           args.maximum_failed_delta, args.maximum_consecutive_failures) < 0:
        raise SystemExit("acceptance thresholds must be non-negative")

    started = time.monotonic()
    samples: list[dict[str, Any]] = []
    errors: list[str] = []
    while True:
        try:
            device = select_device(fetch(args.url, args.timeout), args.device_id)
            samples.append({
                "elapsedSeconds": round(time.monotonic() - started, 3),
                "state": device.get("state"),
                "sequence": device.get("sequence"),
                "diagnostics": device["diagnostics"],
            })
        except Exception as error:  # Evidence must retain every probe failure.
            errors.append(str(error))
        elapsed = time.monotonic() - started
        if elapsed >= args.duration:
            break
        time.sleep(min(args.interval, args.duration - elapsed))

    failures = list(errors)
    deltas: dict[str, int] = {}
    if samples:
        first, last = samples[0], samples[-1]
        for name in ("successfulOperations", "failedOperations", "reconnectAttempts"):
            deltas[name] = counter(last, name) - counter(first, name)
        if last.get("state") != args.require_final_state:
            failures.append(
                f"final state {last.get('state')!r} is not {args.require_final_state!r}")
        maximum_consecutive = max(
            counter(sample, "consecutiveFailures") for sample in samples)
        if deltas["successfulOperations"] < args.minimum_success_delta:
            failures.append("successful operation delta below minimum")
        if deltas["reconnectAttempts"] < args.minimum_reconnect_delta:
            failures.append("reconnect delta below minimum")
        if deltas["failedOperations"] > args.maximum_failed_delta:
            failures.append("failed operation delta above maximum")
        if maximum_consecutive > args.maximum_consecutive_failures:
            failures.append("consecutive failure count above maximum")
    else:
        maximum_consecutive = 0
        failures.append("no valid device samples collected")

    evidence = {
        "schemaVersion": 1,
        "deviceId": args.device_id,
        "url": args.url,
        "durationSeconds": round(time.monotonic() - started, 3),
        "thresholds": {
            "minimumSuccessDelta": args.minimum_success_delta,
            "minimumReconnectDelta": args.minimum_reconnect_delta,
            "maximumFailedDelta": args.maximum_failed_delta,
            "maximumConsecutiveFailures": args.maximum_consecutive_failures,
            "requiredFinalState": args.require_final_state,
        },
        "deltas": deltas,
        "maximumConsecutiveFailuresObserved": maximum_consecutive,
        "samples": samples,
        "probeErrors": errors,
        "failures": failures,
        "passed": not failures,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print("DEVICE_ACCEPTANCE_PASS" if not failures else "DEVICE_ACCEPTANCE_FAIL",
          f"device={args.device_id} samples={len(samples)}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
