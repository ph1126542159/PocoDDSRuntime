#pragma once

#include <Poco/BasicEvent.h>
#include <Poco/OSP/Service.h>

#include <string>
#include <typeinfo>

namespace PocoDDS::Services
{
struct WebEvent
{
    std::string subject;
    std::string data;
};

class WebEventService : public Poco::OSP::Service
{
public:
    Poco::BasicEvent<const WebEvent> eventPublished;

    virtual void notify(const std::string& subject, const std::string& data) = 0;

    const std::type_info& type() const override { return typeid(WebEventService); }
    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) == typeid(WebEventService).name() ||
               Poco::OSP::Service::isA(other);
    }
};
} // namespace PocoDDS::Services
