#!/usr/bin/env python3
"""Create deterministic, test-only Ed25519 keys and a two-team trust policy."""

import argparse
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


TEAMS = (
    ("workflow", "team.workflow", "team.order-workflow", bytes(range(1, 33))),
    ("scheduling", "team.scheduling", "team.scheduler", bytes(range(33, 65))),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    keys = output / "keys"
    keys.mkdir(parents=True, exist_ok=True)
    publishers = []
    for name, owner, package_id, seed in TEAMS:
        key = Ed25519PrivateKey.from_private_bytes(seed)
        private_path = output / f"team-{name}.private.pem"
        public_path = keys / f"team-{name}.pem"
        private_path.write_bytes(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
        public_path.write_bytes(key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ))
        publishers.append({
            "owner": owner,
            "keyId": f"team-{name}-test-2026",
            "algorithm": "Ed25519",
            "publicKey": f"keys/team-{name}.pem",
            "publicKeySha256": hashlib.sha256(public_path.read_bytes()).hexdigest(),
            "packageIds": [package_id],
            "notBefore": "2025-01-01T00:00:00Z",
            "notAfter": "2030-01-01T00:00:00Z",
        })
    policy = {
        "schemaVersion": 1,
        "product": "PocoDDSRuntimeTeamContractTrustPolicy",
        "policyId": "component-consumer-team-contracts",
        "allowedPublishers": publishers,
        "revokedKeys": [],
    }
    (output / "team-contract-trust-policy.json").write_text(
        json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    approval_key = Ed25519PrivateKey.from_private_bytes(bytes(range(65, 97)))
    approval_private = output / "team-workflow-impact-approval.private.pem"
    approval_public = keys / "team-workflow-impact-approval.pem"
    approval_private.write_bytes(approval_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    approval_public.write_bytes(approval_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ))
    approval_policy = {
        "schemaVersion": 1,
        "product": "PocoDDSRuntimeTeamContractImpactApprovalPolicy",
        "policyId": "component-consumer-impact-owners",
        "maxApprovalLifetimeSeconds": 7200,
        "allowedApprovers": [{
            "owner": "team.workflow",
            "approverId": "workflow-contract-owner",
            "keyId": "team-workflow-impact-approver-2026",
            "algorithm": "Ed25519",
            "publicKey": "keys/team-workflow-impact-approval.pem",
            "publicKeySha256": hashlib.sha256(
                approval_public.read_bytes()
            ).hexdigest(),
            "notBefore": "2025-01-01T00:00:00Z",
            "notAfter": "2030-01-01T00:00:00Z",
        }],
        "revokedKeys": [],
    }
    (output / "team-contract-impact-approval-policy.json").write_text(
        json.dumps(approval_policy, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    runner_key = Ed25519PrivateKey.from_private_bytes(bytes(range(97, 129)))
    runner_private = output / "team-contract-ci-runner.private.pem"
    runner_public = keys / "team-contract-ci-runner.pem"
    runner_private.write_bytes(runner_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    runner_public.write_bytes(runner_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ))
    runner_policy = {
        "schemaVersion": 1,
        "product": "PocoDDSRuntimeTeamContractRunnerTrustPolicy",
        "policyId": "component-consumer-ci-runners",
        "maxAttestationLifetimeSeconds": 7200,
        "allowedRunners": [{
            "runnerId": "ci.windows.release",
            "keyId": "component-consumer-runner-2026",
            "algorithm": "Ed25519",
            "publicKey": "keys/team-contract-ci-runner.pem",
            "publicKeySha256": hashlib.sha256(runner_public.read_bytes()).hexdigest(),
            "repositories": ["pocodds/runtime"],
            "workflows": ["team-contract-acceptance"],
            "notBefore": "2025-01-01T00:00:00Z",
            "notAfter": "2030-01-01T00:00:00Z",
        }],
        "revokedKeys": [],
    }
    (output / "team-contract-runner-trust-policy.json").write_text(
        json.dumps(runner_policy, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    anchor_key = Ed25519PrivateKey.from_private_bytes(bytes(range(129, 161)))
    anchor_private = output / "team-contract-registry-anchor.private.pem"
    anchor_public = keys / "team-contract-registry-anchor.pem"
    anchor_private.write_bytes(anchor_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    anchor_public.write_bytes(anchor_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ))
    anchor_policy = {
        "schemaVersion": 1,
        "product": "PocoDDSRuntimeTeamContractRegistryAnchorPolicy",
        "policyId": "component-consumer-registry-auditors",
        "allowedAnchors": [{
            "anchorServiceId": "external.audit.service",
            "keyId": "component-consumer-anchor-2026",
            "algorithm": "Ed25519",
            "publicKey": "keys/team-contract-registry-anchor.pem",
            "publicKeySha256": hashlib.sha256(anchor_public.read_bytes()).hexdigest(),
            "registryIds": ["component-consumer-contracts"],
            "notBefore": "2025-01-01T00:00:00Z",
            "notAfter": "2030-01-01T00:00:00Z",
        }],
        "revokedKeys": [],
    }
    (output / "team-contract-registry-anchor-policy.json").write_text(
        json.dumps(anchor_policy, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    gate_authorizer_key = Ed25519PrivateKey.from_private_bytes(bytes(range(161, 193)))
    gate_authorizer_private = output / "team-contract-gate-authorizer.private.pem"
    gate_authorizer_public = keys / "team-contract-gate-authorizer.pem"
    gate_authorizer_private.write_bytes(gate_authorizer_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    gate_authorizer_public.write_bytes(gate_authorizer_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ))
    gate_authorization_policy = {
        "schemaVersion": 1,
        "product": "PocoDDSRuntimeTeamContractGateAuthorizationPolicy",
        "policyId": "component-consumer-gate-authorizers",
        "maxAuthorizationLifetimeSeconds": 7200,
        "allowedAuthorizers": [{
            "authorizerId": "release.gate.service",
            "keyId": "component-consumer-gate-authorizer-2026",
            "algorithm": "Ed25519",
            "publicKey": "keys/team-contract-gate-authorizer.pem",
            "publicKeySha256": hashlib.sha256(
                gate_authorizer_public.read_bytes()
            ).hexdigest(),
            "registryIds": ["component-consumer-contracts"],
            "channels": ["staging", "production"],
            "notBefore": "2025-01-01T00:00:00Z",
            "notAfter": "2030-01-01T00:00:00Z",
        }],
        "revokedKeys": [],
    }
    (output / "team-contract-gate-authorization-policy.json").write_text(
        json.dumps(gate_authorization_policy, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    remote_reader_token = "component-consumer-reader-token-0123456789abcdef-2026"
    remote_access_policy = {
        "schemaVersion": 1,
        "product": "PocoDDSRuntimeTeamContractRegistryAccessPolicy",
        "policyId": "component-consumer-registry-remote-access",
        "registryId": "component-consumer-contracts",
        "maxRequestBytes": 4 * 1024 * 1024,
        "maxResponseBytes": 4 * 1024 * 1024,
        "principals": [{
            "principalId": "team.workflow.remote-consumer",
            "tokenSha256": hashlib.sha256(
                remote_reader_token.encode("utf-8")
            ).hexdigest(),
            "roles": ["reader", "auditor"],
            "packageIds": [],
            "channels": [],
            "notBefore": "2025-01-01T00:00:00Z",
            "notAfter": "2030-01-01T00:00:00Z",
        }],
        "revokedTokenSha256": [],
    }
    (output / "team-contract-registry-access-policy.json").write_text(
        json.dumps(remote_access_policy, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
