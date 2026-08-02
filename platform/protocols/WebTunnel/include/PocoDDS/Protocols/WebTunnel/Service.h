#pragma once

#include <atomic>
#include <functional>
#include <mutex>
#include <string>
#include <utility>
#include <vector>

namespace PocoDDS::Protocols::WebTunnel
{

struct Property
{
    std::string name;
    std::string value;
};

class Service
{
public:
    using ConnectionHandler = std::function<void(bool connected)>;

    virtual ~Service() = default;
    [[nodiscard]] virtual bool isConnected() const = 0;
    virtual void updateProperties(const std::vector<Property>& properties) = 0;

    void setConnectionHandler(ConnectionHandler handler)
    {
        std::lock_guard lock(_handlerMutex);
        _connectionHandler = std::move(handler);
    }

    [[nodiscard]] std::size_t connectionHandlerFailures() const noexcept
    {
        return _connectionHandlerFailures.load(std::memory_order_relaxed);
    }

protected:
    void reportConnection(bool connected) const noexcept
    {
        ConnectionHandler handler;
        {
            std::lock_guard lock(_handlerMutex);
            handler = _connectionHandler;
        }
        if (!handler) return;
        try { handler(connected); }
        catch (...) { _connectionHandlerFailures.fetch_add(1, std::memory_order_relaxed); }
    }

private:
    mutable std::mutex _handlerMutex;
    ConnectionHandler _connectionHandler;
    mutable std::atomic<std::size_t> _connectionHandlerFailures{0};
};

} // namespace PocoDDS::Protocols::WebTunnel
