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


KINDS = ("module", "service", "device", "workflow", "bundle", "plugin", "subprocess")
PERSISTENCE_KINDS = {"tasks": "tasks", "idempotency": "requests"}


def tool_root() -> Path:
    return Path(__file__).resolve().parents[1]


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
    namespace = f"PocoDDS::Generated::{name}"
    symbolic = f"pdr.plugin.{lowered}"
    cmake = f'''cmake_minimum_required(VERSION 3.24)
project({name}Plugin LANGUAGES CXX)
find_package(PocoDDSRuntime 0.1 CONFIG REQUIRED COMPONENTS Plugins)
include(CTest)

add_library({name}Core STATIC src/StatusService.cpp)
set_target_properties({name}Core PROPERTIES POSITION_INDEPENDENT_CODE ON)
target_include_directories({name}Core PUBLIC
    $<BUILD_INTERFACE:${{CMAKE_CURRENT_SOURCE_DIR}}/include>)
target_link_libraries({name}Core PUBLIC PocoDDS::Plugins)

pdr_add_osp_bundle({name}Bundle
    SYMBOLIC_NAME {symbolic}
    BUNDLE_SPEC ${{CMAKE_CURRENT_SOURCE_DIR}}/{name}.bndlspec
    SOURCES ${{CMAKE_CURRENT_SOURCE_DIR}}/src/BundleActivator.cpp
    LINK_LIBS {name}Core
    INCLUDE_DIRS ${{CMAKE_CURRENT_SOURCE_DIR}}/include)

if(BUILD_TESTING)
    add_executable({name}Smoke tests/{name}Smoke.cpp)
    target_link_libraries({name}Smoke PRIVATE {name}Core)
    add_test(NAME {lowered}-plugin-smoke COMMAND {name}Smoke)
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


def subprocess_templates(name: str) -> dict[str, str]:
    target = "pdr-" + re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()
    cmake = f'''cmake_minimum_required(VERSION 3.24)
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
    project({name}Subprocess LANGUAGES CXX)
    find_package(PocoDDSRuntime 0.1 CONFIG REQUIRED)
    include(CTest)
endif()

add_executable({target} src/main.cpp)
target_link_libraries({target} PRIVATE PocoDDS::SDK)
if(DEFINED PDR_SUBPROCESS_OUTPUT_ROOT)
    set({name}_OUTPUT_ROOT "${{PDR_SUBPROCESS_OUTPUT_ROOT}}")
else()
    set({name}_OUTPUT_ROOT "${{CMAKE_BINARY_DIR}}/processes")
endif()
set_target_properties({target} PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${{{name}_OUTPUT_ROOT}}/{target}")
if(CMAKE_CONFIGURATION_TYPES)
    foreach(configuration IN LISTS CMAKE_CONFIGURATION_TYPES)
        string(TOUPPER "${{configuration}}" configuration_upper)
        set_target_properties({target} PROPERTIES
            RUNTIME_OUTPUT_DIRECTORY_${{configuration_upper}}
                "${{{name}_OUTPUT_ROOT}}/{target}")
    endforeach()
endif()

if(BUILD_TESTING)
    add_test(NAME {target}-self-test COMMAND {target} --self-test)
endif()

install(TARGETS {target}
    RUNTIME DESTINATION "bin/processes/{target}")
install(FILES config/pdr-subprocess-entry.properties
    DESTINATION "share/PocoDDSRuntime/subprocesses/{target}")
'''
    source = f'''#include <PocoDDS/SDK/SDK.h>

#include <atomic>
#include <chrono>
#include <csignal>
#include <iostream>
#include <string_view>
#include <thread>

namespace
{{
std::atomic_bool running{{true}};

void requestStop(int)
{{
    running.store(false);
}}
}}

int main(int argc, char** argv)
{{
    for (int index = 1; index < argc; ++index)
    {{
        if (std::string_view(argv[index]) == "--self-test")
        {{
            std::cout << "{target.upper().replace('-', '_')}_SELF_TEST_PASS sdk="
                      << PocoDDS::SDK::versionString << '\\n';
            return 0;
        }}
    }}

    std::signal(SIGINT, requestStop);
    std::signal(SIGTERM, requestStop);
    std::cout << "{target.upper().replace('-', '_')}_READY" << std::endl;
    while (running.load())
    {{
        std::cout << "{target.upper().replace('-', '_')}_HEARTBEAT" << std::endl;
        std::this_thread::sleep_for(std::chrono::seconds(1));
    }}
    std::cout << "{target.upper().replace('-', '_')}_STOPPED" << std::endl;
    return 0;
}}
'''
    configuration = f'''# Merge this block into pdr-subprocesses.properties and replace N with
# the next contiguous numeric slot. Paths are relative to the Runtime bin directory.
subprocess.N.enabled = true
subprocess.N.name = {target}
subprocess.N.location = local
subprocess.N.required = false
subprocess.N.path = processes/{target}/{target}{'.exe' if os.name == 'nt' else ''}
subprocess.N.workingDirectory = processes/{target}
subprocess.N.argument.count = 0
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
    if kind in ("bundle", "plugin"):
        return plugin_templates(name, kind)
    if kind == "subprocess":
        return subprocess_templates(name)
    namespace = f"PocoDDS::Generated::{name}"
    common_cmake = f'''cmake_minimum_required(VERSION 3.24)
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
    project({name} LANGUAGES CXX)
    find_package(PocoDDSRuntime 0.1 CONFIG REQUIRED COMPONENTS SDK)
    include(CTest)
endif()

add_library({name} src/{name}.cpp)
target_include_directories({name} PUBLIC
    $<BUILD_INTERFACE:${{CMAKE_CURRENT_SOURCE_DIR}}/include>
    $<INSTALL_INTERFACE:include>)
target_link_libraries({name} PUBLIC PocoDDS::SDK)

if(BUILD_TESTING)
    add_executable({name}Smoke tests/{name}Smoke.cpp)
    target_link_libraries({name}Smoke PRIVATE {name})
    add_test(NAME {name.lower()}-smoke COMMAND {name}Smoke)
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


def create_module(args: argparse.Namespace) -> int:
    destination = Path(args.output).resolve() / args.name
    if destination.exists() and any(destination.iterdir()) and not args.force:
        print(f"error: destination is not empty: {destination}", file=sys.stderr)
        return 2
    destination.mkdir(parents=True, exist_ok=True)
    for relative, content in templates(args.kind, args.name).items():
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and not args.force:
            print(f"error: file already exists: {path}", file=sys.stderr)
            return 2
        path.write_text(content, encoding="utf-8", newline="\n")
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
    except (FileNotFoundError, OSError) as error:
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
    new = commands.add_parser("new", help="create a framework module")
    new.add_argument("kind", choices=KINDS)
    new.add_argument("name", type=valid_name)
    new.add_argument("--output", default="generated")
    new.add_argument("--force", action="store_true")
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
    acceptance_types = ("petalinux-target", "physical-protocols", "production-identity",
                        "site-network", "soak-24h", "soak-72h")
    release_external_template = release_commands.add_parser(
        "external-template", help="create candidate-bound external acceptance checklist"
    )
    release_external_template.add_argument("--type", choices=acceptance_types, required=True)
    release_external_template.add_argument("--version", required=True)
    release_external_template.add_argument("--git-commit", required=True)
    release_external_template.add_argument("--artifact-manifest", type=Path, required=True)
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
