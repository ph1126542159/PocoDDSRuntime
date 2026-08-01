#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "contracts" / "schemas" / "runtime-config.schema.json"
VALIDATOR_PATH = ROOT / "platform" / "configuration" / "src" / "ConfigurationValidator.cpp"
DEFAULT_CONFIG_PATH = ROOT / "config" / "pdr-runtime.properties"


class ConfigurationContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.source = VALIDATOR_PATH.read_text(encoding="utf-8")

    def rule(self, key: str) -> dict[str, object]:
        properties = self.schema["properties"]
        if key in properties:
            return properties[key]
        matches = [
            rule for pattern, rule in self.schema["patternProperties"].items()
            if re.fullmatch(pattern, key)
        ]
        self.assertEqual(len(matches), 1, f"expected exactly one schema rule for {key}")
        return matches[0]

    def test_required_keys_match_validator(self) -> None:
        required_strings = set(re.findall(
            r'requireString\(config,\s*"([^"]+)"\s*,\s*issues\)', self.source
        ))
        required_integers = set(re.findall(
            r'integerRange\(config,\s*"([^"]+)"\s*,\s*\d+\s*,\s*\d+\s*,\s*true',
            self.source,
        ))
        runtime_required = required_strings | required_integers
        schema_required = set(self.schema["required"])
        self.assertTrue(schema_required < runtime_required)
        self.assertEqual(
            runtime_required - schema_required,
            {"pdr.subprocess.shutdownTimeoutMilliseconds"},
            "same-major schema compatibility may only omit the historically optional timeout",
        )
        self.assertIn("pdr.subprocess.shutdownTimeoutMilliseconds", self.schema["properties"])

    def test_global_integer_ranges_match_validator(self) -> None:
        ranges = re.findall(
            r'integerRange\(config,\s*"([^"]+)"\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(?:true|false)',
            self.source,
        )
        self.assertGreaterEqual(len(ranges), 10)
        for key, minimum, maximum in ranges:
            rule = self.rule(key)
            self.assertEqual(rule.get("type"), "integer", key)
            self.assertEqual(rule.get("minimum"), int(minimum), key)
            self.assertEqual(rule.get("maximum"), int(maximum), key)

    def test_all_indexed_families_have_common_schema(self) -> None:
        families = set(re.findall(r'validateFamily\("pdr\.([a-z]+)"', self.source))
        self.assertEqual(families, {
            "simulation", "modbus", "serial", "gnss", "gpio", "xbee", "can", "led",
            "mqtt", "ros", "udp",
        })
        for family in families:
            self.assertEqual(self.rule(f"pdr.{family}.count"), {
                "type": "integer", "minimum": 0, "maximum": 256,
            })
            self.assertEqual(self.rule(f"pdr.{family}.0.id").get("minLength"), 1)
            self.assertEqual(self.rule(f"pdr.{family}.0.enabled").get("type"), "boolean")
            self.assertEqual(self.rule(f"pdr.{family}.0.required").get("type"), "boolean")

    def test_protocol_and_device_edge_ranges_are_published(self) -> None:
        expected = {
            "pdr.mqtt.0.keepAliveSeconds": (0, 86400),
            "pdr.mqtt.0.connectTimeoutSeconds": (1, 3600),
            "pdr.mqtt.0.reconnectDelayMilliseconds": (100, 3600000),
            "pdr.ros.0.maximumMessageSize": (1, 2147483647),
            "pdr.ros.0.connectTimeoutSeconds": (1, 3600),
            "pdr.udp.0.localPort": (0, 65535),
            "pdr.udp.0.remotePort": (1, 65535),
            "pdr.xbee.0.analogChannel": (0, 15),
            "pdr.can.0.bitOffset": (0, 511),
            "pdr.can.0.bitLength": (1, 64),
        }
        for key, bounds in expected.items():
            rule = self.rule(key)
            self.assertEqual((rule.get("minimum"), rule.get("maximum")), bounds, key)
        self.assertEqual(self.rule("pdr.ros.0.uri").get("pattern"), "^wss?://")
        self.assertEqual(
            self.rule("pdr.mqtt.0.passwordEnvironment").get("pattern"),
            "^[A-Za-z_][A-Za-z0-9_]*$",
        )
        self.assertEqual(
            set(self.rule("pdr.xbee.0.conversion").get("enum", [])),
            {"raw", "millivolts", "temperature", "humidity"},
        )

    def test_default_config_values_obey_published_rules(self) -> None:
        values = {}
        for raw_line in DEFAULT_CONFIG_PATH.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
        self.assertTrue(set(self.schema["required"]).issubset(values))
        for key, text in values.items():
            if key not in self.schema["properties"] and not any(
                re.fullmatch(pattern, key) for pattern in self.schema["patternProperties"]
            ):
                continue
            with self.subTest(key=key):
                rule = self.rule(key)
                kind = rule.get("type")
                if kind == "integer":
                    self.assertRegex(text, r"^-?\d+$")
                    value = int(text)
                    self.assertGreaterEqual(value, int(rule.get("minimum", value)))
                    self.assertLessEqual(value, int(rule.get("maximum", value)))
                elif kind == "boolean":
                    self.assertIn(text, {"true", "false"})
                elif kind == "string":
                    if "minLength" in rule:
                        self.assertGreaterEqual(len(text), int(rule["minLength"]))
                    if "enum" in rule:
                        self.assertIn(text, rule["enum"])
                    if "pattern" in rule:
                        self.assertRegex(text, str(rule["pattern"]))


if __name__ == "__main__":
    unittest.main()
