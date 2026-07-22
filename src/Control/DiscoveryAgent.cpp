#include "PocoDDS/Control/DiscoveryAgent.h"

#include "PocoDDS/Control/ContractCodec.h"

#include <vector>

namespace PocoDDS::Control
{
DiscoveryAgent::DiscoveryAgent(Transport::ITransport& transport, Core::ComponentRegistry& registry,
                               std::string nodeId, std::chrono::milliseconds heartbeatInterval,
                               std::chrono::milliseconds lease)
    : _transport(transport), _registry(registry), _nodeId(std::move(nodeId)),
      _heartbeatInterval(heartbeatInterval), _lease(lease)
{
    if (_nodeId.empty())
        throw std::invalid_argument("discovery node id must not be empty");
    if (_heartbeatInterval.count() <= 0 || _lease <= _heartbeatInterval)
        throw std::invalid_argument("discovery lease must be greater than heartbeat interval");
    _subscription = _transport.subscribe(ComponentTopic, [this](const Transport::Message& message)
                                         { receive(message); });
}

DiscoveryAgent::~DiscoveryAgent() { stop(); }

void DiscoveryAgent::registerLocal(Core::Component component)
{
    if (component.id.empty())
        throw std::invalid_argument("component id must not be empty");
    std::lock_guard lock(_mutex);
    _local[component.id] = std::move(component);
}

void DiscoveryAgent::unregisterLocal(const std::string& componentId)
{
    std::lock_guard lock(_mutex);
    _local.erase(componentId);
}

void DiscoveryAgent::start()
{
    bool expected = false;
    if (!_running.compare_exchange_strong(expected, true))
        return;
    _thread = std::thread([this]() { run(); });
}

void DiscoveryAgent::stop()
{
    if (!_running.exchange(false))
        return;
    if (_thread.joinable())
        _thread.join();
}

void DiscoveryAgent::publishNow()
{
    std::vector<Core::Component> components;
    {
        std::lock_guard lock(_mutex);
        for (const auto& [id, component] : _local)
        {
            static_cast<void>(id);
            components.push_back(component);
        }
    }
    const auto now = std::chrono::duration_cast<std::chrono::milliseconds>(
                         std::chrono::system_clock::now().time_since_epoch())
                         .count();
    for (const auto& component : components)
    {
        ComponentManifest manifest;
        manifest.nodeId = _nodeId;
        manifest.component = component;
        manifest.heartbeatUnixMilliseconds = now;
        manifest.leaseMilliseconds = static_cast<std::uint32_t>(_lease.count());
        _transport.publish({ComponentTopic, "PocoDDS.ComponentManifest.v1", encode(manifest), {}});
    }
}

void DiscoveryAgent::sweepExpired()
{
    std::vector<std::string> expired;
    const auto now = std::chrono::steady_clock::now();
    {
        std::lock_guard lock(_mutex);
        for (const auto& [id, lastSeen] : _lastSeen)
            if (now - lastSeen > _lease)
                expired.push_back(id);
        for (const auto& id : expired)
            _lastSeen.erase(id);
    }
    for (const auto& id : expired)
        _registry.remove(id);
}

void DiscoveryAgent::receive(const Transport::Message& message)
{
    if (message.type != "PocoDDS.ComponentManifest.v1")
        return;
    ComponentManifest manifest;
    try
    {
        manifest = decodeComponentManifest(message.payload);
    }
    catch (const std::invalid_argument&)
    {
        return;
    }
    if (manifest.nodeId == _nodeId)
        return;
    {
        std::lock_guard lock(_mutex);
        _lastSeen[manifest.component.id] = std::chrono::steady_clock::now();
    }
    _registry.upsert(manifest.component);
}

void DiscoveryAgent::run()
{
    while (_running.load())
    {
        publishNow();
        sweepExpired();
        std::this_thread::sleep_for(_heartbeatInterval);
    }
}
} // namespace PocoDDS::Control
