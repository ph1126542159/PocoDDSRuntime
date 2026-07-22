#pragma once

#include "PocoDDS/Control/Contracts.h"
#include "PocoDDS/Transport/ITransport.h"

#include <atomic>
#include <chrono>
#include <memory>
#include <mutex>
#include <string>
#include <unordered_map>

namespace PocoDDS::Control
{
class ControlPlaneClient
{
  public:
    explicit ControlPlaneClient(Transport::ITransport& transport, std::string clientId);
    ~ControlPlaneClient();

    ControlPlaneClient(const ControlPlaneClient&) = delete;
    ControlPlaneClient& operator=(const ControlPlaneClient&) = delete;

    CommandResult applyConfiguration(const std::string& targetComponentId,
                                     const std::map<std::string, std::string>& changes,
                                     std::uint64_t expectedRevision,
                                     std::chrono::milliseconds timeout = std::chrono::seconds(3),
                                     const std::string& traceParent = {});

    CommandResult
    executeLifecycle(const std::string& targetComponentId, LifecycleAction action,
                     std::chrono::milliseconds gracefulTimeout = std::chrono::seconds(3),
                     std::chrono::milliseconds responseTimeout = std::chrono::seconds(3),
                     const std::string& traceParent = {});

  private:
    class Pending;
    std::string correlationId();
    CommandResult request(const Transport::Message& message, const std::string& correlationId,
                          std::chrono::milliseconds timeout);
    void receive(const Transport::Message& message);

    Transport::ITransport& _transport;
    std::string _clientId;
    std::atomic_uint64_t _sequence{0};
    std::mutex _mutex;
    bool _stopping{false};
    std::unordered_map<std::string, std::shared_ptr<Pending>> _pending;
    std::unique_ptr<Transport::Subscription> _resultSubscription;
};
} // namespace PocoDDS::Control
