#include <PocoDDS/ServiceClient/Client.h>
#include <PocoDDS/ServiceClient/ProviderRegistry.h>
#include <PocoDDS/ServiceClient/RuntimeCoordinator.h>
#include <PocoDDS/ServiceClient/ServiceClientRuntimeService.h>
#include <PocoDDS/ServiceClient/ServiceInvocationProvider.h>
#include <PocoDDS/ServiceClient/Testing/ProviderConformance.h>

#include <chrono>
#include <type_traits>

int main()
{
    using namespace PocoDDS::ServiceClient;
    using namespace PocoDDS::ServiceDirectory;
    static_assert(std::is_base_of_v<Poco::OSP::Service,
                  ServiceInvocationProvider>);
    static_assert(std::is_base_of_v<Poco::OSP::Service,
                  ServiceClientRuntimeService>);
    const auto conformanceEntryPoint =
        &Testing::runProviderConformance;
    (void)conformanceEntryPoint;
    ProviderRegistry providers;
    if (!providers.snapshot().providers.empty()) return 2;

    InstanceSnapshot instance;
    instance.state = InstanceState::ready;
    instance.advertisement.serviceName = "sdk.service.v1";
    instance.advertisement.instanceId = "sdk-instance";
    instance.advertisement.runtimeId = "sdk-runtime";
    instance.advertisement.runtimeIncarnation = 1;
    instance.advertisement.revision = 1;
    instance.advertisement.endpoint = "local://sdk-instance";
    instance.advertisement.protocol = "local";

    Client client({}, [instance](const RouteRequest&) {
        return RouteResult{SelectionStatus::selected, instance, 1,
                           "SDK route"};
    });
    InvocationRequest request;
    request.route.serviceName = "sdk.service.v1";
    request.operation = "read";
    request.idempotent = true;
    const auto result = client.invoke(request, [](const AttemptContext& context) {
        return context.remaining > std::chrono::milliseconds{0}
                   ? AttemptResult::success({0x01})
                   : AttemptResult::retryable("deadline", "no budget");
    });
    return result && result.payload.size() == 1 &&
                   client.snapshot().succeeded == 1
               ? 0
               : 1;
}
