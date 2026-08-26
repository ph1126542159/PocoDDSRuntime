#pragma once

#include "PocoDDS/FastDdsTransport/Export.h"
#include "PocoDDS/RuntimeCore/TransportRegistry.h"

namespace PocoDDS::FastDdsTransport
{

PDR_FASTDDS_TRANSPORT_API PocoDDS::RuntimeCore::TransportDescriptor fastDdsTransportDescriptor();
PDR_FASTDDS_TRANSPORT_API PocoDDS::RuntimeCore::Outcome<
    std::shared_ptr<PocoDDS::RuntimeCore::IMessageTransport>>
createFastDdsTransport(const PocoDDS::RuntimeCore::TransportConfiguration& configuration);

PDR_FASTDDS_TRANSPORT_API PocoDDS::RuntimeCore::Outcome<PocoDDS::RuntimeCore::TransportRegistration>
registerFastDdsTransport(PocoDDS::RuntimeCore::ITransportRegistry& registry);

} // namespace PocoDDS::FastDdsTransport
