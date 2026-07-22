#include "PocoDDS/Transport/InMemoryTransport.h"

namespace PocoDDS::Transport
{
class InMemoryTransport::LocalSubscription final : public Subscription
{
  public:
    LocalSubscription(InMemoryTransport& owner, std::string topic, std::size_t id)
        : _owner(owner), _topic(std::move(topic)), _id(id)
    {
    }
    ~LocalSubscription() override { _owner.unsubscribe(_topic, _id); }

  private:
    InMemoryTransport& _owner;
    std::string _topic;
    std::size_t _id;
};

void InMemoryTransport::publish(const Message& message)
{
    std::unordered_map<std::size_t, Handler> handlers;
    {
        std::lock_guard lock(_mutex);
        const auto it = _handlers.find(message.topic);
        if (it != _handlers.end())
            handlers = it->second;
    }
    for (const auto& [id, handler] : handlers)
    {
        static_cast<void>(id);
        handler(message);
    }
}

std::unique_ptr<Subscription> InMemoryTransport::subscribe(const std::string& topic,
                                                           Handler handler)
{
    std::lock_guard lock(_mutex);
    const auto id = _nextId++;
    _handlers[topic][id] = std::move(handler);
    return std::make_unique<LocalSubscription>(*this, topic, id);
}

void InMemoryTransport::unsubscribe(const std::string& topic, std::size_t id)
{
    std::lock_guard lock(_mutex);
    const auto it = _handlers.find(topic);
    if (it != _handlers.end())
        it->second.erase(id);
}
} // namespace PocoDDS::Transport
