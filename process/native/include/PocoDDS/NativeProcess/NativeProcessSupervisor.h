#pragma once

#include "PocoDDS/NativeProcess/Export.h"
#include "PocoDDS/RuntimeCore/Process.h"

#include <chrono>
#include <memory>
#include <string>

namespace PocoDDS::NativeProcess
{

struct NativeProcessSupervisorOptions
{
    std::string processRoot;
    bool allowOutsideProcessRoot{false};
    std::chrono::milliseconds monitorInterval{50};
};

class PDR_NATIVE_PROCESS_API NativeProcessSupervisor final
    : public PocoDDS::RuntimeCore::IProcessSupervisor
{
  public:
    explicit NativeProcessSupervisor(NativeProcessSupervisorOptions options = {});
    ~NativeProcessSupervisor() override;

    NativeProcessSupervisor(const NativeProcessSupervisor&) = delete;
    NativeProcessSupervisor& operator=(const NativeProcessSupervisor&) = delete;

    PocoDDS::RuntimeCore::Outcome<void>
    registerProcess(PocoDDS::RuntimeCore::ProcessSpec spec) override;
    PocoDDS::RuntimeCore::Outcome<void> start(const std::string& id) override;
    PocoDDS::RuntimeCore::Outcome<void> startAll() override;
    PocoDDS::RuntimeCore::Outcome<void> stop(const std::string& id) override;
    void stopAll() noexcept override;
    PocoDDS::RuntimeCore::Outcome<void> restart(const std::string& id) override;
    std::vector<PocoDDS::RuntimeCore::ProcessSnapshot> snapshots() const override;

  private:
    struct State;
    std::unique_ptr<State> _state;
};

} // namespace PocoDDS::NativeProcess
