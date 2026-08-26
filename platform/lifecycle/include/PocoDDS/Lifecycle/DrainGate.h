#pragma once

#include "PocoDDS/Lifecycle/Export.h"

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>

namespace PocoDDS::Lifecycle
{
enum class DrainState
{
    accepting,
    quiescing,
    quiesced
};

PDR_LIFECYCLE_API const char* toString(DrainState state) noexcept;

struct DrainSnapshot
{
    DrainState state{DrainState::accepting};
    bool accepting{true};
    std::size_t inFlight{0};
    std::uint64_t generation{0};
};

class PDR_LIFECYCLE_API DrainGate
{
private:
    struct State;

public:
    class PDR_LIFECYCLE_API Lease
    {
    public:
        Lease() = default;
        ~Lease();
        Lease(Lease&& other) noexcept;
        Lease& operator=(Lease&& other) noexcept;
        Lease(const Lease&) = delete;
        Lease& operator=(const Lease&) = delete;
        explicit operator bool() const noexcept { return static_cast<bool>(_state); }

    private:
        friend class DrainGate;
        explicit Lease(std::shared_ptr<State> state);
        void release() noexcept;
        std::shared_ptr<State> _state;
    };

    DrainGate();
    ~DrainGate();
    DrainGate(const DrainGate&) = delete;
    DrainGate& operator=(const DrainGate&) = delete;

    /// Enters one operation when the gate is accepting. The returned Lease is
    /// the in-flight barrier and must live until Bundle-owned work is complete.
    [[nodiscard]] std::optional<Lease> tryEnter();

    /// Atomically rejects new operations and waits for all existing Leases.
    /// A timeout leaves the gate quiescing until resume() or the last Lease exits.
    bool quiesce(std::chrono::milliseconds timeout) noexcept;
    /// Permanent Bundle unload barrier. Rejects new operations and waits
    /// without a timeout until every Lease has been released.
    void closeAndWait() noexcept;
    void resume() noexcept;
    [[nodiscard]] DrainSnapshot snapshot() const noexcept;

private:
    std::shared_ptr<State> _state;
};
} // namespace PocoDDS::Lifecycle
