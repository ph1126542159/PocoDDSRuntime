#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = ROOT / "tools" / "configuration_participant_contract.py"
SPEC = importlib.util.spec_from_file_location(
    "configuration_participant_contract_under_test", TOOL_PATH
)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


class ConfigurationParticipantDeclarationTests(unittest.TestCase):
    @staticmethod
    def write_bundle(root: Path, name: str, owner: str,
                     participants: list[dict], *, packaged: bool = True) -> Path:
        component = root / name
        bundle = component / "bundle"
        bundle.mkdir(parents=True)
        declaration = bundle / "configuration-participants.json"
        declaration.write_text(json.dumps({
            "schemaVersion": 1,
            "participants": participants,
        }), encoding="utf-8")
        files = "  <files>bundle/*</files>\n" if packaged else ""
        (component / f"{name}.bndlspec").write_text(
            "<?xml version=\"1.0\"?>\n"
            "<bundlespec><manifest>"
            f"<symbolicName>{owner}</symbolicName>"
            "</manifest>\n"
            f"{files}</bundlespec>\n",
            encoding="utf-8",
        )
        return declaration

    @staticmethod
    def participant(identifier: str, prefix: str,
                    after: list[str] | None = None) -> dict:
        return {
            "id": identifier,
            "serviceName": f"pdr.configuration.participant.{identifier}",
            "ownedPrefixes": [prefix],
            "after": after or [],
        }

    @staticmethod
    def write_baseline(path: Path, participants: list[dict],
                       runtime_version: str = "0.1.0") -> Path:
        path.write_text(json.dumps({
            "schemaVersion": 1,
            "product": TOOL.BASELINE_PRODUCT,
            "runtimeVersion": runtime_version,
            "participants": participants,
        }), encoding="utf-8")
        return path

    @staticmethod
    def published(owner: str, participant: dict) -> dict:
        return {"owner": owner, **participant}

    def test_repository_declarations_are_globally_valid(self) -> None:
        paths = TOOL.discover(ROOT)
        baseline = ROOT / "contracts" / "configuration-participant-baseline.json"
        report = TOOL.validate(paths, baseline)
        self.assertGreaterEqual(report["declarationCount"], 2)
        self.assertGreaterEqual(report["participantCount"], 2)
        self.assertTrue(report["passed"])
        self.assertTrue(report["compatible"])
        self.assertEqual(report["baseline"]["runtimeVersion"], "0.1.0")
        self.assertEqual(report["violations"], [])
        self.assertEqual(report["errors"], [])

    def test_removed_published_participant_is_incompatible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = self.write_bundle(
                root, "Current", "pdr.test.current",
                [self.participant("current", "pdr.current")],
            )
            baseline = self.write_baseline(root / "baseline.json", [
                self.published("pdr.test.current", self.participant("current", "pdr.current")),
                self.published("pdr.test.removed", self.participant("removed", "pdr.removed")),
            ])
            report = TOOL.validate([current], baseline)
            self.assertFalse(report["passed"])
            self.assertIn(
                "published-participant-removed",
                {item["code"] for item in report["violations"]},
            )

    def test_published_identity_and_owner_cannot_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            changed = self.participant("stable", "pdr.stable")
            changed["serviceName"] = "pdr.configuration.participant.changed"
            current = self.write_bundle(
                root, "Current", "pdr.test.changed-owner", [changed]
            )
            published = self.participant("stable", "pdr.stable")
            baseline = self.write_baseline(root / "baseline.json", [
                self.published("pdr.test.original-owner", published),
            ])
            report = TOOL.validate([current], baseline)
            codes = {item["code"] for item in report["violations"]}
            self.assertIn("published-owner-changed", codes)
            self.assertIn("published-service-name-changed", codes)

    def test_published_prefix_cannot_be_narrowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = self.write_bundle(
                root, "Current", "pdr.test.current",
                [self.participant("stable", "pdr.stable.child")],
            )
            baseline = self.write_baseline(root / "baseline.json", [
                self.published(
                    "pdr.test.current", self.participant("stable", "pdr.stable")
                ),
            ])
            report = TOOL.validate([current], baseline)
            self.assertEqual(
                {item["code"] for item in report["violations"]},
                {"published-prefix-narrowed"},
            )

    def test_published_prefix_may_be_widened(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = self.write_bundle(
                root, "Current", "pdr.test.current",
                [self.participant("stable", "pdr.stable")],
            )
            baseline = self.write_baseline(root / "baseline.json", [
                self.published(
                    "pdr.test.current",
                    self.participant("stable", "pdr.stable.child"),
                ),
            ])
            report = TOOL.validate([current], baseline)
            self.assertTrue(report["compatible"])

    def test_published_prefix_cannot_move_to_another_participant(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = self.write_bundle(
                root, "Original", "pdr.test.original",
                [self.participant("original", "pdr.original")],
            )
            replacement = self.write_bundle(
                root, "Replacement", "pdr.test.replacement",
                [self.participant("replacement", "pdr.stable")],
            )
            baseline = self.write_baseline(root / "baseline.json", [
                self.published(
                    "pdr.test.original", self.participant("original", "pdr.stable")
                ),
            ])
            report = TOOL.validate([original, replacement], baseline)
            self.assertEqual(
                {item["code"] for item in report["violations"]},
                {"published-prefix-owner-changed"},
            )

    def test_published_ordering_dependency_cannot_be_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self.write_bundle(
                root, "First", "pdr.test.first",
                [self.participant("first", "pdr.first")],
            )
            second = self.write_bundle(
                root, "Second", "pdr.test.second",
                [self.participant("second", "pdr.second")],
            )
            baseline = self.write_baseline(root / "baseline.json", [
                self.published(
                    "pdr.test.first",
                    self.participant("first", "pdr.first", ["second"]),
                ),
                self.published(
                    "pdr.test.second", self.participant("second", "pdr.second")
                ),
            ])
            report = TOOL.validate([first, second], baseline)
            self.assertEqual(
                {item["code"] for item in report["violations"]},
                {"published-dependency-removed"},
            )

    def test_malformed_baseline_has_stable_error_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = self.write_bundle(
                root, "Current", "pdr.test.current",
                [self.participant("current", "pdr.current")],
            )
            baseline = self.write_baseline(root / "baseline.json", [{
                "owner": "pdr.test.current",
                **self.participant("current", "invalid prefix!"),
            }])
            with self.assertRaises(TOOL.ContractError) as raised:
                TOOL.validate([current], baseline)
            self.assertEqual(raised.exception.code, "baseline-invalid")

    def test_incompatible_command_writes_evidence_and_returns_one(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = self.write_bundle(
                root, "Current", "pdr.test.current",
                [self.participant("current", "pdr.current")],
            )
            baseline = self.write_baseline(root / "baseline.json", [
                self.published(
                    "pdr.test.removed", self.participant("removed", "pdr.removed")
                ),
            ])
            evidence = root / "report.json"
            self.assertEqual(TOOL.execute([current], evidence, baseline), 1)
            report = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertFalse(report["passed"])
            self.assertEqual(report["baseline"]["runtimeVersion"], "0.1.0")
            self.assertEqual(report["errors"], [])

    def test_cross_bundle_prefix_overlap_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self.write_bundle(
                root, "First", "pdr.test.first",
                [self.participant("first", "pdr.shared")],
            )
            second = self.write_bundle(
                root, "Second", "pdr.test.second",
                [self.participant("second", "pdr.shared.child")],
            )
            with self.assertRaisesRegex(TOOL.ContractError, "overlaps") as raised:
                TOOL.validate([first, second])
            self.assertEqual(raised.exception.code, "prefix-overlap")

    def test_dependency_cycle_marks_only_cycle_nodes(self) -> None:
        graph = {
            "cycle-a": ["cycle-b"],
            "cycle-b": ["cycle-a"],
            "upstream": ["cycle-a"],
        }
        self.assertEqual(TOOL.cycle_nodes(graph), {"cycle-a", "cycle-b"})

    def test_cross_bundle_dependency_cycle_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self.write_bundle(
                root, "First", "pdr.test.first",
                [self.participant("cycle-a", "pdr.first", ["cycle-b"])],
            )
            second = self.write_bundle(
                root, "Second", "pdr.test.second",
                [self.participant("cycle-b", "pdr.second", ["cycle-a"])],
            )
            with self.assertRaises(TOOL.ContractError) as raised:
                TOOL.validate([first, second])
            self.assertEqual(raised.exception.code, "dependency-cycle")
            self.assertIn("cycle-a,cycle-b", raised.exception.detail)

    def test_unexpected_fields_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            declaration = self.write_bundle(
                root, "Unsafe", "pdr.test.unsafe",
                [dict(self.participant("unsafe", "pdr.unsafe"), secret="must-not-pass")],
            )
            with self.assertRaises(TOOL.ContractError) as raised:
                TOOL.validate([declaration])
            self.assertEqual(raised.exception.code, "declaration-invalid")

    def test_bundle_must_package_declaration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            declaration = self.write_bundle(
                Path(directory), "Unpackaged", "pdr.test.unpackaged",
                [self.participant("unpackaged", "pdr.unpackaged")], packaged=False,
            )
            with self.assertRaises(TOOL.ContractError) as raised:
                TOOL.validate([declaration])
            self.assertEqual(raised.exception.code, "declaration-not-packaged")

    def test_empty_declaration_is_valid_but_non_claiming(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            declaration = self.write_bundle(
                Path(directory), "Empty", "pdr.test.empty", []
            )
            report = TOOL.validate([declaration])
            self.assertEqual(report["participantCount"], 0)


if __name__ == "__main__":
    unittest.main()
