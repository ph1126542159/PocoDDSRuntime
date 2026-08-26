#pragma once

#include <Poco/Types.h>

#include <chrono>
#include <cstddef>
#include <string>
#include <utility>

namespace PocoDDS::StoreForward
{
enum class State
{
    pending,
    delivering,
    delivered,
    deadLetter,
    cancelled
};

enum class DeliveryDisposition
{
    acknowledged,
    retry,
    permanentFailure
};

struct DeliveryResult
{
    DeliveryDisposition disposition{DeliveryDisposition::acknowledged};
    std::chrono::milliseconds retryDelay{0};
    std::string errorCode;
    std::string errorMessage;

    static DeliveryResult ack()
    {
        return {};
    }

    static DeliveryResult retryAfter(std::chrono::milliseconds delay,
                                     std::string code,
                                     std::string message)
    {
        DeliveryResult result;
        result.disposition = DeliveryDisposition::retry;
        result.retryDelay = delay;
        result.errorCode = std::move(code);
        result.errorMessage = std::move(message);
        return result;
    }

    static DeliveryResult permanent(std::string code, std::string message)
    {
        DeliveryResult result;
        result.disposition = DeliveryDisposition::permanentFailure;
        result.errorCode = std::move(code);
        result.errorMessage = std::move(message);
        return result;
    }
};

struct ProviderDescriptor
{
    std::string type;
    std::string version;
    std::size_t maximumPayloadBytes{0};
};

struct DeliveryRequest
{
    std::string messageId;
    std::string destination;
    std::string idempotencyKey;
    std::string orderingKey;
    std::string payload;
    unsigned attempt{1};
};

struct EnqueueRequest
{
    std::string provider;
    std::string destination;
    std::string idempotencyKey;
    std::string orderingKey;
    std::string payload;
    Poco::Int64 expiresAtMicroseconds{0};
};

struct Message
{
    std::string id;
    std::string provider;
    std::string destination;
    std::string idempotencyKey;
    std::string orderingKey;
    std::string payload;
    State state{State::pending};
    unsigned attempts{0};
    Poco::Int64 nextAttemptMicroseconds{0};
    Poco::Int64 expiresAtMicroseconds{0};
    Poco::Int64 createdMicroseconds{0};
    Poco::Int64 updatedMicroseconds{0};
    Poco::Int64 deliveredMicroseconds{0};
    std::string lastErrorCode;
    std::string lastErrorMessage;
    Poco::UInt64 revision{0};
};

struct Policy
{
    std::size_t maximumActiveMessages{10000};
    std::size_t maximumPayloadBytes{1024 * 1024};
    unsigned maximumAttempts{8};
    std::chrono::milliseconds initialRetryDelay{1000};
    std::chrono::milliseconds maximumRetryDelay{60000};
    std::size_t deliveryBatchSize{100};
    std::chrono::hours terminalRetention{24 * 7};
};

struct Snapshot
{
    std::size_t pending{0};
    std::size_t delivering{0};
    std::size_t delivered{0};
    std::size_t deadLetter{0};
    std::size_t cancelled{0};
};

const char* stateName(State state) noexcept;
State parseState(const std::string& value);
bool terminal(State state) noexcept;
} // namespace PocoDDS::StoreForward
