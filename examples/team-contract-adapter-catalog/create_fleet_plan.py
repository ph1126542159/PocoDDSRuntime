#!/usr/bin/env python3
"""Create a digest-pinned canary/wave Adapter Catalog Fleet plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path


PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalogFleetPlan"
CATALOG_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalog"
BACKEND_CONFIG_PRODUCT = "PocoDDSRuntimeTeamContractRegistryLeaderBackendConfig"
ARTIFACT_STORE_CONFIG_PRODUCT = "PocoDDSRuntimeTeamContractArtifactStoreConfig"
EXECUTOR_CONFIG_PRODUCT = \
    "PocoDDSRuntimeTeamContractAdapterCatalogFleetExecutorConfig"
GATE_CONFIG_PRODUCT = \
    "PocoDDSRuntimeTeamContractAdapterCatalogWaveGateConfig"
AUTHORIZER_CONFIG_PRODUCT = \
    "PocoDDSRuntimeTeamContractAdapterCatalogControlAuthorizerConfig"
ADAPTER_CONFIG_TYPES = {
    "fleet-executor": (EXECUTOR_CONFIG_PRODUCT, "executorId"),
    "wave-gate": (GATE_CONFIG_PRODUCT, "gateId"),
    "control-authorizer": (AUTHORIZER_CONFIG_PRODUCT, "authorizerId"),
    "registry-leader-backend": (BACKEND_CONFIG_PRODUCT, "backendId"),
    "artifact-store": (ARTIFACT_STORE_CONFIG_PRODUCT, "storeId"),
}
PATH_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,60}$")
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
CONFORMANCE_KINDS = [
    "adapter-config-resolver", "artifact-store", "control-authorizer",
    "fleet-executor", "registry-leader-backend", "wave-gate",
]
CONFORMANCE_CHECKS = [
    "adapter-identity-bound", "artifact-pins-revalidated",
    "capability-negotiated", "capability-replay-stable",
    "config-pin-enforced", "config-revalidated", "environment-confined",
    "evidence-redacted", "process-policy-bounded",
]


def regular(value: str, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or path.is_symlink():
        raise ValueError(f"{label} must be an absolute non-link file")
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f"{label} is unavailable")
    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def adapter_identity(path: Path, adapter_kind: str) -> str:
    product, identity_field = ADAPTER_CONFIG_TYPES[adapter_kind]
    document = json.loads(path.read_bytes())
    identity = str(document.get(identity_field, "")) \
        if isinstance(document, dict) else ""
    if (not isinstance(document, dict)
            or document.get("product") != product
            or IDENTIFIER.fullmatch(identity) is None):
        raise ValueError(f"Fleet {adapter_kind} config is malformed")
    return identity


def execute(args: argparse.Namespace) -> int:
    try:
        if (PATH_ID.fullmatch(args.rollout_id) is None
                or not 1 <= args.max_parallel_nodes <= 16):
            raise ValueError("Fleet plan identity is malformed")
        catalog_path = regular(args.catalog, "candidate Catalog")
        config_path = regular(args.executor_config, "Fleet Executor config")
        gate_path = regular(args.gate_config, "Wave Gate config") \
            if args.gate_config else None
        authorizer_path = regular(
            args.control_authorizer_config, "Control Authorizer config"
        ) if args.control_authorizer_config else None
        state_backend_path = regular(
            args.state_backend_config, "Fleet state Backend config"
        ) if args.state_backend_config else None
        artifact_store_path = regular(
            args.artifact_store_config, "Fleet Artifact Store config"
        ) if args.artifact_store_config else None
        if authorizer_path is not None and gate_path is None:
            raise ValueError("Control Authorizer requires a Wave Gate config")
        if (state_backend_path is None) != (artifact_store_path is None):
            raise ValueError(
                "Fleet remote state requires Backend and Artifact Store configs"
            )
        if state_backend_path is not None and authorizer_path is None:
            raise ValueError(
                "Fleet remote state requires a Control Authorizer config"
            )
        portable = args.adapter_config_resolver_id is not None \
            or bool(args.config_ref)
        conformance = args.adapter_conformance_policy_id is not None
        signed_conformance = \
            args.adapter_conformance_trust_policy_id is not None
        if signed_conformance and not conformance:
            raise ValueError(
                "signed Adapter admission requires a conformance policy"
            )
        if signed_conformance and (
                IDENTIFIER.fullmatch(
                    args.adapter_conformance_trust_policy_id) is None
                or not 1 <= args.minimum_trust_policy_generation
                    <= 2147483647):
            raise ValueError(
                "Adapter conformance trust requirement is malformed"
            )
        if conformance and not portable:
            raise ValueError(
                "Adapter conformance admission requires a portable Fleet plan"
            )
        if (conformance and (
                IDENTIFIER.fullmatch(args.adapter_conformance_policy_id) is None
                or not 60 <= args.maximum_evidence_age_seconds <= 2678400)):
            raise ValueError(
                "Adapter conformance admission policy is malformed"
            )
        if portable:
            if (args.adapter_config_resolver_id is None
                    or IDENTIFIER.fullmatch(
                        args.adapter_config_resolver_id) is None):
                raise ValueError("Fleet Config Resolver identity is malformed")
            if any(path is None for path in (
                    gate_path, authorizer_path, state_backend_path,
                    artifact_store_path)):
                raise ValueError(
                    "Fleet v5 requires all five local Adapter configs"
                )
        catalog = json.loads(catalog_path.read_bytes())
        if (not isinstance(catalog, dict)
                or catalog.get("product") != CATALOG_PRODUCT
                or IDENTIFIER.fullmatch(str(catalog.get("catalogId", ""))) is None
                or type(catalog.get("generation")) is not int
                or catalog["generation"] < 2):
            raise ValueError("candidate Catalog is malformed")
        state_backend = json.loads(state_backend_path.read_bytes()) \
            if state_backend_path is not None else None
        artifact_store = json.loads(artifact_store_path.read_bytes()) \
            if artifact_store_path is not None else None
        if state_backend is not None and (
                not isinstance(state_backend, dict)
                or state_backend.get("product") != BACKEND_CONFIG_PRODUCT
                or IDENTIFIER.fullmatch(str(
                    state_backend.get("backendId", ""))) is None):
            raise ValueError("Fleet state Backend config is malformed")
        if artifact_store is not None and (
                not isinstance(artifact_store, dict)
                or artifact_store.get("product") != ARTIFACT_STORE_CONFIG_PRODUCT
                or IDENTIFIER.fullmatch(str(
                    artifact_store.get("storeId", ""))) is None):
            raise ValueError("Fleet Artifact Store config is malformed")
        references: dict[str, dict[str, str]] = {}
        for adapter_kind, config_id, revision in args.config_ref:
            if (adapter_kind not in ADAPTER_CONFIG_TYPES
                    or adapter_kind in references
                    or IDENTIFIER.fullmatch(config_id) is None
                    or IDENTIFIER.fullmatch(revision) is None):
                raise ValueError("Fleet Adapter config reference is malformed")
            references[adapter_kind] = {
                "kind": "adapter-config-ref",
                "resolverId": args.adapter_config_resolver_id,
                "configId": config_id, "adapterKind": adapter_kind,
                "adapterId": "pending", "revision": revision,
            }
        if portable and set(references) != set(ADAPTER_CONFIG_TYPES):
            raise ValueError("Fleet v5 requires exactly five config references")
        waves: list[dict[str, object]] = []
        by_id: dict[str, dict[str, object]] = {}
        for index, values in enumerate(args.wave):
            wave_id, mode, failures_value = values
            failures = int(failures_value)
            if (PATH_ID.fullmatch(wave_id) is None or wave_id in by_id
                    or mode not in {"canary", "wave"}
                    or (index == 0) != (mode == "canary") or failures < 0
                    or (index == 0 and failures != 0)):
                raise ValueError("Fleet wave is malformed")
            wave = {"waveId": wave_id, "mode": mode,
                    "maxFailures": failures, "nodes": []}
            waves.append(wave)
            by_id[wave_id] = wave
        seen: set[str] = set()
        for values in args.node:
            wave_id, node_id, domain, generation_value = values
            generation = int(generation_value)
            if (wave_id not in by_id or PATH_ID.fullmatch(node_id) is None
                    or node_id in seen or IDENTIFIER.fullmatch(domain) is None
                    or generation < 1):
                raise ValueError("Fleet plan node is malformed")
            by_id[wave_id]["nodes"].append({
                "nodeId": node_id, "failureDomain": domain,
                "expectedActivationGeneration": generation,
            })
            seen.add(node_id)
        for wave in waves:
            wave["nodes"] = sorted(wave["nodes"], key=lambda item: item["nodeId"])
            if (not wave["nodes"]
                    or wave["maxFailures"] >= len(wave["nodes"])):
                raise ValueError("Fleet wave failure budget is malformed")
        policies: dict[str, dict[str, object]] = {}
        for values in args.wave_gate:
            wave_id, observation_value, evaluations_value, action = values
            observation = int(observation_value)
            evaluations = int(evaluations_value)
            if (wave_id not in by_id or wave_id in policies
                    or not 0 <= observation <= 86400
                    or not 1 <= evaluations <= 100
                    or action not in {"pause", "rollback"}):
                raise ValueError("Fleet Wave Gate policy is malformed")
            policies[wave_id] = {
                "minimumObservationSeconds": observation,
                "maxEvaluations": evaluations, "rejectionAction": action,
            }
        if gate_path is None and policies:
            raise ValueError("Wave Gate policies require a Gate config")
        if gate_path is not None:
            if set(policies) != set(by_id):
                raise ValueError("every Fleet wave requires one Gate policy")
            for wave in waves:
                wave["gatePolicy"] = policies[wave["waveId"]]
        output = Path(args.output)
        if not output.is_absolute() or output.is_symlink():
            raise ValueError("output must be an absolute non-link path")
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "schemaVersion": (7 if signed_conformance else
                6 if conformance else 5 if portable else
                4 if state_backend_path is not None else
                3 if authorizer_path is not None else
                2 if gate_path is not None else 1
            ),
            "product": PRODUCT,
            "rolloutId": args.rollout_id, "catalogId": catalog["catalogId"],
            "candidateCatalogGeneration": catalog["generation"],
            "candidateCatalogSha256": sha(catalog_path),
            "maxParallelNodes": args.max_parallel_nodes, "waves": waves,
        }
        if portable:
            paths = {
                "fleet-executor": config_path,
                "wave-gate": gate_path,
                "control-authorizer": authorizer_path,
                "registry-leader-backend": state_backend_path,
                "artifact-store": artifact_store_path,
            }
            for adapter_kind, path in paths.items():
                assert path is not None
                references[adapter_kind]["adapterId"] = adapter_identity(
                    path, adapter_kind
                )
            document.update({
                "adapterConfigResolverId": args.adapter_config_resolver_id,
                "executorConfigRef": references["fleet-executor"],
                "gateConfigRef": references["wave-gate"],
                "controlAuthorizerConfigRef":
                    references["control-authorizer"],
                "stateBackendConfigRef":
                    references["registry-leader-backend"],
                "artifactStoreConfigRef": references["artifact-store"],
            })
            if conformance:
                document["adapterConformancePolicy"] = {
                    "policyId": args.adapter_conformance_policy_id,
                    "certificationLevel": "integration-readiness",
                    "checkSetVersion": "1.0.0",
                    "maximumEvidenceAgeSeconds":
                        args.maximum_evidence_age_seconds,
                    "requiredAdapterKinds": CONFORMANCE_KINDS,
                    "requiredChecks": CONFORMANCE_CHECKS,
                }
            if signed_conformance:
                document["adapterConformanceTrustPolicy"] = {
                    "policyId":
                        args.adapter_conformance_trust_policy_id,
                    "minimumGeneration":
                        args.minimum_trust_policy_generation,
                }
        else:
            document.update({
                "executorConfigPath": str(config_path),
                "executorConfigSha256": sha(config_path),
            })
        if gate_path is not None and not portable:
            document.update({
                "gateConfigPath": str(gate_path),
                "gateConfigSha256": sha(gate_path),
            })
        if authorizer_path is not None and not portable:
            document.update({
                "controlAuthorizerConfigPath": str(authorizer_path),
                "controlAuthorizerConfigSha256": sha(authorizer_path),
            })
        if state_backend_path is not None and not portable:
            assert state_backend is not None and artifact_store is not None
            document.update({
                "stateBackendId": state_backend["backendId"],
                "stateBackendConfigSha256": sha(state_backend_path),
                "artifactStoreId": artifact_store["storeId"],
                "artifactStoreConfigSha256": sha(artifact_store_path),
            })
        content = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
        descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
        print(
            "PDR_ADAPTER_CATALOG_FLEET_PLAN_PASS "
            f"rollout={args.rollout_id} nodes={len(seen)} "
            f"sha256={hashlib.sha256(content).hexdigest()}"
        )
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"PDR_ADAPTER_CATALOG_FLEET_PLAN_ERROR: {error}", file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--rollout-id", required=True)
    result.add_argument("--catalog", required=True)
    result.add_argument("--executor-config", required=True)
    result.add_argument("--gate-config")
    result.add_argument("--control-authorizer-config")
    result.add_argument("--state-backend-config")
    result.add_argument("--artifact-store-config")
    result.add_argument("--adapter-config-resolver-id")
    result.add_argument("--adapter-conformance-policy-id")
    result.add_argument("--adapter-conformance-trust-policy-id")
    result.add_argument(
        "--minimum-trust-policy-generation", type=int, default=1
    )
    result.add_argument(
        "--maximum-evidence-age-seconds", type=int, default=86400
    )
    result.add_argument(
        "--config-ref", action="append", nargs=3, default=[],
        metavar=("ADAPTER_KIND", "CONFIG_ID", "REVISION"),
    )
    result.add_argument("--max-parallel-nodes", type=int, default=1)
    result.add_argument(
        "--wave", action="append", nargs=3, required=True,
        metavar=("WAVE_ID", "MODE", "MAX_FAILURES"),
    )
    result.add_argument(
        "--node", action="append", nargs=4, required=True,
        metavar=("WAVE_ID", "NODE_ID", "FAILURE_DOMAIN", "EXPECTED_GENERATION"),
    )
    result.add_argument(
        "--wave-gate", action="append", nargs=4, default=[],
        metavar=("WAVE_ID", "MIN_OBSERVATION_SECONDS", "MAX_EVALUATIONS",
                 "REJECTION_ACTION"),
    )
    result.add_argument("--output", required=True)
    return result


if __name__ == "__main__":
    raise SystemExit(execute(parser().parse_args()))
