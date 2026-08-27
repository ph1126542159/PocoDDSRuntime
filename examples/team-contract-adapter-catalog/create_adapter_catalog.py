#!/usr/bin/env python3
"""Create a host-local digest-pinned Team Contract Adapter catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalog"
MANIFEST_PRODUCT = "PocoDDSRuntimeTeamContractAdapterManifest"
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
ADAPTER_TYPE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def execute(args: argparse.Namespace) -> int:
    try:
        if (IDENTIFIER.fullmatch(args.catalog_id) is None
                or not 1 <= args.generation <= 2**63 - 1):
            raise ValueError("adapter catalog arguments are malformed")
        entries = []
        adapter_ids = set()
        manifest_ids = set()
        manifest_paths = set()
        for path_value in args.manifest:
            path = Path(path_value)
            if not path.is_absolute():
                raise ValueError("adapter manifest path must be absolute")
            path = path.resolve()
            if path.is_symlink() or not path.is_file():
                raise ValueError("adapter manifest must be a regular non-link file")
            content = path.read_bytes()
            manifest = json.loads(content)
            if (not isinstance(manifest, dict)
                    or manifest.get("product") != MANIFEST_PRODUCT
                    or any(IDENTIFIER.fullmatch(str(manifest.get(name, "")))
                           is None for name in (
                               "adapterId", "manifestId", "revision"))
                    or ADAPTER_TYPE.fullmatch(
                        str(manifest.get("adapterType", ""))) is None):
                raise ValueError("adapter manifest product is incompatible")
            if (manifest["adapterId"] in adapter_ids
                    or manifest["manifestId"] in manifest_ids
                    or str(path) in manifest_paths):
                raise ValueError("adapter manifest identity is duplicated")
            adapter_ids.add(manifest["adapterId"])
            manifest_ids.add(manifest["manifestId"])
            manifest_paths.add(str(path))
            entries.append({
                "adapterId": manifest["adapterId"],
                "adapterType": manifest["adapterType"],
                "manifestId": manifest["manifestId"],
                "revision": manifest["revision"],
                "manifestPath": str(path),
                "manifestSha256": hashlib.sha256(content).hexdigest(),
            })
        entries.sort(key=lambda item: (item["adapterType"], item["adapterId"]))
        output = Path(args.output)
        if not output.is_absolute():
            raise ValueError("output must be absolute")
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "schemaVersion": 1, "product": PRODUCT,
            "catalogId": args.catalog_id, "generation": args.generation,
            "entries": entries,
        }
        content = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
        with output.open("xb") as stream:
            stream.write(content)
        print(
            "PDR_ADAPTER_CATALOG_CREATE_PASS "
            f"catalog={args.catalog_id} adapters={len(entries)} "
            f"sha256={hashlib.sha256(content).hexdigest()}"
        )
        return 0
    except (OSError, UnicodeError, ValueError,
            json.JSONDecodeError) as error:
        print(f"PDR_ADAPTER_CATALOG_CREATE_ERROR: {error}", file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--catalog-id", required=True)
    result.add_argument("--generation", type=int, default=1)
    result.add_argument("--manifest", action="append", required=True)
    result.add_argument("--output", required=True)
    result.set_defaults(handler=execute)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
