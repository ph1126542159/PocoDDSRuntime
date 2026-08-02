#!/usr/bin/env python3
"""Verify ROS Bridge wss/mTLS/auth through the library and Runtime gateway."""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from mqtt_tls_integration import generate_ca, generate_client, generate_server


def execute(command: list[str], cwd: Path, environment: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    values = os.environ.copy()
    values["OPENSSL_CONF"] = str(cwd / "openssl.cnf")
    if environment:
        values.update(environment)
    return subprocess.run(
        command, cwd=cwd, env=values, text=True, capture_output=True, check=False
    )


def require_success(command: list[str], cwd: Path, environment: dict[str, str] | None = None) -> None:
    result = execute(command, cwd, environment)
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"{result.stdout}{result.stderr}"
        )


def receive_upgrade(connection: ssl.SSLSocket) -> dict[str, str]:
    request = bytearray()
    while b"\r\n\r\n" not in request:
        chunk = connection.recv(4096)
        if not chunk:
            raise ConnectionError("peer closed before WebSocket upgrade")
        request.extend(chunk)
        if len(request) > 65536:
            raise ValueError("oversized WebSocket upgrade")
    headers: dict[str, str] = {}
    for line in request.decode("iso-8859-1").split("\r\n")[1:]:
        name, separator, value = line.partition(":")
        if separator:
            headers[name.strip().lower()] = value.strip()
    return headers


def send_upgrade(connection: ssl.SSLSocket, key: str) -> None:
    accept = base64.b64encode(hashlib.sha1(
        (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
    ).digest()).decode("ascii")
    connection.sendall(
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n\r\n".encode("ascii")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openssl", required=True, type=Path)
    parser.add_argument("--probe", required=True, type=Path)
    parser.add_argument("--runtime-smoke", required=True, type=Path)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--working-directory", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--install-bin", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="pdr-ros-tls-") as temporary:
        directory = Path(temporary)
        (directory / "openssl.cnf").write_text(
            "openssl_conf=openssl_init\n[openssl_init]\nproviders=providers\n"
            "[providers]\ndefault=default_provider\n[default_provider]\nactivate=1\n"
            "[req]\ndistinguished_name=req_dn\n[req_dn]\n",
            encoding="ascii", newline="\n",
        )
        ca_key, ca = generate_ca(args.openssl, directory, "PDR-ROS-Test-CA")
        _, wrong_ca = generate_ca(args.openssl, directory, "PDR-ROS-Wrong-CA")
        server_key, server_certificate = generate_server(args.openssl, directory, ca_key, ca)
        client_key, client_certificate = generate_client(args.openssl, directory, ca_key, ca)

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(server_certificate, server_key)
        context.load_verify_locations(cafile=ca)
        context.verify_mode = ssl.CERT_REQUIRED
        # Poco resolves localhost to IPv6 first on Windows.  Use one dual-stack
        # listener so the trusted localhost case and the intentional IPv4
        # hostname-mismatch case both reach the same TLS fixture.
        listener = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        listener.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        listener.bind(("::", 0))
        listener.listen()
        listener.settimeout(6)
        port = listener.getsockname()[1]
        authorization = "Bearer pdr-ros-authorization-must-not-leak"
        errors: list[str] = []

        def serve() -> None:
            successful = 0
            while successful < 2:
                try:
                    plain, _ = listener.accept()
                    with plain:
                        with context.wrap_socket(plain, server_side=True) as secured:
                            headers = receive_upgrade(secured)
                            if not secured.getpeercert():
                                raise RuntimeError("ROS client did not present mTLS certificate")
                            if headers.get("authorization") != authorization:
                                raise RuntimeError("ROS Authorization header missing or invalid")
                            key = headers.get("sec-websocket-key", "")
                            if not key:
                                raise RuntimeError("WebSocket key missing")
                            send_upgrade(secured, key)
                            successful += 1
                            if successful == 2:
                                threading.Event().wait(5)
                except (ssl.SSLError, ConnectionError):
                    if successful == 0:
                        errors.append("trusted ROS client failed before WebSocket upgrade")
                except TimeoutError:
                    errors.append("ROS TLS server timed out")
                    return
                except Exception as error:
                    errors.append(str(error))

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        uri = f"wss://localhost:{port}/"
        common_probe = [
            str(client_certificate), str(client_key), authorization,
        ]
        require_success([
            str(args.probe), uri, str(ca), *common_probe, "expect-success"
        ], directory)
        require_success([
            str(args.probe), uri, str(wrong_ca), *common_probe, "expect-failure"
        ], directory)
        require_success([
            str(args.probe), f"wss://127.0.0.1:{port}/", str(ca),
            *common_probe, "expect-failure"
        ], directory)

        runtime_command = [
            sys.executable, str(args.runtime_smoke),
            "--executable", str(args.runtime),
            "--working-directory", str(args.working_directory),
            "--config", str(args.config), "--timeout", "20",
            "--stability-window", "2", "--clear-code-cache",
            "--path", str(args.install_bin), "--path", str(args.working_directory),
            "--endpoint", "/api/v1/protocols",
            "--set", "pdr.ros.count=1",
            "--set", "pdr.ros.0.id=runtime-ros-tls",
            "--set", f"pdr.ros.0.uri={uri}",
            "--set", f"pdr.ros.0.trustStore={ca.as_posix()}",
            "--set", f"pdr.ros.0.clientCertificate={client_certificate.as_posix()}",
            "--set", f"pdr.ros.0.privateKey={client_key.as_posix()}",
            "--set", "pdr.ros.0.authorizationEnvironment=PDR_TEST_ROS_AUTHORIZATION",
            "--set", "pdr.ros.0.verifyServerCertificate=true",
            "--set", "pdr.ros.0.verifyHostname=true",
            "--set", "pdr.ros.0.required=true",
            "--set", "pdr.ros.0.autoReconnect=false",
            "--require-body", "runtime-ros-tls",
            "--require-body", '\"type\":\"rosbridge\"',
            "--require-body", '\"open\":true',
            "--report", str(args.report),
        ]
        require_success(runtime_command, directory, {
            "PDR_TEST_ROS_AUTHORIZATION": authorization,
        })
        thread.join(timeout=8)
        listener.close()
        if thread.is_alive() or errors:
            raise RuntimeError(f"ROS TLS server failed: alive={thread.is_alive()} errors={errors}")
        evidence = args.report.read_text(encoding="utf-8")
        log = args.report.with_suffix(".log")
        if log.exists():
            evidence += log.read_text(encoding="utf-8", errors="replace")
        if authorization in evidence:
            raise RuntimeError("ROS Authorization secret leaked into report or log")

    print(
        "ROS_TLS_INTEGRATION_PASS wss=verified mtls=verified auth=verified "
        "wrongCA=rejected hostnameMismatch=rejected runtimeGateway=open"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
