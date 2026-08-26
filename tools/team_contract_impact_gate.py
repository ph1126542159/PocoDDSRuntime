#!/usr/bin/env python3
"""Execute team-contract impact tests and gate signed Consumer Owner approvals."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import team_contract_impact as impact_tool
import team_contract_package as package_tool


EVIDENCE_PRODUCT = "PocoDDSRuntimeTeamContractImpactExecutionEvidence"
APPROVAL_PRODUCT = "PocoDDSRuntimeTeamContractImpactApproval"
POLICY_PRODUCT = "PocoDDSRuntimeTeamContractImpactApprovalPolicy"
GATE_PRODUCT = "PocoDDSRuntimeTeamContractImpactGate"
MAX_APPROVAL_LIFETIME = 86400
MAX_SELECTED_TESTS = 512


def run_ctest(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Run CTest, preserving regex metacharacters for test batch shims on Windows."""
    executable = Path(command[0])
    if os.name == "nt" and executable.suffix.lower() in {".bat", ".cmd"}:
        if any(any(character in value for character in ('\n', '\r', '"', '%', '!'))
               for value in command):
            raise ValueError("Windows CTest batch shim arguments are unsafe")
        command_line = " ".join(f'"{value}"' for value in command)
        return subprocess.run(command_line, shell=True, **kwargs)
    return subprocess.run(command, **kwargs)


def impact_report(path: Path) -> tuple[dict[str, Any], str]:
    document, _ = impact_tool.load_json(path, "team contract upgrade impact report")
    impact_tool.validate_report(document)
    return document, impact_tool.canonical_sha(document)


def test_properties(test: dict[str, Any]) -> tuple[list[str], bool, str]:
    labels: list[str] = []
    disabled = False
    working_directory = ""
    for prop in test.get("properties", []):
        if not isinstance(prop, dict):
            continue
        if prop.get("name") == "LABELS" and isinstance(prop.get("value"), list):
            labels = sorted(set(str(value) for value in prop["value"]))
        elif prop.get("name") == "DISABLED":
            disabled = prop.get("value") is True
        elif prop.get("name") == "WORKING_DIRECTORY" and isinstance(prop.get("value"), str):
            working_directory = prop["value"]
    return labels, disabled, working_directory


def parse_ctest_catalog(content: str) -> list[dict[str, Any]]:
    try:
        catalog = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError("CTest catalog is invalid JSON") from error
    tests = catalog.get("tests") if isinstance(catalog, dict) else None
    if not isinstance(tests, list):
        raise ValueError("CTest catalog contains no test list")
    records: list[dict[str, Any]] = []
    names: set[str] = set()
    for test in tests:
        if (not isinstance(test, dict) or not isinstance(test.get("name"), str)
                or not test["name"] or not isinstance(test.get("command"), list)
                or not test["command"]):
            raise ValueError("CTest catalog contains a malformed test")
        if test["name"] in names:
            raise ValueError(f"CTest catalog repeats test name: {test['name']}")
        names.add(test["name"])
        labels, disabled, working_directory = test_properties(test)
        records.append({
            "name": test["name"],
            "labels": labels,
            "disabled": disabled,
            "commandSha256": impact_tool.canonical_sha({
                "command": test["command"], "workingDirectory": working_directory,
            }),
        })
    return sorted(records, key=lambda item: item["name"])


def selected_ctest_command(ctest: Path, test_dir: Path, config: str,
                           label_regex: str, junit: Path) -> list[str]:
    return [
        str(ctest), "--test-dir", str(test_dir), "-C", config,
        "-L", label_regex, "--output-on-failure", "--no-tests=error",
        "--output-junit", str(junit),
    ]


