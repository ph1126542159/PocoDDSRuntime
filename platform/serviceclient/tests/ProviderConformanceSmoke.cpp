#include "PocoDDS/ServiceClient/Testing/ProviderConformance.h"

#include <Poco/AutoPtr.h>
#include <Poco/Timestamp.h>

#include <atomic>
#include <chrono>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

using namespace std::chrono_literals;
using namespace PocoDDS::ServiceClient;
using namespace PocoDDS::ServiceClient::Testing;

namespace
{
void require(bool condition, const std::string& detail)
{
    if (!condition) throw std::runtime_error(detail);
}

class ProbeProvider final : public ServiceInvocationProvider
{
public:
    explicit ProbeProvider(bool honorCancellation)
        : _honorCancellation(honorCancellation)
    {
    }

    std::string providerId() const override { return "conformance-probe"; }
    std::string protocol() const override { return "probe"; }

    AttemptResult invoke(const ProviderInvocationRequest& request) override
    {
        if (!request.input)
            return AttemptResult::permanent(
                "probe-input-invalid", "input is required");
        if (request.invocationId.empty())
            return AttemptResult::permanent(
                "probe-invocation-id-invalid", "invocation ID is required");
        if (_honorCancellation && request.cancellationRequested &&
            request.cancellationRequested())
            return AttemptResult::permanent(
                "cancelled", "invocation was cancelled", true);
        if (request.attempt.remaining <= 0ms ||
            request.deadlineUnixMicroseconds <=
                Poco::Timestamp().epochMicroseconds())
            return AttemptResult::permanent(
                "deadline-exceeded", "invocation deadline expired", true);
        ++_observed;
        return AttemptResult::success(request.input->payload);
    }

    std::uint64_t observed() const noexcept { return _observed.load(); }

private:
    bool _honorCancellation;
    std::atomic<std::uint64_t> _observed{0};
};

ProviderInvocationRequest request()
{
    ProviderInvocationRequest value;
    value.invocationId = "provider-conformance-invocation";
    value.deadlineUnixMicroseconds =
        Poco::Timestamp().epochMicroseconds() + 5000000;
    value.attempt.instance.advertisement.serviceName = "probe.v1";
    value.attempt.instance.advertisement.instanceId = "probe-a";
    value.attempt.instance.advertisement.runtimeId = "runtime-a";
    value.attempt.instance.advertisement.runtimeIncarnation = 1;
    value.attempt.instance.advertisement.protocol = "probe";
    value.attempt.instance.advertisement.endpoint = "probe://fixture";
    value.attempt.attempt = 1;
    value.attempt.remaining = 1000ms;
    value.attempt.operation = "verify";
    value.attempt.idempotencyKey = "provider-conformance-key";
    auto input = std::make_shared<InvocationInput>();
    input->payload = {1, 2, 3, 4};
    input->metadata["content-type"] = "application/octet-stream";
    value.input = std::move(input);
    value.cancellationRequested = [] { return false; };
    return value;
}
} // namespace

int main()
{
    try
    {
        Poco::AutoPtr<ProbeProvider> conforming = new ProbeProvider(true);
        ProviderConformanceExpectations expectations;
        expectations.providerId = "conformance-probe";
        expectations.protocol = "probe";
        expectations.validRequest = request();
        expectations.validResult = [](const AttemptResult& result) {
            return result.payload == std::vector<std::uint8_t>({1, 2, 3, 4});
        };
        expectations.observedInvocations = [conforming] {
            return conforming->observed();
        };
        expectations.maximumCallDuration = 100ms;
        const auto passed = runProviderConformance(*conforming, expectations);
        require(passed && passed.report.passedChecks.size() == 9 &&
                    conforming->observed() == 1,
                "conforming Provider did not pass the shared TCK: " +
                    passed.failedCheck + " " + passed.detail);

        Poco::AutoPtr<ProbeProvider> nonConforming = new ProbeProvider(false);
        expectations.observedInvocations = [nonConforming] {
            return nonConforming->observed();
        };
        const auto rejected = runProviderConformance(
            *nonConforming, expectations);
        require(!rejected && rejected.failedCheck == "pre-cancellation" &&
                    nonConforming->observed() == 1,
                "TCK did not reject a Provider that ignored cancellation");

        std::cout << "SERVICE_CLIENT_PROVIDER_CONFORMANCE_PASS checks="
                  << passed.report.passedChecks.size()
                  << " detected=" << rejected.failedCheck << '\n';
        return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << "SERVICE_CLIENT_PROVIDER_CONFORMANCE_ERROR: "
                  << exception.what() << '\n';
        return 1;
    }
}
