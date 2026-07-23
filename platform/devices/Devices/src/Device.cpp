#include "PocoDDS/Devices/Device.h"

namespace PocoDDS::Devices
{
const char* toString(DeviceState state) noexcept
{
    switch (state)
    {
    case DeviceState::offline:
        return "offline";
    case DeviceState::ready:
        return "ready";
    case DeviceState::fault:
        return "fault";
    }
    return "unknown";
}
} // namespace PocoDDS::Devices
