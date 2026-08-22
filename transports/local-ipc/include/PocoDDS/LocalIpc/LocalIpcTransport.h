#pragma once

#include "PocoDDS/LocalIpc/Export.h"
#include "PocoDDS/RuntimeCore/InProcessTransport.h"

#include <chrono>
#include <memory>
#include <string>

namespace PocoDDS::LocalIpc
{

enum class EndpointRole
{
    server,
    client
};

struct LocalIpcOptions
{
    std::string endpoint;
    EndpointRole role{EndpointRole::client};
    std::string authenticationToken;
    std::size_t maximumFrameBytes{16U * 1024U * 1024U};
    std::chrono::milliseconds connectTimeout{3000};
};

class PDR_LOCAL_IPC_API LocalIpcTransport final : public PocoDDS::RuntimeCore::IMessageTransport
{
  public:
    explicit LocalIpcTransport(LocalIpcOptions options);
    ~LocalIpcTransport() override;

    LocalIpcTransport(const LocalIpcTransport&) = delete;
    LocalIpcTransport& operator=(const LocalIpcTransport&) = delete;

    PocoDDS::RuntimeCore::Outcome<void> start();
    void stop() noexcept;
    bool running() const noexcept;
    std::size_t peerCount() const noexcept;

    std::string id() const override;
    PocoDDS::RuntimeCore::TransportCapabilities capabilities() const noexcept override;
    PocoDDS::RuntimeCore::Subscription subscribe(const PocoDDS::RuntimeCore::TopicSpec& topic,
                                                 Handler handler) override;
    PocoDDS::RuntimeCore::PublishResult
    publish(const PocoDDS::RuntimeCore::TopicSpec& topic,
            const PocoDDS::RuntimeCore::Message& message) override;

  private:
    struct State;
    std::shared_ptr<State> _state;
};

} // namespace PocoDDS::LocalIpc
