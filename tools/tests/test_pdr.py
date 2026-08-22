import json
import hashlib
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


TOOL = Path(__file__).resolve().parents[1] / "pdr.py"
PDR_SPEC = importlib.util.spec_from_file_location("pdr_tool_under_test", TOOL)
assert PDR_SPEC and PDR_SPEC.loader
PDR = importlib.util.module_from_spec(PDR_SPEC)
PDR_SPEC.loader.exec_module(PDR)


class PdrToolTests(unittest.TestCase):
    @staticmethod
    def write_snapshot(path: Path, field: str, records: list[dict]) -> str:
        content = json.dumps(
            records, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        snapshot = {
            "schemaVersion": 2,
            "contentSha256": hashlib.sha256(content).hexdigest(),
            field: records,
        }
        path.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @classmethod
    def create_recovery_point_fixture(cls, root: Path,
                                      include_rotated_audit: bool = True) -> tuple[Path, dict]:
        source = root / "source"
        source.mkdir()
        tasks = source / "management-tasks.json"
        ledger = source / "management-idempotency.json"
        configuration = source / "pdr-runtime.properties"
        audit = source / "management-audit.jsonl"
        cls.write_snapshot(tasks, "tasks", [{"id": "saved-task"}])
        cls.write_snapshot(ledger, "requests", [{"requestId": "saved-request"}])
        configuration.write_text("state=saved\n", encoding="utf-8")
        audit.write_text('{"event":"saved-current"}\n', encoding="utf-8")
        if include_rotated_audit:
            Path(str(audit) + ".1").write_text(
                '{"event":"saved-previous"}\n', encoding="utf-8"
            )
        report = root / "fixture-backup.json"
        result = subprocess.run([
            sys.executable, str(TOOL), "persistence", "backup",
            "--tasks", str(tasks), "--idempotency", str(ledger),
            "--configuration", str(configuration), "--management-audit", str(audit),
            "--output", str(root / "recovery-points"), "--operator", "unit-test",
            "--confirm-runtime-stopped", "--report", str(report),
        ], check=False, capture_output=True, text=True)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        evidence = json.loads(report.read_text(encoding="utf-8"))
        return Path(evidence["path"]), evidence

    @staticmethod
    def write_restore_transaction_evidence(root: Path,
                                           audit_complete: bool = True) -> tuple[str, Path, Path]:
        restore_id = "restore-evidence-id"
        manifest_sha = "a" * 64
        report = root / "restore-transaction.json"
        audit = root / "restore-operations.jsonl"
        report.write_text(json.dumps({
            "operation": "persistence-restore-recovery-point", "restoreId": restore_id,
            "recoveryPointId": "recovery-point-id", "manifestSha256": manifest_sha,
            "operator": "restore-operator", "transactionMode": "staged-replace-with-rollback",
            "passed": True,
        }), encoding="utf-8")
        events = [{
            "event": "restore-started", "restoreId": restore_id,
            "manifestSha256": manifest_sha,
        }]
        if audit_complete:
            events.append({"event": "restore-finished", "restoreId": restore_id, "passed": True})
        audit.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
        return restore_id, report, audit

    @staticmethod
    def healthy_restore_endpoint(url: str, _headers: dict, _timeout: float,
                                 tasks=None, idempotency_interrupted: int = 0):
        if url.endswith("/health/live"):
            return {"url": url, "status": 200, "json": {"live": True}}
        if url.endswith("/health/ready"):
            return {"url": url, "status": 200, "json": {"ready": True}}
        if url.endswith("/health/detail"):
            return {"url": url, "status": 200, "json": {"ready": True, "status": "UP"}}
        return {"url": url, "status": 200, "json": {
            "tasks": tasks or [],
            "persistence": {"healthy": True, "recoveryRequired": False,
                            "schemaVersion": 2, "integrityAlgorithm": "SHA-256"},
            "idempotency": {"healthy": True, "recoveryRequired": False,
                            "schemaVersion": 2, "integrityAlgorithm": "SHA-256",
                            "interrupted": idempotency_interrupted},
        }}

    @staticmethod
    def create_doctor_layout(root: Path, prefix: Path) -> None:
        (root / "application").mkdir(parents=True)
        (root / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.24)\n")
        package = prefix / "lib" / "cmake" / "PocoDDSRuntime"
        package.mkdir(parents=True)
        (package / "PocoDDSRuntimeConfig.cmake").write_text("# test package\n")
        (package / "PocoDDSRuntimeTargets.cmake").write_text(
            "add_library(PocoDDS::SDK INTERFACE IMPORTED)\n"
        )
        (prefix / "cmake").mkdir(parents=True)
        (prefix / "cmake" / "PocoConfig.cmake").write_text("# test Poco\n")

    def test_generates_all_supported_module_kinds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for kind in ("module", "service", "device", "workflow", "bundle", "plugin", "subprocess"):
                name = kind.title() + "Example"
                result = subprocess.run(
                    [sys.executable, str(TOOL), "new", kind, name, "--output", str(root)],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                module = root / name
                self.assertTrue((module / "CMakeLists.txt").is_file())
                if kind in ("bundle", "plugin"):
                    source_name = "BundleActivator.cpp"
                elif kind == "subprocess":
                    source_name = "main.cpp"
                else:
                    source_name = f"{name}.cpp"
                self.assertTrue((module / f"src/{source_name}").is_file())
                if kind != "subprocess":
                    self.assertTrue((module / f"tests/{name}Smoke.cpp").is_file())
                if kind in ("bundle", "plugin"):
                    cmake = (module / "CMakeLists.txt").read_text(encoding="utf-8")
                    specification = (module / f"{name}.bndlspec").read_text(encoding="utf-8")
                    self.assertIn("COMPONENTS Plugins", cmake)
                    self.assertIn("pdr_add_osp_bundle", cmake)
                    self.assertIn(f"pdr.plugin.{name.lower()}", specification)
                if kind == "device":
                    header = (module / f"include/PocoDDS/Generated/{name}/{name}.h").read_text(
                        encoding="utf-8"
                    )
                    source = (module / f"src/{name}.cpp").read_text(encoding="utf-8")
                    readme = (module / "README.md").read_text(encoding="utf-8")
                    self.assertIn("public PocoDDS::Devices::Device", header)
                    self.assertIn("public PocoDDS::Devices::DiagnosticDevice", header)
                    self.assertIn("DeviceSnapshot", header)
                    self.assertIn('operation != "ping"', source)
                    self.assertIn("successfulOperations", source)
                    self.assertIn(f"pdr.{name.lower()}.count = 1", readme)
                if kind == "subprocess":
                    cmake = (module / "CMakeLists.txt").read_text(encoding="utf-8")
                    entry = (module / "config/pdr-subprocess-entry.properties").read_text(
                        encoding="utf-8"
                    )
                    self.assertIn("RUNTIME_OUTPUT_DIRECTORY", cmake)
                    self.assertIn("subprocess.N.name", entry)

    def test_generates_robotics_specific_extensions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expectations = {
                "robot-module": ("src/Plugin.cpp", "RobotBusinessModule"),
                "robot-hardware-adapter": (
                    "include/PocoDDS/Generated/DriveHardware/DriveHardware.h", "HardwareInterface"
                ),
                "robot-simulation-adapter": (
                    "include/PocoDDS/Generated/WorldSimulation/WorldSimulation.h",
                    "SimulationAdapter",
                ),
                "robot-process": ("src/main.cpp", "PDR_ROBOT_VISION_WORKER_READY"),
                "ros2-node": ("package.xml", "ament_cmake"),
            }
            names = {
                "robot-module": "ChargingModule",
                "robot-hardware-adapter": "DriveHardware",
                "robot-simulation-adapter": "WorldSimulation",
                "robot-process": "VisionWorker",
                "ros2-node": "MissionGateway",
            }
            for kind, (relative, marker) in expectations.items():
                name = names[kind]
                result = subprocess.run(
                    [sys.executable, str(TOOL), "new", kind, name, "--output", str(root)],
                    check=False, capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                content = (root / name / relative).read_text(encoding="utf-8")
                self.assertIn(marker, content)
                if kind == "ros2-node":
                    package_xml = (root / name / "package.xml").read_text(encoding="utf-8")
                    launch = next((root / name / "launch").glob("*.launch.py")).read_text(
                        encoding="utf-8"
                    )
                    self.assertIn("ament_index_python", package_xml)
                    self.assertIn("get_package_share_directory", launch)
                    self.assertNotIn('parameters=["config/runtime.yaml"]', launch)

    def test_rejects_invalid_name(self):
        result = subprocess.run(
            [sys.executable, str(TOOL), "new", "service", "bad-name"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_verify_records_missing_module_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.json"
            result = subprocess.run(
                [sys.executable, str(TOOL), "verify", str(Path(directory) / "missing"),
                 "--report", str(report)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2)
            evidence = json.loads(report.read_text(encoding="utf-8"))
            self.assertFalse(evidence["passed"])
            self.assertIn("CMakeLists.txt not found", evidence["error"])
            self.assertEqual(evidence["stages"], [])

    def test_verify_records_failed_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            module = Path(directory) / "module"
            module.mkdir()
            (module / "CMakeLists.txt").write_text(
                "cmake_minimum_required(VERSION 3.24)\n", encoding="utf-8"
            )
            report = Path(directory) / "report.json"
            result = subprocess.run(
                [sys.executable, str(TOOL), "verify", str(module),
                 "--cmake", sys.executable, "--ctest", sys.executable,
                 "--report", str(report)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2)
            evidence = json.loads(report.read_text(encoding="utf-8"))
            self.assertFalse(evidence["passed"])
            self.assertEqual(len(evidence["stages"]), 1)
            self.assertEqual(evidence["stages"][0]["name"], "configure")
            self.assertFalse(evidence["stages"][0]["passed"])

    def test_doctor_validates_selected_install_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "source"
            prefix = Path(directory) / "install"
            self.create_doctor_layout(root, prefix)
            report = Path(directory) / "doctor.json"
            result = subprocess.run(
                [sys.executable, str(TOOL), "doctor", "--root", str(root),
                 "--prefix", str(prefix), "--report", str(report)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            evidence = json.loads(report.read_text(encoding="utf-8"))
            self.assertTrue(evidence["passed"])
            self.assertEqual({item["id"] for item in evidence["checks"]}, {
                "layout", "python", "cmake", "ctest", "sdk-package",
                "sdk-target", "poco-package",
            })

    def test_installed_doctor_auto_detects_its_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory) / "package"
            self.create_doctor_layout(Path(directory) / "unused-source", prefix)
            dependency_prefix = Path(directory) / "dependencies"
            (dependency_prefix / "cmake").mkdir(parents=True)
            (dependency_prefix / "cmake" / "PocoConfig.cmake").write_text(
                "# split Poco package\n", encoding="utf-8"
            )
            (prefix / "cmake" / "PocoConfig.cmake").unlink()
            bin_dir = prefix / "bin"
            bin_dir.mkdir()
            installed_tool = bin_dir / "pdr.py"
            installed_tool.write_text(TOOL.read_text(encoding="utf-8"), encoding="utf-8")
            report = Path(directory) / "installed-doctor.json"
            result = subprocess.run(
                [sys.executable, str(installed_tool), "doctor",
                 "--dependency-prefix", str(dependency_prefix), "--report", str(report)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            evidence = json.loads(report.read_text(encoding="utf-8"))
            self.assertTrue(evidence["passed"])
            self.assertEqual(Path(evidence["prefix"]), prefix)
            self.assertEqual(Path(evidence["dependencyPrefix"]), dependency_prefix)
            layout = next(item for item in evidence["checks"] if item["id"] == "layout")
            self.assertIn("installed:", layout["detail"])

    def test_doctor_accepts_unix_poco_package_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "source"
            prefix = Path(directory) / "install"
            self.create_doctor_layout(root, prefix)
            windows_layout = prefix / "cmake" / "PocoConfig.cmake"
            windows_layout.unlink()
            unix_layout = prefix / "lib" / "cmake" / "Poco" / "PocoConfig.cmake"
            unix_layout.parent.mkdir(parents=True)
            unix_layout.write_text("# Unix Poco package\n", encoding="utf-8")
            report = Path(directory) / "doctor.json"
            result = subprocess.run(
                [sys.executable, str(TOOL), "doctor", "--root", str(root),
                 "--prefix", str(prefix), "--report", str(report)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            evidence = json.loads(report.read_text(encoding="utf-8"))
            poco = next(item for item in evidence["checks"]
                        if item["id"] == "poco-package")
            self.assertEqual(Path(poco["detail"]), unix_layout)

    def test_doctor_failure_report_contains_remedies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "source"
            root.mkdir()
            report = Path(directory) / "doctor.json"
            result = subprocess.run(
                [sys.executable, str(TOOL), "doctor", "--root", str(root),
                 "--prefix", str(Path(directory) / "missing"), "--report", str(report)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1)
            evidence = json.loads(report.read_text(encoding="utf-8"))
            self.assertFalse(evidence["passed"])
            failed = [item for item in evidence["checks"] if not item["passed"]]
            self.assertGreaterEqual(len(failed), 4)
            self.assertTrue(all(item.get("remedy") for item in failed))

    def test_validate_config_reports_missing_checker(self):
        with tempfile.TemporaryDirectory() as directory:
            configuration = Path(directory) / "runtime.properties"
            configuration.write_text("osp.web.server.port = 9080\n", encoding="utf-8")
            report = Path(directory) / "validation.json"
            result = subprocess.run(
                [sys.executable, str(TOOL), "validate-config", str(configuration),
                 "--prefix", str(Path(directory) / "missing"), "--report", str(report)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2)
            evidence = json.loads(report.read_text(encoding="utf-8"))
            self.assertFalse(evidence["passed"])
            self.assertIn("configuration checker not found", evidence["error"])

    def test_persistence_inspect_reports_current_and_previous_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            current = Path(directory) / "management-tasks.json"
            previous = Path(str(current) + ".previous")
            self.write_snapshot(current, "tasks", [{"id": "current"}])
            previous_hash = self.write_snapshot(previous, "tasks", [{"id": "previous"}])
            report = Path(directory) / "inspect.json"
            result = subprocess.run(
                [sys.executable, str(TOOL), "persistence", "inspect", str(current),
                 "--kind", "tasks", "--report", str(report)],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            evidence = json.loads(report.read_text(encoding="utf-8"))
            self.assertTrue(evidence["passed"])
            self.assertTrue(evidence["recoveryCandidateAvailable"])
            self.assertEqual(evidence["previous"]["fileSha256"], previous_hash)

    def test_persistence_recovery_is_offline_hash_bound_and_audited(self):
        with tempfile.TemporaryDirectory() as directory:
            current = Path(directory) / "management-idempotency.json"
            previous = Path(str(current) + ".previous")
            current.write_text("{corrupt", encoding="utf-8")
            current_hash = hashlib.sha256(current.read_bytes()).hexdigest()
            previous_hash = self.write_snapshot(
                previous, "requests", [{"requestId": "known-complete"}]
            )
            report = Path(directory) / "recover.json"
            base = [
                sys.executable, str(TOOL), "persistence", "recover", str(current),
                "--kind", "idempotency", "--operator", "unit-test",
                "--expected-current-sha256", current_hash,
                "--expected-previous-sha256", previous_hash,
                "--report", str(report),
            ]
            refused = subprocess.run(base, check=False, capture_output=True, text=True)
            self.assertEqual(refused.returncode, 2)
            self.assertIn("--confirm-runtime-stopped", refused.stdout)
            recovered = subprocess.run(
                [*base, "--confirm-runtime-stopped"],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(recovered.returncode, 0, recovered.stdout + recovered.stderr)
            evidence = json.loads(report.read_text(encoding="utf-8"))
            self.assertTrue(evidence["passed"])
            self.assertEqual(hashlib.sha256(current.read_bytes()).hexdigest(), previous_hash)
            archive = Path(evidence["archivePath"])
            self.assertEqual(archive.read_text(encoding="utf-8"), "{corrupt")
            audit_lines = Path(evidence["auditPath"]).read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(audit_lines), 2)
            self.assertFalse(json.loads(audit_lines[0])["passed"])
            self.assertTrue(json.loads(audit_lines[1])["passed"])

    def test_persistence_recovery_rejects_changed_or_healthy_current(self):
        with tempfile.TemporaryDirectory() as directory:
            current = Path(directory) / "management-tasks.json"
            previous = Path(str(current) + ".previous")
            current_hash = self.write_snapshot(current, "tasks", [{"id": "new"}])
            previous_hash = self.write_snapshot(previous, "tasks", [{"id": "old"}])
            command = [
                sys.executable, str(TOOL), "persistence", "recover", str(current),
                "--kind", "tasks", "--operator", "unit-test",
                "--expected-current-sha256", current_hash,
                "--expected-previous-sha256", previous_hash,
                "--confirm-runtime-stopped",
            ]
            healthy = subprocess.run(command, check=False, capture_output=True, text=True)
            self.assertEqual(healthy.returncode, 2)
            self.assertIn("current snapshot is healthy", healthy.stdout)
            current.write_text("{changed", encoding="utf-8")
            changed = subprocess.run(command, check=False, capture_output=True, text=True)
            self.assertEqual(changed.returncode, 2)
            self.assertIn("changed since inspection", changed.stdout)

    def test_persistence_recovery_detects_change_during_preparation(self):
        with tempfile.TemporaryDirectory() as directory:
            current = Path(directory) / "management-tasks.json"
            previous = Path(str(current) + ".previous")
            current.write_text("{corrupt", encoding="utf-8")
            current_hash = hashlib.sha256(current.read_bytes()).hexdigest()
            previous_hash = self.write_snapshot(previous, "tasks", [{"id": "old"}])
            arguments = PDR.parser().parse_args([
                "persistence", "recover", str(current), "--kind", "tasks",
                "--operator", "unit-test", "--confirm-runtime-stopped",
                "--expected-current-sha256", current_hash,
                "--expected-previous-sha256", previous_hash,
            ])
            real_copy = PDR.shutil.copy2

            def copy_and_mutate(source, destination):
                result = real_copy(source, destination)
                if str(destination).endswith(".recovery.new"):
                    current.write_text("{concurrent-change", encoding="utf-8")
                return result

            with mock.patch.object(PDR.shutil, "copy2", side_effect=copy_and_mutate), \
                    mock.patch("builtins.print"):
                result = PDR.recover_persistence(arguments)
            self.assertEqual(result, 2)
            self.assertEqual(current.read_text(encoding="utf-8"), "{concurrent-change")
            self.assertFalse(Path(str(current) + ".recovery.new").exists())
            audit = Path(str(current) + ".recovery-audit.jsonl")
            event = json.loads(audit.read_text(encoding="utf-8").splitlines()[-1])
            self.assertIn("changed while preparing recovery", event["error"])

    def test_persistence_backup_is_atomic_complete_and_independently_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tasks = root / "management-tasks.json"
            ledger = root / "management-idempotency.json"
            configuration = root / "pdr-runtime.properties"
            audit = root / "management-audit.jsonl"
            output = root / "recovery-points"
            self.write_snapshot(tasks, "tasks", [{"id": "task-1"}])
            self.write_snapshot(ledger, "requests", [{"requestId": "request-1"}])
            configuration.write_text("osp.web.server.port = 9080\n", encoding="utf-8")
            audit.write_text('{"event":"current"}\n', encoding="utf-8")
            Path(str(audit) + ".1").write_text('{"event":"previous"}\n', encoding="utf-8")
            report = root / "backup.json"
            command = [
                sys.executable, str(TOOL), "persistence", "backup",
                "--tasks", str(tasks), "--idempotency", str(ledger),
                "--configuration", str(configuration), "--management-audit", str(audit),
                "--output", str(output), "--operator", "unit-test", "--report", str(report),
            ]
            refused = subprocess.run(command, check=False, capture_output=True, text=True)
            self.assertEqual(refused.returncode, 2)
            self.assertFalse(output.exists())
            created = subprocess.run(
                [*command, "--confirm-runtime-stopped"],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            evidence = json.loads(report.read_text(encoding="utf-8"))
            recovery_point = Path(evidence["path"])
            self.assertTrue(evidence["passed"])
            self.assertEqual(len(list(output.iterdir())), 1)
            self.assertFalse(any(path.name.endswith(".new") for path in output.iterdir()))
            roles = {entry["role"] for entry in evidence["verification"]["files"]}
            self.assertEqual(roles, {
                "configuration", "management-tasks", "management-idempotency",
                "management-audit", "management-audit-previous",
            })
            verified = subprocess.run(
                [sys.executable, str(TOOL), "persistence", "verify-recovery-point",
                 str(recovery_point)],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
            (recovery_point / "management/management-audit.jsonl").write_text(
                "tampered\n", encoding="utf-8"
            )
            tampered = subprocess.run(
                [sys.executable, str(TOOL), "persistence", "verify-recovery-point",
                 str(recovery_point)],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(tampered.returncode, 1)
            self.assertIn("verification failed", tampered.stdout)
            (recovery_point / "management/management-audit.jsonl").write_text(
                '{"event":"current"}\n', encoding="utf-8"
            )
            unexpected_path = recovery_point / "unexpected.txt"
            unexpected_path.write_text("unexpected", encoding="utf-8")
            unexpected = subprocess.run(
                [sys.executable, str(TOOL), "persistence", "verify-recovery-point",
                 str(recovery_point)], check=False, capture_output=True, text=True,
            )
            self.assertEqual(unexpected.returncode, 1)
            self.assertIn("unexpected recovery artifact", unexpected.stdout)
            unexpected_path.unlink()
            configuration_copy = recovery_point / "runtime/pdr-runtime.properties"
            held_configuration = recovery_point / "runtime/pdr-runtime.properties.held"
            configuration_copy.rename(held_configuration)
            missing = subprocess.run(
                [sys.executable, str(TOOL), "persistence", "verify-recovery-point",
                 str(recovery_point)], check=False, capture_output=True, text=True,
            )
            self.assertEqual(missing.returncode, 1)
            self.assertIn("missing recovery artifact", missing.stdout)
            held_configuration.rename(configuration_copy)
            manifest_path = recovery_point / "recovery-manifest.json"
            original_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_document = json.loads(json.dumps(original_manifest))
            manifest_document["files"][0]["path"] = "../escape"
            manifest_path.write_text(
                json.dumps(manifest_document, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8", newline="\n",
            )
            (recovery_point / "recovery-manifest.sha256").write_text(
                hashlib.sha256(manifest_path.read_bytes()).hexdigest() + "\n",
                encoding="ascii",
            )
            traversal = subprocess.run(
                [sys.executable, str(TOOL), "persistence", "verify-recovery-point",
                 str(recovery_point)], check=False, capture_output=True, text=True,
            )
            self.assertEqual(traversal.returncode, 1)
            self.assertIn("unsafe recovery-point path", traversal.stdout)
            original_manifest["files"].append(dict(original_manifest["files"][0]))
            manifest_path.write_text(
                json.dumps(original_manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8", newline="\n",
            )
            (recovery_point / "recovery-manifest.sha256").write_text(
                hashlib.sha256(manifest_path.read_bytes()).hexdigest() + "\n",
                encoding="ascii",
            )
            duplicate = subprocess.run(
                [sys.executable, str(TOOL), "persistence", "verify-recovery-point",
                 str(recovery_point)], check=False, capture_output=True, text=True,
            )
            self.assertEqual(duplicate.returncode, 1)
            self.assertIn("duplicate recovery manifest entry", duplicate.stdout)

    def test_persistence_backup_rejects_invalid_snapshot_before_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tasks = root / "management-tasks.json"
            ledger = root / "management-idempotency.json"
            configuration = root / "pdr-runtime.properties"
            audit = root / "management-audit.jsonl"
            tasks.write_text("{corrupt", encoding="utf-8")
            self.write_snapshot(ledger, "requests", [])
            configuration.write_text("key=value\n", encoding="utf-8")
            audit.write_text("", encoding="utf-8")
            output = root / "recovery-points"
            result = subprocess.run([
                sys.executable, str(TOOL), "persistence", "backup",
                "--tasks", str(tasks), "--idempotency", str(ledger),
                "--configuration", str(configuration), "--management-audit", str(audit),
                "--output", str(output), "--operator", "unit-test",
                "--confirm-runtime-stopped",
            ], check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("required recovery snapshot is invalid", result.stdout)
            self.assertFalse(output.exists())

    def test_recovery_point_restore_archives_and_replaces_complete_target_set(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recovery_point, backup = self.create_recovery_point_fixture(root)
            target = root / "target"
            target.mkdir()
            tasks = target / "management-tasks.json"
            ledger = target / "management-idempotency.json"
            configuration = target / "pdr-runtime.properties"
            audit = target / "management-audit.jsonl"
            self.write_snapshot(tasks, "tasks", [{"id": "current-task"}])
            self.write_snapshot(ledger, "requests", [{"requestId": "current-request"}])
            configuration.write_text("state=current\n", encoding="utf-8")
            audit.write_text('{"event":"current"}\n', encoding="utf-8")
            Path(str(audit) + ".1").write_text('{"event":"current-previous"}\n', encoding="utf-8")
            original_hashes = {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (tasks, ledger, configuration, audit, Path(str(audit) + ".1"))
            }
            report = root / "restore.json"
            operation_audit = root / "restore-operations.jsonl"
            command = [
                sys.executable, str(TOOL), "persistence", "restore-recovery-point",
                str(recovery_point), "--tasks", str(tasks), "--idempotency", str(ledger),
                "--configuration", str(configuration), "--management-audit", str(audit),
                "--archive-output", str(root / "pre-restore"),
                "--operation-audit", str(operation_audit), "--operator", "unit-test",
                "--expected-manifest-sha256", backup["verification"]["manifestSha256"],
                "--confirm-runtime-stopped", "--report", str(report),
            ]
            restored = subprocess.run(command, check=False, capture_output=True, text=True)
            self.assertEqual(restored.returncode, 0, restored.stdout + restored.stderr)
            evidence = json.loads(report.read_text(encoding="utf-8"))
            self.assertTrue(evidence["passed"])
            self.assertFalse(evidence["rollbackAttempted"])
            source_manifest = json.loads(
                (recovery_point / "recovery-manifest.json").read_text(encoding="utf-8")
            )
            expected_by_role = {entry["role"]: entry["sha256"] for entry in source_manifest["files"]}
            self.assertEqual(hashlib.sha256(configuration.read_bytes()).hexdigest(),
                             expected_by_role["configuration"])
            self.assertEqual(hashlib.sha256(tasks.read_bytes()).hexdigest(),
                             expected_by_role["management-tasks"])
            self.assertEqual(hashlib.sha256(ledger.read_bytes()).hexdigest(),
                             expected_by_role["management-idempotency"])
            self.assertEqual(hashlib.sha256(audit.read_bytes()).hexdigest(),
                             expected_by_role["management-audit"])
            self.assertEqual(hashlib.sha256(Path(str(audit) + ".1").read_bytes()).hexdigest(),
                             expected_by_role["management-audit-previous"])
            archive = Path(evidence["preRestoreArchive"])
            archive_manifest = json.loads(
                (archive / "pre-restore-manifest.json").read_text(encoding="utf-8")
            )
            for entry in archive_manifest["files"]:
                self.assertEqual(entry["sha256"], original_hashes[Path(entry["targetPath"]).name])
            events = [json.loads(line)["event"] for line in
                      operation_audit.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(events, ["restore-started", "restore-finished"])
            mismatch_command = list(command)
            digest_index = mismatch_command.index("--expected-manifest-sha256") + 1
            mismatch_command[digest_index] = "0" * 64
            refused = subprocess.run(
                mismatch_command, check=False, capture_output=True, text=True,
            )
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("changed since approval", refused.stdout)

    def test_recovery_point_restore_rolls_back_all_targets_after_replace_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recovery_point, backup = self.create_recovery_point_fixture(root)
            target = root / "target"
            target.mkdir()
            tasks = target / "management-tasks.json"
            ledger = target / "management-idempotency.json"
            configuration = target / "pdr-runtime.properties"
            audit = target / "management-audit.jsonl"
            self.write_snapshot(tasks, "tasks", [{"id": "current-task"}])
            self.write_snapshot(ledger, "requests", [{"requestId": "current-request"}])
            configuration.write_text("state=current\n", encoding="utf-8")
            audit.write_text('{"event":"current"}\n', encoding="utf-8")
            current_contents = {path: path.read_bytes() for path in
                                (tasks, ledger, configuration, audit)}
            arguments = PDR.parser().parse_args([
                "persistence", "restore-recovery-point", str(recovery_point),
                "--tasks", str(tasks), "--idempotency", str(ledger),
                "--configuration", str(configuration), "--management-audit", str(audit),
                "--archive-output", str(root / "pre-restore"),
                "--operation-audit", str(root / "restore-operations.jsonl"),
                "--operator", "unit-test", "--expected-manifest-sha256",
                backup["verification"]["manifestSha256"], "--confirm-runtime-stopped",
                "--report", str(root / "restore.json"),
            ])
            real_replace = PDR.os.replace
            replacements = 0

            def fail_second_restore(source, destination):
                nonlocal replacements
                if ".restore-" in str(source):
                    replacements += 1
                    if replacements == 2:
                        raise OSError("injected replace failure")
                return real_replace(source, destination)

            with mock.patch.object(PDR.os, "replace", side_effect=fail_second_restore), \
                    mock.patch("builtins.print"):
                result = PDR.restore_recovery_point(arguments)
            self.assertEqual(result, 2)
            evidence = json.loads((root / "restore.json").read_text(encoding="utf-8"))
            self.assertTrue(evidence["rollbackAttempted"])
            self.assertTrue(evidence["rollbackPassed"])
            for path, content in current_contents.items():
                self.assertEqual(path.read_bytes(), content)
            self.assertFalse(any(target.glob("*.new")))

    def test_recovery_point_restore_removes_stale_rotated_audit_when_source_has_none(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recovery_point, backup = self.create_recovery_point_fixture(
                root, include_rotated_audit=False
            )
            target = root / "target"
            target.mkdir()
            tasks = target / "management-tasks.json"
            ledger = target / "management-idempotency.json"
            configuration = target / "pdr-runtime.properties"
            audit = target / "management-audit.jsonl"
            rotated = Path(str(audit) + ".1")
            self.write_snapshot(tasks, "tasks", [])
            self.write_snapshot(ledger, "requests", [])
            configuration.write_text("state=current\n", encoding="utf-8")
            audit.write_text("current\n", encoding="utf-8")
            rotated.write_text("stale-rotated\n", encoding="utf-8")
            result = subprocess.run([
                sys.executable, str(TOOL), "persistence", "restore-recovery-point",
                str(recovery_point), "--tasks", str(tasks), "--idempotency", str(ledger),
                "--configuration", str(configuration), "--management-audit", str(audit),
                "--archive-output", str(root / "pre-restore"),
                "--operation-audit", str(root / "restore-operations.jsonl"),
                "--operator", "unit-test", "--expected-manifest-sha256",
                backup["verification"]["manifestSha256"], "--confirm-runtime-stopped",
            ], check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(rotated.exists())
            archive = next((root / "pre-restore").iterdir())
            manifest = json.loads(
                (archive / "pre-restore-manifest.json").read_text(encoding="utf-8")
            )
            rotated_entry = next(
                item for item in manifest["files"]
                if item["role"] == "management-audit-previous"
            )
            self.assertTrue(rotated_entry["existed"])
            self.assertEqual(
                (archive / rotated_entry["archivePath"]).read_text(encoding="utf-8"),
                "stale-rotated\n",
            )

    def test_restored_runtime_validation_approves_only_complete_healthy_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            restore_id, restore_report, operation_audit = \
                self.write_restore_transaction_evidence(root)
            validation_report = root / "validation.json"
            arguments = PDR.parser().parse_args([
                "persistence", "validate-restored-runtime",
                "--base-url", "http://127.0.0.1:9999",
                "--restore-report", str(restore_report),
                "--operation-audit", str(operation_audit),
                "--expected-restore-id", restore_id, "--operator", "validator",
                "--timeout", "0.1", "--request-timeout", "0.05",
                "--poll-interval", "0.01", "--report", str(validation_report),
            ])
            with mock.patch.object(PDR, "fetch_json_endpoint",
                                   side_effect=self.healthy_restore_endpoint), \
                    mock.patch("builtins.print"):
                result = PDR.validate_restored_runtime(arguments)
            self.assertEqual(result, 0)
            evidence = json.loads(validation_report.read_text(encoding="utf-8"))
            self.assertEqual(evidence["verdict"], "APPROVED")
            self.assertTrue(evidence["approvedForManagementWrites"])
            self.assertEqual(evidence["denialReasons"], [])
            self.assertNotIn("json", evidence["endpoints"]["managementTasks"])

    def test_restored_runtime_validation_requires_complete_interrupted_dispositions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            restore_id, restore_report, operation_audit = \
                self.write_restore_transaction_evidence(root)
            report = root / "validation.json"
            arguments = PDR.parser().parse_args([
                "persistence", "validate-restored-runtime",
                "--base-url", "http://127.0.0.1:9999",
                "--restore-report", str(restore_report),
                "--operation-audit", str(operation_audit),
                "--expected-restore-id", restore_id, "--operator", "validator",
                "--timeout", "0.1", "--request-timeout", "0.05",
                "--poll-interval", "0.01", "--report", str(report),
            ])
            interrupted = [{"id": "task-1", "state": "interrupted",
                            "operation": "bundle-lifecycle", "target": "bundle-1",
                            "recoveryPolicy": "verify-before-retry"}]

            def endpoint(url, headers, timeout):
                return self.healthy_restore_endpoint(
                    url, headers, timeout, interrupted, idempotency_interrupted=1
                )

            with mock.patch.object(PDR, "fetch_json_endpoint", side_effect=endpoint), \
                    mock.patch("builtins.print"):
                denied = PDR.validate_restored_runtime(arguments)
            self.assertEqual(denied, 1)
            evidence = json.loads(report.read_text(encoding="utf-8"))
            self.assertIn("INTERRUPTED_DISPOSITIONS_INCOMPLETE", evidence["denialReasons"])
            dispositions = root / "dispositions.json"
            dispositions.write_text(json.dumps({
                "schemaVersion": 1, "restoreId": restore_id,
                "approvedBy": "reviewer", "approvedAt": "2026-08-01T18:00:00Z",
                "items": [
                    {"type": "management-task", "id": "task-1", "decision": "no-retry",
                     "verifiedState": "bundle already active", "evidence": "ticket-1"},
                    {"type": "idempotency-ledger", "id": "aggregate", "count": 1,
                     "decision": "no-retry", "verifiedState": "target state verified",
                     "evidence": "ticket-2"},
                ],
            }), encoding="utf-8")
            arguments.dispositions = str(dispositions)
            with mock.patch.object(PDR, "fetch_json_endpoint", side_effect=endpoint), \
                    mock.patch("builtins.print"):
                approved = PDR.validate_restored_runtime(arguments)
            self.assertEqual(approved, 0)
            evidence = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(evidence["verdict"], "APPROVED")
            self.assertEqual(evidence["dispositions"]["approvedBy"], "reviewer")

    def test_restored_runtime_validation_denies_degraded_or_incomplete_restore_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            restore_id, restore_report, incomplete_audit = \
                self.write_restore_transaction_evidence(root, audit_complete=False)
            arguments = PDR.parser().parse_args([
                "persistence", "validate-restored-runtime",
                "--base-url", "http://127.0.0.1:9999",
                "--restore-report", str(restore_report),
                "--operation-audit", str(incomplete_audit),
                "--expected-restore-id", restore_id, "--operator", "validator",
                "--timeout", "0.03", "--request-timeout", "0.01",
                "--poll-interval", "0.005", "--report", str(root / "invalid.json"),
            ])
            with mock.patch.object(PDR, "fetch_json_endpoint") as fetch, \
                    mock.patch("builtins.print"):
                invalid = PDR.validate_restored_runtime(arguments)
            self.assertEqual(invalid, 2)
            fetch.assert_not_called()
            restore_id, restore_report, complete_audit = \
                self.write_restore_transaction_evidence(root, audit_complete=True)
            arguments.operation_audit = str(complete_audit)
            arguments.restore_report = str(restore_report)

            def degraded(url, headers, timeout):
                evidence = self.healthy_restore_endpoint(url, headers, timeout)
                if url.endswith("/health/ready"):
                    evidence = {"url": url, "status": 503,
                                "json": {"ready": False, "status": "DEGRADED"}}
                return evidence

            with mock.patch.object(PDR, "fetch_json_endpoint", side_effect=degraded), \
                    mock.patch("builtins.print"):
                denied = PDR.validate_restored_runtime(arguments)
            self.assertEqual(denied, 1)
            evidence = json.loads((root / "invalid.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence["denialReasons"], ["RUNTIME_NOT_READY"])

    def test_isolated_plugin_scaffold_creates_supervised_instance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            executable_suffix = ".exe" if os.name == "nt" else ""
            launcher = (runtime / "processes" / "pdr-launcher" /
                        f"pdr-launcher{executable_suffix}")
            host = (runtime / "processes" / "pdr-plugin-host" /
                    f"pdr-plugin-host{executable_suffix}")
            launcher.parent.mkdir(parents=True)
            host.parent.mkdir(parents=True)
            launcher.write_bytes(b"launcher")
            host.write_bytes(b"host")
            artifact = root / "pdr.plugin.example_1.0.0.bndl"
            core = root / "osp.core_1.7.0.bndl"
            artifact.write_bytes(b"plugin")
            core.write_bytes(b"core")
            approval = root / "approval.json"
            approval.write_text(json.dumps({
                "operation": "plugin-preflight", "passed": True,
                "artifact": {"symbolicName": "pdr.plugin.example",
                             "sha256": hashlib.sha256(b"plugin").hexdigest()},
                "provenance": {"verified": True, "diagnosticBypass": False},
            }), encoding="utf-8")

            class Manager:
                @staticmethod
                def inspect_bundle(path, require_plugin=True):
                    if Path(path) == artifact:
                        return {"symbolicName": "pdr.plugin.example", "version": "1.0.0",
                                "dependencies": [{"id": "osp.core"}]}
                    return {"symbolicName": "osp.core", "version": "1.7.0",
                            "dependencies": []}

                @staticmethod
                def sha256(path):
                    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

                @staticmethod
                def atomic_json(path, document):
                    Path(path).write_text(json.dumps(document), encoding="utf-8")

            arguments = PDR.parser().parse_args([
                "plugin", "scaffold-isolated", str(artifact),
                "--runtime-root", str(runtime), "--instance-name", "example-host",
                "--dependency-bundle", str(core),
                "--approval-report", str(approval),
            ])
            with mock.patch.object(PDR, "load_plugin_manager", return_value=Manager), \
                    mock.patch("builtins.print"):
                self.assertEqual(PDR.scaffold_isolated_plugin(arguments), 0)
            instance = runtime / "processes" / "example-host"
            self.assertTrue((instance / artifact.name).exists() is False)
            self.assertTrue((instance / "bundles" / artifact.name).is_file())
            host_config = (instance / "pdr-plugin-host.properties").read_text(encoding="utf-8")
            launcher_config = (instance / "pdr-launcher.properties").read_text(encoding="utf-8")
            snippet = (instance / "pdr-subprocess-entry.properties").read_text(encoding="utf-8")
            self.assertIn("pluginHost.pluginId = pdr.plugin.example", host_config)
            self.assertIn("watchdog.requireFile = true", launcher_config)
            self.assertIn("childArgument.count = 1", launcher_config)
            self.assertIn("subprocess.N.argument.count = 2", snippet)

            configuration = runtime / "pdr-subprocesses.properties"
            configuration.write_text("\n".join([
                "# existing application worker",
                "subprocess.count = 1",
                "subprocess.0.enabled = true",
                "subprocess.0.name = application-worker",
                "subprocess.0.path = processes/application-worker.exe",
            ]) + "\n", encoding="utf-8")
            unconfirmed_arguments = PDR.parser().parse_args([
                "plugin", "apply-isolated", "example-host",
                "--runtime-root", str(runtime),
            ])
            with self.assertRaisesRegex(ValueError, "confirm-runtime-stopped"):
                PDR.apply_isolated_plugin(unconfirmed_arguments)
            conflict = runtime / "conflict.properties"
            conflict.write_text("\n".join([
                "subprocess.count = 1", "subprocess.0.name = example-host",
                "subprocess.0.path = processes/other.exe",
            ]) + "\n", encoding="utf-8")
            conflict_arguments = PDR.parser().parse_args([
                "plugin", "apply-isolated", "example-host",
                "--runtime-root", str(runtime), "--configuration", str(conflict),
                "--confirm-runtime-stopped",
            ])
            with self.assertRaisesRegex(ValueError, "unmanaged entry"):
                PDR.apply_isolated_plugin(conflict_arguments)
            apply_arguments = PDR.parser().parse_args([
                "plugin", "apply-isolated", "example-host",
                "--runtime-root", str(runtime), "--confirm-runtime-stopped",
            ])
            lock = configuration.with_name(configuration.name + ".lock")
            lock.write_text(f"pid={os.getpid()}\n", encoding="ascii")
            with self.assertRaisesRegex(RuntimeError, "locked by pid"):
                PDR.apply_isolated_plugin(apply_arguments)
            lock.unlink()
            lock.write_text("pid=2147483647\n", encoding="ascii")
            with mock.patch.object(PDR, "load_plugin_manager", return_value=Manager), \
                    mock.patch("builtins.print"):
                self.assertEqual(PDR.apply_isolated_plugin(apply_arguments), 0)
                self.assertEqual(PDR.apply_isolated_plugin(apply_arguments), 0)
            self.assertFalse(lock.exists())
            applied = configuration.read_text(encoding="utf-8")
            self.assertIn("subprocess.count = 2", applied)
            self.assertEqual(applied.count("subprocess.1.name = example-host"), 1)
            self.assertIn("subprocess.1.pdrManaged = true", applied)
            self.assertIn("# existing application worker", applied)

            list_report = root / "isolated-list.json"
            list_arguments = PDR.parser().parse_args([
                "plugin", "list-isolated", "--runtime-root", str(runtime),
                "--report", str(list_report),
            ])
            with mock.patch.object(PDR, "load_plugin_manager", return_value=Manager), \
                    mock.patch("builtins.print"):
                self.assertEqual(PDR.list_isolated_plugins(list_arguments), 0)
            listed = json.loads(list_report.read_text(encoding="utf-8"))
            self.assertEqual(len(listed["instances"]), 1)
            self.assertEqual(listed["instances"][0]["pluginId"], "pdr.plugin.example")
            self.assertEqual(listed["instances"][0]["state"], "ready")

            (instance / "pdr-plugin-host.properties").write_text(
                host_config + "# tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                PDR.apply_isolated_plugin(apply_arguments)

            remove_arguments = PDR.parser().parse_args([
                "plugin", "remove-isolated", "example-host",
                "--runtime-root", str(runtime), "--confirm-runtime-stopped", "--purge",
            ])
            with mock.patch.object(PDR, "load_plugin_manager", return_value=Manager), \
                    mock.patch("builtins.print"):
                self.assertEqual(PDR.remove_isolated_plugin(remove_arguments), 0)
            removed = configuration.read_text(encoding="utf-8")
            self.assertIn("subprocess.count = 1", removed)
            self.assertIn("subprocess.0.name = application-worker", removed)
            self.assertFalse(instance.exists())


if __name__ == "__main__":
    unittest.main()
