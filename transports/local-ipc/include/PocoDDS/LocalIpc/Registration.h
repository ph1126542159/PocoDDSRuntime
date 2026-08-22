#pragma once

#include "PocoDDS/LocalIpc/Export.h"
#include "PocoDDS/RuntimeCore/TransportRegistry.h"

namespace PocoDDS::LocalIpc
{

PDR_LOCAL_IPC_API PocoDDS::RuntimeCore::Outcome<PocoDDS::RuntimeCore::TransportRegistration>
registerLocalIpcTransport(PocoDDS::RuntimeCore::ITransportRegistry& registry);

} // namespace PocoDDS::LocalIpc
