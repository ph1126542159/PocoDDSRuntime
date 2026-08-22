#include "PocoDDS/Configuration/ConfigurationValidator.h"
#include "PocoDDS/Configuration/IndexedConfiguration.h"

#include "Poco/Exception.h"
#include "Poco/Util/MapConfiguration.h"
#include "Poco/Environment.h"
#include "Poco/TemporaryFile.h"

#include <algorithm>
#include <fstream>
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
    if (validator.validate(valid).size() != 5)
        return 4;
    Poco::Environment::set("PDR_CONFIGURATION_TEST_MANAGEMENT_TOKEN", "test-token");
    valid.setBool("pdr.management.authentication.required", true);
    valid.setString("pdr.management.authentication.tokenEnvironment",
                    "PDR_CONFIGURATION_TEST_MANAGEMENT_TOKEN");
    valid.setBool("pdr.management.idempotency.requireRequestId", true);
    valid.setString("osp.web.authServiceName", "oidc.auth");
    valid.setInt("osp.web.server.securePort", 9443);
    valid.setBool("auth.simple.enable", false);
    if (!validator.validate(valid).empty())
        return 5;
    valid.setInt("pdr.alerts.debounceMilliseconds", 2000);
    valid.setInt("pdr.alerts.escalationMilliseconds", 1000);
    if (validator.validate(valid).size() != 1)
        return 51;
    valid.setInt("pdr.alerts.escalationMilliseconds", 3000);
    valid.setInt("pdr.alerts.retention", 0);
    if (validator.validate(valid).size() != 1)
        return 52;
    valid.setInt("pdr.alerts.retention", 500);
    valid.setBool("pdr.alerts.history.enabled", true);
    if (validator.validate(valid).size() != 1)
        return 54;
    valid.setString("pdr.alerts.history.path", "data/alerts.jsonl");
    valid.setInt("pdr.alerts.history.maximumBytes", 1024);
    if (!validator.validate(valid).empty())
        return 53;
    valid.setInt("pdr.alerts.deliveryFailureThreshold", 0);
    if (validator.validate(valid).size() != 1)
        return 55;
    valid.setInt("pdr.alerts.deliveryFailureThreshold", 5);
    valid.setInt("pdr.alerts.deliveryCircuitOpenMilliseconds", 99);
    if (validator.validate(valid).size() != 1)
        return 56;
    valid.setInt("pdr.alerts.deliveryCircuitOpenMilliseconds", 30000);

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
    multi.remove("pdr.ros.0.authorizationEnvironment");
    multi.setBool("pdr.alerts.webhook.enabled", true);
    multi.setString("pdr.alerts.webhook.url", "http://127.0.0.1:18080/alerts");
    multi.setUInt("pdr.alerts.webhook.timeoutMilliseconds", 1000);
    multi.setUInt("pdr.alerts.webhook.maximumAttempts", 3);
    multi.setUInt("pdr.alerts.webhook.initialBackoffMilliseconds", 50);
    multi.setUInt("pdr.alerts.webhook.maximumBackoffMilliseconds", 100);
    multi.setString("pdr.alerts.webhook.authorizationEnvironment", "");
    if (!validator.validate(multi).empty())
        return 29;
    multi.setUInt("pdr.alerts.webhook.maximumBackoffMilliseconds", 25);
    const auto invalidBackoffIssues = validator.validate(multi);
    if (std::none_of(invalidBackoffIssues.begin(), invalidBackoffIssues.end(),
                     [](const auto& issue) {
                         return issue.key == "pdr.alerts.webhook.maximumBackoffMilliseconds";
                     }))
        return 30;
    multi.setUInt("pdr.alerts.webhook.maximumBackoffMilliseconds", 100);
    multi.setString("pdr.alerts.webhook.authorizationEnvironment", "NOT VALID");
    const auto invalidWebhookEnvironmentIssues = validator.validate(multi);
    if (std::none_of(invalidWebhookEnvironmentIssues.begin(),
                     invalidWebhookEnvironmentIssues.end(), [](const auto& issue) {
                         return issue.key == "pdr.alerts.webhook.authorizationEnvironment" &&
                                issue.message.find("valid environment") != std::string::npos;
                     }))
        return 31;
    multi.setString("pdr.alerts.webhook.authorizationEnvironment", "");
    multi.setString("pdr.alerts.webhook.url", "https://alerts.example.test/events");
    multi.setString("security.profile", "production");
    multi.setBool("pdr.alerts.webhook.insecureSkipVerify", true);
    const auto insecureWebhookIssues = validator.validate(multi);
    if (std::none_of(insecureWebhookIssues.begin(), insecureWebhookIssues.end(),
                     [](const auto& issue) {
                         return issue.key == "pdr.alerts.webhook.insecureSkipVerify";
                     }))
        return 32;
    multi.setString("security.profile", "development");
    multi.setUInt("pdr.alerts.webhook.count", 2);
    multi.setString("pdr.alerts.webhook.0.id", "operations");
    multi.setString("pdr.alerts.webhook.0.url", "https://ops.example.test/events");
    multi.setUInt("pdr.alerts.webhook.0.timeoutMilliseconds", 1000);
    multi.setString("pdr.alerts.webhook.1.id", "audit");
    multi.setString("pdr.alerts.webhook.1.url", "http://127.0.0.1:18081/audit");
    multi.setUInt("pdr.alerts.webhook.1.maximumAttempts", 1);
    if (!validator.validate(multi).empty())
        return 33;
    multi.setString("pdr.alerts.webhook.1.id", "operations");
    if (validator.validate(multi).empty())
        return 34;
    multi.setString("pdr.alerts.webhook.1.id", "audit");
    multi.setString("pdr.management.manageableBundles",
                    "pdr.service.*, pdr.alert.*, acme.customer.bundle");
    if (!validator.validate(multi).empty())
        return 35;
    multi.setString("pdr.management.manageableBundles", "*");
    if (validator.validate(multi).empty())
        return 36;
    multi.setString("pdr.management.manageableBundles", "acme.*,acme.*");
    const auto duplicateManagementIssues = validator.validate(multi);
    if (std::none_of(duplicateManagementIssues.begin(), duplicateManagementIssues.end(),
                     [](const auto& issue) {
                         return issue.key == "pdr.management.manageableBundles" &&
                                issue.message.find("duplicate") != std::string::npos;
                     }))
        return 37;
    multi.setString("pdr.management.manageableBundles",
                    "pdr.service.*, pdr.alert.*, acme.customer.bundle");
    multi.setString("logging.loggers.root.level", "verbose");
    if (validator.validate(multi).empty())
        return 38;
    multi.setString("logging.loggers.root.level", "debug");
    if (!validator.validate(multi).empty())
        return 39;
    multi.setBool("pdr.management.authentication.required", true);
    multi.setString("pdr.management.authentication.tokenEnvironment", "");
    if (validator.validate(multi).empty())
        return 40;
    multi.setString("pdr.management.authentication.tokenEnvironment", "NOT VALID");
    if (validator.validate(multi).empty())
        return 41;
    multi.setString("pdr.management.authentication.tokenEnvironment",
                    "PDR_CONFIGURATION_TEST_MANAGEMENT_TOKEN");
    if (!validator.validate(multi).empty())
        return 42;
    Poco::Environment::set("PDR_CONFIGURATION_TEST_OPERATOR_TOKEN", "operator-token");
    multi.setString("pdr.management.authentication.tokenEnvironment", "");
    multi.setInt("pdr.management.authentication.principals.count", 1);
    multi.setString("pdr.management.authentication.principals.0.id", "operator");
    multi.setString("pdr.management.authentication.principals.0.tokenEnvironment",
                    "PDR_CONFIGURATION_TEST_OPERATOR_TOKEN");
    multi.setString("pdr.management.authentication.principals.0.permissions",
                    "protocol.manage, process.manage, bundle.manage, diagnostics.read, diagnostics.execute");
    if (!validator.validate(multi).empty())
        return 43;
    multi.setString("pdr.management.authentication.principals.0.permissions",
                    "protocol.manage,root.everything");
    if (validator.validate(multi).empty())
        return 44;
    multi.setString("pdr.management.authentication.principals.0.permissions", "*");
    if (!validator.validate(multi).empty())
        return 45;
    multi.setInt("pdr.management.authentication.principals.count", 2);
    multi.setString("pdr.management.authentication.principals.1.id", "operator");
    multi.setString("pdr.management.authentication.principals.1.tokenEnvironment",
                    "PDR_CONFIGURATION_TEST_MANAGEMENT_TOKEN");
    multi.setString("pdr.management.authentication.principals.1.permissions",
                    "configuration.manage");
    if (validator.validate(multi).empty())
        return 46;
    Poco::Environment::set("PDR_CONFIGURATION_TEST_DUPLICATE_TOKEN", "operator-token");
    multi.setString("pdr.management.authentication.principals.1.id", "auditor");
    multi.setString("pdr.management.authentication.principals.1.tokenEnvironment",
                    "PDR_CONFIGURATION_TEST_DUPLICATE_TOKEN");
    const auto duplicateTokenIssues = validator.validate(multi);
    if (std::none_of(duplicateTokenIssues.begin(), duplicateTokenIssues.end(),
                     [](const auto& issue) {
                         return issue.key ==
                                    "pdr.management.authentication.principals.1.tokenEnvironment" &&
                                issue.message.find("duplicates another management bearer token value") !=
                                    std::string::npos;
                     }))
        return 59;
    multi.setInt("pdr.management.authentication.principals.count", 1);
    Poco::TemporaryFile managementTokenFile;
    {
        std::ofstream tokenStream(managementTokenFile.path(),
                                  std::ios::binary | std::ios::trunc);
        tokenStream << "file-backed-token\n";
        tokenStream.close();
        if (!tokenStream.good()) return 60;
    }
    multi.setString("pdr.management.authentication.principals.0.tokenEnvironment", "");
    multi.setString("pdr.management.authentication.principals.0.tokenFile",
                    managementTokenFile.path());
    if (!validator.validate(multi).empty()) return 61;
    multi.setString("pdr.management.authentication.principals.0.tokenEnvironment",
                    "PDR_CONFIGURATION_TEST_OPERATOR_TOKEN");
    if (validator.validate(multi).empty()) return 62;
    multi.setString("pdr.management.authentication.principals.0.tokenEnvironment", "");
    {
        std::ofstream tokenStream(managementTokenFile.path(),
                                  std::ios::binary | std::ios::trunc);
    }
    if (validator.validate(multi).empty()) return 63;
    {
        std::ofstream tokenStream(managementTokenFile.path(),
                                  std::ios::binary | std::ios::trunc);
        tokenStream << "file-backed-token\n";
    }
    multi.setString("pdr.management.authentication.principals.0.permissions", "audit.read");
    multi.setBool("pdr.management.audit.enabled", true);
    multi.setString("pdr.management.audit.path", "");
    if (validator.validate(multi).empty())
        return 47;
    multi.setString("pdr.management.audit.path", "management-audit.jsonl");
    multi.setInt("pdr.management.audit.maximumBytes", 1023);
    if (validator.validate(multi).empty())
        return 48;
    multi.setInt("pdr.management.audit.maximumBytes", 4194304);
    multi.setInt("pdr.management.idempotency.retention", 0);
    if (validator.validate(multi).empty()) return 56;
    multi.setInt("pdr.management.idempotency.retention", 1000);
    multi.setInt64("pdr.management.idempotency.ttlMilliseconds", 999);
    if (validator.validate(multi).empty()) return 57;
    multi.setInt64("pdr.management.idempotency.ttlMilliseconds", 86400000);
    multi.setBool("pdr.management.idempotency.persistence.enabled", true);
    multi.setString("pdr.management.idempotency.persistence.path", "");
    if (validator.validate(multi).empty()) return 58;
    multi.setString("pdr.management.idempotency.persistence.path",
                    "management-idempotency.json");
    if (!validator.validate(multi).empty())
        return 49;
    multi.setInt("pdr.management.tasks.workerCount", 0);
    if (validator.validate(multi).empty())
        return 50;
    multi.setInt("pdr.management.tasks.workerCount", 2);
    multi.setInt("pdr.management.tasks.capacity", 100);
    multi.setInt("pdr.management.tasks.retention", 1000);
    multi.setInt("pdr.management.tasks.health.degradedWaitMilliseconds", 0);
    if (validator.validate(multi).empty()) return 55;
    multi.setInt("pdr.management.tasks.health.degradedWaitMilliseconds", 30000);
    if (!validator.validate(multi).empty())
        return 51;
    multi.setBool("pdr.management.tasks.persistence.enabled", true);
    multi.setString("pdr.management.tasks.persistence.path", "");
    if (validator.validate(multi).empty())
        return 52;
    multi.setString("pdr.management.tasks.persistence.path", "management-tasks.json");
    if (!validator.validate(multi).empty())
        return 53;
    std::cout << "CONFIGURATION_SMOKE_PASS\n";
}
