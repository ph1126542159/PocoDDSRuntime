#pragma once

#include "PocoDDS/RuntimeCore/Transport.h"

#include <functional>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

namespace PocoDDS::RuntimeCore
{

using TransportConfiguration = std::unordered_map<std::string, std::string>;

struct TransportDescriptor
{
    std::string id;
    std::string version{"1.0.0"};
    TransportCapabilities capabilities;
    std::vector<std::string> configurationKeys;
};

using TransportFactory = std::function<Outcome<std::shared_ptr<IMessageTransport>>(
    const TransportConfiguration& configuration)>;

class PDR_RUNTIME_CORE_API TransportRegistration
{
  public:
    TransportRegistration() = default;
    explicit TransportRegistration(std::function<void()> cancel);
    ~TransportRegistration();

    TransportRegistration(const TransportRegistration&) = delete;
    TransportRegistration& operator=(const TransportRegistration&) = delete;
    TransportRegistration(TransportRegistration&& other) noexcept;
    TransportRegistration& operator=(TransportRegistration&& other) noexcept;

    void reset() noexcept;
    explicit operator bool() const noexcept;

  private:
    std::function<void()> _cancel;
};

class PDR_RUNTIME_CORE_API ITransportRegistry
{
  public:
    virtual ~ITransportRegistry() = default;
    virtual Outcome<TransportRegistration> registerFactory(TransportDescriptor descriptor,
                                                           TransportFactory factory) = 0;
    virtual Outcome<std::shared_ptr<IMessageTransport>>
    create(const std::string& id, const TransportConfiguration& configuration = {}) const = 0;
    virtual std::vector<TransportDescriptor> descriptors() const = 0;
};

class PDR_RUNTIME_CORE_API TransportRegistry final : public ITransportRegistry
{
  public:
    TransportRegistry();
    ~TransportRegistry() override;

    Outcome<TransportRegistration> registerFactory(TransportDescriptor descriptor,
                                                   TransportFactory factory) override;
    Outcome<std::shared_ptr<IMessageTransport>>
    create(const std::string& id, const TransportConfiguration& configuration = {}) const override;
    std::vector<TransportDescriptor> descriptors() const override;

  private:
    struct State;
    std::shared_ptr<State> _state;
};

PDR_RUNTIME_CORE_API Outcome<TransportRegistration>
registerInProcessTransport(ITransportRegistry& registry);

} // namespace PocoDDS::RuntimeCore
