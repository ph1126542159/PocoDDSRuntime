#pragma once

#include "PocoDDS/Workflow/WorkflowDefinitionService.h"
#include "PocoDDS/Workflow/WorkflowStore.h"

#include <Poco/AutoPtr.h>

#include <memory>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

namespace PocoDDS::Workflow
{
class WorkflowEngine
{
public:
    explicit WorkflowEngine(std::unique_ptr<WorkflowStore> store);

    void initialize();
    void attach(Poco::AutoPtr<WorkflowDefinitionService> definition);
    void detach(const std::string& type);

    Instance start(const std::string& type,
                   const std::string& businessKey,
                   const std::string& input);
    Instance signal(const std::string& id,
                    const std::string& event,
                    const std::string& payload);
    Instance resume(const std::string& id);
    Instance cancel(const std::string& id);
    std::size_t runDue();

    Instance get(const std::string& id) const;
    std::vector<Instance> list() const;
    std::vector<std::string> definitionTypes() const;

private:
    struct AttachedDefinition
    {
        DefinitionDescriptor descriptor;
        Poco::AutoPtr<WorkflowDefinitionService> service;
    };

    Instance run(Instance instance, AttachedDefinition& definition);
    Instance failAndCompensate(Instance instance,
                               AttachedDefinition& definition,
                               std::string code,
                               std::string message);
    void persist(Instance& instance);
    AttachedDefinition& requireDefinition(const std::string& type);
    Instance requireInstance(const std::string& id) const;

    std::unique_ptr<WorkflowStore> _store;
    mutable std::mutex _mutex;
    std::unordered_map<std::string, AttachedDefinition> _definitions;
};
} // namespace PocoDDS::Workflow
