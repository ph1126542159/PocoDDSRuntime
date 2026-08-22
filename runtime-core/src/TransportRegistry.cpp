#include "PocoDDS/RuntimeCore/TransportRegistry.h"
#include "PocoDDS/RuntimeCore/InProcessTransport.h"

#include <algorithm>
#include <atomic>
#include <cctype>
#include <mutex>
#include <stdexcept>
#include <utility>

namespace PocoDDS::RuntimeCore
{
namespace
{
RuntimeError registryError(RuntimeErrorCode code, std::string message)
{
    return {code, std::move(message), false};
}

bool validId(const std::string& id)
{
    return !id.empty() && std::all_of(id.begin(), id.end(),
                                      [](unsigned char value)
                                      {
                                          return std::islower(value) || std::isdigit(value) ||
                                                 value == '-' || value == '.';
                                      });
}
} // namespace

TransportRegistration::TransportRegistration(std::function<void()> cancel)
    : _cancel(std::move(cancel))
{
}

TransportRegistration::~TransportRegistration() { reset(); }

TransportRegistration::TransportRegistration(TransportRegistration&& other) noexcept
    : _cancel(std::move(other._cancel))
{
    other._cancel = {};
}

TransportRegistration& TransportRegistration::operator=(TransportRegistration&& other) noexcept
{
    if (this != &other)
    {
        reset();
        _cancel = std::move(other._cancel);
        other._cancel = {};
    }
    return *this;
}

void TransportRegistration::reset() noexcept
{
    if (!_cancel)
        return;
    auto cancel = std::move(_cancel);
    _cancel = {};
    try
    {
        cancel();
    }
    catch (...)
    {
    }
}

TransportRegistration::operator bool() const noexcept { return static_cast<bool>(_cancel); }

struct TransportRegistry::State
{
    struct Entry
    {
        TransportDescriptor descriptor;
        TransportFactory factory;
        std::uint64_t generation{0};
    };

    mutable std::mutex mutex;
    std::unordered_map<std::string, Entry> entries;
    std::atomic<std::uint64_t> nextGeneration{1};
};

TransportRegistry::TransportRegistry() : _state(std::make_shared<State>()) {}

TransportRegistry::~TransportRegistry() = default;

Outcome<TransportRegistration> TransportRegistry::registerFactory(TransportDescriptor descriptor,
                                                                  TransportFactory factory)
{
    if (!validId(descriptor.id))
        return Outcome<TransportRegistration>::failure(
            registryError(RuntimeErrorCode::invalidArgument,
                          "transport id must contain only lowercase letters, digits, '-' or '.'"));
    if (!factory)
        return Outcome<TransportRegistration>::failure(
            registryError(RuntimeErrorCode::invalidArgument, "transport factory cannot be empty"));
    if (descriptor.version.empty())
        return Outcome<TransportRegistration>::failure(
            registryError(RuntimeErrorCode::invalidArgument, "transport version cannot be empty"));

    const auto id = descriptor.id;
    const auto generation = _state->nextGeneration.fetch_add(1, std::memory_order_relaxed);
    {
        std::lock_guard<std::mutex> lock(_state->mutex);
        if (_state->entries.count(id) != 0)
            return Outcome<TransportRegistration>::failure(
                registryError(RuntimeErrorCode::invalidArgument,
                              "transport factory already registered for '" + id + "'"));
        _state->entries.emplace(
            id, State::Entry{std::move(descriptor), std::move(factory), generation});
    }

    std::weak_ptr<State> weak = _state;
    return Outcome<TransportRegistration>::success(TransportRegistration(
        [weak, id, generation]
        {
            const auto state = weak.lock();
            if (!state)
                return;
            std::lock_guard<std::mutex> lock(state->mutex);
            const auto found = state->entries.find(id);
            if (found != state->entries.end() && found->second.generation == generation)
                state->entries.erase(found);
        }));
}

Outcome<std::shared_ptr<IMessageTransport>>
TransportRegistry::create(const std::string& id, const TransportConfiguration& configuration) const
{
    TransportFactory factory;
    {
        std::lock_guard<std::mutex> lock(_state->mutex);
        const auto found = _state->entries.find(id);
        if (found == _state->entries.end())
            return Outcome<std::shared_ptr<IMessageTransport>>::failure(
                registryError(RuntimeErrorCode::unsupported,
                              "transport factory is not registered for '" + id + "'"));
        factory = found->second.factory;
    }
    try
    {
        auto result = factory(configuration);
        if (result && !result.value())
            return Outcome<std::shared_ptr<IMessageTransport>>::failure(
                registryError(RuntimeErrorCode::internalError,
                              "transport factory '" + id + "' returned a null transport"));
        return result;
    }
    catch (const std::exception& exception)
    {
        return Outcome<std::shared_ptr<IMessageTransport>>::failure(
            registryError(RuntimeErrorCode::internalError,
                          "transport factory '" + id + "' threw: " + exception.what()));
    }
    catch (...)
    {
        return Outcome<std::shared_ptr<IMessageTransport>>::failure(
            registryError(RuntimeErrorCode::internalError,
                          "transport factory '" + id + "' threw an unknown exception"));
    }
}

std::vector<TransportDescriptor> TransportRegistry::descriptors() const
{
    std::vector<TransportDescriptor> result;
    {
        std::lock_guard<std::mutex> lock(_state->mutex);
        result.reserve(_state->entries.size());
        for (const auto& [_, entry] : _state->entries)
            result.push_back(entry.descriptor);
    }
    std::sort(result.begin(), result.end(),
              [](const auto& left, const auto& right) { return left.id < right.id; });
    return result;
}

Outcome<TransportRegistration> registerInProcessTransport(ITransportRegistry& registry)
{
    return registry.registerFactory(
        {"inproc", "1.0.0", {true, false, false, false, false, true}, {}},
        [](const TransportConfiguration&)
        {
            return Outcome<std::shared_ptr<IMessageTransport>>::success(
                std::make_shared<InProcessTransport>());
        });
}

} // namespace PocoDDS::RuntimeCore
