#include "PocoDDS/DDS/DeviceBridge.h"

#include "Poco/Timestamp.h"

#include <exception>

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
}

void DeviceBridge::stop() noexcept
{
    if (!_started.exchange(false))
        return;
    _device.setSnapshotHandler({});
    _device.stop();
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
    _runtime.publish(ResponseTopic, response);
}
} // namespace PocoDDS::FastDDS
