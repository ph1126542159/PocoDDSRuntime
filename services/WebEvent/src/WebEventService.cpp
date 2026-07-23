#include "PocoDDS/Services/WebEventService.h"

namespace PocoDDS::Services
{
class WebEventServiceImpl final : public WebEventService
{
public:
    void notify(const std::string& subject, const std::string& data) override
    {
        WebEvent event{subject, data};
        eventPublished(this, event);
    }
};

Poco::OSP::Service::Ptr createWebEventService()
{
    return new WebEventServiceImpl;
}
} // namespace PocoDDS::Services
