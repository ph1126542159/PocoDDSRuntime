#pragma once

#include "PocoDDS/Devices/Device.h"
#include "PocoDDS/Devices/DeviceTypes.h"

#include <functional>

namespace PocoDDS::Devices
{
class GNSSSensor : public Device
{
public:
    using PositionHandler = std::function<void(const GeoPosition&)>;

    virtual GeoPosition position() const = 0;
    virtual bool hasFix() const = 0;
    virtual void setPositionHandler(PositionHandler handler) = 0;
};
} // namespace PocoDDS::Devices
