#!/usr/bin/env python3

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
PDR = TOOLS / "pdr.py"
EXAMPLE = ROOT / "examples/team-contract-adapter-catalog"
MANIFEST_GENERATOR = EXAMPLE / "create_adapter_manifest.py"
CATALOG_GENERATOR = EXAMPLE / "create_adapter_catalog.py"


ADAPTER_SOURCE = r'''#!/usr/bin/env python3
import argparse, json, sys
p=argparse.ArgumentParser()
p.add_argument("--request-product",required=True)
p.add_argument("--manifest-product",required=True)
p.add_argument("--identity-field",required=True)
p.add_argument("--adapter-id",required=True)
a=p.parse_args()
r=json.load(sys.stdin)
if set(r)!={"schemaVersion","product","requestId",a.identity_field}:
    raise SystemExit(2)
if r["product"]!=a.request_product or r[a.identity_field]!=a.adapter_id:
    raise SystemExit(2)
print(json.dumps({"schemaVersion":1,"product":a.manifest_product,
"requestId":r["requestId"],a.identity_field:a.adapter_id,
"implementationId":"generic-catalog-test-v1","protocolMajor":1,
"protocolMinor":0,"capabilities":["discovery","health-check"]},
sort_keys=True,separators=(",",":")))
'''


class AdapterCatalogTests(unittest.TestCase):
    @staticmethod
    def invoke(*arguments: str, environment=None):
        return subprocess.run(
            [sys.executable, *arguments], check=False, capture_output=True,
            text=True, timeout=30, env=environment,
        )

    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_manifest_catalog_discovers_unknown_types_and_fails_on_drift(self):
        sentinel = "catalog-probe-secret-never-report"
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            adapter = work / "generic_adapter.py"
            adapter.write_text(ADAPTER_SOURCE, encoding="utf-8")
            request_product = "PocoDDSRuntimeTestAdapterCapabilityRequest"
            manifest_product = "PocoDDSRuntimeTestAdapterCapabilityManifest"

            manifests = []
            for adapter_id, adapter_type in (
                    ("audit-alpha", "custom-audit-sink"),
                    ("telemetry-beta", "custom-telemetry-exporter")):
                config = work / f"{adapter_id}-config.json"
                config.write_text(json.dumps({
                    "schemaVersion": 1,
                    "product": "PocoDDSRuntimeTestAdapterConfig",
                    "adapterId": adapter_id, "kind": "external-command",
                    "protocolMajor": 1, "minimumProtocolMinor": 0,
                    "requiredCapabilities": ["discovery", "health-check"],
                    "executable": str(Path(sys.executable).resolve()),
                    "executableSha256": self.digest(Path(sys.executable)),
                    "arguments": [
                        str(adapter.resolve()),
                        "--request-product", request_product,
                        "--manifest-product", manifest_product,
                        "--identity-field", "adapterId",
                        "--adapter-id", adapter_id,
                    ],
                    "artifactPins": [{
                        "path": str(adapter.resolve()),
                        "sha256": self.digest(adapter),
                    }],
                    "environmentVariables": [],
                    "optionalEnvironmentVariables": ["PDR_CATALOG_PROBE_SECRET"],
                    "timeoutSeconds": 3, "maxResponseBytes": 4096,
                }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                manifest = work / f"{adapter_id}-manifest.json"
                generated = self.invoke(
                    str(MANIFEST_GENERATOR), "--config", str(config.resolve()),
                    "--manifest-id", f"{adapter_id}.deploy-1",
                    "--adapter-id", adapter_id, "--adapter-type", adapter_type,
                    "--owner", "team/runtime-governance",
                    "--revision", "deploy-1", "--protocol-id", "pdr.test-adapter",
                    "--identity-field", "adapterId",
                    "--capability-request-product", request_product,
                    "--capability-manifest-product", manifest_product,
                    "--output", str(manifest.resolve()),
                )
                self.assertEqual(
                    generated.returncode, 0, generated.stdout + generated.stderr
                )
                manifests.append(manifest)
            reserved_manifest = self.invoke(
                str(MANIFEST_GENERATOR), "--config",
                str((work / "audit-alpha-config.json").resolve()),
                "--manifest-id", "reserved-field.deploy-1",
                "--adapter-id", "audit-alpha",
                "--adapter-type", "custom-audit-sink",
                "--owner", "team/runtime-governance",
                "--revision", "deploy-1", "--protocol-id", "pdr.test-adapter",
                "--identity-field", "product",
                "--capability-request-product", request_product,
                "--capability-manifest-product", manifest_product,
                "--output", str((work / "reserved-manifest.json").resolve()),
            )
            self.assertEqual(reserved_manifest.returncode, 2)
            self.assertIn("arguments are malformed", reserved_manifest.stderr)
            catalog = work / "catalog.json"
            catalog_created = self.invoke(
                str(CATALOG_GENERATOR), "--catalog-id", "test-host-adapters",
                "--generation", "1", "--manifest", str(manifests[0].resolve()),
                "--manifest", str(manifests[1].resolve()),
                "--output", str(catalog.resolve()),
            )
            self.assertEqual(
                catalog_created.returncode, 0,
                catalog_created.stdout + catalog_created.stderr,
            )
            listing = work / "listing.json"
            listed = self.invoke(
                str(PDR), "contract-package", "adapter-catalog-list",
                "--catalog", str(catalog.resolve()),
                "--expected-catalog-sha256", self.digest(catalog),
                "--report", str(listing.resolve()),
            )
            self.assertEqual(listed.returncode, 0, listed.stdout + listed.stderr)
            listed_document = json.loads(listing.read_bytes())
            self.assertEqual(len(listed_document["adapters"]), 2)
            self.assertEqual(
                {item["adapterType"] for item in listed_document["adapters"]},
                {"custom-audit-sink", "custom-telemetry-exporter"},
            )
            environment = dict(os.environ)
            environment["PDR_CATALOG_PROBE_SECRET"] = sentinel
            check_one = work / "check-one.json"
            checked = self.invoke(
                str(PDR), "contract-package", "adapter-catalog-check",
                "--catalog", str(catalog.resolve()),
                "--expected-catalog-sha256", self.digest(catalog),
                "--report", str(check_one.resolve()), environment=environment,
            )
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
            first_check = json.loads(check_one.read_bytes())
            self.assertEqual(len(first_check["adapters"]), 2)
            self.assertTrue(all(item["healthy"] for item in first_check["adapters"]))
            self.assertNotIn(sentinel.encode(), check_one.read_bytes())
            check_two = work / "check-two.json"
            checked_again = self.invoke(
                str(PDR), "contract-package", "adapter-catalog-check",
                "--catalog", str(catalog.resolve()),
                "--expected-catalog-sha256", self.digest(catalog),
                "--report", str(check_two.resolve()), environment=environment,
            )
            self.assertEqual(checked_again.returncode, 0, checked_again.stderr)
            second_check = json.loads(check_two.read_bytes())
            self.assertEqual(
                [item["capabilityManifestSha256"]
                 for item in first_check["adapters"]],
                [item["capabilityManifestSha256"]
                 for item in second_check["adapters"]],
            )
            filtered = self.invoke(
                str(PDR), "contract-package", "adapter-catalog-check",
                "--catalog", str(catalog.resolve()),
                "--expected-catalog-sha256", self.digest(catalog),
                "--adapter-type", "custom-audit-sink", environment=environment,
            )
            self.assertEqual(filtered.returncode, 0, filtered.stderr)
            unknown = self.invoke(
                str(PDR), "contract-package", "adapter-catalog-list",
                "--catalog", str(catalog.resolve()),
                "--expected-catalog-sha256", self.digest(catalog),
                "--adapter-type", "unknown-adapter",
            )
            self.assertEqual(unknown.returncode, 2)

            duplicate = work / "duplicate-catalog.json"
            duplicate_document = json.loads(catalog.read_bytes())
            duplicate_document["entries"].append(
                dict(duplicate_document["entries"][0])
            )
            duplicate.write_text(
                json.dumps(duplicate_document, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            rejected_duplicate = self.invoke(
                str(PDR), "contract-package", "adapter-catalog-list",
                "--catalog", str(duplicate.resolve()),
                "--expected-catalog-sha256", self.digest(duplicate),
            )
            self.assertEqual(rejected_duplicate.returncode, 2)
            duplicate_id = work / "duplicate-adapter-id-catalog.json"
            duplicate_id_document = json.loads(catalog.read_bytes())
            duplicate_id_document["entries"][1]["adapterId"] = \
                duplicate_id_document["entries"][0]["adapterId"]
            duplicate_id.write_text(
                json.dumps(duplicate_id_document, indent=2, sort_keys=True)
                + "\n", encoding="utf-8",
            )
            rejected_duplicate_id = self.invoke(
                str(PDR), "contract-package", "adapter-catalog-list",
                "--catalog", str(duplicate_id.resolve()),
                "--expected-catalog-sha256", self.digest(duplicate_id),
            )
            self.assertEqual(rejected_duplicate_id.returncode, 2)
            self.assertIn("entry is duplicated", rejected_duplicate_id.stderr)
            manifests[0].write_bytes(manifests[0].read_bytes() + b" ")
            rejected_drift = self.invoke(
                str(PDR), "contract-package", "adapter-catalog-check",
                "--catalog", str(catalog.resolve()),
                "--expected-catalog-sha256", self.digest(catalog),
                environment=environment,
            )
            self.assertEqual(rejected_drift.returncode, 2)
        print(
            "PDR_ADAPTER_CATALOG_PASS manifest=1 catalog=1 discovery=1 "
            "genericType=1 capability=1 filter=1 pins=1 drift=1 duplicate=1 "
            "stableDigest=1 redaction=1 cli=1 noCoreRegistration=1"
        )


if __name__ == "__main__":
    unittest.main()
