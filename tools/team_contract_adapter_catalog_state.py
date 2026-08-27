#!/usr/bin/env python3
"""Atomically activate, inspect and roll back host-local Adapter Catalogs."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import process_file_lease as process_lease
import team_contract_adapter_catalog as catalog_tool
import team_contract_package as package_tool
import team_contract_registry as registry_tool


POINTER_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalogPointer"
STATE_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalogState"
OPERATION_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalogStateOperation"
CURRENT_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalogCurrent"
CURRENT_CHECK_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalogCurrentCheck"
VERIFICATION_PRODUCT = "PocoDDSRuntimeTeamContractAdapterCatalogStateVerification"
MAX_STATES = 100000


def linklike(path: Path) -> bool:
    return path.is_symlink() or bool(
        getattr(path, "is_junction", lambda: False)()
    )


def state_root(value: str | Path, create: bool = False) -> Path:
    supplied = Path(value)
    if linklike(supplied):
        raise ValueError(f"Adapter Catalog state root must not be a link: {supplied}")
    root = supplied.resolve()
    if create:
        root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir() or linklike(root):
        raise FileNotFoundError(f"Adapter Catalog state root is unavailable: {root}")
    return root


def safe_member(root: Path, relative: str, label: str) -> Path:
    parts = package_tool.safe_archive_path(relative).parts
    current = root
    for part in parts:
        current = current / part
        if linklike(current):
            raise ValueError(f"{label} path contains a link or junction: {current}")
    resolved = current.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"{label} escapes the state root") from error
    return resolved


def pointer_path(root: Path) -> Path:
    return safe_member(root, "catalog-state.json", "Adapter Catalog pointer")


def catalog_blob_path(root: Path, digest: str) -> Path:
    return safe_member(
        root, f"catalogs/{digest[:2]}/{digest}.catalog.json",
        "Adapter Catalog blob",
    )


def immutable_state_path(root: Path, generation: int, digest: str) -> Path:
    return safe_member(
        root, f"states/{generation:020d}-{digest}.state.json",
        "Adapter Catalog immutable state",
    )


def exclusive_bytes(path: Path, content: bytes) -> None:
    if linklike(path):
        raise ValueError(f"immutable Adapter Catalog artifact is a link: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        if path.is_file() and not path.is_symlink() and path.read_bytes() == content:
            return
        raise ValueError(f"immutable Adapter Catalog artifact differs: {path}")
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def load_json(path: Path, label: str) -> dict[str, Any]:
    if linklike(path) or not path.is_file():
        raise FileNotFoundError(f"{label} is unavailable or is a link: {path}")
    try:
        document = json.loads(path.read_bytes())
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is invalid JSON") from error
    if not isinstance(document, dict):
        raise ValueError(f"{label} is not a JSON object")
    return document


def valid_optional_int(value: Any) -> bool:
    return value is None or (type(value) is int and value >= 1)


def validate_pointer(pointer: Any) -> None:
    if (not isinstance(pointer, dict) or set(pointer) != {
            "schemaVersion", "product", "catalogId", "generation",
            "stateSha256", "updatedAt",
        } or pointer.get("schemaVersion") != 1
            or pointer.get("product") != POINTER_PRODUCT
            or package_tool.IDENTIFIER.fullmatch(
                str(pointer.get("catalogId", ""))) is None
            or type(pointer.get("generation")) is not int
            or pointer["generation"] < 1
            or package_tool.SHA256.fullmatch(
                str(pointer.get("stateSha256", ""))) is None):
        raise ValueError("Adapter Catalog pointer is malformed")
    package_tool.parse_time(pointer.get("updatedAt"), "Adapter Catalog updatedAt")


def validate_state(state: Any) -> None:
    fields = {
        "schemaVersion", "product", "catalogId", "generation",
        "previousStateSha256", "catalogGeneration", "catalogSha256",
        "action", "operationId", "actor", "reason",
        "rollbackFromGeneration", "rollbackToGeneration", "occurredAt",
    }
    if (not isinstance(state, dict) or set(state) != fields
            or state.get("schemaVersion") != 1
            or state.get("product") != STATE_PRODUCT
            or any(package_tool.IDENTIFIER.fullmatch(
                str(state.get(name, ""))) is None
                for name in ("catalogId", "operationId", "actor"))
            or type(state.get("generation")) is not int
            or not 1 <= state["generation"] <= MAX_STATES
            or type(state.get("catalogGeneration")) is not int
            or state["catalogGeneration"] < 1
            or (state.get("previousStateSha256") is not None
                and package_tool.SHA256.fullmatch(
                    str(state["previousStateSha256"])) is None)
            or package_tool.SHA256.fullmatch(
                str(state.get("catalogSha256", ""))) is None
            or state.get("action") not in {"activate", "rollback"}
            or not isinstance(state.get("reason"), str)
            or not 1 <= len(state["reason"]) <= 512
            or "\r" in state["reason"] or "\n" in state["reason"]
            or not valid_optional_int(state.get("rollbackFromGeneration"))
            or not valid_optional_int(state.get("rollbackToGeneration"))):
        raise ValueError("Adapter Catalog state is malformed")
    package_tool.parse_time(state.get("occurredAt"), "Adapter Catalog occurredAt")
    if state["generation"] == 1:
        if (state["previousStateSha256"] is not None
                or state["action"] != "activate"
                or state["rollbackFromGeneration"] is not None
                or state["rollbackToGeneration"] is not None):
            raise ValueError("initial Adapter Catalog state is malformed")
    elif state["previousStateSha256"] is None:
        raise ValueError("Adapter Catalog state lacks predecessor evidence")
    if state["action"] == "activate" and (
            state["rollbackFromGeneration"] is not None
            or state["rollbackToGeneration"] is not None):
        raise ValueError("Adapter Catalog activation contains rollback evidence")
    if state["action"] == "rollback" and (
            state["rollbackFromGeneration"] != state["generation"] - 1
            or state["rollbackToGeneration"] is None
            or state["rollbackToGeneration"] >= state["rollbackFromGeneration"]):
        raise ValueError("Adapter Catalog rollback evidence is malformed")


class CatalogStateLease(process_lease.ProcessFileLease):
    def __init__(self, root: Path, operation: str, actor: str) -> None:
        super().__init__(
            root / ".adapter-catalog-write.lock",
            root / ".adapter-catalog-write.epoch.json",
            "team-contract-adapter-catalog-writer",
            {"operation": operation, "actor": actor},
        )

    def acquire(self) -> "CatalogStateLease":
        try:
            super().acquire()
            return self
        except process_lease.LeaseBusyError as error:
            raise ValueError("Adapter Catalog state is already being modified") from error


def read_current(root: Path) -> tuple[dict[str, Any], dict[str, Any], Path]:
    pointer = load_json(pointer_path(root), "Adapter Catalog pointer")
    validate_pointer(pointer)
    path = immutable_state_path(
        root, pointer["generation"], pointer["stateSha256"]
    )
    state = load_json(path, "Adapter Catalog current state")
    validate_state(state)
    if (package_tool.sha256_file(path) != pointer["stateSha256"]
            or state["catalogId"] != pointer["catalogId"]
            or state["generation"] != pointer["generation"]
            or state["occurredAt"] != pointer["updatedAt"]):
        raise ValueError("Adapter Catalog pointer does not match immutable state")
    return pointer, state, path


def load_catalog_blob(root: Path, state: dict[str, Any]) \
        -> tuple[dict[str, Any], Path, str]:
    path = catalog_blob_path(root, state["catalogSha256"])
    catalog, loaded_path, digest = catalog_tool.load_catalog(
        path, state["catalogSha256"]
    )
    if (catalog["catalogId"] != state["catalogId"]
            or catalog["generation"] != state["catalogGeneration"]):
        raise ValueError("Adapter Catalog state does not match its catalog blob")
    return catalog, loaded_path, digest


def load_ready_entries(catalog: dict[str, Any]) \
        -> list[tuple[dict[str, Any], dict[str, Any]]]:
    loaded = []
    for entry in catalog_tool.selected_entries(catalog, None):
        manifest, config, _, _ = catalog_tool._load_entry(entry)
        loaded.append((manifest, config))
    return loaded


def verify_chain(root: Path, pointer: dict[str, Any], current: dict[str, Any]) \
        -> list[tuple[str, dict[str, Any]]]:
    generation = pointer["generation"]
    digest = pointer["stateSha256"]
    state = current
    reverse_chain: list[tuple[str, dict[str, Any]]] = []
    while True:
        if len(reverse_chain) >= MAX_STATES:
            raise ValueError("Adapter Catalog state history exceeds capacity")
        path = immutable_state_path(root, generation, digest)
        if package_tool.sha256_file(path) != digest:
            raise ValueError(f"Adapter Catalog state generation {generation} changed")
        validate_state(state)
        if (state["generation"] != generation
                or state["catalogId"] != pointer["catalogId"]):
            raise ValueError("Adapter Catalog state chain identity changed")
        load_catalog_blob(root, state)
        reverse_chain.append((digest, state))
        if generation == 1:
            break
        digest = state["previousStateSha256"]
        generation -= 1
        state = load_json(
            immutable_state_path(root, generation, digest),
            f"Adapter Catalog state generation {generation}",
        )
    chain = list(reversed(reverse_chain))
    operation_ids: set[str] = set()
    history: dict[int, dict[str, Any]] = {}
    for index, (_, state) in enumerate(chain):
        if state["operationId"] in operation_ids:
            raise ValueError("Adapter Catalog operation ID is duplicated")
        operation_ids.add(state["operationId"])
        history[state["generation"]] = state
        if index == 0:
            continue
        previous_digest, previous = chain[index - 1]
        if (state["generation"] != previous["generation"] + 1
                or state["previousStateSha256"] != previous_digest
                or package_tool.parse_time(state["occurredAt"], "occurredAt")
                    < package_tool.parse_time(previous["occurredAt"], "occurredAt")):
            raise ValueError("Adapter Catalog state transition is disconnected")
        if state["action"] == "activate":
            if state["catalogGeneration"] <= previous["catalogGeneration"]:
                raise ValueError("Adapter Catalog activation is not an upgrade")
        else:
            target = history.get(state["rollbackToGeneration"])
            if (target is None
                    or state["rollbackFromGeneration"] != previous["generation"]
                    or state["catalogSha256"] != target["catalogSha256"]
                    or state["catalogGeneration"] != target["catalogGeneration"]):
                raise ValueError("Adapter Catalog rollback target is inconsistent")
    return chain


def commit(root: Path, previous: dict[str, Any] | None,
           state: dict[str, Any], lease: CatalogStateLease) \
        -> tuple[dict[str, Any], str]:
    validate_state(state)
    content = package_tool.json_bytes(state)
    digest = package_tool.sha256_bytes(content)
    exclusive_bytes(immutable_state_path(root, state["generation"], digest), content)
    if previous is not None \
            and state["previousStateSha256"] != previous["stateSha256"]:
        raise ValueError("new Adapter Catalog state does not extend current pointer")
    pointer = {
        "schemaVersion": 1, "product": POINTER_PRODUCT,
        "catalogId": state["catalogId"], "generation": state["generation"],
        "stateSha256": digest, "updatedAt": state["occurredAt"],
    }
    lease.assert_current()
    package_tool.write_json(pointer_path(root), pointer)
    return pointer, digest


def validate_operator(args: argparse.Namespace) -> None:
    if (package_tool.IDENTIFIER.fullmatch(str(args.operation_id)) is None
            or package_tool.IDENTIFIER.fullmatch(str(args.actor)) is None
            or not isinstance(args.reason, str)
            or not 1 <= len(args.reason) <= 512
            or "\r" in args.reason or "\n" in args.reason):
        raise ValueError("Adapter Catalog operation identity is malformed")


def operation_matches(state: dict[str, Any], args: argparse.Namespace,
                      action: str, catalog_sha: str | None = None) -> bool:
    return (state["action"] == action
            and state["actor"] == args.actor
            and state["reason"] == args.reason
            and state["generation"] == args.expected_generation + 1
            and (action != "activate" or state["catalogSha256"] == catalog_sha)
            and (action != "rollback"
                 or state["rollbackToGeneration"] == args.to_generation))


def operation_report(pointer: dict[str, Any], state: dict[str, Any],
                     state_sha: str, replay: bool) -> dict[str, Any]:
    return {
        "schemaVersion": 1, "product": OPERATION_PRODUCT, "passed": True,
        "action": state["action"], "catalogId": state["catalogId"],
        "generation": state["generation"],
        "currentGeneration": pointer["generation"],
        "catalogGeneration": state["catalogGeneration"],
        "catalogSha256": state["catalogSha256"],
        "stateSha256": state_sha,
        "previousStateSha256": state["previousStateSha256"],
        "operationId": state["operationId"], "actor": state["actor"],
        "reason": state["reason"],
        "rollbackFromGeneration": state["rollbackFromGeneration"],
        "rollbackToGeneration": state["rollbackToGeneration"],
        "occurredAt": state["occurredAt"], "idempotentReplay": replay,
    }


def write_report(args: argparse.Namespace, report: dict[str, Any]) -> None:
    if getattr(args, "report", None):
        package_tool.write_json(Path(args.report).resolve(), report)


def activate_command(args: argparse.Namespace) -> int:
    try:
        validate_operator(args)
        if package_tool.SHA256.fullmatch(
                str(args.expected_catalog_sha256)) is None:
            raise ValueError("Adapter Catalog expected digest is malformed")
        candidate_sha = args.expected_catalog_sha256
        root = state_root(args.state_dir, create=True)
        with CatalogStateLease(root, "activate", args.actor) as lease:
            if pointer_path(root).exists():
                pointer, current, _ = read_current(root)
                chain = verify_chain(root, pointer, current)
                for state_sha, state in chain:
                    if state["operationId"] == args.operation_id:
                        if not operation_matches(
                                state, args, "activate", candidate_sha):
                            raise ValueError("Adapter Catalog operation ID collision")
                        report = operation_report(pointer, state, state_sha, True)
                        write_report(args, report)
                        print(
                            "PDR_ADAPTER_CATALOG_ACTIVATE_PASS "
                            f"catalog={state['catalogId']} "
                            f"generation={state['generation']} replay=1"
                        )
                        return 0
                if pointer["generation"] != args.expected_generation:
                    raise ValueError(
                        "Adapter Catalog generation changed: "
                        f"expected={args.expected_generation} "
                        f"actual={pointer['generation']}"
                    )
            else:
                if args.expected_generation != 0:
                    raise ValueError("initial Adapter Catalog generation must be zero")
                pointer = None
                current = None
            candidate, candidate_path, candidate_sha = catalog_tool.load_catalog(
                args.catalog, candidate_sha
            )
            load_ready_entries(candidate)
            if pointer is not None:
                if candidate["catalogId"] != current["catalogId"]:
                    raise ValueError("Adapter Catalog identity changed")
                if candidate["generation"] <= current["catalogGeneration"]:
                    raise ValueError("Adapter Catalog candidate is not an upgrade")
                generation = pointer["generation"] + 1
                previous_sha = pointer["stateSha256"]
                previous_pointer = pointer
            else:
                generation = 1
                previous_sha = None
                previous_pointer = None
            content = candidate_path.read_bytes()
            if package_tool.sha256_bytes(content) != candidate_sha:
                raise ValueError("Adapter Catalog candidate changed during activation")
            blob = catalog_blob_path(root, candidate_sha)
            exclusive_bytes(blob, content)
            stored, _, _ = catalog_tool.load_catalog(blob, candidate_sha)
            load_ready_entries(stored)
            occurred_at = registry_tool.utc_time(None)
            state = {
                "schemaVersion": 1, "product": STATE_PRODUCT,
                "catalogId": candidate["catalogId"], "generation": generation,
                "previousStateSha256": previous_sha,
                "catalogGeneration": candidate["generation"],
                "catalogSha256": candidate_sha, "action": "activate",
                "operationId": args.operation_id, "actor": args.actor,
                "reason": args.reason, "rollbackFromGeneration": None,
                "rollbackToGeneration": None, "occurredAt": occurred_at,
            }
            pointer, state_sha = commit(root, previous_pointer, state, lease)
            report = operation_report(pointer, state, state_sha, False)
            write_report(args, report)
        print(
            "PDR_ADAPTER_CATALOG_ACTIVATE_PASS "
            f"catalog={candidate['catalogId']} generation={generation} replay=0"
        )
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_ADAPTER_CATALOG_ACTIVATE_ERROR: {error}", file=sys.stderr)
        return 2


def rollback_command(args: argparse.Namespace) -> int:
    try:
        validate_operator(args)
        root = state_root(args.state_dir)
        with CatalogStateLease(root, "rollback", args.actor) as lease:
            pointer, current, _ = read_current(root)
            chain = verify_chain(root, pointer, current)
            for state_sha, state in chain:
                if state["operationId"] == args.operation_id:
                    if not operation_matches(state, args, "rollback"):
                        raise ValueError("Adapter Catalog operation ID collision")
                    report = operation_report(pointer, state, state_sha, True)
                    write_report(args, report)
                    print(
                        "PDR_ADAPTER_CATALOG_ROLLBACK_PASS "
                        f"catalog={state['catalogId']} "
                        f"generation={state['generation']} replay=1"
                    )
                    return 0
            if pointer["generation"] != args.expected_generation:
                raise ValueError(
                    "Adapter Catalog generation changed: "
                    f"expected={args.expected_generation} "
                    f"actual={pointer['generation']}"
                )
            if not 1 <= args.to_generation < pointer["generation"]:
                raise ValueError("rollback target must be an earlier generation")
            target_matches = [
                (digest, state) for digest, state in chain
                if state["generation"] == args.to_generation
            ]
            if len(target_matches) != 1:
                raise ValueError("rollback target is absent from verified history")
            _, target = target_matches[0]
            catalog, _, _ = load_catalog_blob(root, target)
            load_ready_entries(catalog)
            generation = pointer["generation"] + 1
            occurred_at = registry_tool.utc_time(None)
            state = {
                "schemaVersion": 1, "product": STATE_PRODUCT,
                "catalogId": current["catalogId"], "generation": generation,
                "previousStateSha256": pointer["stateSha256"],
                "catalogGeneration": target["catalogGeneration"],
                "catalogSha256": target["catalogSha256"], "action": "rollback",
                "operationId": args.operation_id, "actor": args.actor,
                "reason": args.reason,
                "rollbackFromGeneration": pointer["generation"],
                "rollbackToGeneration": args.to_generation,
                "occurredAt": occurred_at,
            }
            new_pointer, state_sha = commit(root, pointer, state, lease)
            report = operation_report(new_pointer, state, state_sha, False)
            write_report(args, report)
        print(
            "PDR_ADAPTER_CATALOG_ROLLBACK_PASS "
            f"catalog={state['catalogId']} generation={generation} "
            f"to={args.to_generation} replay=0"
        )
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_ADAPTER_CATALOG_ROLLBACK_ERROR: {error}", file=sys.stderr)
        return 2


def current_context(root: Path) -> tuple[
        dict[str, Any], dict[str, Any], str, dict[str, Any],
        list[tuple[dict[str, Any], dict[str, Any]]]]:
    pointer, state, _ = read_current(root)
    verify_chain(root, pointer, state)
    catalog, _, _ = load_catalog_blob(root, state)
    entries = load_ready_entries(catalog)
    return pointer, state, pointer["stateSha256"], catalog, entries


def assert_current_snapshot(root: Path, pointer: dict[str, Any],
                            state_sha: str, catalog_sha: str) -> None:
    after, after_state, _ = read_current(root)
    if (after["generation"] != pointer["generation"]
            or after["stateSha256"] != state_sha
            or after_state["catalogSha256"] != catalog_sha):
        raise ValueError("Adapter Catalog changed during snapshot validation")


def current_command(args: argparse.Namespace) -> int:
    try:
        root = state_root(args.state_dir)
        pointer, state, state_sha, _, entries = current_context(root)
        adapters = [{
            "adapterId": manifest["adapterId"],
            "adapterType": manifest["adapterType"],
            "manifestId": manifest["manifestId"],
            "revision": manifest["revision"], "owner": manifest["owner"],
            "protocolId": manifest["protocolId"],
            "configSha256": manifest["configSha256"],
        } for manifest, _ in entries]
        report = {
            "schemaVersion": 1, "product": CURRENT_PRODUCT,
            "catalogId": state["catalogId"],
            "generation": pointer["generation"],
            "catalogGeneration": state["catalogGeneration"],
            "catalogSha256": state["catalogSha256"],
            "stateSha256": state_sha, "action": state["action"],
            "operationId": state["operationId"], "actor": state["actor"],
            "occurredAt": state["occurredAt"], "adapters": adapters,
        }
        assert_current_snapshot(
            root, pointer, state_sha, state["catalogSha256"]
        )
        write_report(args, report)
        print(
            "PDR_ADAPTER_CATALOG_CURRENT_PASS "
            f"catalog={state['catalogId']} generation={pointer['generation']} "
            f"adapters={len(adapters)}"
        )
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_ADAPTER_CATALOG_CURRENT_ERROR: {error}", file=sys.stderr)
        return 2


def current_check_command(args: argparse.Namespace) -> int:
    try:
        root = state_root(args.state_dir)
        pointer, state, state_sha, _, entries = current_context(root)
        adapters = [catalog_tool.probe(manifest, config)
                    for manifest, config in entries]
        try:
            assert_current_snapshot(
                root, pointer, state_sha, state["catalogSha256"]
            )
        except ValueError as error:
            raise ValueError(
                "Adapter Catalog changed during capability check"
            ) from error
        report = {
            "schemaVersion": 1, "product": CURRENT_CHECK_PRODUCT,
            "passed": True, "catalogId": state["catalogId"],
            "generation": pointer["generation"],
            "catalogGeneration": state["catalogGeneration"],
            "catalogSha256": state["catalogSha256"],
            "stateSha256": state_sha, "adapters": adapters,
            "checkedAt": registry_tool.utc_time(None),
        }
        write_report(args, report)
        print(
            "PDR_ADAPTER_CATALOG_CURRENT_CHECK_PASS "
            f"catalog={state['catalogId']} generation={pointer['generation']} "
            f"adapters={len(adapters)}"
        )
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_ADAPTER_CATALOG_CURRENT_CHECK_ERROR: {error}", file=sys.stderr)
        return 2


def verify_command(args: argparse.Namespace) -> int:
    try:
        root = state_root(args.state_dir)
        pointer, state, _ = read_current(root)
        chain = verify_chain(root, pointer, state)
        catalog, _, _ = load_catalog_blob(root, state)
        entries = load_ready_entries(catalog)
        report = {
            "schemaVersion": 1, "product": VERIFICATION_PRODUCT,
            "passed": True, "catalogId": state["catalogId"],
            "generation": pointer["generation"],
            "stateSha256": pointer["stateSha256"],
            "catalogGeneration": state["catalogGeneration"],
            "catalogSha256": state["catalogSha256"],
            "stateCount": len(chain),
            "catalogBlobCount": len({item[1]["catalogSha256"] for item in chain}),
            "adapterCount": len(entries), "verifiedAt": registry_tool.utc_time(None),
        }
        assert_current_snapshot(
            root, pointer, pointer["stateSha256"], state["catalogSha256"]
        )
        write_report(args, report)
        print(
            "PDR_ADAPTER_CATALOG_STATE_VERIFY_PASS "
            f"catalog={state['catalogId']} generation={pointer['generation']} "
            f"states={len(chain)}"
        )
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError,
            json.JSONDecodeError) as error:
        print(f"PDR_ADAPTER_CATALOG_STATE_VERIFY_ERROR: {error}", file=sys.stderr)
        return 2


def add_state_argument(command: argparse.ArgumentParser) -> None:
    command.add_argument("--state-dir", required=True)
    command.add_argument("--report")


def add_operator_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--expected-generation", type=int, required=True)
    command.add_argument("--operation-id", required=True)
    command.add_argument("--actor", required=True)
    command.add_argument("--reason", required=True)
    add_state_argument(command)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="operation", required=True)
    activate = commands.add_parser("activate")
    activate.add_argument("--catalog", required=True)
    activate.add_argument("--expected-catalog-sha256", required=True)
    add_operator_arguments(activate)
    activate.set_defaults(handler=activate_command)
    rollback = commands.add_parser("rollback")
    rollback.add_argument("--to-generation", type=int, required=True)
    add_operator_arguments(rollback)
    rollback.set_defaults(handler=rollback_command)
    for name, handler in (
            ("current", current_command),
            ("current-check", current_check_command),
            ("verify", verify_command)):
        command = commands.add_parser(name)
        add_state_argument(command)
        command.set_defaults(handler=handler)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
