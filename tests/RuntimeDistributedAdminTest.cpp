#include "PocoDDS/Supervisor/Process.h"

#include <Poco/Environment.h>
#include <Poco/Net/HTTPClientSession.h>
#include <Poco/Net/HTTPRequest.h>
#include <Poco/Net/HTTPResponse.h>
#include <Poco/Net/ServerSocket.h>
#include <Poco/Net/SocketAddress.h>
#include <Poco/StreamCopier.h>

#include <gtest/gtest.h>

#include <chrono>
#include <sstream>
#include <thread>

namespace
{
constexpr const char* Token = "0123456789abcdef0123456789abcdef";

struct HttpResult
{
    Poco::Net::HTTPResponse::HTTPStatus status;
    std::string body;
};

class ProcessCleanup
{
  public:
    ProcessCleanup(PocoDDS::Supervisor::Process& first, PocoDDS::Supervisor::Process& second)
        : _first(first), _second(second)
    {
    }

    ~ProcessCleanup()
    {
        if (_second.running())
            _second.terminate(std::chrono::milliseconds(500));
        if (_first.running())
            _first.terminate(std::chrono::milliseconds(500));
    }

  private:
    PocoDDS::Supervisor::Process& _first;
    PocoDDS::Supervisor::Process& _second;
};

HttpResult request(std::uint16_t port, const std::string& method, const std::string& path,
                   const std::string& body = {})
{
    Poco::Net::HTTPClientSession session("127.0.0.1", port);
    session.setTimeout(Poco::Timespan(1, 0));
    Poco::Net::HTTPRequest request(method, path, Poco::Net::HTTPMessage::HTTP_1_1);
    request.set("Authorization", std::string("Bearer ") + Token);
    if (!body.empty())
    {
        request.setContentType("application/json");
        request.setContentLength(body.size());
    }
    session.sendRequest(request) << body;
    Poco::Net::HTTPResponse response;
    auto& input = session.receiveResponse(response);
    std::ostringstream content;
    Poco::StreamCopier::copyStream(input, content);
    return {response.getStatus(), content.str()};
}
} // namespace

TEST(RuntimeDistributedAdminTest, DiscoversAndControlsRemoteProcessOverFastDds)
{
    const auto nonce = std::chrono::steady_clock::now().time_since_epoch().count();
    const auto domain = 100 + static_cast<int>(nonce % 100);
    Poco::Net::ServerSocket freePort(Poco::Net::SocketAddress("127.0.0.1", 0));
    const auto port = freePort.address().port();
    freePort.close();

    auto launcher = PocoDDS::Supervisor::createNativeProcessLauncher();
    auto agent = launcher->start({"distributed-admin-agent",
                                  PDR_DDS_PROBE_PATH,
                                  {"control-agent", std::to_string(domain), "auto"},
                                  {},
                                  {}});
    Poco::Environment::set("PDR_ADMIN_TOKEN", Token);
    Poco::Environment::set("PDR_ADMIN_PORT", std::to_string(port));
    Poco::Environment::set("PDR_DDS_DOMAIN", std::to_string(domain));
    Poco::Environment::set("PDR_RUN_SECONDS", "15");
    auto runtime = launcher->start({"distributed-admin-runtime", PDR_RUNTIME_PATH, {}, {}, {}});
    ProcessCleanup cleanup(*agent, *runtime);

    bool discovered = false;
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(8);
    while (!discovered && std::chrono::steady_clock::now() < deadline)
    {
        try
        {
            const auto topology = request(port, "GET", "/api/v1/topology");
            discovered = topology.status == Poco::Net::HTTPResponse::HTTP_OK &&
                         topology.body.find("acceptance.control.worker") != std::string::npos;
        }
        catch (...)
        {
        }
        if (!discovered)
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    ASSERT_TRUE(discovered);

    const auto configured = request(
        port, "PUT", "/api/v1/config",
        R"({"targetComponentId":"acceptance.control.worker","expectedRevision":0,"changes":{"quality":"acceptance"}})");
    EXPECT_EQ(configured.status, Poco::Net::HTTPResponse::HTTP_OK);
    EXPECT_NE(configured.body.find("\"revision\":1"), std::string::npos);
    const auto restarted =
        request(port, "POST", "/api/v1/lifecycle",
                R"({"targetId":"acceptance.control.worker","action":"restart"})");
    EXPECT_EQ(restarted.status, Poco::Net::HTTPResponse::HTTP_OK);
    EXPECT_NE(restarted.body.find("\"success\":true"), std::string::npos);
}
