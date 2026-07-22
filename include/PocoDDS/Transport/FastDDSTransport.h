#pragma once

#include "PocoDDS/Transport/ITransport.h"

#include <chrono>
#include <cstdint>
#include <memory>
#include <string>

namespace PocoDDS::Transport
{
enum class FastDDSTransportMode
{
    Automatic,
    SharedMemoryOnly,
    NetworkOnly
};

struct FastDDSOptions
{
    std::uint32_t domainId{0};
    std::string participantName{"PocoDDSRuntime"};
    FastDDSTransportMode mode{FastDDSTransportMode::Automatic};
};

class FastDDSTransport final : public ITransport
{
  public:
    class Impl;

    explicit FastDDSTransport(FastDDSOptions options = {});
    ~FastDDSTransport() override;

    FastDDSTransport(const FastDDSTransport&) = delete;
    FastDDSTransport& operator=(const FastDDSTransport&) = delete;

    void publish(const Message& message) override;
    std::unique_ptr<Subscription> subscribe(const std::string& topic, Handler handler) override;
    bool waitForPeer(std::chrono::milliseconds timeout) const;

  private:
    std::unique_ptr<Impl> _impl;
};
} // namespace PocoDDS::Transport
