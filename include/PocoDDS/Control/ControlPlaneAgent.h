#pragma once

#include "PocoDDS/Control/Contracts.h"
#include "PocoDDS/Core/Configuration.h"
#include "PocoDDS/Transport/ITransport.h"

#include <atomic>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <string>

namespace PocoDDS::Control
{
class ControlPlaneAgent
{
  public:
    using LifecycleHandler = std::function<void(const LifecycleCommand&)>;

    ControlPlaneAgent(Transport::ITransport& transport, Core::Configuration& configuration,
                      std::string componentId, LifecycleHandler lifecycleHandler);

    std::uint64_t configurationRevision() const;

  private:
    void receiveConfiguration(const Transport::Message& message);
    void receiveLifecycle(const Transport::Message& message);
    void send(CommandResult result, const std::string& traceParent);

    Transport::ITransport& _transport;
    Core::Configuration& _configuration;
    std::string _componentId;
    LifecycleHandler _lifecycleHandler;
    std::mutex _commandMutex;
    std::atomic_uint64_t _revision{0};
    std::unique_ptr<Transport::Subscription> _configurationSubscription;
    std::unique_ptr<Transport::Subscription> _lifecycleSubscription;
};
} // namespace PocoDDS::Control
