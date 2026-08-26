#pragma once

#include "PocoDDS/TransportProviders/Export.h"
#include "PocoDDS/TransportProviders/TransportFactoryService.h"

#include <Poco/AutoPtr.h>

namespace PocoDDS::TransportProviders
{
/// Adapts one OSP provider service into the transport-neutral RuntimeCore
/// registry. The returned RAII token removes the factory on Bundle unload.
PDR_TRANSPORT_PROVIDER_API RuntimeCore::Outcome<RuntimeCore::TransportRegistration>
registerTransportProvider(RuntimeCore::ITransportRegistry& registry,
                          Poco::AutoPtr<TransportFactoryService> provider);
} // namespace PocoDDS::TransportProviders
