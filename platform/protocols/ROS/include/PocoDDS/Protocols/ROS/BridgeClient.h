#pragma once

#include "PocoDDS/Protocols/Protocol.h"
#include "PocoDDS/Protocols/ProtocolDiagnostics.h"

#include <Poco/JSON/Object.h>
#include <Poco/Net/WebSocket.h>
#include <Poco/URI.h>

#include <functional>
#include <cstddef>
#include <map>
#include <memory>
#include <mutex>
#include <string>

namespace PocoDDS::Protocols::ROS
{

class BridgeClient final : public PocoDDS::Protocols::DiagnosticProtocol,
                           public PocoDDS::Protocols::FailureDiagnosticProtocol
{
public:
    struct Options
    {
        Poco::URI uri;
        std::size_t maximumMessageSize{1024 * 1024};
        int connectTimeoutSeconds{10};
        std::string authorization;
        std::string trustStore;
        std::string clientCertificate;
        std::string privateKey;
        bool verifyServerCertificate{true};
        bool verifyHostname{true};
    };

    struct SubscribeOptions
    {
        std::string type;
        int throttleRate{0};
        int queueLength{0};
        int fragmentSize{0};
        std::string compression;
    };

    using MessageHandler = std::function<void(const Poco::JSON::Object::Ptr&)>;

    explicit BridgeClient(Options options);
    explicit BridgeClient(Poco::URI uri, std::size_t maximumMessageSize = 1024 * 1024);
    ~BridgeClient();

    BridgeClient(const BridgeClient&) = delete;
    BridgeClient& operator=(const BridgeClient&) = delete;

    std::string name() const override;
    void open() override;
    void close() noexcept override;
    bool isOpen() const noexcept override;

    void connect();
    void disconnect();
    [[nodiscard]] bool isConnected() const;

    std::string subscribe(const std::string& topic);
    std::string subscribe(const std::string& topic, const SubscribeOptions& options);
    void unsubscribe(const std::string& topic, const std::string& id = {});
    void unsubscribeAll();

    Poco::JSON::Object::Ptr receiveMessage(const Poco::Timespan& timeout);
    void setMessageHandler(MessageHandler handler);
    ProtocolDiagnostics diagnostics() const override;
    PocoDDS::Reliability::Failure failure() const override;

    static std::string makeSubscribeRequest(
        const std::string& topic,
        const std::string& id,
        const SubscribeOptions& options);
    static std::string makeUnsubscribeRequest(const std::string& topic, const std::string& id);

private:
    void sendText(const std::string& payload);

    Poco::URI _uri;
    std::size_t _maximumMessageSize;
    int _connectTimeoutSeconds;
    std::string _authorization;
    std::string _trustStore;
    std::string _clientCertificate;
    std::string _privateKey;
    bool _verifyServerCertificate;
    bool _verifyHostname;
    std::unique_ptr<Poco::Net::WebSocket> _socket;
    std::string _receiveBuffer;
    bool _receivingTextFragments{false};
    std::map<std::string, std::string> _subscriptions;
    MessageHandler _handler;
    ProtocolDiagnostics _diagnostics;
    PocoDDS::Reliability::Failure _failure;
    mutable std::mutex _mutex;
};

} // namespace PocoDDS::Protocols::ROS
