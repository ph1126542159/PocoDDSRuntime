#include "PocoDDS/Configuration/ConfigurationValidator.h"
#include "PocoDDS/Configuration/IndexedConfiguration.h"

#include "Poco/Exception.h"
#include "Poco/Util/MapConfiguration.h"

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
    std::cout << "CONFIGURATION_SMOKE_PASS\n";
}
