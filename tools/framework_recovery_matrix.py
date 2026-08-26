#!/usr/bin/env python3
"""Validate and execute the framework fault-recovery matrix."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from framework_change_impact import atomic_json, document_digest, load_catalog


SCENARIO_ID = re.compile(r"^PDR-REC-[0-9]{4,}$")
SIMPLE_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
OWNER = re.compile(r"^team/[a-z0-9][a-z0-9-]*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SCOPES = {"host", "runtime", "process", "bundle", "service", "transport", "persistence"}


def exact_fields(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) == expected:
        return
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    raise ValueError(
        f"{label} fields are invalid: missing={','.join(missing)}; "
        f"unknown={','.join(unknown)}"
    )


def nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\n" in value:
        raise ValueError(f"{label} must be a non-empty single-line string")
    return value.strip()


def ordered_ids(value: Any, label: str, allowed: set[str] | None = None) -> list[str]:
    if (not isinstance(value, list) or not value or
            any(not isinstance(item, str) or SIMPLE_ID.fullmatch(item) is None
                for item in value)):
        raise ValueError(f"{label} must be a non-empty ID array")
    if value != sorted(set(value)):
        raise ValueError(f"{label} must be sorted and unique")
    if allowed is not None and not set(value) <= allowed:
        raise ValueError(f"{label} contains unsupported values")
    return value


def validate_matrix(document: dict[str, Any], catalog: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(document, dict):
        raise ValueError("recovery matrix root must be an object")
    exact_fields(document, {
        "$schema", "schemaVersion", "matrixVersion", "product", "profile",
        "requiredScopes", "scenarios",
    }, "recovery matrix")
    if (not isinstance(document["schemaVersion"], int) or
            isinstance(document["schemaVersion"], bool) or
            document["schemaVersion"] != 1 or
            document["product"] != "PocoDDSRuntime"):
        raise ValueError("recovery matrix identity is invalid")
    if (not isinstance(document["matrixVersion"], str) or
            not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", document["matrixVersion"])):
        raise ValueError("recovery matrix version is invalid")
    nonempty(document["$schema"], "recovery matrix $schema")
    nonempty(document["profile"], "recovery matrix profile")
    required_scopes = ordered_ids(
        document["requiredScopes"], "recovery matrix requiredScopes", SCOPES
    )
    if not isinstance(document["scenarios"], list) or not document["scenarios"]:
        raise ValueError("recovery matrix scenarios must be a non-empty array")

    components = {item["id"]: item for item in catalog["components"]}
    expected = {
        "id", "title", "component", "owner", "scope", "fault", "injection",
        "recoveryPolicy", "test", "requiredLabels", "timeoutSeconds", "assertions",
    }
    assertion_fields = {"id", "marker", "invariant"}
    ids: set[str] = set()
    tests: set[str] = set()
    covered_scopes: set[str] = set()
    scenarios: list[dict[str, Any]] = []
    for index, scenario in enumerate(document["scenarios"]):
        if not isinstance(scenario, dict):
            raise ValueError(f"recovery scenario {index} must be an object")
        exact_fields(scenario, expected, f"recovery scenario {index}")
        scenario_id = scenario["id"]
        if not isinstance(scenario_id, str) or SCENARIO_ID.fullmatch(scenario_id) is None:
            raise ValueError(f"recovery scenario {index} id is invalid")
        if scenario_id in ids:
            raise ValueError(f"duplicate recovery scenario id: {scenario_id}")
        ids.add(scenario_id)
        component_id = scenario["component"]
        if component_id not in components:
            raise ValueError(f"recovery scenario {scenario_id} component is unknown")
        component = components[component_id]
        if (not isinstance(scenario["owner"], str) or
                OWNER.fullmatch(scenario["owner"]) is None or
                scenario["owner"] != component["owner"]):
            raise ValueError(f"recovery scenario {scenario_id} owner does not match component")
        scope = scenario["scope"]
        if not isinstance(scope, str) or scope not in SCOPES:
            raise ValueError(f"recovery scenario {scenario_id} scope is invalid")
        covered_scopes.add(scope)
        for field in ("title", "fault", "injection", "recoveryPolicy"):
            nonempty(scenario[field], f"recovery scenario {scenario_id} {field}")
        if SIMPLE_ID.fullmatch(scenario["fault"]) is None:
            raise ValueError(f"recovery scenario {scenario_id} fault is invalid")
        test = scenario["test"]
        if not isinstance(test, str) or SIMPLE_ID.fullmatch(test) is None:
            raise ValueError(f"recovery scenario {scenario_id} test is invalid")
        if test in tests:
            raise ValueError(f"recovery test is assigned more than once: {test}")
        tests.add(test)
        labels = ordered_ids(
            scenario["requiredLabels"],
            f"recovery scenario {scenario_id} requiredLabels",
        )
        if not ({"fault-injection", "recovery"} & set(labels)):
            raise ValueError(
                f"recovery scenario {scenario_id} lacks a recovery/fault-injection label"
            )
        if not set(labels) & set(component["testLabels"]):
            raise ValueError(
                f"recovery scenario {scenario_id} labels do not select its component"
            )
        timeout = scenario["timeoutSeconds"]
        if (not isinstance(timeout, int) or isinstance(timeout, bool) or
                timeout < 1 or timeout > 120):
            raise ValueError(f"recovery scenario {scenario_id} timeoutSeconds is invalid")
        assertions = scenario["assertions"]
        if not isinstance(assertions, list) or not assertions:
            raise ValueError(f"recovery scenario {scenario_id} has no assertions")
        assertion_ids: set[str] = set()
        markers: set[str] = set()
        for assertion_index, assertion in enumerate(assertions):
            if not isinstance(assertion, dict):
                raise ValueError(
                    f"recovery scenario {scenario_id} assertion {assertion_index} is invalid"
                )
            exact_fields(
                assertion, assertion_fields,
                f"recovery scenario {scenario_id} assertion {assertion_index}",
            )
            assertion_id = assertion["id"]
            if (not isinstance(assertion_id, str) or
                    SIMPLE_ID.fullmatch(assertion_id) is None or
                    assertion_id in assertion_ids):
                raise ValueError(f"recovery scenario {scenario_id} assertion id is invalid")
            assertion_ids.add(assertion_id)
            marker = nonempty(
                assertion["marker"],
                f"recovery scenario {scenario_id} assertion marker",
            )
            if marker in markers or len(marker) > 256:
                raise ValueError(f"recovery scenario {scenario_id} assertion marker is invalid")
            markers.add(marker)
            nonempty(
                assertion["invariant"],
                f"recovery scenario {scenario_id} assertion invariant",
            )
        scenarios.append(scenario)

    if document["scenarios"] != sorted(document["scenarios"], key=lambda item: item["id"]):
        raise ValueError("recovery matrix scenarios must be sorted by id")
    missing_scopes = sorted(set(required_scopes) - covered_scopes)
    if missing_scopes:
        raise ValueError("recovery matrix lacks required scopes: " + ",".join(missing_scopes))
    return scenarios


def load_inputs(matrix_path: Path, catalog_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    catalog = load_catalog(catalog_path)
    validate_matrix(matrix, catalog)
    return matrix, catalog


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized_catalog_value(value: Any, test_dir: Path) -> Any:
    if isinstance(value, str):
        root = test_dir.resolve().as_posix().rstrip("/")
        return value.replace("\\", "/").replace(root, "<TEST_DIR>")
    if isinstance(value, list):
        return [normalized_catalog_value(item, test_dir) for item in value]
    if isinstance(value, dict):
        return {
            key: normalized_catalog_value(item, test_dir)
            for key, item in sorted(value.items())
        }
    return value


def command_identity(command: list[Any], properties: list[Any],
                     test_dir: Path) -> tuple[str, str]:
    if not command or any(not isinstance(item, str) for item in command):
        raise ValueError("CTest command is missing or malformed")
    semantic_command = []
    artifacts = []
    for position, token in enumerate(command):
        candidate = Path(token)
        if candidate.is_file():
            digest = file_sha256(candidate)
            semantic_command.append({
                "position": position, "token": candidate.name,
                "fileSha256": digest,
            })
            artifacts.append({
                "position": position, "name": candidate.name, "sha256": digest,
            })
        else:
            semantic_command.append({
                "position": position,
                "token": normalized_catalog_value(token, test_dir),
                "fileSha256": "",
            })
    semantic_properties = sorted(
        (
            {
                "name": item.get("name"),
                "value": normalized_catalog_value(item.get("value"), test_dir),
            }
            for item in properties if isinstance(item, dict)
        ),
        key=lambda item: str(item["name"]),
    )
    command_digest = hashlib.sha256(json.dumps(
        {"command": semantic_command, "properties": semantic_properties},
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    artifact_digest = hashlib.sha256(json.dumps(
        artifacts, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    return command_digest, artifact_digest


def runtime_search_paths(properties: list[Any]) -> list[Path]:
    result = []
    prefix = "PATH=path_list_prepend:"
    for item in properties:
        if (not isinstance(item, dict) or
                item.get("name") != "ENVIRONMENT_MODIFICATION" or
                not isinstance(item.get("value"), list)):
            continue
        for value in item["value"]:
            if isinstance(value, str) and value.startswith(prefix):
                result.append(Path(value[len(prefix):]))
    return result


def runtime_artifact_identity(test_dir: Path,
                              search_paths: list[Path] | None = None) -> tuple[int, str]:
    roots = [test_dir.resolve() / "bin", *(search_paths or [])]
    unique_roots = []
    seen: set[Path] = set()
    for root in roots:
        resolved = root.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique_roots.append(resolved)
    root_records = []
    total = 0
    for root in unique_roots:
        records = []
        if not root.is_dir():
            continue
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            name = path.name.lower()
            if not (name.endswith((".dll", ".dylib")) or ".so" in name):
                continue
            records.append({
                "path": path.relative_to(root).as_posix(),
                "sha256": file_sha256(path),
            })
        total += len(records)
        root_records.append({
            "artifactCount": len(records),
            "artifactSetSha256": hashlib.sha256(json.dumps(
                records, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")).hexdigest(),
        })
    digest = hashlib.sha256(json.dumps(
        sorted(root_records, key=lambda item: (
            item["artifactSetSha256"], item["artifactCount"]
        )),
        sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    return total, digest


def query_ctest(ctest: Path, test_dir: Path, configuration: str,
                selected_tests: set[str] | None = None
                ) -> tuple[dict[str, dict[str, Any]], str]:
    result = subprocess.run(
        [str(ctest), "--test-dir", str(test_dir), "-C", configuration,
         "--show-only=json-v1"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise ValueError(f"CTest catalog query failed: {result.stderr.strip()}")
    try:
        document = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ValueError(f"CTest catalog is not valid JSON: {error}") from error
    tests: dict[str, dict[str, Any]] = {}
    observed_names: set[str] = set()
    for test in document.get("tests", []):
        name = test.get("name")
        if not isinstance(name, str) or name in observed_names:
            raise ValueError("CTest catalog has a missing or duplicate test name")
        observed_names.add(name)
        if selected_tests is not None and name not in selected_tests:
            continue
        labels: set[str] = set()
        properties = test.get("properties", [])
        if not isinstance(properties, list):
            raise ValueError(f"CTest {name} properties are malformed")
        for prop in properties:
            if not isinstance(prop, dict):
                raise ValueError(f"CTest {name} property is malformed")
            if prop.get("name") == "LABELS" and isinstance(prop.get("value"), list):
                labels = {str(item) for item in prop["value"]}
        command_sha, artifact_sha = command_identity(
            test.get("command", []), properties, test_dir
        )
        tests[name] = {
            "labels": labels,
            "commandSha256": command_sha,
            "commandArtifactSetSha256": artifact_sha,
            "runtimeSearchPaths": runtime_search_paths(properties),
        }
    semantic = [
        {
            "name": name, "labels": sorted(record["labels"]),
            "commandSha256": record["commandSha256"],
            "commandArtifactSetSha256": record["commandArtifactSetSha256"],
        }
        for name, record in sorted(tests.items())
    ]
    return tests, hashlib.sha256(json.dumps(
        semantic, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def preflight(scenarios: list[dict[str, Any]],
              tests: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    records = []
    violations = []
    for scenario in scenarios:
        test = tests.get(scenario["test"])
        labels = test["labels"] if test else set()
        missing = sorted(set(scenario["requiredLabels"]) - labels)
        registered = scenario["test"] in tests
        if not registered:
            violations.append(f"{scenario['id']}: missing CTest {scenario['test']}")
        elif missing:
            violations.append(
                f"{scenario['id']}: CTest {scenario['test']} lacks labels {','.join(missing)}"
            )
        records.append({
            "id": scenario["id"], "test": scenario["test"],
            "registered": registered, "observedLabels": sorted(labels),
            "missingLabels": missing,
            "commandSha256": test["commandSha256"] if test else "",
            "commandArtifactSetSha256": (
                test["commandArtifactSetSha256"] if test else ""
            ),
        })
    return records, violations


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def ctest_version(ctest: Path) -> str:
    result = subprocess.run(
        [str(ctest), "--version"], capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise ValueError("cannot query CTest version")
    return result.stdout.splitlines()[0].strip()


def validate_evidence(document: dict[str, Any]) -> None:
    expected = {
        "schemaVersion", "operation", "passed", "matrixVersion", "profile",
        "configuration", "matrixSha256", "catalogSha256", "ctestCatalogSha256",
        "runtimeArtifactCount", "runtimeArtifactSetSha256",
        "ctestVersion", "requiredScopes", "scenarioCount", "startedAt", "finishedAt",
        "preflight", "results", "violations",
    }
    exact_fields(document, expected, "recovery evidence")
    if (document["schemaVersion"] != 2 or
            document["operation"] != "framework-recovery-matrix-evidence" or
            not isinstance(document["passed"], bool)):
        raise ValueError("recovery evidence identity is invalid")
    for field in ("matrixSha256", "catalogSha256", "ctestCatalogSha256",
                  "runtimeArtifactSetSha256"):
        if not isinstance(document[field], str) or SHA256.fullmatch(document[field]) is None:
            raise ValueError(f"recovery evidence {field} is invalid")
    for field in ("matrixVersion", "profile", "configuration", "ctestVersion",
                  "startedAt", "finishedAt"):
        nonempty(document[field], f"recovery evidence {field}")
    ordered_ids(document["requiredScopes"], "recovery evidence requiredScopes", SCOPES)
    count = document["scenarioCount"]
    if (not isinstance(count, int) or isinstance(count, bool) or count < 1 or
            not isinstance(document["runtimeArtifactCount"], int) or
            isinstance(document["runtimeArtifactCount"], bool) or
            document["runtimeArtifactCount"] < 0 or
            not isinstance(document["preflight"], list) or
            len(document["preflight"]) != count or
            not isinstance(document["results"], list) or
            not isinstance(document["violations"], list)):
        raise ValueError("recovery evidence scenario counts are inconsistent")
    for item in document["preflight"]:
        if (not isinstance(item, dict) or
                any(not isinstance(item.get(field), str) or
                    (item[field] and SHA256.fullmatch(item[field]) is None)
                    for field in ("commandSha256", "commandArtifactSetSha256"))):
            raise ValueError("recovery evidence preflight command identity is malformed")
    if document["passed"]:
        if (document["violations"] or len(document["results"]) != count or
                any(not item.get("registered") or item.get("missingLabels")
                    for item in document["preflight"]) or
                any(not item.get("passed") for item in document["results"])):
            raise ValueError("passing recovery evidence contains incomplete results")
    elif not document["violations"]:
        raise ValueError("failing recovery evidence has no violations")
    for result in document["results"]:
        assertions = result.get("assertions") if isinstance(result, dict) else None
        if (not isinstance(assertions, list) or not assertions or
                not isinstance(result.get("outputSha256"), str) or
                SHA256.fullmatch(result["outputSha256"]) is None):
            raise ValueError("recovery evidence result is malformed")
        observed = all(item.get("observed") is True for item in assertions)
        derived_pass = (
            result.get("exitCode") == 0 and result.get("timedOut") is False and observed
        )
        if result.get("passed") is not derived_pass:
            raise ValueError("recovery evidence result pass state is inconsistent")


def run_scenario(scenario: dict[str, Any], ctest: Path, test_dir: Path,
                 configuration: str) -> dict[str, Any]:
    command = [
        str(ctest), "--test-dir", str(test_dir), "-C", configuration,
        "-R", f"^{scenario['test']}$", "--output-on-failure", "-V",
        "--timeout", str(scenario["timeoutSeconds"]), "--no-tests=error",
    ]
    started = time.monotonic()
    timed_out = False
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=scenario["timeoutSeconds"] + 10,
        )
        output = result.stdout + result.stderr
        exit_code = result.returncode
    except subprocess.TimeoutExpired as error:
        timed_out = True
        output = (error.stdout or "") + (error.stderr or "")
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        exit_code = 124
    elapsed = max(0, round((time.monotonic() - started) * 1000))
    assertions = [
        {
            "id": item["id"], "marker": item["marker"],
            "invariant": item["invariant"], "observed": item["marker"] in output,
        }
        for item in scenario["assertions"]
    ]
    passed = exit_code == 0 and not timed_out and all(item["observed"] for item in assertions)
    if not passed:
        print(output, file=sys.stderr)
    return {
        "id": scenario["id"], "scope": scenario["scope"],
        "component": scenario["component"], "owner": scenario["owner"],
        "test": scenario["test"], "passed": passed, "exitCode": exit_code,
        "timedOut": timed_out, "elapsedMilliseconds": elapsed,
        "outputBytes": len(output.encode("utf-8")),
        "outputSha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
        "assertions": assertions,
        "diagnostic": "" if passed else output[-4000:],
    }


def validate_command(args: argparse.Namespace) -> int:
    try:
        matrix, catalog = load_inputs(args.matrix.resolve(), args.catalog.resolve())
        print(
            "FRAMEWORK_RECOVERY_MATRIX_CONTRACT_PASS "
            f"version={matrix['matrixVersion']} scenarios={len(matrix['scenarios'])} "
            f"components={len(catalog['components'])}"
        )
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"FRAMEWORK_RECOVERY_MATRIX_CONTRACT_ERROR: {error}", file=sys.stderr)
        return 2


def execute_command(args: argparse.Namespace) -> int:
    started_at = utc_now()
    try:
        matrix_path = args.matrix.resolve()
        catalog_path = args.catalog.resolve()
        matrix, catalog = load_inputs(matrix_path, catalog_path)
        if args.profile != matrix["profile"]:
            raise ValueError(
                f"matrix profile {matrix['profile']} does not match requested {args.profile}"
            )
        selected_tests = {item["test"] for item in matrix["scenarios"]}
        tests, test_catalog_sha = query_ctest(
            args.ctest.resolve(), args.test_dir.resolve(), args.config,
            selected_tests,
        )
        runtime_paths = [
            path for test in tests.values() for path in test["runtimeSearchPaths"]
        ]
        runtime_artifact_count, runtime_artifact_sha = runtime_artifact_identity(
            args.test_dir.resolve(), runtime_paths
        )
        checks, violations = preflight(matrix["scenarios"], tests)
        results = []
        version = ctest_version(args.ctest.resolve())
        if not violations:
            results = [
                run_scenario(
                    scenario, args.ctest.resolve(), args.test_dir.resolve(), args.config
                )
                for scenario in matrix["scenarios"]
            ]
            violations.extend(
                f"{item['id']}: recovery assertions failed"
                for item in results if not item["passed"]
            )
        evidence = {
            "schemaVersion": 2,
            "operation": "framework-recovery-matrix-evidence",
            "passed": not violations,
            "matrixVersion": matrix["matrixVersion"],
            "profile": args.profile,
            "configuration": args.config,
            "matrixSha256": document_digest(matrix),
            "catalogSha256": document_digest(catalog),
            "ctestCatalogSha256": test_catalog_sha,
            "runtimeArtifactCount": runtime_artifact_count,
            "runtimeArtifactSetSha256": runtime_artifact_sha,
            "ctestVersion": version,
            "requiredScopes": matrix["requiredScopes"],
            "scenarioCount": len(matrix["scenarios"]),
            "startedAt": started_at,
            "finishedAt": utc_now(),
            "preflight": checks,
            "results": results,
            "violations": violations,
        }
        validate_evidence(evidence)
        atomic_json(args.report.resolve(), evidence)
        if violations:
            print(
                "FRAMEWORK_RECOVERY_MATRIX_ERROR "
                f"violations={len(violations)} report={args.report.resolve()}",
                file=sys.stderr,
            )
            return 1
        print(
            "FRAMEWORK_RECOVERY_MATRIX_PASS "
            f"scenarios={len(results)} scopes={len(matrix['requiredScopes'])} "
            f"report={args.report.resolve()}"
        )
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"FRAMEWORK_RECOVERY_MATRIX_ERROR: {error}", file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--matrix", type=Path, required=True)
    validate.add_argument("--catalog", type=Path, required=True)
    validate.set_defaults(handler=validate_command)
    execute = commands.add_parser("execute")
    execute.add_argument("--matrix", type=Path, required=True)
    execute.add_argument("--catalog", type=Path, required=True)
    execute.add_argument("--ctest", type=Path, required=True)
    execute.add_argument("--test-dir", type=Path, required=True)
    execute.add_argument("--config", required=True)
    execute.add_argument("--profile", required=True)
    execute.add_argument("--report", type=Path, required=True)
    execute.set_defaults(handler=execute_command)
    return result


if __name__ == "__main__":
    arguments = parser().parse_args()
    raise SystemExit(arguments.handler(arguments))
