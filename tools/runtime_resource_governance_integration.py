#!/usr/bin/env python3
"""Verify ResourceGovernor Bundle registration, least privilege and status contract."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


OPERATOR_ENV = "PDR_RESOURCE_GOVERNANCE_OPERATOR_TOKEN"
READER_ENV = "PDR_RESOURCE_GOVERNANCE_READER_TOKEN"
ENDPOINT = "/api/v1/resource-governance?owner=pdr.test.bundle"
WORKFLOW_ENDPOINT = "/api/v1/resource-governance?owner=pdr.service.workflowRuntime"
OUTBOX_ENDPOINT = "/api/v1/resource-governance?owner=pdr.service.outboxRuntime"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", required=True)
    parser.add_argument("--runtime-smoke", type=Path, required=True)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--working-directory", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args()


def base_command(args: argparse.Namespace, report: Path, log: Path) -> list[str]:
    command = [
        args.python, str(args.runtime_smoke),
        "--executable", str(args.executable),
        "--working-directory", str(args.working_directory),
        "--config", str(args.config),
        "--port", "0",
        "--timeout", "15",
        "--stability-window", "1",
        "--shutdown-timeout", "10",
        "--clear-code-cache",
        "--set", "pdr.management.authentication.required=true",
        "--set", "pdr.management.authentication.principals.count=2",
        "--set", "pdr.management.authentication.principals.0.id=resource-operator",
        "--set", f"pdr.management.authentication.principals.0.tokenEnvironment={OPERATOR_ENV}",
        "--set", "pdr.management.authentication.principals.0.permissions=resource.read",
        "--set", "pdr.management.authentication.principals.1.id=task-reader",
        "--set", f"pdr.management.authentication.principals.1.tokenEnvironment={READER_ENV}",
        "--set", "pdr.management.authentication.principals.1.permissions=task.read",
        "--set", "pdr.resourceGovernor.overrides.count=1",
        "--set", "pdr.resourceGovernor.overrides.0.owner=pdr.test.bundle",
        "--set", "pdr.resourceGovernor.overrides.0.maximumConcurrency=3",
        "--set", "pdr.resourceGovernor.overrides.0.queueCapacity=7",
        "--endpoint", ENDPOINT,
        "--require-log", "Bundle resource governor started with isolated owner lanes",
        "--report", str(report),
        "--log", str(log),
    ]
    for value in args.path:
        command.extend(("--path", value))
    return command


def run(command: list[str], environment: dict[str, str]) -> dict[str, object]:
    completed = subprocess.run(command, env=environment, text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError("runtime smoke failed\n" + completed.stdout + "\n" + completed.stderr)
    report = Path(command[command.index("--report") + 1])
    return json.loads(report.read_text(encoding="utf-8"))


def endpoint_body(report: dict[str, object], endpoint: str = ENDPOINT) -> dict[str, object]:
    for probe in report.get("probes", []):
        if isinstance(probe, dict) and probe.get("endpoint") == endpoint:
            try:
                body = json.loads(str(probe.get("body", "{}")))
            except json.JSONDecodeError:
                continue
            if isinstance(body, dict):
                return body
    raise RuntimeError(f"resource governance response body was not captured: {endpoint}")


def main() -> int:
    args = parse_args()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment[OPERATOR_ENV] = "resource-operator-integration-secret"
    environment[READER_ENV] = "task-reader-integration-secret"

    allowed_report = args.report.with_name(args.report.stem + "-allowed.json")
    allowed = base_command(args, allowed_report,
                           args.report.with_name(args.report.stem + "-allowed.log"))
    allowed.extend((
        "--probe-delay", "0.5",
        "--set", "pdr.resourceGovernor.overrides.count=3",
        "--set", "pdr.resourceGovernor.overrides.1.owner=pdr.service.workflowRuntime",
        "--set", "pdr.resourceGovernor.overrides.1.maximumConcurrency=1",
        "--set", "pdr.resourceGovernor.overrides.1.queueCapacity=1",
        "--set", "pdr.resourceGovernor.overrides.2.owner=pdr.service.outboxRuntime",
        "--set", "pdr.resourceGovernor.overrides.2.maximumConcurrency=1",
        "--set", "pdr.resourceGovernor.overrides.2.queueCapacity=1",
        "--endpoint", WORKFLOW_ENDPOINT,
        "--endpoint", OUTBOX_ENDPOINT,
        "--expect-status", ENDPOINT + "=200",
        "--expect-status", WORKFLOW_ENDPOINT + "=200",
        "--expect-status", OUTBOX_ENDPOINT + "=200",
        "--endpoint-bearer-token-environment", ENDPOINT + "=" + OPERATOR_ENV,
        "--endpoint-bearer-token-environment", WORKFLOW_ENDPOINT + "=" + OPERATOR_ENV,
        "--endpoint-bearer-token-environment", OUTBOX_ENDPOINT + "=" + OPERATOR_ENV,
        "--require-body", '"owner":"pdr.test.bundle"',
        "--require-body", '"maximumConcurrency":3',
        "--require-body", '"queueCapacity":7',
        "--require-body", '"cooperativeExecutionTimeout":true',
        "--require-body", '"hardThreadTermination":false',
    ))
    allowed_result = run(allowed, environment)
    body = endpoint_body(allowed_result)
    lanes = body.get("lanes", [])
    if body.get("principal") != "resource-operator" or body.get("laneCount") != 1 or \
            not isinstance(lanes, list) or len(lanes) != 1:
        raise RuntimeError("authenticated resource governance status contract mismatch")
    for endpoint, owner in ((WORKFLOW_ENDPOINT, "pdr.service.workflowRuntime"),
                            (OUTBOX_ENDPOINT, "pdr.service.outboxRuntime")):
        governed = endpoint_body(allowed_result, endpoint)
        governed_lanes = governed.get("lanes", [])
        if not isinstance(governed_lanes, list) or len(governed_lanes) != 1:
            raise RuntimeError(f"governed scheduler lane is missing: {owner}")
        lane = governed_lanes[0]
        if not isinstance(lane, dict) or lane.get("owner") != owner or \
                lane.get("maximumConcurrency") != 1 or lane.get("queueCapacity") != 1 or \
                int(lane.get("submitted", 0)) < 1 or int(lane.get("succeeded", 0)) < 1:
            raise RuntimeError(f"governed scheduler did not execute successfully: {owner}")

    denied_report = args.report.with_name(args.report.stem + "-denied.json")
    denied = base_command(args, denied_report,
                          args.report.with_name(args.report.stem + "-denied.log"))
    denied.extend((
        "--expect-status", ENDPOINT + "=403",
        "--endpoint-bearer-token-environment", ENDPOINT + "=" + READER_ENV,
        "--require-body", "RESOURCE_PERMISSION_DENIED",
    ))
    denied_result = run(denied, environment)

    anonymous_report = args.report.with_name(args.report.stem + "-anonymous.json")
    anonymous = base_command(args, anonymous_report,
                             args.report.with_name(args.report.stem + "-anonymous.log"))
    anonymous.extend((
        "--expect-status", ENDPOINT + "=401",
        "--require-body", "RESOURCE_AUTHENTICATION_REQUIRED",
    ))
    anonymous_result = run(anonymous, environment)

    for name, result in (("allowed", allowed_result), ("denied", denied_result),
                         ("anonymous", anonymous_result)):
        if not result.get("passed") or not result.get("shutdown", {}).get("clean"):
            raise RuntimeError(f"{name} Runtime did not shut down cleanly")

    summary = {
        "schemaVersion": 1,
        "passed": True,
        "serviceRegistered": True,
        "principal": "resource-operator",
        "leastPrivilegeDenied": True,
        "authenticationRequired": True,
        "configuredOwner": "pdr.test.bundle",
        "governedSchedulers": [
            "pdr.service.workflowRuntime",
            "pdr.service.outboxRuntime",
        ],
        "maximumConcurrency": 3,
        "queueCapacity": 7,
        "cooperativeExecutionTimeout": True,
        "hardThreadTermination": False,
        "shutdownsClean": True,
    }
    args.report.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print("RUNTIME_RESOURCE_GOVERNANCE_INTEGRATION_PASS owner=pdr.test.bundle concurrency=3")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"RUNTIME_RESOURCE_GOVERNANCE_INTEGRATION_FAIL {error}", file=sys.stderr)
        raise SystemExit(1)
