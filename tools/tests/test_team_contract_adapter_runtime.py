#!/usr/bin/env python3

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
import team_contract_adapter_runtime as adapter_runtime  # noqa: E402


class AdapterRuntimeTests(unittest.TestCase):
    def test_shared_runtime_is_bounded_isolated_and_redacted(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            artifact = work / "adapter.py"
            artifact.write_text("print('adapter')\n", encoding="utf-8")
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
            self.assertEqual(
                adapter_runtime.regular_pinned_file(
                    str(artifact.resolve()), digest, "test adapter"
                ), artifact.resolve(),
            )
            artifact.write_text("print('drift')\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "digest changed"):
                adapter_runtime.regular_pinned_file(
                    str(artifact.resolve()), digest, "test adapter"
                )
            with self.assertRaises(ValueError):
                adapter_runtime.validate_artifact_pins([
                    {"path": "same", "sha256": "0" * 64},
                    {"path": "same", "sha256": "1" * 64},
                ], "test")

            base_environment = {
                name: os.environ[name] for name in ("SystemRoot", "WINDIR")
                if name in os.environ
            }
            with mock.patch.dict(os.environ, {
                **base_environment, "PDR_REQUIRED": "required",
                "PDR_OPTIONAL": "optional", "PDR_UNRELATED": "hidden",
            }, clear=True):
                environment = adapter_runtime.isolated_environment(
                    ["PDR_REQUIRED"], optional=["PDR_OPTIONAL"], label="test"
                )
            self.assertEqual(environment["PDR_REQUIRED"], "required")
            self.assertEqual(environment["PDR_OPTIONAL"], "optional")
            self.assertNotIn("PDR_UNRELATED", environment)
            with mock.patch.dict(os.environ, base_environment, clear=True):
                with self.assertRaisesRegex(ValueError, "environment is unset"):
                    adapter_runtime.isolated_environment(
                        ["PDR_REQUIRED"], label="test"
                    )

            echo_code = (
                "import json,os,sys; r=json.load(sys.stdin); "
                "print(json.dumps({'request':r,'visible':sorted(k for k in "
                "os.environ if k.startswith('PDR_'))}))"
            )
            response = adapter_runtime.invoke_json(
                [sys.executable, "-c", echo_code], {"value": 7},
                environment=environment, timeout_seconds=2,
                max_response_bytes=4096, label="test adapter",
            )
            self.assertEqual(response["request"], {"value": 7})
            self.assertEqual(
                response["visible"], ["PDR_OPTIONAL", "PDR_REQUIRED"]
            )

            leaking_code = (
                "import sys; sys.stdin.read(); "
                "print('stderr-secret-marker',file=sys.stderr); sys.exit(2)"
            )
            with self.assertRaises(RuntimeError) as redacted:
                adapter_runtime.invoke_json(
                    [sys.executable, "-c", leaking_code], {},
                    environment=base_environment, timeout_seconds=2,
                    max_response_bytes=1024, label="test adapter",
                )
            self.assertNotIn("stderr-secret-marker", str(redacted.exception))
            with self.assertRaises(RuntimeError) as diagnostic:
                adapter_runtime.invoke_json(
                    [sys.executable, "-c", leaking_code], {},
                    environment=base_environment, timeout_seconds=2,
                    max_response_bytes=1024, label="test adapter",
                    expose_stderr=True,
                )
            self.assertIn("stderr-secret-marker", str(diagnostic.exception))

            with self.assertRaisesRegex(RuntimeError, "timed out"):
                adapter_runtime.invoke_json(
                    [sys.executable, "-c",
                     "import sys,time; sys.stdin.read(); time.sleep(2)"], {},
                    environment=base_environment, timeout_seconds=1,
                    max_response_bytes=1024, label="test adapter",
                )
            with self.assertRaisesRegex(
                    ValueError,
                    r"response (?:exceeds policy|size is outside policy)"):
                adapter_runtime.invoke_json(
                    [sys.executable, "-c",
                     "import sys; sys.stdin.read(); print('x'*8192)"], {},
                    environment=base_environment, timeout_seconds=2,
                    max_response_bytes=1024, label="test adapter",
                )
            with self.assertRaisesRegex(ValueError, "invalid JSON"):
                adapter_runtime.invoke_json(
                    [sys.executable, "-c",
                     "import sys; sys.stdin.read(); print('not-json')"], {},
                    environment=base_environment, timeout_seconds=2,
                    max_response_bytes=1024, label="test adapter",
                )

        config = {
            "protocolMajor": 1, "minimumProtocolMinor": 1,
            "requiredCapabilities": ["bounded", "stable"],
        }
        manifest = {
            "adapterId": "adapter", "implementationId": "implementation",
            "protocolMajor": 1, "protocolMinor": 1,
            "capabilities": ["bounded", "stable"], "requestId": "first",
        }
        adapter_runtime.enforce_capability_policy(config, manifest, "test adapter")
        first = adapter_runtime.capability_digest(manifest, "adapterId")
        manifest["requestId"] = "second"
        self.assertEqual(
            first, adapter_runtime.capability_digest(manifest, "adapterId")
        )
        with self.assertRaisesRegex(ValueError, "required capabilities"):
            adapter_runtime.enforce_capability_policy(
                dict(config, requiredCapabilities=["missing"]), manifest,
                "test adapter",
            )
        self_check = subprocess.run(
            [sys.executable, str(TOOLS / "team_contract_adapter_runtime.py"),
             "--self-check"], check=False, capture_output=True, text=True,
            timeout=10,
        )
        self.assertEqual(self_check.returncode, 0, self_check.stderr)
        self.assertIn("PDR_ADAPTER_RUNTIME_SELF_CHECK_PASS", self_check.stdout)
        print(
            "PDR_ADAPTER_RUNTIME_PASS pins=1 environment=1 isolation=1 "
            "timeout=1 responseBound=1 redaction=1 stderrOptIn=1 json=1 "
            "capabilityPolicy=1 stableDigest=1 selfCheck=1"
        )


if __name__ == "__main__":
    unittest.main()
