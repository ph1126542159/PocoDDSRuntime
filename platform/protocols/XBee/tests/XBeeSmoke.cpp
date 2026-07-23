#include "PocoDDS/Protocols/XBee/XBeeFrame.h"
#include "PocoDDS/Protocols/XBee/IoSample.h"

#include <cstdint>
#include <iostream>
#include <vector>

int main()
{
    using namespace PocoDDS::Protocols::XBee;
    const std::vector<std::uint8_t> payload{0x01, 0x7E, 0x7D, 0x11, 0x13, 0x55};
    XBeeFrame frame(FrameType::atCommand, payload);

    for (const bool escaped : {false, true})
    {
        const auto wire = frame.encode(escaped);
        XBeeFrame decoded;
        std::size_t consumed = 0;
        const auto status =
            XBeeFrame::parse(decoded, wire.data(), wire.size(), consumed, escaped);
        if (status != ParseStatus::ok || consumed == 0 ||
            decoded.type() != FrameType::atCommand || decoded.data() != payload)
        {
            std::cerr << "XBEE_SMOKE_FAIL escaped=" << escaped << '\n';
            return 2;
        }
    }

    auto corrupt = frame.encode();
    corrupt.back() ^= 0x01;
    XBeeFrame decoded;
    std::size_t consumed = 0;
    if (XBeeFrame::parse(decoded, corrupt.data(), corrupt.size(), consumed) !=
        ParseStatus::badChecksum)
    {
        std::cerr << "XBEE_SMOKE_FAIL checksum\n";
        return 3;
    }

    const XBeeFrame ioFrame(
        FrameType::zigbeeIoSample,
        {0x00, 0x13, 0xA2, 0x00, 0x40, 0x52, 0x91, 0xAB,
         0x7D, 0x84, 0x01, 0x01, 0x00, 0x03, 0x05,
         0x00, 0x01, 0x02, 0x00, 0x03, 0xFF});
    const auto sample = IoSample::decode(ioFrame);
    if (sample.addressString() != "0013A200405291AB" ||
        !sample.digital(0) || sample.digital(1) ||
        sample.analog(0) != 0x0200 || sample.analog(2) != 0x03FF)
        return 5;

    std::cout << "XBEE_SMOKE_PASS address=" << sample.addressString() << '\n';
    return 0;
}
