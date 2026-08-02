import json
import os
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
    closed_call = 2
    expected_authorization = None

    def do_GET(self):
        if (type(self).expected_authorization and
                self.headers.get("Authorization") != type(self).expected_authorization):
            self.send_error(401)
            return
        type(self).calls += 1
        count = type(self).calls
        opened = count != type(self).closed_call
        payload = {"protocols": [{
            "id": "factory-broker", "type": "mqtt", "required": True,
            "open": opened, "desiredOpen": True,
            "diagnostics": {
                "successfulOperations": count * 2,
                "failedOperations": 0,
                "reconnectAttempts": 1 if count > 1 else 0,
                "sentMessages": count, "receivedMessages": count,
                "sentBytes": count * 8, "receivedBytes": count * 9,
                "timeouts": 0, "handlerFailures": 0, "lastError": "",
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


class ProtocolAcceptanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def run_tool(self, *extra, environment=None):
        with tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary) / "evidence.json"
            command = [
                sys.executable, str(ROOT / "tools/protocol_acceptance.py"),
                "--url", f"http://127.0.0.1:{self.server.server_port}/api/v1/protocols",
                "--protocol-id", "factory-broker", "--protocol-type", "mqtt",
                "--duration", "0.12", "--interval", "0.02",
                "--report", str(report), *extra,
            ]
            values = os.environ.copy()
            if environment:
                values.update(environment)
            completed = subprocess.run(
                command, check=False, capture_output=True, text=True, env=values)
            return completed, json.loads(report.read_text(encoding="utf-8"))

    def test_collects_traffic_reconnect_and_recovery_evidence(self):
        Handler.calls = 0
        Handler.closed_call = 2
        Handler.expected_authorization = "Bearer acceptance-secret"
        completed, evidence = self.run_tool(
            "--minimum-success-delta", "2", "--minimum-reconnect-delta", "1",
            "--minimum-sent-message-delta", "1",
            "--minimum-received-message-delta", "1",
            "--minimum-sent-byte-delta", "8",
            "--minimum-received-byte-delta", "9",
            "--maximum-consecutive-closed-samples", "1",
            "--authorization-environment", "PDR_TEST_PROTOCOL_AUTH",
            environment={"PDR_TEST_PROTOCOL_AUTH": "Bearer acceptance-secret"})
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertTrue(evidence["passed"])
        self.assertEqual(evidence["maximumConsecutiveClosedSamplesObserved"], 1)
        self.assertGreaterEqual(evidence["deltas"]["sentBytes"], 8)
        self.assertEqual(
            evidence["transportSecurity"]["authorizationEnvironment"],
            "PDR_TEST_PROTOCOL_AUTH")
        self.assertNotIn("acceptance-secret", json.dumps(evidence))

    def test_rejects_a_protocol_that_stays_closed(self):
        Handler.calls = 0
        Handler.closed_call = 999
        Handler.expected_authorization = None
        completed, evidence = self.run_tool("--minimum-reconnect-delta", "99")
        self.assertNotEqual(completed.returncode, 0)
        self.assertFalse(evidence["passed"])
        self.assertIn("reconnectAttempts delta below minimum", evidence["failures"])


if __name__ == "__main__":
    unittest.main()
