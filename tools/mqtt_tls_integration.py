#!/usr/bin/env python3
"""Verify MQTT TLS trust and rejection with temporary local certificates."""

from __future__ import annotations

import argparse
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
from pathlib import Path


def run(command: list[str], cwd: Path, environment_overrides: dict[str, str] | None = None) -> None:
    environment = os.environ.copy()
    environment["OPENSSL_CONF"] = str(cwd / "openssl.cnf")
    if environment_overrides:
        environment.update(environment_overrides)
    result = subprocess.run(
        command, cwd=cwd, env=environment, text=True, capture_output=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"{result.stdout}{result.stderr}"
        )


def generate_ca(openssl: Path, directory: Path, name: str) -> tuple[Path, Path]:
    key = directory / f"{name}.key"
    certificate = directory / f"{name}.pem"
    run([
        str(openssl), "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", str(key), "-out", str(certificate), "-days", "1",
        "-subj", f"/CN={name}", "-sha256",
        "-addext", "basicConstraints=critical,CA:TRUE",
        "-addext", "keyUsage=critical,keyCertSign,cRLSign",
    ], directory)
    return key, certificate


def generate_server(openssl: Path, directory: Path, ca_key: Path, ca: Path) -> tuple[Path, Path]:
    key = directory / "server.key"
    request = directory / "server.csr"
    certificate = directory / "server.pem"
    extensions = directory / "server.ext"
    extensions.write_text(
        "subjectAltName=DNS:localhost\nextendedKeyUsage=serverAuth\n",
        encoding="ascii", newline="\n",
    )
    run([
        str(openssl), "req", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
        "-out", str(request), "-subj", "/CN=localhost", "-sha256",
    ], directory)
    run([
        str(openssl), "x509", "-req", "-in", str(request), "-CA", str(ca),
        "-CAkey", str(ca_key), "-CAcreateserial", "-out", str(certificate),
        "-days", "1", "-sha256", "-extfile", str(extensions),
    ], directory)
    return key, certificate


def generate_client(openssl: Path, directory: Path, ca_key: Path, ca: Path) -> tuple[Path, Path]:
    key = directory / "client.key"
    request = directory / "client.csr"
    certificate = directory / "client.pem"
    extensions = directory / "client.ext"
    extensions.write_text("extendedKeyUsage=clientAuth\n", encoding="ascii", newline="\n")
    run([
        str(openssl), "req", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
        "-out", str(request), "-subj", "/CN=pdr-runtime", "-sha256",
    ], directory)
    run([
        str(openssl), "x509", "-req", "-in", str(request), "-CA", str(ca),
        "-CAkey", str(ca_key), "-CAcreateserial", "-out", str(certificate),
        "-days", "1", "-sha256", "-extfile", str(extensions),
    ], directory)
    return key, certificate


