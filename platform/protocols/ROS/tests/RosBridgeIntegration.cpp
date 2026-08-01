#include "PocoDDS/Protocols/ROS/BridgeClient.h"

#include <Poco/Buffer.h>
#include <Poco/JSON/Parser.h>
#include <Poco/Net/HTTPServer.h>
#include <Poco/Net/HTTPRequestHandler.h>
#include <Poco/Net/HTTPRequestHandlerFactory.h>
#include <Poco/Net/HTTPServerParams.h>
#include <Poco/Net/ServerSocket.h>
#include <Poco/Net/WebSocket.h>

#include <condition_variable>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <utility>

namespace
{
struct State
{
    std::mutex mutex;
    std::condition_variable changed;
    bool finished{false};
    std::string error;
};

class Handler final : public Poco::Net::HTTPRequestHandler
{
public:
    explicit Handler(State& state): _state(state) {}

    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        std::string stage = "upgrade";
        try
        {
            Poco::Net::WebSocket socket(request, response);
            stage = "subscribe";
            Poco::Buffer<char> frame(0);
            int flags = 0;
            const int subscribed = socket.receiveFrame(frame, flags);
            if ((flags & Poco::Net::WebSocket::FRAME_OP_BITMASK) !=
                    Poco::Net::WebSocket::FRAME_OP_TEXT || subscribed <= 0)
                throw std::runtime_error("expected ROS subscribe request");
            Poco::JSON::Parser parser;
            const auto requestObject = parser.parse(
                std::string(frame.begin(), static_cast<std::size_t>(subscribed)))
                .extract<Poco::JSON::Object::Ptr>();
            if (requestObject->getValue<std::string>("op") != "subscribe")
                throw std::runtime_error("invalid ROS subscribe request");

            const std::string payload =
                R"({"op":"publish","topic":"/fix","msg":{"value":42}})";
            stage = "publish";
            const auto split = payload.size() / 2;
            socket.sendFrame(payload.data(), static_cast<int>(split),
                             Poco::Net::WebSocket::FRAME_OP_TEXT);
            const char ping = 'p';
            socket.sendFrame(&ping, 1,
                Poco::Net::WebSocket::FRAME_FLAG_FIN |
                Poco::Net::WebSocket::FRAME_OP_PING);
            socket.sendFrame(payload.data() + split,
                             static_cast<int>(payload.size() - split),
                             Poco::Net::WebSocket::FRAME_FLAG_FIN |
                             Poco::Net::WebSocket::FRAME_OP_CONT);

            bool unsubscribed = false;
            stage = "unsubscribe";
            while (!unsubscribed)
            {
                Poco::Buffer<char> nextFrame(0);
                flags = 0;
                const int count = socket.receiveFrame(nextFrame, flags);
                const int opcode = flags & Poco::Net::WebSocket::FRAME_OP_BITMASK;
                if (opcode == Poco::Net::WebSocket::FRAME_OP_PONG) continue;
                if (opcode == Poco::Net::WebSocket::FRAME_OP_TEXT && count > 0)
                {
                    const std::string text(
                        nextFrame.begin(), static_cast<std::size_t>(count));
                    const auto object = parser.parse(text)
                        .extract<Poco::JSON::Object::Ptr>();
                    unsubscribed = object->getValue<std::string>("op") == "unsubscribe";
                }
                else if (opcode == Poco::Net::WebSocket::FRAME_OP_CLOSE)
                    break;
            }
            if (!unsubscribed)
                throw std::runtime_error("expected ROS unsubscribe request");
        }
        catch (const std::exception& error)
        {
            std::lock_guard lock(_state.mutex);
            _state.error = stage + ": " + error.what();
        }
        {
            std::lock_guard lock(_state.mutex);
            _state.finished = true;
        }
        _state.changed.notify_all();
    }
private:
    State& _state;
};

class Factory final : public Poco::Net::HTTPRequestHandlerFactory
{
public:
    explicit Factory(State& state): _state(state) {}
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new Handler(_state);
    }
private:
    State& _state;
};
}

int main()
{
    State state;
    Poco::Net::ServerSocket listener(Poco::Net::SocketAddress("127.0.0.1", 0));
    const auto port = listener.address().port();
    Poco::Net::HTTPServer server(
        new Factory(state), listener, new Poco::Net::HTTPServerParams);
    server.start();

    PocoDDS::Protocols::ROS::BridgeClient::Options options;
    options.uri = Poco::URI("ws://127.0.0.1:" + std::to_string(port) + "/");
    options.maximumMessageSize = 4096;
    PocoDDS::Protocols::ROS::BridgeClient client(std::move(options));
    int callbacks = 0;
    client.setMessageHandler([&](const auto&) {
        ++callbacks;
        throw std::runtime_error("consumer failure");
    });
    client.open();
    if (!client.isOpen()) return 1;
    const auto subscription = client.subscribe("/fix");
    const auto message = client.receiveMessage(Poco::Timespan(3, 0));
    if (!message || message->getValue<std::string>("op") != "publish" ||
        message->getObject("msg")->getValue<int>("value") != 42 || callbacks != 1)
        return 1;
    client.unsubscribe("/fix", subscription);
    const auto diagnostics = client.diagnostics();
    if (diagnostics.sentMessages != 2 || diagnostics.receivedMessages != 1 ||
        diagnostics.sentBytes == 0 || diagnostics.receivedBytes == 0 ||
        diagnostics.handlerFailures != 1 || diagnostics.failedOperations != 0)
        return 1;
    client.close();
    if (client.isOpen()) return 1;

    {
        std::unique_lock lock(state.mutex);
        state.changed.wait_for(lock, std::chrono::seconds(3),
                               [&] { return state.finished; });
    }
    server.stop();
    if (!state.finished || !state.error.empty())
    {
        std::cerr << "ROS_BRIDGE_INTEGRATION_FAIL finished=" << state.finished
                  << " error=" << state.error << '\n';
        return 2;
    }
    return 0;
}
