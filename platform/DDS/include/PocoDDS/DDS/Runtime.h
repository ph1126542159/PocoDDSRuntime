#pragma once

#include "PocoDDS/DDS/Envelope.h"

#include <functional>
#include <memory>
#include <string>
#include <vector>

namespace PocoDDS::FastDDS
{
#if defined(_WIN32)
#if defined(PDRFastDDS_EXPORTS)
#define PDR_FASTDDS_RUNTIME_API __declspec(dllexport)
#else
#define PDR_FASTDDS_RUNTIME_API __declspec(dllimport)
#endif
#else
#define PDR_FASTDDS_RUNTIME_API
#endif

struct RuntimeSnapshot
{
    std::uint32_t domainId{0};
    std::string participantName;
    bool started{false};
    std::size_t topicCount{0};
    std::size_t writerCount{0};
    std::size_t readerCount{0};
    std::vector<std::string> topics;
    std::string transport{"UDPv4"};
    std::string qosProfile{"Fast DDS defaults"};
};

#if defined(_MSC_VER)
#pragma warning(push)
#pragma warning(disable: 4251)
#endif
class PDR_FASTDDS_RUNTIME_API Runtime
{
public:
    using Handler = std::function<void(const Envelope&)>;

    explicit Runtime(std::uint32_t domainId = 0, std::string participantName = "pdr-runtime");
    ~Runtime();

    Runtime(const Runtime&) = delete;
    Runtime& operator=(const Runtime&) = delete;

    void start();
    void stop() noexcept;
    bool started() const noexcept;
    static std::vector<RuntimeSnapshot> snapshots();

    void preparePublisher(const std::string& topic);
    void publish(const std::string& topic, const Envelope& envelope);
    void subscribe(const std::string& topic, Handler handler);

private:
    class Impl;
    std::unique_ptr<Impl> _impl;
};
#if defined(_MSC_VER)
#pragma warning(pop)
#endif
} // namespace PocoDDS::FastDDS

#undef PDR_FASTDDS_RUNTIME_API
