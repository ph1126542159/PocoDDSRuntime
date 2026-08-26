#!/usr/bin/env python3
"""Exercise authenticated online capability policy governance and restart recovery."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


OPERATOR_ENV = "PDR_CAPABILITY_API_OPERATOR_TOKEN"
READER_ENV = "PDR_CAPABILITY_API_READER_TOKEN"
DELEGATED_ENV = "PDR_CAPABILITY_API_DELEGATED_TOKEN"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", required=True)
    parser.add_argument("--runtime-smoke", type=Path, required=True)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--working-directory", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args()


def cleanup_database(path: Path) -> None:
    for suffix in ("", "-wal", "-shm", ".lock"):
        Path(str(path) + suffix).unlink(missing_ok=True)


def base_command(args: argparse.Namespace, report: Path, log: Path) -> list[str]:
    command = [
        args.python,
        str(args.runtime_smoke),
        "--executable", str(args.executable),
        "--working-directory", str(args.working_directory),
        "--config", str(args.config),
        "--port", "0",
        "--timeout", "15",
        "--stability-window", "1",
        "--shutdown-timeout", "10",
        "--clear-code-cache",
        "--bearer-token-environment", OPERATOR_ENV,
        "--set", "pdr.management.authentication.required=true",
        "--set", "pdr.management.authentication.principals.count=3",
        "--set", "pdr.management.authentication.principals.0.id=operator",
        "--set", f"pdr.management.authentication.principals.0.tokenEnvironment={OPERATOR_ENV}",
        "--set", "pdr.management.authentication.principals.0.permissions=capability.read,capability.manage",
        "--set", "pdr.management.authentication.principals.1.id=reader",
        "--set", f"pdr.management.authentication.principals.1.tokenEnvironment={READER_ENV}",
        "--set", "pdr.management.authentication.principals.1.permissions=capability.read",
        "--set", "pdr.management.authentication.principals.2.id=delegated-admin",
        "--set", f"pdr.management.authentication.principals.2.tokenEnvironment={DELEGATED_ENV}",
        "--set", "pdr.management.authentication.principals.2.permissions=capability.manage",
        "--set", f"pdr.capabilityRuntime.database={args.database.as_posix()}",
        "--endpoint", "/health/live",
        "--endpoint", "/api/v1/capabilities",
        "--endpoint", "/api/v1/capabilities/audit?limit=3",
        "--expect-status", "/health/live=200",
        "--expect-status", "/api/v1/capabilities=200",
        "--expect-status", "/api/v1/capabilities/audit?limit=3=200",
        "--endpoint-bearer-token-environment", f"/api/v1/capabilities={OPERATOR_ENV}",
        "--endpoint-bearer-token-environment", f"/api/v1/capabilities/audit?limit=3={OPERATOR_ENV}",
        "--require-log", "Capability management API started",
        "--report", str(report),
        "--log", str(log),
    ]
    for value in args.path:
        command.extend(("--path", value))
    return command


def run(command: list[str], environment: dict[str, str]) -> dict[str, object]:
    completed = subprocess.run(command, env=environment, text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError(
            "runtime smoke failed\n" + completed.stdout + "\n" + completed.stderr
        )
    report_index = command.index("--report") + 1
    return json.loads(Path(command[report_index]).read_text(encoding="utf-8"))


def response_objects(report: dict[str, object], endpoint: str) -> list[tuple[int, dict[str, object]]]:
    values: list[tuple[int, dict[str, object]]] = []
    for probe in report.get("probes", []):
        if not isinstance(probe, dict) or probe.get("endpoint") != endpoint:
            continue
        try:
            body = json.loads(str(probe.get("body", "{}")))
        except json.JSONDecodeError:
            continue
        if isinstance(body, dict):
            values.append((int(probe.get("status", 0)), body))
    return values


def main() -> int:
    args = parse_args()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.database.parent.mkdir(parents=True, exist_ok=True)
    cleanup_database(args.database)
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    policy.pop("$schema", None)
    replacement = {"expectedGeneration": 1, "policy": policy}
    spoofed = dict(replacement)
    spoofed["actor"] = "forged-administrator"
    environment = dict(os.environ)
    environment[OPERATOR_ENV] = "operator-online-capability-secret"
    environment[READER_ENV] = "reader-online-capability-secret"
    environment[DELEGATED_ENV] = "delegated-online-capability-secret"

    first_report = args.report.with_name(args.report.stem + "-first.json")
    first_log = args.report.with_name(args.report.stem + "-first.log")
    command = base_command(args, first_report, first_log)
    command.extend(("--post-interval", "0.05", "--post-health-interval", "0.05"))
    posts = [
        ("/api/v1/capabilities/validate", policy),
        ("/api/v1/capabilities/validate", policy),
        ("/api/v1/capabilities/validate", policy),
        ("/api/v1/capabilities/policy", spoofed),
        ("/api/v1/capabilities/policy", replacement),
        ("/api/v1/capabilities/policy", replacement),
        ("/api/v1/capabilities/policy", replacement),
        ("/api/v1/capabilities/policy", replacement),
    ]
    for endpoint, body in posts:
        command.extend(("--post", endpoint + "=" + json.dumps(body, separators=(",", ":"))))
    command.extend((
        "--post-omit-bearer", "1",
        "--post-response-status", "1=401",
        "--post-bearer-token-environment", f"2={READER_ENV}",
        "--post-response-status", "2=403",
        "--post-request-id", "4=capability-spoof-proof",
        "--post-response-status", "4=400",
        "--post-request-id", "5=capability-online-change-1",
        "--post-request-id", "6=capability-online-change-1",
        "--post-bearer-token-environment", f"7={DELEGATED_ENV}",
        "--post-request-id", "7=capability-dual-gate-proof",
        "--post-response-status", "7=403",
        "--post-request-id", "8=capability-stale-generation-proof",
        "--post-response-status", "8=409",
    ))
    first = run(command, environment)

    replacements = response_objects(first, "/api/v1/capabilities/policy")
    successful = [body for status, body in replacements if status == 200]
    codes = {str(body.get("code", "")) for _, body in replacements}
    if len(successful) != 2:
        raise RuntimeError("expected one online commit and one idempotent replay")
    if successful[0].get("actor") != "operator" or successful[0].get("idempotentReplay") is not False:
        raise RuntimeError("authenticated Principal was not bound as first commit actor")
    if successful[1].get("actor") != "operator" or successful[1].get("idempotentReplay") is not True:
        raise RuntimeError("online policy replay did not preserve authenticated actor")
    if any(item.get("policy", {}).get("generation") != 2 for item in successful):
        raise RuntimeError("online policy replacement did not commit generation two")
    required_codes = {
        "CAPABILITY_REQUEST_INVALID", "CAPABILITY_POLICY_DENIED", "CAPABILITY_REPLACE_CONFLICT"
    }
    if not required_codes.issubset(codes):
        raise RuntimeError(f"missing policy management failure evidence: {required_codes - codes}")
    validate_codes = {
        str(body.get("code", ""))
        for _, body in response_objects(first, "/api/v1/capabilities/validate")
    }
    if not {"CAPABILITY_AUTHENTICATION_REQUIRED", "CAPABILITY_PERMISSION_DENIED"}.issubset(validate_codes):
        raise RuntimeError("authentication or management permission denial was not observed")
    statuses = response_objects(first, "/api/v1/capabilities")
    if not any(body.get("policy", {}).get("generation") == 2 for _, body in statuses):
        raise RuntimeError("online status did not observe committed generation two")
    audits = response_objects(first, "/api/v1/capabilities/audit?limit=3")
    if not any(
        any(item.get("principal") == "operator" and item.get("resource") == "pdr.service.capabilityRuntime"
            for item in body.get("items", []))
        for _, body in audits
    ):
        raise RuntimeError("durable online capability authorization audit was not observed")

    recovery_report = args.report.with_name(args.report.stem + "-recovery.json")
    recovery_log = args.report.with_name(args.report.stem + "-recovery.log")
    recovery_command = base_command(args, recovery_report, recovery_log)
    recovery_command.extend((
        "--require-log", "generation 2",
        "--require-body", '"generation":2',
    ))
    recovery = run(recovery_command, environment)
    if not recovery.get("passed") or not recovery.get("shutdown", {}).get("clean"):
        raise RuntimeError("generation two restart recovery was not clean")

    result = {
        "schemaVersion": 1,
        "passed": True,
        "actorBinding": "operator",
        "generation": 2,
        "idempotentReplay": True,
        "authenticationDenied": True,
        "permissionDenied": True,
        "actorSpoofRejected": True,
        "dualGateDenied": True,
        "staleGenerationRejected": True,
        "durableAuditObserved": True,
        "restartRecovered": True,
        "firstShutdown": first.get("shutdown"),
        "recoveryShutdown": recovery.get("shutdown"),
    }
    args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("RUNTIME_CAPABILITY_MANAGEMENT_INTEGRATION_PASS generation=2 actor=operator")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"RUNTIME_CAPABILITY_MANAGEMENT_INTEGRATION_FAIL {error}", file=sys.stderr)
        raise SystemExit(1)
