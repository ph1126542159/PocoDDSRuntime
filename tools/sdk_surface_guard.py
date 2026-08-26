#!/usr/bin/env python3
"""Snapshot and enforce PocoDDSRuntime installed SDK API and binary ABI surfaces."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

from framework_change_impact import atomic_json


HEADER_EXTENSIONS = {".h", ".hh", ".hpp", ".hxx"}
SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
CPP_TOKEN = re.compile(
    r"//[^\n]*(?:\n|$)|/\*.*?\*/|"
    r'R"(?P<raw>[^ ()\\\t\r\n]{0,16})\(.*?\)(?P=raw)"|'
    r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|'
    r"[A-Za-z_][A-Za-z0-9_]*|"
    r"0[xX][0-9A-Fa-f']+|0[bB][01']+|[0-9][0-9A-Za-z_.'+-]*|"
    r"<=>|>>=|<<=|->\*|\.\.\.|::|->|\+\+|--|&&|\|\||"
    r"==|!=|<=|>=|<<|>>|\+=|-=|\*=|/=|%=|&=|\|=|\^=|##|"
    r"[^\s]",
    re.DOTALL,
)
TARGET = re.compile(r"(?m)^add_library\((PocoDDS::[^\s)]+)\s+")
WINDOWS_EXPORT = re.compile(
    r"^\s*\d+\s+[0-9A-Fa-f]+\s+[0-9A-Fa-f]+\s+(\S+)", re.MULTILINE
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
ABI_KEY = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
GOVERNED_DEPRECATION_ATTRIBUTE = re.compile(
    r'\[\[\s*deprecated\s*\(\s*"PDR-DEP-[0-9]{4,}:\s*(?:\\.|[^"\\])+"\s*\)\s*\]\]',
    re.DOTALL,
)


def semver(value: str) -> tuple[int, int, int]:
    match = SEMVER.fullmatch(value)
    if not match:
        raise ValueError(f"invalid semantic version: {value}")
    return tuple(int(item) for item in match.groups())  # type: ignore[return-value]


def cpp_tokens(text: str) -> list[str]:
    # A registered deprecation warning changes lifecycle metadata, not the
    # callable surface. Ignore only attributes carrying a stable PDR-DEP ID;
    # arbitrary deprecated attributes and all declaration tokens remain gated.
    text = GOVERNED_DEPRECATION_ATTRIBUTE.sub("", text)
    tokens = []
    for match in CPP_TOKEN.finditer(text):
        token = match.group(0)
        if token.startswith("//") or token.startswith("/*"):
            continue
        tokens.append(token)
    return tokens


def digest_strings(values: list[str]) -> str:
    payload = "\n".join(values).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def surface_digest(
        headers: dict[str, dict[str, Any]], targets: list[str]) -> str:
    lines = [
        *(f"H {path} {record['tokenSha256']}" for path, record in headers.items()),
        *(f"T {target}" for target in targets),
    ]
    return digest_strings(lines)


def public_headers(install: Path) -> dict[str, dict[str, Any]]:
    include_root = install / "include" / "PocoDDS"
    if not include_root.is_dir():
        raise ValueError(f"installed PocoDDS public include tree is missing: {include_root}")
    result = {}
    for path in sorted(include_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in HEADER_EXTENSIONS:
            continue
        tokens = cpp_tokens(path.read_text(encoding="utf-8", errors="strict"))
        relative = path.relative_to(install).as_posix()
        result[relative] = {
            "tokenSha256": digest_strings(tokens),
            "tokenCount": len(tokens),
        }
    if not result:
        raise ValueError("installed PocoDDS public include tree contains no headers")
    return result


def exported_cmake_targets(install: Path) -> list[str]:
    cmake_root = install / "lib" / "cmake"
    if not cmake_root.is_dir():
        raise ValueError(f"installed CMake package tree is missing: {cmake_root}")
    targets: set[str] = set()
    for path in cmake_root.rglob("*Targets.cmake"):
        targets.update(TARGET.findall(path.read_text(encoding="utf-8", errors="strict")))
    if not targets:
        raise ValueError("installed SDK exports no PocoDDS CMake library targets")
    return sorted(targets)


def read_windows_exports(tool: Path, artifact: Path) -> list[str]:
    result = subprocess.run(
        [str(tool), "/nologo", "/exports", str(artifact)],
        text=True, encoding="utf-8", errors="replace", capture_output=True, check=False,
    )
    if result.returncode != 0:
        raise ValueError(
            f"symbol tool failed for {artifact.name}: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return sorted(set(WINDOWS_EXPORT.findall(result.stdout)))


def read_posix_exports(tool: Path, artifact: Path) -> list[str]:
    result = subprocess.run(
        [str(tool), "-D", "--defined-only", str(artifact)],
        text=True, encoding="utf-8", errors="replace", capture_output=True, check=False,
    )
    if result.returncode != 0:
        raise ValueError(
            f"symbol tool failed for {artifact.name}: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    symbols = []
    for line in result.stdout.splitlines():
        fields = line.split()
        if fields:
            symbols.append(fields[-1])
    return sorted(set(symbols))


def binary_abi(
        install: Path, abi_key: str, symbol_tool: Path,
        reader: Callable[[Path, Path], list[str]] | None = None) -> dict[str, Any]:
    if not abi_key or not ABI_KEY.fullmatch(abi_key):
        raise ValueError(f"invalid ABI key: {abi_key}")
    if not symbol_tool.is_file():
        raise ValueError(f"symbol tool is unavailable: {symbol_tool}")
    if reader is None:
        reader = read_windows_exports if os.name == "nt" else read_posix_exports
    if os.name == "nt":
        artifacts = sorted((install / "bin").glob("PDR*.dll"))
    else:
        artifacts = sorted((install / "lib").glob("libPDR*.so*"))
    if not artifacts:
        raise ValueError("installed SDK contains no dynamic PDR ABI artifacts")
    records = {}
    for artifact in artifacts:
        symbols = reader(symbol_tool, artifact)
        if not symbols:
            raise ValueError(f"dynamic ABI artifact exports no symbols: {artifact.name}")
        relative = artifact.relative_to(install).as_posix()
        records[relative] = {
            "symbolSha256": digest_strings(symbols),
            "symbolCount": len(symbols),
        }
    return {"key": abi_key, "artifacts": records}


def snapshot(
        install: Path, runtime_version: str, abi_key: str | None = None,
        symbol_tool: Path | None = None,
        reader: Callable[[Path, Path], list[str]] | None = None) -> dict[str, Any]:
    install = install.resolve()
    if not install.is_dir():
        raise ValueError(f"installed SDK tree is unavailable: {install}")
    semver(runtime_version)
    headers = public_headers(install)
    targets = exported_cmake_targets(install)
    abi = None
    if abi_key or symbol_tool:
        if not abi_key or symbol_tool is None:
            raise ValueError("ABI key and symbol tool must be supplied together")
        abi = binary_abi(install, abi_key, symbol_tool.resolve(), reader)
    return {
        "schemaVersion": 1,
        "operation": "sdk-public-surface-snapshot",
        "runtimeVersion": runtime_version,
        "surfaceSha256": surface_digest(headers, targets),
        "publicHeaders": headers,
        "cmakeLibraryTargets": targets,
        "binaryAbi": abi,
    }


def validate_snapshot(document: dict[str, Any], label: str) -> None:
    if (document.get("schemaVersion") != 1 or
            document.get("operation") != "sdk-public-surface-snapshot" or
            not isinstance(document.get("runtimeVersion"), str) or
            not isinstance(document.get("surfaceSha256"), str) or
            not SHA256.fullmatch(document["surfaceSha256"]) or
            not isinstance(document.get("publicHeaders"), dict) or
            not document["publicHeaders"] or
            not isinstance(document.get("cmakeLibraryTargets"), list) or
            not document["cmakeLibraryTargets"] or
            (document.get("binaryAbi") is not None and
             not isinstance(document.get("binaryAbi"), dict))):
        raise ValueError(f"{label} SDK surface snapshot is malformed")
    semver(document["runtimeVersion"])
    headers = document["publicHeaders"]
    for path, record in headers.items():
        if (not isinstance(path, str) or
                not path.startswith("include/PocoDDS/") or
                not isinstance(record, dict) or
                set(record) != {"tokenSha256", "tokenCount"} or
                not isinstance(record["tokenSha256"], str) or
                not SHA256.fullmatch(record["tokenSha256"]) or
                not isinstance(record["tokenCount"], int) or
                isinstance(record["tokenCount"], bool) or
                record["tokenCount"] < 1):
            raise ValueError(f"{label} SDK public header record is malformed: {path}")
    targets = document["cmakeLibraryTargets"]
    if (targets != sorted(set(targets)) or
            any(not isinstance(target, str) or not target.startswith("PocoDDS::")
                for target in targets)):
        raise ValueError(f"{label} SDK CMake target list is malformed")
    expected_surface = surface_digest(headers, targets)
    if document["surfaceSha256"] != expected_surface:
        raise ValueError(f"{label} SDK surface digest is inconsistent")
    abi = document.get("binaryAbi")
    if abi is not None:
        if (set(abi) != {"key", "artifacts"} or
                not isinstance(abi.get("key"), str) or
                not ABI_KEY.fullmatch(abi["key"]) or
                not isinstance(abi.get("artifacts"), dict) or
                not abi["artifacts"]):
            raise ValueError(f"{label} SDK binary ABI record is malformed")
        for path, record in abi["artifacts"].items():
            if (not isinstance(path, str) or not path or
                    not isinstance(record, dict) or
                    set(record) != {"symbolSha256", "symbolCount"} or
                    not isinstance(record["symbolSha256"], str) or
                    not SHA256.fullmatch(record["symbolSha256"]) or
                    not isinstance(record["symbolCount"], int) or
                    isinstance(record["symbolCount"], bool) or
                    record["symbolCount"] < 1):
                raise ValueError(
                    f"{label} SDK binary ABI artifact is malformed: {path}"
                )


def compare(
        baseline: dict[str, Any], current: dict[str, Any], require_abi: bool) -> dict[str, Any]:
    validate_snapshot(baseline, "baseline")
    validate_snapshot(current, "current")
    old_version = semver(baseline["runtimeVersion"])
    new_version = semver(current["runtimeVersion"])
    if new_version < old_version:
        raise ValueError(
            "current Runtime version is older than the SDK compatibility baseline: "
            f"baseline={baseline['runtimeVersion']} current={current['runtimeVersion']}"
        )
    old_headers = baseline["publicHeaders"]
    new_headers = current["publicHeaders"]
    removed_headers = sorted(set(old_headers) - set(new_headers))
    added_headers = sorted(set(new_headers) - set(old_headers))
    changed_headers = sorted(
        path for path in set(old_headers) & set(new_headers)
        if old_headers[path].get("tokenSha256") != new_headers[path].get("tokenSha256")
    )
    old_targets = set(baseline["cmakeLibraryTargets"])
    new_targets = set(current["cmakeLibraryTargets"])
    removed_targets = sorted(old_targets - new_targets)
    added_targets = sorted(new_targets - old_targets)

    abi_checked = False
    abi_key = None
    removed_artifacts: list[str] = []
    added_artifacts: list[str] = []
    changed_artifacts: list[str] = []
    old_abi = baseline.get("binaryAbi")
    new_abi = current.get("binaryAbi")
    if new_abi is not None:
        if old_abi is None:
            raise ValueError("current snapshot has ABI evidence but baseline has none")
        if old_abi.get("key") != new_abi.get("key"):
            raise ValueError(
                f"ABI key mismatch: baseline={old_abi.get('key')} current={new_abi.get('key')}"
            )
        abi_checked = True
        abi_key = new_abi["key"]
        old_artifacts = old_abi.get("artifacts", {})
        new_artifacts = new_abi.get("artifacts", {})
        removed_artifacts = sorted(set(old_artifacts) - set(new_artifacts))
        added_artifacts = sorted(set(new_artifacts) - set(old_artifacts))
        changed_artifacts = sorted(
            path for path in set(old_artifacts) & set(new_artifacts)
            if old_artifacts[path].get("symbolSha256") !=
            new_artifacts[path].get("symbolSha256")
        )
    elif require_abi:
        raise ValueError("binary ABI evidence is required but current snapshot has none")

    breaking = bool(
        removed_headers or changed_headers or removed_targets or
        removed_artifacts or changed_artifacts
    )
    major_approved = new_version[0] > old_version[0]
    passed = not breaking or major_approved
    return {
        "schemaVersion": 1,
        "operation": "sdk-public-surface-compatibility",
        "passed": passed,
        "baselineVersion": baseline["runtimeVersion"],
        "currentVersion": current["runtimeVersion"],
        "baselineSurfaceSha256": baseline["surfaceSha256"],
        "currentSurfaceSha256": current["surfaceSha256"],
        "abiChecked": abi_checked,
        "abiKey": abi_key,
        "majorVersionBreakApproved": major_approved and breaking,
        "removedHeaders": removed_headers,
        "addedHeaders": added_headers,
        "changedHeaders": changed_headers,
        "removedCmakeTargets": removed_targets,
        "addedCmakeTargets": added_targets,
        "removedAbiArtifacts": removed_artifacts,
        "addedAbiArtifacts": added_artifacts,
        "changedAbiArtifacts": changed_artifacts,
    }


def snapshot_command(args: argparse.Namespace) -> int:
    try:
        document = snapshot(
            args.install, args.runtime_version, args.abi_key, args.symbol_tool
        )
        atomic_json(args.output.resolve(), document)
        print(
            "SDK_SURFACE_SNAPSHOT_PASS "
            f"headers={len(document['publicHeaders'])} "
            f"targets={len(document['cmakeLibraryTargets'])} "
            f"abiArtifacts={len((document['binaryAbi'] or {}).get('artifacts', {}))}"
        )
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"SDK_SURFACE_ERROR: {error}", file=os.sys.stderr)
        return 1


def compare_command(args: argparse.Namespace) -> int:
    try:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        current = json.loads(args.current.read_text(encoding="utf-8"))
        report = compare(baseline, current, args.require_abi)
        atomic_json(args.report.resolve(), report)
        if not report["passed"]:
            print(
                "SDK_SURFACE_COMPATIBILITY_ERROR: "
                f"removedHeaders={len(report['removedHeaders'])} "
                f"changedHeaders={len(report['changedHeaders'])} "
                f"removedTargets={len(report['removedCmakeTargets'])} "
                f"removedAbi={len(report['removedAbiArtifacts'])} "
                f"changedAbi={len(report['changedAbiArtifacts'])}",
                file=os.sys.stderr,
            )
            return 1
        print(
            "SDK_SURFACE_COMPATIBILITY_PASS "
            f"baseline={report['baselineVersion']} current={report['currentVersion']} "
            f"abiChecked={str(report['abiChecked']).lower()}"
        )
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"SDK_SURFACE_ERROR: {error}", file=os.sys.stderr)
        return 1


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    create = commands.add_parser("snapshot")
    create.add_argument("--install", type=Path, required=True)
    create.add_argument("--runtime-version", required=True)
    create.add_argument("--abi-key")
    create.add_argument("--symbol-tool", type=Path)
    create.add_argument("--output", type=Path, required=True)
    create.set_defaults(handler=snapshot_command)
    check = commands.add_parser("compare")
    check.add_argument("--baseline", type=Path, required=True)
    check.add_argument("--current", type=Path, required=True)
    check.add_argument("--require-abi", action="store_true")
    check.add_argument("--report", type=Path, required=True)
    check.set_defaults(handler=compare_command)
    return result


if __name__ == "__main__":
    arguments = parser().parse_args()
    raise SystemExit(arguments.handler(arguments))
