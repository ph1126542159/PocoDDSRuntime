#include <PocoDDS/SDK/SDK.h>
#ifdef PDR_SDK_CONSUMER_PROTOCOLS
#include <PocoDDS/Protocols/WebTunnel/LocalForwarder.h>
#include <PocoDDS/Protocols/MQTT/MqttClient.h>
#include <PocoDDS/Protocols/ROS/BridgeClient.h>
#include <PocoDDS/Protocols/UDP/UdpChannel.h>
#endif

#include <iostream>
#include <utility>

int main()
{
    PocoDDS::Application::CommandContext context;
    if (context.expired()) return 1;
    PocoDDS::Security::PrincipalStore emptyIdentityStore;
    if (emptyIdentityStore.required() || emptyIdentityStore.size() != 0) return 4;
#ifdef PDR_SDK_CONSUMER_PROTOCOLS
    PocoDDS::Protocols::WebTunnel::LocalForwarder::Options options;
    options.remoteUri = "ws://127.0.0.1:65535/tunnel";
    options.remotePort = 1;
    PocoDDS::Protocols::WebTunnel::LocalForwarder forwarder(std::move(options));
    if (forwarder.isOpen() || forwarder.localPort() != 0) return 2;
    PocoDDS::Protocols::MQTT::MqttClient::Options mqttOptions;
    PocoDDS::Protocols::ROS::BridgeClient::Options rosOptions;
    PocoDDS::Protocols::UDP::UdpChannel::Options udpOptions;
    static_cast<void>(udpOptions);
    if (!mqttOptions.serverUri.empty() || rosOptions.maximumMessageSize == 0) return 3;
#endif
    std::cout << "PocoDDSRuntime SDK " << PocoDDS::SDK::versionString
#ifdef PDR_SDK_CONSUMER_PROTOCOLS
              << " Protocols=available"
#endif
              << '\n';
    return 0;
}
