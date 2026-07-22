#pragma once

#include "PocoDDS/Control/Contracts.h"
#include "PocoDDS/Core/ComponentRegistry.h"
#include "PocoDDS/Transport/ITransport.h"

#include <atomic>
#include <chrono>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>

namespace PocoDDS::Control
{
class DiscoveryAgent
{
  public:
    DiscoveryAgent(Transport::ITransport& transport, Core::ComponentRegistry& registry,
                   std::string nodeId,
                   std::chrono::milliseconds heartbeatInterval = std::chrono::seconds(1),
                   std::chrono::milliseconds lease = std::chrono::seconds(5));
    ~DiscoveryAgent();

    DiscoveryAgent(const DiscoveryAgent&) = delete;
    DiscoveryAgent& operator=(const DiscoveryAgent&) = delete;

    void registerLocal(Core::Component component);
    void unregisterLocal(const std::string& componentId);
    void start();
    void stop();
    void publishNow();
    void sweepExpired();

  private:
    void receive(const Transport::Message& message);
    void run();

    Transport::ITransport& _transport;
    Core::ComponentRegistry& _registry;
    std::string _nodeId;
    std::chrono::milliseconds _heartbeatInterval;
    std::chrono::milliseconds _lease;
    std::unique_ptr<Transport::Subscription> _subscription;
    std::mutex _mutex;
    std::unordered_map<std::string, Core::Component> _local;
    std::unordered_map<std::string, std::chrono::steady_clock::time_point> _lastSeen;
    std::atomic_bool _running{false};
    std::thread _thread;
};
} // namespace PocoDDS::Control
