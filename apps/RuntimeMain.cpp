#include "PocoDDS/Core/ComponentRegistry.h"
#include "PocoDDS/Core/Configuration.h"

#if defined(PDR_ENABLE_ADMIN)
#include "PocoDDS/Admin/AdminHttpServer.h"
#endif

#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdlib>
#include <iostream>
#include <string>
#include <thread>

namespace
{
std::atomic_bool running{true};

void stopRuntime(int) { running = false; }

std::string environment(const char* name, const char* fallback = "")
{
#if defined(_WIN32)
    char* value = nullptr;
    std::size_t size = 0;
    if (_dupenv_s(&value, &size, name) == 0 && value)
    {
        std::string result(value);
        std::free(value);
        return result;
    }
#else
    const auto* value = std::getenv(name);
    if (value && *value)
        return value;
#endif
    return fallback;
}
} // namespace

int main(int argc, char** argv)
{
    PocoDDS::Core::ComponentRegistry registry;
    PocoDDS::Core::Configuration configuration;
    registry.upsert({"runtime-1",
                     "pdr-runtime",
                     "localhost",
                     0,
                     PocoDDS::Core::ComponentKind::Process,
                     PocoDDS::Core::ComponentState::Running,
                     {}});

#if defined(PDR_ENABLE_ADMIN)
    const auto token = environment("PDR_ADMIN_TOKEN");
    if (token.empty())
    {
        std::cerr << "PDR_ADMIN_TOKEN is required and must contain at least 16 characters\n";
        return 2;
    }
    const auto bindAddress = environment("PDR_ADMIN_BIND", "127.0.0.1");
    const auto port = static_cast<std::uint16_t>(std::stoi(environment("PDR_ADMIN_PORT", "9080")));
    PocoDDS::Admin::AdminService admin(
        registry, configuration,
        [&](const std::string& target, const std::string& action)
        {
            auto component = registry.find(target);
            if (!component)
                return PocoDDS::Admin::LifecycleResult{false, "component not found"};
            if (action == "uninstall")
            {
                registry.remove(target);
                return PocoDDS::Admin::LifecycleResult{true, "component removed"};
            }
            component->state = action == "stop" ? PocoDDS::Core::ComponentState::Stopped
                                                : PocoDDS::Core::ComponentState::Running;
            registry.upsert(*component);
            return PocoDDS::Admin::LifecycleResult{true, "lifecycle command applied"};
        });
    admin.appendLog(
        {std::chrono::system_clock::now(), "runtime-1", "info", "runtime started", {}, {}});
    PocoDDS::Admin::AdminHttpServer server(admin, {bindAddress, port, token});
    server.start();
    std::cout << "PocoDDSRuntime administration: http://" << bindAddress << ':' << server.port()
              << '\n';
#endif

    if (argc > 1 && std::string(argv[1]) == "--once")
        return 0;

    std::signal(SIGINT, stopRuntime);
    std::signal(SIGTERM, stopRuntime);
    const auto runSeconds = std::stoi(environment("PDR_RUN_SECONDS", "0"));
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(runSeconds);
    while (running && (runSeconds == 0 || std::chrono::steady_clock::now() < deadline))
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    return 0;
}
