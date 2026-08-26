#pragma once

#include "PocoDDS/Workflow/WorkflowStore.h"

#include <memory>
#include <string>

namespace PocoDDS::Workflow
{
class SqliteWorkflowStore final : public WorkflowStore
{
public:
    explicit SqliteWorkflowStore(std::string path);
    ~SqliteWorkflowStore() override;

    SqliteWorkflowStore(const SqliteWorkflowStore&) = delete;
    SqliteWorkflowStore& operator=(const SqliteWorkflowStore&) = delete;

    void initialize() override;
    void save(const Instance& instance) override;
    std::optional<Instance> find(const std::string& id) const override;
    std::optional<Instance> findByBusinessKey(
        const std::string& type, const std::string& businessKey) const override;
    std::vector<Instance> list() const override;
    std::vector<Instance> due(Poco::Int64 nowMicroseconds) const override;
    std::size_t markActiveInterrupted(Poco::Int64 nowMicroseconds) override;

private:
    class Impl;
    std::unique_ptr<Impl> _impl;
};
} // namespace PocoDDS::Workflow
