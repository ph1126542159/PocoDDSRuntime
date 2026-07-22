#include "PocoDDS/Transport/FastDDSTransport.h"

#include <fastcdr/Cdr.h>
#include <fastcdr/FastBuffer.h>
#include <fastcdr/exceptions/Exception.h>
#include <fastdds/dds/core/status/PublicationMatchedStatus.hpp>
#include <fastdds/dds/core/status/SubscriptionMatchedStatus.hpp>
#include <fastdds/dds/domain/DomainParticipant.hpp>
#include <fastdds/dds/domain/DomainParticipantFactory.hpp>
#include <fastdds/dds/publisher/DataWriter.hpp>
#include <fastdds/dds/publisher/DataWriterListener.hpp>
#include <fastdds/dds/publisher/Publisher.hpp>
#include <fastdds/dds/subscriber/DataReader.hpp>
#include <fastdds/dds/subscriber/DataReaderListener.hpp>
#include <fastdds/dds/subscriber/SampleInfo.hpp>
#include <fastdds/dds/subscriber/Subscriber.hpp>
#include <fastdds/dds/topic/Topic.hpp>
#include <fastdds/dds/topic/TopicDataType.hpp>
#include <fastdds/dds/topic/TypeSupport.hpp>
#include <fastdds/rtps/transport/UDPv4TransportDescriptor.hpp>
#include <fastdds/rtps/transport/shared_mem/SharedMemTransportDescriptor.hpp>

#include <atomic>
#include <condition_variable>
#include <mutex>
#include <stdexcept>
#include <unordered_map>

namespace PocoDDS::Transport
{
namespace
{
using eprosima::fastdds::dds::DataRepresentationId_t;
using eprosima::fastdds::rtps::InstanceHandle_t;
using eprosima::fastdds::rtps::SerializedPayload_t;

struct WireMessage
{
    std::string topic;
    std::string type;
    std::vector<std::uint8_t> payload;
    std::string traceParent;
};

class WireMessageType final : public eprosima::fastdds::dds::TopicDataType
{
  public:
    WireMessageType()
    {
        set_name("PocoDDS::WireMessageV1");
        max_serialized_type_size = 4U * 1024U * 1024U;
        is_compute_key_provided = false;
    }

    bool serialize(const void* const data, SerializedPayload_t& serialized,
                   DataRepresentationId_t representation) override
    {
        const auto* message = static_cast<const WireMessage*>(data);
        eprosima::fastcdr::FastBuffer buffer(reinterpret_cast<char*>(serialized.data),
                                             serialized.max_size);
        eprosima::fastcdr::Cdr serializer(buffer, eprosima::fastcdr::Cdr::DEFAULT_ENDIAN,
                                          representation ==
                                                  DataRepresentationId_t::XCDR_DATA_REPRESENTATION
                                              ? eprosima::fastcdr::CdrVersion::XCDRv1
                                              : eprosima::fastcdr::CdrVersion::XCDRv2);
        serialized.encapsulation =
            serializer.endianness() == eprosima::fastcdr::Cdr::BIG_ENDIANNESS ? CDR_BE : CDR_LE;
        serializer.set_encoding_flag(representation ==
                                             DataRepresentationId_t::XCDR_DATA_REPRESENTATION
                                         ? eprosima::fastcdr::EncodingAlgorithmFlag::PLAIN_CDR
                                         : eprosima::fastcdr::EncodingAlgorithmFlag::DELIMIT_CDR2);
        try
        {
            serializer.serialize_encapsulation();
            serializer << message->topic << message->type << message->payload
                       << message->traceParent;
            serializer.set_dds_cdr_options({0, 0});
            serialized.length = static_cast<std::uint32_t>(serializer.get_serialized_data_length());
            return true;
        }
        catch (const eprosima::fastcdr::exception::Exception&)
        {
            return false;
        }
    }

