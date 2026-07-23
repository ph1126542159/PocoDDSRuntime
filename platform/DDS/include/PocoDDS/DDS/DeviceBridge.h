#pragma once

#include "PocoDDS/Devices/Device.h"
#include "PocoDDS/DDS/Runtime.h"

#include <atomic>
#include <string>

namespace PocoDDS::FastDDS
{
class DeviceBridge
{
public:
    static constexpr const char* StateTopic = "pdr.device.state";
    static constexpr const char* RequestTopic = "pdr.device.request";
    static constexpr const char* ResponseTopic = "pdr.device.response";

    DeviceBridge(Runtime& runtime, PocoDDS::Devices::Device& device);
    ~DeviceBridge();

    void start();
    void stop() noexcept;

private:
    void publishSnapshot(const PocoDDS::Devices::DeviceSnapshot& snapshot);
    void handleRequest(const Envelope& request);

    Runtime& _runtime;
    PocoDDS::Devices::Device& _device;
    std::atomic<bool> _started{false};
};
} // namespace PocoDDS::FastDDS
