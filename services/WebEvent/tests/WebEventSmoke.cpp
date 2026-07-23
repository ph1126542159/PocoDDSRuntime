#include "PocoDDS/Services/WebEventService.h"

#include <Poco/Delegate.h>

#include <iostream>

namespace PocoDDS::Services
{
Poco::OSP::Service::Ptr createWebEventService();
}

class Receiver
{
public:
    void receive(const void*, const PocoDDS::Services::WebEvent& event)
    {
        received = event.subject == "test" && event.data == "{}";
    }
    bool received{false};
};

int main()
{
    auto service = PocoDDS::Services::createWebEventService()
                       .cast<PocoDDS::Services::WebEventService>();
    Receiver receiver;
    service->eventPublished += Poco::delegate(&receiver, &Receiver::receive);
    service->notify("test", "{}");
    service->eventPublished -= Poco::delegate(&receiver, &Receiver::receive);
    if (!receiver.received)
    {
        std::cerr << "WebEvent smoke test failed\n";
        return 1;
    }
    return 0;
}
