#pragma once

#include "PocoDDS/MqttTransport/Export.h"
#include "PocoDDS/RuntimeCore/TransportRegistry.h"

namespace PocoDDS::MqttTransport
{

PDR_MQTT_TRANSPORT_API PocoDDS::RuntimeCore::Outcome<PocoDDS::RuntimeCore::TransportRegistration>
registerMqttTransport(PocoDDS::RuntimeCore::ITransportRegistry& registry);

} // namespace PocoDDS::MqttTransport
