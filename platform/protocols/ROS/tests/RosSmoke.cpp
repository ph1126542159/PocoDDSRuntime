#include "PocoDDS/Protocols/ROS/BridgeClient.h"

#include <Poco/JSON/Parser.h>

#include <iostream>
#include <type_traits>

int main()
{
    using Client = PocoDDS::Protocols::ROS::BridgeClient;
    static_assert(std::is_base_of_v<PocoDDS::Protocols::Protocol, Client>);
    Client::SubscribeOptions options;
    options.type = "sensor_msgs/NavSatFix";
    options.throttleRate = 100;
    options.queueLength = 4;
    options.compression = "none";

    Poco::JSON::Parser parser;
    const auto subscribe = parser.parse(
        Client::makeSubscribeRequest("/fix", "sub-1", options))
        .extract<Poco::JSON::Object::Ptr>();
    const auto unsubscribe = parser.parse(
        Client::makeUnsubscribeRequest("/fix", "sub-1"))
        .extract<Poco::JSON::Object::Ptr>();

    Client client(Poco::URI("ws://127.0.0.1:9090"));
    if (client.name() != "rosbridge" || client.isOpen() ||
        subscribe->getValue<std::string>("op") != "subscribe" ||
        subscribe->getValue<std::string>("topic") != "/fix" ||
        subscribe->getValue<int>("throttle_rate") != 100 ||
        unsubscribe->getValue<std::string>("op") != "unsubscribe")
        return 1;

    std::cout << "ROS_SMOKE_PASS topic=/fix throttle=100\n";
    return 0;
}
