#pragma once

#include "PocoDDS/Devices/Device.h"
#include "PocoDDS/Devices/DeviceTypes.h"

#include <functional>

namespace PocoDDS::Devices
{
class Camera : public Device
{
public:
    using ImageHandler = std::function<void(const Image&)>;

    virtual Image capture() = 0;
    virtual void setImageHandler(ImageHandler handler) = 0;
};

class BarcodeReader : public Device
{
public:
    using ReadHandler = std::function<void(const BarcodeRead&)>;

    virtual void setReadHandler(ReadHandler handler) = 0;
};

class RotaryEncoder : public Device
{
public:
    using PositionHandler = std::function<void(std::int64_t)>;

    virtual std::int64_t position() const = 0;
    virtual void reset() = 0;
    virtual void setPositionHandler(PositionHandler handler) = 0;
};
} // namespace PocoDDS::Devices
