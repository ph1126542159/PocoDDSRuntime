#include "PocoDDS/Protocols/UDP/UdpChannel.h"

#include <iostream>
#include <stdexcept>
#include <utility>

int main()
{
    using PocoDDS::Protocols::UDP::UdpChannel;
    const Poco::Net::SocketAddress any("127.0.0.1", 0);
    UdpChannel receiver(UdpChannel::Options{any, any});
    receiver.open();
    UdpChannel sender(any, receiver.localAddress());
    sender.open();

    const std::vector<std::uint8_t> payload{0x00, 0x7E, 0xFF, 0x42};
    if (sender.send(payload.data(), payload.size()) != payload.size()) return 1;
    const auto datagram = receiver.receiveDatagram(64, Poco::Timespan(1, 0));
    if (!datagram.received || datagram.bytes != payload ||
        datagram.sender != sender.localAddress()) return 2;

    const auto timeout = receiver.receiveDatagram(64, Poco::Timespan(10000));
    if (timeout.received || !timeout.bytes.empty()) return 3;
    bool rejected = false;
    try { (void) receiver.receiveDatagram(0, Poco::Timespan(1000)); }
    catch (const std::length_error&) { rejected = true; }
    if (!rejected) return 4;

    const auto senderDiagnostics = sender.diagnostics();
    const auto receiverDiagnostics = receiver.diagnostics();
    if (senderDiagnostics.sentMessages != 1 ||
        senderDiagnostics.sentBytes != payload.size() ||
        receiverDiagnostics.receivedMessages != 1 ||
        receiverDiagnostics.receivedBytes != payload.size() ||
        receiverDiagnostics.timeouts != 1)
        return 5;

    sender.close();
    receiver.close();
    if (sender.isOpen() || receiver.isOpen()) return 6;
    std::cout << "UDP_SMOKE_PASS bytes=" << payload.size() << '\n';
    return 0;
}
