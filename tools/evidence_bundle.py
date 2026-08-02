#!/usr/bin/env python3
"""Create and offline-verify signed PocoDDSRuntime release evidence bundles."""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


PRODUCT = "PocoDDSRuntimeEvidenceBundle"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(path.parts) and not path.is_absolute() and "\\" not in name and all(
        part not in {"", ".", ".."} for part in path.parts)


def add_file(files: dict[str, tuple[Path, str]], bundle_path: str, source: Path, role: str) -> None:
    if not safe_member(bundle_path) or bundle_path in files:
        raise ValueError(f"unsafe or duplicate evidence bundle path: {bundle_path}")
    resolved = source.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"evidence source file not found: {resolved}")
    files[bundle_path] = (resolved, role)


def collect(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, tuple[Path, str]]]:
    qualification_path = args.qualification.resolve()
    qualification = json.loads(qualification_path.read_text(encoding="utf-8"))
    if (qualification.get("operation") != "release-qualification" or
            qualification.get("passed") is not True):
        raise ValueError("evidence bundle requires passing release qualification")
    files: dict[str, tuple[Path, str]] = {}
    add_file(files, "metadata/release-qualification.json", qualification_path, "qualification")
    tests = qualification.get("tests", {})
    add_file(files, "tests/ctest.log", Path(str(tests.get("path", ""))), "ctest")
    for item in qualification.get("evidence", []):
        name = str(item.get("name", ""))
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
            raise ValueError("qualification contains unsafe evidence name")
        add_file(files, f"local/{name}.json", Path(str(item.get("path", ""))),
                 f"local:{name}")
    artifact = qualification.get("artifactManifest")
    if isinstance(artifact, dict) and artifact.get("path"):
        add_file(files, "artifacts/SHA256SUMS.json", Path(str(artifact["path"])),
                 "artifact-manifest")
        if args.include_artifacts:
            root = Path(str(artifact.get("artifactRoot", ""))).resolve()
            manifest = json.loads(Path(str(artifact["path"])).read_text(encoding="utf-8"))
            for entry in manifest.get("files", []):
                relative = str(entry.get("path", ""))
                if not safe_member(relative):
                    raise ValueError(f"unsafe artifact manifest path: {relative}")
                add_file(files, f"artifacts/payload/{relative}", root / Path(*PurePosixPath(relative).parts),
                         "artifact")
    for item in qualification.get("externalAcceptance", []):
        if not item.get("verified"):
            continue
        name = str(item.get("name", ""))
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name):
            raise ValueError("qualification contains unsafe external acceptance name")
        report = Path(str(item.get("path", ""))).resolve()
        add_file(files, f"external/{name}/report.json", report, f"external:{name}")
        add_file(files, f"external/{name}/report.sig.json",
                 Path(str(item.get("signaturePath", ""))), f"external-signature:{name}")
        policy = Path(str(item.get("trustPolicyPath", ""))).resolve()
        add_file(files, f"external/{name}/trust-policy.json", policy, f"external-policy:{name}")
        policy_document = json.loads(policy.read_text(encoding="utf-8"))
        for approver in policy_document.get("allowedApprovers", []):
            public_path = (policy.parent / str(approver.get("publicKeyPath", ""))).resolve()
            add_file(files, f"external/{name}/{public_path.name}", public_path,
                     f"external-public-key:{name}")
        report_document = json.loads(report.read_text(encoding="utf-8"))
        for check in report_document.get("checks", []):
            for attachment in check.get("evidence", []):
                source = Path(str(attachment.get("path", "")))
                if not source.is_absolute():
                    source = report.parent / source
                relative = PurePosixPath(str(attachment.get("path", "")))
                if not safe_member(relative.as_posix()):
                    raise ValueError("external acceptance contains unsafe attachment path")
                add_file(files, f"external/{name}/{relative.as_posix()}", source,
                         f"external-attachment:{name}")
    entries = [{"path": path, "role": role, "size": source.stat().st_size,
                "sha256": digest(source)} for path, (source, role) in sorted(files.items())]
    manifest = {
        "schemaVersion": 1, "product": PRODUCT,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "qualificationVerdict": qualification.get("verdict"),
        "releaseApproved": qualification.get("releaseApproved"),
        "version": qualification.get("version"),
        "gitCommit": qualification.get("git", {}).get("commit"),
        "worktreeSha256": qualification.get("git", {}).get("worktreeSha256"),
        "includesArtifacts": args.include_artifacts, "files": entries,
    }
    return manifest, files


