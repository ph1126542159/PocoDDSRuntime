#!/usr/bin/env python3
"""Verify authenticated transactional schedule reconfiguration in a live Runtime."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


OPERATOR_ENV = "PDR_SCHEDULE_CONFIG_OPERATOR_TOKEN"
READER_ENV = "PDR_SCHEDULE_CONFIG_READER_TOKEN"
DENIED_ENV = "PDR_SCHEDULE_CONFIG_DENIED_TOKEN"
CONFIG_ENDPOINT = "/api/v1/configuration-transactions"
PREFLIGHT_ENDPOINT = CONFIG_ENDPOINT + "/preflight"
PARTICIPANTS_ENDPOINT = "/api/v1/configuration-participants"
PARTICIPANTS_INVALID_ENDPOINT = PARTICIPANTS_ENDPOINT + "?unexpected=true"
PARTICIPANTS_READER_ENDPOINT = PARTICIPANTS_ENDPOINT + "?as=reader"
SCHEDULER_ENDPOINT = "/api/v1/scheduled-tasks"
WORKFLOW_TASK = "pdr.service.workflowRuntime.runDue"
HEALTH_DETAIL_ENDPOINT = "/health/detail"
HEALTH_READY_ENDPOINT = "/health/ready"


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


def compact(value: object) -> str:
    return json.dumps(value, separators=(",", ":"))


def task_from(body: str) -> dict[str, object]:
    payload = json.loads(body)
    for task in payload.get("tasks", []):
        if isinstance(task, dict) and task.get("id") == WORKFLOW_TASK:
            return task
    raise RuntimeError("workflow task is missing from scheduler response")


def stage_probe(report: dict[str, object], endpoint: str, stage_prefix: str) -> dict[str, object]:
    matches = [probe for probe in report.get("probes", [])
               if isinstance(probe, dict) and probe.get("endpoint") == endpoint and
               str(probe.get("stage", "")).startswith(stage_prefix)]
    if not matches:
        raise RuntimeError(f"missing {endpoint} observation for {stage_prefix}")
    return matches[-1]


def main() -> int:
    args = parse_args()
    args.report = args.report.resolve()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    transaction_db = args.report.with_suffix(".transactions.sqlite")
    capability_db = args.report.with_suffix(".capabilities.sqlite")
    policy_path = args.report.with_suffix(".capability-policy.json")
    for database in (transaction_db, capability_db):
        for suffix in ("", "-wal", "-shm"):
            try:
                Path(str(database) + suffix).unlink()
            except FileNotFoundError:
                pass
    policy = {
        "version": 1,
        "defaultEffect": "deny",
        "rules": [
            {"id": "runtime-schema-bootstrap", "effect": "allow",
             "principal": "pdr.runtime-core", "resourceKind": "schema",
             "resource": "pdr.runtime.*", "actions": ["read", "register"]},
            {"id": "schedule-config-operator", "effect": "allow",
             "principal": "schedule-config-operator", "resourceKind": "configuration",
             "resource": "pdr.workflow.*", "actions": ["read", "write"]},
        ],
    }
    policy_path.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")

    environment = dict(os.environ)
    environment[OPERATOR_ENV] = "schedule-config-operator-secret"
    environment[READER_ENV] = "schedule-config-reader-secret"
    environment[DENIED_ENV] = "schedule-config-denied-secret"
    smoke_report = args.report.with_name(args.report.stem + "-runtime.json")
    log = args.report.with_name(args.report.stem + ".log")
    command = [
        args.python, str(args.runtime_smoke),
        "--executable", str(args.executable),
        "--working-directory", str(args.working_directory),
        "--config", str(args.config),
        "--port", "0", "--timeout", "20", "--stability-window", "1",
        "--shutdown-timeout", "10", "--clear-code-cache",
        "--bearer-token-environment", OPERATOR_ENV,
        "--set", "pdr.management.authentication.required=true",
        "--set", "pdr.management.authentication.principals.count=3",
        "--set", "pdr.management.authentication.principals.0.id=schedule-config-operator",
        "--set", f"pdr.management.authentication.principals.0.tokenEnvironment={OPERATOR_ENV}",
        "--set", "pdr.management.authentication.principals.0.permissions=*",
        "--set", "pdr.management.authentication.principals.1.id=schedule-config-reader",
        "--set", f"pdr.management.authentication.principals.1.tokenEnvironment={READER_ENV}",
        "--set", "pdr.management.authentication.principals.1.permissions=diagnostics.read",
        "--set", "pdr.management.authentication.principals.2.id=schedule-config-denied",
        "--set", f"pdr.management.authentication.principals.2.tokenEnvironment={DENIED_ENV}",
        "--set", "pdr.management.authentication.principals.2.permissions=configuration.manage",
        "--set", f"pdr.configurationRuntime.database={transaction_db.as_posix()}",
        "--set", f"pdr.capabilityRuntime.database={capability_db.as_posix()}",
        "--set", f"pdr.capabilityRuntime.policy={policy_path.as_posix()}",
        "--endpoint", CONFIG_ENDPOINT,
        "--endpoint", PARTICIPANTS_ENDPOINT,
        "--endpoint", PARTICIPANTS_INVALID_ENDPOINT,
        "--endpoint", PARTICIPANTS_READER_ENDPOINT,
        "--endpoint", SCHEDULER_ENDPOINT,
        "--endpoint", HEALTH_DETAIL_ENDPOINT,
        "--endpoint", HEALTH_READY_ENDPOINT,
        "--expect-status", CONFIG_ENDPOINT + "=200",
        "--expect-status", PARTICIPANTS_ENDPOINT + "=200",
        "--expect-status", PARTICIPANTS_INVALID_ENDPOINT + "=400",
        "--expect-status", PARTICIPANTS_READER_ENDPOINT + "=403",
        "--endpoint-bearer-token-environment",
        PARTICIPANTS_READER_ENDPOINT + "=" + READER_ENV,
        "--expect-status", SCHEDULER_ENDPOINT + "=200",
        "--expect-status", HEALTH_DETAIL_ENDPOINT + "=200",
        "--expect-status", HEALTH_READY_ENDPOINT + "=200",
        "--post-interval", "0.25", "--post-health-interval", "0.1",
        "--report", str(smoke_report), "--log", str(log),
    ]
    for value in args.path:
        command.extend(("--path", value))

    posts = [
        ({"expectedGeneration": 1, "changes": {
            "pdr.workflow.schedulerEnabled": "false",
            "pdr.workflow.schedulerIntervalMilliseconds": "250",
            "pdr.workflow.schedulerJitterMilliseconds": "10"}}, 200,
         OPERATOR_ENV, "preview-disable", PREFLIGHT_ENDPOINT),
        ({"expectedGeneration": 2, "changes": {
            "pdr.workflow.schedulerEnabled": "false"}}, 409,
         OPERATOR_ENV, "preview-stale", PREFLIGHT_ENDPOINT),
        ({"expectedGeneration": 1, "changes": {
            "pdr.workflow.schedulerEnabled": "false",
            "pdr.workflow.schedulerIntervalMilliseconds": "250",
            "pdr.workflow.schedulerJitterMilliseconds": "10"}}, 200,
         OPERATOR_ENV, "disable-workflow", CONFIG_ENDPOINT),
        ({"expectedGeneration": 2, "changes": {
            "pdr.workflow.schedulerJitterMilliseconds": "251"}}, 400,
         OPERATOR_ENV, "invalid-workflow", CONFIG_ENDPOINT),
        ({"expectedGeneration": 2, "changes": {
            "pdr.workflow.schedulerEnabled": "true",
            "pdr.workflow.schedulerIntervalMilliseconds": "50",
            "pdr.workflow.schedulerJitterMilliseconds": "0"}}, 200,
         OPERATOR_ENV, "enable-workflow", CONFIG_ENDPOINT),
        ({"expectedGeneration": 1, "changes": {
            "pdr.workflow.schedulerEnabled": "false",
            "pdr.workflow.schedulerIntervalMilliseconds": "250",
            "pdr.workflow.schedulerJitterMilliseconds": "10"}}, 200,
         OPERATOR_ENV, "disable-workflow", CONFIG_ENDPOINT),
        ({"expectedGeneration": 3, "changes": {
            "pdr.workflow.schedulerIntervalMilliseconds": "60"}}, 403,
         READER_ENV, "reader-denied", CONFIG_ENDPOINT),
        ({"expectedGeneration": 3, "changes": {
            "pdr.workflow.schedulerIntervalMilliseconds": "60"}}, 401,
         None, "anonymous-denied", CONFIG_ENDPOINT),
        ({"expectedGeneration": 3, "changes": {
            "pdr.outbox.schedulerEnabled": "false"}}, 403,
         DENIED_ENV, "capability-denied", CONFIG_ENDPOINT),
    ]
    for index, (body, status, token_environment, request_id, endpoint) in enumerate(posts, start=1):
        command.extend(("--post", endpoint + "=" + compact(body)))
        command.extend(("--post-response-status", f"{index}={status}"))
        command.extend(("--post-request-id", f"{index}={request_id}"))
        if token_environment is None:
            command.extend(("--post-omit-bearer", str(index)))
        elif token_environment != OPERATOR_ENV:
            command.extend(("--post-bearer-token-environment",
                            f"{index}={token_environment}"))

    completed = subprocess.run(command, env=environment, text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError("runtime smoke failed\n" + completed.stdout + "\n" + completed.stderr)
    report = json.loads(smoke_report.read_text(encoding="utf-8"))
    if not report.get("passed") or not report.get("shutdown", {}).get("clean"):
        raise RuntimeError("Runtime did not complete or shut down cleanly")

    initial_config = next(
        probe for probe in report["probes"]
        if probe.get("endpoint") == CONFIG_ENDPOINT and probe.get("method") is None)
    initial_body = json.loads(initial_config["body"])
    participants = set(initial_body.get("participants", []))
    if initial_body.get("generation") != 1 or not {
            "workflow-scheduler", "outbox-scheduler"}.issubset(participants):
        raise RuntimeError("configuration participants were not registered")
    initial_catalog_probe = next(
        probe for probe in report["probes"]
        if probe.get("endpoint") == PARTICIPANTS_ENDPOINT and probe.get("method") is None)
    initial_catalog = json.loads(initial_catalog_probe["body"])
    catalog_entries = initial_catalog.get("participants", [])
    catalog_ids = [entry.get("id") for entry in catalog_entries if isinstance(entry, dict)]
    if initial_catalog.get("participantCount") != len(catalog_entries) or \
            initial_catalog.get("schemaVersion") != 4 or \
            initial_catalog.get("generation", 0) < len(catalog_entries) or \
            len(initial_catalog.get("digest", "")) != 64 or \
            catalog_ids != sorted(catalog_ids) or \
            not participants.issubset(set(catalog_ids)) or \
            any(not entry.get("ownedPrefixes") or
                entry.get("registrationGeneration", 0) < 1 or
                entry.get("unresolvedAfter") != []
                for entry in catalog_entries if isinstance(entry, dict)):
        raise RuntimeError("configuration participant catalog is incomplete")
    if initial_catalog.get("admissionGeneration") != 0 or \
            initial_catalog.get("rejectedCount") != 0 or \
            initial_catalog.get("admissionOverflow") is not False or \
            initial_catalog.get("rejectedParticipants") != []:
        raise RuntimeError("valid configuration participants produced admission failures")
    declared = initial_catalog.get("declaredParticipants", [])
    declared_ids = {item.get("id") for item in declared if isinstance(item, dict)}
    if initial_catalog.get("expectationsReady") is not True or \
            initial_catalog.get("expectationGeneration", 0) < 1 or \
            initial_catalog.get("declaredParticipantCount") != len(declared) or \
            initial_catalog.get("declarationIssueCount") != 0 or \
            initial_catalog.get("declarationIssues") != [] or \
            not {"workflow-scheduler", "outbox-scheduler"}.issubset(declared_ids) or \
            any(item.get("status") != "satisfied" or
                item.get("ownerActive") is not True or item.get("code") != ""
                for item in declared if isinstance(item, dict)):
        raise RuntimeError("Bundle-local configuration participant expectations are incomplete")
    if initial_catalog.get("keyLifecyclesReady") is not True or \
            initial_catalog.get("keyLifecycleGeneration", 0) < 1 or \
            initial_catalog.get("keyLifecycleDeclarationCount", 0) < 2 or \
            initial_catalog.get("keyLifecycleEntryCount") != 0 or \
            initial_catalog.get("keyLifecycles") != [] or \
            initial_catalog.get("keyLifecycleIssueCount") != 0 or \
            initial_catalog.get("keyLifecycleIssues") != []:
        raise RuntimeError("Bundle-local configuration key lifecycle catalog is incomplete")
    initial_health_probe = next(
        probe for probe in report["probes"]
        if probe.get("endpoint") == HEALTH_DETAIL_ENDPOINT and
        probe.get("method") is None)
    initial_health = json.loads(initial_health_probe["body"])
    admission_health = next(
        (component for component in initial_health.get("components", [])
         if isinstance(component, dict) and
         component.get("name") == "configuration-participants"),
        None)
    if not admission_health or admission_health.get("status") != "UP" or \
            admission_health.get("code") != \
            "PDR-HEALTH-CONFIGURATION-PARTICIPANTS-UP":
        raise RuntimeError("configuration participant admission health is missing")

    preflight_responses = [probe for probe in report["probes"]
                           if probe.get("endpoint") == PREFLIGHT_ENDPOINT and
                           probe.get("method") == "POST"]
    preview = json.loads(preflight_responses[0]["body"])
    stale_preview = json.loads(preflight_responses[1]["body"])
    if preview.get("accepted") is not True or preview.get("changed") is not True or \
            preview.get("observedGeneration") != 1 or \
            preview.get("candidateGeneration") != 2 or \
            preview.get("participants") != ["workflow-scheduler"]:
        raise RuntimeError("configuration preflight result is incomplete")
    if stale_preview.get("accepted") is not False or \
            stale_preview.get("errorCode") != "generation-conflict" or \
            stale_preview.get("observedGeneration") != 1:
        raise RuntimeError("stale configuration preflight was not rejected")
    after_preview_config = json.loads(stage_probe(
        report, CONFIG_ENDPOINT, "post-1-")["body"])
    after_preview_task = task_from(stage_probe(
        report, SCHEDULER_ENDPOINT, "post-1-")["body"])
    if after_preview_config.get("generation") != 1 or \
            after_preview_config.get("history") or \
            after_preview_task.get("enabled") is not True:
        raise RuntimeError("configuration preflight mutated Runtime state")

    disabled_task = task_from(stage_probe(
        report, SCHEDULER_ENDPOINT, "post-3-")["body"])
    if disabled_task.get("enabled") is not False or \
            disabled_task.get("intervalMilliseconds") != 250 or \
            disabled_task.get("jitterMilliseconds") != 10 or \
            disabled_task.get("nextRunInMilliseconds") is not None:
        raise RuntimeError("committed disable transaction did not reconfigure scheduler")

    enabled_task = task_from(stage_probe(
        report, SCHEDULER_ENDPOINT, "post-5-")["body"])
    if enabled_task.get("enabled") is not True or \
            enabled_task.get("intervalMilliseconds") != 50 or \
            enabled_task.get("jitterMilliseconds") != 0:
        raise RuntimeError("committed enable transaction did not resume scheduler")

    post_responses = [probe for probe in report["probes"]
                      if probe.get("endpoint") == CONFIG_ENDPOINT and
                      probe.get("method") == "POST"]
    replay = json.loads(post_responses[3]["body"])
    if replay.get("idempotentReplay") is not True or replay.get("generation") != 2:
        raise RuntimeError("configuration patch idempotency replay contract failed")
    after_replay = task_from(stage_probe(
        report, SCHEDULER_ENDPOINT, "post-6-")["body"])
    if after_replay.get("enabled") is not True or \
            after_replay.get("intervalMilliseconds") != 50:
        raise RuntimeError("idempotent replay mutated the current schedule")
    final_config = json.loads(stage_probe(
        report, CONFIG_ENDPOINT, "post-9-")["body"])
    if final_config.get("generation") != 3:
        raise RuntimeError("rejected transactions changed configuration generation")
    final_catalog = json.loads(stage_probe(
        report, PARTICIPANTS_ENDPOINT, "post-9-")["body"])
    if final_catalog.get("generation") != initial_catalog.get("generation") or \
            final_catalog.get("digest") != initial_catalog.get("digest") or \
            final_catalog.get("admissionGeneration") != 0 or \
            final_catalog.get("rejectedCount") != 0 or \
            final_catalog.get("expectationGeneration") != \
                initial_catalog.get("expectationGeneration") or \
            final_catalog.get("expectationsReady") is not True:
        raise RuntimeError("configuration transactions changed participant topology")

    summary = {
        "schemaVersion": 1,
        "passed": True,
        "participants": sorted(participants),
        "participantCatalogObserved": True,
        "participantCatalogStrictQuery": True,
        "participantCatalogPermissionDenied": True,
        "participantCatalogGeneration": initial_catalog["generation"],
        "participantAdmissionObserved": True,
        "participantAdmissionHealthy": True,
        "participantExpectationsObserved": True,
        "participantExpectationsReady": True,
        "preflightSideEffectFree": True,
        "preflightGenerationConflict": True,
        "disableCommitted": True,
        "invalidRejected": True,
        "enableCommitted": True,
        "idempotentReplay": True,
        "permissionDenied": True,
        "authenticationRequired": True,
        "capabilityDenied": True,
        "finalGeneration": 3,
        "shutdownClean": True,
    }
    args.report.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print("RUNTIME_SCHEDULE_CONFIGURATION_PASS generation=3 transactional=true "
          "preflightSideEffectFree=true preflightRechecked=true")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"RUNTIME_SCHEDULE_CONFIGURATION_FAIL {error}", file=sys.stderr)
        raise SystemExit(1)
