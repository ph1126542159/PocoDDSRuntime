#pragma once

#include <cstdint>
#include <memory>
#include <string>

namespace PocoDDS::Protocols::WebTunnel
{

class LocalForwarder
{
public:
    struct Options
    {
        std::string localHost{"127.0.0.1"};
        std::uint16_t localPort{0};
        std::uint16_t remotePort{0};
        std::string remoteUri;
        int connectTimeoutSeconds{10};
        int localIdleTimeoutSeconds{0};
        int remoteIdleTimeoutSeconds{300};
        int maximumQueuedConnections{64};
        int maximumThreads{8};
        std::string authorization;
        std::string trustStore;
        std::string clientCertificate;
        std::string privateKey;
        bool verifyServerCertificate{true};
        bool verifyHostname{true};
    };

    explicit LocalForwarder(Options options);
    ~LocalForwarder();

    LocalForwarder(const LocalForwarder&) = delete;
    LocalForwarder& operator=(const LocalForwarder&) = delete;

    void open();
    void close() noexcept;
    [[nodiscard]] bool isOpen() const noexcept;
    [[nodiscard]] std::uint16_t localPort() const noexcept;

private:
    class Impl;
    std::unique_ptr<Impl> _impl;
};

} // namespace PocoDDS::Protocols::WebTunnel
