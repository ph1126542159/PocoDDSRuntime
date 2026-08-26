#include "PocoDDS/DDS/Runtime.h"

#include "PocoDDS/DDS/EnvelopeTopicDataType.h"

#include "Poco/DigestEngine.h"
#include "Poco/SHA2Engine.h"

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
#include <fastdds/rtps/common/Locator.hpp>
#include <fastdds/rtps/transport/UDPv4TransportDescriptor.hpp>
#include <fastdds/rtps/transport/shared_mem/SharedMemTransportDescriptor.hpp>
#include <fastdds/utils/IPLocator.hpp>

#include <algorithm>
#include <array>
#include <charconv>
#include <cctype>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <map>
#include <chrono>
#include <mutex>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string_view>
#include <utility>
#include <vector>

namespace PocoDDS::FastDDS
{
using namespace eprosima::fastdds::dds;
namespace
{
constexpr const char* deploymentProfileEnvironment = "PDR_FASTDDS_PROFILE";
constexpr const char* deploymentProfileSha256Environment = "PDR_FASTDDS_PROFILE_SHA256";
constexpr std::size_t maximumDeploymentProfileBytes = 64U * 1024U;
constexpr std::array<std::string_view, 6> deploymentKeys{
    "profileVersion", "interfaceWhitelist", "initialPeers", "avoidBuiltinMulticast",
    "sharedMemory", "maxInitialPeersRange"};

struct DeploymentPeer
{
    std::string address;
    std::uint16_t port{0};
};

struct DeploymentProfile
{
    std::vector<std::string> interfaceWhitelist;
    std::vector<DeploymentPeer> initialPeers;
    bool avoidBuiltinMulticast{false};
    bool sharedMemory{false};
    std::uint32_t maxInitialPeersRange{4};
    bool configured{false};
    bool digestBound{false};