def parse_junit(path: Path, expected_tests: list[str]) -> str:
    path = package_tool.resolved_path(path, "team contract impact JUnit evidence")
    if not path.is_file():
        raise FileNotFoundError(f"CTest JUnit evidence is unavailable: {path}")
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as error:
        raise ValueError("CTest JUnit evidence is invalid XML") from error
    if root.tag != "testsuite":
        raise ValueError("CTest JUnit evidence root is not testsuite")
    try:
        totals = {field: int(root.attrib.get(field, "-1"))
                  for field in ("tests", "failures", "disabled", "skipped")}
    except ValueError as error:
        raise ValueError("CTest JUnit evidence counters are malformed") from error
    testcases = root.findall("testcase")
    names = sorted(str(item.attrib.get("name", "")) for item in testcases)
    if (totals["tests"] != len(expected_tests) or totals["failures"] != 0
            or totals["disabled"] != 0 or totals["skipped"] != 0
            or names != sorted(expected_tests)
            or any(item.attrib.get("status") != "run" for item in testcases)
            or any(item.find("failure") is not None or item.find("error") is not None
                   or item.find("skipped") is not None for item in testcases)):
        raise ValueError("CTest JUnit evidence does not prove every selected test passed")
    return package_tool.sha256_file(path)


def execute_command(args: argparse.Namespace) -> int:
    try:
        report, report_sha = impact_report(Path(args.report))
        if not report["compatible"]:
            raise ValueError("breaking team contract impact cannot enter execution gate")
        ctest = package_tool.resolved_path(args.ctest, "CTest executable")
        test_dir = package_tool.resolved_path(args.test_dir, "CTest test directory")
        if not ctest.is_file() or not test_dir.is_dir():
            raise ValueError("CTest executable or test directory is unavailable")
        labels = report["requiredTestLabels"]
        common = [str(ctest), "--test-dir", str(test_dir), "-C", args.config]
        if not labels:
            evidence = {
                "schemaVersion": 1,
                "product": EVIDENCE_PRODUCT,
                "operation": "team-contract-impact-execute",
                "passed": True,
                "impactReportSha256": report_sha,
                "impactInputSetSha256": report["inputSetSha256"],
                "candidateLockSha256": report["candidateLockSha256"],
                "requiredTestLabels": [],
                "ctestLabelRegex": None,
                "ctestConfig": args.config,
                "ctestExecutableSha256": package_tool.sha256_file(ctest),
                "ctestCatalogSha256": impact_tool.canonical_sha({"tests": []}),
                "ctestCommandSha256": impact_tool.canonical_sha({"command": []}),
                "executedTestCount": 0,
                "executedTests": [],
                "passedLabels": [],
                "junitSha256": None,
            }
            package_tool.write_json(Path(args.evidence).resolve(), evidence)
            print("PDR_TEAM_CONTRACT_IMPACT_EXECUTE_PASS tests=0")
            return 0
        selector = ["-L", report["ctestLabelRegex"]]
        query = run_ctest(
            [*common, *selector, "--show-only=json-v1"],
            capture_output=True, text=True, check=False,
        )
        if query.returncode != 0:
            raise ValueError((query.stderr or query.stdout).strip()
                             or "CTest selection query failed")
        records = parse_ctest_catalog(query.stdout)
        if not records or len(records) > MAX_SELECTED_TESTS:
            raise ValueError("CTest impact selection is empty or exceeds capacity")
        if any(item["disabled"] for item in records):
            raise ValueError("CTest impact selection contains disabled tests")
        covered = {label for item in records for label in item["labels"]}
        missing = sorted(set(labels) - covered)
        if missing:
            raise ValueError("CTest selection does not cover required labels: " + ", ".join(missing))
        junit = package_tool.resolved_path(args.junit, "team contract impact JUnit output")
        junit.parent.mkdir(parents=True, exist_ok=True)
        junit.unlink(missing_ok=True)
        command = selected_ctest_command(
            ctest, test_dir, args.config, report["ctestLabelRegex"], junit
        )
        run = run_ctest(command, check=False)
        if run.returncode != 0:
            raise ValueError(f"CTest execution failed with exit code {run.returncode}")
        names = [item["name"] for item in records]
        junit_sha = parse_junit(junit, names)
        evidence = {
            "schemaVersion": 1,
            "product": EVIDENCE_PRODUCT,
            "operation": "team-contract-impact-execute",
            "passed": True,
            "impactReportSha256": report_sha,
            "impactInputSetSha256": report["inputSetSha256"],
            "candidateLockSha256": report["candidateLockSha256"],
            "requiredTestLabels": labels,
            "ctestLabelRegex": report["ctestLabelRegex"],
            "ctestConfig": args.config,
            "ctestExecutableSha256": package_tool.sha256_file(ctest),
            "ctestCatalogSha256": impact_tool.canonical_sha({"tests": records}),
            "ctestCommandSha256": impact_tool.canonical_sha({"command": command}),
            "executedTestCount": len(records),
            "executedTests": records,
            "passedLabels": labels,
            "junitSha256": junit_sha,
        }
        validate_evidence(evidence, report, report_sha, junit)
        package_tool.write_json(Path(args.evidence).resolve(), evidence)
        print(f"PDR_TEAM_CONTRACT_IMPACT_EXECUTE_PASS tests={len(records)}")
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(f"PDR_TEAM_CONTRACT_IMPACT_EXECUTE_ERROR: {error}", file=sys.stderr)
        return 2


