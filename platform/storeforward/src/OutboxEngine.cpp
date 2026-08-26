#include "PocoDDS/StoreForward/OutboxEngine.h"

#include <Poco/Exception.h>
#include <Poco/Timestamp.h>
#include <Poco/UUIDGenerator.h>

#include <algorithm>
#include <limits>
#include <regex>
#include <utility>

namespace PocoDDS::StoreForward
{
namespace
{
Poco::Int64 nowMicroseconds()
{
    return Poco::Timestamp().epochMicroseconds();
}

void validateProviderDescriptor(const ProviderDescriptor& descriptor)
{
    static const std::regex typePattern("^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$");
    if (!std::regex_match(descriptor.type, typePattern))
        throw Poco::InvalidArgumentException(
            "Delivery provider type must be a lower-case kebab-case identifier",
            descriptor.type);
    if (descriptor.version.empty())
        throw Poco::InvalidArgumentException("Delivery provider version is empty");
}
} // namespace

const char* stateName(State state) noexcept
{
    switch (state)
    {
    case State::pending: return "pending";
    case State::delivering: return "delivering";
    case State::delivered: return "delivered";
    case State::deadLetter: return "dead-letter";
    case State::cancelled: return "cancelled";
    }
    return "unknown";
}

State parseState(const std::string& value)
{
    if (value == "pending") return State::pending;
    if (value == "delivering") return State::delivering;
    if (value == "delivered") return State::delivered;
    if (value == "dead-letter") return State::deadLetter;
    if (value == "cancelled") return State::cancelled;
    throw Poco::DataFormatException("Unknown outbox message state", value);
}

bool terminal(State state) noexcept
{
    return state == State::delivered || state == State::deadLetter ||
           state == State::cancelled;
}

OutboxEngine::OutboxEngine(std::unique_ptr<OutboxStore> store, Policy policy, Clock clock)
    : _store(std::move(store)), _policy(std::move(policy)),
      _clock(clock ? std::move(clock) : Clock(nowMicroseconds))
{
    if (!_store) throw Poco::NullPointerException("Outbox store is null");
    if (_policy.maximumActiveMessages == 0)
        throw Poco::InvalidArgumentException("Outbox maximumActiveMessages must be positive");
    if (_policy.maximumPayloadBytes == 0)
        throw Poco::InvalidArgumentException("Outbox maximumPayloadBytes must be positive");
    if (_policy.maximumAttempts == 0)
        throw Poco::InvalidArgumentException("Outbox maximumAttempts must be positive");
    if (_policy.initialRetryDelay.count() < 0 ||
        _policy.maximumRetryDelay < _policy.initialRetryDelay)
        throw Poco::InvalidArgumentException("Outbox retry delay policy is invalid");
    if (_policy.deliveryBatchSize == 0)
        throw Poco::InvalidArgumentException("Outbox deliveryBatchSize must be positive");
    if (_policy.terminalRetention.count() < 0)
        throw Poco::InvalidArgumentException("Outbox terminalRetention is negative");
}

void OutboxEngine::initialize()
{
    std::lock_guard<std::recursive_mutex> lock(_mutex);
    _store->initialize();
    _store->recoverDelivering(_clock());
}

void OutboxEngine::attach(Poco::AutoPtr<DeliveryProviderService> provider)
{
    if (!provider) throw Poco::NullPointerException("Delivery provider service is null");
    auto descriptor = provider->descriptor();
    validateProviderDescriptor(descriptor);
    std::lock_guard<std::recursive_mutex> lock(_mutex);
    if (_providers.find(descriptor.type) != _providers.end())
        throw Poco::ExistsException("Delivery provider is already attached", descriptor.type);
    const std::string type = descriptor.type;
    _providers.emplace(type, AttachedProvider{std::move(descriptor), std::move(provider)});
}

void OutboxEngine::detach(const std::string& type)
{
    std::lock_guard<std::recursive_mutex> lock(_mutex);
    _providers.erase(type);
}

Message OutboxEngine::enqueue(const EnqueueRequest& request)
{
    if (request.provider.empty())
        throw Poco::InvalidArgumentException("Outbox provider is empty");
    if (request.destination.empty())
        throw Poco::InvalidArgumentException("Outbox destination is empty");
    if (request.idempotencyKey.empty())
        throw Poco::InvalidArgumentException("Outbox idempotency key is empty");
    if (request.payload.size() > _policy.maximumPayloadBytes)
        throw Poco::InvalidArgumentException("Outbox payload exceeds the global limit");

    std::lock_guard<std::recursive_mutex> lock(_mutex);
    if (const auto existing =
            _store->findByIdempotencyKey(request.provider, request.idempotencyKey))
        return *existing;
    if (_store->activeCount() >= _policy.maximumActiveMessages)
        throw Poco::OutOfMemoryException("Outbox active-message quota is exhausted");
    const auto provider = _providers.find(request.provider);
    if (provider != _providers.end() &&
        provider->second.descriptor.maximumPayloadBytes > 0 &&
        request.payload.size() > provider->second.descriptor.maximumPayloadBytes)
        throw Poco::InvalidArgumentException("Outbox payload exceeds the provider limit");

    const auto now = _clock();
    if (request.expiresAtMicroseconds > 0 && request.expiresAtMicroseconds <= now)
        throw Poco::InvalidArgumentException("Outbox message is already expired");
    Message message;
    message.id = Poco::UUIDGenerator::defaultGenerator().createRandom().toString();
    message.provider = request.provider;
    message.destination = request.destination;
    message.idempotencyKey = request.idempotencyKey;
    message.orderingKey = request.orderingKey;
    message.payload = request.payload;
    message.nextAttemptMicroseconds = now;
    message.expiresAtMicroseconds = request.expiresAtMicroseconds;
    message.createdMicroseconds = now;
    persist(message);
    return message;
}

Message OutboxEngine::cancel(const std::string& id)
{
    std::lock_guard<std::recursive_mutex> lock(_mutex);
    auto message = requireMessage(id);
    if (message.state != State::pending) return message;
    message.state = State::cancelled;
    message.nextAttemptMicroseconds = 0;
    message.lastErrorCode = "cancelled";
    message.lastErrorMessage = "Message cancelled before delivery";
    persist(message);
    return message;
}

Message OutboxEngine::redrive(const std::string& id)
{
    std::lock_guard<std::recursive_mutex> lock(_mutex);
    auto message = requireMessage(id);
    if (message.state != State::deadLetter)
        throw Poco::IllegalStateException("Only dead-letter messages can be redriven", id);
    if (_store->activeCount() >= _policy.maximumActiveMessages)
        throw Poco::OutOfMemoryException("Outbox active-message quota is exhausted");
    message.state = State::pending;
    message.attempts = 0;
    message.nextAttemptMicroseconds = _clock();
    message.deliveredMicroseconds = 0;
    message.lastErrorCode.clear();
    message.lastErrorMessage.clear();
    persist(message);
    return message;
}

std::size_t OutboxEngine::pump()
{
    std::lock_guard<std::recursive_mutex> lock(_mutex);
    const auto now = _clock();
    auto messages = _store->due(now, _policy.deliveryBatchSize);
    std::size_t processed = 0;
    for (auto& message : messages)
    {
        if (message.expiresAtMicroseconds > 0 && message.expiresAtMicroseconds <= now)
        {
            message.state = State::deadLetter;
            message.nextAttemptMicroseconds = 0;
            message.lastErrorCode = "expired";
            message.lastErrorMessage = "Message expired before acknowledgement";
            persist(message);
            ++processed;
            continue;
        }

        const auto provider = _providers.find(message.provider);
        if (provider == _providers.end()) continue;
        const auto providerLimit = provider->second.descriptor.maximumPayloadBytes;
        if (providerLimit > 0 && message.payload.size() > providerLimit)
        {
            message.state = State::deadLetter;
            message.nextAttemptMicroseconds = 0;
            message.lastErrorCode = "provider-payload-limit";
            message.lastErrorMessage = "Message exceeds the attached provider limit";
            persist(message);
            ++processed;
            continue;
        }

        message.state = State::delivering;
        ++message.attempts;
        persist(message); // Durable checkpoint before invoking provider code.

        DeliveryResult result;
        try
        {
            result = provider->second.service->deliver(
                {message.id, message.destination, message.idempotencyKey,
                 message.orderingKey, message.payload, message.attempts});
        }
        catch (const Poco::Exception& exception)
        {
            result = DeliveryResult::retryAfter(
                std::chrono::milliseconds(0), "provider-exception", exception.displayText());
        }
        catch (const std::exception& exception)
        {
            result = DeliveryResult::retryAfter(
                std::chrono::milliseconds(0), "provider-exception", exception.what());
        }
        catch (...)
        {
            result = DeliveryResult::retryAfter(
                std::chrono::milliseconds(0), "provider-exception",
                "Unknown delivery provider exception");
        }

        if (result.disposition == DeliveryDisposition::acknowledged)
        {
            message.state = State::delivered;
            message.nextAttemptMicroseconds = 0;
            message.deliveredMicroseconds = _clock();
            message.lastErrorCode.clear();
            message.lastErrorMessage.clear();
        }
        else if (result.disposition == DeliveryDisposition::permanentFailure ||
                 result.retryDelay.count() < 0 ||
                 message.attempts >= _policy.maximumAttempts)
        {
            message.state = State::deadLetter;
            message.nextAttemptMicroseconds = 0;
            message.lastErrorCode = result.errorCode.empty()
                ? (message.attempts >= _policy.maximumAttempts
                       ? "attempts-exhausted" : "permanent-failure")
                : result.errorCode;
            message.lastErrorMessage = result.errorMessage.empty()
                ? "Message delivery permanently failed" : result.errorMessage;
        }
        else
        {
            message.state = State::pending;
            message.nextAttemptMicroseconds = _clock() +
                retryDelay(message.attempts, result.retryDelay).count() * 1000;
            message.lastErrorCode = result.errorCode.empty()
                ? "delivery-retry" : result.errorCode;
            message.lastErrorMessage = result.errorMessage;
        }
        persist(message);
        ++processed;
    }
    return processed;
}

std::size_t OutboxEngine::purge()
{
    std::lock_guard<std::recursive_mutex> lock(_mutex);
    const auto retention = std::chrono::duration_cast<std::chrono::microseconds>(
        _policy.terminalRetention).count();
    return _store->purgeTerminalBefore(_clock() - retention);
}

Message OutboxEngine::get(const std::string& id) const
{
    std::lock_guard<std::recursive_mutex> lock(_mutex);
    return requireMessage(id);
}

std::vector<Message> OutboxEngine::list() const
{
    std::lock_guard<std::recursive_mutex> lock(_mutex);
    return _store->list();
}

Snapshot OutboxEngine::snapshot() const
{
    std::lock_guard<std::recursive_mutex> lock(_mutex);
    Snapshot result;
    for (const auto& message : _store->list())
    {
        switch (message.state)
        {
        case State::pending: ++result.pending; break;
        case State::delivering: ++result.delivering; break;
        case State::delivered: ++result.delivered; break;
        case State::deadLetter: ++result.deadLetter; break;
        case State::cancelled: ++result.cancelled; break;
        }
    }
    return result;
}

std::vector<std::string> OutboxEngine::providerTypes() const
{
    std::lock_guard<std::recursive_mutex> lock(_mutex);
    std::vector<std::string> result;
    result.reserve(_providers.size());
    for (const auto& [type, provider] : _providers) result.push_back(type);
    std::sort(result.begin(), result.end());
    return result;
}

void OutboxEngine::persist(Message& message)
{
    message.updatedMicroseconds = _clock();
    ++message.revision;
    _store->save(message);
}

Message OutboxEngine::requireMessage(const std::string& id) const
{
    const auto message = _store->find(id);
    if (!message) throw Poco::NotFoundException("Outbox message was not found", id);
    return *message;
}

std::chrono::milliseconds OutboxEngine::retryDelay(
    unsigned attempt, std::chrono::milliseconds requested) const
{
    if (requested.count() > 0)
        return std::min(requested, _policy.maximumRetryDelay);
    auto delay = _policy.initialRetryDelay;
    for (unsigned index = 1; index < attempt && delay < _policy.maximumRetryDelay; ++index)
    {
        if (delay.count() > _policy.maximumRetryDelay.count() / 2)
            return _policy.maximumRetryDelay;
        delay *= 2;
    }
    return std::min(delay, _policy.maximumRetryDelay);
}
} // namespace PocoDDS::StoreForward
