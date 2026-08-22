#include "PocoDDS/RuntimeCore/StaticHost.h"

#include <iostream>
#include <memory>
#include <string>
#include <utility>
#include <vector>

namespace
{
using namespace PocoDDS::RuntimeCore;

class TestComponent final : public IHostedComponent
{
  public:
    TestComponent(ComponentDescriptor descriptor, std::vector<std::string>& events,
                  bool failStart = false, HealthState health = HealthState::healthy)
        : _descriptor(std::move(descriptor)), _events(events), _failStart(failStart),
          _health(health)
    {
    }

    ComponentDescriptor descriptor() const override { return _descriptor; }

    Outcome<void> configure(const HostEnvironment& environment) override
    {
        _events.push_back("configure:" + _descriptor.id + ":" + environment.profile);
        return Outcome<void>::success();
    }

    Outcome<void> start() override
    {
        _events.push_back("start:" + _descriptor.id);
        if (_failStart)
            return Outcome<void>::failure(
                {RuntimeErrorCode::unavailable, "injected start failure", true});
        return Outcome<void>::success();
    }

    void stop() noexcept override { _events.push_back("stop:" + _descriptor.id); }

    ComponentHealth health() const override { return {_health, _descriptor.id, {}}; }

  private:
    ComponentDescriptor _descriptor;
    std::vector<std::string>& _events;
    bool _failStart;
    HealthState _health;
};

std::shared_ptr<TestComponent> component(std::string id, std::vector<std::string>& events,
                                         std::vector<ComponentDependency> dependencies = {},
                                         bool failStart = false, bool required = true,
                                         HealthState health = HealthState::healthy)
{
    return std::make_shared<TestComponent>(
        ComponentDescriptor{std::move(id), "1.0.0", std::move(dependencies), required}, events,
        failStart, health);
}
} // namespace

int main()
{
    using namespace PocoDDS::RuntimeCore;

    std::vector<std::string> events;
    StaticHost host;
    if (!host.registerComponent(component("feature", events, {{"core", true}})) ||
        !host.registerComponent(component("core", events)) ||
        !host.registerComponent(
            component("optional", events, {}, false, false, HealthState::unhealthy)))
        return 1;
    if (!host.configure({"desktop-lite", "static", {"inproc"}, {}}))
        return 2;
    if (!host.start())
        return 3;
    const auto running = host.snapshot();
    if (running.state != HostState::running || running.health != HealthState::degraded ||
        running.lifecycleOrder != std::vector<std::string>({"core", "optional", "feature"}))
        return 4;
    host.stop();
    if (events !=
        std::vector<std::string>({"configure:core:desktop-lite", "configure:optional:desktop-lite",
                                  "configure:feature:desktop-lite", "start:core", "start:optional",
                                  "start:feature", "stop:feature", "stop:optional", "stop:core"}))
        return 5;

    events.clear();
    StaticHost failingHost;
    if (!failingHost.registerComponent(component("core", events)) ||
        !failingHost.registerComponent(component("feature", events, {{"core", true}}, true)) ||
        !failingHost.configure({"server", "osp", {}, {}}))
        return 6;
    const auto failedStart = failingHost.start();
    if (failedStart || failedStart.error().code != RuntimeErrorCode::unavailable ||
        failingHost.snapshot().state != HostState::failed)
        return 7;
    if (events.size() < 2 || events[events.size() - 2] != "stop:feature" ||
        events.back() != "stop:core")
        return 8;

    StaticHost invalidHost;
    if (!invalidHost.registerComponent(component("orphan", events, {{"missing", true}})))
        return 9;
    const auto invalidConfiguration = invalidHost.configure({});
    if (invalidConfiguration ||
        invalidConfiguration.error().code != RuntimeErrorCode::dependencyFailure)
        return 10;

    std::cout
        << "PDR_RUNTIME_CORE_HOST_PASS ordering=topological rollback=verified health=degraded\n";
    return 0;
}
