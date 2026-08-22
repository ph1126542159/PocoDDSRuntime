#!/usr/bin/env python3
"""Create, validate and resolve deterministic PocoDDSRuntime product projects."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
PROFILE_MODELS = {
    "desktop-lite": {"host": "static", "transports": ["inproc"]},
    "desktop-distributed": {
        "host": "desktop", "transports": ["inproc", "ipc", "http", "websocket"],
    },
    "embedded": {
        "host": "service", "transports": ["inproc", "fastdds", "modbus", "can", "serial"],
    },
    "edge-industrial": {
        "host": "osp",
        "transports": ["inproc", "http", "mqtt", "fastdds", "modbus", "can", "serial"],
    },
    "edge-test": {
        "host": "osp",
        "transports": ["inproc", "http", "websocket", "mqtt", "fastdds", "modbus", "can", "serial"],
    },
    "server": {
        "host": "osp", "transports": ["inproc", "http", "websocket", "mqtt", "fastdds"],
    },
    "robotics": {"host": "robotics", "transports": ["inproc", "ros2"]},
}
PROFILES = set(PROFILE_MODELS)
HOST_MODELS = {"static", "desktop", "osp", "service", "robotics"}
TRANSPORTS = {
    "inproc", "ipc", "http", "websocket", "grpc", "mqtt", "fastdds", "ros2",
    "modbus", "can", "serial",
}
BACKENDS = {"in_memory", "mock_hardware", "topic_simulation", "topic_hardware"}
COMPONENT_LISTS = {
    "robotModules", "robotProcesses", "modules", "services", "devices", "workflows",
    "bundles", "subprocesses", "webBundles",
}
ADAPTER_LISTS = {"hardware", "simulation", "ros2"}
ROBOTICS_COMPONENT_LISTS = {"robotModules", "robotProcesses"}
APPLICATION_COMPONENT_LISTS = {"modules", "services"}
MANAGEMENT_COMPONENT_LISTS = {"devices", "workflows", "bundles", "subprocesses"}
COMPONENT_KIND_FIELDS = {
    "robot-module": ("robotModules",),
    "robot-process": ("robotProcesses",),
    "robot-hardware-adapter": ("adapters", "hardware"),
    "robot-simulation-adapter": ("adapters", "simulation"),
    "ros2-node": ("adapters", "ros2"),
    "module": ("modules",),
    "service": ("services",),
    "device": ("devices",),
    "workflow": ("workflows",),
    "bundle": ("bundles",),
    "plugin": ("bundles",),
    "subprocess": ("subprocesses",),
    "web-bundle": ("webBundles",),
}
COMPONENT_FIELD_KINDS = {
    "robotModules": {"robot-module"},
    "robotProcesses": {"robot-process"},
    "modules": {"module"},
    "services": {"service"},
    "devices": {"device"},
    "workflows": {"workflow"},
    "bundles": {"bundle", "plugin"},
    "subprocesses": {"subprocess"},
    "webBundles": set(),
    "hardware": {"robot-hardware-adapter"},
    "simulation": {"robot-simulation-adapter"},
    "ros2": {"ros2-node"},
}
IGNORED_TREE_PARTS = {
    ".git", "build", "install", "__pycache__", ".pytest_cache",
    "template-backups", "template-conflicts",
}
COMPOSITION_FILE = "pdr-project.components.cmake"


def slugify(name: str) -> str:
    value = re.sub(r"(?<!^)(?=[A-Z])", "-", name).replace("_", "-").lower()
    value = re.sub(r"[^a-z0-9-]+", "-", value).strip("-")
    if not value or not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", value):
        raise ValueError("project name must produce a lowercase kebab-case identifier")
    return value


def atomic_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def load_manifest(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        document = json.loads(text)
    except json.JSONDecodeError as json_error:
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError as error:
            raise ValueError(
                "pdr-project.yaml must use JSON-compatible YAML when PyYAML is unavailable"
            ) from json_error
        try:
            document = yaml.safe_load(text)
        except Exception as error:  # PyYAML exposes multiple parser exception types.
            raise ValueError(f"cannot parse project manifest: {error}") from error
    if not isinstance(document, dict):
        raise ValueError("project manifest root must be an object")
    return document


def safe_relative_path(value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} entries must be non-empty strings")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field} contains an unsafe path: {value}")
    return path


def require_string(document: dict[str, Any], key: str, field: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def validate_string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    result: list[str] = []
    for item in value:
        path = safe_relative_path(item, field).as_posix()
        if path in result:
            raise ValueError(f"{field} contains duplicate entry: {path}")
        result.append(path)
    return result


def validate_runtime_transports(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError("runtime.transports must be a non-empty array")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or item not in TRANSPORTS:
            raise ValueError(
                "runtime.transports entries must be one of: " + ", ".join(sorted(TRANSPORTS))
            )
        if item in result:
            raise ValueError(f"runtime.transports contains duplicate entry: {item}")
        result.append(item)
    if "inproc" not in result:
        raise ValueError("runtime.transports must include inproc for local Service delivery")
    return result


def validate_manifest(path: Path, check_paths: bool = True) -> dict[str, Any]:
    manifest = path.resolve()
    if not manifest.is_file():
        raise FileNotFoundError(f"project manifest not found: {manifest}")
    document = load_manifest(manifest)
    allowed = {"schemaVersion", "name", "displayName", "version", "runtime", "robot", "components",
               "config", "acceptance", "dependencies", "template"}
    unknown = sorted(set(document) - allowed)
    if unknown:
        raise ValueError("unknown project manifest fields: " + ", ".join(unknown))
    if document.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError(f"schemaVersion must be {SCHEMA_VERSION}")
    name = require_string(document, "name", "name")
    if slugify(name) != name:
        raise ValueError("name must already be lowercase kebab-case")
    require_string(document, "displayName", "displayName")
    project_version = document.get("version")
    if project_version is not None:
        if (not isinstance(project_version, str) or not re.fullmatch(
                r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", project_version)):
            raise ValueError("version must be a concrete semantic version")

    template = document.get("template")
    normalized_template: dict[str, Any] | None = None
    if template is not None:
        if not isinstance(template, dict) or set(template) != {"id", "version"}:
            raise ValueError("template must contain only id and version")
        template_id = require_string(template, "id", "template.id")
        if slugify(template_id) != template_id:
            raise ValueError("template.id must be lowercase kebab-case")
        template_version = template.get("version")
        if (not isinstance(template_version, int) or isinstance(template_version, bool)
                or template_version < 1):
            raise ValueError("template.version must be a positive integer")
        normalized_template = {"id": template_id, "version": template_version}

    runtime = document.get("runtime")
    if not isinstance(runtime, dict):
        raise ValueError("runtime must be an object")
    if set(runtime) - {"profile", "version", "host", "transports"}:
        raise ValueError("runtime contains unknown fields")
    profile = require_string(runtime, "profile", "runtime.profile")
    if profile not in PROFILES:
        raise ValueError("runtime.profile must be one of: " + ", ".join(sorted(PROFILES)))
    version = require_string(runtime, "version", "runtime.version")
    if not re.fullmatch(r"\d+\.\d+\.(?:\d+|x)(?:[-+][0-9A-Za-z.-]+)?", version):
        raise ValueError("runtime.version must be a semantic version or patch wildcard")
    defaults = PROFILE_MODELS[profile]
    host = runtime.get("host", defaults["host"])
    if host not in HOST_MODELS:
        raise ValueError("runtime.host must be one of: " + ", ".join(sorted(HOST_MODELS)))
    transports = validate_runtime_transports(runtime.get("transports", defaults["transports"]))
    if profile == "desktop-lite" and (host != "static" or transports != ["inproc"]):
        raise ValueError("desktop-lite requires host=static and transports=[inproc]")
    if profile == "robotics" and host != "robotics":
        raise ValueError("robotics profile requires runtime.host=robotics")

    robot = document.get("robot")
    normalized_robot: dict[str, Any] | None = None
    if robot is not None:
        if not isinstance(robot, dict):
            raise ValueError("robot must be an object when present")
        if set(robot) - {"model", "backend", "controlPeriodMs"}:
            raise ValueError("robot contains unknown fields")
        model = require_string(robot, "model", "robot.model")
        backend = require_string(robot, "backend", "robot.backend")
        if backend not in BACKENDS:
            raise ValueError("robot.backend must be one of: " + ", ".join(sorted(BACKENDS)))
        control_period = robot.get("controlPeriodMs")
        if (not isinstance(control_period, int) or isinstance(control_period, bool)
                or not 1 <= control_period <= 1000):
            raise ValueError("robot.controlPeriodMs must be an integer from 1 to 1000")
        normalized_robot = {"model": model, "backend": backend,
                            "controlPeriodMs": control_period}
    if profile == "robotics" and normalized_robot is None:
        raise ValueError("robot is required when runtime.profile is robotics")

    components = document.get("components")
    if not isinstance(components, dict):
        raise ValueError("components must be an object")
    if set(components) - (COMPONENT_LISTS | {"adapters"}):
        raise ValueError("components contains unknown fields")
    normalized_components: dict[str, Any] = {}
    for field in sorted(COMPONENT_LISTS):
        normalized_components[field] = validate_string_list(components.get(field, []),
                                                            f"components.{field}")
    adapters = components.get("adapters", {})
    if not isinstance(adapters, dict) or set(adapters) - ADAPTER_LISTS:
        raise ValueError("components.adapters must contain only hardware, simulation and ros2")
    normalized_components["adapters"] = {
        field: validate_string_list(adapters.get(field, []), f"components.adapters.{field}")
        for field in sorted(ADAPTER_LISTS)
    }
    if normalized_components["adapters"]["ros2"] and "ros2" not in transports:
        raise ValueError("registered ROS 2 adapters require runtime.transports to include ros2")
    if profile == "desktop-lite":
        unsupported = sorted(
            field for field in MANAGEMENT_COMPONENT_LISTS
            if normalized_components[field]
        )
        if unsupported:
            raise ValueError(
                "desktop-lite supports modules and services only; use desktop-distributed "
                "or an OSP profile for: " + ", ".join(unsupported)
            )
    all_component_paths = [
        relative for field in sorted(COMPONENT_LISTS)
        for relative in normalized_components[field]
    ] + [
        relative for field in sorted(ADAPTER_LISTS)
        for relative in normalized_components["adapters"][field]
    ]
    duplicate_paths = sorted({relative for relative in all_component_paths
                              if all_component_paths.count(relative) > 1})
    if duplicate_paths:
        raise ValueError("component paths must be globally unique: " + ", ".join(duplicate_paths))

    config = document.get("config")
    if not isinstance(config, dict) or set(config) - {
            "version", "layers", "migrations", "capabilities"}:
        raise ValueError(
            "config must contain only version, layers, migrations and capabilities"
        )
    config_version = config.get("version")
    if (not isinstance(config_version, int) or isinstance(config_version, bool)
            or config_version < 1):
        raise ValueError("config.version must be a positive integer")
    layers = validate_string_list(config.get("layers", []), "config.layers")
    if not layers:
        raise ValueError("config.layers must contain at least one layer")
    migrations = safe_relative_path(config.get("migrations"), "config.migrations").as_posix()
    capabilities_value = config.get("capabilities")
    capabilities = (
        safe_relative_path(capabilities_value, "config.capabilities").as_posix()
        if capabilities_value is not None else None
    )

    acceptance = document.get("acceptance")
    if not isinstance(acceptance, dict):
        raise ValueError("acceptance must be an object")
    if set(acceptance) - {"unit", "sil", "hil", "soakHours"}:
        raise ValueError("acceptance contains unknown fields")
    for field in ("unit", "sil", "hil"):
        if not isinstance(acceptance.get(field), bool):
            raise ValueError(f"acceptance.{field} must be boolean")
    soak_hours = acceptance.get("soakHours")
    if not isinstance(soak_hours, int) or isinstance(soak_hours, bool) or soak_hours < 0:
        raise ValueError("acceptance.soakHours must be a non-negative integer")

    dependencies = document.get("dependencies")
    if not isinstance(dependencies, list):
        raise ValueError("dependencies must be an array")
    normalized_dependencies: list[dict[str, Any]] = []
    dependency_names: set[str] = set()
    for index, dependency in enumerate(dependencies):
        field = f"dependencies[{index}]"
        if not isinstance(dependency, dict):
            raise ValueError(f"{field} must be an object")
        if set(dependency) - {"name", "version", "license", "download", "scope", "optional"}:
            raise ValueError(f"{field} contains unknown fields")
        dependency_name = require_string(dependency, "name", f"{field}.name")
        if dependency_name in dependency_names:
            raise ValueError(f"duplicate dependency name: {dependency_name}")
        dependency_names.add(dependency_name)
        dependency_version = require_string(dependency, "version", f"{field}.version")
        dependency_license = require_string(dependency, "license", f"{field}.license")
        dependency_download = require_string(dependency, "download", f"{field}.download")
        dependency_scope = dependency.get("scope", "runtime")
        if dependency_scope not in {"runtime", "build", "test"}:
            raise ValueError(f"{field}.scope must be runtime, build or test")
        optional = dependency.get("optional", False)
        if not isinstance(optional, bool):
            raise ValueError(f"{field}.optional must be boolean")
        normalized_dependencies.append({
            "name": dependency_name, "version": dependency_version,
            "license": dependency_license, "download": dependency_download,
            "scope": dependency_scope, "optional": optional,
        })
    normalized_dependencies.sort(key=lambda item: item["name"].casefold())

    root = manifest.parent
    referenced: list[str] = []
    for field in sorted(COMPONENT_LISTS):
        referenced.extend(normalized_components[field])
    for field in sorted(ADAPTER_LISTS):
        referenced.extend(normalized_components["adapters"][field])
    referenced.extend(layers)
    referenced.append(migrations)
    if capabilities is not None:
        referenced.append(capabilities)
    if check_paths:
        for relative in referenced:
            candidate = (root / relative).resolve()
            try:
                candidate.relative_to(root)
            except ValueError as error:
                raise ValueError(f"referenced path escapes project root: {relative}") from error
            if not candidate.exists():
                raise ValueError(f"referenced project path does not exist: {relative}")

        for relative in [*layers, migrations]:
            if not (root / relative).is_dir():
                raise ValueError(f"configuration path must be a directory: {relative}")
        if capabilities is not None and not (root / capabilities).is_file():
            raise ValueError(f"configuration capabilities must be a file: {capabilities}")

        cmake_component_fields = COMPONENT_LISTS - {"webBundles"}
        for field in sorted(COMPONENT_LISTS - {"webBundles"}):
            for relative in normalized_components[field]:
                candidate = root / relative
                if field in cmake_component_fields and not (candidate / "CMakeLists.txt").is_file():
                    raise ValueError(
                        f"components.{field} entry must contain CMakeLists.txt: {relative}"
                    )
        for field in ("hardware", "simulation"):
            for relative in normalized_components["adapters"][field]:
                if not (root / relative / "CMakeLists.txt").is_file():
                    raise ValueError(
                        f"components.adapters.{field} entry must contain CMakeLists.txt: {relative}"
                    )
        for relative in normalized_components["adapters"]["ros2"]:
            candidate = root / relative
            required = [name for name in ("CMakeLists.txt", "package.xml")
                        if not (candidate / name).is_file()]
            if required:
                raise ValueError(
                    "components.adapters.ros2 entry is missing "
                    + ", ".join(required) + f": {relative}"
                )
        for relative in normalized_components["webBundles"]:
            candidate = root / relative
            if not any((candidate / name).is_file()
                       for name in ("CMakeLists.txt", "package.json")):
                raise ValueError(
                    "components.webBundles entry must contain CMakeLists.txt or package.json: "
                    + relative
                )

        import component_template

        for field in sorted(COMPONENT_LISTS):
            for relative in normalized_components[field]:
                state = component_template.require_current_clean(root / relative)
                if state is not None and state["kind"] not in COMPONENT_FIELD_KINDS[field]:
                    raise ValueError(
                        f"component template kind {state['kind']} does not match "
                        f"components.{field}: {relative}"
                    )
        for field in sorted(ADAPTER_LISTS):
            for relative in normalized_components["adapters"][field]:
                state = component_template.require_current_clean(root / relative)
                if state is not None and state["kind"] not in COMPONENT_FIELD_KINDS[field]:
                    raise ValueError(
                        f"component template kind {state['kind']} does not match "
                        f"components.adapters.{field}: {relative}"
                    )

    return {
        "schemaVersion": SCHEMA_VERSION,
        "name": name,
        "displayName": document["displayName"],
        "runtime": {"profile": profile, "version": version, "host": host,
                    "transports": transports},
        "components": normalized_components,
        "config": {
            "version": config_version, "layers": layers, "migrations": migrations,
        } | ({"capabilities": capabilities} if capabilities is not None else {}),
        "acceptance": {"unit": acceptance["unit"], "sil": acceptance["sil"],
                       "hil": acceptance["hil"], "soakHours": soak_hours},
        "dependencies": normalized_dependencies,
    } | ({"version": project_version} if project_version is not None else {}) \
        | ({"robot": normalized_robot} if normalized_robot is not None else {}) \
        | ({"template": normalized_template} if normalized_template is not None else {})


def tree_digest(root: Path, excluded: set[Path] | None = None) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    excluded = {path.resolve() for path in (excluded or set())}
    if not root.exists():
        return digest.hexdigest(), count
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.resolve() in excluded or path.with_name(path.name.removesuffix(".tmp")).resolve() in excluded:
            continue
        relative = path.relative_to(root)
        if any(part in IGNORED_TREE_PARTS for part in relative.parts):
            continue
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
        count += 1
    return digest.hexdigest(), count


def cmake_bracket(value: str) -> str:
    """Return one injection-safe CMake bracket argument."""
    marker = "="
    while f"]{marker}]" in value:
        marker += "="
    return f"[{marker}[{value}]{marker}]"


def composition_lines(project: dict[str, Any], manifest_sha256: str) -> list[str]:
    lines = [
        "# Generated by pdr project sync. Do not edit by hand.",
        f'set(PDR_PROJECT_MANIFEST_SHA256 "{manifest_sha256}")',
        f'set(PDR_PROJECT_PROFILE "{project["runtime"]["profile"]}")',
        f'set(PDR_PROJECT_HOST_MODEL "{project["runtime"]["host"]}")',
        'set(PDR_PROJECT_TRANSPORTS ' + " ".join(
            f'"{item}"' for item in project["runtime"]["transports"]
        ) + ')',
        'file(SHA256 "${CMAKE_CURRENT_LIST_DIR}/pdr-project.yaml" _pdr_manifest_sha256)',
        'if(NOT _pdr_manifest_sha256 STREQUAL PDR_PROJECT_MANIFEST_SHA256)',
        '    message(FATAL_ERROR "pdr-project.yaml changed; run: pdr project sync pdr-project.yaml")',
        "endif()",
        "unset(_pdr_manifest_sha256)",
        "",
        "function(pdr_add_manifest_component relative category ordinal)",
        '    set(source "${CMAKE_CURRENT_LIST_DIR}/${relative}")',
        '    if(NOT EXISTS "${source}/CMakeLists.txt")',
        '        message(FATAL_ERROR "Manifest component is missing CMakeLists.txt: ${relative}")',
        "    endif()",
        '    get_filename_component(name "${source}" NAME)',
        '    add_subdirectory("${source}"',
        '        "${CMAKE_CURRENT_BINARY_DIR}/components/${category}/${ordinal}-${name}")',
        "endfunction()",
        "",
    ]

    def append_group(condition: str, fields: set[str]) -> None:
        lines.append(f"if({condition})")
        ordinal = 0
        for field in sorted(fields):
            for relative in project["components"][field]:
                ordinal += 1
                lines.append(
                    f"    pdr_add_manifest_component({cmake_bracket(relative)} "
                    f"{cmake_bracket(field)} {ordinal:03d})"
                )
        if ordinal == 0:
            lines.append("    # No registered components in this plane.")
        lines.extend(["endif()", ""])

    append_group("PDR_PROJECT_BUILD_ROBOTICS", ROBOTICS_COMPONENT_LISTS)
    lines.append("if(PDR_PROJECT_BUILD_ROBOTICS)")
    adapter_ordinal = 0
    for field in ("hardware", "simulation"):
        for relative in project["components"]["adapters"][field]:
            adapter_ordinal += 1
            lines.append(
                f"    pdr_add_manifest_component({cmake_bracket(relative)} "
                f"{cmake_bracket(field)} {adapter_ordinal:03d})"
            )
    if adapter_ordinal == 0:
        lines.append("    # No registered in-process robotics adapters.")
    lines.extend(["endif()", ""])
    append_group("PDR_PROJECT_BUILD_APPLICATION", APPLICATION_COMPONENT_LISTS)
    append_group("PDR_PROJECT_BUILD_MANAGEMENT", MANAGEMENT_COMPONENT_LISTS)
    lines.append("unset(_pdr_project_root)")
    return lines


def write_composition_file(manifest: Path, output: Path | None = None) -> Path:
    manifest = manifest.resolve()
    project = validate_manifest(manifest, check_paths=True)
    destination = (output or manifest.with_name(COMPOSITION_FILE)).resolve()
    try:
        destination.relative_to(manifest.parent)
    except ValueError as error:
        raise ValueError("composition output must stay inside the project root") from error
    content = "\n".join(
        composition_lines(project, hashlib.sha256(manifest.read_bytes()).hexdigest())
    ) + "\n"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(destination)
    return destination


def component_field(project: dict[str, Any], kind: str) -> list[str]:
    route = COMPONENT_KIND_FIELDS.get(kind)
    if route is None:
        raise ValueError("unsupported project component kind: " + kind)
    current: Any = project["components"]
    for part in route:
        current = current[part]
    return current


def normalized_project_path(manifest: Path, value: str | Path) -> str:
    root = manifest.resolve().parent
    supplied = Path(value)
    candidate = supplied.resolve() if supplied.is_absolute() else (root / supplied).resolve()
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise ValueError(f"component path escapes project root: {value}") from error
    return safe_relative_path(relative.as_posix(), "component path").as_posix()


def register_component_path(manifest: Path, kind: str, path: str | Path,
                            allow_existing: bool = False) -> str:
    manifest = manifest.resolve()
    project = validate_manifest(manifest, check_paths=True)
    relative = normalized_project_path(manifest, path)
    target = component_field(project, kind)
    if relative in target:
        if allow_existing:
            write_composition_file(manifest)
            return relative
        raise ValueError(f"component is already registered: {relative}")
    target.append(relative)
    target.sort()
    atomic_json(manifest, project)
    try:
        validate_manifest(manifest, check_paths=True)
        write_composition_file(manifest)
    except Exception:
        target.remove(relative)
        atomic_json(manifest, project)
        raise
    return relative


def unregister_component_path(manifest: Path, kind: str, path: str | Path) -> str:
    manifest = manifest.resolve()
    project = validate_manifest(manifest, check_paths=True)
    relative = normalized_project_path(manifest, path)
    target = component_field(project, kind)
    if relative not in target:
        raise ValueError(f"component is not registered: {relative}")
    target.remove(relative)
    atomic_json(manifest, project)
    write_composition_file(manifest)
    return relative


def create_project(args: Any) -> int:
    import project_template

    output = Path(args.output).resolve()
    slug = slugify(args.name)
    destination = output / args.name
    if destination.exists() and any(destination.iterdir()) and not args.force:
        raise FileExistsError(f"project destination is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    directories = (
        "modules", "services", "devices", "workflows", "bundles", "processes", "webui",
        "adapters/hardware", "adapters/simulation", "adapters/ros2",
        "config/base", "config/robot", "config/site", "config/migrations",
        "tests/unit", "tests/sil", "tests/hil", "deploy",
    )
    for relative in directories:
        directory = destination / relative
        directory.mkdir(parents=True, exist_ok=True)
        keep = directory / ".gitkeep"
        if not keep.exists() or args.force:
            keep.write_text("", encoding="utf-8")

    manifest: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "name": slug,
        "displayName": args.name,
        "version": args.version,
        "runtime": {
            "profile": args.profile,
            "version": args.runtime_version,
            "host": PROFILE_MODELS[args.profile]["host"],
            "transports": PROFILE_MODELS[args.profile]["transports"],
        },
        "template": {
            "id": project_template.TEMPLATE_ID,
            "version": project_template.CURRENT_TEMPLATE_VERSION,
        },
        "components": {
            "robotModules": [], "robotProcesses": [],
            "modules": [], "services": [], "devices": [], "workflows": [],
            "adapters": {"hardware": [], "simulation": [], "ros2": []},
            "bundles": [], "subprocesses": [], "webBundles": [],
        },
        "config": {"version": 1, "layers": ["config/base", "config/robot", "config/site"],
                   "migrations": "config/migrations",
                   "capabilities": "config/capabilities.json"},
        "acceptance": {"unit": True, "sil": True, "hil": False, "soakHours": 0},
        "dependencies": [],
    }
    if args.profile == "robotics":
        manifest["robot"] = {"model": slug, "backend": "in_memory", "controlPeriodMs": 5}
    atomic_json(destination / "pdr-project.yaml", manifest)
    files = project_template.render_template(
        manifest, project_template.CURRENT_TEMPLATE_VERSION
    ) | {
        "config/base/project.json": json.dumps({
            "version": 1,
            "values": {"runtime": {
                "profile": args.profile,
                "host": PROFILE_MODELS[args.profile]["host"],
                "transports": PROFILE_MODELS[args.profile]["transports"],
            }},
        }, indent=2) + "\n",
        "config/robot/project.json": json.dumps({
            "version": 1,
            "values": ({"robot": {"model": slug, "backend": "in_memory",
                                    "controlPeriodMs": 5}}
                       if args.profile == "robotics" else {}),
        }, indent=2) + "\n",
        "config/site/project.json": json.dumps({"version": 1, "values": {}}, indent=2) + "\n",
        "config/capabilities.json": json.dumps({
            "schemaVersion": 1,
            "participants": [],
        }, indent=2) + "\n",
    }
    for relative, content in files.items():
        target = destination / relative
        if target.exists() and not args.force:
            raise FileExistsError(f"project file already exists: {target}")
        target.write_text(content, encoding="utf-8", newline="\n")
    project_template.atomic_json(
        destination / project_template.STATE_PATH,
        project_template.initial_state(manifest),
    )
    write_composition_file(destination / "pdr-project.yaml")
    print(f"PDR_PROJECT_CREATE_PASS name={slug} path={destination}")
    return 0


def validate_project(args: Any) -> int:
    manifest = Path(args.manifest).resolve()
    report_path = Path(args.report).resolve() if args.report else None
    try:
        normalized = validate_manifest(manifest, check_paths=not args.skip_path_checks)
        report = {"schemaVersion": 1, "operation": "project-validate", "passed": True,
                  "manifest": str(manifest), "project": normalized}
    except Exception as error:
        report = {"schemaVersion": 1, "operation": "project-validate", "passed": False,
                  "manifest": str(manifest), "error": str(error)}
        if report_path:
            atomic_json(report_path, report)
        print(f"PDR_PROJECT_VALIDATE_FAIL error={error}")
        return 1
    if report_path:
        atomic_json(report_path, report)
    print(f"PDR_PROJECT_VALIDATE_PASS name={normalized['name']}")
    return 0


def add_project_component(args: Any) -> int:
    manifest = Path(args.manifest).resolve()
    relative = register_component_path(manifest, args.kind, args.path)
    print(f"PDR_PROJECT_ADD_PASS kind={args.kind} path={relative}")
    return 0


def remove_project_component(args: Any) -> int:
    manifest = Path(args.manifest).resolve()
    relative = unregister_component_path(manifest, args.kind, args.path)
    print(f"PDR_PROJECT_REMOVE_PASS kind={args.kind} path={relative}")
    return 0


def list_project_components(args: Any) -> int:
    manifest = Path(args.manifest).resolve()
    project = validate_manifest(manifest, check_paths=not args.skip_path_checks)
    records: list[dict[str, str]] = []
    reverse_routes: dict[tuple[str, ...], str] = {}
    for kind, route in COMPONENT_KIND_FIELDS.items():
        reverse_routes.setdefault(route, kind)
    for field in sorted(COMPONENT_LISTS):
        kind = reverse_routes[(field,)]
        for relative in project["components"][field]:
            records.append({"kind": kind, "path": relative})
    for field in sorted(ADAPTER_LISTS):
        kind = reverse_routes[("adapters", field)]
        for relative in project["components"]["adapters"][field]:
            records.append({"kind": kind, "path": relative})
    records.sort(key=lambda item: (item["kind"], item["path"]))
    if args.json:
        print(json.dumps(records, indent=2, ensure_ascii=False))
    elif records:
        for record in records:
            print(f"{record['kind']}\t{record['path']}")
    else:
        print("PDR_PROJECT_LIST_EMPTY")
    return 0


def sync_project(args: Any) -> int:
    manifest = Path(args.manifest).resolve()
    output = Path(args.output).resolve() if args.output else None
    destination = write_composition_file(manifest, output)
    project = validate_manifest(manifest, check_paths=True)
    count = sum(len(project["components"][field]) for field in COMPONENT_LISTS)
    count += sum(len(project["components"]["adapters"][field]) for field in ADAPTER_LISTS)
    print(f"PDR_PROJECT_SYNC_PASS components={count} output={destination}")
    return 0


def add_project_dependency(args: Any) -> int:
    manifest = Path(args.manifest).resolve()
    project = validate_manifest(manifest, check_paths=True)
    if any(item["name"] == args.name for item in project["dependencies"]):
        raise ValueError(f"dependency is already registered: {args.name}")
    project["dependencies"].append({
        "name": args.name,
        "version": args.version,
        "license": args.license,
        "download": args.download,
        "scope": args.scope,
        "optional": args.optional,
    })
    project["dependencies"].sort(key=lambda item: item["name"].casefold())
    atomic_json(manifest, project)
    validate_manifest(manifest, check_paths=True)
    write_composition_file(manifest)
    print(f"PDR_PROJECT_DEPENDENCY_ADD_PASS name={args.name} version={args.version}")
    return 0


def remove_project_dependency(args: Any) -> int:
    manifest = Path(args.manifest).resolve()
    project = validate_manifest(manifest, check_paths=True)
    matches = [item for item in project["dependencies"] if item["name"] == args.name]
    if not matches:
        raise ValueError(f"dependency is not registered: {args.name}")
    project["dependencies"] = [
        item for item in project["dependencies"] if item["name"] != args.name
    ]
    atomic_json(manifest, project)
    write_composition_file(manifest)
    print(f"PDR_PROJECT_DEPENDENCY_REMOVE_PASS name={args.name}")
    return 0


def list_project_dependencies(args: Any) -> int:
    manifest = Path(args.manifest).resolve()
    dependencies = validate_manifest(manifest, check_paths=not args.skip_path_checks)["dependencies"]
    if args.json:
        print(json.dumps(dependencies, indent=2, ensure_ascii=False))
    elif dependencies:
        for dependency in dependencies:
            optional = "optional" if dependency["optional"] else "required"
            print(
                f"{dependency['name']}\t{dependency['version']}\t"
                f"{dependency['scope']}\t{optional}"
            )
    else:
        print("PDR_PROJECT_DEPENDENCY_LIST_EMPTY")
    return 0


def write_project_lock(manifest: Path, output: Path) -> dict[str, Any]:
    manifest = manifest.resolve()
    project = validate_manifest(manifest, check_paths=True)
    output = output.resolve()
    try:
        output.relative_to(manifest.parent)
    except ValueError as error:
        raise ValueError("project lock output must stay inside the project root") from error
    digest, file_count = tree_digest(manifest.parent, {output})
    lock = {
        "schemaVersion": 1,
        "operation": "project-resolve",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "manifest": manifest.name,
        "manifestSha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "sourceTreeSha256": digest,
        "sourceFileCount": file_count,
        "project": project,
    }
    atomic_json(output, lock)
    return lock


def resolve_project(args: Any) -> int:
    manifest = Path(args.manifest).resolve()
    output = Path(args.output).resolve()
    lock = write_project_lock(manifest, output)
    project = lock["project"]
    file_count = lock["sourceFileCount"]
    print(f"PDR_PROJECT_RESOLVE_PASS name={project['name']} files={file_count} lock={output}")
    return 0


def set_project_version(args: Any) -> int:
    manifest = Path(args.manifest).resolve()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", args.version):
        raise ValueError("project version must be a concrete semantic version")
    project = validate_manifest(manifest, check_paths=True)
    previous = project.get("version")
    project["version"] = args.version
    atomic_json(manifest, project)
    write_composition_file(manifest)
    print(
        f"PDR_PROJECT_VERSION_SET_PASS from={previous or '-'} to={args.version} "
        f"manifest={manifest}"
    )
    return 0
