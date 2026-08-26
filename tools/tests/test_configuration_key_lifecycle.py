#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
TOOL_PATH = TOOLS / "configuration_key_lifecycle.py"
SPEC = importlib.util.spec_from_file_location(
    "configuration_key_lifecycle_under_test", TOOL_PATH
)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


class ConfigurationKeyLifecycleTests(unittest.TestCase):
    @staticmethod
    def entry(source: str = "pdr.example.old", replacement: str | None =
              "pdr.example.current", **overrides) -> dict:
        value = {
            "id": "PDR-CFG-0001",
            "participantId": "example",
            "operation": "rename" if replacement is not None else "remove",
            "sourceKey": source,
            "replacementKey": replacement,
            "deprecatedSince": "0.1.0",
            "removalAllowedFrom": "1.0.0",
        }
        value.update(overrides)
        return value

    @staticmethod
    def write_bundle(root: Path, name: str, owner: str,
                     prefixes: list[str], entries: list[dict]) -> tuple[Path, Path]:
        component = root / name
        bundle = component / "bundle"
        bundle.mkdir(parents=True)
        participant = bundle / "configuration-participants.json"
        participant.write_text(json.dumps({
            "schemaVersion": 1,
            "participants": [{
                "id": name.lower(),
                "serviceName": f"pdr.configuration.participant.{name}",
                "ownedPrefixes": prefixes,
                "after": [],
            }],
        }), encoding="utf-8")
        lifecycle = bundle / "configuration-key-lifecycle.json"
        lifecycle.write_text(json.dumps({
            "schemaVersion": 1, "entries": entries,
        }), encoding="utf-8")
        (component / f"{name}.bndlspec").write_text(
            "<?xml version=\"1.0\"?>\n"
            "<bundlespec><manifest>"
            f"<symbolicName>{owner}</symbolicName>"
            "</manifest><files>bundle/*</files></bundlespec>\n",
            encoding="utf-8",
        )
        return lifecycle, participant

    @staticmethod
    def write_migration(path: Path, operations: list[dict]) -> Path:
        path.write_text(json.dumps({
            "from": 1, "to": 2, "operations": operations,
        }), encoding="utf-8")
        return path

    @staticmethod
    def write_baseline(path: Path, entries: list[dict],
                       runtime_version: str = "0.1.0") -> Path:
        path.write_text(json.dumps({
            "schemaVersion": 1,
            "product": TOOL.BASELINE_PRODUCT,
            "runtimeVersion": runtime_version,
            "entries": entries,
        }), encoding="utf-8")
        return path

    @staticmethod
    def published(owner: str, entry: dict) -> dict:
        return {"owner": owner, **entry}

    def test_repository_lifecycle_declarations_are_valid(self) -> None:
        report = TOOL.validate(
            TOOL.discover_lifecycles(ROOT),
            TOOL.discover_participants(ROOT),
            [], "0.1.0",
            ROOT / "contracts/configuration-key-lifecycle-baseline.json",
        )
        self.assertTrue(report["passed"])
        self.assertGreaterEqual(report["lifecycleDeclarationCount"], 2)
        self.assertEqual(report["entryCount"], 0)
        self.assertEqual(report["baseline"]["entryCount"], 0)

    def test_matching_project_rename_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lifecycle_entry = self.entry(participantId="example")
            lifecycle, participant = self.write_bundle(
                root, "Example", "pdr.test.example", ["pdr.example"],
                [lifecycle_entry],
            )
            migration = self.write_migration(root / "v1-to-v2.json", [{
                "op": "rename", "from": "pdr.example.old",
                "path": "pdr.example.current",
            }])
            report = TOOL.validate(
                [lifecycle], [participant], [migration], "0.1.0"
            )
            self.assertTrue(report["compatible"])
            self.assertEqual(report["entryCount"], 1)
            self.assertEqual(len(report["migrationOperations"]), 1)

    def test_migration_without_owner_lifecycle_is_incompatible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lifecycle, participant = self.write_bundle(
                root, "Example", "pdr.test.example", ["pdr.example"], []
            )
            migration = self.write_migration(root / "v1-to-v2.json", [{
                "op": "remove", "path": "pdr.example.legacy",
            }])
            report = TOOL.validate(
                [lifecycle], [participant], [migration], "0.1.0"
            )
            self.assertFalse(report["passed"])
            self.assertEqual(
                report["violations"][0]["code"], "migration-lifecycle-missing"
            )

    def test_migration_must_match_declared_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lifecycle, participant = self.write_bundle(
                root, "Example", "pdr.test.example", ["pdr.example"],
                [self.entry(participantId="example")],
            )
            migration = self.write_migration(root / "v1-to-v2.json", [{
                "op": "rename", "from": "pdr.example.old",
                "path": "pdr.example.other",
            }])
            report = TOOL.validate(
                [lifecycle], [participant], [migration], "0.1.0"
            )
            self.assertEqual(
                report["violations"][0]["code"], "migration-lifecycle-mismatch"
            )

    def test_key_cannot_escape_participant_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lifecycle, participant = self.write_bundle(
                root, "Example", "pdr.test.example", ["pdr.example"],
                [self.entry(replacement="pdr.other.current", participantId="example")],
            )
            with self.assertRaises(TOOL.ContractError) as raised:
                TOOL.validate([lifecycle], [participant], [], "0.1.0")
            self.assertEqual(raised.exception.code, "lifecycle-key-outside-owner")

    def test_bundle_cannot_deprecate_another_bundle_participant(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lifecycle, first = self.write_bundle(
                root, "First", "pdr.test.first", ["pdr.first"],
                [self.entry(
                    source="pdr.second.old", replacement="pdr.second.current",
                    participantId="second",
                )],
            )
            _, second = self.write_bundle(
                root, "Second", "pdr.test.second", ["pdr.second"], []
            )
            with self.assertRaises(TOOL.ContractError) as raised:
                TOOL.validate([lifecycle], [first, second], [], "0.1.0")
            self.assertEqual(raised.exception.code, "lifecycle-owner-mismatch")

    def test_deprecation_cannot_be_backdated_from_the_future(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lifecycle, participant = self.write_bundle(
                root, "Example", "pdr.test.example", ["pdr.example"],
                [self.entry(participantId="example", deprecatedSince="0.2.0")],
            )
            with self.assertRaises(TOOL.ContractError) as raised:
                TOOL.validate([lifecycle], [participant], [], "0.1.0")
            self.assertEqual(raised.exception.code, "lifecycle-version-future")

    def test_removal_requires_later_major_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lifecycle, participant = self.write_bundle(
                root, "Example", "pdr.test.example", ["pdr.example"],
                [self.entry(
                    participantId="example", removalAllowedFrom="0.2.0"
                )],
            )
            with self.assertRaises(TOOL.ContractError) as raised:
                TOOL.validate([lifecycle], [participant], [], "0.1.0")
            self.assertEqual(raised.exception.code, "lifecycle-removal-window-invalid")

    def test_replacement_cycle_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entries = [
                self.entry(
                    source="pdr.example.a", replacement="pdr.example.b",
                    participantId="example",
                ),
                self.entry(
                    source="pdr.example.b", replacement="pdr.example.a",
                    id="PDR-CFG-0002", participantId="example",
                ),
            ]
            lifecycle, participant = self.write_bundle(
                root, "Example", "pdr.test.example", ["pdr.example"], entries
            )
            with self.assertRaises(TOOL.ContractError) as raised:
                TOOL.validate([lifecycle], [participant], [], "0.1.0")
            self.assertEqual(raised.exception.code, "lifecycle-replacement-cycle")

    def test_published_lifecycle_cannot_disappear_before_removal_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lifecycle, participant = self.write_bundle(
                root, "Example", "pdr.test.example", ["pdr.example"], []
            )
            baseline = self.write_baseline(root / "baseline.json", [
                self.published(
                    "pdr.test.example", self.entry(participantId="example")
                ),
            ])
            report = TOOL.validate(
                [lifecycle], [participant], [], "0.2.0", baseline
            )
            self.assertFalse(report["compatible"])
            self.assertEqual(
                report["violations"][0]["code"],
                "published-lifecycle-removed-early",
            )

    def test_published_lifecycle_may_disappear_at_allowed_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lifecycle, participant = self.write_bundle(
                root, "Example", "pdr.test.example", ["pdr.example"], []
            )
            baseline = self.write_baseline(root / "baseline.json", [
                self.published(
                    "pdr.test.example", self.entry(participantId="example")
                ),
            ])
            report = TOOL.validate(
                [lifecycle], [participant], [], "1.0.0", baseline
            )
            self.assertTrue(report["compatible"])

    def test_published_identity_and_removal_window_cannot_be_weakened(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = self.entry(
                participantId="example",
                replacementKey="pdr.example.changed",
                removalAllowedFrom="1.0.0",
            )
            lifecycle, participant = self.write_bundle(
                root, "Example", "pdr.test.example", ["pdr.example"], [current]
            )
            published = self.entry(
                participantId="example", removalAllowedFrom="2.0.0"
            )
            baseline = self.write_baseline(root / "baseline.json", [
                self.published("pdr.test.example", published),
            ])
            report = TOOL.validate(
                [lifecycle], [participant], [], "0.1.0", baseline
            )
            codes = {item["code"] for item in report["violations"]}
            self.assertEqual(codes, {
                "published-lifecycle-changed",
                "published-removal-window-shortened",
            })


if __name__ == "__main__":
    unittest.main()
