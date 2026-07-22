#include "PocoDDS/Admin/AdminHttpServer.h"

#include <Poco/JSON/Object.h>
#include <Poco/JSON/Parser.h>
#include <Poco/Net/HTTPClientSession.h>
#include <Poco/Net/HTTPRequest.h>
#include <Poco/Net/HTTPResponse.h>
#include <Poco/StreamCopier.h>

#include <gtest/gtest.h>

#include <sstream>

namespace
{
constexpr const char* Token = "0123456789abcdef0123456789abcdef";

struct Response
{
    Poco::Net::HTTPResponse::HTTPStatus status;
    std::string body;
};

Response request(std::uint16_t port, const std::string& method, const std::string& path,
                 const std::string& body = {}, bool authorized = true)
{
    Poco::Net::HTTPClientSession session("127.0.0.1", port);
    Poco::Net::HTTPRequest request(method, path, Poco::Net::HTTPMessage::HTTP_1_1);
    if (authorized)
        request.set("Authorization", std::string("Bearer ") + Token);
    if (!body.empty())
    {
        request.setContentType("application/json");
        request.setContentLength(body.size());
    }
    auto& output = session.sendRequest(request);
    output << body;
    Poco::Net::HTTPResponse response;
    auto& input = session.receiveResponse(response);
    std::ostringstream content;
    Poco::StreamCopier::copyStream(input, content);
    return {response.getStatus(), content.str()};
}
} // namespace

TEST(AdminHttpServerTest, EnforcesAuthenticationAndServesRuntimeData)
{
    PocoDDS::Core::ComponentRegistry registry;
    PocoDDS::Core::Configuration configuration;
    registry.upsert({"service.one",
                     "Service One",
                     "localhost",
                     101,
                     PocoDDS::Core::ComponentKind::Service,
                     PocoDDS::Core::ComponentState::Running,
                     {}});
    std::string lifecycle;
    PocoDDS::Admin::AdminService service(registry, configuration,
                                         [&](const auto& id, const auto& action)
                                         {
                                             lifecycle = id + ":" + action;
                                             return PocoDDS::Admin::LifecycleResult{true, "done"};
                                         });
    service.appendLog({std::chrono::system_clock::now(), "service.one", "info", "ready",
                       "trace-one", "span-one"});
    service.appendTrace({"trace-one",
                         "span-one",
                         {},
                         "start",
                         "service.one",
                         "success",
                         123,
                         {{"input", "one"}},
                         {{"output", "two"}},
                         {}});

    PocoDDS::Admin::AdminHttpServer server(service, {"127.0.0.1", 0, Token});
    server.start();

    EXPECT_EQ(request(server.port(), "GET", "/api/v1/topology", {}, false).status,
              Poco::Net::HTTPResponse::HTTP_UNAUTHORIZED);
    EXPECT_EQ(request(server.port(), "GET", "/", {}, false).status,
              Poco::Net::HTTPResponse::HTTP_OK);

    auto topology = request(server.port(), "GET", "/api/v1/topology");
    EXPECT_EQ(topology.status, Poco::Net::HTTPResponse::HTTP_OK);
    EXPECT_NE(topology.body.find("service.one"), std::string::npos);

    auto updated =
        request(server.port(), "PUT", "/api/v1/config", R"({"changes":{"quality":"high"}})");
    EXPECT_EQ(updated.status, Poco::Net::HTTPResponse::HTTP_OK);
    EXPECT_EQ(configuration.get("quality"), "high");

    auto controlled = request(server.port(), "POST", "/api/v1/lifecycle",
                              R"({"targetId":"service.one","action":"restart"})");
    EXPECT_EQ(controlled.status, Poco::Net::HTTPResponse::HTTP_OK);
    EXPECT_EQ(lifecycle, "service.one:restart");

    EXPECT_NE(
        request(server.port(), "GET", "/api/v1/logs?component=service.one").body.find("ready"),
        std::string::npos);
    auto trace = request(server.port(), "GET", "/api/v1/traces/trace-one");
    EXPECT_NE(trace.body.find("span-one"), std::string::npos);
    EXPECT_NE(trace.body.find("input"), std::string::npos);
    EXPECT_NE(request(server.port(), "GET", "/").body.find("PocoDDS Runtime"), std::string::npos);

    server.stop();
}

TEST(AdminHttpServerTest, RejectsWeakBearerToken)
{
    PocoDDS::Core::ComponentRegistry registry;
    PocoDDS::Core::Configuration configuration;
    PocoDDS::Admin::AdminService service(registry, configuration, [](const auto&, const auto&)
                                         { return PocoDDS::Admin::LifecycleResult{true, {}}; });
    EXPECT_THROW((PocoDDS::Admin::AdminHttpServer(service, {"127.0.0.1", 0, "short"})),
                 std::invalid_argument);
}
