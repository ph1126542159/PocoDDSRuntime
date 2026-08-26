#include <PocoDDS/ServiceDirectory/Directory.h>
#include <PocoDDS/ServiceDirectory/ServiceAdvertisementProvider.h>
#include <PocoDDS/ServiceDirectory/ServiceDirectoryRuntimeService.h>

#include <type_traits>

int main()
{
    using namespace PocoDDS::ServiceDirectory;
    static_assert(std::is_base_of_v<Poco::OSP::Service,
                  ServiceAdvertisementProvider>);
    static_assert(std::is_base_of_v<Poco::OSP::Service,
                  ServiceDirectoryRuntimeService>);

    Directory directory;
    Advertisement advertisement;
    advertisement.serviceName = "pdr.sdk.test";
    advertisement.instanceId = "sdk-instance";
    advertisement.endpoint = "local://sdk-instance";
    advertisement.protocol = "local";
    advertisement.tags = {"sdk"};
    advertisement.runtimeId = "sdk-runtime";
    advertisement.runtimeIncarnation = 1;
    advertisement.revision = 1;
    if (!directory.observe(advertisement)) return 1;

    RouteRequest request;
    request.serviceName = advertisement.serviceName;
    request.requiredTags = {"sdk"};
    Router router;
    const auto selected = router.select(
        directory.snapshot(), request,
        [](const Advertisement&) { return true; });
    return selected && selected.instance->advertisement.instanceId ==
                           advertisement.instanceId
               ? 0
               : 2;
}
