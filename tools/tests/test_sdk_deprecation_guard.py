import argparse
import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "sdk_deprecation_guard", ROOT / "tools/sdk_deprecation_guard.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)
import sdk_surface_guard as SURFACE


class SDKDeprecationGuardTests(unittest.TestCase):
    header_path = "include/PocoDDS/Core/API.h"

    def fixture(self, root: Path, marker: str | None = None) -> Path:
        install = root / "install"
        header = install / self.header_path
        header.parent.mkdir(parents=True)
        attribute = f' [[deprecated("{marker}: use CoreAPI")]]' if marker else ""
        header.write_text(
            f"#pragma once\nnamespace PocoDDS {{ struct{attribute} API {{ int value; }}; }}\n",
            encoding="utf-8",
        )
        extra = install / "include/PocoDDS/Core/Keep.h"
        extra.write_text("#pragma once\nstruct Keep {};\n", encoding="utf-8")
        targets = install / "lib/cmake/PocoDDSRuntime/PocoDDSRuntimeTargets.cmake"
        targets.parent.mkdir(parents=True)
        targets.write_text(
            "add_library(PocoDDS::Core STATIC IMPORTED)\n", encoding="utf-8"
        )
        return install

    def entry(self, snapshot: dict, *, state: str = "active",
              allowed: str = "2.0.0", kind: str = "header",
              surface: str | None = None) -> dict:
        return {
            "id": "PDR-DEP-0001",
            "kind": kind,
            "surface": surface or self.header_path,
            "symbol": "PocoDDS::API",
            "state": state,
            "deprecatedSince": snapshot["runtimeVersion"],
            "removalAllowedFrom": allowed,
            "replacement": "PocoDDS::CoreAPI",
            "owner": "team/core",
            "noticeSurfaceSha256": snapshot["surfaceSha256"],
        }

    def evaluate(self, catalog: dict, baseline: dict, current: dict,
                 published: list[dict], install: Path):
        return MODULE.evaluate(
            catalog, baseline, current, published, install, [{
                "role": "catalog", "path": "fixture", "sha256": "0" * 64,
            }]
        )

    def test_empty_catalog_passes_unchanged_surface(self):
        with tempfile.TemporaryDirectory() as directory:
            install = self.fixture(Path(directory))
            snapshot = SURFACE.snapshot(install, "1.0.0")
            report = self.evaluate(
                {"schemaVersion": 1, "entries": []}, snapshot, snapshot, [snapshot], install
            )
            self.assertTrue(report["passed"])

    def test_registered_active_header_marker_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plain_install = self.fixture(root / "plain")
            baseline = SURFACE.snapshot(plain_install, "1.0.0")
            install = self.fixture(root / "marked", "PDR-DEP-0001")
            current = SURFACE.snapshot(install, "1.0.0")
            self.assertEqual(baseline["surfaceSha256"], current["surfaceSha256"])
            catalog = {"schemaVersion": 1, "entries": [self.entry(current)]}
            report = self.evaluate(catalog, baseline, current, [baseline], install)
            self.assertTrue(report["passed"], report["violations"])

    def test_unregistered_and_missing_markers_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marked = self.fixture(root / "marked", "PDR-DEP-9999")
            marked_snapshot = SURFACE.snapshot(marked, "1.0.0")
            unregistered = self.evaluate(
                {"schemaVersion": 1, "entries": []},
                marked_snapshot, marked_snapshot, [marked_snapshot], marked,
            )
            self.assertIn(
                "unregistered-marker", {item["code"] for item in unregistered["violations"]}
            )

            plain = self.fixture(root / "plain")
            plain_snapshot = SURFACE.snapshot(plain, "1.0.0")
            missing = self.evaluate(
                {"schemaVersion": 1, "entries": [self.entry(plain_snapshot)]},
                plain_snapshot, plain_snapshot, [plain_snapshot], plain,
            )
            self.assertIn(
                "active-marker-missing", {item["code"] for item in missing["violations"]}
            )

    def test_comment_only_marker_is_not_a_deprecation_notice(self):
        with tempfile.TemporaryDirectory() as directory:
            install = self.fixture(Path(directory))
            header = install / self.header_path
            header.write_text(
                header.read_text(encoding="utf-8") + "// PDR-DEP-0001\n",
                encoding="utf-8",
            )
            snapshot = SURFACE.snapshot(install, "1.0.0")
            catalog = {"schemaVersion": 1, "entries": [self.entry(snapshot)]}
            with self.assertRaisesRegex(ValueError, "outside a standardized"):
                self.evaluate(catalog, snapshot, snapshot, [snapshot], install)

    def removed_current(self, install: Path, version: str) -> dict:
        (install / self.header_path).unlink()
        return SURFACE.snapshot(install, version)

    def test_early_removal_fails_even_after_published_notice(self):
        with tempfile.TemporaryDirectory() as directory:
            install = self.fixture(Path(directory), "PDR-DEP-0001")
            notice = SURFACE.snapshot(install, "1.0.0")
            current = self.removed_current(install, "1.5.0")
            catalog = {"schemaVersion": 1, "entries": [
                self.entry(notice, state="removed", allowed="2.0.0")
            ]}
            report = self.evaluate(catalog, notice, current, [notice], install)
            self.assertIn("early-removal", {item["code"] for item in report["violations"]})

    def test_due_removal_after_published_notice_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            install = self.fixture(Path(directory), "PDR-DEP-0001")
            notice = SURFACE.snapshot(install, "1.0.0")
            current = self.removed_current(install, "2.0.0")
            catalog = {"schemaVersion": 1, "entries": [
                self.entry(notice, state="removed", allowed="2.0.0")
            ]}
            report = self.evaluate(catalog, notice, current, [notice], install)
            self.assertTrue(report["passed"], report["violations"])
            self.assertEqual(report["breakingSurfaces"][0]["change"], "removed")

    def test_major_removal_without_notice_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            install = self.fixture(Path(directory))
            baseline = SURFACE.snapshot(install, "1.0.0")
            current = self.removed_current(install, "2.0.0")
            report = self.evaluate(
                {"schemaVersion": 1, "entries": []}, baseline, current, [baseline], install
            )
            self.assertIn(
                "unscheduled-breaking-surface",
                {item["code"] for item in report["violations"]},
            )

    def test_cmake_target_requires_catalog_but_no_header_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            install = self.fixture(Path(directory))
            snapshot = SURFACE.snapshot(install, "1.0.0")
            catalog = {"schemaVersion": 1, "entries": [self.entry(
                snapshot, kind="cmake-target", surface="PocoDDS::Core"
            )]}
            report = self.evaluate(catalog, snapshot, snapshot, [snapshot], install)
            self.assertTrue(report["passed"], report["violations"])

    def test_register_captures_snapshot_and_requires_header_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            install = self.fixture(root, "PDR-DEP-0001")
            snapshot = SURFACE.snapshot(install, "1.2.0")
            snapshot_path = root / "snapshot.json"
            catalog_path = root / "catalog.json"
            snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
            catalog_path.write_text(
                json.dumps({"schemaVersion": 1, "entries": []}), encoding="utf-8"
            )
            result = MODULE.register_command(argparse.Namespace(
                catalog=catalog_path, snapshot=snapshot_path, install=install,
                id="PDR-DEP-0001", kind="header", surface=self.header_path,
                symbol="PocoDDS::API", removal_allowed_from="2.0.0",
                replacement="PocoDDS::CoreAPI", owner="team/core",
            ))
            self.assertEqual(result, 0)
            entry = json.loads(catalog_path.read_text(encoding="utf-8"))["entries"][0]
            self.assertEqual(entry["deprecatedSince"], "1.2.0")
            self.assertEqual(entry["noticeSurfaceSha256"], snapshot["surfaceSha256"])

    def test_catalog_requires_later_major_removal(self):
        with tempfile.TemporaryDirectory() as directory:
            install = self.fixture(Path(directory), "PDR-DEP-0001")
            snapshot = SURFACE.snapshot(install, "1.2.0")
            catalog = {"schemaVersion": 1, "entries": [
                self.entry(snapshot, allowed="1.9.0")
            ]}
            with self.assertRaisesRegex(ValueError, "later major"):
                MODULE.validate_catalog(catalog)

    def test_duplicate_published_snapshot_identity_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            install = self.fixture(Path(directory))
            snapshot = SURFACE.snapshot(install, "1.0.0")
            with self.assertRaisesRegex(ValueError, "duplicate version/surface identity"):
                self.evaluate(
                    {"schemaVersion": 1, "entries": []},
                    snapshot, snapshot, [snapshot, copy.deepcopy(snapshot)], install,
                )

    def test_malformed_catalog_types_fail_as_validation_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            install = self.fixture(Path(directory), "PDR-DEP-0001")
            snapshot = SURFACE.snapshot(install, "1.0.0")
            for field, value in (
                ("kind", 1),
                ("state", None),
                ("deprecatedSince", 1),
                ("removalAllowedFrom", False),
            ):
                with self.subTest(field=field):
                    malformed = self.entry(snapshot)
                    malformed[field] = value
                    with self.assertRaises(ValueError):
                        MODULE.validate_catalog({
                            "schemaVersion": 1, "entries": [malformed],
                        })


if __name__ == "__main__":
    unittest.main()
