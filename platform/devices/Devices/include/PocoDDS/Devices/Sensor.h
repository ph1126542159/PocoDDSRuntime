#pragma once

#include "PocoDDS/Devices/Device.h"

#include <functional>
#include <string>

namespace PocoDDS::Devices
{
class Sensor : public Device
{
public:
    using ValueHandler = std::function<void(double)>;

    virtual double value() const = 0;
    virtual std::string physicalQuantity() const = 0;
    virtual std::string physicalUnit() const = 0;
    virtual void setValueHandler(ValueHandler handler) = 0;
};
} // namespace PocoDDS::Devices
