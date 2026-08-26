#include "PocoDDS/DDS/AbiV1.h"

#include <chrono>
#include <atomic>
#include <condition_variable>
#include <cstdlib>
#include <iostream>
#include <mutex>
#include <string>
#include <thread>

namespace
{
struct CallbackState
{
    std::mutex mutex;
    std::condition_variable condition;
    std::size_t received{0};
    std::uint64_t sequence{0};
    std::string payload;
};

struct BlockingCallbackState
{
    std::mutex mutex;
    std::condition_variable condition;
    bool entered{false};
    bool release{false};
};

void PDR_FASTDDS_ABI_V1_CALL receiveEnvelope(
    const PdrFastDdsEnvelopeV1* envelope, void* userData)
{
    auto& state = *static_cast<CallbackState*>(userData);
    std::lock_guard<std::mutex> lock(state.mutex);
    if (envelope != nullptr && envelope->struct_size >= sizeof(PdrFastDdsEnvelopeV1))
    {
        state.sequence = envelope->sequence;
        state.payload = envelope->payload != nullptr ? envelope->payload : "";
        ++state.received;
    }
    state.condition.notify_one();
}

void PDR_FASTDDS_ABI_V1_CALL blockEnvelope(
    const PdrFastDdsEnvelopeV1*, void* userData)
{
    auto& state = *static_cast<BlockingCallbackState*>(userData);
    std::unique_lock<std::mutex> lock(state.mutex);
    state.entered = true;
    state.condition.notify_all();
    state.condition.wait(lock, [&] { return state.release; });
}

void require(bool condition, const std::string& message)
{
    if (!condition)
    {
        std::cerr << "FAST_DDS_ABI_V1_FAIL: " << message << '\n';
        std::exit(1);
    }
}
} // namespace

