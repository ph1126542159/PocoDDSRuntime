#!/usr/bin/env python3
"""Verify WebTunnel LocalForwarder wss, mTLS and Authorization behavior."""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import socket
import ssl
import struct
import subprocess
import tempfile
import threading
from pathlib import Path

from mqtt_tls_integration import generate_ca, generate_client, generate_server


def receive_exact(connection: socket.socket, size: int) -> bytes:
    value = bytearray()
    while len(value) < size:
        chunk = connection.recv(size - len(value))
        if not chunk:
            raise ConnectionError("peer closed before expected data")
        value.extend(chunk)
    return bytes(value)


def receive_upgrade(connection: socket.socket) -> dict[str, str]:
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


def receive_frame(connection: socket.socket) -> tuple[int, bytes]:
    first, second = receive_exact(connection, 2)
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", receive_exact(connection, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", receive_exact(connection, 8))[0]
    mask = receive_exact(connection, 4) if second & 0x80 else b""
    payload = bytearray(receive_exact(connection, length))
    for index in range(len(payload)):
        if mask:
            payload[index] ^= mask[index % 4]
    return first & 0x0F, bytes(payload)


def send_frame(connection: socket.socket, opcode: int, payload: bytes) -> None:
    header = bytearray([0x80 | opcode])
    if len(payload) < 126:
        header.append(len(payload))
    elif len(payload) <= 0xFFFF:
        header.extend((126, *struct.pack("!H", len(payload))))
    else:
        header.extend((127, *struct.pack("!Q", len(payload))))
    connection.sendall(header + payload)


def run_probe(probe: Path, directory: Path, arguments: list[str], secret: str) -> None:
    environment = os.environ.copy()
    environment["OPENSSL_CONF"] = str(directory / "openssl.cnf")
    environment["PDR_TEST_WEBTUNNEL_AUTH"] = secret
    result = subprocess.run(
        [str(probe), *arguments], cwd=directory, env=environment,
        text=True, capture_output=True, check=False)
    evidence = result.stdout + result.stderr
    if secret in evidence:
        raise RuntimeError("WebTunnel Authorization secret leaked into probe output")
    if result.returncode != 0:
        raise RuntimeError(f"WebTunnel TLS probe failed ({result.returncode}): {evidence}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openssl", required=True, type=Path)
    parser.add_argument("--probe", required=True, type=Path)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="pdr-webtunnel-tls-") as temporary:
        directory = Path(temporary)
        (directory / "openssl.cnf").write_text(
            "openssl_conf=openssl_init\n[openssl_init]\nproviders=providers\n"
            "[providers]\ndefault=default_provider\n[default_provider]\nactivate=1\n"
            "[req]\ndistinguished_name=req_dn\n[req_dn]\n",
            encoding="ascii", newline="\n")
        ca_key, ca = generate_ca(args.openssl, directory, "PDR-WebTunnel-Test-CA")
        _, wrong_ca = generate_ca(args.openssl, directory, "PDR-WebTunnel-Wrong-CA")
        server_key, server_certificate = generate_server(
            args.openssl, directory, ca_key, ca)
        client_key, client_certificate = generate_client(
            args.openssl, directory, ca_key, ca)

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(server_certificate, server_key)
        context.load_verify_locations(cafile=ca)
        context.verify_mode = ssl.CERT_REQUIRED
        listener = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        listener.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        listener.bind(("::", 0))
        listener.listen()
        listener.settimeout(8)
        port = listener.getsockname()[1]
        authorization = "Bearer pdr-webtunnel-authorization-must-not-leak"
        errors: list[str] = []

        def serve() -> None:
            attempts = 0
            successful = 0
            while attempts < 4:
                try:
                    plain, _ = listener.accept()
                    attempts += 1
                    with plain:
                        with context.wrap_socket(plain, server_side=True) as secured:
                            headers = receive_upgrade(secured)
                            if not secured.getpeercert():
                                raise RuntimeError("WebTunnel client certificate missing")
                            if headers.get("authorization") != authorization:
                                raise RuntimeError("WebTunnel Authorization invalid")
                            if headers.get("sec-websocket-protocol") != \
                                    "com.appinf.webtunnel.client/1.0":
                                raise RuntimeError("WebTunnel subprotocol missing")
                            if headers.get("x-webtunnel-remoteport") != "9080":
                                raise RuntimeError("WebTunnel target port invalid")
                            key = headers.get("sec-websocket-key", "")
                            accept = base64.b64encode(hashlib.sha1(
                                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11")
                                .encode("ascii")).digest()).decode("ascii")
                            secured.sendall(
                                "HTTP/1.1 101 Switching Protocols\r\n"
                                "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                                "Sec-WebSocket-Protocol: com.appinf.webtunnel.client/1.0\r\n"
                                f"Sec-WebSocket-Accept: {accept}\r\n\r\n".encode("ascii"))
                            opcode, payload = receive_frame(secured)
                            if opcode != 2:
                                raise RuntimeError("WebTunnel binary frame missing")
                            send_frame(secured, 2, payload)
                            successful += 1
                except (ssl.SSLError, ConnectionError):
                    if successful == 0:
                        errors.append("trusted WebTunnel client failed before data exchange")
                except Exception as error:
                    errors.append(str(error))
            if successful != 1:
                errors.append(f"expected one successful tunnel, observed {successful}")

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        common = [str(client_certificate), str(client_key),
                  "PDR_TEST_WEBTUNNEL_AUTH"]
        run_probe(args.probe, directory, [
            f"wss://localhost:{port}/tunnel", str(ca), *common, "expect-success"
        ], authorization)
        run_probe(args.probe, directory, [
            f"wss://localhost:{port}/tunnel", str(wrong_ca), *common, "expect-failure"
        ], authorization)
        run_probe(args.probe, directory, [
            f"wss://127.0.0.1:{port}/tunnel", str(ca), *common, "expect-failure"
        ], authorization)
        run_probe(args.probe, directory, [
            f"wss://localhost:{port}/tunnel", str(ca), "-", "-",
            "PDR_TEST_WEBTUNNEL_AUTH", "expect-failure"
        ], authorization)
        thread.join(timeout=10)
        listener.close()
        if thread.is_alive() or errors:
            raise RuntimeError(
                f"WebTunnel TLS server failed: alive={thread.is_alive()} errors={errors}")

    print("WEBTUNNEL_TLS_INTEGRATION_PASS wss=verified mtls=verified "
          "authorization=verified wrongCA=rejected hostnameMismatch=rejected "
          "missingClientCertificate=rejected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
