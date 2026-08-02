#include "PocoDDS/DDS/DeviceBridge.h"

#include "Poco/Timestamp.h"

#if defined(PDR_ENABLE_OBSERVABILITY)
#include "PocoDDS/Observability/Metrics.h"
#endif

#include <exception>
#include <chrono>

namespace PocoDDS::FastDDS
{
DeviceBridge::DeviceBridge(Runtime& runtime, PocoDDS::Devices::Device& device)
    : _runtime(runtime), _device(device)
{
}

DeviceBridge::~DeviceBridge()
{
    stop();
}

void DeviceBridge::start()
{
    if (_started.exchange(true))
        return;
    _runtime.preparePublisher(StateTopic);
    _runtime.preparePublisher(ResponseTopic);
    _runtime.subscribe(RequestTopic, [this](const Envelope& request) { handleRequest(request); });
    _device.setSnapshotHandler(
        [this](const PocoDDS::Devices::DeviceSnapshot& snapshot) { publishSnapshot(snapshot); });
    _device.start();
#if defined(PDR_ENABLE_OBSERVABILITY)
    auto& metrics = PocoDDS::Observability::Metrics::global();
    metrics.recordHistogram("pdr.device.online", 1, {{"device.id", _device.id()},
                                              {"device.type", _device.type()}},
                     "Device online state", "1");
    metrics.addCounter("pdr.device.starts", 1, {{"device.type", _device.type()}},
                       "Device starts", "{start}");
#endif
}

void DeviceBridge::stop() noexcept
{
    if (!_started.exchange(false))
        return;
    _device.setSnapshotHandler({});
    _device.stop();
#if defined(PDR_ENABLE_OBSERVABILITY)
    PocoDDS::Observability::Metrics::global().recordHistogram(
        "pdr.device.online", 0, {{"device.id", _device.id()}, {"device.type", _device.type()}},
        "Device online state", "1");
#endif
}

void DeviceBridge::publishSnapshot(const PocoDDS::Devices::DeviceSnapshot& snapshot)
{
    if (!_started)
        return;
    Envelope envelope;
    envelope.sequence = snapshot.sequence;
    envelope.timestampMicroseconds = snapshot.timestampMicroseconds;
    envelope.kind = "device.state";
    envelope.deviceId = snapshot.id;
    envelope.operation = PocoDDS::Devices::toString(snapshot.state);
    envelope.payload = snapshot.payload;
    _runtime.publish(StateTopic, envelope);
}

void DeviceBridge::handleRequest(const Envelope& request)
{
    if (!_started || request.deviceId != _device.id())
        return;

    Envelope response;
    response.sequence = request.sequence;
    response.timestampMicroseconds = Poco::Timestamp().epochMicroseconds();
    response.kind = "device.response";
    response.deviceId = request.deviceId;
    response.operation = request.operation;
    response.correlationId = request.correlationId;
#if defined(PDR_ENABLE_OBSERVABILITY)
    const auto startedAt = std::chrono::steady_clock::now();
#endif
    try
    {
        response.payload = _device.execute(request.operation, request.payload);
        response.status = 0;
    }
    catch (const std::exception& exception)
    {
        response.payload = exception.what();
        response.status = 1;
    }
#if defined(PDR_ENABLE_OBSERVABILITY)
    auto& metrics = PocoDDS::Observability::Metrics::global();
    const std::string result = response.status == 0 ? "success" : "error";
    metrics.addCounter("pdr.device.commands", 1,
                       {{"device.id", _device.id()}, {"device.type", _device.type()},
                        {"operation", request.operation}, {"result", result}},
                       "Device commands completed", "{command}");
    metrics.recordHistogram(
        "pdr.device.command.duration", std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - startedAt).count(),
        {{"device.type", _device.type()}, {"operation", request.operation}},
        "Device command duration", "ms");
#endif
    _runtime.publish(ResponseTopic, response);
}
} // namespace PocoDDS::FastDDS
