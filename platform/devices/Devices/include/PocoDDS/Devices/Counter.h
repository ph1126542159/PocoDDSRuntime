#pragma once

#include "PocoDDS/Devices/Device.h"

#include <cstdint>
#include <functional>

namespace PocoDDS::Devices
{
class Counter : public Device
{
public:
    using CountHandler = std::function<void(std::int64_t)>;

    virtual std::int64_t count() const = 0;
    virtual void reset() = 0;
    virtual void setCountHandler(CountHandler handler) = 0;
};
} // namespace PocoDDS::Devices
