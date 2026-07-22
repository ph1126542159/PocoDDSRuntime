#pragma once

#include <functional>
#include <memory>
#include <string>
#include <vector>

namespace PocoDDS::Transport
{
struct Message
{
    std::string topic;
    std::string type;
    std::vector<std::byte> payload;
    std::string traceParent;
};

class Subscription
{
  public:
    virtual ~Subscription() = default;
};

class ITransport
{
  public:
    using Handler = std::function<void(const Message&)>;
    virtual ~ITransport() = default;
    virtual void publish(const Message& message) = 0;
    virtual std::unique_ptr<Subscription> subscribe(const std::string& topic, Handler handler) = 0;
};
} // namespace PocoDDS::Transport
