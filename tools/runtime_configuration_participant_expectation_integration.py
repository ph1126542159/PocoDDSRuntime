#!/usr/bin/env python3
"""Inject an active Bundle with a missing declared participant into an isolated Runtime."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile


TOKEN_ENV = "PDR_CONFIGURATION_EXPECTATION_TOKEN"
CATALOG_ENDPOINT = "/api/v1/configuration-participants"
DETAIL_ENDPOINT = "/health/detail"
READY_ENDPOINT = "/health/ready"


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


def write_fixture(repository: Path, bundle_tool: Path, fixture_root: Path) -> None:
    if not bundle_tool.is_file():
        raise RuntimeError(f"Bundle packaging tool is missing: {bundle_tool}")
    declaration = {
        "schemaVersion": 1,
        "participants": [{
            "id": "intentionally-missing-participant",
            "serviceName": "pdr.configuration.participant.intentionallyMissing",
            "ownedPrefixes": ["pdr.test.intentionallyMissing"],
            "after": [],
        }],
    }
    bundle_directory = fixture_root / "bundle"
    bundle_directory.mkdir(parents=True)
    (bundle_directory / "configuration-participants.json").write_text(
        json.dumps(declaration, indent=2) + "\n", encoding="utf-8")
    specification = fixture_root / "ExpectationFixture.bndlspec"
    specification.write_text("""<?xml version="1.0"?>
<bundlespec>
  <manifest>
    <name>Configuration Participant Expectation Integration Fixture</name>
    <symbolicName>pdr.test.configurationParticipantExpectation</symbolicName>
    <version>1.0.0</version>
    <vendor>PocoDDSRuntime Tests</vendor>
    <lazyStart>false</lazyStart>
    <runLevel>124</runLevel>
    <requiredBundles>
      <bundle><symbolicName>osp.core</symbolicName><version>[1.0.0,2.0.0)</version></bundle>
    </requiredBundles>
  </manifest>
  <files>bundle/*</files>
</bundlespec>
""", encoding="utf-8")
    completed = subprocess.run(
        [str(bundle_tool), f"/output-dir={repository}",
         f"/osname={'Windows_NT' if os.name == 'nt' else platform.system()}",
         f"/osarch={platform.machine()}", str(specification)],
        cwd=fixture_root, text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError("fixture Bundle packaging failed\n" +
                           completed.stdout + "\n" + completed.stderr)


def main() -> int:
    args = parse_args()
    args.report = args.report.resolve()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    source_repository = args.working_directory / "bundles"
    if not source_repository.is_dir():
        raise RuntimeError(f"Bundle repository is missing: {source_repository}")

    with tempfile.TemporaryDirectory(
            prefix="configuration-participant-expectation-",
            dir=args.report.parent) as temporary:
        working = Path(temporary)
        repository = working / "bundles"
        shutil.copytree(source_repository, repository)
        write_fixture(repository, args.working_directory / "bundle.exe",
                      working / "fixture-source")
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
            "--set", "pdr.management.authentication.principals.0.id=expectation-reader",
            "--set", f"pdr.management.authentication.principals.0.tokenEnvironment={TOKEN_ENV}",
            "--set", "pdr.management.authentication.principals.0.permissions=configuration.manage",
            "--endpoint", CATALOG_ENDPOINT,
            "--endpoint", DETAIL_ENDPOINT,
            "--expect-status", READY_ENDPOINT + "=503",
            "--expect-status", CATALOG_ENDPOINT + "=200",
            "--expect-status", DETAIL_ENDPOINT + "=200",
            "--require-body", "participant-required-missing",
            "--require-body", "PDR-HEALTH-CONFIGURATION-PARTICIPANT-REQUIRED-MISSING",
            "--require-body", "pdr.test.configurationParticipantExpectation",
            "--report", str(smoke_report), "--log", str(log),
        ]
        for path in args.path:
            command.extend(("--path", path))
        environment = dict(os.environ)
        environment[TOKEN_ENV] = "configuration-expectation-secret"
        completed = subprocess.run(
            command, env=environment, text=True, capture_output=True)
        if completed.returncode != 0:
            raise RuntimeError(
                "runtime smoke failed\n" + completed.stdout + "\n" + completed.stderr)
        report = json.loads(smoke_report.read_text(encoding="utf-8"))
        if not report.get("passed") or not report.get("shutdown", {}).get("clean"):
            raise RuntimeError("isolated Runtime did not pass and shut down cleanly")
        statuses = {probe.get("endpoint"): probe.get("status")
                    for probe in report.get("probes", [])}
        if statuses.get("/health/live") != 200 or \
                statuses.get(READY_ENDPOINT) != 503 or \
                statuses.get(CATALOG_ENDPOINT) != 200 or \
                statuses.get(DETAIL_ENDPOINT) != 200:
            raise RuntimeError("missing-participant health status contract failed")

    summary = {
        "schemaVersion": 1,
        "passed": True,
        "fixtureBundleActive": True,
        "requiredParticipantMissing": True,
        "catalogObserved": True,
        "healthDegraded": True,
        "readinessRejected": True,
        "livenessPreserved": True,
        "shutdownClean": True,
    }
    args.report.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print("RUNTIME_CONFIGURATION_PARTICIPANT_EXPECTATION_PASS "
          "missing=1 readiness503=1 liveness200=1 shutdownClean=1")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"RUNTIME_CONFIGURATION_PARTICIPANT_EXPECTATION_FAIL {error}",
              file=sys.stderr)
        raise SystemExit(1)
