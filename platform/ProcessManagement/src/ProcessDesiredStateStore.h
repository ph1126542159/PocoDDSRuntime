#pragma once

#include <cstdint>
#include <functional>
#include <map>
#include <memory>
#include <string>

namespace PocoDDS::ProcessManagement::Detail
{
struct ProcessDesiredStateSnapshot
{
    bool available{false};
    bool recovered{false};
    std::string recoveredFrom;
    std::uint64_t generation{0};
    std::map<std::string, bool> states;
};

struct ProcessDesiredStateIntegrity
{
    bool primaryValid{false};
    bool previousAvailable{false};
    bool previousValid{false};
    std::string primaryError;
    std::string previousError;
};

enum class ProcessDesiredStateCommitStage
{
    stagingFlushed,
    previousCommitted,
    primaryCommitted
};

class ProcessDesiredStateStore final
{
  public:
    using FaultInjector =
        std::function<void(ProcessDesiredStateCommitStage)>;

    explicit ProcessDesiredStateStore(
        std::string path, FaultInjector faultInjector = {});
    ~ProcessDesiredStateStore();

    const std::string& path() const noexcept;
    void acquireLease();
    bool leaseHeld() const noexcept;
    ProcessDesiredStateSnapshot load() const;
    ProcessDesiredStateIntegrity inspect(
        std::uint64_t expectedGeneration,
        const std::map<std::string, bool>& expectedStates) const;
    void save(std::uint64_t generation,
              const std::map<std::string, bool>& states) const;

  private:
    void notifyCommitStage(ProcessDesiredStateCommitStage stage) const;

    class Lease;
    std::string _path;
    FaultInjector _faultInjector;
    std::unique_ptr<Lease> _lease;
};
} // namespace PocoDDS::ProcessManagement::Detail
