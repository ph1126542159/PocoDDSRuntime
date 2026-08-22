#!/usr/bin/env python3
"""End-to-end acceptance test for the local robotics simulation WebUI service."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class OtlpCaptureHandler(BaseHTTPRequestHandler):
    payloads: list[dict] = []
    received = threading.Event()

    def do_POST(self) -> None:  # noqa: N802 - HTTP server callback
        length = int(self.headers.get("Content-Length", "0"))
        OtlpCaptureHandler.payloads.append(json.loads(self.rfile.read(length).decode("utf-8")))
        OtlpCaptureHandler.received.set()
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format_string: str, *args: object) -> None:
        del format_string, args


def request(url: str, method: str = "GET", value: dict | None = None) -> dict:
    body = json.dumps(value).encode("utf-8") if value is not None else None
    headers = {"Content-Type": "application/json"} if body else {}
    with urlopen(Request(url, data=body, headers=headers, method=method), timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def cors_request(url: str, origin: str, method: str = "GET") -> tuple[int, str | None]:
    with urlopen(Request(url, headers={"Origin": origin}, method=method), timeout=5) as response:
        return response.status, response.headers.get("Access-Control-Allow-Origin")


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
    parser.add_argument("--framework-manifest", type=Path)
    return parser.parse_args()


def main() -> int:
    options = parse_arguments()
    OtlpCaptureHandler.payloads.clear()
    OtlpCaptureHandler.received.clear()
    collector = ThreadingHTTPServer(("127.0.0.1", 0), OtlpCaptureHandler)
    collector_thread = threading.Thread(target=collector.serve_forever, daemon=True)
    collector_thread.start()
    collector_url = f"http://127.0.0.1:{collector.server_address[1]}/v1/traces"
    command = [
            sys.executable,
            str(options.server),
            "--port",
            "0",
            "--binary",
            str(options.binary),
            "--static-dir",
            str(options.static_dir),
            "--otlp-http-endpoint",
            collector_url,
        ]
    if options.framework_manifest:
        command.extend(["--framework-manifest", str(options.framework_manifest)])
    process = subprocess.Popen(
        command,
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
        framework = request(f"{base_url}/framework-model.json")
        assert health == {"live": True, "service": "pdr-robotics-web-sim"}
        assert framework["schemaVersion"] == 1
        assert framework["framework"]["family"] in {"robotics", "hybrid"}
        assert framework["capabilities"]["robotics"] is True
        assert {item["module"] for item in catalog["scenarios"]} == {
            "warehouse",
            "inspection",
            "pick_place",
        }
        cors_status, cors_origin = cors_request(
            f"{base_url}/api/v1/robotics-simulation/catalog", "http://127.0.0.1:9080"
        )
        assert cors_status == 200 and cors_origin == "http://127.0.0.1:9080"
        with urlopen(f"{base_url}/", timeout=5) as response:
            page = response.read().decode("utf-8")
            assert response.status == 200 and "机器人仿真中心" in page
            assert "framework-model-name" in page
            assert "OPENTELEMETRY TRACE" in page and "OpenTelemetry Span 详情" in page

        started = request(
            f"{base_url}/api/v1/robotics-simulation/runs",
            "POST",
            {"module": "warehouse", "periodMs": 10, "streamDelayMs": 1, "maxSteps": 5000},
        )
        completed = wait_for_run(base_url, started["runId"], {"success", "failed"})
        assert completed["status"] == "success"
        assert len(completed["nodes"]) == 5
        assert all(node["status"] == "success" for node in completed["nodes"])
        assert len(completed["traceId"]) == 32
        assert len(completed["rootSpanId"]) == 16
        assert completed["traceParent"] == (
            f"00-{completed['traceId']}-{completed['rootSpanId']}-01"
        )
        assert all(len(node["spanId"]) == 16 for node in completed["nodes"])
        assert all(node["traceId"] == completed["traceId"] for node in completed["nodes"])
        assert all(node["parentSpanId"] == completed["rootSpanId"] for node in completed["nodes"])
        assert all(node["otelStatusCode"] == "STATUS_CODE_OK" for node in completed["nodes"])
        trace = request(
            f"{base_url}/api/v1/robotics-simulation/traces/{completed['traceId']}"
        )
        assert trace["rootSpanId"] == completed["rootSpanId"]
        assert len(trace["spans"]) == 5
        assert OtlpCaptureHandler.received.wait(timeout=5)
        payload = OtlpCaptureHandler.payloads[0]
        exported_spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
        assert len(exported_spans) == 6
        assert exported_spans[0]["traceId"] == completed["traceId"]
        assert exported_spans[0]["flags"] == 1 and exported_spans[0]["kind"] == 1
        assert exported_spans[1]["parentSpanId"] == completed["rootSpanId"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            trace = request(
                f"{base_url}/api/v1/robotics-simulation/traces/{completed['traceId']}"
            )
            if trace["telemetry"]["export"]["status"] == "exported":
                break
            time.sleep(0.05)
        assert trace["telemetry"]["export"]["status"] == "exported"
        navigation = next(node for node in completed["nodes"] if node["operation"] == "navigate_to_pickup")
        assert navigation["inputs"]["target_x"] == "1.000"
        assert navigation["outputs"]["replans"] == "1"
        assert any(log["fields"].get("event") == "obstacle-injected" for log in navigation["logs"])
        assert completed["result"]["watchdogStop"] is True
        assert abs(float(completed["result"]["x"]) - 2.0) < 1e-9

        pick_place = request(
            f"{base_url}/api/v1/robotics-simulation/runs",
            "POST",
            {"module": "pick_place", "periodMs": 10, "streamDelayMs": 1, "maxSteps": 5000},
        )
        pick_place = wait_for_run(base_url, pick_place["runId"], {"success", "failed"})
        assert pick_place["status"] == "success"
        assert [node["operation"] for node in pick_place["nodes"]] == [
            "approach_object", "close_gripper", "move_to_place", "open_gripper"
        ]
        assert all(node["status"] == "success" for node in pick_place["nodes"])

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
            f"events={len(completed['events'])} trace={completed['traceId']} "
            f"otlpSpans={len(exported_spans)} cancelled={cancelled['runId']}"
        )
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        collector.shutdown()
        collector.server_close()
        collector_thread.join(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
