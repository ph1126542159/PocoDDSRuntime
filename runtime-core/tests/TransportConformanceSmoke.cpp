#include "PocoDDS/RuntimeCore/InProcessTransport.h"
#include "PocoDDS/RuntimeCore/Testing/TransportConformance.h"

#include <iostream>

int main()
{
    using namespace PocoDDS::RuntimeCore;
    using namespace PocoDDS::RuntimeCore::Testing;

    InProcessTransport transport;
    const auto report =
        runTransportConformance(transport, {"inproc", {true, false, false, false, false, true}});
    if (!report || report.value().passedChecks.size() != 7)
        return 1;
    std::cout << "PDR_TRANSPORT_CONFORMANCE_PASS transport=" << report.value().transportId
              << " checks=" << report.value().passedChecks.size() << '\n';
    return 0;
}
