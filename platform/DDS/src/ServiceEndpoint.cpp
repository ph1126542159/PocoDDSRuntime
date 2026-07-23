#include "PocoDDS/DDS/ServiceEndpoint.h"

#if defined(PDR_ENABLE_OBSERVABILITY)
#include "PocoDDS/Observability/TraceSerialization.h"
#endif

#include <Poco/Exception.h>
#include <Poco/Timestamp.h>

#include <atomic>
#include <stdexcept>
#include <utility>

namespace PocoDDS::FastDDS
{
namespace
{
#if defined(PDR_ENABLE_OBSERVABILITY)
constexpr const char* TraceSpanTopic = "pdr.observability.span";
#endif

std::int64_t nowMicroseconds()
{
    return Poco::Timestamp().epochMicroseconds();
}

std::string jsonError(const std::string& message)
{
    std::string escaped;
    escaped.reserve(message.size() + 16);
    for (const char ch : message)
    {
        if (ch == '"' || ch == '\\')
            escaped.push_back('\\');
        escaped.push_back(ch);
    }
    return "{\"error\":\"" + escaped + "\"}";
}
} // namespace

ServiceEndpoint::ServiceEndpoint(std::uint32_t domainId,
                                 std::string participantName,
                                 std::string requestTopic,
                                 std::string responseTopic,
                                 std::string eventTopic)
    : _runtime(std::make_unique<Runtime>(domainId, std::move(participantName))),
      _requestTopic(std::move(requestTopic)),
      _responseTopic(std::move(responseTopic)),
      _eventTopic(std::move(eventTopic))
{
#if defined(PDR_ENABLE_OBSERVABILITY)
    PocoDDS::Observability::BusinessTracerOptions options;
    options.bundleName = _requestTopic;
    options.onChanged = [this](const auto& snapshot) {
        Envelope event;
        event.kind = "observability.span";
        event.operation = "upsert";
        event.payload = PocoDDS::Observability::serializeSpanSnapshot(snapshot);
        event.traceParent = snapshot.traceParent;
        event.businessName = snapshot.businessName;
        event.businessInstanceId = snapshot.businessInstanceId;
        {
            std::lock_guard<std::mutex> lock(_mutex);
            if (_stopping)
                return;
            _traceEvents.push_back(std::move(event));
        }
        _condition.notify_one();
    };
    _tracer = std::make_unique<PocoDDS::Observability::BusinessTracer>(
        "FastDDS." + _requestTopic, std::move(options));
#endif
}

ServiceEndpoint::~ServiceEndpoint()
{
    stop();
}

void ServiceEndpoint::start(Handler handler)
{
    if (!handler)
        throw std::invalid_argument("Fast DDS service handler is empty");
    _runtime->start();
    _runtime->preparePublisher(_responseTopic);
#if defined(PDR_ENABLE_OBSERVABILITY)
    _runtime->preparePublisher(TraceSpanTopic);
#endif
    if (!_eventTopic.empty())
        _runtime->preparePublisher(_eventTopic);
    {
        std::lock_guard<std::mutex> lock(_mutex);
        _handler = std::move(handler);
        _stopping = false;
    }
    _worker = std::thread([this] { run(); });
    _runtime->subscribe(
        _requestTopic, [this](const Envelope& request) { enqueue(request); });
}

void ServiceEndpoint::enqueue(const Envelope& request)
{
    {
        std::lock_guard<std::mutex> lock(_mutex);
        if (_stopping)
            return;
        _requests.push_back(request);
    }
    _condition.notify_one();
}

void ServiceEndpoint::run()
{
    for (;;)
    {
        Envelope request;
        Envelope event;
        Envelope cached;
        bool hasEvent = false;
#if defined(PDR_ENABLE_OBSERVABILITY)
        bool hasTraceEvent = false;
#endif
        bool hasCached = false;
        {
            std::unique_lock<std::mutex> lock(_mutex);
            _condition.wait(lock, [this] {
                return _stopping || !_requests.empty() || !_events.empty()
#if defined(PDR_ENABLE_OBSERVABILITY)
                       || !_traceEvents.empty()
#endif
                    ;
            });
            if (_stopping && _requests.empty() && _events.empty()
#if defined(PDR_ENABLE_OBSERVABILITY)
                && _traceEvents.empty()
#endif
            )
                return;
            if (!_requests.empty())
            {
                request = std::move(_requests.front());
                _requests.pop_front();
                const auto found = _responses.find(request.correlationId);
                if (!request.correlationId.empty() && found != _responses.end())
                {
                    cached = found->second;
                    hasCached = true;
                }
            }
            else if (!_events.empty())
            {
                event = std::move(_events.front());
                _events.pop_front();
                hasEvent = true;
            }
#if defined(PDR_ENABLE_OBSERVABILITY)
            else
            {
                event = std::move(_traceEvents.front());
                _traceEvents.pop_front();
                hasTraceEvent = true;
            }
#endif
        }

#if defined(PDR_ENABLE_OBSERVABILITY)
        if (hasTraceEvent)
        {
            try
            {
                _runtime->publish(TraceSpanTopic, event);
            }
            catch (...)
            {
            }
            continue;
        }
#endif

        if (hasEvent)
        {
            try
            {
                _runtime->publish(_eventTopic, event);
            }
            catch (...)
            {
            }
            continue;
        }

        if (hasCached)
        {
            try
            {
                _runtime->publish(_responseTopic, cached);
            }
            catch (...)
            {
            }
            continue;
        }

        Envelope response;
        response.kind = "response";
        response.operation = request.operation;
        response.correlationId = request.correlationId;
        response.timestampMicroseconds = nowMicroseconds();
#if defined(PDR_ENABLE_OBSERVABILITY)
        auto trace = request.traceParent.empty()
                         ? _tracer->startBusiness(
                               request.businessName.empty() ? request.operation
                                                            : request.businessName,
                               {{"request.payload", request.payload}},
                               request.businessInstanceId)
                         : _tracer->continueBusiness(
                               request.businessName.empty() ? request.operation
                                                            : request.businessName,
                               request.operation,
                               request.traceParent,
                               request.businessInstanceId,
                               {{"request.payload", request.payload}});
        response.businessName =
            request.businessName.empty() ? request.operation : request.businessName;
        response.businessInstanceId = trace.businessInstanceId();
        response.traceParent = trace.traceParent();
#endif
        try
        {
            response = _handler(request);
            response.kind = "response";
            response.operation = request.operation;
            response.correlationId = request.correlationId;
            response.timestampMicroseconds = nowMicroseconds();
#if defined(PDR_ENABLE_OBSERVABILITY)
            response.businessName =
                request.businessName.empty() ? request.operation : request.businessName;
            response.businessInstanceId = trace.businessInstanceId();
            response.traceParent = trace.traceParent();
            if (response.status == 0)
                trace.success({{"response.payload", response.payload}});
            else
                trace.failure("service_status_" + std::to_string(response.status),
                              response.payload);
#endif
        }
        catch (const Poco::Exception& exception)
        {
            response.status = 500;
            response.payload = jsonError(exception.displayText());
#if defined(PDR_ENABLE_OBSERVABILITY)
            trace.failure("poco_exception", exception.displayText());
#endif
        }
        catch (const std::exception& exception)
        {
            response.status = 500;
            response.payload = jsonError(exception.what());
#if defined(PDR_ENABLE_OBSERVABILITY)
            trace.failure("std_exception", exception.what());
#endif
        }
        catch (...)
        {
            response.status = 500;
            response.payload = jsonError("unknown service error");
#if defined(PDR_ENABLE_OBSERVABILITY)
            trace.failure("unknown_exception", "unknown service error");
#endif
        }
        if (!request.correlationId.empty())
        {
            std::lock_guard<std::mutex> lock(_mutex);
            _responses[request.correlationId] = response;
            _responseOrder.push_back(request.correlationId);
            while (_responseOrder.size() > 256)
            {
                _responses.erase(_responseOrder.front());
                _responseOrder.pop_front();
            }
        }
        try
        {
            _runtime->publish(_responseTopic, response);
        }
        catch (...)
        {
        }
    }
}

void ServiceEndpoint::stop() noexcept
{
    if (!_runtime)
        return;
    {
        std::lock_guard<std::mutex> lock(_mutex);
        _stopping = true;
    }
    _condition.notify_all();
    if (_worker.joinable())
        _worker.join();
    _runtime->stop();
    std::lock_guard<std::mutex> lock(_mutex);
    _handler = {};
    _requests.clear();
    _events.clear();
#if defined(PDR_ENABLE_OBSERVABILITY)
    _traceEvents.clear();
#endif
    _responses.clear();
    _responseOrder.clear();
}

void ServiceEndpoint::publishEvent(std::string operation, std::string payload)
{
    if (_eventTopic.empty())
        throw std::logic_error("Fast DDS event topic is not configured");
    static std::atomic<std::uint64_t> sequence{0};
    Envelope event;
    event.sequence = ++sequence;
    event.timestampMicroseconds = nowMicroseconds();
    event.kind = "event";
    event.operation = std::move(operation);
    event.payload = std::move(payload);
    {
        std::lock_guard<std::mutex> lock(_mutex);
        if (_stopping || !_runtime->started())
            return;
        _events.push_back(std::move(event));
    }
    _condition.notify_one();
}

bool ServiceEndpoint::started() const noexcept
{
    return _runtime && _runtime->started();
}
} // namespace PocoDDS::FastDDS
