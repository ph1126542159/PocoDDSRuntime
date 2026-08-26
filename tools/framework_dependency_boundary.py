#!/usr/bin/env python3
"""Enforce declared source-level dependencies between framework components."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from framework_change_impact import load_catalog


HEADER_EXTENSIONS = {".h", ".hh", ".hpp", ".hxx"}
SOURCE_EXTENSIONS = HEADER_EXTENSIONS | {".c", ".cc", ".cpp", ".cxx"}
NON_PRODUCTION_SEGMENTS = {
    "benchmark", "benchmarks", "example", "examples", "sample", "samples",
    "test", "tests", "testsuite", "tool", "tools",
}
INCLUDE = re.compile(
    r"^\s*#\s*include\s*([<\"])([^>\"]+)[>\"]", re.MULTILINE
)


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


def component_files(root: Path, component: dict[str, Any], extensions: set[str]):
    seen: set[Path] = set()
    for rule in component["paths"]:
        base = root / rule.rstrip("/")
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix.lower() in extensions and path not in seen:
                seen.add(path)
                yield path


def public_include(path: Path) -> str | None:
    parts = path.parts
    include_positions = [index for index, part in enumerate(parts)
                         if part.lower() == "include"]
    if not include_positions:
        return None
    index = include_positions[-1]
    if index + 1 >= len(parts):
        return None
    return Path(*parts[index + 1:]).as_posix()


def production_source(root: Path, path: Path) -> bool:
    relative = path.relative_to(root)
    return not any(part.lower() in NON_PRODUCTION_SEGMENTS for part in relative.parts)


def resolved_repository_header(
        root: Path, source: Path, include: str, quoted: bool,
        headers: dict[Path, dict[str, str | None]]) -> dict[str, str | None] | None:
    include_path = Path(include.replace("\\", "/"))
    if include_path.is_absolute():
        candidates = [include_path]
    else:
        candidates = []
        if quoted:
            candidates.append(source.parent / include_path)
        candidates.append(root / include_path)
    for candidate in candidates:
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        record = headers.get(resolved)
        if record is not None:
            return record
    return None


def analyze(root: Path, catalog: dict[str, Any]) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"framework root is unavailable: {root}")
    owners: dict[str, str] = {}
    owner_evidence: dict[str, str] = {}
    header_paths: dict[Path, dict[str, str | None]] = {}
    ambiguous: list[dict[str, str]] = []
    components = {item["id"]: item for item in catalog["components"]}

    for component in catalog["components"]:
        for path in component_files(root, component, HEADER_EXTENSIONS):
            if not production_source(root, path):
                continue
            include = public_include(path)
            relative = path.relative_to(root).as_posix()
            header_paths[path.resolve()] = {
                "component": component["id"],
                "header": relative,
                "publicInclude": include,
            }
            if include is None:
                continue
            previous = owners.get(include)
            if previous is not None and previous != component["id"]:
                ambiguous.append({
                    "include": include,
                    "firstComponent": previous,
                    "firstHeader": owner_evidence[include],
                    "secondComponent": component["id"],
                    "secondHeader": relative,
                })
                continue
            owners[include] = component["id"]
            owner_evidence[include] = relative

    edges: dict[tuple[str, str], list[dict[str, Any]]] = {}
    scanned_files = 0
    resolved_includes = 0
    private_violations: list[dict[str, Any]] = []
    for component in catalog["components"]:
        consumer = component["id"]
        for path in component_files(root, component, SOURCE_EXTENSIONS):
            if not production_source(root, path):
                continue
            scanned_files += 1
            content = path.read_text(encoding="utf-8", errors="replace")
            for match in INCLUDE.finditer(content):
                include = match.group(2).replace("\\", "/")
                provider = owners.get(include)
                resolved_header = None
                if provider is None:
                    resolved_header = resolved_repository_header(
                        root, path, include, match.group(1) == '"', header_paths
                    )
                    if resolved_header is not None:
                        provider = str(resolved_header["component"])
                if provider is None or provider == consumer:
                    continue
                line = content.count("\n", 0, match.start()) + 1
                evidence = {
                    "source": path.relative_to(root).as_posix(),
                    "line": line,
                    "include": include,
                }
                if (resolved_header is not None and
                        resolved_header["publicInclude"] is None):
                    private_violations.append({
                        "consumer": consumer,
                        "provider": provider,
                        "privateHeader": resolved_header["header"],
                        "evidence": evidence,
                    })
                    continue
                resolved_includes += 1
                edge_evidence = edges.setdefault((consumer, provider), [])
                if len(edge_evidence) < 10:
                    edge_evidence.append(evidence)

    observed = []
    violations = []
    for (consumer, provider), evidence in sorted(edges.items()):
        declared = provider in components[consumer]["requires"]
        record = {
            "consumer": consumer,
            "provider": provider,
            "declared": declared,
            "evidence": evidence,
        }
        observed.append(record)
        if not declared:
            violations.append(record)

    return {
        "schemaVersion": 1,
        "operation": "framework-source-dependency-boundary",
        "passed": not ambiguous and not violations and not private_violations,
        "componentCount": len(components),
        "publicHeaderCount": len(owners),
        "privateHeaderCount": sum(
            1 for record in header_paths.values()
            if record["publicInclude"] is None
        ),
        "scannedProductionFiles": scanned_files,
        "resolvedCrossComponentIncludes": resolved_includes,
        "resolvedCrossComponentPrivateIncludes": len(private_violations),
        "declaredDependencies": {
            component_id: sorted(component["requires"])
            for component_id, component in sorted(components.items())
        },
        "observedEdges": observed,
        "ambiguousPublicHeaders": ambiguous,
        "privateHeaderViolations": private_violations,
        "violations": violations,
    }


def validate_command(args: argparse.Namespace) -> int:
    try:
        report = analyze(args.root, load_catalog(args.catalog.resolve()))
        if args.report:
            atomic_json(args.report.resolve(), report)
        if not report["passed"]:
            reasons = []
            if report["ambiguousPublicHeaders"]:
                reasons.append(f"ambiguous-headers={len(report['ambiguousPublicHeaders'])}")
            if report["violations"]:
                reasons.append(f"undeclared-edges={len(report['violations'])}")
            if report["privateHeaderViolations"]:
                reasons.append(
                    f"private-header-includes={len(report['privateHeaderViolations'])}"
                )
            print("FRAMEWORK_DEPENDENCY_BOUNDARY_ERROR: " + " ".join(reasons),
                  file=os.sys.stderr)
            return 1
        print(
            "FRAMEWORK_DEPENDENCY_BOUNDARY_PASS "
            f"components={report['componentCount']} "
            f"headers={report['publicHeaderCount']} "
            f"privateHeaders={report['privateHeaderCount']} "
            f"files={report['scannedProductionFiles']} "
            f"edges={len(report['observedEdges'])}"
        )
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"FRAMEWORK_DEPENDENCY_BOUNDARY_ERROR: {error}", file=os.sys.stderr)
        return 1


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--root", type=Path, required=True)
    validate.add_argument("--catalog", type=Path, required=True)
    validate.add_argument("--report", type=Path)
    validate.set_defaults(handler=validate_command)
    return result


if __name__ == "__main__":
    arguments = parser().parse_args()
    raise SystemExit(arguments.handler(arguments))
