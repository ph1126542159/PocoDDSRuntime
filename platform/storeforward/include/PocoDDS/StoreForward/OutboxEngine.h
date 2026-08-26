#pragma once

#include "PocoDDS/StoreForward/DeliveryProviderService.h"
#include "PocoDDS/StoreForward/OutboxStore.h"

#include <Poco/AutoPtr.h>

#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

namespace PocoDDS::StoreForward
{
class OutboxEngine
{
public:
    using Clock = std::function<Poco::Int64()>;

    OutboxEngine(std::unique_ptr<OutboxStore> store, Policy policy = {},
                 Clock clock = {});

    void initialize();
    void attach(Poco::AutoPtr<DeliveryProviderService> provider);
    void detach(const std::string& type);

    Message enqueue(const EnqueueRequest& request);
    Message cancel(const std::string& id);
    Message redrive(const std::string& id);
    std::size_t pump();
    std::size_t purge();

    Message get(const std::string& id) const;
    std::vector<Message> list() const;
    Snapshot snapshot() const;
    std::vector<std::string> providerTypes() const;

private:
    struct AttachedProvider
    {
        ProviderDescriptor descriptor;
        Poco::AutoPtr<DeliveryProviderService> service;
    };

    void persist(Message& message);
    Message requireMessage(const std::string& id) const;
    std::chrono::milliseconds retryDelay(unsigned attempt,
                                         std::chrono::milliseconds requested) const;

    std::unique_ptr<OutboxStore> _store;
    Policy _policy;
    Clock _clock;
    mutable std::recursive_mutex _mutex;
    std::unordered_map<std::string, AttachedProvider> _providers;
};
} // namespace PocoDDS::StoreForward
