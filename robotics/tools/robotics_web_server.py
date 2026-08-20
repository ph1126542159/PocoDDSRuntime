#!/usr/bin/env python3
"""Local, dependency-free Web controller for the real C++ robotics business SIL."""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
import threading
import time
import uuid
import webbrowser
from collections import OrderedDict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit


SCENARIOS: dict[str, dict[str, Any]] = {
    "warehouse": {
        "title": "仓储搬运机器人",
        "mission": "deliver",
        "description": "定位、避障取货、通信中断看门狗、送货和卸载",
        "steps": [
            ("localize", "地图定位", "map=warehouse_map"),
            ("navigate_to_pickup", "前往取货点", "target_x=1.000,speed=0.500,obstacle_signal=warehouse.obstacle"),
            ("pick_payload", "机械臂取货", "joint=arm_joint,target=0.800"),
            ("navigate_to_dropoff", "前往卸货点", "target_x=2.000,speed=0.500,obstacle_signal=warehouse.obstacle"),
            ("release_payload", "释放货物", "joint=arm_joint,target=-0.200"),
        ],
    },
    "inspection": {
        "title": "自主巡检机器人",
        "mission": "patrol",
        "description": "传感器自检、避障巡检、异常分析和返回起点",
        "steps": [
            ("sensor_self_check", "传感器自检", "sensors=required"),
            ("patrol_to_asset", "巡检目标设备", "target_x=0.800,speed=0.400,obstacle_signal=inspection.obstacle"),
            ("analyze_asset", "分析设备异常", "anomaly_signal=inspection.anomaly"),
            ("return_home", "返回起点", "target_x=0.000,speed=0.400,obstacle_signal=inspection.obstacle"),
        ],
    },
    "pick_place": {
        "title": "机械臂抓取转运",
        "mission": "transfer",
        "description": "机械臂接近、夹爪闭合、转运和释放",
        "steps": [
            ("approach_payload", "接近物料", "joint=arm_joint,target=0.600"),
            ("close_gripper", "闭合夹爪", "joint=gripper_joint,target=0.300"),
            ("transfer_payload", "转运物料", "joint=arm_joint,target=-0.500"),
            ("open_gripper", "打开夹爪", "joint=gripper_joint,target=-0.200"),
        ],
    },
}


def now_microseconds() -> int:
    return time.time_ns() // 1_000


def parse_fields(value: str) -> dict[str, str]:
    if not value:
        return {}
    result: dict[str, str] = {}
    current_key = ""
    for index, item in enumerate(value.split(",")):
        key, separator, field_value = item.partition("=")
        if separator:
            current_key = key.strip()
            result[current_key] = field_value.strip()
        elif current_key:
            result[current_key] += f",{item.strip()}"
        else:
            result[f"value{index + 1}"] = item.strip()
    return result


def make_log(level: str, message: str, fields: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "timestampUnixMicroseconds": now_microseconds(),
        "level": level,
        "message": message,
        "fields": {key: str(value) for key, value in (fields or {}).items()},
    }