    std::string summary() const
    {
        if (!configured)
            return "Fast DDS defaults";
        const auto discovery = initialPeers.empty()
                                   ? "multicast"
                                   : (avoidBuiltinMulticast ? "initial-peers"
                                                            : "multicast+initial-peers");
        return "deployment-file;discovery=" + std::string(discovery) +
               ";interfaces=" + std::to_string(interfaceWhitelist.size()) +
               ";peers=" + std::to_string(initialPeers.size()) +
               ";range=" + std::to_string(maxInitialPeersRange) +
               (digestBound ? ";integrity=sha256" : "");
    }
};

std::string trim(std::string value)
{
    const auto first = std::find_if_not(value.begin(), value.end(),
                                        [](unsigned char character) { return std::isspace(character); });
    const auto last = std::find_if_not(value.rbegin(), value.rend(),
                                       [](unsigned char character) { return std::isspace(character); })
                          .base();
    if (first >= last)
        return {};
    return std::string(first, last);
}

std::uint64_t parseUnsigned(const std::string& value, const char* key,
                            std::uint64_t minimum, std::uint64_t maximum)
{
    std::uint64_t parsed = 0;
    const auto* begin = value.data();
    const auto* end = begin + value.size();
    const auto conversion = std::from_chars(begin, end, parsed);
    if (conversion.ec != std::errc{} || conversion.ptr != end || parsed < minimum ||
        parsed > maximum)
        throw std::invalid_argument(std::string(key) + " must be in range " +
                                    std::to_string(minimum) + ".." +
                                    std::to_string(maximum));
    return parsed;
}

bool parseBoolean(const std::string& value, const char* key)
{
    if (value == "true")
        return true;
    if (value == "false")
        return false;
    throw std::invalid_argument(std::string(key) + " must be 'true' or 'false'");
}

std::vector<std::string> parseList(const std::string& value, const char* key)
{
    if (trim(value).empty())
        return {};
    std::vector<std::string> result;
    std::size_t begin = 0;
    while (begin <= value.size())
    {
        const auto separator = value.find(',', begin);
        auto item = trim(value.substr(begin, separator == std::string::npos
                                                ? std::string::npos
                                                : separator - begin));
        if (item.empty())
            throw std::invalid_argument(std::string(key) + " contains an empty entry");
        result.push_back(std::move(item));
        if (separator == std::string::npos)
            break;
        begin = separator + 1;
    }
    return result;
}

DeploymentPeer parsePeer(const std::string& value)
{
    const auto separator = value.find(':');
    if (separator != std::string::npos && value.find(':', separator + 1) != std::string::npos)
        throw std::invalid_argument("initialPeers supports IPv4 addresses only");
    DeploymentPeer peer;
    peer.address = trim(value.substr(0, separator));
    if (peer.address.empty())
        throw std::invalid_argument("initialPeers contains an empty address");
    eprosima::fastdds::rtps::Locator_t locator;
    locator.kind = LOCATOR_KIND_UDPv4;
    if (!eprosima::fastdds::rtps::IPLocator::setIPv4(locator, peer.address))
        throw std::invalid_argument("invalid initial peer IPv4 address: " + peer.address);
    if (separator != std::string::npos)
    {
        const auto port = trim(value.substr(separator + 1));
        peer.port = static_cast<std::uint16_t>(
            parseUnsigned(port, "initial peer port", 1, 65535));
    }
    return peer;
}

std::optional<std::string> environmentValue(const char* name)
{
#if defined(_WIN32)
    char* value = nullptr;
    std::size_t size = 0;
    if (_dupenv_s(&value, &size, name) != 0)
        throw std::runtime_error("cannot read Fast DDS deployment environment");
    const std::unique_ptr<char, decltype(&std::free)> holder(value, &std::free);
    if (size == 0)
        return std::nullopt;
    return std::string(value);
#else
    if (const char* value = std::getenv(name))
        return std::string(value);
    return std::nullopt;
#endif
}

std::string readDeploymentProfile(const std::filesystem::path& path)
{
    std::ifstream input(path, std::ios::binary);
    if (!input)
        throw std::invalid_argument("cannot open Fast DDS deployment profile: " + path.string());
    std::string content;
    std::array<char, 4096> buffer{};
    while (input)
    {
        input.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
        const auto count = input.gcount();
        if (count > 0)
        {
            if (content.size() + static_cast<std::size_t>(count) >
                maximumDeploymentProfileBytes)
                throw std::invalid_argument(
                    "Fast DDS deployment profile exceeds 65536 bytes");
            content.append(buffer.data(), static_cast<std::size_t>(count));
        }
    }
    if (input.bad())
        throw std::invalid_argument("cannot read Fast DDS deployment profile");
    return content;
}

std::string sha256(const std::string& content)
{
    Poco::SHA2Engine engine(Poco::SHA2Engine::SHA_256);
    engine.update(content);
    return Poco::DigestEngine::digestToHex(engine.digest());
}

bool canonicalSha256(const std::string& value)
{
    return value.size() == 64 &&
           std::all_of(value.begin(), value.end(), [](unsigned char character)
           {
               return (character >= '0' && character <= '9') ||
                      (character >= 'a' && character <= 'f');
           });
}

DeploymentProfile loadDeploymentProfile()
{
    const auto configuredPath = environmentValue(deploymentProfileEnvironment);
    const auto expectedSha256 = environmentValue(deploymentProfileSha256Environment);
    if (!configuredPath)
    {
        if (expectedSha256)
            throw std::invalid_argument(
                "PDR_FASTDDS_PROFILE_SHA256 requires PDR_FASTDDS_PROFILE");
        return {};
    }
    if (configuredPath->empty())
        throw std::invalid_argument("PDR_FASTDDS_PROFILE cannot be empty");
    const std::filesystem::path path(*configuredPath);
    const std::string content = readDeploymentProfile(path);
    if (expectedSha256)
    {
        if (!canonicalSha256(*expectedSha256))
            throw std::invalid_argument(
                "PDR_FASTDDS_PROFILE_SHA256 must be 64 lowercase hexadecimal characters");
        if (sha256(content) != *expectedSha256)
            throw std::invalid_argument("Fast DDS deployment profile SHA-256 mismatch");
    }

    std::map<std::string, std::string> values;
    std::istringstream input(content);
    std::string line;
    std::size_t lineNumber = 0;
    while (std::getline(input, line))
    {
        ++lineNumber;
        const auto lineContent = trim(line);
        if (lineContent.empty() || lineContent.front() == '#' || lineContent.front() == ';')
            continue;
        const auto separator = lineContent.find('=');
        if (separator == std::string::npos)
            throw std::invalid_argument("invalid Fast DDS deployment profile line " +
                                        std::to_string(lineNumber));
        const auto key = trim(lineContent.substr(0, separator));
        const auto value = trim(lineContent.substr(separator + 1));
        if (std::find(deploymentKeys.begin(), deploymentKeys.end(), key) ==
            deploymentKeys.end())
            throw std::invalid_argument("unknown Fast DDS deployment profile key: " + key);
        if (!values.emplace(key, value).second)
            throw std::invalid_argument("duplicate Fast DDS deployment profile key: " + key);
    }
    const auto version = values.find("profileVersion");
    if (version == values.end() || version->second != "1")
        throw std::invalid_argument("Fast DDS deployment profileVersion must be '1'");

    DeploymentProfile profile;
    profile.configured = true;
    profile.digestBound = expectedSha256.has_value();
    if (const auto interfaces = values.find("interfaceWhitelist"); interfaces != values.end())
        profile.interfaceWhitelist = parseList(interfaces->second, "interfaceWhitelist");
    if (const auto peers = values.find("initialPeers"); peers != values.end())
    {
        for (const auto& peer : parseList(peers->second, "initialPeers"))
            profile.initialPeers.push_back(parsePeer(peer));
    }
    if (const auto multicast = values.find("avoidBuiltinMulticast"); multicast != values.end())
        profile.avoidBuiltinMulticast =
            parseBoolean(multicast->second, "avoidBuiltinMulticast");
    if (const auto sharedMemory = values.find("sharedMemory"); sharedMemory != values.end())
        profile.sharedMemory = parseBoolean(sharedMemory->second, "sharedMemory");
    if (const auto range = values.find("maxInitialPeersRange"); range != values.end())
        profile.maxInitialPeersRange = static_cast<std::uint32_t>(
            parseUnsigned(range->second, "maxInitialPeersRange", 1, 32));
    if (profile.avoidBuiltinMulticast && profile.initialPeers.empty())
        throw std::invalid_argument(
            "initialPeers are required when builtin multicast is disabled");
    return profile;
}
} // namespace

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