int main()
{
    require(pdr_fastdds_abi_version_v1() == PDR_FASTDDS_ABI_VERSION_V1,
            "unexpected ABI version");
    require(pdr_fastdds_envelope_size_v1() == sizeof(PdrFastDdsEnvelopeV1),
            "envelope layout mismatch");

    char error[512]{};
    require(pdr_fastdds_runtime_create_v1(0, "invalid", nullptr, error, sizeof(error)) ==
                PDR_FASTDDS_STATUS_V1_INVALID_ARGUMENT,
            "null output handle was accepted");
    require(error[0] != '\0', "invalid argument did not provide an error message");

    PdrFastDdsRuntimeV1* runtime = nullptr;
    require(pdr_fastdds_runtime_create_v1(37, "pdr-fastdds-abi-v1-smoke", &runtime,
                                          error, sizeof(error)) == PDR_FASTDDS_STATUS_V1_OK,
            error);
    require(runtime != nullptr, "create returned a null runtime");

    int32_t started = -1;
    require(pdr_fastdds_runtime_started_v1(runtime, &started, error, sizeof(error)) ==
                PDR_FASTDDS_STATUS_V1_OK && started == 0,
            "new runtime was unexpectedly started");
    require(pdr_fastdds_runtime_start_v1(runtime, error, sizeof(error)) ==
                PDR_FASTDDS_STATUS_V1_OK,
            error);
    require(pdr_fastdds_runtime_started_v1(runtime, &started, error, sizeof(error)) ==
                PDR_FASTDDS_STATUS_V1_OK && started == 1,
            "runtime did not report started");

    constexpr const char* topic = "pdr.fastdds.abi.v1.smoke";
    CallbackState callback;
    PdrFastDdsSubscriptionV1* subscription = nullptr;
    require(pdr_fastdds_runtime_subscribe_v1(runtime, topic, receiveEnvelope, &callback,
                                              &subscription, error, sizeof(error)) ==
                PDR_FASTDDS_STATUS_V1_OK,
            error);
    require(subscription != nullptr, "subscribe returned a null subscription handle");
    require(pdr_fastdds_runtime_prepare_publisher_v1(runtime, topic, error, sizeof(error)) ==
                PDR_FASTDDS_STATUS_V1_OK,
            error);

    PdrFastDdsEnvelopeV1 envelope{};
    envelope.struct_size = sizeof(envelope);
    envelope.sequence = 73;
    envelope.kind = "abi-v1-smoke";
    envelope.payload = "opaque-c-abi";
    require(pdr_fastdds_runtime_publish_v1(runtime, topic, &envelope, error, sizeof(error)) ==
                PDR_FASTDDS_STATUS_V1_OK,
            error);
    {
        std::unique_lock<std::mutex> lock(callback.mutex);
        require(callback.condition.wait_for(lock, std::chrono::seconds(3),
                                            [&] { return callback.received == 1; }),
                "subscription callback timed out");
        require(callback.sequence == 73 && callback.payload == "opaque-c-abi",
                "subscription callback payload mismatch");
    }

    require(pdr_fastdds_subscription_unsubscribe_v1(
                subscription, error, sizeof(error)) == PDR_FASTDDS_STATUS_V1_OK,
            error);
    envelope.sequence = 74;
    envelope.payload = "must-not-dispatch";
    require(pdr_fastdds_runtime_publish_v1(runtime, topic, &envelope, error, sizeof(error)) ==
                PDR_FASTDDS_STATUS_V1_OK,
            error);
    std::this_thread::sleep_for(std::chrono::milliseconds(250));
    {
        std::lock_guard<std::mutex> lock(callback.mutex);
        require(callback.received == 1,
                "callback ran after subscription unsubscribe returned");
    }
    pdr_fastdds_subscription_destroy_v1(subscription);

    constexpr const char* blockingTopic = "pdr.fastdds.abi.v1.blocking";
    BlockingCallbackState blocking;
    PdrFastDdsSubscriptionV1* blockingSubscription = nullptr;
    require(pdr_fastdds_runtime_subscribe_v1(
                runtime, blockingTopic, blockEnvelope, &blocking, &blockingSubscription,
                error, sizeof(error)) == PDR_FASTDDS_STATUS_V1_OK,
            error);
    require(pdr_fastdds_runtime_prepare_publisher_v1(
                runtime, blockingTopic, error, sizeof(error)) == PDR_FASTDDS_STATUS_V1_OK,
            error);
    std::atomic<int32_t> publishStatus{PDR_FASTDDS_STATUS_V1_UNKNOWN_ERROR};
    std::thread publisher([&]
    {
        char threadError[512]{};
        publishStatus = pdr_fastdds_runtime_publish_v1(
            runtime, blockingTopic, &envelope, threadError, sizeof(threadError));
    });
    {
        std::unique_lock<std::mutex> lock(blocking.mutex);
        require(blocking.condition.wait_for(lock, std::chrono::seconds(3),
                                            [&] { return blocking.entered; }),
                "blocking callback did not start");
    }
    std::atomic<bool> unsubscribeStarted{false};
    std::atomic<bool> unsubscribeReturned{false};
    std::atomic<int32_t> unsubscribeStatus{PDR_FASTDDS_STATUS_V1_UNKNOWN_ERROR};
    std::thread unsubscriber([&]
    {
        char threadError[512]{};
        unsubscribeStarted = true;
        unsubscribeStatus = pdr_fastdds_subscription_unsubscribe_v1(
            blockingSubscription, threadError, sizeof(threadError));
        unsubscribeReturned = true;
    });
    for (int attempt = 0; attempt < 100 && !unsubscribeStarted; ++attempt)
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    require(unsubscribeStarted, "unsubscribe worker did not start");
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    require(!unsubscribeReturned,
            "unsubscribe returned before an in-flight callback drained");
    {
        std::lock_guard<std::mutex> lock(blocking.mutex);
        blocking.release = true;
    }
    blocking.condition.notify_all();
    publisher.join();
    unsubscriber.join();
    require(publishStatus == PDR_FASTDDS_STATUS_V1_OK,
            "blocking callback publish failed");
    require(unsubscribeStatus == PDR_FASTDDS_STATUS_V1_OK && unsubscribeReturned,
            "unsubscribe did not finish after the callback drained");
    pdr_fastdds_subscription_destroy_v1(blockingSubscription);

    require(pdr_fastdds_runtime_stop_v1(runtime, error, sizeof(error)) ==
                PDR_FASTDDS_STATUS_V1_OK,
            error);
    pdr_fastdds_runtime_destroy_v1(runtime);
    std::cout << "FAST_DDS_ABI_V1_PASS version=1 lifecycle=verified callback=verified "
                 "unsubscribe=verified drain=verified\n";
    return 0;
}