class SimulationManager:
    def __init__(self, binary: Path, maximum_history: int = 30) -> None:
        self._binary = binary.resolve()
        self._maximum_history = maximum_history
        self._lock = threading.RLock()
        self._runs: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._processes: dict[str, subprocess.Popen[str]] = {}

    @property
    def binary(self) -> Path:
        return self._binary

    def catalog(self) -> dict[str, Any]:
        return {
            "simulator": "PocoDDS deterministic robotics SIL",
            "binary": str(self._binary),
            "scenarios": [
                {
                    "module": module,
                    "title": definition["title"],
                    "mission": definition["mission"],
                    "description": definition["description"],
                    "stepCount": len(definition["steps"]),
                }
                for module, definition in SCENARIOS.items()
            ],
            "limits": {"periodMs": [1, 1000], "streamDelayMs": [1, 1000], "maxSteps": [1, 1_000_000]},
        }

    def summaries(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._summary(run) for run in reversed(self._runs.values())]

    def detail(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            run = self._runs.get(run_id)
            return copy.deepcopy(run) if run else None

    def start(self, module: str, period_ms: int, stream_delay_ms: int, maximum_steps: int) -> dict[str, Any]:
        if module not in SCENARIOS:
            raise ValueError("unknown robotics business module")
        if not 1 <= period_ms <= 1000:
            raise ValueError("periodMs must be in [1, 1000]")
        if not 1 <= stream_delay_ms <= 1000:
            raise ValueError("streamDelayMs must be in [1, 1000]")
        if not 1 <= maximum_steps <= 1_000_000:
            raise ValueError("maxSteps must be in [1, 1000000]")
        if not self._binary.is_file():
            raise RuntimeError(f"simulator binary not found: {self._binary}")

        with self._lock:
            if any(run["status"] in {"queued", "running"} for run in self._runs.values()):
                raise RuntimeError("another simulation is already running")
            run_id = f"robotics-{module}-{int(time.time())}-{uuid.uuid4().hex[:8]}"
            definition = SCENARIOS[module]
            started = now_microseconds()
            nodes = []
            previous = ""
            for index, (step, title, inputs) in enumerate(definition["steps"]):
                span_id = f"{index + 1:02d}-{step}"
                nodes.append(
                    {
                        "businessName": definition["title"],
                        "businessInstanceId": run_id,
                        "operation": step,
                        "displayName": title,
                        "serviceName": "pdr-business-sim",
                        "bundleName": f"robotics.business.{module}",
                        "hostName": os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "localhost",
                        "processId": 0,
                        "traceId": run_id,
                        "spanId": span_id,
                        "parentSpanId": previous,
                        "status": "pending",
                        "errorCode": "",
                        "errorMessage": "",
                        "startedUnixMicroseconds": 0,
                        "endedUnixMicroseconds": 0,
                        "durationNanoseconds": 0,
                        "inputs": parse_fields(inputs),
                        "outputs": {},
                        "logs": [],
                    }
                )
                previous = span_id
            run = {
                "runId": run_id,
                "traceId": run_id,
                "module": module,
                "mission": definition["mission"],
                "title": definition["title"],
                "description": definition["description"],
                "status": "queued",
                "startedUnixMicroseconds": started,
                "endedUnixMicroseconds": 0,
                "durationNanoseconds": 0,
                "parameters": {
                    "periodMs": period_ms,
                    "streamDelayMs": stream_delay_ms,
                    "maxSteps": maximum_steps,
                },
                "nodes": nodes,
                "events": [make_log("info", "仿真任务已进入执行队列", {"module": module})],
                "result": {},
                "rawOutput": [],
                "cancelRequested": False,
            }
            self._runs[run_id] = run
            while len(self._runs) > self._maximum_history:
                self._runs.popitem(last=False)

        thread = threading.Thread(
            target=self._execute,
            args=(run_id, period_ms, stream_delay_ms, maximum_steps),
            name=f"robotics-web-{module}",
            daemon=True,
        )
        thread.start()
        return self._summary(run)

    def cancel(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            run = self._runs.get(run_id)
            if not run:
                raise KeyError(run_id)
            if run["status"] not in {"queued", "running"}:
                return self._summary(run)
            run["cancelRequested"] = True
            run["events"].append(make_log("warning", "用户请求取消仿真任务"))
            process = self._processes.get(run_id)
        if process and process.poll() is None:
            process.terminate()
        return self._summary(self.detail(run_id) or run)

    def stop_all(self) -> None:
        with self._lock:
            processes = list(self._processes.values())
        for process in processes:
            if process.poll() is None:
                process.terminate()

    def _execute(self, run_id: str, period_ms: int, stream_delay_ms: int, maximum_steps: int) -> None:
        with self._lock:
            if self._runs[run_id]["cancelRequested"]:
                run = self._runs[run_id]
                run["status"] = "cancelled"
                run["endedUnixMicroseconds"] = now_microseconds()
                run["durationNanoseconds"] = max(
                    0, (run["endedUnixMicroseconds"] - run["startedUnixMicroseconds"]) * 1000
                )
                for node in run["nodes"]:
                    node["status"] = "cancelled"
                    node["endedUnixMicroseconds"] = run["endedUnixMicroseconds"]
                    node["errorCode"] = "SIMULATION_CANCELLED"
                    node["errorMessage"] = "simulation cancelled before process start"
                return
        command = [
            str(self._binary),
            "--module",
            self._runs[run_id]["module"],
            "--period-ms",
            str(period_ms),
            "--max-steps",
            str(maximum_steps),
            "--json-lines",
            "--stream-delay-ms",
            str(stream_delay_ms),
        ]
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            process = subprocess.Popen(
                command,
                cwd=str(self._binary.parent),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creation_flags,
            )
            with self._lock:
                run = self._runs[run_id]
                if run["cancelRequested"]:
                    process.terminate()
                run["status"] = "running"
                run["events"].append(make_log("info", "C++ 仿真进程已启动", {"pid": process.pid}))
                for node in run["nodes"]:
                    node["processId"] = process.pid
                self._processes[run_id] = process
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = raw_line.rstrip("\r\n")
                if line:
                    self._consume(run_id, line)
            return_code = process.wait()
            self._finish_process(run_id, return_code)
        except Exception as exception:  # noqa: BLE001 - boundary records the complete failure
            with self._lock:
                run = self._runs[run_id]
                run["status"] = "failed"
                run["endedUnixMicroseconds"] = now_microseconds()
                run["durationNanoseconds"] = max(
                    0, (run["endedUnixMicroseconds"] - run["startedUnixMicroseconds"]) * 1000
                )
                run["events"].append(make_log("error", "仿真进程启动或读取失败", {"error": exception}))
        finally:
            with self._lock:
                self._processes.pop(run_id, None)

    def _consume(self, run_id: str, line: str) -> None:
        with self._lock:
            run = self._runs[run_id]
            run["rawOutput"].append(line)
            run["rawOutput"] = run["rawOutput"][-200:]
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            with self._lock:
                run["events"].append(make_log("warning", "收到非结构化仿真输出", {"line": line}))
            return

        message_type = message.get("type")
        with self._lock:
            run = self._runs[run_id]
            if message_type == "step":
                node = next((item for item in run["nodes"] if item["operation"] == message.get("step")), None)
                if not node:
                    run["events"].append(make_log("warning", "收到未知业务步骤", message))
                    return
                status = {"succeeded": "success", "canceled": "cancelled"}.get(
                    message.get("status"), message.get("status", "failed")
                )
                node["status"] = status
                node["inputs"] = parse_fields(message.get("input", "")) or node["inputs"]
                if status == "running":
                    node["startedUnixMicroseconds"] = now_microseconds()
                    node["logs"].append(
                        make_log("info", f"开始执行：{node['displayName']}", {"virtualTick": message.get("startTick", 0)})
                    )
                else:
                    node["endedUnixMicroseconds"] = now_microseconds()
                    node["startedUnixMicroseconds"] = node["startedUnixMicroseconds"] or node["endedUnixMicroseconds"]
                    node["durationNanoseconds"] = int(message.get("durationNanoseconds", 0))
                    node["outputs"] = parse_fields(message.get("output", ""))
                    detail = message.get("detail", "")
                    level = "info" if status == "success" else "error"
                    node["logs"].append(
                        make_log(level, f"节点{status}: {detail}", {"finishTick": message.get("finishTick", 0)})
                    )
                    if status == "failed":
                        node["errorCode"] = "ROBOTICS_STEP_FAILED"
                        node["errorMessage"] = detail or "robotics business step failed"
            elif message_type == "event":
                event = make_log(
                    message.get("level", "info"),
                    message.get("message", message.get("event", "simulation event")),
                    {"event": message.get("event", ""), "virtualTick": message.get("tick", 0)},
                )
                run["events"].append(event)
                current = next((node for node in run["nodes"] if node["status"] == "running"), None)
                if current:
                    current["logs"].append(copy.deepcopy(event))
            elif message_type == "summary":
                run["result"] = message
                run["events"].append(make_log("info", "业务场景完成安全验收", message))
            elif message_type == "all-complete":
                run["events"].append(make_log("info", "全部选择的业务模块执行完成", message))

    def _finish_process(self, run_id: str, return_code: int) -> None:
        with self._lock:
            run = self._runs[run_id]
            cancelled = run["cancelRequested"]
            if cancelled:
                run["status"] = "cancelled"
            elif return_code == 0 and run.get("result", {}).get("status") == "success":
                run["status"] = "success"
            else:
                run["status"] = "failed"
            run["endedUnixMicroseconds"] = now_microseconds()
            run["durationNanoseconds"] = max(
                0, (run["endedUnixMicroseconds"] - run["startedUnixMicroseconds"]) * 1000
            )
            for node in run["nodes"]:
                if node["status"] in {"pending", "running"}:
                    node["status"] = "cancelled" if cancelled else "failed"
                    node["endedUnixMicroseconds"] = run["endedUnixMicroseconds"]
                    node["errorCode"] = "SIMULATION_CANCELLED" if cancelled else "SIMULATOR_EXITED"
                    node["errorMessage"] = "simulation cancelled" if cancelled else f"simulator exited with code {return_code}"
            run["events"].append(
                make_log(
                    "info" if run["status"] == "success" else "warning",
                    "仿真进程已结束",
                    {"status": run["status"], "exitCode": return_code},
                )
            )

    @staticmethod
    def _summary(run: dict[str, Any]) -> dict[str, Any]:
        nodes = run.get("nodes", [])
        failed = next((node["operation"] for node in nodes if node["status"] == "failed"), "")
        return {
            "runId": run["runId"],
            "traceId": run["traceId"],
            "businessName": run["title"],
            "businessInstanceId": run["runId"],
            "module": run["module"],
            "mission": run["mission"],
            "description": run["description"],
            "status": run["status"],
            "startedUnixMicroseconds": run["startedUnixMicroseconds"],
            "durationNanoseconds": run["durationNanoseconds"],
            "stepCount": len(nodes),
            "completedStepCount": sum(node["status"] == "success" for node in nodes),
            "failedOperation": failed,
            "parameters": copy.deepcopy(run["parameters"]),
        }


class RoboticsWebServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], manager: SimulationManager, static_dir: Path) -> None:
        super().__init__(address, RoboticsRequestHandler)
        self.manager = manager
        self.static_dir = static_dir.resolve()


