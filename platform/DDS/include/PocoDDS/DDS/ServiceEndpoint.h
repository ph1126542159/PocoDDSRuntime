#pragma once

#include "PocoDDS/DDS/Runtime.h"

#if defined(PDR_ENABLE_OBSERVABILITY)
#include "PocoDDS/Observability/BusinessTracer.h"
#endif

#include <cstdint>
#include <condition_variable>
#include <deque>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <thread>

namespace PocoDDS::FastDDS
{
class ServiceEndpoint
{
public:
    using Handler = std::function<Envelope(const Envelope&)>;

    ServiceEndpoint(std::uint32_t domainId,
                    std::string participantName,
                    std::string requestTopic,
                    std::string responseTopic,
                    std::string eventTopic = {});
    ~ServiceEndpoint();

    ServiceEndpoint(const ServiceEndpoint&) = delete;
    ServiceEndpoint& operator=(const ServiceEndpoint&) = delete;

    void start(Handler handler);
    void stop() noexcept;
    void publishEvent(std::string operation, std::string payload);
    bool started() const noexcept;

private:
    void enqueue(const Envelope& request);
    void run();

    std::unique_ptr<Runtime> _runtime;
    std::string _requestTopic;
    std::string _responseTopic;
    std::string _eventTopic;
    Handler _handler;
    mutable std::mutex _mutex;
    std::condition_variable _condition;
    std::deque<Envelope> _requests;
    std::deque<Envelope> _events;
#if defined(PDR_ENABLE_OBSERVABILITY)
    std::deque<Envelope> _traceEvents;
#endif
    std::map<std::string, Envelope> _responses;
    std::deque<std::string> _responseOrder;
    std::thread _worker;
    bool _stopping{false};
#if defined(PDR_ENABLE_OBSERVABILITY)
    std::unique_ptr<PocoDDS::Observability::BusinessTracer> _tracer;
#endif
};
} // namespace PocoDDS::FastDDS
