#include "PocoDDS/Devices/CanSignalSensor.h"
#include "PocoDDS/Protocols/CAN/LoopbackCanEndpoint.h"

#include "Poco/Thread.h"

#include <atomic>
#include <chrono>
#include <cmath>
#include <iostream>
#include <memory>
#include <stdexcept>

int main()
{
    using namespace std::chrono_literals;
    PocoDDS::Devices::CanSignalSensor::Options options;
    options.id = "can-recovery";
    options.frameId = 0x123;
    options.bitLength = 16;
    options.factor = 0.1;
    auto endpoint =
        std::make_shared<PocoDDS::Protocols::CAN::LoopbackCanEndpoint>("recovery");
    PocoDDS::Devices::CanRecoveryPolicy policy;
    policy.reconnectDelay = 1ms;
    policy.receiveTimeout = 5ms;
    policy.staleAfter = 30ms;
    PocoDDS::Devices::CanSignalSensor sensor(options, endpoint, policy);
    std::atomic_uint snapshots{0};
    std::atomic_uint values{0};
    sensor.setSnapshotHandler([&](const auto&) { ++snapshots; });
    sensor.setValueHandler([&](double) {
        ++values;
        throw std::runtime_error("injected value consumer failure");
    });
    sensor.start();

    PocoDDS::Protocols::CAN::CanFrame ignored;
    ignored.id = 0x124;
    ignored.length = 2;
    endpoint->send(ignored);
    Poco::Thread::sleep(10);
    if (sensor.snapshot().state != PocoDDS::Devices::DeviceState::offline)
        return 1;

    PocoDDS::Protocols::CAN::CanFrame frame;
    frame.id = 0x123;
    frame.length = 2;
    frame.data[0] = 0xD2;
    frame.data[1] = 0x04;
    endpoint->send(frame);
    for (int wait = 0; wait < 100 && values == 0; ++wait)
        Poco::Thread::sleep(2);
    if (values != 1 || std::abs(sensor.value() - 123.4) > 0.0001 ||
        sensor.snapshot().state != PocoDDS::Devices::DeviceState::ready)
        return 2;

    endpoint->injectError(0x40);
    for (int wait = 0; wait < 100 && sensor.diagnostics().reconnectAttempts == 0; ++wait)
        Poco::Thread::sleep(2);
    if (sensor.diagnostics().reconnectAttempts != 1 || !endpoint->isOpen())
        return 3;
    endpoint->send(frame);
    for (int wait = 0; wait < 100 && values < 2; ++wait)
        Poco::Thread::sleep(2);
    const auto recovered = sensor.diagnostics();
    if (values != 2 || sensor.snapshot().state != PocoDDS::Devices::DeviceState::ready ||
        recovered.successfulOperations != 2 || recovered.failedOperations != 1 ||
        recovered.consecutiveFailures != 0)
        return 4;

    for (int wait = 0; wait < 100 &&
         sensor.snapshot().state == PocoDDS::Devices::DeviceState::ready; ++wait)
        Poco::Thread::sleep(2);
    const auto stale = sensor.snapshot();
    const auto diagnostics = sensor.diagnostics();
    const auto failure = sensor.failure();
    sensor.stop();
    if (stale.state != PocoDDS::Devices::DeviceState::offline ||
        diagnostics.failedOperations != 2 || diagnostics.consecutiveFailures != 1 ||
        diagnostics.lastError != "CAN signal stale" ||
        failure.code != "PDR-DEVICE-CAN-SIGNAL_STALE" ||
        !failure.active || !failure.retryable ||
        failure.occurredAtMicroseconds <= 0 || snapshots < 6)
    {
        std::cerr << "CAN_RECOVERY_FAIL state=" << PocoDDS::Devices::toString(stale.state)
                  << " success=" << diagnostics.successfulOperations
                  << " failures=" << diagnostics.failedOperations
                  << " reconnects=" << diagnostics.reconnectAttempts << '\n';
        return 5;
    }
    std::cout << "CAN_RECOVERY_PASS bus-error=1 reconnect=1 stale=1\n";
    return 0;
}
