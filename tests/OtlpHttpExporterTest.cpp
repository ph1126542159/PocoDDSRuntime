#include "PocoDDS/Observability/BusinessTracer.h"

#include <Poco/JSON/Array.h>
#include <Poco/JSON/Object.h>
#include <Poco/JSON/Parser.h>
#include <Poco/Net/HTTPRequestHandler.h>
#include <Poco/Net/HTTPRequestHandlerFactory.h>
#include <Poco/Net/HTTPServer.h>
#include <Poco/Net/HTTPServerRequest.h>
#include <Poco/Net/HTTPServerResponse.h>
#include <Poco/Net/ServerSocket.h>
#include <Poco/Net/SocketAddress.h>
#include <Poco/StreamCopier.h>

#include <gtest/gtest.h>

#include <mutex>
#include <sstream>

namespace
{
struct CollectorState
{
    std::mutex mutex;
    std::string path;
    std::string authorization;
    std::string body;
};

class CollectorHandler final : public Poco::Net::HTTPRequestHandler
{
  public:
    explicit CollectorHandler(CollectorState& state) : _state(state) {}

    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        std::ostringstream body;
        Poco::StreamCopier::copyStream(request.stream(), body);
        {
            std::lock_guard lock(_state.mutex);
            _state.path = request.getURI();
            _state.authorization = request.get("Authorization", "");
            _state.body = body.str();
        }
        response.setStatus(Poco::Net::HTTPServerResponse::HTTP_OK);
        response.setContentType("application/json");
        response.send() << "{}";
    }

  private:
    CollectorState& _state;
};

class CollectorFactory final : public Poco::Net::HTTPRequestHandlerFactory
{
  public:
    explicit CollectorFactory(CollectorState& state) : _state(state) {}

    Poco::Net::HTTPRequestHandler*
    createRequestHandler(const Poco::Net::HTTPServerRequest&) override
    {
        return new CollectorHandler(_state);
    }

  private:
    CollectorState& _state;
};
} // namespace

TEST(OtlpHttpExporterTest, SendsCollectorCompatibleJsonWithBusinessDataAndLogs)
{
    CollectorState state;
    Poco::Net::ServerSocket socket(Poco::Net::SocketAddress("127.0.0.1", 0));
    const auto port = socket.address().port();
    Poco::Net::HTTPServer collector(new CollectorFactory(state), socket,
                                    new Poco::Net::HTTPServerParams);
    collector.start();

    PocoDDS::Observability::BusinessTracer tracer("order.worker",
                                                  {"http://127.0.0.1:" + std::to_string(port),
                                                   {{"Authorization", "Bearer collector-secret"}}});
    auto span = tracer.start("fulfil-order", {{"orderId", "A-42"}});
    span.addLog("inventory reserved");
    span.finish("success", {{"shipmentId", "S-7"}});

    std::string body;
    {
        std::lock_guard lock(state.mutex);
        EXPECT_EQ(state.path, "/v1/traces");
        EXPECT_EQ(state.authorization, "Bearer collector-secret");
        body = state.body;
    }
    collector.stop();

    auto root = Poco::JSON::Parser().parse(body).extract<Poco::JSON::Object::Ptr>();
    auto resourceSpans = root->getArray("resourceSpans");
    ASSERT_TRUE(resourceSpans);
    ASSERT_EQ(resourceSpans->size(), 1U);
    auto resourceSpan = resourceSpans->getObject(0);
    auto scopeSpans = resourceSpan->getArray("scopeSpans");
    auto exportedSpan = scopeSpans->getObject(0)->getArray("spans")->getObject(0);
    EXPECT_EQ(exportedSpan->getValue<std::string>("name"), "fulfil-order");
    EXPECT_EQ(exportedSpan->getObject("status")->getValue<std::string>("message"), "success");
    EXPECT_EQ(exportedSpan->getValue<std::string>("traceId").size(), 32U);
    EXPECT_EQ(exportedSpan->getValue<std::string>("spanId").size(), 16U);
    EXPECT_NE(body.find("service.name"), std::string::npos);
    EXPECT_NE(body.find("business.input.orderId"), std::string::npos);
    EXPECT_NE(body.find("business.output.shipmentId"), std::string::npos);
    EXPECT_NE(body.find("log.message"), std::string::npos);
    EXPECT_NE(body.find("inventory reserved"), std::string::npos);
}
