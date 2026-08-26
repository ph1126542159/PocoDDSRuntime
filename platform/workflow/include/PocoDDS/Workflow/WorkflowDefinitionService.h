#pragma once

#include "PocoDDS/Workflow/Workflow.h"

#include <Poco/OSP/Service.h>

#include <string>
#include <typeinfo>

namespace PocoDDS::Workflow
{
class WorkflowDefinitionService : public Poco::OSP::Service
{
public:
    static constexpr const char* PROPERTY_KIND = "pdr.workflow.provider.kind";
    static constexpr const char* PROPERTY_TYPE = "pdr.workflow.provider.type";
    static constexpr const char* PROVIDER_KIND = "definition";

    virtual DefinitionDescriptor descriptor() const = 0;
    virtual StepResult execute(const std::string& step,
                               const StepContext& context) = 0;
    virtual void compensate(const std::string& step,
                            const StepContext& context) = 0;

    const std::type_info& type() const override
    {
        return typeid(WorkflowDefinitionService);
    }

    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) == typeid(WorkflowDefinitionService).name() ||
               Poco::OSP::Service::isA(other);
    }

protected:
    ~WorkflowDefinitionService() override = default;
};
} // namespace PocoDDS::Workflow