def validate_evidence(evidence: dict[str, Any], report: dict[str, Any],
                      report_sha: str, junit: Path | None) -> None:
    required = {
        "schemaVersion", "product", "operation", "passed", "impactReportSha256",
        "impactInputSetSha256", "candidateLockSha256", "requiredTestLabels",
        "ctestLabelRegex", "ctestConfig", "ctestExecutableSha256",
        "ctestCatalogSha256", "ctestCommandSha256", "executedTestCount",
        "executedTests", "passedLabels", "junitSha256",
    }
    if (not isinstance(evidence, dict) or set(evidence) != required
            or evidence.get("schemaVersion") != 1 or evidence.get("product") != EVIDENCE_PRODUCT
            or evidence.get("operation") != "team-contract-impact-execute"
            or evidence.get("passed") is not True
            or evidence.get("impactReportSha256") != report_sha
            or evidence.get("impactInputSetSha256") != report["inputSetSha256"]
            or evidence.get("candidateLockSha256") != report["candidateLockSha256"]
            or evidence.get("requiredTestLabels") != report["requiredTestLabels"]
            or evidence.get("ctestLabelRegex") != report["ctestLabelRegex"]
            or evidence.get("passedLabels") != report["requiredTestLabels"]
            or not isinstance(evidence.get("ctestConfig"), str) or not evidence["ctestConfig"]
            or any(not package_tool.SHA256.fullmatch(str(evidence.get(field, "")))
                   for field in ("ctestExecutableSha256", "ctestCatalogSha256",
                                 "ctestCommandSha256"))
            or type(evidence.get("executedTestCount")) is not int
            or not isinstance(evidence.get("executedTests"), list)
            or evidence["executedTestCount"] != len(evidence["executedTests"])):
        raise ValueError("team contract impact execution evidence is malformed or stale")
    if report["requiredTestLabels"]:
        records = evidence["executedTests"]
        if (not records or records != sorted(records, key=lambda item: item["name"])
                or any(not isinstance(item, dict)
                       or set(item) != {"name", "labels", "disabled", "commandSha256"}
                       or not isinstance(item.get("name"), str) or not item["name"]
                       or not isinstance(item.get("labels"), list)
                       or item.get("disabled") is not False
                       or not package_tool.SHA256.fullmatch(
                           str(item.get("commandSha256", ""))) for item in records)
                or not package_tool.SHA256.fullmatch(str(evidence.get("junitSha256", "")))
                or junit is None
                or parse_junit(junit, [item["name"] for item in records])
                    != evidence["junitSha256"]):
            raise ValueError("team contract impact executed test evidence is invalid")
    elif (evidence["executedTests"] or evidence["executedTestCount"] != 0
          or evidence["junitSha256"] is not None):
        raise ValueError("no-impact execution evidence must contain no tests")


