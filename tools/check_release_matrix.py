#!/usr/bin/env python3
"""Validate the governed release compatibility matrix against source contracts."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def contract_version(path: Path) -> str:
    match = re.search(r"(?m)^\s{2}version:\s*([0-9.]+)", path.read_text(encoding="utf-8"))
    if not match:
        raise ValueError(f"version missing: {path}")
    return match.group(1)


def main() -> int:
    project = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
    runtime = re.search(r"project\(PocoDDSRuntime VERSION ([0-9.]+)", project).group(1)
    matrix = json.loads((ROOT / "docs/compatibility/releases.json").read_text(encoding="utf-8"))
    releases = matrix.get("releases", [])
    errors = []
    versions = [release.get("runtime") for release in releases]
    if len(versions) != len(set(versions)):
        errors.append("duplicate Runtime version")
    current = next((release for release in releases if release.get("runtime") == runtime), None)
    if current is None:
        errors.append(f"current Runtime {runtime} is missing")
    else:
        expected = {
            "configurationSchema": runtime,
            "openapi": contract_version(ROOT / "contracts/openapi/runtime.yaml"),
            "asyncapi": contract_version(ROOT / "contracts/asyncapi/runtime.yaml"),
        }
        for key, value in expected.items():
            if current.get(key) != value:
                errors.append(f"{key} mismatch: matrix={current.get(key)} source={value}")
        for source in current.get("upgradeFrom", []):
            if source not in versions:
                errors.append(f"upgradeFrom references unknown release: {source}")
    for error in errors:
        print(f"RELEASE_MATRIX_ERROR: {error}", file=sys.stderr)
    if errors:
        return 1
    print(f"RELEASE_MATRIX_PASS current={runtime} releases={len(releases)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
