#!/usr/bin/env python3
"""Qualify a Registry leader backend in an explicitly dedicated empty scope."""

from __future__ import annotations

import argparse
import base64
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import team_contract_package as package_tool
import team_contract_registry as registry_tool
import team_contract_registry_leader_backend as backend_tool


REPORT_PRODUCT = \
    "PocoDDSRuntimeTeamContractRegistryLeaderBackendConformance"
GRANT_PRODUCT = "PocoDDSRuntimeTeamContractRegistryLeaderGrant"


def synthetic_grant(authority_id: str, registry_id: str, token: int,
                    previous_sha: str | None, candidate: int) \
        -> tuple[dict[str, Any], bytes, str]:
    state_sha = f"{candidate % 16:x}" * 64
    signature = base64.b64encode(bytes([candidate % 256]) * 64).decode("ascii")
    document = {
        "schemaVersion": 1, "product": GRANT_PRODUCT,
        "authorityId": authority_id, "registryId": registry_id,
        "purpose": "fence", "leaderId": None, "fencingToken": token,
        "previousGrantSha256": previous_sha, "baselineRevision": candidate,
        "baselineStateSha256": state_sha, "handoffEvidenceSha256": None,
        "issuedAt": "2026-01-01T00:00:00+00:00",
        "notBefore": "2026-01-01T00:00:00+00:00",
        "expiresAt": "2026-01-01T01:00:00+00:00",
        "trustPolicy": {
            "policyId": "backend-conformance-trust", "policySha256": "a" * 64,
        },
        "signer": {
            "keyId": "backend-conformance-key", "algorithm": "Ed25519",
            "signature": signature,
        },
    }
    content = package_tool.json_bytes(document)
    return document, content, package_tool.sha256_bytes(content)


def check(checks: list[dict[str, Any]], identity: str,
          evidence: dict[str, Any]) -> None:
    checks.append({"id": identity, "passed": True, "evidence": evidence})


def expect_value_error(call: Any, label: str) -> str:
    try:
        call()
    except ValueError as error:
        return str(error)
    raise ValueError(f"Registry leader backend {label} unexpectedly succeeded")


