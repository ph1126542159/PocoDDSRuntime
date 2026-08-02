#include "PocoDDS/Protocols/MQTT/MqttClient.h"

#include <exception>
#include <iostream>
#include <string>

int main(int argc, char** argv)
{
    if (argc != 4)
    {
        std::cerr << "usage: pdr-mqtt-tls-probe URI CA_FILE expect-success|expect-failure\n";
        return 2;
    }
    const bool expectSuccess = std::string(argv[3]) == "expect-success";
    try
    {
        PocoDDS::Protocols::MQTT::MqttClient::Options options;
        options.serverUri = argv[1];
        options.clientId = expectSuccess ? "pdr-mqtt-tls-ok" : "pdr-mqtt-tls-reject";
        options.trustStore = argv[2];
        options.connectTimeoutSeconds = 3;
        PocoDDS::Protocols::MQTT::MqttClient client(std::move(options));
        client.open();
        client.close();
        if (!expectSuccess)
        {
            std::cerr << "MQTT_TLS_PROBE_FAIL untrusted certificate was accepted\n";
            return 3;
        }
        std::cout << "MQTT_TLS_PROBE_PASS trusted certificate accepted\n";
        return 0;
    }
    catch (const std::exception& error)
    {
        if (expectSuccess)
        {
            std::cerr << "MQTT_TLS_PROBE_FAIL " << error.what() << '\n';
            return 4;
        }
        std::cout << "MQTT_TLS_PROBE_PASS untrusted certificate rejected\n";
        return 0;
    }
}
