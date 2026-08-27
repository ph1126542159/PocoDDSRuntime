#!/usr/bin/env python3
"""Create a digest-pinned mapping for the reference Fleet Node Executor."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path


PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalogFleetNodeMap"
PATH_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,60}$")
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def absolute(value: str, label: str, *, file: bool = False) -> Path:
    path = Path(value)
    if not path.is_absolute() or path.is_symlink():
        raise ValueError(f"{label} must be an absolute non-link path")
    path = path.resolve()
    if file and not path.is_file():
        raise ValueError(f"{label} is unavailable")
    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(args: argparse.Namespace) -> int:
    try:
        if IDENTIFIER.fullmatch(args.executor_id) is None or not args.node:
            raise ValueError("Fleet node map identity is malformed")
        audit = absolute(args.audit, "audit path")
        nodes = []
        seen: set[str] = set()
        for values in args.node:
            (node_id, state_dir, transaction_dir, lifecycle_dir,
             config_value, catalog_value, generation_value, health_mode) = values
            if (PATH_ID.fullmatch(node_id) is None or node_id in seen
                    or health_mode not in {"healthy", "unhealthy"}):
                raise ValueError("Fleet node identity is malformed")
            generation = int(generation_value)
            if generation < 1:
                raise ValueError("Fleet node generation is malformed")
            state = absolute(state_dir, "node state directory")
            if not state.is_dir():
                raise ValueError("node state directory is unavailable")
            transaction = absolute(transaction_dir, "node transaction directory")
            lifecycle = absolute(lifecycle_dir, "node lifecycle directory")
            config = absolute(config_value, "node Reconciler config", file=True)
            catalog = absolute(catalog_value, "node candidate Catalog", file=True)
            nodes.append({
                "nodeId": node_id, "stateDir": str(state),
                "transactionDir": str(transaction),
                "lifecycleStateDir": str(lifecycle),
                "reconcilerConfigPath": str(config),
                "reconcilerConfigSha256": sha(config),
                "catalogPath": str(catalog), "catalogSha256": sha(catalog),
                "expectedActivationGeneration": generation,
                "healthMode": health_mode,
            })
            seen.add(node_id)
        output = absolute(args.output, "output")
        output.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "schemaVersion": 1, "product": PRODUCT,
            "executorId": args.executor_id, "auditPath": str(audit),
            "nodes": sorted(nodes, key=lambda item: item["nodeId"]),
        }
        content = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
        descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
        print(
            "PDR_ADAPTER_CATALOG_FLEET_NODE_MAP_PASS "
            f"nodes={len(nodes)} sha256={hashlib.sha256(content).hexdigest()}"
        )
        return 0
    except (OSError, ValueError) as error:
        print(f"PDR_ADAPTER_CATALOG_FLEET_NODE_MAP_ERROR: {error}", file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--executor-id", required=True)
    result.add_argument("--audit", required=True)
    result.add_argument(
        "--node", action="append", nargs=8, required=True,
        metavar=("NODE_ID", "STATE_DIR", "TRANSACTION_DIR", "LIFECYCLE_DIR",
                 "RECONCILER_CONFIG", "CATALOG", "EXPECTED_GENERATION",
                 "HEALTH_MODE"),
    )
    result.add_argument("--output", required=True)
    return result


if __name__ == "__main__":
    raise SystemExit(execute(parser().parse_args()))
