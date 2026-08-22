#!/usr/bin/env python3
"""Fail closed when the portable robotics core crosses implementation boundaries."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


FORBIDDEN_INCLUDES = (
    "Poco/", "fastdds/", "fastrtps/", "rclcpp/", "rclcpp_action/",
    "lifecycle_msgs/", "sensor_msgs/", "geometry_msgs/", "Qt", "QApplication",
)
SCANNED_DIRECTORIES = ("robotics/include", "robotics/src", "robotics/apps", "robotics/tests",
                       "robotics/examples")


def scan(root: Path) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    include_pattern = re.compile(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]')
    for relative_directory in SCANNED_DIRECTORIES:
        directory = root / relative_directory
        if not directory.is_dir():
            findings.append({"file": relative_directory, "line": 0,
                             "reason": "required robotics core directory is missing"})
            continue
        for path in sorted(directory.rglob("*")):
            if path.suffix.lower() not in {".h", ".hpp", ".cpp", ".cc", ".cxx"}:
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                match = include_pattern.match(line)
                if not match:
                    continue
                included = match.group(1)
                boundary = next((prefix for prefix in FORBIDDEN_INCLUDES
                                 if included.startswith(prefix)), None)
                if boundary:
                    findings.append({
                        "file": path.relative_to(root).as_posix(), "line": number,
                        "include": included,
                        "reason": f"portable robotics core must not depend on {boundary}",
                    })
    cmake_path = root / "robotics/CMakeLists.txt"
    if cmake_path.is_file():
        forbidden_cmake = ("find_package(Qt", "find_package(Poco", "find_package(fastdds",
                           "find_package(fastrtps", "find_package(rclcpp")
        for number, line in enumerate(cmake_path.read_text(encoding="utf-8").splitlines(), 1):
            marker = next((item for item in forbidden_cmake if item.lower() in line.lower()), None)
            if marker:
                findings.append({"file": "robotics/CMakeLists.txt", "line": number,
                                 "reason": f"portable robotics CMake contains forbidden dependency: {marker}"})
    else:
        findings.append({"file": "robotics/CMakeLists.txt", "line": 0,
                         "reason": "portable robotics CMake entry is missing"})
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    findings = scan(root)
    report = {"schemaVersion": 1, "operation": "robotics-architecture-boundary",
              "passed": not findings, "root": str(root), "findings": findings}
    if args.report:
        args.report.resolve().parent.mkdir(parents=True, exist_ok=True)
        args.report.resolve().write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for finding in findings:
        print(f"{finding['file']}:{finding['line']}: {finding['reason']}")
    if findings:
        print(f"PDR_ROBOTICS_ARCHITECTURE_FAIL findings={len(findings)}")
        return 1
    print("PDR_ROBOTICS_ARCHITECTURE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
