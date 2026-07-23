#pragma once

#include "PocoDDS/Protocols/BtLE/GattClient.h"

#include <functional>
#include <memory>
#include <string>
#include <utility>
#include <vector>

namespace PocoDDS::Protocols::BtLE
{

struct PeripheralInfo
{
    std::string address;
    std::string name;
    int rssi{0};
    std::vector<std::string> serviceUuids;
};

class PeripheralBrowser
{
public:
    using PeripheralHandler = std::function<void(const PeripheralInfo&)>;
    using CompleteHandler = std::function<void()>;

    virtual ~PeripheralBrowser() = default;
    virtual void browse(int seconds) = 0;
    virtual std::shared_ptr<GattClient> createClient(const std::string& address) = 0;

    void setPeripheralHandler(PeripheralHandler handler) { _peripheralHandler = std::move(handler); }
    void setCompleteHandler(CompleteHandler handler) { _completeHandler = std::move(handler); }

protected:
    void reportPeripheral(const PeripheralInfo& info) const
    {
        if (_peripheralHandler) _peripheralHandler(info);
    }
    void reportComplete() const
    {
        if (_completeHandler) _completeHandler();
    }

private:
    PeripheralHandler _peripheralHandler;
    CompleteHandler _completeHandler;
};

} // namespace PocoDDS::Protocols::BtLE
