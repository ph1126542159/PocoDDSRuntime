#!/usr/bin/env python3
"""Exercise a packaged Runtime upgrade, live validation and rollback transaction."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def run(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=cwd, capture_output=True, text=True, check=False
    )


def write_report(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2), encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cmake", required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--config", default="Release")
    parser.add_argument("--version", required=True)
    parser.add_argument("--runtime-file-name", required=True)
    parser.add_argument("--signature-check-executable", type=Path, required=True)
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.cycles < 1 or args.cycles > 100:
        parser.error("--cycles must be between 1 and 100")

    source = args.source.resolve()
    build = args.build.resolve()
    workspace = args.workspace.resolve()
    report_path = args.report.resolve()
    if workspace.name != "runtime-upgrade-acceptance-workspace":
        print("UPGRADE_INTEGRATION_ERROR: unsafe workspace name", file=sys.stderr)
        return 1
    result: dict[str, Any] = {"schemaVersion": 1, "integrationPassed": False}
    signing_environment: str | None = None
    private_key_path: Path | None = None
    try:
        if workspace.exists():
            shutil.rmtree(workspace)
        workspace.mkdir(parents=True)
        package = workspace / "package"
        target = workspace / "runtime"
        manifest_dir = workspace / "release"
        manifest_path = manifest_dir / "SHA256SUMS.json"
        audit_path = workspace / "upgrade-audit.jsonl"
        signature_path = manifest_dir / "SHA256SUMS.sig.json"
        private_key_path = workspace / "release-private-key.pem"
        public_key_path = workspace / "release-public-key.pem"
        trust_policy_path = workspace / "release-trust-policy.json"
        signing_environment = "PDR_UPGRADE_INTEGRATION_PRIVATE_KEY_PATH"
        signing_key_id = "integration-test-key"
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        except ImportError as error:
            raise RuntimeError("integration release host lacks cryptography for Ed25519 signing") from error
        private_key = Ed25519PrivateKey.generate()
        private_key_path.write_bytes(private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
        public_key_path.write_bytes(private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ))
        os.environ[signing_environment] = str(private_key_path)

        install = run([
            args.cmake, "--install", str(build), "--config", args.config,
            "--prefix", str(package),
        ])
        if install.returncode != 0:
            raise RuntimeError(f"package install failed: {install.stdout}{install.stderr}")
        generated = run([
            args.python, str(source / "tools/release_manifest.py"), "generate",
            "--root", str(source), "--artifacts", str(package),
            "--output", str(manifest_dir), "--version", args.version,
            "--ed25519-private-key-environment", signing_environment,
            "--signing-key-id", signing_key_id,
        ])
        if generated.returncode != 0:
            raise RuntimeError(f"manifest generation failed: {generated.stdout}{generated.stderr}")
        private_key_path.unlink()
        os.environ.pop(signing_environment, None)
        signature_verifier = args.signature_check_executable.resolve()
        public_key_sha256 = hashlib.sha256(public_key_path.read_bytes()).hexdigest()
        trust_policy_id = "integration-policy-v1"
        trust_policy = {
            "schemaVersion": 1,
            "product": "PocoDDSRuntime",
            "policyId": trust_policy_id,
            "allowedKeys": [{
                "keyId": signing_key_id,
                "algorithm": "Ed25519",
                "publicKeySha256": public_key_sha256,
                "notBefore": "2020-01-01T00:00:00Z",
                "notAfter": "2100-01-01T00:00:00Z",
            }],
            "revokedKeys": [],
        }
        trust_policy_path.write_text(
            json.dumps(trust_policy, indent=2), encoding="utf-8", newline="\n"
        )
        trust_policy_sha256 = hashlib.sha256(trust_policy_path.read_bytes()).hexdigest()
        release_verification = run([
            args.python, str(source / "tools/release_manifest.py"), "verify",
            "--manifest", str(manifest_path), "--artifacts", str(package),
            "--signature", str(signature_path), "--require-signature",
            "--expected-key-id", signing_key_id,
            "--public-key", str(public_key_path),
            "--expected-public-key-sha256", public_key_sha256,
            "--signature-check-executable", str(signature_verifier),
        ])
        if release_verification.returncode != 0:
            raise RuntimeError(
                "signed release verification failed: "
                f"{release_verification.stdout}{release_verification.stderr}"
            )

        shutil.copytree(package, target)
        (target / "pdr-release.json").write_text(
            json.dumps({"product": "PocoDDSRuntime", "version": args.version}),
            encoding="utf-8", newline="\n",
        )
        (target / "bin/data").mkdir(parents=True, exist_ok=True)
        (target / "bin/data/upgrade-state.txt").write_text(
            "before-upgrade", encoding="utf-8"
        )
        (target / "bin/codeCache").mkdir(parents=True, exist_ok=True)
        (target / "bin/codeCache/stale.cache").write_bytes(b"stale")

        preflight_base = [
            args.python, str(source / "tools/upgrade_manager.py"), "preflight",
            "--package", str(package), "--manifest", str(manifest_path),
            "--target", str(target), "--allow-development-release",
            "--signature", str(signature_path), "--expected-key-id", signing_key_id,
            "--public-key", str(public_key_path),
            "--signature-check-executable", str(signature_verifier),
        ]
        rejected_preflight = run([
            *preflight_base, "--expected-public-key-sha256", "0" * 64,
        ])
        if (rejected_preflight.returncode == 0 or
                "public key SHA-256 is not trusted" not in rejected_preflight.stdout):
            raise RuntimeError("upgrade preflight did not reject an untrusted public key digest")
        approved_preflight = run([
            *preflight_base, "--expected-public-key-sha256", public_key_sha256,
            "--trust-policy", str(trust_policy_path),
            "--expected-trust-policy-id", trust_policy_id,
            "--expected-trust-policy-sha256", trust_policy_sha256,
        ])
        if approved_preflight.returncode != 0:
            raise RuntimeError(
                f"signed upgrade preflight failed: {approved_preflight.stdout}{approved_preflight.stderr}"
            )

        tampered_policy_preflight = run([
            *preflight_base, "--expected-public-key-sha256", public_key_sha256,
            "--trust-policy", str(trust_policy_path),
            "--expected-trust-policy-id", trust_policy_id,
            "--expected-trust-policy-sha256", "0" * 64,
        ])
        if (tampered_policy_preflight.returncode == 0 or
                "trust policy SHA-256 is not trusted" not in tampered_policy_preflight.stdout):
            raise RuntimeError("upgrade preflight did not reject an untrusted policy digest")

        revoked_policy_path = workspace / "revoked-trust-policy.json"
        revoked_policy = dict(trust_policy)
        revoked_policy["policyId"] = "integration-revoked-v1"
        revoked_policy["revokedKeys"] = [{
            "keyId": signing_key_id,
            "revokedAt": "2026-01-01T00:00:00Z",
            "reason": "integration revocation test",
        }]
        revoked_policy_path.write_text(
            json.dumps(revoked_policy, indent=2), encoding="utf-8", newline="\n"
        )
        revoked_preflight = run([
            *preflight_base, "--expected-public-key-sha256", public_key_sha256,
            "--trust-policy", str(revoked_policy_path),
            "--expected-trust-policy-id", revoked_policy["policyId"],
            "--expected-trust-policy-sha256",
            hashlib.sha256(revoked_policy_path.read_bytes()).hexdigest(),
        ])
        if (revoked_preflight.returncode == 0 or
                "signing key is revoked" not in revoked_preflight.stdout):
            raise RuntimeError("upgrade preflight did not reject a revoked signing key")

        expired_policy_path = workspace / "expired-trust-policy.json"
        expired_policy = json.loads(json.dumps(trust_policy))
        expired_policy["policyId"] = "integration-expired-v1"
        expired_policy["allowedKeys"][0]["notAfter"] = "2020-01-02T00:00:00Z"
        expired_policy_path.write_text(
            json.dumps(expired_policy, indent=2), encoding="utf-8", newline="\n"
        )
        expired_preflight = run([
            *preflight_base, "--expected-public-key-sha256", public_key_sha256,
            "--trust-policy", str(expired_policy_path),
            "--expected-trust-policy-id", expired_policy["policyId"],
            "--expected-trust-policy-sha256",
            hashlib.sha256(expired_policy_path.read_bytes()).hexdigest(),
        ])
        if (expired_preflight.returncode == 0 or
                "signing key has expired" not in expired_preflight.stdout):
            raise RuntimeError("upgrade preflight did not reject an expired signing key")

        smoke_tool = source / "tools/runtime_smoke.py"
        runtime = "{target}/bin/" + args.runtime_file_name
        state_path = target / "bin/data/upgrade-state.txt"
        cycle_results = []
        for cycle in range(1, args.cycles + 1):
            smoke_report = workspace / f"installed-runtime-smoke-{cycle:02d}.json"
            smoke_log = workspace / f"installed-runtime-smoke-{cycle:02d}.log"
            before_state = f"cycle-{cycle:02d}-before-upgrade"
            after_state = f"cycle-{cycle:02d}-after-upgrade"
            state_path.write_text(before_state, encoding="utf-8")
            stale_cache = target / f"bin/codeCache/stale-{cycle:02d}.cache"
            stale_cache.parent.mkdir(parents=True, exist_ok=True)
            stale_cache.write_bytes(b"stale")
            upgrade = run([
                args.python, str(source / "tools/upgrade_manager.py"), "apply",
                "--package", str(package), "--manifest", str(manifest_path),
                "--target", str(target), "--audit", str(audit_path),
                "--allow-development-release",
                "--signature", str(signature_path),
                "--expected-key-id", signing_key_id,
                "--public-key", str(public_key_path),
                "--expected-public-key-sha256", public_key_sha256,
                "--signature-check-executable", str(signature_verifier),
                "--trust-policy", str(trust_policy_path),
                "--expected-trust-policy-id", trust_policy_id,
                "--expected-trust-policy-sha256", trust_policy_sha256,
                "--health-timeout", "30", "--health-command", args.python,
                f"--health-command-arg={smoke_tool}",
                f"--health-command-arg=--executable", f"--health-command-arg={runtime}",
                f"--health-command-arg=--working-directory",
                f"--health-command-arg={{target}}/bin",
                f"--health-command-arg=--path", f"--health-command-arg={{target}}/bin",
                f"--health-command-arg=--timeout", f"--health-command-arg=20",
                f"--health-command-arg=--stability-window", f"--health-command-arg=1",
                f"--health-command-arg=--endpoint", f"--health-command-arg=/health/detail",
                f"--health-command-arg=--report", f"--health-command-arg={smoke_report}",
                f"--health-command-arg=--log", f"--health-command-arg={smoke_log}",
            ])
            if upgrade.returncode != 0:
                raise RuntimeError(
                    f"upgrade cycle {cycle} failed: {upgrade.stdout}{upgrade.stderr}"
                )
            smoke = json.loads(smoke_report.read_text(encoding="utf-8"))
            if (not smoke.get("passed") or
                    smoke.get("shutdown", {}).get("mode") != "graceful" or
                    smoke.get("shutdown", {}).get("exitCode") != 0):
                raise RuntimeError(f"Runtime cycle {cycle} did not pass graceful validation")
            if "Shutdown complete" not in smoke_log.read_text(encoding="utf-8", errors="replace"):
                raise RuntimeError(f"Runtime cycle {cycle} lacks shutdown completion evidence")
            if state_path.read_text(encoding="utf-8") != before_state:
                raise RuntimeError(f"mutable state was not preserved in upgrade cycle {cycle}")
            if stale_cache.exists():
                raise RuntimeError(f"stale code cache migrated in upgrade cycle {cycle}")

            state_path.write_text(after_state, encoding="utf-8")
            rollback = run([
                args.python, str(source / "tools/upgrade_manager.py"), "rollback",
                "--target", str(target), "--audit", str(audit_path),
            ])
            if rollback.returncode != 0:
                raise RuntimeError(
                    f"rollback cycle {cycle} failed: {rollback.stdout}{rollback.stderr}"
                )
            if state_path.read_text(encoding="utf-8") != after_state:
                raise RuntimeError(f"mutable state was not preserved in rollback cycle {cycle}")
            cycle_results.append({
                "cycle": cycle,
                "upgradeExitCode": upgrade.returncode,
                "rollbackExitCode": rollback.returncode,
                "shutdown": smoke["shutdown"],
                "mutableState": after_state,
            })
        events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
        event_names = [event["event"] for event in events]
        event_counts: dict[str, int] = {}
        for event_name in event_names:
            event_counts[event_name] = event_counts.get(event_name, 0) + 1
        for expected_event in (
                "preflight_passed", "staging_verified", "activated", "health_passed",
                "backup_retention_applied", "manual_rollback"):
            if event_names.count(expected_event) != args.cycles:
                raise RuntimeError(
                    f"audit event {expected_event} count is {event_names.count(expected_event)}, "
                    f"expected {args.cycles}"
                )
        rename_operations = [
            operation
            for event in events
            for operation in event.get("renameEvidence", [])
        ]
        retried_rename_operations = [
            operation for operation in rename_operations
            if operation.get("attempts", 0) > 1
        ]
        result.update({
            "integrationPassed": True,
            "version": args.version,
            "upgradeExitCode": upgrade.returncode,
            "rollbackExitCode": rollback.returncode,
            "runtimeShutdown": smoke["shutdown"],
            "cyclesRequested": args.cycles,
            "cyclesPassed": len(cycle_results),
            "cycles": cycle_results,
            "mutableStatePreserved": True,
            "staleCodeCacheDiscarded": True,
            "signatureVerified": True,
            "signatureAlgorithm": "Ed25519",
            "signatureKeyId": signing_key_id,
            "publicKeySha256": public_key_sha256,
            "releaseVerificationExitCode": release_verification.returncode,
            "untrustedPublicKeyRejected": True,
            "preflightExitCode": approved_preflight.returncode,
            "trustPolicyId": trust_policy_id,
            "trustPolicySha256": trust_policy_sha256,
            "tamperedTrustPolicyRejected": True,
            "revokedKeyRejected": True,
            "expiredKeyRejected": True,
            "auditEvents": event_names,
            "auditEventCounts": event_counts,
            "renameOperations": len(rename_operations),
            "renameOperationsRetried": len(retried_rename_operations),
            "maxRenameAttempts": max(
                (operation.get("attempts", 0) for operation in rename_operations),
                default=0,
            ),
        })
        write_report(report_path, result)
        print(f"UPGRADE_INTEGRATION_PASS report={report_path}")
        return 0
    except Exception as error:
        result["error"] = str(error)
        write_report(report_path, result)
        print(f"UPGRADE_INTEGRATION_ERROR: {error}", file=sys.stderr)
        return 1
    finally:
        if signing_environment:
            os.environ.pop(signing_environment, None)
        if private_key_path and private_key_path.exists():
            private_key_path.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