def sign_file(path: Path, signature_output: Path, args: argparse.Namespace) -> None:
    if not args.key_id or any(character.isspace() for character in args.key_id):
        raise ValueError("evidence bundle key id must be non-empty and contain no whitespace")
    key_value = os.environ.get(args.private_key_path_environment)
    if not key_value:
        raise ValueError("evidence bundle private key path environment is unset")
    password = None
    if args.private_key_passphrase_environment:
        value = os.environ.get(args.private_key_passphrase_environment)
        if value is None:
            raise ValueError("evidence bundle private key passphrase environment is unset")
        password = value.encode("utf-8")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
    except ImportError as error:
        raise ValueError("Ed25519 signing requires the release-host cryptography package") from error
    key = load_pem_private_key(Path(key_value).read_bytes(), password=password)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("evidence bundle private key is not Ed25519")
    content = path.read_bytes()
    envelope = {"schemaVersion": 1, "product": PRODUCT, "algorithm": "Ed25519",
                "keyId": args.key_id, "manifestSha256": hashlib.sha256(content).hexdigest(),
                "signature": base64.b64encode(key.sign(content)).decode("ascii")}
    signature_output.parent.mkdir(parents=True, exist_ok=True)
    signature_output.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8", newline="\n")


def create(args: argparse.Namespace) -> int:
    output, signature = args.output.resolve(), args.signature_output.resolve()
    if output.exists() or signature.exists():
        raise FileExistsError("evidence bundle or signature already exists")
    manifest, files = collect(args)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            info = zipfile.ZipInfo("evidence-bundle.json", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
            for bundle_path, (source, _) in sorted(files.items()):
                info = zipfile.ZipInfo(bundle_path, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, source.read_bytes())
        sign_file(output, signature, args)
    except Exception:
        output.unlink(missing_ok=True)
        signature.unlink(missing_ok=True)
        raise
    print(f"EVIDENCE_BUNDLE_CREATE_PASS files={len(files)} output={output}")
    return 0


def verify(args: argparse.Namespace) -> int:
    bundle, signature, public_key = (args.bundle.resolve(), args.signature.resolve(),
                                     args.public_key.resolve())
    public_sha = digest(public_key)
    if public_sha != args.expected_public_key_sha256.lower():
        raise ValueError("evidence bundle public key SHA-256 is not trusted")
    completed = subprocess.run(
        [str(args.signature_check_executable.resolve()), str(bundle), str(signature),
         str(public_key), args.expected_key_id, PRODUCT], capture_output=True, text=True, check=False)
    if completed.returncode:
        raise ValueError((completed.stderr or completed.stdout).strip() or
                         "evidence bundle signature verification failed")
    with zipfile.ZipFile(bundle, "r") as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or any(not safe_member(name) for name in names):
            raise ValueError("evidence bundle contains unsafe or duplicate paths")
        if "evidence-bundle.json" not in names:
            raise ValueError("evidence bundle manifest is missing")
        manifest = json.loads(archive.read("evidence-bundle.json"))
        if manifest.get("schemaVersion") != 1 or manifest.get("product") != PRODUCT:
            raise ValueError("unsupported evidence bundle manifest")
        entries = manifest.get("files")
        if not isinstance(entries, list):
            raise ValueError("evidence bundle file list is malformed")
        expected = set()
        for entry in entries:
            name = entry.get("path")
            if not isinstance(name, str) or not safe_member(name) or name in expected:
                raise ValueError("evidence bundle entry is unsafe or duplicated")
            expected.add(name)
            content = archive.read(name) if name in names else None
            if (content is None or len(content) != entry.get("size") or
                    hashlib.sha256(content).hexdigest() != entry.get("sha256")):
                raise ValueError(f"evidence bundle file changed or missing: {name}")
        if set(names) != expected | {"evidence-bundle.json"}:
            raise ValueError("evidence bundle contains unexpected files")
        qualification = json.loads(archive.read("metadata/release-qualification.json"))
        if qualification.get("passed") is not True or qualification.get("verdict") == "DENIED":
            raise ValueError("bundled release qualification is not passing")
        if manifest.get("includesArtifacts"):
            artifact_manifest = json.loads(archive.read("artifacts/SHA256SUMS.json"))
            artifact_paths = set()
            for entry in artifact_manifest.get("files", []):
                relative = str(entry.get("path", ""))
                name = f"artifacts/payload/{relative}"
                if not safe_member(relative) or name not in names:
                    raise ValueError(f"bundled artifact is unsafe or missing: {relative}")
                content = archive.read(name)
                if (len(content) != entry.get("size") or
                        hashlib.sha256(content).hexdigest() != entry.get("sha256")):
                    raise ValueError(f"bundled artifact differs from release manifest: {relative}")
                artifact_paths.add(name)
            actual_artifacts = {name for name in names if name.startswith("artifacts/payload/")}
            if actual_artifacts != artifact_paths:
                raise ValueError("bundled artifact payload contains unexpected files")
        external_items = [item for item in qualification.get("externalAcceptance", [])
                          if item.get("verified")]
        if external_items:
            module_path = Path(__file__).resolve().with_name("external_acceptance.py")
            spec = importlib.util.spec_from_file_location("pdr_external_acceptance_bundle", module_path)
            if spec is None or spec.loader is None:
                raise ValueError("external acceptance verifier is unavailable")
            external_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(external_module)
            with tempfile.TemporaryDirectory() as directory:
                extracted = Path(directory)
                for name in names:
                    if not name.startswith("external/"):
                        continue
                    destination = (extracted / Path(*PurePosixPath(name).parts)).resolve()
                    destination.relative_to(extracted)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(archive.read(name))
                for item in external_items:
                    acceptance_type = str(item.get("name"))
                    base = extracted / "external" / acceptance_type
                    verification = item.get("verification", {})
                    external_module.verify_signed_report(
                        base / "report.json", base / "report.sig.json", base / "trust-policy.json",
                        str(verification.get("policyId")), str(verification.get("policySha256")),
                        args.signature_check_executable.resolve(), acceptance_type,
                        str(qualification.get("version")), qualification.get("git", {}).get("commit"),
                        qualification.get("artifactManifest", {}).get("sha256"))
    print(f"EVIDENCE_BUNDLE_VERIFY_PASS files={len(expected)} bundle={bundle}")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    create_parser = commands.add_parser("create")
    create_parser.add_argument("--qualification", type=Path, required=True)
    create_parser.add_argument("--include-artifacts", action="store_true")
    create_parser.add_argument("--output", type=Path, required=True)
    create_parser.add_argument("--signature-output", type=Path, required=True)
    create_parser.add_argument("--key-id", required=True)
    create_parser.add_argument("--private-key-path-environment", required=True)
    create_parser.add_argument("--private-key-passphrase-environment")
    create_parser.set_defaults(handler=create)
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--bundle", type=Path, required=True)
    verify_parser.add_argument("--signature", type=Path, required=True)
    verify_parser.add_argument("--public-key", type=Path, required=True)
    verify_parser.add_argument("--expected-key-id", required=True)
    verify_parser.add_argument("--expected-public-key-sha256", required=True)
    verify_parser.add_argument("--signature-check-executable", type=Path, required=True)
    verify_parser.set_defaults(handler=verify)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return args.handler(args)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"EVIDENCE_BUNDLE_ERROR: {error}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