    bool deserialize(SerializedPayload_t& serialized, void* data) override
    {
        auto* message = static_cast<WireMessage*>(data);
        eprosima::fastcdr::FastBuffer buffer(reinterpret_cast<char*>(serialized.data),
                                             serialized.length);
        eprosima::fastcdr::Cdr deserializer(buffer, eprosima::fastcdr::Cdr::DEFAULT_ENDIAN);
        try
        {
            deserializer.read_encapsulation();
            serialized.encapsulation =
                deserializer.endianness() == eprosima::fastcdr::Cdr::BIG_ENDIANNESS ? CDR_BE
                                                                                    : CDR_LE;
            deserializer >> message->topic >> message->type >> message->payload >>
                message->traceParent;
            return true;
        }
        catch (const eprosima::fastcdr::exception::Exception&)
        {
            return false;
        }
    }

    std::uint32_t calculate_serialized_size(const void* const, DataRepresentationId_t) override
    {
        return max_serialized_type_size;
    }

    void* create_data() override { return new WireMessage; }
    void delete_data(void* data) override { delete static_cast<WireMessage*>(data); }
    bool compute_key(SerializedPayload_t&, InstanceHandle_t&, bool) override { return false; }
    bool compute_key(const void* const, InstanceHandle_t&, bool) override { return false; }
    void register_type_object_representation() override {}
};
} // namespace

class FastDDSTransport::Impl final : public eprosima::fastdds::dds::DataWriterListener,
                                     public eprosima::fastdds::dds::DataReaderListener
{
  public:
    explicit Impl(const FastDDSOptions& options) : _type(new WireMessageType)
    {
        using namespace eprosima::fastdds::dds;
        using namespace eprosima::fastdds::rtps;
        DomainParticipantQos participantQos;
        participantQos.name(options.participantName);
        participantQos.transport().use_builtin_transports = false;
        if (options.mode != FastDDSTransportMode::NetworkOnly)
            participantQos.transport().user_transports.push_back(
                std::make_shared<SharedMemTransportDescriptor>());
        if (options.mode != FastDDSTransportMode::SharedMemoryOnly)
            participantQos.transport().user_transports.push_back(
                std::make_shared<UDPv4TransportDescriptor>());

        _participant = DomainParticipantFactory::get_instance()->create_participant(
            options.domainId, participantQos);
        if (!_participant)
            throw std::runtime_error("Fast-DDS participant creation failed");
        _type.register_type(_participant);
        _topic =
            _participant->create_topic("PocoDDS.Wire.v1", _type.get_type_name(), TOPIC_QOS_DEFAULT);
        _publisher = _participant->create_publisher(PUBLISHER_QOS_DEFAULT, nullptr);
        _subscriber = _participant->create_subscriber(SUBSCRIBER_QOS_DEFAULT, nullptr);
        if (!_topic || !_publisher || !_subscriber)
            fail("Fast-DDS entity creation failed");

        DataWriterQos writerQos;
        _publisher->get_default_datawriter_qos(writerQos);
        writerQos.reliability().kind = RELIABLE_RELIABILITY_QOS;
        _writer = _publisher->create_datawriter(_topic, writerQos, this);
        DataReaderQos readerQos;
        _subscriber->get_default_datareader_qos(readerQos);
        readerQos.reliability().kind = RELIABLE_RELIABILITY_QOS;
        _reader = _subscriber->create_datareader(_topic, readerQos, this);
        if (!_writer || !_reader)
            fail("Fast-DDS endpoint creation failed");
    }

    ~Impl() override
    {
        if (_participant)
            _participant->delete_contained_entities();
        if (_participant)
            eprosima::fastdds::dds::DomainParticipantFactory::get_instance()->delete_participant(
                _participant);
    }

    void publish(const Message& message)
    {
        if (message.payload.size() > 3U * 1024U * 1024U)
            throw std::length_error("Fast-DDS message payload exceeds 3 MiB wire limit");
        WireMessage wire;
        wire.topic = message.topic;
        wire.type = message.type;
        wire.traceParent = message.traceParent;
        wire.payload.reserve(message.payload.size());
        for (const auto value : message.payload)
            wire.payload.push_back(std::to_integer<std::uint8_t>(value));
        if (_writer->write(&wire) != eprosima::fastdds::dds::RETCODE_OK)
            throw std::runtime_error("Fast-DDS write failed");
    }

    std::size_t subscribe(std::string topic, Handler handler)
    {
        std::lock_guard lock(_mutex);
        const auto id = _nextId++;
        _handlers.emplace(id, Entry{std::move(topic), std::move(handler)});
        return id;
    }

    void unsubscribe(std::size_t id)
    {
        std::lock_guard lock(_mutex);
        _handlers.erase(id);
    }

    bool waitForPeer(std::chrono::milliseconds timeout) const
    {
        std::unique_lock lock(_matchMutex);
        return _matchChanged.wait_for(lock, timeout, [&]() { return _matched.load() > 1; });
    }

    void
    on_publication_matched(eprosima::fastdds::dds::DataWriter*,
                           const eprosima::fastdds::dds::PublicationMatchedStatus& status) override
    {
        _matched.store(status.current_count);
        _matchChanged.notify_all();
    }

    void on_data_available(eprosima::fastdds::dds::DataReader* reader) override
    {
        WireMessage wire;
        eprosima::fastdds::dds::SampleInfo info;
        while (reader->take_next_sample(&wire, &info) == eprosima::fastdds::dds::RETCODE_OK)
        {
            if (!info.valid_data)
                continue;
            Message message;
            message.topic = wire.topic;
            message.type = wire.type;
            message.traceParent = wire.traceParent;
            message.payload.reserve(wire.payload.size());
            for (const auto value : wire.payload)
                message.payload.push_back(std::byte(value));
            std::vector<Handler> handlers;
            {
                std::lock_guard lock(_mutex);
                for (const auto& [id, entry] : _handlers)
                {
                    static_cast<void>(id);
                    if (entry.topic == message.topic)
                        handlers.push_back(entry.handler);
                }
            }
            for (const auto& handler : handlers)
                handler(message);
        }
    }

  private:
    struct Entry
    {
        std::string topic;
        Handler handler;
    };

    [[noreturn]] void fail(const char* message)
    {
        if (_participant)
            _participant->delete_contained_entities();
        if (_participant)
            eprosima::fastdds::dds::DomainParticipantFactory::get_instance()->delete_participant(
                _participant);
        _participant = nullptr;
        throw std::runtime_error(message);
    }

    eprosima::fastdds::dds::TypeSupport _type;
    eprosima::fastdds::dds::DomainParticipant* _participant{nullptr};
    eprosima::fastdds::dds::Publisher* _publisher{nullptr};
    eprosima::fastdds::dds::Subscriber* _subscriber{nullptr};
    eprosima::fastdds::dds::Topic* _topic{nullptr};
    eprosima::fastdds::dds::DataWriter* _writer{nullptr};
    eprosima::fastdds::dds::DataReader* _reader{nullptr};
    std::mutex _mutex;
    std::size_t _nextId{1};
    std::unordered_map<std::size_t, Entry> _handlers;
    std::atomic_int _matched{0};
    mutable std::mutex _matchMutex;
    mutable std::condition_variable _matchChanged;
};

namespace
{
class FastDDSSubscription final : public Subscription
{
  public:
    FastDDSSubscription(FastDDSTransport::Impl& owner, std::size_t id) : _owner(owner), _id(id) {}
    ~FastDDSSubscription() override { _owner.unsubscribe(_id); }

  private:
    FastDDSTransport::Impl& _owner;
    std::size_t _id;
};
} // namespace

FastDDSTransport::FastDDSTransport(FastDDSOptions options) : _impl(std::make_unique<Impl>(options))
{
}
FastDDSTransport::~FastDDSTransport() = default;

void FastDDSTransport::publish(const Message& message) { _impl->publish(message); }

std::unique_ptr<Subscription> FastDDSTransport::subscribe(const std::string& topic, Handler handler)
{
    const auto id = _impl->subscribe(topic, std::move(handler));
    return std::make_unique<FastDDSSubscription>(*_impl, id);
}

bool FastDDSTransport::waitForPeer(std::chrono::milliseconds timeout) const
{
    return _impl->waitForPeer(timeout);
}
} // namespace PocoDDS::Transport
