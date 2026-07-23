#include "PocoDDS/Protocols/ROS/BridgeClient.h"

#include <Poco/JSON/Parser.h>

#include <iostream>

int main()
{
    using Client = PocoDDS::Protocols::ROS::BridgeClient;
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

    if (subscribe->getValue<std::string>("op") != "subscribe" ||
        subscribe->getValue<std::string>("topic") != "/fix" ||
        subscribe->getValue<int>("throttle_rate") != 100 ||
        unsubscribe->getValue<std::string>("op") != "unsubscribe")
        return 1;

    std::cout << "ROS_SMOKE_PASS topic=/fix throttle=100\n";
    return 0;
}
