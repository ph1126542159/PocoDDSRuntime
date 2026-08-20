#!/usr/bin/env python3
"""End-to-end acceptance test for the local robotics simulation WebUI service."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def request(url: str, method: str = "GET", value: dict | None = None) -> dict:
    body = json.dumps(value).encode("utf-8") if value is not None else None
    headers = {"Content-Type": "application/json"} if body else {}
    with urlopen(Request(url, data=body, headers=headers, method=method), timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_run(base_url: str, run_id: str, terminal: set[str], timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        detail = request(f"{base_url}/api/v1/robotics-simulation/runs/{run_id}")
        if detail["status"] in terminal:
            return detail
        time.sleep(0.1)
    raise AssertionError(f"simulation {run_id} did not reach {terminal}")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--static-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    options = parse_arguments()
    process = subprocess.Popen(
        [
            sys.executable,
            str(options.server),
            "--port",
            "0",
            "--binary",
            str(options.binary),
            "--static-dir",
            str(options.static_dir),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        assert process.stdout is not None
        ready = process.stdout.readline().strip()
        if not ready.startswith("PDR_ROBOTICS_WEB_READY http://"):
            raise AssertionError(f"Web server did not become ready: {ready}")
        base_url = ready.split()[1].rstrip("/")
        health = request(f"{base_url}/health/live")
        catalog = request(f"{base_url}/api/v1/robotics-simulation/catalog")
        assert health == {"live": True, "service": "pdr-robotics-web-sim"}
        assert {item["module"] for item in catalog["scenarios"]} == {
            "warehouse",
            "inspection",
            "pick_place",
        }
        with urlopen(f"{base_url}/", timeout=5) as response:
            page = response.read().decode("utf-8")
            assert response.status == 200 and "机器人仿真中心" in page

        started = request(
            f"{base_url}/api/v1/robotics-simulation/runs",
            "POST",
            {"module": "warehouse", "periodMs": 10, "streamDelayMs": 1, "maxSteps": 5000},
        )
        completed = wait_for_run(base_url, started["runId"], {"success", "failed"})
        assert completed["status"] == "success"
        assert len(completed["nodes"]) == 5
        assert all(node["status"] == "success" for node in completed["nodes"])
        navigation = next(node for node in completed["nodes"] if node["operation"] == "navigate_to_pickup")
        assert navigation["inputs"]["target_x"] == "1.000"
        assert navigation["outputs"]["replans"] == "1"
        assert any(log["fields"].get("event") == "obstacle-injected" for log in navigation["logs"])
        assert completed["result"]["watchdogStop"] is True
        assert abs(float(completed["result"]["x"]) - 2.0) < 1e-9

        cancellable = request(
            f"{base_url}/api/v1/robotics-simulation/runs",
            "POST",
            {"module": "inspection", "periodMs": 10, "streamDelayMs": 30, "maxSteps": 5000},
        )
        wait_for_run(base_url, cancellable["runId"], {"running"}, timeout=5)
        request(
            f"{base_url}/api/v1/robotics-simulation/runs/{cancellable['runId']}/cancel",
            "POST",
            {},
        )
        cancelled = wait_for_run(base_url, cancellable["runId"], {"cancelled", "failed"})
        assert cancelled["status"] == "cancelled"
        assert any(node["status"] == "cancelled" for node in cancelled["nodes"])

        try:
            request(
                f"{base_url}/api/v1/robotics-simulation/runs",
                "POST",
                {"module": "not-registered"},
            )
            raise AssertionError("unknown module was accepted")
        except HTTPError as exception:
            assert exception.code == 400

        print(
            "PDR_ROBOTICS_WEB_TEST_PASS "
            f"run={completed['runId']} nodes={len(completed['nodes'])} "
            f"events={len(completed['events'])} cancelled={cancelled['runId']}"
        )
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
