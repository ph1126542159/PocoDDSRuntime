#!/usr/bin/env python3
"""Run the packaged Runtime against local MQTT and rosbridge protocol servers."""

from __future__ import annotations

import argparse
import hashlib
import base64
import hashlib
import json
import math
import os
import socket
import struct
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def receive_exact(connection: socket.socket, size: int) -> bytes:
    result = bytearray()
    while len(result) < size:
        chunk = connection.recv(size - len(result))
        if not chunk:
            raise ConnectionError("peer closed the connection")
        result.extend(chunk)
    return bytes(result)


class TestServer:
    def __init__(self) -> None:
        self.listener = socket.socket()
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen()
        self.listener.settimeout(0.2)
        self.port = int(self.listener.getsockname()[1])
        self.connections = 0
        self.errors: list[str] = []
        self.transport_closures: list[str] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.listener.close()
        self._thread.join(timeout=3)
        if self._thread.is_alive():
            self.errors.append("server thread did not stop")

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                connection, _ = self.listener.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            try:
                connection.settimeout(5)
                self.handle(connection)
            except (ConnectionError, OSError, ValueError) as error:
                transport_closure = (
                    (isinstance(error, (ConnectionError, TimeoutError)) or
                     getattr(error, "winerror", None) in {10053, 10054} or
                     getattr(error, "errno", None) in {10053, 10054})
                )
                if transport_closure:
                    self.transport_closures.append(str(error))
                elif not self._stop.is_set():
                    self.errors.append(str(error))
            finally:
                connection.close()

    def handle(self, connection: socket.socket) -> None:
        raise NotImplementedError


class MqttServer(TestServer):
    def __init__(self, disconnect_connections: set[int] | None = None,
                 disconnect_delay: float = 0.25) -> None:
        super().__init__()
        self.injected_disconnect_connections = disconnect_connections or {1}
        self.disconnect_delay = disconnect_delay

    @staticmethod
    def receive_packet(connection: socket.socket) -> tuple[int, bytes]:
        header = receive_exact(connection, 1)[0]
        remaining = 0
        multiplier = 1
        for _ in range(4):
            encoded = receive_exact(connection, 1)[0]
            remaining += (encoded & 0x7F) * multiplier
            if encoded & 0x80 == 0:
                return header, receive_exact(connection, remaining)
            multiplier *= 128
        raise ValueError("invalid MQTT remaining length")

    def handle(self, connection: socket.socket) -> None:
        header, _ = self.receive_packet(connection)
        if header >> 4 != 1:
            raise ValueError("expected MQTT CONNECT")
        connection.sendall(b"\x20\x02\x00\x00")
        self.connections += 1
        if self.connections in self.injected_disconnect_connections:
            # Inject a transport-side failure after the initial CONNACK. The
            # short delay lets the client commit its connected state so this
            # exercises established-session recovery rather than handshake timing.
            time.sleep(self.disconnect_delay)
            connection.shutdown(socket.SHUT_RDWR)
            return
        while not self._stop.is_set():
            header, _ = self.receive_packet(connection)
            packet_type = header >> 4
            if packet_type == 12:  # PINGREQ
                connection.sendall(b"\xD0\x00")
            elif packet_type == 14:  # DISCONNECT
                return


class RosbridgeServer(TestServer):
    @staticmethod
    def receive_frame(connection: socket.socket) -> tuple[int, bytes]:
        first, second = receive_exact(connection, 2)
        opcode = first & 0x0F
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", receive_exact(connection, 2))[0]
        elif length == 127:
            length = struct.unpack("!Q", receive_exact(connection, 8))[0]
        mask = receive_exact(connection, 4) if second & 0x80 else b""
        payload = bytearray(receive_exact(connection, length))
        if mask:
            for index in range(len(payload)):
                payload[index] ^= mask[index % 4]
        return opcode, bytes(payload)

    @staticmethod
    def send_frame(connection: socket.socket, opcode: int, payload: bytes = b"") -> None:
        header = bytearray([0x80 | opcode])
        if len(payload) < 126:
            header.append(len(payload))
        elif len(payload) <= 0xFFFF:
            header.extend((126, *struct.pack("!H", len(payload))))
        else:
            header.extend((127, *struct.pack("!Q", len(payload))))
        connection.sendall(header + payload)

    def handle(self, connection: socket.socket) -> None:
        request = bytearray()
        while b"\r\n\r\n" not in request:
            chunk = connection.recv(4096)
            if not chunk:
                raise ConnectionError("peer closed during WebSocket upgrade")
            request.extend(chunk)
            if len(request) > 65536:
                raise ValueError("oversized WebSocket upgrade request")
        headers: dict[str, str] = {}
        for line in request.decode("iso-8859-1").split("\r\n")[1:]:
            name, separator, value = line.partition(":")
            if separator:
                headers[name.strip().lower()] = value.strip()
        key = headers.get("sec-websocket-key", "")
        if not key:
            raise ValueError("missing Sec-WebSocket-Key")
        accept = base64.b64encode(hashlib.sha1(
            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
        ).digest()).decode("ascii")
        connection.sendall(
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n\r\n".encode("ascii")
        )
        self.connections += 1
        while not self._stop.is_set():
            opcode, payload = self.receive_frame(connection)
            if opcode == 8:
                self.send_frame(connection, 8, payload)
                return
            if opcode == 9:
                self.send_frame(connection, 10, payload)


