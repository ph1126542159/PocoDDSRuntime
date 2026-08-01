#!/usr/bin/env python3
"""Ensure the release SBOM dependency inventory matches CMake pins."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PINS = {
    "Poco": ("cmake/PDRPocoBootstrap.cmake", r"poco-([0-9.]+)-release"),
    "Fast-DDS": ("cmake/PDRFastDDSBootstrap.cmake", r"GIT_TAG v(3\.[0-9.]+)"),
    "Fast-CDR": ("cmake/PDRFastDDSBootstrap.cmake", r"GIT_TAG v(2\.[0-9.]+)"),
    "foonathan-memory": ("cmake/PDRFastDDSBootstrap.cmake", r"GIT_TAG v(1\.4\.1)"),
    "Eclipse-Paho-MQTT-C": ("cmake/PDRPahoMqttBootstrap.cmake", r"GIT_TAG v([0-9.]+)"),
    "OpenTelemetry-CPP": ("cmake/PDROpenTelemetryBootstrap.cmake", r"GIT_TAG v([0-9.]+)"),
    "GoogleTest": ("cmake/PDRGoogleTestBootstrap.cmake", r"GIT_TAG v([0-9.]+)"),
}


def main() -> int:
    packages = {
        package["name"]: package
        for package in json.loads((ROOT / "release/dependencies.json").read_text(encoding="utf-8"))["packages"]
    }
    errors = []
    for name, (relative, pattern) in PINS.items():
        match = re.search(pattern, (ROOT / relative).read_text(encoding="utf-8"))
        if not match:
            errors.append(f"cannot determine CMake pin: {name}")
        elif name not in packages:
            errors.append(f"dependency missing from release inventory: {name}")
        elif packages[name]["version"] != match.group(1):
            errors.append(
                f"dependency version mismatch: {name} CMake={match.group(1)} inventory={packages[name]['version']}"
            )
    for error in errors:
        print(f"DEPENDENCY_LOCK_ERROR: {error}", file=sys.stderr)
    if errors:
        return 1
    print(f"DEPENDENCY_LOCK_PASS packages={len(packages)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
