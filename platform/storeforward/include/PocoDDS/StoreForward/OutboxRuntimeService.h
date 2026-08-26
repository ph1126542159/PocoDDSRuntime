#pragma once

#include "PocoDDS/StoreForward/StoreForward.h"

#include <Poco/OSP/Service.h>

#include <string>
#include <typeinfo>
#include <vector>

namespace PocoDDS::StoreForward
{
class OutboxRuntimeService : public Poco::OSP::Service
{
public:
    virtual Message enqueue(const EnqueueRequest& request) = 0;
    virtual Message cancel(const std::string& id) = 0;
    virtual Message redrive(const std::string& id) = 0;
    virtual Message message(const std::string& id) const = 0;
    virtual std::vector<Message> messages() const = 0;
    virtual Snapshot snapshot() const = 0;
    virtual std::vector<std::string> providerTypes() const = 0;

    const std::type_info& type() const override
    {
        return typeid(OutboxRuntimeService);
    }

    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) == typeid(OutboxRuntimeService).name() ||
               Poco::OSP::Service::isA(other);
    }

protected:
    ~OutboxRuntimeService() override = default;
};
} // namespace PocoDDS::StoreForward
