#include "PocoDDS/DDS/Runtime.h"

#include "PocoDDS/DDS/EnvelopeTopicDataType.h"

#if defined(PDR_ENABLE_OBSERVABILITY)
#include "PocoDDS/Observability/Metrics.h"
#endif

#include <fastdds/dds/core/ReturnCode.hpp>
#include <fastdds/dds/core/status/StatusMask.hpp>
#include <fastdds/dds/domain/DomainParticipant.hpp>
#include <fastdds/dds/domain/DomainParticipantFactory.hpp>
#include <fastdds/dds/domain/qos/DomainParticipantQos.hpp>
#include <fastdds/dds/publisher/DataWriter.hpp>
#include <fastdds/dds/publisher/Publisher.hpp>
#include <fastdds/dds/subscriber/DataReader.hpp>
#include <fastdds/dds/subscriber/DataReaderListener.hpp>
#include <fastdds/dds/subscriber/SampleInfo.hpp>
#include <fastdds/dds/subscriber/Subscriber.hpp>
#include <fastdds/dds/topic/Topic.hpp>
#include <fastdds/dds/topic/TypeSupport.hpp>
#include <fastdds/rtps/transport/UDPv4TransportDescriptor.hpp>

#include <map>
#include <chrono>
#include <mutex>
#include <stdexcept>
#include <utility>
#include <vector>

namespace PocoDDS::FastDDS
{
using namespace eprosima::fastdds::dds;

class Runtime::Impl
{
public:
    class ReaderListener final : public DataReaderListener
    {
    public:
        ReaderListener(std::string topicName, Handler handler)
            : _topicName(std::move(topicName)), _handler(std::move(handler)) {}

        void on_data_available(DataReader* reader) override
        {
            Envelope envelope;
            SampleInfo info;
            while (reader->take_next_sample(&envelope, &info) == RETCODE_OK)
            {
                if (info.valid_data)
                {
#if defined(PDR_ENABLE_OBSERVABILITY)
                    PocoDDS::Observability::Metrics::global().addCounter(
                        "pdr.dds.messages.received", 1, {{"topic", _topicName}},
                        "Fast DDS samples received", "{message}");
#endif
                    try
                    {
                        _handler(envelope);
                    }
                    catch (...)
                    {
#if defined(PDR_ENABLE_OBSERVABILITY)
                        PocoDDS::Observability::Metrics::global().addCounter(
                            "pdr.dds.handler.errors", 1, {{"topic", _topicName}},
                            "Exceptions rejected at the DDS listener boundary", "{error}");
#endif
                        // Exceptions must never escape into a Fast DDS listener thread.
                        // The caller may report a protocol-level error on a later request.
                    }
                }
            }
        }

    private:
        std::string _topicName;
        Handler _handler;
    };

    Impl(std::uint32_t domainId, std::string participantName)
        : domainId(domainId), participantName(std::move(participantName)),
          envelopeType(new EnvelopeTopicDataType)
    {
    }

    ~Impl()
    {
        stop();
    }

    void start()
    {
        std::lock_guard<std::mutex> lock(mutex);
        if (participant)
            return;

        DomainParticipantQos qos = PARTICIPANT_QOS_DEFAULT;
        qos.name(participantName);
        qos.transport().use_builtin_transports = false;
        qos.transport().user_transports.push_back(
            std::make_shared<eprosima::fastdds::rtps::UDPv4TransportDescriptor>());
        participant = DomainParticipantFactory::get_instance()->create_participant(domainId, qos);
        if (!participant)
            throw std::runtime_error("Fast DDS failed to create DomainParticipant");

        if (envelopeType.register_type(participant) != RETCODE_OK)
        {
            stopUnlocked();
            throw std::runtime_error("Fast DDS failed to register Envelope type");
        }

        publisher = participant->create_publisher(PUBLISHER_QOS_DEFAULT);
        subscriber = participant->create_subscriber(SUBSCRIBER_QOS_DEFAULT);
        if (!publisher || !subscriber)
        {
            stopUnlocked();
            throw std::runtime_error("Fast DDS failed to create publisher/subscriber");
        }
#if defined(PDR_ENABLE_OBSERVABILITY)
        PocoDDS::Observability::Metrics::global().addCounter(
            "pdr.dds.runtime.starts", 1, {{"participant", participantName}},
            "Fast DDS runtime starts", "{start}");
#endif
    }

    void stop() noexcept
    {
        std::lock_guard<std::mutex> lock(mutex);
        stopUnlocked();
    }

    bool started() const noexcept
    {
        std::lock_guard<std::mutex> lock(mutex);
        return participant != nullptr;
    }

