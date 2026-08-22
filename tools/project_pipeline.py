#!/usr/bin/env python3
"""Generate and operate a portable, checkpointed product-project pipeline."""

from __future__ import annotations

import json
import importlib.util
import os
import re
import sys
from pathlib import Path
from typing import Any


GATE_ACCEPTANCE_TYPES = {
    "sil": "project-sil",
    "hil": "project-hil",
    "soak": "project-soak",
}


def _load_sibling(name: str):
    path = Path(__file__).resolve().with_name(name + ".py")
    spec = importlib.util.spec_from_file_location(f"pdr_project_pipeline_{name}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load project pipeline dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _confined(root: Path, value: Path, label: str) -> Path:
    resolved = value.resolve() if value.is_absolute() else (root / value).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"project pipeline {label} must stay inside the project root")
    return resolved


def _relative(root: Path, value: Path, label: str) -> str:
    try:
        return value.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise ValueError(f"project pipeline {label} must stay inside the build root") from error


def _atomic_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.new")
    try:
        temporary.write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8", newline="\n",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _executable(value: str | Path, label: str) -> str:
    text = str(value)
    if not text or "\x00" in text:
        raise ValueError(f"project pipeline {label} executable is invalid")
    return str(Path(text).resolve()) if Path(text).is_absolute() else text


def _stage(identifier: str, command: list[str], timeout: int,
           inputs: list[str] | None = None,
           outputs: list[str] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": identifier,
        "command": command,
        "workingDirectory": ".",
        "timeoutSeconds": timeout,
    }
    if inputs:
        result["requiredInputs"] = inputs
    if outputs:
        result["requiredOutputs"] = outputs
    return result


def acceptance_boundary(project: dict[str, Any]) -> dict[str, Any]:
    acceptance = project["acceptance"]
    automated = ["manifest", "component-templates", "configuration", "configure", "build"]
    if acceptance["unit"]:
        automated.append("unit")
    if project["components"]["adapters"]["ros2"]:
        automated.append("ros2-build-test")
    external = []
    if acceptance["sil"]:
        external.append({"id": "sil", "status": "REQUIRED",
                         "reason": "project-specific simulator evidence is not inferred"})
    if acceptance["hil"]:
        external.append({"id": "hil", "status": "REQUIRED",
                         "reason": "physical hardware evidence must be approved separately"})
    if acceptance["soakHours"]:
        external.append({"id": "soak", "status": "REQUIRED",
                         "minimumHours": acceptance["soakHours"],
                         "reason": "elapsed-time and resource evidence must be approved separately"})
    return {"automatedGates": automated, "externalGates": external}


