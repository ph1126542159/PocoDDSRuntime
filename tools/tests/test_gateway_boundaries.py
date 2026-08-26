import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class GatewayBoundaryTests(unittest.TestCase):
    def test_gateways_do_not_link_concrete_device_or_protocol_implementations(self):
        device_cmake = (ROOT / "services/DeviceGateway/CMakeLists.txt").read_text(
            encoding="utf-8"
        )
        protocol_cmake = (ROOT / "services/ProtocolGateway/CMakeLists.txt").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("PocoDDS::Devices", device_cmake)
        for target in ("PocoDDS::MQTT", "PocoDDS::ROS", "PocoDDS::UDP"):
            self.assertNotIn(target, protocol_cmake)
        self.assertIn("PocoDDS::DeviceCore", device_cmake)
        self.assertIn("PocoDDS::GatewayAPI", device_cmake)
        self.assertIn("PocoDDS::GatewayAPI", protocol_cmake)

    def test_builtin_implementations_are_owned_by_provider_bundles(self):
        device_source = (ROOT /
            "services/BuiltinDeviceFactories/src/BundleActivator.cpp").read_text(
                encoding="utf-8"
            )
        protocol_source = (ROOT /
            "services/BuiltinProtocolFactories/src/BundleActivator.cpp").read_text(
                encoding="utf-8"
            )
        self.assertIn("SimulatedDevice", device_source)
        self.assertIn("ModbusRegisterDevice", device_source)
        self.assertIn("MqttClient", protocol_source)
        self.assertIn("BridgeClient", protocol_source)
        self.assertIn("UdpChannel", protocol_source)
        self.assertIn("<runLevel>090</runLevel>", (ROOT /
            "services/BuiltinDeviceFactories/BuiltinDeviceFactories.bndlspec").read_text(
                encoding="utf-8"
            ))
        self.assertIn("<runLevel>105</runLevel>", (ROOT /
            "services/BuiltinProtocolFactories/BuiltinProtocolFactories.bndlspec").read_text(
                encoding="utf-8"
            ))


if __name__ == "__main__":
    unittest.main()
