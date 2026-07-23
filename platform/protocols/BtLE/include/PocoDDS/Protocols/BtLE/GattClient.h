#pragma once

#include <cstdint>
#include <functional>
#include <string>
#include <utility>
#include <vector>

namespace PocoDDS::Protocols::BtLE
{

struct Service
{
    std::string uuid;
    std::uint16_t firstHandle{0};
    std::uint16_t lastHandle{0};
};

struct Characteristic
{
    enum Property : std::uint16_t
    {
        Broadcast = 0x01,
        Read = 0x02,
        WriteWithoutResponse = 0x04,
        Write = 0x08,
        Notify = 0x10,
        Indicate = 0x20,
        SignedWrite = 0x40,
        Extended = 0x80
    };

    std::string uuid;
    std::uint16_t handle{0};
    std::uint16_t properties{0};
    std::uint16_t valueHandle{0};
};

struct Descriptor
{
    std::uint16_t handle{0};
    std::string uuid;
};

struct ValueEvent
{
    std::uint16_t handle{0};
    std::vector<std::uint8_t> data;
};

class GattClient
{
public:
    enum class ConnectMode { Wait, NoWait };
    enum class State { Disconnected, Connecting, Connected, Disconnecting };
    enum class SecurityLevel { Low, Medium, High };

    using StateHandler = std::function<void(State)>;
    using ValueHandler = std::function<void(const ValueEvent&)>;
    using ErrorHandler = std::function<void(const std::string&)>;

    virtual ~GattClient() = default;
    virtual void connect(const std::string& address, ConnectMode mode = ConnectMode::Wait) = 0;
    virtual void disconnect() = 0;
    [[nodiscard]] virtual State state() const = 0;
    [[nodiscard]] virtual std::string address() const = 0;
    virtual std::vector<Service> services() = 0;
    virtual std::vector<Characteristic> characteristics(const std::string& serviceUuid) = 0;
    virtual std::vector<Descriptor> descriptors(const std::string& serviceUuid) = 0;
    virtual std::vector<std::uint8_t> read(std::uint16_t handle) = 0;
    virtual void write(
        std::uint16_t handle,
        const std::vector<std::uint8_t>& value,
        bool withResponse = true) = 0;
    virtual void setSecurityLevel(SecurityLevel level) = 0;
    [[nodiscard]] virtual SecurityLevel securityLevel() const = 0;
    virtual void setMtu(std::uint16_t mtu) = 0;
    [[nodiscard]] virtual std::uint16_t mtu() const = 0;
    virtual void setTimeout(long milliseconds) = 0;
    [[nodiscard]] virtual long timeout() const = 0;

    void setStateHandler(StateHandler handler) { _stateHandler = std::move(handler); }
    void setNotificationHandler(ValueHandler handler) { _notificationHandler = std::move(handler); }
    void setIndicationHandler(ValueHandler handler) { _indicationHandler = std::move(handler); }
    void setErrorHandler(ErrorHandler handler) { _errorHandler = std::move(handler); }

protected:
    void reportState(State state) const { if (_stateHandler) _stateHandler(state); }
    void reportNotification(const ValueEvent& event) const
    {
        if (_notificationHandler) _notificationHandler(event);
    }
    void reportIndication(const ValueEvent& event) const
    {
        if (_indicationHandler) _indicationHandler(event);
    }
    void reportError(const std::string& message) const
    {
        if (_errorHandler) _errorHandler(message);
    }

private:
    StateHandler _stateHandler;
    ValueHandler _notificationHandler;
    ValueHandler _indicationHandler;
    ErrorHandler _errorHandler;
};

} // namespace PocoDDS::Protocols::BtLE
