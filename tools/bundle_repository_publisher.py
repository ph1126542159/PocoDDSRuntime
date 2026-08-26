#!/usr/bin/env python3
"""Create a detached Ed25519 publisher attestation for a Bundle repository."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


IDENTITY = re.compile(r"^[^\s]+$")
KEY_ID = re.compile(r"^[A-Za-z0-9._-]+$")
FINGERPRINT = re.compile(r"^BUNDLE_REPOSITORY_FINGERPRINT sha256=([0-9a-f]{64})$", re.MULTILINE)
MAX_ROLLOUT_SEQUENCE = (1 << 63) - 1


def positive_rollout_sequence(value: str) -> int:
    try:
        parsed = int(value, 10)
    except ValueError as error:
        raise argparse.ArgumentTypeError("rollout sequence must be a positive integer") from error
    if parsed < 1 or parsed > MAX_ROLLOUT_SEQUENCE:
        raise argparse.ArgumentTypeError("rollout sequence must be in 1..2^63-1")
    return parsed


def atomic_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def file_sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def artifact_set_sha256(entries: list[dict[str, Any]]) -> str:
    payload = json.dumps(entries, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def release_provenance(args: argparse.Namespace, repository: Path) -> dict[str, str]:
    manifest_path = args.release_manifest.resolve()
    sbom_path = args.release_sbom.resolve()
    artifact_root = args.release_artifacts_root.resolve()
    for material, description in ((manifest_path, "release manifest"),
                                  (sbom_path, "release SBOM")):
        if not material.is_file():
            raise ValueError(f"{description} is unavailable: {material}")
        if material == repository or repository in material.parents:
            raise ValueError(f"{description} must not come from the Bundle repository")
    if not artifact_root.is_dir():
        raise ValueError(f"release artifact root is unavailable: {artifact_root}")
    try:
        repository.relative_to(artifact_root)
    except ValueError as error:
        raise ValueError("Bundle repository must be inside the verified release artifact root") from error

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"release provenance JSON is malformed: {error}") from error
    entries = manifest.get("files")
    provenance = manifest.get("provenance")
    sbom_evidence = manifest.get("sbom")
    version = manifest.get("version")
    git_commit = manifest.get("gitCommit")
    generated_at = manifest.get("generatedAt")
    if (manifest.get("schemaVersion") != 1 or
            manifest.get("product") != "PocoDDSRuntime" or
            manifest.get("dirty") is not False or not isinstance(entries, list) or
            not isinstance(provenance, dict) or not isinstance(sbom_evidence, dict)):
        raise ValueError("release manifest is unsupported, dirty or lacks provenance/SBOM binding")
    if (not isinstance(version, str) or IDENTITY.fullmatch(version) is None or
            not isinstance(git_commit, str) or
            re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", git_commit) is None):
        raise ValueError("release version or Git commit identity is malformed")
    try:
        generated_time = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("release manifest generatedAt is not valid ISO-8601") from error
    if generated_time.tzinfo is None:
        raise ValueError("release manifest generatedAt must include a timezone")
    if not entries:
        raise ValueError("release manifest artifact inventory is empty")
    if (not isinstance(provenance.get("builderId"), str) or
            IDENTITY.fullmatch(provenance["builderId"]) is None or
            not isinstance(provenance.get("buildProfile"), str) or
            IDENTITY.fullmatch(provenance["buildProfile"]) is None or
            provenance.get("artifactSetSha256") != artifact_set_sha256(entries) or
            provenance.get("source") != {"gitCommit": git_commit, "dirty": False}):
        raise ValueError("release build provenance does not match the artifact inventory")
    actual_sbom_sha256 = file_sha256(sbom_path)
    if (sbom_evidence.get("sha256") != actual_sbom_sha256 or
            sbom_evidence.get("spdxVersion") != "SPDX-2.3" or
            sbom.get("spdxVersion") != "SPDX-2.3" or
            sbom.get("documentNamespace") != sbom_evidence.get("documentNamespace")):
        raise ValueError("release SBOM does not match the release manifest")
    packages = sbom.get("packages")
    if (not isinstance(packages, list) or not any(
            isinstance(package, dict) and package.get("name") == "PocoDDSRuntime" and
            package.get("versionInfo") == version for package in packages)):
        raise ValueError("release SBOM does not identify the Runtime version")

    inventory: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if (not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or
                entry["path"] in inventory):
            raise ValueError("release manifest artifact inventory is malformed")
        inventory[entry["path"]] = entry
    repository_files = [path for path in sorted(repository.rglob("*")) if path.is_file()]
    if not repository_files:
        raise ValueError("Bundle repository contains no files")
    for path in repository_files:
        relative = path.relative_to(artifact_root).as_posix()
        entry = inventory.get(relative)
        if (entry is None or entry.get("size") != path.stat().st_size or
                entry.get("sha256") != file_sha256(path)):
            raise ValueError(f"Bundle repository file is not covered by release manifest: {relative}")
    return {
        "releaseManifestSha256": file_sha256(manifest_path),
        "sbomSha256": actual_sbom_sha256,
        "version": version,
        "gitCommit": git_commit.lower(),
        "builderId": provenance["builderId"],
        "buildProfile": provenance["buildProfile"],
        "artifactSetSha256": provenance["artifactSetSha256"],
    }


def repository_digest(checker: Path, repository: Path) -> str:
    result = subprocess.run(
        [str(checker), "fingerprint", str(repository)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise ValueError((result.stderr or result.stdout).strip() or "repository fingerprint failed")
    match = FINGERPRINT.search(result.stdout)
    if match is None:
        raise ValueError("repository fingerprint output is malformed")
    return match.group(1)


def sign_command(args: argparse.Namespace) -> int:
    try:
        repository = args.repository.resolve()
        checker = args.fingerprint_executable.resolve()
        output = args.output_directory.resolve()
        if not repository.is_dir():
            raise ValueError(f"Bundle repository is not a directory: {repository}")
        if not checker.is_file():
            raise ValueError(f"Bundle repository fingerprint executable is unavailable: {checker}")
        if repository == output or repository in output.parents or output in repository.parents:
            raise ValueError("authorization evidence directory must not overlap the Bundle repository")
        if not IDENTITY.fullmatch(args.repository_id) or not IDENTITY.fullmatch(args.publisher_id):
            raise ValueError("repository and publisher identities must be non-empty and contain no whitespace")
        if not KEY_ID.fullmatch(args.key_id):
            raise ValueError("key id must use only letters, digits, dot, underscore or hyphen")
        key_path_value = os.environ.get(args.private_key_path_environment)
        if not key_path_value:
            raise ValueError("Bundle repository private key path environment is unset")
        passphrase = None
        if args.private_key_passphrase_environment:
            value = os.environ.get(args.private_key_passphrase_environment)
            if value is None:
                raise ValueError("Bundle repository private key passphrase environment is unset")
            passphrase = value.encode("utf-8")
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
        except ImportError as error:
            raise ValueError("Ed25519 signing requires the release-host cryptography package") from error
        key = load_pem_private_key(Path(key_path_value).read_bytes(), password=passphrase)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("Bundle repository private key is not Ed25519")

        provenance = release_provenance(args, repository)
        digest = repository_digest(checker, repository)
        attestation = {
            "schemaVersion": 2,
            "product": "PocoDDSBundleRepository",
            "publisherId": args.publisher_id,
            "repositoryId": args.repository_id,
            "rolloutSequence": args.rollout_sequence,
            "candidateDigest": digest,
            "provenance": provenance,
            "issuedAt": datetime.now(timezone.utc).isoformat(),
        }
        attestation_path = output / f"{digest}.attestation.json"
        signature_path = output / f"{digest}.sig.json"
        release_manifest_evidence = output / f"{digest}.release-manifest.json"
        sbom_evidence = output / f"{digest}.spdx.json"
        atomic_bytes(release_manifest_evidence, args.release_manifest.resolve().read_bytes())
        atomic_bytes(sbom_evidence, args.release_sbom.resolve().read_bytes())
        atomic_json(attestation_path, attestation)
        payload = attestation_path.read_bytes()
        signature = {
            "schemaVersion": 1,
            "product": "PocoDDSBundleRepository",
            "algorithm": "Ed25519",
            "keyId": args.key_id,
            "manifestSha256": hashlib.sha256(payload).hexdigest(),
            "signature": base64.b64encode(key.sign(payload)).decode("ascii"),
        }
        atomic_json(signature_path, signature)
        print(json.dumps({
            "result": "BUNDLE_REPOSITORY_SIGN_PASS",
            "repositoryId": args.repository_id,
            "publisherId": args.publisher_id,
            "keyId": args.key_id,
            "rolloutSequence": args.rollout_sequence,
            "candidateDigest": digest,
            "provenance": provenance,
            "attestation": str(attestation_path),
            "signature": str(signature_path),
            "releaseManifest": str(release_manifest_evidence),
            "sbom": str(sbom_evidence),
        }, ensure_ascii=False))
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(f"BUNDLE_REPOSITORY_SIGN_ERROR: {error}", file=sys.stderr)
        return 1


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    sign = commands.add_parser("sign", help="sign the deterministic repository fingerprint")
    sign.add_argument("--repository", type=Path, required=True)
    sign.add_argument("--fingerprint-executable", type=Path, required=True)
    sign.add_argument("--repository-id", required=True)
    sign.add_argument("--rollout-sequence", type=positive_rollout_sequence, required=True)
    sign.add_argument("--publisher-id", required=True)
    sign.add_argument("--key-id", required=True)
    sign.add_argument("--private-key-path-environment", required=True)
    sign.add_argument("--private-key-passphrase-environment")
    sign.add_argument("--output-directory", type=Path, required=True)
    sign.add_argument("--release-manifest", type=Path, required=True)
    sign.add_argument("--release-sbom", type=Path, required=True)
    sign.add_argument("--release-artifacts-root", type=Path, required=True)
    sign.set_defaults(handler=sign_command)
    return result


if __name__ == "__main__":
    arguments = parser().parse_args()
    raise SystemExit(arguments.handler(arguments))
