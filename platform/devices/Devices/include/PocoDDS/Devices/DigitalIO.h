#pragma once

#include "PocoDDS/Devices/Device.h"

#include <cstdint>
#include <functional>

namespace PocoDDS::Devices
{
class DigitalIO : public Device
{
public:
    using ValueHandler = std::function<void(std::uint32_t)>;

    virtual std::uint32_t read() const = 0;
    virtual void write(std::uint32_t value) = 0;
    virtual void setValueHandler(ValueHandler handler) = 0;
};

class LED : public Device
{
public:
    virtual void setBrightness(double brightness) = 0;
    virtual double brightness() const = 0;
};

class Switch : public Device
{
public:
    virtual void set(bool enabled) = 0;
    virtual bool get() const = 0;
};

class Trigger : public Device
{
public:
    virtual void trigger() = 0;
};
} // namespace PocoDDS::Devices
