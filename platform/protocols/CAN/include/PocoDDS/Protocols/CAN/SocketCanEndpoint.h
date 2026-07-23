#pragma once

#include "PocoDDS/Protocols/CAN/CanEndpoint.h"

#include <memory>
#include <string>

namespace PocoDDS::Protocols::CAN
{
class SocketCanEndpoint final : public CanEndpoint
{
public:
    explicit SocketCanEndpoint(std::string interfaceName);
    ~SocketCanEndpoint() override;

    std::string name() const override;
    void open() override;
    void close() noexcept override;
    bool isOpen() const noexcept override;
    void send(const CanFrame& frame) override;
    bool receive(CanFrame& frame, std::chrono::milliseconds timeout) override;
    void setFrameHandler(FrameHandler handler) override;

private:
    class Impl;
    std::unique_ptr<Impl> _impl;
};
} // namespace PocoDDS::Protocols::CAN
