#include <PocoDDS/Lifecycle/DrainGate.h>

#include <chrono>

int main()
{
    using namespace std::chrono_literals;
    PocoDDS::Lifecycle::DrainGate gate;
    auto lease = gate.tryEnter();
    if (!lease || gate.snapshot().inFlight != 1) return 1;
    if (gate.quiesce(1ms)) return 2;
    if (gate.snapshot().accepting || gate.tryEnter()) return 3;
    lease.reset();
    if (!gate.quiesce(10ms) ||
        gate.snapshot().state != PocoDDS::Lifecycle::DrainState::quiesced)
        return 4;
    gate.resume();
    auto resumed = gate.tryEnter();
    if (!resumed || !gate.snapshot().accepting) return 5;
    resumed.reset();
    gate.closeAndWait();
    gate.resume();
    return gate.tryEnter() ? 6 : 0;
}
