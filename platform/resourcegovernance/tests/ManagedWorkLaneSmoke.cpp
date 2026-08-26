#include "PocoDDS/ResourceGovernance/ManagedWorkLane.h"

#include <atomic>
#include <chrono>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <thread>

using namespace PocoDDS::ResourceGovernance;
using namespace std::chrono_literals;

namespace
{
class TestGovernorService final : public ResourceGovernorService
{
public:
    TestGovernorService()
        : _governor(Policy{"*", 1, 1, 1s, 2s, 5, 100ms})
    {
    }

    Admission submit(const std::string& owner, WorkItem item) override
    {
        return _governor.submit(owner, std::move(item));
    }

    Snapshot snapshot(const std::string& owner) const override
    {
        return _governor.snapshot(owner);
    }

    std::vector<Snapshot> snapshots() const override
    {
        return _governor.snapshots();
    }

private:
    ResourceGovernor _governor;
};

bool waitFor(const std::function<bool()>& predicate,
             std::chrono::milliseconds timeout = 2s)
{
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    while (std::chrono::steady_clock::now() < deadline)
    {
        if (predicate()) return true;
        std::this_thread::sleep_for(2ms);
    }
    return predicate();
}
} // namespace

int main()
{
    try
    {
        auto* implementation = new TestGovernorService;
        ResourceGovernorService::Ptr service = implementation;
        ManagedWorkLane lane(service, "pdr.test.managedLane");

        std::atomic<bool> throwingCompletionRan{false};
        auto quick = lane.submit({"throwing-completion", [](const auto&) {},
            [&](const Completion&) {
                throwingCompletionRan = true;
                throw std::runtime_error("injected completion failure");
            }});
        if (quick.status != AdmissionStatus::accepted ||
            !waitFor([&] { return throwingCompletionRan.load() && lane.outstanding() == 0; }))
            throw std::runtime_error("throwing completion leaked an outstanding task");

        std::atomic<bool> release{false};
        std::atomic<int> completions{0};
        auto callbackLifetime = std::make_shared<int>(1);
        std::weak_ptr<int> callbackLifetimeProbe = callbackLifetime;
        if (lane.submit({"active", [&, callbackLifetime](const CancellationToken&) {
                while (!release.load()) std::this_thread::sleep_for(2ms);
            }, [&](const Completion&) { ++completions; }}).status !=
                AdmissionStatus::accepted ||
            !waitFor([&] { return implementation->snapshot(lane.owner()).active == 1; }))
            throw std::runtime_error("managed lane did not bind active work to its owner");
        callbackLifetime.reset();
        if (lane.submit({"queued", [](const auto&) {},
                [&](const Completion&) { ++completions; }}).status !=
                AdmissionStatus::accepted)
            throw std::runtime_error("managed lane did not track queued work");
        if (lane.submit({"rejected", [](const auto&) {}, {}}).status !=
                AdmissionStatus::queueFull || lane.outstanding() != 2)
            throw std::runtime_error("rejected work leaked into managed outstanding state");

        std::atomic<bool> closed{false};
        std::thread closer([&] {
            lane.closeAndWait();
            closed = true;
        });
        std::this_thread::sleep_for(30ms);
        if (closed.load())
            throw std::runtime_error("close returned while Bundle callbacks were still active");
        release = true;
        closer.join();

        if (!closed.load() || lane.accepting() || lane.outstanding() != 0 ||
            completions.load() != 2 || !callbackLifetimeProbe.expired())
            throw std::runtime_error("managed lane unload barrier did not drain callbacks");
        if (lane.submit({"after-close", [](const auto&) {}, {}}).status !=
                AdmissionStatus::shuttingDown)
            throw std::runtime_error("managed lane accepted work after close");

        const auto snapshot = implementation->snapshot(lane.owner());
        if (snapshot.submitted != 4 || snapshot.rejectedQueueFull != 1 ||
            snapshot.succeeded != 3)
            throw std::runtime_error("owner-bound governance counters are incomplete");

        std::cout << "MANAGED_WORK_LANE_SMOKE_PASS ownerBinding=1 rejection=1 "
                     "completionSafety=1 unloadBarrier=1\n";
        return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << "MANAGED_WORK_LANE_SMOKE_FAIL " << exception.what() << '\n';
        return 1;
    }
}
