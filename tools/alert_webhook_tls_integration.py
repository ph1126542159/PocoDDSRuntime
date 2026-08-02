#!/usr/bin/env python3
"""Verify Runtime alert webhook TLS trust, mTLS, isolation and secret handling."""

from __future__ import annotations

import argparse
import json
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from mqtt_tls_integration import generate_ca, generate_client, generate_server


def invoke(command: list[str], directory: Path, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=directory, env=environment, text=True,
        capture_output=True, check=False,
    )


class SecureWebhookServer:
    def __init__(self, ca: Path, certificate: Path, key: Path) -> None:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
                try:
                    body = json.loads(self.rfile.read(
                        int(self.headers.get("Content-Length", "0"))
                    ).decode("utf-8"))
                    owner.requests.append({
                        "authorization": self.headers.get("Authorization", ""),
                        "idempotencyKey": self.headers.get("Idempotency-Key", ""),
                        "clientCertificate": bool(self.connection.getpeercert()),
                        "body": body,
                    })
                    self.send_response(204)
                    self.end_headers()
                except Exception as error:  # evidence returned to parent test
                    owner.errors.append(str(error))
                    self.send_response(400)
                    self.end_headers()

            def log_message(self, _format: str, *_args: object) -> None:
                return

        class IPv6ThreadingHTTPServer(ThreadingHTTPServer):
            address_family = socket.AF_INET6

        self.server = IPv6ThreadingHTTPServer(("::1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certificate, key)
        context.load_verify_locations(cafile=ca)
        context.verify_mode = ssl.CERT_REQUIRED
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.port = int(self.server.server_address[1])
        self.requests: list[dict[str, object]] = []
        self.errors: list[str] = []
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        if self.thread.is_alive():
            self.errors.append("HTTPS server thread did not stop")


def runtime_command(args: argparse.Namespace, report: Path, url: str, ca: Path,
                    client_certificate: Path, client_key: Path) -> list[str]:
    return [
        sys.executable, str(args.runtime_smoke),
        "--executable", str(args.runtime),
        "--working-directory", str(args.working_directory),
        "--config", str(args.config),
        "--timeout", "12", "--stability-window", "2", "--probe-delay", "0.5",
        "--clear-code-cache",
        "--path", str(args.install_bin), "--path", str(args.working_directory),
        "--endpoint", "/api/v1/alerts",
        "--endpoint", "/api/v1/alert-sinks",
        "--endpoint", "/api/v1/metrics",
        "--set", "pdr.ros.count=1",
        "--set", "pdr.ros.0.id=webhook-tls-trigger",
        "--set", "pdr.ros.0.uri=ws://127.0.0.1:1/",
        "--set", "pdr.ros.0.required=false",
        "--set", "pdr.ros.0.autoReconnect=false",
        "--set", "pdr.alerts.debounceMilliseconds=50",
        "--set", "pdr.alerts.escalationMilliseconds=200",
        "--set", "pdr.alerts.webhook.enabled=true",
        "--set", "pdr.alerts.deliveryFailureThreshold=1",
        "--set", "pdr.alerts.deliveryCircuitOpenMilliseconds=30000",
        "--set", f"pdr.alerts.webhook.url={url}",
        "--set", "pdr.alerts.webhook.timeoutMilliseconds=1000",
        "--set", "pdr.alerts.webhook.maximumAttempts=2",
        "--set", "pdr.alerts.webhook.initialBackoffMilliseconds=50",
        "--set", "pdr.alerts.webhook.maximumBackoffMilliseconds=100",
        "--set", "pdr.alerts.webhook.authorizationEnvironment=PDR_TEST_WEBHOOK_TLS_AUTH",
        "--set", f"pdr.alerts.webhook.caCertificate={ca.as_posix()}",
        "--set", f"pdr.alerts.webhook.clientCertificate={client_certificate.as_posix()}",
        "--set", f"pdr.alerts.webhook.privateKey={client_key.as_posix()}",
        "--require-log", "Alert webhook sink registered",
        "--require-log", "alert.event=alert.opened",
        "--require-body", "https-webhook",
        "--report", str(report),
    ]


def combined_evidence(report: Path, completed: subprocess.CompletedProcess[str]) -> str:
    evidence = completed.stdout + completed.stderr
    if report.exists():
        evidence += report.read_text(encoding="utf-8", errors="replace")
    log = report.with_suffix(".log")
    if log.exists():
        evidence += log.read_text(encoding="utf-8", errors="replace")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openssl", required=True, type=Path)
    parser.add_argument("--runtime-smoke", required=True, type=Path)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--working-directory", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--install-bin", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="pdr-alert-webhook-tls-") as temporary:
        directory = Path(temporary)
        (directory / "openssl.cnf").write_text(
            "openssl_conf=openssl_init\n[openssl_init]\nproviders=providers\n"
            "[providers]\ndefault=default_provider\n[default_provider]\nactivate=1\n"
            "[req]\ndistinguished_name=req_dn\n[req_dn]\n",
            encoding="ascii", newline="\n",
        )
        ca_key, ca = generate_ca(args.openssl, directory, "PDR-Webhook-Test-CA")
        _, wrong_ca = generate_ca(args.openssl, directory, "PDR-Webhook-Wrong-CA")
        server_key, server_certificate = generate_server(
            args.openssl, directory, ca_key, ca
        )
        client_key, client_certificate = generate_client(
            args.openssl, directory, ca_key, ca
        )
        server = SecureWebhookServer(ca, server_certificate, server_key)
        server.start()
        url = f"https://localhost:{server.port}/alerts"
        secret = "Bearer pdr-webhook-tls-secret-must-not-leak"
        environment = os.environ.copy()
        environment["OPENSSL_CONF"] = str(directory / "openssl.cnf")
        environment["PDR_TEST_WEBHOOK_TLS_AUTH"] = secret

        trusted = invoke(
            runtime_command(args, args.report, url, ca, client_certificate, client_key),
            directory, environment,
        )
        if trusted.returncode != 0:
            server.stop()
            raise RuntimeError(
                "trusted mTLS Runtime failed:\n" + combined_evidence(args.report, trusted)
            )
        if secret in combined_evidence(args.report, trusted):
            server.stop()
            raise RuntimeError("webhook authorization secret leaked into report or log")
        if server.errors or not server.requests:
            server.stop()
            raise RuntimeError(f"mTLS webhook did not receive an alert: {server.errors}")
        if not all(
            request["authorization"] == secret and request["clientCertificate"] and
            request["idempotencyKey"] and request["body"].get("schemaVersion") == 1
            for request in server.requests
        ):
            server.stop()
            raise RuntimeError("mTLS webhook request headers, certificate or schema are invalid")

        rejected_report = args.report.with_name(args.report.stem + "-wrong-ca.json")
        rejected_command = runtime_command(
            args, rejected_report, url, wrong_ca, client_certificate, client_key
        )
        rejected_command.extend([
            "--require-log", "Alert sink webhook failed",
            "--require-body", '"status":"circuit-open"',
            "--require-body", '"circuitOpen":true',
            "--require-body", '"circuitOpenSkips":1',
        ])
        rejected = invoke(rejected_command, directory, environment)
        if rejected.returncode != 0:
            server.stop()
            raise RuntimeError(
                "wrong-CA failure was not isolated from Runtime:\n" +
                combined_evidence(rejected_report, rejected)
            )

        missing_report = args.report.with_name(args.report.stem + "-missing-secret.json")
        missing_command = runtime_command(
            args, missing_report, url, ca, client_certificate, client_key
        )
        missing_environment = environment.copy()
        missing_environment.pop("PDR_TEST_WEBHOOK_TLS_AUTH", None)
        missing = invoke(missing_command, directory, missing_environment)
        missing_evidence = combined_evidence(missing_report, missing)
        if missing.returncode == 0 or "PDR_TEST_WEBHOOK_TLS_AUTH" not in missing_evidence:
            server.stop()
            raise RuntimeError("missing webhook secret was not rejected with an actionable error")
        server.stop()
        if server.errors:
            raise RuntimeError("; ".join(server.errors))

        result = json.loads(args.report.read_text(encoding="utf-8"))
        result["webhookTlsVerification"] = {
            "trustedServerCertificate": True,
            "clientCertificatePresented": True,
            "wrongCaRejectedAndRuntimeStayedUp": True,
            "missingSecretFailFast": True,
            "authorizationSecretAbsentFromEvidence": True,
            "receivedEvents": [request["body"].get("event") for request in server.requests],
        }
        args.report.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8", newline="\n",
        )

    print(
        "ALERT_WEBHOOK_TLS_INTEGRATION_PASS trusted=accepted mtls=verified "
        "wrongCA=rejected failureIsolated=true missingSecret=fail-fast secretLeak=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
