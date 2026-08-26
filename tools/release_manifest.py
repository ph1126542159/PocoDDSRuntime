#!/usr/bin/env python3
"""Generate and verify release hashes plus an SPDX 2.3 SBOM."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any


EXCLUDED_PARTS = {"logs", "data", "codeCache", "disabled-bundles"}


def signing_key(environment: str) -> bytes:
    encoded = os.environ.get(environment)
    if not encoded:
        raise ValueError(f"signing key environment is unset: {environment}")
    try:
        key = base64.b64decode(encoded, validate=True)
    except Exception as error:
        raise ValueError("signing key must be valid Base64") from error
    if len(key) < 32:
        raise ValueError("signing key must decode to at least 32 bytes")
    return key


def create_signature(manifest_path: Path, output: Path, environment: str, key_id: str) -> None:
    if not key_id or any(character.isspace() for character in key_id):
        raise ValueError("signing key id must be non-empty and contain no whitespace")
    content = manifest_path.read_bytes()
    key = signing_key(environment)
    signature = {
        "schemaVersion": 1,
        "product": "PocoDDSRuntime",
        "algorithm": "HMAC-SHA256",
        "keyId": key_id,
        "manifestSha256": hashlib.sha256(content).hexdigest(),
        "signature": base64.b64encode(hmac.new(key, content, hashlib.sha256).digest()).decode("ascii"),
    }
    output.write_text(json.dumps(signature, indent=2), encoding="utf-8", newline="\n")


def create_ed25519_signature(
        manifest_path: Path, output: Path, private_key_path_environment: str,
        passphrase_environment: str | None, key_id: str) -> None:
    if not key_id or any(character.isspace() for character in key_id):
        raise ValueError("signing key id must be non-empty and contain no whitespace")
    key_path = os.environ.get(private_key_path_environment)
    if not key_path:
        raise ValueError(
            f"private key path environment is unset: {private_key_path_environment}"
        )
    passphrase = None
    if passphrase_environment:
        value = os.environ.get(passphrase_environment)
        if value is None:
            raise ValueError(f"private key passphrase environment is unset: {passphrase_environment}")
        passphrase = value.encode("utf-8")
    try:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError as error:
        raise ValueError(
            "Ed25519 signing requires the release-host cryptography package"
        ) from error
    key = load_pem_private_key(Path(key_path).read_bytes(), password=passphrase)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("release private key is not Ed25519")
    content = manifest_path.read_bytes()
    signature = {
        "schemaVersion": 1,
        "product": "PocoDDSRuntime",
        "algorithm": "Ed25519",
        "keyId": key_id,
        "manifestSha256": hashlib.sha256(content).hexdigest(),
        "signature": base64.b64encode(key.sign(content)).decode("ascii"),
    }
    output.write_text(json.dumps(signature, indent=2), encoding="utf-8", newline="\n")


def verify_signature(
        manifest_path: Path, signature_path: Path,
        environment: str, expected_key_id: str) -> None:
    document = json.loads(signature_path.read_text(encoding="utf-8"))
    if (document.get("schemaVersion") != 1 or
            document.get("product") != "PocoDDSRuntime" or
            document.get("algorithm") != "HMAC-SHA256"):
        raise ValueError("unsupported release signature")
    if document.get("keyId") != expected_key_id:
        raise ValueError("release signature key id is not trusted")
    content = manifest_path.read_bytes()
    if not hmac.compare_digest(
            str(document.get("manifestSha256", "")), hashlib.sha256(content).hexdigest()):
        raise ValueError("release signature manifest digest mismatch")
    expected = base64.b64encode(
        hmac.new(signing_key(environment), content, hashlib.sha256).digest()
    ).decode("ascii")
    if not hmac.compare_digest(str(document.get("signature", "")), expected):
        raise ValueError("release signature verification failed")


def verify_ed25519_signature(
        manifest_path: Path, signature_path: Path, public_key: Path,
        expected_key_id: str, expected_public_key_sha256: str,
        executable: Path | None, untrusted_artifact_root: Path) -> None:
    actual_public_key_sha256 = digest(public_key)
    if not hmac.compare_digest(actual_public_key_sha256, expected_public_key_sha256.lower()):
        raise ValueError("release public key SHA-256 is not trusted")
    verifier = executable or Path(__file__).resolve().with_name(
        "pdr-signature-check.exe" if os.name == "nt" else "pdr-signature-check"
    )
    verifier = verifier.resolve()
    try:
        verifier.relative_to(untrusted_artifact_root)
    except ValueError:
        pass
    else:
        raise ValueError("Ed25519 verifier must not come from the unverified artifact directory")
    if not verifier.is_file():
        raise ValueError(f"Ed25519 signature verifier is unavailable: {verifier}")
    result = subprocess.run(
        [str(verifier), str(manifest_path), str(signature_path),
         str(public_key), expected_key_id],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ValueError(detail or "Ed25519 signature verification failed")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def artifacts(root: Path) -> list[dict[str, Any]]:
    result = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        result.append({"path": relative.as_posix(), "size": path.stat().st_size, "sha256": digest(path)})
    return result


def artifact_set_digest(entries: list[dict[str, Any]]) -> str:
    """Bind the ordered artifact inventory independently of output formatting."""
    payload = json.dumps(entries, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def git_value(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments], cwd=root, capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def generate(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    artifact_root = args.artifacts.resolve()
    output = args.output.resolve()
    entries = artifacts(artifact_root)
    if not entries:
        print("RELEASE_ERROR: artifact directory contains no files", file=sys.stderr)
        return 1
    commit = git_value(root, "rev-parse", "HEAD")
    dirty = bool(git_value(root, "status", "--porcelain"))
    if args.require_clean and dirty:
        print("RELEASE_ERROR: worktree is dirty", file=sys.stderr)
        return 1
    generated_at = datetime.now(timezone.utc).isoformat()
    manifest = {
        "schemaVersion": 1,
        "product": "PocoDDSRuntime",
        "version": args.version,
        "gitCommit": commit,
        "dirty": dirty,
        "cleanRequired": args.require_clean,
        "generatedAt": generated_at,
        "artifactRoot": str(artifact_root),
        "files": entries,
    }
    dependencies = json.loads((root / "release/dependencies.json").read_text(encoding="utf-8"))["packages"]
    matrix = json.loads((root / "docs/compatibility/releases.json").read_text(encoding="utf-8"))
    compatibility = next(
        (release for release in matrix["releases"] if release["runtime"] == args.version), None
    )
    if compatibility is None:
        print(f"RELEASE_ERROR: version {args.version} is missing from compatibility matrix", file=sys.stderr)
        return 1
    manifest["compatibility"] = compatibility
    namespace_hash = hashlib.sha256(f"{commit}:{args.version}".encode()).hexdigest()[:24]
    packages = [
        {
            "SPDXID": "SPDXRef-Package-PocoDDSRuntime",
            "name": "PocoDDSRuntime",
            "versionInfo": args.version,
            "downloadLocation": "NOASSERTION",
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": "NOASSERTION",
            "copyrightText": "NOASSERTION",
        }
    ]
    relationships = []
    for index, dependency in enumerate(dependencies, 1):
        spdx_id = f"SPDXRef-Dependency-{index}"
        packages.append(
            {
                "SPDXID": spdx_id,
                "name": dependency["name"],
                "versionInfo": dependency["version"],
                "downloadLocation": dependency["download"],
                "licenseConcluded": dependency["license"],
                "licenseDeclared": dependency["license"],
                "copyrightText": "NOASSERTION",
                "primaryPackagePurpose": "LIBRARY",
            }
        )
        relationships.append(
            {"spdxElementId": "SPDXRef-Package-PocoDDSRuntime", "relationshipType": "DEPENDS_ON", "relatedSpdxElement": spdx_id}
        )
    sbom = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"PocoDDSRuntime-{args.version}",
        "documentNamespace": f"https://pocodds.local/spdx/{namespace_hash}",
        "creationInfo": {"created": generated_at, "creators": ["Tool: PocoDDSRuntime-release_manifest"]},
        "packages": packages,
        "relationships": relationships,
    }
    output.mkdir(parents=True, exist_ok=True)
    signature_output = output / "SHA256SUMS.sig.json"
    signature_output.unlink(missing_ok=True)
    sbom_path = output / "pocoddsruntime.spdx.json"
    sbom_path.write_text(json.dumps(sbom, indent=2), encoding="utf-8", newline="\n")
    sbom_sha256 = digest(sbom_path)
    manifest["sbom"] = {
        "path": sbom_path.name,
        "sha256": sbom_sha256,
        "spdxVersion": "SPDX-2.3",
        "documentNamespace": sbom["documentNamespace"],
    }
    manifest["provenance"] = {
        "builderId": getattr(args, "builder_id", None) or
                     "pocoddsruntime.release_manifest",
        "buildProfile": getattr(args, "build_profile", None) or "unknown",
        "artifactSetSha256": artifact_set_digest(entries),
        "source": {"gitCommit": commit, "dirty": dirty},
    }
    manifest_path = output / "SHA256SUMS.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8", newline="\n")
    signing_environment = getattr(args, "signing_key_environment", None)
    ed25519_key_environment = getattr(args, "ed25519_private_key_environment", None)
    passphrase_environment = getattr(args, "private_key_passphrase_environment", None)
    signing_key_id = getattr(args, "signing_key_id", None)
    if signing_environment and ed25519_key_environment:
        print("RELEASE_ERROR: choose either HMAC or Ed25519 signing", file=sys.stderr)
        manifest_path.unlink(missing_ok=True)
        sbom_path.unlink(missing_ok=True)
        return 1
    if bool(signing_environment or ed25519_key_environment) != bool(signing_key_id):
        print("RELEASE_ERROR: signing key source and key id must be provided together", file=sys.stderr)
        manifest_path.unlink(missing_ok=True)
        sbom_path.unlink(missing_ok=True)
        return 1
    if passphrase_environment and not ed25519_key_environment:
        print("RELEASE_ERROR: private key passphrase requires Ed25519 signing", file=sys.stderr)
        manifest_path.unlink(missing_ok=True)
        sbom_path.unlink(missing_ok=True)
        return 1
    if signing_environment or ed25519_key_environment:
        try:
            if ed25519_key_environment:
                create_ed25519_signature(
                    manifest_path, signature_output, ed25519_key_environment,
                    passphrase_environment, signing_key_id,
                )
            else:
                create_signature(
                    manifest_path, signature_output,
                    signing_environment, signing_key_id,
                )
        except (OSError, ValueError) as error:
            print(f"RELEASE_ERROR: cannot sign manifest: {error}", file=sys.stderr)
            manifest_path.unlink(missing_ok=True)
            sbom_path.unlink(missing_ok=True)
            return 1
    print(f"RELEASE_MANIFEST_PASS files={len(entries)} output={output}")
    return 0


def verify(args: argparse.Namespace) -> int:
    manifest_path = args.manifest.resolve()
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"RELEASE_ERROR: cannot read manifest: {error}", file=sys.stderr)
        return 1
    if (document.get("schemaVersion") != 1 or
            document.get("product") != "PocoDDSRuntime" or
            not isinstance(document.get("files"), list)):
        print("RELEASE_ERROR: unsupported or malformed release manifest", file=sys.stderr)
        return 1
    artifact_root = (
        args.artifacts.resolve() if args.artifacts else Path(document.get("artifactRoot", "")).resolve()
    )
    signature_path = getattr(args, "signature", None)
    require_signature = getattr(args, "require_signature", False)
    if require_signature and not signature_path:
        print("RELEASE_ERROR: detached release signature is required", file=sys.stderr)
        return 1
    if signature_path:
        environment = getattr(args, "trusted_key_environment", None)
        key_id = getattr(args, "expected_key_id", None)
        if not key_id:
            print("RELEASE_ERROR: signature verification requires expected key id", file=sys.stderr)
            return 1
        try:
            signature_document = json.loads(signature_path.resolve().read_text(encoding="utf-8"))
            algorithm = signature_document.get("algorithm")
            if algorithm == "HMAC-SHA256":
                if not environment:
                    raise ValueError("HMAC verification requires trusted key environment")
                verify_signature(manifest_path, signature_path.resolve(), environment, key_id)
            elif algorithm == "Ed25519":
                public_key = getattr(args, "public_key", None)
                if not public_key:
                    raise ValueError("Ed25519 verification requires a public key")
                expected_public_key_sha256 = getattr(args, "expected_public_key_sha256", None)
                if not expected_public_key_sha256:
                    raise ValueError("Ed25519 verification requires expected public key SHA-256")
                verify_ed25519_signature(
                    manifest_path, signature_path.resolve(), public_key.resolve(), key_id,
                    expected_public_key_sha256,
                    getattr(args, "signature_check_executable", None),
                    artifact_root,
                )
            else:
                raise ValueError("unsupported release signature")
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            print(f"RELEASE_ERROR: {error}", file=sys.stderr)
            return 1
    errors: list[str] = []
    sbom_evidence = document.get("sbom")
    provenance = document.get("provenance")
    if not isinstance(sbom_evidence, dict):
        errors.append("release manifest does not bind an SPDX SBOM")
    else:
        sbom_name = sbom_evidence.get("path")
        if (not isinstance(sbom_name, str) or not sbom_name or
                PurePosixPath(sbom_name).name != sbom_name):
            errors.append("release manifest SBOM path is unsafe")
        else:
            explicit_sbom = getattr(args, "sbom", None)
            sbom_path = (explicit_sbom.resolve() if explicit_sbom else
                         (manifest_path.parent / sbom_name).resolve())
            try:
                sbom_document = json.loads(sbom_path.read_text(encoding="utf-8"))
                if digest(sbom_path) != sbom_evidence.get("sha256"):
                    errors.append("release SBOM SHA-256 does not match the signed manifest")
                if (sbom_document.get("spdxVersion") != "SPDX-2.3" or
                        sbom_document.get("documentNamespace") !=
                        sbom_evidence.get("documentNamespace") or
                        sbom_evidence.get("spdxVersion") != "SPDX-2.3"):
                    errors.append("release SBOM identity does not match the signed manifest")
                packages = sbom_document.get("packages")
                if (not isinstance(packages, list) or not any(
                        isinstance(package, dict) and
                        package.get("name") == "PocoDDSRuntime" and
                        package.get("versionInfo") == document.get("version")
                        for package in packages)):
                    errors.append("release SBOM does not identify the Runtime version")
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                errors.append(f"cannot read release SBOM: {error}")
    if not isinstance(provenance, dict):
        errors.append("release manifest does not contain build provenance")
    else:
        source = provenance.get("source")
        if (not isinstance(provenance.get("builderId"), str) or
                not provenance.get("builderId") or
                not isinstance(provenance.get("buildProfile"), str) or
                not provenance.get("buildProfile") or
                provenance.get("artifactSetSha256") != artifact_set_digest(document["files"]) or
                not isinstance(source, dict) or
                source.get("gitCommit") != document.get("gitCommit") or
                source.get("dirty") is not document.get("dirty")):
            errors.append("release build provenance does not match the artifact manifest")
    expected_paths: set[str] = set()
    for entry in document["files"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            errors.append("malformed artifact entry")
            continue
        relative_text = entry["path"]
        relative = PurePosixPath(relative_text)
        if (not relative.parts or relative.is_absolute() or "\\" in relative_text or
                any(part in {"", ".", ".."} for part in relative.parts)):
            errors.append(f"unsafe artifact path: {relative_text}")
            continue
        path = (artifact_root / Path(*relative.parts)).resolve()
        try:
            path.relative_to(artifact_root)
        except ValueError:
            errors.append(f"artifact escapes root: {relative_text}")
            continue
        if relative_text in expected_paths:
            errors.append(f"duplicate artifact entry: {relative_text}")
            continue
        expected_paths.add(relative_text)
        if not path.is_file():
            errors.append(f"missing artifact: {relative_text}")
        elif (not isinstance(entry.get("size"), int) or
              not isinstance(entry.get("sha256"), str) or
              path.stat().st_size != entry["size"] or digest(path) != entry["sha256"]):
            errors.append(f"artifact changed: {relative_text}")
    actual_paths = {entry["path"] for entry in artifacts(artifact_root)} if artifact_root.is_dir() else set()
    for unexpected in sorted(actual_paths - expected_paths):
        errors.append(f"unexpected artifact: {unexpected}")
    if errors:
        for error in errors:
            print(f"RELEASE_ERROR: {error}", file=sys.stderr)
        return 1
    print(f"RELEASE_VERIFY_PASS files={len(document['files'])}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("generate")
    create.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    create.add_argument("--artifacts", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--version", default="0.1.0")
    create.add_argument("--require-clean", action="store_true")
    create.add_argument("--builder-id", default="pocoddsruntime.release_manifest")
    create.add_argument("--build-profile", default="unknown")
    create.add_argument("--signing-key-environment")
    create.add_argument("--ed25519-private-key-environment")
    create.add_argument("--private-key-passphrase-environment")
    create.add_argument("--signing-key-id")
    create.set_defaults(handler=generate)
    check = commands.add_parser("verify")
    check.add_argument("--manifest", type=Path, required=True)
    check.add_argument("--artifacts", type=Path)
    check.add_argument("--sbom", type=Path)
    check.add_argument("--signature", type=Path)
    check.add_argument("--trusted-key-environment")
    check.add_argument("--expected-key-id")
    check.add_argument("--public-key", type=Path)
    check.add_argument("--expected-public-key-sha256")
    check.add_argument("--signature-check-executable", type=Path)
    check.add_argument("--require-signature", action="store_true")
    check.set_defaults(handler=verify)
    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
