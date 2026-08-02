import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bundle(path: Path, symbolic: str, version: str) -> None:
    manifest = (
        "Manifest-Version: 1.0\n"
        f"Bundle-Name: {symbolic}\nBundle-SymbolicName: {symbolic}\n"
        f"Bundle-Version: {version}\nBundle-Vendor: integration-test\n"
        "PDR-Plugin-API: 1.0.0\nPDR-Plugin-ABI: 1.0.0\n"
        "PDR-Plugin-ABI-Fingerprint: MSVC-19-Windows_NT-AMD64\n"
        "PDR-Runtime-Version: [0.1.0,0.2.0)\n"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("META-INF/manifest.mf", manifest)
        archive.writestr("bin/Windows_NT/AMD64/plugin.dll", b"publisher-integration")


def run(command: list[str], expected: int, environment=None) -> subprocess.CompletedProcess:
    result = subprocess.run(command, capture_output=True, text=True, check=False, env=environment)
    if result.returncode != expected:
        raise AssertionError(
            f"expected {expected}, got {result.returncode}: {' '.join(command)}\n"
            f"{result.stdout}\n{result.stderr}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", required=True)
    parser.add_argument("--pdr", type=Path, required=True)
    parser.add_argument("--verifier", type=Path, required=True)
    args = parser.parse_args()
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding, NoEncryption, PrivateFormat, PublicFormat,
    )
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        bundles = root / "runtime" / "bundles"
        bundles.mkdir(parents=True)
        contract = {
            "schemaVersion": 1, "runtimeVersion": "0.1.0",
            "pluginApiVersion": "1.0.0", "pluginAbiVersion": "1.0.0",
            "abiFingerprint": "MSVC-19-Windows_NT-AMD64",
            "targetOs": "Windows_NT", "targetArch": "AMD64",
            "compilerId": "MSVC", "compilerMajor": "19",
        }
        (bundles.parent / "pdr-plugin-runtime.json").write_text(
            json.dumps(contract), encoding="utf-8")
        artifact = root / "pdr.plugin.vendor.sample_1.0.0.bndl"
        bundle(artifact, "pdr.plugin.vendor.sample", "1.0.0")
        key = Ed25519PrivateKey.generate()
        private_key, public_key = root / "private.pem", root / "public.pem"
        private_key.write_bytes(key.private_bytes(
            Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
        public_key.write_bytes(key.public_key().public_bytes(
            Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
        attestation, signature = root / "attestation.json", root / "signature.json"
        environment = dict(os.environ, PDR_PLUGIN_PRIVATE_KEY=str(private_key))
        run([args.python, str(args.pdr), "plugin", "sign", str(artifact),
             "--publisher-id", "vendor", "--key-id", "vendor-key",
             "--private-key-path-environment", "PDR_PLUGIN_PRIVATE_KEY",
             "--attestation", str(attestation), "--signature", str(signature)], 0, environment)
        current = datetime.now(timezone.utc)
        policy_path = root / "policy.json"

        def policy(pattern="pdr.plugin.vendor.*", revoked=False):
            document = {
                "schemaVersion": 1, "product": "PocoDDSRuntimePlugin", "policyId": "test-policy",
                "allowedPublishers": [{
                    "publisherId": "vendor", "keyId": "vendor-key", "algorithm": "Ed25519",
                    "publicKeySha256": digest(public_key), "pluginPatterns": [pattern],
                    "notBefore": (current - timedelta(days=1)).isoformat(),
                    "notAfter": (current + timedelta(days=1)).isoformat(),
                }],
                "revokedKeys": [{"keyId": "vendor-key", "revokedAt": current.isoformat(),
                                  "reason": "integration revocation"}] if revoked else [],
            }
            policy_path.write_text(json.dumps(document), encoding="utf-8")
            return digest(policy_path)

        def provenance(command_name: str, policy_digest: str):
            return [args.python, str(args.pdr), "plugin", command_name, str(artifact),
                    "--bundle-directory", str(bundles), "--expected-sha256", digest(artifact),
                    "--attestation", str(attestation), "--signature", str(signature),
                    "--public-key", str(public_key), "--trust-policy", str(policy_path),
                    "--expected-trust-policy-id", "test-policy",
                    "--expected-trust-policy-sha256", policy_digest,
                    "--signature-check-executable", str(args.verifier)]

        approved = policy()
        run([args.python, str(args.pdr), "plugin", "preflight", str(artifact),
             "--bundle-directory", str(bundles), "--expected-sha256", digest(artifact)], 2)
        result = run(provenance("preflight", approved), 0)
        if '"verified": true' not in result.stdout or '"publisherId": "vendor"' not in result.stdout:
            raise AssertionError("verified publisher evidence is missing")
        install = provenance("install", approved)
        install.extend(["--confirm-runtime-stopped", "--report", str(root / "install.json")])
        run(install, 0)
        report = json.loads((root / "install.json").read_text(encoding="utf-8"))
        if report["preflight"]["provenance"].get("publisherId") != "vendor":
            raise AssertionError("installation report lost publisher provenance")
        audit = (bundles.parent / "plugin-transactions.audit.jsonl").read_text(encoding="utf-8")
        if '"publisherId":"vendor"' not in audit or '"signingKeyId":"vendor-key"' not in audit:
            raise AssertionError("installation audit lost publisher provenance")

        # Re-sign a second copy, then mutate it to prove the attestation binds the exact bytes.
        artifact.unlink()
        bundle(artifact, "pdr.plugin.vendor.sample", "1.0.0")
        with zipfile.ZipFile(artifact, "a") as archive:
            archive.writestr("tampered.bin", b"tampered")
        run(provenance("preflight", approved), 2)
        run(provenance("preflight", policy("pdr.plugin.other.*")), 2)
        run(provenance("preflight", policy(revoked=True)), 2)
    print("PLUGIN_PUBLISHER_INTEGRATION_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
