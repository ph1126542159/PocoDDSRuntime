#include "PocoDDS/LocalIpc/LocalIpcTransport.h"
#include "PocoDDS/LocalIpc/Registration.h"
#include "PocoDDS/RuntimeCore/Testing/TransportConformance.h"

#include <chrono>
#include <future>
#include <iostream>
#include <memory>
#include <string>

#ifdef _WIN32
#include <Windows.h>
#else
#include <unistd.h>
#endif

int main()
{
    using namespace PocoDDS::LocalIpc;
    using namespace PocoDDS::RuntimeCore;
    using namespace std::chrono_literals;

    TransportRegistry registry;
    auto factoryRegistration = registerLocalIpcTransport(registry);
    if (!factoryRegistration || registry.descriptors().size() != 1 ||
        registry.descriptors().front().id != "ipc")
        return 10;
    const auto invalidFactoryConfiguration = registry.create("ipc");
    if (invalidFactoryConfiguration ||
        invalidFactoryConfiguration.error().code != RuntimeErrorCode::invalidArgument)
        return 11;

#ifdef _WIN32
    const auto endpoint = "pdr-local-ipc-smoke-" + std::to_string(GetCurrentProcessId());
#else
    const auto endpoint = "/tmp/pdr-local-ipc-smoke-" + std::to_string(getpid()) + ".sock";
#endif
    LocalIpcOptions serverOptions{endpoint, EndpointRole::server, "test-token", 1024 * 1024, 2s};
    LocalIpcOptions clientOptions{endpoint, EndpointRole::client, "test-token", 1024 * 1024, 2s};
    LocalIpcTransport server(serverOptions);
    LocalIpcTransport client(clientOptions);
    const TopicSpec clientTopic{"ipc.client-to-server", "example.IpcEvent", "1", Delivery::reliable,
                                false};
    const TopicSpec serverTopic{"ipc.server-to-client", "example.IpcEvent", "1", Delivery::reliable,
                                false};

    std::promise<std::string> serverReceived;
    auto serverFuture = serverReceived.get_future();
    std::promise<std::string> clientReceived;
    auto clientFuture = clientReceived.get_future();
    auto serverSubscription =
        server.subscribe(clientTopic, [&serverReceived](const TopicSpec&, const Message& message)
                         { serverReceived.set_value(message.context.messageId); });
    auto clientSubscription =
        client.subscribe(serverTopic, [&clientReceived](const TopicSpec&, const Message& message)
                         { clientReceived.set_value(message.context.correlationId); });

    if (!server.start() || !client.start())
        return 1;
    const auto conformance = PocoDDS::RuntimeCore::Testing::runTransportConformance(
        server, {server.id(), {false, true, false, false, false, false}});
    if (!conformance || conformance.value().passedChecks.size() != 7)
        return 12;
    Message fromClient{
        "example.IpcEvent", "1", std::make_shared<const Payload>(Payload{1, 2, 3}), {}};
    fromClient.context.messageId = "client-to-server";
    if (client.publish(clientTopic, fromClient).accepted == 0 ||
        serverFuture.wait_for(2s) != std::future_status::ready ||
        serverFuture.get() != "client-to-server")
        return 2;

    Message fromServer{
        "example.IpcEvent", "1", std::make_shared<const Payload>(Payload{4, 5, 6}), {}};
    fromServer.context.correlationId = "server-to-client";
    const auto serverResult = server.publish(serverTopic, fromServer);
    const auto clientStatus = clientFuture.wait_for(2s);
    if (serverResult.accepted == 0 || clientStatus != std::future_status::ready ||
        clientFuture.get() != "server-to-client")
        return 3;
    if (!server.running() || !client.running() || server.peerCount() != 1 ||
        client.peerCount() != 1 || !server.capabilities().interProcess)
        return 4;

    const TopicSpec rejectedTopic{"ipc.rejected", "example.IpcEvent", "1", Delivery::reliable,
                                  false};
    std::promise<void> rejectedDelivery;
    auto rejectedFuture = rejectedDelivery.get_future();
    auto rejectedSubscription =
        server.subscribe(rejectedTopic, [&rejectedDelivery](const TopicSpec&, const Message&)
                         { rejectedDelivery.set_value(); });
    LocalIpcTransport unauthorized(
        {endpoint, EndpointRole::client, "wrong-token", 1024 * 1024, 2s});
    if (!unauthorized.start())
        return 5;
    Message rejected{"example.IpcEvent", "1", std::make_shared<const Payload>(Payload{7}), {}};
    if (unauthorized.publish(rejectedTopic, rejected).accepted == 0 ||
        rejectedFuture.wait_for(200ms) != std::future_status::timeout)
        return 6;
    unauthorized.stop();

    const TopicSpec oversizedTopic{"ipc.oversized", "example.IpcEvent", "1", Delivery::bestEffort,
                                   false};
    Message oversized{
        "example.IpcEvent", "1", std::make_shared<const Payload>(Payload(1024 * 1024, 0x55)), {}};
    if (client.publish(oversizedTopic, oversized).dropped != 1)
        return 7;

    client.stop();
    if (client.publish(clientTopic, fromClient).failed == 0)
        return 8;
    server.stop();
    std::cout << "PDR_LOCAL_IPC_PASS transport=" << server.id()
              << " bidirectional=verified framing=v1\n";
    return 0;
}
