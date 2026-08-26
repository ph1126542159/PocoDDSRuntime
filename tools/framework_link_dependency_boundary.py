#!/usr/bin/env python3
"""Enforce declared component boundaries on configured CMake target links."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from framework_change_impact import atomic_json, load_catalog, matches


BUILD_TARGET_TYPES = {
    "EXECUTABLE",
    "INTERFACE_LIBRARY",
    "MODULE_LIBRARY",
    "OBJECT_LIBRARY",
    "SHARED_LIBRARY",
    "STATIC_LIBRARY",
}
PROFILE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
NON_PRODUCTION_SEGMENTS = {
    "benchmark", "benchmarks", "example", "examples", "sample", "samples",
    "test", "tests", "testsuite", "tool", "tools",
}


def relative_to(root: Path, value: str, base: Path | None = None) -> str | None:
    if not value or "$<" in value:
        return None
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = (base or root) / candidate
    try:
        return candidate.resolve().relative_to(root).as_posix()
    except ValueError:
        return None


def component_owners(catalog: dict[str, Any], path: str) -> set[str]:
    return {
        component["id"]
        for component in catalog["components"]
        if any(matches(rule, path) for rule in component["paths"])
    }


def global_path(catalog: dict[str, Any], path: str) -> bool:
    return any(matches(rule, path) for rule in catalog["globalPaths"])


def components_exposed_by_directory(
        catalog: dict[str, Any], path: str) -> set[str]:
    normalized = path.rstrip("/")
    if normalized == ".":
        normalized = ""
    result = set()
    for component in catalog["components"]:
        for rule in component["paths"]:
            base = rule.rstrip("/")
            if (not normalized or matches(rule, normalized) or
                    base.startswith(normalized + "/")):
                result.add(component["id"])
                break
    return result


def public_include_directory(path: str) -> bool:
    return "include" in {part.lower() for part in Path(path).parts}


def non_production(path: str) -> bool:
    return any(part.lower() in NON_PRODUCTION_SEGMENTS for part in Path(path).parts)


def load_manifest(path: Path, root: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if (document.get("schemaVersion") != 1 or
            document.get("operation") != "cmake-target-link-manifest" or
            not isinstance(document.get("profile"), str) or
            not PROFILE.fullmatch(document["profile"]) or
            not isinstance(document.get("sourceRoot"), str) or
            not isinstance(document.get("buildRoot"), str) or
            not isinstance(document.get("targets"), list)):
        raise ValueError("CMake target link manifest is malformed")
    if Path(document["sourceRoot"]).resolve() != root:
        raise ValueError("CMake target link manifest belongs to a different source root")

    names: set[str] = set()
    for target in document["targets"]:
        if (not isinstance(target, dict) or
                not isinstance(target.get("name"), str) or not target["name"] or
                not isinstance(target.get("type"), str) or
                not isinstance(target.get("sourceDirectory"), str) or
                not isinstance(target.get("sources"), list) or
                not all(isinstance(item, str) for item in target["sources"]) or
                not isinstance(target.get("dependencies"), list) or
                not all(isinstance(item, str) for item in target["dependencies"]) or
                not isinstance(target.get("unresolvedLinkItems"), list) or
                not all(isinstance(item, str) for item in target["unresolvedLinkItems"]) or
                not isinstance(target.get("includeDirectories"), list) or
                not all(isinstance(item, str) for item in target["includeDirectories"]) or
                not isinstance(target.get("unresolvedIncludeItems"), list) or
                not all(isinstance(item, str) for item in target["unresolvedIncludeItems"])):
            raise ValueError("CMake target link manifest contains a malformed target")
        if target["name"] in names:
            raise ValueError(f"duplicate CMake target in link manifest: {target['name']}")
        names.add(target["name"])
    for target in document["targets"]:
        for dependency in target["dependencies"]:
            if dependency not in names:
                raise ValueError(
                    f"CMake target {target['name']} references unknown target {dependency}"
                )
    return document


def target_classification(
        root: Path, catalog: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    source_directory = Path(target["sourceDirectory"])
    directory_path = relative_to(root, str(source_directory))
    owned_paths: list[dict[str, Any]] = []
    paths: list[str] = []
    if directory_path is not None:
        paths.append(directory_path)

    for source in target["sources"]:
        source_path = relative_to(root, source, source_directory)
        if source_path is not None:
            paths.append(source_path)

    owners: set[str] = {
        component["id"]
        for component in catalog["components"]
        if target["name"] in component["buildTargets"]
    }
    for path in sorted(set(paths)):
        path_owners = component_owners(catalog, path)
        owners.update(path_owners)
        if path_owners:
            owned_paths.append({"path": path, "owners": sorted(path_owners)})

    source_paths = paths[1:] if directory_path is not None else paths
    excluded = (
        target["type"] not in BUILD_TARGET_TYPES or
        any(non_production(path) for path in source_paths)
    )
    relevant_unowned_paths = [
        path for path in paths
        if not component_owners(catalog, path) and
        not global_path(catalog, path) and
        not non_production(path) and
        not path.startswith("build/")
    ]
    return {
        "target": target["name"],
        "type": target["type"],
        "sourceDirectory": directory_path or target["sourceDirectory"],
        "owners": sorted(owners),
        "ownedPaths": owned_paths,
        "unownedPaths": sorted(set(relevant_unowned_paths)),
        "excluded": excluded,
    }


def analyze(
        root: Path, catalog: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    root = root.resolve()
    components = {item["id"]: item for item in catalog["components"]}
    targets = {item["name"]: item for item in manifest["targets"]}
    classifications = {
        name: target_classification(root, catalog, target)
        for name, target in targets.items()
    }

    unclassified_targets = []
    ambiguous_targets = []
    unresolved_link_items = []
    unresolved_include_items = []
    analyzed: dict[str, str] = {}
    for name, classification in sorted(classifications.items()):
        if classification["excluded"]:
            continue
        if not classification["owners"]:
            if classification["unownedPaths"]:
                unclassified_targets.append(classification)
            continue
        if len(classification["owners"]) != 1:
            ambiguous_targets.append(classification)
            continue
        analyzed[name] = classification["owners"][0]
        if targets[name]["unresolvedLinkItems"]:
            unresolved_link_items.append({
                "target": name,
                "component": analyzed[name],
                "items": sorted(targets[name]["unresolvedLinkItems"]),
            })
        if targets[name]["unresolvedIncludeItems"]:
            unresolved_include_items.append({
                "target": name,
                "component": analyzed[name],
                "items": sorted(targets[name]["unresolvedIncludeItems"]),
            })

    resolved_include_directories = 0
    private_include_violations = []
    for target_name, consumer_component in sorted(analyzed.items()):
        source_directory = Path(targets[target_name]["sourceDirectory"])
        for include_item in sorted(set(targets[target_name]["includeDirectories"])):
            include_path = relative_to(root, include_item, source_directory)
            if include_path is None or include_path.startswith("build/"):
                continue
            exposed = components_exposed_by_directory(catalog, include_path)
            if not exposed:
                continue
            resolved_include_directories += 1
            if public_include_directory(include_path):
                continue
            for provider_component in sorted(exposed - {consumer_component}):
                private_include_violations.append({
                    "consumer": consumer_component,
                    "provider": provider_component,
                    "consumerTarget": target_name,
                    "includeDirectory": include_path,
                })

    edges: dict[tuple[str, str], list[dict[str, str]]] = {}
    resolved_target_links = 0
    for consumer_target, consumer_component in sorted(analyzed.items()):
        for provider_target in sorted(set(targets[consumer_target]["dependencies"])):
            provider = classifications[provider_target]
            if provider["type"] not in BUILD_TARGET_TYPES:
                continue
            provider_owners = provider["owners"]
            if len(provider_owners) != 1:
                continue
            resolved_target_links += 1
            provider_component = provider_owners[0]
            if provider_component == consumer_component:
                continue
            evidence = {
                "consumerTarget": consumer_target,
                "providerTarget": provider_target,
                "consumerSourceDirectory": classifications[consumer_target]["sourceDirectory"],
                "providerSourceDirectory": provider["sourceDirectory"],
            }
            edge_evidence = edges.setdefault(
                (consumer_component, provider_component), []
            )
            if len(edge_evidence) < 20:
                edge_evidence.append(evidence)

    observed_edges = []
    violations = []
    for (consumer, provider), evidence in sorted(edges.items()):
        declared = provider in components[consumer]["requires"]
        record = {
            "consumer": consumer,
            "provider": provider,
            "declared": declared,
            "evidence": evidence,
        }
        observed_edges.append(record)
        if not declared:
            violations.append(record)

    passed = not (
        unclassified_targets or ambiguous_targets or unresolved_link_items or
        unresolved_include_items or private_include_violations or violations
    )
    return {
        "schemaVersion": 1,
        "operation": "framework-link-dependency-boundary",
        "profile": manifest["profile"],
        "passed": passed,
        "componentCount": len(components),
        "manifestTargetCount": len(targets),
        "analyzedProductionTargets": len(analyzed),
        "resolvedProjectTargetLinks": resolved_target_links,
        "resolvedProjectIncludeDirectories": resolved_include_directories,
        "declaredDependencies": {
            component_id: sorted(component["requires"])
            for component_id, component in sorted(components.items())
        },
        "observedEdges": observed_edges,
        "unclassifiedTargets": unclassified_targets,
        "ambiguousTargets": ambiguous_targets,
        "unresolvedLinkItems": unresolved_link_items,
        "unresolvedIncludeItems": unresolved_include_items,
        "privateIncludeDirectoryViolations": private_include_violations,
        "violations": violations,
    }


def validate_command(args: argparse.Namespace) -> int:
    try:
        root = args.root.resolve()
        if not root.is_dir():
            raise ValueError(f"framework root is unavailable: {root}")
        catalog = load_catalog(args.catalog.resolve())
        manifest = load_manifest(args.manifest.resolve(), root)
        if args.expect_profile and not PROFILE.fullmatch(args.expect_profile):
            raise ValueError(f"expected Profile is malformed: {args.expect_profile}")
        if args.expect_profile and manifest["profile"] != args.expect_profile:
            raise ValueError(
                f"CMake target link manifest profile is {manifest['profile']}, "
                f"expected {args.expect_profile}"
            )
        report = analyze(root, catalog, manifest)
        if args.report:
            atomic_json(args.report.resolve(), report)
        if not report["passed"]:
            reasons = []
            for key, label in (
                    ("unclassifiedTargets", "unclassified-targets"),
                    ("ambiguousTargets", "ambiguous-targets"),
                    ("unresolvedLinkItems", "unresolved-link-items"),
                    ("unresolvedIncludeItems", "unresolved-include-items"),
                    ("privateIncludeDirectoryViolations", "private-include-directories"),
                    ("violations", "undeclared-edges")):
                if report[key]:
                    reasons.append(f"{label}={len(report[key])}")
            print("FRAMEWORK_LINK_DEPENDENCY_BOUNDARY_ERROR: " + " ".join(reasons),
                  file=os.sys.stderr)
            return 1
        print(
            "FRAMEWORK_LINK_DEPENDENCY_BOUNDARY_PASS "
            f"profile={report['profile']} "
            f"components={report['componentCount']} "
            f"targets={report['analyzedProductionTargets']} "
            f"links={report['resolvedProjectTargetLinks']} "
            f"includeDirs={report['resolvedProjectIncludeDirectories']} "
            f"edges={len(report['observedEdges'])}"
        )
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"FRAMEWORK_LINK_DEPENDENCY_BOUNDARY_ERROR: {error}", file=os.sys.stderr)
        return 1


def load_boundary_report(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    required_counts = (
        "componentCount", "manifestTargetCount", "analyzedProductionTargets",
        "resolvedProjectTargetLinks",
        "resolvedProjectIncludeDirectories",
    )
    required_lists = (
        "observedEdges", "unclassifiedTargets", "ambiguousTargets",
        "unresolvedLinkItems", "violations",
        "unresolvedIncludeItems", "privateIncludeDirectoryViolations",
    )
    if (document.get("schemaVersion") != 1 or
            document.get("operation") != "framework-link-dependency-boundary" or
            not isinstance(document.get("profile"), str) or
            not PROFILE.fullmatch(document["profile"]) or
            not isinstance(document.get("passed"), bool) or
            any(not isinstance(document.get(field), int) or document[field] < 0
                for field in required_counts) or
            any(not isinstance(document.get(field), list) for field in required_lists)):
        raise ValueError(f"framework link dependency report is malformed: {path}")
    expected_passed = not any(document[field] for field in (
        "unclassifiedTargets", "ambiguousTargets", "unresolvedLinkItems",
        "unresolvedIncludeItems", "privateIncludeDirectoryViolations", "violations"
    ))
    if document["passed"] != expected_passed:
        raise ValueError(f"framework link dependency report is inconsistent: {path}")
    return document


def matrix_command(args: argparse.Namespace) -> int:
    try:
        required = sorted(set(args.required_profile))
        if (not required or len(required) != len(args.required_profile) or
                any(not PROFILE.fullmatch(item) for item in required)):
            raise ValueError("required Profile matrix is empty, duplicated or malformed")
        if not args.profile_report:
            raise ValueError("at least one Profile boundary report is required")

        by_profile: dict[str, dict[str, Any]] = {}
        duplicates: set[str] = set()
        for path in args.profile_report:
            document = load_boundary_report(path.resolve())
            profile = document["profile"]
            if profile in by_profile:
                duplicates.add(profile)
                continue
            by_profile[profile] = document

        present = set(by_profile)
        required_set = set(required)
        missing = sorted(required_set - present)
        unexpected = sorted(present - required_set)
        summaries = []
        for profile, document in sorted(by_profile.items()):
            summaries.append({
                "profile": profile,
                "passed": document["passed"],
                "componentCount": document["componentCount"],
                "manifestTargetCount": document["manifestTargetCount"],
                "analyzedProductionTargets": document["analyzedProductionTargets"],
                "resolvedProjectTargetLinks": document["resolvedProjectTargetLinks"],
                "resolvedProjectIncludeDirectories": document["resolvedProjectIncludeDirectories"],
                "observedEdges": len(document["observedEdges"]),
                "unclassifiedTargets": len(document["unclassifiedTargets"]),
                "ambiguousTargets": len(document["ambiguousTargets"]),
                "unresolvedLinkItems": len(document["unresolvedLinkItems"]),
                "unresolvedIncludeItems": len(document["unresolvedIncludeItems"]),
                "privateIncludeDirectoryViolations": len(document["privateIncludeDirectoryViolations"]),
                "violations": len(document["violations"]),
            })
        passed = (
            not missing and not unexpected and not duplicates and
            all(item["passed"] for item in summaries)
        )
        report = {
            "schemaVersion": 1,
            "operation": "framework-link-dependency-matrix",
            "passed": passed,
            "requiredProfiles": required,
            "profiles": summaries,
            "missingProfiles": missing,
            "unexpectedProfiles": unexpected,
            "duplicateProfiles": sorted(duplicates),
        }
        atomic_json(args.output.resolve(), report)
        if not passed:
            failed = [item["profile"] for item in summaries if not item["passed"]]
            print(
                "FRAMEWORK_LINK_DEPENDENCY_MATRIX_ERROR: "
                f"missing={','.join(missing) or '-'} "
                f"unexpected={','.join(unexpected) or '-'} "
                f"duplicates={','.join(sorted(duplicates)) or '-'} "
                f"failed={','.join(failed) or '-'}",
                file=os.sys.stderr,
            )
            return 1
        print(
            "FRAMEWORK_LINK_DEPENDENCY_MATRIX_PASS "
            f"profiles={len(summaries)} "
            f"targets={sum(item['analyzedProductionTargets'] for item in summaries)} "
            f"links={sum(item['resolvedProjectTargetLinks'] for item in summaries)}"
        )
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"FRAMEWORK_LINK_DEPENDENCY_MATRIX_ERROR: {error}", file=os.sys.stderr)
        return 1


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--root", type=Path, required=True)
    validate.add_argument("--catalog", type=Path, required=True)
    validate.add_argument("--manifest", type=Path, required=True)
    validate.add_argument("--expect-profile")
    validate.add_argument("--report", type=Path)
    validate.set_defaults(handler=validate_command)
    matrix = commands.add_parser("matrix")
    matrix.add_argument("--required-profile", action="append", required=True)
    matrix.add_argument("--profile-report", type=Path, action="append", required=True)
    matrix.add_argument("--output", type=Path, required=True)
    matrix.set_defaults(handler=matrix_command)
    return result


if __name__ == "__main__":
    arguments = parser().parse_args()
    raise SystemExit(arguments.handler(arguments))
