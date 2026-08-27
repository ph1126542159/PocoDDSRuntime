#!/usr/bin/env python3
"""Run evidence-bound etcd preflight, conformance, and postflight acceptance."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import team_contract_package as package_tool
import team_contract_registry_leader_backend as backend_tool
import team_contract_registry_leader_backend_conformance as conformance_tool


PRODUCT = "PocoDDSRuntimeTeamContractRegistryLeaderEtcdAcceptance"
FAILURE_PRODUCT = "PocoDDSRuntimeTeamContractRegistryLeaderEtcdAcceptanceFailure"


class CommittedAcceptanceError(RuntimeError):
    """The dedicated scope may contain a committed conformance grant."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def example_directory() -> Path:
    root = Path(__file__).resolve().parents[1]
    candidates = (
        root / "examples/team-contract-registry-leader-backend-etcdctl",
        root / "share/PocoDDSRuntime/examples/team-contract-registry-leader-backend-etcdctl",
    )
    directory = next((item for item in candidates if item.is_dir()), None)
    if directory is None:
        raise ValueError("Registry leader etcd SDK example is unavailable")
    return directory


def load_preflight_module():
    directory = example_directory()
    path = directory / "etcd_cluster_preflight.py"
    spec = importlib.util.spec_from_file_location(
        "pdr_team_contract_registry_leader_etcd_acceptance_preflight", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load etcd cluster preflight: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(directory))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def load_report(path: Path, product: str) -> dict[str, Any]:
    document = json.loads(path.read_bytes())
    if (not isinstance(document, dict) or document.get("product") != product
            or document.get("passed") is not True):
        raise ValueError(f"acceptance stage report is invalid: {path.name}")
    return document


def exclusive_json(path: Path, document: dict[str, Any]) -> None:
    with path.open("xb") as stream:
        stream.write(package_tool.json_bytes(document))


def backend_binds_adapter(backend: backend_tool.ExternalCommandBackend,
                          adapter_config: Path, adapter_sha: str) -> None:
    if (backend.config.get("schemaVersion") != 2
            or backend.capability_manifest is None
            or backend.capability_manifest_sha256 is None):
        raise ValueError(
            "etcd acceptance requires negotiated backend capabilities"
        )
    arguments = backend.config["arguments"]
    if (arguments.count("--config") != 1
            or arguments.count("--expected-config-sha256") != 1):
        raise ValueError("backend does not bind one etcd adapter configuration")
    try:
        configured_path = Path(arguments[arguments.index("--config") + 1]).resolve()
        configured_sha = arguments[
            arguments.index("--expected-config-sha256") + 1
        ]
    except (IndexError, OSError) as error:
        raise ValueError("backend etcd adapter arguments are malformed") from error
    pins = {
        str(Path(item["path"]).resolve()): item["sha256"]
        for item in backend.config["artifactPins"]
    }
    if (configured_path != adapter_config or configured_sha != adapter_sha
            or pins.get(str(adapter_config)) != adapter_sha):
        raise ValueError("backend and etcd adapter configuration identities differ")


