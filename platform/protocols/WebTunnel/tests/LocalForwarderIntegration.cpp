#include "PocoDDS/Protocols/WebTunnel/LocalForwarder.h"

#include <Poco/Net/HTTPServer.h>
#include <Poco/Net/HTTPServerParams.h>
#include <Poco/Net/HTTPRequestHandler.h>
#include <Poco/Net/HTTPRequestHandlerFactory.h>
#include <Poco/Net/HTTPServerRequest.h>
#include <Poco/Net/HTTPServerResponse.h>
#include <Poco/Net/ServerSocket.h>
#include <Poco/Net/SocketAddress.h>
#include <Poco/Net/StreamSocket.h>
#include <Poco/Net/WebSocket.h>
#include <Poco/NumberFormatter.h>
#include <Poco/Timespan.h>

#include <array>
#include <atomic>
#include <cstdint>
#include <iostream>
#include <memory>
#include <string>
#include <thread>

namespace
{
constexpr const char* Authorization = "Bearer pdr-webtunnel-test";
constexpr const char* Protocol = "com.appinf.webtunnel.client/1.0";

struct TunnelState
{
    TunnelState(Poco::UInt16 targetPort): targetPort(targetPort)
    {
    }

    Poco::UInt16 targetPort;
    std::atomic<int> accepted{0};
    std::atomic<int> rejected{0};
};

class TunnelHandler final : public Poco::Net::HTTPRequestHandler
{
public:
    explicit TunnelHandler(std::shared_ptr<TunnelState> state): _state(std::move(state)) {}

    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        if (request.getMethod() != "POST" ||
            request.get("Authorization", "") != Authorization ||
            request.get("Sec-WebSocket-Protocol", "") != Protocol ||
            request.get("X-WebTunnel-RemotePort", "") !=
                Poco::NumberFormatter::format(_state->targetPort))
        {
            ++_state->rejected;
            response.setStatus(Poco::Net::HTTPResponse::HTTP_FORBIDDEN);
            response.setContentLength(0);
            response.send();
            return;
        }

        response.set("Sec-WebSocket-Protocol", Protocol);
        Poco::Net::WebSocket socket(request, response);
        socket.setReceiveTimeout(Poco::Timespan(5, 0));
        Poco::Net::StreamSocket target;
        target.connect(
            Poco::Net::SocketAddress("127.0.0.1", _state->targetPort),
            Poco::Timespan(3, 0));
        target.setReceiveTimeout(Poco::Timespan(5, 0));
        ++_state->accepted;
        std::array<std::uint8_t, 4096> buffer{};
        while (true)
        {
            int flags = 0;
            const int count = socket.receiveFrame(
                buffer.data(), static_cast<int>(buffer.size()), flags);
            if (count <= 0 ||
                (flags & Poco::Net::WebSocket::FRAME_OP_BITMASK) ==
                    Poco::Net::WebSocket::FRAME_OP_CLOSE)
                break;
            if ((flags & Poco::Net::WebSocket::FRAME_OP_BITMASK) !=
                Poco::Net::WebSocket::FRAME_OP_BINARY)
                continue;
            target.sendBytes(buffer.data(), count);
            const int echoed = target.receiveBytes(
                buffer.data(), static_cast<int>(buffer.size()));
            if (echoed <= 0) break;
            socket.sendFrame(buffer.data(), echoed, Poco::Net::WebSocket::FRAME_BINARY);
        }
    }

private:
    std::shared_ptr<TunnelState> _state;
};

class TunnelHandlerFactory final : public Poco::Net::HTTPRequestHandlerFactory
{
public:
    explicit TunnelHandlerFactory(std::shared_ptr<TunnelState> state):
        _state(std::move(state))
    {
    }

    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new TunnelHandler(_state);
    }

private:
    std::shared_ptr<TunnelState> _state;
};

bool receiveExactly(Poco::Net::StreamSocket& socket, std::uint8_t* data, std::size_t size)
{
    std::size_t received = 0;
    while (received < size)
    {
        const int count = socket.receiveBytes(
            data + received, static_cast<int>(size - received));
        if (count <= 0) return false;
        received += static_cast<std::size_t>(count);
    }
    return true;
}
} // namespace

int main()
{
    using PocoDDS::Protocols::WebTunnel::LocalForwarder;

    Poco::Net::ServerSocket echoListener(Poco::Net::SocketAddress("127.0.0.1", 0));
    const auto echoPort = echoListener.address().port();
    std::atomic<bool> echoPassed{false};
    std::thread echoThread([&] {
        try
        {
            Poco::Net::StreamSocket peer = echoListener.acceptConnection();
            peer.setReceiveTimeout(Poco::Timespan(5, 0));
            std::array<std::uint8_t, 8> payload{};
            if (receiveExactly(peer, payload.data(), payload.size()))
            {
                peer.sendBytes(payload.data(), static_cast<int>(payload.size()));
                echoPassed = true;
            }
        }
        catch (...) {}
    });

    auto state = std::make_shared<TunnelState>(echoPort);
    Poco::Net::ServerSocket tunnelListener(Poco::Net::SocketAddress("127.0.0.1", 0));
    const auto tunnelPort = tunnelListener.address().port();
    Poco::Net::HTTPServer tunnelServer(
        new TunnelHandlerFactory(state), tunnelListener, new Poco::Net::HTTPServerParams);
    tunnelServer.start();

    int result = 0;
    try
    {
        LocalForwarder::Options options;
        options.remoteUri = "ws://127.0.0.1:" + std::to_string(tunnelPort) + "/tunnel";
        options.remotePort = echoPort;
        options.authorization = Authorization;
        options.connectTimeoutSeconds = 3;
        options.remoteIdleTimeoutSeconds = 10;
        LocalForwarder forwarder(std::move(options));
        forwarder.open();
        forwarder.open(); // Idempotent lifecycle.
        if (!forwarder.isOpen() || forwarder.localPort() == 0)
            throw std::runtime_error("local forwarder did not start");

        Poco::Net::StreamSocket client;
        client.connect(
            Poco::Net::SocketAddress("127.0.0.1", forwarder.localPort()),
            Poco::Timespan(3, 0));
        client.setReceiveTimeout(Poco::Timespan(5, 0));
        const std::array<std::uint8_t, 8> sent{0x00, 0x7f, 0x80, 0xff, 1, 2, 3, 4};
        std::array<std::uint8_t, 8> received{};
        client.sendBytes(sent.data(), static_cast<int>(sent.size()));
        if (!receiveExactly(client, received.data(), received.size()) || received != sent)
            throw std::runtime_error("tunneled binary echo mismatch");
        client.close();
        forwarder.close();
        forwarder.close();
        if (forwarder.isOpen())
            throw std::runtime_error("local forwarder did not stop");
    }
    catch (const std::exception& error)
    {
        std::cerr << "WEBTUNNEL_LOCAL_FORWARDER_FAIL " << error.what() << '\n';
        result = 1;
    }

    echoListener.close();
    if (echoThread.joinable()) echoThread.join();
    tunnelServer.stopAll(true);
    if (!echoPassed || state->accepted != 1 || state->rejected != 0)
    {
        std::cerr << "WEBTUNNEL_LOCAL_FORWARDER_FAIL evidence echo=" << echoPassed
                  << " accepted=" << state->accepted << " rejected=" << state->rejected
                  << '\n';
        return 2;
    }
    if (result != 0) return result;
    std::cout << "WEBTUNNEL_LOCAL_FORWARDER_PASS binaryEcho=verified "
                 "authorization=verified lifecycle=idempotent\n";
    return 0;
}
