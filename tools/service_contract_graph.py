#!/usr/bin/env python3
"""Build and verify the production Bundle service-contract dependency graph."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from typing import Any

import component_contract_test as contract


BASELINE_PRODUCT = "PocoDDSRuntimeServiceContractBaseline"
REPORT_OPERATION = "service-contract-graph"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_digest(document: Any) -> str:
    payload = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def atomic_json(path: Path, document: dict[str, Any]) -> None:
    path = path.resolve()
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


def confined(root: Path, value: Path, description: str) -> Path:
    candidate = value if value.is_absolute() else root / value
    candidate = candidate.resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"{description} must stay inside repository root") from error
    return candidate


def relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def required_text(parent: ET.Element, path: str, description: str) -> str:
    node = parent.find(path)
    value = node.text.strip() if node is not None and node.text else ""
    if not value:
        raise ValueError(f"Bundle spec is missing {description}")
    return value


def semantic_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        key: bundle[key]
        for key in (
            "owner", "path", "bundleVersion", "runLevel", "lazyStart",
            "provides", "requires",
        )
    }


def load_bundle(root: Path, contract_path: Path) -> dict[str, Any]:
    if contract_path.parent.name != "bundle":
        raise ValueError(f"service contract must be in a bundle directory: {contract_path}")
    component_dir = contract_path.parent.parent
    specs = sorted(component_dir.glob("*.bndlspec"))
    if len(specs) != 1:
        raise ValueError(
            f"service contract owner must have exactly one Bundle spec: {component_dir}"
        )
    spec_path = specs[0]
    try:
        document = ET.parse(spec_path).getroot()
    except ET.ParseError as error:
        raise ValueError(f"Bundle spec XML is invalid: {spec_path}: {error}") from error
    if document.tag != "bundlespec":
        raise ValueError(f"Bundle spec root is invalid: {spec_path}")
    manifest = document.find("manifest")
    if manifest is None:
        raise ValueError(f"Bundle spec manifest is missing: {spec_path}")
    owner = required_text(manifest, "symbolicName", "manifest.symbolicName")
    if contract.IDENTIFIER.fullmatch(owner) is None:
        raise ValueError(f"Bundle symbolic name is invalid: {owner}")
    bundle_version = required_text(manifest, "version", "manifest.version")
    contract.parse_version(bundle_version)
    run_level_text = required_text(manifest, "runLevel", "manifest.runLevel")
    if not run_level_text.isdigit() or int(run_level_text) > 999:
        raise ValueError(f"Bundle run level is invalid: {spec_path}")
    lazy_text = required_text(manifest, "lazyStart", "manifest.lazyStart").lower()
    if lazy_text not in {"true", "false"}:
        raise ValueError(f"Bundle lazyStart is invalid: {spec_path}")
    files = required_text(document, "files", "files")
    if "bundle/*" not in {item.strip() for item in files.split(",")}:
        raise ValueError(
            f"Bundle spec does not package bundle/service-contracts.json: {spec_path}"
        )
    service = contract.load_service_contract(contract_path)
    return {
        "owner": owner,
        "path": relative(root, contract_path),
        "bndlspec": relative(root, spec_path),
        "bundleVersion": bundle_version,
        "runLevel": int(run_level_text),
        "lazyStart": lazy_text == "true",
        "contractSha256": sha256(contract_path),
        "bundleSpecSha256": sha256(spec_path),
        "provides": service["provides"],
        "requires": service["requires"],
    }


def discover(root: Path, scan_root: Path) -> list[dict[str, Any]]:
    scan = confined(root, scan_root, "service contract scan root")
    if not scan.is_dir():
        raise FileNotFoundError(f"service contract scan root is missing: {scan}")
    paths = sorted(
        (path.resolve() for path in scan.rglob("service-contracts.json")),
        key=lambda path: relative(root, path),
    )
    if not paths:
        raise ValueError(f"no production service contracts found below {scan}")
    bundles = [load_bundle(root, path) for path in paths]
    owners: set[str] = set()
    for bundle in bundles:
        if bundle["owner"] in owners:
            raise ValueError(f"duplicate Bundle service-contract owner: {bundle['owner']}")
        owners.add(bundle["owner"])
    return bundles


def load_baseline(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(document, dict)
            or set(document) != {"schemaVersion", "product", "bundles"}
            or document.get("schemaVersion") != 1
            or document.get("product") != BASELINE_PRODUCT
            or not isinstance(document.get("bundles"), list)):
        raise ValueError("service contract baseline is malformed")
    owners: set[str] = set()
    for bundle in document["bundles"]:
        expected = {
            "owner", "path", "bundleVersion", "runLevel", "lazyStart",
            "provides", "requires",
        }
        if not isinstance(bundle, dict) or set(bundle) != expected:
            raise ValueError("service contract baseline Bundle is malformed")
        owner = bundle.get("owner")
        path_value = bundle.get("path")
        version_value = bundle.get("bundleVersion")
        if (not isinstance(owner, str) or contract.IDENTIFIER.fullmatch(owner) is None
                or not isinstance(path_value, str) or "\\" in path_value
                or PurePosixPath(path_value).is_absolute()
                or any(part in {"", ".", ".."} for part in PurePosixPath(path_value).parts)
                or not path_value.endswith("/bundle/service-contracts.json")
                or not isinstance(version_value, str)):
            raise ValueError("service contract baseline Bundle identity is malformed")
        if bundle["owner"] in owners:
            raise ValueError("service contract baseline repeats a Bundle owner")
        owners.add(bundle["owner"])
        contract.parse_version(bundle["bundleVersion"])
        if (not isinstance(bundle["runLevel"], int)
                or isinstance(bundle["runLevel"], bool)
                or not 0 <= bundle["runLevel"] <= 999
                or not isinstance(bundle["lazyStart"], bool)):
            raise ValueError("service contract baseline Bundle metadata is malformed")
        # Reuse the exact runtime contract parser by validating an in-memory clone below.
        if not isinstance(bundle["provides"], list) or not isinstance(bundle["requires"], list):
            raise ValueError("service contract baseline declarations are malformed")
        provider_keys: set[tuple[str, str]] = set()
        for provider in bundle["provides"]:
            if (not isinstance(provider, dict)
                    or set(provider) != {"contract", "version", "serviceName"}
                    or contract.IDENTIFIER.fullmatch(str(provider.get("contract", ""))) is None
                    or contract.VERSION.fullmatch(str(provider.get("version", ""))) is None
                    or contract.SERVICE_NAME.fullmatch(
                        str(provider.get("serviceName", ""))) is None):
                raise ValueError("service contract baseline Provider is malformed")
            contract.parse_version(provider["version"])
            key = (provider["contract"], provider["serviceName"])
            if key in provider_keys:
                raise ValueError("service contract baseline repeats a Provider")
            provider_keys.add(key)
        requirement_keys: set[str] = set()
        for requirement in bundle["requires"]:
            if (not isinstance(requirement, dict)
                    or set(requirement) != {
                        "contract", "versionRange", "required", "minimumProviders"
                    }
                    or contract.IDENTIFIER.fullmatch(
                        str(requirement.get("contract", ""))) is None
                    or not isinstance(requirement.get("required"), bool)
                    or not isinstance(requirement.get("minimumProviders"), int)
                    or isinstance(requirement.get("minimumProviders"), bool)
                    or not 1 <= requirement["minimumProviders"] <= 64):
                raise ValueError("service contract baseline Requirement is malformed")
            contract.validate_version_range(
                requirement.get("versionRange"), "baseline requirement.versionRange"
            )
            if requirement["contract"] in requirement_keys:
                raise ValueError("service contract baseline repeats a Requirement")
            requirement_keys.add(requirement["contract"])
    return document


def provider_label(provider: dict[str, Any]) -> str:
    return (
        f"{provider['owner']}/{provider['serviceName']}@{provider['version']}"
    )


def canonical_cycle(values: list[str]) -> tuple[str, ...]:
    nodes = values[:-1]
    rotations = [tuple(nodes[index:] + nodes[:index]) for index in range(len(nodes))]
    smallest = min(rotations)
    return (*smallest, smallest[0])


def find_cycles(owners: list[str], edges: list[dict[str, Any]]) -> list[list[str]]:
    adjacency = {owner: set() for owner in owners}
    for edge in edges:
        if edge["required"]:
            adjacency[edge["consumer"]].add(edge["provider"])
    state: dict[str, int] = {owner: 0 for owner in owners}
    stack: list[str] = []
    cycles: set[tuple[str, ...]] = set()

    def visit(owner: str) -> None:
        state[owner] = 1
        stack.append(owner)
        for dependency in sorted(adjacency[owner]):
            if state[dependency] == 0:
                visit(dependency)
            elif state[dependency] == 1:
                begin = stack.index(dependency)
                cycles.add(canonical_cycle(stack[begin:] + [dependency]))
        stack.pop()
        state[owner] = 2

    for owner in sorted(owners):
        if state[owner] == 0:
            visit(owner)
    return [list(cycle) for cycle in sorted(cycles)]


def compatibility_violations(bundles: list[dict[str, Any]],
                             baseline: dict[str, Any]) -> tuple[list[str], list[str]]:
    violations: list[str] = []
    warnings: list[str] = []
    current = {bundle["owner"]: bundle for bundle in bundles}
    for published in baseline["bundles"]:
        owner = published["owner"]
        candidate = current.get(owner)
        if candidate is None:
            violations.append(f"published service-contract owner removed: {owner}")
            continue
        if contract.parse_version(candidate["bundleVersion"]) < contract.parse_version(
                published["bundleVersion"]):
            violations.append(f"Bundle version decreased: {owner}")
        for provider in published["provides"]:
            previous_version = contract.parse_version(provider["version"])
            same_service = next((
                item for item in candidate["provides"]
                if item["contract"] == provider["contract"]
                and item["serviceName"] == provider["serviceName"]
            ), None)
            if same_service is not None:
                current_version = contract.parse_version(same_service["version"])
                if current_version < previous_version:
                    violations.append(
                        f"Provider version decreased: {owner}/{provider['contract']}"
                    )
                elif current_version[0] > previous_version[0]:
                    warnings.append(
                        f"Provider major-version upgrade: {owner}/{provider['contract']} "
                        f"{provider['version']} -> {same_service['version']}"
                    )
                continue
            replacements = [
                item for item in candidate["provides"]
                if item["contract"] == provider["contract"]
                and contract.parse_version(item["version"])[0] > previous_version[0]
            ]
            if replacements:
                warnings.append(
                    f"Provider major-version replacement: {owner}/{provider['contract']} "
                    f"{provider['version']} -> {replacements[0]['version']}"
                )
            else:
                violations.append(
                    f"published Provider removed or renamed without a major version bump: "
                    f"{owner}/{provider['contract']}/{provider['serviceName']}"
                )
    return violations, warnings


def build_report(root: Path, scan_root: Path, baseline_path: Path) -> dict[str, Any]:
    bundles = discover(root, scan_root)
    baseline = load_baseline(baseline_path)
    providers: list[dict[str, Any]] = []
    for bundle in bundles:
        providers.extend({"owner": bundle["owner"], **item} for item in bundle["provides"])
    violations, warnings = compatibility_violations(bundles, baseline)
    service_names: dict[str, str] = {}
    for provider in providers:
        previous = service_names.get(provider["serviceName"])
        if previous is not None:
            violations.append(
                f"serviceName is declared by multiple owners: "
                f"{provider['serviceName']} ({previous}, {provider['owner']})"
            )
        service_names[provider["serviceName"]] = provider["owner"]

    results: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    required_satisfied = 0
    optional_unsatisfied = 0
    for bundle in bundles:
        for requirement in bundle["requires"]:
            declared = [
                provider for provider in providers
                if provider["contract"] == requirement["contract"]
            ]
            matching = [
                provider for provider in declared
                if contract.matches_version(
                    provider["version"], requirement["versionRange"]
                )
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
                "owner": bundle["owner"], **requirement, "status": status,
                "declaredProviders": len(declared),
                "matchingProviders": len(matching),
                "availableVersions": sorted({item["version"] for item in declared}),
                "matchedProviders": sorted(provider_label(item) for item in matching),
            }
            results.append(result)
            for provider in matching:
                edges.append({
                    "consumer": bundle["owner"], "provider": provider["owner"],
                    "contract": requirement["contract"],
                    "required": requirement["required"],
                })
            if status != "satisfied":
                detail = (
                    f"{bundle['owner']} requires {requirement['contract']} "
                    f"{requirement['versionRange']} x{requirement['minimumProviders']}: {status}"
                )
                if requirement["required"]:
                    violations.append(detail)
                else:
                    optional_unsatisfied += 1
                    warnings.append("optional " + detail)
    edges = sorted(
        {(
            item["consumer"], item["provider"], item["contract"], item["required"]
        ) for item in edges}
    )
    edge_documents = [
        {"consumer": item[0], "provider": item[1], "contract": item[2],
         "required": item[3]}
        for item in edges
    ]
    owners = [bundle["owner"] for bundle in bundles]
    cycles = find_cycles(owners, edge_documents)
    for cycle in cycles:
        violations.append("required service dependency cycle: " + " -> ".join(cycle))
    inputs = sorted([
        {"role": "service-contract", "path": bundle["path"],
         "sha256": bundle["contractSha256"]}
        for bundle in bundles
    ] + [
        {"role": "bundle-spec", "path": bundle["bndlspec"],
         "sha256": bundle["bundleSpecSha256"]}
        for bundle in bundles
    ], key=lambda item: (item["role"], item["path"]))
    required_count = sum(
        item["required"] for bundle in bundles for item in bundle["requires"]
    )
    return {
        "schemaVersion": 1,
        "operation": REPORT_OPERATION,
        "passed": not violations,
        "scanRoot": relative(root, confined(root, scan_root, "service contract scan root")),
        "baseline": relative(root, baseline_path),
        "baselineSha256": sha256(baseline_path),
        "inputSetSha256": canonical_digest(inputs),
        "inputs": inputs,
        "bundleCount": len(bundles),
        "providerCount": len(providers),
        "requirementCount": len(results),
        "requiredRequirementCount": required_count,
        "requiredSatisfiedCount": required_satisfied,
        "optionalUnsatisfiedCount": optional_unsatisfied,
        "bundles": bundles,
        "requirements": results,
        "edges": edge_documents,
        "cycles": cycles,
        "violations": sorted(set(violations)),
        "warnings": sorted(set(warnings)),
    }


def snapshot_command(args: argparse.Namespace) -> int:
    try:
        root = args.root.resolve()
        bundles = discover(root, args.scan_root)
        document = {
            "schemaVersion": 1,
            "product": BASELINE_PRODUCT,
            "bundles": [semantic_bundle(bundle) for bundle in bundles],
        }
        atomic_json(args.output.resolve(), document)
        print(
            f"SERVICE_CONTRACT_BASELINE_PASS bundles={len(bundles)} "
            f"output={args.output.resolve()}"
        )
        return 0
    except (OSError, ValueError, ET.ParseError, json.JSONDecodeError) as error:
        print(f"SERVICE_CONTRACT_BASELINE_ERROR: {error}", file=os.sys.stderr)
        return 2


def check_command(args: argparse.Namespace) -> int:
    try:
        root = args.root.resolve()
        baseline = confined(root, args.baseline, "service contract baseline")
        report = build_report(root, args.scan_root, baseline)
        if args.report:
            atomic_json(args.report.resolve(), report)
        if not report["passed"]:
            print(
                "SERVICE_CONTRACT_GRAPH_ERROR: " + "; ".join(report["violations"]),
                file=os.sys.stderr,
            )
            return 1
        print(
            f"SERVICE_CONTRACT_GRAPH_PASS bundles={report['bundleCount']} "
            f"providers={report['providerCount']} "
            f"requirements={report['requirementCount']} "
            f"warnings={len(report['warnings'])}"
        )
        return 0
    except (OSError, ValueError, ET.ParseError, json.JSONDecodeError) as error:
        print(f"SERVICE_CONTRACT_GRAPH_ERROR: {error}", file=os.sys.stderr)
        return 2


def verify_command(args: argparse.Namespace) -> int:
    try:
        root = args.root.resolve()
        baseline = confined(root, args.baseline, "service contract baseline")
        expected = build_report(root, args.scan_root, baseline)
        actual = json.loads(args.report.resolve().read_text(encoding="utf-8"))
        if actual != expected:
            raise ValueError("service contract graph report differs from current bound inputs")
        if not expected["passed"]:
            raise ValueError("service contract graph report records violations")
        print(
            f"SERVICE_CONTRACT_GRAPH_EVIDENCE_PASS "
            f"inputSetSha256={expected['inputSetSha256']}"
        )
        return 0
    except (OSError, ValueError, ET.ParseError, json.JSONDecodeError) as error:
        print(f"SERVICE_CONTRACT_GRAPH_EVIDENCE_ERROR: {error}", file=os.sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Validate the repository-wide production Bundle service-contract graph"
    )
    commands = result.add_subparsers(dest="command", required=True)
    for name in ("snapshot", "check", "verify"):
        command = commands.add_parser(name)
        command.add_argument("--root", type=Path, default=Path("."))
        command.add_argument("--scan-root", type=Path, default=Path("services"))
        if name == "snapshot":
            command.add_argument("--output", type=Path, required=True)
            command.set_defaults(handler=snapshot_command)
        else:
            command.add_argument(
                "--baseline", type=Path,
                default=Path("contracts/service-contract-baseline.json"),
            )
            command.add_argument("--report", type=Path, required=True)
            command.set_defaults(
                handler=check_command if name == "check" else verify_command
            )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
