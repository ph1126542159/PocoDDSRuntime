#!/usr/bin/env python3
"""PocoDDSRuntime developer command line tools."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path


KINDS = (
    "module", "service", "device", "workflow", "bundle", "plugin", "subprocess",
    "robot-module", "robot-hardware-adapter", "robot-simulation-adapter", "robot-process",
    "ros2-node",
)
EXTERNAL_ACCEPTANCE_TYPES = (
    "petalinux-target", "physical-protocols", "production-identity", "site-network",
    "soak-24h", "soak-72h", "project-sil", "project-hil", "project-soak",
)
PERSISTENCE_KINDS = {"tasks": "tasks", "idempotency": "requests"}


def tool_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_project_manager():
    path = Path(__file__).resolve().with_name("project_manager.py")
    spec = importlib.util.spec_from_file_location("pdr_project_manager_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load project manager: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_project(args: argparse.Namespace) -> int:
    return load_project_manager().create_project(args)


def validate_project(args: argparse.Namespace) -> int:
    return load_project_manager().validate_project(args)


def resolve_project(args: argparse.Namespace) -> int:
    return load_project_manager().resolve_project(args)


def set_project_version(args: argparse.Namespace) -> int:
    return load_project_manager().set_project_version(args)


def add_project_component(args: argparse.Namespace) -> int:
    return load_project_manager().add_project_component(args)


def remove_project_component(args: argparse.Namespace) -> int:
    return load_project_manager().remove_project_component(args)


def list_project_components(args: argparse.Namespace) -> int:
    return load_project_manager().list_project_components(args)


def sync_project(args: argparse.Namespace) -> int:
    return load_project_manager().sync_project(args)


def project_change_impact(args: argparse.Namespace) -> int:
    return load_project_manager().project_change_impact(args)


def load_project_config():
    path = Path(__file__).resolve().with_name("project_config.py")
    spec = importlib.util.spec_from_file_location("pdr_project_config_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load project config resolver: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def resolve_project_config(args: argparse.Namespace) -> int:
    return load_project_config().resolve_project_config(args)


def load_project_config_transaction():
    path = Path(__file__).resolve().with_name("project_config_transaction.py")
    spec = importlib.util.spec_from_file_location("pdr_project_config_transaction_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load project configuration transaction tooling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def plan_project_config(args: argparse.Namespace) -> int:
    return load_project_config_transaction().plan_command(args)


def preflight_project_config(args: argparse.Namespace) -> int:
    return load_project_config_transaction().preflight_command(args)


def load_project_config_approval():
    path = Path(__file__).resolve().with_name("project_config_approval.py")
    spec = importlib.util.spec_from_file_location("pdr_project_config_approval_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load project configuration approval tooling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def request_project_config_approval(args: argparse.Namespace) -> int:
    return load_project_config_approval().request_command(args)


def approve_project_config(args: argparse.Namespace) -> int:
    return load_project_config_approval().approve_command(args)


def load_project_config_audit():
    path = Path(__file__).resolve().with_name("project_config_audit.py")
    spec = importlib.util.spec_from_file_location("pdr_project_config_audit_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load project configuration audit tooling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_project_config_audit(args: argparse.Namespace) -> int:
    return load_project_config_audit().verify_command(args)


def load_project_config_audit_checkpoint():
    path = Path(__file__).resolve().with_name("project_config_audit_checkpoint.py")
    spec = importlib.util.spec_from_file_location(
        "pdr_project_config_audit_checkpoint_cli", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load project configuration audit checkpoint tooling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def checkpoint_project_config_audit(args: argparse.Namespace) -> int:
    return load_project_config_audit_checkpoint().checkpoint_command(args)


def verify_project_config_audit_checkpoint(args: argparse.Namespace) -> int:
    return load_project_config_audit_checkpoint().verify_checkpoint_command(args)


def load_project_config_status():
    path = Path(__file__).resolve().with_name("project_config_status.py")
    spec = importlib.util.spec_from_file_location("pdr_project_config_status_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load project configuration status tooling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def project_config_status(args: argparse.Namespace) -> int:
    return load_project_config_status().status_command(args)


def apply_project_config(args: argparse.Namespace) -> int:
    return load_project_config_transaction().apply_command(args)


def recover_project_config(args: argparse.Namespace) -> int:
    return load_project_config_transaction().recover_command(args)


def load_project_template():
    path = Path(__file__).resolve().with_name("project_template.py")
    spec = importlib.util.spec_from_file_location("pdr_project_template_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load project template tooling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def project_template_status(args: argparse.Namespace) -> int:
    return load_project_template().status_command(args)


def adopt_project_template(args: argparse.Namespace) -> int:
    return load_project_template().adopt_command(args)


def upgrade_project_template(args: argparse.Namespace) -> int:
    return load_project_template().upgrade_command(args)


def recover_project_template(args: argparse.Namespace) -> int:
    return load_project_template().recover_command(args)


def load_component_template():
    path = Path(__file__).resolve().with_name("component_template.py")
    spec = importlib.util.spec_from_file_location("pdr_component_template_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load component template tooling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def component_template_status(args: argparse.Namespace) -> int:
    return load_component_template().status_command(args, templates)


def adopt_component_template(args: argparse.Namespace) -> int:
    return load_component_template().adopt_command(args, templates)


def upgrade_component_template(args: argparse.Namespace) -> int:
    return load_component_template().upgrade_command(args, templates)


def recover_component_template(args: argparse.Namespace) -> int:
    return load_component_template().recover_command(args)


def component_dependency(args: argparse.Namespace) -> int:
    return load_component_template().dependency_command(args)


def load_component_contract_test():
    path = Path(__file__).resolve().with_name("component_contract_test.py")
    spec = importlib.util.spec_from_file_location("pdr_component_contract_test_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load component contract test tooling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def component_contract_test(args: argparse.Namespace) -> int:
    return load_component_contract_test().validate_command(args)


def component_contract_verify(args: argparse.Namespace) -> int:
    return load_component_contract_test().verify_report_command(args)


def load_configuration_participant_contract():
    path = Path(__file__).resolve().with_name("configuration_participant_contract.py")
    spec = importlib.util.spec_from_file_location(
        "pdr_configuration_participant_contract_cli", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"cannot load configuration participant contract tooling: {path}"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configuration_participant_contract_test(args: argparse.Namespace) -> int:
    return load_configuration_participant_contract().validate_command(args)


def load_configuration_key_lifecycle():
    path = Path(__file__).resolve().with_name("configuration_key_lifecycle.py")
    spec = importlib.util.spec_from_file_location(
        "pdr_configuration_key_lifecycle_cli", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load configuration key lifecycle tooling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configuration_key_lifecycle_test(args: argparse.Namespace) -> int:
    return load_configuration_key_lifecycle().validate_command(args)


def load_service_contract_graph():
    path = Path(__file__).resolve().with_name("service_contract_graph.py")
    spec = importlib.util.spec_from_file_location("pdr_service_contract_graph_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load service contract graph tooling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def service_contract_graph_check(args: argparse.Namespace) -> int:
    return load_service_contract_graph().check_command(args)


def service_contract_graph_verify(args: argparse.Namespace) -> int:
    return load_service_contract_graph().verify_command(args)


def service_contract_baseline_snapshot(args: argparse.Namespace) -> int:
    return load_service_contract_graph().snapshot_command(args)


def load_schema_contract():
    path = Path(__file__).resolve().with_name("schema_contract.py")
    spec = importlib.util.spec_from_file_location("pdr_schema_contract_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load schema contract tooling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def scaffold_schema(args: argparse.Namespace) -> int:
    try:
        return load_schema_contract().scaffold_command(args)
    except (OSError, ValueError) as error:
        print(f"SCHEMA_SCAFFOLD_ERROR: {error}", file=sys.stderr)
        return 2


CAPABILITY_ACTIONS = {
    "service": {"discover", "use"},
    "topic": {"publish", "subscribe"},
    "configuration": {"read", "write"},
    "device": {"observe", "operate"},
    "schema": {"read", "register", "deprecate"},
}


def scaffold_capability_policy(args: argparse.Namespace) -> int:
    try:
        if args.action not in CAPABILITY_ACTIONS[args.resource_kind]:
            raise ValueError(
                f"action {args.action} is not valid for {args.resource_kind} resources"
            )
        output = Path(args.output).resolve()
        if output.exists() and not args.force:
            raise FileExistsError(f"output already exists: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "$schema": str(
                (tool_root() / "contracts" / "schemas" /
                 "runtime-capability-policy.schema.json").resolve()
            ),
            "version": 1,
            "defaultEffect": "deny",
            "rules": [{
                "id": args.rule_id,
                "effect": args.effect,
                "principal": args.principal,
                "resourceKind": args.resource_kind,
                "resource": args.resource,
                "actions": [args.action],
            }],
        }
        output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
        print(json.dumps({"created": str(output), "defaultEffect": "deny",
                          "ruleCount": 1}, ensure_ascii=False))
        return 0
    except (OSError, ValueError) as error:
        print(f"CAPABILITY_SCAFFOLD_ERROR: {error}", file=sys.stderr)
        return 2


def check_capability(args: argparse.Namespace) -> int:
    if not args.validate and not all(
            (args.principal, args.resource_kind, args.resource, args.action)):
        print("CAPABILITY_CHECK_ERROR: decision mode requires --principal, "
              "--resource-kind, --resource and --action", file=sys.stderr)
        return 2
    executable = Path(args.checker).resolve() if args.checker else None
    if executable is None:
        name = "pdr-capability-check.exe" if os.name == "nt" else "pdr-capability-check"
        candidates = [
            tool_root() / "build" / "bin" / name,
            tool_root() / "build" / "workflow-validation" / "bin" / name,
        ]
        located = shutil.which(name)
        if located:
            candidates.insert(0, Path(located))
        executable = next((candidate for candidate in candidates if candidate.is_file()), None)
    if executable is None or not executable.is_file():
        print("CAPABILITY_CHECK_ERROR: pdr-capability-check executable not found",
              file=sys.stderr)
        return 2
    command = [str(executable), "--policy", str(Path(args.policy).resolve())]
    if args.validate:
        command.append("--validate")
    else:
        command.extend([
            "--principal", args.principal,
            "--resource-kind", args.resource_kind,
            "--resource", args.resource,
            "--action", args.action,
        ])
    return subprocess.run(command, check=False).returncode


def check_capability_store(args: argparse.Namespace) -> int:
    executable = Path(args.checker).resolve() if args.checker else None
    if executable is None:
        name = "pdr-capability-store-check.exe" if os.name == "nt" else \
            "pdr-capability-store-check"
        candidates = [
            tool_root() / "build" / "bin" / name,
            tool_root() / "build" / "workflow-validation" / "bin" / name,
        ]
        located = shutil.which(name)
        if located:
            candidates.insert(0, Path(located))
        executable = next((candidate for candidate in candidates if candidate.is_file()), None)
    if executable is None or not executable.is_file():
        print("CAPABILITY_STORE_CHECK_ERROR: native checker executable not found",
              file=sys.stderr)
        return 2
    return subprocess.run([
        str(executable),
        "--database", str(Path(args.database).resolve()),
        "--seed-policy", str(Path(args.seed_policy).resolve()),
    ], check=False).returncode


def apply_capability_store(args: argparse.Namespace) -> int:
    executable = Path(args.checker).resolve() if args.checker else None
    if executable is None:
        name = "pdr-capability-store-apply.exe" if os.name == "nt" else \
            "pdr-capability-store-apply"
        candidates = [
            tool_root() / "build" / "bin" / name,
            tool_root() / "build" / "workflow-validation" / "bin" / name,
        ]
        located = shutil.which(name)
        if located:
            candidates.insert(0, Path(located))
        executable = next((candidate for candidate in candidates if candidate.is_file()), None)
    if executable is None or not executable.is_file():
        print("CAPABILITY_STORE_APPLY_ERROR: native apply executable not found",
              file=sys.stderr)
        return 2
    return subprocess.run([
        str(executable),
        "--database", str(Path(args.database).resolve()),
        "--seed-policy", str(Path(args.seed_policy).resolve()),
        "--candidate-policy", str(Path(args.candidate_policy).resolve()),
        "--actor", args.actor,
        "--request-id", args.request_id,
        "--expected-generation", str(args.expected_generation),
    ], check=False).returncode


def manage_lifecycle_store(args: argparse.Namespace) -> int:
    executable = Path(args.tool).resolve() if args.tool else None
    if executable is None:
        name = "pdr-lifecycle-store.exe" if os.name == "nt" else \
            "pdr-lifecycle-store"
        candidates = [
            tool_root() / "build" / "bin" / name,
            tool_root() / "build" / "workflow-validation" / "bin" / name,
        ]
        located = shutil.which(name)
        if located:
            candidates.insert(0, Path(located))
        executable = next((candidate for candidate in candidates if candidate.is_file()), None)
    if executable is None or not executable.is_file():
        print("LIFECYCLE_STORE_ERROR: native lifecycle store tool not found",
              file=sys.stderr)
        return 2
    command = [
        str(executable),
        "--action", "check" if args.lifecycle_command == "store-check" else "backup",
        "--database", str(Path(args.database).resolve()),
    ]
    if args.lifecycle_command == "store-check":
        command.extend(["--limit", str(args.limit)])
    else:
        command.extend(["--destination", str(Path(args.destination).resolve())])
    return subprocess.run(command, check=False).returncode


def add_project_dependency(args: argparse.Namespace) -> int:
    return load_project_manager().add_project_dependency(args)


def remove_project_dependency(args: argparse.Namespace) -> int:
    return load_project_manager().remove_project_dependency(args)


def list_project_dependencies(args: argparse.Namespace) -> int:
    return load_project_manager().list_project_dependencies(args)


def load_project_package():
    path = Path(__file__).resolve().with_name("project_package.py")
    spec = importlib.util.spec_from_file_location("pdr_project_package_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load project package tooling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_project_package(args: argparse.Namespace) -> int:
    return load_project_package().create_project_package(args)


def verify_project_package(args: argparse.Namespace) -> int:
    return load_project_package().verify_project_package(args)


def load_team_contract_package():
    path = Path(__file__).resolve().with_name("team_contract_package.py")
    spec = importlib.util.spec_from_file_location("pdr_team_contract_package_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load team contract package tooling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pack_team_contract_package(args: argparse.Namespace) -> int:
    return run_team_contract_package("pack", args)


def verify_team_contract_package(args: argparse.Namespace) -> int:
    return run_team_contract_package("verify", args)


def lock_team_contract_packages(args: argparse.Namespace) -> int:
    return run_team_contract_package("create_lock", args)


def resolve_team_contract_packages(args: argparse.Namespace) -> int:
    return run_team_contract_package("resolve", args)


def run_team_contract_package(action: str, args: argparse.Namespace) -> int:
    try:
        return getattr(load_team_contract_package(), action)(args)
    except (OSError, ValueError) as error:
        print(f"PDR_TEAM_CONTRACT_PACKAGE_ERROR: {error}", file=sys.stderr)
        return 2


def load_team_contract_impact():
    path = Path(__file__).resolve().with_name("team_contract_impact.py")
    spec = importlib.util.spec_from_file_location("pdr_team_contract_impact_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load team contract impact tooling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def analyze_team_contract_impact(args: argparse.Namespace) -> int:
    return load_team_contract_impact().impact_command(args)


def load_team_contract_impact_gate():
    path = Path(__file__).resolve().with_name("team_contract_impact_gate.py")
    spec = importlib.util.spec_from_file_location("pdr_team_contract_impact_gate_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load team contract impact gate tooling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def execute_team_contract_impact(args: argparse.Namespace) -> int:
    return load_team_contract_impact_gate().execute_command(args)


def approve_team_contract_impact(args: argparse.Namespace) -> int:
    return load_team_contract_impact_gate().approve_command(args)


def gate_team_contract_impact(args: argparse.Namespace) -> int:
    return load_team_contract_impact_gate().gate_command(args)


def load_team_contract_registry():
    path = Path(__file__).resolve().with_name("team_contract_registry.py")
    spec = importlib.util.spec_from_file_location("pdr_team_contract_registry_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load team contract Registry tooling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def init_team_contract_registry(args: argparse.Namespace) -> int:
    return load_team_contract_registry().init_command(args)


def publish_team_contract_registry(args: argparse.Namespace) -> int:
    return load_team_contract_registry().publish_command(args)


def promote_team_contract_registry(args: argparse.Namespace) -> int:
    return load_team_contract_registry().promote_command(args)


def rollback_team_contract_registry(args: argparse.Namespace) -> int:
    return load_team_contract_registry().rollback_command(args)


def resolve_team_contract_registry(args: argparse.Namespace) -> int:
    return load_team_contract_registry().resolve_command(args)


def verify_team_contract_registry(args: argparse.Namespace) -> int:
    return load_team_contract_registry().verify_command(args)


def inspect_team_contract_registry_lease(args: argparse.Namespace) -> int:
    return load_team_contract_registry().lease_status_command(args)


def load_team_contract_provenance():
    path = Path(__file__).resolve().with_name("team_contract_provenance.py")
    spec = importlib.util.spec_from_file_location("pdr_team_contract_provenance_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load team contract provenance tooling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def attest_team_contract_runner(args: argparse.Namespace) -> int:
    return load_team_contract_provenance().runner_attest_command(args)


def verify_team_contract_runner(args: argparse.Namespace) -> int:
    return load_team_contract_provenance().runner_verify_command(args)


def authorize_team_contract_gate(args: argparse.Namespace) -> int:
    return load_team_contract_provenance().gate_authorize_command(args)


def verify_team_contract_gate_authorization(args: argparse.Namespace) -> int:
    return load_team_contract_provenance().gate_authorization_verify_command(args)


def anchor_team_contract_registry(args: argparse.Namespace) -> int:
    return load_team_contract_provenance().registry_anchor_command(args)


def verify_team_contract_registry_anchor(args: argparse.Namespace) -> int:
    return load_team_contract_provenance().registry_anchor_verify_command(args)


def load_team_contract_registry_remote():
    path = Path(__file__).resolve().with_name("team_contract_registry_remote.py")
    spec = importlib.util.spec_from_file_location("pdr_team_contract_registry_remote_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load remote team contract Registry tooling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_team_contract_registry_audit_archive():
    path = Path(__file__).resolve().with_name(
        "team_contract_registry_audit_archive.py"
    )
    spec = importlib.util.spec_from_file_location(
        "pdr_team_contract_registry_audit_archive_cli", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Registry audit archive tooling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_team_contract_registry_recovery():
    path = Path(__file__).resolve().with_name("team_contract_registry_recovery.py")
    spec = importlib.util.spec_from_file_location(
        "pdr_team_contract_registry_recovery_cli", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Registry recovery tooling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_team_contract_registry_standby():
    path = Path(__file__).resolve().with_name("team_contract_registry_standby.py")
    spec = importlib.util.spec_from_file_location(
        "pdr_team_contract_registry_standby_cli", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Registry standby tooling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_team_contract_registry_leader():
    path = Path(__file__).resolve().with_name("team_contract_registry_leader.py")
    spec = importlib.util.spec_from_file_location(
        "pdr_team_contract_registry_leader_cli", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Registry leader tooling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_team_contract_registry_handoff():
    path = Path(__file__).resolve().with_name("team_contract_registry_handoff.py")
    spec = importlib.util.spec_from_file_location(
        "pdr_team_contract_registry_handoff_cli", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Registry handoff tooling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_team_contract_registry_access_policy():
    path = Path(__file__).resolve().with_name(
        "team_contract_registry_access_policy.py"
    )
    spec = importlib.util.spec_from_file_location(
        "pdr_team_contract_registry_access_policy_cli", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Registry access-policy tooling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def serve_team_contract_registry_remote(args: argparse.Namespace) -> int:
    return load_team_contract_registry_remote().serve_command(args)


def checkpoint_team_contract_registry_remote_audit(args: argparse.Namespace) -> int:
    return load_team_contract_registry_remote().audit_checkpoint_create_command(args)


def verify_team_contract_registry_remote_audit_checkpoint(
        args: argparse.Namespace) -> int:
    return load_team_contract_registry_remote().audit_checkpoint_verify_command(args)


def manage_team_contract_registry_remote_audit_archive(
        args: argparse.Namespace) -> int:
    archive = load_team_contract_registry_audit_archive()
    return getattr(archive, f"{args.archive_operation}_command")(args)


def manage_team_contract_registry_recovery(args: argparse.Namespace) -> int:
    recovery = load_team_contract_registry_recovery()
    return getattr(recovery, f"{args.recovery_operation}_command")(args)


def manage_team_contract_registry_standby(args: argparse.Namespace) -> int:
    standby = load_team_contract_registry_standby()
    return getattr(standby, f"{args.standby_operation}_command")(args)


def manage_team_contract_registry_leader(args: argparse.Namespace) -> int:
    leader = load_team_contract_registry_leader()
    return getattr(leader, f"{args.leader_operation}_command")(args)


def load_team_contract_registry_leader_backend_capabilities():
    path = Path(__file__).resolve().with_name(
        "team_contract_registry_leader_backend_capabilities.py"
    )
    spec = importlib.util.spec_from_file_location(
        "pdr_team_contract_registry_leader_backend_capabilities_cli", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"cannot load Registry leader backend capability tooling: {path}"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inspect_team_contract_registry_leader_backend_capabilities(
        args: argparse.Namespace) -> int:
    return load_team_contract_registry_leader_backend_capabilities() \
        .execute_command(args)


def load_team_contract_registry_leader_backend_migration():
    path = Path(__file__).resolve().with_name(
        "team_contract_registry_leader_backend_migration.py"
    )
    spec = importlib.util.spec_from_file_location(
        "pdr_team_contract_registry_leader_backend_migration_cli", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"cannot load Registry leader backend migration tooling: {path}"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manage_team_contract_registry_leader_backend_migration(
        args: argparse.Namespace) -> int:
    tool = load_team_contract_registry_leader_backend_migration()
    return getattr(tool, f"{args.migration_operation}_command")(args)


def load_team_contract_artifact_store():
    path = Path(__file__).resolve().with_name("team_contract_artifact_store.py")
    spec = importlib.util.spec_from_file_location(
        "pdr_team_contract_artifact_store_cli", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Artifact Store tooling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manage_team_contract_artifact_store(args: argparse.Namespace) -> int:
    tool = load_team_contract_artifact_store()
    return getattr(tool, f"{args.artifact_operation}_command")(args)


def load_team_contract_backend_config_resolver():
    path = Path(__file__).resolve().with_name(
        "team_contract_backend_config_resolver.py"
    )
    spec = importlib.util.spec_from_file_location(
        "pdr_team_contract_backend_config_resolver_cli", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"cannot load Backend Config Resolver tooling: {path}"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manage_team_contract_backend_config_resolver(
        args: argparse.Namespace) -> int:
    return load_team_contract_backend_config_resolver().resolve_command(args)


def load_team_contract_secret_provider():
    path = Path(__file__).resolve().with_name("team_contract_secret_provider.py")
    spec = importlib.util.spec_from_file_location(
        "pdr_team_contract_secret_provider_cli", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Secret Provider tooling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manage_team_contract_secret_provider(args: argparse.Namespace) -> int:
    return load_team_contract_secret_provider().check_command(args)


def load_team_contract_adapter_catalog():
    path = Path(__file__).resolve().with_name("team_contract_adapter_catalog.py")
    spec = importlib.util.spec_from_file_location(
        "pdr_team_contract_adapter_catalog_cli", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Adapter Catalog tooling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manage_team_contract_adapter_catalog(args: argparse.Namespace) -> int:
    tool = load_team_contract_adapter_catalog()
    return getattr(tool, f"{args.adapter_catalog_operation}_command")(args)


def load_team_contract_adapter_catalog_state():
    path = Path(__file__).resolve().with_name(
        "team_contract_adapter_catalog_state.py"
    )
    spec = importlib.util.spec_from_file_location(
        "pdr_team_contract_adapter_catalog_state_cli", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Adapter Catalog state tooling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manage_team_contract_adapter_catalog_state(args: argparse.Namespace) -> int:
    tool = load_team_contract_adapter_catalog_state()
    return getattr(tool, f"{args.adapter_catalog_state_operation}_command")(args)


def load_team_contract_adapter_catalog_reconciler():
    path = Path(__file__).resolve().with_name(
        "team_contract_adapter_catalog_reconciler.py"
    )
    spec = importlib.util.spec_from_file_location(
        "pdr_team_contract_adapter_catalog_reconciler_cli", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Adapter Catalog Reconciler tooling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manage_team_contract_adapter_catalog_reconciler(
        args: argparse.Namespace) -> int:
    tool = load_team_contract_adapter_catalog_reconciler()
    return getattr(
        tool, f"{args.adapter_catalog_reconcile_operation}_command"
    )(args)


def load_team_contract_adapter_catalog_fleet():
    path = Path(__file__).resolve().with_name(
        "team_contract_adapter_catalog_fleet.py"
    )
    spec = importlib.util.spec_from_file_location(
        "pdr_team_contract_adapter_catalog_fleet_cli", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Adapter Catalog Fleet tooling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manage_team_contract_adapter_catalog_fleet(
        args: argparse.Namespace) -> int:
    tool = load_team_contract_adapter_catalog_fleet()
    return getattr(tool, f"{args.adapter_catalog_fleet_operation}_command")(args)


def load_team_contract_adapter_conformance():
    path = Path(__file__).resolve().with_name(
        "team_contract_adapter_conformance.py"
    )
    spec = importlib.util.spec_from_file_location(
        "pdr_team_contract_adapter_conformance_cli", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Adapter conformance tooling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def qualify_team_contract_adapter(args: argparse.Namespace) -> int:
    return load_team_contract_adapter_conformance().execute_command(args)


def load_team_contract_adapter_conformance_admission():
    path = Path(__file__).resolve().with_name(
        "team_contract_adapter_conformance_admission.py"
    )
    spec = importlib.util.spec_from_file_location(
        "pdr_team_contract_adapter_conformance_admission_cli", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"cannot load Adapter conformance admission tooling: {path}"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_team_contract_adapter_admission(args: argparse.Namespace) -> int:
    return load_team_contract_adapter_conformance_admission().create_command(args)


def load_team_contract_adapter_conformance_trust():
    path = Path(__file__).resolve().with_name(
        "team_contract_adapter_conformance_trust.py"
    )
    spec = importlib.util.spec_from_file_location(
        "pdr_team_contract_adapter_conformance_trust_cli", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"cannot load Adapter conformance trust tooling: {path}"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def attest_team_contract_adapter(args: argparse.Namespace) -> int:
    return load_team_contract_adapter_conformance_trust().attest_command(args)


def load_team_contract_registry_leader_backend_conformance():
    path = Path(__file__).resolve().with_name(
        "team_contract_registry_leader_backend_conformance.py"
    )
    spec = importlib.util.spec_from_file_location(
        "pdr_team_contract_registry_leader_backend_conformance_cli", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"cannot load Registry leader backend conformance tooling: {path}"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def qualify_team_contract_registry_leader_backend(
        args: argparse.Namespace) -> int:
    return load_team_contract_registry_leader_backend_conformance().execute_command(
        args
    )


def load_team_contract_registry_leader_etcd_preflight():
    root = tool_root()
    candidates = (
        root / "examples/team-contract-registry-leader-backend-etcdctl",
        root / "share/PocoDDSRuntime/examples/team-contract-registry-leader-backend-etcdctl",
    )
    directory = next((item for item in candidates if item.is_dir()), None)
    if directory is None:
        raise RuntimeError("cannot locate Registry leader etcd adapter SDK example")
    path = directory / "etcd_cluster_preflight.py"
    spec = importlib.util.spec_from_file_location(
        "pdr_team_contract_registry_leader_etcd_preflight_cli", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"cannot load Registry leader etcd preflight tooling: {path}"
        )
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(directory))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def preflight_team_contract_registry_leader_etcd(
        args: argparse.Namespace) -> int:
    return load_team_contract_registry_leader_etcd_preflight().execute(args)


def load_team_contract_registry_leader_etcd_acceptance():
    path = Path(__file__).resolve().with_name(
        "team_contract_registry_leader_etcd_acceptance.py"
    )
    spec = importlib.util.spec_from_file_location(
        "pdr_team_contract_registry_leader_etcd_acceptance_cli", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"cannot load Registry leader etcd acceptance tooling: {path}"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def accept_team_contract_registry_leader_etcd(
        args: argparse.Namespace) -> int:
    return load_team_contract_registry_leader_etcd_acceptance().execute_command(args)


def manage_team_contract_registry_handoff(args: argparse.Namespace) -> int:
    handoff = load_team_contract_registry_handoff()
    return getattr(handoff, f"{args.handoff_operation}_command")(args)


def sign_team_contract_registry_access_policy(args: argparse.Namespace) -> int:
    return load_team_contract_registry_access_policy().sign_command(args)


def activate_team_contract_registry_access_policy(args: argparse.Namespace) -> int:
    return load_team_contract_registry_access_policy().activate_command(args)


def invoke_team_contract_registry_remote(args: argparse.Namespace) -> int:
    args.command = args.remote_operation
    remote = load_team_contract_registry_remote()
    if args.remote_operation == "status":
        return remote.status_client_command(args)
    if args.remote_operation == "audit-verify":
        return remote.audit_client_command(args)
    if args.remote_operation == "audit-archive-status":
        return remote.audit_archive_status_client_command(args)
    if args.remote_operation == "recover":
        return remote.recovery_client_command(args)
    if args.remote_operation == "capacity":
        return remote.capacity_client_command(args)
    if args.remote_operation in {"drain-start", "drain-finalize", "drain-resume"}:
        return remote.remote_drain_client_command(args)
    if args.remote_operation == "drain-status":
        return remote.remote_drain_status_client_command(args)
    if args.remote_operation == "lease-status":
        return remote.lease_status_client_command(args)
    return remote.client_command(args)


def add_team_contract_private_key_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--private-key-environment", required=True)
    parser.add_argument("--private-key-passphrase-environment")


def add_team_contract_registry_trust_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--trust-policy", required=True)
    parser.add_argument("--expected-trust-policy-id", required=True)
    parser.add_argument("--expected-trust-policy-sha256", required=True)
    parser.add_argument("--verification-time")


def add_team_contract_registry_limits(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--maximum-files", type=int, default=64)
    parser.add_argument("--maximum-expanded-bytes", type=int, default=16 * 1024 * 1024)


def add_team_contract_registry_remote_client_arguments(
        parser: argparse.ArgumentParser, mutation: bool = False) -> None:
    parser.add_argument("--url", required=True)
    parser.add_argument("--registry-id", required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--token-environment", required=True)
    parser.add_argument("--expected-revision", type=int, required=mutation)
    parser.add_argument("--allow-insecure-loopback", action="store_true")
    parser.add_argument("--ca-file")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--report")
    parser.set_defaults(handler=invoke_team_contract_registry_remote)


def add_team_contract_registry_remote_query_arguments(
        parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--url", required=True)
    parser.add_argument("--registry-id", required=True)
    parser.add_argument("--token-environment", required=True)
    parser.add_argument("--allow-insecure-loopback", action="store_true")
    parser.add_argument("--ca-file")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--report")
    parser.set_defaults(handler=invoke_team_contract_registry_remote)


def load_upgrade_manager():
    path = Path(__file__).resolve().with_name("upgrade_manager.py")
    spec = importlib.util.spec_from_file_location("pdr_upgrade_manager_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load upgrade manager: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def apply_runtime_upgrade(args: argparse.Namespace) -> int:
    return load_upgrade_manager().apply_upgrade(args)


def preflight_runtime_upgrade(args: argparse.Namespace) -> int:
    return load_upgrade_manager().preflight_upgrade(args)


def rollback_runtime_upgrade(args: argparse.Namespace) -> int:
    return load_upgrade_manager().rollback(args)


def recover_runtime_upgrade(args: argparse.Namespace) -> int:
    return load_upgrade_manager().recover(args)


def load_plugin_manager():
    path = Path(__file__).resolve().with_name("plugin_manager.py")
    spec = importlib.util.spec_from_file_location("pdr_plugin_manager_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load plugin manager: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def preflight_plugin(args: argparse.Namespace) -> int:
    return load_plugin_manager().preflight_command(args)


def install_plugin(args: argparse.Namespace) -> int:
    return load_plugin_manager().install_plugin(args)


def rollback_plugin(args: argparse.Namespace) -> int:
    return load_plugin_manager().rollback_plugin(args)


def recover_plugin(args: argparse.Namespace) -> int:
    return load_plugin_manager().recover_plugin(args)


def sign_plugin(args: argparse.Namespace) -> int:
    return load_plugin_manager().sign_plugin(args)


def load_release_qualification():
    path = Path(__file__).resolve().with_name("release_qualification.py")
    spec = importlib.util.spec_from_file_location("pdr_release_qualification_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load release qualification tool: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def qualify_release(args: argparse.Namespace) -> int:
    return load_release_qualification().qualification_command(args)


def load_external_acceptance():
    path = Path(__file__).resolve().with_name("external_acceptance.py")
    spec = importlib.util.spec_from_file_location("pdr_external_acceptance_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load external acceptance tool: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_external_acceptance_template(args: argparse.Namespace) -> int:
    return load_external_acceptance().create_template(args)


def approve_external_acceptance(args: argparse.Namespace) -> int:
    return load_external_acceptance().approve(args)


def verify_external_acceptance_command(args: argparse.Namespace) -> int:
    return load_external_acceptance().verify_command(args)


def load_evidence_bundle():
    path = Path(__file__).resolve().with_name("evidence_bundle.py")
    spec = importlib.util.spec_from_file_location("pdr_evidence_bundle_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load evidence bundle tool: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_evidence_bundle(args: argparse.Namespace) -> int:
    return load_evidence_bundle().create(args)


def verify_evidence_bundle(args: argparse.Namespace) -> int:
    return load_evidence_bundle().verify(args)


def load_release_pipeline():
    path = Path(__file__).resolve().with_name("release_pipeline.py")
    spec = importlib.util.spec_from_file_location("pdr_release_pipeline_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load release pipeline tool: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_release_pipeline(args: argparse.Namespace) -> int:
    return load_release_pipeline().execute(args, False)


def resume_release_pipeline(args: argparse.Namespace) -> int:
    return load_release_pipeline().execute(args, True)


def release_pipeline_status(args: argparse.Namespace) -> int:
    return load_release_pipeline().status(args)


def load_project_pipeline():
    path = Path(__file__).resolve().with_name("project_pipeline.py")
    spec = importlib.util.spec_from_file_location("pdr_project_pipeline_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load project pipeline tool: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_project_pipeline(args: argparse.Namespace) -> int:
    return load_project_pipeline().create_plan(args)


def run_project_pipeline(args: argparse.Namespace) -> int:
    return load_project_pipeline().execute(args, False)


def resume_project_pipeline(args: argparse.Namespace) -> int:
    return load_project_pipeline().execute(args, True)


def project_pipeline_status(args: argparse.Namespace) -> int:
    return load_project_pipeline().status(args)


def add_release_qualification_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--source", required=True, type=Path)
    command.add_argument("--build", required=True, type=Path)
    command.add_argument("--version", required=True)
    command.add_argument("--config", default="Release")
    command.add_argument("--ctest-log", required=True, type=Path)
    command.add_argument("--expected-tests", required=True, type=int)
    command.add_argument("--max-test-age-hours", type=float, default=24.0)
    command.add_argument("--evidence", action="append", type=named_qualification_path, default=[])
    command.add_argument("--required-evidence", action="append", default=[])
    command.add_argument("--artifact-manifest", type=Path)
    command.add_argument("--artifacts", type=Path)
    command.add_argument("--required-external", action="append", default=[])
    command.add_argument("--external-evidence", action="append", type=named_qualification_path,
                         default=[])
    command.add_argument("--external-signature", action="append", type=named_qualification_path,
                         default=[])
    command.add_argument("--external-trust-policy", type=Path)
    command.add_argument("--expected-external-trust-policy-id")
    command.add_argument("--expected-external-trust-policy-sha256")
    command.add_argument("--signature-check-executable", type=Path)
    command.add_argument("--require-release-approval", action="store_true")
    command.add_argument("--report", required=True, type=Path)


def named_qualification_path(value: str) -> tuple[str, Path]:
    name, separator, raw_path = value.partition("=")
    if not separator or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        raise argparse.ArgumentTypeError("expected NAME=PATH")
    return name, Path(raw_path)


def named_requirement(value: str) -> tuple[str, str]:
    name, separator, requirement = value.partition("=")
    if (not separator or not re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]*", name)
            or not requirement or "\x00" in requirement):
        raise argparse.ArgumentTypeError("expected REQUIREMENT=VALUE")
    return name, requirement


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _isolated_configuration_path(runtime_root: Path, configured: Path | None) -> Path:
    path = configured.resolve() if configured else (runtime_root / "pdr-subprocesses.properties").resolve()
    if path != runtime_root and runtime_root not in path.parents:
        raise ValueError("subprocess configuration must stay inside the Runtime root")
    return path


def _process_exists(process_id: int) -> bool:
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.OpenProcess(0x1000, False, process_id)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return ctypes.get_last_error() != 87  # ERROR_INVALID_PARAMETER means no such PID.
    try:
        os.kill(process_id, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


@contextlib.contextmanager
def _exclusive_file_lock(target: Path):
    lock = target.with_name(target.name + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    descriptor = -1
    for attempt in range(2):
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError as error:
            try:
                existing = lock.read_text(encoding="ascii")
                match = re.search(r"^pid=(\d+)$", existing, re.MULTILINE)
                owner = int(match.group(1)) if match else 0
                if owner <= 0:
                    raise RuntimeError(f"isolated deployment configuration has an invalid lock: {lock}")
                if _process_exists(owner):
                    raise RuntimeError(
                        f"isolated deployment configuration is locked by pid {owner}: {lock}")
                if lock.read_text(encoding="ascii") != existing:
                    raise RuntimeError(f"isolated deployment configuration lock changed: {lock}")
                lock.unlink()
            except RuntimeError:
                raise
            except (OSError, ValueError) as inspection_error:
                raise RuntimeError(
                    f"cannot safely inspect isolated deployment configuration lock: {lock}") \
                    from inspection_error
            if attempt:
                raise RuntimeError(f"cannot recover isolated deployment configuration lock: {lock}") from error
    if descriptor < 0:
        raise RuntimeError(f"cannot acquire isolated deployment configuration lock: {lock}")
    try:
        os.write(descriptor, (
            f"pid={os.getpid()}\n"
            f"createdAt={datetime.now(timezone.utc).isoformat()}\n"
        ).encode("ascii"))
        os.close(descriptor)
        descriptor = -1
        yield
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        lock.unlink(missing_ok=True)


def _parse_subprocess_configuration(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    preserved: list[str] = []
    slots: dict[int, dict[str, str]] = {}
    if not path.exists():
        return preserved, []
    for raw in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*subprocess\.(\d+)\.([^=]+?)\s*=\s*(.*)\s*$", raw)
        if match:
            slots.setdefault(int(match.group(1)), {})[match.group(2).strip()] = match.group(3).strip()
        elif not re.match(r"\s*subprocess\.count\s*=", raw):
            preserved.append(raw)
    ordered = [slots[index] for index in sorted(slots)]
    return preserved, ordered


def _write_subprocess_configuration(path: Path, preserved: list[str],
                                    slots: list[dict[str, str]]) -> None:
    lines = list(preserved)
    while lines and not lines[-1].strip():
        lines.pop()
    if lines:
        lines.append("")
    lines.append(f"subprocess.count = {len(slots)}")
    preferred = ("enabled", "name", "location", "required", "path", "workingDirectory",
                 "argument.count", "pdrManaged", "pdrInstanceManifest")
    for index, slot in enumerate(slots):
        lines.append("")
        keys = [key for key in preferred if key in slot]
        keys += sorted(key for key in slot if key not in keys)
        for key in keys:
            lines.append(f"subprocess.{index}.{key} = {slot[key]}")
    temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.new")
    try:
        temporary.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_isolated_manifest(runtime_root: Path, instance_name: str) -> tuple[Path, dict[str, object]]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", instance_name):
        raise ValueError("instance name must contain only letters, digits, dot, underscore or hyphen")
    instance = (runtime_root / "processes" / instance_name).resolve()
    processes = (runtime_root / "processes").resolve()
    if processes not in instance.parents:
        raise ValueError("isolated plugin instance escapes the Runtime processes directory")
    manifest_path = instance / "scaffold-report.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("operation") != "plugin-isolated-scaffold" or
            manifest.get("passed") is not True or Path(str(manifest.get("instance", ""))).resolve() != instance):
        raise ValueError("invalid isolated plugin scaffold report")
    deployment_files = manifest.get("deploymentFiles")
    if not isinstance(deployment_files, dict) or not deployment_files or \
            "pdr-subprocess-entry.properties" not in deployment_files:
        raise ValueError("isolated plugin scaffold report has no deployment file evidence")
    for relative, expected in deployment_files.items():
        candidate = (instance / relative).resolve()
        if instance not in candidate.parents or not candidate.is_file():
            raise ValueError(f"isolated deployment file is missing or unsafe: {relative}")
        if _file_sha256(candidate) != expected:
            raise ValueError(f"isolated deployment file digest mismatch: {relative}")
    return instance, manifest


def apply_isolated_plugin(args: argparse.Namespace) -> int:
    if not args.confirm_runtime_stopped:
        raise ValueError("refusing configuration mutation without --confirm-runtime-stopped")
    runtime_root = args.runtime_root.resolve()
    instance, manifest = _load_isolated_manifest(runtime_root, args.instance_name)
    configuration = _isolated_configuration_path(runtime_root, args.configuration)
    snippet = instance / "pdr-subprocess-entry.properties"
    _, source_slots = _parse_subprocess_configuration(snippet)
    if len(source_slots) != 0:
        raise ValueError("isolated scaffold snippet must use the N placeholder")
    slot: dict[str, str] = {}
    for raw in snippet.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*subprocess\.N\.([^=]+?)\s*=\s*(.*)\s*$", raw)
        if match:
            slot[match.group(1).strip()] = match.group(2).strip()
    if slot.get("name") != args.instance_name or "path" not in slot:
        raise ValueError("isolated scaffold snippet identity is invalid")
    slot["pdrManaged"] = "true"
    slot["pdrInstanceManifest"] = (instance / "scaffold-report.json").relative_to(runtime_root).as_posix()
    with _exclusive_file_lock(configuration):
        preserved, slots = _parse_subprocess_configuration(configuration)
        matching = [index for index, item in enumerate(slots) if item.get("name") == args.instance_name]
        if matching:
            current = slots[matching[0]]
            if current.get("pdrManaged", "").lower() != "true":
                raise ValueError(f"subprocess name is owned by an unmanaged entry: {args.instance_name}")
            slots[matching[0]] = slot
            changed = current != slot
        else:
            slots.append(slot)
            changed = True
        if changed:
            _write_subprocess_configuration(configuration, preserved, slots)
    report = {"schemaVersion": 1, "operation": "plugin-isolated-apply", "passed": True,
              "changed": changed, "instanceName": args.instance_name,
              "pluginId": manifest.get("pluginId"), "configuration": str(configuration)}
    if args.report:
        load_plugin_manager().atomic_json(args.report.resolve(), report)
    print(f"PLUGIN_ISOLATED_APPLY_PASS instance={args.instance_name} changed={str(changed).lower()}")
    return 0


def list_isolated_plugins(args: argparse.Namespace) -> int:
    runtime_root = args.runtime_root.resolve()
    configuration = _isolated_configuration_path(runtime_root, args.configuration)
    _, slots = _parse_subprocess_configuration(configuration)
    instances = []
    for index, slot in enumerate(slots):
        if slot.get("pdrManaged", "").lower() != "true":
            continue
        manifest_path = (runtime_root / slot.get("pdrInstanceManifest", "")).resolve()
        state = "ready" if manifest_path.is_file() else "manifest-missing"
        plugin_id = None
        if manifest_path.is_file():
            try:
                plugin_id = json.loads(manifest_path.read_text(encoding="utf-8")).get("pluginId")
            except (OSError, ValueError):
                state = "manifest-invalid"
        instances.append({"slot": index, "instanceName": slot.get("name"), "pluginId": plugin_id,
                          "enabled": slot.get("enabled", "true").lower() == "true",
                          "state": state, "manifest": str(manifest_path)})
    report = {"schemaVersion": 1, "operation": "plugin-isolated-list", "passed": True,
              "configuration": str(configuration), "instances": instances}
    if args.report:
        load_plugin_manager().atomic_json(args.report.resolve(), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def remove_isolated_plugin(args: argparse.Namespace) -> int:
    if not args.confirm_runtime_stopped:
        raise ValueError("refusing configuration mutation without --confirm-runtime-stopped")
    runtime_root = args.runtime_root.resolve()
    configuration = _isolated_configuration_path(runtime_root, args.configuration)
    instance = (runtime_root / "processes" / args.instance_name).resolve()
    processes = (runtime_root / "processes").resolve()
    if processes not in instance.parents:
        raise ValueError("isolated plugin instance escapes the Runtime processes directory")
    with _exclusive_file_lock(configuration):
        preserved, slots = _parse_subprocess_configuration(configuration)
        matches = [(index, slot) for index, slot in enumerate(slots)
                   if slot.get("name") == args.instance_name]
        if not matches:
            changed = False
        else:
            index, slot = matches[0]
            if slot.get("pdrManaged", "").lower() != "true":
                raise ValueError(f"refusing to remove unmanaged subprocess: {args.instance_name}")
            del slots[index]
            _write_subprocess_configuration(configuration, preserved, slots)
            changed = True
    purged = False
    if args.purge and instance.exists():
        if not changed:
            _load_isolated_manifest(runtime_root, args.instance_name)
        shutil.rmtree(instance)
        purged = True
    report = {"schemaVersion": 1, "operation": "plugin-isolated-remove", "passed": True,
              "changed": changed, "purged": purged, "instanceName": args.instance_name,
              "configuration": str(configuration)}
    if args.report:
        load_plugin_manager().atomic_json(args.report.resolve(), report)
    print(f"PLUGIN_ISOLATED_REMOVE_PASS instance={args.instance_name} changed={str(changed).lower()} purged={str(purged).lower()}")
    return 0


def scaffold_isolated_plugin(args: argparse.Namespace) -> int:
    manager = load_plugin_manager()
    artifact = args.artifact.resolve()
    runtime_root = args.runtime_root.resolve()
    if not runtime_root.is_dir():
        raise FileNotFoundError(f"runtime root does not exist: {runtime_root}")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", args.instance_name):
        raise ValueError("instance name must contain only letters, digits, dot, underscore or hyphen")
    for name, value, minimum in (
        ("heartbeat-interval", args.heartbeat_interval, 10),
        ("heartbeat-timeout", args.heartbeat_timeout, 1),
        ("watchdog-interval", args.watchdog_interval, 1),
        ("startup-grace", args.startup_grace, 0),
        ("restart-delay", args.restart_delay, 0),
        ("max-restarts", args.max_restarts, 0),
        ("restart-window", args.restart_window, 1),
        ("memory-bytes", args.memory_bytes, 0),
        ("active-process-limit", args.active_process_limit, 0),
    ):
        if value < minimum:
            raise ValueError(f"{name} must be at least {minimum}")
    if args.cpu_rate_percent < 0 or args.cpu_rate_percent > 100:
        raise ValueError("cpu-rate-percent must be between 0 and 100")
    if os.name != "nt" and (args.memory_bytes or args.active_process_limit or
                             args.cpu_rate_percent) and not args.linux_cgroup_path:
        raise ValueError("numeric resource limits on Linux require --linux-cgroup-path")
    info = manager.inspect_bundle(artifact)
    plugin_id = str(info["symbolicName"])
    approval = json.loads(args.approval_report.resolve().read_text(encoding="utf-8"))
    if approval.get("operation") == "plugin-install":
        approval = approval.get("preflight", {})
    if approval.get("operation") != "plugin-preflight" or approval.get("passed") is not True:
        raise ValueError("approval report must contain a successful plugin preflight")
    approved_artifact = approval.get("artifact", {})
    artifact_sha = manager.sha256(artifact)
    if (approved_artifact.get("sha256") != artifact_sha or
            approved_artifact.get("symbolicName") != plugin_id):
        raise ValueError("approval report artifact identity or SHA-256 does not match")
    provenance = approval.get("provenance", {})
    diagnostic_bypass = provenance.get("diagnosticBypass") is True
    if provenance.get("verified") is not True and not (
            diagnostic_bypass and args.allow_diagnostic_bypass):
        raise ValueError("publisher provenance is not verified; diagnostic bypass was not authorized")
    instance = (runtime_root / "processes" / args.instance_name).resolve()
    processes_root = (runtime_root / "processes").resolve()
    if processes_root not in instance.parents:
        raise ValueError("isolated plugin instance escapes the Runtime processes directory")
    if instance.exists():
        raise FileExistsError(f"isolated plugin instance already exists: {instance}")
    launcher = (runtime_root / args.launcher_path).resolve()
    host = (runtime_root / args.host_path).resolve()
    for executable, label in ((launcher, "launcher"), (host, "plugin host")):
        if not executable.is_file():
            raise FileNotFoundError(f"{label} executable not found: {executable}")
    dependencies: dict[str, tuple[Path, dict[str, object]]] = {}
    for source in args.dependency_bundle:
        path = source.resolve()
        dependency_info = manager.inspect_bundle(path, require_plugin=False)
        dependencies[str(dependency_info["symbolicName"])] = (path, dependency_info)
    required = [str(item["id"]) for item in info.get("dependencies", [])]
    missing = [name for name in required if name != plugin_id and name not in dependencies]
    if missing:
        raise ValueError("missing dependency Bundle(s): " + ", ".join(sorted(missing)))
    bundles = instance / "bundles"
    bundles.mkdir(parents=True)
    (instance / "codeCache").mkdir()
    (instance / "data").mkdir()
    shutil.copy2(artifact, bundles / artifact.name)
    for source, _ in dependencies.values():
        shutil.copy2(source, bundles / source.name)
    heartbeat = instance / "plugin-host.heartbeat"
    state = instance / "pdr-process-status.json"
    host_config = instance / "pdr-plugin-host.properties"
    launcher_config = instance / "pdr-launcher.properties"
    allowed = [name for name in dependencies if name != "osp.core"]
    host_config.write_text("\n".join([
        f"pluginHost.pluginId = {plugin_id}",
        f"pluginHost.allowedBundles = {','.join(sorted(allowed))}",
        f"pluginHost.heartbeatFile = {heartbeat.as_posix()}",
        f"pluginHost.stateFile = {state.as_posix()}",
        f"pluginHost.heartbeatIntervalMilliseconds = {args.heartbeat_interval}",
        f"osp.bundleRepository = {bundles.as_posix()}",
        f"osp.codeCache = {(instance / 'codeCache').as_posix()}",
        f"osp.data = {(instance / 'data').as_posix()}",
        "logging.loggers.root.channel = console", "logging.loggers.root.level = information",
        "logging.channels.console.class = ConsoleChannel",
    ]) + "\n", encoding="utf-8", newline="\n")
    host_option = ("/config-file=" if os.name == "nt" else "--config-file=") + host_config.as_posix()
    launcher_config.write_text("\n".join([
        f"relaunchDelay = {args.restart_delay}",
        f"restartBudget.maxRestarts = {args.max_restarts}",
        f"restartBudget.windowMilliseconds = {args.restart_window}",
        "resourceLimits.killProcessTreeOnExit = true",
        f"resourceLimits.memoryBytes = {args.memory_bytes}",
        f"resourceLimits.activeProcessLimit = {args.active_process_limit}",
        f"resourceLimits.cpuRatePercent = {args.cpu_rate_percent}",
        f"resourceLimits.linuxCgroupPath = {args.linux_cgroup_path or ''}",
        f"watchdog.file = {heartbeat.as_posix()}",
        f"watchdog.timeout = {args.heartbeat_timeout}",
        f"watchdog.interval = {args.watchdog_interval}",
        f"watchdog.startupGraceMilliseconds = {args.startup_grace}",
        "watchdog.requireFile = true", "childArgument.count = 1",
        f"childArgument.0 = {host_option}", "osp.bundleMonitor.enabled = false",
        f"osp.bundleRepository = {(instance / 'launcher-bundles').as_posix()}",
        "logging.loggers.root.channel = console", "logging.loggers.root.level = information",
        "logging.channels.console.class = ConsoleChannel",
    ]) + "\n", encoding="utf-8", newline="\n")
    (instance / "launcher-bundles").mkdir()
    launcher_option = ("/config-file=" if os.name == "nt" else "--config-file=") + launcher_config.as_posix()
    snippet = instance / "pdr-subprocess-entry.properties"
    snippet.write_text("\n".join([
        "# Merge this slot into pdr-subprocesses.properties and adjust N/count.",
        f"subprocess.N.enabled = true", f"subprocess.N.name = {args.instance_name}",
        "subprocess.N.location = local", "subprocess.N.required = true",
        f"subprocess.N.path = {launcher.relative_to(runtime_root).as_posix()}",
        f"subprocess.N.workingDirectory = {instance.relative_to(runtime_root).as_posix()}",
        "subprocess.N.argument.count = 2", f"subprocess.N.argument.0 = {launcher_option}",
        f"subprocess.N.argument.1 = {host.as_posix()}",
    ]) + "\n", encoding="utf-8", newline="\n")
    deployment_files = [host_config, launcher_config, snippet]
    deployment_files += sorted(bundles.iterdir())
    report = {
        "schemaVersion": 1, "operation": "plugin-isolated-scaffold", "passed": True,
        "pluginId": plugin_id, "pluginVersion": info.get("version"),
        "artifactSha256": artifact_sha, "instance": str(instance),
        "bundles": sorted(path.name for path in bundles.iterdir()),
        "hostConfiguration": str(host_config), "launcherConfiguration": str(launcher_config),
        "subprocessSnippet": str(snippet),
        "deploymentFiles": {path.relative_to(instance).as_posix(): _file_sha256(path)
                            for path in deployment_files},
        "resourceLimits": {"memoryBytes": args.memory_bytes,
                           "activeProcessLimit": args.active_process_limit,
                           "cpuRatePercent": args.cpu_rate_percent,
                           "linuxCgroupPath": args.linux_cgroup_path or ""},
        "approval": {"report": str(args.approval_report.resolve()),
                     "publisherVerified": provenance.get("verified") is True,
                     "diagnosticBypass": diagnostic_bypass},
    }
    manifest_path = instance / "scaffold-report.json"
    manager.atomic_json(manifest_path, report)
    if args.report and args.report.resolve() != manifest_path:
        manager.atomic_json(args.report.resolve(), report)
    print(f"PLUGIN_ISOLATED_SCAFFOLD_PASS plugin={plugin_id} instance={instance}")
    return 0


def add_plugin_provenance_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--attestation", type=Path)
    command.add_argument("--signature", type=Path)
    command.add_argument("--public-key", type=Path)
    command.add_argument("--trust-policy", type=Path)
    command.add_argument("--expected-trust-policy-id")
    command.add_argument("--expected-trust-policy-sha256")
    command.add_argument("--signature-check-executable", type=Path)
    command.add_argument("--allow-unsigned-plugin", action="store_true")


def default_install_prefix(root: Path | None = None) -> Path:
    candidate = (root or tool_root()).resolve()
    installed_package = candidate / "lib" / "cmake" / "PocoDDSRuntime"
    return candidate if installed_package.is_dir() else candidate / "build" / "install"


def valid_name(value: str) -> str:
    if not re.fullmatch(r"[A-Z][A-Za-z0-9]*", value):
        raise argparse.ArgumentTypeError(
            "name must be PascalCase and contain only ASCII letters and digits"
        )
    return value


def plugin_templates(name: str, requested_kind: str = "plugin") -> dict[str, str]:
    lowered = name.lower()
    target_stem = f"pdr_generated_{requested_kind}_{snake_name(name)}"
    namespace = f"PocoDDS::Generated::{name}"
    symbolic = f"pdr.plugin.{lowered}"
    cmake = f'''cmake_minimum_required(VERSION 3.24)
project({name}Plugin LANGUAGES CXX)
find_package(PocoDDSRuntime 0.1 CONFIG REQUIRED COMPONENTS Plugins)
include(CTest)

add_library({target_stem}_core STATIC src/StatusService.cpp)
set_target_properties({target_stem}_core PROPERTIES
    POSITION_INDEPENDENT_CODE ON OUTPUT_NAME "{name}Core")
target_include_directories({target_stem}_core PUBLIC
    $<BUILD_INTERFACE:${{CMAKE_CURRENT_SOURCE_DIR}}/include>)
target_link_libraries({target_stem}_core PUBLIC PocoDDS::Plugins)

pdr_add_osp_bundle({target_stem}_bundle
    SYMBOLIC_NAME {symbolic}
    BUNDLE_SPEC ${{CMAKE_CURRENT_SOURCE_DIR}}/{name}.bndlspec
    SOURCES ${{CMAKE_CURRENT_SOURCE_DIR}}/src/BundleActivator.cpp
    LINK_LIBS {target_stem}_core
    INCLUDE_DIRS ${{CMAKE_CURRENT_SOURCE_DIR}}/include)

install(DIRECTORY "${{{target_stem}_bundle_BUNDLE_DIRECTORY}}/"
    DESTINATION bin/bundles FILES_MATCHING PATTERN "*.bndl")

if(BUILD_TESTING)
    add_executable({target_stem}_smoke tests/{name}Smoke.cpp)
    set_target_properties({target_stem}_smoke PROPERTIES OUTPUT_NAME "{name}Smoke")
    target_link_libraries({target_stem}_smoke PRIVATE {target_stem}_core)
    add_test(NAME {requested_kind}-{lowered}-smoke COMMAND {target_stem}_smoke)
endif()
'''
    header = f'''#pragma once

#include <Poco/OSP/Service.h>

#include <string>

namespace {namespace}
{{
class StatusService final : public Poco::OSP::Service
{{
public:
    static constexpr const char* SERVICE_NAME = "{symbolic}.status";

    const std::string& pluginName() const noexcept {{ return _pluginName; }}
    bool started() const noexcept {{ return _started; }}
    void markStarted(bool value) noexcept {{ _started = value; }}
    const std::type_info& type() const override {{ return typeid(StatusService); }}
    bool isA(const std::type_info& other) const override
    {{
        return std::string(other.name()) == typeid(StatusService).name() ||
               Poco::OSP::Service::isA(other);
    }}

private:
    std::string _pluginName{{"{name}"}};
    bool _started{{false}};
}};
}}
'''
    status_source = f'''#include <PocoDDS/Generated/{name}/StatusService.h>
'''
    activator = f'''#include <PocoDDS/Generated/{name}/StatusService.h>

#include <Poco/ClassLibrary.h>
#include <Poco/AutoPtr.h>
#include <Poco/OSP/BundleActivator.h>
#include <Poco/OSP/BundleContext.h>
#include <Poco/OSP/Properties.h>
#include <Poco/OSP/ServiceRef.h>
#include <Poco/OSP/ServiceRegistry.h>

namespace {namespace}
{{
class BundleActivator final : public Poco::OSP::BundleActivator
{{
public:
    void start(Poco::OSP::BundleContext::Ptr context) override
    {{
        _service = new StatusService;
        _service->markStarted(true);
        Poco::OSP::Properties properties;
        properties.set("pdr.plugin", "{symbolic}");
        properties.set("pdr.plugin.version", "1.0.0");
        _serviceRef = context->registry().registerService(
            StatusService::SERVICE_NAME, _service, properties);
        context->logger().information("{name} plugin started");
    }}

    void stop(Poco::OSP::BundleContext::Ptr context) override
    {{
        if (_serviceRef) context->registry().unregisterService(_serviceRef);
        if (_service) _service->markStarted(false);
        _serviceRef.reset();
        _service.reset();
    }}

private:
    Poco::AutoPtr<StatusService> _service;
    Poco::OSP::ServiceRef::Ptr _serviceRef;
}};
}}

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
    POCO_EXPORT_CLASS({namespace}::BundleActivator)
POCO_END_MANIFEST
'''
    smoke = f'''#include <PocoDDS/Generated/{name}/StatusService.h>

int main()
{{
    {namespace}::StatusService service;
    if (service.pluginName() != "{name}" || service.started()) return 1;
    service.markStarted(true);
    return service.started() && service.isA(typeid({namespace}::StatusService)) ? 0 : 2;
}}
'''
    specification = f'''<?xml version="1.0"?>
<bundlespec>
  <manifest>
    <name>{name} Plugin</name>
    <symbolicName>{symbolic}</symbolicName>
    <version>1.0.0</version>
    <vendor>Generated with PocoDDSRuntime</vendor>
    <pluginApi>${{pdrPluginApi}}</pluginApi>
    <pluginAbi>${{pdrPluginAbi}}</pluginAbi>
    <pluginAbiFingerprint>${{pdrPluginAbiFingerprint}}</pluginAbiFingerprint>
    <runtimeVersion>${{pdrRuntimeRange}}</runtimeVersion>
    <activator>
      <class>{namespace}::BundleActivator</class>
      <library>{symbolic}</library>
    </activator>
    <lazyStart>false</lazyStart>
    <runLevel>200</runLevel>
    <requiredBundles>
      <bundle><symbolicName>osp.core</symbolicName><version>[1.0.0,2.0.0)</version></bundle>
    </requiredBundles>
  </manifest>
  <code>
    ${{bin}}/*.dll,
    ${{bin}}/*.pdb,
    bin/${{osName}}/${{osArch}}/*.so,
    bin/${{osName}}/${{osArch}}/*.dylib
  </code>
</bundlespec>
'''
    kind_note = (
        "`bundle` is the user-facing alias for a deployable external OSP plugin. "
        "The `pdr.plugin.*` symbolic-name boundary keeps it subject to the same "
        "compatibility, signing and quarantine gates."
        if requested_kind == "bundle" else
        "This is a deployable external OSP plugin Bundle."
    )
    readme = f'''# {name} Plugin

Generated external OSP plugin using only the installed `PocoDDSRuntime` Plugins component.
{kind_note}

```text
pdr verify . --prefix <install-prefix> --config Release --artifact-output dist \
  --report verify-report.json
```

The build creates `bundles/{symbolic}.bndl`. Copy that artifact into a stopped Runtime's
`bundles/` directory, validate the deployment inventory, and then restart Runtime. The plugin
registers `{symbolic}.status`; business behavior belongs in this plugin, not framework Core.
Never overwrite an existing symbolic name without an explicit compatibility and rollback plan.
'''
    return {
        "CMakeLists.txt": cmake,
        f"include/PocoDDS/Generated/{name}/StatusService.h": header,
        "src/StatusService.cpp": status_source,
        "src/BundleActivator.cpp": activator,
        f"tests/{name}Smoke.cpp": smoke,
        f"{name}.bndlspec": specification,
        "README.md": readme,
    }


def kebab_name(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()


def snake_name(name: str) -> str:
    return kebab_name(name).replace("-", "_")


def robot_module_templates(name: str) -> dict[str, str]:
    slug = kebab_name(name)
    module_id = snake_name(name)
    namespace = f"PocoDDS::Generated::{name}"
    target_stem = f"pdr_robot_module_{snake_name(name)}"
    cmake = f'''cmake_minimum_required(VERSION 3.24)
project({name}RobotModule LANGUAGES CXX)
find_package(PDRRoboticsRuntime 0.1 CONFIG REQUIRED)
include(CTest)

add_library({target_stem}_core STATIC src/{name}.cpp)
set_target_properties({target_stem}_core PROPERTIES
    POSITION_INDEPENDENT_CODE ON OUTPUT_NAME "{name}Core")
target_include_directories({target_stem}_core PUBLIC
    $<BUILD_INTERFACE:${{CMAKE_CURRENT_SOURCE_DIR}}/include>)
target_link_libraries({target_stem}_core PUBLIC PocoDDS::RoboticsRuntime)

add_library({target_stem}_plugin MODULE src/Plugin.cpp)
target_link_libraries({target_stem}_plugin PRIVATE {target_stem}_core)
set_target_properties({target_stem}_plugin PROPERTIES
    PREFIX "" OUTPUT_NAME "pdr-robot-{slug}-plugin")

if(BUILD_TESTING)
    add_executable({target_stem}_smoke tests/{name}Smoke.cpp)
    set_target_properties({target_stem}_smoke PROPERTIES OUTPUT_NAME "{name}Smoke")
    target_link_libraries({target_stem}_smoke PRIVATE {target_stem}_core)
    add_test(NAME {slug}-robot-module-smoke COMMAND {target_stem}_smoke)
endif()

install(TARGETS {target_stem}_plugin
    LIBRARY DESTINATION lib/pdr/robotics/plugins
    RUNTIME DESTINATION bin/robotics/plugins)
'''
    header = f'''#pragma once

#include <PocoDDS/Robotics/Business.h>

namespace {namespace}
{{
class {name} final : public PocoDDS::Robotics::RobotBusinessModule
{{
public:
    std::string name() const override;
    std::vector<std::string> missions() const override;
    std::unique_ptr<PocoDDS::Robotics::Behavior>
        createMission(const std::string& mission,
                      PocoDDS::Robotics::BusinessContext& context) const override;
}};
}}
'''
    source = f'''#include <PocoDDS/Generated/{name}/{name}.h>

namespace {namespace}
{{
std::string {name}::name() const {{ return "{module_id}"; }}

std::vector<std::string> {name}::missions() const {{ return {{"execute"}}; }}

std::unique_ptr<PocoDDS::Robotics::Behavior>
{name}::createMission(const std::string& mission,
                      PocoDDS::Robotics::BusinessContext& context) const
{{
    if (mission != "execute") return {{}};
    return PocoDDS::Robotics::makeTracedBusinessStep(
        context, name(), mission, "complete", "generated=true",
        std::make_unique<PocoDDS::Robotics::BehaviorTask>(
            [](PocoDDS::Robotics::BehaviorBlackboard&)
            {{ return PocoDDS::Robotics::BehaviorStatus::succeeded; }}),
        [] {{ return std::string("result=completed"); }});
}}
}}
'''
    plugin = f'''#include <PocoDDS/Generated/{name}/{name}.h>
#include <PocoDDS/Robotics/BusinessPlugin.h>

namespace
{{
PocoDDS::Robotics::RobotBusinessModule* createModule()
{{
    return new {namespace}::{name};
}}

void destroyModule(PocoDDS::Robotics::RobotBusinessModule* module) noexcept
{{
    delete module;
}}

const PocoDDS::Robotics::BusinessPluginDescriptor descriptor{{
    sizeof(PocoDDS::Robotics::BusinessPluginDescriptor),
    PocoDDS::Robotics::businessPluginAbiVersion,
    "{module_id}", &createModule, &destroyModule}};
}}

PDR_BUSINESS_PLUGIN_EXPORT
const PocoDDS::Robotics::BusinessPluginDescriptor* pdrBusinessPluginV1()
{{
    return &descriptor;
}}
'''
    smoke = f'''#include <PocoDDS/Generated/{name}/{name}.h>

#include <algorithm>

int main()
{{
    {namespace}::{name} module;
    const auto missions = module.missions();
    return module.name() == "{module_id}" &&
           std::find(missions.begin(), missions.end(), "execute") != missions.end() ? 0 : 1;
}}
'''
    readme = f'''# {name} robot business module

This is a trusted native `RobotBusinessModule` plugin. Build it with the exact
PDRRoboticsRuntime SDK, compiler, architecture and C++ runtime used by the host.
Load the resulting library only through an explicit `business_plugins` path and
list `{module_id}` in `business_modules`; never enable directory auto-scanning.

```text
pdr verify . --prefix <robotics-install-prefix> --config Release
```
'''
    return {
        "CMakeLists.txt": cmake,
        f"include/PocoDDS/Generated/{name}/{name}.h": header,
        f"src/{name}.cpp": source,
        "src/Plugin.cpp": plugin,
        f"tests/{name}Smoke.cpp": smoke,
        "README.md": readme,
    }


def robot_adapter_templates(name: str, kind: str) -> dict[str, str]:
    slug = kebab_name(name)
    namespace = f"PocoDDS::Generated::{name}"
    simulation = kind == "robot-simulation-adapter"
    target_stem = f"pdr_{kind.replace('-', '_')}_{snake_name(name)}"
    base_header = "SimulationAdapter.h" if simulation else "HardwareInterface.h"
    base_class = "SimulationAdapter" if simulation else "HardwareInterface"
    cmake = f'''cmake_minimum_required(VERSION 3.24)
project({name}RobotAdapter LANGUAGES CXX)
find_package(PDRRoboticsRuntime 0.1 CONFIG REQUIRED)
include(CTest)

add_library({target_stem} src/{name}.cpp)
set_target_properties({target_stem} PROPERTIES OUTPUT_NAME "{name}")
target_include_directories({target_stem} PUBLIC
    $<BUILD_INTERFACE:${{CMAKE_CURRENT_SOURCE_DIR}}/include>)
target_link_libraries({target_stem} PUBLIC PocoDDS::RoboticsRuntime)

install(TARGETS {target_stem}
    ARCHIVE DESTINATION lib
    LIBRARY DESTINATION lib
    RUNTIME DESTINATION bin)
install(DIRECTORY include/ DESTINATION include)

if(BUILD_TESTING)
    add_executable({target_stem}_smoke tests/{name}Smoke.cpp)
    set_target_properties({target_stem}_smoke PROPERTIES OUTPUT_NAME "{name}Smoke")
    target_link_libraries({target_stem}_smoke PRIVATE {target_stem})
    add_test(NAME {kind}-{slug}-smoke COMMAND {target_stem}_smoke)
endif()
'''
    common_members = '''    mutable std::mutex _mutex;
    bool _configured{false};
    bool _active{false};
    PocoDDS::Robotics::RobotFrame _frame;
    PocoDDS::Robotics::RobotCommand _command;
    std::uint64_t _readCount{0};
    std::uint64_t _writeCount{0};'''
    if simulation:
        declarations = '''    std::string backendName() const override;
    bool connect(const std::string& world) override;
    void reset() override;
    void applyCommand(const PocoDDS::Robotics::RobotCommand& command) override;
    PocoDDS::Robotics::RobotFrame step(std::chrono::nanoseconds duration) override;
    bool connected() const noexcept override;
    PocoDDS::Robotics::BackendHealth health() const override;'''
    else:
        declarations = '''    std::string name() const override;
    bool configure(const std::string& description) override;
    bool activate() override;
    void deactivate() noexcept override;
    void reset() override;
    PocoDDS::Robotics::RobotFrame read(std::chrono::nanoseconds period) override;
    bool write(const PocoDDS::Robotics::RobotCommand& command,
               std::chrono::nanoseconds period) override;
    PocoDDS::Robotics::BackendHealth health() const override;'''
    header = f'''#pragma once

#include <PocoDDS/Robotics/{base_header}>

#include <cstdint>
#include <mutex>

namespace {namespace}
{{
class {name} final : public PocoDDS::Robotics::{base_class}
{{
public:
{declarations}

private:
{common_members}
}};
}}
'''
    if simulation:
        source = f'''#include <PocoDDS/Generated/{name}/{name}.h>

namespace {namespace}
{{
std::string {name}::backendName() const {{ return "{slug}"; }}
bool {name}::connect(const std::string& world)
{{
    std::lock_guard lock(_mutex);
    _configured = !world.empty();
    return _configured;
}}
void {name}::reset()
{{
    std::lock_guard lock(_mutex);
    _frame = {{}}; _command = {{}}; _readCount = 0; _writeCount = 0;
}}
void {name}::applyCommand(const PocoDDS::Robotics::RobotCommand& command)
{{
    std::lock_guard lock(_mutex); _command = command; ++_writeCount;
}}
PocoDDS::Robotics::RobotFrame {name}::step(std::chrono::nanoseconds)
{{
    std::lock_guard lock(_mutex); ++_readCount; return _frame;
}}
bool {name}::connected() const noexcept
{{
    std::lock_guard lock(_mutex); return _configured;
}}
PocoDDS::Robotics::BackendHealth {name}::health() const
{{
    std::lock_guard lock(_mutex);
    return {{_configured, _backendActive.load(), _configured && _backendActive.load(),
             _readCount, _writeCount, _configured ? "ready" : "disconnected"}};
}}
}}
'''
        smoke_body = f'''{namespace}::{name} adapter;
    if (!adapter.connect("generated-world") || !adapter.activate()) return 1;
    PocoDDS::Robotics::RobotCommand command;
    if (!adapter.write(command, std::chrono::milliseconds(5))) return 2;
    adapter.read(std::chrono::milliseconds(5));
    const auto health = adapter.health();
    adapter.deactivate();
    return health.ready && health.readCount == 1 && health.writeCount == 1 ? 0 : 3;'''
    else:
        source = f'''#include <PocoDDS/Generated/{name}/{name}.h>

namespace {namespace}
{{
std::string {name}::name() const {{ return "{slug}"; }}
bool {name}::configure(const std::string& description)
{{
    std::lock_guard lock(_mutex); _configured = !description.empty(); return _configured;
}}
bool {name}::activate()
{{
    std::lock_guard lock(_mutex); _active = _configured; return _active;
}}
void {name}::deactivate() noexcept
{{
    std::lock_guard lock(_mutex); _active = false;
}}
void {name}::reset()
{{
    std::lock_guard lock(_mutex); _frame = {{}}; _command = {{}}; _readCount = 0; _writeCount = 0;
}}
PocoDDS::Robotics::RobotFrame {name}::read(std::chrono::nanoseconds)
{{
    std::lock_guard lock(_mutex); ++_readCount; return _frame;
}}
bool {name}::write(const PocoDDS::Robotics::RobotCommand& command, std::chrono::nanoseconds)
{{
    std::lock_guard lock(_mutex);
    if (!_active) return false;
    _command = command; ++_writeCount; return true;
}}
PocoDDS::Robotics::BackendHealth {name}::health() const
{{
    std::lock_guard lock(_mutex);
    return {{_configured, _active, _configured && _active,
             _readCount, _writeCount, _active ? "ready" : "inactive"}};
}}
}}
'''
        smoke_body = f'''{namespace}::{name} adapter;
    if (adapter.kind() != PocoDDS::Robotics::BackendKind::hardware ||
        !adapter.configure("generated-hardware") || !adapter.activate()) return 1;
    PocoDDS::Robotics::RobotCommand command;
    if (!adapter.write(command, std::chrono::milliseconds(5))) return 2;
    adapter.read(std::chrono::milliseconds(5));
    const auto health = adapter.health();
    adapter.deactivate();
    return health.ready && health.readCount == 1 && health.writeCount == 1 ? 0 : 3;'''
    smoke = f'''#include <PocoDDS/Generated/{name}/{name}.h>

#include <chrono>

int main()
{{
    {smoke_body}
}}
'''
    adapter_name = "simulation" if simulation else "hardware"
    readme = f'''# {name} robot {adapter_name} adapter

Generated transport-neutral `{base_class}` implementation. Replace the stub I/O
with the real simulator or device transport, but keep feedback time-bounded and
fail closed before activation. Business modules must depend on the public Backend
contract, never on this concrete adapter type.
'''
    return {
        "CMakeLists.txt": cmake,
        f"include/PocoDDS/Generated/{name}/{name}.h": header,
        f"src/{name}.cpp": source,
        f"tests/{name}Smoke.cpp": smoke,
        "README.md": readme,
    }


def robot_process_templates(name: str) -> dict[str, str]:
    target = "pdr-robot-" + kebab_name(name)
    cmake_target = "pdr_robot_process_" + snake_name(name)
    cmake = f'''cmake_minimum_required(VERSION 3.24)
project({name}RobotProcess LANGUAGES CXX)
find_package(PDRRoboticsRuntime 0.1 CONFIG REQUIRED)
include(CTest)

add_executable({cmake_target} src/main.cpp)
target_link_libraries({cmake_target} PRIVATE PocoDDS::RoboticsRuntime)
set(output "${{CMAKE_BINARY_DIR}}/processes/{target}")
set_target_properties({cmake_target} PROPERTIES
    OUTPUT_NAME "{target}" RUNTIME_OUTPUT_DIRECTORY "${{output}}")
if(CMAKE_CONFIGURATION_TYPES)
  foreach(configuration IN LISTS CMAKE_CONFIGURATION_TYPES)
    string(TOUPPER "${{configuration}}" upper)
    set_target_properties({cmake_target} PROPERTIES RUNTIME_OUTPUT_DIRECTORY_${{upper}} "${{output}}")
  endforeach()
endif()
if(BUILD_TESTING)
  add_test(NAME {target}-self-test COMMAND {cmake_target} --self-test)
endif()
install(TARGETS {cmake_target} RUNTIME DESTINATION bin/processes/{target})
'''
    source = f'''#include <PocoDDS/Robotics/Types.h>

#include <atomic>
#include <chrono>
#include <csignal>
#include <iostream>
#include <string_view>
#include <thread>

namespace {{ std::atomic_bool running{{true}}; void stop(int) {{ running = false; }} }}
int main(int argc, char** argv)
{{
    if (argc == 2 && std::string_view(argv[1]) == "--self-test")
    {{
        PocoDDS::Robotics::RobotFrame frame;
        std::cout << "{target.upper().replace('-', '_')}_SELF_TEST_PASS sensors="
                  << frame.sensors.size() << '\\n';
        return 0;
    }}
    std::signal(SIGINT, stop); std::signal(SIGTERM, stop);
    std::cout << "{target.upper().replace('-', '_')}_READY" << std::endl;
    while (running.load())
    {{
        std::cout << "{target.upper().replace('-', '_')}_HEARTBEAT" << std::endl;
        std::this_thread::sleep_for(std::chrono::seconds(1));
    }}
    std::cout << "{target.upper().replace('-', '_')}_STOPPED" << std::endl;
}}
'''
    readme = f'''# {name} robot process

Independent robotics process template. Use ROS 2 or another public protocol for
communication. It must not access the OSP Service Registry or a robot core object
owned by another process. Add readiness, bounded restart and resource policies
before production deployment.
'''
    return {"CMakeLists.txt": cmake, "src/main.cpp": source, "README.md": readme}


def ros2_node_templates(name: str) -> dict[str, str]:
    package = f"pdr_{snake_name(name)}_ros2"
    node = f"{snake_name(name)}_node"
    cmake = f'''cmake_minimum_required(VERSION 3.16)
project({package})
find_package(ament_cmake REQUIRED)
find_package(ament_cmake_gtest REQUIRED)
find_package(rclcpp REQUIRED)
find_package(PDRRoboticsRuntime REQUIRED)

add_library(${{PROJECT_NAME}}_component src/{name}Node.cpp)
target_include_directories(${{PROJECT_NAME}}_component PUBLIC include)
ament_target_dependencies(${{PROJECT_NAME}}_component rclcpp)
target_link_libraries(${{PROJECT_NAME}}_component PocoDDS::RoboticsRuntime)
add_executable({node} src/main.cpp)
target_link_libraries({node} ${{PROJECT_NAME}}_component)
ament_target_dependencies({node} rclcpp)

ament_add_gtest(${{PROJECT_NAME}}_test test/{name}NodeTest.cpp)
target_link_libraries(${{PROJECT_NAME}}_test ${{PROJECT_NAME}}_component)
ament_target_dependencies(${{PROJECT_NAME}}_test rclcpp)

install(TARGETS ${{PROJECT_NAME}}_component {node} DESTINATION lib/${{PROJECT_NAME}})
install(DIRECTORY include/ DESTINATION include)
install(DIRECTORY config launch DESTINATION share/${{PROJECT_NAME}})
ament_package()
'''
    header = f'''#pragma once
#include <rclcpp/rclcpp.hpp>
namespace PocoDDS::Generated::{name}
{{
class {name}Node final : public rclcpp::Node
{{
public:
    {name}Node();
}};
}}
'''
    source = f'''#include <{package}/{name}Node.h>
namespace PocoDDS::Generated::{name}
{{
{name}Node::{name}Node() : rclcpp::Node("{node}")
{{
    declare_parameter("enabled", true);
}}
}}
'''
    main = f'''#include <{package}/{name}Node.h>
#include <rclcpp/rclcpp.hpp>
int main(int argc, char** argv)
{{
    rclcpp::init(argc, argv);
    rclcpp::spin(std::make_shared<PocoDDS::Generated::{name}::{name}Node>());
    rclcpp::shutdown();
    return 0;
}}
'''
    test = f'''#include <{package}/{name}Node.h>
#include <gtest/gtest.h>
#include <rclcpp/rclcpp.hpp>
TEST({name}Node, StableName)
{{
    if (!rclcpp::ok()) rclcpp::init(0, nullptr);
    auto node = std::make_shared<PocoDDS::Generated::{name}::{name}Node>();
    EXPECT_EQ(node->get_name(), std::string("{node}"));
    rclcpp::shutdown();
}}
'''
    package_xml = f'''<?xml version="1.0"?>
<package format="3">
  <name>{package}</name><version>0.1.0</version>
  <description>Generated PocoDDS robotics ROS 2 adapter.</description>
  <maintainer email="maintainer@example.com">Maintainer</maintainer>
  <license>Proprietary</license>
  <buildtool_depend>ament_cmake</buildtool_depend>
  <depend>rclcpp</depend>
  <exec_depend>ament_index_python</exec_depend>
  <test_depend>ament_cmake_gtest</test_depend>
  <export><build_type>ament_cmake</build_type></export>
</package>
'''
    launch = f'''from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    config = str(Path(get_package_share_directory("{package}")) / "config" / "runtime.yaml")
    return LaunchDescription([Node(package="{package}", executable="{node}",
        name="{node}", parameters=[config])])
'''
    return {
        "CMakeLists.txt": cmake, "package.xml": package_xml,
        f"include/{package}/{name}Node.h": header, f"src/{name}Node.cpp": source,
        "src/main.cpp": main, f"test/{name}NodeTest.cpp": test,
        "config/runtime.yaml": f"{node}:\n  ros__parameters:\n    enabled: true\n",
        f"launch/{snake_name(name)}.launch.py": launch,
        "README.md": f"# {name} ROS 2 node\n\nBuild with `colcon build --packages-select {package}` after sourcing ROS 2 and the installed PDRRoboticsRuntime SDK.\n",
    }


def subprocess_templates(name: str) -> dict[str, str]:
    target = "pdr-" + re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()
    cmake_target = "pdr_generated_subprocess_" + snake_name(name)
    cmake = f'''cmake_minimum_required(VERSION 3.24)
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
    project({name}Subprocess LANGUAGES CXX)
    find_package(PocoDDSRuntime 0.1 CONFIG REQUIRED)
    include(CTest)
endif()

add_executable({cmake_target} src/main.cpp)
target_link_libraries({cmake_target} PRIVATE PocoDDS::SDK Poco::Util)
if(DEFINED PDR_SUBPROCESS_OUTPUT_ROOT)
    set({name}_OUTPUT_ROOT "${{PDR_SUBPROCESS_OUTPUT_ROOT}}")
else()
    set({name}_OUTPUT_ROOT "${{CMAKE_BINARY_DIR}}/processes")
endif()
set_target_properties({cmake_target} PROPERTIES
    OUTPUT_NAME "{target}"
    RUNTIME_OUTPUT_DIRECTORY "${{{name}_OUTPUT_ROOT}}/{target}")
if(CMAKE_CONFIGURATION_TYPES)
    foreach(configuration IN LISTS CMAKE_CONFIGURATION_TYPES)
        string(TOUPPER "${{configuration}}" configuration_upper)
        set_target_properties({cmake_target} PROPERTIES
            RUNTIME_OUTPUT_DIRECTORY_${{configuration_upper}}
                "${{{name}_OUTPUT_ROOT}}/{target}")
    endforeach()
endif()

if(BUILD_TESTING)
    add_test(NAME {target}-self-test COMMAND {cmake_target} --self-test)
endif()

install(TARGETS {cmake_target}
    RUNTIME DESTINATION "bin/processes/{target}")
install(FILES config/pdr-subprocess-entry.properties
    DESTINATION "share/PocoDDSRuntime/subprocesses/{target}")
'''
    source = f'''#include <PocoDDS/SDK/SDK.h>

#include <Poco/Util/ServerApplication.h>

#include <atomic>
#include <chrono>
#include <fstream>
#include <iostream>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

namespace
{{
std::atomic_bool running{{true}};
std::string healthFile;

void writeHealth(std::string_view state)
{{
    if (healthFile.empty()) return;
    const auto now = std::chrono::duration_cast<std::chrono::microseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    std::ofstream output(healthFile, std::ios::trunc);
    output << state << ' ' << now << '\\n';
}}
}}

class GeneratedSubprocess final : public Poco::Util::ServerApplication
{{
  protected:
    int main(const std::vector<std::string>& arguments) override
    {{
        for (const auto& value : arguments)
        {{
            const std::string_view argument(value);
            if (argument == "--self-test")
            {{
                std::cout << "{target.upper().replace('-', '_')}_SELF_TEST_PASS sdk="
                          << PocoDDS::SDK::versionString << '\\n';
                return Application::EXIT_OK;
            }}
            constexpr std::string_view healthPrefix = "--health-file=";
            if (argument.substr(0, healthPrefix.size()) == healthPrefix)
                healthFile = std::string(argument.substr(healthPrefix.size()));
        }}

        running.store(true);
        writeHealth("ready");
        std::cout << "{target.upper().replace('-', '_')}_READY" << std::endl;
        std::thread heartbeat([] {{
            while (running.load())
            {{
                writeHealth("running");
                std::cout << "{target.upper().replace('-', '_')}_HEARTBEAT"
                          << std::endl;
                for (int waited = 0; running.load() && waited < 1000;
                     waited += 25)
                    std::this_thread::sleep_for(std::chrono::milliseconds(25));
            }}
        }});
        waitForTerminationRequest();
        running.store(false);
        heartbeat.join();
        writeHealth("stopped");
        std::cout << "{target.upper().replace('-', '_')}_STOPPED" << std::endl;
        return Application::EXIT_OK;
    }}
}};

POCO_SERVER_MAIN(GeneratedSubprocess)
'''
    configuration = f'''# Merge this block into pdr-subprocesses.properties and replace N with
# the next contiguous numeric slot. Paths are relative to the Runtime bin directory.
subprocess.N.enabled = true
subprocess.N.name = {target}
subprocess.N.location = local
subprocess.N.required = false
subprocess.N.dependency.count = 0
subprocess.N.path = processes/{target}/{target}{'.exe' if os.name == 'nt' else ''}
subprocess.N.workingDirectory = processes/{target}
subprocess.N.restartPolicy = on-failure
subprocess.N.restartMaximumAttempts = 5
subprocess.N.restartInitialBackoffMilliseconds = 250
subprocess.N.restartMaximumBackoffMilliseconds = 30000
subprocess.N.restartBackoffMultiplier = 2.0
subprocess.N.restartResetAfterMilliseconds = 60000
subprocess.N.readinessFile = processes/{target}/pdr-subprocess.heartbeat
subprocess.N.readinessTimeoutMilliseconds = 10000
subprocess.N.heartbeatTimeoutMilliseconds = 5000
subprocess.N.argument.count = 1
subprocess.N.argument.0 = --health-file=pdr-subprocess.heartbeat
'''
    readme = f'''# {name} subprocess

This process is an independent failure boundary. It communicates through public
contracts and must not access the Runtime's in-process OSP Service Registry.

Build and test it against an installed SDK:

```text
pdr verify . --prefix <install-prefix> --config Release --report verify-report.json
```

After installing, merge `config/pdr-subprocess-entry.properties` into the
deployment's `pdr-subprocesses.properties`, replace `N` with the next contiguous
slot, and validate start, heartbeat, graceful stop and crash recovery.
'''
    return {
        "CMakeLists.txt": cmake,
        "src/main.cpp": source,
        "config/pdr-subprocess-entry.properties": configuration,
        "README.md": readme,
    }


def templates(kind: str, name: str) -> dict[str, str]:
    """Render the frozen v1 component scaffold; evolve it in component_template.py."""
    if kind == "robot-module":
        return robot_module_templates(name)
    if kind in ("robot-hardware-adapter", "robot-simulation-adapter"):
        return robot_adapter_templates(name, kind)
    if kind == "robot-process":
        return robot_process_templates(name)
    if kind == "ros2-node":
        return ros2_node_templates(name)
    if kind in ("bundle", "plugin"):
        return plugin_templates(name, kind)
    if kind == "subprocess":
        return subprocess_templates(name)
    namespace = f"PocoDDS::Generated::{name}"
    target_stem = f"pdr_generated_{kind.replace('-', '_')}_{snake_name(name)}"
    common_cmake = f'''cmake_minimum_required(VERSION 3.24)
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
    project({name} LANGUAGES CXX)
    find_package(PocoDDSRuntime 0.1 CONFIG REQUIRED COMPONENTS SDK)
    include(CTest)
endif()

add_library({target_stem} src/{name}.cpp)
set_target_properties({target_stem} PROPERTIES OUTPUT_NAME "{name}")
target_include_directories({target_stem} PUBLIC
    $<BUILD_INTERFACE:${{CMAKE_CURRENT_SOURCE_DIR}}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries({target_stem} PUBLIC PocoDDS::SDK)

install(TARGETS {target_stem}
    ARCHIVE DESTINATION lib
    LIBRARY DESTINATION lib
    RUNTIME DESTINATION bin)
install(DIRECTORY include/ DESTINATION include)

if(BUILD_TESTING)
    add_executable({target_stem}_smoke tests/{name}Smoke.cpp)
    set_target_properties({target_stem}_smoke PROPERTIES OUTPUT_NAME "{name}Smoke")
    target_link_libraries({target_stem}_smoke PRIVATE {target_stem})
    add_test(NAME {kind}-{name.lower()}-smoke COMMAND {target_stem}_smoke)
endif()
'''
    if kind == "workflow":
        header = f'''#pragma once

#include <PocoDDS/Application/Application.h>

namespace {namespace}
{{
class {name} final : public PocoDDS::Application::IWorkflow
{{
public:
    PocoDDS::Application::Result<PocoDDS::Application::WorkflowState>
        start(const PocoDDS::Application::CommandContext& context) override;
    PocoDDS::Application::Result<PocoDDS::Application::WorkflowState>
        handle(const PocoDDS::Application::WorkflowEvent& event) override;
    PocoDDS::Application::Result<PocoDDS::Application::WorkflowState>
        cancel(const PocoDDS::Application::CommandContext& context) override;
    [[nodiscard]] PocoDDS::Application::WorkflowState state() const noexcept override;

private:
    PocoDDS::Application::WorkflowState _state{{PocoDDS::Application::WorkflowState::idle}};
}};
}}
'''
        source = f'''#include <PocoDDS/Generated/{name}/{name}.h>

namespace {namespace}
{{
using PocoDDS::Application::Result;
using PocoDDS::Application::WorkflowState;

Result<WorkflowState> {name}::start(const PocoDDS::Application::CommandContext& context)
{{
    if (context.expired())
        return Result<WorkflowState>::failure({{"deadline_exceeded", "workflow deadline expired", false}});
    _state = WorkflowState::succeeded;
    return Result<WorkflowState>::success(_state);
}}

Result<WorkflowState> {name}::handle(const PocoDDS::Application::WorkflowEvent&)
{{
    return Result<WorkflowState>::success(_state);
}}

Result<WorkflowState> {name}::cancel(const PocoDDS::Application::CommandContext&)
{{
    _state = WorkflowState::cancelled;
    return Result<WorkflowState>::success(_state);
}}

WorkflowState {name}::state() const noexcept {{ return _state; }}
}}
'''
        smoke_body = f'''{namespace}::{name} component;
    PocoDDS::Application::CommandContext context;
    return component.start(context) ? 0 : 1;'''
    elif kind == "device":
        header = f'''#pragma once

#include <PocoDDS/Devices/Device.h>

#include <mutex>
#include <string>

namespace {namespace}
{{
class {name} final : public PocoDDS::Devices::Device,
                     public PocoDDS::Devices::DiagnosticDevice,
                     public PocoDDS::Devices::FailureDiagnosticDevice
{{
public:
    explicit {name}(std::string id);

    const std::string& id() const noexcept override;
    const std::string& type() const noexcept override;
    void start() override;
    void stop() noexcept override;
    PocoDDS::Devices::DeviceSnapshot snapshot() const override;
    std::string execute(const std::string& operation, const std::string& payload) override;
    void setSnapshotHandler(SnapshotHandler handler) override;
    PocoDDS::Devices::DeviceDiagnostics diagnostics() const override;
    PocoDDS::Reliability::Failure failure() const override;

private:
    PocoDDS::Devices::DeviceSnapshot snapshotUnlocked() const;

    std::string _id;
    std::string _type{{"{name}"}};
    mutable std::mutex _mutex;
    PocoDDS::Devices::DeviceState _state{{PocoDDS::Devices::DeviceState::offline}};
    std::uint64_t _sequence{{0}};
    SnapshotHandler _handler;
    PocoDDS::Devices::DeviceDiagnostics _diagnostics;
    PocoDDS::Reliability::Failure _failure;
}};
}}
'''
        source = f'''#include <PocoDDS/Generated/{name}/{name}.h>

#include <chrono>
#include <stdexcept>
#include <utility>

namespace {namespace}
{{
namespace
{{
std::int64_t nowMicroseconds()
{{
    return std::chrono::duration_cast<std::chrono::microseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
}}
}}

{name}::{name}(std::string id) : _id(std::move(id))
{{
    if (_id.empty()) throw std::invalid_argument("device id must not be empty");
}}

const std::string& {name}::id() const noexcept {{ return _id; }}
const std::string& {name}::type() const noexcept {{ return _type; }}

void {name}::start()
{{
    SnapshotHandler handler;
    PocoDDS::Devices::DeviceSnapshot current;
    {{
        std::lock_guard lock(_mutex);
        _state = PocoDDS::Devices::DeviceState::ready;
        ++_sequence;
        current = snapshotUnlocked();
        handler = _handler;
    }}
    if (handler) handler(current);
}}

void {name}::stop() noexcept
{{
    std::lock_guard lock(_mutex);
    _state = PocoDDS::Devices::DeviceState::offline;
}}

PocoDDS::Devices::DeviceSnapshot {name}::snapshot() const
{{
    std::lock_guard lock(_mutex);
    return snapshotUnlocked();
}}

PocoDDS::Devices::DeviceSnapshot {name}::snapshotUnlocked() const
{{
    return {{_id, _type, _state, _sequence, nowMicroseconds(), "{{}}"}};
}}

std::string {name}::execute(const std::string& operation, const std::string& payload)
{{
    SnapshotHandler handler;
    PocoDDS::Devices::DeviceSnapshot current;
    std::string result;
    {{
        std::lock_guard lock(_mutex);
        if (_state != PocoDDS::Devices::DeviceState::ready)
            throw std::runtime_error("device is not ready");
        if (operation != "ping")
            throw std::invalid_argument("unsupported device operation: " + operation);
        result = payload.empty() ? "pong" : payload;
        ++_sequence;
        ++_diagnostics.successfulOperations;
        _diagnostics.consecutiveFailures = 0;
        _diagnostics.lastSuccessMicroseconds = nowMicroseconds();
        PocoDDS::Devices::resolveFailure(_diagnostics, _failure);
        current = snapshotUnlocked();
        handler = _handler;
    }}
    if (handler) handler(current);
    return result;
}}

void {name}::setSnapshotHandler(SnapshotHandler handler)
{{
    std::lock_guard lock(_mutex);
    _handler = std::move(handler);
}}

PocoDDS::Devices::DeviceDiagnostics {name}::diagnostics() const
{{
    std::lock_guard lock(_mutex);
    return _diagnostics;
}}

PocoDDS::Reliability::Failure {name}::failure() const
{{
    std::lock_guard lock(_mutex);
    return _failure;
}}
}}
'''
        smoke_body = f'''{namespace}::{name} device("{name.lower()}-1");
    device.start();
    const auto snapshot = device.snapshot();
    const bool passed = snapshot.id == "{name.lower()}-1" &&
        snapshot.state == PocoDDS::Devices::DeviceState::ready &&
        device.execute("ping", "") == "pong" &&
        device.diagnostics().successfulOperations == 1;
    device.stop();
    return passed ? 0 : 1;'''
    else:
        header = f'''#pragma once

#include <string_view>

namespace {namespace}
{{
class {name}
{{
public:
    [[nodiscard]] std::string_view name() const noexcept;
    [[nodiscard]] bool ready() const noexcept;
}};
}}
'''
        source = f'''#include <PocoDDS/Generated/{name}/{name}.h>

namespace {namespace}
{{
std::string_view {name}::name() const noexcept {{ return "{name}"; }}
bool {name}::ready() const noexcept {{ return true; }}
}}
'''
        smoke_body = f'''{namespace}::{name} component;
    return component.ready() ? 0 : 1;'''
    smoke = f'''#include <PocoDDS/Generated/{name}/{name}.h>

int main()
{{
    {smoke_body}
}}
'''
    device_notes = f'''\n## Runtime configuration

Register the adapter from an OSP bundle and use indexed configuration so multiple
instances can coexist:

```properties
pdr.{name.lower()}.count = 1
pdr.{name.lower()}.0.id = {name.lower()}-1
pdr.{name.lower()}.0.enabled = true
```
''' if kind == "device" else ""
    readme = f'''# {name}

Generated PocoDDSRuntime {kind} module.

## Integration

Add `add_subdirectory(<module-path>)` to the owning product CMake file. The module
uses only the public `PocoDDS::SDK` target and includes a smoke test.

Before integration, verify the module against an installed SDK in an isolated build:

```text
pdr verify . --prefix <install-prefix> --config Release
```

Add `--report verify-report.json` to retain configure, build and CTest evidence.
{device_notes}
'''
    return {
        "CMakeLists.txt": common_cmake,
        f"include/PocoDDS/Generated/{name}/{name}.h": header,
        f"src/{name}.cpp": source,
        f"tests/{name}Smoke.cpp": smoke,
        "README.md": readme,
    }


def locate_project_manifest(output: Path, explicit: str | None) -> Path | None:
    if explicit:
        supplied = Path(explicit).resolve()
        manifest = supplied / "pdr-project.yaml" if supplied.is_dir() else supplied
        if not manifest.is_file():
            raise FileNotFoundError(f"project manifest not found: {manifest}")
        return manifest
    visited: set[Path] = set()
    for start in (output.resolve(), Path.cwd().resolve()):
        for directory in (start, *start.parents):
            if directory in visited:
                continue
            visited.add(directory)
            manifest = directory / "pdr-project.yaml"
            if manifest.is_file():
                return manifest
    return None


def create_module(args: argparse.Namespace) -> int:
    destination = Path(args.output).resolve() / args.name
    project_manager = None
    manifest = None
    if not args.no_register:
        manifest = locate_project_manifest(Path(args.output), args.project)
        if manifest:
            project_manager = load_project_manager()
            project_manager.validate_manifest(manifest, check_paths=True)
            project_manager.normalized_project_path(manifest, destination)
    if destination.exists() and any(destination.iterdir()) and not args.force:
        print(f"error: destination is not empty: {destination}", file=sys.stderr)
        return 2
    destination.mkdir(parents=True, exist_ok=True)
    component_template = load_component_template()
    rendered = component_template.render_component_template(
        args.kind,
        args.name,
        templates,
        component_template.CURRENT_TEMPLATE_VERSION,
    )
    for relative, content in rendered.items():
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and not args.force:
            print(f"error: file already exists: {path}", file=sys.stderr)
            return 2
        path.write_text(content, encoding="utf-8", newline="\n")
    component_template.write_initial_state(
        destination, args.kind, args.name, rendered
    )
    if manifest and project_manager:
        relative = project_manager.register_component_path(
            manifest, args.kind, destination, allow_existing=args.force
        )
        print(f"registered {args.kind}: {relative} in {manifest}")
    print(f"created {args.kind} module: {destination}")
    return 0


def doctor(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else tool_root()
    prefix = Path(args.prefix).resolve() if args.prefix else default_install_prefix(root)
    dependency_prefix = (
        Path(args.dependency_prefix).resolve() if args.dependency_prefix else prefix
    )
    checks: list[dict[str, object]] = []

    def add(identifier: str, passed: bool, detail: str, remedy: str = "") -> None:
        check: dict[str, object] = {"id": identifier, "passed": passed, "detail": detail}
        if remedy and not passed:
            check["remedy"] = remedy
        checks.append(check)

    source_layout = (root / "CMakeLists.txt").is_file() and (root / "application").is_dir()
    installed_layout = (prefix / "lib" / "cmake" / "PocoDDSRuntime").is_dir()
    layout = "source" if source_layout else "installed" if installed_layout else "unknown"
    add(
        "layout", source_layout or installed_layout, f"{layout}: root={root}; prefix={prefix}",
        "pass --root for a source tree or --prefix for an installed PocoDDSRuntime package",
    )
    python_version = ".".join(str(part) for part in sys.version_info[:3])
    add("python", sys.version_info >= (3, 9), python_version, "install Python 3.9 or newer")
    try:
        cmake = executable(args.cmake, "cmake")
        version_result = subprocess.run(
            [cmake, "--version"], text=True, capture_output=True, check=False
        )
        match = re.search(r"cmake version (\d+)\.(\d+)\.(\d+)", version_result.stdout)
        version = tuple(int(part) for part in match.groups()) if match else (0, 0, 0)
        add(
            "cmake", version_result.returncode == 0 and version >= (3, 24, 0),
            f"{cmake} ({'.'.join(map(str, version))})",
            "install CMake 3.24 or newer or pass --cmake",
        )
    except (FileNotFoundError, OSError) as error:
        add("cmake", False, str(error), "install CMake 3.24 or newer or pass --cmake")
    try:
        ctest = executable(args.ctest, "ctest")
        add("ctest", True, ctest)
    except (FileNotFoundError, OSError) as error:
        add("ctest", False, str(error), "install CTest or pass --ctest")

    package_dir = prefix / "lib" / "cmake" / "PocoDDSRuntime"
    config = package_dir / "PocoDDSRuntimeConfig.cmake"
    targets = package_dir / "PocoDDSRuntimeTargets.cmake"
    poco_candidates = (
        dependency_prefix / "cmake" / "PocoConfig.cmake",
        dependency_prefix / "lib" / "cmake" / "Poco" / "PocoConfig.cmake",
        dependency_prefix / "lib64" / "cmake" / "Poco" / "PocoConfig.cmake",
    )
    poco = next((candidate for candidate in poco_candidates if candidate.is_file()),
                poco_candidates[0])
    add(
        "sdk-package", config.is_file(), str(config),
        "install PocoDDSRuntime to the selected --prefix",
    )
    targets_content = targets.read_text(encoding="utf-8", errors="replace") if targets.is_file() else ""
    add(
        "sdk-target", "add_library(PocoDDS::SDK" in targets_content, str(targets),
        "reinstall an SDK package that exports PocoDDS::SDK",
    )
    add(
        "poco-package", poco.is_file(), str(poco),
        "install Poco dependencies or pass --dependency-prefix",
    )

    for check in checks:
        print(f"[{'OK' if check['passed'] else 'FAIL'}] {check['id']}: {check['detail']}")
        if not check["passed"] and "remedy" in check:
            print(f"       fix: {check['remedy']}")
    failed = [str(check["id"]) for check in checks if not check["passed"]]
    report = {
        "schemaVersion": 1,
        "root": str(root),
        "prefix": str(prefix),
        "dependencyPrefix": str(dependency_prefix),
        "passed": not failed,
        "checks": checks,
    }
    if args.report:
        report_path = Path(args.report).resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8", newline="\n")
    if failed:
        print("doctor found missing requirements: " + ", ".join(failed), file=sys.stderr)
        return 1
    return 0


def executable(value: str | None, name: str) -> str:
    if value:
        path = Path(value).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"{name} executable not found: {path}")
        return str(path)
    discovered = shutil.which(name)
    if discovered:
        return discovered
    qt_candidate = Path(f"C:/Qt/Tools/CMake_64/bin/{name}.exe")
    if qt_candidate.is_file():
        return str(qt_candidate)
    raise FileNotFoundError(f"{name} executable not found; pass --{name}")


def run_stage(name: str, command: list[str]) -> dict[str, object]:
    started = datetime.now(timezone.utc)
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    return {
        "name": name,
        "startedAt": started.isoformat(),
        "command": command,
        "exitCode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "passed": completed.returncode == 0,
    }


def verify_module(args: argparse.Namespace) -> int:
    module = Path(args.module).resolve()
    report_path = Path(args.report).resolve() if args.report else None
    report: dict[str, object] = {
        "schemaVersion": 1,
        "module": str(module),
        "configuration": args.config,
        "passed": False,
        "stages": [],
    }
    result = 1
    try:
        if not (module / "CMakeLists.txt").is_file():
            raise FileNotFoundError(f"module CMakeLists.txt not found: {module}")
        component_state = load_component_template().require_current_clean(module, templates)
        if component_state is not None:
            report["componentTemplate"] = {
                "kind": component_state["kind"],
                "name": component_state["name"],
                "version": component_state["appliedVersion"],
            }
        cmake = executable(args.cmake, "cmake")
        ctest = executable(args.ctest, "ctest")
        prefixes = [str(Path(item).resolve()) for item in args.prefix]
        if not prefixes:
            prefixes.append(str(default_install_prefix()))
        with tempfile.TemporaryDirectory(prefix="pdr-verify-") as temporary:
            build = Path(temporary) / "build"
            configure = [cmake, "-S", str(module), "-B", str(build)]
            if args.generator:
                configure.extend(["-G", args.generator])
            if args.platform:
                configure.extend(["-A", args.platform])
            if prefixes:
                configure.append("-DCMAKE_PREFIX_PATH=" + ";".join(prefixes))
            poco_dir = Path(args.poco_dir).resolve() if args.poco_dir else next(
                (Path(prefix) / "cmake" for prefix in prefixes
                 if (Path(prefix) / "cmake" / "PocoConfig.cmake").is_file()),
                None,
            )
            if poco_dir:
                configure.append("-DPoco_DIR=" + str(poco_dir))
                report["pocoDir"] = str(poco_dir)
            commands = [
                ("configure", configure),
                ("build", [cmake, "--build", str(build), "--config", args.config]),
                ("test", [ctest, "--test-dir", str(build), "-C", args.config,
                          "--output-on-failure"]),
            ]
            for stage_name, command in commands:
                stage = run_stage(stage_name, command)
                report["stages"].append(stage)  # type: ignore[union-attr]
                if not stage["passed"]:
                    print(stage["stdout"], end="", file=sys.stderr)
                    print(stage["stderr"], end="", file=sys.stderr)
                    print(f"verify failed during {stage_name}", file=sys.stderr)
                    result = 2
                    break
            else:
                bundle_specs = list(module.glob("*.bndlspec"))
                if bundle_specs:
                    bundles = sorted((build / "bundles").glob("*.bndl"))
                    if not bundles:
                        raise FileNotFoundError("plugin build produced no .bndl artifact")
                    artifacts = []
                    output = Path(args.artifact_output).resolve() if args.artifact_output else None
                    if output:
                        output.mkdir(parents=True, exist_ok=True)
                    for bundle in bundles:
                        entry: dict[str, object] = {
                            "name": bundle.name,
                            "size": bundle.stat().st_size,
                            "sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
                        }
                        if output:
                            destination = output / bundle.name
                            shutil.copy2(bundle, destination)
                            entry["path"] = str(destination)
                        artifacts.append(entry)
                    report["bundleArtifacts"] = artifacts
                report["passed"] = True
                result = 0
                print(f"verified module: {module}")
    except (FileNotFoundError, OSError, ValueError) as error:
        report["error"] = str(error)
        print(f"verify failed: {error}", file=sys.stderr)
        result = 2
    finally:
        report["finishedAt"] = datetime.now(timezone.utc).isoformat()
        if report_path:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8", newline="\n")
    return result


def validate_config(args: argparse.Namespace) -> int:
    prefix = Path(args.prefix).resolve() if args.prefix else default_install_prefix()
    default_name = "pdr-config-check.exe" if sys.platform == "win32" else "pdr-config-check"
    checker = Path(args.executable).resolve() if args.executable else prefix / "bin" / default_name
    configurations = [Path(item).resolve() for item in args.configuration]
    report = {
        "schemaVersion": 1,
        "executable": str(checker),
        "configurationFiles": [str(item) for item in configurations],
        "passed": False,
    }
    result = 2
    if not checker.is_file():
        report["error"] = f"configuration checker not found: {checker}"
        print(f"config validation failed: {report['error']}", file=sys.stderr)
    else:
        completed = subprocess.run(
            [str(checker), *(str(item) for item in configurations)],
            text=True,
            capture_output=True,
            check=False,
        )
        report.update({
            "exitCode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "passed": completed.returncode == 0,
        })
        if completed.stdout:
            print(completed.stdout, end="")
        if completed.stderr:
            print(completed.stderr, end="", file=sys.stderr)
        result = completed.returncode
    if args.report:
        report_path = Path(args.report).resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8", newline="\n")
    return result


def inspect_identity(args: argparse.Namespace) -> int:
    prefix = Path(args.prefix).resolve() if args.prefix else default_install_prefix()
    default_name = "pdr-identity-check.exe" if sys.platform == "win32" else "pdr-identity-check"
    checker = Path(args.executable).resolve() if args.executable else prefix / "bin" / default_name
    configurations = [Path(item).resolve() for item in args.configuration]
    strict = args.identity_command == "check"
    report: dict[str, object] = {
        "schemaVersion": 1,
        "operation": f"identity-{args.identity_command}",
        "executable": str(checker),
        "configurationFiles": [str(item) for item in configurations],
        "passed": False,
    }
    result = 2
    if not checker.is_file():
        report["error"] = f"identity checker not found: {checker}"
    else:
        command = [str(checker)]
        if strict:
            command.append("--strict")
        command.extend(str(item) for item in configurations)
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
        report["exitCode"] = completed.returncode
        try:
            evidence = json.loads(completed.stdout)
            if not isinstance(evidence, dict):
                raise ValueError("identity checker output is not a JSON object")
            report["evidence"] = evidence
            report["passed"] = completed.returncode == 0 and evidence.get("passed") is True
            result = completed.returncode
        except (json.JSONDecodeError, ValueError) as error:
            report["error"] = f"invalid identity checker output: {error}"
        if completed.stderr:
            print(completed.stderr, end="", file=sys.stderr)
    write_json_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_persistence_snapshot(path: Path, kind: str) -> dict[str, object]:
    array_field = PERSISTENCE_KINDS[kind]
    evidence: dict[str, object] = {
        "path": str(path), "kind": kind, "arrayField": array_field,
        "exists": path.is_file(), "valid": False,
    }
    if not path.is_file():
        evidence["error"] = "file not found"
        return evidence
    evidence["fileSha256"] = sha256_file(path)
    evidence["sizeBytes"] = path.stat().st_size
    try:
        root = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(root, dict):
            raise ValueError("snapshot root must be a JSON object")
        schema_version = root.get("schemaVersion")
        if schema_version not in (1, 2):
            raise ValueError(f"unsupported schemaVersion: {schema_version!r}")
        records = root.get(array_field)
        if not isinstance(records, list):
            raise ValueError(f"{array_field} must be a JSON array")
        evidence.update({"schemaVersion": schema_version, "recordCount": len(records)})
        if schema_version == 2:
            expected = root.get("contentSha256")
            if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
                raise ValueError("contentSha256 must be a lowercase SHA-256 digest")
            serialized = json.dumps(
                records, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            actual = hashlib.sha256(serialized).hexdigest()
            evidence.update({"contentSha256": expected, "computedContentSha256": actual})
            if actual != expected:
                raise ValueError("contentSha256 mismatch")
        evidence["valid"] = True
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        evidence["error"] = str(error)
    return evidence


def write_json_report(path_value: str | None, report: dict[str, object]) -> None:
    if not path_value:
        return
    path = Path(path_value).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")


def inspect_persistence(args: argparse.Namespace) -> int:
    current = Path(args.path).resolve()
    report: dict[str, object] = {
        "schemaVersion": 1,
        "operation": "persistence-inspect",
        "inspectedAt": datetime.now(timezone.utc).isoformat(),
        "current": inspect_persistence_snapshot(current, args.kind),
        "previous": inspect_persistence_snapshot(Path(str(current) + ".previous"), args.kind),
    }
    report["recoveryCandidateAvailable"] = bool(report["previous"]["valid"])
    report["passed"] = bool(report["current"]["valid"])
    write_json_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


def recover_persistence(args: argparse.Namespace) -> int:
    current = Path(args.path).resolve()
    previous = Path(str(current) + ".previous")
    before = inspect_persistence_snapshot(current, args.kind)
    source = inspect_persistence_snapshot(previous, args.kind)
    report: dict[str, object] = {
        "schemaVersion": 1,
        "operation": "persistence-recover",
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "kind": args.kind,
        "operator": args.operator,
        "currentBefore": before,
        "source": source,
        "passed": False,
    }
    result = 2
    try:
        if not args.confirm_runtime_stopped:
            raise ValueError("refusing recovery without --confirm-runtime-stopped")
        if before.get("valid") and not args.allow_healthy_current:
            raise ValueError("current snapshot is healthy; use --allow-healthy-current only after review")
        if before.get("fileSha256") != args.expected_current_sha256:
            raise ValueError("current file changed since inspection")
        if not source.get("valid"):
            raise ValueError("previous snapshot is not a valid recovery source")
        if source.get("fileSha256") != args.expected_previous_sha256:
            raise ValueError("previous file changed since inspection")
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        archive = Path(str(current) + f".recovery-{timestamp}.original")
        staged = Path(str(current) + ".recovery.new")
        if staged.exists():
            staged.unlink()
        shutil.copy2(current, archive)
        shutil.copy2(previous, staged)
        staged_evidence = inspect_persistence_snapshot(staged, args.kind)
        if not staged_evidence.get("valid"):
            raise ValueError("staged recovery snapshot failed validation")
        if staged_evidence.get("fileSha256") != source.get("fileSha256"):
            raise ValueError("staged recovery snapshot hash differs from source")
        if sha256_file(current) != args.expected_current_sha256:
            raise ValueError("current file changed while preparing recovery")
        os.replace(staged, current)
        after = inspect_persistence_snapshot(current, args.kind)
        if not after.get("valid") or after.get("fileSha256") != source.get("fileSha256"):
            raise ValueError("recovered current snapshot failed post-replacement verification")
        report.update({"archivePath": str(archive), "currentAfter": after, "passed": True})
        result = 0
    except (OSError, ValueError) as error:
        report["error"] = str(error)
    finally:
        staged_path = Path(str(current) + ".recovery.new")
        if staged_path.exists():
            staged_path.unlink()
        report["finishedAt"] = datetime.now(timezone.utc).isoformat()
        audit = Path(args.audit).resolve() if args.audit else Path(str(current) + ".recovery-audit.jsonl")
        audit.parent.mkdir(parents=True, exist_ok=True)
        with audit.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(report, ensure_ascii=False, separators=(",", ":")) + "\n")
        report["auditPath"] = str(audit)
        write_json_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return result


def safe_recovery_relative(value: object) -> Path:
    if not isinstance(value, str):
        raise ValueError("recovery-point file path must be a string")
    path = Path(value)
    if (path.is_absolute() or "\\" in value or not path.parts or
            any(part in {"", ".", ".."} for part in path.parts)):
        raise ValueError(f"unsafe recovery-point path: {value!r}")
    return path


def verify_recovery_point_path(root: Path) -> dict[str, object]:
    evidence: dict[str, object] = {
        "path": str(root), "valid": False, "files": [],
    }
    try:
        manifest_path = root / "recovery-manifest.json"
        digest_path = root / "recovery-manifest.sha256"
        if not root.is_dir() or not manifest_path.is_file() or not digest_path.is_file():
            raise ValueError("recovery point, manifest or manifest digest is missing")
        expected_manifest_digest = digest_path.read_text(encoding="ascii").strip()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_manifest_digest):
            raise ValueError("invalid recovery-manifest.sha256")
        actual_manifest_digest = sha256_file(manifest_path)
        if actual_manifest_digest != expected_manifest_digest:
            raise ValueError("recovery manifest digest mismatch")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (not isinstance(manifest, dict) or manifest.get("product") != "PocoDDSRuntime" or
                manifest.get("schemaVersion") != 1 or
                manifest.get("type") != "management-recovery-point" or
                manifest.get("consistency") != "runtime-stopped"):
            raise ValueError("unsupported recovery manifest")
        entries = manifest.get("files")
        if not isinstance(entries, list) or not entries:
            raise ValueError("recovery manifest contains no files")
        expected_paths = {"recovery-manifest.json", "recovery-manifest.sha256"}
        roles: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("role"), str):
                raise ValueError("malformed recovery manifest entry")
            role = entry["role"]
            relative = safe_recovery_relative(entry.get("path"))
            normalized = relative.as_posix()
            if role in roles or normalized in expected_paths:
                raise ValueError(f"duplicate recovery manifest entry: {role}/{normalized}")
            roles.add(role)
            expected_paths.add(normalized)
            artifact = (root / relative).resolve()
            try:
                artifact.relative_to(root.resolve())
            except ValueError as error:
                raise ValueError(f"recovery artifact escapes root: {normalized}") from error
            if not artifact.is_file():
                raise ValueError(f"missing recovery artifact: {normalized}")
            if (not isinstance(entry.get("sizeBytes"), int) or
                    not isinstance(entry.get("sha256"), str) or
                    artifact.stat().st_size != entry["sizeBytes"] or
                    sha256_file(artifact) != entry["sha256"]):
                raise ValueError(f"recovery artifact verification failed: {normalized}")
            file_evidence: dict[str, object] = {
                "role": role, "path": normalized, "valid": True,
                "sizeBytes": entry["sizeBytes"], "sha256": entry["sha256"],
            }
            kind = entry.get("persistenceKind")
            if kind is not None:
                if kind not in PERSISTENCE_KINDS:
                    raise ValueError(f"invalid persistence kind for {normalized}")
                snapshot = inspect_persistence_snapshot(artifact, kind)
                if not snapshot.get("valid"):
                    raise ValueError(f"invalid persistence snapshot: {normalized}")
                file_evidence["snapshot"] = snapshot
            evidence["files"].append(file_evidence)
        required_roles = {"configuration", "management-tasks", "management-idempotency",
                          "management-audit"}
        if not required_roles.issubset(roles):
            raise ValueError("recovery manifest is missing a required role")
        actual_paths = {
            path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
        }
        unexpected = sorted(actual_paths - expected_paths)
        missing = sorted(expected_paths - actual_paths)
        if unexpected:
            raise ValueError(f"unexpected recovery artifact: {unexpected[0]}")
        if missing:
            raise ValueError(f"missing recovery artifact: {missing[0]}")
        evidence.update({
            "valid": True,
            "recoveryPointId": manifest.get("recoveryPointId"),
            "createdAt": manifest.get("createdAt"),
            "operator": manifest.get("operator"),
            "manifestSha256": actual_manifest_digest,
        })
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        evidence["error"] = str(error)
    return evidence


def create_recovery_point(args: argparse.Namespace) -> int:
    output = Path(args.output).resolve()
    recovery_id = str(uuid.uuid4())
    created = datetime.now(timezone.utc)
    final_name = created.strftime("%Y%m%dT%H%M%S.%fZ-") + recovery_id
    staging = output / f".{final_name}.new"
    final = output / final_name
    report: dict[str, object] = {
        "schemaVersion": 1, "operation": "persistence-backup",
        "recoveryPointId": recovery_id, "operator": args.operator,
        "startedAt": created.isoformat(), "passed": False,
    }
    try:
        if not args.confirm_runtime_stopped:
            raise ValueError("refusing backup without --confirm-runtime-stopped")
        sources = [
            ("configuration", Path(args.configuration).resolve(), "runtime/pdr-runtime.properties", None),
            ("management-tasks", Path(args.tasks).resolve(),
             "management/management-tasks.json", "tasks"),
            ("management-idempotency", Path(args.idempotency).resolve(),
             "management/management-idempotency.json", "idempotency"),
            ("management-audit", Path(args.management_audit).resolve(),
             "management/management-audit.jsonl", None),
        ]
        rotated_audit = Path(str(Path(args.management_audit).resolve()) + ".1")
        if rotated_audit.is_file():
            sources.append(("management-audit-previous", rotated_audit,
                            "management/management-audit.jsonl.1", None))
        for role, source, _, kind in sources:
            if not source.is_file():
                raise ValueError(f"required recovery source is missing: {role}: {source}")
            if kind and not inspect_persistence_snapshot(source, kind).get("valid"):
                raise ValueError(f"required recovery snapshot is invalid: {role}: {source}")
        output.mkdir(parents=True, exist_ok=True)
        staging.mkdir()
        entries: list[dict[str, object]] = []
        for role, source, relative_name, kind in sources:
            destination = staging / safe_recovery_relative(relative_name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            entry: dict[str, object] = {
                "role": role, "path": relative_name, "sourcePath": str(source),
                "sizeBytes": destination.stat().st_size, "sha256": sha256_file(destination),
            }
            if kind:
                entry["persistenceKind"] = kind
            entries.append(entry)
        manifest = {
            "product": "PocoDDSRuntime", "schemaVersion": 1,
            "type": "management-recovery-point", "recoveryPointId": recovery_id,
            "createdAt": created.isoformat(), "operator": args.operator,
            "consistency": "runtime-stopped", "files": entries,
        }
        manifest_path = staging / "recovery-manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8", newline="\n")
        (staging / "recovery-manifest.sha256").write_text(
            sha256_file(manifest_path) + "\n", encoding="ascii", newline="\n"
        )
        staged_evidence = verify_recovery_point_path(staging)
        if not staged_evidence.get("valid"):
            raise ValueError(f"staged recovery point failed verification: {staged_evidence.get('error')}")
        staging.rename(final)
        final_evidence = verify_recovery_point_path(final)
        if not final_evidence.get("valid"):
            raise ValueError(f"published recovery point failed verification: {final_evidence.get('error')}")
        report.update({"path": str(final), "verification": final_evidence, "passed": True})
        result = 0
    except (OSError, ValueError) as error:
        report["error"] = str(error)
        result = 2
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        report["finishedAt"] = datetime.now(timezone.utc).isoformat()
        write_json_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return result


def verify_recovery_point(args: argparse.Namespace) -> int:
    report: dict[str, object] = {
        "schemaVersion": 1, "operation": "persistence-verify-recovery-point",
        "verifiedAt": datetime.now(timezone.utc).isoformat(),
        "verification": verify_recovery_point_path(Path(args.path).resolve()),
    }
    report["passed"] = bool(report["verification"]["valid"])
    write_json_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


def append_jsonl(path: Path, event: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")


def archive_restore_targets(targets: list[dict[str, object]], output: Path,
                            restore_id: str, operator: str) -> tuple[Path, list[dict[str, object]]]:
    timestamp = datetime.now(timezone.utc)
    name = timestamp.strftime("%Y%m%dT%H%M%S.%fZ-") + restore_id
    staging = output / f".{name}.new"
    final = output / name
    entries: list[dict[str, object]] = []
    try:
        output.mkdir(parents=True, exist_ok=True)
        staging.mkdir()
        for target in targets:
            role = str(target["role"])
            path = Path(target["target"])
            entry: dict[str, object] = {
                "role": role, "targetPath": str(path), "existed": path.is_file(),
            }
            if path.is_file():
                relative = safe_recovery_relative(f"original/{role}")
                archived = staging / relative
                archived.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, archived)
                entry.update({
                    "archivePath": relative.as_posix(), "sizeBytes": archived.stat().st_size,
                    "sha256": sha256_file(archived),
                })
            entries.append(entry)
        manifest = {
            "product": "PocoDDSRuntime", "schemaVersion": 1,
            "type": "pre-restore-evidence", "restoreId": restore_id,
            "createdAt": timestamp.isoformat(), "operator": operator, "files": entries,
        }
        manifest_path = staging / "pre-restore-manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8", newline="\n")
        (staging / "pre-restore-manifest.sha256").write_text(
            sha256_file(manifest_path) + "\n", encoding="ascii", newline="\n"
        )
        for entry in entries:
            if entry["existed"]:
                archived = staging / safe_recovery_relative(entry["archivePath"])
                if (not archived.is_file() or archived.stat().st_size != entry["sizeBytes"] or
                        sha256_file(archived) != entry["sha256"]):
                    raise ValueError(f"pre-restore archive verification failed: {entry['role']}")
        staging.rename(final)
        return final, entries
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def target_matches_archive_state(target: Path, archive_entry: dict[str, object]) -> bool:
    if not archive_entry["existed"]:
        return not target.exists()
    return (target.is_file() and target.stat().st_size == archive_entry["sizeBytes"] and
            sha256_file(target) == archive_entry["sha256"])


def restore_recovery_point(args: argparse.Namespace) -> int:
    recovery_point = Path(args.path).resolve()
    restore_id = str(uuid.uuid4())
    operation_audit = Path(args.operation_audit).resolve()
    report: dict[str, object] = {
        "schemaVersion": 1, "operation": "persistence-restore-recovery-point",
        "restoreId": restore_id, "operator": args.operator,
        "startedAt": datetime.now(timezone.utc).isoformat(), "passed": False,
        "rollbackAttempted": False, "rollbackPassed": None,
    }
    staged_paths: list[Path] = []
    archive_path: Path | None = None
    targets: list[dict[str, object]] = []
    archive_entries: list[dict[str, object]] = []
    mutations_started = False
    operation_audit_started = False
    result = 2
    try:
        if not args.confirm_runtime_stopped:
            raise ValueError("refusing restore without --confirm-runtime-stopped")
        verification = verify_recovery_point_path(recovery_point)
        report["sourceVerification"] = verification
        if not verification.get("valid"):
            raise ValueError(f"invalid recovery point: {verification.get('error')}")
        if verification.get("manifestSha256") != args.expected_manifest_sha256:
            raise ValueError("recovery manifest changed since approval")
        manifest = json.loads((recovery_point / "recovery-manifest.json").read_text(
            encoding="utf-8"))
        source_entries = {entry["role"]: entry for entry in manifest["files"]}
        destination_paths = {
            "configuration": Path(args.configuration).resolve(),
            "management-tasks": Path(args.tasks).resolve(),
            "management-idempotency": Path(args.idempotency).resolve(),
            "management-audit": Path(args.management_audit).resolve(),
        }
        destination_paths["management-audit-previous"] = Path(
            str(destination_paths["management-audit"]) + ".1")
        if len(set(destination_paths.values())) != len(destination_paths):
            raise ValueError("restore destination paths must be distinct")
        if operation_audit in destination_paths.values():
            raise ValueError("operation audit must be outside restored destinations")
        for role, target in destination_paths.items():
            source_entry = source_entries.get(role)
            source = (recovery_point / safe_recovery_relative(source_entry["path"])).resolve() \
                if source_entry else None
            if source is not None and target == source:
                raise ValueError(f"restore source and destination overlap: {role}")
            targets.append({"role": role, "target": target, "source": source,
                            "sourceEntry": source_entry})
        append_jsonl(operation_audit, {
            "timestamp": datetime.now(timezone.utc).isoformat(), "event": "restore-started",
            "restoreId": restore_id, "operator": args.operator,
            "recoveryPointId": verification.get("recoveryPointId"),
            "manifestSha256": verification.get("manifestSha256"),
        })
        operation_audit_started = True
        archive_path, archive_entries = archive_restore_targets(
            targets, Path(args.archive_output).resolve(), restore_id, args.operator
        )
        report["preRestoreArchive"] = str(archive_path)
        archive_by_role = {entry["role"]: entry for entry in archive_entries}
        for target in targets:
            source = target["source"]
            if source is None:
                continue
            destination = Path(target["target"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            staged = Path(str(destination) + f".restore-{restore_id}.new")
            if staged.exists():
                raise ValueError(f"restore staging path already exists: {staged}")
            shutil.copy2(source, staged)
            source_entry = target["sourceEntry"]
            if (staged.stat().st_size != source_entry["sizeBytes"] or
                    sha256_file(staged) != source_entry["sha256"]):
                raise ValueError(f"staged restore verification failed: {target['role']}")
            staged_paths.append(staged)
        if sha256_file(recovery_point / "recovery-manifest.json") != args.expected_manifest_sha256:
            raise ValueError("recovery manifest changed while preparing restore")
        for target in targets:
            if not target_matches_archive_state(
                    Path(target["target"]), archive_by_role[str(target["role"])]):
                raise ValueError(f"restore destination changed while preparing: {target['role']}")
        mutations_started = True
        staged_by_target = {
            str(path).split(f".restore-{restore_id}.new", 1)[0]: path for path in staged_paths
        }
        for target in targets:
            destination = Path(target["target"])
            staged = staged_by_target.get(str(destination))
            if staged is None:
                if destination.exists():
                    destination.unlink()
            else:
                os.replace(staged, destination)
        for target in targets:
            destination = Path(target["target"])
            source_entry = target["sourceEntry"]
            if source_entry is None:
                if destination.exists():
                    raise ValueError(f"restore expected destination to be absent: {target['role']}")
            elif (not destination.is_file() or
                  destination.stat().st_size != source_entry["sizeBytes"] or
                  sha256_file(destination) != source_entry["sha256"]):
                raise ValueError(f"post-restore verification failed: {target['role']}")
        if not inspect_persistence_snapshot(destination_paths["management-tasks"], "tasks").get("valid"):
            raise ValueError("restored task snapshot failed content verification")
        if not inspect_persistence_snapshot(
                destination_paths["management-idempotency"], "idempotency").get("valid"):
            raise ValueError("restored idempotency snapshot failed content verification")
        report.update({
            "passed": True, "transactionMode": "staged-replace-with-rollback",
            "recoveryPointId": verification.get("recoveryPointId"),
            "manifestSha256": verification.get("manifestSha256"),
            "destinations": {role: str(path) for role, path in destination_paths.items()},
        })
        result = 0
    except Exception as error:
        report["error"] = str(error)
        if mutations_started and archive_path is not None:
            report["rollbackAttempted"] = True
            rollback_errors: list[str] = []
            archive_by_role = {entry["role"]: entry for entry in archive_entries}
            for target in targets:
                role = str(target["role"])
                destination = Path(target["target"])
                entry = archive_by_role[role]
                try:
                    if entry["existed"]:
                        rollback_source = archive_path / safe_recovery_relative(entry["archivePath"])
                        rollback_stage = Path(str(destination) + f".rollback-{restore_id}.new")
                        shutil.copy2(rollback_source, rollback_stage)
                        os.replace(rollback_stage, destination)
                    elif destination.exists():
                        destination.unlink()
                    if not target_matches_archive_state(destination, entry):
                        raise ValueError("rollback verification failed")
                except (OSError, ValueError) as rollback_error:
                    rollback_errors.append(f"{role}: {rollback_error}")
            report["rollbackPassed"] = not rollback_errors
            if rollback_errors:
                report["rollbackErrors"] = rollback_errors
                result = 3
    finally:
        for staged in staged_paths:
            if staged.exists():
                staged.unlink()
        report["finishedAt"] = datetime.now(timezone.utc).isoformat()
        if operation_audit_started:
            try:
                append_jsonl(operation_audit, {
                    "timestamp": report["finishedAt"], "event": "restore-finished",
                    "restoreId": restore_id, "operator": args.operator,
                    "passed": report["passed"], "rollbackAttempted": report["rollbackAttempted"],
                    "rollbackPassed": report["rollbackPassed"], "error": report.get("error"),
                    "preRestoreArchive": report.get("preRestoreArchive"),
                })
            except OSError as audit_error:
                report["operationAuditError"] = str(audit_error)
                if result == 0:
                    result = 3
                    report["passed"] = False
        report["operationAudit"] = str(operation_audit)
        write_json_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return result


def fetch_json_endpoint(url: str, headers: dict[str, str], timeout: float) -> dict[str, object]:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        status = error.code
        body = error.read().decode("utf-8", errors="replace")
    try:
        document = json.loads(body)
    except json.JSONDecodeError:
        document = None
    return {"url": url, "status": status, "json": document, "body": body[:1024]}


def validate_restore_transaction_evidence(report_path: Path, audit_path: Path,
                                          expected_restore_id: str) -> dict[str, object]:
    evidence: dict[str, object] = {"valid": False}
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if (not isinstance(report, dict) or
                report.get("operation") != "persistence-restore-recovery-point" or
                report.get("restoreId") != expected_restore_id or not report.get("passed")):
            raise ValueError("restore report is not a successful matching transaction")
        events = []
        for line in audit_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if isinstance(event, dict) and event.get("restoreId") == expected_restore_id:
                events.append(event)
        started = [event for event in events if event.get("event") == "restore-started"]
        finished = [event for event in events if event.get("event") == "restore-finished"]
        if len(started) != 1 or len(finished) != 1 or not finished[0].get("passed"):
            raise ValueError("restore operation audit is incomplete or unsuccessful")
        if started[0].get("manifestSha256") != report.get("manifestSha256"):
            raise ValueError("restore report and operation audit manifest digests differ")
        evidence.update({
            "valid": True, "restoreId": expected_restore_id,
            "recoveryPointId": report.get("recoveryPointId"),
            "manifestSha256": report.get("manifestSha256"),
            "restoreOperator": report.get("operator"),
            "transactionMode": report.get("transactionMode"),
            "reportSha256": sha256_file(report_path), "auditSha256": sha256_file(audit_path),
        })
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        evidence["error"] = str(error)
    return evidence


def validate_interrupted_dispositions(path_value: str | None, restore_id: str,
                                      tasks: list[dict], ledger_count: int) -> dict[str, object]:
    required = bool(tasks or ledger_count)
    evidence: dict[str, object] = {
        "required": required, "valid": not required,
        "taskIds": [str(task.get("id", "")) for task in tasks],
        "idempotencyInterrupted": ledger_count,
    }
    if not required:
        return evidence
    if not path_value:
        evidence["error"] = "interrupted operations require a disposition file"
        return evidence
    path = Path(path_value).resolve()
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(document, dict) or document.get("schemaVersion") != 1 or
                document.get("restoreId") != restore_id or
                not isinstance(document.get("approvedBy"), str) or
                not document["approvedBy"].strip() or
                not isinstance(document.get("approvedAt"), str) or
                not document["approvedAt"].strip() or
                not isinstance(document.get("items"), list)):
            raise ValueError("invalid interrupted disposition document")
        items = document["items"]

        def accepted(item: object) -> bool:
            return (isinstance(item, dict) and
                    item.get("decision") in {"no-retry", "retry-with-new-request-id"} and
                    isinstance(item.get("verifiedState"), str) and
                    bool(item["verifiedState"].strip()) and
                    isinstance(item.get("evidence"), str) and bool(item["evidence"].strip()))

        for task in tasks:
            task_id = str(task.get("id", ""))
            matches = [item for item in items if isinstance(item, dict) and
                       item.get("type") == "management-task" and item.get("id") == task_id]
            if len(matches) != 1 or not accepted(matches[0]):
                raise ValueError(f"missing or invalid disposition for task: {task_id}")
        if ledger_count:
            matches = [item for item in items if isinstance(item, dict) and
                       item.get("type") == "idempotency-ledger" and
                       item.get("id") == "aggregate" and item.get("count") == ledger_count]
            if len(matches) != 1 or not accepted(matches[0]):
                raise ValueError("missing or invalid idempotency interrupted disposition")
        evidence.update({
            "valid": True, "path": str(path), "sha256": sha256_file(path),
            "approvedBy": document["approvedBy"], "approvedAt": document["approvedAt"],
            "itemCount": len(items),
        })
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        evidence["error"] = str(error)
    return evidence


def validate_restored_runtime(args: argparse.Namespace) -> int:
    started = time.monotonic()
    report: dict[str, object] = {
        "schemaVersion": 1, "operation": "persistence-validate-restored-runtime",
        "restoreId": args.expected_restore_id, "operator": args.operator,
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "verdict": "DENIED", "approvedForManagementWrites": False,
    }
    try:
        transaction = validate_restore_transaction_evidence(
            Path(args.restore_report).resolve(), Path(args.operation_audit).resolve(),
            args.expected_restore_id,
        )
        report["restoreTransaction"] = transaction
        if not transaction.get("valid"):
            raise ValueError(f"invalid restore transaction evidence: {transaction.get('error')}")
        parsed = urllib.parse.urlparse(args.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("base URL must be an absolute HTTP(S) URL")
        if (parsed.scheme != "https" and
                parsed.hostname not in {"127.0.0.1", "localhost", "::1"}):
            raise ValueError("plain HTTP is allowed only for loopback validation")
        if args.timeout <= 0 or args.request_timeout <= 0 or args.poll_interval <= 0:
            raise ValueError("timeout, request timeout and poll interval must be positive")
        base_url = args.base_url.rstrip("/")
        headers: dict[str, str] = {"Accept": "application/json"}
        if args.authorization_environment:
            token = os.environ.get(args.authorization_environment, "")
            if not token:
                raise ValueError("authorization environment variable is empty or missing")
            headers["Authorization"] = f"Bearer {token}"
        deadline = time.monotonic() + args.timeout
        attempts = 0
        endpoints: dict[str, dict[str, object]] = {}
        runtime_ready = False
        while time.monotonic() < deadline:
            attempts += 1
            endpoints = {}
            for name, endpoint in {
                "live": "/health/live", "ready": "/health/ready",
                "detail": "/health/detail", "managementTasks": "/api/v1/management-tasks?limit=1000",
            }.items():
                try:
                    endpoints[name] = fetch_json_endpoint(
                        base_url + endpoint, headers, min(args.request_timeout, args.timeout)
                    )
                except (OSError, urllib.error.URLError) as error:
                    endpoints[name] = {"url": base_url + endpoint, "error": str(error)}
            live = endpoints.get("live", {})
            ready = endpoints.get("ready", {})
            detail = endpoints.get("detail", {})
            inventory = endpoints.get("managementTasks", {})
            runtime_ready = (
                live.get("status") == 200 and isinstance(live.get("json"), dict) and
                live["json"].get("live") is True and
                ready.get("status") == 200 and isinstance(ready.get("json"), dict) and
                ready["json"].get("ready") is True and
                detail.get("status") == 200 and isinstance(detail.get("json"), dict) and
                detail["json"].get("ready") is True and detail["json"].get("status") == "UP" and
                inventory.get("status") == 200 and isinstance(inventory.get("json"), dict)
            )
            if runtime_ready:
                break
            time.sleep(min(args.poll_interval, max(0.0, deadline - time.monotonic())))
        report["attempts"] = attempts
        report["endpoints"] = {
            name: {
                "url": endpoint.get("url"), "status": endpoint.get("status"),
                "error": endpoint.get("error"),
                **({"json": endpoint.get("json")} if name != "managementTasks" else {}),
            }
            for name, endpoint in endpoints.items()
        }
        if not runtime_ready:
            report["denialReasons"] = ["RUNTIME_NOT_READY"]
            return_code = 1
        else:
            inventory_document = endpoints["managementTasks"]["json"]
            persistence = inventory_document.get("persistence", {})
            idempotency = inventory_document.get("idempotency", {})
            persistence_healthy = (
                persistence.get("healthy") is True and
                persistence.get("recoveryRequired") is False and
                persistence.get("schemaVersion") == 2 and
                persistence.get("integrityAlgorithm") == "SHA-256"
            )
            idempotency_healthy = (
                idempotency.get("healthy") is True and
                idempotency.get("recoveryRequired") is False and
                idempotency.get("schemaVersion") == 2 and
                idempotency.get("integrityAlgorithm") == "SHA-256"
            )
            interrupted_tasks = [task for task in inventory_document.get("tasks", [])
                                 if isinstance(task, dict) and task.get("state") == "interrupted"]
            interrupted_policy_valid = all(
                isinstance(task.get("id"), str) and bool(task["id"]) and
                task.get("recoveryPolicy") == "verify-before-retry"
                for task in interrupted_tasks
            )
            interrupted_count = idempotency.get("interrupted", 0)
            if not isinstance(interrupted_count, int) or interrupted_count < 0:
                interrupted_count = -1
            dispositions = validate_interrupted_dispositions(
                args.dispositions, args.expected_restore_id, interrupted_tasks, interrupted_count
            )
            report.update({
                "taskPersistenceHealthy": persistence_healthy,
                "idempotencyPersistenceHealthy": idempotency_healthy,
                "interruptedTasks": [{
                    "id": task.get("id"), "operation": task.get("operation"),
                    "target": task.get("target"), "recoveryPolicy": task.get("recoveryPolicy"),
                } for task in interrupted_tasks],
                "idempotencyInterrupted": interrupted_count,
                "interruptedTaskPoliciesValid": interrupted_policy_valid,
                "dispositions": dispositions,
            })
            reasons = []
            if not persistence_healthy:
                reasons.append("TASK_PERSISTENCE_UNHEALTHY")
            if not idempotency_healthy:
                reasons.append("IDEMPOTENCY_PERSISTENCE_UNHEALTHY")
            if interrupted_count < 0:
                reasons.append("IDEMPOTENCY_INTERRUPTED_INVALID")
            if not interrupted_policy_valid:
                reasons.append("INTERRUPTED_TASK_POLICY_INVALID")
            if not dispositions.get("valid"):
                reasons.append("INTERRUPTED_DISPOSITIONS_INCOMPLETE")
            report["denialReasons"] = reasons
            if not reasons:
                report["verdict"] = "APPROVED"
                report["approvedForManagementWrites"] = True
                return_code = 0
            else:
                return_code = 1
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        report["evidenceError"] = str(error)
        report["denialReasons"] = ["VALIDATION_EVIDENCE_INVALID"]
        return_code = 2
    finally:
        report["durationSeconds"] = round(time.monotonic() - started, 3)
        report["finishedAt"] = datetime.now(timezone.utc).isoformat()
        write_json_report(args.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return return_code


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="pdr", description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    schema = commands.add_parser(
        "schema", help="scaffold provider-owned, versioned Runtime schema contracts"
    )
    schema_commands = schema.add_subparsers(dest="schema_command", required=True)
    schema_scaffold = schema_commands.add_parser(
        "scaffold", help="create a JSON Schema contract without editing a central registry"
    )
    schema_scaffold.add_argument("subject")
    schema_scaffold.add_argument("--owner", required=True)
    schema_scaffold.add_argument(
        "--kind", choices=("message", "event", "command", "configuration", "service"),
        default="event",
    )
    schema_scaffold.add_argument("--version", default="1.0.0")
    schema_scaffold.add_argument(
        "--compatibility", choices=("none", "backward", "forward", "full"),
        default="backward",
    )
    schema_scaffold.add_argument("--output", required=True)
    schema_scaffold.add_argument("--force", action="store_true")
    schema_scaffold.set_defaults(handler=scaffold_schema)
    capability = commands.add_parser(
        "capability", help="scaffold and evaluate default-deny Bundle capability policies"
    )
    capability_commands = capability.add_subparsers(
        dest="capability_command", required=True
    )
    capability_scaffold = capability_commands.add_parser(
        "scaffold", help="create a standalone policy without editing a central registry"
    )
    capability_scaffold.add_argument("--rule-id", required=True)
    capability_scaffold.add_argument("--effect", choices=("allow", "deny"), default="allow")
    capability_scaffold.add_argument("--principal", required=True)
    capability_scaffold.add_argument(
        "--resource-kind", choices=tuple(CAPABILITY_ACTIONS), required=True
    )
    capability_scaffold.add_argument("--resource", required=True)
    capability_scaffold.add_argument(
        "--action", choices=tuple(sorted(set().union(*CAPABILITY_ACTIONS.values()))),
        required=True,
    )
    capability_scaffold.add_argument("--output", required=True)
    capability_scaffold.add_argument("--force", action="store_true")
    capability_scaffold.set_defaults(handler=scaffold_capability_policy)
    capability_check = capability_commands.add_parser(
        "check", help="validate a policy or explain one authorization decision"
    )
    capability_check.add_argument("--policy", required=True)
    capability_check.add_argument("--checker")
    capability_check.add_argument("--validate", action="store_true")
    capability_check.add_argument("--principal")
    capability_check.add_argument("--resource-kind", choices=tuple(CAPABILITY_ACTIONS))
    capability_check.add_argument("--resource")
    capability_check.add_argument(
        "--action", choices=tuple(sorted(set().union(*CAPABILITY_ACTIONS.values())))
    )
    capability_check.set_defaults(handler=check_capability)
    capability_store_check = capability_commands.add_parser(
        "store-check", help="initialize or verify the durable SQLite policy store"
    )
    capability_store_check.add_argument("--database", required=True)
    capability_store_check.add_argument("--seed-policy", required=True)
    capability_store_check.add_argument("--checker")
    capability_store_check.set_defaults(handler=check_capability_store)
    capability_store_apply = capability_commands.add_parser(
        "store-apply", help="offline transactional policy replacement; Runtime must be stopped"
    )
    capability_store_apply.add_argument("--database", required=True)
    capability_store_apply.add_argument("--seed-policy", required=True)
    capability_store_apply.add_argument("--candidate-policy", required=True)
    capability_store_apply.add_argument("--actor", required=True)
    capability_store_apply.add_argument("--request-id", required=True)
    capability_store_apply.add_argument("--expected-generation", type=int, required=True)
    capability_store_apply.add_argument("--checker")
    capability_store_apply.set_defaults(handler=apply_capability_store)
    lifecycle = commands.add_parser(
        "lifecycle", help="inspect and back up the durable Bundle maintenance journal"
    )
    lifecycle_commands = lifecycle.add_subparsers(
        dest="lifecycle_command", required=True
    )
    lifecycle_store_check = lifecycle_commands.add_parser(
        "store-check", help="offline integrity check and bounded JSON plan export"
    )
    lifecycle_store_check.add_argument("--database", required=True)
    lifecycle_store_check.add_argument("--limit", type=int, default=256)
    lifecycle_store_check.add_argument("--tool")
    lifecycle_store_check.set_defaults(handler=manage_lifecycle_store)
    lifecycle_store_backup = lifecycle_commands.add_parser(
        "store-backup", help="create a verified consistent SQLite backup; Runtime must be stopped"
    )
    lifecycle_store_backup.add_argument("--database", required=True)
    lifecycle_store_backup.add_argument("--destination", required=True)
    lifecycle_store_backup.add_argument("--tool")
    lifecycle_store_backup.set_defaults(handler=manage_lifecycle_store)
    project = commands.add_parser(
        "project", help="create, validate and resolve a deterministic product project"
    )
    project_commands = project.add_subparsers(dest="project_command", required=True)
    project_create = project_commands.add_parser(
        "create", help="create a standalone product project consuming the installed SDK"
    )
    project_create.add_argument("name", type=valid_name)
    project_create.add_argument("--output", default=".")
    project_create.add_argument(
        "--profile",
        choices=("desktop-lite", "desktop-distributed", "embedded", "edge-industrial",
                 "edge-test", "server", "robotics"),
        default="desktop-lite",
    )
    project_create.add_argument("--runtime-version", default="0.1.x")
    project_create.add_argument("--version", default="0.1.0")
    project_create.add_argument("--force", action="store_true")
    project_create.set_defaults(handler=create_project)
    project_validate = project_commands.add_parser(
        "validate", help="validate project structure and every referenced path"
    )
    project_validate.add_argument("manifest")
    project_validate.add_argument("--skip-path-checks", action="store_true")
    project_validate.add_argument("--report")
    project_validate.set_defaults(handler=validate_project)
    project_resolve = project_commands.add_parser(
        "resolve", help="validate and write a source-hash-bound project lock"
    )
    project_resolve.add_argument("manifest")
    project_resolve.add_argument("--output", required=True)
    project_resolve.set_defaults(handler=resolve_project)
    project_version = project_commands.add_parser(
        "version", help="set the concrete product version and refresh composition binding"
    )
    project_version.add_argument("manifest")
    project_version.add_argument("version")
    project_version.set_defaults(handler=set_project_version)
    project_component_kinds = (*KINDS, "web-bundle")
    project_add = project_commands.add_parser(
        "add", help="register a generated component and refresh manifest-driven CMake"
    )
    project_add.add_argument("manifest")
    project_add.add_argument("kind", choices=project_component_kinds)
    project_add.add_argument("path")
    project_add.set_defaults(handler=add_project_component)
    project_remove = project_commands.add_parser(
        "remove", help="unregister a component without deleting its source directory"
    )
    project_remove.add_argument("manifest")
    project_remove.add_argument("kind", choices=project_component_kinds)
    project_remove.add_argument("path")
    project_remove.set_defaults(handler=remove_project_component)
    project_list = project_commands.add_parser("list", help="list registered components")
    project_list.add_argument("manifest")
    project_list.add_argument("--skip-path-checks", action="store_true")
    project_list.add_argument("--json", action="store_true")
    project_list.set_defaults(handler=list_project_components)
    project_sync = project_commands.add_parser(
        "sync", help="validate the manifest and regenerate deterministic CMake composition"
    )
    project_sync.add_argument("manifest")
    project_sync.add_argument("--output")
    project_sync.set_defaults(handler=sync_project)
    project_impact = project_commands.add_parser(
        "impact",
        help="map changed paths to directly changed and dependency-affected component owners",
    )
    project_impact.add_argument("manifest")
    project_impact.add_argument("paths", nargs="+")
    project_impact.add_argument("--output")
    project_impact.set_defaults(handler=project_change_impact)
    project_config = project_commands.add_parser(
        "config", help="resolve layered, secret-safe and migration-aware product configuration"
    )
    project_config_commands = project_config.add_subparsers(
        dest="project_config_command", required=True
    )
    project_config_resolve = project_config_commands.add_parser(
        "resolve", help="merge configured layers and optionally migrate to a target version"
    )
    project_config_resolve.add_argument("manifest")
    project_config_resolve.add_argument("--output", required=True)
    project_config_resolve.add_argument("--target-version", type=int)
    project_config_resolve.add_argument("--require-environment", action="store_true")
    project_config_resolve.set_defaults(handler=resolve_project_config)
    project_config_plan = project_config_commands.add_parser(
        "plan", help="bind a candidate diff to component owners and update capabilities"
    )
    project_config_plan.add_argument("manifest")
    project_config_plan.add_argument("--current", required=True)
    project_config_plan.add_argument("--candidate", required=True)
    project_config_plan.add_argument("--output", required=True)
    project_config_plan.set_defaults(handler=plan_project_config)
    project_config_preflight = project_config_commands.add_parser(
        "preflight", help="run all affected participants without committing configuration"
    )
    project_config_preflight.add_argument("manifest")
    project_config_preflight.add_argument("--plan", required=True)
    project_config_preflight.add_argument("--current", required=True)
    project_config_preflight.add_argument("--candidate", required=True)
    project_config_preflight.add_argument("--output", required=True)
    project_config_preflight.set_defaults(handler=preflight_project_config)
    project_config_approval_request = project_config_commands.add_parser(
        "approval-request",
        help="bind a short-lived high-risk approval request to an exact configuration plan",
    )
    project_config_approval_request.add_argument("manifest")
    project_config_approval_request.add_argument("--plan", required=True)
    project_config_approval_request.add_argument("--ticket", required=True)
    project_config_approval_request.add_argument("--initiator", required=True)
    project_config_approval_request.add_argument(
        "--expires-in-seconds", type=int, default=1800
    )
    project_config_approval_request.add_argument("--output", required=True)
    project_config_approval_request.set_defaults(handler=request_project_config_approval)
    project_config_approve = project_config_commands.add_parser(
        "approve", help="sign an exact high-risk configuration approval request"
    )
    project_config_approve.add_argument("--request", required=True)
    project_config_approve.add_argument("--approver-id", required=True)
    project_config_approve.add_argument("--key-id", required=True)
    project_config_approve.add_argument(
        "--private-key-path-environment", required=True
    )
    project_config_approve.add_argument("--private-key-passphrase-environment")
    project_config_approve.add_argument("--signature-output", required=True)
    project_config_approve.set_defaults(handler=approve_project_config)
    project_config_apply = project_config_commands.add_parser(
        "apply", help="preflight and transactionally commit a configuration plan"
    )
    project_config_apply.add_argument("manifest")
    project_config_apply.add_argument("--plan", required=True)
    project_config_apply.add_argument("--current", required=True)
    project_config_apply.add_argument("--candidate", required=True)
    project_config_apply.add_argument("--actor", required=True)
    project_config_apply.add_argument("--state-dir", default="build/config-transactions")
    project_config_apply.add_argument("--preflight-evidence")
    project_config_apply.add_argument("--require-approval-policy", action="store_true")
    project_config_apply.add_argument("--approval-request")
    project_config_apply.add_argument("--approval-policy")
    project_config_apply.add_argument("--expected-approval-policy-id")
    project_config_apply.add_argument("--expected-approval-policy-sha256")
    project_config_apply.add_argument("--approval-trusted-keys-directory")
    project_config_apply.add_argument("--approval-signature", action="append", default=[])
    project_config_apply.add_argument("--signature-check-executable")
    project_config_apply.add_argument("--allow-restart", action="store_true")
    project_config_apply.set_defaults(handler=apply_project_config)
    project_config_recover = project_config_commands.add_parser(
        "recover", help="rollback an interrupted configuration transaction from its journal"
    )
    project_config_recover.add_argument("manifest")
    project_config_recover.add_argument("--journal", required=True)
    project_config_recover.add_argument("--actor", required=True)
    project_config_recover.add_argument("--retry-rollback", action="store_true")
    project_config_recover.set_defaults(handler=recover_project_config)
    project_config_status_parser = project_config_commands.add_parser(
        "status",
        help="report lock, recovery and audit readiness for team handoff",
    )
    project_config_status_parser.add_argument("manifest")
    project_config_status_parser.add_argument(
        "--state-dir", default="build/config-transactions"
    )
    project_config_status_parser.add_argument("--check", action="store_true")
    project_config_status_parser.add_argument("--json", action="store_true")
    project_config_status_parser.add_argument("--report")
    project_config_status_parser.set_defaults(handler=project_config_status)
    project_config_verify_audit = project_config_commands.add_parser(
        "verify-audit", help="verify the transaction audit hash chain, head and journals"
    )
    project_config_verify_audit.add_argument(
        "--state-dir", default="build/config-transactions"
    )
    project_config_verify_audit.add_argument("--report")
    project_config_verify_audit.set_defaults(handler=verify_project_config_audit)
    project_config_audit_checkpoint = project_config_commands.add_parser(
        "audit-checkpoint", help="create and sign a portable audit-chain anchor"
    )
    project_config_audit_checkpoint.add_argument(
        "--state-dir", default="build/config-transactions"
    )
    project_config_audit_checkpoint.add_argument("--actor", required=True)
    project_config_audit_checkpoint.add_argument("--checkpoint-id")
    project_config_audit_checkpoint.add_argument("--key-id", required=True)
    project_config_audit_checkpoint.add_argument(
        "--private-key-path-environment", required=True
    )
    project_config_audit_checkpoint.add_argument(
        "--private-key-passphrase-environment"
    )
    project_config_audit_checkpoint.add_argument("--output", required=True)
    project_config_audit_checkpoint.add_argument("--signature-output", required=True)
    project_config_audit_checkpoint.set_defaults(handler=checkpoint_project_config_audit)
    project_config_verify_checkpoint = project_config_commands.add_parser(
        "verify-audit-checkpoint",
        help="verify a signed checkpoint and optionally prove it is in the current chain",
    )
    project_config_verify_checkpoint.add_argument("--checkpoint", required=True)
    project_config_verify_checkpoint.add_argument("--signature", required=True)
    project_config_verify_checkpoint.add_argument("--public-key", required=True)
    project_config_verify_checkpoint.add_argument("--expected-key-id", required=True)
    project_config_verify_checkpoint.add_argument(
        "--expected-public-key-sha256", required=True
    )
    project_config_verify_checkpoint.add_argument(
        "--signature-check-executable", required=True
    )
    project_config_verify_checkpoint.add_argument("--state-dir")
    project_config_verify_checkpoint.add_argument(
        "--expected-min-sequence", type=int, default=1
    )
    project_config_verify_checkpoint.add_argument("--report")
    project_config_verify_checkpoint.set_defaults(
        handler=verify_project_config_audit_checkpoint
    )
    project_template = project_commands.add_parser(
        "template", help="inspect, adopt and transactionally upgrade project scaffolding"
    )
    project_template_commands = project_template.add_subparsers(
        dest="project_template_command", required=True
    )
    project_template_status_parser = project_template_commands.add_parser(
        "status", help="report template version, available updates and managed-file drift"
    )
    project_template_status_parser.add_argument("manifest")
    project_template_status_parser.add_argument("--check", action="store_true")
    project_template_status_parser.add_argument("--json", action="store_true")
    project_template_status_parser.add_argument("--report")
    project_template_status_parser.set_defaults(handler=project_template_status)
    project_template_adopt = project_template_commands.add_parser(
        "adopt", help="safely attach legacy projects to a known template baseline"
    )
    project_template_adopt.add_argument("manifest")
    project_template_adopt.add_argument("--version", type=int, required=True)
    project_template_adopt.add_argument("--report")
    project_template_adopt.set_defaults(handler=adopt_project_template)
    project_template_upgrade = project_template_commands.add_parser(
        "upgrade", help="upgrade clean files and require explicit conflict resolution"
    )
    project_template_upgrade.add_argument("manifest")
    project_template_upgrade.add_argument("--target-version", type=int)
    project_template_upgrade.add_argument("--accept-template", action="append", default=[])
    project_template_upgrade.add_argument("--keep-project", action="append", default=[])
    project_template_upgrade.add_argument("--report")
    project_template_upgrade.set_defaults(handler=upgrade_project_template)
    project_template_recover = project_template_commands.add_parser(
        "recover", help="restore all files from an interrupted template transaction"
    )
    project_template_recover.add_argument("manifest")
    project_template_recover.add_argument("--journal", required=True)
    project_template_recover.add_argument("--retry-rollback", action="store_true")
    project_template_recover.set_defaults(handler=recover_project_template)
    project_pipeline = project_commands.add_parser(
        "pipeline", help="create and run a standard hash-bound project qualification pipeline"
    )
    project_pipeline_commands = project_pipeline.add_subparsers(
        dest="project_pipeline_command", required=True
    )
    project_pipeline_create = project_pipeline_commands.add_parser(
        "create", help="generate the portable automated plan and list external gates"
    )
    project_pipeline_create.add_argument("manifest")
    project_pipeline_create.add_argument("--build-root", default="build/qualification")
    project_pipeline_create.add_argument("--output", default="build/qualification/plan.json")
    project_pipeline_create.add_argument(
        "--sdk-prefix", default=str(default_install_prefix(tool_root()))
    )
    project_pipeline_create.add_argument("--python", default=sys.executable)
    project_pipeline_create.add_argument("--cmake", default="cmake")
    project_pipeline_create.add_argument("--ctest", default="ctest")
    project_pipeline_create.add_argument("--colcon", default="colcon")
    project_pipeline_create.add_argument("--config", default="Release")
    project_pipeline_create.add_argument("--candidate-version")
    project_pipeline_create.add_argument("--jobs", type=int, default=2)
    project_pipeline_create.add_argument("--cmake-argument", action="append", default=[])
    project_pipeline_create.add_argument("--require-environment", action="store_true")
    project_pipeline_create.add_argument("--preflight-timeout", type=int, default=300)
    project_pipeline_create.add_argument("--configure-timeout", type=int, default=900)
    project_pipeline_create.add_argument("--build-timeout", type=int, default=3600)
    project_pipeline_create.add_argument("--test-timeout", type=int, default=3600)
    project_pipeline_create.set_defaults(
        handler=create_project_pipeline, skip_ros2=False
    )
    for command_name, help_text, handler in (
        ("run", "run a new generated project pipeline", run_project_pipeline),
        ("resume", "resume a failed or interrupted project pipeline", resume_project_pipeline),
    ):
        project_pipeline_execute = project_pipeline_commands.add_parser(
            command_name, help=help_text
        )
        project_pipeline_execute.add_argument("--plan", type=Path, required=True)
        project_pipeline_execute.add_argument("--state", type=Path, required=True)
        project_pipeline_execute.add_argument("--confirm-run", action="store_true")
        project_pipeline_execute.set_defaults(handler=handler)
    project_pipeline_state = project_pipeline_commands.add_parser(
        "status", help="show automated results without conflating pending external gates"
    )
    project_pipeline_state.add_argument("--plan", type=Path, required=True)
    project_pipeline_state.add_argument("--state", type=Path, required=True)
    project_pipeline_state.add_argument(
        "--external-evidence", action="append", type=named_qualification_path, default=[]
    )
    project_pipeline_state.add_argument(
        "--external-signature", action="append", type=named_qualification_path, default=[]
    )
    project_pipeline_state.add_argument("--trust-policy", type=Path)
    project_pipeline_state.add_argument("--expected-trust-policy-id")
    project_pipeline_state.add_argument("--expected-trust-policy-sha256")
    project_pipeline_state.add_argument("--signature-check-executable", type=Path)
    project_pipeline_state.set_defaults(handler=project_pipeline_status)
    project_dependency = project_commands.add_parser(
        "dependency", help="manage project-owned third-party dependency declarations"
    )
    project_dependency_commands = project_dependency.add_subparsers(
        dest="project_dependency_command", required=True
    )
    project_dependency_add = project_dependency_commands.add_parser(
        "add", help="add one dependency to the project manifest and SBOM inventory"
    )
    project_dependency_add.add_argument("manifest")
    project_dependency_add.add_argument("name")
    project_dependency_add.add_argument("--version", required=True)
    project_dependency_add.add_argument("--license", required=True)
    project_dependency_add.add_argument("--download", required=True)
    project_dependency_add.add_argument("--scope", choices=("runtime", "build", "test"),
                                        default="runtime")
    project_dependency_add.add_argument("--optional", action="store_true")
    project_dependency_add.set_defaults(handler=add_project_dependency)
    project_dependency_remove = project_dependency_commands.add_parser(
        "remove", help="remove a dependency declaration without touching downloaded files"
    )
    project_dependency_remove.add_argument("manifest")
    project_dependency_remove.add_argument("name")
    project_dependency_remove.set_defaults(handler=remove_project_dependency)
    project_dependency_list = project_dependency_commands.add_parser(
        "list", help="list project dependency declarations"
    )
    project_dependency_list.add_argument("manifest")
    project_dependency_list.add_argument("--skip-path-checks", action="store_true")
    project_dependency_list.add_argument("--json", action="store_true")
    project_dependency_list.set_defaults(handler=list_project_dependencies)
    project_package = project_commands.add_parser(
        "package", help="create and verify deterministic signed product packages"
    )
    project_package_commands = project_package.add_subparsers(
        dest="project_package_command", required=True
    )
    project_package_create = project_package_commands.add_parser(
        "create", help="bind payload, project lock, resolved config, SPDX SBOM and signature"
    )
    project_package_create.add_argument("manifest")
    project_package_create.add_argument("--artifacts", required=True)
    project_package_create.add_argument("--output", required=True)
    project_package_create.add_argument("--version", required=True)
    project_package_create.add_argument("--license", default="NOASSERTION")
    project_package_create.add_argument("--lock")
    project_package_create.add_argument("--refresh-lock", action="store_true")
    project_package_create.add_argument("--target-config-version", type=int)
    project_package_create.add_argument("--require-environment", action="store_true")
    project_package_create.add_argument(
        "--source-date-epoch", type=int,
        default=os.environ.get("SOURCE_DATE_EPOCH", "0"),
    )
    project_package_create.add_argument("--maximum-files", type=int, default=10000)
    project_package_create.add_argument(
        "--maximum-expanded-bytes", type=int, default=4 * 1024 * 1024 * 1024
    )
    project_package_create.add_argument("--signing-key-environment")
    project_package_create.add_argument("--ed25519-private-key-environment")
    project_package_create.add_argument("--private-key-passphrase-environment")
    project_package_create.add_argument("--signing-key-id")
    project_package_create.add_argument("--force", action="store_true")
    project_package_create.set_defaults(handler=create_project_package)
    project_package_verify = project_package_commands.add_parser(
        "verify", help="verify package structure, hashes, SBOM and optional signature in place"
    )
    project_package_verify.add_argument("package")
    project_package_verify.add_argument("--require-signature", action="store_true")
    project_package_verify.add_argument("--trusted-key-environment")
    project_package_verify.add_argument("--expected-key-id")
    project_package_verify.add_argument("--public-key")
    project_package_verify.add_argument("--expected-public-key-sha256")
    project_package_verify.add_argument("--maximum-files", type=int, default=10000)
    project_package_verify.add_argument(
        "--maximum-expanded-bytes", type=int, default=4 * 1024 * 1024 * 1024
    )
    project_package_verify.add_argument("--report")
    project_package_verify.set_defaults(handler=verify_project_package)

    component = commands.add_parser(
        "component", help="inspect, adopt and transactionally upgrade component scaffolding"
    )
    component_commands = component.add_subparsers(dest="component_command", required=True)
    component_status_parser = component_commands.add_parser(
        "status", help="report component template version and managed-file drift"
    )
    component_status_parser.add_argument("component")
    component_status_parser.add_argument("--check", action="store_true")
    component_status_parser.add_argument("--json", action="store_true")
    component_status_parser.add_argument("--report")
    component_status_parser.set_defaults(handler=component_template_status)
    component_adopt = component_commands.add_parser(
        "adopt", help="attach a legacy generated component to a known template baseline"
    )
    component_adopt.add_argument("component")
    component_adopt.add_argument("--kind", choices=KINDS, required=True)
    component_adopt.add_argument("--name", type=valid_name, required=True)
    component_adopt.add_argument("--version", type=int, required=True)
    component_adopt.add_argument("--report")
    component_adopt.set_defaults(handler=adopt_component_template)
    component_upgrade = component_commands.add_parser(
        "upgrade", help="upgrade structural files with explicit conflict decisions"
    )
    component_upgrade.add_argument("component")
    component_upgrade.add_argument("--target-version", type=int)
    component_upgrade.add_argument("--accept-template", action="append", default=[])
    component_upgrade.add_argument("--keep-project", action="append", default=[])
    component_upgrade.add_argument("--report")
    component_upgrade.set_defaults(handler=upgrade_component_template)
    component_recover = component_commands.add_parser(
        "recover", help="restore an interrupted component template transaction"
    )
    component_recover.add_argument("component")
    component_recover.add_argument("--journal", required=True)
    component_recover.add_argument("--retry-rollback", action="store_true")
    component_recover.set_defaults(handler=recover_component_template)

    component_dependency_parser = component_commands.add_parser(
        "dependency", help="manage explicit dependencies in pdr-component.json"
    )
    component_dependency_commands = component_dependency_parser.add_subparsers(
        dest="dependency_operation", required=True
    )
    for operation in ("add", "remove"):
        dependency_command = component_dependency_commands.add_parser(
            operation, help=f"{operation} one declared project-component dependency"
        )
        dependency_command.add_argument("component")
        dependency_command.add_argument("dependency")
        dependency_command.set_defaults(handler=component_dependency)
    dependency_list = component_dependency_commands.add_parser(
        "list", help="list declared project-component dependencies"
    )
    dependency_list.add_argument("component")
    dependency_list.add_argument("--json", action="store_true")
    dependency_list.set_defaults(handler=component_dependency)

    component_contract = component_commands.add_parser(
        "contract-test",
        help="validate service requirements against explicit provider contracts",
    )
    component_contract.add_argument("component")
    component_contract.add_argument("--service-contract", required=True)
    component_contract.add_argument("--provider-contract", action="append", default=[])
    component_contract.add_argument("--report")
    component_contract.set_defaults(handler=component_contract_test)

    component_contract_verify_parser = component_commands.add_parser(
        "contract-verify",
        help="recompute and verify component contract evidence and all bound inputs",
    )
    component_contract_verify_parser.add_argument("verify_report")
    component_contract_verify_parser.set_defaults(handler=component_contract_verify)

    participant_contract = component_commands.add_parser(
        "participant-contract-test",
        help="validate configuration participant ownership against explicit team contracts",
    )
    participant_contract.add_argument("declaration")
    participant_contract.add_argument(
        "--provider-declaration", action="append", default=[]
    )
    participant_contract.add_argument("--baseline")
    participant_contract.add_argument("--report")
    participant_contract.set_defaults(
        handler=configuration_participant_contract_test
    )

    key_lifecycle = component_commands.add_parser(
        "key-lifecycle-test",
        help="validate Bundle-owned key deprecations against project migrations",
    )
    key_lifecycle.add_argument("declaration")
    key_lifecycle.add_argument(
        "--provider-declaration", action="append", default=[]
    )
    key_lifecycle.add_argument(
        "--participant-declaration", action="append", default=[], required=True
    )
    key_lifecycle.add_argument("--migration", action="append", default=[])
    key_lifecycle.add_argument("--runtime-version", required=True)
    key_lifecycle.add_argument("--baseline")
    key_lifecycle.add_argument("--report")
    key_lifecycle.set_defaults(handler=configuration_key_lifecycle_test)

    service_contract = commands.add_parser(
        "service-contract",
        help="validate the production Bundle service dependency graph",
    )
    service_contract_commands = service_contract.add_subparsers(
        dest="service_contract_command", required=True
    )
    service_contract_graph = service_contract_commands.add_parser(
        "graph", help="check all production contracts against the published baseline"
    )
    service_contract_graph.add_argument("--root", type=Path, default=Path("."))
    service_contract_graph.add_argument(
        "--scan-root", type=Path, default=Path("services")
    )
    service_contract_graph.add_argument(
        "--baseline", type=Path,
        default=Path("contracts/service-contract-baseline.json"),
    )
    service_contract_graph.add_argument("--report", type=Path, required=True)
    service_contract_graph.set_defaults(handler=service_contract_graph_check)
    service_contract_verify = service_contract_commands.add_parser(
        "verify", help="recompute and verify service-contract graph evidence"
    )
    service_contract_verify.add_argument("--root", type=Path, default=Path("."))
    service_contract_verify.add_argument(
        "--scan-root", type=Path, default=Path("services")
    )
    service_contract_verify.add_argument(
        "--baseline", type=Path,
        default=Path("contracts/service-contract-baseline.json"),
    )
    service_contract_verify.add_argument("--report", type=Path, required=True)
    service_contract_verify.set_defaults(handler=service_contract_graph_verify)
    service_contract_snapshot = service_contract_commands.add_parser(
        "baseline-snapshot",
        help="snapshot reviewed production contracts for a deliberate baseline update",
    )
    service_contract_snapshot.add_argument("--root", type=Path, default=Path("."))
    service_contract_snapshot.add_argument(
        "--scan-root", type=Path, default=Path("services")
    )
    service_contract_snapshot.add_argument("--output", type=Path, required=True)
    service_contract_snapshot.set_defaults(handler=service_contract_baseline_snapshot)

    team_contract = commands.add_parser(
        "contract-package",
        help="publish, lock and resolve immutable cross-team contract packages",
    )
    team_contract_commands = team_contract.add_subparsers(
        dest="team_contract_command", required=True
    )
    team_contract_pack = team_contract_commands.add_parser(
        "pack", help="create a deterministic content-addressed contract package"
    )
    team_contract_pack.add_argument("--package-id", required=True)
    team_contract_pack.add_argument("--version", required=True)
    team_contract_pack.add_argument("--owner", required=True)
    team_contract_pack.add_argument("--input", action="append", default=[])
    team_contract_pack.add_argument("--output", required=True)
    team_contract_pack.add_argument("--source-date-epoch", type=int, default=0)
    team_contract_pack.add_argument("--ed25519-private-key-environment")
    team_contract_pack.add_argument("--private-key-passphrase-environment")
    team_contract_pack.add_argument("--signing-key-id")
    team_contract_pack.add_argument("--maximum-files", type=int, default=64)
    team_contract_pack.add_argument(
        "--maximum-expanded-bytes", type=int, default=16 * 1024 * 1024
    )
    team_contract_pack.add_argument("--force", action="store_true")
    team_contract_pack.set_defaults(handler=pack_team_contract_package)

    team_contract_verify = team_contract_commands.add_parser(
        "verify", help="verify package identity, entry set and every digest"
    )
    team_contract_verify.add_argument("package")
    team_contract_verify.add_argument("--maximum-files", type=int, default=64)
    team_contract_verify.add_argument(
        "--maximum-expanded-bytes", type=int, default=16 * 1024 * 1024
    )
    team_contract_verify.add_argument("--report")
    team_contract_verify.add_argument("--require-signature", action="store_true")
    team_contract_verify.add_argument("--trust-policy")
    team_contract_verify.add_argument("--expected-trust-policy-id")
    team_contract_verify.add_argument("--expected-trust-policy-sha256")
    team_contract_verify.add_argument("--verification-time")
    team_contract_verify.set_defaults(handler=verify_team_contract_package)

    team_contract_lock = team_contract_commands.add_parser(
        "lock", help="write a path-independent lock for exact package identities"
    )
    team_contract_lock.add_argument("--package", action="append", default=[])
    team_contract_lock.add_argument("--output", required=True)
    team_contract_lock.add_argument("--maximum-files", type=int, default=64)
    team_contract_lock.add_argument(
        "--maximum-expanded-bytes", type=int, default=16 * 1024 * 1024
    )
    team_contract_lock.add_argument("--force", action="store_true")
    team_contract_lock.add_argument("--require-signature", action="store_true")
    team_contract_lock.add_argument("--trust-policy")
    team_contract_lock.add_argument("--expected-trust-policy-id")
    team_contract_lock.add_argument("--expected-trust-policy-sha256")
    team_contract_lock.add_argument("--verification-time")
    team_contract_lock.set_defaults(handler=lock_team_contract_packages)

    team_contract_resolve = team_contract_commands.add_parser(
        "resolve", help="verify a lock and expose stable paths for existing contract tests"
    )
    team_contract_resolve.add_argument("--lock", required=True)
    team_contract_resolve.add_argument("--package", action="append", default=[])
    team_contract_resolve.add_argument("--output", required=True)
    team_contract_resolve.add_argument("--report")
    team_contract_resolve.add_argument("--require-signature", action="store_true")
    team_contract_resolve.add_argument("--trust-policy")
    team_contract_resolve.add_argument("--expected-trust-policy-id")
    team_contract_resolve.add_argument("--expected-trust-policy-sha256")
    team_contract_resolve.add_argument("--verification-time")
    team_contract_resolve.add_argument("--maximum-files", type=int, default=64)
    team_contract_resolve.add_argument(
        "--maximum-expanded-bytes", type=int, default=16 * 1024 * 1024
    )
    team_contract_resolve.set_defaults(handler=resolve_team_contract_packages)

    team_contract_impact = team_contract_commands.add_parser(
        "impact", help="preview a signed lock upgrade and route affected consumer tests"
    )
    team_contract_impact.add_argument("--current-lock", required=True)
    team_contract_impact.add_argument("--current-package", action="append", default=[])
    team_contract_impact.add_argument("--candidate-lock", required=True)
    team_contract_impact.add_argument("--candidate-package", action="append", default=[])
    team_contract_impact.add_argument("--consumer-catalog", required=True)
    team_contract_impact.add_argument("--require-signature", action="store_true")
    for side in ("current", "candidate"):
        team_contract_impact.add_argument(f"--{side}-trust-policy")
        team_contract_impact.add_argument(f"--{side}-expected-trust-policy-id")
        team_contract_impact.add_argument(f"--{side}-expected-trust-policy-sha256")
    team_contract_impact.add_argument("--verification-time")
    team_contract_impact.add_argument("--report", required=True)
    team_contract_impact.set_defaults(handler=analyze_team_contract_impact)

    team_contract_execute = team_contract_commands.add_parser(
        "impact-execute",
        help="execute the exact CTest labels selected by a compatible impact report",
    )
    team_contract_execute.add_argument("--report", required=True)
    team_contract_execute.add_argument("--ctest", required=True)
    team_contract_execute.add_argument("--test-dir", required=True)
    team_contract_execute.add_argument("--config", default="Release")
    team_contract_execute.add_argument("--evidence", required=True)
    team_contract_execute.add_argument("--junit", required=True)
    team_contract_execute.set_defaults(handler=execute_team_contract_impact)

    team_contract_approve = team_contract_commands.add_parser(
        "impact-approve", help="sign one short-lived affected Consumer Owner approval"
    )
    team_contract_approve.add_argument("--report", required=True)
    team_contract_approve.add_argument("--owner", required=True)
    team_contract_approve.add_argument("--approver-id", required=True)
    team_contract_approve.add_argument("--key-id", required=True)
    team_contract_approve.add_argument("--private-key-environment", required=True)
    team_contract_approve.add_argument("--private-key-passphrase-environment")
    team_contract_approve.add_argument("--issued-at")
    team_contract_approve.add_argument("--lifetime-seconds", type=int, default=3600)
    team_contract_approve.add_argument("--output", required=True)
    team_contract_approve.set_defaults(handler=approve_team_contract_impact)

    team_contract_gate = team_contract_commands.add_parser(
        "impact-gate", help="bind execution evidence and every affected Owner approval"
    )
    team_contract_gate.add_argument("--report", required=True)
    team_contract_gate.add_argument("--evidence", required=True)
    team_contract_gate.add_argument("--junit", required=True)
    team_contract_gate.add_argument("--ctest")
    team_contract_gate.add_argument("--test-dir")
    team_contract_gate.add_argument("--config", default="Release")
    team_contract_gate.add_argument("--approval-policy")
    team_contract_gate.add_argument("--expected-approval-policy-id")
    team_contract_gate.add_argument("--expected-approval-policy-sha256")
    team_contract_gate.add_argument("--approval", action="append", default=[])
    team_contract_gate.add_argument("--runner-attestation")
    team_contract_gate.add_argument("--runner-trust-policy")
    team_contract_gate.add_argument("--expected-runner-trust-policy-id")
    team_contract_gate.add_argument("--expected-runner-trust-policy-sha256")
    team_contract_gate.add_argument("--verification-time")
    team_contract_gate.add_argument("--gate-report", required=True)
    team_contract_gate.set_defaults(handler=gate_team_contract_impact)

    registry_init = team_contract_commands.add_parser(
        "registry-init", help="initialize a pinned immutable contract Registry"
    )
    registry_init.add_argument("--registry", required=True)
    registry_init.add_argument("--registry-id", required=True)
    registry_init.add_argument("--channel", action="append", default=[])
    registry_init.add_argument("--actor", required=True)
    registry_init.add_argument("--occurred-at")
    registry_init.add_argument("--report")
    add_team_contract_registry_trust_arguments(registry_init)
    registry_init.set_defaults(handler=init_team_contract_registry)

    registry_publish = team_contract_commands.add_parser(
        "registry-publish", help="publish a trusted immutable package blob"
    )
    registry_publish.add_argument("--registry", required=True)
    registry_publish.add_argument("--package", required=True)
    registry_publish.add_argument("--expected-revision", type=int)
    registry_publish.add_argument("--actor", required=True)
    registry_publish.add_argument("--occurred-at")
    registry_publish.add_argument("--report")
    add_team_contract_registry_trust_arguments(registry_publish)
    add_team_contract_registry_limits(registry_publish)
    registry_publish.set_defaults(handler=publish_team_contract_registry)

    registry_promote = team_contract_commands.add_parser(
        "registry-promote", help="promote one exact lock through ordered channels"
    )
    registry_promote.add_argument("--registry", required=True)
    registry_promote.add_argument("--channel", required=True)
    registry_promote.add_argument("--lock", required=True)
    registry_promote.add_argument("--expected-generation", type=int, required=True)
    registry_promote.add_argument("--expected-revision", type=int)
    registry_promote.add_argument("--impact-gate")
    registry_promote.add_argument("--runner-attestation")
    registry_promote.add_argument("--runner-trust-policy")
    registry_promote.add_argument("--expected-runner-trust-policy-id")
    registry_promote.add_argument("--expected-runner-trust-policy-sha256")
    registry_promote.add_argument("--gate-authorization")
    registry_promote.add_argument("--gate-authorization-policy")
    registry_promote.add_argument("--expected-gate-authorization-policy-id")
    registry_promote.add_argument("--expected-gate-authorization-policy-sha256")
    registry_promote.add_argument("--actor", required=True)
    registry_promote.add_argument("--occurred-at")
    registry_promote.add_argument("--report")
    add_team_contract_registry_trust_arguments(registry_promote)
    add_team_contract_registry_limits(registry_promote)
    registry_promote.set_defaults(handler=promote_team_contract_registry)

    registry_rollback = team_contract_commands.add_parser(
        "registry-rollback", help="restore an earlier immutable channel generation"
    )
    registry_rollback.add_argument("--registry", required=True)
    registry_rollback.add_argument("--channel", required=True)
    registry_rollback.add_argument("--expected-generation", type=int, required=True)
    registry_rollback.add_argument("--expected-revision", type=int)
    registry_rollback.add_argument("--to-generation", type=int, required=True)
    registry_rollback.add_argument("--actor", required=True)
    registry_rollback.add_argument("--reason", required=True)
    registry_rollback.add_argument("--occurred-at")
    registry_rollback.add_argument("--report")
    add_team_contract_registry_trust_arguments(registry_rollback)
    add_team_contract_registry_limits(registry_rollback)
    registry_rollback.set_defaults(handler=rollback_team_contract_registry)

    registry_resolve = team_contract_commands.add_parser(
        "registry-resolve", help="resolve a promoted channel without package paths"
    )
    registry_resolve.add_argument("--registry", required=True)
    registry_resolve.add_argument("--channel", required=True)
    registry_resolve.add_argument("--output", required=True)
    registry_resolve.add_argument("--package-report")
    registry_resolve.add_argument("--report", required=True)
    add_team_contract_registry_trust_arguments(registry_resolve)
    add_team_contract_registry_limits(registry_resolve)
    registry_resolve.set_defaults(handler=resolve_team_contract_registry)

    registry_verify = team_contract_commands.add_parser(
        "registry-verify", help="verify Registry history, blobs, locks and signatures"
    )
    registry_verify.add_argument("--registry", required=True)
    registry_verify.add_argument("--report")
    add_team_contract_registry_trust_arguments(registry_verify)
    add_team_contract_registry_limits(registry_verify)
    registry_verify.set_defaults(handler=verify_team_contract_registry)

    registry_lease_status = team_contract_commands.add_parser(
        "registry-lease-status", help="inspect the OS-owned Registry writer lease"
    )
    registry_lease_status.add_argument("--registry", required=True)
    registry_lease_status.add_argument("--report")
    registry_lease_status.set_defaults(handler=inspect_team_contract_registry_lease)

    remote_serve = team_contract_commands.add_parser(
        "registry-remote-serve", help="serve one Registry with scoped remote RBAC"
    )
    remote_serve.add_argument("--registry", required=True)
    remote_serve.add_argument("--bind", default="127.0.0.1")
    remote_serve.add_argument("--port", type=int, default=9443)
    remote_serve.add_argument("--tls-certificate")
    remote_serve.add_argument("--tls-private-key")
    remote_serve.add_argument("--allow-insecure-loopback", action="store_true")
    remote_serve.add_argument("--control-directory")
    remote_serve.add_argument("--audit-archive-directory")
    remote_serve.add_argument("--access-policy", required=True)
    remote_serve.add_argument("--expected-access-policy-id", required=True)
    remote_serve.add_argument("--expected-access-policy-sha256", required=True)
    remote_serve.add_argument("--access-policy-trust-policy")
    remote_serve.add_argument("--expected-access-policy-trust-policy-id")
    remote_serve.add_argument("--expected-access-policy-trust-policy-sha256")
    remote_serve.add_argument("--trust-policy", required=True)
    remote_serve.add_argument("--expected-trust-policy-id", required=True)
    remote_serve.add_argument("--expected-trust-policy-sha256", required=True)
    remote_serve.add_argument("--runner-trust-policy")
    remote_serve.add_argument("--expected-runner-trust-policy-id")
    remote_serve.add_argument("--expected-runner-trust-policy-sha256")
    remote_serve.add_argument("--gate-authorization-policy")
    remote_serve.add_argument("--expected-gate-authorization-policy-id")
    remote_serve.add_argument("--expected-gate-authorization-policy-sha256")
    remote_serve.add_argument("--verification-time")
    remote_serve.add_argument("--maximum-files", type=int, default=64)
    remote_serve.add_argument("--maximum-expanded-bytes", type=int,
                              default=16 * 1024 * 1024)
    remote_serve.add_argument("--node-id")
    remote_serve.add_argument("--handoff-evidence-directory")
    remote_serve.add_argument("--handoff-key-id")
    remote_serve.add_argument("--handoff-private-key-environment")
    remote_serve.add_argument("--handoff-private-key-passphrase-environment")
    remote_serve.add_argument("--handoff-leader-verification-time")
    remote_serve.add_argument("--quiet", action="store_true")
    remote_serve.set_defaults(handler=serve_team_contract_registry_remote)

    remote_publish = team_contract_commands.add_parser(
        "registry-remote-publish", help="upload a signed package without server paths"
    )
    remote_publish.add_argument("--package", required=True)
    remote_publish.set_defaults(remote_operation="publish")
    add_team_contract_registry_remote_client_arguments(remote_publish, mutation=True)

    remote_promote = team_contract_commands.add_parser(
        "registry-remote-promote", help="upload and promote a lock with Gate evidence"
    )
    remote_promote.add_argument("--channel", required=True)
    remote_promote.add_argument("--lock", required=True)
    remote_promote.add_argument("--expected-generation", type=int, required=True)
    remote_promote.add_argument("--impact-gate")
    remote_promote.add_argument("--runner-attestation")
    remote_promote.add_argument("--gate-authorization")
    remote_promote.set_defaults(remote_operation="promote")
    add_team_contract_registry_remote_client_arguments(remote_promote, mutation=True)

    remote_rollback = team_contract_commands.add_parser(
        "registry-remote-rollback", help="create a remote rollback generation"
    )
    remote_rollback.add_argument("--channel", required=True)
    remote_rollback.add_argument("--expected-generation", type=int, required=True)
    remote_rollback.add_argument("--to-generation", type=int, required=True)
    remote_rollback.add_argument("--reason", required=True)
    remote_rollback.set_defaults(remote_operation="rollback")
    add_team_contract_registry_remote_client_arguments(remote_rollback, mutation=True)

    remote_verify = team_contract_commands.add_parser(
        "registry-remote-verify", help="verify Registry history through the remote service"
    )
    remote_verify.set_defaults(remote_operation="verify")
    add_team_contract_registry_remote_client_arguments(remote_verify)

    remote_resolve = team_contract_commands.add_parser(
        "registry-remote-resolve", help="download a channel without server paths"
    )
    remote_resolve.add_argument("--channel", required=True)
    remote_resolve.add_argument("--output", required=True)
    remote_resolve.set_defaults(remote_operation="resolve")
    add_team_contract_registry_remote_client_arguments(remote_resolve)

    remote_status = team_contract_commands.add_parser(
        "registry-remote-status", help="query one durable remote request disposition"
    )
    remote_status.add_argument("--request-id", required=True)
    remote_status.set_defaults(remote_operation="status")
    add_team_contract_registry_remote_query_arguments(remote_status)

    remote_audit = team_contract_commands.add_parser(
        "registry-remote-audit-verify",
        help="verify the immutable remote request audit chain",
    )
    remote_audit.set_defaults(remote_operation="audit-verify")
    add_team_contract_registry_remote_query_arguments(remote_audit)

    remote_archive_status = team_contract_commands.add_parser(
        "registry-remote-audit-archive-status",
        help="show registered remote audit archive continuity",
    )
    remote_archive_status.set_defaults(remote_operation="audit-archive-status")
    add_team_contract_registry_remote_query_arguments(remote_archive_status)

    remote_capacity = team_contract_commands.add_parser(
        "registry-remote-capacity",
        help="show bounded remote control-state usage and limits",
    )
    remote_capacity.set_defaults(remote_operation="capacity")
    add_team_contract_registry_remote_query_arguments(remote_capacity)

    def add_remote_drain_client_arguments(command: argparse.ArgumentParser) -> None:
        command.add_argument("--handoff-id", required=True)
        command.add_argument("--expected-generation", type=int, required=True)
        command.add_argument("--expected-revision", type=int, required=True)
        command.add_argument("--expected-state-sha256", required=True)
        add_team_contract_registry_remote_query_arguments(command)

    remote_drain_start = team_contract_commands.add_parser(
        "registry-remote-drain-start",
        help="close remote command admission through operator RBAC",
    )
    add_remote_drain_client_arguments(remote_drain_start)
    remote_drain_start.add_argument("--reason", required=True)
    remote_drain_start.set_defaults(
        remote_operation="drain-start", remote_drain_operation="start",
        issued_at=None, expires_at=None, evidence_output=None,
    )

    remote_drain_finalize = team_contract_commands.add_parser(
        "registry-remote-drain-finalize",
        help="request signed zero-inflight handoff evidence",
    )
    add_remote_drain_client_arguments(remote_drain_finalize)
    remote_drain_finalize.add_argument("--issued-at", required=True)
    remote_drain_finalize.add_argument("--expires-at", required=True)
    remote_drain_finalize.add_argument("--evidence-output", required=True)
    remote_drain_finalize.set_defaults(
        remote_operation="drain-finalize", remote_drain_operation="finalize",
        reason=None,
    )

    remote_drain_resume = team_contract_commands.add_parser(
        "registry-remote-drain-resume",
        help="reopen admission only while the old node remains Leader",
    )
    add_remote_drain_client_arguments(remote_drain_resume)
    remote_drain_resume.add_argument("--reason", required=True)
    remote_drain_resume.set_defaults(
        remote_operation="drain-resume", remote_drain_operation="resume",
        issued_at=None, expires_at=None, evidence_output=None,
    )

    remote_drain_status = team_contract_commands.add_parser(
        "registry-remote-drain-status", help="inspect drain state through RBAC"
    )
    remote_drain_status.set_defaults(remote_operation="drain-status")
    add_team_contract_registry_remote_query_arguments(remote_drain_status)

    remote_leases = team_contract_commands.add_parser(
        "registry-remote-lease-status",
        help="inspect remote command and Registry writer leases",
    )
    remote_leases.set_defaults(remote_operation="lease-status")
    add_team_contract_registry_remote_query_arguments(remote_leases)

    remote_recover = team_contract_commands.add_parser(
        "registry-remote-recover",
        help="explicitly terminate one interrupted remote request",
    )
    remote_recover.add_argument("--recovery-id", required=True)
    remote_recover.add_argument("--target-request-id", required=True)
    remote_recover.add_argument("--target-request-sha256", required=True)
    remote_recover.add_argument("--expected-started-revision", type=int, required=True)
    remote_recover.add_argument("--expected-current-revision", type=int, required=True)
    remote_recover.add_argument(
        "--disposition", choices=("aborted", "uncertain"), required=True
    )
    remote_recover.add_argument("--reason", required=True)
    remote_recover.set_defaults(remote_operation="recover")
    add_team_contract_registry_remote_query_arguments(remote_recover)

    remote_audit_checkpoint = team_contract_commands.add_parser(
        "registry-remote-audit-checkpoint",
        help="sign an externally stored remote request audit checkpoint",
    )
    remote_audit_checkpoint.add_argument("--control-directory", required=True)
    remote_audit_checkpoint.add_argument("--audit-archive-directory")
    remote_audit_checkpoint.add_argument("--registry-id", required=True)
    remote_audit_checkpoint.add_argument("--checkpoint-id", required=True)
    remote_audit_checkpoint.add_argument("--auditor-id", required=True)
    remote_audit_checkpoint.add_argument("--key-id", required=True)
    remote_audit_checkpoint.add_argument("--private-key-environment", required=True)
    remote_audit_checkpoint.add_argument("--private-key-passphrase-environment")
    remote_audit_checkpoint.add_argument("--issued-at")
    remote_audit_checkpoint.add_argument("--output", required=True)
    remote_audit_checkpoint.set_defaults(
        handler=checkpoint_team_contract_registry_remote_audit
    )

    remote_audit_checkpoint_verify = team_contract_commands.add_parser(
        "registry-remote-audit-checkpoint-verify",
        help="verify external checkpoint signature and audit-chain continuity",
    )
    remote_audit_checkpoint_verify.add_argument("--control-directory", required=True)
    remote_audit_checkpoint_verify.add_argument("--audit-archive-directory")
    remote_audit_checkpoint_verify.add_argument("--registry-id", required=True)
    remote_audit_checkpoint_verify.add_argument("--checkpoint", required=True)
    remote_audit_checkpoint_verify.add_argument("--audit-policy", required=True)
    remote_audit_checkpoint_verify.add_argument(
        "--expected-audit-policy-id", required=True
    )
    remote_audit_checkpoint_verify.add_argument(
        "--expected-audit-policy-sha256", required=True
    )
    remote_audit_checkpoint_verify.add_argument("--verification-time")
    remote_audit_checkpoint_verify.add_argument("--report")
    remote_audit_checkpoint_verify.set_defaults(
        handler=verify_team_contract_registry_remote_audit_checkpoint
    )

    def add_remote_audit_archive_common(command: argparse.ArgumentParser) -> None:
        command.add_argument("--control-directory", required=True)
        command.add_argument("--audit-archive-directory",
                             dest="archive_directory", required=True)
        command.add_argument("--registry-id", required=True)
        command.add_argument("--report")
        command.set_defaults(handler=manage_team_contract_registry_remote_audit_archive)

    def add_remote_audit_archive_trust(command: argparse.ArgumentParser) -> None:
        command.add_argument("--audit-policy", required=True)
        command.add_argument("--expected-audit-policy-id", required=True)
        command.add_argument("--expected-audit-policy-sha256", required=True)
        command.add_argument("--verification-time")

    remote_archive_create = team_contract_commands.add_parser(
        "registry-remote-audit-archive-create",
        help="create and register a signed-checkpoint-bound audit segment",
    )
    add_remote_audit_archive_common(remote_archive_create)
    add_remote_audit_archive_trust(remote_archive_create)
    remote_archive_create.add_argument("--archive-id", required=True)
    remote_archive_create.add_argument("--checkpoint", required=True)
    remote_archive_create.add_argument("--through-sequence", type=int)
    remote_archive_create.add_argument("--created-at")
    remote_archive_create.add_argument("--output", required=True)
    remote_archive_create.set_defaults(archive_operation="create")

    remote_archive_verify = team_contract_commands.add_parser(
        "registry-remote-audit-archive-verify",
        help="verify archive bytes, marker chain and checkpoint signatures",
    )
    add_remote_audit_archive_common(remote_archive_verify)
    add_remote_audit_archive_trust(remote_archive_verify)
    remote_archive_verify.set_defaults(archive_operation="verify")

    remote_archive_prune = team_contract_commands.add_parser(
        "registry-remote-audit-archive-prune",
        help="explicitly remove online records already preserved in an archive",
    )
    add_remote_audit_archive_common(remote_archive_prune)
    remote_archive_prune.add_argument(
        "--expected-through-sequence", type=int, required=True
    )
    remote_archive_prune.add_argument(
        "--expected-through-record-sha256", required=True
    )
    remote_archive_prune.add_argument("--confirm-prune", action="store_true")
    remote_archive_prune.set_defaults(archive_operation="prune")

    remote_archive_local_status = team_contract_commands.add_parser(
        "registry-remote-audit-archive-inspect",
        help="inspect registered audit archives from local control state",
    )
    add_remote_audit_archive_common(remote_archive_local_status)
    remote_archive_local_status.set_defaults(archive_operation="status")

    def add_registry_recovery_trust(command: argparse.ArgumentParser) -> None:
        command.add_argument("--trust-policy", required=True)
        command.add_argument("--expected-trust-policy-id", required=True)
        command.add_argument("--expected-trust-policy-sha256", required=True)
        command.add_argument("--anchor-policy", required=True)
        command.add_argument("--expected-anchor-policy-id", required=True)
        command.add_argument("--expected-anchor-policy-sha256", required=True)
        command.add_argument("--verification-time")
        command.add_argument("--maximum-files", type=int, default=64)
        command.add_argument("--maximum-expanded-bytes", type=int,
                             default=16 * 1024 * 1024)
        command.add_argument("--report")
        command.set_defaults(handler=manage_team_contract_registry_recovery)

    registry_recovery_create = team_contract_commands.add_parser(
        "registry-recovery-create",
        help="create an externally anchored portable Registry recovery point",
    )
    registry_recovery_create.add_argument("--registry", required=True)
    registry_recovery_create.add_argument("--recovery-point-id", required=True)
    registry_recovery_create.add_argument("--anchor", required=True)
    registry_recovery_create.add_argument("--operator", required=True)
    registry_recovery_create.add_argument("--created-at")
    registry_recovery_create.add_argument("--output", required=True)
    add_registry_recovery_trust(registry_recovery_create)
    registry_recovery_create.set_defaults(recovery_operation="create")

    registry_recovery_verify = team_contract_commands.add_parser(
        "registry-recovery-verify",
        help="independently verify a portable Registry recovery point",
    )
    registry_recovery_verify.add_argument("--recovery-point", required=True)
    registry_recovery_verify.add_argument("--expected-recovery-point-sha256")
    add_registry_recovery_trust(registry_recovery_verify)
    registry_recovery_verify.set_defaults(recovery_operation="verify")

    registry_recovery_restore = team_contract_commands.add_parser(
        "registry-recovery-restore",
        help="atomically restore an anchored Registry into an absent destination",
    )
    registry_recovery_restore.add_argument("--recovery-point", required=True)
    registry_recovery_restore.add_argument(
        "--expected-recovery-point-sha256", required=True
    )
    registry_recovery_restore.add_argument("--destination", required=True)
    registry_recovery_restore.add_argument("--restore-id", required=True)
    registry_recovery_restore.add_argument("--operator", required=True)
    registry_recovery_restore.add_argument("--operation-audit", required=True)
    registry_recovery_restore.add_argument(
        "--confirm-source-unavailable", action="store_true"
    )
    add_registry_recovery_trust(registry_recovery_restore)
    registry_recovery_restore.set_defaults(recovery_operation="restore")

    registry_standby_init = team_contract_commands.add_parser(
        "registry-standby-init",
        help="initialize an externally anchored read-only Registry standby",
    )
    registry_standby_init.add_argument("--recovery-point", required=True)
    registry_standby_init.add_argument(
        "--expected-recovery-point-sha256", required=True
    )
    registry_standby_init.add_argument("--destination", required=True)
    registry_standby_init.add_argument("--standby-id", required=True)
    registry_standby_init.add_argument("--operator", required=True)
    registry_standby_init.add_argument("--operation-audit", required=True)
    registry_standby_init.add_argument("--updated-at")
    add_registry_recovery_trust(registry_standby_init)
    registry_standby_init.set_defaults(
        handler=manage_team_contract_registry_standby, standby_operation="init"
    )

    registry_standby_sync = team_contract_commands.add_parser(
        "registry-standby-sync",
        help="fast-forward a stopped standby and preserve its prior directory",
    )
    registry_standby_sync.add_argument("--recovery-point", required=True)
    registry_standby_sync.add_argument(
        "--expected-recovery-point-sha256", required=True
    )
    registry_standby_sync.add_argument("--destination", required=True)
    registry_standby_sync.add_argument("--standby-id", required=True)
    registry_standby_sync.add_argument("--sync-id", required=True)
    registry_standby_sync.add_argument("--operator", required=True)
    registry_standby_sync.add_argument("--operation-audit", required=True)
    registry_standby_sync.add_argument("--previous-output", required=True)
    registry_standby_sync.add_argument(
        "--expected-revision", type=int, required=True
    )
    registry_standby_sync.add_argument("--expected-state-sha256", required=True)
    registry_standby_sync.add_argument(
        "--expected-sync-generation", type=int, required=True
    )
    registry_standby_sync.add_argument(
        "--confirm-standby-stopped", action="store_true"
    )
    registry_standby_sync.add_argument("--updated-at")
    add_registry_recovery_trust(registry_standby_sync)
    registry_standby_sync.set_defaults(
        handler=manage_team_contract_registry_standby, standby_operation="sync"
    )

    registry_standby_status = team_contract_commands.add_parser(
        "registry-standby-status",
        help="verify Registry standby identity, marker and current state",
    )
    registry_standby_status.add_argument("--registry", required=True)
    add_registry_recovery_trust(registry_standby_status)
    registry_standby_status.set_defaults(
        handler=manage_team_contract_registry_standby, standby_operation="status"
    )

    def add_registry_leader_trust(command: argparse.ArgumentParser) -> None:
        command.add_argument("--leader-trust-policy", required=True)
        command.add_argument("--expected-leader-trust-policy-id", required=True)
        command.add_argument("--expected-leader-trust-policy-sha256", required=True)

    registry_leader_issue = team_contract_commands.add_parser(
        "registry-leader-issue",
        help="issue the next external signed leader or fence grant",
    )
    registry_leader_issue_backend = \
        registry_leader_issue.add_mutually_exclusive_group(required=True)
    registry_leader_issue_backend.add_argument("--authority")
    registry_leader_issue_backend.add_argument("--authority-backend-config")
    registry_leader_issue.add_argument(
        "--expected-authority-backend-config-sha256"
    )
    registry_leader_issue.add_argument("--authority-id", required=True)
    registry_leader_issue.add_argument("--registry-id", required=True)
    registry_leader_issue.add_argument(
        "--purpose", choices=("leadership", "fence"), required=True
    )
    registry_leader_issue.add_argument("--leader-id")
    registry_leader_issue.add_argument(
        "--expected-current-token", type=int, required=True
    )
    registry_leader_issue.add_argument(
        "--expected-current-grant-sha256", required=True
    )
    registry_leader_issue.add_argument(
        "--baseline-revision", type=int, required=True
    )
    registry_leader_issue.add_argument("--baseline-state-sha256", required=True)
    registry_leader_issue.add_argument("--issued-at")
    registry_leader_issue.add_argument("--not-before", required=True)
    registry_leader_issue.add_argument("--expires-at", required=True)
    registry_leader_issue.add_argument("--key-id", required=True)
    registry_leader_issue.add_argument(
        "--private-key-environment", required=True
    )
    registry_leader_issue.add_argument("--private-key-passphrase-environment")
    registry_leader_issue.add_argument("--operator", required=True)
    registry_leader_issue.add_argument("--operation-audit")
    registry_leader_issue.add_argument("--report")
    registry_leader_issue.add_argument("--handoff-evidence")
    registry_leader_issue.add_argument("--handoff-trust-policy")
    registry_leader_issue.add_argument("--expected-handoff-trust-policy-id")
    registry_leader_issue.add_argument("--expected-handoff-trust-policy-sha256")
    registry_leader_issue.add_argument("--handoff-verification-time")
    add_registry_leader_trust(registry_leader_issue)
    registry_leader_issue.set_defaults(
        handler=manage_team_contract_registry_leader, leader_operation="issue"
    )

    registry_leader_activate = team_contract_commands.add_parser(
        "registry-leader-activate",
        help="bind an exact external leader grant to a primary or standby",
    )
    registry_leader_activate.add_argument("--registry", required=True)
    registry_leader_activate.add_argument("--node-id", required=True)
    registry_leader_activate_source = \
        registry_leader_activate.add_mutually_exclusive_group(required=True)
    registry_leader_activate_source.add_argument("--current-grant")
    registry_leader_activate_source.add_argument("--authority-backend-config")
    registry_leader_activate.add_argument("--authority-id")
    registry_leader_activate.add_argument(
        "--expected-authority-backend-config-sha256"
    )
    registry_leader_activate.add_argument(
        "--expected-current-grant-sha256", required=True
    )
    registry_leader_activate.add_argument("--operator", required=True)
    registry_leader_activate.add_argument("--operation-audit", required=True)
    registry_leader_activate.add_argument(
        "--confirm-enroll-primary", action="store_true"
    )
    registry_leader_activate.add_argument("--backend-migration-evidence")
    registry_leader_activate.add_argument(
        "--expected-backend-migration-evidence-sha256"
    )
    registry_leader_activate.add_argument("--artifact-store-config")
    registry_leader_activate.add_argument(
        "--expected-artifact-store-config-sha256"
    )
    registry_leader_activate.add_argument(
        "--backend-config-resolver-config"
    )
    registry_leader_activate.add_argument(
        "--expected-backend-config-resolver-config-sha256"
    )
    registry_leader_activate.add_argument("--bound-at")
    registry_leader_activate.add_argument("--report")
    registry_leader_activate.add_argument("--trust-policy", required=True)
    registry_leader_activate.add_argument(
        "--expected-trust-policy-id", required=True
    )
    registry_leader_activate.add_argument(
        "--expected-trust-policy-sha256", required=True
    )
    registry_leader_activate.add_argument("--verification-time")
    registry_leader_activate.add_argument("--leader-verification-time")
    registry_leader_activate.add_argument("--maximum-files", type=int, default=64)
    registry_leader_activate.add_argument(
        "--maximum-expanded-bytes", type=int, default=16 * 1024 * 1024
    )
    add_registry_leader_trust(registry_leader_activate)
    registry_leader_activate.set_defaults(
        handler=manage_team_contract_registry_leader, leader_operation="activate"
    )

    registry_leader_status = team_contract_commands.add_parser(
        "registry-leader-status",
        help="verify the current writable Registry leader and lease",
    )
    registry_leader_status.add_argument("--registry", required=True)
    registry_leader_status.add_argument("--verification-time")
    registry_leader_status.add_argument("--report")
    registry_leader_status.set_defaults(
        handler=manage_team_contract_registry_leader, leader_operation="status"
    )

    registry_leader_backend_conformance = team_contract_commands.add_parser(
        "registry-leader-backend-conformance",
        help="qualify one adapter in an explicitly dedicated empty scope",
    )
    registry_leader_backend_conformance.add_argument(
        "--backend-config", required=True
    )
    registry_leader_backend_conformance.add_argument(
        "--expected-backend-config-sha256", required=True
    )
    registry_leader_backend_conformance.add_argument(
        "--authority-id", required=True
    )
    registry_leader_backend_conformance.add_argument(
        "--registry-id", required=True
    )
    registry_leader_backend_conformance.add_argument(
        "--confirm-dedicated-empty-scope", action="store_true"
    )
    registry_leader_backend_conformance.add_argument("--report")
    registry_leader_backend_conformance.set_defaults(
        handler=qualify_team_contract_registry_leader_backend
    )

    registry_leader_backend_capabilities = team_contract_commands.add_parser(
        "registry-leader-backend-capabilities",
        help="negotiate and record a pinned backend capability manifest",
    )
    registry_leader_backend_capabilities.add_argument(
        "--backend-config", required=True
    )
    registry_leader_backend_capabilities.add_argument(
        "--expected-backend-config-sha256", required=True
    )
    registry_leader_backend_capabilities.add_argument(
        "--authority-id", required=True
    )
    registry_leader_backend_capabilities.add_argument(
        "--registry-id", required=True
    )
    registry_leader_backend_capabilities.add_argument("--report")
    registry_leader_backend_capabilities.set_defaults(
        handler=inspect_team_contract_registry_leader_backend_capabilities
    )

    artifact_store_put = team_contract_commands.add_parser(
        "artifact-store-put",
        help="publish immutable evidence and return a content-addressed reference",
    )
    artifact_store_get = team_contract_commands.add_parser(
        "artifact-store-get",
        help="materialize pinned content-addressed evidence",
    )
    for command, operation in (
            (artifact_store_put, "put"), (artifact_store_get, "get")):
        command.add_argument("--config", required=True)
        command.add_argument("--expected-config-sha256", required=True)
        command.add_argument("--namespace-id", required=True)
        command.set_defaults(
            handler=manage_team_contract_artifact_store,
            artifact_operation=operation,
        )
    artifact_store_put.add_argument("--input", required=True)
    artifact_store_put.add_argument(
        "--media-type", default="application/octet-stream"
    )
    artifact_store_put.add_argument("--reference-output", required=True)
    artifact_store_get.add_argument("--reference", required=True)
    artifact_store_get.add_argument("--output", required=True)

    secret_provider_check = team_contract_commands.add_parser(
        "secret-provider-check",
        help="resolve a version-pinned secret and emit only redacted availability",
    )
    secret_provider_check.add_argument("--config", required=True)
    secret_provider_check.add_argument(
        "--expected-config-sha256", required=True
    )
    secret_provider_check.add_argument("--reference", required=True)
    secret_provider_check.add_argument(
        "--expected-reference-sha256", required=True
    )
    secret_provider_check.add_argument("--report")
    secret_provider_check.set_defaults(
        handler=manage_team_contract_secret_provider
    )

    for operation in ("list", "check"):
        adapter_catalog = team_contract_commands.add_parser(
            f"adapter-catalog-{operation}",
            help=("list pinned discoverable adapters" if operation == "list"
                  else "negotiate capabilities for discoverable adapters"),
        )
        adapter_catalog.add_argument("--catalog", required=True)
        adapter_catalog.add_argument(
            "--expected-catalog-sha256", required=True
        )
        adapter_catalog.add_argument("--adapter-type")
        adapter_catalog.add_argument("--report")
        adapter_catalog.set_defaults(
            handler=manage_team_contract_adapter_catalog,
            adapter_catalog_operation=operation,
        )

    adapter_catalog_activate = team_contract_commands.add_parser(
        "adapter-catalog-activate",
        help="atomically activate a pinned host-local Adapter Catalog",
    )
    adapter_catalog_activate.add_argument("--catalog", required=True)
    adapter_catalog_activate.add_argument(
        "--expected-catalog-sha256", required=True
    )
    adapter_catalog_rollback = team_contract_commands.add_parser(
        "adapter-catalog-rollback",
        help="restore an earlier verified Adapter Catalog generation",
    )
    adapter_catalog_rollback.add_argument(
        "--to-generation", type=int, required=True
    )
    for command, operation in (
            (adapter_catalog_activate, "activate"),
            (adapter_catalog_rollback, "rollback")):
        command.add_argument("--state-dir", required=True)
        command.add_argument("--expected-generation", type=int, required=True)
        command.add_argument("--operation-id", required=True)
        command.add_argument("--actor", required=True)
        command.add_argument("--reason", required=True)
        command.add_argument("--report")
        command.set_defaults(
            handler=manage_team_contract_adapter_catalog_state,
            adapter_catalog_state_operation=operation,
        )
    for command_name, operation, help_text in (
            ("adapter-catalog-current", "current",
             "resolve the current verified Adapter Catalog"),
            ("adapter-catalog-current-check", "current_check",
             "probe the current Catalog and reject a concurrent switch"),
            ("adapter-catalog-state-verify", "verify",
             "verify the immutable Catalog activation history")):
        command = team_contract_commands.add_parser(
            command_name, help=help_text
        )
        command.add_argument("--state-dir", required=True)
        command.add_argument("--report")
        command.set_defaults(
            handler=manage_team_contract_adapter_catalog_state,
            adapter_catalog_state_operation=operation,
        )

    adapter_catalog_reconcile = team_contract_commands.add_parser(
        "adapter-catalog-reconcile",
        help="health-gate a Catalog rollout and automatically roll back",
    )
    adapter_catalog_reconcile.add_argument("--catalog", required=True)
    adapter_catalog_reconcile.add_argument(
        "--expected-catalog-sha256", required=True
    )
    adapter_catalog_reconcile.add_argument(
        "--expected-generation", type=int, required=True
    )
    adapter_catalog_reconcile.add_argument("--actor", required=True)
    adapter_catalog_reconcile.add_argument("--reason", required=True)
    adapter_catalog_reconcile.set_defaults(
        adapter_catalog_reconcile_operation="run"
    )
    adapter_catalog_reconcile_recover = team_contract_commands.add_parser(
        "adapter-catalog-reconcile-recover",
        help="resume an interrupted Catalog rollout or rollback",
    )
    adapter_catalog_reconcile_recover.set_defaults(
        adapter_catalog_reconcile_operation="recover"
    )
    adapter_catalog_reconcile_revert = team_contract_commands.add_parser(
        "adapter-catalog-reconcile-revert",
        help="reverse a committed Catalog rollout through its lifecycle Hook",
    )
    adapter_catalog_reconcile_revert.set_defaults(
        adapter_catalog_reconcile_operation="revert"
    )
    for command in (
            adapter_catalog_reconcile,
            adapter_catalog_reconcile_recover,
            adapter_catalog_reconcile_revert):
        command.add_argument("--config", required=True)
        command.add_argument("--expected-config-sha256", required=True)
        command.add_argument("--state-dir", required=True)
        command.add_argument("--transaction-dir", required=True)
        command.add_argument("--transaction-id", required=True)
        command.add_argument("--report")
        command.set_defaults(handler=manage_team_contract_adapter_catalog_reconciler)
    adapter_catalog_reconcile_status = team_contract_commands.add_parser(
        "adapter-catalog-reconcile-status",
        help="inspect one persistent Catalog rollout journal",
    )
    adapter_catalog_reconcile_status.add_argument(
        "--transaction-dir", required=True
    )
    adapter_catalog_reconcile_status.add_argument(
        "--transaction-id", required=True
    )
    adapter_catalog_reconcile_status.add_argument("--report")
    adapter_catalog_reconcile_status.set_defaults(
        handler=manage_team_contract_adapter_catalog_reconciler,
        adapter_catalog_reconcile_operation="status",
    )

    for command_name, operation, help_text in (
            ("adapter-catalog-fleet-run", "run",
             "run a persistent canary/wave Catalog rollout"),
            ("adapter-catalog-fleet-recover", "recover",
             "resume an interrupted canary/wave Catalog rollout"),
            ("adapter-catalog-fleet-resume", "resume",
             "approve and continue a Wave Gate paused rollout"),
            ("adapter-catalog-fleet-abort", "abort",
             "abort a Wave Gate paused rollout and reverse committed nodes")):
        command = team_contract_commands.add_parser(
            command_name, help=help_text
        )
        command.add_argument("--plan", required=True)
        command.add_argument("--expected-plan-sha256", required=True)
        command.add_argument("--executor-config")
        command.add_argument(
            "--expected-executor-config-sha256"
        )
        command.add_argument("--adapter-config-resolver-config")
        command.add_argument(
            "--expected-adapter-config-resolver-config-sha256"
        )
        command.add_argument("--adapter-conformance-bundle")
        command.add_argument(
            "--expected-adapter-conformance-bundle-sha256"
        )
        command.add_argument("--adapter-conformance-trust-policy")
        command.add_argument(
            "--expected-adapter-conformance-trust-policy-sha256"
        )
        command.add_argument("--state-dir", required=True)
        command.add_argument("--state-backend-config")
        command.add_argument("--artifact-store-config")
        command.add_argument("--coordinator-id")
        command.add_argument("--report")
        if operation in {"resume", "abort"}:
            command.add_argument(
                "--expected-control-generation", type=int, required=True
            )
            command.add_argument("--operation-id", required=True)
            command.add_argument("--actor", required=True)
            command.add_argument("--reason", required=True)
        command.set_defaults(
            handler=manage_team_contract_adapter_catalog_fleet,
            adapter_catalog_fleet_operation=operation,
        )
    adapter_catalog_fleet_status = team_contract_commands.add_parser(
        "adapter-catalog-fleet-status",
        help="inspect one persistent canary/wave Fleet journal",
    )
    adapter_catalog_fleet_status.add_argument("--plan", required=True)
    adapter_catalog_fleet_status.add_argument(
        "--expected-plan-sha256", required=True
    )
    adapter_catalog_fleet_status.add_argument("--state-dir", required=True)
    adapter_catalog_fleet_status.add_argument("--state-backend-config")
    adapter_catalog_fleet_status.add_argument("--artifact-store-config")
    adapter_catalog_fleet_status.add_argument("--coordinator-id")
    adapter_catalog_fleet_status.add_argument(
        "--adapter-config-resolver-config"
    )
    adapter_catalog_fleet_status.add_argument(
        "--expected-adapter-config-resolver-config-sha256"
    )
    adapter_catalog_fleet_status.add_argument("--adapter-conformance-bundle")
    adapter_catalog_fleet_status.add_argument(
        "--expected-adapter-conformance-bundle-sha256"
    )
    adapter_catalog_fleet_status.add_argument(
        "--adapter-conformance-trust-policy"
    )
    adapter_catalog_fleet_status.add_argument(
        "--expected-adapter-conformance-trust-policy-sha256"
    )
    adapter_catalog_fleet_status.add_argument("--report")
    adapter_catalog_fleet_status.set_defaults(
        handler=manage_team_contract_adapter_catalog_fleet,
        adapter_catalog_fleet_operation="status",
    )

    adapter_conformance = team_contract_commands.add_parser(
        "adapter-conformance",
        help="certify one pinned Adapter for integration readiness",
    )
    adapter_conformance.add_argument(
        "--adapter-kind", required=True, choices=(
            "adapter-config-resolver", "artifact-store",
            "control-authorizer", "fleet-executor",
            "registry-leader-backend", "wave-gate",
        ),
    )
    adapter_conformance.add_argument("--config", required=True)
    adapter_conformance.add_argument(
        "--expected-config-sha256", required=True
    )
    adapter_conformance.add_argument("--scope-primary")
    adapter_conformance.add_argument("--scope-secondary")
    adapter_conformance.add_argument("--report", required=True)
    adapter_conformance.set_defaults(
        handler=qualify_team_contract_adapter
    )
    adapter_admission = team_contract_commands.add_parser(
        "adapter-conformance-admission-create",
        help="create a host-local pinned six-Adapter admission bundle",
    )
    adapter_admission.add_argument("--bundle-id", required=True)
    adapter_admission.add_argument("--rollout-id", required=True)
    adapter_admission.add_argument("--catalog-id", required=True)
    adapter_admission.add_argument(
        "--evidence", action="append", nargs=2,
        metavar=("ADAPTER_KIND", "EVIDENCE_PATH"), required=True,
    )
    adapter_admission.add_argument(
        "--attestation", action="append", nargs=2,
        metavar=("ADAPTER_KIND", "ATTESTATION_PATH"),
    )
    adapter_admission.add_argument("--output", required=True)
    adapter_admission.set_defaults(
        handler=create_team_contract_adapter_admission
    )
    adapter_attestation = team_contract_commands.add_parser(
        "adapter-conformance-attest",
        help="sign exact Adapter conformance evidence with Ed25519",
    )
    adapter_attestation.add_argument("--evidence", required=True)
    adapter_attestation.add_argument(
        "--expected-evidence-sha256", required=True
    )
    adapter_attestation.add_argument("--certifier-id", required=True)
    adapter_attestation.add_argument("--key-id", required=True)
    adapter_attestation.add_argument(
        "--private-key-environment", required=True
    )
    adapter_attestation.add_argument(
        "--private-key-passphrase-environment"
    )
    adapter_attestation.add_argument("--issued-at")
    adapter_attestation.add_argument(
        "--lifetime-seconds", type=int, default=3600
    )
    adapter_attestation.add_argument("--report", required=True)
    adapter_attestation.set_defaults(handler=attest_team_contract_adapter)

    backend_config_resolve = team_contract_commands.add_parser(
        "backend-config-resolve",
        help="resolve a portable backend config reference on this host",
    )
    backend_config_resolve.add_argument("--config", required=True)
    backend_config_resolve.add_argument(
        "--expected-config-sha256", required=True
    )
    backend_config_resolve.add_argument("--reference", required=True)
    backend_config_resolve.add_argument("--authority-id", required=True)
    backend_config_resolve.add_argument("--registry-id", required=True)
    backend_config_resolve.add_argument("--report")
    backend_config_resolve.set_defaults(
        handler=manage_team_contract_backend_config_resolver
    )

    registry_leader_backend_migration_sync = team_contract_commands.add_parser(
        "registry-leader-backend-migration-sync",
        help="synchronize an immutable grant chain into a target backend",
    )
    registry_leader_backend_migration_sync.add_argument(
        "--migration-id", required=True
    )
    registry_leader_backend_migration_sync.add_argument(
        "--authority-id", required=True
    )
    registry_leader_backend_migration_sync.add_argument(
        "--registry-id", required=True
    )
    registry_leader_backend_migration_sync.add_argument(
        "--source-backend-config"
    )
    registry_leader_backend_migration_sync.add_argument(
        "--expected-source-backend-config-sha256"
    )
    registry_leader_backend_migration_sync.add_argument(
        "--target-backend-config"
    )
    registry_leader_backend_migration_sync.add_argument(
        "--expected-target-backend-config-sha256"
    )
    registry_leader_backend_migration_sync.add_argument("--source-backend-ref")
    registry_leader_backend_migration_sync.add_argument(
        "--expected-source-backend-ref-sha256"
    )
    registry_leader_backend_migration_sync.add_argument("--target-backend-ref")
    registry_leader_backend_migration_sync.add_argument(
        "--expected-target-backend-ref-sha256"
    )
    registry_leader_backend_migration_sync.add_argument(
        "--confirm-target-migration-scope", action="store_true"
    )
    registry_leader_backend_migration_sync.add_argument("--transaction")
    registry_leader_backend_migration_sync.add_argument(
        "--transaction-backend-config"
    )
    registry_leader_backend_migration_sync.add_argument(
        "--expected-transaction-backend-config-sha256"
    )
    registry_leader_backend_migration_sync.add_argument("--artifact-store-config")
    registry_leader_backend_migration_sync.add_argument(
        "--expected-artifact-store-config-sha256"
    )
    registry_leader_backend_migration_sync.add_argument(
        "--backend-config-resolver-config"
    )
    registry_leader_backend_migration_sync.add_argument(
        "--expected-backend-config-resolver-config-sha256"
    )
    registry_leader_backend_migration_sync.add_argument("--actor")
    registry_leader_backend_migration_sync.add_argument(
        "--output", required=True
    )
    registry_leader_backend_migration_sync.set_defaults(
        handler=manage_team_contract_registry_leader_backend_migration,
        migration_operation="sync",
    )

    registry_leader_backend_migration_finalize = \
        team_contract_commands.add_parser(
            "registry-leader-backend-migration-finalize",
            help="verify a fenced source and target leadership cutover",
        )
    registry_leader_backend_migration_finalize.add_argument(
        "--migration-id", required=True
    )
    registry_leader_backend_migration_finalize.add_argument(
        "--registry", required=True
    )
    registry_leader_backend_migration_finalize.add_argument(
        "--authority-id", required=True
    )
    registry_leader_backend_migration_finalize.add_argument(
        "--registry-id", required=True
    )
    registry_leader_backend_migration_finalize.add_argument(
        "--sync-evidence", required=True
    )
    registry_leader_backend_migration_finalize.add_argument(
        "--expected-sync-evidence-sha256", required=True
    )
    registry_leader_backend_migration_finalize.add_argument(
        "--expected-target-grant-sha256", required=True
    )
    registry_leader_backend_migration_finalize.add_argument(
        "--leader-verification-time"
    )
    registry_leader_backend_migration_finalize.add_argument(
        "--trust-policy", required=True
    )
    registry_leader_backend_migration_finalize.add_argument(
        "--expected-trust-policy-id", required=True
    )
    registry_leader_backend_migration_finalize.add_argument(
        "--expected-trust-policy-sha256", required=True
    )
    registry_leader_backend_migration_finalize.add_argument(
        "--verification-time"
    )
    registry_leader_backend_migration_finalize.add_argument(
        "--maximum-files", type=int, default=64
    )
    registry_leader_backend_migration_finalize.add_argument(
        "--maximum-expanded-bytes", type=int, default=16 * 1024 * 1024
    )
    registry_leader_backend_migration_finalize.add_argument("--transaction")
    registry_leader_backend_migration_finalize.add_argument(
        "--transaction-backend-config"
    )
    registry_leader_backend_migration_finalize.add_argument(
        "--expected-transaction-backend-config-sha256"
    )
    registry_leader_backend_migration_finalize.add_argument("--artifact-store-config")
    registry_leader_backend_migration_finalize.add_argument(
        "--expected-artifact-store-config-sha256"
    )
    registry_leader_backend_migration_finalize.add_argument(
        "--backend-config-resolver-config"
    )
    registry_leader_backend_migration_finalize.add_argument(
        "--expected-backend-config-resolver-config-sha256"
    )
    registry_leader_backend_migration_finalize.add_argument(
        "--expected-transaction-sha256"
    )
    registry_leader_backend_migration_finalize.add_argument("--actor")
    registry_leader_backend_migration_finalize.add_argument(
        "--output", required=True
    )
    registry_leader_backend_migration_finalize.set_defaults(
        handler=manage_team_contract_registry_leader_backend_migration,
        migration_operation="finalize",
    )

    registry_leader_backend_migration_status = \
        team_contract_commands.add_parser(
            "registry-leader-backend-migration-status",
            help="classify live migration phase from a shared transaction",
        )
    registry_leader_backend_migration_status.add_argument(
        "--transaction"
    )
    registry_leader_backend_migration_status.add_argument(
        "--transaction-backend-config"
    )
    registry_leader_backend_migration_status.add_argument(
        "--expected-transaction-backend-config-sha256"
    )
    registry_leader_backend_migration_status.add_argument("--artifact-store-config")
    registry_leader_backend_migration_status.add_argument(
        "--expected-artifact-store-config-sha256"
    )
    registry_leader_backend_migration_status.add_argument(
        "--backend-config-resolver-config"
    )
    registry_leader_backend_migration_status.add_argument(
        "--expected-backend-config-resolver-config-sha256"
    )
    registry_leader_backend_migration_status.add_argument("--migration-id")
    registry_leader_backend_migration_status.add_argument("--registry-id")
    registry_leader_backend_migration_status.add_argument(
        "--registry", required=True
    )
    registry_leader_backend_migration_status.add_argument("--report")
    registry_leader_backend_migration_status.set_defaults(
        handler=manage_team_contract_registry_leader_backend_migration,
        migration_operation="status",
    )

    registry_leader_backend_migration_resume = \
        team_contract_commands.add_parser(
            "registry-leader-backend-migration-resume",
            help="resume exact-prefix synchronization from pinned state",
        )
    registry_leader_backend_migration_resume.add_argument(
        "--transaction"
    )
    registry_leader_backend_migration_resume.add_argument(
        "--transaction-backend-config"
    )
    registry_leader_backend_migration_resume.add_argument(
        "--expected-transaction-backend-config-sha256"
    )
    registry_leader_backend_migration_resume.add_argument("--artifact-store-config")
    registry_leader_backend_migration_resume.add_argument(
        "--expected-artifact-store-config-sha256"
    )
    registry_leader_backend_migration_resume.add_argument(
        "--backend-config-resolver-config"
    )
    registry_leader_backend_migration_resume.add_argument(
        "--expected-backend-config-resolver-config-sha256"
    )
    registry_leader_backend_migration_resume.add_argument("--migration-id")
    registry_leader_backend_migration_resume.add_argument("--registry-id")
    registry_leader_backend_migration_resume.add_argument(
        "--expected-transaction-sha256", required=True
    )
    registry_leader_backend_migration_resume.add_argument(
        "--actor", required=True
    )
    registry_leader_backend_migration_resume.add_argument(
        "--confirm-target-migration-scope", action="store_true"
    )
    registry_leader_backend_migration_resume.add_argument(
        "--output", required=True
    )
    registry_leader_backend_migration_resume.set_defaults(
        handler=manage_team_contract_registry_leader_backend_migration,
        migration_operation="resume",
    )

    registry_leader_backend_migration_reconcile = \
        team_contract_commands.add_parser(
            "registry-leader-backend-migration-reconcile",
            help="adopt a pinned checkpoint or confirm completed cutover",
        )
    registry_leader_backend_migration_reconcile.add_argument(
        "--transaction"
    )
    registry_leader_backend_migration_reconcile.add_argument(
        "--transaction-backend-config"
    )
    registry_leader_backend_migration_reconcile.add_argument(
        "--expected-transaction-backend-config-sha256"
    )
    registry_leader_backend_migration_reconcile.add_argument("--artifact-store-config")
    registry_leader_backend_migration_reconcile.add_argument(
        "--expected-artifact-store-config-sha256"
    )
    registry_leader_backend_migration_reconcile.add_argument(
        "--backend-config-resolver-config"
    )
    registry_leader_backend_migration_reconcile.add_argument(
        "--expected-backend-config-resolver-config-sha256"
    )
    registry_leader_backend_migration_reconcile.add_argument("--migration-id")
    registry_leader_backend_migration_reconcile.add_argument("--registry-id")
    registry_leader_backend_migration_reconcile.add_argument(
        "--expected-transaction-sha256"
    )
    registry_leader_backend_migration_reconcile.add_argument(
        "--actor", required=True
    )
    registry_leader_backend_migration_reconcile.add_argument(
        "--sync-evidence"
    )
    registry_leader_backend_migration_reconcile.add_argument(
        "--expected-sync-evidence-sha256"
    )
    registry_leader_backend_migration_reconcile.add_argument(
        "--migration-evidence"
    )
    registry_leader_backend_migration_reconcile.add_argument(
        "--expected-migration-evidence-sha256"
    )
    registry_leader_backend_migration_reconcile.add_argument("--registry")
    registry_leader_backend_migration_reconcile.add_argument(
        "--confirm-adopt-orphaned-sync", action="store_true"
    )
    registry_leader_backend_migration_reconcile.set_defaults(
        handler=manage_team_contract_registry_leader_backend_migration,
        migration_operation="reconcile",
    )

    registry_leader_backend_migration_abort = \
        team_contract_commands.add_parser(
            "registry-leader-backend-migration-abort",
            help="terminally abort a pre-fence shared migration transaction",
        )
    registry_leader_backend_migration_abort.add_argument(
        "--transaction"
    )
    registry_leader_backend_migration_abort.add_argument(
        "--transaction-backend-config"
    )
    registry_leader_backend_migration_abort.add_argument(
        "--expected-transaction-backend-config-sha256"
    )
    registry_leader_backend_migration_abort.add_argument("--artifact-store-config")
    registry_leader_backend_migration_abort.add_argument(
        "--expected-artifact-store-config-sha256"
    )
    registry_leader_backend_migration_abort.add_argument(
        "--backend-config-resolver-config"
    )
    registry_leader_backend_migration_abort.add_argument(
        "--expected-backend-config-resolver-config-sha256"
    )
    registry_leader_backend_migration_abort.add_argument("--migration-id")
    registry_leader_backend_migration_abort.add_argument("--registry-id")
    registry_leader_backend_migration_abort.add_argument(
        "--expected-transaction-sha256", required=True
    )
    registry_leader_backend_migration_abort.add_argument(
        "--registry", required=True
    )
    registry_leader_backend_migration_abort.add_argument(
        "--operator", required=True
    )
    registry_leader_backend_migration_abort.add_argument(
        "--reason", required=True
    )
    registry_leader_backend_migration_abort.add_argument(
        "--output", required=True
    )
    registry_leader_backend_migration_abort.set_defaults(
        handler=manage_team_contract_registry_leader_backend_migration,
        migration_operation="abort",
    )

    registry_leader_etcd_preflight = team_contract_commands.add_parser(
        "registry-leader-etcd-preflight",
        help="verify pinned etcd cluster topology before authority writes",
    )
    registry_leader_etcd_preflight.add_argument("--config", required=True)
    registry_leader_etcd_preflight.add_argument(
        "--expected-config-sha256", required=True
    )
    registry_leader_etcd_preflight.add_argument("--report")
    registry_leader_etcd_preflight.set_defaults(
        handler=preflight_team_contract_registry_leader_etcd
    )

    registry_leader_etcd_acceptance = team_contract_commands.add_parser(
        "registry-leader-etcd-acceptance",
        help="run pinned etcd preflight, conformance and postflight evidence",
    )
    registry_leader_etcd_acceptance.add_argument(
        "--adapter-config", required=True
    )
    registry_leader_etcd_acceptance.add_argument(
        "--expected-adapter-config-sha256", required=True
    )
    registry_leader_etcd_acceptance.add_argument(
        "--backend-config", required=True
    )
    registry_leader_etcd_acceptance.add_argument(
        "--expected-backend-config-sha256", required=True
    )
    registry_leader_etcd_acceptance.add_argument(
        "--authority-id", required=True
    )
    registry_leader_etcd_acceptance.add_argument(
        "--registry-id", required=True
    )
    registry_leader_etcd_acceptance.add_argument(
        "--confirm-dedicated-empty-scope", action="store_true"
    )
    registry_leader_etcd_acceptance.add_argument(
        "--output-directory", required=True
    )
    registry_leader_etcd_acceptance.set_defaults(
        handler=accept_team_contract_registry_leader_etcd
    )

    def add_registry_handoff_common(
            command: argparse.ArgumentParser, identity: bool = True) -> None:
        command.add_argument("--control-directory", required=True)
        command.add_argument("--audit-archive-directory")
        command.add_argument("--registry-id", required=True)
        if identity:
            command.add_argument("--registry", required=True)
            command.add_argument("--node-id", required=True)
            command.add_argument("--handoff-id", required=True)
            command.add_argument("--expected-generation", type=int, required=True)
            command.add_argument("--expected-revision", type=int, required=True)
            command.add_argument("--expected-state-sha256", required=True)
            command.add_argument("--operator", required=True)
        command.add_argument("--report")

    registry_drain_start = team_contract_commands.add_parser(
        "registry-drain-start",
        help="persistently close remote command admission before handoff",
    )
    add_registry_handoff_common(registry_drain_start)
    registry_drain_start.add_argument("--reason", required=True)
    registry_drain_start.set_defaults(
        handler=manage_team_contract_registry_handoff, handoff_operation="start"
    )

    registry_drain_finalize = team_contract_commands.add_parser(
        "registry-drain-finalize",
        help="prove zero pending requests and sign portable handoff evidence",
    )
    add_registry_handoff_common(registry_drain_finalize)
    registry_drain_finalize.add_argument("--leader-verification-time")
    registry_drain_finalize.add_argument("--issued-at", required=True)
    registry_drain_finalize.add_argument("--expires-at", required=True)
    registry_drain_finalize.add_argument("--key-id", required=True)
    registry_drain_finalize.add_argument(
        "--private-key-environment", required=True
    )
    registry_drain_finalize.add_argument("--private-key-passphrase-environment")
    registry_drain_finalize.add_argument("--output", required=True)
    registry_drain_finalize.set_defaults(
        handler=manage_team_contract_registry_handoff, handoff_operation="finalize"
    )

    registry_drain_resume = team_contract_commands.add_parser(
        "registry-drain-resume",
        help="reopen command admission only for a still-authorized old leader",
    )
    add_registry_handoff_common(registry_drain_resume)
    registry_drain_resume.add_argument("--reason", required=True)
    registry_drain_resume.set_defaults(
        handler=manage_team_contract_registry_handoff, handoff_operation="resume"
    )

    registry_drain_status = team_contract_commands.add_parser(
        "registry-drain-status", help="inspect persistent Registry drain state"
    )
    add_registry_handoff_common(registry_drain_status, identity=False)
    registry_drain_status.set_defaults(
        handler=manage_team_contract_registry_handoff, handoff_operation="status"
    )

    access_policy_sign = team_contract_commands.add_parser(
        "registry-access-policy-sign",
        help="sign an exact successor for remote access-policy hot reload",
    )
    access_policy_sign.add_argument("--input", required=True)
    access_policy_sign.add_argument(
        "--expected-previous-policy-sha256", required=True
    )
    access_policy_sign.add_argument("--policy-revision", type=int, required=True)
    access_policy_sign.add_argument("--issued-at")
    access_policy_sign.add_argument("--key-id", required=True)
    access_policy_sign.add_argument("--private-key-environment", required=True)
    access_policy_sign.add_argument("--private-key-passphrase-environment")
    access_policy_sign.add_argument(
        "--max-active-request-records", type=int, default=100000
    )
    access_policy_sign.add_argument("--max-recovery-records", type=int, default=100000)
    access_policy_sign.add_argument("--max-audit-records", type=int, default=1000000)
    access_policy_sign.add_argument(
        "--max-control-bytes", type=int, default=4 * 1024 * 1024 * 1024
    )
    access_policy_sign.add_argument("--output", required=True)
    access_policy_sign.set_defaults(handler=sign_team_contract_registry_access_policy)

    access_policy_activate = team_contract_commands.add_parser(
        "registry-access-policy-activate",
        help="verify and atomically activate one signed access-policy revision",
    )
    access_policy_activate.add_argument("--active-policy", required=True)
    access_policy_activate.add_argument("--candidate", required=True)
    access_policy_activate.add_argument(
        "--expected-current-policy-sha256", required=True
    )
    access_policy_activate.add_argument("--trust-policy", required=True)
    access_policy_activate.add_argument("--expected-trust-policy-id", required=True)
    access_policy_activate.add_argument("--expected-trust-policy-sha256", required=True)
    access_policy_activate.add_argument("--verification-time")
    access_policy_activate.add_argument("--report")
    access_policy_activate.set_defaults(
        handler=activate_team_contract_registry_access_policy
    )

    runner_attest = team_contract_commands.add_parser(
        "runner-attest", help="sign exact impact execution with a CI Runner identity"
    )
    runner_attest.add_argument("--report", required=True)
    runner_attest.add_argument("--evidence", required=True)
    runner_attest.add_argument("--junit")
    runner_attest.add_argument("--runner-id", required=True)
    runner_attest.add_argument("--repository", required=True)
    runner_attest.add_argument("--source-revision", required=True)
    runner_attest.add_argument("--workflow", required=True)
    runner_attest.add_argument("--job-id", required=True)
    runner_attest.add_argument("--run-id", required=True)
    runner_attest.add_argument("--issued-at")
    runner_attest.add_argument("--lifetime-seconds", type=int, default=3600)
    runner_attest.add_argument("--output", required=True)
    add_team_contract_private_key_arguments(runner_attest)
    runner_attest.set_defaults(handler=attest_team_contract_runner)

    runner_verify = team_contract_commands.add_parser(
        "runner-verify", help="verify Runner signature, scope and exact execution evidence"
    )
    runner_verify.add_argument("--attestation", required=True)
    runner_verify.add_argument("--report", required=True)
    runner_verify.add_argument("--evidence", required=True)
    runner_verify.add_argument("--junit")
    runner_verify.add_argument("--trust-policy", required=True)
    runner_verify.add_argument("--expected-trust-policy-id", required=True)
    runner_verify.add_argument("--expected-trust-policy-sha256", required=True)
    runner_verify.add_argument("--verification-time")
    runner_verify.add_argument("--verification-report")
    runner_verify.set_defaults(handler=verify_team_contract_runner)

    gate_authorize = team_contract_commands.add_parser(
        "gate-authorize", help="replay and sign a complete impact Gate for release"
    )
    gate_authorize.add_argument("--gate-report", required=True)
    gate_authorize.add_argument("--report", required=True)
    gate_authorize.add_argument("--evidence", required=True)
    gate_authorize.add_argument("--junit", required=True)
    gate_authorize.add_argument("--ctest")
    gate_authorize.add_argument("--test-dir")
    gate_authorize.add_argument("--config", default="Release")
    gate_authorize.add_argument("--approval-policy")
    gate_authorize.add_argument("--expected-approval-policy-id")
    gate_authorize.add_argument("--expected-approval-policy-sha256")
    gate_authorize.add_argument("--approval", action="append", default=[])
    gate_authorize.add_argument("--runner-attestation")
    gate_authorize.add_argument("--runner-trust-policy")
    gate_authorize.add_argument("--expected-runner-trust-policy-id")
    gate_authorize.add_argument("--expected-runner-trust-policy-sha256")
    gate_authorize.add_argument("--verification-time")
    gate_authorize.add_argument("--registry-id", required=True)
    gate_authorize.add_argument("--channel", action="append", required=True)
    gate_authorize.add_argument("--authorization-id", required=True)
    gate_authorize.add_argument("--authorizer-id", required=True)
    gate_authorize.add_argument("--issued-at")
    gate_authorize.add_argument("--lifetime-seconds", type=int, default=3600)
    gate_authorize.add_argument("--output", required=True)
    add_team_contract_private_key_arguments(gate_authorize)
    gate_authorize.set_defaults(handler=authorize_team_contract_gate)

    gate_authorization_verify = team_contract_commands.add_parser(
        "gate-authorization-verify", help="verify a Registry-scoped Gate authorization"
    )
    gate_authorization_verify.add_argument("--gate-report", required=True)
    gate_authorization_verify.add_argument("--authorization", required=True)
    gate_authorization_verify.add_argument("--authorization-policy", required=True)
    gate_authorization_verify.add_argument(
        "--expected-authorization-policy-id", required=True
    )
    gate_authorization_verify.add_argument(
        "--expected-authorization-policy-sha256", required=True
    )
    gate_authorization_verify.add_argument("--expected-registry-id", required=True)
    gate_authorization_verify.add_argument("--expected-channel", required=True)
    gate_authorization_verify.add_argument("--verification-time")
    gate_authorization_verify.add_argument("--verification-report")
    gate_authorization_verify.set_defaults(
        handler=verify_team_contract_gate_authorization
    )

    registry_anchor = team_contract_commands.add_parser(
        "registry-anchor", help="sign the current Registry state outside its root"
    )
    registry_anchor.add_argument("--registry", required=True)
    registry_anchor.add_argument("--anchor-id", required=True)
    registry_anchor.add_argument("--anchor-service-id", required=True)
    registry_anchor.add_argument("--previous-anchor")
    registry_anchor.add_argument("--issued-at")
    registry_anchor.add_argument("--output", required=True)
    add_team_contract_private_key_arguments(registry_anchor)
    add_team_contract_registry_trust_arguments(registry_anchor)
    add_team_contract_registry_limits(registry_anchor)
    registry_anchor.set_defaults(handler=anchor_team_contract_registry)

    registry_anchor_verify = team_contract_commands.add_parser(
        "registry-anchor-verify", help="detect Registry rollback against an external anchor"
    )
    registry_anchor_verify.add_argument("--registry", required=True)
    registry_anchor_verify.add_argument("--anchor", required=True)
    registry_anchor_verify.add_argument("--anchor-policy", required=True)
    registry_anchor_verify.add_argument("--expected-anchor-policy-id", required=True)
    registry_anchor_verify.add_argument("--expected-anchor-policy-sha256", required=True)
    registry_anchor_verify.add_argument("--verification-report")
    add_team_contract_registry_trust_arguments(registry_anchor_verify)
    add_team_contract_registry_limits(registry_anchor_verify)
    registry_anchor_verify.set_defaults(handler=verify_team_contract_registry_anchor)

    new = commands.add_parser("new", help="create a framework module")
    new.add_argument("kind", choices=KINDS)
    new.add_argument("name", type=valid_name)
    new.add_argument("--output", default="generated")
    new.add_argument("--force", action="store_true")
    new.add_argument("--project", help="project directory or pdr-project.yaml to register into")
    new.add_argument("--no-register", action="store_true",
                     help="do not auto-register even when a project manifest is found")
    new.set_defaults(handler=create_module)
    check = commands.add_parser("doctor", help="check the local development environment")
    check.add_argument("--root")
    check.add_argument("--prefix", help="installed PocoDDSRuntime/dependency prefix")
    check.add_argument("--dependency-prefix", help="separate Poco dependency install prefix")
    check.add_argument("--cmake")
    check.add_argument("--ctest")
    check.add_argument("--report")
    check.set_defaults(handler=doctor)
    verify = commands.add_parser("verify", help="configure, build and test a generated module")
    verify.add_argument("module")
    verify.add_argument("--prefix", action="append", default=[],
                        help="SDK/dependency install prefix; may be repeated")
    verify.add_argument("--poco-dir", help="directory containing PocoConfig.cmake")
    verify.add_argument("--config", default="Release")
    verify.add_argument("--generator")
    verify.add_argument("--platform")
    verify.add_argument("--cmake")
    verify.add_argument("--ctest")
    verify.add_argument("--report")
    verify.add_argument("--artifact-output",
                        help="copy generated .bndl artifacts to this directory")
    verify.set_defaults(handler=verify_module)
    config_check = commands.add_parser(
        "validate-config", help="validate layered Runtime configuration without starting services"
    )
    config_check.add_argument("configuration", nargs="+")
    config_check.add_argument("--prefix", help="installed PocoDDSRuntime prefix")
    config_check.add_argument("--executable", help="pdr-config-check executable")
    config_check.add_argument("--report")
    config_check.set_defaults(handler=validate_config)
    identity = commands.add_parser(
        "identity", help="inspect management identity sources and enforce production policy"
    )
    identity_commands = identity.add_subparsers(dest="identity_command", required=True)
    for name, help_text in (
        ("inspect", "report identity source and token-file permission diagnostics"),
        ("check", "enforce production authentication and restricted token-file access"),
    ):
        identity_command = identity_commands.add_parser(name, help=help_text)
        identity_command.add_argument("configuration", nargs="+")
        identity_command.add_argument("--prefix", help="installed PocoDDSRuntime prefix")
        identity_command.add_argument("--executable", help="pdr-identity-check executable")
        identity_command.add_argument("--report")
        identity_command.set_defaults(handler=inspect_identity)
    persistence = commands.add_parser(
        "persistence", help="inspect or recover Runtime management persistence snapshots"
    )
    persistence_commands = persistence.add_subparsers(dest="persistence_command", required=True)
    persistence_inspect = persistence_commands.add_parser(
        "inspect", help="validate current and .previous snapshots without changing them"
    )
    persistence_inspect.add_argument("path")
    persistence_inspect.add_argument("--kind", choices=tuple(PERSISTENCE_KINDS), required=True)
    persistence_inspect.add_argument("--report")
    persistence_inspect.set_defaults(handler=inspect_persistence)
    persistence_recover = persistence_commands.add_parser(
        "recover", help="offline recovery from a verified .previous snapshot"
    )
    persistence_recover.add_argument("path")
    persistence_recover.add_argument("--kind", choices=tuple(PERSISTENCE_KINDS), required=True)
    persistence_recover.add_argument("--operator", required=True,
                                     help="operator identity recorded in the audit event")
    persistence_recover.add_argument("--expected-current-sha256", required=True)
    persistence_recover.add_argument("--expected-previous-sha256", required=True)
    persistence_recover.add_argument("--confirm-runtime-stopped", action="store_true")
    persistence_recover.add_argument("--allow-healthy-current", action="store_true")
    persistence_recover.add_argument("--audit")
    persistence_recover.add_argument("--report")
    persistence_recover.set_defaults(handler=recover_persistence)
    persistence_backup = persistence_commands.add_parser(
        "backup", help="create an atomically published offline management recovery point"
    )
    persistence_backup.add_argument("--tasks", required=True)
    persistence_backup.add_argument("--idempotency", required=True)
    persistence_backup.add_argument("--configuration", required=True)
    persistence_backup.add_argument("--management-audit", required=True)
    persistence_backup.add_argument("--output", required=True)
    persistence_backup.add_argument("--operator", required=True)
    persistence_backup.add_argument("--confirm-runtime-stopped", action="store_true")
    persistence_backup.add_argument("--report")
    persistence_backup.set_defaults(handler=create_recovery_point)
    persistence_verify = persistence_commands.add_parser(
        "verify-recovery-point", help="verify a recovery point manifest and every artifact"
    )
    persistence_verify.add_argument("path")
    persistence_verify.add_argument("--report")
    persistence_verify.set_defaults(handler=verify_recovery_point)
    persistence_restore = persistence_commands.add_parser(
        "restore-recovery-point",
        help="restore a complete recovery point with pre-restore archive and rollback",
    )
    persistence_restore.add_argument("path")
    persistence_restore.add_argument("--tasks", required=True)
    persistence_restore.add_argument("--idempotency", required=True)
    persistence_restore.add_argument("--configuration", required=True)
    persistence_restore.add_argument("--management-audit", required=True)
    persistence_restore.add_argument("--archive-output", required=True)
    persistence_restore.add_argument("--operation-audit", required=True)
    persistence_restore.add_argument("--operator", required=True)
    persistence_restore.add_argument("--expected-manifest-sha256", required=True)
    persistence_restore.add_argument("--confirm-runtime-stopped", action="store_true")
    persistence_restore.add_argument("--report")
    persistence_restore.set_defaults(handler=restore_recovery_point)
    persistence_validate = persistence_commands.add_parser(
        "validate-restored-runtime",
        help="gate management writes after restore using transaction and live Runtime evidence",
    )
    persistence_validate.add_argument("--base-url", required=True)
    persistence_validate.add_argument("--restore-report", required=True)
    persistence_validate.add_argument("--operation-audit", required=True)
    persistence_validate.add_argument("--expected-restore-id", required=True)
    persistence_validate.add_argument("--operator", required=True)
    persistence_validate.add_argument("--authorization-environment")
    persistence_validate.add_argument("--dispositions")
    persistence_validate.add_argument("--timeout", type=float, default=60.0)
    persistence_validate.add_argument("--request-timeout", type=float, default=2.0)
    persistence_validate.add_argument("--poll-interval", type=float, default=0.5)
    persistence_validate.add_argument("--report")
    persistence_validate.set_defaults(handler=validate_restored_runtime)
    plugin = commands.add_parser(
        "plugin", help="preflight, install, recover or roll back a stopped-Runtime plugin"
    )
    plugin_commands = plugin.add_subparsers(dest="plugin_command", required=True)
    plugin_sign = plugin_commands.add_parser(
        "sign", help="create a publisher attestation and detached Ed25519 signature"
    )
    plugin_sign.add_argument("artifact", type=Path)
    plugin_sign.add_argument("--publisher-id", required=True)
    plugin_sign.add_argument("--key-id", required=True)
    plugin_sign.add_argument("--private-key-path-environment", required=True)
    plugin_sign.add_argument("--private-key-passphrase-environment")
    plugin_sign.add_argument("--attestation", required=True, type=Path)
    plugin_sign.add_argument("--signature", required=True, type=Path)
    plugin_sign.set_defaults(handler=sign_plugin)
    plugin_preflight = plugin_commands.add_parser(
        "preflight", help="verify archive safety, identity, digest and dependencies"
    )
    plugin_preflight.add_argument("artifact", type=Path)
    plugin_preflight.add_argument("--bundle-directory", required=True, type=Path)
    plugin_preflight.add_argument("--expected-sha256")
    plugin_preflight.add_argument("--runtime-contract", type=Path)
    add_plugin_provenance_arguments(plugin_preflight)
    plugin_preflight.add_argument("--report", type=Path)
    plugin_preflight.set_defaults(handler=preflight_plugin)
    plugin_install = plugin_commands.add_parser(
        "install", help="atomically publish an approved plugin and retain the old version"
    )
    plugin_install.add_argument("artifact", type=Path)
    plugin_install.add_argument("--bundle-directory", required=True, type=Path)
    plugin_install.add_argument("--backup-directory", type=Path)
    plugin_install.add_argument("--expected-sha256", required=True)
    plugin_install.add_argument("--runtime-contract", type=Path)
    add_plugin_provenance_arguments(plugin_install)
    plugin_install.add_argument("--confirm-runtime-stopped", action="store_true")
    plugin_install.add_argument("--audit", type=Path)
    plugin_install.add_argument("--report", type=Path)
    plugin_install.set_defaults(handler=install_plugin)
    plugin_rollback = plugin_commands.add_parser(
        "rollback", help="restore the latest approved backup with dual digest guards"
    )
    plugin_rollback.add_argument("symbolic_name")
    plugin_rollback.add_argument("--bundle-directory", required=True, type=Path)
    plugin_rollback.add_argument("--backup-directory", type=Path)
    plugin_rollback.add_argument("--expected-current-sha256", required=True)
    plugin_rollback.add_argument("--expected-backup-sha256", required=True)
    plugin_rollback.add_argument("--confirm-runtime-stopped", action="store_true")
    plugin_rollback.add_argument("--audit", type=Path)
    plugin_rollback.add_argument("--report", type=Path)
    plugin_rollback.set_defaults(handler=rollback_plugin)
    plugin_recover = plugin_commands.add_parser(
        "recover", help="reconcile an interrupted stopped-Runtime install transaction"
    )
    plugin_recover.add_argument("--bundle-directory", required=True, type=Path)
    plugin_recover.add_argument("--backup-directory", type=Path)
    plugin_recover.add_argument("--confirm-runtime-stopped", action="store_true")
    plugin_recover.add_argument("--audit", type=Path)
    plugin_recover.add_argument("--report", type=Path)
    plugin_recover.set_defaults(handler=recover_plugin)
    plugin_isolated = plugin_commands.add_parser(
        "scaffold-isolated", help="create a supervised single-plugin process deployment"
    )
    plugin_isolated.add_argument("artifact", type=Path)
    plugin_isolated.add_argument("--runtime-root", type=Path, required=True)
    plugin_isolated.add_argument("--instance-name", required=True)
    plugin_isolated.add_argument("--dependency-bundle", type=Path, action="append", default=[])
    plugin_isolated.add_argument("--approval-report", type=Path, required=True)
    plugin_isolated.add_argument("--allow-diagnostic-bypass", action="store_true")
    plugin_isolated.add_argument(
        "--launcher-path", type=Path,
        default=Path("processes/pdr-launcher/pdr-launcher.exe" if os.name == "nt" else
                     "processes/pdr-launcher/pdr-launcher"))
    plugin_isolated.add_argument(
        "--host-path", type=Path,
        default=Path("processes/pdr-plugin-host/pdr-plugin-host.exe" if os.name == "nt" else
                     "processes/pdr-plugin-host/pdr-plugin-host"))
    plugin_isolated.add_argument("--heartbeat-interval", type=int, default=1000)
    plugin_isolated.add_argument("--heartbeat-timeout", type=int, default=5000)
    plugin_isolated.add_argument("--watchdog-interval", type=int, default=500)
    plugin_isolated.add_argument("--startup-grace", type=int, default=10000)
    plugin_isolated.add_argument("--restart-delay", type=int, default=1000)
    plugin_isolated.add_argument("--max-restarts", type=int, default=5)
    plugin_isolated.add_argument("--restart-window", type=int, default=60000)
    plugin_isolated.add_argument("--memory-bytes", type=int, default=0)
    plugin_isolated.add_argument("--active-process-limit", type=int,
                                 default=1 if os.name == "nt" else 0)
    plugin_isolated.add_argument("--cpu-rate-percent", type=int, default=0)
    plugin_isolated.add_argument("--linux-cgroup-path")
    plugin_isolated.add_argument("--report", type=Path)
    plugin_isolated.set_defaults(handler=scaffold_isolated_plugin)
    plugin_isolated_apply = plugin_commands.add_parser(
        "apply-isolated", help="atomically register a scaffolded isolated plugin instance"
    )
    plugin_isolated_apply.add_argument("instance_name")
    plugin_isolated_apply.add_argument("--runtime-root", type=Path, required=True)
    plugin_isolated_apply.add_argument("--configuration", type=Path)
    plugin_isolated_apply.add_argument("--confirm-runtime-stopped", action="store_true")
    plugin_isolated_apply.add_argument("--report", type=Path)
    plugin_isolated_apply.set_defaults(handler=apply_isolated_plugin)
    plugin_isolated_list = plugin_commands.add_parser(
        "list-isolated", help="list Runtime-managed isolated plugin instances"
    )
    plugin_isolated_list.add_argument("--runtime-root", type=Path, required=True)
    plugin_isolated_list.add_argument("--configuration", type=Path)
    plugin_isolated_list.add_argument("--report", type=Path)
    plugin_isolated_list.set_defaults(handler=list_isolated_plugins)
    plugin_isolated_remove = plugin_commands.add_parser(
        "remove-isolated", help="atomically unregister an isolated plugin instance"
    )
    plugin_isolated_remove.add_argument("instance_name")
    plugin_isolated_remove.add_argument("--runtime-root", type=Path, required=True)
    plugin_isolated_remove.add_argument("--configuration", type=Path)
    plugin_isolated_remove.add_argument("--confirm-runtime-stopped", action="store_true")
    plugin_isolated_remove.add_argument("--purge", action="store_true")
    plugin_isolated_remove.add_argument("--report", type=Path)
    plugin_isolated_remove.set_defaults(handler=remove_isolated_plugin)
    release = commands.add_parser(
        "release", help="collect and enforce release qualification evidence"
    )
    release_commands = release.add_subparsers(dest="release_command", required=True)
    release_qualify = release_commands.add_parser(
        "qualify", help="combine CTest, report, artifact and external acceptance evidence"
    )
    add_release_qualification_arguments(release_qualify)
    release_qualify.set_defaults(handler=qualify_release)
    acceptance_types = EXTERNAL_ACCEPTANCE_TYPES
    release_external_template = release_commands.add_parser(
        "external-template", help="create candidate-bound external acceptance checklist"
    )
    release_external_template.add_argument("--type", choices=acceptance_types, required=True)
    release_external_template.add_argument("--version", required=True)
    release_external_template.add_argument("--git-commit", required=True)
    release_external_template.add_argument("--artifact-manifest", type=Path, required=True)
    release_external_template.add_argument(
        "--requirement", action="append", type=named_requirement, default=[]
    )
    release_external_template.add_argument("--output", type=Path, required=True)
    release_external_template.set_defaults(handler=create_external_acceptance_template)
    release_external_approve = release_commands.add_parser(
        "external-approve", help="approve a complete external checklist and bind attachments"
    )
    release_external_approve.add_argument("--template", type=Path, required=True)
    release_external_approve.add_argument("--evidence", action="append",
                                           type=named_qualification_path, default=[])
    release_external_approve.add_argument("--approver-id", required=True)
    release_external_approve.add_argument("--approval-record", required=True)
    release_external_approve.add_argument("--confirm-all-checks-passed", action="store_true")
    release_external_approve.add_argument("--output", type=Path, required=True)
    release_external_approve.add_argument("--signature-output", type=Path, required=True)
    release_external_approve.add_argument("--key-id", required=True)
    release_external_approve.add_argument("--private-key-path-environment", required=True)
    release_external_approve.add_argument("--private-key-passphrase-environment")
    release_external_approve.set_defaults(handler=approve_external_acceptance)
    release_external_verify = release_commands.add_parser(
        "external-verify", help="verify external evidence identity, integrity and attachments"
    )
    release_external_verify.add_argument("--report", type=Path, required=True)
    release_external_verify.add_argument("--type", choices=acceptance_types)
    release_external_verify.add_argument("--version")
    release_external_verify.add_argument("--git-commit")
    release_external_verify.add_argument("--artifact-manifest-sha256")
    release_external_verify.add_argument(
        "--requirement", action="append", type=named_requirement, default=[]
    )
    release_external_verify.add_argument("--signature", type=Path)
    release_external_verify.add_argument("--trust-policy", type=Path)
    release_external_verify.add_argument("--expected-trust-policy-id")
    release_external_verify.add_argument("--expected-trust-policy-sha256")
    release_external_verify.add_argument("--signature-check-executable", type=Path)
    release_external_verify.set_defaults(handler=verify_external_acceptance_command)
    release_bundle_create = release_commands.add_parser(
        "bundle-create", help="collect and sign a portable release evidence ZIP"
    )
    release_bundle_create.add_argument("--qualification", type=Path, required=True)
    release_bundle_create.add_argument("--include-artifacts", action="store_true")
    release_bundle_create.add_argument("--output", type=Path, required=True)
    release_bundle_create.add_argument("--signature-output", type=Path, required=True)
    release_bundle_create.add_argument("--key-id", required=True)
    release_bundle_create.add_argument("--private-key-path-environment", required=True)
    release_bundle_create.add_argument("--private-key-passphrase-environment")
    release_bundle_create.set_defaults(handler=create_evidence_bundle)
    release_bundle_verify = release_commands.add_parser(
        "bundle-verify", help="offline-verify a signed release evidence ZIP"
    )
    release_bundle_verify.add_argument("--bundle", type=Path, required=True)
    release_bundle_verify.add_argument("--signature", type=Path, required=True)
    release_bundle_verify.add_argument("--public-key", type=Path, required=True)
    release_bundle_verify.add_argument("--expected-key-id", required=True)
    release_bundle_verify.add_argument("--expected-public-key-sha256", required=True)
    release_bundle_verify.add_argument("--signature-check-executable", type=Path, required=True)
    release_bundle_verify.set_defaults(handler=verify_evidence_bundle)
    for command_name, help_text, handler in (
        ("pipeline-run", "run a checkpointed release stage plan", run_release_pipeline),
        ("pipeline-resume", "resume a hash-bound interrupted release plan", resume_release_pipeline),
    ):
        release_pipeline_command = release_commands.add_parser(command_name, help=help_text)
        release_pipeline_command.add_argument("--plan", type=Path, required=True)
        release_pipeline_command.add_argument("--state", type=Path, required=True)
        release_pipeline_command.add_argument("--confirm-run", action="store_true")
        release_pipeline_command.set_defaults(handler=handler)
    release_pipeline_status_command = release_commands.add_parser(
        "pipeline-status", help="show checkpointed release stage status"
    )
    release_pipeline_status_command.add_argument("--state", type=Path, required=True)
    release_pipeline_status_command.set_defaults(handler=release_pipeline_status)
    upgrade = commands.add_parser(
        "upgrade", help="transactionally install, recover or roll back a Runtime release"
    )
    upgrade_commands = upgrade.add_subparsers(dest="upgrade_command", required=True)
    upgrade_preflight = upgrade_commands.add_parser(
        "preflight", help="validate an upgrade without modifying the target"
    )
    upgrade_preflight.add_argument("--package", type=Path, required=True)
    upgrade_preflight.add_argument("--manifest", type=Path, required=True)
    upgrade_preflight.add_argument("--target", type=Path, required=True)
    upgrade_preflight.add_argument("--report", type=Path)
    upgrade_preflight.add_argument("--signature", type=Path)
    upgrade_preflight.add_argument("--trusted-key-environment")
    upgrade_preflight.add_argument("--expected-key-id")
    upgrade_preflight.add_argument("--public-key", type=Path)
    upgrade_preflight.add_argument("--expected-public-key-sha256")
    upgrade_preflight.add_argument("--signature-check-executable", type=Path)
    upgrade_preflight.add_argument("--allow-unsigned-release", action="store_true")
    upgrade_preflight.add_argument("--trust-policy", type=Path)
    upgrade_preflight.add_argument("--expected-trust-policy-id")
    upgrade_preflight.add_argument("--expected-trust-policy-sha256")
    upgrade_preflight.add_argument("--allow-unmanaged-trust", action="store_true")
    upgrade_preflight.add_argument("--min-free-bytes", type=int, default=64 * 1024 * 1024)
    upgrade_preflight.add_argument("--allow-initial-install", action="store_true")
    upgrade_preflight.add_argument("--allow-major-upgrade", action="store_true")
    upgrade_preflight.add_argument("--allow-development-release", action="store_true")
    upgrade_preflight.set_defaults(handler=preflight_runtime_upgrade)
    upgrade_apply = upgrade_commands.add_parser(
        "apply", help="verify, stage, activate and validate a release"
    )
    upgrade_apply.add_argument("--package", type=Path, required=True)
    upgrade_apply.add_argument("--manifest", type=Path, required=True)
    upgrade_apply.add_argument("--target", type=Path, required=True)
    upgrade_apply.add_argument("--audit", type=Path, required=True)
    upgrade_apply.add_argument("--signature", type=Path)
    upgrade_apply.add_argument("--trusted-key-environment")
    upgrade_apply.add_argument("--expected-key-id")
    upgrade_apply.add_argument("--public-key", type=Path)
    upgrade_apply.add_argument("--expected-public-key-sha256")
    upgrade_apply.add_argument("--signature-check-executable", type=Path)
    upgrade_apply.add_argument("--allow-unsigned-release", action="store_true")
    upgrade_apply.add_argument("--trust-policy", type=Path)
    upgrade_apply.add_argument("--expected-trust-policy-id")
    upgrade_apply.add_argument("--expected-trust-policy-sha256")
    upgrade_apply.add_argument("--allow-unmanaged-trust", action="store_true")
    upgrade_apply.add_argument("--health-file")
    upgrade_apply.add_argument("--health-url")
    upgrade_apply.add_argument("--health-body-pattern")
    upgrade_apply.add_argument("--health-command")
    upgrade_apply.add_argument("--health-command-arg", action="append", default=[])
    upgrade_apply.add_argument("--health-timeout", type=float, default=30.0)
    upgrade_apply.add_argument("--skip-health-check", action="store_true")
    upgrade_apply.add_argument("--min-free-bytes", type=int, default=64 * 1024 * 1024)
    upgrade_apply.add_argument("--keep-backups", type=int, default=2)
    upgrade_apply.add_argument("--rename-timeout", type=float, default=5.0)
    upgrade_apply.add_argument("--allow-initial-install", action="store_true")
    upgrade_apply.add_argument("--allow-major-upgrade", action="store_true")
    upgrade_apply.add_argument("--allow-development-release", action="store_true")
    upgrade_apply.set_defaults(handler=apply_runtime_upgrade)
    upgrade_rollback = upgrade_commands.add_parser(
        "rollback", help="restore the latest completed upgrade backup"
    )
    upgrade_rollback.add_argument("--target", type=Path, required=True)
    upgrade_rollback.add_argument("--audit", type=Path, required=True)
    upgrade_rollback.add_argument("--rename-timeout", type=float, default=5.0)
    upgrade_rollback.set_defaults(handler=rollback_runtime_upgrade)
    upgrade_recover = upgrade_commands.add_parser(
        "recover", help="fail closed and recover an interrupted upgrade transaction"
    )
    upgrade_recover.add_argument("--target", type=Path, required=True)
    upgrade_recover.add_argument("--rename-timeout", type=float, default=5.0)
    upgrade_recover.set_defaults(handler=recover_runtime_upgrade)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
