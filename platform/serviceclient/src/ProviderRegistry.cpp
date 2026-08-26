#include "PocoDDS/ServiceClient/ProviderRegistry.h"

#include <algorithm>
#include <condition_variable>
#include <map>
#include <mutex>
#include <stdexcept>
#include <thread>
#include <utility>

namespace PocoDDS::ServiceClient
{
namespace
{
bool safeText(const std::string& value, std::size_t maximum)
{
    return !value.empty() && value.size() <= maximum &&
           std::all_of(value.begin(), value.end(), [](unsigned char character) {
               return character >= 0x21 && character <= 0x7e;
           });
}
} // namespace

const char* toString(ProviderAttachStatus value) noexcept
{
    switch (value)
    {
    case ProviderAttachStatus::attached: return "attached";
    case ProviderAttachStatus::invalid: return "invalid";
    case ProviderAttachStatus::duplicateProvider: return "duplicate-provider";
    case ProviderAttachStatus::protocolConflict: return "protocol-conflict";
    case ProviderAttachStatus::capacityExceeded: return "capacity-exceeded";
    case ProviderAttachStatus::closing: return "closing";
    }
    return "invalid";
}

const char* toString(ProviderDispatchStatus value) noexcept
{
    switch (value)
    {
    case ProviderDispatchStatus::invoked: return "invoked";
    case ProviderDispatchStatus::invalid: return "invalid";
    case ProviderDispatchStatus::noProvider: return "no-provider";
    case ProviderDispatchStatus::providerFailure: return "provider-failure";
    case ProviderDispatchStatus::closing: return "closing";
    }
    return "invalid";
}

class ProviderRegistry::Impl
{
public:
    explicit Impl(std::size_t valueMaximumProviders)
        : maximumProviders(valueMaximumProviders)
    {
    }

    struct Entry
    {
        Entry(std::string valueId, std::string valueProtocol,
              ServiceInvocationProvider::Ptr valueProvider)
            : id(std::move(valueId)), protocol(std::move(valueProtocol)),
              provider(std::move(valueProvider))
        {
        }

        bool acquire()
        {
            std::lock_guard<std::mutex> lock(mutex);
            if (!accepting) return false;
            ++active;
            ++activeThreads[std::this_thread::get_id()];
            return true;
        }

        void release() noexcept
        {
            {
                std::lock_guard<std::mutex> lock(mutex);
                if (active > 0) --active;
                const auto thread = activeThreads.find(std::this_thread::get_id());
                if (thread != activeThreads.end())
                {
                    if (thread->second > 1) --thread->second;
                    else activeThreads.erase(thread);
                }
            }
            changed.notify_all();
        }

        void beginRemoval()
        {
            std::lock_guard<std::mutex> lock(mutex);
            if (activeThreads.count(std::this_thread::get_id()) != 0)
                throw std::logic_error(
                    "invocation Provider cannot detach from its own active callback");
            accepting = false;
        }

        void wait()
        {
            std::unique_lock<std::mutex> lock(mutex);
            changed.wait(lock, [&] { return active == 0; });
        }

        ProviderSnapshot snapshot() const
        {
            std::lock_guard<std::mutex> lock(mutex);
            return {id, protocol, accepting, active, dispatched, failed};
        }

        std::string id;
        std::string protocol;
        ServiceInvocationProvider::Ptr provider;
        mutable std::mutex mutex;
        std::condition_variable changed;
        bool accepting{true};
        std::size_t active{0};
        std::map<std::thread::id, std::size_t> activeThreads;
        std::uint64_t dispatched{0};
        std::uint64_t failed{0};
    };

    struct Lease
    {
        explicit Lease(std::shared_ptr<Entry> value): entry(std::move(value)) {}
        ~Lease() { if (entry) entry->release(); }
        std::shared_ptr<Entry> entry;
    };

