#pragma once

#include "PocoDDS/Devices/Device.h"

#include "Poco/OSP/Service.h"

#include <string>
#include <typeinfo>

namespace PocoDDS::Devices
{
// OSP integration surface for runtime discovery. Holding a ServiceRef keeps
// this object and its Device alive while a consumer reads a snapshot.
class DeviceService final : public Poco::OSP::Service
{
public:
    explicit DeviceService(Device& device) : _device(device) {}

    Device& device() noexcept { return _device; }
    const Device& device() const noexcept { return _device; }

    const std::type_info& type() const override { return typeid(DeviceService); }
    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) == typeid(DeviceService).name() ||
               Poco::OSP::Service::isA(other);
    }

private:
    Device& _device;
};
}
