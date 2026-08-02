#include "PocoDDS/Protocols/ProtocolService.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <iostream>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace
{
class ConcurrencyProbeProtocol final : public PocoDDS::Protocols::DiagnosticProtocol,
                                       public PocoDDS::Protocols::FailureDiagnosticProtocol
{
public:
    std::string name() const override
    {
        Guard guard(*this);
        return "concurrency-probe";
    }

    void open() override
    {
        Guard guard(*this);
        _open = true;
        ++_diagnostics.successfulOperations;
    }

    void close() noexcept override
    {
        Guard guard(*this);
        _open = false;
        ++_diagnostics.successfulOperations;
    }

    bool isOpen() const noexcept override
    {
        Guard guard(*this);
        return _open;
    }

    PocoDDS::Protocols::ProtocolDiagnostics diagnostics() const override
    {
        Guard guard(*this);
        return _diagnostics;
    }

    PocoDDS::Reliability::Failure failure() const override
    {
        Guard guard(*this);
        return {"PDR-PROTOCOL-TEST-LAST_FAILURE",
                PocoDDS::Reliability::FailureKind::transient, true, false, 1,
                "recovered test failure"};
    }

    int maximumConcurrency() const noexcept { return _maximumActive.load(); }

private:
    class Guard
    {
    public:
        explicit Guard(const ConcurrencyProbeProtocol& owner): _owner(owner)
        {
            const int active = ++_owner._active;
            int maximum = _owner._maximumActive.load();
            while (maximum < active &&
                   !_owner._maximumActive.compare_exchange_weak(maximum, active)) {}
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }

        ~Guard() { --_owner._active; }

    private:
        const ConcurrencyProbeProtocol& _owner;
    };

    mutable std::atomic<int> _active{0};
    mutable std::atomic<int> _maximumActive{0};
    mutable bool _open{false};
    mutable PocoDDS::Protocols::ProtocolDiagnostics _diagnostics;
};

class BlockingRecoveryProtocol final : public PocoDDS::Protocols::DiagnosticProtocol
{
public:
    std::string name() const override { return "blocking-recovery"; }
    void open() override
    {
        std::unique_lock<std::mutex> lock(_mutex);
        _entered = true;
        _changed.notify_all();
        _changed.wait(lock, [&] { return _released; });
        _open = true;
    }
    void close() noexcept override { _open = false; }
    bool isOpen() const noexcept override { return _open.load(); }
    PocoDDS::Protocols::ProtocolDiagnostics diagnostics() const override { return {}; }
    void waitUntilEntered()
    {
        std::unique_lock<std::mutex> lock(_mutex);
        _changed.wait(lock, [&] { return _entered; });
    }
    void release()
    {
        std::lock_guard<std::mutex> lock(_mutex);
        _released = true;
        _changed.notify_all();
    }
private:
    std::atomic<bool> _open{false};
    std::mutex _mutex;
    std::condition_variable _changed;
    bool _entered{false};
    bool _released{false};
};
}

int main()
{
    ConcurrencyProbeProtocol protocol;
    PocoDDS::Protocols::ProtocolService service(protocol);
    service.open();

    std::atomic<bool> start{false};
    std::vector<std::thread> workers;
    for (int index = 0; index < 8; ++index)
    {
        workers.emplace_back([&, index] {
            while (!start.load()) std::this_thread::yield();
            for (int iteration = 0; iteration < 12; ++iteration)
            {
                if ((index + iteration) % 4 == 0) service.restart();
                else if ((index + iteration) % 5 == 0) (void) service.recoverIfDesired();
                else if ((index + iteration) % 3 == 0) (void) service.name();
                else if ((index + iteration) % 2 == 0) (void) service.diagnostics();
                else (void) service.isOpen();
            }
        });
    }
    start = true;
    for (auto& worker : workers) worker.join();

    if (!service.isOpen() || protocol.maximumConcurrency() != 1 ||
        service.failure().code != "PDR-PROTOCOL-TEST-LAST_FAILURE")
    {
        std::cerr << "PROTOCOL_SERVICE_SMOKE_FAIL open=" << service.isOpen()
                  << " maximumConcurrency=" << protocol.maximumConcurrency() << '\n';
        return 2;
    }
    service.close();
    if (service.isOpen() || service.desiredOpen() || service.recoverIfDesired())
    {
        std::cerr << "PROTOCOL_SERVICE_SMOKE_FAIL manual close was auto-recovered\n";
        return 3;
    }
    service.open();
    protocol.close(); // Simulate a transport-side connection loss.
    if (!service.desiredOpen() || !service.recoverIfDesired() || !service.isOpen())
    {
        std::cerr << "PROTOCOL_SERVICE_SMOKE_FAIL desired connection did not recover\n";
        return 4;
    }

    BlockingRecoveryProtocol blockingProtocol;
    PocoDDS::Protocols::ProtocolService blockingService(blockingProtocol);
    std::thread recovery([&] { (void) blockingService.recoverIfDesired(); });
    blockingProtocol.waitUntilEntered();
    const auto snapshotStart = std::chrono::steady_clock::now();
    const bool openDuringRecovery = blockingService.isOpen();
    (void) blockingService.diagnostics();
    const auto snapshotDuration = std::chrono::steady_clock::now() - snapshotStart;
    blockingProtocol.release();
    recovery.join();
    if (openDuringRecovery || snapshotDuration > std::chrono::milliseconds(50) ||
        !blockingService.isOpen())
    {
        std::cerr << "PROTOCOL_SERVICE_SMOKE_FAIL health snapshot blocked during recovery\n";
        return 5;
    }

    std::cout << "PROTOCOL_SERVICE_SMOKE_PASS maximumConcurrency=1 lifecycle=1\n";
    return 0;
}
