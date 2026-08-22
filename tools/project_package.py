#!/usr/bin/env python3
"""Create and verify deterministic, signed PocoDDSRuntime product packages."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import stat
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


PRODUCT = "PocoDDSRuntimeProjectPackage"
EXCLUDED_PARTS = {"logs", "data", "codeCache", "disabled-bundles", "__pycache__"}
MAX_FILES_DEFAULT = 10000
MAX_EXPANDED_BYTES_DEFAULT = 4 * 1024 * 1024 * 1024


def json_bytes(document: Any) -> bytes:
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


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
        raise ValueError(f"unsafe package entry: {value}")
    return path


def artifact_files(root: Path, maximum_files: int, maximum_bytes: int) -> list[Path]:
    if not root.is_dir():
        raise FileNotFoundError(f"artifact directory not found: {root}")
    result: list[Path] = []
    total = 0
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError(f"artifact links are prohibited: {relative.as_posix()}")
        if not path.is_file():
            continue
        safe_archive_path(relative.as_posix())
        result.append(path)
        total += path.stat().st_size
        if len(result) > maximum_files:
            raise ValueError(f"artifact file count exceeds {maximum_files}")
        if total > maximum_bytes:
            raise ValueError(f"artifact expanded size exceeds {maximum_bytes} bytes")
    if not result:
        raise ValueError("artifact directory contains no files")
    return result


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


def validate_key_id(key_id: str) -> None:
    if not key_id or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", key_id):
        raise ValueError("signing key id is invalid")


def sign_manifest(content: bytes, args: Any) -> bytes | None:
    hmac_environment = args.signing_key_environment
    ed25519_environment = args.ed25519_private_key_environment
    key_id = args.signing_key_id
    if hmac_environment and ed25519_environment:
        raise ValueError("choose either HMAC or Ed25519 signing")
    if bool(hmac_environment or ed25519_environment) != bool(key_id):
        raise ValueError("signing key source and key id must be provided together")
    if args.private_key_passphrase_environment and not ed25519_environment:
        raise ValueError("private key passphrase requires Ed25519 signing")
    if not key_id:
        return None
    validate_key_id(key_id)
    if hmac_environment:
        signature = hmac.new(signing_key(hmac_environment), content, hashlib.sha256).digest()
        algorithm = "HMAC-SHA256"
    else:
        key_path = os.environ.get(ed25519_environment)
        if not key_path:
            raise ValueError(f"private key path environment is unset: {ed25519_environment}")
        passphrase = None
        if args.private_key_passphrase_environment:
            value = os.environ.get(args.private_key_passphrase_environment)
            if value is None:
                raise ValueError(
                    "private key passphrase environment is unset: "
                    + args.private_key_passphrase_environment
                )
            passphrase = value.encode("utf-8")
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
        except ImportError as error:
            raise ValueError("Ed25519 signing requires the cryptography package") from error
        key = load_pem_private_key(Path(key_path).read_bytes(), password=passphrase)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("project package private key is not Ed25519")
        signature = key.sign(content)
        algorithm = "Ed25519"
    return json_bytes({
        "schemaVersion": 1,
        "product": PRODUCT,
        "algorithm": algorithm,
        "keyId": key_id,
        "manifestSha256": sha256_bytes(content),
        "signature": base64.b64encode(signature).decode("ascii"),
    })


def package_output_allowed(project_root: Path, output: Path) -> bool:
    try:
        relative = output.resolve().relative_to(project_root.resolve())
    except ValueError:
        return True
    return bool(relative.parts and relative.parts[0] in {"build", "install"})


def validate_lock(manifest: Path, lock_path: Path, lock: dict[str, Any]) -> None:
    import project_manager

    if (lock.get("schemaVersion") != 1 or lock.get("operation") != "project-resolve"
            or not isinstance(lock.get("project"), dict)):
        raise ValueError("project lock is malformed")
    manifest_digest = sha256_file(manifest)
    if lock.get("manifestSha256") != manifest_digest:
        raise ValueError("project lock does not match pdr-project.yaml; run project resolve")
    project = project_manager.validate_manifest(manifest, check_paths=True)
    if lock["project"] != project:
        raise ValueError("project lock normalized project does not match current manifest")
    tree_digest, file_count = project_manager.tree_digest(manifest.parent, {lock_path})
    if (lock.get("sourceTreeSha256") != tree_digest
            or lock.get("sourceFileCount") != file_count):
        raise ValueError("project source tree changed after lock; run project resolve")


def component_records(project: dict[str, Any]) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    for field, values in project["components"].items():
        if field == "adapters":
            for adapter_kind, paths in values.items():
                records.extend((f"adapter-{adapter_kind}", path) for path in paths)
        else:
            records.extend((field, path) for path in values)
    return sorted(records, key=lambda item: (item[0], item[1]))


def make_spdx(project: dict[str, Any], version: str, license_id: str,
              lock: dict[str, Any], payload: list[dict[str, Any]], epoch: int) -> dict[str, Any]:
    package_id = "SPDXRef-Package-Project"
    packages: list[dict[str, Any]] = [{
        "SPDXID": package_id,
        "name": project["name"],
        "versionInfo": version,
        "downloadLocation": "NOASSERTION",
        "licenseConcluded": license_id,
        "licenseDeclared": license_id,
        "copyrightText": "NOASSERTION",
        "primaryPackagePurpose": "APPLICATION",
    }]
    relationships: list[dict[str, str]] = []
    dependencies = [{
        "name": "PocoDDSRuntime",
        "version": project["runtime"]["version"],
        "license": "NOASSERTION",
        "download": "NOASSERTION",
        "scope": "runtime",
        "optional": False,
    }, *project["dependencies"]]
    for index, dependency in enumerate(dependencies, 1):
        dependency_id = f"SPDXRef-Dependency-{index}"
        packages.append({
            "SPDXID": dependency_id,
            "name": dependency["name"],
            "versionInfo": dependency["version"],
            "downloadLocation": dependency["download"],
            "licenseConcluded": dependency["license"],
            "licenseDeclared": dependency["license"],
            "copyrightText": "NOASSERTION",
            "primaryPackagePurpose": "LIBRARY",
        })
        relationships.append({
            "spdxElementId": package_id,
            "relationshipType": "DEPENDS_ON",
            "relatedSpdxElement": dependency_id,
            "comment": f"scope={dependency['scope']}; optional={str(dependency['optional']).lower()}",
        })
    for index, (kind, path) in enumerate(component_records(project), 1):
        component_id = f"SPDXRef-Component-{index}"
        packages.append({
            "SPDXID": component_id,
            "name": Path(path).name,
            "versionInfo": version,
            "downloadLocation": "NOASSERTION",
            "licenseConcluded": license_id,
            "licenseDeclared": license_id,
            "copyrightText": "NOASSERTION",
            "primaryPackagePurpose": "LIBRARY",
            "comment": f"kind={kind}; source={path}",
        })
        relationships.append({
            "spdxElementId": package_id,
            "relationshipType": "CONTAINS",
            "relatedSpdxElement": component_id,
        })
    files = []
    for index, entry in enumerate(payload, 1):
        file_id = f"SPDXRef-File-{index}"
        files.append({
            "SPDXID": file_id,
            "fileName": entry["path"],
            "checksums": [{"algorithm": "SHA256", "checksumValue": entry["sha256"]}],
            "licenseConcluded": "NOASSERTION",
            "copyrightText": "NOASSERTION",
        })
        relationships.append({
            "spdxElementId": package_id,
            "relationshipType": "CONTAINS",
            "relatedSpdxElement": file_id,
        })
    namespace_seed = f"{project['name']}:{version}:{lock['sourceTreeSha256']}"
    created = datetime.fromtimestamp(epoch, timezone.utc).isoformat()
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{project['name']}-{version}",
        "documentNamespace": "https://pocoddsruntime.local/spdx/"
                             + hashlib.sha256(namespace_seed.encode()).hexdigest(),
        "creationInfo": {"created": created, "creators": ["Tool: pdr-project-package"]},
        "packages": packages,
        "files": files,
        "relationships": relationships,
    }


def create_project_package(args: Any) -> int:
    import project_config
    import project_manager
    import project_template

    manifest = Path(args.manifest).resolve()
    project_root = manifest.parent
    output = Path(args.output).resolve()
    artifacts_root = Path(args.artifacts).resolve()
    if output.exists() and not args.force:
        raise FileExistsError(f"package output already exists: {output}")
    if not package_output_allowed(project_root, output):
        raise ValueError("package output inside project must be under build/ or install/")
    try:
        output.relative_to(artifacts_root)
    except ValueError:
        pass
    else:
        raise ValueError("package output must not be inside the artifact directory")
    project = project_manager.validate_manifest(manifest, check_paths=True)
    if project.get("version") is not None and project["version"] != args.version:
        raise ValueError(
            f"package version {args.version} does not match project version {project['version']}"
        )
    if project.get("template"):
        template_status = project_template.status_document(manifest)
        if not template_status["healthy"]:
            raise ValueError(
                "project template is not release-ready: "
                f"update={template_status['updateAvailable']} "
                f"drift={template_status['drifted']}"
            )
    lock_path = (Path(args.lock).resolve() if args.lock
                 else manifest.with_name("pdr-project.lock.json"))
    if args.refresh_lock:
        lock = project_manager.write_project_lock(manifest, lock_path)
    else:
        if not lock_path.is_file():
            raise FileNotFoundError("project lock not found; run project resolve or use --refresh-lock")
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    validate_lock(manifest, lock_path, lock)
    resolved_config = project_config.resolve_configuration(
        manifest, args.target_config_version, args.require_environment
    )
    files = artifact_files(artifacts_root, args.maximum_files, args.maximum_expanded_bytes)
    entries: dict[str, bytes] = {
        "metadata/pdr-project.yaml": manifest.read_bytes(),
        "metadata/pdr-project.lock.json": lock_path.read_bytes(),
        "metadata/resolved-config.json": json_bytes(resolved_config),
    }
    payload_evidence: list[dict[str, Any]] = []
    for path in files:
        relative = path.relative_to(artifacts_root).as_posix()
        archive_path = f"payload/{relative}"
        content = path.read_bytes()
        entries[archive_path] = content
        payload_evidence.append({
            "path": archive_path, "size": len(content), "sha256": sha256_bytes(content)
        })
    sbom = make_spdx(project, args.version, args.license, lock, payload_evidence,
                     args.source_date_epoch)
    entries["metadata/project.spdx.json"] = json_bytes(sbom)
    file_evidence = [
        {"path": name, "size": len(content), "sha256": sha256_bytes(content)}
        for name, content in sorted(entries.items())
    ]
    package_manifest = {
        "schemaVersion": 1,
        "product": PRODUCT,
        "name": project["name"],
        "displayName": project["displayName"],
        "version": args.version,
        "runtime": project["runtime"],
        "template": project.get("template"),
        "sourceDateEpoch": args.source_date_epoch,
        "projectManifestSha256": sha256_file(manifest),
        "projectLockSha256": sha256_file(lock_path),
        "sourceTreeSha256": lock["sourceTreeSha256"],
        "resolvedConfigSha256": sha256_bytes(entries["metadata/resolved-config.json"]),
        "sbomSha256": sha256_bytes(entries["metadata/project.spdx.json"]),
        "files": file_evidence,
    }
    manifest_content = json_bytes(package_manifest)
    entries["metadata/package-manifest.json"] = manifest_content
    signature = sign_manifest(manifest_content, args)
    if signature is not None:
        entries["metadata/package-manifest.sig.json"] = signature
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=9, strict_timestamps=True) as archive:
            for name, content in sorted(entries.items()):
                archive.writestr(zip_info(name, args.source_date_epoch), content)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    print(
        f"PDR_PROJECT_PACKAGE_CREATE_PASS name={project['name']} version={args.version} "
        f"files={len(entries)} sha256={sha256_file(output)} output={output}"
    )
    return 0


def verify_signature(manifest: bytes, signature: dict[str, Any], args: Any) -> dict[str, Any]:
    if (signature.get("schemaVersion") != 1 or signature.get("product") != PRODUCT
            or signature.get("keyId") != args.expected_key_id
            or signature.get("manifestSha256") != sha256_bytes(manifest)):
        raise ValueError("package signature identity or manifest digest is invalid")
    try:
        supplied = base64.b64decode(signature["signature"], validate=True)
    except Exception as error:
        raise ValueError("package signature encoding is invalid") from error
    algorithm = signature.get("algorithm")
    if algorithm == "HMAC-SHA256":
        if not args.trusted_key_environment:
            raise ValueError("HMAC verification requires trusted key environment")
        expected = hmac.new(
            signing_key(args.trusted_key_environment), manifest, hashlib.sha256
        ).digest()
        if not hmac.compare_digest(supplied, expected):
            raise ValueError("package HMAC signature verification failed")
        return {"algorithm": algorithm, "keyId": args.expected_key_id}
    if algorithm == "Ed25519":
        if not args.public_key or not args.expected_public_key_sha256:
            raise ValueError("Ed25519 verification requires a pinned public key")
        public_key = Path(args.public_key).resolve()
        if not hmac.compare_digest(
                sha256_file(public_key), args.expected_public_key_sha256.lower()):
            raise ValueError("package public key SHA-256 is not trusted")
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            from cryptography.hazmat.primitives.serialization import load_pem_public_key
        except ImportError as error:
            raise ValueError("Ed25519 verification requires the cryptography package") from error
        key = load_pem_public_key(public_key.read_bytes())
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("package public key is not Ed25519")
        try:
            key.verify(supplied, manifest)
        except Exception as error:
            raise ValueError("package Ed25519 signature verification failed") from error
        return {"algorithm": algorithm, "keyId": args.expected_key_id,
                "publicKeySha256": sha256_file(public_key)}
    raise ValueError("unsupported package signature algorithm")


def inspect_archive(path: Path, maximum_files: int,
                    maximum_bytes: int) -> tuple[dict[str, bytes], list[str]]:
    entries: dict[str, bytes] = {}
    errors: list[str] = []
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > maximum_files:
            raise ValueError(f"package file count exceeds {maximum_files}")
        expanded = 0
        for info in infos:
            name = info.filename
            try:
                safe_archive_path(name)
            except ValueError as error:
                errors.append(str(error))
                continue
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                errors.append(f"package links are prohibited: {name}")
                continue
            if name in entries:
                errors.append(f"duplicate package entry: {name}")
                continue
            expanded += info.file_size
            if expanded > maximum_bytes:
                raise ValueError(f"package expanded size exceeds {maximum_bytes} bytes")
            entries[name] = archive.read(info)
    return entries, errors


def verify_project_package(args: Any) -> int:
    archive_path = Path(args.package).resolve()
    if not archive_path.is_file() or archive_path.is_symlink():
        raise FileNotFoundError(f"project package not found or is a link: {archive_path}")
    try:
        entries, errors = inspect_archive(
            archive_path, args.maximum_files, args.maximum_expanded_bytes
        )
    except zipfile.BadZipFile as error:
        raise ValueError("project package is not a valid ZIP archive") from error
    required = {
        "metadata/pdr-project.yaml", "metadata/pdr-project.lock.json",
        "metadata/resolved-config.json", "metadata/project.spdx.json",
        "metadata/package-manifest.json",
    }
    missing = sorted(required - set(entries))
    errors.extend(f"missing required package entry: {name}" for name in missing)
    if missing:
        raise ValueError("; ".join(errors))
    try:
        manifest = json.loads(entries["metadata/package-manifest.json"])
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("package manifest is invalid JSON") from error
    if (manifest.get("schemaVersion") != 1 or manifest.get("product") != PRODUCT
            or not isinstance(manifest.get("files"), list)):
        errors.append("package manifest identity is invalid")
    expected_paths: set[str] = set()
    for evidence in manifest.get("files", []):
        if not isinstance(evidence, dict) or not isinstance(evidence.get("path"), str):
            errors.append("malformed package file evidence")
            continue
        name = evidence["path"]
        try:
            safe_archive_path(name)
        except ValueError as error:
            errors.append(str(error))
            continue
        if name in expected_paths:
            errors.append(f"duplicate package manifest path: {name}")
            continue
        expected_paths.add(name)
        content = entries.get(name)
        if content is None:
            errors.append(f"package manifest references missing entry: {name}")
        elif evidence.get("size") != len(content) or evidence.get("sha256") != sha256_bytes(content):
            errors.append(f"package entry changed: {name}")
    allowed_unlisted = {"metadata/package-manifest.json", "metadata/package-manifest.sig.json"}
    unexpected = sorted(set(entries) - expected_paths - allowed_unlisted)
    errors.extend(f"unexpected package entry: {name}" for name in unexpected)
    for name, field in (
        ("metadata/pdr-project.yaml", "projectManifestSha256"),
        ("metadata/pdr-project.lock.json", "projectLockSha256"),
        ("metadata/resolved-config.json", "resolvedConfigSha256"),
        ("metadata/project.spdx.json", "sbomSha256"),
    ):
        if manifest.get(field) != sha256_bytes(entries[name]):
            errors.append(f"package manifest {field} mismatch")
    lock = json.loads(entries["metadata/pdr-project.lock.json"])
    if lock.get("manifestSha256") != sha256_bytes(entries["metadata/pdr-project.yaml"]):
        errors.append("package lock project manifest digest mismatch")
    if lock.get("sourceTreeSha256") != manifest.get("sourceTreeSha256"):
        errors.append("package lock source tree digest mismatch")
    locked_project = lock.get("project")
    if (not isinstance(locked_project, dict) or locked_project.get("name") != manifest.get("name")
            or manifest.get("runtime") != locked_project.get("runtime")
            or manifest.get("template") != locked_project.get("template")):
        errors.append("package identity does not match the locked project")
    resolved_config = json.loads(entries["metadata/resolved-config.json"])
    if (resolved_config.get("operation") != "project-config-resolve"
            or resolved_config.get("project") != manifest.get("name")):
        errors.append("resolved configuration does not match the package project")
    sbom = json.loads(entries["metadata/project.spdx.json"])
    if (sbom.get("spdxVersion") != "SPDX-2.3" or sbom.get("dataLicense") != "CC0-1.0"
            or not isinstance(sbom.get("packages"), list)):
        errors.append("package SPDX SBOM is malformed")
    elif not any(
            isinstance(item, dict) and item.get("name") == manifest.get("name")
            and item.get("versionInfo") == manifest.get("version")
            for item in sbom["packages"]):
        errors.append("package SPDX SBOM does not identify the packaged project version")
    signature_name = "metadata/package-manifest.sig.json"
    signature_evidence = None
    if signature_name in entries:
        if not args.expected_key_id:
            errors.append("signed package verification requires expected key id")
        else:
            try:
                signature_document = json.loads(entries[signature_name])
                signature_evidence = verify_signature(
                    entries["metadata/package-manifest.json"], signature_document, args
                )
            except (UnicodeError, json.JSONDecodeError, OSError, ValueError) as error:
                errors.append(str(error))
    elif args.require_signature:
        errors.append("project package signature is required")
    if errors:
        raise ValueError("; ".join(errors))
    report = {
        "schemaVersion": 1,
        "operation": "project-package-verify",
        "passed": True,
        "package": str(archive_path),
        "packageSha256": sha256_file(archive_path),
        "name": manifest["name"],
        "version": manifest["version"],
        "files": len(entries),
        "sourceTreeSha256": manifest["sourceTreeSha256"],
        "signature": signature_evidence,
    }
    if args.report:
        import project_manager
        project_manager.atomic_json(Path(args.report).resolve(), report)
    print(
        f"PDR_PROJECT_PACKAGE_VERIFY_PASS name={manifest['name']} version={manifest['version']} "
        f"files={len(entries)} sha256={report['packageSha256']}"
    )
    return 0
