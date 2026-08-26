#pragma once

#include "PocoDDS/Workflow/Workflow.h"

#include <optional>
#include <string>
#include <vector>

namespace PocoDDS::Workflow
{
class WorkflowStore
{
public:
    virtual ~WorkflowStore() = default;
    virtual void initialize() = 0;
    virtual void save(const Instance& instance) = 0;
    virtual std::optional<Instance> find(const std::string& id) const = 0;
    virtual std::optional<Instance> findByBusinessKey(
        const std::string& type, const std::string& businessKey) const = 0;
    virtual std::vector<Instance> list() const = 0;
    virtual std::vector<Instance> due(Poco::Int64 nowMicroseconds) const = 0;
    virtual std::size_t markActiveInterrupted(Poco::Int64 nowMicroseconds) = 0;
};
} // namespace PocoDDS::Workflow
