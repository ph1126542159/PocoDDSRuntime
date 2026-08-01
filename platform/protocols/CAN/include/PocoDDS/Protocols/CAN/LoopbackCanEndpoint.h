#pragma once

#include "PocoDDS/Protocols/CAN/CanEndpoint.h"

#include <condition_variable>
#include <deque>
#include <mutex>
#include <string>

namespace PocoDDS::Protocols::CAN
{
class LoopbackCanEndpoint final : public CanEndpoint
{
public:
    explicit LoopbackCanEndpoint(std::string endpointName = "loopback");

    std::string name() const override;
    void open() override;
    void close() noexcept override;
    bool isOpen() const noexcept override;
    void send(const CanFrame& frame) override;
    bool receive(CanFrame& frame, std::chrono::milliseconds timeout) override;
    void setFrameHandler(FrameHandler handler) override;

    void injectError(std::uint32_t errorMask);
    void disconnect();

private:
    std::string _name;
    mutable std::mutex _mutex;
    std::condition_variable _ready;
    std::deque<CanFrame> _frames;
    FrameHandler _handler;
    bool _open{false};
};
}
