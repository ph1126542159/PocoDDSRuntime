#!/usr/bin/env python3
"""Pinned manifest catalog and generic capability probe for Team Contract adapters."""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any

import team_contract_adapter_runtime as adapter_runtime
import team_contract_package as package_tool
import team_contract_registry as registry_tool


MANIFEST_PRODUCT = "PocoDDSRuntimeTeamContractAdapterManifest"
CATALOG_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalog"
LISTING_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalogListing"
CHECK_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalogCheck"
ADAPTER_TYPE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
FIELD_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,63}$")
OWNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}/[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
RESERVED_CAPABILITY_FIELDS = {
    "schemaVersion", "product", "requestId", "implementationId",
    "protocolMajor", "protocolMinor", "capabilities",
}


def validate_manifest(document: Any) -> None:
    fields = {
        "schemaVersion", "product", "manifestId", "adapterId",
        "adapterType", "owner", "revision", "protocolId", "configPath",
        "configSha256", "identityField", "capabilityRequestProduct",
        "capabilityManifestProduct",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != MANIFEST_PRODUCT
            or any(package_tool.IDENTIFIER.fullmatch(
                str(document.get(name, ""))) is None
                for name in ("manifestId", "adapterId", "revision", "protocolId",
                             "capabilityRequestProduct",
                             "capabilityManifestProduct"))
            or ADAPTER_TYPE.fullmatch(str(document.get("adapterType", ""))) is None
            or OWNER.fullmatch(str(document.get("owner", ""))) is None
            or not isinstance(document.get("configPath"), str)
            or not Path(document["configPath"]).is_absolute()
            or not package_tool.SHA256.fullmatch(
                str(document.get("configSha256", "")))
            or FIELD_NAME.fullmatch(
                str(document.get("identityField", ""))) is None
            or document.get("identityField") in RESERVED_CAPABILITY_FIELDS):
        raise ValueError("adapter manifest is malformed")


def validate_catalog(document: Any) -> None:
    if (not isinstance(document, dict)
            or set(document) != {
                "schemaVersion", "product", "catalogId", "generation", "entries"
            }
            or document.get("schemaVersion") != 1
            or document.get("product") != CATALOG_PRODUCT
            or package_tool.IDENTIFIER.fullmatch(
                str(document.get("catalogId", ""))) is None
            or type(document.get("generation")) is not int
            or document["generation"] < 1
            or not isinstance(document.get("entries"), list)
            or not document["entries"] or len(document["entries"]) > 256):
        raise ValueError("adapter catalog is malformed")
    identities: set[tuple[str, str]] = set()
    adapter_ids: set[str] = set()
    manifest_ids: set[str] = set()
    paths: set[str] = set()
    expected_fields = {
        "adapterId", "adapterType", "manifestId", "revision",
        "manifestPath", "manifestSha256",
    }
    for entry in document["entries"]:
        if (not isinstance(entry, dict) or set(entry) != expected_fields
                or any(package_tool.IDENTIFIER.fullmatch(
                    str(entry.get(name, ""))) is None
                    for name in ("adapterId", "manifestId", "revision"))
                or ADAPTER_TYPE.fullmatch(
                    str(entry.get("adapterType", ""))) is None
                or not isinstance(entry.get("manifestPath"), str)
                or not Path(entry["manifestPath"]).is_absolute()
                or not package_tool.SHA256.fullmatch(
                    str(entry.get("manifestSha256", "")))):
            raise ValueError("adapter catalog entry is malformed")
        identity = (entry["adapterType"], entry["adapterId"])
        if (identity in identities or entry["adapterId"] in adapter_ids
                or entry["manifestId"] in manifest_ids \
                or entry["manifestPath"] in paths):
            raise ValueError("adapter catalog entry is duplicated")
        identities.add(identity)
        adapter_ids.add(entry["adapterId"])
        manifest_ids.add(entry["manifestId"])
        paths.add(entry["manifestPath"])
    if document["entries"] != sorted(
            document["entries"],
            key=lambda item: (item["adapterType"], item["adapterId"])):
        raise ValueError("adapter catalog entries are not sorted")


def validate_common_config(config: Any, manifest: dict[str, Any]) -> None:
    required = {
        manifest["identityField"], "kind", "protocolMajor",
        "minimumProtocolMinor", "requiredCapabilities", "executable",
        "executableSha256", "arguments", "artifactPins",
        "environmentVariables", "timeoutSeconds", "maxResponseBytes",
    }
    if (not isinstance(config, dict) or not required.issubset(config)
            or config.get(manifest["identityField"]) != manifest["adapterId"]
            or config.get("kind") != "external-command"
            or type(config.get("protocolMajor")) is not int
            or not 1 <= config["protocolMajor"] <= 65535
            or type(config.get("minimumProtocolMinor")) is not int
            or not 0 <= config["minimumProtocolMinor"] <= 65535
            or not isinstance(config.get("requiredCapabilities"), list)
            or not config["requiredCapabilities"]
            or config["requiredCapabilities"]
                != sorted(set(config["requiredCapabilities"]))
            or any(adapter_runtime.CAPABILITY_ID.fullmatch(str(item)) is None
                   for item in config["requiredCapabilities"])
            or not isinstance(config.get("executable"), str)
            or not package_tool.SHA256.fullmatch(
                str(config.get("executableSha256", "")))
            or not isinstance(config.get("arguments"), list)
            or len(config["arguments"]) > 32
            or any(not isinstance(item, str) or not item or "\x00" in item
                   or len(item) > 1024 for item in config["arguments"])
            or type(config.get("timeoutSeconds")) is not int
            or not 1 <= config["timeoutSeconds"] <= 60
            or type(config.get("maxResponseBytes")) is not int
            or not 1024 <= config["maxResponseBytes"] <= 64 * 1024 * 1024):
        raise ValueError("adapter manifest config is incompatible")
    adapter_runtime.validate_artifact_pins(config["artifactPins"], "adapter")
    adapter_runtime.validate_environment_policy(
        config["environmentVariables"],
        optional=config.get("optionalEnvironmentVariables", []),
        label="adapter",
    )


def load_manifest(path_value: str | Path, expected_sha: str) \
        -> tuple[dict[str, Any], dict[str, Any], Path, str]:
    manifest, path, digest = adapter_runtime.load_pinned_json(
        path_value, expected_sha, "adapter manifest", validate_manifest
    )
    config_path = package_tool.resolved_path(
        manifest["configPath"], "adapter manifest target config"
    )
    config_content = config_path.read_bytes()
    config_digest = package_tool.sha256_bytes(config_content)
    if config_digest != manifest["configSha256"]:
        raise ValueError("adapter manifest target config identity changed")
    try:
        config = json.loads(config_content)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("adapter manifest target config is invalid JSON") from error
    validate_common_config(config, manifest)
    adapter_runtime.revalidate_artifacts(config, "adapter")
    return manifest, config, path, digest


def load_catalog(path_value: str | Path, expected_sha: str) \
        -> tuple[dict[str, Any], Path, str]:
    return adapter_runtime.load_pinned_json(
        path_value, expected_sha, "adapter catalog", validate_catalog
    )


def validate_capability_manifest(document: Any, request: dict[str, Any],
                                 manifest: dict[str, Any]) -> None:
    identity = manifest["identityField"]
    fields = {
        "schemaVersion", "product", "requestId", identity,
        "implementationId", "protocolMajor", "protocolMinor", "capabilities",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != manifest["capabilityManifestProduct"]
            or document.get("requestId") != request["requestId"]
            or document.get(identity) != manifest["adapterId"]
            or package_tool.IDENTIFIER.fullmatch(
                str(document.get("implementationId", ""))) is None
            or type(document.get("protocolMajor")) is not int
            or type(document.get("protocolMinor")) is not int
            or not isinstance(document.get("capabilities"), list)
            or not document["capabilities"]
            or document["capabilities"]
                != sorted(set(document["capabilities"]))
            or any(adapter_runtime.CAPABILITY_ID.fullmatch(str(item)) is None
                   for item in document["capabilities"])):
        raise ValueError("adapter capability manifest is malformed or mismatched")


def probe(manifest: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    identity = manifest["identityField"]
    request = {
        "schemaVersion": 1,
        "product": manifest["capabilityRequestProduct"],
        "requestId": str(uuid.uuid4()), identity: manifest["adapterId"],
    }
    environment = adapter_runtime.isolated_environment(
        config["environmentVariables"],
        optional=config.get("optionalEnvironmentVariables", []),
        require_required=False, label="adapter capability probe",
    )
    response = adapter_runtime.invoke_json(
        [str(Path(config["executable"]).resolve()), *config["arguments"]],
        request, environment=environment,
        timeout_seconds=config["timeoutSeconds"],
        max_response_bytes=config["maxResponseBytes"],
        label="adapter capability probe", expose_stderr=False,
    )
    validate_capability_manifest(response, request, manifest)
    adapter_runtime.enforce_capability_policy(
        config, response, "adapter capability probe"
    )
    return {
        "adapterId": manifest["adapterId"],
        "adapterType": manifest["adapterType"],
        "manifestId": manifest["manifestId"],
        "revision": manifest["revision"], "owner": manifest["owner"],
        "protocolId": manifest["protocolId"],
        "protocolMajor": response["protocolMajor"],
        "protocolMinor": response["protocolMinor"],
        "capabilities": response["capabilities"],
        "capabilityManifestSha256": adapter_runtime.capability_digest(
            response, identity
        ),
        "configSha256": manifest["configSha256"], "healthy": True,
    }


def selected_entries(catalog: dict[str, Any], adapter_type: str | None) \
        -> list[dict[str, Any]]:
    if adapter_type is not None \
            and ADAPTER_TYPE.fullmatch(adapter_type) is None:
        raise ValueError("adapter type filter is malformed")
    entries = [
        item for item in catalog["entries"]
        if adapter_type is None or item["adapterType"] == adapter_type
    ]
    if not entries:
        raise ValueError("adapter catalog selection is empty")
    return entries


def _load_entry(entry: dict[str, Any]) \
        -> tuple[dict[str, Any], dict[str, Any], Path, str]:
    manifest, config, path, digest = load_manifest(
        entry["manifestPath"], entry["manifestSha256"]
    )
    if any(manifest[name] != entry[name] for name in (
            "adapterId", "adapterType", "manifestId", "revision")):
        raise ValueError("adapter catalog manifest identity changed")
    return manifest, config, path, digest


def list_command(args: argparse.Namespace) -> int:
    try:
        catalog, _, digest = load_catalog(
            args.catalog, args.expected_catalog_sha256
        )
        adapters = []
        for entry in selected_entries(catalog, args.adapter_type):
            manifest, _, _, _ = _load_entry(entry)
            adapters.append({
                "adapterId": manifest["adapterId"],
                "adapterType": manifest["adapterType"],
                "manifestId": manifest["manifestId"],
                "revision": manifest["revision"], "owner": manifest["owner"],
                "protocolId": manifest["protocolId"],
                "configSha256": manifest["configSha256"],
            })
        report = {
            "schemaVersion": 1, "product": LISTING_PRODUCT,
            "catalogId": catalog["catalogId"],
            "catalogGeneration": catalog["generation"],
            "catalogSha256": digest, "adapters": adapters,
        }
        if args.report:
            package_tool.write_json(Path(args.report).resolve(), report)
        print(
            "PDR_ADAPTER_CATALOG_LIST_PASS "
            f"catalog={catalog['catalogId']} adapters={len(adapters)}"
        )
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        print(f"PDR_ADAPTER_CATALOG_LIST_ERROR: {error}", file=sys.stderr)
        return 2


def check_command(args: argparse.Namespace) -> int:
    try:
        catalog, _, digest = load_catalog(
            args.catalog, args.expected_catalog_sha256
        )
        adapters = []
        for entry in selected_entries(catalog, args.adapter_type):
            manifest, config, _, _ = _load_entry(entry)
            adapters.append(probe(manifest, config))
        report = {
            "schemaVersion": 1, "product": CHECK_PRODUCT, "passed": True,
            "catalogId": catalog["catalogId"],
            "catalogGeneration": catalog["generation"],
            "catalogSha256": digest, "adapters": adapters,
            "checkedAt": registry_tool.utc_time(None),
        }
        if args.report:
            package_tool.write_json(Path(args.report).resolve(), report)
        print(
            "PDR_ADAPTER_CATALOG_CHECK_PASS "
            f"catalog={catalog['catalogId']} adapters={len(adapters)}"
        )
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_ADAPTER_CATALOG_CHECK_ERROR: {error}", file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="operation", required=True)
    for name, handler in (("list", list_command), ("check", check_command)):
        command = commands.add_parser(name)
        command.add_argument("--catalog", required=True)
        command.add_argument("--expected-catalog-sha256", required=True)
        command.add_argument("--adapter-type")
        command.add_argument("--report")
        command.set_defaults(handler=handler)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
