#!/usr/bin/env python3
"""Govern SDK surface deprecation notices and removal eligibility."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from framework_change_impact import atomic_json
import sdk_surface_guard as surface_guard


DEPRECATION_ID = re.compile(r"^PDR-DEP-[0-9]{4,}$")
MARKER = re.compile(r"PDR-DEP-[0-9]{4,}")
GOVERNED_MARKER = re.compile(
    r'\[\[\s*deprecated\s*\(\s*"(?P<id>PDR-DEP-[0-9]{4,}):\s*'
    r'(?:\\.|[^"\\])+"\s*\)\s*\]\]',
    re.DOTALL,
)
HEADER = re.compile(r"^include/PocoDDS/.+\.(?:h|hh|hpp|hxx)$")
TARGET = re.compile(r"^PocoDDS::\S+$")
ABI_ARTIFACT = re.compile(r"^(?:bin/PDR.+\.dll|lib/libPDR.+\.so(?:\..*)?)$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
KINDS = {"header", "cmake-target", "abi-artifact"}
STATES = {"active", "removed"}


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exact_fields(document: dict[str, Any], expected: set[str], label: str) -> None:
    if set(document) == expected:
        return
    missing = sorted(expected - set(document))
    unknown = sorted(set(document) - expected)
    detail = []
    if missing:
        detail.append("missing=" + ",".join(missing))
    if unknown:
        detail.append("unknown=" + ",".join(unknown))
    raise ValueError(f"{label} has invalid fields: {'; '.join(detail)}")


def validate_catalog(document: dict[str, Any]) -> list[dict[str, str]]:
    if not isinstance(document, dict):
        raise ValueError("SDK deprecation catalog root must be an object")
    exact_fields(document, {"schemaVersion", "entries"}, "SDK deprecation catalog")
    if (not isinstance(document["schemaVersion"], int)
            or isinstance(document["schemaVersion"], bool)
            or document["schemaVersion"] != 1):
        raise ValueError("SDK deprecation catalog schemaVersion must equal 1")
    if not isinstance(document["entries"], list):
        raise ValueError("SDK deprecation catalog entries must be an array")
    expected = {
        "id", "kind", "surface", "symbol", "state", "deprecatedSince",
        "removalAllowedFrom", "replacement", "owner", "noticeSurfaceSha256",
    }
    entries: list[dict[str, str]] = []
    ids: set[str] = set()
    surfaces: set[tuple[str, str]] = set()
    for index, item in enumerate(document["entries"]):
        if not isinstance(item, dict):
            raise ValueError(f"SDK deprecation entry {index} must be an object")
        exact_fields(item, expected, f"SDK deprecation entry {index}")
        if not isinstance(item["id"], str) or DEPRECATION_ID.fullmatch(item["id"]) is None:
            raise ValueError(f"SDK deprecation entry {index} id is invalid")
        if item["id"] in ids:
            raise ValueError(f"duplicate SDK deprecation id: {item['id']}")
        ids.add(item["id"])
        if not isinstance(item["kind"], str) or item["kind"] not in KINDS:
            raise ValueError(f"SDK deprecation entry {item['id']} kind is invalid")
        pattern = {
            "header": HEADER,
            "cmake-target": TARGET,
            "abi-artifact": ABI_ARTIFACT,
        }[item["kind"]]
        if not isinstance(item["surface"], str) or pattern.fullmatch(item["surface"]) is None:
            raise ValueError(f"SDK deprecation entry {item['id']} surface is invalid")
        surface_key = (item["kind"], item["surface"])
        if surface_key in surfaces:
            raise ValueError(
                f"duplicate SDK deprecation surface: {item['kind']} {item['surface']}"
            )
        surfaces.add(surface_key)
        for field in ("symbol", "replacement", "owner"):
            if not isinstance(item[field], str) or not item[field].strip():
                raise ValueError(f"SDK deprecation entry {item['id']} {field} is invalid")
        if not isinstance(item["state"], str) or item["state"] not in STATES:
            raise ValueError(f"SDK deprecation entry {item['id']} state is invalid")
        for version_field in ("deprecatedSince", "removalAllowedFrom"):
            if not isinstance(item[version_field], str):
                raise ValueError(
                    f"SDK deprecation entry {item['id']} {version_field} is invalid"
                )
        deprecated = surface_guard.semver(item["deprecatedSince"])
        removal = surface_guard.semver(item["removalAllowedFrom"])
        if removal <= deprecated:
            raise ValueError(
                f"SDK deprecation entry {item['id']} removal version must be later"
            )
        if removal[0] <= deprecated[0]:
            raise ValueError(
                f"SDK deprecation entry {item['id']} must retain the surface until a later major"
            )
        digest = item["noticeSurfaceSha256"]
        if not isinstance(digest, str) or SHA256.fullmatch(digest) is None:
            raise ValueError(
                f"SDK deprecation entry {item['id']} notice digest is invalid"
            )
        entries.append(dict(item))
    return sorted(entries, key=lambda item: item["id"])


def load_snapshot(path: Path, label: str) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    surface_guard.validate_snapshot(document, label)
    return document


def surface_value(snapshot: dict[str, Any], kind: str, name: str) -> str | None:
    if kind == "header":
        record = snapshot["publicHeaders"].get(name)
        return record.get("tokenSha256") if isinstance(record, dict) else None
    if kind == "cmake-target":
        return name if name in snapshot["cmakeLibraryTargets"] else None
    abi = snapshot.get("binaryAbi")
    if not isinstance(abi, dict):
        return None
    record = abi.get("artifacts", {}).get(name)
    return record.get("symbolSha256") if isinstance(record, dict) else None


def scan_markers(install: Path, current: dict[str, Any]) -> dict[str, list[str]]:
    observed = surface_guard.public_headers(install)
    if observed != current["publicHeaders"]:
        raise ValueError("installed public headers do not match the current SDK snapshot")
    markers: dict[str, list[str]] = {}
    for relative in current["publicHeaders"]:
        text = (install / relative).read_text(encoding="utf-8", errors="strict")
        all_markers = set(MARKER.findall(text))
        governed_markers = {
            match.group("id") for match in GOVERNED_MARKER.finditer(text)
        }
        malformed = sorted(all_markers - governed_markers)
        if malformed:
            raise ValueError(
                f"public header {relative} contains PDR-DEP IDs outside a standardized "
                f"deprecated attribute: {','.join(malformed)}"
            )
        for marker in sorted(governed_markers):
            markers.setdefault(marker, []).append(relative)
    return markers


def breaking_surfaces(baseline: dict[str, Any], current: dict[str, Any]) -> list[dict[str, str]]:
    comparison = surface_guard.compare(baseline, current, False)
    records = []
    for field, kind, change in (
        ("removedHeaders", "header", "removed"),
        ("changedHeaders", "header", "changed"),
        ("removedCmakeTargets", "cmake-target", "removed"),
        ("removedAbiArtifacts", "abi-artifact", "removed"),
        ("changedAbiArtifacts", "abi-artifact", "changed"),
    ):
        records.extend(
            {"kind": kind, "surface": item, "change": change}
            for item in comparison[field]
        )
    return sorted(records, key=lambda item: (item["kind"], item["surface"]))


def violation(code: str, detail: str, entry: dict[str, str] | None = None,
              kind: str = "", surface: str = "") -> dict[str, str]:
    return {
        "code": code,
        "id": entry["id"] if entry else "",
        "kind": entry["kind"] if entry else kind,
        "surface": entry["surface"] if entry else surface,
        "detail": detail,
    }


def input_record(role: str, path: Path) -> dict[str, str]:
    return {"role": role, "path": str(path.resolve()), "sha256": file_sha256(path)}


def input_set_sha256(inputs: list[dict[str, str]]) -> str:
    semantic = sorted(
        ({"role": item["role"], "sha256": item["sha256"]} for item in inputs),
        key=lambda item: (item["role"], item["sha256"]),
    )
    return hashlib.sha256(json.dumps(
        semantic, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def evaluate(catalog: dict[str, Any], baseline: dict[str, Any],
             current: dict[str, Any], published: list[dict[str, Any]],
             install: Path, inputs: list[dict[str, str]]) -> dict[str, Any]:
    entries = validate_catalog(catalog)
    baseline_version = surface_guard.semver(baseline["runtimeVersion"])
    current_version = surface_guard.semver(current["runtimeVersion"])
    if current_version < baseline_version:
        raise ValueError("current SDK version is older than the deprecation baseline")
    markers = scan_markers(install.resolve(), current)
    published_by_identity = {
        (item["runtimeVersion"], item["surfaceSha256"]): item for item in published
    }
    if len(published_by_identity) != len(published):
        raise ValueError("published SDK snapshots contain a duplicate version/surface identity")
    current_identity = (current["runtimeVersion"], current["surfaceSha256"])
    known_by_identity = {**published_by_identity, current_identity: current}
    by_id = {item["id"]: item for item in entries}
    by_surface = {(item["kind"], item["surface"]): item for item in entries}
    violations: list[dict[str, str]] = []

    for marker, paths in sorted(markers.items()):
        entry = by_id.get(marker)
        if entry is None:
            violations.append(violation(
                "unregistered-marker",
                f"header marker {marker} is not registered in the deprecation catalog",
                kind="header", surface=",".join(paths),
            ))
        elif entry["kind"] != "header" or paths != [entry["surface"]]:
            violations.append(violation(
                "marker-surface-mismatch",
                f"marker {marker} occurs in {','.join(paths)} instead of its declared header",
                entry,
            ))

    for entry in entries:
        notice_identity = (entry["deprecatedSince"], entry["noticeSurfaceSha256"])
        notice = known_by_identity.get(notice_identity)
        if notice is None:
            violations.append(violation(
                "unknown-notice-snapshot",
                "noticeSurfaceSha256 does not identify the current or a published SDK snapshot",
                entry,
            ))
            continue
        if notice["runtimeVersion"] != entry["deprecatedSince"]:
            violations.append(violation(
                "notice-version-mismatch",
                f"notice snapshot version {notice['runtimeVersion']} does not match deprecatedSince",
                entry,
            ))
        notice_value = surface_value(notice, entry["kind"], entry["surface"])
        if notice_value is None:
            violations.append(violation(
                "notice-surface-missing",
                "the declared surface did not exist in its notice snapshot",
                entry,
            ))
            continue
        current_value = surface_value(current, entry["kind"], entry["surface"])
        if entry["state"] == "active":
            if current_value is None:
                violations.append(violation(
                    "active-surface-missing",
                    "an active deprecated surface is missing from the current SDK",
                    entry,
                ))
            if entry["kind"] == "header" and entry["id"] not in markers:
                violations.append(violation(
                    "active-marker-missing",
                    "an active deprecated header has no matching PDR-DEP marker",
                    entry,
                ))
        else:
            if notice_identity not in published_by_identity:
                violations.append(violation(
                    "unpublished-notice-removal",
                    "surface removal is based only on an unpublished candidate snapshot",
                    entry,
                ))
            if current_version < surface_guard.semver(entry["removalAllowedFrom"]):
                violations.append(violation(
                    "early-removal",
                    f"current version {current['runtimeVersion']} is earlier than "
                    f"{entry['removalAllowedFrom']}",
                    entry,
                ))
            if current_value == notice_value:
                violations.append(violation(
                    "removed-surface-unchanged",
                    "catalog says removed but the notice surface is unchanged in the current SDK",
                    entry,
                ))
            if entry["kind"] == "cmake-target" and current_value is not None:
                violations.append(violation(
                    "removed-target-present",
                    "catalog says removed but the CMake target is still exported",
                    entry,
                ))

    breaking = breaking_surfaces(baseline, current)
    for item in breaking:
        entry = by_surface.get((item["kind"], item["surface"]))
        if entry is None:
            violations.append(violation(
                "unscheduled-breaking-surface",
                f"{item['change']} SDK surface has no deprecation lifecycle entry",
                kind=item["kind"], surface=item["surface"],
            ))
        elif entry["state"] != "removed":
            violations.append(violation(
                "breaking-surface-still-active",
                f"{item['change']} SDK surface is still marked active",
                entry,
            ))

    return {
        "schemaVersion": 1,
        "operation": "sdk-deprecation-policy",
        "passed": not violations,
        "baselineVersion": baseline["runtimeVersion"],
        "currentVersion": current["runtimeVersion"],
        "baselineSurfaceSha256": baseline["surfaceSha256"],
        "currentSurfaceSha256": current["surfaceSha256"],
        "inputs": inputs,
        "inputSetSha256": input_set_sha256(inputs),
        "publishedSnapshotCount": len(published_by_identity),
        "entryCount": len(entries),
        "activeEntryCount": sum(item["state"] == "active" for item in entries),
        "removedEntryCount": sum(item["state"] == "removed" for item in entries),
        "markerCount": len(markers),
        "breakingSurfaces": breaking,
        "violations": violations,
    }


def validate_command(args: argparse.Namespace) -> int:
    try:
        catalog_path = args.catalog.resolve()
        baseline_path = args.baseline.resolve()
        current_path = args.current.resolve()
        published_paths = [path.resolve() for path in args.published_snapshot]
        if baseline_path not in published_paths:
            published_paths.append(baseline_path)
        if len(set(published_paths)) != len(published_paths):
            raise ValueError("published SDK snapshot input is repeated")
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        baseline = load_snapshot(baseline_path, "deprecation baseline")
        current = load_snapshot(current_path, "deprecation current")
        published = [
            load_snapshot(path, f"published snapshot {index}")
            for index, path in enumerate(published_paths)
        ]
        inputs = [
            input_record("catalog", catalog_path),
            input_record("baseline-snapshot", baseline_path),
            input_record("current-snapshot", current_path),
            *(input_record("published-snapshot", path) for path in published_paths),
        ]
        report = evaluate(catalog, baseline, current, published, args.install, inputs)
        atomic_json(args.report.resolve(), report)
        if not report["passed"]:
            codes = sorted({item["code"] for item in report["violations"]})
            print(
                "SDK_DEPRECATION_POLICY_ERROR: "
                f"violations={len(report['violations'])} codes={','.join(codes)}",
                file=sys.stderr,
            )
            return 1
        print(
            "SDK_DEPRECATION_POLICY_PASS "
            f"entries={report['entryCount']} markers={report['markerCount']} "
            f"breaking={len(report['breakingSurfaces'])}"
        )
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"SDK_DEPRECATION_POLICY_ERROR: {error}", file=sys.stderr)
        return 2


def register_command(args: argparse.Namespace) -> int:
    try:
        catalog_path = args.catalog.resolve()
        snapshot = load_snapshot(args.snapshot.resolve(), "registration snapshot")
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        entries = validate_catalog(catalog)
        candidate = {
            "id": args.id,
            "kind": args.kind,
            "surface": args.surface,
            "symbol": args.symbol,
            "state": "active",
            "deprecatedSince": snapshot["runtimeVersion"],
            "removalAllowedFrom": args.removal_allowed_from,
            "replacement": args.replacement,
            "owner": args.owner,
            "noticeSurfaceSha256": snapshot["surfaceSha256"],
        }
        validate_catalog({"schemaVersion": 1, "entries": [*entries, candidate]})
        if surface_value(snapshot, args.kind, args.surface) is None:
            raise ValueError("deprecated surface is absent from the registration snapshot")
        if args.kind == "header":
            markers = scan_markers(args.install.resolve(), snapshot)
            if markers.get(args.id) != [args.surface]:
                raise ValueError(
                    "deprecated header must contain its unique PDR-DEP marker before registration"
                )
        updated = {"schemaVersion": 1, "entries": sorted(
            [*entries, candidate], key=lambda item: item["id"]
        )}
        atomic_json(catalog_path, updated)
        print(
            "SDK_DEPRECATION_REGISTER_PASS "
            f"id={args.id} surface={args.surface} notice={snapshot['surfaceSha256']}"
        )
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"SDK_DEPRECATION_REGISTER_ERROR: {error}", file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--catalog", type=Path, required=True)
    validate.add_argument("--baseline", type=Path, required=True)
    validate.add_argument("--current", type=Path, required=True)
    validate.add_argument("--published-snapshot", type=Path, action="append", default=[])
    validate.add_argument("--install", type=Path, required=True)
    validate.add_argument("--report", type=Path, required=True)
    validate.set_defaults(handler=validate_command)
    register = commands.add_parser("register")
    register.add_argument("--catalog", type=Path, required=True)
    register.add_argument("--snapshot", type=Path, required=True)
    register.add_argument("--install", type=Path, required=True)
    register.add_argument("--id", required=True)
    register.add_argument("--kind", choices=sorted(KINDS), required=True)
    register.add_argument("--surface", required=True)
    register.add_argument("--symbol", required=True)
    register.add_argument("--removal-allowed-from", required=True)
    register.add_argument("--replacement", required=True)
    register.add_argument("--owner", required=True)
    register.set_defaults(handler=register_command)
    return result


if __name__ == "__main__":
    arguments = parser().parse_args()
    raise SystemExit(arguments.handler(arguments))
