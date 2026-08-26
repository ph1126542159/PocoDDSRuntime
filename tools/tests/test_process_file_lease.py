#!/usr/bin/env python3

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TOOLS = Path(__file__).resolve().parents[1]
LEASE_TOOL = TOOLS / "process_file_lease.py"
sys.path.insert(0, str(TOOLS))

import process_file_lease as lease_tool


class ProcessFileLeaseTests(unittest.TestCase):
    def paths(self, root: Path) -> tuple[Path, Path]:
        return root / "writer.lock", root / "writer.epoch.json"

    def lease(self, root: Path) -> lease_tool.ProcessFileLease:
        lock, epoch = self.paths(root)
        return lease_tool.ProcessFileLease(
            lock, epoch, "unit-writer", {"operation": "unit-test"}
        )

    def test_owner_status_epoch_and_fencing_are_durable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.lease(root) as first:
                self.assertEqual(first.epoch, 1)
                first.assert_current()
                status = lease_tool.inspect_lease(
                    *self.paths(root), "unit-writer"
                )
                self.assertTrue(status["healthy"])
                self.assertTrue(status["active"])
                self.assertEqual(status["epoch"], 1)
                self.assertEqual(status["owner"]["leaseId"], first.owner["leaseId"])
                with self.assertRaises(lease_tool.LeaseBusyError):
                    self.lease(root).acquire()

                epoch_path = self.paths(root)[1]
                forged = json.loads(epoch_path.read_text(encoding="utf-8"))
                forged["epoch"] = 2
                epoch_path.write_text(json.dumps(forged) + "\n", encoding="utf-8")
                with self.assertRaises(lease_tool.LeaseFencedError):
                    first.assert_current()

            with self.lease(root) as successor:
                self.assertEqual(successor.epoch, 3)
                successor.assert_current()
            released = lease_tool.inspect_lease(*self.paths(root), "unit-writer")
            self.assertTrue(released["healthy"])
            self.assertFalse(released["active"])
            self.assertEqual(released["epoch"], 3)
            print("PROCESS_FILE_LEASE_FENCING_PASS fencing=1 epoch=3")

    def test_operating_system_releases_abandoned_process_lease(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock, epoch = self.paths(root)
            helper = (
                "import sys,time;from pathlib import Path;"
                f"sys.path.insert(0,{str(TOOLS)!r});"
                "import process_file_lease as p;"
                "d=Path(sys.argv[1]);"
                "l=p.ProcessFileLease(d/'writer.lock',d/'writer.epoch.json',"
                "'unit-writer',{'operation':'crash-test'});"
                "l.acquire();print(l.epoch,flush=True);time.sleep(120)"
            )
            process = subprocess.Popen(
                [sys.executable, "-c", helper, str(root)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            try:
                line = process.stdout.readline().strip()
                self.assertEqual(line, "1", process.stderr.read() if process.poll() else "")
                active = lease_tool.inspect_lease(lock, epoch, "unit-writer")
                self.assertTrue(active["active"])
                with self.assertRaises(lease_tool.LeaseBusyError):
                    self.lease(root).acquire()
            finally:
                process.kill()
                process.wait(timeout=10)
                if process.stdout is not None:
                    process.stdout.close()
                if process.stderr is not None:
                    process.stderr.close()

            with self.lease(root) as recovered:
                self.assertEqual(recovered.epoch, 2)
                self.assertEqual(recovered.owner["details"]["operation"], "unit-test")
            final = lease_tool.inspect_lease(lock, epoch, "unit-writer")
            self.assertTrue(final["healthy"])
            self.assertFalse(final["active"])
            print("PROCESS_FILE_LEASE_CRASH_PASS contention=1 crashRelease=1")

    def test_corrupt_epoch_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.lease(root):
                pass
            self.paths(root)[1].write_text("{}\n", encoding="utf-8")
            status = lease_tool.inspect_lease(*self.paths(root), "unit-writer")
            self.assertFalse(status["healthy"])
            with self.assertRaises(ValueError):
                self.lease(root).acquire()
            print("PROCESS_FILE_LEASE_CORRUPTION_PASS corruptionFailClosed=1")

    def test_standalone_status_cli_emits_machine_readable_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = root / "status.json"
            result = subprocess.run([
                sys.executable, str(LEASE_TOOL), "status",
                "--lock", str(root / "writer.lock"),
                "--epoch", str(root / "writer.epoch.json"),
                "--lease-name", "unit-writer", "--require-free",
                "--report", str(report),
            ], check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            document = json.loads(report.read_bytes())
            self.assertTrue(document["healthy"])
            self.assertFalse(document["active"])
            self.assertEqual(document["epoch"], 0)

    @classmethod
    def tearDownClass(cls):
        print("PROCESS_FILE_LEASE_RECOVERY_PASS")


if __name__ == "__main__":
    unittest.main()
