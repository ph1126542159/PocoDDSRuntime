#pragma once

#include "PocoDDS/Protocols/Protocol.h"

#include <array>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <functional>

namespace PocoDDS::Protocols::CAN
{
struct CanFrame
{
    std::uint32_t id{0};
    bool extended{false};
    bool remoteRequest{false};
    bool error{false};
    std::uint8_t length{0};
    std::array<std::uint8_t, 64> data{};
};

class CanEndpoint : public PocoDDS::Protocols::Protocol
{
public:
    using FrameHandler = std::function<void(const CanFrame&)>;

    virtual void send(const CanFrame& frame) = 0;
    virtual bool receive(CanFrame& frame, std::chrono::milliseconds timeout) = 0;
    virtual void setFrameHandler(FrameHandler handler) = 0;
};
} // namespace PocoDDS::Protocols::CAN
