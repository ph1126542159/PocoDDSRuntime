#if defined(PDR_TEST_FASTDDS_TRANSPORT)
#include <PocoDDS/FastDdsTransport/Registration.h>
#endif
#if defined(PDR_TEST_MQTT_TRANSPORT)
#include <PocoDDS/MqttTransport/Registration.h>
#endif
#include <PocoDDS/RuntimeCore/TransportRegistry.h>

#include <iostream>

int main()
{
    PocoDDS::RuntimeCore::TransportRegistry registry;
#if defined(PDR_TEST_MQTT_TRANSPORT)
    auto mqtt = PocoDDS::MqttTransport::registerMqttTransport(registry);
#endif
#if defined(PDR_TEST_FASTDDS_TRANSPORT)
    auto fastdds = PocoDDS::FastDdsTransport::registerFastDdsTransport(registry);
#endif
    std::size_t expected = 0;
#if defined(PDR_TEST_MQTT_TRANSPORT)
    if (!mqtt)
        return 1;
    ++expected;
#endif
#if defined(PDR_TEST_FASTDDS_TRANSPORT)
    if (!fastdds)
        return 1;
    ++expected;
#endif
    if (registry.descriptors().size() != expected)
        return 1;
    std::cout << "PDR_TRANSPORT_CONSUMER_PASS registry=" << expected << '\n';
    return 0;
}
