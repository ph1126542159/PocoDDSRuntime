#include "PocoDDS/Configuration/ConfigurationValidator.h"
#include "PocoDDS/Configuration/IndexedConfiguration.h"

#include "Poco/Exception.h"
#include "Poco/Util/MapConfiguration.h"

#include <algorithm>
#include <iostream>

int main()
{
    Poco::Util::MapConfiguration valid;
    valid.setString("osp.web.server.host", "127.0.0.1");
    valid.setInt("osp.web.server.port", 9080);
    valid.setInt("pdr.fastdds.domainId", 0);
    valid.setInt("pdr.subprocess.shutdownTimeoutMilliseconds", 5000);
    valid.setString("security.profile", "development");
    PocoDDS::Configuration::ConfigurationValidator validator;
    if (!validator.validate(valid).empty())
        return 1;
    valid.setString("osp.web.server.port", "invalid");
    if (validator.validate(valid).size() != 1)
        return 2;
    valid.setInt("osp.web.server.port", 9080);
    valid.setString("osp.web.server.host", "0.0.0.0");
    if (validator.validate(valid).empty())
        return 3;
    valid.setString("security.profile", "production");
    valid.setString("osp.web.authServiceName", "");
    valid.setInt("osp.web.server.securePort", 0);
    valid.setBool("auth.simple.enable", true);
    if (validator.validate(valid).size() != 3)
        return 4;
    valid.setString("osp.web.authServiceName", "oidc.auth");
    valid.setInt("osp.web.server.securePort", 9443);
    valid.setBool("auth.simple.enable", false);
    if (!validator.validate(valid).empty())
        return 5;

    Poco::Util::MapConfiguration legacy;
    legacy.setBool("pdr.serial.enabled", true);
    legacy.setString("pdr.serial.port", "COM5");
    auto instances = PocoDDS::Configuration::indexedInstances(
        legacy, "pdr.serial", false, 0, "serial");
    if (instances.size() != 1 || !instances[0].legacy ||
        instances[0].prefix != "pdr.serial" || instances[0].id != "serial-1")
        return 6;

    Poco::Util::MapConfiguration indexed;
    indexed.setUInt("pdr.serial.count", 2);
    indexed.setString("pdr.serial.0.id", "fixture-control");
    indexed.setString("pdr.serial.0.port", "COM5");
    indexed.setString("pdr.serial.1.id", "fixture-meter");
    indexed.setString("pdr.serial.1.port", "COM6");
    instances = PocoDDS::Configuration::indexedInstances(
        indexed, "pdr.serial", false, 0, "serial");
    if (instances.size() != 2 || instances[0].legacy ||
        instances[0].id != "fixture-control" ||
        instances[1].prefix != "pdr.serial.1")
        return 7;

    indexed.setString("pdr.serial.1.id", "fixture-control");
    bool duplicateRejected = false;
    try
    {
        (void) PocoDDS::Configuration::indexedInstances(
            indexed, "pdr.serial", false, 0, "serial");
    }
    catch (const Poco::InvalidArgumentException&)
    {
        duplicateRejected = true;
    }
    if (!duplicateRejected)
        return 8;

    Poco::Util::MapConfiguration multi;
    multi.setString("osp.web.server.host", "127.0.0.1");
    multi.setInt("osp.web.server.port", 9080);
    multi.setInt("pdr.fastdds.domainId", 0);
    multi.setInt("pdr.subprocess.shutdownTimeoutMilliseconds", 5000);
    multi.setUInt("pdr.simulation.count", 2);
    multi.setString("pdr.simulation.0.id", "sim-a");
    multi.setString("pdr.simulation.1.id", "sim-b");
    multi.setUInt("pdr.serial.count", 2);
    multi.setString("pdr.serial.0.id", "serial-a");
    multi.setString("pdr.serial.0.port", "COM5");
    multi.setString("pdr.serial.0.parameters", "7E1");
    multi.setString("pdr.serial.0.flowControl", "rtscts");
    multi.setInt("pdr.serial.0.readTimeoutMilliseconds", 100);
    multi.setString("pdr.serial.1.id", "serial-b");
    multi.setString("pdr.serial.1.port", "COM6");
    multi.setUInt("pdr.can.count", 1);
    multi.setString("pdr.can.0.id", "can-a");
    multi.setString("pdr.can.0.transport", "loopback");
    multi.setString("pdr.can.0.frameId", "0x123");
    multi.setUInt("pdr.can.0.bitOffset", 72);
    multi.setUInt("pdr.can.0.bitLength", 16);
    multi.setUInt("pdr.xbee.count", 1);
    multi.setString("pdr.xbee.0.id", "xbee-a");
    multi.setString("pdr.xbee.0.transport", "loopback");
    multi.setString("pdr.xbee.0.sourceAddress", "0013A200405291AB");
    multi.setUInt("pdr.xbee.0.analogChannel", 7);
    multi.setUInt("pdr.mqtt.count", 1);
    multi.setString("pdr.mqtt.0.id", "mqtt-a");
    multi.setString("pdr.mqtt.0.serverUri", "tcp://127.0.0.1:1883");
    multi.setUInt("pdr.mqtt.0.reconnectDelayMilliseconds", 250);
    multi.setUInt("pdr.mqtt.0.reconnectMaximumDelayMilliseconds", 1000);
    multi.setUInt("pdr.ros.count", 1);
    multi.setString("pdr.ros.0.id", "ros-a");
    multi.setString("pdr.ros.0.uri", "ws://127.0.0.1:9090");
    multi.setUInt("pdr.udp.count", 1);
    multi.setString("pdr.udp.0.id", "udp-a");
    multi.setString("pdr.udp.0.localHost", "127.0.0.1");
    multi.setUInt("pdr.udp.0.localPort", 0);
    multi.setString("pdr.udp.0.remoteHost", "127.0.0.1");
    multi.setUInt("pdr.udp.0.remotePort", 9000);
    if (!validator.validate(multi).empty())
        return 9;
    multi.setString("pdr.serial.1.id", "sim-a");
    if (validator.validate(multi).empty())
        return 10;
    multi.setString("pdr.serial.1.id", "serial-b");
    multi.setString("pdr.serial.0.parameters", "9X3");
    if (validator.validate(multi).empty())
        return 11;
    multi.setString("pdr.serial.0.parameters", "8N1");
    multi.setString("pdr.serial.0.flowControl", "xonxoff");
    if (validator.validate(multi).empty())
        return 12;
    multi.setString("pdr.serial.0.flowControl", "none");
    multi.setUInt("pdr.can.0.bitOffset", 500);
    multi.setUInt("pdr.can.0.bitLength", 64);
    if (validator.validate(multi).empty())
        return 13;
    multi.setUInt("pdr.can.0.bitOffset", 0);
    multi.setString("pdr.can.0.frameId", "0x20000000");
    if (validator.validate(multi).empty())
        return 14;
    multi.setString("pdr.can.0.frameId", "0x123");
    multi.setUInt("pdr.xbee.0.analogChannel", 16);
    if (validator.validate(multi).empty())
        return 15;
    multi.setUInt("pdr.xbee.0.analogChannel", 7);
    multi.setString("pdr.xbee.0.sourceAddress", "not-hex");
    if (validator.validate(multi).empty())
        return 16;
    multi.setString("pdr.xbee.0.sourceAddress", "0013A200405291AB");
    multi.setUInt("pdr.udp.0.remotePort", 0);
    if (validator.validate(multi).empty())
        return 17;
    multi.setUInt("pdr.udp.0.remotePort", 9000);
    multi.setUInt("pdr.mqtt.0.reconnectDelayMilliseconds", 2000);
    multi.setUInt("pdr.mqtt.0.reconnectMaximumDelayMilliseconds", 1000);
    if (validator.validate(multi).empty())
        return 18;
    multi.setUInt("pdr.mqtt.0.reconnectDelayMilliseconds", 250);
    multi.setUInt("pdr.mqtt.0.reconnectMaximumDelayMilliseconds", 1000);
    multi.setString("pdr.mqtt.0.serverUri", "ssl://broker.example:8883");
    multi.setString("pdr.mqtt.0.trustStore", "certificates/ca.pem");
    if (!validator.validate(multi).empty())
        return 19;
    multi.setString("pdr.mqtt.0.serverUri", "tcp://broker.example:1883");
    if (validator.validate(multi).empty())
        return 20;
    multi.setString("pdr.mqtt.0.serverUri", "ssl://broker.example:8883");
    multi.setString("pdr.mqtt.0.privateKeyPassword", "secret");
    if (validator.validate(multi).empty())
        return 21;
    multi.setString("pdr.mqtt.0.privateKey", "certificates/client.key");
    multi.setString("pdr.mqtt.0.keyStore", "certificates/client.crt");
    multi.setString("security.profile", "production");
    multi.setBool("pdr.mqtt.0.verifyHostname", false);
    const auto productionIssues = validator.validate(multi);
    if (std::none_of(productionIssues.begin(), productionIssues.end(), [](const auto& issue) {
            return issue.key == "pdr.mqtt.0.verifyHostname";
        }))
        return 22;
    multi.setString("security.profile", "development");
    multi.setBool("pdr.mqtt.0.verifyHostname", true);
    multi.setString("pdr.mqtt.0.passwordEnvironment", "NOT VALID");
    const auto invalidEnvironmentIssues = validator.validate(multi);
    if (std::none_of(invalidEnvironmentIssues.begin(), invalidEnvironmentIssues.end(),
                     [](const auto& issue) {
                         return issue.key == "pdr.mqtt.0.passwordEnvironment" &&
                                issue.message.find("valid environment") != std::string::npos;
                     }))
        return 23;
    multi.setString("pdr.mqtt.0.passwordEnvironment", "PDR_TEST_MQTT_PASSWORD");
    multi.setString("pdr.mqtt.0.password", "inline-secret");
    const auto conflictingSecretIssues = validator.validate(multi);
    if (std::none_of(conflictingSecretIssues.begin(), conflictingSecretIssues.end(),
                     [](const auto& issue) {
                         return issue.key == "pdr.mqtt.0.passwordEnvironment" &&
                                issue.message.find("mutually exclusive") != std::string::npos;
                     }))
        return 24;
    multi.remove("pdr.mqtt.0.password");
    multi.remove("pdr.mqtt.0.passwordEnvironment");
    multi.setString("pdr.ros.0.uri", "wss://ros.example:9443/");
    multi.setString("pdr.ros.0.trustStore", "certificates/ca.pem");
    if (!validator.validate(multi).empty())
        return 25;
    multi.setString("pdr.ros.0.uri", "ws://ros.example:9090/");
    if (validator.validate(multi).empty())
        return 26;
    multi.setString("pdr.ros.0.uri", "wss://ros.example:9443/");
    multi.setString("pdr.ros.0.clientCertificate", "certificates/client.pem");
    if (validator.validate(multi).empty())
        return 27;
    multi.setString("pdr.ros.0.privateKey", "certificates/client.key");
    multi.setString("pdr.ros.0.authorizationEnvironment", "NOT VALID");
    const auto invalidRosEnvironmentIssues = validator.validate(multi);
    if (std::none_of(invalidRosEnvironmentIssues.begin(), invalidRosEnvironmentIssues.end(),
                     [](const auto& issue) {
                         return issue.key == "pdr.ros.0.authorizationEnvironment" &&
                                issue.message.find("valid environment") != std::string::npos;
                     }))
        return 28;
    std::cout << "CONFIGURATION_SMOKE_PASS\n";
}
