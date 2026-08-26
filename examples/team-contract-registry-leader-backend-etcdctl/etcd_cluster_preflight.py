#!/usr/bin/env python3
"""Read-only topology and health preflight for a pinned etcd adapter config."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from etcd_backend_adapter import EtcdStore, load_config


PRODUCT = "PocoDDSRuntimeTeamContractRegistryLeaderEtcdPreflight"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def positive_integer(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"etcd endpoint status has invalid {label}")
    return value


def validate_status(document: Any, endpoints: list[str]) \
        -> tuple[int, list[int], int, int]:
    if not isinstance(document, list) or len(document) != len(endpoints):
        raise ValueError("etcd endpoint status does not cover configured endpoints")
    observed_endpoints: list[str] = []
    cluster_ids: list[int] = []
    member_ids: list[int] = []
    leaders: list[int] = []
    minimum_revision: int | None = None
    for item in document:
        if (not isinstance(item, dict) or set(item) != {"Endpoint", "Status"}
                or not isinstance(item["Endpoint"], str)
                or not isinstance(item["Status"], dict)):
            raise ValueError("etcd endpoint status entry is malformed")
        observed_endpoints.append(item["Endpoint"])
        status = item["Status"]
        header = status.get("header")
        if not isinstance(header, dict):
            raise ValueError("etcd endpoint status header is missing")
        cluster_ids.append(positive_integer(header.get("cluster_id"), "cluster ID"))
        member_ids.append(positive_integer(header.get("member_id"), "member ID"))
        leaders.append(positive_integer(status.get("leader"), "leader ID"))
        revision = positive_integer(header.get("revision"), "revision")
        minimum_revision = revision if minimum_revision is None \
            else min(minimum_revision, revision)
        raft_term = positive_integer(status.get("raftTerm"), "Raft term")
        raft_index = positive_integer(status.get("raftIndex"), "Raft index")
        applied = positive_integer(
            status.get("raftAppliedIndex"), "Raft applied index"
        )
        if applied > raft_index or header.get("raft_term") not in (None, raft_term):
            raise ValueError("etcd endpoint Raft status is inconsistent")
        if status.get("isLearner", False) is not False:
            raise ValueError("etcd leader backend endpoint is a learner")
        if status.get("errors") not in (None, [], ""):
            raise ValueError("etcd endpoint reports cluster errors")
        if not isinstance(status.get("version"), str) \
                or not status["version"].startswith("3."):
            raise ValueError("etcd endpoint version is unsupported")
    if set(observed_endpoints) != set(endpoints):
        raise ValueError("etcd endpoint status returned an unexpected endpoint")
    if len(set(cluster_ids)) != 1:
        raise ValueError("etcd endpoints disagree on cluster ID")
    if len(set(member_ids)) != len(member_ids):
        raise ValueError("etcd endpoint member IDs are not unique")
    if len(set(leaders)) != 1 or leaders[0] not in set(member_ids):
        raise ValueError("etcd endpoints disagree on an elected member leader")
    assert minimum_revision is not None
    return cluster_ids[0], member_ids, leaders[0], minimum_revision


def execute(args: argparse.Namespace) -> int:
    try:
        config, config_path = load_config(
            args.config, args.expected_config_sha256
        )
        started = utc_now()
        store = EtcdStore(config)
        health = store.command("endpoint", "--cluster", "health")
        health_text = health.decode("utf-8", errors="strict")
        if (health_text.count("is healthy") != len(config["endpoints"])
                or any(item not in health_text for item in config["endpoints"])):
            raise ValueError("etcd endpoint health does not cover every endpoint")
        status_bytes = store.command(
            "--write-out=json", "endpoint", "--cluster", "status"
        )
        try:
            status = json.loads(status_bytes)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("etcd endpoint status is invalid JSON") from error
        cluster_id, member_ids, leader_id, revision = validate_status(
            status, config["endpoints"]
        )
        # A linearizable read under the configured prefix proves TLS identity and
        # read RBAC without mutating the authority namespace.
        sentinel = f"{config['keyPrefix']}/_preflight/absent"
        if store.get(sentinel) is not None:
            raise ValueError("etcd preflight sentinel key is unexpectedly occupied")
        report = {
            "schemaVersion": 1, "product": PRODUCT, "passed": True,
            "adapterId": config["adapterId"],
            "adapterConfigPath": str(config_path),
            "adapterConfigSha256": args.expected_config_sha256,
            "etcdctlVersion": config["etcdctlVersion"],
            "keyPrefix": config["keyPrefix"], "endpoints": config["endpoints"],
            "clusterId": str(cluster_id),
            "memberIds": [str(item) for item in member_ids],
            "leaderId": str(leader_id), "minimumRevision": revision,
            "checks": {
                "allEndpointsHealthy": True, "singleCluster": True,
                "uniqueMembers": True, "singleLeader": True,
                "raftApplied": True, "linearizableRead": True,
            },
            "startedAt": started, "completedAt": utc_now(),
        }
        if args.report:
            output = Path(args.report)
            if not output.is_absolute():
                raise ValueError("etcd preflight report path must be absolute")
            output = output.resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("xb") as stream:
                stream.write((json.dumps(report, indent=2, sort_keys=True)
                              + "\n").encode("utf-8"))
        print(
            "PDR_LEADER_ETCD_PREFLIGHT_PASS "
            f"adapter={config['adapterId']} endpoints={len(config['endpoints'])} "
            f"members={len(member_ids)} cluster={cluster_id} leader={leader_id} "
            f"revision={revision}"
        )
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_LEADER_ETCD_PREFLIGHT_ERROR: {error}", file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--config", required=True)
    result.add_argument("--expected-config-sha256", required=True)
    result.add_argument("--report")
    result.set_defaults(handler=execute)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
