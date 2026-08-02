#pragma once

#include <cstdint>
#include <string>

namespace PocoDDS::Reliability
{
struct AlertNotification
{
    std::string alertId;
    std::string event;
    std::string domain;
    std::string instance;
    std::string code;
    std::string status;
    std::string severity;
    std::string traceId;
    std::string message;
    bool retryable{false};
    bool silenced{false};
    std::int64_t occurredAtMicroseconds{0};
};

// Extension SPI. Implementations should also derive from Poco::OSP::Service and
// register with the property pdr.alertSink=true. Delivery runs on a bounded
// worker queue, never on a device/protocol monitoring thread.
class AlertSink
{
public:
    virtual ~AlertSink() = default;
    virtual void deliver(const AlertNotification& notification) = 0;
};
}