class RoboticsRequestHandler(BaseHTTPRequestHandler):
    server: RoboticsWebServer

    def log_message(self, format_string: str, *args: Any) -> None:
        request_line = str(args[0]) if args else ""
        try:
            status = int(args[1])
        except (IndexError, TypeError, ValueError):
            status = 0
        if status < 400 and request_line.startswith("GET /api/v1/robotics-simulation/runs"):
            return
        print(f"PDR_ROBOTICS_WEB_ACCESS {self.address_string()} {format_string % args}")

    def _headers(self, status: HTTPStatus, content_type: str, length: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'")
        self.end_headers()

    def _json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(body))
        self.wfile.write(body)

    def _error(self, status: HTTPStatus, message: str) -> None:
        self._json({"error": message}, status)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 65_536:
            raise ValueError("request body must contain 1 to 65536 bytes")
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("request body must be a JSON object")
        return value

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        path = unquote(urlsplit(self.path).path)
        if path == "/health/live":
            self._json({"live": True, "service": "pdr-robotics-web-sim"})
        elif path == "/api/v1/robotics-simulation/catalog":
            self._json(self.server.manager.catalog())
        elif path == "/api/v1/robotics-simulation/runs":
            self._json({"runs": self.server.manager.summaries()})
        elif path.startswith("/api/v1/robotics-simulation/runs/"):
            run_id = path.removeprefix("/api/v1/robotics-simulation/runs/").strip("/")
            detail = self.server.manager.detail(run_id)
            if detail:
                self._json(detail)
            else:
                self._error(HTTPStatus.NOT_FOUND, "simulation run not found")
        else:
            self._static(path)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        path = unquote(urlsplit(self.path).path)
        try:
            if path == "/api/v1/robotics-simulation/runs":
                body = self._read_json()
                result = self.server.manager.start(
                    str(body.get("module", "warehouse")),
                    int(body.get("periodMs", 10)),
                    int(body.get("streamDelayMs", 8)),
                    int(body.get("maxSteps", 5000)),
                )
                self._json(result, HTTPStatus.ACCEPTED)
            elif path.endswith("/cancel") and path.startswith("/api/v1/robotics-simulation/runs/"):
                run_id = path.removeprefix("/api/v1/robotics-simulation/runs/").removesuffix("/cancel").strip("/")
                self._json(self.server.manager.cancel(run_id))
            else:
                self._error(HTTPStatus.NOT_FOUND, "endpoint not found")
        except KeyError:
            self._error(HTTPStatus.NOT_FOUND, "simulation run not found")
        except RuntimeError as exception:
            self._error(HTTPStatus.CONFLICT, str(exception))
        except (ValueError, TypeError, json.JSONDecodeError) as exception:
            self._error(HTTPStatus.BAD_REQUEST, str(exception))

    def _static(self, path: str) -> None:
        files = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/index.html": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/styles.css": ("styles.css", "text/css; charset=utf-8"),
        }
        selected = files.get(path)
        if not selected:
            self._error(HTTPStatus.NOT_FOUND, "resource not found")
            return
        file_path = self.server.static_dir / selected[0]
        if not file_path.is_file():
            self._error(HTTPStatus.NOT_FOUND, "WebUI resource not built")
            return
        body = file_path.read_bytes()
        self._headers(HTTPStatus.OK, selected[1], len(body))
        self.wfile.write(body)