def receive_packet(connection: ssl.SSLSocket) -> int:
    header = connection.recv(1)
    if not header:
        raise ConnectionError("MQTT peer closed before packet")
    remaining = 0
    multiplier = 1
    for _ in range(4):
        encoded = connection.recv(1)
        if not encoded:
            raise ConnectionError("MQTT peer closed during remaining length")
        remaining += (encoded[0] & 0x7F) * multiplier
        if encoded[0] & 0x80 == 0:
            break
        multiplier *= 128
    while remaining:
        chunk = connection.recv(remaining)
        if not chunk:
            raise ConnectionError("MQTT peer closed during packet")
        remaining -= len(chunk)
    return header[0] >> 4


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

    with tempfile.TemporaryDirectory(prefix="pdr-mqtt-tls-") as temporary:
        directory = Path(temporary)
        (directory / "openssl.cnf").write_text(
            "openssl_conf=openssl_init\n"
            "[openssl_init]\nproviders=providers\n"
            "[providers]\ndefault=default_provider\n"
            "[default_provider]\nactivate=1\n"
            "[req]\ndistinguished_name=req_dn\n"
            "[req_dn]\n",
            encoding="ascii", newline="\n",
        )
        ca_key, ca = generate_ca(args.openssl, directory, "PDR-Test-CA")
        _, wrong_ca = generate_ca(args.openssl, directory, "PDR-Wrong-CA")
        server_key, server_certificate = generate_server(
            args.openssl, directory, ca_key, ca
        )
        client_key, client_certificate = generate_client(
            args.openssl, directory, ca_key, ca
        )

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(server_certificate, server_key)
        context.load_verify_locations(cafile=ca)
        context.verify_mode = ssl.CERT_OPTIONAL
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(5)
        port = listener.getsockname()[1]
        errors: list[str] = []

        def serve() -> None:
            successful_connections = 0
            deadline = threading.Event()
            while successful_connections < 2 and not deadline.wait(0):
                try:
                    plain, _ = listener.accept()
                    with plain:
                        with context.wrap_socket(plain, server_side=True) as secured:
                            connection_index = successful_connections
                            if receive_packet(secured) != 1:
                                raise RuntimeError("expected MQTT CONNECT")
                            if connection_index == 1 and not secured.getpeercert():
                                raise RuntimeError("Runtime did not present its mTLS client certificate")
                            successful_connections += 1
                            secured.sendall(b"\x20\x02\x00\x00")
                            if connection_index == 1:
                                # Runtime smoke ends by terminating the process tree, so keep
                                # the broker side alive for its health/stability window.
                                for _ in range(60):
                                    if secured.fileno() < 0:
                                        break
                                    threading.Event().wait(0.1)
                                continue
                            if receive_packet(secured) != 14:
                                raise RuntimeError("expected MQTT DISCONNECT")
                except ssl.SSLError as error:
                    if successful_connections == 0:
                        errors.append(f"trusted client TLS handshake failed: {error}")
                except TimeoutError:
                    errors.append("TLS broker timed out waiting for a trusted client")
                    return
                except ConnectionError as error:
                    if successful_connections == 0:
                        errors.append(f"trusted client closed before MQTT CONNECT: {error}")
                except Exception as error:  # evidence is returned to the parent test
                    errors.append(str(error))

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        uri = f"ssl://localhost:{port}"
        password_secret = "pdr-mqtt-password-must-not-leak"
        try:
            run([str(args.probe), uri, str(ca), "expect-success"], directory)
        except Exception as error:
            thread.join(timeout=2)
            raise RuntimeError(f"{error}; TLS server evidence: {errors}") from error
        run([str(args.probe), uri, str(wrong_ca), "expect-failure"], directory)
        run([
            str(args.probe), f"ssl://127.0.0.1:{port}", str(ca), "expect-failure"
        ], directory)
        runtime_command = [
            sys.executable, str(args.runtime_smoke),
            "--executable", str(args.runtime),
            "--working-directory", str(args.working_directory),
            "--config", str(args.config),
            "--timeout", "20", "--stability-window", "2", "--clear-code-cache",
            "--path", str(args.install_bin), "--path", str(args.working_directory),
            "--endpoint", "/api/v1/protocols",
            "--set", "pdr.mqtt.count=1",
            "--set", "pdr.mqtt.0.id=runtime-mqtt-tls",
            "--set", f"pdr.mqtt.0.serverUri={uri}",
            "--set", "pdr.mqtt.0.clientId=pdr-runtime-tls-integration",
            "--set", "pdr.mqtt.0.usernameEnvironment=PDR_TEST_MQTT_USERNAME",
            "--set", "pdr.mqtt.0.passwordEnvironment=PDR_TEST_MQTT_PASSWORD",
            "--set", f"pdr.mqtt.0.trustStore={ca.as_posix()}",
            "--set", f"pdr.mqtt.0.keyStore={client_certificate.as_posix()}",
            "--set", f"pdr.mqtt.0.privateKey={client_key.as_posix()}",
            "--set", "pdr.mqtt.0.verifyServerCertificate=true",
            "--set", "pdr.mqtt.0.verifyHostname=true",
            "--set", "pdr.mqtt.0.required=true",
            "--set", "pdr.mqtt.0.autoReconnect=false",
            "--require-body", "runtime-mqtt-tls",
            "--require-body", '\"type\":\"mqtt\"',
            "--require-body", '\"open\":true',
            "--report", str(args.report),
        ]
        try:
            run(runtime_command, directory, {
                "PDR_TEST_MQTT_USERNAME": "pdr-runtime-test",
                "PDR_TEST_MQTT_PASSWORD": password_secret,
            })
        except Exception as error:
            thread.join(timeout=2)
            raise RuntimeError(f"{error}; TLS server evidence: {errors}") from error
        evidence_text = args.report.read_text(encoding="utf-8")
        runtime_log = args.report.with_suffix(".log")
        if runtime_log.exists():
            evidence_text += runtime_log.read_text(encoding="utf-8", errors="replace")
        if password_secret in evidence_text:
            raise RuntimeError("MQTT password leaked into Runtime report or log")
        thread.join(timeout=8)
        listener.close()
        if thread.is_alive():
            raise RuntimeError("TLS broker thread did not stop")
        if errors:
            raise RuntimeError("; ".join(errors))

        missing_variable = "PDR_INTENTIONALLY_MISSING_MQTT_PASSWORD"
        missing_report = args.report.with_name("runtime-mqtt-missing-secret.json")
        missing_command = [
            item.replace(
                "pdr.mqtt.0.passwordEnvironment=PDR_TEST_MQTT_PASSWORD",
                f"pdr.mqtt.0.passwordEnvironment={missing_variable}",
            ).replace(str(args.report), str(missing_report))
            for item in runtime_command
        ]
        missing_environment = os.environ.copy()
        missing_environment["OPENSSL_CONF"] = str(directory / "openssl.cnf")
        missing_environment["PDR_TEST_MQTT_USERNAME"] = "pdr-runtime-test"
        missing_environment.pop(missing_variable, None)
        missing_result = subprocess.run(
            missing_command, cwd=directory, env=missing_environment,
            text=True, capture_output=True, check=False,
        )
        if missing_result.returncode == 0:
            raise RuntimeError("Runtime accepted a configured but missing MQTT secret variable")
        if not missing_report.exists():
            raise RuntimeError("missing-secret Runtime did not write its failure report")
        missing_report_data = missing_report.read_text(encoding="utf-8")
        if '"probes": []' not in missing_report_data or "runtime exited with code 78" not in missing_report_data:
            raise RuntimeError("missing MQTT secret was not rejected before HTTP startup")
        missing_evidence = missing_result.stdout + missing_result.stderr
        missing_log = missing_report.with_suffix(".log")
        if missing_log.exists():
            missing_evidence += missing_log.read_text(encoding="utf-8", errors="replace")
        if missing_variable not in missing_evidence or "not set" not in missing_evidence:
            raise RuntimeError("missing MQTT secret did not produce an actionable fail-fast error")

    print(
        "MQTT_TLS_INTEGRATION_PASS trusted=accepted untrusted=rejected "
        "hostname=verified mtls=verified runtimeGateway=open missingSecret=fail-fast"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
