#pragma once

#include <Poco/JSON/Object.h>
#include <Poco/Net/WebSocket.h>
#include <Poco/URI.h>

#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <string>

namespace PocoDDS::Protocols::ROS
{

class BridgeClient
{
public:
    struct SubscribeOptions
    {
        std::string type;
        int throttleRate{0};
        int queueLength{0};
        int fragmentSize{0};
        std::string compression;
    };

    using MessageHandler = std::function<void(const Poco::JSON::Object::Ptr&)>;

    explicit BridgeClient(Poco::URI uri);
    ~BridgeClient();

    BridgeClient(const BridgeClient&) = delete;
    BridgeClient& operator=(const BridgeClient&) = delete;

    void connect();
    void disconnect();
    [[nodiscard]] bool isConnected() const;

    std::string subscribe(const std::string& topic);
    std::string subscribe(const std::string& topic, const SubscribeOptions& options);
    void unsubscribe(const std::string& topic, const std::string& id = {});
    void unsubscribeAll();

    Poco::JSON::Object::Ptr receiveMessage(const Poco::Timespan& timeout);
    void setMessageHandler(MessageHandler handler);

    static std::string makeSubscribeRequest(
        const std::string& topic,
        const std::string& id,
        const SubscribeOptions& options);
    static std::string makeUnsubscribeRequest(const std::string& topic, const std::string& id);

private:
    void sendText(const std::string& payload);

    Poco::URI _uri;
    std::unique_ptr<Poco::Net::WebSocket> _socket;
    std::map<std::string, std::string> _subscriptions;
    MessageHandler _handler;
    mutable std::mutex _mutex;
};

} // namespace PocoDDS::Protocols::ROS
