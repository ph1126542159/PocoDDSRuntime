#pragma once

#include "PocoDDS/Lifecycle/DrainGate.h"

#include <Poco/AutoPtr.h>
#include <Poco/OSP/Service.h>

#include <chrono>
#include <string>
#include <typeinfo>

namespace PocoDDS::Lifecycle
{
struct DrainResult
{
    bool drained{false};
    std::string code;
    std::string detail;
    DrainSnapshot snapshot;
};

class DrainParticipantService : public Poco::OSP::Service
{
public:
    using Ptr = Poco::AutoPtr<DrainParticipantService>;
    static constexpr const char* SERVICE_PREFIX =
        "pdr.lifecycle.drainParticipant.";
    static constexpr const char* PROPERTY_KIND = "pdr.lifecycle.participant";
    static constexpr const char* PROPERTY_OWNER = "pdr.bundle";

    virtual std::string owner() const = 0;
    virtual DrainResult quiesce(std::chrono::milliseconds timeout) = 0;
    virtual void resume() noexcept = 0;
    virtual DrainSnapshot drainSnapshot() const noexcept = 0;

    const std::type_info& type() const override
    {
        return typeid(DrainParticipantService);
    }

    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) == typeid(DrainParticipantService).name() ||
               Poco::OSP::Service::isA(other);
    }

protected:
    ~DrainParticipantService() override = default;
};
} // namespace PocoDDS::Lifecycle
