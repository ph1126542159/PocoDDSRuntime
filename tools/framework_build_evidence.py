#!/usr/bin/env python3
"""Execute framework builds and emit replay-resistant, input-bound evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from framework_change_impact import (
    atomic_json,
    document_digest,
    validate_report,
)


SHA256 = re.compile(r"^[0-9a-f]{64}$")
REVISION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{6,127}$")
CONFIGURATION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,63}$")
INPUTS = (
    ("cmake-cache", "cache"),
    ("target-graph", "links"),
    ("component-build-groups", "groups"),
    ("dependency-inventory", "dependencies"),
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(identifier: str, path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"required build input is unavailable or not a regular file: {path}")
    return {
        "id": identifier,
        "size": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def build_inputs(args: argparse.Namespace) -> list[dict[str, Any]]:
    paths = {
        "cache": args.build_dir.resolve() / "CMakeCache.txt",
        "links": args.links.resolve(),
        "groups": args.groups.resolve(),
        "dependencies": args.dependencies.resolve(),
    }
    return [file_record(identifier, paths[field]) for identifier, field in INPUTS]


def source_inputs(root: Path, report: dict[str, Any]) -> list[dict[str, Any]]:
    root = root.resolve()
    result = []
    for relative in report["changedPaths"]:
        unresolved = root / relative
        if unresolved.is_symlink():
            raise ValueError(f"changed path must not be a symbolic link: {relative}")
        candidate = unresolved.resolve()
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise ValueError(f"changed path escapes framework root: {relative}") from error
        if candidate.is_symlink() or candidate.is_dir():
            raise ValueError(f"changed path is not a regular file or deletion: {relative}")
        if candidate.is_file():
            result.append({
                "path": relative,
                "state": "file",
                "size": candidate.stat().st_size,
                "sha256": file_sha256(candidate),
            })
        elif candidate.exists():
            raise ValueError(f"changed path has an unsupported file type: {relative}")
        else:
            payload = f"absent\0{relative}".encode("utf-8")
            result.append({
                "path": relative,
                "state": "absent",
                "size": 0,
                "sha256": hashlib.sha256(payload).hexdigest(),
            })
    return result


def manifest_profile(root: Path, build_dir: Path, links: Path, groups: Path) -> str:
    root = root.resolve()
    build_dir = build_dir.resolve()
    links = links.resolve()
    groups = groups.resolve()
    try:
        links.relative_to(build_dir)
        groups.relative_to(build_dir)
    except ValueError as error:
        raise ValueError("configured target manifests must belong to the build tree") from error
    link_document = json.loads(links.read_text(encoding="utf-8"))
    group_document = json.loads(groups.read_text(encoding="utf-8"))
    link_profile = link_document.get("profile")
    source_root = link_document.get("sourceRoot")
    manifest_build_root = link_document.get("buildRoot")
    if (
        link_document.get("schemaVersion") != 1
        or link_document.get("operation") != "cmake-target-link-manifest"
        or not isinstance(source_root, str)
        or not source_root
        or Path(source_root).resolve() != root
        or not isinstance(manifest_build_root, str)
        or not manifest_build_root
        or Path(manifest_build_root).resolve() != build_dir
        or group_document.get("schemaVersion") != 1
        or group_document.get("operation") != "framework-component-build-groups"
        or not isinstance(link_profile, str)
        or not link_profile
        or group_document.get("profile") != link_profile
    ):
        raise ValueError("CMake target and component-group manifest identity is invalid")
    return link_profile


def selection(report: dict[str, Any], force_full_build: bool) -> str:
    if force_full_build or report["fullSuite"]:
        return "full-build"
    if report["docsOnly"]:
        return "docs-only"
    if not report["buildTargets"]:
        raise ValueError("affected build plan has no build target")
    return "affected-targets"


def abstract_command(
    selected: str, configuration: str, parallelism: int, targets: list[str]
) -> list[str]:
    if selected == "docs-only":
        return []
    command = [
        "cmake", "--build", "<build-tree>", "--config", configuration,
        "--parallel", str(parallelism),
    ]
    if selected == "affected-targets":
        command.extend(["--target", *targets])
    return command


def cache_key(
    profile: str,
    configuration: str,
    selected: str,
    report_sha256: str,
    source_sha256: str,
    build_sha256: str,
    source_revision: str,
    cmake_version: str,
) -> str:
    revision_sha = hashlib.sha256(source_revision.encode("utf-8")).hexdigest()
    cmake_sha = hashlib.sha256(cmake_version.encode("utf-8")).hexdigest()
    return (
        f"pdr-{profile}-{configuration.lower()}-{selected}-"
        f"{revision_sha[:12]}-{cmake_sha[:12]}-{source_sha256[:12]}-{build_sha256[:12]}-"
        f"{report_sha256[:12]}"
    )


def without_self_digest(evidence: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in evidence.items() if key != "evidenceSha256"}


def validate_evidence_shape(evidence: dict[str, Any]) -> None:
    required = {
        "schemaVersion", "operation", "reportSha256", "profile",
        "sourceRevision", "sourceInputs", "sourceInputSetSha256",
        "buildInputs", "buildInputSetSha256", "selection", "configuration",
        "parallelism", "requestedTargets", "executedTargets", "command",
        "commandSha256", "cmakeVersion", "cacheKey", "passed", "evidenceSha256",
    }
    if (
        set(evidence) != required
        or evidence.get("schemaVersion") != 1
        or evidence.get("operation") != "framework-build-execution-evidence"
        or evidence.get("selection") not in {
            "affected-targets", "full-build", "docs-only"
        }
        or not isinstance(evidence.get("profile"), str)
        or not evidence["profile"]
        or not isinstance(evidence.get("sourceRevision"), str)
        or not REVISION.fullmatch(evidence["sourceRevision"])
        or not isinstance(evidence.get("configuration"), str)
        or not CONFIGURATION.fullmatch(evidence["configuration"])
        or not isinstance(evidence.get("parallelism"), int)
        or isinstance(evidence.get("parallelism"), bool)
        or not 1 <= evidence["parallelism"] <= 256
        or any(not isinstance(evidence.get(field), list) for field in (
            "sourceInputs", "buildInputs", "requestedTargets", "executedTargets", "command"
        ))
        or any(not isinstance(item, str) or not item for field in (
            "requestedTargets", "executedTargets", "command"
        ) for item in evidence[field])
        or evidence["requestedTargets"] != sorted(set(evidence["requestedTargets"]))
        or evidence["executedTargets"] != sorted(set(evidence["executedTargets"]))
        or evidence.get("passed") is not True
        or not isinstance(evidence.get("cmakeVersion"), str)
        or not evidence["cmakeVersion"].startswith("cmake version ")
        or not isinstance(evidence.get("cacheKey"), str)
        or not evidence["cacheKey"].startswith("pdr-")
        or any(not isinstance(evidence.get(field), str) or not SHA256.fullmatch(evidence[field])
               for field in (
                   "reportSha256", "sourceInputSetSha256", "buildInputSetSha256",
                   "commandSha256", "evidenceSha256"
               ))
    ):
        raise ValueError("framework build evidence is malformed")


def cmake_version(cmake: Path) -> str:
    version = subprocess.run(
        [str(cmake.resolve()), "--version"], capture_output=True,
        text=True, check=False,
    )
    lines = (version.stdout or "").splitlines()
    if version.returncode != 0 or not lines or not lines[0].startswith("cmake version "):
        raise ValueError("cannot determine CMake version")
    return lines[0]


def expected_state(args: argparse.Namespace, report: dict[str, Any], selected: str,
                   configuration: str, parallelism: int,
                   current_cmake_version: str) -> dict[str, Any]:
    root = args.root.resolve()
    dependencies = args.dependencies.resolve()
    try:
        dependencies.relative_to(root)
    except ValueError as error:
        raise ValueError("dependency inventory must belong to the framework root") from error
    profile = manifest_profile(
        root, args.build_dir.resolve(), args.links.resolve(), args.groups.resolve()
    )
    sources = source_inputs(args.root.resolve(), report)
    inputs = build_inputs(args)
    source_sha = document_digest({"inputs": sources})
    build_sha = document_digest({"inputs": inputs})
    report_sha = document_digest(report)
    requested = sorted(report["buildTargets"])
    executed = (
        requested if selected == "affected-targets"
        else ["<default>"] if selected == "full-build"
        else []
    )
    command = abstract_command(selected, configuration, parallelism, requested)
    command_sha = document_digest({"command": command})
    return {
        "profile": profile,
        "sourceInputs": sources,
        "sourceInputSetSha256": source_sha,
        "buildInputs": inputs,
        "buildInputSetSha256": build_sha,
        "reportSha256": report_sha,
        "requestedTargets": requested,
        "executedTargets": executed,
        "command": command,
        "commandSha256": command_sha,
        "cacheKey": cache_key(
            profile, configuration, selected, report_sha, source_sha, build_sha,
            args.source_revision, current_cmake_version,
        ),
    }


def execute_command(args: argparse.Namespace) -> int:
    try:
        if not REVISION.fullmatch(args.source_revision):
            raise ValueError("source revision is malformed")
        if not CONFIGURATION.fullmatch(args.configuration):
            raise ValueError("build configuration is malformed")
        if not 1 <= args.parallelism <= 256:
            raise ValueError("parallelism must be between 1 and 256")
        report = json.loads(args.report.resolve().read_text(encoding="utf-8"))
        validate_report(report)
        selected = selection(report, args.force_full_build)
        version_line = cmake_version(args.cmake)
        before = expected_state(
            args, report, selected, args.configuration, args.parallelism, version_line
        )

        if selected != "docs-only":
            real_command = [
                str(args.cmake.resolve()), "--build", str(args.build_dir.resolve()),
                "--config", args.configuration, "--parallel", str(args.parallelism),
            ]
            if selected == "affected-targets":
                real_command.extend(["--target", *before["requestedTargets"]])
            build = subprocess.run(real_command, check=False)
            if build.returncode != 0:
                raise ValueError(f"CMake build failed with exit code {build.returncode}")

        after = expected_state(
            args, report, selected, args.configuration, args.parallelism, version_line
        )
        if before != after:
            raise ValueError("framework build inputs changed while the build was running")
        evidence = {
            "schemaVersion": 1,
            "operation": "framework-build-execution-evidence",
            **after,
            "sourceRevision": args.source_revision,
            "selection": selected,
            "configuration": args.configuration,
            "parallelism": args.parallelism,
            "cmakeVersion": version_line,
            "passed": True,
        }
        evidence["evidenceSha256"] = document_digest(evidence)
        atomic_json(args.evidence.resolve(), evidence)
        print(
            "FRAMEWORK_BUILD_EXECUTION_PASS "
            f"selection={selected} targets={len(evidence['executedTargets'])} "
            f"cacheKey={evidence['cacheKey']}"
        )
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"FRAMEWORK_BUILD_EXECUTION_ERROR: {error}", file=os.sys.stderr)
        return 1


def gate_command(args: argparse.Namespace) -> int:
    try:
        if not REVISION.fullmatch(args.source_revision):
            raise ValueError("source revision is malformed")
        report = json.loads(args.report.resolve().read_text(encoding="utf-8"))
        evidence = json.loads(args.evidence.resolve().read_text(encoding="utf-8"))
        validate_report(report)
        validate_evidence_shape(evidence)
        if evidence["evidenceSha256"] != document_digest(without_self_digest(evidence)):
            raise ValueError("framework build evidence self-digest is invalid")
        if evidence["sourceRevision"] != args.source_revision:
            raise ValueError("framework build evidence belongs to another source revision")
        current_cmake_version = cmake_version(args.cmake)
        if evidence["cmakeVersion"] != current_cmake_version:
            raise ValueError("framework build evidence belongs to another CMake version")

        if report["fullSuite"] and evidence["selection"] != "full-build":
            raise ValueError("framework-wide change requires full-build evidence")
        if report["docsOnly"] and evidence["selection"] not in {"docs-only", "full-build"}:
            raise ValueError("docs-only report has an invalid build selection")
        if not report["fullSuite"] and not report["docsOnly"] and evidence["selection"] not in {
            "affected-targets", "full-build"
        }:
            raise ValueError("affected report has an invalid build selection")

        expected = expected_state(
            args, report, evidence["selection"], evidence["configuration"],
            evidence["parallelism"], current_cmake_version,
        )
        for field, value in expected.items():
            if evidence[field] != value:
                raise ValueError(f"framework build evidence has stale or invalid {field}")
        print(
            "FRAMEWORK_BUILD_GATE_PASS "
            f"selection={evidence['selection']} cacheKey={evidence['cacheKey']}"
        )
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"FRAMEWORK_BUILD_GATE_ERROR: {error}", file=os.sys.stderr)
        return 1


def add_common_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--root", type=Path, required=True)
    command.add_argument("--report", type=Path, required=True)
    command.add_argument("--build-dir", type=Path, required=True)
    command.add_argument("--links", type=Path, required=True)
    command.add_argument("--groups", type=Path, required=True)
    command.add_argument("--dependencies", type=Path, required=True)
    command.add_argument("--source-revision", required=True)
    command.add_argument("--cmake", type=Path, required=True)
    command.add_argument("--evidence", type=Path, required=True)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    execute = commands.add_parser("execute")
    add_common_arguments(execute)
    execute.add_argument("--configuration", default="Release")
    execute.add_argument("--parallelism", type=int, default=2)
    execute.add_argument("--force-full-build", action="store_true")
    execute.set_defaults(handler=execute_command)
    gate = commands.add_parser("gate")
    add_common_arguments(gate)
    gate.set_defaults(handler=gate_command)
    return result


if __name__ == "__main__":
    arguments = parser().parse_args()
    raise SystemExit(arguments.handler(arguments))
