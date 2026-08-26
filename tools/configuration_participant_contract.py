#!/usr/bin/env python3
"""Validate Bundle-local transactional configuration participant declarations."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any
import xml.etree.ElementTree as ET


MAXIMUM_DOCUMENT_BYTES = 64 * 1024
MAXIMUM_DOCUMENT_PARTICIPANTS = 128
MAXIMUM_DECLARATIONS = 1024
MAXIMUM_ARRAY_ITEMS = 64
BASELINE_PRODUCT = "PocoDDSRuntimeConfigurationParticipantBaseline"
ID = re.compile(r"^[a-z][a-z0-9.-]{0,127}$")
SERVICE = re.compile(r"^[A-Za-z0-9._:-]{1,192}$")
PREFIX = re.compile(r"^[A-Za-z0-9_-](?:[A-Za-z0-9._-]*[A-Za-z0-9_-])?$")
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
IGNORED_DIRECTORY_NAMES = {
    ".git", ".idea", ".vs", ".vscode", "node_modules", "reports",
}
DISCOVERY_ROOTS = (
    "application", "bundles", "platform", "plugins", "services", "SubSystem", "webui",
)


class ContractError(ValueError):
    def __init__(self, code: str, detail: str, path: Path | None = None) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.path = path


def owns(prefix: str, key: str) -> bool:
    return key == prefix or key.startswith(prefix + ".")


def overlaps(left: str, right: str) -> bool:
    return owns(left, right) or owns(right, left)


def discover(root: Path) -> list[Path]:
    root = root.resolve()
    paths: set[Path] = set()
    direct = root / "bundle" / "configuration-participants.json"
    if direct.is_file():
        paths.add(direct.resolve())
    for name in DISCOVERY_ROOTS:
        search_root = root / name
        if not search_root.is_dir():
            continue
        for path in search_root.rglob("configuration-participants.json"):
            relative_parts = path.relative_to(search_root).parts[:-1]
            if any(part in IGNORED_DIRECTORY_NAMES or part.startswith("build")
                   for part in relative_parts):
                continue
            if path.parent.name == "bundle":
                paths.add(path.resolve())
    return sorted(paths)


def bundle_owner(path: Path) -> str:
    if path.name != "configuration-participants.json" or path.parent.name != "bundle":
        raise ContractError(
            "declaration-location-invalid",
            "declaration must be named bundle/configuration-participants.json",
            path,
        )
    component = path.parent.parent
    specifications = sorted(component.glob("*.bndlspec"))
    if len(specifications) != 1:
        raise ContractError(
            "bundle-spec-invalid",
            "declaration owner must contain exactly one Bundle specification",
            path,
        )
    specification = specifications[0]
    try:
        root = ET.fromstring(specification.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ET.ParseError) as error:
        raise ContractError(
            "bundle-spec-invalid", "Bundle specification is not valid UTF-8 XML", specification
        ) from error
    symbolic_names = root.findall("./manifest/symbolicName")
    owner = symbolic_names[0].text.strip() if len(symbolic_names) == 1 and symbolic_names[0].text else ""
    files = [item.text.strip() for item in root.findall("./files") if item.text]
    if not SERVICE.fullmatch(owner):
        raise ContractError(
            "bundle-owner-invalid", "Bundle specification has no valid symbolicName", specification
        )
    if "bundle/*" not in files:
        raise ContractError(
            "declaration-not-packaged",
            "Bundle specification must package <files>bundle/*</files>",
            specification,
        )
    return owner


def require_string_array(item: dict[str, Any], field: str, *, nonempty: bool,
                         pattern: re.Pattern[str], path: Path) -> list[str]:
    value = item.get(field)
    if (not isinstance(value, list) or len(value) > MAXIMUM_ARRAY_ITEMS or
            (nonempty and not value)):
        raise ContractError(
            "declaration-invalid", f"{field} has an invalid item count", path
        )
    if any(not isinstance(entry, str) or pattern.fullmatch(entry) is None for entry in value):
        raise ContractError(
            "declaration-invalid", f"{field} contains an invalid entry", path
        )
    if len(set(value)) != len(value):
        raise ContractError(
            "declaration-invalid", f"{field} contains duplicate entries", path
        )
    return sorted(value)


def parse_document(path: Path) -> tuple[str, list[dict[str, Any]], str]:
    path = path.resolve()
    owner = bundle_owner(path)
    try:
        data = path.read_bytes()
    except OSError as error:
        raise ContractError("declaration-unreadable", "cannot read declaration", path) from error
    if len(data) > MAXIMUM_DOCUMENT_BYTES:
        raise ContractError(
            "declaration-too-large", "declaration exceeds 64 KiB", path
        )
    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ContractError(
            "declaration-invalid", "declaration is not valid UTF-8 JSON", path
        ) from error
    if not isinstance(document, dict) or set(document) != {"schemaVersion", "participants"}:
        raise ContractError(
            "declaration-invalid", "declaration has an unexpected envelope", path
        )
    if document["schemaVersion"] != 1 or isinstance(document["schemaVersion"], bool):
        raise ContractError(
            "declaration-invalid", "schemaVersion must equal integer 1", path
        )
    participants = document["participants"]
    if not isinstance(participants, list) or len(participants) > MAXIMUM_DOCUMENT_PARTICIPANTS:
        raise ContractError(
            "declaration-invalid", "participants has an invalid item count", path
        )
    parsed: list[dict[str, Any]] = []
    local_ids: set[str] = set()
    local_services: set[str] = set()
    local_prefixes: list[str] = []
    for index, item in enumerate(participants):
        if not isinstance(item, dict) or set(item) != {
                "id", "serviceName", "ownedPrefixes", "after"}:
            raise ContractError(
                "declaration-invalid", f"participant {index} has unexpected fields", path
            )
        participant_id = item["id"]
        service_name = item["serviceName"]
        if not isinstance(participant_id, str) or ID.fullmatch(participant_id) is None:
            raise ContractError(
                "declaration-invalid", f"participant {index} has an invalid id", path
            )
        if not isinstance(service_name, str) or SERVICE.fullmatch(service_name) is None:
            raise ContractError(
                "declaration-invalid", f"participant {index} has an invalid serviceName", path
            )
        prefixes = require_string_array(
            item, "ownedPrefixes", nonempty=True, pattern=PREFIX, path=path
        )
        after = require_string_array(item, "after", nonempty=False, pattern=ID, path=path)
        if participant_id in after:
            raise ContractError(
                "dependency-self-reference",
                f"participant {participant_id} depends on itself",
                path,
            )
        if participant_id in local_ids:
            raise ContractError(
                "duplicate-participant-id", f"duplicate participant id {participant_id}", path
            )
        if service_name in local_services:
            raise ContractError(
                "duplicate-service-name", f"duplicate serviceName {service_name}", path
            )
        for prefix in prefixes:
            conflict = next((known for known in local_prefixes if overlaps(prefix, known)), None)
            if conflict is not None:
                raise ContractError(
                    "prefix-overlap", f"owned prefix {prefix} overlaps {conflict}", path
                )
            local_prefixes.append(prefix)
        local_ids.add(participant_id)
        local_services.add(service_name)
        parsed.append({
            "owner": owner,
            "path": path,
            "id": participant_id,
            "serviceName": service_name,
            "ownedPrefixes": prefixes,
            "after": after,
        })
    return owner, parsed, hashlib.sha256(data).hexdigest()


def cycle_nodes(graph: dict[str, list[str]]) -> set[str]:
    colors: dict[str, int] = {}
    stack: list[str] = []
    cyclic: set[str] = set()

    def visit(node: str) -> None:
        colors[node] = 1
        stack.append(node)
        for dependency in graph[node]:
            if dependency not in graph:
                continue
            if colors.get(dependency, 0) == 1:
                cyclic.update(stack[stack.index(dependency):])
            elif colors.get(dependency, 0) == 0:
                visit(dependency)
        stack.pop()
        colors[node] = 2

    for node in sorted(graph):
        if colors.get(node, 0) == 0:
            visit(node)
    return cyclic


def load_baseline(path: Path) -> tuple[dict[str, Any], str]:
    path = path.resolve()
    try:
        data = path.read_bytes()
        document = json.loads(data.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContractError(
            "baseline-invalid", "baseline is not valid UTF-8 JSON", path
        ) from error
    if (not isinstance(document, dict) or set(document) != {
            "schemaVersion", "product", "runtimeVersion", "participants"} or
            document.get("schemaVersion") != 1 or
            isinstance(document.get("schemaVersion"), bool) or
            document.get("product") != BASELINE_PRODUCT or
            not isinstance(document.get("runtimeVersion"), str) or
            VERSION.fullmatch(document["runtimeVersion"]) is None or
            not isinstance(document.get("participants"), list) or
            not document["participants"] or
            len(document["participants"]) > MAXIMUM_DECLARATIONS):
        raise ContractError("baseline-invalid", "baseline envelope is invalid", path)

    ids: set[str] = set()
    services: set[str] = set()
    prefixes: list[str] = []
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(document["participants"]):
        if not isinstance(item, dict) or set(item) != {
                "owner", "id", "serviceName", "ownedPrefixes", "after"}:
            raise ContractError(
                "baseline-invalid", f"baseline participant {index} has unexpected fields", path
            )
        owner = item["owner"]
        participant_id = item["id"]
        service_name = item["serviceName"]
        if (not isinstance(owner, str) or SERVICE.fullmatch(owner) is None or
                not isinstance(participant_id, str) or ID.fullmatch(participant_id) is None or
                not isinstance(service_name, str) or SERVICE.fullmatch(service_name) is None):
            raise ContractError(
                "baseline-invalid", f"baseline participant {index} identity is invalid", path
            )
        try:
            owned_prefixes = require_string_array(
                item, "ownedPrefixes", nonempty=True, pattern=PREFIX, path=path
            )
            after = require_string_array(
                item, "after", nonempty=False, pattern=ID, path=path
            )
        except ContractError as error:
            raise ContractError(
                "baseline-invalid", f"baseline participant {index}: {error.detail}", path
            ) from error
        if participant_id in after:
            raise ContractError(
                "baseline-invalid", f"baseline participant {participant_id} depends on itself", path
            )
        if participant_id in ids or service_name in services:
            raise ContractError(
                "baseline-invalid", "baseline repeats a participant ID or serviceName", path
            )
        for prefix in owned_prefixes:
            conflict = next((known for known in prefixes if overlaps(prefix, known)), None)
            if conflict is not None:
                raise ContractError(
                    "baseline-invalid", f"baseline prefix {prefix} overlaps {conflict}", path
                )
            prefixes.append(prefix)
        ids.add(participant_id)
        services.add(service_name)
        normalized.append({
            "owner": owner,
            "id": participant_id,
            "serviceName": service_name,
            "ownedPrefixes": owned_prefixes,
            "after": after,
        })
    cyclic = cycle_nodes({item["id"]: item["after"] for item in normalized})
    if cyclic:
        raise ContractError(
            "baseline-invalid",
            "baseline dependency cycle: " + ",".join(sorted(cyclic)),
            path,
        )
    return {
        "schemaVersion": 1,
        "product": BASELINE_PRODUCT,
        "runtimeVersion": document["runtimeVersion"],
        "participants": sorted(normalized, key=lambda item: item["id"]),
    }, hashlib.sha256(data).hexdigest()


def compatibility_violations(
        current: list[dict[str, Any]], baseline: dict[str, Any]) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    current_by_id = {item["id"]: item for item in current}
    current_by_service = {item["serviceName"]: item for item in current}
    for published in baseline["participants"]:
        candidate = current_by_id.get(published["id"])
        if candidate is None:
            violations.append({
                "code": "published-participant-removed",
                "participantId": published["id"],
                "detail": "published participant is missing from the candidate",
            })
            reassigned = current_by_service.get(published["serviceName"])
            if reassigned is not None:
                violations.append({
                    "code": "published-service-reassigned",
                    "participantId": published["id"],
                    "detail": "published serviceName is assigned to another participant",
                })
            for prefix in published["ownedPrefixes"]:
                replacement = next((
                    item for item in current
                    if any(owns(current_prefix, prefix)
                           for current_prefix in item["ownedPrefixes"])
                ), None)
                if replacement is not None:
                    violations.append({
                        "code": "published-prefix-owner-changed",
                        "participantId": published["id"],
                        "detail": f"published prefix {prefix} moved to {replacement['id']}",
                    })
            continue
        if candidate["owner"] != published["owner"]:
            violations.append({
                "code": "published-owner-changed",
                "participantId": published["id"],
                "detail": "published Bundle owner changed",
            })
        if candidate["serviceName"] != published["serviceName"]:
            violations.append({
                "code": "published-service-name-changed",
                "participantId": published["id"],
                "detail": "published serviceName changed",
            })
        for prefix in published["ownedPrefixes"]:
            if not any(owns(current_prefix, prefix)
                       for current_prefix in candidate["ownedPrefixes"]):
                replacement = next((
                    item for item in current
                    if item["id"] != published["id"] and any(
                        owns(current_prefix, prefix)
                        for current_prefix in item["ownedPrefixes"]
                    )
                ), None)
                if replacement is not None:
                    violations.append({
                        "code": "published-prefix-owner-changed",
                        "participantId": published["id"],
                        "detail": f"published prefix {prefix} moved to {replacement['id']}",
                    })
                else:
                    violations.append({
                        "code": "published-prefix-narrowed",
                        "participantId": published["id"],
                        "detail": f"published prefix {prefix} is no longer fully owned",
                    })
        for dependency in published["after"]:
            if dependency not in candidate["after"]:
                violations.append({
                    "code": "published-dependency-removed",
                    "participantId": published["id"],
                    "detail": f"published ordering dependency {dependency} was removed",
                })
    return sorted(
        violations, key=lambda item: (item["participantId"], item["code"], item["detail"])
    )


def validate(paths: list[Path], baseline_path: Path | None = None) -> dict[str, Any]:
    unique_paths = sorted({path.resolve() for path in paths})
    if not unique_paths:
        raise ContractError("declaration-missing", "no participant declarations were supplied")
    declarations: list[dict[str, Any]] = []
    owners: list[str] = []
    inputs: list[dict[str, str]] = []
    for path in unique_paths:
        owner, parsed, digest = parse_document(path)
        owners.append(owner)
        inputs.append({"owner": owner, "path": str(path), "sha256": digest})
        declarations.extend(parsed)
        if len(declarations) > MAXIMUM_DECLARATIONS:
            raise ContractError(
                "declaration-capacity-exceeded", "declarations exceed global capacity", path
            )

    ids: dict[str, dict[str, Any]] = {}
    services: dict[str, dict[str, Any]] = {}
    prefixes: list[tuple[str, dict[str, Any]]] = []
    for declaration in declarations:
        participant_id = declaration["id"]
        service_name = declaration["serviceName"]
        if participant_id in ids:
            raise ContractError(
                "duplicate-participant-id",
                f"participant id {participant_id} is owned by multiple Bundles",
                declaration["path"],
            )
        if service_name in services:
            raise ContractError(
                "duplicate-service-name",
                f"serviceName {service_name} is owned by multiple Bundles",
                declaration["path"],
            )
        for prefix in declaration["ownedPrefixes"]:
            conflict = next((item for item in prefixes if overlaps(prefix, item[0])), None)
            if conflict is not None:
                raise ContractError(
                    "prefix-overlap",
                    f"owned prefix {prefix} overlaps {conflict[0]}",
                    declaration["path"],
                )
            prefixes.append((prefix, declaration))
        ids[participant_id] = declaration
        services[service_name] = declaration

    graph = {item["id"]: item["after"] for item in declarations}
    cyclic = cycle_nodes(graph)
    if cyclic:
        first = ids[sorted(cyclic)[0]]
        raise ContractError(
            "dependency-cycle",
            "configuration participant dependency cycle: " + ",".join(sorted(cyclic)),
            first["path"],
        )
    input_identity = [
        {"owner": item["owner"], "sha256": item["sha256"]}
        for item in sorted(inputs, key=lambda entry: (entry["owner"], entry["sha256"]))
    ]
    input_set_sha256 = hashlib.sha256(json.dumps(
        input_identity, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    current_participants = [
        {
            "owner": item["owner"],
            "id": item["id"],
            "serviceName": item["serviceName"],
            "ownedPrefixes": item["ownedPrefixes"],
            "after": item["after"],
        }
        for item in sorted(declarations, key=lambda entry: entry["id"])
    ]
    baseline_evidence = None
    violations: list[dict[str, str]] = []
    if baseline_path is not None:
        baseline, baseline_sha256 = load_baseline(baseline_path)
        baseline_evidence = {
            "path": str(baseline_path.resolve()),
            "sha256": baseline_sha256,
            "runtimeVersion": baseline["runtimeVersion"],
            "participantCount": len(baseline["participants"]),
        }
        violations = compatibility_violations(current_participants, baseline)
    compatible = not violations
    return {
        "schemaVersion": 1,
        "operation": "configuration-participant-contract",
        "passed": compatible,
        "compatible": compatible,
        "declarationCount": len(unique_paths),
        "participantCount": len(declarations),
        "inputSetSha256": input_set_sha256,
        "inputs": sorted(inputs, key=lambda item: item["owner"]),
        "owners": sorted(set(owners)),
        "participants": current_participants,
        "baseline": baseline_evidence,
        "violations": violations,
        "errors": [],
    }


def atomic_json(path: Path, document: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8", newline="\n")
    temporary.replace(path)


def execute(paths: list[Path], report_path: Path | None = None,
            baseline_path: Path | None = None) -> int:
    try:
        report = validate(paths, baseline_path)
    except ContractError as error:
        report = {
            "schemaVersion": 1,
            "operation": "configuration-participant-contract",
            "passed": False,
            "compatible": False,
            "declarationCount": len({path.resolve() for path in paths}),
            "participantCount": 0,
            "inputSetSha256": None,
            "inputs": [],
            "owners": [],
            "participants": [],
            "baseline": None,
            "violations": [],
            "errors": [{
                "code": error.code,
                "path": str(error.path.resolve()) if error.path else "",
                "detail": error.detail,
            }],
        }
        if report_path:
            atomic_json(report_path, report)
        print(
            f"PDR_CONFIGURATION_PARTICIPANT_CONTRACT_FAIL code={error.code} "
            f"path={error.path or '-'}",
            file=sys.stderr,
        )
        return 2
    if report_path:
        atomic_json(report_path, report)
    if not report["compatible"]:
        print(
            "PDR_CONFIGURATION_PARTICIPANT_CONTRACT_INCOMPATIBLE "
            f"violations={len(report['violations'])}",
            file=sys.stderr,
        )
        return 1
    print(
        "PDR_CONFIGURATION_PARTICIPANT_CONTRACT_PASS "
        f"declarations={report['declarationCount']} participants={report['participantCount']}"
    )
    return 0


def validate_command(args: argparse.Namespace) -> int:
    paths = [Path(args.declaration)]
    paths.extend(Path(path) for path in args.provider_declaration)
    return execute(
        paths,
        Path(args.report) if args.report else None,
        Path(args.baseline) if getattr(args, "baseline", None) else None,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate Bundle-local configuration participant contracts."
    )
    parser.add_argument("--root", type=Path)
    parser.add_argument("--declaration", type=Path, action="append", default=[])
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    paths = list(args.declaration)
    if args.root:
        paths.extend(discover(args.root))
    return execute(paths, args.report, args.baseline)


if __name__ == "__main__":
    raise SystemExit(main())
