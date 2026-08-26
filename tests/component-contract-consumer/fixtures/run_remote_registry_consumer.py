#!/usr/bin/env python3
"""Resolve a production channel through the installed remote Registry SDK."""

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def wait_server(process: subprocess.Popen[str], port: int) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=1)
            raise RuntimeError(f"remote Registry exited:\n{stdout}\n{stderr}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("remote Registry did not become ready")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True)
    parser.add_argument("--pdr", type=Path, required=True)
    parser.add_argument("--remote-tool", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--access-policy", type=Path, required=True)
    parser.add_argument("--access-policy-sha256", required=True)
    parser.add_argument("--trust-policy", type=Path, required=True)
    parser.add_argument("--trust-policy-sha256", required=True)
    parser.add_argument("--runner-policy", type=Path, required=True)
    parser.add_argument("--runner-policy-sha256", required=True)
    parser.add_argument("--gate-policy", type=Path, required=True)
    parser.add_argument("--gate-policy-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--control", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.pdr, args.remote_tool, args.registry, args.access_policy,
                 args.trust_policy, args.runner_policy, args.gate_policy):
        if not path.exists():
            raise FileNotFoundError(path)
    port = free_port()
    server = subprocess.Popen([
        args.python, str(args.remote_tool), "serve", "--registry", str(args.registry),
        "--bind", "127.0.0.1", "--port", str(port), "--allow-insecure-loopback",
        "--quiet", "--control-directory", str(args.control),
        "--access-policy", str(args.access_policy),
        "--expected-access-policy-id", "component-consumer-registry-remote-access",
        "--expected-access-policy-sha256", args.access_policy_sha256,
        "--trust-policy", str(args.trust_policy),
        "--expected-trust-policy-id", "component-consumer-team-contracts",
        "--expected-trust-policy-sha256", args.trust_policy_sha256,
        "--runner-trust-policy", str(args.runner_policy),
        "--expected-runner-trust-policy-id", "component-consumer-ci-runners",
        "--expected-runner-trust-policy-sha256", args.runner_policy_sha256,
        "--gate-authorization-policy", str(args.gate_policy),
        "--expected-gate-authorization-policy-id", "component-consumer-gate-authorizers",
        "--expected-gate-authorization-policy-sha256", args.gate_policy_sha256,
        "--verification-time", "2026-08-25T12:30:00Z",
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        wait_server(server, port)
        environment = dict(os.environ)
        environment["PDR_TEST_REMOTE_CONSUMER_TOKEN"] = \
            "component-consumer-reader-token-0123456789abcdef-2026"
        result = subprocess.run([
            args.python, str(args.pdr), "contract-package", "registry-remote-resolve",
            "--url", f"http://127.0.0.1:{port}",
            "--registry-id", "component-consumer-contracts",
            "--request-id", "component-consumer-production-resolve-0001",
            "--token-environment", "PDR_TEST_REMOTE_CONSUMER_TOKEN",
            "--allow-insecure-loopback", "--channel", "production",
            "--output", str(args.output), "--report", str(args.report),
        ], check=False, capture_output=True, text=True, env=environment)
        if result.returncode != 0:
            sys.stderr.write(result.stdout + result.stderr)
            return result.returncode
        audit = subprocess.run([
            args.python, str(args.pdr), "contract-package",
            "registry-remote-audit-verify",
            "--url", f"http://127.0.0.1:{port}",
            "--registry-id", "component-consumer-contracts",
            "--token-environment", "PDR_TEST_REMOTE_CONSUMER_TOKEN",
            "--allow-insecure-loopback",
        ], check=False, capture_output=True, text=True, env=environment)
        if audit.returncode != 0:
            sys.stderr.write(audit.stdout + audit.stderr)
            return audit.returncode
        capacity = subprocess.run([
            args.python, str(args.pdr), "contract-package",
            "registry-remote-capacity",
            "--url", f"http://127.0.0.1:{port}",
            "--registry-id", "component-consumer-contracts",
            "--token-environment", "PDR_TEST_REMOTE_CONSUMER_TOKEN",
            "--allow-insecure-loopback",
        ], check=False, capture_output=True, text=True, env=environment)
        if capacity.returncode != 0 or "accepting=true" not in capacity.stdout:
            sys.stderr.write(capacity.stdout + capacity.stderr)
            return capacity.returncode or 2
        lease_status = subprocess.run([
            args.python, str(args.pdr), "contract-package",
            "registry-remote-lease-status",
            "--url", f"http://127.0.0.1:{port}",
            "--registry-id", "component-consumer-contracts",
            "--token-environment", "PDR_TEST_REMOTE_CONSUMER_TOKEN",
            "--allow-insecure-loopback",
        ], check=False, capture_output=True, text=True, env=environment)
        if lease_status.returncode != 0 or "accepting=true" not in lease_status.stdout:
            sys.stderr.write(lease_status.stdout + lease_status.stderr)
            return lease_status.returncode or 2
        if not args.report.is_file() or not args.output.is_dir():
            raise RuntimeError("installed remote Consumer produced no durable evidence")
        evidence = json.loads(args.report.read_bytes())
        serialized = json.dumps(evidence, ensure_ascii=False)
        if (str(args.registry.resolve()) in serialized
                or "pdr-remote-registry-" in serialized):
            raise RuntimeError("remote Consumer evidence exposed a server filesystem path")
        print("PDR_TEAM_CONTRACT_REMOTE_CONSUMER_PASS channel=production")
        return 0
    finally:
        server.terminate()
        try:
            server.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.communicate(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
