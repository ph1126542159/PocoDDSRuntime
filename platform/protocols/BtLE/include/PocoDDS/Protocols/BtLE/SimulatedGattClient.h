#pragma once

#include "PocoDDS/Protocols/BtLE/GattClient.h"
#include "PocoDDS/Protocols/ProtocolMetrics.h"

#include <chrono>
#include <map>
#include <stdexcept>
#include <thread>

namespace PocoDDS::Protocols::BtLE
{
class SimulatedGattClient final : public GattClient
{
public:
    SimulatedGattClient()
    {
        _values.emplace(11, std::vector<std::uint8_t>{0x00, 72});
    }

    void connect(const std::string& address, ConnectMode = ConnectMode::Wait) override
    {
        ProtocolMetricTimer timer("btle", "connect");
        if (address.empty()) { timer.failure(); throw std::invalid_argument("empty BLE address"); }
        _state = State::Connecting; reportState(_state);
        _address = address;
        _state = State::Connected; reportState(_state);
        timer.success();
    }
    void disconnect() override
    {
        ProtocolMetricTimer timer("btle", "disconnect");
        _state = State::Disconnecting; reportState(_state);
        _state = State::Disconnected; reportState(_state);
        timer.success();
    }
    [[nodiscard]] State state() const override { return _state; }
    [[nodiscard]] std::string address() const override { return _address; }
    std::vector<Service> services() override
    {
        requireConnected();
        return {{"0000180d-0000-1000-8000-00805f9b34fb", 1, 20}};
    }
    std::vector<Characteristic> characteristics(const std::string&) override
    {
        requireConnected();
        return {{"00002a37-0000-1000-8000-00805f9b34fb", 10,
                 static_cast<std::uint16_t>(Characteristic::Read | Characteristic::Write |
                                            Characteristic::Notify), 11}};
    }
    std::vector<Descriptor> descriptors(const std::string&) override
    {
        requireConnected(); return {{12, "00002902-0000-1000-8000-00805f9b34fb"}};
    }
    std::vector<std::uint8_t> read(std::uint16_t handle) override
    {
        requireConnected();
        const auto found = _values.find(handle);
        if (found == _values.end()) throw std::out_of_range("unknown GATT handle");
        ProtocolMetricTimer timer("btle", "read", found->second.size()); timer.success();
        return found->second;
    }
    void write(std::uint16_t handle, const std::vector<std::uint8_t>& value, bool = true) override
    {
        requireConnected();
        _values[handle] = value;
        ProtocolMetricTimer timer("btle", "write", value.size()); timer.success();
        reportNotification({handle, value});
    }
    void setSecurityLevel(SecurityLevel value) override { _security = value; }
    [[nodiscard]] SecurityLevel securityLevel() const override { return _security; }
    void setMtu(std::uint16_t value) override { _mtu = value; }
    [[nodiscard]] std::uint16_t mtu() const override { return _mtu; }
    void setTimeout(long value) override { _timeout = value; }
    [[nodiscard]] long timeout() const override { return _timeout; }

private:
    void requireConnected() const
    {
        if (_state != State::Connected) throw std::logic_error("BLE simulator is disconnected");
    }
    State _state{State::Disconnected};
    SecurityLevel _security{SecurityLevel::Low};
    std::string _address;
    std::uint16_t _mtu{23};
    long _timeout{5000};
    std::map<std::uint16_t, std::vector<std::uint8_t>> _values;
};
}
