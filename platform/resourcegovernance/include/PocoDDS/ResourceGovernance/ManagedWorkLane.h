#pragma once

#include "PocoDDS/ResourceGovernance/Export.h"
#include "PocoDDS/ResourceGovernance/ResourceGovernorService.h"

#include <cstddef>
#include <memory>
#include <string>

namespace PocoDDS::ResourceGovernance
{
/// Bundle-facing adapter that binds all submitted work to one governance owner.
/// closeAndWait() is the Bundle unload barrier: after it returns, no submitted
/// run or completion callback can still execute from the calling Bundle.
class PDR_RESOURCE_GOVERNANCE_OSP_API ManagedWorkLane
{
public:
    ManagedWorkLane(ResourceGovernorService::Ptr service, std::string owner);
    ~ManagedWorkLane();

    ManagedWorkLane(const ManagedWorkLane&) = delete;
    ManagedWorkLane& operator=(const ManagedWorkLane&) = delete;

    Admission submit(WorkItem item);
    void closeAndWait() noexcept;

    [[nodiscard]] const std::string& owner() const noexcept;
    [[nodiscard]] bool accepting() const noexcept;
    [[nodiscard]] std::size_t outstanding() const noexcept;

private:
    struct State;
    static void finish(const std::shared_ptr<State>& state) noexcept;

    ResourceGovernorService::Ptr _service;
    std::string _owner;
    std::shared_ptr<State> _state;
};
} // namespace PocoDDS::ResourceGovernance
