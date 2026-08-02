#include "PocoDDS/Reliability/Reliability.h"
#include "PocoDDS/Reliability/AlertSink.h"

#include <iostream>

int main()
{
    using namespace PocoDDS::Reliability;
    struct CapturingSink final : AlertSink
    {
        void deliver(const AlertNotification& value) override { last = value; }
        AlertNotification last;
    } sink;
    sink.deliver({"a1", "alert.opened", "device", "d1", "PDR-DEVICE-TEST",
                  "firing", "warning", "trace1", "test", true, false, 1});
    if (sink.last.instance != "d1" || !sink.last.retryable)
        return 8;
    RetryPolicy retry;
    if (retry.delayFor(3) != std::chrono::milliseconds(400))
        return 1;
    const auto now = std::chrono::steady_clock::now();
    CircuitBreaker breaker(2, std::chrono::milliseconds(100));
    breaker.failure(now);
    breaker.failure(now);
    if (breaker.allow(now) || !breaker.allow(now + std::chrono::milliseconds(101)))
        return 2;
    IdempotencyWindow keys(2);
    if (!keys.accept("a") || keys.accept("a") || !keys.accept("b") || !keys.accept("c") ||
        !keys.accept("a"))
        return 3;
    Bulkhead bulkhead(1);
    if (!bulkhead.tryAcquire() || bulkhead.tryAcquire())
        return 4;
    bulkhead.release();
    BoundedQueue<int> queue(1);
    if (!queue.tryPush(7) || queue.tryPush(8) || queue.pop(std::chrono::milliseconds(1)) != 7)
        return 5;
    Lease lease(std::chrono::seconds(1));
    ShutdownSignal shutdown;
    if (!lease.valid() || shutdown.requested())
        return 6;
    shutdown.request();
    if (!shutdown.requested())
        return 7;
    std::cout << "RELIABILITY_SMOKE_PASS\n";
}