def validate_current_ctest_binding(args: argparse.Namespace, evidence: dict[str, Any],
                                   report: dict[str, Any]) -> None:
    if not report["requiredTestLabels"]:
        return
    if not args.ctest or not args.test_dir:
        raise ValueError("impact gate requires CTest executable and test directory")
    ctest = package_tool.resolved_path(args.ctest, "CTest executable")
    test_dir = package_tool.resolved_path(args.test_dir, "CTest test directory")
    if (not ctest.is_file() or not test_dir.is_dir()
            or package_tool.sha256_file(ctest) != evidence["ctestExecutableSha256"]
            or args.config != evidence["ctestConfig"]):
        raise ValueError("impact gate CTest executable, directory or config changed")
    query = run_ctest(
        [str(ctest), "--test-dir", str(test_dir), "-C", args.config,
         "-L", report["ctestLabelRegex"], "--show-only=json-v1"],
        capture_output=True, text=True, check=False,
    )
    if query.returncode != 0:
        raise ValueError((query.stderr or query.stdout).strip()
                         or "impact gate CTest catalog query failed")
    records = parse_ctest_catalog(query.stdout)
    if (records != evidence["executedTests"]
            or impact_tool.canonical_sha({"tests": records})
                != evidence["ctestCatalogSha256"]):
        raise ValueError("impact gate CTest catalog changed after execution")
    junit = package_tool.resolved_path(args.junit, "team contract impact JUnit evidence")
    expected_command = selected_ctest_command(
        ctest, test_dir, args.config, report["ctestLabelRegex"], junit
    )
    if impact_tool.canonical_sha({"command": expected_command}) != \
            evidence["ctestCommandSha256"]:
        raise ValueError("impact gate CTest execution command changed after execution")


def policy(path: Path, expected_id: str, expected_sha: str) -> tuple[dict[str, Any], Path, str]:
    policy_path = package_tool.resolved_path(path, "team contract impact approval policy")
    document, actual_sha = impact_tool.load_json(
        policy_path, "team contract impact approval policy"
    )
    if (not package_tool.SHA256.fullmatch(str(expected_sha).lower())
            or actual_sha != str(expected_sha).lower()
            or document.get("policyId") != expected_id):
        raise ValueError("team contract impact approval policy identity is not trusted")
    validate_policy(document)
    return document, policy_path, actual_sha


def validate_policy(document: dict[str, Any]) -> None:
    required = {
        "schemaVersion", "product", "policyId", "maxApprovalLifetimeSeconds",
        "allowedApprovers", "revokedKeys",
    }
    if (not isinstance(document, dict) or set(document) != required
            or document.get("schemaVersion") != 1 or document.get("product") != POLICY_PRODUCT
            or not package_tool.IDENTIFIER.fullmatch(str(document.get("policyId", "")))
            or type(document.get("maxApprovalLifetimeSeconds")) is not int
            or not 60 <= document["maxApprovalLifetimeSeconds"] <= MAX_APPROVAL_LIFETIME
            or not isinstance(document.get("allowedApprovers"), list)
            or not document["allowedApprovers"]
            or not isinstance(document.get("revokedKeys"), list)):
        raise ValueError("team contract impact approval policy is malformed")
    approver_fields = {
        "owner", "approverId", "keyId", "algorithm", "publicKey",
        "publicKeySha256", "notBefore", "notAfter",
    }
    seen_keys: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    for item in document["allowedApprovers"]:
        pair = (str(item.get("owner", "")), str(item.get("approverId", ""))) \
            if isinstance(item, dict) else ("", "")
        if (not isinstance(item, dict) or set(item) != approver_fields
                or not package_tool.IDENTIFIER.fullmatch(pair[0])
                or not package_tool.IDENTIFIER.fullmatch(pair[1])
                or not package_tool.IDENTIFIER.fullmatch(str(item.get("keyId", "")))
                or item.get("algorithm") != "Ed25519"
                or not re.fullmatch(r"keys/[A-Za-z0-9._-]+\.pem", str(item.get("publicKey", "")))
                or not package_tool.SHA256.fullmatch(str(item.get("publicKeySha256", "")))
                or item.get("keyId") in seen_keys or pair in seen_pairs):
            raise ValueError("team contract impact approval policy approver is malformed")
        seen_keys.add(item["keyId"])
        seen_pairs.add(pair)
        if package_tool.parse_time(item["notBefore"], "approver notBefore") >= \
                package_tool.parse_time(item["notAfter"], "approver notAfter"):
            raise ValueError("team contract impact approver validity window is reversed")
    seen_revocations: set[str] = set()
    for item in document["revokedKeys"]:
        if (not isinstance(item, dict) or set(item) != {"keyId", "revokedAt", "reason"}
                or not package_tool.IDENTIFIER.fullmatch(str(item.get("keyId", "")))
                or not isinstance(item.get("reason"), str) or not item["reason"]
                or item["keyId"] in seen_revocations):
            raise ValueError("team contract impact key revocation is malformed")
        seen_revocations.add(item["keyId"])
        package_tool.parse_time(item["revokedAt"], "revokedAt")


