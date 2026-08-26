#!/usr/bin/env python3
"""Real Launcher -> Runtime acceptance for process-boundary Bundle deployment."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.request import urlopen


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def replace_property(text: str, key: str, value: str) -> str:
    prefix = key + " ="
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = f"{key} = {value}"
            break
    else:
        lines.append(f"{key} = {value}")
    return "\n".join(lines) + "\n"


def portable(path: Path) -> str:
    return path.resolve().as_posix()


def read_properties(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def validate_jsonl(path: Path) -> int:
    count = 0
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            document = json.loads(line)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"malformed audit JSONL {path}:{line_number}: {error}") from error
        if not isinstance(document, dict):
            raise RuntimeError(f"audit JSONL entry is not an object: {path}:{line_number}")
        count += 1
    if count == 0:
        raise RuntimeError(f"audit JSONL contains no evidence: {path}")
    return count


def wait_for(predicate, timeout: float, description: str):
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except Exception as error:
            last_error = error
        time.sleep(0.2)
    detail = f": {last_error}" if last_error else ""
    raise RuntimeError(f"timed out waiting for {description}{detail}")


def health(port: int) -> dict[str, object] | None:
    with urlopen(f"http://127.0.0.1:{port}/health/ready", timeout=1.0) as response:
        if response.status != 200:
            return None
        return json.loads(response.read().decode("utf-8"))


def journal_state(path: Path, state: str, transaction_id: str | None = None):
    values = read_properties(path)
    if values.get("state") != state:
        return None
    if transaction_id is not None and values.get("transactionId") != transaction_id:
        return None
    return values


def stop(process: subprocess.Popen[bytes], stdout, stderr) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
    stdout.close()
    stderr.close()


def release_provenance(repository: Path, evidence: Path,
                       rollout_sequence: int) -> tuple[Path, Path, Path]:
    artifact_root = repository.parent
    entries = []
    for path in sorted(repository.rglob("*")):
        if path.is_file():
            entries.append({
                "path": path.relative_to(artifact_root).as_posix(),
                "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            })
    artifact_set = hashlib.sha256(json.dumps(
        entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    version = f"0.1.{rollout_sequence}"
    git_commit = f"{rollout_sequence:040x}"[-40:]
    sbom = evidence / f"release-{rollout_sequence}.spdx.json"
    sbom_document = {
        "spdxVersion": "SPDX-2.3", "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "documentNamespace": f"https://pocodds.local/spdx/acceptance-{rollout_sequence}",
        "packages": [{"name": "PocoDDSRuntime", "versionInfo": version}],
    }
    sbom.write_text(json.dumps(sbom_document, indent=2) + "\n", encoding="utf-8")
    manifest = evidence / f"release-{rollout_sequence}.manifest.json"
    manifest.write_text(json.dumps({
        "schemaVersion": 1, "product": "PocoDDSRuntime", "version": version,
        "gitCommit": git_commit, "dirty": False,
        "generatedAt": "2026-08-25T00:00:00+00:00", "files": entries,
        "sbom": {"path": sbom.name,
                 "sha256": hashlib.sha256(sbom.read_bytes()).hexdigest(),
                 "spdxVersion": "SPDX-2.3",
                 "documentNamespace": sbom_document["documentNamespace"]},
        "provenance": {"builderId": "acceptance-builder",
                       "buildProfile": "server",
                       "artifactSetSha256": artifact_set,
                       "source": {"gitCommit": git_commit, "dirty": False}},
    }, indent=2) + "\n", encoding="utf-8")
    return manifest, sbom, artifact_root


def sign_repository(args: argparse.Namespace, repository: Path, evidence: Path,
                    private_key: Path, rollout_sequence: int) -> dict[str, object]:
    environment = dict(os.environ)
    environment["PDR_BUNDLE_DEPLOYMENT_PRIVATE_KEY"] = str(private_key)
    release_manifest, release_sbom, release_artifacts = release_provenance(
        repository, evidence, rollout_sequence
    )
    result = subprocess.run(
        [
            sys.executable, str(args.publisher), "sign",
            "--repository", str(repository),
            "--fingerprint-executable", str(args.fingerprint_checker),
            "--repository-id", "runtime-main",
            "--rollout-sequence", str(rollout_sequence),
            "--publisher-id", "acceptance-publisher",
            "--key-id", "acceptance-2026",
            "--private-key-path-environment", "PDR_BUNDLE_DEPLOYMENT_PRIVATE_KEY",
            "--output-directory", str(evidence),
            "--release-manifest", str(release_manifest),
            "--release-sbom", str(release_sbom),
            "--release-artifacts-root", str(release_artifacts),
        ],
        capture_output=True, text=True, check=False, env=environment,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip() or "repository signing failed")
    return json.loads(result.stdout)


def run(args: argparse.Namespace) -> dict[str, object]:
    source_dir = args.source_dir.resolve()
    work_dir = args.work_dir.resolve()
    if work_dir.exists():
        shutil.rmtree(work_dir)
    shutil.copytree(source_dir, work_dir)
    for mutable in ("data", "logs", "codeCache"):
        path = work_dir / mutable
        if path.exists():
            shutil.rmtree(path)
        path.mkdir()
    (work_dir / "empty-subprocesses.properties").write_text("# empty\n", encoding="utf-8")

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import (
            Encoding, NoEncryption, PrivateFormat, PublicFormat,
        )
    except ImportError as error:
        raise RuntimeError(f"release-host cryptography is required: {error}") from error
    trust_root = work_dir / "bundle-trust"
    evidence_dir = trust_root / "evidence"
    keys_dir = trust_root / "keys"
    evidence_dir.mkdir(parents=True)
    keys_dir.mkdir()
    private_key = trust_root / "acceptance-private.pem"
    public_key = keys_dir / "acceptance-2026.pem"
    key = Ed25519PrivateKey.generate()
    private_key.write_bytes(key.private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    public_key.write_bytes(key.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
    policy = trust_root / "bundle-trust-policy.json"
    policy.write_text(json.dumps({
        "schemaVersion": 1,
        "product": "PocoDDSBundleRepository",
        "policyId": "acceptance-policy-v1",
        "allowedPublishers": [{
            "publisherId": "acceptance-publisher",
            "keyId": "acceptance-2026",
            "algorithm": "Ed25519",
            "publicKeySha256": hashlib.sha256(public_key.read_bytes()).hexdigest(),
            "repositoryPatterns": ["runtime-*"],
        }],
        "revokedKeys": [],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    policy_digest = hashlib.sha256(policy.read_bytes()).hexdigest()

    port = free_port()
    runtime_config = work_dir / "pdr-runtime.properties"
    runtime_text = runtime_config.read_text(encoding="utf-8")
    for key, value in (
        ("osp.bundleMonitor.enabled", "true"),
        ("osp.bundleMonitor.intervalMilliseconds", "100"),
        ("osp.bundleMonitor.stableScanCount", "50"),
        ("osp.bundleMonitor.stateDirectory", "${application.dir}data/bundle-manager/"),
        ("osp.bundleMonitor.inProcessReloadEnabled", "false"),
        ("osp.bundleMonitor.authorization.required", "true"),
        ("osp.bundleMonitor.authorization.repositoryId", "runtime-main"),
        ("osp.bundleMonitor.authorization.evidenceDirectory", portable(evidence_dir)),
        ("osp.bundleMonitor.authorization.trustPolicyFile", portable(policy)),
        ("osp.bundleMonitor.authorization.expectedTrustPolicyId", "acceptance-policy-v1"),
        ("osp.bundleMonitor.authorization.expectedTrustPolicySha256", policy_digest),
        ("osp.bundleMonitor.authorization.trustedKeysDirectory", portable(keys_dir)),
        ("osp.web.server.port", str(port)),
        ("pdr.subprocess.configuration", "${application.dir}empty-subprocesses.properties"),
    ):
        runtime_text = replace_property(runtime_text, key, value)
    runtime_config.write_text(runtime_text, encoding="utf-8")

    runtime = work_dir / args.runtime.name
    launcher_dir = work_dir / "processes" / "pdr-launcher"
    launcher = launcher_dir / args.launcher.name
    state_dir = work_dir / "data" / "bundle-manager"
    transaction_path = state_dir / "transaction.properties"
    deployment_path = state_dir / "deployment.properties"
    bundles = work_dir / "bundles"
    initial_authorization = sign_repository(args, bundles, evidence_dir, private_key, 100)
    initial_replay = work_dir / "initial-replay-bundles"
    shutil.copytree(bundles, initial_replay)
    launcher_config = launcher_dir / "deployment-acceptance.properties"
    launcher_config.write_text(
        "\n".join(
            (
                "relaunchDelay = 100",
                "restartBudget.maxRestarts = 5",
                "restartBudget.windowMilliseconds = 60000",
                "childArgument.count = 0",
                f"childWorkingDirectory = {portable(work_dir)}",
                "resourceLimits.killProcessTreeOnExit = true",
                "resourceLimits.memoryBytes = 0",
                "resourceLimits.activeProcessLimit = 0",
                "resourceLimits.cpuRatePercent = 0",
                "watchdog.file =",
                "watchdog.timeout = 60000",
                "watchdog.interval = 1000",
                "watchdog.startupGraceMilliseconds = 60000",
                "watchdog.requireFile = false",
                "osp.bundleMonitor.enabled = false",
                "deployment.enabled = true",
                f"deployment.repository = {portable(bundles)}",
                f"deployment.stateDirectory = {portable(state_dir)}",
                "deployment.pollMilliseconds = 2000",
                "deployment.stopTimeoutMilliseconds = 10000",
                "deployment.startupTimeoutMilliseconds = 45000",
                "deployment.probationMilliseconds = 500",
                "deployment.readiness.file =",
                "deployment.authorization.required = true",
                "deployment.authorization.repositoryId = runtime-main",
                f"deployment.authorization.evidenceDirectory = {portable(evidence_dir)}",
                f"deployment.authorization.trustPolicyFile = {portable(policy)}",
                "deployment.authorization.expectedTrustPolicyId = acceptance-policy-v1",
                f"deployment.authorization.expectedTrustPolicySha256 = {policy_digest}",
                f"deployment.authorization.trustedKeysDirectory = {portable(keys_dir)}",
                "logging.loggers.root.channel = console",
                "logging.loggers.root.level = information",
                "logging.channels.console.class = ConsoleChannel",
                "",
            )
        ),
        encoding="utf-8",
    )

    config_option = ("/config-file=" if os.name == "nt" else "--config-file=") + str(
        launcher_config
    )
    stdout = (work_dir / "launcher.stdout.log").open("wb")
    stderr = (work_dir / "launcher.stderr.log").open("wb")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        [str(launcher), config_option, str(runtime)],
        cwd=launcher_dir,
        stdout=stdout,
        stderr=stderr,
        creationflags=flags,
    )
    evidence: dict[str, object] = {
        "port": port,
        "authorization": {
            "required": True,
            "policyId": "acceptance-policy-v1",
            "policySha256": policy_digest,
            "initial": initial_authorization,
        },
    }
    try:
        evidence["initialHealth"] = wait_for(lambda: health(port), 45, "initial readiness")
        evidence["startup"] = wait_for(
            lambda: journal_state(transaction_path, "committed", "startup"),
            20,
            "startup Bundle journal",
        )

        archives = sorted(bundles.glob("*.bndl"))
        if len(archives) < 2:
            raise RuntimeError("acceptance requires at least two Bundle archives")
        activated_source = archives[0]
        activated_target = activated_source.with_name(activated_source.stem + ".activated.bndl")
        activated_source.rename(activated_target)
        evidence["authorization"]["candidate"] = sign_repository(
            args, bundles, evidence_dir, private_key, 101)
        pending = wait_for(
            lambda: journal_state(transaction_path, "restartRequired"),
            20,
            "restartRequired candidate",
        )
        digest = pending.get("candidateDigest", "")
        if len(digest) != 64:
            raise RuntimeError("restartRequired transaction has no SHA-256 candidateDigest")
        transaction_id = pending["transactionId"]
        evidence["restartRequired"] = pending
        committed = wait_for(
            lambda: journal_state(deployment_path, "committed", transaction_id),
            60,
            "Launcher deployment commit",
        )
        evidence["deploymentCommitted"] = committed
        evidence["healthAfterCommit"] = wait_for(
            lambda: health(port), 45, "post-deployment readiness"
        )
        activation = read_properties(transaction_path)
        if activation.get("state") != "activationReady" or activation.get("transactionId") != transaction_id:
            raise RuntimeError("Runtime did not acknowledge the exact deployment transaction")
        if activation.get("candidateDigest") != digest:
            raise RuntimeError("Runtime activation digest does not match preflight digest")
        for key_name, expected in (
            ("authorizationVerified", "true"),
            ("repositoryId", "runtime-main"),
            ("publisherId", "acceptance-publisher"),
            ("signingKeyId", "acceptance-2026"),
            ("trustPolicyId", "acceptance-policy-v1"),
            ("trustPolicySha256", policy_digest),
            ("rolloutSequence", "101"),
            ("releaseManifestSha256", evidence["authorization"]["candidate"]
             ["provenance"]["releaseManifestSha256"]),
            ("sbomSha256", evidence["authorization"]["candidate"]
             ["provenance"]["sbomSha256"]),
            ("artifactSetSha256", evidence["authorization"]["candidate"]
             ["provenance"]["artifactSetSha256"]),
            ("releaseVersion", evidence["authorization"]["candidate"]
             ["provenance"]["version"]),
            ("gitCommit", evidence["authorization"]["candidate"]
             ["provenance"]["gitCommit"]),
            ("builderId", "acceptance-builder"),
            ("buildProfile", "server"),
        ):
            if activation.get(key_name) != expected or committed.get(key_name) != expected:
                raise RuntimeError(f"authorization evidence mismatch for {key_name}")

        remaining = sorted(path for path in bundles.glob("*.bndl") if path != activated_target)
        tamper_source = remaining[0]
        tamper_target = tamper_source.with_name(tamper_source.stem + ".pending.bndl")
        tamper_source.rename(tamper_target)
        evidence["authorization"]["tamperCandidate"] = sign_repository(
            args, bundles, evidence_dir, private_key, 102)
        tamper_pending = wait_for(
            lambda: (
                value
                if (value := journal_state(transaction_path, "restartRequired"))
                and value.get("transactionId") != transaction_id
                else None
            ),
            20,
            "second restartRequired candidate",
        )
        tamper_transaction_id = tamper_pending["transactionId"]
        tamper_target.rename(tamper_source)
        rejected = wait_for(
            lambda: journal_state(deployment_path, "rejected", tamper_transaction_id),
            10,
            "post-preflight tamper rejection",
        )
        evidence["tamperRejected"] = rejected
        evidence["healthAfterTamperReject"] = health(port)
        if not evidence["healthAfterTamperReject"]:
            raise RuntimeError("current Runtime lost readiness after fail-before-stop rejection")
        if process.poll() is not None:
            raise RuntimeError(f"Launcher exited unexpectedly: {process.returncode}")

        # An unsigned malformed archive must be rejected by the authorization gate
        # before the OSP Bundle/ZIP parser sees it, while the current child remains up.
        malformed = bundles / "unsigned-malformed.bndl"
        malformed.write_bytes(b"not-a-bundle-archive")
        unsigned_rejected = wait_for(
            lambda: (
                value
                if (value := journal_state(transaction_path, "rejected"))
                and value.get("transactionId") not in {transaction_id, tamper_transaction_id}
                else None
            ),
            25,
            "unsigned malformed candidate rejection",
        )
        if "digest-bound attestation and signature" not in unsigned_rejected.get("error", ""):
            raise RuntimeError("unsigned candidate was not rejected at the authorization boundary")
        evidence["unsignedMalformedRejectedBeforeParsing"] = unsigned_rejected
        evidence["healthAfterUnsignedReject"] = health(port)
        if not evidence["healthAfterUnsignedReject"]:
            raise RuntimeError("current Runtime lost readiness after unsigned candidate rejection")
    finally:
        stop(process, stdout, stderr)

    high_water = read_properties(state_dir / "repository-rollout-high-water.properties")
    if (high_water.get("schemaVersion") != "2" or
            high_water.get("rolloutSequence") != "101" or
            high_water.get("candidateDigest") != digest or
            high_water.get("releaseManifestSha256") !=
            evidence["authorization"]["candidate"]["provenance"]["releaseManifestSha256"] or
            high_water.get("sbomSha256") !=
            evidence["authorization"]["candidate"]["provenance"]["sbomSha256"]):
        raise RuntimeError("committed deployment did not persist the exact rollout high-water mark")
    evidence["rolloutHighWater"] = high_water

    replay_config = work_dir / "replay-runtime.properties"
    replay_text = runtime_config.read_text(encoding="utf-8")
    replay_text = replace_property(replay_text, "osp.bundleRepository", portable(initial_replay))
    replay_config.write_text(replay_text, encoding="utf-8")
    replay_option = ("/config-file=" if os.name == "nt" else "--config-file=") + str(replay_config)
    replay_rejection = subprocess.run(
        [str(runtime), replay_option], cwd=work_dir, capture_output=True, text=True,
        check=False, timeout=20, creationflags=flags,
    )
    replay_output = replay_rejection.stdout + replay_rejection.stderr
    if replay_rejection.returncode == 0:
        raise RuntimeError("older signed Bundle rollout unexpectedly passed Runtime startup")
    if "Bundle repository rollback detected" not in replay_output or "Startup complete." in replay_output:
        raise RuntimeError("Runtime did not reject the signed rollback before OSP startup")
    evidence["signedRollbackRejectedBeforeOsp"] = {
        "exitCode": replay_rejection.returncode,
        "candidateSequence": 100,
        "acceptedSequence": 101,
        "ospStartupComplete": False,
    }

    startup_rejection = subprocess.run(
        [str(runtime)], cwd=work_dir, capture_output=True, text=True,
        check=False, timeout=20, creationflags=flags,
    )
    startup_output = startup_rejection.stdout + startup_rejection.stderr
    if startup_rejection.returncode == 0:
        raise RuntimeError("unsigned repository unexpectedly passed Runtime startup authorization")
    if ("digest-bound attestation and signature" not in startup_output or
            "Startup complete." in startup_output):
        raise RuntimeError("Runtime did not reject unsigned repository before OSP startup")
    evidence["unsignedStartupRejectedBeforeOsp"] = {
        "exitCode": startup_rejection.returncode,
        "authorizationError": True,
        "ospStartupComplete": False,
    }

    evidence["auditJsonl"] = {
        "bundleManagerEntries": validate_jsonl(state_dir / "transactions.jsonl"),
        "deploymentEntries": validate_jsonl(state_dir / "deployment-transactions.jsonl"),
    }

    evidence["result"] = "PASS"
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return evidence


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--launcher", required=True, type=Path)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--publisher", required=True, type=Path)
    parser.add_argument("--fingerprint-checker", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        print(json.dumps(run(args), ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        print(f"Launcher Bundle deployment acceptance failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
