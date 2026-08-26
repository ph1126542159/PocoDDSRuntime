#!/usr/bin/env python3
"""Generate and record an installed SDK public-header self-containment build."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from framework_change_impact import atomic_json, document_digest
from sdk_surface_guard import exported_cmake_targets, public_headers, surface_digest


SHA256 = re.compile(r"^[0-9a-f]{64}$")


def validate_plan(plan: dict[str, Any]) -> None:
    if (set(plan) != {"schemaVersion", "operation", "surfaceSha256",
                     "publicHeaders", "cmakeLibraryTargets"} or
            plan.get("schemaVersion") != 1 or
            plan.get("operation") != "sdk-header-self-containment-plan" or
            not isinstance(plan.get("surfaceSha256"), str) or
            not SHA256.fullmatch(plan["surfaceSha256"]) or
            not isinstance(plan.get("publicHeaders"), dict) or
            not plan["publicHeaders"] or
            not isinstance(plan.get("cmakeLibraryTargets"), list) or
            not plan["cmakeLibraryTargets"] or
            plan["cmakeLibraryTargets"] != sorted(set(plan["cmakeLibraryTargets"])) or
            any(not isinstance(target, str) or not target.startswith("PocoDDS::")
                for target in plan["cmakeLibraryTargets"])):
        raise ValueError("SDK header self-containment plan is malformed")
    if list(plan["publicHeaders"]) != sorted(plan["publicHeaders"]):
        raise ValueError("SDK header self-containment header list is not canonical")
    for path, record in plan["publicHeaders"].items():
        if (not isinstance(path, str) or not path.startswith("include/PocoDDS/") or
                not isinstance(record, dict) or
                set(record) != {"tokenSha256", "tokenCount"} or
                not isinstance(record["tokenSha256"], str) or
                not SHA256.fullmatch(record["tokenSha256"]) or
                not isinstance(record["tokenCount"], int) or
                isinstance(record["tokenCount"], bool) or record["tokenCount"] < 1):
            raise ValueError(f"SDK header plan record is malformed: {path}")
    expected = surface_digest(plan["publicHeaders"], plan["cmakeLibraryTargets"])
    if expected != plan["surfaceSha256"]:
        raise ValueError("SDK header self-containment surface digest is inconsistent")


def cmake_project(targets: list[str], sources: list[str]) -> str:
    source_lines = "\n".join(
        f'    "${{CMAKE_CURRENT_SOURCE_DIR}}/{item}"' for item in sources
    )
    target_lines = "\n".join(f"    {target}" for target in targets)
    return f"""cmake_minimum_required(VERSION 3.24)
project(PocoDDSRuntimeHeaderSelfContainment LANGUAGES CXX)

find_package(PocoDDSRuntime CONFIG REQUIRED COMPONENTS SDK)
if(NOT PocoDDSRuntime_KNOWN_COMPONENTS)
    message(FATAL_ERROR "Installed package does not publish PocoDDSRuntime_KNOWN_COMPONENTS")
endif()
find_package(PocoDDSRuntime CONFIG REQUIRED COMPONENTS ${{PocoDDSRuntime_KNOWN_COMPONENTS}})

add_library(pdr-sdk-header-self-containment OBJECT
{source_lines})
target_compile_features(pdr-sdk-header-self-containment PRIVATE cxx_std_17)
target_link_libraries(pdr-sdk-header-self-containment PRIVATE
{target_lines})
"""


def generate(install: Path, output: Path) -> dict[str, Any]:
    install = install.resolve()
    output = output.resolve()
    # pathlib sorts WindowsPath values case-insensitively, while the persisted
    # plan is validated as canonical POSIX path strings.  Normalize the map at
    # this boundary so mixed-case component names (FastDDS/FastDds) remain
    # deterministic on every host.
    headers = dict(sorted(public_headers(install).items()))
    targets = exported_cmake_targets(install)
    if "PocoDDS::SDK" not in targets:
        raise ValueError("installed SDK does not export PocoDDS::SDK")
    output.mkdir(parents=True, exist_ok=True)
    sources_directory = output / "sources"
    sources_directory.mkdir(parents=True, exist_ok=True)
    sources = []
    for index, path in enumerate(headers, start=1):
        include = path.removeprefix("include/")
        stem = re.sub(r"[^A-Za-z0-9]+", "_", Path(include).stem).strip("_")
        relative_source = f"sources/header_{index:04d}_{stem}.cpp"
        (output / relative_source).write_text(
            f"#include <{include}>\n\n"
            f"namespace {{ constexpr int pdr_header_{index:04d} = {index}; }}\n",
            encoding="utf-8", newline="\n",
        )
        sources.append(relative_source)
    (output / "CMakeLists.txt").write_text(
        cmake_project(targets, sources), encoding="utf-8", newline="\n"
    )
    plan = {
        "schemaVersion": 1,
        "operation": "sdk-header-self-containment-plan",
        "surfaceSha256": surface_digest(headers, targets),
        "publicHeaders": headers,
        "cmakeLibraryTargets": targets,
    }
    validate_plan(plan)
    return plan


def generate_command(args: argparse.Namespace) -> int:
    try:
        plan = generate(args.install, args.output)
        atomic_json(args.plan.resolve(), plan)
        print(
            "SDK_HEADER_SELF_CONTAINMENT_GENERATE_PASS "
            f"headers={len(plan['publicHeaders'])} "
            f"targets={len(plan['cmakeLibraryTargets'])}"
        )
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"SDK_HEADER_SELF_CONTAINMENT_ERROR: {error}", file=os.sys.stderr)
        return 1


def complete_command(args: argparse.Namespace) -> int:
    try:
        plan = json.loads(args.plan.resolve().read_text(encoding="utf-8"))
        validate_plan(plan)
        evidence = {
            "schemaVersion": 1,
            "operation": "sdk-header-self-containment-evidence",
            "passed": True,
            "planSha256": document_digest(plan),
            "surfaceSha256": plan["surfaceSha256"],
            "compiledHeaderCount": len(plan["publicHeaders"]),
            "usageTargetCount": len(plan["cmakeLibraryTargets"]),
            "buildConfig": args.config,
        }
        atomic_json(args.evidence.resolve(), evidence)
        print(
            "SDK_HEADER_SELF_CONTAINMENT_PASS "
            f"headers={evidence['compiledHeaderCount']} "
            f"targets={evidence['usageTargetCount']}"
        )
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"SDK_HEADER_SELF_CONTAINMENT_ERROR: {error}", file=os.sys.stderr)
        return 1


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    create = commands.add_parser("generate")
    create.add_argument("--install", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--plan", type=Path, required=True)
    create.set_defaults(handler=generate_command)
    complete = commands.add_parser("complete")
    complete.add_argument("--plan", type=Path, required=True)
    complete.add_argument("--config", required=True)
    complete.add_argument("--evidence", type=Path, required=True)
    complete.set_defaults(handler=complete_command)
    return result


if __name__ == "__main__":
    arguments = parser().parse_args()
    raise SystemExit(arguments.handler(arguments))
