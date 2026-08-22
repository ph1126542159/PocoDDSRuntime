#pragma once

#include "PocoDDS/RuntimeCore/Contract.h"
#include "PocoDDS/RuntimeCore/Export.h"

#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

namespace PocoDDS::RuntimeCore
{
using Payload = std::vector<std::uint8_t>;

enum class Delivery
{
    bestEffort,
    reliable
};

struct TopicSpec
{
    std::string name;
    std::string messageType;
    std::string schemaVersion{"1"};
    Delivery delivery{Delivery::bestEffort};
    bool durable{false};
};

struct Message
{
    std::string type;
    std::string schemaVersion{"1"};
    std::shared_ptr<const Payload> payload;
    std::unordered_map<std::string, std::string> headers;
    MessageContext context;
};

struct TransportCapabilities
{
    bool inProcess{false};
    bool interProcess{false};
    bool distributed{false};
    bool requestReply{false};
    bool durable{false};
    bool zeroCopyPayload{false};
};

struct PublishResult
{
    std::size_t accepted{0};
    std::size_t delivered{0};
    std::size_t failed{0};
    std::size_t dropped{0};
};

class PDR_RUNTIME_CORE_API Subscription
{
  public:
    Subscription() = default;
    explicit Subscription(std::function<void()> cancel);
    ~Subscription();

    Subscription(const Subscription&) = delete;
    Subscription& operator=(const Subscription&) = delete;
    Subscription(Subscription&& other) noexcept;
    Subscription& operator=(Subscription&& other) noexcept;

    void reset() noexcept;
    explicit operator bool() const noexcept;

  private:
    std::function<void()> _cancel;
};

class PDR_RUNTIME_CORE_API IMessageTransport
{
  public:
    using Handler = std::function<void(const TopicSpec&, const Message&)>;

    virtual ~IMessageTransport() = default;
    virtual std::string id() const = 0;
    virtual TransportCapabilities capabilities() const noexcept = 0;
    virtual Subscription subscribe(const TopicSpec& topic, Handler handler) = 0;
    virtual PublishResult publish(const TopicSpec& topic, const Message& message) = 0;
};

} // namespace PocoDDS::RuntimeCore
