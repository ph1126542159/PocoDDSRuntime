#include "PocoDDS/Protocols/WebTunnel/LocalForwarder.h"

#include <Poco/Net/SocketAddress.h>
#include <Poco/Net/StreamSocket.h>
#include <Poco/Timespan.h>

#include <array>
#include <cstdlib>
#include <exception>
#include <iostream>
#include <string>

namespace
{
std::string environmentValue(const char* name)
{
#ifdef _WIN32
    char* value = nullptr;
    std::size_t size = 0;
    if (_dupenv_s(&value, &size, name) != 0 || !value) return {};
    std::string result(value);
    std::free(value);
    return result;
#else
    const char* value = std::getenv(name);
    return value ? value : "";
#endif
}
} // namespace

int main(int argc, char** argv)
{
    if (argc != 7)
    {
        std::cerr << "usage: probe URI CA CERT KEY AUTH_ENV expect-success|expect-failure\n";
        return 2;
    }
    const bool expectSuccess = std::string(argv[6]) == "expect-success";
    const std::string authorization = environmentValue(argv[5]);
    if (authorization.empty())
    {
        std::cerr << "WEBTUNNEL_TLS_PROBE_FAIL authorization environment missing\n";
        return 3;
    }

    try
    {
        PocoDDS::Protocols::WebTunnel::LocalForwarder::Options options;
        options.remoteUri = argv[1];
        options.remotePort = 9080;
        options.authorization = authorization;
        options.trustStore = argv[2];
        if (std::string(argv[3]) != "-") options.clientCertificate = argv[3];
        if (std::string(argv[4]) != "-") options.privateKey = argv[4];
        options.connectTimeoutSeconds = 3;
        options.remoteIdleTimeoutSeconds = 3;
        PocoDDS::Protocols::WebTunnel::LocalForwarder forwarder(std::move(options));
        forwarder.open();

        Poco::Net::StreamSocket client;
        client.connect(
            Poco::Net::SocketAddress("127.0.0.1", forwarder.localPort()),
            Poco::Timespan(3, 0));
        client.setReceiveTimeout(Poco::Timespan(3, 0));
        const std::array<unsigned char, 6> sent{0, 1, 0x7f, 0x80, 0xfe, 0xff};
        std::array<unsigned char, 6> received{};
        client.sendBytes(sent.data(), static_cast<int>(sent.size()));
        std::size_t total = 0;
        while (total < received.size())
        {
            const int count = client.receiveBytes(
                received.data() + total,
                static_cast<int>(received.size() - total));
            if (count <= 0) break;
            total += static_cast<std::size_t>(count);
        }
        const bool exchanged = total == sent.size() && received == sent;
        if (exchanged != expectSuccess)
        {
            std::cerr << "WEBTUNNEL_TLS_PROBE_FAIL unexpected exchange result\n";
            return 4;
        }
    }
    catch (const std::exception& error)
    {
        if (expectSuccess)
        {
            std::cerr << "WEBTUNNEL_TLS_PROBE_FAIL " << error.what() << '\n';
            return 5;
        }
    }
    std::cout << "WEBTUNNEL_TLS_PROBE_PASS expectation="
              << (expectSuccess ? "success" : "failure") << '\n';
    return 0;
}
