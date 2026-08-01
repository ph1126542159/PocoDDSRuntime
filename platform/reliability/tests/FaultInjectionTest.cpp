#include "PocoDDS/Reliability/Reliability.h"

#include <atomic>
#include <chrono>
#include <iostream>
#include <thread>
#include <vector>

int main()
{
    using namespace PocoDDS::Reliability;
    using namespace std::chrono_literals;

    // Dependency outage: the circuit must reject work after repeated failures
    // and permit a half-open probe after the reset timeout.
    const auto start = std::chrono::steady_clock::now();
    CircuitBreaker breaker(3, 250ms);
    breaker.failure(start);
    breaker.failure(start + 1ms);
    breaker.failure(start + 2ms);
    if (breaker.allow(start + 3ms) || !breaker.allow(start + 253ms))
        return 1;
    breaker.success();
    if (!breaker.allow(start + 4ms))
        return 2;

    // Retry storm protection: delays grow but never exceed the configured cap.
    RetryPolicy retry{8, 10ms, 80ms, 2.0};
    if (retry.delayFor(1) != 10ms || retry.delayFor(4) != 80ms ||
        retry.delayFor(8) != 80ms)
        return 3;

    // Duplicate delivery: only one consumer may accept the same idempotency key.
    IdempotencyWindow idempotency(16);
    std::atomic<int> accepted{0};
    std::vector<std::thread> duplicates;
    for (int index = 0; index < 16; ++index)
        duplicates.emplace_back([&] {
            if (idempotency.accept("replayed-command"))
                ++accepted;
        });
    for (auto& thread : duplicates)
        thread.join();
    if (accepted != 1)
        return 4;

    // Slow consumer: producers must observe backpressure instead of unbounded growth.
    BoundedQueue<int> queue(2);
    if (!queue.tryPush(1) || !queue.tryPush(2) || queue.tryPush(3) || queue.size() != 2)
        return 5;
    if (queue.pop(1ms) != 1 || !queue.tryPush(3))
        return 6;
    queue.close();
    if (queue.tryPush(4))
        return 7;

    // Graceful shutdown must wake a blocked consumer promptly.
    BoundedQueue<int> blocked(1);
    std::atomic<bool> woke{false};
    std::thread consumer([&] {
        const auto value = blocked.pop(5s);
        woke = !value.has_value();
    });
    std::this_thread::sleep_for(20ms);
    blocked.close();
    consumer.join();
    if (!woke)
        return 8;

    std::cout << "FAULT_INJECTION_PASS outage retry duplicate backpressure shutdown\n";
    return 0;
}
