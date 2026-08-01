#pragma once

#include "PocoDDS/Protocols/WebTunnel/Service.h"
#include "PocoDDS/Protocols/ProtocolMetrics.h"

#include <mutex>
#include <stdexcept>

namespace PocoDDS::Protocols::WebTunnel
{
class SimulatedService final : public Service
{
public:
    void connect()
    {
        ProtocolMetricTimer timer("webtunnel", "connect");
        { std::lock_guard lock(_mutex); _connected = true; }
        reportConnection(true); timer.success();
    }
    void disconnect()
    {
        ProtocolMetricTimer timer("webtunnel", "disconnect");
        { std::lock_guard lock(_mutex); _connected = false; }
        reportConnection(false); timer.success();
    }
    [[nodiscard]] bool isConnected() const override
    {
        std::lock_guard lock(_mutex); return _connected;
    }
    void updateProperties(const std::vector<Property>& properties) override
    {
        ProtocolMetricTimer timer("webtunnel", "update_properties", properties.size());
        { std::lock_guard lock(_mutex); _properties = properties; }
        timer.success();
    }
    std::vector<std::uint8_t> exchange(const std::vector<std::uint8_t>& payload)
    {
        ProtocolMetricTimer timer("webtunnel", "exchange", payload.size());
        {
            std::lock_guard lock(_mutex);
            if (!_connected) { timer.failure(); throw std::logic_error("tunnel is disconnected"); }
            _bytesSent += payload.size(); _bytesReceived += payload.size();
        }
        timer.success();
        return payload;
    }
    [[nodiscard]] std::size_t bytesSent() const
    {
        std::lock_guard lock(_mutex); return _bytesSent;
    }
    [[nodiscard]] std::size_t bytesReceived() const
    {
        std::lock_guard lock(_mutex); return _bytesReceived;
    }

private:
    mutable std::mutex _mutex;
    bool _connected{false};
    std::vector<Property> _properties;
    std::size_t _bytesSent{0};
    std::size_t _bytesReceived{0};
};
}
