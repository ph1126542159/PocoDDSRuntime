#pragma once

#include "PocoDDS/DDS/Envelope.h"

#include <functional>
#include <memory>
#include <string>

namespace PocoDDS::FastDDS
{
class Runtime
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

    void preparePublisher(const std::string& topic);
    void publish(const std::string& topic, const Envelope& envelope);
    void subscribe(const std::string& topic, Handler handler);

private:
    class Impl;
    std::unique_ptr<Impl> _impl;
};
} // namespace PocoDDS::FastDDS