def create_plan(args: Any) -> int:
    project_manager = _load_sibling("project_manager")

    manifest = Path(args.manifest).resolve()
    project_root = manifest.parent
    project = project_manager.validate_manifest(manifest, check_paths=True)
    candidate_version = args.candidate_version or project.get("version")
    if candidate_version is None:
        raise ValueError(
            "project pipeline requires a product version; run pdr project version or pass "
            "--candidate-version for a legacy project"
        )
    if project.get("version") is not None and candidate_version != project["version"]:
        raise ValueError("project pipeline candidate version does not match project manifest")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", args.config):
        raise ValueError("project pipeline build configuration is invalid")
    if args.jobs < 1:
        raise ValueError("project pipeline jobs must be positive")
    for name in ("preflight_timeout", "configure_timeout", "build_timeout", "test_timeout"):
        value = getattr(args, name)
        if value < 1 or value > 86400:
            raise ValueError(f"project pipeline {name.replace('_', '-')} is out of range")
    if any("\x00" in value for value in args.cmake_argument):
        raise ValueError("project pipeline CMake argument contains NUL")
    build_root = _confined(project_root, Path(args.build_root), "build root")
    if build_root == project_root:
        raise ValueError("project pipeline build root cannot be the project root")
    output = _confined(project_root, Path(args.output), "plan output")
    build_root.mkdir(parents=True, exist_ok=True)
    _relative(build_root, output, "plan output")

    sdk_prefix = Path(args.sdk_prefix).resolve()
    if not sdk_prefix.is_dir():
        raise FileNotFoundError(f"project pipeline SDK prefix not found: {sdk_prefix}")
    pdr = Path(__file__).resolve().with_name("pdr.py")
    python = _executable(args.python, "Python")
    cmake = _executable(args.cmake, "CMake")
    ctest = _executable(args.ctest, "CTest")
    colcon = _executable(args.colcon, "colcon")
    reports = build_root / "reports"
    cmake_build = build_root / "cmake"
    lock = build_root / "pdr-project.lock.json"
    resolved_config = build_root / "resolved-config.json"

    validate_report = reports / "project-validation.json"
    stages = [
        _stage("validate", [
            python, str(pdr), "project", "validate", str(manifest),
            "--report", str(validate_report),
        ], args.preflight_timeout, outputs=[_relative(build_root, validate_report, "report")]),
        _stage("resolve", [
            python, str(pdr), "project", "resolve", str(manifest),
            "--output", str(lock),
        ], args.preflight_timeout,
            inputs=[_relative(build_root, validate_report, "validation report")],
            outputs=[_relative(build_root, lock, "project lock")]),
        _stage("config", [
            python, str(pdr), "project", "config", "resolve", str(manifest),
            "--output", str(resolved_config),
        ] + (["--require-environment"] if args.require_environment else []),
            args.preflight_timeout,
            inputs=[_relative(build_root, lock, "project lock")],
            outputs=[_relative(build_root, resolved_config, "resolved config")]),
        _stage("configure", [
            cmake, "-S", str(project_root), "-B", str(cmake_build),
            f"-DCMAKE_PREFIX_PATH={sdk_prefix}", "-DBUILD_TESTING=ON",
            f"-DCMAKE_BUILD_TYPE={args.config}", *args.cmake_argument,
        ], args.configure_timeout,
            inputs=[_relative(build_root, resolved_config, "resolved config")],
            outputs=[_relative(build_root, cmake_build / "CMakeCache.txt", "CMake cache")]),
        _stage("build", [
            cmake, "--build", str(cmake_build), "--config", args.config,
            "--parallel", str(args.jobs),
        ], args.build_timeout,
            inputs=[_relative(build_root, cmake_build / "CMakeCache.txt", "CMake cache")]),
    ]
    if project["acceptance"]["unit"]:
        stages.append(_stage("unit-test", [
            ctest, "--test-dir", str(cmake_build), "-C", args.config,
            "--output-on-failure", "--no-tests=error", "-j", str(args.jobs),
        ], args.test_timeout,
            inputs=[_relative(build_root, cmake_build / "CMakeCache.txt", "CMake cache")],
            outputs=[_relative(
                build_root, cmake_build / "Testing/Temporary/LastTest.log", "CTest log"
            )]))

    ros2_paths = [project_root / item for item in project["components"]["adapters"]["ros2"]]
    if ros2_paths and not args.skip_ros2:
        ros_build = build_root / "ros2-build"
        ros_install = build_root / "ros2-install"
        ros_log = build_root / "ros2-log"
        base_paths = [str(path) for path in ros2_paths]
        stages.extend([
            _stage("ros2-build", [
                colcon, "--log-base", str(ros_log), "build", "--base-paths", *base_paths,
                "--build-base", str(ros_build), "--install-base", str(ros_install),
                "--cmake-args", f"-DCMAKE_PREFIX_PATH={sdk_prefix}",
            ], args.build_timeout),
            _stage("ros2-test", [
                colcon, "--log-base", str(ros_log), "test",
                "--build-base", str(ros_build), "--install-base", str(ros_install),
            ], args.test_timeout),
            _stage("ros2-test-result", [
                colcon, "test-result", "--test-result-base", str(ros_build), "--verbose",
            ], args.preflight_timeout),
        ])
    elif ros2_paths and args.skip_ros2:
        raise ValueError("registered ROS 2 adapters cannot be silently skipped")

    boundary = acceptance_boundary(project)
    plan = {
        "schemaVersion": 1,
        "pipelineId": f"{project['name']}-project-qualification",
        "sourceRoot": str(project_root),
        "buildRoot": str(build_root),
        "metadata": {
            "planType": "pdr-project-qualification",
            "project": project["name"],
            "manifest": manifest.name,
            "runtimeProfile": project["runtime"]["profile"],
            "configuration": args.config,
            "candidateVersion": candidate_version,
            "sdkPrefix": str(sdk_prefix),
            **boundary,
        },
        "stages": stages,
    }
    _atomic_json(output, plan)
    print(
        f"PDR_PROJECT_PIPELINE_CREATE_PASS project={project['name']} stages={len(stages)} "
        f"external={len(boundary['externalGates'])} plan={output}"
    )
    return 0


