#pragma once

#include "PocoDDS/RuntimeCore/Executor.h"
#include "PocoDDS/RuntimeCore/Transport.h"

#include <future>
#include <memory>

namespace PocoDDS::RuntimeCore
{

struct AsyncPublishTicket
{
    SubmitStatus submission{SubmitStatus::rejected};
    std::future<Outcome<PublishResult>> completion;

    bool accepted() const noexcept
    {
        return submission == SubmitStatus::accepted ||
               submission == SubmitStatus::acceptedAfterDroppingOldest;
    }
};

class PDR_RUNTIME_CORE_API IAsyncMessageTransport
{
  public:
    virtual ~IAsyncMessageTransport() = default;
    virtual AsyncPublishTicket publishAsync(const TopicSpec& topic, const Message& message) = 0;
};

class PDR_RUNTIME_CORE_API InProcessTransport final : public IMessageTransport,
                                                      public IAsyncMessageTransport
{
  public:
    InProcessTransport();
    explicit InProcessTransport(std::shared_ptr<IExecutor> executor);
    ~InProcessTransport() override;

    InProcessTransport(const InProcessTransport&) = delete;
    InProcessTransport& operator=(const InProcessTransport&) = delete;

    std::string id() const override;
    TransportCapabilities capabilities() const noexcept override;
    Subscription subscribe(const TopicSpec& topic, Handler handler) override;
    PublishResult publish(const TopicSpec& topic, const Message& message) override;
    AsyncPublishTicket publishAsync(const TopicSpec& topic, const Message& message) override;
    std::size_t subscriptionCount() const noexcept;

  private:
    struct State;
    static PublishResult dispatch(const std::shared_ptr<State>& state, const TopicSpec& topic,
                                  const Message& message);
    std::shared_ptr<State> _state;
    std::shared_ptr<IExecutor> _executor;
};

} // namespace PocoDDS::RuntimeCore
