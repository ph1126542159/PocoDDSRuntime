#pragma once

#include "PocoDDS/RuntimeCore/Contract.h"
#include "PocoDDS/RuntimeCore/Export.h"

#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

namespace PocoDDS::RuntimeCore
{

struct ComponentDependency
{
    std::string id;
    bool required{true};
};

struct ComponentDescriptor
{
    std::string id;
    std::string version{"1.0.0"};
    std::vector<ComponentDependency> dependencies;
    bool required{true};
};

struct HostEnvironment
{
    std::string profile;
    std::string hostModel;
    std::vector<std::string> transports;
    std::unordered_map<std::string, std::string> properties;
};

enum class HealthState
{
    unknown,
    healthy,
    degraded,
    unhealthy,
    stopped
};

struct ComponentHealth
{
    HealthState state{HealthState::unknown};
    std::string summary;
    std::unordered_map<std::string, std::string> details;
};

class PDR_RUNTIME_CORE_API IHostedComponent
{
  public:
    virtual ~IHostedComponent() = default;
    virtual ComponentDescriptor descriptor() const = 0;
    virtual Outcome<void> configure(const HostEnvironment& environment) = 0;
    virtual Outcome<void> start() = 0;
    // Must be idempotent and safe after a partially completed configure/start.
    virtual void stop() noexcept = 0;
    virtual ComponentHealth health() const = 0;
};

enum class HostState
{
    empty,
    configuring,
    configured,
    starting,
    running,
    stopping,
    stopped,
    failed
};

struct HostedComponentSnapshot
{
    ComponentDescriptor descriptor;
    ComponentHealth health;
};

struct HostSnapshot
{
    HostState state{HostState::empty};
    HealthState health{HealthState::unknown};
    std::vector<std::string> lifecycleOrder;
    std::vector<HostedComponentSnapshot> components;
    RuntimeError lastError;
};

class PDR_RUNTIME_CORE_API IRuntimeHost
{
  public:
    virtual ~IRuntimeHost() = default;
    virtual Outcome<void> registerComponent(std::shared_ptr<IHostedComponent> component) = 0;
    virtual Outcome<void> configure(HostEnvironment environment) = 0;
    virtual Outcome<void> start() = 0;
    virtual void stop() noexcept = 0;
    virtual HostSnapshot snapshot() const = 0;
};

} // namespace PocoDDS::RuntimeCore
