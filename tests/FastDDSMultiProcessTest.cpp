#include "PocoDDS/Supervisor/Process.h"
#include <gtest/gtest.h>

#include <chrono>
#include <filesystem>
#include <fstream>
#include <thread>

namespace
{
void runMultiProcessTransportTest(const std::string& transportMode)
{
    const auto nonce = std::chrono::steady_clock::now().time_since_epoch().count();
    const auto domainId = 100 + static_cast<int>(nonce % 100);
    const auto marker =
        std::filesystem::temp_directory_path() / ("pdr-fastdds-" + std::to_string(nonce) + ".txt");
    auto launcher = PocoDDS::Supervisor::createNativeProcessLauncher();
    auto subscriber =
        launcher->start({"dds-subscriber",
                         PDR_DDS_PROBE_PATH,
                         {"subscribe", std::to_string(domainId), transportMode, marker.string()},
                         {},
                         {}});
    std::this_thread::sleep_for(std::chrono::milliseconds(300));
    auto publisher = launcher->start({"dds-publisher",
                                      PDR_DDS_PROBE_PATH,
                                      {"publish", std::to_string(domainId), transportMode},
                                      {},
                                      {}});

    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(25);
    while (!std::filesystem::exists(marker) && std::chrono::steady_clock::now() < deadline)
        std::this_thread::sleep_for(std::chrono::milliseconds(50));

    if (publisher->running())
        publisher->terminate(std::chrono::milliseconds(100));
    if (subscriber->running())
        subscriber->terminate(std::chrono::milliseconds(100));
    ASSERT_TRUE(std::filesystem::exists(marker));
    std::ifstream input(marker);
    std::string result;
    std::getline(input, result);
    input.close();
    std::filesystem::remove(marker);
    EXPECT_EQ(result, "FAST_DDS_TWO_PROCESS_PASS");
}

void runMultiProcessControlTest(const std::string& transportMode)
{
    const auto nonce = std::chrono::steady_clock::now().time_since_epoch().count();
    const auto domainId = 100 + static_cast<int>(nonce % 100);
    const auto marker = std::filesystem::temp_directory_path() /
                        ("pdr-fastdds-control-" + std::to_string(nonce) + ".txt");
    auto launcher = PocoDDS::Supervisor::createNativeProcessLauncher();
    auto agent = launcher->start({"dds-control-agent",
                                  PDR_DDS_PROBE_PATH,
                                  {"control-agent", std::to_string(domainId), transportMode},
                                  {},
                                  {}});
    std::this_thread::sleep_for(std::chrono::milliseconds(300));
    auto client = launcher->start(
        {"dds-control-client",
         PDR_DDS_PROBE_PATH,
         {"control-client", std::to_string(domainId), transportMode, marker.string()},
         {},
         {}});
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(25);
    while (!std::filesystem::exists(marker) && std::chrono::steady_clock::now() < deadline)
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    if (client->running())
        client->terminate(std::chrono::milliseconds(100));
    if (agent->running())
        agent->terminate(std::chrono::milliseconds(100));
    ASSERT_TRUE(std::filesystem::exists(marker));
    std::ifstream input(marker);
    std::string result;
    std::getline(input, result);
    input.close();
    std::filesystem::remove(marker);
    EXPECT_EQ(result, "FAST_DDS_CONTROL_PASS");
}
} // namespace

TEST(FastDDSMultiProcessTest, UsesSharedMemoryAndPreservesPayloadAndTraceContext)
{
    runMultiProcessTransportTest("shm");
}

TEST(FastDDSMultiProcessTest, UsesNetworkTransportAndPreservesPayloadAndTraceContext)
{
    runMultiProcessTransportTest("network");
}

TEST(FastDDSMultiProcessTest, RoutesControlCommandsAcrossProcessesUsingSharedMemory)
{
    runMultiProcessControlTest("shm");
}

TEST(FastDDSMultiProcessTest, RoutesControlCommandsAcrossProcessesUsingNetworkTransport)
{
    runMultiProcessControlTest("network");
}
