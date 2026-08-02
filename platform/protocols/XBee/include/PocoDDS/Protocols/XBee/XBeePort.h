#pragma once

#include "PocoDDS/Protocols/Serial/SerialChannel.h"
#include "PocoDDS/Protocols/XBee/XBeeFrame.h"

#include <memory>
#include <string>
#include <vector>

namespace PocoDDS::Protocols::XBee
{
class XBeePort final : public PocoDDS::Protocols::Protocol
{
public:
    explicit XBeePort(std::shared_ptr<PocoDDS::Protocols::Serial::ISerialChannel> serial,
                      bool escapedApiMode = false);

    std::string name() const override;
    void open() override;
    void close() noexcept override;
    bool isOpen() const noexcept override;

    void send(const XBeeFrame& frame);
    bool receive(XBeeFrame& frame, Poco::Timespan timeout);

private:
    std::shared_ptr<PocoDDS::Protocols::Serial::ISerialChannel> _serial;
    bool _escapedApiMode;
    std::vector<std::uint8_t> _receiveBuffer;
};
} // namespace PocoDDS::Protocols::XBee
