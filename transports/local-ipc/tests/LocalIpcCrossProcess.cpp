#include "PocoDDS/LocalIpc/LocalIpcTransport.h"

#include <chrono>
#include <future>
#include <iostream>
#include <memory>
#include <string>
#include <thread>

#ifdef _WIN32
#include <Windows.h>
#else
#include <csignal>
#include <sys/wait.h>
#include <unistd.h>
#endif

namespace
{
using namespace PocoDDS::LocalIpc;
using namespace PocoDDS::RuntimeCore;
using namespace std::chrono_literals;

const TopicSpec requestTopic{"ipc.cross-process.request", "example.Request", "1",
                             Delivery::reliable, false};
const TopicSpec responseTopic{"ipc.cross-process.response", "example.Response", "1",
                              Delivery::reliable, false};

int runClient(const std::string& endpoint)
{
    LocalIpcTransport client(
        {endpoint, EndpointRole::client, "cross-process-token", 1024 * 1024, 3s});
    std::promise<std::string> response;
    auto responseFuture = response.get_future();
    auto subscription =
        client.subscribe(responseTopic, [&response](const TopicSpec&, const Message& message)
                         { response.set_value(message.context.correlationId); });
    if (!client.start())
        return 11;
    Message request{
        "example.Request", "1", std::make_shared<const Payload>(Payload{0x10, 0x20}), {}};
    request.context.messageId = "request-1";
    if (client.publish(requestTopic, request).accepted == 0)
        return 12;
    if (responseFuture.wait_for(3s) != std::future_status::ready ||
        responseFuture.get() != "request-1")
        return 13;
    client.stop();
    return 0;
}

#ifdef _WIN32
struct ChildProcess
{
    PROCESS_INFORMATION information{};
};

ChildProcess launchChild(const std::string& executable, const std::string& endpoint)
{
    std::string command = "\"" + executable + "\" --client \"" + endpoint + "\"";
    STARTUPINFOA startup{};
    startup.cb = sizeof(startup);
    ChildProcess child;
    if (!CreateProcessA(nullptr, command.data(), nullptr, nullptr, FALSE, CREATE_NO_WINDOW, nullptr,
                        nullptr, &startup, &child.information))
        throw std::runtime_error("CreateProcess failed");
    return child;
}

int waitChild(ChildProcess& child)
{
    const auto wait = WaitForSingleObject(child.information.hProcess, 5000);
    if (wait != WAIT_OBJECT_0)
    {
        TerminateProcess(child.information.hProcess, 124);
        WaitForSingleObject(child.information.hProcess, 1000);
    }
    DWORD exitCode = 125;
    GetExitCodeProcess(child.information.hProcess, &exitCode);
    CloseHandle(child.information.hThread);
    CloseHandle(child.information.hProcess);
    return wait == WAIT_OBJECT_0 ? static_cast<int>(exitCode) : 124;
}
#else
struct ChildProcess
{
    pid_t pid{-1};
};

ChildProcess launchChild(const std::string& executable, const std::string& endpoint)
{
    const auto pid = fork();
    if (pid < 0)
        throw std::runtime_error("fork failed");
    if (pid == 0)
    {
        execl(executable.c_str(), executable.c_str(), "--client", endpoint.c_str(),
              static_cast<char*>(nullptr));
        _exit(126);
    }
    return {pid};
}

int waitChild(ChildProcess& child)
{
    int status = 0;
    for (int attempt = 0; attempt < 100; ++attempt)
    {
        if (waitpid(child.pid, &status, WNOHANG) == child.pid)
            return WIFEXITED(status) ? WEXITSTATUS(status) : 125;
        std::this_thread::sleep_for(50ms);
    }
    kill(child.pid, SIGTERM);
    waitpid(child.pid, &status, 0);
    return 124;
}
#endif
} // namespace

int main(int argc, char** argv)
{
    using namespace PocoDDS::LocalIpc;
    using namespace PocoDDS::RuntimeCore;
    using namespace std::chrono_literals;

    if (argc == 3 && std::string(argv[1]) == "--client")
        return runClient(argv[2]);

#ifdef _WIN32
    const auto endpoint = "pdr-local-ipc-cross-process-" + std::to_string(GetCurrentProcessId());
#else
    const auto endpoint = "/tmp/pdr-local-ipc-cross-process-" + std::to_string(getpid()) + ".sock";
#endif
    LocalIpcTransport server(
        {endpoint, EndpointRole::server, "cross-process-token", 1024 * 1024, 3s});
    std::promise<std::string> request;
    auto requestFuture = request.get_future();
    auto subscription =
        server.subscribe(requestTopic, [&request](const TopicSpec&, const Message& message)
                         { request.set_value(message.context.messageId); });
    if (!server.start())
        return 1;

    ChildProcess child;
    try
    {
        child = launchChild(argv[0], endpoint);
    }
    catch (...)
    {
        server.stop();
        return 2;
    }
    if (requestFuture.wait_for(3s) != std::future_status::ready)
    {
        const auto childCode = waitChild(child);
        server.stop();
        return childCode == 0 ? 3 : childCode;
    }
    const auto requestId = requestFuture.get();
    Message response{
        "example.Response", "1", std::make_shared<const Payload>(Payload{0x30, 0x40}), {}};
    response.context.correlationId = requestId;
    if (server.publish(responseTopic, response).accepted == 0)
    {
        waitChild(child);
        server.stop();
        return 4;
    }
    const auto childCode = waitChild(child);
    server.stop();
    if (childCode != 0)
        return childCode;

    std::cout << "PDR_LOCAL_IPC_CROSS_PROCESS_PASS transport=" << server.id()
              << " childExit=0 bidirectional=verified\n";
    return 0;
}