    Impl(std::uint32_t valueDomainId, std::string valueParticipantName)
        : deployment(loadDeploymentProfile()), domainId(valueDomainId),
          participantName(std::move(valueParticipantName)),
          envelopeType(new EnvelopeTopicDataType)
    {
        if (domainId > 232)
            throw std::invalid_argument("Fast DDS domainId must be in range 0..232");
        if (participantName.empty())
            throw std::invalid_argument("Fast DDS participant name cannot be empty");
        std::lock_guard<std::mutex> lock(registryMutex);
        registry.insert(this);
    }

    ~Impl()
    {
        {
            std::lock_guard<std::mutex> lock(registryMutex);
            registry.erase(this);
        }
        stop();
    }

    RuntimeSnapshot snapshot() const
    {
        std::lock_guard<std::mutex> lock(mutex);
        RuntimeSnapshot result;
        result.domainId = domainId;
        result.participantName = participantName;
        result.started = participant != nullptr;
        result.topicCount = topics.size();
        result.writerCount = writers.size();
        result.readerCount = readers.size();
        result.transport = deployment.sharedMemory ? "UDPv4+SHM" : "UDPv4";
        result.qosProfile = deployment.summary();
        for (const auto& item : topics) result.topics.push_back(item.first);
        return result;
    }

    static std::vector<RuntimeSnapshot> snapshots()
    {
        std::lock_guard<std::mutex> lock(registryMutex);
        std::vector<RuntimeSnapshot> result;
        result.reserve(registry.size());
        for (const auto* runtime : registry) result.push_back(runtime->snapshot());
        return result;
    }

    void start()
    {
        std::lock_guard<std::mutex> lock(mutex);
        if (participant)
            return;

        DomainParticipantQos qos = PARTICIPANT_QOS_DEFAULT;
        qos.name(participantName);
        qos.transport().use_builtin_transports = false;
        auto udp = std::make_shared<eprosima::fastdds::rtps::UDPv4TransportDescriptor>();
        udp->interfaceWhiteList = deployment.interfaceWhitelist;
        udp->maxInitialPeersRange = deployment.maxInitialPeersRange;
        qos.transport().user_transports.push_back(std::move(udp));
        if (deployment.sharedMemory)
            qos.transport().user_transports.push_back(
                std::make_shared<eprosima::fastdds::rtps::SharedMemTransportDescriptor>());
        qos.wire_protocol().builtin.avoid_builtin_multicast = deployment.avoidBuiltinMulticast;
        for (const auto& peer : deployment.initialPeers)
        {
            eprosima::fastdds::rtps::Locator_t locator;
            locator.kind = LOCATOR_KIND_UDPv4;
            locator.port = peer.port;
            if (!eprosima::fastdds::rtps::IPLocator::setIPv4(locator, peer.address))
                throw std::invalid_argument("invalid Fast DDS initial peer IPv4 address: " +
                                            peer.address);
            qos.wire_protocol().builtin.initialPeersList.push_back(locator);
        }
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
    const DeploymentProfile deployment;
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
    static std::mutex registryMutex;
    static std::set<Impl*> registry;
};

std::mutex Runtime::Impl::registryMutex;
std::set<Runtime::Impl*> Runtime::Impl::registry;

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

std::vector<RuntimeSnapshot> Runtime::snapshots()
{
    return Impl::snapshots();
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
