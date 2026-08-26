#!/usr/bin/env python3
"""Validate one component's service contract against explicit provider contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import project_manager


IDENTIFIER = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
SERVICE_NAME = re.compile(r"^[A-Za-z0-9._:-]{1,192}$")
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
RANGE = re.compile(
    r"^([\[(])\s*([0-9]+\.[0-9]+\.[0-9]+)?\s*,\s*"
    r"([0-9]+\.[0-9]+\.[0-9]+)?\s*([\])])$"
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def require_exact_fields(document: dict[str, Any], expected: set[str], field: str) -> None:
    if set(document) == expected:
        return
    missing = sorted(expected - set(document))
    unknown = sorted(set(document) - expected)
    details: list[str] = []
    if missing:
        details.append("missing=" + ",".join(missing))
    if unknown:
        details.append("unknown=" + ",".join(unknown))
    raise ValueError(f"{field} has invalid fields: {'; '.join(details)}")


def require_identifier(value: Any, field: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError(f"{field} is invalid")
    return value


def parse_version(value: str) -> tuple[int, int, int]:
    if VERSION.fullmatch(value) is None:
        raise ValueError(f"invalid semantic version: {value}")
    parts = tuple(int(part) for part in value.split("."))
    if any(part > 0xFFFFFFFF for part in parts):
        raise ValueError(f"semantic version part exceeds uint32: {value}")
    return parts  # type: ignore[return-value]


def validate_version_range(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) > 128:
        raise ValueError(f"{field} is invalid")
    if VERSION.fullmatch(value):
        parse_version(value)
        return value
    match = RANGE.fullmatch(value)
    if match is None or (match.group(2) is None and match.group(3) is None):
        raise ValueError(f"{field} is invalid")
    lower = parse_version(match.group(2)) if match.group(2) else None
    upper = parse_version(match.group(3)) if match.group(3) else None
    if lower is not None and upper is not None and lower > upper:
        raise ValueError(f"{field} lower bound exceeds upper bound")
    if lower == upper and lower is not None and not (
        match.group(1) == "[" and match.group(4) == "]"
    ):
        raise ValueError(f"{field} is an empty range")
    return value


def matches_version(version: str, version_range: str) -> bool:
    candidate = parse_version(version)
    if VERSION.fullmatch(version_range):
        return candidate == parse_version(version_range)
    match = RANGE.fullmatch(version_range)
    if match is None:
        return False
    lower = parse_version(match.group(2)) if match.group(2) else None
    upper = parse_version(match.group(3)) if match.group(3) else None
    if lower is not None:
        if candidate < lower or (candidate == lower and match.group(1) == "("):
            return False
    if upper is not None:
        if candidate > upper or (candidate == upper and match.group(4) == ")"):
            return False
    return True


def load_service_contract(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON in {path}: {error}") from error
    if not isinstance(document, dict):
        raise ValueError(f"service contract root must be an object: {path}")
    require_exact_fields(document, {"schemaVersion", "provides", "requires"}, str(path))
    if (not isinstance(document["schemaVersion"], int)
            or isinstance(document["schemaVersion"], bool)
            or document["schemaVersion"] != 1):
        raise ValueError(f"service contract schemaVersion must equal 1: {path}")
    if not isinstance(document["provides"], list) or len(document["provides"]) > 128:
        raise ValueError(f"provides must be an array with at most 128 entries: {path}")
    if not isinstance(document["requires"], list) or len(document["requires"]) > 128:
        raise ValueError(f"requires must be an array with at most 128 entries: {path}")

    providers: list[dict[str, str]] = []
    provider_keys: set[tuple[str, str]] = set()
    for index, item in enumerate(document["provides"]):
        if not isinstance(item, dict):
            raise ValueError(f"provides[{index}] must be an object: {path}")
        require_exact_fields(
            item, {"contract", "version", "serviceName"}, f"{path}:provides[{index}]"
        )
        contract = require_identifier(item["contract"], "provider.contract", IDENTIFIER)
        version = require_identifier(item["version"], "provider.version", VERSION)
        parse_version(version)
        service_name = require_identifier(
            item["serviceName"], "provider.serviceName", SERVICE_NAME
        )
        key = (contract, service_name)
        if key in provider_keys:
            raise ValueError(f"duplicate provider declaration {contract}/{service_name}: {path}")
        provider_keys.add(key)
        providers.append(
            {"contract": contract, "version": version, "serviceName": service_name}
        )

    requirements: list[dict[str, Any]] = []
    requirement_keys: set[str] = set()
    for index, item in enumerate(document["requires"]):
        if not isinstance(item, dict):
            raise ValueError(f"requires[{index}] must be an object: {path}")
        allowed = {"contract", "versionRange", "required", "minimumProviders"}
        unknown = set(item) - allowed
        missing = {"contract", "versionRange"} - set(item)
        if unknown or missing:
            details = []
            if missing:
                details.append("missing=" + ",".join(sorted(missing)))
            if unknown:
                details.append("unknown=" + ",".join(sorted(unknown)))
            raise ValueError(
                f"{path}:requires[{index}] has invalid fields: {'; '.join(details)}"
            )
        contract = require_identifier(item["contract"], "requirement.contract", IDENTIFIER)
        version_range = validate_version_range(
            item["versionRange"], "requirement.versionRange"
        )
        required = item.get("required", True)
        minimum = item.get("minimumProviders", 1)
        if not isinstance(required, bool):
            raise ValueError(f"requirement.required must be boolean: {path}")
        if (
            not isinstance(minimum, int)
            or isinstance(minimum, bool)
            or minimum < 1
            or minimum > 64
        ):
            raise ValueError(f"requirement.minimumProviders must be 1..64: {path}")
        if contract in requirement_keys:
            raise ValueError(f"duplicate requirement declaration {contract}: {path}")
        requirement_keys.add(contract)
        requirements.append(
            {
                "contract": contract,
                "versionRange": version_range,
                "required": required,
                "minimumProviders": minimum,
            }
        )
    return {"schemaVersion": 1, "provides": providers, "requires": requirements}


def component_path(value: Path) -> Path:
    candidate = value.resolve()
    return candidate / "pdr-component.json" if candidate.is_dir() else candidate


def load_component(path: Path) -> dict[str, Any]:
    if path.name != "pdr-component.json":
        raise ValueError("component contract file must be named pdr-component.json")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid pdr-component.json: {error}") from error
    kind = raw.get("kind") if isinstance(raw, dict) else None
    if not isinstance(kind, str) or kind not in project_manager.COMPONENT_PLANES:
        raise ValueError("pdr-component.json kind is missing or unsupported")
    return project_manager.validate_component_contract(path.parent, path.parent.name, {kind})


def input_record(role: str, path: Path) -> dict[str, str]:
    return {"role": role, "path": str(path), "sha256": sha256(path)}


def input_set_sha256(inputs: list[dict[str, str]]) -> str:
    # Clone/build paths are diagnostic only. Bind semantic roles and content so
    # the same reviewed contracts produce the same evidence ID on every agent.
    semantic_inputs = sorted(
        ({"role": item["role"], "sha256": item["sha256"]} for item in inputs),
        key=lambda item: (item["role"], item["sha256"]),
    )
    canonical = json.dumps(
        semantic_inputs, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_report(component: dict[str, Any], service_path: Path,
                 provider_paths: list[Path]) -> dict[str, Any]:
    service = load_service_contract(service_path)
    provider_documents = [load_service_contract(path) for path in provider_paths]
    inputs = [input_record("component", Path(component["contractPath"]))]
    inputs.append(input_record("consumer-service-contract", service_path))
    inputs.extend(input_record("provider-service-contract", path) for path in provider_paths)

    available: list[dict[str, str]] = []
    for provider in service["provides"]:
        available.append({**provider, "source": str(service_path)})
    for path, document in zip(provider_paths, provider_documents):
        for provider in document["provides"]:
            available.append({**provider, "source": str(path)})
    provider_keys: set[tuple[str, str]] = set()
    for provider in available:
        key = (provider["contract"], provider["serviceName"])
        if key in provider_keys:
            raise ValueError(
                "provider fixture set repeats the same contract/serviceName: "
                f"{provider['contract']}/{provider['serviceName']}"
            )
        provider_keys.add(key)

    results: list[dict[str, Any]] = []
    violations: list[str] = []
    required_satisfied = 0
    optional_unsatisfied = 0
    for requirement in service["requires"]:
        declared = [
            provider for provider in available
            if provider["contract"] == requirement["contract"]
        ]
        matching = [
            provider for provider in declared
            if matches_version(provider["version"], requirement["versionRange"])
        ]
        if len(matching) >= requirement["minimumProviders"]:
            status = "satisfied"
            if requirement["required"]:
                required_satisfied += 1
        elif not declared:
            status = "missing"
        elif not matching:
            status = "versionMismatch"
        else:
            status = "insufficientProviders"
        result = {
            **requirement,
            "status": status,
            "declaredProviders": len(declared),
            "matchingProviders": len(matching),
            "availableVersions": sorted({provider["version"] for provider in declared}),
            "matchedServices": sorted(
                f"{provider['serviceName']}@{provider['version']}" for provider in matching
            ),
        }
        results.append(result)
        if status != "satisfied":
            if requirement["required"]:
                violations.append(
                    f"required contract {requirement['contract']} {status}: "
                    f"need {requirement['minimumProviders']} provider(s) in "
                    f"{requirement['versionRange']}, matched {len(matching)}"
                )
            else:
                optional_unsatisfied += 1

    required_count = sum(1 for item in service["requires"] if item["required"])
    return {
        "schemaVersion": 1,
        "operation": "component-contract-conformance",
        "passed": not violations,
        "component": {
            key: component[key]
            for key in ("id", "name", "kind", "plane", "target", "owner", "isolation")
        },
        "inputs": inputs,
        "inputSetSha256": input_set_sha256(inputs),
        "providedContractCount": len(available),
        "requirementCount": len(service["requires"]),
        "requiredRequirementCount": required_count,
        "requiredSatisfiedCount": required_satisfied,
        "optionalUnsatisfiedCount": optional_unsatisfied,
        "requirements": results,
        "violations": violations,
    }


def validate_command(args: argparse.Namespace) -> int:
    try:
        component_contract = component_path(Path(args.component))
        service_contract = Path(args.service_contract).resolve()
        provider_contracts = [Path(path).resolve() for path in args.provider_contract]
        if len(set(provider_contracts)) != len(provider_contracts):
            raise ValueError("provider contract input is repeated")
        for path in [component_contract, service_contract, *provider_contracts]:
            if not path.is_file():
                raise FileNotFoundError(f"contract file does not exist: {path}")
        component = load_component(component_contract)
        component["contractPath"] = str(component_contract)
        report = build_report(component, service_contract, provider_contracts)
        if args.report:
            atomic_json(Path(args.report).resolve(), report)
        if not report["passed"]:
            print(
                "COMPONENT_CONTRACT_CONFORMANCE_ERROR: "
                + "; ".join(report["violations"]),
                file=sys.stderr,
            )
            return 1
        print(
            "COMPONENT_CONTRACT_CONFORMANCE_PASS "
            f"component={report['component']['id']} "
            f"provided={report['providedContractCount']} "
            f"requirements={report['requirementCount']} "
            f"optionalUnsatisfied={report['optionalUnsatisfiedCount']}"
        )
        return 0
    except (OSError, ValueError) as error:
        print(f"COMPONENT_CONTRACT_CONFORMANCE_ERROR: {error}", file=sys.stderr)
        return 2


def verify_report_command(args: argparse.Namespace) -> int:
    try:
        report_path = Path(args.verify_report).resolve()
        document = json.loads(report_path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("conformance report root must be an object")
        if document.get("schemaVersion") != 1 or document.get("operation") != (
            "component-contract-conformance"
        ):
            raise ValueError("unsupported component contract conformance report")
        inputs = document.get("inputs")
        if not isinstance(inputs, list):
            raise ValueError("conformance report inputs must be an array")
        by_role: dict[str, list[Path]] = {}
        for index, item in enumerate(inputs):
            if not isinstance(item, dict) or set(item) != {"role", "path", "sha256"}:
                raise ValueError(f"conformance report input {index} is invalid")
            role = item["role"]
            path = Path(item["path"]).resolve()
            digest = item["sha256"]
            if role not in {
                "component", "consumer-service-contract", "provider-service-contract"
            }:
                raise ValueError(f"conformance report input role is invalid: {role}")
            if not isinstance(digest, str) or SHA256.fullmatch(digest) is None:
                raise ValueError(f"conformance report input digest is invalid: {path}")
            if not path.is_file():
                raise FileNotFoundError(f"conformance report input is missing: {path}")
            if sha256(path) != digest:
                raise ValueError(f"conformance report input digest mismatch: {path}")
            by_role.setdefault(role, []).append(path)
        if len(by_role.get("component", [])) != 1:
            raise ValueError("conformance report must bind exactly one component input")
        if len(by_role.get("consumer-service-contract", [])) != 1:
            raise ValueError("conformance report must bind exactly one consumer contract")
        component_contract = by_role["component"][0]
        component = load_component(component_contract)
        component["contractPath"] = str(component_contract)
        rebuilt = build_report(
            component,
            by_role["consumer-service-contract"][0],
            by_role.get("provider-service-contract", []),
        )
        if rebuilt != document:
            raise ValueError("conformance report content does not match recomputed evidence")
        if not rebuilt["passed"]:
            raise ValueError("conformance report records a failed contract test")
        print(
            "COMPONENT_CONTRACT_EVIDENCE_PASS "
            f"component={rebuilt['component']['id']} "
            f"inputSetSha256={rebuilt['inputSetSha256']}"
        )
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"COMPONENT_CONTRACT_EVIDENCE_ERROR: {error}", file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Validate a component service contract without starting Runtime"
    )
    result.add_argument("component", nargs="?", help="component directory or pdr-component.json")
    result.add_argument("--service-contract")
    result.add_argument("--provider-contract", action="append", default=[])
    result.add_argument("--report")
    result.add_argument("--verify-report")
    return result


def main(argv: list[str] | None = None) -> int:
    argument_parser = parser()
    args = argument_parser.parse_args(argv)
    if args.verify_report:
        if args.component or args.service_contract or args.provider_contract or args.report:
            argument_parser.error("--verify-report cannot be combined with generation inputs")
        return verify_report_command(args)
    if not args.component or not args.service_contract:
        argument_parser.error("component and --service-contract are required")
    return validate_command(args)


if __name__ == "__main__":
    raise SystemExit(main())
