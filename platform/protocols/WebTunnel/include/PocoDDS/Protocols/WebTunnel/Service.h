#pragma once

#include <functional>
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
        _connectionHandler = std::move(handler);
    }

protected:
    void reportConnection(bool connected) const
    {
        if (_connectionHandler)
            _connectionHandler(connected);
    }

private:
    ConnectionHandler _connectionHandler;
};

} // namespace PocoDDS::Protocols::WebTunnel
