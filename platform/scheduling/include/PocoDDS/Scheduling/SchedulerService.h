#pragma once

#include "PocoDDS/Scheduling/Scheduler.h"

#include <Poco/AutoPtr.h>
#include <Poco/OSP/Service.h>

#include <string>
#include <typeinfo>
#include <vector>

namespace PocoDDS::Scheduling
{
class SchedulerService : public Poco::OSP::Service
{
public:
    using Ptr = Poco::AutoPtr<SchedulerService>;
    static constexpr const char* SERVICE_NAME = "pdr.service.schedulerRuntime";

    virtual Registration schedule(TaskSpec spec, TaskCallback run,
                                  CompletionCallback complete = {}) = 0;
    virtual Reconfiguration reconfigure(TaskSpec spec) = 0;
    virtual bool cancelAndWait(const std::string& taskId) noexcept = 0;
    virtual std::optional<TaskSnapshot> snapshot(const std::string& taskId) const = 0;
    virtual std::vector<TaskSnapshot> snapshots() const = 0;

    const std::type_info& type() const override { return typeid(SchedulerService); }
    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) == typeid(SchedulerService).name() ||
               Poco::OSP::Service::isA(other);
    }

protected:
    ~SchedulerService() override = default;
};
} // namespace PocoDDS::Scheduling
