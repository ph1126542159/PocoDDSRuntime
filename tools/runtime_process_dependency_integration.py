#!/usr/bin/env python3
"""Validate waiting, satisfied and reverse-shutdown process DAG API states."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from runtime_smoke import free_port, probe, stop_tree, write_overlay


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--bundle-repository", required=True, type=Path)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=15.0)
    return parser.parse_args()


def copy_required_bundles(source: Path, destination: Path) -> None:
    prefixes = (
        "osp.core_", "osp.web_", "osp.web.server_",
        "poco.net_", "pdr.platform.health_", "pdr.platform.processGraph_",
    )
    destination.mkdir(parents=True)
    for prefix in prefixes:
        matches = sorted(source.glob(prefix + "*.bndl"))
        if len(matches) != 1:
            raise RuntimeError(
                f"expected one bundle matching {prefix}*.bndl, found {len(matches)}"
            )
        shutil.copy2(matches[0], destination / matches[0].name)


def write_subprocess_configuration(
    destination: Path, process_root_name: str, event_path: Path
) -> None:
    event = event_path.as_posix()
    entries = [
        (0, "api-worker", "worker", "worker.ready", 50, "api-foundation"),
        (1, "api-foundation", "foundation", "foundation.ready", 2500, ""),
    ]
    lines = [
        "subprocess.count = 2",
        "subprocess.supervisionIntervalMilliseconds = 50",
    ]
    for index, name, directory, readiness, delay, dependency in entries:
        prefix = f"subprocess.{index}."
        relative_directory = f"processes/{process_root_name}/{directory}"
        lines.extend([
            f"{prefix}enabled = true",
            f"{prefix}name = {name}",
            f"{prefix}location = local",
            f"{prefix}required = true",
            f"{prefix}dependency.count = {1 if dependency else 0}",
        ])
        if dependency:
            lines.append(f"{prefix}dependency.0 = {dependency}")
        lines.extend([
            f"{prefix}path = {relative_directory}/dependency-fixture.exe",
            f"{prefix}workingDirectory = {relative_directory}",
            f"{prefix}restartPolicy = never",
            f"{prefix}readinessFile = {relative_directory}/{readiness}",
            f"{prefix}readinessTimeoutMilliseconds = 5000",
            f"{prefix}argument.count = 5",
            f"{prefix}argument.0 = --dependency-child",
            f"{prefix}argument.1 = {name}",
            f"{prefix}argument.2 = {event}",
            f"{prefix}argument.3 = {readiness}",
            f"{prefix}argument.4 = {delay}",
        ])
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def edge(graph: dict[str, object]) -> dict[str, object]:
    edges = graph.get("edges", [])
    if not isinstance(edges, list) or len(edges) != 1 or not isinstance(edges[0], dict):
        raise RuntimeError("process dependency graph did not expose exactly one edge")
    return edges[0]


def nodes_by_name(graph: dict[str, object]) -> dict[str, dict[str, object]]:
    nodes = graph.get("nodes", [])
    if not isinstance(nodes, list):
        raise RuntimeError("process dependency graph nodes are invalid")
    return {
        str(node.get("name")): node
        for node in nodes if isinstance(node, dict)
    }


def main() -> int:
    args = parse_args()
    runtime = args.runtime.resolve()
    base_config = args.config.resolve()
    fixture = args.fixture.resolve()
    bundle_repository = args.bundle_repository.resolve()
    report_path = args.report.resolve()
    log_path = args.log.resolve()
    for required in (runtime, base_config, fixture):
        if not required.is_file():
            raise SystemExit(f"required file not found: {required}")
    if not bundle_repository.is_dir():
        raise SystemExit(f"bundle repository not found: {bundle_repository}")

    runtime_root = runtime.parent
    processes_root = runtime_root / "processes"
    processes_root.mkdir(parents=True, exist_ok=True)
    process_workspace = Path(tempfile.mkdtemp(
        prefix="pdr-dependency-api-", dir=processes_root
    )).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(
        prefix="process-dependency-api-", dir=report_path.parent
    )).resolve()
    result: dict[str, object] = {
        "schemaVersion": 1,
        "passed": False,
        "runtime": str(runtime),
    }
    process: subprocess.Popen[bytes] | None = None
    log_stream = None
    try:
        foundation_directory = process_workspace / "foundation"
        worker_directory = process_workspace / "worker"
        foundation_directory.mkdir()
        worker_directory.mkdir()
        shutil.copy2(fixture, foundation_directory / "dependency-fixture.exe")
        shutil.copy2(fixture, worker_directory / "dependency-fixture.exe")
        minimal_repository = work / "bundles"
        copy_required_bundles(bundle_repository, minimal_repository)
        subprocess_config = work / "pdr-subprocesses.properties"
        write_subprocess_configuration(
            subprocess_config, process_workspace.name, work / "events.log"
        )

        port = free_port("127.0.0.1")
        overlay = work / "pdr-runtime.properties"
        write_overlay(base_config, overlay, "127.0.0.1", port, {
            "osp.bundleRepository": minimal_repository.as_posix() + "/",
            "pdr.subprocess.configuration": subprocess_config.as_posix(),
        })
        environment = os.environ.copy()
        environment["PATH"] = str(runtime_root) + os.pathsep + environment.get("PATH", "")
        option = f"/config-file={overlay}" if os.name == "nt" else f"--config-file={overlay}"
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_stream = log_path.open("wb")
        process = subprocess.Popen(
            [str(runtime), option], cwd=work, env=environment,
            stdout=log_stream, stderr=subprocess.STDOUT,
            creationflags=creationflags, start_new_session=os.name != "nt",
        )
        result["pid"] = process.pid
        result["port"] = port
        deadline = time.monotonic() + args.timeout
        waiting_graph: dict[str, object] | None = None
        running_graph: dict[str, object] | None = None
        url = f"http://127.0.0.1:{port}/api/v1/process-dependencies"
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"Runtime exited with code {process.returncode}")
            try:
                status, body = probe(url, 0.5)
                if status != 200:
                    time.sleep(0.05)
                    continue
                graph = json.loads(body)
                by_name = nodes_by_name(graph)
                if set(by_name) != {"api-foundation", "api-worker"}:
                    time.sleep(0.05)
                    continue
                if (by_name["api-foundation"].get("state") == "starting" and
                        by_name["api-worker"].get("state") == "waiting-dependency"):
                    waiting_graph = graph
                if (by_name["api-foundation"].get("state") == "running" and
                        by_name["api-worker"].get("state") == "running"):
                    running_graph = graph
                    break
            except (OSError, ValueError):
                pass
            time.sleep(0.05)
        if waiting_graph is None:
            raise RuntimeError("API did not expose the dependency-waiting state")
        if running_graph is None:
            raise RuntimeError("API did not converge to the satisfied dependency state")

        persistence = running_graph.get("desiredStatePersistence")
        if (not isinstance(persistence, dict) or
                persistence.get("enabled") is not False or
                persistence.get("healthy") is not True or
                persistence.get("leaseHeld") is not False or
                persistence.get("recoveredFromPrevious") is not False or
                persistence.get("primaryValid") is not True or
                persistence.get("previousAvailable") is not False or
                persistence.get("previousValid") is not False or
                persistence.get("generation") != 0 or
                persistence.get("lastIntegrityCheckEpochMicroseconds") != 0 or
                persistence.get("state") != "disabled" or
                persistence.get("integrityState") != "disabled"):
            raise RuntimeError("disabled desired-state persistence status is incorrect")

        waiting_nodes = nodes_by_name(waiting_graph)
        waiting_edge = edge(waiting_graph)
        worker_blockers = waiting_nodes["api-worker"].get("blockedBy", [])
        if (waiting_graph.get("startupOrder") != ["api-foundation", "api-worker"] or
                waiting_graph.get("shutdownOrder") != ["api-worker", "api-foundation"] or
                waiting_edge.get("state") != "waiting" or
                waiting_edge.get("reason") != "dependency-starting" or
                not isinstance(worker_blockers, list) or len(worker_blockers) != 1 or
                worker_blockers[0].get("name") != "api-foundation" or
                worker_blockers[0].get("reason") != "dependency-starting"):
            raise RuntimeError("waiting dependency API contract is incorrect")
        running_edge = edge(running_graph)
        if (running_edge.get("state") != "satisfied" or
                running_edge.get("reason") != "none" or
                nodes_by_name(running_graph)["api-worker"].get("blockedBy") != []):
            raise RuntimeError("satisfied dependency API contract is incorrect")

        impact_base = f"http://127.0.0.1:{port}/api/v1/process-dependencies/impact"
        stop_status, stop_body = probe(
            impact_base + "?target=api-foundation&action=stop", 0.5)
        start_status, start_body = probe(
            impact_base + "?target=api-worker&action=start", 0.5)
        invalid_status, invalid_body = probe(
            impact_base + "?target=api-worker&target=duplicate&action=start", 0.5)
        if stop_status != 200 or start_status != 200:
            raise RuntimeError("process lifecycle impact endpoint did not return HTTP 200")
        stop_impact = json.loads(stop_body)
        start_impact = json.loads(start_body)
        invalid_impact = json.loads(invalid_body)
        if (stop_impact.get("generation") != running_graph.get("generation") or
                stop_impact.get("target") != "api-foundation" or
                stop_impact.get("action") != "stop" or
                stop_impact.get("allowed") is not True or
                stop_impact.get("requiresConfirmation") is not True or
                stop_impact.get("affectedDependents") != ["api-worker"] or
                stop_impact.get("stopOrder") != ["api-worker", "api-foundation"] or
                stop_impact.get("startOrder") != []):
            raise RuntimeError("stop impact plan contract is incorrect")
        if (start_impact.get("target") != "api-worker" or
                start_impact.get("allowed") is not True or
                start_impact.get("noOp") is not True or
                start_impact.get("prerequisites") != ["api-foundation"] or
                start_impact.get("startOrder") != ["api-foundation", "api-worker"]):
            raise RuntimeError("start impact plan contract is incorrect")
        if (invalid_status != 400 or
                invalid_impact.get("code") != "PDR-PROCESS-IMPACT-QUERY_INVALID"):
            raise RuntimeError("duplicate impact query was not rejected")

        after_status, after_body = probe(url, 0.5)
        after_graph = json.loads(after_body) if after_status == 200 else {}
        before_nodes = nodes_by_name(running_graph)
        after_nodes = nodes_by_name(after_graph)
        if (set(after_nodes) != set(before_nodes) or
                any(after_nodes[name].get("state") != "running" or
                    after_nodes[name].get("processId") != before_nodes[name].get("processId")
                    for name in before_nodes)):
            raise RuntimeError("impact preflight changed managed process state")
        result["waiting"] = waiting_graph
        result["running"] = running_graph
        result["stopImpact"] = stop_impact
        result["startImpact"] = start_impact
        result["impactSideEffectFree"] = True
        result["passed"] = True
    except Exception as error:
        result["error"] = str(error)
    finally:
        if process is not None:
            result["shutdown"] = stop_tree(process, 10.0)
            if not result["shutdown"].get("clean", False):
                result["passed"] = False
                result["shutdownError"] = "Runtime did not stop cleanly"
        if log_stream is not None:
            log_stream.close()
        if log_path.is_file():
            log_content = log_path.read_text(encoding="utf-8", errors="replace")
            worker_stop = log_content.find("Stopping subprocess 'api-worker'")
            foundation_stop = log_content.find("Stopping subprocess 'api-foundation'")
            result["reverseShutdownObserved"] = (
                worker_stop >= 0 and foundation_stop > worker_stop
            )
            if not result["reverseShutdownObserved"]:
                result["passed"] = False
                result["shutdownOrderError"] = "reverse dependency shutdown was not observed"
        if process_workspace.parent != processes_root.resolve():
            raise RuntimeError("refusing to remove unexpected process fixture path")
        shutil.rmtree(process_workspace, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)
        report_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8", newline="\n",
        )

    if result["passed"]:
        print("PROCESS_DEPENDENCY_API_PASS waiting=1 satisfied=1 blockedReason=1 impact=1 sideEffectFree=1 reverseShutdown=1")
        return 0
    print(f"PROCESS_DEPENDENCY_API_FAIL {result.get('error', result.get('shutdownError', 'validation failed'))}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
