#pragma once

#include "PocoDDS/RuntimeCore/Contract.h"
#include "PocoDDS/RuntimeCore/Testing/Export.h"
#include "PocoDDS/RuntimeCore/Transport.h"

#include <string>
#include <vector>

namespace PocoDDS::RuntimeCore::Testing
{

struct TransportConformanceExpectations
{
    std::string id;
    TransportCapabilities requiredCapabilities;
};

struct TransportConformanceReport
{
    std::string transportId;
    std::vector<std::string> passedChecks;
};

PDR_RUNTIME_CORE_TESTING_API Outcome<TransportConformanceReport>
runTransportConformance(IMessageTransport& transport,
                        const TransportConformanceExpectations& expectations);

} // namespace PocoDDS::RuntimeCore::Testing
