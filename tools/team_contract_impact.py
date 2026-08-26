#!/usr/bin/env python3
"""Preview signed team-contract lock upgrades and route affected consumer tests."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import team_contract_package as package_tool


PRODUCT = "PocoDDSRuntimeTeamContractConsumerCatalog"
REPORT_PRODUCT = "PocoDDSRuntimeTeamContractUpgradeImpact"
LABEL = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$")
ROLE_SET = set(package_tool.ROLE_PRODUCTS)


def canonical_sha(document: Any) -> str:
    return hashlib.sha256(package_tool.canonical_bytes(document)).hexdigest()


def load_json(path: Path, label: str) -> tuple[dict[str, Any], str]:
    path = package_tool.resolved_path(path, label)
    if not path.is_file():
        raise FileNotFoundError(f"{label} is unavailable: {path}")
    try:
        document = json.loads(path.read_bytes())
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is invalid JSON") from error
    if not isinstance(document, dict):
        raise ValueError(f"{label} must be a JSON object")
    return document, package_tool.sha256_file(path)


def load_catalog(path: Path) -> tuple[dict[str, Any], str]:
    catalog, digest = load_json(path, "team contract consumer catalog")
    if (set(catalog) != {"schemaVersion", "product", "consumers"}
            or catalog.get("schemaVersion") != 1 or catalog.get("product") != PRODUCT
            or not isinstance(catalog.get("consumers"), list)):
        raise ValueError("team contract consumer catalog identity is invalid")
    ids: set[str] = set()
    for consumer in catalog["consumers"]:
        if (not isinstance(consumer, dict)
                or set(consumer) != {
                    "id", "owner", "dependencies", "requiredTestLabels"
                }
                or not package_tool.PACKAGE_ID.fullmatch(str(consumer.get("id", "")))
                or not package_tool.IDENTIFIER.fullmatch(str(consumer.get("owner", "")))
                or not isinstance(consumer.get("dependencies"), list)
                or not consumer["dependencies"]
                or not isinstance(consumer.get("requiredTestLabels"), list)
                or not consumer["requiredTestLabels"]):
            raise ValueError("team contract consumer catalog entry is malformed")
        if consumer["id"] in ids:
            raise ValueError(f"duplicate team contract consumer id: {consumer['id']}")
        ids.add(consumer["id"])
        labels = consumer["requiredTestLabels"]
        if (labels != sorted(set(labels))
                or any(not LABEL.fullmatch(str(value)) for value in labels)):
            raise ValueError(
                f"team contract consumer {consumer['id']} test labels are malformed"
            )
        packages: set[str] = set()
        for dependency in consumer["dependencies"]:
            if (not isinstance(dependency, dict)
                    or set(dependency) != {"packageId", "roles"}
                    or not package_tool.PACKAGE_ID.fullmatch(
                        str(dependency.get("packageId", "")))
                    or not isinstance(dependency.get("roles"), list)
                    or any(role not in ROLE_SET for role in dependency["roles"])
                    or dependency["roles"] != sorted(set(dependency["roles"]))):
                raise ValueError(
                    f"team contract consumer {consumer['id']} dependency is malformed"
                )
            if dependency["packageId"] in packages:
                raise ValueError(
                    f"team contract consumer {consumer['id']} repeats a package dependency"
                )
            packages.add(dependency["packageId"])
    if catalog["consumers"] != sorted(catalog["consumers"], key=lambda item: item["id"]):
        raise ValueError("team contract consumer catalog entries are not sorted")
    return catalog, digest


def side_arguments(args: argparse.Namespace, side: str) -> dict[str, Any]:
    return {
        "lock": Path(getattr(args, f"{side}_lock")),
        "packages": getattr(args, f"{side}_package"),
        "trustPolicy": getattr(args, f"{side}_trust_policy"),
        "expectedPolicyId": getattr(args, f"{side}_expected_trust_policy_id"),
        "expectedPolicySha256": getattr(args, f"{side}_expected_trust_policy_sha256"),
    }


def load_side(values: dict[str, Any], at, require_signature: bool) -> dict[str, Any]:
    lock_path = package_tool.resolved_path(values["lock"], "team contract package lock")
    lock = package_tool.load_lock(lock_path)
    locked_trust = lock.get("trustPolicy")
    if require_signature and locked_trust is None:
        raise ValueError("impact analysis requires trusted current and candidate locks")
    trust_path = values["trustPolicy"]
    expected_id = values["expectedPolicyId"]
    expected_sha = values["expectedPolicySha256"]
    if locked_trust is not None:
        if not trust_path or not expected_id or not expected_sha:
            raise ValueError("trusted impact input lacks policy path, expected id or SHA-256")
        if locked_trust != {
                "policyId": expected_id, "policySha256": str(expected_sha).lower()}:
            raise ValueError("impact trust policy identity does not match its package lock")
    elif trust_path or expected_id or expected_sha:
        raise ValueError("untrusted impact input cannot add trust after lock creation")
    supplied: dict[str, dict[str, Any]] = {}
    for value in values["packages"]:
        verified = package_tool.verify_package(Path(value))
        package_id = verified["manifest"]["packageId"]
        if package_id in supplied:
            raise ValueError(f"duplicate supplied impact package id: {package_id}")
        supplied[package_id] = verified
    expected_ids = {item["packageId"] for item in lock["packages"]}
    if set(supplied) != expected_ids:
        raise ValueError(
            f"impact package set does not match lock; missing={sorted(expected_ids - set(supplied))} "
            f"unexpected={sorted(set(supplied) - expected_ids)}"
        )
    records = {item["packageId"]: item for item in lock["packages"]}
    for package_id, verified in supplied.items():
        trust = None
        if locked_trust is not None:
            trust = package_tool.verify_trust(
                verified, Path(trust_path), expected_id, expected_sha, at
            )
        if package_tool.lock_record(verified, trust) != records[package_id]:
            raise ValueError(f"impact package does not match lock: {package_id}")
    return {
        "path": lock_path,
        "sha256": package_tool.sha256_file(lock_path),
        "lock": lock,
        "records": records,
        "packages": supplied,
    }


def version(value: str) -> tuple[int, int, int]:
    match = re.match(r"^([0-9]+)\.([0-9]+)\.([0-9]+)", value)
    if match is None:
        raise ValueError(f"invalid package or service version: {value}")
    return tuple(int(item) for item in match.groups())


def documents(verified: dict[str, Any], role: str) -> list[dict[str, Any]]:
    result = []
    for item in verified["manifest"]["files"]:
        if item["role"] == role:
            result.append(json.loads(verified["entries"][item["path"]]))
    return result


def change(code: str, severity: str, role: str, subject: str,
           detail: str) -> dict[str, str]:
    return {
        "code": code, "severity": severity, "role": role,
        "subject": subject, "detail": detail,
    }


def service_providers(verified: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    providers: dict[tuple[str, str], dict[str, Any]] = {}
    for document in documents(verified, "service-contract"):
        values = document.get("provides", [])
        for item in values:
            key = (str(item.get("contract", "")), str(item.get("serviceName", "")))
            if not all(key) or not isinstance(item.get("version"), str):
                raise ValueError("team contract package service providers are malformed")
            if key in providers and providers[key] != item:
                raise ValueError("team contract package repeats a Provider with conflicting data")
            providers[key] = item
    for document in documents(verified, "service-baseline"):
        for bundle in document.get("bundles", []):
            for item in bundle.get("provides", []):
                key = (str(item.get("contract", "")), str(item.get("serviceName", "")))
                if not all(key) or not isinstance(item.get("version"), str):
                    raise ValueError("team contract package service baseline is malformed")
                if key in providers and providers[key] != item:
                    raise ValueError("team contract package repeats a Provider with conflicting data")
                providers[key] = item
    return providers


def service_requirements(verified: dict[str, Any]) -> dict[str, dict[str, Any]]:
    requirements: dict[str, dict[str, Any]] = {}
    for document in documents(verified, "service-contract"):
        for item in document.get("requires", []):
            contract = str(item.get("contract", ""))
            if not contract or contract in requirements:
                raise ValueError("team contract package service requirements are malformed")
            requirements[contract] = item
    return requirements


def compare_services(current: dict[str, Any], candidate: dict[str, Any]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    old = service_providers(current)
    new = service_providers(candidate)
    for key, provider in sorted(old.items()):
        if key not in new:
            replacement = next((value for candidate_key, value in new.items()
                                if candidate_key[0] == key[0]), None)
            result.append(change(
                "provider-service-renamed" if replacement else "provider-contract-removed",
                "breaking", "service-contract", key[0],
                "published Provider service name changed" if replacement
                else "published Provider contract was removed",
            ))
            continue
        old_version = version(provider["version"])
        new_version = version(new[key]["version"])
        if new_version < old_version:
            result.append(change(
                "provider-version-downgraded", "breaking", "service-contract", key[0],
                f"Provider version decreased from {provider['version']} to {new[key]['version']}",
            ))
        elif new_version[0] != old_version[0]:
            result.append(change(
                "provider-major-version-changed", "breaking", "service-contract", key[0],
                f"Provider major version changed from {provider['version']} to {new[key]['version']}",
            ))
        elif new_version > old_version:
            result.append(change(
                "provider-version-upgraded", "compatible", "service-contract", key[0],
                f"Provider version increased from {provider['version']} to {new[key]['version']}",
            ))
    for key in sorted(set(new) - set(old)):
        if not any(old_key[0] == key[0] for old_key in old):
            result.append(change(
                "provider-contract-added", "compatible", "service-contract", key[0],
                "new Provider contract was added",
            ))
    old_requirements = service_requirements(current)
    new_requirements = service_requirements(candidate)
    for contract, requirement in sorted(new_requirements.items()):
        previous = old_requirements.get(contract)
        if previous is None and requirement.get("required") is True:
            result.append(change(
                "required-dependency-added", "attention", "service-contract", contract,
                "package added a required Service dependency",
            ))
        elif previous is not None and any(
                previous.get(field) != requirement.get(field)
                for field in ("versionRange", "required", "minimumProviders")):
            result.append(change(
                "service-requirement-changed", "attention", "service-contract", contract,
                "Service dependency range, requirement or provider count changed",
            ))
    return result


def owns(prefix: str, key: str) -> bool:
    return key == prefix or key.startswith(prefix + ".")


def participants(verified: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    owner = verified["manifest"]["owner"]
    for document in documents(verified, "participant-declaration"):
        for item in document.get("participants", []):
            normalized = {**item, "owner": owner}
            if not isinstance(item.get("id"), str):
                raise ValueError("team contract package participant declarations are malformed")
            if item["id"] in result and result[item["id"]] != normalized:
                raise ValueError("team contract package repeats a Participant with conflicting data")
            result[item["id"]] = normalized
    for document in documents(verified, "participant-baseline"):
        for item in document.get("participants", []):
            if not isinstance(item.get("id"), str):
                raise ValueError("team contract package participant baseline is malformed")
            if item["id"] in result and result[item["id"]] != item:
                raise ValueError("team contract package repeats a Participant with conflicting data")
            result[item["id"]] = item
    return result


def compare_participants(current: dict[str, Any], candidate: dict[str, Any]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    old = participants(current)
    new = participants(candidate)
    for participant_id, item in sorted(old.items()):
        replacement = new.get(participant_id)
        if replacement is None:
            result.append(change(
                "participant-removed", "breaking", "participant-declaration", participant_id,
                "published configuration Participant was removed",
            ))
            continue
        if replacement.get("owner") != item.get("owner"):
            result.append(change(
                "participant-owner-changed", "breaking", "participant-declaration", participant_id,
                "configuration Participant Owner changed",
            ))
        if replacement.get("serviceName") != item.get("serviceName"):
            result.append(change(
                "participant-service-changed", "breaking", "participant-declaration", participant_id,
                "configuration Participant serviceName changed",
            ))
        old_prefixes = item.get("ownedPrefixes", [])
        new_prefixes = replacement.get("ownedPrefixes", [])
        if not isinstance(old_prefixes, list) or not isinstance(new_prefixes, list):
            raise ValueError("team contract package Participant prefixes are malformed")
        for prefix in old_prefixes:
            if not any(owns(candidate_prefix, prefix) for candidate_prefix in new_prefixes):
                result.append(change(
                    "participant-prefix-narrowed", "breaking", "participant-declaration",
                    participant_id, f"published configuration prefix {prefix} is no longer owned",
                ))
        old_after = item.get("after", [])
        new_after = replacement.get("after", [])
        if not isinstance(old_after, list) or not isinstance(new_after, list):
            raise ValueError("team contract package Participant ordering is malformed")
        for dependency in old_after:
            if dependency not in new_after:
                result.append(change(
                    "participant-ordering-removed", "breaking", "participant-declaration",
                    participant_id, f"published ordering dependency {dependency} was removed",
                ))
    for participant_id in sorted(set(new) - set(old)):
        result.append(change(
            "participant-added", "compatible", "participant-declaration", participant_id,
            "new configuration Participant was added",
        ))
    return result


def lifecycle_entries(verified: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    owner = verified["manifest"]["owner"]
    for role in ("key-lifecycle", "key-lifecycle-baseline"):
        for document in documents(verified, role):
            for item in document.get("entries", []):
                normalized = dict(item)
                normalized.setdefault("owner", owner)
                if not isinstance(item.get("id"), str):
                    raise ValueError("team contract package lifecycle entries are malformed")
                if item["id"] in result and result[item["id"]] != normalized:
                    raise ValueError("team contract package repeats lifecycle data with a conflict")
                result[item["id"]] = normalized
    return result


def compare_lifecycle(current: dict[str, Any], candidate: dict[str, Any]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    old = lifecycle_entries(current)
    new = lifecycle_entries(candidate)
    identity_fields = (
        "owner", "participantId", "operation", "sourceKey", "replacementKey",
        "deprecatedSince", "removalAllowedFrom",
    )
    for entry_id, item in sorted(old.items()):
        replacement = new.get(entry_id)
        if replacement is None:
            result.append(change(
                "key-lifecycle-removed", "breaking", "key-lifecycle", entry_id,
                "published key lifecycle declaration was removed",
            ))
        elif any(item.get(field) != replacement.get(field) for field in identity_fields):
            result.append(change(
                "key-lifecycle-identity-changed", "breaking", "key-lifecycle", entry_id,
                "published key lifecycle identity or removal window changed",
            ))
    for entry_id in sorted(set(new) - set(old)):
        result.append(change(
            "key-lifecycle-added", "compatible", "key-lifecycle", entry_id,
            "new configuration key lifecycle declaration was added",
        ))
    return result


def role_digests(verified: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for item in verified["manifest"]["files"]:
        result.setdefault(item["role"], []).append(item["sha256"])
    return {role: sorted(values) for role, values in sorted(result.items())}


def severity(changes: list[dict[str, str]]) -> str:
    if any(item["severity"] == "breaking" for item in changes):
        return "breaking"
    if any(item["severity"] == "attention" for item in changes):
        return "attention"
    return "compatible"


def compare_package(package_id: str, current: dict[str, Any] | None,
                    candidate: dict[str, Any] | None) -> dict[str, Any]:
    if current is None:
        return {
            "packageId": package_id, "status": "added", "severity": "compatible",
            "currentVersion": None, "candidateVersion": candidate["manifest"]["version"],
            "currentPackageSha256": None, "candidatePackageSha256": candidate["packageSha256"],
            "changedRoles": sorted(role_digests(candidate)),
            "changes": [change(
                "package-added", "compatible", "package", package_id,
                "new team contract package was added",
            )],
        }
    if candidate is None:
        return {
            "packageId": package_id, "status": "removed", "severity": "breaking",
            "currentVersion": current["manifest"]["version"], "candidateVersion": None,
            "currentPackageSha256": current["packageSha256"], "candidatePackageSha256": None,
            "changedRoles": sorted(role_digests(current)),
            "changes": [change(
                "package-removed", "breaking", "package", package_id,
                "team contract package was removed",
            )],
        }
    old_manifest = current["manifest"]
    new_manifest = candidate["manifest"]
    old_roles = role_digests(current)
    new_roles = role_digests(candidate)
    changed_roles = sorted(role for role in set(old_roles) | set(new_roles)
                           if old_roles.get(role) != new_roles.get(role))
    changes: list[dict[str, str]] = []
    if old_manifest["owner"] != new_manifest["owner"]:
        changes.append(change(
            "package-owner-changed", "breaking", "package", package_id,
            "team contract package Owner changed",
        ))
    old_version = version(old_manifest["version"])
    new_version = version(new_manifest["version"])
    if new_version < old_version:
        changes.append(change(
            "package-version-downgraded", "breaking", "package", package_id,
            "team contract package version decreased",
        ))
    elif new_version[0] != old_version[0]:
        changes.append(change(
            "package-major-upgrade", "attention", "package", package_id,
            "team contract package major version changed",
        ))
    elif new_version > old_version or old_manifest["version"] != new_manifest["version"]:
        changes.append(change(
            "package-version-upgraded", "compatible", "package", package_id,
            "team contract package version increased",
        ))
    if old_manifest["version"] == new_manifest["version"] and changed_roles:
        changes.append(change(
            "same-version-contract-drift", "breaking", "package", package_id,
            "contract content changed without a package version change",
        ))
    if any(role in changed_roles for role in ("service-contract", "service-baseline")):
        changes.extend(compare_services(current, candidate))
    if any(role in changed_roles for role in
           ("participant-declaration", "participant-baseline")):
        changes.extend(compare_participants(current, candidate))
    if any(role in changed_roles for role in ("key-lifecycle", "key-lifecycle-baseline")):
        changes.extend(compare_lifecycle(current, candidate))
    if changed_roles and not changes:
        changes.append(change(
            "contract-bytes-changed", "compatible", changed_roles[0], package_id,
            "contract bytes changed without a detected published-surface break",
        ))
    if (not changed_roles and old_manifest["version"] == new_manifest["version"]
            and old_manifest["owner"] == new_manifest["owner"]
            and current["signatureSha256"] != candidate["signatureSha256"]):
        changes.append(change(
            "publisher-evidence-changed", "attention", "package", package_id,
            "signature evidence changed while contract content stayed identical",
        ))
    status = "unchanged" if not changes else "changed"
    return {
        "packageId": package_id, "status": status, "severity": severity(changes),
        "currentVersion": old_manifest["version"],
        "candidateVersion": new_manifest["version"],
        "currentPackageSha256": current["packageSha256"],
        "candidatePackageSha256": candidate["packageSha256"],
        "changedRoles": changed_roles,
        "changes": sorted(changes, key=lambda item: (
            item["severity"], item["role"], item["subject"], item["code"]
        )),
    }


def route_consumers(catalog: dict[str, Any], packages: list[dict[str, Any]],
                    trust_changed: bool) -> list[dict[str, Any]]:
    changed = {item["packageId"]: item for item in packages if item["status"] != "unchanged"}
    result = []
    for consumer in catalog["consumers"]:
        reasons: list[dict[str, Any]] = []
        for dependency in consumer["dependencies"]:
            impact = changed.get(dependency["packageId"])
            if impact is None:
                continue
            roles = dependency["roles"]
            if (impact["status"] in {"removed", "added"} or not roles
                    or set(roles) & set(impact["changedRoles"])):
                reasons.append({
                    "packageId": dependency["packageId"],
                    "roles": sorted(set(roles) & set(impact["changedRoles"])) if roles else
                        impact["changedRoles"],
                    "severity": ("breaking" if impact["severity"] == "breaking"
                                 else "attention"),
                })
        if trust_changed and consumer["dependencies"]:
            reasons.append({
                "packageId": "*", "roles": [], "severity": "attention",
            })
        if reasons:
            result.append({
                "id": consumer["id"], "owner": consumer["owner"],
                "severity": ("breaking" if any(item["severity"] == "breaking"
                                                 for item in reasons) else "attention"),
                "requiredTestLabels": consumer["requiredTestLabels"],
                "reasons": sorted(reasons, key=lambda item: item["packageId"]),
            })
    return result


def analyze(args: argparse.Namespace) -> dict[str, Any]:
    at = package_tool.verification_time(args.verification_time)
    current = load_side(side_arguments(args, "current"), at, args.require_signature)
    candidate = load_side(side_arguments(args, "candidate"), at, args.require_signature)
    catalog, catalog_sha = load_catalog(Path(args.consumer_catalog))
    package_ids = sorted(set(current["packages"]) | set(candidate["packages"]))
    packages = [compare_package(
        package_id, current["packages"].get(package_id),
        candidate["packages"].get(package_id),
    ) for package_id in package_ids]
    current_trust = current["lock"].get("trustPolicy")
    candidate_trust = candidate["lock"].get("trustPolicy")
    trust_changed = current_trust != candidate_trust
    consumers = route_consumers(catalog, packages, trust_changed)
    labels = sorted({label for item in consumers for label in item["requiredTestLabels"]})
    breaking_count = sum(
        1 for item in packages for entry in item["changes"]
        if entry["severity"] == "breaking"
    )
    attention_count = sum(
        1 for item in packages for entry in item["changes"]
        if entry["severity"] == "attention"
    ) + int(trust_changed)
    input_identity = {
        "currentLockSha256": current["sha256"],
        "candidateLockSha256": candidate["sha256"],
        "consumerCatalogSha256": catalog_sha,
    }
    return {
        "schemaVersion": 1,
        "product": REPORT_PRODUCT,
        "operation": "team-contract-upgrade-impact",
        "compatible": breaking_count == 0,
        "reviewRequired": bool(breaking_count or attention_count or consumers),
        "inputSetSha256": canonical_sha(input_identity),
        **input_identity,
        "currentTrustPolicy": current_trust,
        "candidateTrustPolicy": candidate_trust,
        "trustPolicyChanged": trust_changed,
        "breakingChangeCount": breaking_count,
        "attentionChangeCount": attention_count,
        "affectedConsumerCount": len(consumers),
        "requiredTestLabels": labels,
        "ctestLabelRegex": ("^(" + "|".join(re.escape(label) for label in labels) + ")$"
                            if labels else None),
        "packages": packages,
        "affectedConsumers": consumers,
    }


def validate_report(report: dict[str, Any]) -> None:
    required = {
        "schemaVersion", "product", "operation", "compatible", "reviewRequired",
        "inputSetSha256", "currentLockSha256", "candidateLockSha256",
        "consumerCatalogSha256", "currentTrustPolicy", "candidateTrustPolicy",
        "trustPolicyChanged", "breakingChangeCount", "attentionChangeCount",
        "affectedConsumerCount", "requiredTestLabels", "ctestLabelRegex",
        "packages", "affectedConsumers",
    }
    if (not isinstance(report, dict) or set(report) != required
            or report.get("schemaVersion") != 1 or report.get("product") != REPORT_PRODUCT
            or report.get("operation") != "team-contract-upgrade-impact"
            or any(not package_tool.SHA256.fullmatch(str(report.get(field, "")))
                   for field in ("inputSetSha256", "currentLockSha256",
                                 "candidateLockSha256", "consumerCatalogSha256"))
            or any(type(report.get(field)) is not bool
                   for field in ("compatible", "reviewRequired", "trustPolicyChanged"))
            or any(type(report.get(field)) is not int or report[field] < 0
                   for field in ("breakingChangeCount", "attentionChangeCount",
                                 "affectedConsumerCount"))
            or not isinstance(report.get("packages"), list)
            or not isinstance(report.get("affectedConsumers"), list)
            or not isinstance(report.get("requiredTestLabels"), list)):
        raise ValueError("team contract upgrade impact report is malformed")
    identity = {
        key: report[key] for key in (
            "currentLockSha256", "candidateLockSha256", "consumerCatalogSha256"
        )
    }
    if report["inputSetSha256"] != canonical_sha(identity):
        raise ValueError("team contract upgrade impact input-set digest is invalid")
    for field in ("currentTrustPolicy", "candidateTrustPolicy"):
        trust = report[field]
        if trust is not None and (
                not isinstance(trust, dict) or set(trust) != {"policyId", "policySha256"}
                or not package_tool.IDENTIFIER.fullmatch(str(trust.get("policyId", "")))
                or not package_tool.SHA256.fullmatch(str(trust.get("policySha256", "")))):
            raise ValueError("team contract upgrade impact trust identity is malformed")
    if report["trustPolicyChanged"] != (
            report["currentTrustPolicy"] != report["candidateTrustPolicy"]):
        raise ValueError("team contract upgrade impact trust change flag is inconsistent")
    package_ids: set[str] = set()
    changes: list[dict[str, Any]] = []
    package_fields = {
        "packageId", "status", "severity", "currentVersion", "candidateVersion",
        "currentPackageSha256", "candidatePackageSha256", "changedRoles", "changes",
    }
    change_fields = {"code", "severity", "role", "subject", "detail"}
    for item in report["packages"]:
        if (not isinstance(item, dict) or set(item) != package_fields
                or not package_tool.PACKAGE_ID.fullmatch(str(item.get("packageId", "")))
                or item["packageId"] in package_ids
                or item.get("status") not in {"unchanged", "changed", "added", "removed"}
                or item.get("severity") not in {"compatible", "attention", "breaking"}
                or not isinstance(item.get("changedRoles"), list)
                or item["changedRoles"] != sorted(set(item["changedRoles"]))
                or any(role not in ROLE_SET for role in item["changedRoles"])
                or not isinstance(item.get("changes"), list)):
            raise ValueError("team contract upgrade impact package record is malformed")
        package_ids.add(item["packageId"])
        for entry in item["changes"]:
            if (not isinstance(entry, dict) or set(entry) != change_fields
                    or entry.get("severity") not in {"compatible", "attention", "breaking"}
                    or entry.get("role") not in ROLE_SET | {"package"}
                    or any(not isinstance(entry.get(field), str) or not entry[field]
                           for field in ("code", "subject", "detail"))):
                raise ValueError("team contract upgrade impact change record is malformed")
            changes.append(entry)
    if report["packages"] != sorted(report["packages"], key=lambda item: item["packageId"]):
        raise ValueError("team contract upgrade impact packages are not sorted")
    breaking_count = sum(item["severity"] == "breaking" for item in changes)
    attention_count = sum(item["severity"] == "attention" for item in changes) \
        + int(report["trustPolicyChanged"])
    if (report["breakingChangeCount"] != breaking_count
            or report["attentionChangeCount"] != attention_count
            or report["compatible"] != (breaking_count == 0)):
        raise ValueError("team contract upgrade impact severity counts are inconsistent")
    consumer_ids: set[str] = set()
    labels: set[str] = set()
    for consumer in report["affectedConsumers"]:
        if (not isinstance(consumer, dict)
                or set(consumer) != {
                    "id", "owner", "severity", "requiredTestLabels", "reasons"
                }
                or not package_tool.PACKAGE_ID.fullmatch(str(consumer.get("id", "")))
                or consumer["id"] in consumer_ids
                or not package_tool.IDENTIFIER.fullmatch(str(consumer.get("owner", "")))
                or consumer.get("severity") not in {"attention", "breaking"}
                or not isinstance(consumer.get("requiredTestLabels"), list)
                or consumer["requiredTestLabels"] != sorted(
                    set(consumer["requiredTestLabels"]))
                or any(not LABEL.fullmatch(str(label))
                       for label in consumer["requiredTestLabels"])
                or not isinstance(consumer.get("reasons"), list)
                or not consumer["reasons"]):
            raise ValueError("team contract upgrade affected Consumer is malformed")
        consumer_ids.add(consumer["id"])
        labels.update(consumer["requiredTestLabels"])
    if report["affectedConsumers"] != sorted(
            report["affectedConsumers"], key=lambda item: item["id"]):
        raise ValueError("team contract upgrade affected Consumers are not sorted")
    expected_labels = sorted(labels)
    expected_regex = ("^(" + "|".join(re.escape(label) for label in expected_labels) + ")$"
                      if expected_labels else None)
    if (report["affectedConsumerCount"] != len(report["affectedConsumers"])
            or report["requiredTestLabels"] != expected_labels
            or report["ctestLabelRegex"] != expected_regex
            or report["reviewRequired"] != bool(
                breaking_count or attention_count or report["affectedConsumers"])):
        raise ValueError("team contract upgrade Consumer routing is inconsistent")


def impact_command(args: argparse.Namespace) -> int:
    try:
        report = analyze(args)
        validate_report(report)
        package_tool.write_json(Path(args.report).resolve(), report)
        if not report["compatible"]:
            print(
                "PDR_TEAM_CONTRACT_IMPACT_BREAKING "
                f"changes={report['breakingChangeCount']} "
                f"consumers={report['affectedConsumerCount']}", file=sys.stderr,
            )
            return 1
        print(
            "PDR_TEAM_CONTRACT_IMPACT_PASS "
            f"review={str(report['reviewRequired']).lower()} "
            f"consumers={report['affectedConsumerCount']}"
        )
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(f"PDR_TEAM_CONTRACT_IMPACT_ERROR: {error}", file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--current-lock", required=True)
    result.add_argument("--current-package", action="append", default=[])
    result.add_argument("--candidate-lock", required=True)
    result.add_argument("--candidate-package", action="append", default=[])
    result.add_argument("--consumer-catalog", required=True)
    result.add_argument("--require-signature", action="store_true")
    for side in ("current", "candidate"):
        result.add_argument(f"--{side}-trust-policy")
        result.add_argument(f"--{side}-expected-trust-policy-id")
        result.add_argument(f"--{side}-expected-trust-policy-sha256")
    result.add_argument("--verification-time")
    result.add_argument("--report", required=True)
    result.set_defaults(handler=impact_command)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
