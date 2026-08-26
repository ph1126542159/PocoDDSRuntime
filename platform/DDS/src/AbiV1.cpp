#include "PocoDDS/DDS/AbiV1.h"

#include "PocoDDS/DDS/Runtime.h"

#include <algorithm>
#include <condition_variable>
#include <cstring>
#include <exception>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

struct PdrFastDdsSubscriptionStateV1
{
    std::mutex mutex;
    std::condition_variable drained;
    PdrFastDdsEnvelopeHandlerV1 handler{nullptr};
    void* userData{nullptr};
    std::size_t inFlight{0};
};

struct PdrFastDdsRuntimeV1
{
    explicit PdrFastDdsRuntimeV1(uint32_t domainId, std::string participantName)
        : runtime(domainId, std::move(participantName))
    {
    }

    PocoDDS::FastDDS::Runtime runtime;
    std::mutex subscriptionsMutex;
    std::vector<std::weak_ptr<PdrFastDdsSubscriptionStateV1>> subscriptions;
};

struct PdrFastDdsSubscriptionV1
{
    explicit PdrFastDdsSubscriptionV1(
        std::shared_ptr<PdrFastDdsSubscriptionStateV1> value)
        : state(std::move(value))
    {
    }

    std::shared_ptr<PdrFastDdsSubscriptionStateV1> state;
};

namespace
{
thread_local const PdrFastDdsSubscriptionStateV1* activeSubscription = nullptr;

PdrFastDdsEnvelopeV1 toAbiEnvelope(
    const PocoDDS::FastDDS::Envelope& value) noexcept;

void clearError(char* message, size_t capacity) noexcept
{
    if (message != nullptr && capacity != 0)
        message[0] = '\0';
}

void writeError(char* message, size_t capacity, const char* value) noexcept
{
    if (message == nullptr || capacity == 0)
        return;
    const char* source = value != nullptr ? value : "unknown error";
    const auto length = std::min(capacity - 1, std::strlen(source));
    std::memcpy(message, source, length);
    message[length] = '\0';
}

template <typename Operation>
int32_t invoke(char* message, size_t capacity, Operation&& operation) noexcept
{
    clearError(message, capacity);
    try
    {
        operation();
        return PDR_FASTDDS_STATUS_V1_OK;
    }
    catch (const std::invalid_argument& exception)
    {
        writeError(message, capacity, exception.what());
        return PDR_FASTDDS_STATUS_V1_INVALID_ARGUMENT;
    }
    catch (const std::logic_error& exception)
    {
        writeError(message, capacity, exception.what());
        return PDR_FASTDDS_STATUS_V1_INVALID_STATE;
    }
    catch (const std::exception& exception)
    {
        writeError(message, capacity, exception.what());
        return PDR_FASTDDS_STATUS_V1_RUNTIME_ERROR;
    }
    catch (...)
    {
        writeError(message, capacity, "unknown Fast DDS runtime error");
        return PDR_FASTDDS_STATUS_V1_UNKNOWN_ERROR;
    }
}

PdrFastDdsRuntimeV1& requireRuntime(PdrFastDdsRuntimeV1* runtime)
{
    if (runtime == nullptr)
        throw std::invalid_argument("Fast DDS ABI runtime handle is null");
    return *runtime;
}

const PdrFastDdsRuntimeV1& requireRuntime(const PdrFastDdsRuntimeV1* runtime)
{
    if (runtime == nullptr)
        throw std::invalid_argument("Fast DDS ABI runtime handle is null");
    return *runtime;
}

PdrFastDdsSubscriptionV1& requireSubscription(PdrFastDdsSubscriptionV1* subscription)
{
    if (subscription == nullptr)
        throw std::invalid_argument("Fast DDS ABI subscription handle is null");
    return *subscription;
}

void disableSubscription(
    const std::shared_ptr<PdrFastDdsSubscriptionStateV1>& state) noexcept
{
    if (!state)
        return;
    std::unique_lock<std::mutex> lock(state->mutex);
    state->handler = nullptr;
    state->userData = nullptr;
    if (activeSubscription != state.get())
        state->drained.wait(lock, [&] { return state->inFlight == 0; });
}

void disableRuntimeSubscriptions(PdrFastDdsRuntimeV1& runtime) noexcept
{
    std::vector<std::shared_ptr<PdrFastDdsSubscriptionStateV1>> states;
    {
        std::lock_guard<std::mutex> lock(runtime.subscriptionsMutex);
        states.reserve(runtime.subscriptions.size());
        for (const auto& subscription : runtime.subscriptions)
        {
            if (auto state = subscription.lock())
                states.push_back(std::move(state));
        }
    }
    for (const auto& state : states)
        disableSubscription(state);
}

void dispatchSubscription(
    const std::shared_ptr<PdrFastDdsSubscriptionStateV1>& state,
    const PocoDDS::FastDDS::Envelope& envelope) noexcept
{
    PdrFastDdsEnvelopeHandlerV1 handler = nullptr;
    void* userData = nullptr;
    {
        std::lock_guard<std::mutex> lock(state->mutex);
        if (state->handler == nullptr)
            return;
        handler = state->handler;
        userData = state->userData;
        ++state->inFlight;
    }

    const auto* previous = activeSubscription;
    activeSubscription = state.get();
    const auto abiEnvelope = toAbiEnvelope(envelope);
    try
    {
        handler(&abiEnvelope, userData);
    }
    catch (...)
    {
    }
    activeSubscription = previous;

    {
        std::lock_guard<std::mutex> lock(state->mutex);
        --state->inFlight;
        if (state->inFlight == 0)
            state->drained.notify_all();
    }
}

std::string requireText(const char* value, const char* field)
{
    if (value == nullptr || value[0] == '\0')
        throw std::invalid_argument(std::string(field) + " is empty");
    return value;
}

std::string optionalText(const char* value)
{
    return value != nullptr ? std::string(value) : std::string{};
}

PocoDDS::FastDDS::Envelope toCppEnvelope(const PdrFastDdsEnvelopeV1* value)
{
    if (value == nullptr)
        throw std::invalid_argument("Fast DDS ABI envelope is null");
    if (value->struct_size < sizeof(PdrFastDdsEnvelopeV1))
        throw std::invalid_argument("Fast DDS ABI envelope struct_size is too small");
    PocoDDS::FastDDS::Envelope result;
    result.sequence = value->sequence;
    result.timestampMicroseconds = value->timestamp_microseconds;
    result.kind = optionalText(value->kind);
    result.deviceId = optionalText(value->device_id);
    result.operation = optionalText(value->operation);
    result.payload = optionalText(value->payload);
    result.correlationId = optionalText(value->correlation_id);
    result.traceParent = optionalText(value->trace_parent);
    result.traceState = optionalText(value->trace_state);
    result.businessName = optionalText(value->business_name);
    result.businessInstanceId = optionalText(value->business_instance_id);
    result.status = value->status;
    return result;
}

PdrFastDdsEnvelopeV1 toAbiEnvelope(const PocoDDS::FastDDS::Envelope& value) noexcept
{
    PdrFastDdsEnvelopeV1 result{};
    result.struct_size = sizeof(result);
    result.sequence = value.sequence;
    result.timestamp_microseconds = value.timestampMicroseconds;
    result.kind = value.kind.c_str();
    result.device_id = value.deviceId.c_str();
    result.operation = value.operation.c_str();
    result.payload = value.payload.c_str();
    result.correlation_id = value.correlationId.c_str();
    result.trace_parent = value.traceParent.c_str();
    result.trace_state = value.traceState.c_str();
    result.business_name = value.businessName.c_str();
    result.business_instance_id = value.businessInstanceId.c_str();
    result.status = value.status;
    return result;
}
} // namespace

