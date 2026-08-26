#!/usr/bin/env python3
"""Verify independently buildable component groups against configured CMake targets."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from framework_change_impact import atomic_json, load_catalog
from framework_link_dependency_boundary import (
    BUILD_TARGET_TYPES,
    load_manifest,
    target_classification,
)


PROFILE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def load_group_manifest(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if (
        set(document) != {"schemaVersion", "operation", "profile", "groups"}
        or document.get("schemaVersion") != 1
        or document.get("operation") != "framework-component-build-groups"
        or not isinstance(document.get("profile"), str)
        or not PROFILE.fullmatch(document["profile"])
        or not isinstance(document.get("groups"), list)
        or not document["groups"]
    ):
        raise ValueError("component build-group manifest is malformed")

    components: set[str] = set()
    targets: set[str] = set()
    previous_target = ""
    for group in document["groups"]:
        if (
            not isinstance(group, dict)
            or set(group) != {"component", "target", "members"}
            or not isinstance(group.get("component"), str)
            or not re.fullmatch(r"^[a-z0-9][a-z0-9-]*$", group["component"])
            or not isinstance(group.get("target"), str)
            or not group["target"]
            or not isinstance(group.get("members"), list)
            or not group["members"]
            or any(not isinstance(member, str) or not member for member in group["members"])
            or group["members"] != sorted(set(group["members"]))
            or group["component"] in components
            or group["target"] in targets
            or (previous_target and group["target"] <= previous_target)
        ):
            raise ValueError("component build-group manifest contains an invalid group")
        components.add(group["component"])
        targets.add(group["target"])
        previous_target = group["target"]
    return document


def service_components(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        component["id"]: component
        for component in catalog["components"]
        if component["paths"]
        and all(path.startswith("services/") for path in component["paths"])
    }


def analyze(
    root: Path,
    catalog: dict[str, Any],
    groups: dict[str, Any],
    links: dict[str, Any],
) -> dict[str, Any]:
    root = root.resolve()
    target_by_name = {target["name"]: target for target in links["targets"]}
    classifications = {
        name: target_classification(root, catalog, target)
        for name, target in target_by_name.items()
    }
    components = service_components(catalog)
    group_by_component = {group["component"]: group for group in groups["groups"]}
    violations: list[str] = []
    records: list[dict[str, Any]] = []

    if groups["profile"] != links["profile"]:
        violations.append(
            f"profile mismatch: groups={groups['profile']} links={links['profile']}"
        )
    missing_groups = sorted(set(components) - set(group_by_component))
    extra_groups = sorted(set(group_by_component) - set(components))
    violations.extend(f"missing group for component {item}" for item in missing_groups)
    violations.extend(f"group references non-service component {item}" for item in extra_groups)

    for component_id, component in sorted(components.items()):
        group = group_by_component.get(component_id)
        if group is None:
            continue
        group_target = target_by_name.get(group["target"])
        if component["buildTargets"] != [group["target"]]:
            violations.append(
                f"component {component_id} must expose only group target {group['target']}"
            )
        if group_target is None or group_target["type"] != "UTILITY":
            violations.append(
                f"group target {group['target']} is missing or is not a CMake UTILITY target"
            )

        expected = sorted(
            name
            for name, classification in classifications.items()
            if classification["owners"] == [component_id]
            and not classification["excluded"]
        )
        actual = group["members"]
        missing = sorted(set(expected) - set(actual))
        unexpected = sorted(set(actual) - set(expected))
        violations.extend(
            f"group {group['target']} misses production target {name}" for name in missing
        )
        violations.extend(
            f"group {group['target']} contains foreign or non-production target {name}"
            for name in unexpected
        )
        for member in actual:
            target = target_by_name.get(member)
            if target is None:
                violations.append(f"group {group['target']} references unknown target {member}")
            elif target["type"] not in BUILD_TARGET_TYPES:
                violations.append(
                    f"group {group['target']} member {member} is not buildable"
                )
        records.append(
            {
                "component": component_id,
                "owner": component["owner"],
                "target": group["target"],
                "members": actual,
                "productionTargets": expected,
                "passed": not missing and not unexpected and group_target is not None
                and group_target["type"] == "UTILITY"
                and component["buildTargets"] == [group["target"]],
            }
        )

    violations = sorted(set(violations))
    return {
        "schemaVersion": 1,
        "operation": "framework-component-build-groups-validation",
        "profile": groups["profile"],
        "passed": not violations,
        "componentCount": len(components),
        "groupCount": len(groups["groups"]),
        "memberTargetCount": sum(len(group["members"]) for group in groups["groups"]),
        "groups": records,
        "violations": violations,
    }


def validate_command(args: argparse.Namespace) -> int:
    try:
        root = args.root.resolve()
        catalog = load_catalog(args.catalog.resolve())
        groups = load_group_manifest(args.groups.resolve())
        links = load_manifest(args.links.resolve(), root)
        report = analyze(root, catalog, groups, links)
        if args.report:
            atomic_json(args.report.resolve(), report)
        if not report["passed"]:
            raise ValueError("; ".join(report["violations"]))
        print(
            "FRAMEWORK_COMPONENT_BUILD_GROUPS_PASS "
            f"profile={report['profile']} components={report['componentCount']} "
            f"groups={report['groupCount']} members={report['memberTargetCount']}"
        )
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"FRAMEWORK_COMPONENT_BUILD_GROUPS_ERROR: {error}", file=os.sys.stderr)
        return 1


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--root", type=Path, required=True)
    result.add_argument("--catalog", type=Path, required=True)
    result.add_argument("--groups", type=Path, required=True)
    result.add_argument("--links", type=Path, required=True)
    result.add_argument("--report", type=Path)
    result.set_defaults(handler=validate_command)
    return result


if __name__ == "__main__":
    arguments = parser().parse_args()
    raise SystemExit(arguments.handler(arguments))
