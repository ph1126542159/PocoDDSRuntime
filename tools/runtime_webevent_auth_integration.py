#!/usr/bin/env python3
"""Prove that the Runtime WebEvent endpoint accepts dispatcher-authenticated users."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--runtime-smoke", type=Path, required=True)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--working-directory", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    report_path = args.report.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    unauthenticated_report = report_path.with_name(report_path.stem + "-unauthenticated.json")
    unauthenticated_log = report_path.with_name(report_path.stem + "-unauthenticated.log")
    invalid_report = report_path.with_name(report_path.stem + "-invalid-credentials.json")
    invalid_log = report_path.with_name(report_path.stem + "-invalid-credentials.log")
    invalid_bearer_report = report_path.with_name(report_path.stem + "-invalid-bearer.json")
    invalid_bearer_log = report_path.with_name(report_path.stem + "-invalid-bearer.log")
    authenticated_bearer_report = report_path.with_name(
        report_path.stem + "-authenticated-bearer.json")
    authenticated_bearer_log = report_path.with_name(
        report_path.stem + "-authenticated-bearer.log")
    authenticated_report = report_path.with_name(report_path.stem + "-authenticated.json")
    authenticated_log = report_path.with_name(report_path.stem + "-authenticated.log")
    credential_environment = "PDR_WEBEVENT_INTEGRATION_BASIC"
    management_token_environment = "PDR_WEBEVENT_INTEGRATION_MANAGEMENT_TOKEN"
    invalid_bearer_environment = "PDR_WEBEVENT_INTEGRATION_INVALID_BEARER"
    username = "integration-admin"
    management_token = secrets.token_urlsafe(48)
    invalid_password = secrets.token_urlsafe(32)
    invalid_bearer = secrets.token_urlsafe(48)

    environment = os.environ.copy()
    environment[management_token_environment] = management_token
    environment[invalid_bearer_environment] = invalid_bearer

    def run_smoke(expected_status: int, output: Path, log: Path, auth_mode: str):
        command = [
            str(args.python.resolve()), str(args.runtime_smoke.resolve()),
            "--executable", str(args.executable.resolve()),
            "--working-directory", str(args.working_directory.resolve()),
            "--config", str(args.config.resolve()),
            "--timeout", "20",
            "--stability-window", "1",
            "--clear-code-cache",
            "--endpoint", "/webevent",
            "--expect-status", f"/webevent={expected_status}",
            "--set", "auth.simple.enable=false",
            "--set", "osp.web.authServiceName=pdr.auth.management",
            "--set", "osp.web.tokenValidatorName=pdr.auth.management.tokens",
            "--set", "pdr.management.authentication.required=true",
            "--set", "pdr.management.authentication.principals.count=1",
            "--set", f"pdr.management.authentication.principals.0.id={username}",
            "--set", ("pdr.management.authentication.principals.0.tokenEnvironment=" +
                      management_token_environment),
            "--set", "pdr.management.authentication.principals.0.permissions=*",
            "--report", str(output),
            "--log", str(log),
        ]
        if auth_mode == "basic":
            command.extend((
                "--endpoint-basic-credentials-environment",
                f"/webevent={credential_environment}",
            ))
        elif auth_mode in {"invalid-bearer", "bearer"}:
            environment_name = (invalid_bearer_environment
                                if auth_mode == "invalid-bearer"
                                else management_token_environment)
            command.extend((
                "--endpoint-bearer-token-environment",
                f"/webevent={environment_name}",
            ))
        for path in args.path:
            command.extend(("--path", str(Path(path).resolve())))
        completed = subprocess.run(
            command, env=environment, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        return completed, json.loads(output.read_text(encoding="utf-8"))

    try:
        unauthenticated, unauthenticated_smoke = run_smoke(
            401, unauthenticated_report, unauthenticated_log, "none"
        )
        environment[credential_environment] = f"{username}:{invalid_password}"
        invalid, invalid_smoke = run_smoke(401, invalid_report, invalid_log, "basic")
        invalid_bearer_result, invalid_bearer_smoke = run_smoke(
            401, invalid_bearer_report, invalid_bearer_log, "invalid-bearer"
        )
        authenticated_bearer, authenticated_bearer_smoke = run_smoke(
            400, authenticated_bearer_report, authenticated_bearer_log, "bearer"
        )
        environment[credential_environment] = f"{username}:{management_token}"
        authenticated, authenticated_smoke = run_smoke(
            400, authenticated_report, authenticated_log, "basic"
        )
        evidence_segments = {
            "unauthenticated-stdout": unauthenticated.stdout,
            "invalid-basic-stdout": invalid.stdout,
            "invalid-bearer-stdout": invalid_bearer_result.stdout,
            "authenticated-bearer-stdout": authenticated_bearer.stdout,
            "authenticated-basic-stdout": authenticated.stdout,
            "unauthenticated-report": json.dumps(unauthenticated_smoke, ensure_ascii=False),
            "invalid-basic-report": json.dumps(invalid_smoke, ensure_ascii=False),
            "invalid-bearer-report": json.dumps(invalid_bearer_smoke, ensure_ascii=False),
            "authenticated-bearer-report": json.dumps(authenticated_bearer_smoke, ensure_ascii=False),
            "authenticated-basic-report": json.dumps(authenticated_smoke, ensure_ascii=False),
            "unauthenticated-log": unauthenticated_log.read_text(encoding="utf-8", errors="replace"),
            "invalid-basic-log": invalid_log.read_text(encoding="utf-8", errors="replace"),
            "invalid-bearer-log": invalid_bearer_log.read_text(encoding="utf-8", errors="replace"),
            "authenticated-bearer-log": authenticated_bearer_log.read_text(encoding="utf-8", errors="replace"),
            "authenticated-basic-log": authenticated_log.read_text(encoding="utf-8", errors="replace"),
        }
        secret_values = {
            "management-token": management_token,
            "invalid-basic-password": invalid_password,
            "invalid-bearer": invalid_bearer,
            "basic-credential-pair": f"{username}:{management_token}",
        }
        leaks = [
            f"{secret_name}@{segment_name}"
            for secret_name, secret in secret_values.items()
            for segment_name, evidence in evidence_segments.items()
            if secret in evidence
        ]
        if leaks:
            raise RuntimeError(
                "authentication credentials leaked into Runtime smoke evidence: " +
                ", ".join(leaks)
            )
        unauthenticated_probes = [
            probe for probe in unauthenticated_smoke.get("probes", [])
            if probe.get("endpoint") == "/webevent"
        ]
        web_event_probes = [
            probe for probe in authenticated_smoke.get("probes", [])
            if probe.get("endpoint") == "/webevent"
        ]
        invalid_probes = [
            probe for probe in invalid_smoke.get("probes", [])
            if probe.get("endpoint") == "/webevent"
        ]
        invalid_bearer_probes = [
            probe for probe in invalid_bearer_smoke.get("probes", [])
            if probe.get("endpoint") == "/webevent"
        ]
        authenticated_bearer_probes = [
            probe for probe in authenticated_bearer_smoke.get("probes", [])
            if probe.get("endpoint") == "/webevent"
        ]
        if unauthenticated.returncode != 0 or not unauthenticated_smoke.get("passed"):
            raise RuntimeError(f"unauthenticated Runtime smoke failed: {unauthenticated.stdout}")
        if len(unauthenticated_probes) != 1 or unauthenticated_probes[0].get("status") != 401:
            raise RuntimeError("unauthenticated WebEvent request was not rejected")
        if invalid.returncode != 0 or not invalid_smoke.get("passed"):
            raise RuntimeError(f"invalid-credential Runtime smoke failed: {invalid.stdout}")
        if len(invalid_probes) != 1 or invalid_probes[0].get("status") != 401:
            raise RuntimeError("invalid WebEvent credentials were not rejected")
        if invalid_bearer_result.returncode != 0 or not invalid_bearer_smoke.get("passed"):
            raise RuntimeError(
                f"invalid-Bearer Runtime smoke failed: {invalid_bearer_result.stdout}"
            )
        if len(invalid_bearer_probes) != 1 or invalid_bearer_probes[0].get("status") != 401:
            raise RuntimeError("invalid WebEvent Bearer token was not rejected")
        if authenticated_bearer.returncode != 0 or not authenticated_bearer_smoke.get("passed"):
            raise RuntimeError(
                f"authenticated-Bearer Runtime smoke failed: {authenticated_bearer.stdout}"
            )
        if (len(authenticated_bearer_probes) != 1 or
                authenticated_bearer_probes[0].get("status") != 400):
            raise RuntimeError("management Bearer token did not authenticate WebEvent")
        if authenticated.returncode != 0 or not authenticated_smoke.get("passed"):
            raise RuntimeError(f"authenticated Runtime smoke failed: {authenticated.stdout}")
        if len(web_event_probes) != 1 or web_event_probes[0].get("status") != 400:
            raise RuntimeError("authenticated WebEvent request did not reach WebSocket handshake validation")
        if authenticated_smoke.get("endpointBasicAuthentication", {}).get("/webevent") != credential_environment:
            raise RuntimeError("Runtime smoke did not record the credential environment binding")
        result = {
            "schemaVersion": 1,
            "passed": True,
            "unauthenticatedStatus": 401,
            "invalidCredentialsStatus": 401,
            "invalidBearerStatus": 401,
            "authenticatedBearerHandshakeStatus": 400,
            "authenticatedHandshakeStatus": 400,
            "credentialEnvironment": credential_environment,
            "credentialsLeaked": False,
            "runtimeShutdowns": [
                unauthenticated_smoke.get("shutdown"), invalid_smoke.get("shutdown"),
                invalid_bearer_smoke.get("shutdown"),
                authenticated_bearer_smoke.get("shutdown"),
                authenticated_smoke.get("shutdown")
            ],
            "unauthenticatedReport": str(unauthenticated_report),
            "invalidCredentialsReport": str(invalid_report),
            "invalidBearerReport": str(invalid_bearer_report),
            "authenticatedBearerReport": str(authenticated_bearer_report),
            "authenticatedReport": str(authenticated_report),
        }
        report_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"WEBEVENT_AUTH_INTEGRATION_PASS report={report_path}")
        return 0
    except Exception as error:
        report_path.write_text(json.dumps({
            "schemaVersion": 1,
            "passed": False,
            "error": str(error),
        }, indent=2) + "\n", encoding="utf-8")
        print(f"WEBEVENT_AUTH_INTEGRATION_ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
