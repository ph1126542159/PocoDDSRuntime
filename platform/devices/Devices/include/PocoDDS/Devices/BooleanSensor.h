#pragma once

#include "PocoDDS/Devices/Device.h"

#include <functional>

namespace PocoDDS::Devices
{
class BooleanSensor : public Device
{
public:
    using StateHandler = std::function<void(bool)>;

    virtual bool value() const = 0;
    virtual void setStateHandler(StateHandler handler) = 0;
};
} // namespace PocoDDS::Devices