extern "C"
{
uint32_t PDR_FASTDDS_ABI_V1_CALL pdr_fastdds_abi_version_v1(void)
{
    return PDR_FASTDDS_ABI_VERSION_V1;
}

uint32_t PDR_FASTDDS_ABI_V1_CALL pdr_fastdds_envelope_size_v1(void)
{
    return static_cast<uint32_t>(sizeof(PdrFastDdsEnvelopeV1));
}

int32_t PDR_FASTDDS_ABI_V1_CALL pdr_fastdds_runtime_create_v1(
    uint32_t domainId, const char* participantName, PdrFastDdsRuntimeV1** runtime,
    char* errorMessage, size_t errorCapacity)
{
    if (runtime != nullptr)
        *runtime = nullptr;
    return invoke(errorMessage, errorCapacity, [&]
    {
        if (runtime == nullptr)
            throw std::invalid_argument("Fast DDS ABI output runtime handle is null");
        *runtime = new PdrFastDdsRuntimeV1(
            domainId, requireText(participantName, "Fast DDS participant name"));
    });
}

void PDR_FASTDDS_ABI_V1_CALL pdr_fastdds_runtime_destroy_v1(PdrFastDdsRuntimeV1* runtime)
{
    try
    {
        if (runtime != nullptr)
            disableRuntimeSubscriptions(*runtime);
        delete runtime;
    }
    catch (...)
    {
    }
}

int32_t PDR_FASTDDS_ABI_V1_CALL pdr_fastdds_runtime_start_v1(
    PdrFastDdsRuntimeV1* runtime, char* errorMessage, size_t errorCapacity)
{
    return invoke(errorMessage, errorCapacity,
                  [&] { requireRuntime(runtime).runtime.start(); });
}

int32_t PDR_FASTDDS_ABI_V1_CALL pdr_fastdds_runtime_stop_v1(
    PdrFastDdsRuntimeV1* runtime, char* errorMessage, size_t errorCapacity)
{
    return invoke(errorMessage, errorCapacity, [&]
    {
        auto& owner = requireRuntime(runtime);
        disableRuntimeSubscriptions(owner);
        owner.runtime.stop();
    });
}

int32_t PDR_FASTDDS_ABI_V1_CALL pdr_fastdds_runtime_started_v1(
    const PdrFastDdsRuntimeV1* runtime, int32_t* started, char* errorMessage,
    size_t errorCapacity)
{
    if (started != nullptr)
        *started = 0;
    return invoke(errorMessage, errorCapacity, [&]
    {
        if (started == nullptr)
            throw std::invalid_argument("Fast DDS ABI started output is null");
        *started = requireRuntime(runtime).runtime.started() ? 1 : 0;
    });
}

int32_t PDR_FASTDDS_ABI_V1_CALL pdr_fastdds_runtime_prepare_publisher_v1(
    PdrFastDdsRuntimeV1* runtime, const char* topic, char* errorMessage,
    size_t errorCapacity)
{
    return invoke(errorMessage, errorCapacity, [&]
    {
        requireRuntime(runtime).runtime.preparePublisher(requireText(topic, "Fast DDS topic"));
    });
}

int32_t PDR_FASTDDS_ABI_V1_CALL pdr_fastdds_runtime_publish_v1(
    PdrFastDdsRuntimeV1* runtime, const char* topic,
    const PdrFastDdsEnvelopeV1* envelope, char* errorMessage, size_t errorCapacity)
{
    return invoke(errorMessage, errorCapacity, [&]
    {
        requireRuntime(runtime).runtime.publish(requireText(topic, "Fast DDS topic"),
                                                toCppEnvelope(envelope));
    });
}

int32_t PDR_FASTDDS_ABI_V1_CALL pdr_fastdds_runtime_subscribe_v1(
    PdrFastDdsRuntimeV1* runtime, const char* topic,
    PdrFastDdsEnvelopeHandlerV1 handler, void* userData,
    PdrFastDdsSubscriptionV1** subscription, char* errorMessage, size_t errorCapacity)
{
    if (subscription != nullptr)
        *subscription = nullptr;
    return invoke(errorMessage, errorCapacity, [&]
    {
        if (handler == nullptr)
            throw std::invalid_argument("Fast DDS ABI subscription handler is null");
        if (subscription == nullptr)
            throw std::invalid_argument("Fast DDS ABI output subscription handle is null");
        auto& owner = requireRuntime(runtime);
        auto state = std::make_shared<PdrFastDdsSubscriptionStateV1>();
        state->handler = handler;
        state->userData = userData;
        auto token = std::make_unique<PdrFastDdsSubscriptionV1>(state);
        try
        {
            owner.runtime.subscribe(
                requireText(topic, "Fast DDS topic"),
                [state](const PocoDDS::FastDDS::Envelope& envelope) noexcept
                {
                    dispatchSubscription(state, envelope);
                });
            std::lock_guard<std::mutex> lock(owner.subscriptionsMutex);
            owner.subscriptions.erase(
                std::remove_if(owner.subscriptions.begin(), owner.subscriptions.end(),
                               [](const auto& item) { return item.expired(); }),
                owner.subscriptions.end());
            owner.subscriptions.push_back(state);
        }
        catch (...)
        {
            disableSubscription(state);
            throw;
        }
        *subscription = token.release();
    });
}

int32_t PDR_FASTDDS_ABI_V1_CALL pdr_fastdds_subscription_unsubscribe_v1(
    PdrFastDdsSubscriptionV1* subscription, char* errorMessage, size_t errorCapacity)
{
    return invoke(errorMessage, errorCapacity, [&]
    {
        disableSubscription(requireSubscription(subscription).state);
    });
}

void PDR_FASTDDS_ABI_V1_CALL pdr_fastdds_subscription_destroy_v1(
    PdrFastDdsSubscriptionV1* subscription)
{
    try
    {
        if (subscription != nullptr)
            disableSubscription(subscription->state);
        delete subscription;
    }
    catch (...)
    {
    }
}
}
