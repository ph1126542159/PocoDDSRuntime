#include "PocoDDS/Devices/SimulatedDevice.h"
#include "PocoDDS/DDS/DeviceBridge.h"
#include "PocoDDS/DDS/Runtime.h"

#include <chrono>
#include <condition_variable>
#include <iostream>
#include <mutex>
#include <string>
#include <thread>

int main(int argc, char** argv)
{
    using PocoDDS::FastDDS::DeviceBridge;
    using PocoDDS::FastDDS::Envelope;

    try
    {
    const bool externalGateway = argc > 1 && std::string(argv[1]) == "--probe";
    std::cerr << "SMOKE_STAGE runtime-create\n";
    PocoDDS::FastDDS::Runtime runtime(externalGateway ? 0 : 37,
                                     externalGateway ? "pdr-fastdds-device-probe"
                                                     : "pdr-fastdds-device-smoke");
    runtime.start();
    std::cerr << "SMOKE_STAGE runtime-started\n";

    std::mutex mutex;
    std::condition_variable changed;
    int stateCount = 0;
    bool responseReceived = false;
    std::string responsePayload;

    runtime.subscribe(DeviceBridge::StateTopic, [&](const Envelope& envelope) {
        if (envelope.deviceId == "simulation-1")
        {
            std::lock_guard<std::mutex> lock(mutex);
            ++stateCount;
            changed.notify_all();
        }
    });
    runtime.subscribe(DeviceBridge::ResponseTopic, [&](const Envelope& envelope) {
        if (envelope.correlationId == "smoke-request-1" && envelope.status == 0)
        {
            std::lock_guard<std::mutex> lock(mutex);
            responseReceived = true;
            responsePayload = envelope.payload;
            changed.notify_all();
        }
    });
    std::cerr << "SMOKE_STAGE readers-created\n";

    std::unique_ptr<PocoDDS::Devices::SimulatedDevice> device;
    std::unique_ptr<DeviceBridge> bridge;
    if (!externalGateway)
    {
        device = std::make_unique<PocoDDS::Devices::SimulatedDevice>("simulation-1");
        bridge = std::make_unique<DeviceBridge>(runtime, *device);
        bridge->start();
        std::cerr << "SMOKE_STAGE bridge-started\n";
    }

    if (externalGateway)
    {
        std::unique_lock<std::mutex> lock(mutex);
        changed.wait_for(lock, std::chrono::seconds(8), [&] { return stateCount >= 1; });
    }
    else
    {
        std::this_thread::sleep_for(std::chrono::milliseconds(800));
    }
    Envelope request;
    request.sequence = 1;
    request.kind = "device.request";
    request.deviceId = "simulation-1";
    request.operation = "read";
    request.correlationId = "smoke-request-1";
    if (externalGateway)
    {
        // Endpoint discovery is asynchronous. Repeat the idempotent read request
        // until the gateway's request reader and response writer are both matched.
        for (int attempt = 0; attempt < 12; ++attempt)
        {
            runtime.publish(DeviceBridge::RequestTopic, request);
            std::unique_lock<std::mutex> lock(mutex);
            if (changed.wait_for(lock, std::chrono::milliseconds(500),
                                 [&] { return responseReceived; }))
                break;
        }
    }
    else
    {
        runtime.publish(DeviceBridge::RequestTopic, request);
    }
    std::cerr << "SMOKE_STAGE request-published\n";

    {
        std::unique_lock<std::mutex> lock(mutex);
        const int requiredStates = externalGateway ? 1 : 2;
        changed.wait_for(lock, std::chrono::seconds(8),
                         [&] { return stateCount >= requiredStates && responseReceived; });
    }

    if (bridge)
    {
        bridge->stop();
        std::cerr << "SMOKE_STAGE bridge-stopped\n";
    }
    runtime.stop();
    std::cerr << "SMOKE_STAGE runtime-stopped\n";

    if (stateCount < (externalGateway ? 1 : 2))
    {
        std::cerr << "FAST_DDS_DEVICE_SMOKE_FAIL stateCount=" << stateCount << '\n';
        return 2;
    }
    if (!responseReceived)
    {
        std::cerr << "FAST_DDS_DEVICE_SMOKE_FAIL no response\n";
        return 3;
    }

    std::cout << (externalGateway ? "FAST_DDS_DEVICE_GATEWAY_PROBE_PASS"
                                 : "FAST_DDS_DEVICE_SMOKE_PASS")
              << " states=" << stateCount
              << " response=" << responsePayload << '\n';
    return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << "FAST_DDS_DEVICE_SMOKE_EXCEPTION " << exception.what() << '\n';
        return 10;
    }
}
