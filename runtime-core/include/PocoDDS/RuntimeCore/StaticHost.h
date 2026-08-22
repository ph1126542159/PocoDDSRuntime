#pragma once

#include "PocoDDS/RuntimeCore/Host.h"

#include <memory>

namespace PocoDDS::RuntimeCore
{

class PDR_RUNTIME_CORE_API StaticHost final : public IRuntimeHost
{
  public:
    StaticHost();
    ~StaticHost() override;

    StaticHost(const StaticHost&) = delete;
    StaticHost& operator=(const StaticHost&) = delete;

    Outcome<void> registerComponent(std::shared_ptr<IHostedComponent> component) override;
    Outcome<void> configure(HostEnvironment environment) override;
    Outcome<void> start() override;
    void stop() noexcept override;
    HostSnapshot snapshot() const override;

  private:
    struct State;
    std::unique_ptr<State> _state;
};

} // namespace PocoDDS::RuntimeCore
