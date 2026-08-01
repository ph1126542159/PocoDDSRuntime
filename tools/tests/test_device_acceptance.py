import json
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class Handler(BaseHTTPRequestHandler):
    calls = 0

    def do_GET(self):
        type(self).calls += 1
        count = type(self).calls
        payload = {"devices": [{
            "id": "reference", "state": "ready", "sequence": count,
            "diagnostics": {
                "successfulOperations": count * 2,
                "failedOperations": 0,
                "reconnectAttempts": 1 if count > 1 else 0,
                "consecutiveFailures": 0,
            },
        }]}
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


class DeviceAcceptanceTest(unittest.TestCase):
    def test_collects_counter_deltas_and_reconnect(self):
        Handler.calls = 0
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temporary:
                report = Path(temporary) / "evidence.json"
                completed = subprocess.run([
                    sys.executable, str(ROOT / "tools/device_acceptance.py"),
                    "--url", f"http://127.0.0.1:{server.server_port}/api/v1/devices",
                    "--device-id", "reference", "--duration", "0.12",
                    "--interval", "0.02", "--minimum-success-delta", "2",
                    "--minimum-reconnect-delta", "1", "--report", str(report),
                ], check=False)
                evidence = json.loads(report.read_text(encoding="utf-8"))
                self.assertEqual(completed.returncode, 0)
                self.assertTrue(evidence["passed"])
                self.assertGreaterEqual(evidence["deltas"]["successfulOperations"], 2)
                self.assertGreaterEqual(evidence["deltas"]["reconnectAttempts"], 1)
                self.assertFalse(evidence["probeErrors"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
