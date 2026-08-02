#!/usr/bin/env python3
"""Reject unversioned breaking changes to PocoDDSRuntime public contracts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


HTTP_METHODS = {"get", "put", "post", "delete", "patch", "head", "options", "trace"}


def yaml_version(text: str) -> str:
    match = re.search(r"(?m)^\s{2}version:\s*([^\s#]+)", text)
    if not match:
        raise ValueError("contract info.version is missing")
    return match.group(1).strip('"\'')


def openapi_operations(text: str) -> list[str]:
    result: list[str] = []
    current_path = ""
    for line in text.splitlines():
        path_match = re.match(r"^  (/[^:]+):\s*$", line)
        if path_match:
            current_path = path_match.group(1)
            continue
        method_match = re.match(r"^    ([a-z]+):\s*$", line)
        if current_path and method_match and method_match.group(1) in HTTP_METHODS:
            result.append(f"{method_match.group(1).upper()} {current_path}")
    return sorted(result)


def asyncapi_channels(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    in_channels = False
    channel = ""
    for line in text.splitlines():
        if line == "channels:":
            in_channels = True
            continue
        if in_channels and line and not line.startswith(" "):
            break
        channel_match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if channel_match:
            channel = channel_match.group(1)
            continue
        address_match = re.match(r"^    address:\s*([^\s#]+)", line)
        if channel and address_match:
            result[channel] = address_match.group(1).strip('"\'')
    return dict(sorted(result.items()))


def public_types(text: str) -> list[str]:
    pattern = r"(?m)^\s*(?:class|struct|enum\s+class)\s+([A-Za-z_][A-Za-z0-9_]*)"
    return sorted(set(re.findall(pattern, text)))


def schema_surface(document: dict[str, Any]) -> dict[str, Any]:
    properties = document.get("properties", {})
    patterns = document.get("patternProperties", {})
    constraints = ("type", "minimum", "maximum", "minLength", "maxLength", "enum")
    return {
        "required": sorted(document.get("required", [])),
        "properties": {
            name: {
                key: definition[key]
                for key in constraints
                if key in definition
            }
            for name, definition in sorted(properties.items())
        },
        "patterns": {
            name: {key: definition[key] for key in constraints if key in definition}
            for name, definition in sorted(patterns.items())
        },
    }


def current_surface(root: Path) -> dict[str, Any]:
    header_paths = [
        "application/include/PocoDDS/Application/Application.h",
        "platform/configuration/include/PocoDDS/Configuration/ConfigurationValidator.h",
        "platform/configuration/include/PocoDDS/Configuration/IndexedConfiguration.h",
        "platform/devices/Devices/include/PocoDDS/Devices/Device.h",
        "platform/devices/Devices/include/PocoDDS/Devices/DeviceService.h",
        "platform/reliability/include/PocoDDS/Reliability/Reliability.h",
        "platform/health/include/PocoDDS/Health/Health.h",
        "platform/persistence/include/PocoDDS/Persistence/Persistence.h",
        "sdk/include/PocoDDS/SDK/SDK.h",
        "sdk/include/PocoDDS/SDK/Version.h.in",
        "platform/protocols/include/PocoDDS/Protocols/Protocol.h",
        "platform/protocols/include/PocoDDS/Protocols/ProtocolDiagnostics.h",
        "platform/protocols/include/PocoDDS/Protocols/ProtocolService.h",
        "platform/protocols/BtLE/include/PocoDDS/Protocols/BtLE/GattClient.h",
        "platform/protocols/BtLE/include/PocoDDS/Protocols/BtLE/PeripheralBrowser.h",
        "platform/protocols/CAN/include/PocoDDS/Protocols/CAN/CanEndpoint.h",
        "platform/protocols/CAN/include/PocoDDS/Protocols/CAN/SignalCodec.h",
        "platform/protocols/Modbus/include/PocoDDS/Protocols/Modbus/ModbusTcpClient.h",
        "platform/protocols/Modbus/include/PocoDDS/Protocols/Modbus/ModbusTcpCodec.h",
        "platform/protocols/MQTT/include/PocoDDS/Protocols/MQTT/MqttClient.h",
        "platform/protocols/ROS/include/PocoDDS/Protocols/ROS/BridgeClient.h",
        "platform/protocols/Serial/include/PocoDDS/Protocols/Serial/SerialChannel.h",
        "platform/protocols/UDP/include/PocoDDS/Protocols/UDP/UdpChannel.h",
        "platform/protocols/WebTunnel/include/PocoDDS/Protocols/WebTunnel/LocalForwarder.h",
        "platform/protocols/WebTunnel/include/PocoDDS/Protocols/WebTunnel/Service.h",
        "platform/protocols/XBee/include/PocoDDS/Protocols/XBee/IoSample.h",
        "platform/protocols/XBee/include/PocoDDS/Protocols/XBee/XBeeFrame.h",
        "platform/protocols/XBee/include/PocoDDS/Protocols/XBee/XBeePort.h",
    ]
    openapi = (root / "contracts/openapi/runtime.yaml").read_text(encoding="utf-8")
    asyncapi = (root / "contracts/asyncapi/runtime.yaml").read_text(encoding="utf-8")
    schema = json.loads((root / "contracts/schemas/runtime-config.schema.json").read_text(encoding="utf-8"))
    cmake_text = (root / "CMakeLists.txt").read_text(encoding="utf-8")
    def cmake_value(name: str) -> str:
        match = re.search(rf'set\({re.escape(name)}\s+"([^"]+)"\)', cmake_text)
        if not match:
            raise ValueError(f"missing compatibility variable: {name}")
        return match.group(1)

    return {
        "runtimeVersion": re.search(
            r"project\(PocoDDSRuntime VERSION ([0-9.]+)",
            cmake_text,
        ).group(1),
        "pluginContract": {
            "apiVersion": cmake_value("PDR_PLUGIN_API_VERSION"),
            "abiVersion": cmake_value("PDR_PLUGIN_ABI_VERSION"),
            "manifestHeaders": [
                "PDR-Plugin-API", "PDR-Plugin-ABI",
                "PDR-Plugin-ABI-Fingerprint", "PDR-Runtime-Version",
            ],
        },
        "cmakeTargets": [
            "PocoDDS::Application",
            "PocoDDS::Configuration",
            "PocoDDS::DeviceCore",
            "PocoDDS::Health",
            "PocoDDS::Persistence",
            "PocoDDS::Plugins",
            "PocoDDS::Reliability",
            "PocoDDS::SDK",
            "PocoDDS::Protocols",
            "PocoDDS::BtLE",
            "PocoDDS::CAN",
            "PocoDDS::Modbus",
            "PocoDDS::MQTT",
            "PocoDDS::ROS",
            "PocoDDS::SerialProtocol",
            "PocoDDS::UDP",
            "PocoDDS::WebTunnelProtocol",
            "PocoDDS::XBee",
        ],
        "publicHeaders": {
            path: public_types((root / path).read_text(encoding="utf-8"))
            for path in header_paths
        },
        "configuration": schema_surface(schema),
        "openapi": {"version": yaml_version(openapi), "operations": openapi_operations(openapi)},
        "asyncapi": {"version": yaml_version(asyncapi), "channels": asyncapi_channels(asyncapi)},
    }


def version_tuple(value: str) -> tuple[int, int, int]:
    parts = value.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError(f"invalid semantic version: {value}")
    return tuple(int(part) for part in parts)  # type: ignore[return-value]


def constraints_breaking(old: dict[str, Any], new: dict[str, Any]) -> bool:
    if old.get("type") != new.get("type"):
        return True
    if "minimum" in old and ("minimum" not in new or new["minimum"] > old["minimum"]):
        return True
    if "maximum" in old and ("maximum" not in new or new["maximum"] < old["maximum"]):
        return True
    if "minLength" in old and ("minLength" not in new or new["minLength"] > old["minLength"]):
        return True
    if "maxLength" in old and ("maxLength" not in new or new["maxLength"] < old["maxLength"]):
        return True
    if "enum" in old:
        if "enum" not in new or not set(old["enum"]).issubset(new["enum"]):
            return True
    known = {"type", "minimum", "maximum", "minLength", "maxLength", "enum"}
    return any(key not in known and old.get(key) != new.get(key) for key in set(old) | set(new))


def compare(baseline: dict[str, Any], current: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    baseline_version = version_tuple(baseline["runtimeVersion"])
    current_version = version_tuple(current["runtimeVersion"])
    breaking: list[str] = []

    old_plugin = baseline.get("pluginContract")
    new_plugin = current.get("pluginContract")
    if old_plugin:
        if not new_plugin:
            breaking.append("removed plugin compatibility contract")
        else:
            for field in ("apiVersion", "abiVersion"):
                if old_plugin.get(field) != new_plugin.get(field):
                    breaking.append(f"changed plugin contract {field}")
            for header in old_plugin.get("manifestHeaders", []):
                if header not in new_plugin.get("manifestHeaders", []):
                    breaking.append(f"removed plugin manifest header: {header}")

    for target in baseline["cmakeTargets"]:
        if target not in current["cmakeTargets"]:
            breaking.append(f"removed CMake target: {target}")
    for header, types in baseline["publicHeaders"].items():
        if header not in current["publicHeaders"]:
            breaking.append(f"removed public header: {header}")
            continue
        for type_name in types:
            if type_name not in current["publicHeaders"][header]:
                breaking.append(f"removed public type: {type_name} ({header})")

    old_config = baseline["configuration"]
    new_config = current["configuration"]
    for name, definition in old_config["properties"].items():
        if name not in new_config["properties"]:
            breaking.append(f"removed configuration property: {name}")
        elif constraints_breaking(definition, new_config["properties"][name]):
            breaking.append(f"changed configuration constraints: {name}")
    for name, definition in old_config.get("patterns", {}).items():
        if name not in new_config.get("patterns", {}):
            breaking.append(f"removed configuration pattern: {name}")
        elif constraints_breaking(definition, new_config["patterns"][name]):
            breaking.append(f"changed configuration pattern constraints: {name}")
    newly_required = set(new_config["required"]) - set(old_config["required"])
    for name in sorted(newly_required):
        breaking.append(f"new required configuration property: {name}")

    for operation in baseline["openapi"]["operations"]:
        if operation not in current["openapi"]["operations"]:
            breaking.append(f"removed OpenAPI operation: {operation}")
    for name, address in baseline["asyncapi"]["channels"].items():
        if name not in current["asyncapi"]["channels"]:
            breaking.append(f"removed AsyncAPI channel: {name}")
        elif current["asyncapi"]["channels"][name] != address:
            breaking.append(f"changed AsyncAPI address: {name}")

    if breaking and current_version[0] <= baseline_version[0]:
        errors.extend(breaking)
        errors.append(
            "breaking changes require a new Runtime major version and an intentional baseline update"
        )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--print-current", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    surface = current_surface(root)
    if args.print_current:
        print(json.dumps(surface, indent=2, ensure_ascii=False))
        return 0
    baseline_path = args.baseline or root / "contracts/compatibility/0.1.0.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    errors = compare(baseline, surface)
    if errors:
        for error in errors:
            print(f"COMPATIBILITY_ERROR: {error}", file=sys.stderr)
        return 1
    print(f"COMPATIBILITY_PASS baseline={baseline['runtimeVersion']} current={surface['runtimeVersion']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
