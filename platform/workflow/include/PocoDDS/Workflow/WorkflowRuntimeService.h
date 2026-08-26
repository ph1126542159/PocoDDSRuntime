#pragma once

#include "PocoDDS/Workflow/Workflow.h"

#include <Poco/OSP/Service.h>

#include <string>
#include <typeinfo>
#include <vector>

namespace PocoDDS::Workflow
{
class WorkflowRuntimeService : public Poco::OSP::Service
{
public:
    virtual Instance startWorkflow(const std::string& type,
                                   const std::string& businessKey,
                                   const std::string& input) = 0;
    virtual Instance signalWorkflow(const std::string& id,
                                    const std::string& event,
                                    const std::string& payload) = 0;
    virtual Instance resumeWorkflow(const std::string& id) = 0;
    virtual Instance cancelWorkflow(const std::string& id) = 0;
    virtual Instance workflow(const std::string& id) const = 0;
    virtual std::vector<Instance> workflows() const = 0;
    virtual std::vector<std::string> definitionTypes() const = 0;

    const std::type_info& type() const override
    {
        return typeid(WorkflowRuntimeService);
    }

    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) == typeid(WorkflowRuntimeService).name() ||
               Poco::OSP::Service::isA(other);
    }

protected:
    ~WorkflowRuntimeService() override = default;
};
} // namespace PocoDDS::Workflow
