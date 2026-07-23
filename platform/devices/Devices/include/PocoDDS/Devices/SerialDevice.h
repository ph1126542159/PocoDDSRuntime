#pragma once

#include "PocoDDS/Devices/Device.h"

#include <cstddef>
#include <cstdint>
#include <functional>
#include <vector>

namespace PocoDDS::Devices
{
class SerialDevice : public Device
{
public:
    using DataHandler = std::function<void(const std::vector<std::uint8_t>&)>;

    virtual std::size_t write(const std::vector<std::uint8_t>& data) = 0;
    virtual void setDataHandler(DataHandler handler) = 0;
};
} // namespace PocoDDS::Devices
