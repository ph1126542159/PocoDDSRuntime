#!/usr/bin/env python3
"""Pinned external-command provider for bounded versioned secret references."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple

import team_contract_package as package_tool
import team_contract_registry as registry_tool
import team_contract_adapter_runtime as adapter_runtime


CONFIG_PRODUCT = "PocoDDSRuntimeTeamContractSecretProviderConfig"
REFERENCE_PRODUCT = "PocoDDSRuntimeTeamContractSecretReference"
REQUEST_PRODUCT = "PocoDDSRuntimeTeamContractSecretProviderRequest"
RESPONSE_PRODUCT = "PocoDDSRuntimeTeamContractSecretProviderResponse"
CAPABILITY_REQUEST_PRODUCT = \
    "PocoDDSRuntimeTeamContractSecretProviderCapabilityRequest"
CAPABILITY_MANIFEST_PRODUCT = \
    "PocoDDSRuntimeTeamContractSecretProviderCapabilityManifest"
CHECK_PRODUCT = "PocoDDSRuntimeTeamContractSecretProviderCheck"
ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
CAPABILITY_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def _regular_pinned_file(path_value: str, expected_sha: str, label: str) -> Path:
    return adapter_runtime.regular_pinned_file(
        path_value, expected_sha, label
    )


def validate_reference(document: Any, *, provider_id: str | None = None) \
        -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ValueError("secret reference is malformed or out of scope")
    kind = document.get("kind")
    common_valid = (
        package_tool.IDENTIFIER.fullmatch(
            str(document.get("providerId", ""))) is not None
        and package_tool.IDENTIFIER.fullmatch(
            str(document.get("secretId", ""))) is not None
        and (provider_id is None or document["providerId"] == provider_id)
    )
    if kind == "secret-ref":
        valid = (set(document) == {
            "kind", "providerId", "secretId", "version"
        } and package_tool.IDENTIFIER.fullmatch(
            str(document.get("version", ""))) is not None)
    elif kind == "secret-rotation-ref":
        versions = document.get("versions")
        valid = (set(document) == {
            "kind", "providerId", "secretId", "versions", "fallbackUntil"
        } and isinstance(versions, list)
            and 2 <= len(versions) <= 4
            and len(versions) == len(set(versions))
            and all(package_tool.IDENTIFIER.fullmatch(str(item)) is not None
                    for item in versions)
            and isinstance(document.get("fallbackUntil"), str))
        if valid:
            try:
                package_tool.verification_time(document["fallbackUntil"])
            except ValueError:
                valid = False
    else:
        valid = False
    if not common_valid or not valid:
        raise ValueError("secret reference is malformed or out of scope")
    return document


def reference_versions(reference: dict[str, Any]) -> list[str]:
    return [reference["version"]] if reference["kind"] == "secret-ref" \
        else list(reference["versions"])


def validate_config(document: Any) -> None:
    base_fields = {
        "schemaVersion", "product", "providerId", "kind", "secretIds",
        "protocolMajor", "minimumProtocolMinor", "requiredCapabilities",
        "executable", "executableSha256", "arguments", "artifactPins",
        "environmentVariables", "timeoutSeconds", "maxResponseBytes",
        "maxSecretBytes",
    }
    if not isinstance(document, dict):
        raise ValueError("secret provider configuration is malformed")
    version = document.get("schemaVersion")
    fields = base_fields | ({
        "leasePolicy", "optionalEnvironmentVariables"
    } if version == 2 else set())
    if (set(document) != fields
            or version not in {1, 2}
            or document.get("product") != CONFIG_PRODUCT
            or not package_tool.IDENTIFIER.fullmatch(
                str(document.get("providerId", "")))
            or document.get("kind") != "external-command"
            or not isinstance(document.get("secretIds"), list)
            or not document["secretIds"]
            or len(document["secretIds"]) > 128
            or document["secretIds"] != sorted(set(document["secretIds"]))
            or any(not package_tool.IDENTIFIER.fullmatch(str(item))
                   for item in document["secretIds"])
            or type(document.get("protocolMajor")) is not int
            or not 1 <= document["protocolMajor"] <= 65535
            or type(document.get("minimumProtocolMinor")) is not int
            or not 0 <= document["minimumProtocolMinor"] <= 65535
            or not isinstance(document.get("requiredCapabilities"), list)
            or not document["requiredCapabilities"]
            or document["requiredCapabilities"]
                != sorted(set(document["requiredCapabilities"]))
            or len(document["requiredCapabilities"]) > 32
            or any(not isinstance(item, str)
                   or CAPABILITY_ID.fullmatch(item) is None
                   for item in document["requiredCapabilities"])
            or not isinstance(document.get("executable"), str)
            or not package_tool.SHA256.fullmatch(
                str(document.get("executableSha256", "")))
            or not isinstance(document.get("arguments"), list)
            or len(document["arguments"]) > 32
            or any(not isinstance(item, str) or not item
                   or len(item) > 1024 or "\x00" in item
                   for item in document["arguments"])
            or not isinstance(document.get("artifactPins"), list)
            or len(document["artifactPins"]) > 32
            or not isinstance(document.get("environmentVariables"), list)
            or len(document["environmentVariables"]) > 32
            or document["environmentVariables"]
                != sorted(set(document["environmentVariables"]))
            or any(ENVIRONMENT_NAME.fullmatch(str(item)) is None
                   for item in document["environmentVariables"])
            or type(document.get("timeoutSeconds")) is not int
            or not 1 <= document["timeoutSeconds"] <= 30
            or type(document.get("maxResponseBytes")) is not int
            or not 1024 <= document["maxResponseBytes"] <= 1024 * 1024
            or type(document.get("maxSecretBytes")) is not int
            or not 1 <= document["maxSecretBytes"] <= 64 * 1024
            or document["maxResponseBytes"]
                < ((document["maxSecretBytes"] + 2) // 3) * 4 + 4096):
        raise ValueError("secret provider configuration is malformed")
    if version == 2:
        policy = document.get("leasePolicy")
        if (not isinstance(policy, dict)
                or set(policy) != {
                    "requestedLeaseSeconds", "minimumRemainingSeconds"
                }
                or type(policy.get("requestedLeaseSeconds")) is not int
                or not 2 <= policy["requestedLeaseSeconds"] <= 3600
                or type(policy.get("minimumRemainingSeconds")) is not int
                or not 1 <= policy["minimumRemainingSeconds"]
                    < policy["requestedLeaseSeconds"]):
            raise ValueError("secret provider lease policy is malformed")
        optional = document.get("optionalEnvironmentVariables")
        if (not isinstance(optional, list) or len(optional) > 64
                or optional != sorted(set(optional))
                or any(ENVIRONMENT_NAME.fullmatch(str(item)) is None
                       for item in optional)
                or set(optional) & set(document["environmentVariables"])):
            raise ValueError(
                "secret provider optional environment policy is malformed"
            )
    seen: set[str] = set()
    for item in document["artifactPins"]:
        if (not isinstance(item, dict) or set(item) != {"path", "sha256"}
                or not isinstance(item.get("path"), str)
                or item["path"] in seen
                or not package_tool.SHA256.fullmatch(
                    str(item.get("sha256", "")))):
            raise ValueError("secret provider artifact pin is malformed")
        seen.add(item["path"])


def load_config(path_value: str | Path, expected_sha: str) \
        -> tuple[dict[str, Any], Path, str]:
    path = package_tool.resolved_path(path_value, "secret provider config")
    content = path.read_bytes()
    digest = package_tool.sha256_bytes(content)
    expected = str(expected_sha).lower()
    if not package_tool.SHA256.fullmatch(expected) or digest != expected:
        raise ValueError("secret provider configuration identity is not pinned")
    document = json.loads(content)
    validate_config(document)
    _regular_pinned_file(
        document["executable"], document["executableSha256"],
        "secret provider executable",
    )
    for artifact in document["artifactPins"]:
        _regular_pinned_file(
            artifact["path"], artifact["sha256"],
            "secret provider artifact",
        )
    return document, path, digest


def _capability_request(provider_id: str) -> dict[str, Any]:
    return {
        "schemaVersion": 1, "product": CAPABILITY_REQUEST_PRODUCT,
        "requestId": str(uuid.uuid4()), "providerId": provider_id,
    }


def _request(config: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    leased = config["schemaVersion"] == 2
    result = {
        "schemaVersion": 2 if leased else 1, "product": REQUEST_PRODUCT,
        "requestId": str(uuid.uuid4()), "providerId": config["providerId"],
        "operation": "lease" if leased else "resolve", "reference": reference,
    }
    if leased:
        result["requestedLeaseSeconds"] = \
            config["leasePolicy"]["requestedLeaseSeconds"]
    return result


def validate_capability_manifest(document: Any,
                                 request: dict[str, Any]) -> None:
    fields = {
        "schemaVersion", "product", "requestId", "providerId",
        "implementationId", "protocolMajor", "protocolMinor", "capabilities",
    }
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != 1
            or document.get("product") != CAPABILITY_MANIFEST_PRODUCT
            or document.get("requestId") != request["requestId"]
            or document.get("providerId") != request["providerId"]
            or not package_tool.IDENTIFIER.fullmatch(
                str(document.get("implementationId", "")))
            or type(document.get("protocolMajor")) is not int
            or type(document.get("protocolMinor")) is not int
            or not isinstance(document.get("capabilities"), list)
            or not document["capabilities"]
            or document["capabilities"]
                != sorted(set(document["capabilities"]))
            or any(not isinstance(item, str)
                   or CAPABILITY_ID.fullmatch(item) is None
                   for item in document["capabilities"])):
        raise ValueError("secret provider capability manifest is malformed")


def validate_response(document: Any, request: dict[str, Any]) -> None:
    base_fields = {
        "schemaVersion", "product", "requestId", "providerId", "operation",
        "passed", "reference", "secretBase64", "error",
    }
    leased = request["schemaVersion"] == 2
    fields = base_fields | ({
        "selectedVersion", "leaseId", "issuedAt", "expiresAt"
    } if leased else set())
    if (not isinstance(document, dict) or set(document) != fields
            or document.get("schemaVersion") != request["schemaVersion"]
            or document.get("product") != RESPONSE_PRODUCT
            or document.get("requestId") != request["requestId"]
            or document.get("providerId") != request["providerId"]
            or document.get("operation") != request["operation"]
            or type(document.get("passed")) is not bool
            or document.get("reference") != request["reference"]
            or (document.get("error") is not None
                and (not isinstance(document["error"], str)
                     or not 1 <= len(document["error"]) <= 1024))):
        raise ValueError("secret provider response is malformed")
    if document["passed"]:
        if document["error"] is not None \
                or not isinstance(document.get("secretBase64"), str):
            raise ValueError("secret provider success is malformed")
        if leased and (
                document.get("selectedVersion")
                    not in reference_versions(request["reference"])
                or not package_tool.IDENTIFIER.fullmatch(
                    str(document.get("leaseId", "")))
                or not isinstance(document.get("issuedAt"), str)
                or not isinstance(document.get("expiresAt"), str)):
            raise ValueError("secret provider lease response is malformed")
    elif document["error"] is None or document["secretBase64"] is not None:
        raise ValueError("secret provider failure is malformed")
    elif leased and any(document.get(name) is not None for name in (
            "selectedVersion", "leaseId", "issuedAt", "expiresAt")):
        raise ValueError("secret provider failed lease contains metadata")


class SecretLease(NamedTuple):
    value: bytes
    selected_version: str
    lease_id: str | None
    issued_at: datetime | None
    expires_at: datetime | None

    def remaining_seconds(self, now: datetime | None = None) -> float | None:
        if self.expires_at is None:
            return None
        current = now or package_tool.verification_time(None)
        return (self.expires_at - current).total_seconds()


class ExternalCommandSecretProvider:
    def __init__(self, config_path: str | Path,
                 expected_config_sha256: str) -> None:
        self.config, self.config_path, self.config_sha256 = load_config(
            config_path, expected_config_sha256
        )
        request = _capability_request(self.provider_id)
        manifest = self._invoke(request, configured_environment=False)
        validate_capability_manifest(manifest, request)
        adapter_runtime.enforce_capability_policy(
            self.config, manifest, "secret provider"
        )
        self.capability_manifest = manifest
        self.capability_manifest_sha256 = adapter_runtime.capability_digest(
            manifest, "providerId"
        )

    @property
    def provider_id(self) -> str:
        return str(self.config["providerId"])

    def descriptor(self) -> dict[str, Any]:
        return {
            "kind": "external-command", "providerId": self.provider_id,
            "configPath": str(self.config_path),
            "configSha256": self.config_sha256,
            "capabilityManifestSha256": self.capability_manifest_sha256,
        }

    def _invoke(self, request: dict[str, Any], *,
                configured_environment: bool = True) -> dict[str, Any]:
        config, path, digest = load_config(
            self.config_path, self.config_sha256
        )
        if config != self.config or path != self.config_path \
                or digest != self.config_sha256:
            raise ValueError("secret provider configuration changed")
        environment = adapter_runtime.isolated_environment(
            config["environmentVariables"],
            optional=config.get("optionalEnvironmentVariables", []),
            require_required=configured_environment,
            label="secret provider",
        )
        command = [str(Path(config["executable"]).resolve()), *config["arguments"]]
        return adapter_runtime.invoke_json(
            command, request, environment=environment,
            timeout_seconds=config["timeoutSeconds"],
            max_response_bytes=config["maxResponseBytes"],
            label="secret provider", expose_stderr=False,
        )

    def lease(self, reference: dict[str, Any]) -> SecretLease:
        validate_reference(reference, provider_id=self.provider_id)
        if reference["secretId"] not in self.config["secretIds"]:
            raise ValueError("secret reference is not authorized")
        if (reference["kind"] == "secret-rotation-ref"
                and self.config["schemaVersion"] != 2):
            raise ValueError("secret rotation requires provider schema v2")
        request = _request(self.config, reference)
        response = self._invoke(request)
        validate_response(response, request)
        if not response["passed"]:
            # Error fields are also provider-controlled; retain only a redacted
            # classification at the host boundary.
            raise RuntimeError("secret provider rejected request")
        try:
            content = base64.b64decode(
                response["secretBase64"], validate=True
            )
        except (ValueError, binascii.Error) as error:
            raise ValueError("secret provider returned invalid base64") from error
        if not 1 <= len(content) <= self.config["maxSecretBytes"]:
            raise ValueError("resolved secret size is outside policy")
        if self.config["schemaVersion"] == 1:
            return SecretLease(
                content, reference["version"], None, None, None
            )
        try:
            issued_at = package_tool.verification_time(response["issuedAt"])
            expires_at = package_tool.verification_time(response["expiresAt"])
        except ValueError as error:
            raise ValueError("secret provider lease time is malformed") from error
        now = package_tool.verification_time(None)
        duration = (expires_at - issued_at).total_seconds()
        remaining = (expires_at - now).total_seconds()
        policy = self.config["leasePolicy"]
        if (issued_at > now or duration <= 0
                or duration > policy["requestedLeaseSeconds"]
                or remaining < policy["minimumRemainingSeconds"]):
            raise ValueError("secret provider lease is outside policy")
        if (reference["kind"] == "secret-rotation-ref"
                and response["selectedVersion"] != reference["versions"][0]
                and now > package_tool.verification_time(
                    reference["fallbackUntil"])):
            raise ValueError("secret rotation fallback window expired")
        return SecretLease(
            content, response["selectedVersion"], response["leaseId"],
            issued_at, expires_at,
        )

    def resolve(self, reference: dict[str, Any]) -> bytes:
        return self.lease(reference).value


def check_command(args: argparse.Namespace) -> int:
    try:
        path = package_tool.resolved_path(args.reference, "secret reference")
        content = path.read_bytes()
        if package_tool.sha256_bytes(content) != \
                str(args.expected_reference_sha256).lower():
            raise ValueError("secret reference identity changed")
        reference = json.loads(content)
        provider = ExternalCommandSecretProvider(
            args.config, args.expected_config_sha256
        )
        lease = provider.lease(reference)
        report = {
            "schemaVersion": 2 if lease.expires_at is not None else 1,
            "product": CHECK_PRODUCT, "passed": True,
            "reference": reference, "provider": provider.descriptor(),
            "available": bool(lease.value),
            "checkedAt": registry_tool.utc_time(None),
        }
        if lease.expires_at is not None:
            report["selectedVersion"] = lease.selected_version
            report["leaseExpiresAt"] = lease.expires_at.isoformat()
        if args.report:
            package_tool.write_json(Path(args.report).resolve(), report)
        print(
            "PDR_SECRET_PROVIDER_CHECK_PASS "
            f"provider={provider.provider_id} secret={reference['secretId']} "
            f"version={lease.selected_version} available=1"
        )
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_SECRET_PROVIDER_CHECK_ERROR: {error}", file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--config", required=True)
    result.add_argument("--expected-config-sha256", required=True)
    result.add_argument("--reference", required=True)
    result.add_argument("--expected-reference-sha256", required=True)
    result.add_argument("--report")
    result.set_defaults(handler=check_command)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