class WebhookServer:
    def __init__(self, inject_faults: bool = True) -> None:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
                length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(length)
                try:
                    body = json.loads(raw_body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    owner.errors.append(f"invalid JSON body: {error}")
                    self.send_response(400)
                    self.end_headers()
                    return
                request_record = {
                    "path": self.path,
                    "headers": {name.lower(): value for name, value in self.headers.items()},
                    "body": body,
                    "receivedAtMonotonic": time.monotonic(),
                    "respondedAtMonotonic": 0.0,
                }
                owner.requests.append(request_record)
                event = str(body.get("event", ""))
                if owner.inject_faults and event == "alert.opened" and not owner.injected_retry:
                    owner.injected_retry = True
                    # A deliberately slow first target proves that another Sink has its own
                    # execution channel instead of waiting behind this response and retry.
                    time.sleep(0.75)
                    self.send_response(503)
                elif (owner.inject_faults and event == "alert.escalated" and
                      not owner.injected_nonretryable):
                    owner.injected_nonretryable = True
                    self.send_response(400)
                else:
                    self.send_response(204)
                self.end_headers()
                request_record["respondedAtMonotonic"] = time.monotonic()

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = int(self.server.server_address[1])
        self.requests: list[dict[str, object]] = []
        self.errors: list[str] = []
        self.injected_retry = False
        self.injected_nonretryable = False
        self.inject_faults = inject_faults
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        if self.thread.is_alive():
            self.errors.append("server thread did not stop")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-smoke", required=True, type=Path)
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--working-directory", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--install-bin", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--cycles", type=int, default=5)
    parser.add_argument("--startup-recovery-delay", type=float, default=1.0,
                        help="seconds allowed for the injected initial MQTT recovery")
    parser.add_argument("--cycle-action-delay", type=float, default=1.0,
                        help="seconds to monitor readiness after each MQTT or ROS restart action")
    parser.add_argument("--health-sample-interval", type=float, default=5.0,
                        help="readiness/resource sampling interval between restart actions")
    parser.add_argument("--stability-window", type=float, default=2.0,
                        help="final readiness observation window in seconds")
    parser.add_argument("--timeout", type=float,
                        help="overall runtime timeout; calculated from delays when omitted")
    parser.add_argument("--max-rss-growth-mib", type=float, default=32.0)
    parser.add_argument("--max-handle-growth", type=int, default=16)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if (args.cycles < 1 or args.startup_recovery_delay < 0 or
            args.cycle_action_delay < 0 or args.health_sample_interval <= 0 or
            args.stability_window < 0 or
            (args.timeout is not None and args.timeout <= 0) or
            args.max_rss_growth_mib < 0 or args.max_handle_growth < 0):
        raise SystemExit(
            "cycles must be positive; delays, stability window and resource limits must be "
            "non-negative; an explicit timeout must be positive"
        )
    minimum_timeout = (args.startup_recovery_delay +
                       2 * args.cycle_action_delay +
                       args.cycles * 2 * args.cycle_action_delay +
                       args.stability_window + 30)
    if args.timeout is not None and args.timeout < minimum_timeout:
        raise SystemExit(
            f"--timeout must be at least {minimum_timeout:g} seconds for the configured cycles"
        )
    timeout = args.timeout if args.timeout is not None else max(20.0, minimum_timeout)
    alert_history = args.report.with_suffix(".alerts.jsonl").resolve()
    management_audit = args.report.with_suffix(".management-audit.jsonl").resolve()
    management_audit_maximum_bytes = 32 * 1024
    management_tasks_path = args.report.with_suffix(".management-tasks.json").resolve()
    management_idempotency_path = args.report.with_suffix(
        ".management-idempotency.json").resolve()
    alert_history.parent.mkdir(parents=True, exist_ok=True)
    alert_history.unlink(missing_ok=True)
    management_audit.unlink(missing_ok=True)
    Path(str(management_audit) + ".1").unlink(missing_ok=True)
    management_tasks_path.unlink(missing_ok=True)
    Path(str(management_tasks_path) + ".new").unlink(missing_ok=True)
    management_idempotency_path.unlink(missing_ok=True)
    Path(str(management_idempotency_path) + ".new").unlink(missing_ok=True)
    mqtt = MqttServer()
    reload_probe_mqtt = MqttServer({1}, 4.0)
    ros = RosbridgeServer()
    webhook = WebhookServer()
    audit_webhook = WebhookServer(inject_faults=False)
    mqtt.start()
    reload_probe_mqtt.start()
    ros.start()
    webhook.start()
    audit_webhook.start()
    command = [
        sys.executable, str(args.runtime_smoke),
        "--executable", str(args.executable),
        "--working-directory", str(args.working_directory),
        "--config", str(args.config),
        "--timeout", str(timeout), "--stability-window", str(args.stability_window),
        "--clear-code-cache", "--post-delay", str(args.startup_recovery_delay),
        "--force-shutdown",
        "--post-interval", str(args.cycle_action_delay),
        "--post-health-interval", str(args.health_sample_interval),
        "--path", str(args.install_bin), "--path", str(args.working_directory),
        "--bearer-token-environment", "PDR_TEST_MANAGEMENT_TOKEN",
        "--endpoint", "/api/v1/protocols",
        "--endpoint", "/api/v1/topology",
        "--endpoint", "/api/v1/process-detail",
        "--endpoint", "/api/v1/process-config",
        "--endpoint", "/api/v1/management-audit?limit=1000",
        "--endpoint", "/api/v1/management-audit?operatorProbe",
        "--expect-status", "/api/v1/management-audit?operatorProbe=403",
        "--endpoint-bearer-token-environment",
        "/api/v1/management-audit?operatorProbe=PDR_TEST_OPERATOR_TOKEN",
        "--endpoint", "/api/v1/management-tasks?limit=100",
        "--endpoint", "/api/v1/management-tasks?operatorProbe",
        "--expect-status", "/api/v1/management-tasks?operatorProbe=403",
        "--endpoint-bearer-token-environment",
        "/api/v1/management-tasks?operatorProbe=PDR_TEST_OPERATOR_TOKEN",
        "--endpoint", "/api/v1/diagnostic-events",
        "--endpoint", "/api/v1/alerts",
        "--endpoint", "/api/v1/alert-history",
        "--endpoint", "/api/v1/alert-sinks",
        "--endpoint", "/api/v1/business-traces",
        "--endpoint", "/api/v1/metrics",
        "--endpoint", "/health/detail",
        "--set", "pdr.mqtt.count=2",
        "--set", "pdr.mqtt.0.id=runtime-mqtt",
        "--set", f"pdr.mqtt.0.serverUri=tcp://127.0.0.1:{mqtt.port}",
        "--set", "pdr.mqtt.0.clientId=pdr-runtime-integration",
        "--set", "pdr.mqtt.0.keepAliveSeconds=2",
        "--set", "pdr.mqtt.0.connectTimeoutSeconds=3",
        "--set", "pdr.mqtt.0.required=true",
        "--set", "pdr.mqtt.0.autoReconnect=true",
        "--set", "pdr.mqtt.0.reconnectDelayMilliseconds=700",
        "--set", "pdr.mqtt.0.reconnectMaximumDelayMilliseconds=1000",
        "--set", "pdr.mqtt.1.id=reload-probe",
        "--set", f"pdr.mqtt.1.serverUri=tcp://127.0.0.1:{reload_probe_mqtt.port}",
        "--set", "pdr.mqtt.1.clientId=pdr-alert-sink-reload-probe",
        "--set", "pdr.mqtt.1.keepAliveSeconds=2",
        "--set", "pdr.mqtt.1.connectTimeoutSeconds=3",
        "--set", "pdr.mqtt.1.required=false",
        "--set", "pdr.mqtt.1.autoReconnect=false",
        "--set", "pdr.ros.count=1",
        "--set", "pdr.ros.0.id=runtime-ros",
        "--set", f"pdr.ros.0.uri=ws://127.0.0.1:{ros.port}/",
        "--set", "pdr.ros.0.required=true",
        "--set", "pdr.management.manageableBundles=pdr.alert.*",
        "--set", "pdr.management.authentication.required=true",
        "--set", "pdr.management.authentication.tokenEnvironment=PDR_TEST_MANAGEMENT_TOKEN",
        "--set", "pdr.management.authentication.principals.count=1",
        "--set", "pdr.management.authentication.principals.0.id=protocol-operator",
        "--set", "pdr.management.authentication.principals.0.tokenEnvironment=PDR_TEST_OPERATOR_TOKEN",
        "--set", "pdr.management.authentication.principals.0.permissions=protocol.manage",
        "--set", "pdr.management.idempotency.requireRequestId=true",
        "--set", f"pdr.management.idempotency.persistence.path={management_idempotency_path.as_posix()}",
        "--set", f"pdr.management.audit.path={management_audit.as_posix()}",
        "--set", f"pdr.management.audit.maximumBytes={management_audit_maximum_bytes}",
        "--set", "pdr.management.tasks.workerCount=2",
        "--set", "pdr.management.tasks.health.degradedWaitMilliseconds=1",
        "--set", f"pdr.management.tasks.persistence.path={management_tasks_path.as_posix()}",
        "--set", "pdr.alerts.debounceMilliseconds=100",
        "--set", "pdr.alerts.escalationMilliseconds=300",
        "--set", f"pdr.alerts.history.path={alert_history.as_posix()}",
        "--set", "pdr.alerts.webhook.count=2",
        "--set", "pdr.alerts.webhook.0.id=primary-webhook",
        "--set", "pdr.alerts.webhook.0.enabled=true",
        "--set", "pdr.alerts.deliveryFailureThreshold=1",
        "--set", "pdr.alerts.deliveryCircuitOpenMilliseconds=100",
        "--set", f"pdr.alerts.webhook.0.url=http://127.0.0.1:{webhook.port}/alerts",
        "--set", "pdr.alerts.webhook.0.timeoutMilliseconds=1000",
        "--set", "pdr.alerts.webhook.0.maximumAttempts=3",
        "--set", "pdr.alerts.webhook.0.initialBackoffMilliseconds=50",
        "--set", "pdr.alerts.webhook.0.maximumBackoffMilliseconds=100",
        "--set", "pdr.alerts.webhook.0.authorizationEnvironment=PDR_TEST_WEBHOOK_AUTH",
        "--set", "pdr.alerts.webhook.1.id=audit-webhook",
        "--set", "pdr.alerts.webhook.1.enabled=true",
        "--set", f"pdr.alerts.webhook.1.url=http://127.0.0.1:{audit_webhook.port}/audit",
        "--set", "pdr.alerts.webhook.1.timeoutMilliseconds=1000",
        "--set", "pdr.alerts.webhook.1.maximumAttempts=1",
        "--set", "pdr.alerts.webhook.1.authorizationEnvironment=PDR_TEST_WEBHOOK_AUTH",
        "--require-log", "Protocol gateway started with 3 protocol instance",
        "--require-log", "Protocol runtime-mqtt recovered automatically",
        "--require-log", "diagnostic.event=failure.detected domain=protocol instance=runtime-mqtt error.code=PDR-PROTOCOL-MQTT-OPERATION_FAILED",
        "--require-log", "diagnostic.event=failure.resolved domain=protocol instance=runtime-mqtt error.code=PDR-PROTOCOL-MQTT-OPERATION_FAILED",
        "--require-log", "alert.event=alert.opened",
        "--require-log", "alert.event=alert.escalated",
        "--require-log", "alert.event=alert.resolved",
        "--require-body", "runtime-mqtt", "--require-body", "runtime-ros",
        "--require-body", "reload-probe",
        "--require-body", '"type":"mqtt"',
        "--require-body", '"type":"rosbridge"',
        "--require-body", '"open":true',
        "--require-body", '"action":"restart"',
        "--require-body", '"event":"failure.detected"',
        "--require-body", '"event":"failure.resolved"',
        "--require-body", '"businessName":"runtime.diagnostics"',
        "--require-body", '"businessName":"runtime.alerts"',
        "--require-body", '"status":"resolved"',
        "--require-body", '"severity":"critical"',
        "--require-body", '"debounceMilliseconds":100',
        "--require-body", '"event":"alert.resolved"',
        "--require-body", 'pdr.alert.delivery',
        "--require-body", 'https-webhook',
        "--require-body", 'local-history',
        "--require-body", 'primary-webhook',
        "--require-body", 'audit-webhook',
        "--require-body", '"status":"healthy"',
        "--require-body", '"consecutiveFailures":0',
        "--require-body", '"manageable":true,"name":"PocoDDS Alert Webhook"',
        "--require-body", '"manageable":false,"name":"PocoDDS System Monitoring"',
        "--require-body", '"validated":true',
        "--require-body", '"persisted":true',
        "--require-body", '"applied":true',
        "--require-body", '"rolledBack":false',
        "--require-body", '"rolledBack":true',
        "--require-body", 'configuration validation failed',
        "--require-body", 'pdr.modbus.port[^}]*502',
        "--require-body", '"rollbackFileAvailable":true',
        "--require-body", '"action":"rollback"',
        "--require-body", '配置已回退并生效',
        "--require-body", '管理操作需要有效的 Bearer 令牌',
        "--require-body", '"managementAuthenticationRequired":true',
        "--require-body", '"managementSession":{"authenticated":true',
        "--require-body", '"principal":"legacy-admin"',
        "--require-body", '"configuration.manage"',
        "--require-body", '"operation":"protocol-lifecycle"',
        "--require-body", '"status":"succeeded"',
        "--require-body", '"status":"denied"',
        "--require-body", '"status":"replayed"',
        "--require-body", '"durationMicroseconds"',
        "--require-body", '"state":"queued"',
        "--require-body", '"state":"succeeded"',
        "--require-body", '"state":"cancelled"',
        "--require-body", '"state":"timed-out"',
        "--require-body", '"phase":"cancellation-requested"',
        "--require-body", '"phaseBeforeCancellation":"waiting-resource"',
        "--require-body", '"cancellationMode":"cooperative"',
        "--require-body", '"resourceKey":"protocol-lifecycle:runtime-mqtt"',
        "--require-body", '"blockingTaskId":"management-task-',
        "--require-body", '"scheduler":{',
        "--require-body", 'pdr.management.tasks.queue.depth',
        "--require-body", 'pdr.management.tasks.workers.active',
        "--require-body", 'PDR-HEALTH-MANAGEMENT-TASK-WAIT_EXCESSIVE',
        "--require-body", '管理写操作需要 X-PDR-Request-Id',
        "--require-body", '当前管理身份没有执行该操作的权限',
        "--require-body", '"idempotentReplay":true',
        "--require-body", 'X-PDR-Request-Id 已用于不同的管理操作',
        "--require-body", '"audited":true',
        "--require-body", '"status":"committed"',
        "--require-body", '"status":"rejected"',
        "--require-body", '"status":"rolled-back"',
        "--forbid-body", 'previousValue',
        "--forbid-body", 'currentValue',
        "--report", str(args.report),
        "--sample-resources", "--max-rss-growth-mib", str(args.max_rss_growth_mib),
        "--max-handle-growth", str(args.max_handle_growth),
        "--resource-baseline-after-post", "2",
    ]
    command.extend([
        "--post", '/api/v1/bundle-lifecycle={"id":"pdr.alert.webhook","action":"restart"}',
        "--post-response-status", "1=401",
        "--post-omit-bearer", "1",
        "--post", '/api/v1/bundle-lifecycle={"id":"pdr.alert.webhook","action":"restart"}',
        "--post-response-status", "2=401",
        "--post-bearer-token-environment", "2=PDR_TEST_WRONG_MANAGEMENT_TOKEN",
        "--post", '/api/v1/bundle-lifecycle={"id":"pdr.alert.webhook","action":"restart"}',
        "--post-response-status", "3=428",
        "--post-omit-request-id", "3",
        "--post", '/api/v1/bundle-lifecycle={"id":"pdr.alert.webhook","action":"restart"}',
        "--post", '/api/v1/bundle-lifecycle={"id":"pdr.platform.systemMonitoring","action":"restart"}',
        "--post-response-status", "5=403",
    ])
    for _ in range(args.cycles):
        command.extend([
            "--post", '/api/v1/protocols={"id":"runtime-mqtt","action":"restart"}',
            "--post", '/api/v1/protocols={"id":"runtime-ros","action":"restart"}',
        ])
    configuration_post_index = 5 + args.cycles * 2 + 1
    command.extend([
        "--post", '/api/v1/process-config={"key":"logging.loggers.root.level","value":"debug"}',
        "--post", '/api/v1/process-config={"key":"logging.loggers.root.level","value":"verbose"}',
        "--post-response-status", f"{configuration_post_index + 1}=400",
        "--post", '/api/v1/process-config={"key":"logging.loggers.root.level","value":"information"}',
        "--post", '/api/v1/process-config={"key":"pdr.modbus.port","value":"503"}',
        "--post-response-status", f"{configuration_post_index + 3}=409",
        "--post", '/api/v1/process-config={"action":"rollback","transactionId":"${lastCommittedTransactionId}"}',
        "--post", '/api/v1/process-config={"key":"logging.loggers.root.level","value":"information"}',
        "--post", '/api/v1/process-config={"action":"rollback","transactionId":"stale-transaction"}',
        "--post-response-status", f"{configuration_post_index + 6}=409",
        "--post", '/api/v1/protocols={"id":"runtime-mqtt","action":"restart"}',
        "--post-response-status", f"{configuration_post_index + 7}=401",
        "--post-omit-bearer", str(configuration_post_index + 7),
        "--post", '/api/v1/process-lifecycle={"id":"not-authorized","action":"restart"}',
        "--post-response-status", f"{configuration_post_index + 8}=401",
        "--post-omit-bearer", str(configuration_post_index + 8),
        "--post", '/api/v1/process-config={"key":"logging.loggers.root.level","value":"debug"}',
        "--post-response-status", f"{configuration_post_index + 9}=401",
        "--post-omit-bearer", str(configuration_post_index + 9),
        "--post", '/api/v1/protocols={"id":"runtime-mqtt","action":"restart"}',
        "--post-bearer-token-environment", f"{configuration_post_index + 10}=PDR_TEST_OPERATOR_TOKEN",
        "--post-request-id", f"{configuration_post_index + 10}=operator-allowed-proof",
        "--post", '/api/v1/process-config={"key":"logging.loggers.root.level","value":"debug"}',
        "--post-response-status", f"{configuration_post_index + 11}=403",
        "--post-bearer-token-environment", f"{configuration_post_index + 11}=PDR_TEST_OPERATOR_TOKEN",
        "--post-request-id", f"{configuration_post_index + 11}=operator-denied-proof",
        "--post", '/api/v1/protocols={"id":"runtime-mqtt","action":"restart"}',
        "--post-request-id", f"{configuration_post_index + 12}=configuration-replay-proof",
        "--post", '/api/v1/protocols={"id":"runtime-mqtt","action":"restart"}',
        "--post-request-id", f"{configuration_post_index + 13}=configuration-replay-proof",
        "--post", '/api/v1/protocols={"id":"runtime-mqtt","action":"stop"}',
        "--post-request-id", f"{configuration_post_index + 14}=configuration-replay-proof",
        "--post-response-status", f"{configuration_post_index + 14}=409",
        "--post", '/api/v1/bundle-lifecycle={"id":"pdr.alert.webhook","action":"start","async":true,"startTimeoutMilliseconds":30000}',
        "--post-response-status", f"{configuration_post_index + 15}=202",
        "--post-request-id", f"{configuration_post_index + 15}=async-task-running-proof",
        "--post-interval-override", f"{configuration_post_index + 15}=1",
        "--post", '/api/v1/bundle-lifecycle={"id":"pdr.alert.webhook","action":"start","async":true,"startTimeoutMilliseconds":30000,"notBeforeMilliseconds":3000}',
        "--post-response-status", f"{configuration_post_index + 16}=202",
        "--post-request-id", f"{configuration_post_index + 16}=async-task-delay-proof",
        "--post-interval-override", f"{configuration_post_index + 16}=0",
        "--post", '/api/v1/protocols={"id":"runtime-mqtt","action":"open","async":true,"startTimeoutMilliseconds":30000,"executionTimeoutMilliseconds":10000,"stabilityWindowMilliseconds":3000}',
        "--post-response-status", f"{configuration_post_index + 17}=202",
        "--post-request-id", f"{configuration_post_index + 17}=async-task-timeout-owner-proof",
        "--post-interval-override", f"{configuration_post_index + 17}=0.25",
        "--post", '/api/v1/protocols={"id":"runtime-ros","action":"open","async":true,"startTimeoutMilliseconds":30000,"executionTimeoutMilliseconds":10000,"stabilityWindowMilliseconds":2000}',
        "--post-response-status", f"{configuration_post_index + 18}=202",
        "--post-request-id", f"{configuration_post_index + 18}=async-task-timeout-peer-proof",
        "--post-interval-override", f"{configuration_post_index + 18}=0.25",
        "--post", '/api/v1/bundle-lifecycle={"id":"pdr.alert.webhook","action":"start","async":true,"startTimeoutMilliseconds":1}',
        "--post-response-status", f"{configuration_post_index + 19}=202",
        "--post-request-id", f"{configuration_post_index + 19}=async-task-timeout-proof",
        "--post-interval-override", f"{configuration_post_index + 19}=0",
        "--post", '/api/v1/bundle-lifecycle={"id":"pdr.alert.webhook","action":"start","async":true,"startTimeoutMilliseconds":30000}',
        "--post-response-status", f"{configuration_post_index + 20}=202",
        "--post-request-id", f"{configuration_post_index + 20}=async-task-ready-bypass-proof",
        "--post-interval-override", f"{configuration_post_index + 20}=0.5",
        "--post-expect-status", f"{configuration_post_index + 20}:/health/ready=503",
        "--post", '/api/v1/bundle-lifecycle={"id":"pdr.alert.webhook","action":"start","async":true,"startTimeoutMilliseconds":30000,"notBeforeMilliseconds":5000}',
        "--post-response-status", f"{configuration_post_index + 21}=202",
        "--post-request-id", f"{configuration_post_index + 21}=async-task-cancel-proof",
        "--post-interval-override", f"{configuration_post_index + 21}=0",
        "--post", '/api/v1/management-tasks={"id":"${lastManagementTaskId}","action":"cancel"}',
        "--post-request-id", f"{configuration_post_index + 22}=async-task-cancel-request",
        "--post-interval-override", f"{configuration_post_index + 22}=5",
        "--post-expect-status", f"{configuration_post_index + 22}:/health/ready=503",
        "--post", '/api/v1/protocols={"id":"runtime-mqtt","action":"restart","async":true,"startTimeoutMilliseconds":30000,"executionTimeoutMilliseconds":1}',
        "--post-response-status", f"{configuration_post_index + 23}=202",
        "--post-request-id", f"{configuration_post_index + 23}=async-task-execution-timeout-proof",
        "--post-interval-override", f"{configuration_post_index + 23}=1",
        "--post", '/api/v1/protocols={"id":"runtime-mqtt","action":"open","async":true,"startTimeoutMilliseconds":30000,"executionTimeoutMilliseconds":10000,"stabilityWindowMilliseconds":3000}',
        "--post-response-status", f"{configuration_post_index + 24}=202",
        "--post-request-id", f"{configuration_post_index + 24}=async-task-resource-owner-proof",
        "--post-interval-override", f"{configuration_post_index + 24}=0.25",
        "--post", '/api/v1/protocols={"id":"runtime-ros","action":"open","async":true,"startTimeoutMilliseconds":30000,"executionTimeoutMilliseconds":10000}',
        "--post-response-status", f"{configuration_post_index + 25}=202",
        "--post-request-id", f"{configuration_post_index + 25}=async-task-parallel-resource-proof",
        "--post-interval-override", f"{configuration_post_index + 25}=0.25",
        "--post", '/api/v1/protocols={"id":"runtime-mqtt","action":"open","async":true,"startTimeoutMilliseconds":30000,"executionTimeoutMilliseconds":10000}',
        "--post-response-status", f"{configuration_post_index + 26}=202",
        "--post-request-id", f"{configuration_post_index + 26}=async-task-running-cancel-proof",
        "--post-interval-override", f"{configuration_post_index + 26}=0.25",
        "--post-expect-status", f"{configuration_post_index + 26}:/health/ready=503",
        "--post", '/api/v1/management-tasks={"id":"${lastManagementTaskId}","action":"cancel"}',
        "--post-response-status", f"{configuration_post_index + 27}=202",
        "--post-request-id", f"{configuration_post_index + 27}=async-task-running-cancel-request",
        "--post-interval-override", f"{configuration_post_index + 27}=4",
        "--post", '/api/v1/bundle-lifecycle={"id":"pdr.alert.webhook","action":"start"}',
        "--post-request-id", f"{configuration_post_index + 28}=async-task-final-observation",
        "--post-interval-override", f"{configuration_post_index + 28}=6",
        "--post", '/api/v1/bundle-lifecycle={"id":"pdr.alert.webhook","action":"start","async":true,"startTimeoutMilliseconds":120000,"notBeforeMilliseconds":60000}',
        "--post-response-status", f"{configuration_post_index + 29}=202",
        "--post-request-id", f"{configuration_post_index + 29}=async-task-interrupted-proof",
        "--post-interval-override", f"{configuration_post_index + 29}=0",
    ])
    runtime_environment = os.environ.copy()
    runtime_environment["PDR_TEST_WEBHOOK_AUTH"] = "Bearer pdr-webhook-test"
    runtime_environment["PDR_TEST_MANAGEMENT_TOKEN"] = "pdr-correct-management-token"
    runtime_environment["PDR_TEST_WRONG_MANAGEMENT_TOKEN"] = "pdr-wrong-management-token"
    runtime_environment["PDR_TEST_OPERATOR_TOKEN"] = "pdr-protocol-operator-token"
    completed = subprocess.run(
        command, text=True, capture_output=True, check=False, env=runtime_environment
    )
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    if management_idempotency_path.exists():
        ledger_fixture = json.loads(management_idempotency_path.read_text(encoding="utf-8"))
        interrupted_source = next(
            (entry for entry in ledger_fixture.get("requests", [])
             if entry.get("operation") == "protocol-lifecycle" and
             entry.get("target") == "runtime-ros" and entry.get("action") == "restart"),
            None,
        )
        if interrupted_source:
            interrupted_fixture = dict(interrupted_source)
            interrupted_fixture.update({
                "requestId": "idempotency-interrupted-proof",
                "state": "in-progress",
                "updatedMicroseconds": int(time.time() * 1_000_000),
            })
            ledger_fixture.setdefault("requests", []).append(interrupted_fixture)
            serialized_requests = json.dumps(
                ledger_fixture["requests"], separators=(",", ":"),
                ensure_ascii=False, sort_keys=True,
            )
            ledger_fixture["contentSha256"] = hashlib.sha256(
                serialized_requests.encode("utf-8")).hexdigest()
            staged_ledger = Path(str(management_idempotency_path) + ".fixture")
            staged_ledger.write_text(
                json.dumps(ledger_fixture, separators=(",", ":"), ensure_ascii=False),
                encoding="utf-8", newline="\n",
            )
            staged_ledger.replace(management_idempotency_path)
    restart_report = args.report.with_name(args.report.stem + "-restart.json")
    restart_command = [
        sys.executable, str(args.runtime_smoke),
        "--executable", str(args.executable),
        "--working-directory", str(args.working_directory),
        "--config", str(args.config),
        "--timeout", "15", "--stability-window", "2", "--clear-code-cache",
        "--path", str(args.install_bin), "--path", str(args.working_directory),
        "--endpoint", "/api/v1/alert-history",
        "--endpoint", "/api/v1/management-tasks?limit=100",
        "--set", "pdr.mqtt.count=0", "--set", "pdr.ros.count=0",
        "--set", "pdr.management.authentication.required=true",
        "--set", "pdr.management.authentication.tokenEnvironment=PDR_TEST_MANAGEMENT_TOKEN",
        "--set", "pdr.management.idempotency.requireRequestId=true",
        "--set", f"pdr.management.idempotency.persistence.path={management_idempotency_path.as_posix()}",
        "--set", f"pdr.management.tasks.persistence.path={management_tasks_path.as_posix()}",
        "--bearer-token-environment", "PDR_TEST_MANAGEMENT_TOKEN",
        "--set", f"pdr.alerts.history.path={alert_history.as_posix()}",
        "--require-body", "PDR-PROTOCOL-MQTT-OPERATION_FAILED",
        "--require-body", "alert.resolved",
        "--require-body", '"state":"interrupted"',
        "--require-body", '"interruptedFromState":"queued"',
        "--require-body", '"recoveryPolicy":"verify-before-retry"',
        "--require-body", '"persistence":\\{[^}]*"healthy":true[^}]*"recoveryRequired":false',
        "--require-body", '"idempotency":{"completed":',
        "--require-body", '"interrupted":1',
        "--require-body", '"idempotentReplay":true',
        "--require-body", 'X-PDR-Request-Id 已用于不同的管理操作',
        "--post", '/api/v1/protocols={"id":"runtime-mqtt","action":"restart"}',
        "--post-request-id", "1=configuration-replay-proof",
        "--post", '/api/v1/protocols={"id":"runtime-mqtt","action":"stop"}',
        "--post-request-id", "2=configuration-replay-proof",
        "--post-response-status", "2=409",
        "--post", '/api/v1/protocols={"id":"runtime-ros","action":"restart"}',
        "--post-request-id", "3=idempotency-interrupted-proof",
        "--post-response-status", "3=409",
        "--report", str(restart_report),
    ]
    restarted = subprocess.run(
        restart_command, text=True, capture_output=True, check=False, env=runtime_environment
    )
    if restarted.stdout:
        print(restarted.stdout, end="")
    if restarted.stderr:
        print(restarted.stderr, end="", file=sys.stderr)
    time.sleep(0.2)
    mqtt.stop()
    reload_probe_mqtt.stop()
    ros.stop()
    webhook.stop()
    audit_webhook.stop()

    result = json.loads(args.report.read_text(encoding="utf-8")) if args.report.exists() else {}
    restart_result = (json.loads(restart_report.read_text(encoding="utf-8"))
                      if restart_report.exists() else {})
    result["testServers"] = {
        "mqtt": {"port": mqtt.port, "connections": mqtt.connections,
                 "transportClosures": mqtt.transport_closures, "errors": mqtt.errors},
        "reloadProbeMqtt": {"port": reload_probe_mqtt.port,
                            "connections": reload_probe_mqtt.connections,
                            "transportClosures": reload_probe_mqtt.transport_closures,
                            "errors": reload_probe_mqtt.errors},
        "rosbridge": {"port": ros.port, "connections": ros.connections,
                      "transportClosures": ros.transport_closures, "errors": ros.errors},
        "webhook": {"port": webhook.port, "requestCount": len(webhook.requests),
                    "injectedRetry": webhook.injected_retry,
                    "injectedNonRetryable": webhook.injected_nonretryable,
                    "errors": webhook.errors},
        "auditWebhook": {"port": audit_webhook.port,
                         "requestCount": len(audit_webhook.requests),
                         "errors": audit_webhook.errors},
    }
    result["recoveryCycles"] = args.cycles
    result["startupRecoveryDelaySeconds"] = args.startup_recovery_delay
    result["cycleActionDelaySeconds"] = args.cycle_action_delay
    result["healthSampleIntervalSeconds"] = args.health_sample_interval
    result["configuredTimeoutSeconds"] = timeout
    result["alertHistoryPath"] = str(alert_history)
    result["restartHistoryReport"] = str(restart_report)
    result["restartHistoryPassed"] = restarted.returncode == 0
    result["resourceLimits"] = {
        "maxRssGrowthMiB": args.max_rss_growth_mib,
        "maxHandleGrowth": args.max_handle_growth,
    }
    observations_per_action = (
        math.ceil(args.cycle_action_delay / args.health_sample_interval)
        if args.cycle_action_delay > 0 else 0
    )
    expected_resource_samples = 2 + (2 + args.cycles * 2) * (1 + observations_per_action)
    observed_resource_samples = len(result.get("resourceSamples", []))
    result["expectedMinimumResourceSamples"] = expected_resource_samples
    result["observedResourceSamples"] = observed_resource_samples
    webhook_events = [str(request["body"].get("event", ""))
                      for request in webhook.requests]
    opened_requests = [request for request in webhook.requests
                       if request["body"].get("event") == "alert.opened"]
    webhook_headers_valid = all(
        request["path"] == "/alerts" and
        request["headers"].get("authorization") == "Bearer pdr-webhook-test" and
        request["headers"].get("content-type", "").startswith("application/json") and
        request["headers"].get("idempotency-key") and
        request["headers"].get("x-pdr-alert-id") == request["body"].get("alertId") and
        request["headers"].get("x-pdr-trace-id") == request["body"].get("traceId") and
        request["body"].get("schemaVersion") == 1
        for request in webhook.requests
    )
    webhook_retry_stable = (
        len(opened_requests) >= 2 and
        opened_requests[0]["headers"].get("idempotency-key") ==
        opened_requests[1]["headers"].get("idempotency-key")
    )
    final_webhook_status: dict[str, object] = {}
    final_audit_status: dict[str, object] = {}
    final_sink_inventory: dict[str, object] = {}
    for probe_result in result.get("probes", []):
        if probe_result.get("endpoint") != "/api/v1/alert-sinks":
            continue
        try:
            inventory = json.loads(str(probe_result.get("body", "{}")))
            final_sink_inventory = inventory
            for sink in inventory.get("sinks", []):
                if (sink.get("name") == "primary-webhook" and
                        sink.get("successes", 0) >= final_webhook_status.get("successes", 0)):
                    final_webhook_status = sink
                elif (sink.get("name") == "audit-webhook" and
                      sink.get("successes", 0) >= final_audit_status.get("successes", 0)):
                    final_audit_status = sink
        except json.JSONDecodeError:
            pass
    circuit_recovered = (
        webhook.injected_nonretryable and
        "alert.resolved" in webhook_events and
        final_webhook_status.get("status") == "healthy" and
        final_webhook_status.get("successes", 0) >= 2 and
        final_webhook_status.get("consecutiveFailures", -1) == 0 and
        final_webhook_status.get("circuitOpen") is False
    )
    audit_events = [str(request["body"].get("event", ""))
                    for request in audit_webhook.requests]
    first_primary_opened = next((request for request in webhook.requests
                                 if request["body"].get("event") == "alert.opened"), {})
    first_audit_opened = next((request for request in audit_webhook.requests
                               if request["body"].get("event") == "alert.opened"), {})
    slow_sink_isolated = (
        float(first_audit_opened.get("receivedAtMonotonic", float("inf"))) <
        float(first_primary_opened.get("respondedAtMonotonic", 0.0))
    )
    runtime_log = args.report.with_suffix(".log")
    runtime_log_text = (runtime_log.read_text(encoding="utf-8", errors="replace")
                        if runtime_log.exists() else "")
    management_audit_archive = Path(str(management_audit) + ".1")
    management_audit_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in (management_audit_archive, management_audit)
        if path.exists()
    )
    management_audit_events = []
    for probe_result in result.get("probes", []):
        if not str(probe_result.get("endpoint", "")).startswith(
                "/api/v1/management-audit") or probe_result.get("status") != 200:
            continue
        try:
            inventory = json.loads(str(probe_result.get("body", "{}")))
            management_audit_events.extend(inventory.get("events", []))
        except json.JSONDecodeError:
            pass
    for line in management_audit_text.splitlines():
        try:
            management_audit_events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    management_audit_events = list({
        str(event.get("eventId")): event for event in management_audit_events
        if event.get("eventId")
    }.values())
    sink_registration_count = runtime_log_text.count(
        "Alert webhook sink registered: 2 instance(s)."
    )
    core_protection_passed = any(
        probe.get("method") == "POST" and
        probe.get("endpoint") == "/api/v1/bundle-lifecycle" and
        probe.get("status") == 403
        for probe in result.get("probes", [])
    )
    management_lifecycle_statuses = [
        probe.get("status") for probe in result.get("probes", [])
        if probe.get("method") == "POST" and
        probe.get("endpoint") == "/api/v1/bundle-lifecycle"
    ]
    management_secrets_absent = all(
        secret not in runtime_log_text and secret not in management_audit_text and
        secret not in json.dumps(result)
        for secret in ("pdr-correct-management-token", "pdr-wrong-management-token",
                       "pdr-protocol-operator-token")
    )
    management_authentication_passed = (
        management_lifecycle_statuses[:5] == [401, 401, 428, 200, 403] and
        all(any(
            probe.get("method") == "POST" and probe.get("endpoint") == endpoint and
            probe.get("status") == 401
            for probe in result.get("probes", []))
            for endpoint in ("/api/v1/protocols", "/api/v1/process-lifecycle",
                             "/api/v1/process-config")) and
        management_secrets_absent
    )
    management_least_privilege_passed = (
        any(probe.get("method") == "POST" and
            probe.get("endpoint") == "/api/v1/protocols" and
            probe.get("status") == 200 and
            "operator-allowed-proof" in str(probe.get("body", ""))
            for probe in result.get("probes", [])) and
        any(probe.get("method") == "POST" and
            probe.get("endpoint") == "/api/v1/process-config" and
            probe.get("status") == 403 and
            "没有执行该操作的权限" in str(probe.get("body", ""))
            for probe in result.get("probes", []))
    )
    idempotency_responses = []
    for probe in result.get("probes", []):
        if probe.get("method") != "POST":
            continue
        try:
            response = json.loads(str(probe.get("body", "{}")))
        except json.JSONDecodeError:
            continue
        if response.get("requestId") == "configuration-replay-proof":
            idempotency_responses.append((probe.get("status"), response))
    idempotency_conflict = any(
        probe.get("method") == "POST" and
        probe.get("endpoint") == "/api/v1/protocols" and
        probe.get("status") == 409 and
        "X-PDR-Request-Id" in str(probe.get("body", ""))
        for probe in result.get("probes", [])
    )
    management_idempotency_passed = (
        len(idempotency_responses) == 2 and
        idempotency_responses[0][0] == 200 and
        idempotency_responses[0][1].get("idempotentReplay") is False and
        idempotency_responses[1][0] == 200 and
        idempotency_responses[1][1].get("idempotentReplay") is True and
        idempotency_conflict
    )
    restart_replay = any(
        probe.get("method") == "POST" and
        probe.get("endpoint") == "/api/v1/protocols" and
        probe.get("status") == 200 and
        json.loads(str(probe.get("body", "{}"))).get("idempotentReplay") is True
        for probe in restart_result.get("probes", [])
        if str(probe.get("body", "{}")).startswith("{")
    )
    restart_conflict = any(
        probe.get("method") == "POST" and
        probe.get("endpoint") == "/api/v1/protocols" and
        probe.get("status") == 409 and
        "X-PDR-Request-Id" in str(probe.get("body", ""))
        for probe in restart_result.get("probes", [])
    )
    restart_interrupted_rejected = any(
        probe.get("method") == "POST" and
        probe.get("endpoint") == "/api/v1/protocols" and
        probe.get("status") == 409 and
        "先核对目标状态" in str(probe.get("body", ""))
        for probe in restart_result.get("probes", [])
    )
    ledger_text = (management_idempotency_path.read_text(encoding="utf-8")
                   if management_idempotency_path.exists() else "")
    management_idempotency_persistence_passed = (
        restart_replay and restart_conflict and restart_interrupted_rejected and
        '"fingerprintSha256"' in ledger_text and
        '/api/v1/protocols|' not in ledger_text and
        '"value":"debug"' not in ledger_text and
        all(secret not in ledger_text for secret in (
            "pdr-correct-management-token", "pdr-wrong-management-token",
            "pdr-protocol-operator-token"))
    )
    management_tasks = {}
    async_acceptances = []
    for probe in result.get("probes", []):
        try:
            payload = json.loads(str(probe.get("body", "{}")))
        except json.JSONDecodeError:
            continue
        task = payload.get("task")
        if isinstance(task, dict) and task.get("id"):
            management_tasks[str(task["id"])] = task
            if (probe.get("status") == 202 and
                    probe.get("endpoint") != "/api/v1/management-tasks"):
                async_acceptances.append(task)
        for listed in payload.get("tasks", []) if isinstance(payload, dict) else []:
            if isinstance(listed, dict) and listed.get("id"):
                management_tasks[str(listed["id"])] = listed
    if management_tasks_path.exists():
        try:
            for persisted in json.loads(
                    management_tasks_path.read_text(encoding="utf-8")).get("tasks", []):
                if isinstance(persisted, dict) and persisted.get("id"):
                    management_tasks[str(persisted["id"])] = persisted
        except json.JSONDecodeError:
            pass
    management_tasks_passed = (
        len(async_acceptances) == 12 and
        all(task.get("state") == "queued" for task in async_acceptances) and
        any(task.get("requestId") == "async-task-running-proof" and
            task.get("state") == "succeeded" for task in management_tasks.values()) and
        any(task.get("requestId") == "async-task-cancel-proof" and
            task.get("state") == "cancelled" and
            task.get("cancellationRequested") is True
            for task in management_tasks.values()) and
        any(task.get("requestId") == "async-task-timeout-proof" and
            task.get("state") == "timed-out" and task.get("startedMicroseconds") == 0
            for task in management_tasks.values()) and
        any(task.get("requestId") == "async-task-ready-bypass-proof" and
            task.get("state") == "succeeded" and
            task.get("finishedMicroseconds", 0) > 0 and
            task.get("finishedMicroseconds", 0) < delayed.get("startedMicroseconds", 0)
            for task in management_tasks.values()
            for delayed in management_tasks.values()
            if delayed.get("requestId") == "async-task-delay-proof") and
        any(task.get("requestId") == "async-task-execution-timeout-proof" and
            task.get("state") == "timed-out" and
            task.get("startedMicroseconds", 0) > 0 and
            "execution deadline" in str(task.get("error", ""))
            for task in management_tasks.values()) and
        any(task.get("requestId") == "async-task-running-cancel-proof" and
            task.get("state") == "cancelled" and
            task.get("startedMicroseconds", 0) > 0 and
            task.get("cancellationRequested") is True and
            task.get("cancellationMode") == "cooperative" and
            task.get("phaseBeforeCancellation") == "waiting-resource" and
            task.get("blockingTaskId") and
            task.get("resourceWaitStartedMicroseconds", 0) > 0 and
            task.get("resourceAcquiredMicroseconds") == 0 and
            task.get("resourceWaitMicroseconds", 0) > 0
            for task in management_tasks.values()) and
        any(task.get("requestId") == "async-task-resource-owner-proof" and
            task.get("state") == "succeeded" and
            task.get("resourceAcquiredMicroseconds", 0) > 0
            for task in management_tasks.values()) and
        any(task.get("requestId") == "async-task-parallel-resource-proof" and
            task.get("state") == "succeeded" and
            task.get("finishedMicroseconds", 0) > 0 and
            task.get("finishedMicroseconds", 0) < owner.get("finishedMicroseconds", 0)
            for task in management_tasks.values()
            for owner in management_tasks.values()
            if owner.get("requestId") == "async-task-resource-owner-proof") and
        any(probe.get("endpoint") == "/api/v1/management-tasks" and
            probe.get("status") == 202 and
            '"phase":"cancellation-requested"' in str(probe.get("body", ""))
            for probe in result.get("probes", [])) and
        any(probe.get("endpoint") == "/api/v1/management-tasks?operatorProbe" and
            probe.get("status") == 403 and
            "没有执行该操作的权限" in str(probe.get("body", ""))
            for probe in result.get("probes", []))
    )
    recovered_tasks = []
    if management_tasks_path.exists():
        try:
            recovered_tasks = json.loads(
                management_tasks_path.read_text(encoding="utf-8")).get("tasks", [])
        except json.JSONDecodeError:
            pass
    management_task_recovery_passed = (
        any(task.get("requestId") == "async-task-interrupted-proof" and
            task.get("state") == "interrupted" and
            task.get("interruptedFromState") == "queued" and
            task.get("recoveryPolicy") == "verify-before-retry"
            for task in recovered_tasks)
    )
    audited_operations = {str(event.get("operation", ""))
                          for event in management_audit_events}
    audited_statuses = {str(event.get("status", ""))
                        for event in management_audit_events}
    management_audit_passed = (
        {"protocol-lifecycle", "process-lifecycle", "bundle-lifecycle",
         "configuration", "management-audit-read"}.issubset(audited_operations) and
        {"succeeded", "denied", "replayed"}.issubset(audited_statuses) and
        all(event.get("schemaVersion") == 1 and event.get("eventId") and
            isinstance(event.get("durationMicroseconds"), int) and
            event.get("httpStatus")
            for event in management_audit_events) and
        any(event.get("principal") == "protocol-operator" and
            event.get("status") == "succeeded"
            for event in management_audit_events) and
        any(event.get("principal") == "protocol-operator" and
            event.get("operation") == "management-audit-read" and
            event.get("status") == "denied" and event.get("httpStatus") == 403
            for event in management_audit_events)
        and management_audit_archive.exists()
        and management_audit.exists() and
        management_audit.stat().st_size <= management_audit_maximum_bytes
    )
    sink_hot_reload_passed = (
        sink_registration_count >= 2 and core_protection_passed and
        webhook_events.count("alert.opened") >= 3 and
        webhook_events.count("alert.escalated") >= 2 and
        webhook_events.count("alert.resolved") >= 1 and
        audit_events.count("alert.opened") >= 2 and
        audit_events.count("alert.escalated") >= 2 and
        audit_events.count("alert.resolved") >= 1 and
        final_sink_inventory.get("count") == 3 and
        final_webhook_status.get("queueDepth") == 0 and
        final_webhook_status.get("status") == "healthy" and
        final_webhook_status.get("successes", 0) >= 2 and
        final_audit_status.get("status") == "healthy" and
        final_audit_status.get("successes", 0) >= 2 and
        final_audit_status.get("queueDepth") == 0
    )
    audit_webhook_passed = (
        not audit_webhook.errors and
        {"alert.opened", "alert.escalated", "alert.resolved"}.issubset(audit_events) and
        all(request["path"] == "/audit" for request in audit_webhook.requests) and
        slow_sink_isolated and sink_hot_reload_passed
    )
    webhook_passed = (
        webhook.injected_retry and not webhook.errors and webhook_headers_valid and
        webhook_retry_stable and circuit_recovered and audit_webhook_passed and
        {"alert.opened", "alert.escalated", "alert.resolved"}.issubset(webhook_events)
    )
    result["webhookVerification"] = {
        "events": webhook_events,
        "headersValid": webhook_headers_valid,
        "retryIdempotencyKeyStable": webhook_retry_stable,
        "circuitRecovered": circuit_recovered,
        "finalSinkStatus": final_webhook_status,
        "finalAuditSinkStatus": final_audit_status,
        "auditEvents": audit_events,
        "slowSinkIsolated": slow_sink_isolated,
        "sinkRegistrationCount": sink_registration_count,
        "coreProtectionPassed": core_protection_passed,
        "managementAuthenticationPassed": management_authentication_passed,
        "managementIdempotencyPassed": management_idempotency_passed,
        "managementIdempotencyPersistencePassed": management_idempotency_persistence_passed,
        "managementLeastPrivilegePassed": management_least_privilege_passed,
        "managementAuditPassed": management_audit_passed,
        "managementAuditEventCount": len(management_audit_events),
        "managementTasksPassed": management_tasks_passed,
        "managementTaskCount": len(management_tasks),
        "managementTaskRecoveryPassed": management_task_recovery_passed,
        "managementSecretsAbsent": management_secrets_absent,
        "sinkHotReloadPassed": sink_hot_reload_passed,
        "auditWebhookPassed": audit_webhook_passed,
        "passed": webhook_passed,
    }
    servers_passed = (
        mqtt.connections >= args.cycles + 2 and ros.connections >= args.cycles + 1 and
        reload_probe_mqtt.connections >= 1 and
        not mqtt.errors and not reload_probe_mqtt.errors and not ros.errors and webhook_passed and
        management_authentication_passed and
        management_idempotency_passed and
        management_idempotency_persistence_passed and
        management_least_privilege_passed and
        management_audit_passed and
        management_tasks_passed and
        management_task_recovery_passed and
        observed_resource_samples >= expected_resource_samples
    )
    result["passed"] = completed.returncode == 0 and restarted.returncode == 0 and servers_passed
    if not servers_passed:
        result["integrationError"] = (
            "protocol servers or resource sampler did not observe the configured recovery soak"
        )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    if not result["passed"]:
        print(
            "RUNTIME_PROTOCOL_GATEWAY_INTEGRATION_FAIL "
            f"mqttConnections={mqtt.connections} rosConnections={ros.connections} "
            f"resourceSamples={observed_resource_samples}/{expected_resource_samples} "
            f"webhook={webhook_passed} managementTasks={management_tasks_passed} "
            f"taskRecovery={management_task_recovery_passed} audit={management_audit_passed}",
            file=sys.stderr,
        )
        return 1
    print(
        "RUNTIME_PROTOCOL_GATEWAY_INTEGRATION_PASS "
        f"mqttConnections={mqtt.connections} rosConnections={ros.connections} "
        f"webhookRequests={len(webhook.requests)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