    Topic* topic(const std::string& topicName)
    {
        auto found = topics.find(topicName);
        if (found != topics.end())
            return found->second;
        Topic* created =
            participant->create_topic(topicName, envelopeType.get_type_name(), TOPIC_QOS_DEFAULT);
        if (!created)
            throw std::runtime_error("Fast DDS failed to create topic: " + topicName);
        topics.emplace(topicName, created);
        return created;
    }

    void publish(const std::string& topicName, const Envelope& envelope)
    {
#if defined(PDR_ENABLE_OBSERVABILITY)
        const auto startedAt = std::chrono::steady_clock::now();
#endif
        preparePublisher(topicName);
        DataWriter* writer = nullptr;
        {
            std::lock_guard<std::mutex> lock(mutex);
            writer = writers.at(topicName);
        }

        // Fast DDS can synchronously dispatch a local reader callback from write().
        // Never hold the runtime mutex here: request handlers are allowed to publish
        // their response immediately on another topic.
        Envelope copy = envelope;
        if (writer->write(&copy) != RETCODE_OK)
        {
#if defined(PDR_ENABLE_OBSERVABILITY)
            PocoDDS::Observability::Metrics::global().addCounter(
                "pdr.dds.publish.errors", 1, {{"topic", topicName}},
                "Fast DDS write failures", "{error}");
#endif
            throw std::runtime_error("Fast DDS failed to write topic: " + topicName);
        }
#if defined(PDR_ENABLE_OBSERVABILITY)
        auto& metrics = PocoDDS::Observability::Metrics::global();
        metrics.addCounter("pdr.dds.messages.published", 1, {{"topic", topicName}},
                           "Fast DDS samples published", "{message}");
        metrics.recordHistogram(
            "pdr.dds.publish.duration", std::chrono::duration<double, std::milli>(
                std::chrono::steady_clock::now() - startedAt).count(),
            {{"topic", topicName}}, "Synchronous Fast DDS publish duration", "ms");
#endif
    }

    void preparePublisher(const std::string& topicName)
    {
        std::lock_guard<std::mutex> lock(mutex);
        requireStarted();
        DataWriter*& writer = writers[topicName];
        if (!writer)
        {
            writer = publisher->create_datawriter(topic(topicName), DATAWRITER_QOS_DEFAULT);
            if (!writer)
                throw std::runtime_error("Fast DDS failed to create writer: " + topicName);
        }
    }

    void subscribe(const std::string& topicName, Handler handler)
    {
        std::lock_guard<std::mutex> lock(mutex);
        requireStarted();
        auto listener = std::make_unique<ReaderListener>(topicName, std::move(handler));
        DataReader* reader = subscriber->create_datareader(
            topic(topicName), DATAREADER_QOS_DEFAULT, listener.get(), StatusMask::data_available());
        if (!reader)
            throw std::runtime_error("Fast DDS failed to create reader: " + topicName);
        readers.push_back(reader);
        listeners.push_back(std::move(listener));
    }

private:
    void requireStarted() const
    {
        if (!participant)
            throw std::logic_error("Fast DDS runtime is not started");
    }

    void stopUnlocked() noexcept
    {
        if (!participant)
            return;
        participant->delete_contained_entities();
        DomainParticipantFactory::get_instance()->delete_participant(participant);
        listeners.clear();
        readers.clear();
        writers.clear();
        topics.clear();
        publisher = nullptr;
        subscriber = nullptr;
        participant = nullptr;
    }

public:
    const std::uint32_t domainId;
    const std::string participantName;
    TypeSupport envelopeType;
    mutable std::mutex mutex;
    DomainParticipant* participant{nullptr};
    Publisher* publisher{nullptr};
    Subscriber* subscriber{nullptr};
    std::map<std::string, Topic*> topics;
    std::map<std::string, DataWriter*> writers;
    std::vector<DataReader*> readers;
    std::vector<std::unique_ptr<ReaderListener>> listeners;
};

Runtime::Runtime(std::uint32_t domainId, std::string participantName)
    : _impl(std::make_unique<Impl>(domainId, std::move(participantName)))
{
}

Runtime::~Runtime() = default;

void Runtime::start()
{
    _impl->start();
}

void Runtime::stop() noexcept
{
    _impl->stop();
}

bool Runtime::started() const noexcept
{
    return _impl->started();
}

void Runtime::preparePublisher(const std::string& topic)
{
    _impl->preparePublisher(topic);
}

void Runtime::publish(const std::string& topic, const Envelope& envelope)
{
    _impl->publish(topic, envelope);
}

void Runtime::subscribe(const std::string& topic, Handler handler)
{
    _impl->subscribe(topic, std::move(handler));
}
} // namespace PocoDDS::FastDDS
