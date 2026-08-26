#include "PocoDDS/ServiceClient/Testing/ProviderConformance.h"

#include <Poco/Timestamp.h>

#include <algorithm>
#include <chrono>
#include <exception>
#include <string>
#include <utility>

namespace PocoDDS::ServiceClient::Testing
{
namespace
{
bool visibleAscii(const std::string& value, std::size_t maximum,
                  bool required = true)
{
    return (!required || !value.empty()) && value.size() <= maximum &&
        std::all_of(value.begin(), value.end(), [](unsigned char character) {
            return character >= 0x21 && character <= 0x7e;
        });
}

ProviderConformanceResult failed(ProviderConformanceReport report,
                                 std::string check, std::string detail)
{
    return {false, std::move(report), std::move(check), std::move(detail)};
}

bool inputUnchanged(const ProviderInvocationRequest& request,
                    const InvocationInput& expected)
{
    return request.input && request.input->payload == expected.payload &&
        request.input->metadata == expected.metadata;
}
} // namespace

ProviderConformanceResult runProviderConformance(
    ServiceInvocationProvider& provider,
    const ProviderConformanceExpectations& expectations)
{
    ProviderConformanceReport report;
    report.providerId = expectations.providerId;
    report.protocol = expectations.protocol;
    if (!visibleAscii(expectations.providerId, 128) ||
        !visibleAscii(expectations.protocol, 32) ||
        !expectations.validRequest.input ||
        !expectations.validResult || !expectations.observedInvocations ||
        expectations.maximumCallDuration < std::chrono::milliseconds{1})
        return failed(std::move(report), "fixture",
                      "conformance expectations are incomplete or invalid");

    try
    {
        const auto firstId = provider.providerId();
        const auto firstProtocol = provider.protocol();
        if (firstId != expectations.providerId ||
            firstProtocol != expectations.protocol ||
            provider.providerId() != firstId ||
            provider.protocol() != firstProtocol)
            return failed(std::move(report), "identity",
                          "Provider identity is mismatched or unstable");
    }
    catch (...)
    {
        return failed(std::move(report), "identity",
                      "Provider identity callback threw");
    }
    report.passedChecks.push_back("identity");

    const auto& valid = expectations.validRequest;
    if (!visibleAscii(valid.invocationId, 128) ||
        valid.deadlineUnixMicroseconds <=
            Poco::Timestamp().epochMicroseconds() ||
        valid.attempt.attempt == 0 ||
        valid.attempt.remaining <= std::chrono::milliseconds{0} ||
        !valid.cancellationRequested || valid.cancellationRequested() ||
        !visibleAscii(valid.attempt.operation, 128) ||
        valid.attempt.instance.advertisement.protocol != expectations.protocol)
        return failed(std::move(report), "fixture-request",
                      "valid fixture request does not satisfy Provider contract");
    const InvocationInput originalInput = *valid.input;
    report.passedChecks.push_back("fixture-request");

    const auto negative = [&](std::string check,
                              ProviderInvocationRequest request,
                              const std::string& requiredCode)
        -> ProviderConformanceResult {
        const auto before = expectations.observedInvocations();
        AttemptResult result;
        const auto started = std::chrono::steady_clock::now();
        try { result = provider.invoke(request); }
        catch (...)
        {
            return failed(report, std::move(check),
                          "Provider threw for a negative contract probe");
        }
        const auto duration = std::chrono::duration_cast<
            std::chrono::milliseconds>(
                std::chrono::steady_clock::now() - started);
        if (duration > expectations.maximumCallDuration)
            return failed(report, std::move(check),
                          "negative probe exceeded the call duration budget");
        if (expectations.observedInvocations() != before)
            return failed(report, std::move(check),
                          "negative probe produced an outbound side effect");
        if (result.disposition != AttemptDisposition::permanentFailure ||
            !visibleAscii(result.code, 128) ||
            (!requiredCode.empty() && result.code != requiredCode))
            return failed(report, std::move(check),
                          "negative probe was not rejected with the required code");
        if (!inputUnchanged(valid, originalInput))
            return failed(report, std::move(check),
                          "Provider mutated the shared invocation input");
        auto success = ProviderConformanceResult{};
        success.passed = true;
        return success;
    };

    auto invalidId = valid;
    invalidId.invocationId.clear();
    auto checked = negative("invalid-invocation-id", std::move(invalidId), "");
    if (!checked) return checked;
    report.passedChecks.push_back("invalid-invocation-id");

    auto missingInput = valid;
    missingInput.input.reset();
    checked = negative("missing-input", std::move(missingInput), "");
    if (!checked) return checked;
    report.passedChecks.push_back("missing-input");

    auto cancelled = valid;
    cancelled.cancellationRequested = [] { return true; };
    checked = negative("pre-cancellation", std::move(cancelled), "cancelled");
    if (!checked) return checked;
    report.passedChecks.push_back("pre-cancellation");

    auto expired = valid;
    expired.deadlineUnixMicroseconds =
        Poco::Timestamp().epochMicroseconds() - 1;
    expired.attempt.remaining = std::chrono::milliseconds{0};
    checked = negative("expired-deadline", std::move(expired),
                       "deadline-exceeded");
    if (!checked) return checked;
    report.passedChecks.push_back("expired-deadline");

    const auto before = expectations.observedInvocations();
    AttemptResult result;
    const auto started = std::chrono::steady_clock::now();
    try { result = provider.invoke(valid); }
    catch (const std::exception& exception)
    {
        return failed(std::move(report), "valid-invocation",
                      std::string("Provider threw: ") + exception.what());
    }
    catch (...)
    {
        return failed(std::move(report), "valid-invocation",
                      "Provider threw an unknown exception");
    }
    const auto duration = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - started);
    if (duration > expectations.maximumCallDuration)
        return failed(std::move(report), "valid-invocation",
                      "valid invocation exceeded the call duration budget");
    if (expectations.observedInvocations() != before + 1)
        return failed(std::move(report), "valid-invocation",
                      "valid invocation did not produce exactly one outbound call");
    if (result.disposition != AttemptDisposition::succeeded ||
        !result.endpointHealthy || !expectations.validResult(result))
        return failed(std::move(report), "valid-result",
                      "valid invocation result did not satisfy expectations");
    if (!inputUnchanged(valid, originalInput))
        return failed(std::move(report), "input-immutability",
                      "Provider mutated the shared invocation input");
    report.passedChecks.push_back("valid-invocation");
    report.passedChecks.push_back("input-immutability");

    try
    {
        if (provider.providerId() != expectations.providerId ||
            provider.protocol() != expectations.protocol)
            return failed(std::move(report), "identity-stability",
                          "Provider identity changed after invocation");
    }
    catch (...)
    {
        return failed(std::move(report), "identity-stability",
                      "Provider identity callback threw after invocation");
    }
    report.passedChecks.push_back("identity-stability");
    return {true, std::move(report), {}, {}};
}
} // namespace PocoDDS::ServiceClient::Testing
