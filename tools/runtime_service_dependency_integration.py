#!/usr/bin/env python3
"""Verify Bundle-local Service contracts, auth and readiness contribution."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess


READER_ENV = "PDR_SERVICE_DEPENDENCY_READER_TOKEN"
DENIED_ENV = "PDR_SERVICE_DEPENDENCY_DENIED_TOKEN"
ALLOWED = "/api/v1/service-dependencies?contract=pdr.scheduling"
DENIED = "/api/v1/service-dependencies?owner=pdr.service.workflowRuntime"
ANONYMOUS = "/api/v1/service-dependencies"
INVALID = "/api/v1/service-dependencies?unexpected=value"
HEALTH = "/health/detail"
START_IMPACT = ("/api/v1/service-dependencies/impact?action=start&"
                "target=pdr.service.workflowRuntime")
STOP_IMPACT = ("/api/v1/service-dependencies/impact?action=stop&"
               "target=pdr.service.schedulerRuntime")
INVALID_IMPACT = "/api/v1/service-dependencies/impact?action=remove&target=bad"


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


def probe_body(report: dict[str, object], endpoint: str) -> dict[str, object]:
    for probe in report.get("probes", []):
        if isinstance(probe, dict) and probe.get("endpoint") == endpoint:
            body = json.loads(str(probe.get("body", "{}")))
            if isinstance(body, dict):
                return body
    raise RuntimeError(f"missing endpoint response: {endpoint}")


def main() -> int:
    args = parse_args()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    live_report = args.report.with_name(args.report.stem + "-live.json")
    log = args.report.with_name(args.report.stem + ".log")
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
        "--set", "pdr.management.authentication.principals.0.id=dependency-reader",
        "--set", f"pdr.management.authentication.principals.0.tokenEnvironment={READER_ENV}",
        "--set", "pdr.management.authentication.principals.0.permissions=resource.read,bundle.manage",
        "--set", "pdr.management.authentication.principals.1.id=task-reader",
        "--set", f"pdr.management.authentication.principals.1.tokenEnvironment={DENIED_ENV}",
        "--set", "pdr.management.authentication.principals.1.permissions=task.read",
        "--endpoint", ALLOWED,
        "--endpoint", DENIED,
        "--endpoint", ANONYMOUS,
        "--endpoint", INVALID,
        "--endpoint", HEALTH,
        "--endpoint", START_IMPACT,
        "--endpoint", STOP_IMPACT,
        "--endpoint", INVALID_IMPACT,
        "--expect-status", ALLOWED + "=200",
        "--expect-status", DENIED + "=403",
        "--expect-status", ANONYMOUS + "=401",
        "--expect-status", INVALID + "=400",
        "--expect-status", HEALTH + "=200",
        "--expect-status", START_IMPACT + "=200",
        "--expect-status", STOP_IMPACT + "=200",
        "--expect-status", INVALID_IMPACT + "=400",
        "--endpoint-bearer-token-environment", ALLOWED + "=" + READER_ENV,
        "--endpoint-bearer-token-environment", DENIED + "=" + DENIED_ENV,
        "--endpoint-bearer-token-environment", INVALID + "=" + READER_ENV,
        "--endpoint-bearer-token-environment", START_IMPACT + "=" + READER_ENV,
        "--endpoint-bearer-token-environment", STOP_IMPACT + "=" + READER_ENV,
        "--endpoint-bearer-token-environment", INVALID_IMPACT + "=" + READER_ENV,
        "--require-body", '"scope":"runtime-process/bundle-service-contracts"',
        "--require-body", '"contract":"pdr.scheduling"',
        "--require-body", '"requiredBlocked":0',
        "--require-body", '"declarationErrors":0',
        "--require-body", '"name":"service-dependencies"',
        "--require-body", "SERVICE_DEPENDENCY_PERMISSION_DENIED",
        "--require-body", "SERVICE_DEPENDENCY_AUTHENTICATION_REQUIRED",
        "--require-body", "SERVICE_DEPENDENCY_QUERY_INVALID",
        "--require-body", "SERVICE_DEPENDENCY_IMPACT_QUERY_INVALID",
        "--require-body", "PDR-BUNDLE-DEPENDENCY-START_BLOCKED",
        "--require-body", "PDR-BUNDLE-DEPENDENCY-STOP_BLOCKED",
        "--require-log", "Service dependency runtime started with Bundle-local contract discovery",
        "--report", str(live_report),
        "--log", str(log),
    ]
    lifecycle_posts = [
        {"id": "pdr.service.schedulerRuntime", "action": "stop"},
        {"id": "pdr.service.workflowRuntime", "action": "stop"},
        {"id": "pdr.service.schedulerRuntime", "action": "stop"},
        {"id": "pdr.service.outboxRuntime", "action": "stop"},
        {"id": "pdr.service.schedulerRuntime", "action": "stop"},
        {"id": "pdr.service.workflowRuntime", "action": "start"},
        {"id": "pdr.service.schedulerRuntime", "action": "start"},
        {"id": "pdr.service.workflowRuntime", "action": "start"},
        {"id": "pdr.service.outboxRuntime", "action": "start"},
    ]
    expected_post_statuses = [400, 200, 400, 200, 200, 400, 200, 200, 200]
    for index, (post, expected) in enumerate(
            zip(lifecycle_posts, expected_post_statuses), start=1):
        command.extend((
            "--post", "/api/v1/bundle-lifecycle=" + json.dumps(post),
            "--post-response-status", f"{index}={expected}",
            "--post-bearer-token-environment", f"{index}={READER_ENV}",
        ))
    for value in args.path:
        command.extend(("--path", value))

    environment = dict(os.environ)
    environment[READER_ENV] = "service-dependency-reader-secret"
    environment[DENIED_ENV] = "service-dependency-denied-secret"
    completed = subprocess.run(command, env=environment, text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError(
            "runtime service dependency integration failed\n" +
            completed.stdout + "\n" + completed.stderr)

    report = json.loads(live_report.read_text(encoding="utf-8"))
    allowed = probe_body(report, ALLOWED)
    providers = allowed.get("providers", [])
    requirements = allowed.get("requirements", [])
    if allowed.get("principal") != "dependency-reader" or \
            allowed.get("ready") is not True or \
            int(allowed.get("requiredBlocked", -1)) != 0 or \
            int(allowed.get("declarationErrors", -1)) != 0 or \
            int(allowed.get("providerCount", -1)) != 1 or \
            int(allowed.get("requirementCount", -1)) != 2 or \
            not isinstance(providers, list) or not isinstance(requirements, list):
        raise RuntimeError("service dependency snapshot contract mismatch")
    provider = providers[0]
    if not isinstance(provider, dict) or provider.get("state") != "ready" or \
            provider.get("owner") != "pdr.service.schedulerRuntime":
        raise RuntimeError("scheduling provider is not ready or has the wrong owner")
    expected_owners = {"pdr.service.workflowRuntime", "pdr.service.outboxRuntime"}
    observed_owners = {
        str(item.get("owner")) for item in requirements
        if isinstance(item, dict) and item.get("status") == "satisfied" and
        item.get("required") is True and int(item.get("readyProviders", 0)) >= 1
    }
    if observed_owners != expected_owners:
        raise RuntimeError("scheduling Consumer requirements are incomplete")

    start_impact = probe_body(report, START_IMPACT)
    if start_impact.get("allowed") is not True or \
            int(start_impact.get("blockerCount", -1)) != 0:
        raise RuntimeError("healthy Consumer start was incorrectly blocked")
    stop_impact = probe_body(report, STOP_IMPACT)
    affected = set(map(str, stop_impact.get("affectedConsumers", [])))
    if stop_impact.get("allowed") is not False or \
            int(stop_impact.get("blockerCount", -1)) != 2 or \
            affected != expected_owners:
        raise RuntimeError("Provider stop impact did not identify active Consumers")

    lifecycle_results = [
        probe for probe in report.get("probes", [])
        if isinstance(probe, dict) and
        probe.get("endpoint") == "/api/v1/bundle-lifecycle" and
        probe.get("method") == "POST"
    ]
    observed_statuses = [int(item.get("status", 0)) for item in lifecycle_results]
    if observed_statuses != expected_post_statuses:
        raise RuntimeError(
            f"lifecycle admission status sequence mismatch: {observed_statuses}")

    health = probe_body(report, HEALTH)
    components = health.get("components", [])
    dependency_health = next((
        item for item in components
        if isinstance(item, dict) and item.get("name") == "service-dependencies"
    ), None)
    if not isinstance(dependency_health, dict) or \
            dependency_health.get("status") != "UP" or \
            "0 required blocked" not in str(dependency_health.get("detail", "")):
        raise RuntimeError("service dependency readiness was not propagated to health")
    shutdown = report.get("shutdown", {})
    if not report.get("passed") or not isinstance(shutdown, dict) or \
            not shutdown.get("clean"):
        raise RuntimeError("Runtime did not finish and shut down cleanly")

    summary = {
        "schemaVersion": 1,
        "passed": True,
        "generation": allowed.get("generation"),
        "providerCount": allowed.get("providerCount"),
        "requirementCount": allowed.get("requirementCount"),
        "requiredBlocked": 0,
        "declarationErrors": 0,
        "providerOwnerVerified": True,
        "consumerOwners": sorted(expected_owners),
        "readinessPropagated": True,
        "startAdmissionAllowedHealthyConsumer": True,
        "providerStopImpactConsumers": sorted(expected_owners),
        "providerStopEnforced": True,
        "inactiveConsumersDoNotBlockStop": True,
        "startAdmissionBlockedMissingProvider": True,
        "lifecycleRecoveryVerified": True,
        "leastPrivilegeDenied": True,
        "authenticationRequired": True,
        "invalidFilterRejected": True,
        "cleanShutdown": True,
        "liveReport": str(live_report),
        "log": str(log),
    }
    args.report.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        "RUNTIME_SERVICE_DEPENDENCY_PASS providers=1 requirements=2 "
        "requiredBlocked=0 lifecycleTransitions=9")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