    mutable std::mutex mutex;
    const std::size_t maximumProviders;
    bool closing{false};
    std::uint64_t generation{0};
    std::uint64_t noProvider{0};
    std::map<std::string, std::shared_ptr<Entry>> byId;
    std::map<std::string, std::shared_ptr<Entry>> byProtocol;
};

ProviderRegistry::ProviderRegistry(std::size_t maximumProviders)
{
    if (maximumProviders == 0 || maximumProviders > 4096)
        throw std::invalid_argument(
            "maximumProviders must be in the range 1..4096");
    _impl = std::make_unique<Impl>(maximumProviders);
}

ProviderRegistry::~ProviderRegistry()
{
    try { closeAndWait(); }
    catch (...) {}
}

ProviderAttachResult ProviderRegistry::attach(
    ServiceInvocationProvider::Ptr provider)
{
    if (!provider)
        return {ProviderAttachStatus::invalid, "", "",
                "Provider service is required"};
    std::string id;
    std::string protocol;
    try
    {
        id = provider->providerId();
        protocol = provider->protocol();
    }
    catch (const std::exception& exception)
    {
        return {ProviderAttachStatus::invalid, id, protocol, exception.what()};
    }
    catch (...)
    {
        return {ProviderAttachStatus::invalid, id, protocol,
                "Provider identity callback threw an unknown exception"};
    }
    if (!safeText(id, 128) || !safeText(protocol, 32))
        return {ProviderAttachStatus::invalid, id, protocol,
                "Provider ID and protocol must be visible ASCII within 128/32 characters"};

    std::lock_guard<std::mutex> lock(_impl->mutex);
    if (_impl->closing)
        return {ProviderAttachStatus::closing, id, protocol,
                "Provider registry is closing"};
    if (_impl->byId.count(id) != 0)
        return {ProviderAttachStatus::duplicateProvider, id, protocol,
                "Provider ID is already attached"};
    if (_impl->byProtocol.count(protocol) != 0)
        return {ProviderAttachStatus::protocolConflict, id, protocol,
                "Protocol already has an invocation Provider"};
    if (_impl->byId.size() >= _impl->maximumProviders)
        return {ProviderAttachStatus::capacityExceeded, id, protocol,
                "Invocation Provider registry capacity is exhausted"};
    auto entry = std::make_shared<Impl::Entry>(id, protocol, std::move(provider));
    _impl->byId.emplace(id, entry);
    _impl->byProtocol.emplace(protocol, std::move(entry));
    ++_impl->generation;
    return {ProviderAttachStatus::attached, id, protocol, "Provider attached"};
}

bool ProviderRegistry::detach(const std::string& providerId)
{
    std::shared_ptr<Impl::Entry> entry;
    {
        std::lock_guard<std::mutex> lock(_impl->mutex);
        const auto found = _impl->byId.find(providerId);
        if (found == _impl->byId.end()) return false;
        entry = found->second;
        entry->beginRemoval();
        _impl->byProtocol.erase(entry->protocol);
        _impl->byId.erase(found);
        ++_impl->generation;
    }
    entry->wait();
    return true;
}

ProviderDispatchResult ProviderRegistry::dispatch(
    const ProviderInvocationRequest& request)
{
    const auto protocol = request.attempt.instance.advertisement.protocol;
    if (!safeText(protocol, 32) || !request.input)
        return {ProviderDispatchStatus::invalid,
                AttemptResult::permanent("invalid-protocol",
                                         "Invocation protocol or input is invalid"),
                "", "Invocation protocol or input is invalid"};
    std::shared_ptr<Impl::Entry> entry;
    {
        std::lock_guard<std::mutex> lock(_impl->mutex);
        if (_impl->closing)
            return {ProviderDispatchStatus::closing,
                    AttemptResult::permanent(
                        "provider-registry-closing",
                        "Invocation Provider registry is closing"),
                    "", "Provider registry is closing"};
        const auto found = _impl->byProtocol.find(protocol);
        if (found == _impl->byProtocol.end())
        {
            ++_impl->noProvider;
            return {ProviderDispatchStatus::noProvider,
                    AttemptResult::permanent(
                        "provider-unavailable",
                        "No local invocation Provider supports protocol " + protocol),
                    "", "No Provider for protocol"};
        }
        entry = found->second;
        if (!entry->acquire())
            return {ProviderDispatchStatus::closing,
                    AttemptResult::permanent(
                        "provider-detaching", "Invocation Provider is detaching"),
                    entry->id, "Provider is detaching"};
    }
    Impl::Lease lease(entry);
    try
    {
        auto result = entry->provider->invoke(request);
        {
            std::lock_guard<std::mutex> lock(entry->mutex);
            ++entry->dispatched;
        }
        return {ProviderDispatchStatus::invoked, std::move(result),
                entry->id, "Provider invoked"};
    }
    catch (const std::exception& exception)
    {
        std::lock_guard<std::mutex> lock(entry->mutex);
        ++entry->dispatched;
        ++entry->failed;
        return {ProviderDispatchStatus::providerFailure,
                AttemptResult::retryable("provider-exception", exception.what()),
                entry->id, exception.what()};
    }
    catch (...)
    {
        std::lock_guard<std::mutex> lock(entry->mutex);
        ++entry->dispatched;
        ++entry->failed;
        return {ProviderDispatchStatus::providerFailure,
                AttemptResult::retryable(
                    "provider-exception", "Unknown Provider exception"),
                entry->id, "Unknown Provider exception"};
    }
}

ProviderRegistrySnapshot ProviderRegistry::snapshot() const
{
    std::lock_guard<std::mutex> lock(_impl->mutex);
    ProviderRegistrySnapshot result;
    result.closing = _impl->closing;
    result.maximumProviders = _impl->maximumProviders;
    result.generation = _impl->generation;
    result.noProvider = _impl->noProvider;
    result.providers.reserve(_impl->byProtocol.size());
    for (const auto& [protocol, entry] : _impl->byProtocol)
    {
        (void) protocol;
        result.providers.push_back(entry->snapshot());
    }
    return result;
}

void ProviderRegistry::closeAndWait()
{
    std::vector<std::shared_ptr<Impl::Entry>> entries;
    {
        std::lock_guard<std::mutex> lock(_impl->mutex);
        if (_impl->closing && _impl->byId.empty()) return;
        for (const auto& [id, entry] : _impl->byId)
        {
            (void) id;
            entry->beginRemoval();
            entries.push_back(entry);
        }
        _impl->closing = true;
        _impl->byId.clear();
        _impl->byProtocol.clear();
        ++_impl->generation;
    }
    for (const auto& entry : entries) entry->wait();
}
} // namespace PocoDDS::ServiceClient
