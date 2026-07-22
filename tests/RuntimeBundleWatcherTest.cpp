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
#include <filesystem>
#include <sstream>
#include <thread>
#include <utility>

namespace
{
constexpr const char* Token = "fedcba9876543210fedcba9876543210";

std::string request(std::uint16_t port, const std::string& method, const std::string& path,
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
    if (response.getStatus() < 200 || response.getStatus() >= 300)
        throw std::runtime_error(content.str());
    return content.str();
}

bool waitForBundle(std::uint16_t port, bool expected)
{
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(6);
    while (std::chrono::steady_clock::now() < deadline)
    {
        try
        {
            const auto topology = request(port, "GET", "/api/v1/topology");
            const bool present = topology.find("test.dynamic.bundle") != std::string::npos;
            if (present == expected)
                return true;
        }
        catch (...)
        {
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    return false;
}

class RuntimeCleanup
{
  public:
    RuntimeCleanup(PocoDDS::Supervisor::Process& runtime, std::filesystem::path directory)
        : _runtime(runtime), _directory(std::move(directory))
    {
    }

    ~RuntimeCleanup()
    {
        if (_runtime.running())
            _runtime.terminate(std::chrono::milliseconds(500));
        std::error_code ignored;
        std::filesystem::remove_all(_directory, ignored);
    }

  private:
    PocoDDS::Supervisor::Process& _runtime;
    std::filesystem::path _directory;
};
} // namespace

TEST(RuntimeBundleWatcherTest, ManagesWatchedBundleFromAdministrationApi)
{
    const auto nonce = std::chrono::steady_clock::now().time_since_epoch().count();
    const auto directory =
        std::filesystem::temp_directory_path() / ("pdr-runtime-bundles-" + std::to_string(nonce));
    std::filesystem::create_directories(directory);
    const auto source = std::filesystem::path(PDR_TEST_BUNDLE_PATH);
    const auto deployed = directory / ("runtime-bundle" + source.extension().string());
    std::filesystem::copy_file(source, deployed);

    Poco::Net::ServerSocket freePort(Poco::Net::SocketAddress("127.0.0.1", 0));
    const auto port = freePort.address().port();
    freePort.close();
    Poco::Environment::set("PDR_ADMIN_TOKEN", Token);
    Poco::Environment::set("PDR_ADMIN_PORT", std::to_string(port));
    Poco::Environment::set("PDR_BUNDLE_DIR", directory.string());
    Poco::Environment::set("PDR_RUN_SECONDS", "15");
    auto launcher = PocoDDS::Supervisor::createNativeProcessLauncher();
    auto runtime = launcher->start({"bundle-runtime", PDR_RUNTIME_PATH, {}, {}, {}});
    RuntimeCleanup cleanup(*runtime, directory);

    ASSERT_TRUE(waitForBundle(port, true));
    EXPECT_NE(request(port, "POST", "/api/v1/lifecycle",
                      R"({"targetId":"test.dynamic.bundle","action":"stop"})")
                  .find("\"success\":true"),
              std::string::npos);
    EXPECT_NE(request(port, "POST", "/api/v1/lifecycle",
                      R"({"targetId":"test.dynamic.bundle","action":"restart"})")
                  .find("\"success\":true"),
              std::string::npos);
    request(port, "POST", "/api/v1/lifecycle",
            R"({"targetId":"test.dynamic.bundle","action":"uninstall"})");
    EXPECT_TRUE(waitForBundle(port, false));
    std::this_thread::sleep_for(std::chrono::milliseconds(1200));
    EXPECT_TRUE(waitForBundle(port, false));

    std::filesystem::last_write_time(deployed, std::filesystem::file_time_type::clock::now() +
                                                   std::chrono::seconds(2));
    EXPECT_TRUE(waitForBundle(port, true));
}
