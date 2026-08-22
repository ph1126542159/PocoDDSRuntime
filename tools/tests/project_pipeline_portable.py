#!/usr/bin/env python3
"""Build a generated product against an installed SDK on the current host."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run(command: list[str], cwd: Path | None = None,
        expected: set[int] = {0}) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command, cwd=cwd, check=False, capture_output=True, text=True
    )
    if completed.returncode not in expected:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {command}\n"
            + completed.stdout + completed.stderr
        )
    return completed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdr", type=Path, required=True)
    parser.add_argument("--sdk-prefix", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--cmake", default="cmake")
    parser.add_argument("--ctest", default="ctest")
    parser.add_argument("--colcon", default="colcon")
    parser.add_argument("--include-ros2", action="store_true")
    args = parser.parse_args()

    pdr = args.pdr.resolve()
    sdk = args.sdk_prefix.resolve()
    workspace = args.workspace.resolve()
    if not pdr.is_file():
        raise FileNotFoundError(f"installed pdr CLI not found: {pdr}")
    if not (sdk / "lib/cmake/PDRRoboticsRuntime/PDRRoboticsRuntimeConfig.cmake").is_file():
        raise FileNotFoundError(f"installed robotics SDK not found: {sdk}")
    if workspace.exists():
        raise FileExistsError(f"portable consumer workspace already exists: {workspace}")
    workspace.parent.mkdir(parents=True, exist_ok=True)
    cli = [sys.executable, str(pdr)]
    run(cli + [
        "project", "create", "PortableRobotProduct", "--output", str(workspace),
        "--profile", "robotics", "--version", "0.1.0",
    ])
    project = workspace / "PortableRobotProduct"
    run(cli + [
        "new", "robot-module", "PortableMission",
        "--output", str(project / "modules"),
    ])
    if args.include_ros2:
        run(cli + [
            "new", "ros2-node", "PortableGateway",
            "--output", str(project / "adapters/ros2"),
        ])
    run(["git", "init", "-q"], project)
    run(["git", "config", "user.email", "portable-ci@example.invalid"], project)
    run(["git", "config", "user.name", "PortableProjectCI"], project)
    run(["git", "add", "."], project)
    run(["git", "commit", "-qm", "portable generated project candidate"], project)
    plan = project / "build/qualification/plan.json"
    state = project / "build/qualification/state.json"
    run(cli + [
        "project", "pipeline", "create", str(project / "pdr-project.yaml"),
        "--sdk-prefix", str(sdk), "--cmake", args.cmake, "--ctest", args.ctest,
        "--colcon", args.colcon,
    ])
    run(cli + [
        "project", "pipeline", "run", "--plan", str(plan),
        "--state", str(state), "--confirm-run",
    ])
    status = run(cli + [
        "project", "pipeline", "status", "--plan", str(plan),
        "--state", str(state),
    ], expected={2})
    report = json.loads(status.stdout)
    if not report.get("automatedComplete") or report.get("releaseReady"):
        raise RuntimeError("portable project status conflated automated and SIL acceptance")
    if report.get("externalGates") != [{
            "id": "sil", "status": "REQUIRED",
            "reason": "project-specific simulator evidence is not inferred"}]:
        raise RuntimeError("portable project did not retain the required SIL boundary")
    changes = run(["git", "status", "--porcelain"], project).stdout.strip()
    if changes:
        raise RuntimeError("portable project pipeline dirtied the source tree: " + changes)
    state_document = json.loads(state.read_text(encoding="utf-8"))
    expected_stages = 9 if args.include_ros2 else 6
    if len(state_document["stages"]) != expected_stages:
        raise RuntimeError(
            f"portable project ran {len(state_document['stages'])} stages; "
            f"expected {expected_stages}"
        )
    print(
        f"PDR_PORTABLE_PROJECT_PIPELINE_PASS platform={sys.platform} "
        f"stages={len(state_document['stages'])} ros2={str(args.include_ros2).lower()} "
        "external=sil"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