def execute(args: Any, resume: bool) -> int:
    release_pipeline = _load_sibling("release_pipeline")

    return release_pipeline.execute(args, resume)


def status(args: Any) -> int:
    external_acceptance = _load_sibling("external_acceptance")
    release_pipeline = _load_sibling("release_pipeline")

    plan, _, _ = release_pipeline.load_plan(args.plan.resolve())
    state = json.loads(args.state.resolve().read_text(encoding="utf-8"))
    if state.get("planSha256") != release_pipeline.digest(args.plan.resolve()):
        raise ValueError("project pipeline state does not match the supplied plan")
    metadata = plan.get("metadata", {})
    external = [dict(item) for item in metadata.get("externalGates", [])]
    reports = dict(args.external_evidence)
    signatures = dict(args.external_signature)
    if len(reports) != len(args.external_evidence) or len(signatures) != len(args.external_signature):
        raise ValueError("project pipeline external evidence contains duplicate gate ids")
    expected_gates = {item["id"] for item in external}
    unexpected = (set(reports) | set(signatures)) - expected_gates
    if unexpected:
        raise ValueError("project pipeline evidence is not required: " + ", ".join(sorted(unexpected)))
    if set(reports) != set(signatures):
        raise ValueError("every project external report requires a matching signature")
    if reports:
        required = (
            args.trust_policy, args.expected_trust_policy_id,
            args.expected_trust_policy_sha256, args.signature_check_executable,
        )
        if any(value is None for value in required):
            raise ValueError("project external evidence requires trust policy pins and verifier")
        source = state.get("source", {})
        commit = source.get("commit")
        if not isinstance(commit, str) or not commit:
            raise ValueError("project pipeline state has no candidate Git commit")
        lock = Path(plan["buildRoot"]).resolve() / "pdr-project.lock.json"
        if not lock.is_file():
            raise FileNotFoundError("project pipeline lock is unavailable for candidate binding")
        for gate in external:
            gate_id = gate["id"]
            if gate_id not in reports:
                continue
            verified = external_acceptance.verify_signed_report(
                reports[gate_id], signatures[gate_id], args.trust_policy,
                args.expected_trust_policy_id, args.expected_trust_policy_sha256,
                args.signature_check_executable, GATE_ACCEPTANCE_TYPES[gate_id],
                metadata["candidateVersion"], commit, release_pipeline.digest(lock),
                ({"minimumHours": str(gate["minimumHours"])}
                 if gate_id == "soak" else {}),
            )
            gate.update({
                "status": "APPROVED",
                "acceptanceType": verified["acceptanceType"],
                "contentSha256": verified["contentSha256"],
                "approverId": verified["approverId"],
                "keyId": verified["keyId"],
            })
    automated_complete = state.get("status") == "complete"
    external_complete = all(item.get("status") == "APPROVED" for item in external)
    report = {
        "schemaVersion": 1,
        "operation": "project-pipeline-status",
        "project": metadata.get("project"),
        "automatedStatus": state.get("status"),
        "automatedComplete": automated_complete,
        "externalGates": external,
        "releaseReady": automated_complete and external_complete,
        "stages": [
            {"id": item.get("id"), "status": item.get("status")}
            for item in state.get("stages", [])
        ],
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["releaseReady"] else 2
