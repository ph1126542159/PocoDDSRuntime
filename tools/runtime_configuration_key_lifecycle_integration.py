#!/usr/bin/env python3
"""Inject an out-of-owner key lifecycle into an isolated Runtime Bundle repository."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile


TOKEN_ENV = "PDR_CONFIGURATION_KEY_LIFECYCLE_TOKEN"
CATALOG_ENDPOINT = "/api/v1/configuration-participants"
DETAIL_ENDPOINT = "/health/detail"
READY_ENDPOINT = "/health/ready"
RESOURCE = "configuration-key-lifecycle.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True)
    parser.add_argument("--runtime-smoke", required=True, type=Path)
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--working-directory", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--report", required=True, type=Path)
    return parser.parse_args()


def replace_resource(bundle: Path) -> None:
    invalid = json.dumps({
        "schemaVersion": 1,
        "entries": [{
            "id": "PDR-CFG-9001",
            "participantId": "workflow-scheduler",
            "operation": "rename",
            "sourceKey": "pdr.otherTeam.legacy",
            "replacementKey": "pdr.otherTeam.current",
            "deprecatedSince": "0.1.0",
            "removalAllowedFrom": "1.0.0",
        }],
    }, indent=2).encode("utf-8") + b"\n"
    temporary = bundle.with_suffix(bundle.suffix + ".new")
    with zipfile.ZipFile(bundle, "r") as source, zipfile.ZipFile(
            temporary, "w") as target:
        names = set(source.namelist())
        if RESOURCE not in names:
            raise RuntimeError(f"Workflow Bundle does not package {RESOURCE}")
        for info in source.infolist():
            payload = invalid if info.filename == RESOURCE else source.read(info.filename)
            target.writestr(info, payload)
    temporary.replace(bundle)


def main() -> int:
    args = parse_args()
    args.report = args.report.resolve()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    source_repository = args.working_directory / "bundles"
    if not source_repository.is_dir():
        raise RuntimeError(f"Bundle repository is missing: {source_repository}")

    with tempfile.TemporaryDirectory(
            prefix="configuration-key-lifecycle-",
            dir=args.report.parent) as temporary:
        working = Path(temporary)
        repository = working / "bundles"
        shutil.copytree(source_repository, repository)
        candidates = list(repository.glob("pdr.service.workflowRuntime_*.bndl"))
        if len(candidates) != 1:
            raise RuntimeError("Expected exactly one WorkflowRuntime Bundle")
        replace_resource(candidates[0])
        smoke_report = args.report.with_name(args.report.stem + "-runtime.json")
        log = args.report.with_suffix(".log")
        command = [
            args.python, str(args.runtime_smoke),
            "--executable", str(args.executable),
            "--working-directory", str(working),
            "--config", str(args.config),
            "--port", "0", "--timeout", "20", "--stability-window", "1",
            "--shutdown-timeout", "10", "--clear-code-cache",
            "--bearer-token-environment", TOKEN_ENV,
            "--set", f"osp.bundleRepository={repository.as_posix()}",
            "--set", "pdr.management.authentication.required=true",
            "--set", "pdr.management.authentication.principals.count=1",
            "--set", "pdr.management.authentication.principals.0.id=lifecycle-reader",
            "--set", f"pdr.management.authentication.principals.0.tokenEnvironment={TOKEN_ENV}",
            "--set", "pdr.management.authentication.principals.0.permissions=configuration.manage",
            "--endpoint", CATALOG_ENDPOINT,
            "--endpoint", DETAIL_ENDPOINT,
            "--expect-status", READY_ENDPOINT + "=503",
            "--expect-status", CATALOG_ENDPOINT + "=200",
            "--expect-status", DETAIL_ENDPOINT + "=200",
            "--require-body", "configuration-key-lifecycle-owner-mismatch",
            "--require-body", "PDR-HEALTH-CONFIGURATION-KEY-LIFECYCLE-INVALID",
            "--require-body", "PDR-CFG-9001",
            "--report", str(smoke_report), "--log", str(log),
        ]
        for path in args.path:
            command.extend(("--path", path))
        environment = dict(os.environ)
        environment[TOKEN_ENV] = "configuration-key-lifecycle-secret"
        completed = subprocess.run(
            command, env=environment, text=True, capture_output=True)
        if completed.returncode != 0:
            raise RuntimeError(
                "runtime smoke failed\n" + completed.stdout + "\n" + completed.stderr)
        report = json.loads(smoke_report.read_text(encoding="utf-8"))
        if not report.get("passed") or not report.get("shutdown", {}).get("clean"):
            raise RuntimeError("isolated Runtime did not pass and shut down cleanly")

    summary = {
        "schemaVersion": 1,
        "passed": True,
        "activeBundleLifecycleInvalid": True,
        "crossOwnerKeyRejected": True,
        "catalogObserved": True,
        "healthDegraded": True,
        "readinessRejected": True,
        "livenessPreserved": True,
        "shutdownClean": True,
    }
    args.report.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print("RUNTIME_CONFIGURATION_KEY_LIFECYCLE_PASS "
          "ownerMismatch=1 readiness503=1 liveness200=1 shutdownClean=1")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"RUNTIME_CONFIGURATION_KEY_LIFECYCLE_FAIL {error}", file=sys.stderr)
        raise SystemExit(1)
