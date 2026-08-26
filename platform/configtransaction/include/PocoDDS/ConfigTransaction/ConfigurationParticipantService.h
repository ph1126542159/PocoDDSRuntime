#pragma once

#include "PocoDDS/ConfigTransaction/ConfigTransaction.h"

#include <Poco/OSP/Service.h>

#include <string>
#include <typeinfo>

namespace PocoDDS::ConfigTransaction
{
class ConfigurationParticipantService : public Poco::OSP::Service
{
public:
    static constexpr const char* PROPERTY_KIND = "pdr.configuration.participant.kind";
    static constexpr const char* PROPERTY_ID = "pdr.configuration.participant.id";
    static constexpr const char* PARTICIPANT_KIND = "transactional";

    virtual ParticipantDescriptor descriptor() const = 0;
    virtual ParticipantResult preflight(const Context& context) = 0;
    virtual ParticipantResult commit(const Context& context) = 0;
    virtual ParticipantResult rollback(const Context& context) = 0;

    const std::type_info& type() const override
    {
        return typeid(ConfigurationParticipantService);
    }

    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) == typeid(ConfigurationParticipantService).name() ||
               Poco::OSP::Service::isA(other);
    }

protected:
    ~ConfigurationParticipantService() override = default;
};
} // namespace PocoDDS::ConfigTransaction