def exclusive_json(path: Path, document: dict[str, Any]) -> None:
    path = path.absolute()
    if path.is_symlink():
        raise ValueError(f"approval output must not be a link: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    content = package_tool.json_bytes(document)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def approval_payload(approval: dict[str, Any]) -> bytes:
    return package_tool.canonical_bytes({
        key: value for key, value in approval.items() if key != "signature"
    })


def approve_command(args: argparse.Namespace) -> int:
    try:
        report, report_sha = impact_report(Path(args.report))
        if not report["compatible"]:
            raise ValueError("breaking team contract impact cannot be approved")
        required_owners = {item["owner"] for item in report["affectedConsumers"]}
        if args.owner not in required_owners:
            raise ValueError("approval Owner is not affected by this impact report")
        if (not package_tool.IDENTIFIER.fullmatch(args.approver_id)
                or not package_tool.IDENTIFIER.fullmatch(args.key_id)):
            raise ValueError("approval identity or key id is invalid")
        issued = package_tool.verification_time(args.issued_at)
        if not 60 <= args.lifetime_seconds <= MAX_APPROVAL_LIFETIME:
            raise ValueError("approval lifetime is outside the supported range")
        expires = issued + timedelta(seconds=args.lifetime_seconds)
        key_value = os.environ.get(args.private_key_environment)
        if not key_value:
            raise ValueError("approval private key path environment is unset")
        key_path = package_tool.resolved_path(key_value, "approval private key")
        passphrase = None
        if args.private_key_passphrase_environment:
            value = os.environ.get(args.private_key_passphrase_environment)
            if value is None:
                raise ValueError("approval private key passphrase environment is unset")
            passphrase = value.encode("utf-8")
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
        except ImportError as error:
            raise ValueError("Ed25519 approval requires the cryptography package") from error
        key = load_pem_private_key(key_path.read_bytes(), password=passphrase)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("team contract impact approval private key is not Ed25519")
        approval = {
            "schemaVersion": 1,
            "product": APPROVAL_PRODUCT,
            "operation": "team-contract-impact-approve",
            "decision": "approve",
            "impactReportSha256": report_sha,
            "impactInputSetSha256": report["inputSetSha256"],
            "candidateLockSha256": report["candidateLockSha256"],
            "owner": args.owner,
            "approverId": args.approver_id,
            "keyId": args.key_id,
            "issuedAt": issued.isoformat(),
            "expiresAt": expires.isoformat(),
        }
        approval["signature"] = base64.b64encode(
            key.sign(approval_payload(approval))
        ).decode("ascii")
        exclusive_json(Path(args.output), approval)
        print(f"PDR_TEAM_CONTRACT_IMPACT_APPROVE_PASS owner={args.owner}")
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(f"PDR_TEAM_CONTRACT_IMPACT_APPROVE_ERROR: {error}", file=sys.stderr)
        return 2


def verify_approvals(args: argparse.Namespace, report: dict[str, Any], report_sha: str,
                     at: datetime) -> tuple[dict[str, Any], list[dict[str, str]]]:
    policy_document, policy_path, policy_sha = policy(
        Path(args.approval_policy), args.expected_approval_policy_id,
        args.expected_approval_policy_sha256,
    )
    required_owners = sorted({item["owner"] for item in report["affectedConsumers"]})
    approval_paths = [package_tool.resolved_path(value, "impact Owner approval")
                      for value in args.approval]
    if len(approval_paths) != len(set(approval_paths)):
        raise ValueError("duplicate impact Owner approval path was supplied")
    revoked = {item["keyId"] for item in policy_document["revokedKeys"]}
    approved: list[dict[str, str]] = []
    seen_owners: set[str] = set()
    seen_people: set[str] = set()
    seen_keys: set[str] = set()
    for approval_path in approval_paths:
        approval, approval_sha = impact_tool.load_json(
            approval_path, "team contract impact Owner approval"
        )
        fields = {
            "schemaVersion", "product", "operation", "decision",
            "impactReportSha256", "impactInputSetSha256", "candidateLockSha256",
            "owner", "approverId", "keyId", "issuedAt", "expiresAt", "signature",
        }
        if (set(approval) != fields or approval.get("schemaVersion") != 1
                or approval.get("product") != APPROVAL_PRODUCT
                or approval.get("operation") != "team-contract-impact-approve"
                or approval.get("decision") != "approve"
                or approval.get("impactReportSha256") != report_sha
                or approval.get("impactInputSetSha256") != report["inputSetSha256"]
                or approval.get("candidateLockSha256") != report["candidateLockSha256"]):
            raise ValueError("team contract impact Owner approval is malformed or stale")
        owner = str(approval.get("owner", ""))
        approver_id = str(approval.get("approverId", ""))
        key_id = str(approval.get("keyId", ""))
        if (owner not in required_owners or owner in seen_owners
                or approver_id in seen_people or key_id in seen_keys):
            raise ValueError("impact approvals require distinct affected Owners, people and keys")
        issued = package_tool.parse_time(approval.get("issuedAt"), "approval issuedAt")
        expires = package_tool.parse_time(approval.get("expiresAt"), "approval expiresAt")
        if (issued > at + timedelta(minutes=5) or at >= expires or issued >= expires
                or (expires - issued).total_seconds()
                    > policy_document["maxApprovalLifetimeSeconds"]):
            raise ValueError("team contract impact Owner approval is expired or too long")
        matches = [item for item in policy_document["allowedApprovers"]
                   if item["owner"] == owner and item["approverId"] == approver_id
                   and item["keyId"] == key_id]
        if len(matches) != 1 or key_id in revoked:
            raise ValueError("team contract impact Owner approver is not trusted or is revoked")
        approver = matches[0]
        if (at < package_tool.parse_time(approver["notBefore"], "approver notBefore")
                or at >= package_tool.parse_time(approver["notAfter"], "approver notAfter")
                or issued < package_tool.parse_time(approver["notBefore"], "approver notBefore")
                or issued >= package_tool.parse_time(approver["notAfter"], "approver notAfter")):
            raise ValueError("team contract impact approver key is outside its validity window")
        public_key = package_tool.policy_public_key(policy_path, approver["publicKey"])
        public_sha = package_tool.sha256_file(public_key)
        if public_sha != approver["publicKeySha256"]:
            raise ValueError("team contract impact approval public key SHA-256 is not trusted")
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            from cryptography.hazmat.primitives.serialization import load_pem_public_key
            key = load_pem_public_key(public_key.read_bytes())
            if not isinstance(key, Ed25519PublicKey):
                raise ValueError("approval public key is not Ed25519")
            signature = base64.b64decode(approval["signature"], validate=True)
            key.verify(signature, approval_payload(approval))
        except Exception as error:
            raise ValueError("team contract impact Owner approval signature failed") from error
        seen_owners.add(owner)
        seen_people.add(approver_id)
        seen_keys.add(key_id)
        approved.append({
            "owner": owner, "approverId": approver_id, "keyId": key_id,
            "approvalSha256": approval_sha, "publicKeySha256": public_sha,
        })
    missing = sorted(set(required_owners) - seen_owners)
    if missing:
        raise ValueError("team contract impact Owner approvals are missing: " + ", ".join(missing))
    return {"policyId": policy_document["policyId"], "policySha256": policy_sha}, \
        sorted(approved, key=lambda item: item["owner"])


def gate_command(args: argparse.Namespace) -> int:
    try:
        report, report_sha = impact_report(Path(args.report))
        if not report["compatible"]:
            raise ValueError("breaking team contract impact cannot pass the acceptance gate")
        evidence_path = package_tool.resolved_path(args.evidence, "impact execution evidence")
        evidence, evidence_sha = impact_tool.load_json(
            evidence_path, "team contract impact execution evidence"
        )
        junit = Path(args.junit) if report["requiredTestLabels"] else None
        validate_evidence(evidence, report, report_sha, junit)
        validate_current_ctest_binding(args, evidence, report)
        at = package_tool.verification_time(args.verification_time)
        runner_arguments = (
            args.runner_attestation, args.runner_trust_policy,
            args.expected_runner_trust_policy_id,
            args.expected_runner_trust_policy_sha256,
        )
        if any(runner_arguments):
            if not all(runner_arguments):
                raise ValueError("runner attestation requires a fully pinned runner trust policy")
            import team_contract_provenance as provenance_tool
            runner_evidence = provenance_tool.verify_runner_attestation(
                args.runner_attestation, args.report, args.evidence,
                args.junit if report["requiredTestLabels"] else None,
                args.runner_trust_policy, args.expected_runner_trust_policy_id,
                args.expected_runner_trust_policy_sha256, args.verification_time,
            )
        else:
            runner_evidence = None
        required_owners = sorted({item["owner"] for item in report["affectedConsumers"]})
        if required_owners:
            if (not args.approval_policy or not args.expected_approval_policy_id
                    or not args.expected_approval_policy_sha256 or not args.approval):
                raise ValueError("affected Consumers require pinned signed Owner approvals")
            policy_evidence, approvals = verify_approvals(args, report, report_sha, at)
        else:
            if (args.approval_policy or args.expected_approval_policy_id
                    or args.expected_approval_policy_sha256 or args.approval):
                raise ValueError("no-impact gate must not accept unrelated approvals")
            policy_evidence, approvals = None, []
        gate = {
            "schemaVersion": 1,
            "product": GATE_PRODUCT,
            "operation": "team-contract-impact-gate",
            "passed": True,
            "impactReportSha256": report_sha,
            "impactInputSetSha256": report["inputSetSha256"],
            "candidateLockSha256": report["candidateLockSha256"],
            "executionEvidenceSha256": evidence_sha,
            "junitSha256": evidence["junitSha256"],
            "runnerAttestation": runner_evidence,
            "approvalPolicy": policy_evidence,
            "requiredOwners": required_owners,
            "approvedOwners": [item["owner"] for item in approvals],
            "approvals": approvals,
        }
        package_tool.write_json(Path(args.gate_report).resolve(), gate)
        print(
            f"PDR_TEAM_CONTRACT_IMPACT_GATE_PASS tests={evidence['executedTestCount']} "
            f"owners={len(approvals)}"
        )
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(f"PDR_TEAM_CONTRACT_IMPACT_GATE_ERROR: {error}", file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    execute = commands.add_parser("execute", help="run every CTest selected by an impact report")
    execute.add_argument("--report", required=True)
    execute.add_argument("--ctest", required=True)
    execute.add_argument("--test-dir", required=True)
    execute.add_argument("--config", default="Release")
    execute.add_argument("--evidence", required=True)
    execute.add_argument("--junit", required=True)
    execute.set_defaults(handler=execute_command)
    approve = commands.add_parser("approve", help="sign one affected Consumer Owner approval")
    approve.add_argument("--report", required=True)
    approve.add_argument("--owner", required=True)
    approve.add_argument("--approver-id", required=True)
    approve.add_argument("--key-id", required=True)
    approve.add_argument("--private-key-environment", required=True)
    approve.add_argument("--private-key-passphrase-environment")
    approve.add_argument("--issued-at")
    approve.add_argument("--lifetime-seconds", type=int, default=3600)
    approve.add_argument("--output", required=True)
    approve.set_defaults(handler=approve_command)
    gate = commands.add_parser("gate", help="bind execution evidence and all Owner approvals")
    gate.add_argument("--report", required=True)
    gate.add_argument("--evidence", required=True)
    gate.add_argument("--junit", required=True)
    gate.add_argument("--ctest")
    gate.add_argument("--test-dir")
    gate.add_argument("--config", default="Release")
    gate.add_argument("--approval-policy")
    gate.add_argument("--expected-approval-policy-id")
    gate.add_argument("--expected-approval-policy-sha256")
    gate.add_argument("--approval", action="append", default=[])
    gate.add_argument("--runner-attestation")
    gate.add_argument("--runner-trust-policy")
    gate.add_argument("--expected-runner-trust-policy-id")
    gate.add_argument("--expected-runner-trust-policy-sha256")
    gate.add_argument("--verification-time")
    gate.add_argument("--gate-report", required=True)
    gate.set_defaults(handler=gate_command)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