def parse_arguments() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    repository = script_dir.parent.parent
    executable = "pdr-business-sim.exe" if os.name == "nt" else "pdr-business-sim"
    installed_prefix = script_dir.parents[2] if len(script_dir.parents) > 2 else script_dir
    binary_candidates = [
        repository / "build" / "robotics" / "bin" / executable,
        installed_prefix / "bin" / executable,
    ]
    discovered = shutil.which(executable)
    if discovered:
        binary_candidates.append(Path(discovered))
    default_binary = next((candidate for candidate in binary_candidates if candidate.is_file()), binary_candidates[0])
    source_static = repository / "robotics" / "webui"
    installed_static = script_dir.parent / "webui"
    default_static = source_static if source_static.is_dir() else installed_static
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9096)
    parser.add_argument("--binary", type=Path, default=default_binary)
    parser.add_argument("--static-dir", type=Path, default=default_static)
    parser.add_argument("--open-browser", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    if not 0 <= arguments.port <= 65_535:
        raise SystemExit("--port must be in [0, 65535]")
    manager = SimulationManager(arguments.binary)
    server = RoboticsWebServer((arguments.host, arguments.port), manager, arguments.static_dir)
    host, port = server.server_address[:2]
    url = f"http://{host}:{port}/"
    print(f"PDR_ROBOTICS_WEB_READY {url} binary={manager.binary}", flush=True)
    if arguments.open_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        manager.stop_all()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
