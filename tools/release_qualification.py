#!/usr/bin/env python3
"""Create fail-closed, machine-readable PocoDDSRuntime release qualification evidence."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_REQUIRED_EVIDENCE = ("package", "upgrade", "identity", "persistence", "protocol")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.new")
    try:
        temporary.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def parse_ctest_log(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    current: str | None = None
    tests: list[dict[str, str]] = []
    started = None
    ended = None
    for line in text.splitlines():
        if line.startswith("Start testing:"):
            started = line.partition(":")[2].strip()
        elif line.startswith("End testing:"):
            ended = line.partition(":")[2].strip()
        match = re.match(r"^\d+/\d+ Test: (.+)$", line)
        if match:
            current = match.group(1).strip()
            continue
        status = re.match(r"^Test (Passed|Failed|Not Run)\.$", line)
        if status and current:
            tests.append({"name": current, "status": status.group(1).lower().replace(" ", "-")})
            current = None
    names = [item["name"] for item in tests]
    duplicate_names = sorted({name for name in names if names.count(name) > 1})
    counts = {status: sum(item["status"] == status for item in tests)
              for status in ("passed", "failed", "not-run")}
    return {"path": str(path), "sha256": sha256(path), "startedAtText": started,
            "endedAtText": ended, "total": len(tests), **counts,
            "duplicateNames": duplicate_names,
            "failedTests": [item["name"] for item in tests if item["status"] != "passed"]}


def git_state(source: Path) -> dict[str, Any]:
    def run(*arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", "-C", str(source), *arguments], capture_output=True,
                              text=True, check=False)
    revision = run("rev-parse", "HEAD")
    status = run("status", "--porcelain=v1", "--untracked-files=normal")
    if revision.returncode or status.returncode:
        return {"available": False, "clean": False, "commit": None,
                "error": (revision.stderr or status.stderr).strip()}
    changes = [line for line in status.stdout.splitlines() if line]
    tracked = subprocess.run(["git", "-C", str(source), "diff", "--name-only", "-z", "HEAD", "--"],
                             capture_output=True, check=False)
    untracked = subprocess.run(["git", "-C", str(source), "ls-files", "--others",
                                "--exclude-standard", "-z"], capture_output=True, check=False)
    paths = sorted(set(item.decode("utf-8", errors="surrogateescape")
                       for item in (tracked.stdout + untracked.stdout).split(b"\0") if item))
    fingerprint = hashlib.sha256()
    latest_epoch = 0.0
    latest_path = None
    for relative in paths:
        path = source / relative
        fingerprint.update(relative.encode("utf-8", errors="surrogateescape") + b"\0")
        if path.is_file():
            fingerprint.update(bytes.fromhex(sha256(path)))
            modified = path.stat().st_mtime
            if modified > latest_epoch:
                latest_epoch, latest_path = modified, relative
        else:
            fingerprint.update(b"<deleted>")
    return {"available": True, "clean": not changes, "commit": revision.stdout.strip(),
            "changeCount": len(changes), "worktreeSha256": fingerprint.hexdigest(),
            "latestChangeEpoch": latest_epoch, "latestChangedPath": latest_path}


def evidence_passed(document: Any) -> bool:
    if not isinstance(document, dict):
        return False
    if document.get("passed") is True or document.get("integrationPassed") is True:
        return True
    return str(document.get("verdict", "")).upper() in {
        "APPROVED", "PASS", "PASSED", "RELEASE_CANDIDATE_APPROVED"
    }


def verify_artifacts(manifest: Path, artifacts_root: Path | None) -> tuple[bool, str]:
    module_path = Path(__file__).resolve().with_name("release_manifest.py")
    spec = importlib.util.spec_from_file_location("pdr_release_manifest_qualification", module_path)
    if spec is None or spec.loader is None:
        return False, f"cannot load release manifest verifier: {module_path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    arguments = argparse.Namespace(
        manifest=manifest, artifacts=artifacts_root, signature=None, require_signature=False,
        trusted_key_environment=None, expected_key_id=None, public_key=None,
        expected_public_key_sha256=None, signature_check_executable=None,
    )
    output = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        result = module.verify(arguments)
    return result == 0, output.getvalue().strip()


def verify_external_acceptance(path: Path, signature: Path, trust_policy: Path,
                               expected_policy_id: str, expected_policy_sha256: str,
                               signature_verifier: Path, acceptance_type: str, version: str,
                               commit: str | None, manifest_sha256: str | None) -> dict[str, Any]:
    module_path = Path(__file__).resolve().with_name("external_acceptance.py")
    spec = importlib.util.spec_from_file_location("pdr_external_acceptance_qualification", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load external acceptance verifier: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.verify_signed_report(
        path, signature, trust_policy, expected_policy_id, expected_policy_sha256,
        signature_verifier, acceptance_type, version, commit, manifest_sha256)


def named_path(value: str) -> tuple[str, Path]:
    name, separator, raw_path = value.partition("=")
    if not separator or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        raise argparse.ArgumentTypeError("expected NAME=PATH")
    return name, Path(raw_path)


def qualify(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    generated = datetime.now(timezone.utc)
    source = args.source.resolve()
    test_log = args.ctest_log.resolve()
    tests = parse_ctest_log(test_log)
    test_age_hours = (generated.timestamp() - test_log.stat().st_mtime) / 3600
    tests["ageHours"] = round(max(0.0, test_age_hours), 3)
    tests["expectedTotal"] = args.expected_tests
    git = git_state(source)
    evidence: list[dict[str, Any]] = []
    local_failures: list[str] = []
    if tests["total"] != args.expected_tests:
        local_failures.append("CTEST_TOTAL_MISMATCH")
    if tests["failed"] or tests["not-run"] or tests["duplicateNames"]:
        local_failures.append("CTEST_NOT_ALL_PASSED")
    if not tests["startedAtText"] or not tests["endedAtText"]:
        local_failures.append("CTEST_LOG_INCOMPLETE")
    # Filesystem timestamps and the qualification host clock can differ slightly,
    # especially on copied Windows evidence. A larger future skew still fails closed.
    if test_age_hours < -(5.0 / 60.0) or test_age_hours > args.max_test_age_hours:
        local_failures.append("CTEST_EVIDENCE_STALE")
    latest_change = float(git.get("latestChangeEpoch", 0.0) or 0.0)
    if latest_change > test_log.stat().st_mtime + 2.0:
        local_failures.append("SOURCE_CHANGED_AFTER_CTEST")
    for name, raw_path in args.evidence:
        path = raw_path.resolve()
        item: dict[str, Any] = {"name": name, "path": str(path), "passed": False}
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            item.update({"sha256": sha256(path), "passed": evidence_passed(document)})
            if not item["passed"]:
                item["error"] = "report does not contain a passing verdict"
        except (OSError, ValueError) as error:
            item["error"] = str(error)
        if not item["passed"]:
            local_failures.append(f"EVIDENCE_FAILED:{name}")
        evidence.append(item)
    evidence_names = [item["name"] for item in evidence]
    if len(set(evidence_names)) != len(evidence_names):
        local_failures.append("EVIDENCE_NAME_DUPLICATE")
    required_evidence = args.required_evidence or list(DEFAULT_REQUIRED_EVIDENCE)
    for name in required_evidence:
        if name not in evidence_names:
            local_failures.append(f"EVIDENCE_MISSING:{name}")
    manifest = None
    if args.artifact_manifest:
        path = args.artifact_manifest.resolve()
        if path.is_file():
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
                artifacts_root = args.artifacts.resolve() if args.artifacts else None
                verified, verification_output = verify_artifacts(path, artifacts_root)
                manifest = {"path": str(path), "sha256": sha256(path), "present": True,
                            "verified": verified, "artifactRoot": str(
                                artifacts_root or Path(str(document.get("artifactRoot", ""))).resolve()),
                            "version": document.get("version"),
                            "gitCommit": document.get("gitCommit"),
                            "dirty": document.get("dirty"),
                            "cleanRequired": document.get("cleanRequired")}
                if not verified:
                    manifest["verificationError"] = verification_output
                    local_failures.append("ARTIFACT_MANIFEST_VERIFICATION_FAILED")
                if (document.get("version") != args.version or
                        (git.get("commit") and document.get("gitCommit") != git.get("commit"))):
                    local_failures.append("ARTIFACT_MANIFEST_IDENTITY_MISMATCH")
            except (OSError, ValueError) as error:
                manifest = {"path": str(path), "present": True, "verified": False,
                            "error": str(error)}
                local_failures.append("ARTIFACT_MANIFEST_INVALID")
        else:
            manifest = {"path": str(path), "present": False, "verified": False}
            local_failures.append("ARTIFACT_MANIFEST_MISSING")
    external = []
    if len({name for name, _ in args.external_evidence}) != len(args.external_evidence):
        local_failures.append("EXTERNAL_EVIDENCE_NAME_DUPLICATE")
    supplied_external = dict(args.external_evidence)
    supplied_signatures = dict(args.external_signature)
    for name in args.required_external:
        path = supplied_external.get(name)
        item: dict[str, Any] = {"name": name, "verified": False}
        if path:
            resolved = path.resolve()
            try:
                signature = supplied_signatures.get(name)
                required_trust = (signature, args.external_trust_policy,
                                  args.expected_external_trust_policy_id,
                                  args.expected_external_trust_policy_sha256,
                                  args.signature_check_executable)
                if any(value is None for value in required_trust):
                    raise ValueError("signed external acceptance and pinned trust policy are required")
                verification = verify_external_acceptance(
                    resolved, signature.resolve(), args.external_trust_policy.resolve(),
                    args.expected_external_trust_policy_id,
                    args.expected_external_trust_policy_sha256,
                    args.signature_check_executable.resolve(), name, args.version, git.get("commit"),
                    manifest.get("sha256") if manifest else None)
                item.update({"path": str(resolved), "sha256": sha256(resolved),
                             "signaturePath": str(signature.resolve()),
                             "signatureSha256": sha256(signature.resolve()),
                             "trustPolicyPath": str(args.external_trust_policy.resolve()),
                             "trustPolicySha256": sha256(args.external_trust_policy.resolve()),
                             "verified": True, "verification": verification})
            except (OSError, RuntimeError, ValueError) as error:
                item.update({"path": str(resolved), "error": str(error)})
        external.append(item)
    external_complete = all(item["verified"] for item in external)
    local_passed = not local_failures
    release_reasons = list(local_failures)
    if args.config.lower() != "release":
        release_reasons.append("CONFIGURATION_NOT_RELEASE")
    if not git.get("clean"):
        release_reasons.append("GIT_WORKTREE_NOT_CLEAN")
    if manifest is None:
        release_reasons.append("ARTIFACT_MANIFEST_NOT_PROVIDED")
    else:
        if manifest.get("dirty") is not False:
            release_reasons.append("ARTIFACT_MANIFEST_DIRTY")
        if manifest.get("cleanRequired") is not True:
            release_reasons.append("ARTIFACT_MANIFEST_NOT_CLEAN_REQUIRED")
    if not external_complete:
        release_reasons.append("EXTERNAL_ACCEPTANCE_INCOMPLETE")
    release_approved = not release_reasons
    if release_approved:
        verdict = "RELEASE_CANDIDATE_APPROVED"
    elif local_passed:
        verdict = "LOCAL_VALIDATION_PASSED"
    else:
        verdict = "DENIED"
    report = {
        "schemaVersion": 1, "operation": "release-qualification",
        "generatedAt": generated.isoformat(), "verdict": verdict,
        "passed": local_passed, "releaseApproved": release_approved,
        "source": str(source), "build": str(args.build.resolve()),
        "version": args.version, "configuration": args.config,
        "platform": {"system": platform.system(), "release": platform.release(),
                     "machine": platform.machine(), "python": platform.python_version()},
        "git": git, "tests": tests, "evidence": evidence,
        "requiredEvidence": required_evidence,
        "artifactManifest": manifest, "externalAcceptance": external,
        "localFailureReasons": local_failures, "releaseDenialReasons": release_reasons,
        "boundaries": [
            "Automated host tests do not prove target-board behavior or physical protocol devices.",
            "Windows results do not prove Linux cgroup v2 enforcement.",
            "Local TLS tests do not prove production PKI, OIDC, proxy or certificate rotation.",
            "A full-duration 24/72 hour soak requires separately supplied external evidence.",
        ],
    }
    if not local_passed:
        return report, 1
    if args.require_release_approval and not release_approved:
        return report, 2
    return report, 0


def add_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--source", required=True, type=Path)
    command.add_argument("--build", required=True, type=Path)
    command.add_argument("--version", required=True)
    command.add_argument("--config", default="Release")
    command.add_argument("--ctest-log", required=True, type=Path)
    command.add_argument("--expected-tests", required=True, type=int)
    command.add_argument("--max-test-age-hours", type=float, default=24.0)
    command.add_argument("--evidence", action="append", type=named_path, default=[])
    command.add_argument("--required-evidence", action="append", default=[])
    command.add_argument("--artifact-manifest", type=Path)
    command.add_argument("--artifacts", type=Path)
    command.add_argument("--required-external", action="append", default=[])
    command.add_argument("--external-evidence", action="append", type=named_path, default=[])
    command.add_argument("--external-signature", action="append", type=named_path, default=[])
    command.add_argument("--external-trust-policy", type=Path)
    command.add_argument("--expected-external-trust-policy-id")
    command.add_argument("--expected-external-trust-policy-sha256")
    command.add_argument("--signature-check-executable", type=Path)
    command.add_argument("--require-release-approval", action="store_true")
    command.add_argument("--report", required=True, type=Path)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    add_arguments(command)
    return command


def qualification_command(args: argparse.Namespace) -> int:
    try:
        report, result = qualify(args)
    except (OSError, ValueError) as error:
        report = {"schemaVersion": 1, "operation": "release-qualification",
                  "generatedAt": datetime.now(timezone.utc).isoformat(), "verdict": "DENIED",
                  "passed": False, "releaseApproved": False, "error": str(error)}
        result = 1
    atomic_json(args.report.resolve(), report)
    print(f"RELEASE_QUALIFICATION_{report['verdict']} report={args.report.resolve()}")
    return result


def main() -> int:
    return qualification_command(parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