def execute_command(args: argparse.Namespace) -> int:
    started = utc_now()
    output: Path | None = None
    output_created = False
    committed = False
    stage = "input"
    try:
        if not args.confirm_dedicated_empty_scope:
            raise ValueError(
                "etcd acceptance requires an explicitly confirmed dedicated empty scope"
            )
        output_input = Path(args.output_directory)
        if not output_input.is_absolute():
            raise ValueError("etcd acceptance output directory must be absolute")
        output = output_input.resolve()
        output.mkdir(parents=True, exist_ok=False)
        output_created = True
        adapter_config = Path(args.adapter_config)
        if not adapter_config.is_absolute():
            raise ValueError("etcd adapter config path must be absolute")
        adapter_config = adapter_config.resolve()
        preflight_tool = load_preflight_module()
        # This validates the adapter config and every nested executable/TLS pin.
        adapter_document, loaded_adapter_path = preflight_tool.load_config(
            str(adapter_config), args.expected_adapter_config_sha256
        )
        if loaded_adapter_path != adapter_config:
            raise ValueError("etcd adapter config resolved identity changed")
        backend = backend_tool.ExternalCommandBackend(
            args.backend_config, args.expected_backend_config_sha256,
            args.authority_id, args.registry_id,
        )
        backend_binds_adapter(
            backend, adapter_config, args.expected_adapter_config_sha256
        )

        stage = "preflight-before"
        before_path = output / "preflight-before.json"
        before_result = preflight_tool.execute(argparse.Namespace(
            config=str(adapter_config),
            expected_config_sha256=args.expected_adapter_config_sha256,
            report=str(before_path),
        ))
        if before_result != 0:
            raise ValueError("etcd acceptance write-before preflight failed")
        before = load_report(
            before_path,
            "PocoDDSRuntimeTeamContractRegistryLeaderEtcdPreflight",
        )

        stage = "conformance"
        conformance_path = output / "conformance.json"
        conformance_result = conformance_tool.execute_command(argparse.Namespace(
            backend_config=args.backend_config,
            expected_backend_config_sha256=args.expected_backend_config_sha256,
            authority_id=args.authority_id, registry_id=args.registry_id,
            confirm_dedicated_empty_scope=True,
            report=str(conformance_path),
        ))
        if conformance_result == 3:
            raise CommittedAcceptanceError(
                "etcd backend conformance commit outcome requires reconciliation"
            )
        if conformance_result != 0:
            raise ValueError("etcd backend conformance failed before a proven commit")
        committed = True
        conformance = load_report(
            conformance_path,
            "PocoDDSRuntimeTeamContractRegistryLeaderBackendConformance",
        )

        stage = "preflight-after"
        after_path = output / "preflight-after.json"
        after_result = preflight_tool.execute(argparse.Namespace(
            config=str(adapter_config),
            expected_config_sha256=args.expected_adapter_config_sha256,
            report=str(after_path),
        ))
        if after_result != 0:
            raise CommittedAcceptanceError(
                "etcd post-conformance topology could not be verified"
            )
        after = load_report(
            after_path,
            "PocoDDSRuntimeTeamContractRegistryLeaderEtcdPreflight",
        )
        if (before["clusterId"] != after["clusterId"]
                or set(before["memberIds"]) != set(after["memberIds"])
                or before["endpoints"] != after["endpoints"]):
            raise CommittedAcceptanceError(
                "etcd topology identity changed during acceptance"
            )
        if (conformance.get("backendId") != backend.backend_id
                or conformance.get("authorityId") != args.authority_id
                or conformance.get("registryId") != args.registry_id
                or conformance.get("backendConfigSha256")
                    != args.expected_backend_config_sha256
                or conformance.get("finalFencingToken") != 2):
            raise CommittedAcceptanceError(
                "etcd conformance evidence identity changed"
            )

        stage = "final-report"
        report = {
            "schemaVersion": 1, "product": PRODUCT, "passed": True,
            "adapterId": adapter_document["adapterId"],
            "backendId": backend.backend_id,
            "authorityId": args.authority_id, "registryId": args.registry_id,
            "adapterConfigSha256": args.expected_adapter_config_sha256,
            "backendConfigSha256": args.expected_backend_config_sha256,
            "backendProtocol": {
                "major": backend.capability_manifest["protocolMajor"],
                "minor": backend.capability_manifest["protocolMinor"],
            },
            "capabilityManifestSha256": backend.capability_manifest_sha256,
            "clusterId": before["clusterId"],
            "memberIds": before["memberIds"],
            "leaderBefore": before["leaderId"],
            "leaderAfter": after["leaderId"],
            "minimumRevisionBefore": before["minimumRevision"],
            "minimumRevisionAfter": after["minimumRevision"],
            "finalFencingToken": conformance["finalFencingToken"],
            "finalGrantSha256": conformance["finalGrantSha256"],
            "evidence": {
                "preflightBefore": {
                    "path": before_path.name,
                    "sha256": package_tool.sha256_file(before_path),
                },
                "conformance": {
                    "path": conformance_path.name,
                    "sha256": package_tool.sha256_file(conformance_path),
                },
                "preflightAfter": {
                    "path": after_path.name,
                    "sha256": package_tool.sha256_file(after_path),
                },
            },
            "checks": {
                "configBinding": True, "preflightBefore": True,
                "conformance": True, "preflightAfter": True,
                "topologyStable": True, "evidenceDigestBound": True,
            },
            "startedAt": started, "completedAt": utc_now(),
        }
        final_path = output / "acceptance.json"
        exclusive_json(final_path, report)
        print(
            "PDR_REGISTRY_LEADER_ETCD_ACCEPTANCE_PASS "
            f"backend={backend.backend_id} endpoints={len(before['endpoints'])} "
            f"members={len(before['memberIds'])} cluster={before['clusterId']} "
            f"token={conformance['finalFencingToken']} "
            f"sha256={conformance['finalGrantSha256']}"
        )
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        is_committed = committed or isinstance(error, CommittedAcceptanceError)
        if output_created and output is not None and output.is_dir():
            failure_path = output / "acceptance-failure.json"
            if not failure_path.exists():
                failure = {
                    "schemaVersion": 1, "product": FAILURE_PRODUCT,
                    "passed": False, "committed": is_committed,
                    "stage": stage, "error": str(error)[:1024],
                    "startedAt": started, "completedAt": utc_now(),
                }
                try:
                    exclusive_json(failure_path, failure)
                except OSError:
                    pass
        marker = "COMMITTED_ERROR" if is_committed else "ERROR"
        print(
            f"PDR_REGISTRY_LEADER_ETCD_ACCEPTANCE_{marker}: {error}",
            file=sys.stderr,
        )
        return 3 if is_committed else 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--adapter-config", required=True)
    result.add_argument("--expected-adapter-config-sha256", required=True)
    result.add_argument("--backend-config", required=True)
    result.add_argument("--expected-backend-config-sha256", required=True)
    result.add_argument("--authority-id", required=True)
    result.add_argument("--registry-id", required=True)
    result.add_argument("--confirm-dedicated-empty-scope", action="store_true")
    result.add_argument("--output-directory", required=True)
    result.set_defaults(handler=execute_command)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
