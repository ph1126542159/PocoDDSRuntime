#include "PocoDDS/Protocols/ROS/BridgeClient.h"

#include <exception>
#include <iostream>
#include <string>
#include <utility>

int main(int argc, char** argv)
{
    if (argc != 7)
    {
        std::cerr << "usage: pdr-ros-tls-probe URI CA CERT KEY AUTH expect-success|expect-failure\n";
        return 2;
    }
    const bool expectSuccess = std::string(argv[6]) == "expect-success";
    try
    {
        PocoDDS::Protocols::ROS::BridgeClient::Options options;
        options.uri = Poco::URI(argv[1]);
        options.trustStore = argv[2];
        options.clientCertificate = argv[3];
        options.privateKey = argv[4];
        options.authorization = argv[5];
        options.connectTimeoutSeconds = 3;
        PocoDDS::Protocols::ROS::BridgeClient client(std::move(options));
        client.open();
        client.close();
        if (!expectSuccess)
        {
            std::cerr << "ROS_TLS_PROBE_FAIL invalid peer was accepted\n";
            return 3;
        }
        std::cout << "ROS_TLS_PROBE_PASS trusted WebSocket accepted\n";
        return 0;
    }
    catch (const std::exception& error)
    {
        if (expectSuccess)
        {
            std::cerr << "ROS_TLS_PROBE_FAIL " << error.what() << '\n';
            return 4;
        }
        std::cout << "ROS_TLS_PROBE_PASS invalid peer rejected\n";
        return 0;
    }
}
