#!/usr/bin/env python3

from __future__ import annotations

import json
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


class SoakHealthTest(unittest.TestCase):
    def test_health_probe_is_recorded_and_enforced(self) -> None:
        port = free_port()
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "soak.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "soak_runner.py"),
                    "--duration", "0.5",
                    "--interval", "0.1",
                    "--warmup", "0.5",
                    "--health-url", f"http://127.0.0.1:{port}/",
                    "--health-timeout", "0.5",
                    "--output", str(report),
                    "--", sys.executable, "-m", "http.server", str(port),
                    "--bind", "127.0.0.1",
                ],
                cwd=directory,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            evidence = json.loads(report.read_text(encoding="utf-8"))
            self.assertTrue(evidence["passed"])
            self.assertEqual(evidence["healthFailureCount"], 0)
            self.assertGreater(evidence["sampleCount"], 0)
            self.assertTrue(all(sample.get("healthy") for sample in evidence["samples"][:-1]))


if __name__ == "__main__":
    unittest.main()
