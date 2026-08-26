#include "PocoDDS/ServiceClient/ProviderRegistry.h"

#include <Poco/AutoPtr.h>

#include <atomic>
#include <chrono>
#include <future>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>

using namespace std::chrono_literals;
using namespace PocoDDS::ServiceClient;

namespace
{
void require(bool condition, const std::string& detail)
{
    if (!condition) throw std::runtime_error(detail);
}

class FakeProvider final : public ServiceInvocationProvider
{
public:
    using Callback = std::function<AttemptResult(
        const ProviderInvocationRequest&)>;

    FakeProvider(std::string valueId, std::string valueProtocol,
                 Callback callback)
        : _id(std::move(valueId)), _protocol(std::move(valueProtocol)),
          _callback(std::move(callback))
    {
    }

    std::string providerId() const override { return _id; }
    std::string protocol() const override { return _protocol; }
    AttemptResult invoke(const ProviderInvocationRequest& request) override
    {
        return _callback(request);
    }

private:
    std::string _id;
    std::string _protocol;
    Callback _callback;
};

ProviderInvocationRequest request(const std::string& protocol)
{
    ProviderInvocationRequest value;
    value.attempt.instance.advertisement.serviceName = "orders.v1";
    value.attempt.instance.advertisement.instanceId = "orders-a";
    value.attempt.instance.advertisement.runtimeId = "runtime-a";
    value.attempt.instance.advertisement.runtimeIncarnation = 1;
    value.attempt.instance.advertisement.protocol = protocol;
    value.attempt.remaining = 1000ms;
    value.attempt.attempt = 1;
    value.attempt.operation = "read";
    value.input = std::make_shared<InvocationInput>();
    return value;
}
} // namespace

int main()
{
    try
    {
        ProviderRegistry registry;
        ServiceInvocationProvider::Ptr provider = new FakeProvider(
            "loopback-provider", "loopback",
            [](const ProviderInvocationRequest& value) {
                return AttemptResult::success(value.input->payload);
            });
        require(static_cast<bool>(registry.attach(provider)),
                "valid Provider was not attached");
        require(registry.attach(provider).status ==
                    ProviderAttachStatus::duplicateProvider,
                "duplicate Provider ID was accepted");
        require(registry.attach(new FakeProvider(
                    "other-provider", "loopback",
                    [](const ProviderInvocationRequest&) {
                        return AttemptResult::success();
                    })).status == ProviderAttachStatus::protocolConflict,
                "duplicate protocol Provider was accepted");

        ProviderRegistry boundedRegistry(1);
        require(static_cast<bool>(boundedRegistry.attach(new FakeProvider(
                    "bounded-a", "bounded-a",
                    [](const ProviderInvocationRequest&) {
                        return AttemptResult::success();
                    }))),
                "bounded Provider registry rejected its first Provider");
        require(boundedRegistry.attach(new FakeProvider(
                    "bounded-b", "bounded-b",
                    [](const ProviderInvocationRequest&) {
                        return AttemptResult::success();
                    })).status == ProviderAttachStatus::capacityExceeded,
                "bounded Provider registry exceeded its configured capacity");
        require(boundedRegistry.snapshot().maximumProviders == 1,
                "Provider registry capacity is absent from its snapshot");

        auto invocation = request("loopback");
        auto input = std::make_shared<InvocationInput>();
        input->payload = {0x4f, 0x4b};
        invocation.input = input;
        const auto dispatched = registry.dispatch(invocation);
        require(dispatched && dispatched.providerId == "loopback-provider" &&
                    dispatched.result.payload == input->payload,
                "Provider dispatch failed");
        require(registry.dispatch(request("missing")).status ==
                    ProviderDispatchStatus::noProvider,
                "missing protocol was not rejected");

        require(registry.detach("loopback-provider"),
                "Provider detach failed");
        ServiceInvocationProvider::Ptr throwing = new FakeProvider(
            "throwing-provider", "throwing",
            [](const ProviderInvocationRequest&) -> AttemptResult {
                throw std::runtime_error("provider failed");
            });
        require(static_cast<bool>(registry.attach(throwing)),
                "throwing Provider attach failed");
        const auto failed = registry.dispatch(request("throwing"));
        require(failed.status == ProviderDispatchStatus::providerFailure &&
                    failed.result.disposition ==
                        AttemptDisposition::retryableFailure &&
                    failed.detail == "provider failed",
                "Provider exception escaped the registry boundary");
        require(registry.detach("throwing-provider"),
                "throwing Provider detach failed");

        std::promise<void> enteredPromise;
        auto entered = enteredPromise.get_future();
        std::promise<void> releasePromise;
        auto release = releasePromise.get_future();
        ServiceInvocationProvider::Ptr blocking = new FakeProvider(
            "blocking-provider", "blocking",
            [&](const ProviderInvocationRequest&) {
                enteredPromise.set_value();
                release.wait();
                return AttemptResult::success();
            });
        require(static_cast<bool>(registry.attach(blocking)),
                "blocking Provider attach failed");
        ProviderDispatchResult blockingResult;
        std::thread invocationThread([&] {
            blockingResult = registry.dispatch(request("blocking"));
        });
        require(entered.wait_for(2s) == std::future_status::ready,
                "blocking Provider did not enter invocation");
        std::atomic<bool> detached{false};
        std::thread detachThread([&] {
            registry.detach("blocking-provider");
            detached = true;
        });
        std::this_thread::sleep_for(20ms);
        require(!detached.load(),
                "Provider detach returned while invocation was active");
        releasePromise.set_value();
        invocationThread.join();
        detachThread.join();
        require(blockingResult && detached.load(),
                "Provider invocation did not drain before detach");

        ServiceInvocationProvider::Ptr selfDetaching = new FakeProvider(
            "self-provider", "self",
            [&](const ProviderInvocationRequest&) {
                registry.detach("self-provider");
                return AttemptResult::success();
            });
        require(static_cast<bool>(registry.attach(selfDetaching)),
                "self-detaching Provider attach failed");
        const auto selfResult = registry.dispatch(request("self"));
        require(selfResult.status == ProviderDispatchStatus::providerFailure &&
                    selfResult.detail.find("own active callback") !=
                        std::string::npos,
                "unsafe self-detach was not rejected");
        require(registry.detach("self-provider"),
                "self Provider did not remain safely attached");

        const auto beforeClose = registry.snapshot();
        require(beforeClose.providers.empty() && beforeClose.noProvider == 1,
                "Provider registry snapshot is incorrect");
        registry.closeAndWait();
        require(registry.attach(provider).status == ProviderAttachStatus::closing,
                "closed Provider registry accepted a Provider");
        require(registry.dispatch(request("loopback")).status ==
                    ProviderDispatchStatus::closing,
                "closed Provider registry dispatched work");

        std::cout << "SERVICE_CLIENT_PROVIDER_REGISTRY_PASS generation="
                  << registry.snapshot().generation
                  << " noProvider=" << beforeClose.noProvider << '\n';
        return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << "SERVICE_CLIENT_PROVIDER_REGISTRY_ERROR: "
                  << exception.what() << '\n';
        return 1;
    }
}
