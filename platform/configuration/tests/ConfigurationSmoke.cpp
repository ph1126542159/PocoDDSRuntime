#include "PocoDDS/Configuration/ConfigurationValidator.h"

#include "Poco/Util/MapConfiguration.h"

#include <iostream>

int main()
{
    Poco::Util::MapConfiguration valid;
    valid.setString("osp.web.server.host", "127.0.0.1");
    valid.setInt("osp.web.server.port", 9080);
    valid.setInt("pdr.fastdds.domainId", 0);
    valid.setInt("pdr.subprocess.shutdownTimeoutMilliseconds", 5000);
    PocoDDS::Configuration::ConfigurationValidator validator;
    if (!validator.validate(valid).empty())
        return 1;
    valid.setString("osp.web.server.port", "invalid");
    if (validator.validate(valid).size() != 1)
        return 2;
    std::cout << "CONFIGURATION_SMOKE_PASS\n";
}
