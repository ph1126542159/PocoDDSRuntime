#include "PocoDDS/Lifecycle/DrainGate.h"

#include <chrono>
#include <iostream>
#include <stdexcept>
#include <thread>

namespace
{
void require(bool condition, const char* message)
{
    if (!condition) throw std::runtime_error(message);
}
}

int main()
{
    using namespace std::chrono_literals;
    using namespace PocoDDS::Lifecycle;
    try
    {
        DrainGate gate;
        auto first = gate.tryEnter();
        require(first.has_value(), "accepting gate rejected operation");
        require(!gate.quiesce(1ms), "quiesce ignored active operation");
        require(!gate.tryEnter().has_value(), "quiescing gate accepted new operation");
        require(gate.snapshot().state == DrainState::quiescing,
                "timed out gate did not remain quiescing");
        first.reset();
        require(gate.quiesce(10ms), "gate did not observe completed operation");
        require(gate.snapshot().state == DrainState::quiesced,
                "gate did not become quiesced");
        gate.resume();
        require(gate.snapshot().accepting && gate.tryEnter().has_value(),
                "resume did not reopen gate");

        for (int iteration = 0; iteration < 1000; ++iteration)
        {
            auto lease = gate.tryEnter();
            require(lease.has_value(), "gate lost accepting state");
        }
        require(gate.snapshot().inFlight == 0, "operation Lease leaked");
        gate.closeAndWait();
        gate.resume();
        require(!gate.tryEnter().has_value(),
                "permanent unload barrier was reopened");
        std::cout << "DRAIN_GATE_SMOKE_PASS timeout=1 resume=1 close=1 leases=1001\n";
        return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << "DRAIN_GATE_SMOKE_FAIL: " << exception.what() << '\n';
        return 1;
    }
}
