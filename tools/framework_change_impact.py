#!/usr/bin/env python3
"""Plan and gate fail-closed affected-component CI for the framework repository."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any


ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
OWNER = re.compile(r"^team/[a-z0-9][a-z0-9-]*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def atomic_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def document_digest(document: dict[str, Any]) -> str:
    payload = json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def normalized_path(value: str) -> str:
    text = value.strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    path = PurePosixPath(text)
    if (not text or path.is_absolute() or re.match(r"^[A-Za-z]:", text) or
            any(part in {"", ".", ".."} for part in path.parts)):
        raise ValueError(f"changed path is unsafe: {value}")
    return path.as_posix()


def matches(rule: str, path: str) -> bool:
    return (path == rule[:-1] or path.startswith(rule)) if rule.endswith("/") else path == rule


def load_catalog(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if (document.get("schemaVersion") != 1 or
            document.get("product") != "PocoDDSRuntimeFrameworkComponents" or
            not isinstance(document.get("globalPaths"), list) or
            not isinstance(document.get("components"), list) or
            not document["components"]):
        raise ValueError("framework component catalog is malformed")
    ids: set[str] = set()
    build_targets: dict[str, str] = {}
    rules: list[tuple[str, str]] = []
    for component in document["components"]:
        if (not isinstance(component, dict) or not ID.fullmatch(str(component.get("id", ""))) or
                not OWNER.fullmatch(str(component.get("owner", "")))):
            raise ValueError("framework component identity or owner is malformed")
        component_id = component["id"]
        if component_id in ids:
            raise ValueError(f"duplicate framework component id: {component_id}")
        ids.add(component_id)
        for field in ("paths", "requires", "buildTargets", "testLabels"):
            if not isinstance(component.get(field), list):
                raise ValueError(f"framework component {component_id} has malformed {field}")
        if not component["paths"] or not component["testLabels"]:
            raise ValueError(f"framework component {component_id} lacks paths or test labels")
        for rule in component["paths"]:
            if not isinstance(rule, str) or normalized_path(rule.rstrip("/")) != rule.rstrip("/"):
                raise ValueError(f"framework component {component_id} has unsafe path rule")
            rules.append((rule, component_id))
        for target in component["buildTargets"]:
            if not isinstance(target, str) or not target.strip():
                raise ValueError(
                    f"framework component {component_id} has malformed build target"
                )
            if target in build_targets:
                raise ValueError(
                    f"framework build target {target} is owned by both "
                    f"{build_targets[target]} and {component_id}"
                )
            build_targets[target] = component_id
    for component in document["components"]:
        for dependency in component["requires"]:
            if dependency not in ids or dependency == component["id"]:
                raise ValueError(
                    f"framework component {component['id']} has invalid dependency {dependency}"
                )
    visiting: set[str] = set()
    visited: set[str] = set()
    by_id = {item["id"]: item for item in document["components"]}

    def visit(component_id: str) -> None:
        if component_id in visiting:
            raise ValueError(f"framework component dependency cycle includes {component_id}")
        if component_id in visited:
            return
        visiting.add(component_id)
        for dependency in by_id[component_id]["requires"]:
            visit(dependency)
        visiting.remove(component_id)
        visited.add(component_id)

    for component_id in sorted(ids):
        visit(component_id)
    for global_rule in document["globalPaths"]:
        if not isinstance(global_rule, str) or normalized_path(global_rule.rstrip("/")) != global_rule.rstrip("/"):
            raise ValueError("framework component catalog has unsafe global path rule")
    return document


def analyze(catalog: dict[str, Any], paths: list[str]) -> dict[str, Any]:
    if not paths:
        raise ValueError("at least one changed path is required")
    changed = sorted(set(normalized_path(path) for path in paths))
    components = catalog["components"]
    by_id = {item["id"]: item for item in components}
    direct: set[str] = set()
    full_reasons: list[str] = []
    for path in changed:
        if any(matches(rule, path) for rule in catalog["globalPaths"]):
            full_reasons.append(f"global:{path}")
            continue
        matches_for_path = [item["id"] for item in components
                            if any(matches(rule, path) for rule in item["paths"])]
        if len(matches_for_path) == 1:
            direct.add(matches_for_path[0])
        elif not matches_for_path:
            full_reasons.append(f"unclassified:{path}")
        else:
            full_reasons.append(f"ambiguous:{path}")

    full_suite = bool(full_reasons)
    affected = set(by_id) if full_suite else set(direct)
    changed_graph = True
    while changed_graph and not full_suite:
        changed_graph = False
        for item in components:
            if item["id"] not in affected and any(
                    dependency in affected for dependency in item["requires"]):
                affected.add(item["id"])
                changed_graph = True
    records = []
    for component_id in sorted(affected):
        item = by_id[component_id]
        records.append({
            "id": component_id,
            "owner": item["owner"],
            "reason": ("framework-wide" if full_suite else
                       "changed" if component_id in direct else "dependency"),
            "buildTargets": sorted(item["buildTargets"]),
            "testLabels": sorted(item["testLabels"]),
        })
    labels = sorted({label for item in records for label in item["testLabels"]})
    owners = sorted({item["owner"] for item in records})
    targets = sorted({target for item in records for target in item["buildTargets"]})
    docs_only = not full_suite and bool(records) and all(item["id"] == "docs" for item in records)
    return {
        "schemaVersion": 1,
        "operation": "framework-change-impact",
        "catalogSha256": document_digest(catalog),
        "fullSuite": full_suite,
        "docsOnly": docs_only,
        "changedPaths": changed,
        "fullSuiteReasons": sorted(full_reasons),
        "owners": owners,
        "buildTargets": targets,
        "testLabels": labels,
        "ctestLabelRegex": "^(" + "|".join(re.escape(label) for label in labels) + ")$",
        "components": records,
    }


def validate_report(report: dict[str, Any]) -> None:
    required = {
        "schemaVersion", "operation", "catalogSha256", "fullSuite", "docsOnly",
        "changedPaths", "fullSuiteReasons", "owners", "buildTargets",
        "testLabels", "ctestLabelRegex", "components",
    }
    if (set(report) != required or report.get("schemaVersion") != 1 or
            report.get("operation") != "framework-change-impact" or
            not isinstance(report.get("catalogSha256"), str) or
            not SHA256.fullmatch(report["catalogSha256"]) or
            not isinstance(report.get("fullSuite"), bool) or
            not isinstance(report.get("docsOnly"), bool) or
            any(not isinstance(report.get(field), list)
                for field in ("changedPaths", "fullSuiteReasons", "owners",
                              "buildTargets", "testLabels", "components")) or
            not isinstance(report.get("ctestLabelRegex"), str)):
        raise ValueError("change-impact report is malformed")
    if (not report["testLabels"] or
            report["owners"] != sorted(set(report["owners"])) or
            report["testLabels"] != sorted(set(report["testLabels"])) or
            any(not OWNER.fullmatch(str(owner)) for owner in report["owners"]) or
            any(not ID.fullmatch(str(label)) for label in report["testLabels"])):
        raise ValueError("change-impact report owner or test-label set is malformed")


def validate_evidence(evidence: dict[str, Any], report: dict[str, Any]) -> None:
    required = {
        "schemaVersion", "operation", "reportSha256", "selection",
        "fullSuitePassed", "passedLabels", "executedTestCount",
        "executedTests", "ctestConfig", "ctestCatalogSha256",
    }
    allowed = required | {"approvedOwners"}
    if (not required <= set(evidence) or not set(evidence) <= allowed or
            evidence.get("schemaVersion") != 1 or
            evidence.get("operation") != "framework-ci-execution-evidence" or
            evidence.get("reportSha256") != document_digest(report) or
            evidence.get("selection") not in {"full-suite", "affected-labels"} or
            not isinstance(evidence.get("fullSuitePassed"), bool) or
            not isinstance(evidence.get("passedLabels"), list) or
            not isinstance(evidence.get("executedTests"), list) or
            not isinstance(evidence.get("executedTestCount"), int) or
            isinstance(evidence.get("executedTestCount"), bool) or
            evidence["executedTestCount"] < 1 or
            evidence["executedTestCount"] != len(evidence["executedTests"]) or
            evidence["executedTests"] != sorted(set(evidence["executedTests"])) or
            any(not isinstance(name, str) or not name for name in evidence["executedTests"]) or
            not isinstance(evidence.get("ctestConfig"), str) or
            not evidence["ctestConfig"] or
            not isinstance(evidence.get("ctestCatalogSha256"), str) or
            not SHA256.fullmatch(evidence["ctestCatalogSha256"])):
        raise ValueError("CI execution evidence is malformed or not bound to the report")
    if evidence["passedLabels"] != sorted(set(evidence["passedLabels"])):
        raise ValueError("CI execution evidence has duplicate or unsorted labels")
    approved = evidence.get("approvedOwners", [])
    if (not isinstance(approved, list) or approved != sorted(set(approved)) or
            any(not OWNER.fullmatch(str(owner)) for owner in approved)):
        raise ValueError("CI execution evidence has malformed owner approvals")


def analyze_command(args: argparse.Namespace) -> int:
    try:
        report = analyze(load_catalog(args.catalog.resolve()), args.paths)
        if args.output:
            atomic_json(args.output.resolve(), report)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"FRAMEWORK_IMPACT_ERROR: {error}", file=os.sys.stderr)
        return 1


def gate_command(args: argparse.Namespace) -> int:
    try:
        report = json.loads(args.report.resolve().read_text(encoding="utf-8"))
        evidence = json.loads(args.evidence.resolve().read_text(encoding="utf-8"))
        validate_report(report)
        validate_evidence(evidence, report)
        missing: list[str] = []
        if report.get("fullSuite") is True:
            if (evidence.get("fullSuitePassed") is not True or
                    evidence.get("selection") != "full-suite"):
                missing.append("full-suite")
        else:
            passed_labels = set(evidence.get("passedLabels", []))
            missing.extend(
                f"test-label:{label}" for label in report.get("testLabels", [])
                if label not in passed_labels
            )
        if args.require_owner_approvals:
            approved_owners = set(evidence.get("approvedOwners", []))
            missing.extend(
                f"owner:{owner}" for owner in report.get("owners", [])
                if owner not in approved_owners
            )
        if missing:
            raise ValueError("required CI evidence is missing: " + ", ".join(sorted(missing)))
        print("FRAMEWORK_IMPACT_GATE_PASS")
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"FRAMEWORK_IMPACT_GATE_ERROR: {error}", file=os.sys.stderr)
        return 1


def execute_command(args: argparse.Namespace) -> int:
    try:
        report_path = args.report.resolve()
        report = json.loads(report_path.read_text(encoding="utf-8"))
        validate_report(report)
        full_suite = bool(report["fullSuite"] or args.force_full_suite)
        selection = "full-suite" if full_suite else "affected-labels"
        common = [
            str(args.ctest.resolve()), "--test-dir", str(args.test_dir.resolve()),
            "-C", args.config,
        ]
        selector = [] if full_suite else ["-L", report["ctestLabelRegex"]]
        query = subprocess.run(
            [*common, *selector, "--show-only=json-v1"],
            capture_output=True, text=True, check=False,
        )
        if query.returncode != 0:
            raise ValueError((query.stderr or query.stdout).strip() or
                             "CTest selection query failed")
        catalog = json.loads(query.stdout)
        test_records = []
        for test in catalog.get("tests", []):
            if (not isinstance(test, dict) or
                    not isinstance(test.get("name"), str) or not test["name"]):
                continue
            labels: set[str] = set()
            for prop in test.get("properties", []):
                if (isinstance(prop, dict) and prop.get("name") == "LABELS" and
                        isinstance(prop.get("value"), list)):
                    labels.update(str(value) for value in prop["value"])
            test_records.append({"name": test["name"], "labels": sorted(labels)})
        test_records.sort(key=lambda item: item["name"])
        test_names = [item["name"] for item in test_records]
        if not test_names:
            raise ValueError("CTest selection contains no tests")
        available_labels = {
            label for item in test_records for label in item["labels"]
        }
        missing_labels = sorted(set(report["testLabels"]) - available_labels)
        if missing_labels:
            raise ValueError(
                "CTest selection does not cover required labels: " +
                ", ".join(missing_labels)
            )
        run = subprocess.run(
            [*common, *selector, "--output-on-failure", "--no-tests=error"],
            check=False,
        )
        if run.returncode != 0:
            raise ValueError(f"CTest execution failed with exit code {run.returncode}")
        evidence = {
            "schemaVersion": 1,
            "operation": "framework-ci-execution-evidence",
            "reportSha256": document_digest(report),
            "selection": selection,
            "fullSuitePassed": full_suite,
            "passedLabels": sorted(report["testLabels"]),
            "executedTestCount": len(test_names),
            "executedTests": test_names,
            "ctestConfig": args.config,
            "ctestCatalogSha256": document_digest({"tests": test_records}),
        }
        atomic_json(args.evidence.resolve(), evidence)
        print(
            "FRAMEWORK_IMPACT_EXECUTE_PASS "
            f"selection={selection} tests={len(test_names)}"
        )
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"FRAMEWORK_IMPACT_EXECUTE_ERROR: {error}", file=os.sys.stderr)
        return 1


def validate_ctest_command(args: argparse.Namespace) -> int:
    try:
        catalog = load_catalog(args.catalog.resolve())
        result = subprocess.run(
            [str(args.ctest.resolve()), "--test-dir", str(args.test_dir.resolve()),
             "-C", args.config, "--show-only=json-v1"],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            raise ValueError((result.stderr or result.stdout).strip() or
                             "CTest catalog query failed")
        ctest = json.loads(result.stdout)
        labels: set[str] = set()
        for test in ctest.get("tests", []):
            for prop in test.get("properties", []):
                if prop.get("name") == "LABELS" and isinstance(prop.get("value"), list):
                    labels.update(str(value) for value in prop["value"])
        required = {label for component in catalog["components"]
                    for label in component["testLabels"]}
        missing = sorted(required - labels)
        if missing:
            raise ValueError("component catalog references unknown CTest labels: " +
                             ", ".join(missing))
        print(f"FRAMEWORK_IMPACT_CTEST_PASS labels={len(required)}")
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"FRAMEWORK_IMPACT_CTEST_ERROR: {error}", file=os.sys.stderr)
        return 1


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("analyze")
    plan.add_argument("--catalog", type=Path, required=True)
    plan.add_argument("--output", type=Path)
    plan.add_argument("paths", nargs="+")
    plan.set_defaults(handler=analyze_command)
    gate = commands.add_parser("gate")
    gate.add_argument("--report", type=Path, required=True)
    gate.add_argument("--evidence", type=Path, required=True)
    gate.add_argument("--require-owner-approvals", action="store_true")
    gate.set_defaults(handler=gate_command)
    execute = commands.add_parser("execute")
    execute.add_argument("--report", type=Path, required=True)
    execute.add_argument("--ctest", type=Path, required=True)
    execute.add_argument("--test-dir", type=Path, required=True)
    execute.add_argument("--config", default="Release")
    execute.add_argument("--evidence", type=Path, required=True)
    execute.add_argument("--force-full-suite", action="store_true")
    execute.set_defaults(handler=execute_command)
    validate = commands.add_parser("validate-ctest")
    validate.add_argument("--catalog", type=Path, required=True)
    validate.add_argument("--ctest", type=Path, required=True)
    validate.add_argument("--test-dir", type=Path, required=True)
    validate.add_argument("--config", default="Release")
    validate.set_defaults(handler=validate_ctest_command)
    return result


if __name__ == "__main__":
    arguments = parser().parse_args()
    raise SystemExit(arguments.handler(arguments))