def execute_command(args: argparse.Namespace) -> int:
    committed = False
    try:
        if (not args.confirm_dedicated_empty_scope
                or not package_tool.IDENTIFIER.fullmatch(str(args.authority_id))
                or not package_tool.IDENTIFIER.fullmatch(str(args.registry_id))):
            raise ValueError(
                "backend conformance requires a valid explicitly confirmed "
                "dedicated empty scope"
            )
        backend = backend_tool.ExternalCommandBackend(
            args.backend_config, args.expected_backend_config_sha256,
            args.authority_id, args.registry_id,
        )
        started = registry_tool.utc_time(None)
        checks: list[dict[str, Any]] = []
        if backend.current() is not None:
            raise ValueError(
                "backend conformance scope is not empty; use a new dedicated identity"
            )
        check(checks, "empty-scope", {"currentFound": False})

        missing_sha = "f" * 64
        missing_error = expect_value_error(
            lambda: backend.grant(1, missing_sha), "missing history read"
        )
        check(checks, "missing-history", {
            "token": 1, "grantSha256": missing_sha, "rejected": True,
            "error": missing_error[:512],
        })

        grant1, content1, sha1 = synthetic_grant(
            args.authority_id, args.registry_id, 1, None, 1
        )
        backend.compare_and_swap(0, backend_tool.ZERO_SHA256,
                                 grant1, content1, sha1)
        committed = True
        current1 = backend.current()
        history1 = backend.grant(1, sha1)
        if (current1 is None or current1[1] != content1
                or current1[2] != sha1 or history1[1] != content1
                or history1[2] != sha1):
            raise ValueError("backend conformance token 1 bytes changed")
        check(checks, "initial-cas", {
            "token": 1, "grantSha256": sha1, "currentByteExact": True,
            "historyByteExact": True,
        })

        stale, stale_content, stale_sha = synthetic_grant(
            args.authority_id, args.registry_id, 1, None, 9
        )
        stale_error = expect_value_error(
            lambda: backend.compare_and_swap(
                0, backend_tool.ZERO_SHA256, stale, stale_content, stale_sha
            ),
            "stale initial CAS",
        )
        unchanged = backend.current()
        if unchanged is None or unchanged[1] != content1 or unchanged[2] != sha1:
            raise ValueError("backend conformance stale CAS changed current state")
        check(checks, "stale-cas", {
            "expectedToken": 0, "actualToken": 1, "rejected": True,
            "currentUnchanged": True, "error": stale_error[:512],
        })

        candidates = [
            synthetic_grant(args.authority_id, args.registry_id, 2, sha1, 2),
            synthetic_grant(args.authority_id, args.registry_id, 2, sha1, 3),
        ]

        def race(candidate: tuple[dict[str, Any], bytes, str]) \
                -> tuple[bool, str]:
            contender = backend_tool.ExternalCommandBackend(
                args.backend_config, args.expected_backend_config_sha256,
                args.authority_id, args.registry_id,
            )
            try:
                contender.compare_and_swap(
                    1, sha1, candidate[0], candidate[1], candidate[2]
                )
                return True, ""
            except ValueError as error:
                return False, str(error)

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(race, candidates))
        if [item[0] for item in outcomes].count(True) != 1:
            raise ValueError(
                "backend conformance concurrent CAS did not produce one winner"
            )
        winner_index = next(index for index, item in enumerate(outcomes) if item[0])
        loser_index = 1 - winner_index
        winner = candidates[winner_index]
        loser = candidates[loser_index]
        current2 = backend.current()
        if current2 is None or current2[1] != winner[1] or current2[2] != winner[2]:
            raise ValueError("backend conformance CAS winner is not current")
        expect_value_error(
            lambda: backend.grant(2, loser[2]), "losing history read"
        )
        check(checks, "concurrent-cas", {
            "contenders": 2, "winnerCount": 1,
            "winnerGrantSha256": winner[2],
            "loserGrantSha256": loser[2], "loserHistoryAbsent": True,
        })

        history1_after = backend.grant(1, sha1)
        history2 = backend.grant(2, winner[2])
        if (history1_after[1] != content1 or history1_after[2] != sha1
                or history2[1] != winner[1] or history2[2] != winner[2]):
            raise ValueError("backend conformance immutable history changed")
        check(checks, "immutable-history", {
            "tokens": [1, 2], "token1Sha256": sha1,
            "token2Sha256": winner[2], "byteExact": True,
        })

        report = {
            "schemaVersion": 1, "product": REPORT_PRODUCT, "passed": True,
            "backendId": backend.backend_id, "authorityId": args.authority_id,
            "registryId": args.registry_id,
            "backendConfigSha256": backend.config_sha256,
            "startedAt": started, "completedAt": registry_tool.utc_time(None),
            "finalFencingToken": 2, "finalGrantSha256": winner[2],
            "checks": checks,
        }
        if args.report:
            registry_tool.exclusive_bytes(
                Path(args.report).resolve(), package_tool.json_bytes(report)
            )
        print(
            "PDR_REGISTRY_LEADER_BACKEND_CONFORMANCE_PASS "
            f"backend={backend.backend_id} checks={len(checks)} token=2 "
            f"sha256={winner[2]}"
        )
        return 0
    except backend_tool.BackendCommitUncertainError as error:
        print(
            "PDR_REGISTRY_LEADER_BACKEND_CONFORMANCE_COMMITTED_ERROR: "
            f"{error}",
            file=sys.stderr,
        )
        return 3
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        marker = "COMMITTED_ERROR" if committed else "ERROR"
        print(
            f"PDR_REGISTRY_LEADER_BACKEND_CONFORMANCE_{marker}: {error}",
            file=sys.stderr,
        )
        return 3 if committed else 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--backend-config", required=True)
    result.add_argument("--expected-backend-config-sha256", required=True)
    result.add_argument("--authority-id", required=True)
    result.add_argument("--registry-id", required=True)
    result.add_argument("--confirm-dedicated-empty-scope", action="store_true")
    result.add_argument("--report")
    result.set_defaults(handler=execute_command)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
