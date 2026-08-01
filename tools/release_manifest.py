#!/usr/bin/env python3
"""Generate and verify release hashes plus an SPDX 2.3 SBOM."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXCLUDED_PARTS = {"logs", "data", "codeCache", "disabled-bundles"}


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
    manifest = {
        "schemaVersion": 1,
        "product": "PocoDDSRuntime",
        "version": args.version,
        "gitCommit": commit,
        "dirty": dirty,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
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
        "creationInfo": {"created": datetime.now(timezone.utc).isoformat(), "creators": ["Tool: PocoDDSRuntime-release_manifest"]},
        "packages": packages,
        "relationships": relationships,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "SHA256SUMS.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8", newline="\n")
    (output / "pocoddsruntime.spdx.json").write_text(json.dumps(sbom, indent=2), encoding="utf-8", newline="\n")
    print(f"RELEASE_MANIFEST_PASS files={len(entries)} output={output}")
    return 0


def verify(args: argparse.Namespace) -> int:
    manifest_path = args.manifest.resolve()
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact_root = args.artifacts.resolve() if args.artifacts else Path(document["artifactRoot"])
    errors = []
    for entry in document["files"]:
        path = artifact_root / entry["path"]
        if not path.is_file():
            errors.append(f"missing artifact: {entry['path']}")
        elif path.stat().st_size != entry["size"] or digest(path) != entry["sha256"]:
            errors.append(f"artifact changed: {entry['path']}")
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
    create.set_defaults(handler=generate)
    check = commands.add_parser("verify")
    check.add_argument("--manifest", type=Path, required=True)
    check.add_argument("--artifacts", type=Path)
    check.set_defaults(handler=verify)
    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
