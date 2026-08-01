#!/usr/bin/env python3
"""Run the packaged Runtime against local MQTT and rosbridge protocol servers."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import socket
import struct
import subprocess
import sys
import threading
import time
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
                    (isinstance(error, ConnectionError) or
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
        if self.connections == 1:
            # Inject a transport-side failure after the initial CONNACK. The
            # short delay lets the client commit its connected state so this
            # exercises established-session recovery rather than handshake timing.
            time.sleep(0.25)
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
                       args.cycles * 2 * args.cycle_action_delay +
                       args.stability_window + 20)
    if args.timeout is not None and args.timeout < minimum_timeout:
        raise SystemExit(
            f"--timeout must be at least {minimum_timeout:g} seconds for the configured cycles"
        )
    timeout = args.timeout if args.timeout is not None else max(20.0, minimum_timeout)
    mqtt = MqttServer()
    ros = RosbridgeServer()
    mqtt.start()
    ros.start()
    command = [
        sys.executable, str(args.runtime_smoke),
        "--executable", str(args.executable),
        "--working-directory", str(args.working_directory),
        "--config", str(args.config),
        "--timeout", str(timeout), "--stability-window", str(args.stability_window),
        "--clear-code-cache", "--post-delay", str(args.startup_recovery_delay),
        "--post-interval", str(args.cycle_action_delay),
        "--post-health-interval", str(args.health_sample_interval),
        "--path", str(args.install_bin), "--path", str(args.working_directory),
        "--endpoint", "/api/v1/protocols",
        "--set", "pdr.mqtt.count=1",
        "--set", "pdr.mqtt.0.id=runtime-mqtt",
        "--set", f"pdr.mqtt.0.serverUri=tcp://127.0.0.1:{mqtt.port}",
        "--set", "pdr.mqtt.0.clientId=pdr-runtime-integration",
        "--set", "pdr.mqtt.0.keepAliveSeconds=2",
        "--set", "pdr.mqtt.0.connectTimeoutSeconds=3",
        "--set", "pdr.mqtt.0.required=true",
        "--set", "pdr.mqtt.0.autoReconnect=true",
        "--set", "pdr.mqtt.0.reconnectDelayMilliseconds=200",
        "--set", "pdr.mqtt.0.reconnectMaximumDelayMilliseconds=1000",
        "--set", "pdr.ros.count=1",
        "--set", "pdr.ros.0.id=runtime-ros",
        "--set", f"pdr.ros.0.uri=ws://127.0.0.1:{ros.port}/",
        "--set", "pdr.ros.0.required=true",
        "--require-log", "Protocol gateway started with 2 protocol instance",
        "--require-log", "Protocol runtime-mqtt recovered automatically",
        "--require-body", "runtime-mqtt", "--require-body", "runtime-ros",
        "--require-body", '"type":"mqtt"',
        "--require-body", '"type":"rosbridge"',
        "--require-body", '"open":true',
        "--require-body", '"action":"restart"',
        "--report", str(args.report),
        "--sample-resources", "--max-rss-growth-mib", str(args.max_rss_growth_mib),
        "--max-handle-growth", str(args.max_handle_growth),
        "--resource-baseline-after-post", "2",
    ]
    for _ in range(args.cycles):
        command.extend([
            "--post", '/api/v1/protocols={"id":"runtime-mqtt","action":"restart"}',
            "--post", '/api/v1/protocols={"id":"runtime-ros","action":"restart"}',
        ])
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    time.sleep(0.2)
    mqtt.stop()
    ros.stop()

    result = json.loads(args.report.read_text(encoding="utf-8")) if args.report.exists() else {}
    result["testServers"] = {
        "mqtt": {"port": mqtt.port, "connections": mqtt.connections,
                 "transportClosures": mqtt.transport_closures, "errors": mqtt.errors},
        "rosbridge": {"port": ros.port, "connections": ros.connections,
                      "transportClosures": ros.transport_closures, "errors": ros.errors},
    }
    result["recoveryCycles"] = args.cycles
    result["startupRecoveryDelaySeconds"] = args.startup_recovery_delay
    result["cycleActionDelaySeconds"] = args.cycle_action_delay
    result["healthSampleIntervalSeconds"] = args.health_sample_interval
    result["configuredTimeoutSeconds"] = timeout
    result["resourceLimits"] = {
        "maxRssGrowthMiB": args.max_rss_growth_mib,
        "maxHandleGrowth": args.max_handle_growth,
    }
    observations_per_action = (
        math.ceil(args.cycle_action_delay / args.health_sample_interval)
        if args.cycle_action_delay > 0 else 0
    )
    expected_resource_samples = 2 + args.cycles * 2 * (1 + observations_per_action)
    observed_resource_samples = len(result.get("resourceSamples", []))
    result["expectedMinimumResourceSamples"] = expected_resource_samples
    result["observedResourceSamples"] = observed_resource_samples
    servers_passed = (
        mqtt.connections >= args.cycles + 2 and ros.connections >= args.cycles + 1 and
        not mqtt.errors and not ros.errors and
        observed_resource_samples >= expected_resource_samples
    )
    result["passed"] = completed.returncode == 0 and servers_passed
    if not servers_passed:
        result["integrationError"] = (
            "protocol servers or resource sampler did not observe the configured recovery soak"
        )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    if not result["passed"]:
        print("RUNTIME_PROTOCOL_GATEWAY_INTEGRATION_FAIL", file=sys.stderr)
        return 1
    print(
        "RUNTIME_PROTOCOL_GATEWAY_INTEGRATION_PASS "
        f"mqttConnections={mqtt.connections} rosConnections={ros.connections}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
