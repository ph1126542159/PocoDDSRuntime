#pragma once

#include "PocoDDS/Transport/ITransport.h"

#include <mutex>
#include <unordered_map>

namespace PocoDDS::Transport
{
class InMemoryTransport final : public ITransport
{
  public:
    void publish(const Message& message) override;
    std::unique_ptr<Subscription> subscribe(const std::string& topic, Handler handler) override;

  private:
    class LocalSubscription;
    void unsubscribe(const std::string& topic, std::size_t id);
    std::mutex _mutex;
    std::size_t _nextId{1};
    std::unordered_map<std::string, std::unordered_map<std::size_t, Handler>> _handlers;
};
} // namespace PocoDDS::Transport
