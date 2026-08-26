#!/usr/bin/env python3
"""Pack, pin and resolve immutable cross-team contract documents."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


PRODUCT = "PocoDDSRuntimeTeamContractPackage"
SIGNATURE_PRODUCT = "PocoDDSRuntimeTeamContractPackageSignature"
TRUST_POLICY_PRODUCT = "PocoDDSRuntimeTeamContractTrustPolicy"
LOCK_PRODUCT = "PocoDDSRuntimeTeamContractPackageLock"
RESOLUTION_PRODUCT = "PocoDDSRuntimeTeamContractPackageResolution"
PACKAGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_FILES_DEFAULT = 64
MAX_EXPANDED_BYTES_DEFAULT = 16 * 1024 * 1024
ROLE_PRODUCTS = {
    "service-contract": None,
    "participant-declaration": None,
    "key-lifecycle": None,
    "service-baseline": "PocoDDSRuntimeServiceContractBaseline",
    "participant-baseline": "PocoDDSRuntimeConfigurationParticipantBaseline",
    "key-lifecycle-baseline": "PocoDDSRuntimeConfigurationKeyLifecycleBaseline",
}
ROLE_FIELDS = {
    "service-contract": ("provides", "requires"),
    "participant-declaration": ("participants",),
    "key-lifecycle": ("entries",),
    "service-baseline": ("bundles",),
    "participant-baseline": ("participants",),
    "key-lifecycle-baseline": ("entries",),
}


def json_bytes(document: Any) -> bytes:
    return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def canonical_bytes(document: Any) -> bytes:
    return json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_archive_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (not path.parts or path.is_absolute() or "\\" in value
            or any(part in {"", ".", ".."} for part in path.parts)):
        raise ValueError(f"unsafe contract package entry: {value}")
    return path


def resolved_path(value: str | Path, label: str) -> Path:
    supplied = Path(value)
    if supplied.is_symlink():
        raise ValueError(f"{label} must not be a link: {supplied}")
    return supplied.resolve()


def source_datetime(epoch: int) -> tuple[int, int, int, int, int, int]:
    if epoch < 0:
        raise ValueError("source date epoch must be non-negative")
    moment = datetime.fromtimestamp(epoch, timezone.utc)
    if moment.year < 1980:
        return 1980, 1, 1, 0, 0, 0
    if moment.year > 2107:
        raise ValueError("source date epoch exceeds ZIP timestamp range")
    return moment.year, moment.month, moment.day, moment.hour, moment.minute, moment.second


def zip_info(name: str, epoch: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, source_datetime(epoch))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    return info


def validate_identity(package_id: str, version: str, owner: str) -> None:
    if not PACKAGE_ID.fullmatch(package_id):
        raise ValueError("package id is invalid")
    if not VERSION.fullmatch(version):
        raise ValueError("package version is not semantic")
    if not IDENTIFIER.fullmatch(owner):
        raise ValueError("package owner is invalid")


def parse_time(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"team contract trust policy {field} is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"team contract trust policy {field} is invalid") from error
    if parsed.tzinfo is None:
        raise ValueError(f"team contract trust policy {field} must include timezone")
    return parsed.astimezone(timezone.utc)


def verification_time(value: str | None) -> datetime:
    return parse_time(value, "verificationTime") if value else datetime.now(timezone.utc)


def create_signature(manifest_content: bytes, manifest: dict[str, Any],
                     args: argparse.Namespace) -> bytes | None:
    key_environment = args.ed25519_private_key_environment
    key_id = args.signing_key_id
    if bool(key_environment) != bool(key_id):
        raise ValueError("Ed25519 private key environment and signing key id are required together")
    if args.private_key_passphrase_environment and not key_environment:
        raise ValueError("private key passphrase requires Ed25519 signing")
    if not key_environment:
        return None
    if not IDENTIFIER.fullmatch(key_id):
        raise ValueError("signing key id is invalid")
    key_value = os.environ.get(key_environment)
    if not key_value:
        raise ValueError(f"Ed25519 private key path environment is unset: {key_environment}")
    key_path = resolved_path(key_value, "Ed25519 private key")
    if not key_path.is_file():
        raise FileNotFoundError(f"Ed25519 private key is unavailable: {key_path}")
    passphrase = None
    if args.private_key_passphrase_environment:
        value = os.environ.get(args.private_key_passphrase_environment)
        if value is None:
            raise ValueError("private key passphrase environment is unset")
        passphrase = value.encode("utf-8")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
    except ImportError as error:
        raise ValueError("Ed25519 signing requires the cryptography package") from error
    key = load_pem_private_key(key_path.read_bytes(), password=passphrase)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("team contract package private key is not Ed25519")
    return json_bytes({
        "schemaVersion": 1,
        "product": SIGNATURE_PRODUCT,
        "algorithm": "Ed25519",
        "keyId": key_id,
        "packageId": manifest["packageId"],
        "version": manifest["version"],
        "owner": manifest["owner"],
        "manifestSha256": sha256_bytes(manifest_content),
        "artifactSetSha256": manifest["artifactSetSha256"],
        "signature": base64.b64encode(key.sign(manifest_content)).decode("ascii"),
    })


def validate_signature_envelope(content: bytes, manifest_content: bytes,
                                manifest: dict[str, Any]) -> dict[str, Any]:
    try:
        signature = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("team contract package signature is invalid JSON") from error
    expected = {
        "schemaVersion": 1,
        "product": SIGNATURE_PRODUCT,
        "algorithm": "Ed25519",
        "packageId": manifest["packageId"],
        "version": manifest["version"],
        "owner": manifest["owner"],
        "manifestSha256": sha256_bytes(manifest_content),
        "artifactSetSha256": manifest["artifactSetSha256"],
    }
    signature_fields = {*expected, "keyId", "signature"}
    if (not isinstance(signature, dict) or set(signature) != signature_fields
            or any(signature.get(key) != value for key, value in expected.items())):
        raise ValueError("team contract package signature identity is invalid")
    if not IDENTIFIER.fullmatch(str(signature.get("keyId", ""))):
        raise ValueError("team contract package signature key id is invalid")
    try:
        decoded = base64.b64decode(signature.get("signature", ""), validate=True)
    except (TypeError, ValueError) as error:
        raise ValueError("team contract package signature encoding is invalid") from error
    if len(decoded) != 64:
        raise ValueError("team contract package Ed25519 signature length is invalid")
    return signature


def load_trust_policy(path: Path, expected_id: str, expected_sha256: str) -> tuple[dict[str, Any], str]:
    policy_path = resolved_path(path, "team contract trust policy")
    if not policy_path.is_file():
        raise FileNotFoundError(f"team contract trust policy is unavailable: {policy_path}")
    actual_sha256 = sha256_file(policy_path)
    if not SHA256.fullmatch(str(expected_sha256).lower()):
        raise ValueError("expected team contract trust policy SHA-256 is invalid")
    if actual_sha256 != str(expected_sha256).lower():
        raise ValueError("team contract trust policy SHA-256 is not trusted")
    try:
        policy = json.loads(policy_path.read_bytes())
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("team contract trust policy is invalid JSON") from error
    if (not isinstance(policy, dict)
            or set(policy) != {
                "schemaVersion", "product", "policyId", "allowedPublishers", "revokedKeys"
            }
            or policy.get("schemaVersion") != 1
            or policy.get("product") != TRUST_POLICY_PRODUCT
            or policy.get("policyId") != expected_id
            or not IDENTIFIER.fullmatch(str(expected_id))):
        raise ValueError("team contract trust policy identity is invalid")
    publishers = policy.get("allowedPublishers")
    revoked = policy.get("revokedKeys")
    if not isinstance(publishers, list) or not publishers or not isinstance(revoked, list):
        raise ValueError("team contract trust policy publisher or revocation list is malformed")
    seen_keys: set[str] = set()
    publisher_fields = {
        "owner", "keyId", "algorithm", "publicKey", "publicKeySha256",
        "packageIds", "packagePrefixes", "notBefore", "notAfter",
    }
    required_publisher_fields = {
        "owner", "keyId", "algorithm", "publicKey", "publicKeySha256",
        "notBefore", "notAfter",
    }
    for publisher in publishers:
        if (not isinstance(publisher, dict)
                or not set(publisher).issubset(publisher_fields)
                or not required_publisher_fields.issubset(publisher)
                or not IDENTIFIER.fullmatch(str(publisher.get("owner", "")))
                or not IDENTIFIER.fullmatch(str(publisher.get("keyId", "")))
                or publisher.get("algorithm") != "Ed25519"
                or not isinstance(publisher.get("publicKey"), str)
                or not re.fullmatch(r"keys/[A-Za-z0-9._-]+\.pem", publisher["publicKey"])
                or not SHA256.fullmatch(str(publisher.get("publicKeySha256", "")))):
            raise ValueError("team contract trust policy publisher entry is malformed")
        if publisher["keyId"] in seen_keys:
            raise ValueError(f"duplicate team contract trust policy key id: {publisher['keyId']}")
        seen_keys.add(publisher["keyId"])
        not_before = parse_time(publisher["notBefore"], "notBefore")
        not_after = parse_time(publisher["notAfter"], "notAfter")
        if not_before > not_after:
            raise ValueError("team contract trust policy validity window is reversed")
        package_ids = publisher.get("packageIds", [])
        prefixes = publisher.get("packagePrefixes", [])
        if (not isinstance(package_ids, list) or not isinstance(prefixes, list)
                or not package_ids and not prefixes
                or any(not PACKAGE_ID.fullmatch(str(value)) for value in package_ids)
                or any(not PACKAGE_ID.fullmatch(str(value)) or not str(value).endswith(".")
                       for value in prefixes)
                or len(set(str(value) for value in package_ids)) != len(package_ids)
                or len(set(str(value) for value in prefixes)) != len(prefixes)):
            raise ValueError("team contract trust policy package scope is malformed")
    seen_revocations: set[str] = set()
    for entry in revoked:
        if (not isinstance(entry, dict)
                or set(entry) != {"keyId", "revokedAt", "reason"}
                or not IDENTIFIER.fullmatch(str(entry.get("keyId", "")))
                or not isinstance(entry.get("reason"), str) or not entry["reason"]):
            raise ValueError("team contract trust policy revoked key entry is malformed")
        parse_time(entry["revokedAt"], "revokedAt")
        if entry["keyId"] in seen_revocations:
            raise ValueError(f"duplicate team contract key revocation: {entry['keyId']}")
        seen_revocations.add(entry["keyId"])
    return policy, actual_sha256


def policy_public_key(policy_path: Path, value: str) -> Path:
    if not isinstance(value, str):
        raise ValueError("team contract trust policy public key path is invalid")
    relative = safe_archive_path(value)
    raw = policy_path.parent.joinpath(*relative.parts)
    key_path = resolved_path(raw, "team contract public key")
    try:
        key_path.relative_to(policy_path.parent.resolve())
    except ValueError as error:
        raise ValueError("team contract public key escapes the trust policy directory") from error
    if not key_path.is_file():
        raise FileNotFoundError(f"team contract public key is unavailable: {key_path}")
    return key_path


def verify_trust(verified: dict[str, Any], policy_path: Path, expected_id: str,
                 expected_sha256: str, at: datetime) -> dict[str, Any]:
    signature = verified.get("signature")
    if signature is None:
        raise ValueError("trusted team contract package signature is required")
    policy_path = resolved_path(policy_path, "team contract trust policy")
    policy, policy_sha256 = load_trust_policy(policy_path, expected_id, expected_sha256)
    key_id = signature["keyId"]
    for revoked in policy["revokedKeys"]:
        if (not isinstance(revoked, dict) or not IDENTIFIER.fullmatch(
                str(revoked.get("keyId", ""))) or not isinstance(revoked.get("reason"), str)):
            raise ValueError("team contract trust policy revoked key entry is malformed")
        parse_time(revoked.get("revokedAt"), "revokedAt")
        if revoked["keyId"] == key_id:
            raise ValueError(f"team contract signing key is revoked: {key_id}: {revoked['reason']}")
    matches = [entry for entry in policy["allowedPublishers"]
               if isinstance(entry, dict) and entry.get("keyId") == key_id]
    if len(matches) != 1:
        raise ValueError("team contract signing key is not uniquely trusted")
    publisher = matches[0]
    manifest = verified["manifest"]
    if (publisher.get("algorithm") != "Ed25519"
            or publisher.get("owner") != manifest["owner"]):
        raise ValueError("team contract signer Owner or algorithm is not trusted")
    not_before = parse_time(publisher.get("notBefore"), "notBefore")
    not_after = parse_time(publisher.get("notAfter"), "notAfter")
    if not_before > not_after or at < not_before or at > not_after:
        raise ValueError("team contract signing key is outside its validity window")
    package_ids = publisher.get("packageIds", [])
    prefixes = publisher.get("packagePrefixes", [])
    if (not isinstance(package_ids, list) or not isinstance(prefixes, list)
            or not package_ids and not prefixes
            or any(not PACKAGE_ID.fullmatch(str(value)) for value in package_ids)
            or any(not PACKAGE_ID.fullmatch(str(value)) or not str(value).endswith(".")
                   for value in prefixes)):
        raise ValueError("team contract trust policy package scope is malformed")
    package_id = manifest["packageId"]
    if package_id not in package_ids and not any(package_id.startswith(value) for value in prefixes):
        raise ValueError("team contract package id is outside the signing key scope")
    public_key = policy_public_key(policy_path, publisher.get("publicKey"))
    public_key_sha256 = sha256_file(public_key)
    if (not SHA256.fullmatch(str(publisher.get("publicKeySha256", "")))
            or publisher["publicKeySha256"] != public_key_sha256):
        raise ValueError("team contract public key SHA-256 is not trusted")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
    except ImportError as error:
        raise ValueError("Ed25519 verification requires the cryptography package") from error
    key = load_pem_public_key(public_key.read_bytes())
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("team contract public key is not Ed25519")
    try:
        decoded = base64.b64decode(signature["signature"], validate=True)
        key.verify(decoded, verified["manifestBytes"])
    except Exception as error:
        raise ValueError("team contract package Ed25519 verification failed") from error
    return {
        "policyId": expected_id,
        "policySha256": policy_sha256,
        "keyId": key_id,
        "publicKeySha256": public_key_sha256,
    }


def load_contract(role: str, path: Path) -> bytes:
    if role not in ROLE_PRODUCTS:
        raise ValueError(f"unsupported contract role: {role}")
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(f"contract input not found or is a link: {path}")
    content = path.read_bytes()
    try:
        document = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"contract input is not valid JSON: {path}") from error
    if not isinstance(document, dict) or document.get("schemaVersion") != 1:
        raise ValueError(f"contract input has unsupported schema identity: {path}")
    expected_product = ROLE_PRODUCTS[role]
    if expected_product is not None and document.get("product") != expected_product:
        raise ValueError(f"contract input product does not match role {role}: {path}")
    for field in ROLE_FIELDS[role]:
        if not isinstance(document.get(field), list):
            raise ValueError(f"contract input for role {role} lacks array field {field}: {path}")
    return content


def parse_input(value: str) -> tuple[str, Path]:
    role, separator, supplied = value.partition("=")
    if not separator or not role or not supplied:
        raise ValueError("contract input must use ROLE=PATH")
    return role, resolved_path(supplied, "contract input")


def artifact_set_sha(files: list[dict[str, Any]]) -> str:
    identity = [
        {"role": item["role"], "path": item["path"], "size": item["size"],
         "sha256": item["sha256"]}
        for item in files
    ]
    return sha256_bytes(canonical_bytes(identity))


def inspect_archive(path: Path, maximum_files: int,
                    maximum_bytes: int) -> dict[str, bytes]:
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(f"contract package not found or is a link: {path}")
    size = path.stat().st_size
    with path.open("rb") as stream:
        stream.seek(max(0, size - (65535 + 22)))
        tail = stream.read()
    marker = tail.rfind(b"PK\x05\x06")
    if marker < 0 or marker + 22 > len(tail):
        raise ValueError("contract package ZIP end record is missing")
    comment_size = int.from_bytes(tail[marker + 20:marker + 22], "little")
    if marker + 22 + comment_size != len(tail):
        raise ValueError("contract package contains bytes after the ZIP end record")
    entries: dict[str, bytes] = {}
    expanded = 0
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > maximum_files:
                raise ValueError(f"contract package file count exceeds {maximum_files}")
            for info in infos:
                name = info.filename
                safe_archive_path(name)
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise ValueError(f"contract package links are prohibited: {name}")
                if name in entries:
                    raise ValueError(f"duplicate contract package entry: {name}")
                expanded += info.file_size
                if expanded > maximum_bytes:
                    raise ValueError(
                        f"contract package expanded size exceeds {maximum_bytes} bytes"
                    )
                entries[name] = archive.read(info)
    except zipfile.BadZipFile as error:
        raise ValueError("contract package is not a valid ZIP archive") from error
    return entries


def verify_package(path: Path, maximum_files: int = MAX_FILES_DEFAULT,
                   maximum_bytes: int = MAX_EXPANDED_BYTES_DEFAULT) -> dict[str, Any]:
    path = resolved_path(path, "contract package")
    entries = inspect_archive(path, maximum_files, maximum_bytes)
    manifest_name = "metadata/team-contract-package.json"
    if manifest_name not in entries:
        raise ValueError("contract package manifest is missing")
    try:
        manifest = json.loads(entries[manifest_name])
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("contract package manifest is invalid JSON") from error
    if (not isinstance(manifest, dict)
            or set(manifest) != {
                "schemaVersion", "product", "packageId", "version", "owner",
                "sourceDateEpoch", "artifactSetSha256", "files"
            }
            or manifest.get("schemaVersion") != 1
            or manifest.get("product") != PRODUCT
            or type(manifest.get("sourceDateEpoch")) is not int
            or manifest["sourceDateEpoch"] < 0
            or not SHA256.fullmatch(str(manifest.get("artifactSetSha256", "")))):
        raise ValueError("contract package manifest identity is invalid")
    validate_identity(
        str(manifest.get("packageId", "")), str(manifest.get("version", "")),
        str(manifest.get("owner", "")),
    )
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("contract package manifest contains no files")
    signature_name = "metadata/team-contract-package.sig.json"
    expected_paths = {manifest_name}
    signature = None
    signature_sha256 = None
    if signature_name in entries:
        expected_paths.add(signature_name)
        signature = validate_signature_envelope(
            entries[signature_name], entries[manifest_name], manifest
        )
        signature_sha256 = sha256_bytes(entries[signature_name])
    seen_role_digest: set[tuple[str, str]] = set()
    for item in files:
        if not isinstance(item, dict) or set(item) != {"role", "path", "size", "sha256"}:
            raise ValueError("contract package contains malformed file evidence")
        role = item.get("role")
        name = item.get("path")
        digest = item.get("sha256")
        if role not in ROLE_PRODUCTS or not isinstance(name, str):
            raise ValueError("contract package file role or path is invalid")
        safe_archive_path(name)
        if name in expected_paths:
            raise ValueError(f"duplicate contract package manifest path: {name}")
        expected_name = f"contracts/{role}/{digest}.json"
        if not SHA256.fullmatch(str(digest)) or name != expected_name:
            raise ValueError(f"contract package content-addressed path is invalid: {name}")
        role_digest = (role, digest)
        if role_digest in seen_role_digest:
            raise ValueError(f"duplicate contract package role/content: {role}/{digest}")
        seen_role_digest.add(role_digest)
        expected_paths.add(name)
        content = entries.get(name)
        if content is None:
            raise ValueError(f"contract package entry is missing: {name}")
        if (type(item.get("size")) is not int or item["size"] < 0
                or item["size"] != len(content) or sha256_bytes(content) != digest):
            raise ValueError(f"contract package entry changed: {name}")
        try:
            document = json.loads(content)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError(f"contract package entry is invalid JSON: {name}") from error
        if not isinstance(document, dict) or document.get("schemaVersion") != 1:
            raise ValueError(f"contract package entry has unsupported schema identity: {name}")
        expected_product = ROLE_PRODUCTS[role]
        if expected_product is not None and document.get("product") != expected_product:
            raise ValueError(f"contract package entry product does not match role: {name}")
        for field in ROLE_FIELDS[role]:
            if not isinstance(document.get(field), list):
                raise ValueError(f"contract package entry lacks array field {field}: {name}")
    if set(entries) != expected_paths:
        unexpected = sorted(set(entries) - expected_paths)
        missing = sorted(expected_paths - set(entries))
        raise ValueError(f"contract package entry set mismatch; unexpected={unexpected} missing={missing}")
    if manifest.get("artifactSetSha256") != artifact_set_sha(files):
        raise ValueError("contract package artifact-set digest mismatch")
    return {
        "manifest": manifest,
        "manifestBytes": entries[manifest_name],
        "manifestSha256": sha256_bytes(entries[manifest_name]),
        "packageSha256": sha256_file(path),
        "signature": signature,
        "signatureSha256": signature_sha256,
        "entries": entries,
    }


def pack(args: argparse.Namespace) -> int:
    validate_identity(args.package_id, args.version, args.owner)
    output = resolved_path(args.output, "contract package output")
    if output.exists() and not args.force:
        raise FileExistsError(f"contract package output already exists: {output}")
    records: list[tuple[str, str, bytes]] = []
    seen: set[tuple[str, str]] = set()
    total = 0
    for value in args.input:
        role, path = parse_input(value)
        content = load_contract(role, path)
        digest = sha256_bytes(content)
        if (role, digest) in seen:
            raise ValueError(f"duplicate contract input role/content: {role}/{digest}")
        seen.add((role, digest))
        records.append((role, digest, content))
        total += len(content)
    if not records:
        raise ValueError("at least one contract input is required")
    signing = bool(args.ed25519_private_key_environment or args.signing_key_id)
    if len(records) + 1 + int(signing) > args.maximum_files:
        raise ValueError(f"contract package file count exceeds {args.maximum_files}")
    if total > args.maximum_expanded_bytes:
        raise ValueError(
            f"contract package expanded size exceeds {args.maximum_expanded_bytes} bytes"
        )
    entries: dict[str, bytes] = {}
    files: list[dict[str, Any]] = []
    for role, digest, content in sorted(records, key=lambda item: (item[0], item[1])):
        name = f"contracts/{role}/{digest}.json"
        entries[name] = content
        files.append({"role": role, "path": name, "size": len(content), "sha256": digest})
    manifest = {
        "schemaVersion": 1,
        "product": PRODUCT,
        "packageId": args.package_id,
        "version": args.version,
        "owner": args.owner,
        "sourceDateEpoch": args.source_date_epoch,
        "artifactSetSha256": artifact_set_sha(files),
        "files": files,
    }
    manifest_content = json_bytes(manifest)
    entries["metadata/team-contract-package.json"] = manifest_content
    signature = create_signature(manifest_content, manifest, args)
    if signature is not None:
        entries["metadata/team-contract-package.sig.json"] = signature
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    try:
        with zipfile.ZipFile(
                temporary, "w", compression=zipfile.ZIP_DEFLATED,
                compresslevel=9, strict_timestamps=True) as archive:
            for name, content in sorted(entries.items()):
                archive.writestr(zip_info(name, args.source_date_epoch), content)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    result = verify_package(output, args.maximum_files, args.maximum_expanded_bytes)
    print(
        f"PDR_TEAM_CONTRACT_PACKAGE_PACK_PASS id={args.package_id} version={args.version} "
        f"files={len(files)} sha256={result['packageSha256']} output={output}"
    )
    return 0


def verification_report(path: Path, verified: dict[str, Any],
                        trust: dict[str, Any] | None = None) -> dict[str, Any]:
    manifest = verified["manifest"]
    return {
        "schemaVersion": 1,
        "product": RESOLUTION_PRODUCT,
        "operation": "verify",
        "passed": True,
        "package": str(path),
        "packageId": manifest["packageId"],
        "version": manifest["version"],
        "owner": manifest["owner"],
        "packageSha256": verified["packageSha256"],
        "manifestSha256": verified["manifestSha256"],
        "artifactSetSha256": manifest["artifactSetSha256"],
        "signature": ({
            "keyId": verified["signature"]["keyId"],
            "signatureSha256": verified["signatureSha256"],
        } if verified["signature"] else None),
        "trust": trust,
        "files": manifest["files"],
    }


def verify(args: argparse.Namespace) -> int:
    path = resolved_path(args.package, "contract package")
    verified = verify_package(path, args.maximum_files, args.maximum_expanded_bytes)
    trust = None
    if args.require_signature or args.trust_policy:
        if not args.trust_policy or not args.expected_trust_policy_id \
                or not args.expected_trust_policy_sha256:
            raise ValueError(
                "trusted verification requires trust policy, expected policy id and SHA-256"
            )
        trust = verify_trust(
            verified, Path(args.trust_policy), args.expected_trust_policy_id,
            args.expected_trust_policy_sha256, verification_time(args.verification_time),
        )
    report = verification_report(path, verified, trust)
    if args.report:
        write_json(Path(args.report).resolve(), report)
    print(
        f"PDR_TEAM_CONTRACT_PACKAGE_VERIFY_PASS id={report['packageId']} "
        f"version={report['version']} sha256={report['packageSha256']}"
    )
    return 0


def lock_record(verified: dict[str, Any],
                trust: dict[str, Any] | None = None) -> dict[str, Any]:
    manifest = verified["manifest"]
    record = {
        "packageId": manifest["packageId"],
        "version": manifest["version"],
        "owner": manifest["owner"],
        "packageSha256": verified["packageSha256"],
        "manifestSha256": verified["manifestSha256"],
        "artifactSetSha256": manifest["artifactSetSha256"],
        "files": [
            {"role": item["role"], "sha256": item["sha256"]}
            for item in manifest["files"]
        ],
    }
    if verified["signature"] is not None:
        record["signature"] = {
            "keyId": verified["signature"]["keyId"],
            "signatureSha256": verified["signatureSha256"],
        }
        if trust is not None:
            record["signature"]["publicKeySha256"] = trust["publicKeySha256"]
    return record


def create_lock(args: argparse.Namespace) -> int:
    records: list[dict[str, Any]] = []
    identities: set[str] = set()
    if args.require_signature and not args.trust_policy:
        raise ValueError("signature-required lock creation requires a trust policy")
    if args.trust_policy and (not args.expected_trust_policy_id
                              or not args.expected_trust_policy_sha256):
        raise ValueError("trust policy lock creation requires expected policy id and SHA-256")
    at = verification_time(args.verification_time)
    trust_policy_evidence = None
    for supplied in args.package:
        verified = verify_package(
            resolved_path(supplied, "contract package"),
            args.maximum_files, args.maximum_expanded_bytes
        )
        trust = None
        if args.trust_policy:
            trust = verify_trust(
                verified, Path(args.trust_policy), args.expected_trust_policy_id,
                args.expected_trust_policy_sha256, at,
            )
            current_policy = {
                "policyId": trust["policyId"], "policySha256": trust["policySha256"]
            }
            if trust_policy_evidence not in (None, current_policy):
                raise ValueError("locked packages were not verified by one trust policy")
            trust_policy_evidence = current_policy
        elif args.require_signature:
            raise ValueError("signature-required lock creation requires trusted signatures")
        record = lock_record(verified, trust)
        if record["packageId"] in identities:
            raise ValueError(f"duplicate locked package id: {record['packageId']}")
        identities.add(record["packageId"])
        records.append(record)
    if not records:
        raise ValueError("at least one package is required")
    lock = {
        "schemaVersion": 1,
        "product": LOCK_PRODUCT,
        "packages": sorted(records, key=lambda item: item["packageId"]),
    }
    if trust_policy_evidence is not None:
        lock["trustPolicy"] = trust_policy_evidence
    output = resolved_path(args.output, "contract package lock output")
    if output.exists() and not args.force:
        raise FileExistsError(f"contract package lock already exists: {output}")
    write_json(output, lock)
    print(
        f"PDR_TEAM_CONTRACT_PACKAGE_LOCK_PASS packages={len(records)} "
        f"sha256={sha256_file(output)} output={output}"
    )
    return 0


def load_lock(path: Path) -> dict[str, Any]:
    path = resolved_path(path, "contract package lock")
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(f"contract package lock not found or is a link: {path}")
    try:
        lock = json.loads(path.read_bytes())
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("contract package lock is invalid JSON") from error
    if (not isinstance(lock, dict) or lock.get("schemaVersion") != 1
            or lock.get("product") != LOCK_PRODUCT
            or not isinstance(lock.get("packages"), list) or not lock["packages"]):
        raise ValueError("contract package lock identity is invalid")
    if set(lock) not in (
            {"schemaVersion", "product", "packages"},
            {"schemaVersion", "product", "packages", "trustPolicy"}):
        raise ValueError("contract package lock contains unsupported fields")
    trust_policy = lock.get("trustPolicy")
    if trust_policy is not None and (
            not isinstance(trust_policy, dict)
            or set(trust_policy) != {"policyId", "policySha256"}
            or not IDENTIFIER.fullmatch(str(trust_policy.get("policyId", "")))
            or not SHA256.fullmatch(str(trust_policy.get("policySha256", "")))):
        raise ValueError("contract package lock trust policy identity is malformed")
    seen: set[str] = set()
    for record in lock["packages"]:
        required_record_fields = {
            "packageId", "version", "owner", "packageSha256", "manifestSha256",
            "artifactSetSha256", "files",
        }
        if (not isinstance(record, dict)
                or set(record) not in (required_record_fields,
                                       required_record_fields | {"signature"})):
            raise ValueError("contract package lock contains malformed record")
        validate_identity(
            str(record.get("packageId", "")), str(record.get("version", "")),
            str(record.get("owner", "")),
        )
        if record["packageId"] in seen:
            raise ValueError(f"duplicate locked package id: {record['packageId']}")
        seen.add(record["packageId"])
        for field in ("packageSha256", "manifestSha256", "artifactSetSha256"):
            if not SHA256.fullmatch(str(record.get(field, ""))):
                raise ValueError(f"locked package {record['packageId']} has invalid {field}")
        if not isinstance(record.get("files"), list) or not record["files"]:
            raise ValueError(f"locked package {record['packageId']} contains no files")
        seen_files: set[tuple[str, str]] = set()
        for item in record["files"]:
            if (not isinstance(item, dict) or set(item) != {"role", "sha256"}
                    or item.get("role") not in ROLE_PRODUCTS
                    or not SHA256.fullmatch(str(item.get("sha256", "")))):
                raise ValueError(
                    f"locked package {record['packageId']} contains malformed file identity"
                )
            identity = (item["role"], item["sha256"])
            if identity in seen_files:
                raise ValueError(
                    f"locked package {record['packageId']} contains duplicate file identity"
                )
            seen_files.add(identity)
        signature = record.get("signature")
        if signature is not None:
            allowed_fields = {"keyId", "signatureSha256", "publicKeySha256"}
            if (not isinstance(signature, dict) or not set(signature).issubset(allowed_fields)
                    or not {"keyId", "signatureSha256"}.issubset(signature)
                    or not IDENTIFIER.fullmatch(str(signature.get("keyId", "")))
                    or not SHA256.fullmatch(str(signature.get("signatureSha256", "")))
                    or ("publicKeySha256" in signature and not SHA256.fullmatch(
                        str(signature["publicKeySha256"])))):
                raise ValueError(
                    f"locked package {record['packageId']} signature identity is malformed"
                )
        if trust_policy is not None and (
                signature is None or "publicKeySha256" not in signature):
            raise ValueError(
                f"trusted lock package {record['packageId']} lacks signer evidence"
            )
    if lock["packages"] != sorted(lock["packages"], key=lambda item: item["packageId"]):
        raise ValueError("contract package lock records are not sorted")
    return lock


def atomic_replace_directory(staging: Path, output: Path) -> None:
    backup = output.with_name(output.name + ".previous")
    if output.is_symlink() or backup.is_symlink():
        raise ValueError("contract package resolution output and backup must not be links")
    if backup.exists():
        shutil.rmtree(backup)
    if output.exists():
        output.replace(backup)
    try:
        staging.replace(output)
    except Exception:
        if backup.exists() and not output.exists():
            backup.replace(output)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def resolve(args: argparse.Namespace) -> int:
    lock_path = resolved_path(args.lock, "contract package lock")
    lock = load_lock(lock_path)
    locked_trust_policy = lock.get("trustPolicy")
    if args.require_signature and locked_trust_policy is None:
        raise ValueError("signature-required resolution requires a trusted package lock")
    if locked_trust_policy is not None:
        if (not args.trust_policy or not args.expected_trust_policy_id
                or not args.expected_trust_policy_sha256):
            raise ValueError(
                "trusted package lock resolution requires trust policy, expected id and SHA-256"
            )
        if locked_trust_policy != {
                "policyId": args.expected_trust_policy_id,
                "policySha256": str(args.expected_trust_policy_sha256).lower()}:
            raise ValueError("supplied trust policy identity does not match the package lock")
    elif args.trust_policy:
        raise ValueError("an untrusted package lock cannot add trust only during resolution")
    at = verification_time(args.verification_time)
    supplied: dict[str, tuple[Path, dict[str, Any]]] = {}
    for value in args.package:
        path = resolved_path(value, "contract package")
        verified = verify_package(path, args.maximum_files, args.maximum_expanded_bytes)
        package_id = verified["manifest"]["packageId"]
        if package_id in supplied:
            raise ValueError(f"duplicate supplied package id: {package_id}")
        supplied[package_id] = (path, verified)
    locked_ids = {item["packageId"] for item in lock["packages"]}
    if set(supplied) != locked_ids:
        raise ValueError(
            f"supplied package set does not match lock; missing={sorted(locked_ids - set(supplied))} "
            f"unexpected={sorted(set(supplied) - locked_ids)}"
        )
    output = resolved_path(args.output, "contract package resolution output")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=output.name + ".tmp-", dir=output.parent))
    resolved_packages: list[dict[str, Any]] = []
    try:
        for expected in lock["packages"]:
            path, verified = supplied[expected["packageId"]]
            trust = None
            if locked_trust_policy is not None:
                trust = verify_trust(
                    verified, Path(args.trust_policy), args.expected_trust_policy_id,
                    args.expected_trust_policy_sha256, at,
                )
            actual = lock_record(verified, trust)
            if actual != expected:
                raise ValueError(
                    f"supplied package does not match lock: {expected['packageId']} ({path})"
                )
            package_root = staging / expected["packageId"] / expected["version"]
            files: list[dict[str, Any]] = []
            for item in verified["manifest"]["files"]:
                relative = safe_archive_path(item["path"])
                destination = package_root.joinpath(*relative.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(verified["entries"][item["path"]])
                files.append({
                    "role": item["role"],
                    "path": str(destination.relative_to(staging).as_posix()),
                    "sha256": item["sha256"],
                })
            resolved_packages.append({
                "packageId": expected["packageId"],
                "version": expected["version"],
                "owner": expected["owner"],
                "packageSha256": expected["packageSha256"],
                "signature": expected.get("signature"),
                "files": files,
            })
        atomic_replace_directory(staging, output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    report = {
        "schemaVersion": 1,
        "product": RESOLUTION_PRODUCT,
        "operation": "resolve",
        "passed": True,
        "lock": str(lock_path),
        "lockSha256": sha256_file(lock_path),
        "output": str(output),
        "trustPolicy": locked_trust_policy,
        "packages": resolved_packages,
    }
    report_path = Path(args.report).resolve() if args.report else output / "resolution.json"
    write_json(report_path, report)
    print(
        f"PDR_TEAM_CONTRACT_PACKAGE_RESOLVE_PASS packages={len(resolved_packages)} "
        f"lockSha256={report['lockSha256']} output={output}"
    )
    return 0


def write_json(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_bytes(json_bytes(document))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    pack_parser = commands.add_parser("pack", help="create a deterministic contract package")
    pack_parser.add_argument("--package-id", required=True)
    pack_parser.add_argument("--version", required=True)
    pack_parser.add_argument("--owner", required=True)
    pack_parser.add_argument("--input", action="append", default=[], metavar="ROLE=PATH")
    pack_parser.add_argument("--output", required=True)
    pack_parser.add_argument("--source-date-epoch", type=int, default=0)
    pack_parser.add_argument("--ed25519-private-key-environment")
    pack_parser.add_argument("--private-key-passphrase-environment")
    pack_parser.add_argument("--signing-key-id")
    pack_parser.add_argument("--maximum-files", type=int, default=MAX_FILES_DEFAULT)
    pack_parser.add_argument(
        "--maximum-expanded-bytes", type=int, default=MAX_EXPANDED_BYTES_DEFAULT
    )
    pack_parser.add_argument("--force", action="store_true")
    pack_parser.set_defaults(handler=pack)

    verify_parser = commands.add_parser("verify", help="verify a contract package")
    verify_parser.add_argument("package")
    verify_parser.add_argument("--maximum-files", type=int, default=MAX_FILES_DEFAULT)
    verify_parser.add_argument(
        "--maximum-expanded-bytes", type=int, default=MAX_EXPANDED_BYTES_DEFAULT
    )
    verify_parser.add_argument("--report")
    verify_parser.add_argument("--require-signature", action="store_true")
    verify_parser.add_argument("--trust-policy")
    verify_parser.add_argument("--expected-trust-policy-id")
    verify_parser.add_argument("--expected-trust-policy-sha256")
    verify_parser.add_argument("--verification-time")
    verify_parser.set_defaults(handler=verify)

    lock_parser = commands.add_parser("lock", help="pin exact package identities and digests")
    lock_parser.add_argument("--package", action="append", default=[])
    lock_parser.add_argument("--output", required=True)
    lock_parser.add_argument("--maximum-files", type=int, default=MAX_FILES_DEFAULT)
    lock_parser.add_argument(
        "--maximum-expanded-bytes", type=int, default=MAX_EXPANDED_BYTES_DEFAULT
    )
    lock_parser.add_argument("--force", action="store_true")
    lock_parser.add_argument("--require-signature", action="store_true")
    lock_parser.add_argument("--trust-policy")
    lock_parser.add_argument("--expected-trust-policy-id")
    lock_parser.add_argument("--expected-trust-policy-sha256")
    lock_parser.add_argument("--verification-time")
    lock_parser.set_defaults(handler=create_lock)

    resolve_parser = commands.add_parser(
        "resolve", help="verify locked packages and expose content-addressed contract paths"
    )
    resolve_parser.add_argument("--lock", required=True)
    resolve_parser.add_argument("--package", action="append", default=[])
    resolve_parser.add_argument("--output", required=True)
    resolve_parser.add_argument("--report")
    resolve_parser.add_argument("--require-signature", action="store_true")
    resolve_parser.add_argument("--trust-policy")
    resolve_parser.add_argument("--expected-trust-policy-id")
    resolve_parser.add_argument("--expected-trust-policy-sha256")
    resolve_parser.add_argument("--verification-time")
    resolve_parser.add_argument("--maximum-files", type=int, default=MAX_FILES_DEFAULT)
    resolve_parser.add_argument(
        "--maximum-expanded-bytes", type=int, default=MAX_EXPANDED_BYTES_DEFAULT
    )
    resolve_parser.set_defaults(handler=resolve)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        return args.handler(args)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"PDR_TEAM_CONTRACT_PACKAGE_ERROR: {error}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
