#include "PocoDDS/ServiceClient/Client.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <map>
#include <mutex>
#include <set>
#include <stdexcept>
#include <thread>
#include <tuple>
#include <utility>

namespace PocoDDS::ServiceClient
{
namespace
{
using TimePoint = std::chrono::steady_clock::time_point;

bool safeText(const std::string& value, std::size_t maximum, bool required)
{
    if ((required && value.empty()) || value.size() > maximum) return false;
    return std::all_of(value.begin(), value.end(), [](unsigned char character) {
        return character >= 0x21 && character <= 0x7e;
    });
}

std::string validatePolicy(const Policy& policy)
{
    if (policy.maximumAttempts == 0 || policy.maximumAttempts > 16)
        return "maximumAttempts must contain 1..16";
    if (policy.timeout < std::chrono::milliseconds{1} ||
        policy.timeout > std::chrono::hours{1})
        return "timeout must contain 1..3600000 milliseconds";
    if (policy.initialBackoff < std::chrono::milliseconds{0} ||
        policy.maximumBackoff < policy.initialBackoff ||
        policy.maximumBackoff > std::chrono::minutes{10})
        return "backoff bounds are invalid";
    if (!std::isfinite(policy.backoffMultiplier) ||
        policy.backoffMultiplier < 1.0 || policy.backoffMultiplier > 10.0)
        return "backoffMultiplier must contain 1.0..10.0";
    if (policy.circuitFailureThreshold == 0 ||
        policy.circuitFailureThreshold > 100000)
        return "circuitFailureThreshold must contain 1..100000";
    if (policy.circuitResetTimeout < std::chrono::milliseconds{1} ||
        policy.circuitResetTimeout > std::chrono::hours{24})
        return "circuitResetTimeout must contain 1..86400000 milliseconds";
    if (policy.maximumCircuitEntries == 0 ||
        policy.maximumCircuitEntries > 100000)
        return "maximumCircuitEntries must contain 1..100000";
    if (policy.circuitIdleRetention < policy.circuitResetTimeout ||
        policy.circuitIdleRetention > std::chrono::hours{24 * 30})
        return "circuitIdleRetention must cover reset timeout and stay within 30 days";
    return {};
}

std::string validateRequest(const InvocationRequest& request)
{
    if (!safeText(request.route.serviceName, 128, true))
        return "serviceName must contain 1..128 visible ASCII characters";
    if (!safeText(request.operation, 128, true))
        return "operation must contain 1..128 visible ASCII characters";
    if (!safeText(request.idempotencyKey, 128, false))
        return "idempotencyKey must contain at most 128 visible ASCII characters";
    return {};
}

std::vector<ServiceDirectory::InstanceIdentity> merged(
    std::vector<ServiceDirectory::InstanceIdentity> left,
    const std::set<ServiceDirectory::InstanceIdentity>& right)
{
    left.insert(left.end(), right.begin(), right.end());
    std::sort(left.begin(), left.end());
    left.erase(std::unique(left.begin(), left.end()), left.end());
    return left;
}

std::chrono::milliseconds remaining(TimePoint deadline, TimePoint now)
{
    if (now >= deadline) return std::chrono::milliseconds{0};
    return std::chrono::duration_cast<std::chrono::milliseconds>(deadline - now);
}
} // namespace

const char* toString(AttemptDisposition value) noexcept
{
    switch (value)
    {
    case AttemptDisposition::succeeded: return "succeeded";
    case AttemptDisposition::retryableFailure: return "retryable-failure";
    case AttemptDisposition::permanentFailure: return "permanent-failure";
    }
    return "unknown";
}

const char* toString(InvocationStatus value) noexcept
{
    switch (value)
    {
    case InvocationStatus::succeeded: return "succeeded";
    case InvocationStatus::invalid: return "invalid";
    case InvocationStatus::noRoute: return "no-route";
    case InvocationStatus::circuitOpen: return "circuit-open";
    case InvocationStatus::circuitCapacityExceeded:
        return "circuit-capacity-exceeded";
    case InvocationStatus::deadlineExceeded: return "deadline-exceeded";
    case InvocationStatus::cancelled: return "cancelled";
    case InvocationStatus::failed: return "failed";
    }
    return "unknown";
}

const char* toString(CircuitState value) noexcept
{
    switch (value)
    {
    case CircuitState::closed: return "closed";
    case CircuitState::open: return "open";
    case CircuitState::halfOpen: return "half-open";
    }
    return "unknown";
}

AttemptResult AttemptResult::success(std::vector<std::uint8_t> value)
{
    AttemptResult result;
    result.disposition = AttemptDisposition::succeeded;
    result.endpointHealthy = true;
    result.payload = std::move(value);
    return result;
}

AttemptResult AttemptResult::retryable(std::string valueCode,
                                       std::string valueDetail)
{
    AttemptResult result;
    result.disposition = AttemptDisposition::retryableFailure;
    result.code = std::move(valueCode);
    result.detail = std::move(valueDetail);
    return result;
}

AttemptResult AttemptResult::permanent(std::string valueCode,
                                       std::string valueDetail,
                                       bool healthy)
{
    AttemptResult result;
    result.disposition = AttemptDisposition::permanentFailure;
    result.endpointHealthy = healthy;
    result.code = std::move(valueCode);
    result.detail = std::move(valueDetail);
    return result;
}

class Client::Impl
{
public:
    using CircuitKey = std::tuple<std::string, std::string, std::string,
                                  std::uint64_t>;

    struct Circuit
    {
        std::size_t failures{0};
        std::optional<TimePoint> openedAt;
        bool probeInFlight{false};
        TimePoint lastTouched{};
    };

    Impl(Policy value, Route router, Clock timeSource, Sleeper wait)
        : policy(std::move(value)), route(std::move(router)),
          clock(std::move(timeSource)), sleeper(std::move(wait))
    {
        const auto issue = validatePolicy(policy);
        if (!issue.empty()) throw std::invalid_argument(issue);
        if (!route) throw std::invalid_argument("route callback is required");
        if (!clock) clock = [] { return std::chrono::steady_clock::now(); };
        if (!sleeper)
            sleeper = [](std::chrono::milliseconds duration) {
                std::this_thread::sleep_for(duration);
            };
    }

    static CircuitKey key(const ServiceDirectory::Advertisement& value)
    {
        return {value.serviceName, value.instanceId, value.runtimeId,
                value.runtimeIncarnation};
    }

    void prune(TimePoint now)
    {
        for (auto iterator = circuits.begin(); iterator != circuits.end();)
        {
            if (!iterator->second.openedAt &&
                now - iterator->second.lastTouched >= policy.circuitIdleRetention)
                iterator = circuits.erase(iterator);
            else ++iterator;
        }
    }

    std::set<ServiceDirectory::InstanceIdentity> unavailable(
        const std::string& serviceName, TimePoint now)
    {
        std::lock_guard<std::mutex> lock(mutex);
        prune(now);
        std::set<ServiceDirectory::InstanceIdentity> result;
        for (const auto& [circuitKey, circuit] : circuits)
        {
            if (std::get<0>(circuitKey) != serviceName || !circuit.openedAt)
                continue;
            if (circuit.probeInFlight ||
                now - *circuit.openedAt < policy.circuitResetTimeout)
                result.insert({std::get<1>(circuitKey), std::get<2>(circuitKey),
                               std::get<3>(circuitKey)});
        }
        return result;
    }

    enum class Reservation
    {
        accepted,
        unavailable,
        capacityExceeded
    };

    Reservation reserve(const ServiceDirectory::Advertisement& advertisement,
                        TimePoint now)
    {
        std::lock_guard<std::mutex> lock(mutex);
        prune(now);
        const auto circuitKey = key(advertisement);
        auto iterator = circuits.find(circuitKey);
        if (iterator == circuits.end())
        {
            if (circuits.size() >= policy.maximumCircuitEntries)
            {
                auto oldest = circuits.end();
                for (auto candidate = circuits.begin(); candidate != circuits.end();
                     ++candidate)
                    if (!candidate->second.openedAt &&
                        (oldest == circuits.end() ||
                         candidate->second.lastTouched < oldest->second.lastTouched))
                        oldest = candidate;
                if (oldest == circuits.end()) return Reservation::capacityExceeded;
                circuits.erase(oldest);
            }
            iterator = circuits.emplace(circuitKey, Circuit{}).first;
        }
        auto& circuit = iterator->second;
        circuit.lastTouched = now;
        if (!circuit.openedAt) return Reservation::accepted;
        if (circuit.probeInFlight ||
            now - *circuit.openedAt < policy.circuitResetTimeout)
            return Reservation::unavailable;
        circuit.probeInFlight = true;
        return Reservation::accepted;
    }

    void complete(const ServiceDirectory::Advertisement& advertisement,
                  const AttemptResult& result, TimePoint now)
    {
        std::lock_guard<std::mutex> lock(mutex);
        auto iterator = circuits.find(key(advertisement));
        if (iterator == circuits.end()) return;
        auto& circuit = iterator->second;
        circuit.lastTouched = now;
        if (result.disposition == AttemptDisposition::succeeded ||
            result.endpointHealthy)
        {
            circuit.failures = 0;
            circuit.openedAt.reset();
            circuit.probeInFlight = false;
            return;
        }
        const bool wasProbe = circuit.probeInFlight;
        circuit.probeInFlight = false;
        ++circuit.failures;
        if (wasProbe || circuit.failures >= policy.circuitFailureThreshold)
            circuit.openedAt = now;
    }

    std::chrono::milliseconds backoff(std::size_t failedAttempt) const
    {
        long double value = static_cast<long double>(
            policy.initialBackoff.count());
        for (std::size_t index = 1; index < failedAttempt; ++index)
        {
            value *= policy.backoffMultiplier;
            if (value >= policy.maximumBackoff.count())
                return policy.maximumBackoff;
        }
        const auto bounded = std::min<long double>(
            value, static_cast<long double>(policy.maximumBackoff.count()));
        return std::chrono::milliseconds{
            static_cast<std::chrono::milliseconds::rep>(bounded)};
    }

    InvocationResult finish(InvocationResult result)
    {
        std::lock_guard<std::mutex> lock(mutex);
        if (result.status == InvocationStatus::succeeded) ++succeeded;
        else ++failed;
        if (result.status == InvocationStatus::noRoute) ++noRoute;
        if (result.status == InvocationStatus::circuitOpen ||
            result.status == InvocationStatus::circuitCapacityExceeded)
            ++circuitRejected;
        if (result.status == InvocationStatus::deadlineExceeded)
            ++deadlineExceeded;
        if (result.status == InvocationStatus::cancelled) ++cancelled;
        return result;
    }

    Policy policy;
    Route route;
    Clock clock;
    Sleeper sleeper;
    mutable std::mutex mutex;
    std::map<CircuitKey, Circuit> circuits;
    std::uint64_t calls{0};
    std::uint64_t succeeded{0};
    std::uint64_t failed{0};
    std::uint64_t attempts{0};
    std::uint64_t retries{0};
    std::uint64_t noRoute{0};
    std::uint64_t circuitRejected{0};
    std::uint64_t deadlineExceeded{0};
    std::uint64_t cancelled{0};
};

Client::Client(Policy policy, Route route, Clock clock, Sleeper sleeper)
    : _impl(std::make_unique<Impl>(std::move(policy), std::move(route),
                                  std::move(clock), std::move(sleeper)))
{
}

Client::~Client() = default;

InvocationResult Client::invoke(const InvocationRequest& request,
                                const Invoke& invocation,
                                const Cancelled& cancellation)
{
    {
        std::lock_guard<std::mutex> lock(_impl->mutex);
        ++_impl->calls;
    }
    const auto issue = validateRequest(request);
    if (!issue.empty() || !invocation)
        return _impl->finish({InvocationStatus::invalid, 0, std::nullopt, {},
                              "invalid-request",
                              issue.empty() ? "invoke callback is required" : issue,
                              {}});

    const auto deadline = _impl->clock() + _impl->policy.timeout;
    const bool retrySafe = request.idempotent || !request.idempotencyKey.empty();
    InvocationResult result;
    std::set<ServiceDirectory::InstanceIdentity> attemptedInstances;
    std::string routeFailure;
    const auto selectRoute = [&](const ServiceDirectory::RouteRequest& value) {
        try
        {
            return _impl->route(value);
        }
        catch (const std::exception& exception)
        {
            routeFailure = exception.what();
        }
        catch (...)
        {
            routeFailure = "Unknown route callback exception";
        }
        return ServiceDirectory::RouteResult{
            ServiceDirectory::SelectionStatus::invalid, std::nullopt, 0,
            routeFailure};
    };

    for (std::size_t attempt = 1;
         attempt <= _impl->policy.maximumAttempts; ++attempt)
    {
        if (cancellation && cancellation())
        {
            result.status = InvocationStatus::cancelled;
            result.code = "cancelled";
            result.detail = "Invocation was cancelled before routing";
            return _impl->finish(std::move(result));
        }
        const auto now = _impl->clock();
        if (now >= deadline)
        {
            result.status = InvocationStatus::deadlineExceeded;
            result.code = "deadline-exceeded";
            result.detail = "Invocation deadline expired before routing";
            return _impl->finish(std::move(result));
        }

        const auto circuitExclusions = _impl->unavailable(
            request.route.serviceName, now);
        auto routeRequest = request.route;
        auto exclusions = circuitExclusions;
        exclusions.insert(attemptedInstances.begin(), attemptedInstances.end());
        routeRequest.excludedInstances = merged(
            routeRequest.excludedInstances, exclusions);
        auto selected = selectRoute(routeRequest);
        if (!selected && !attemptedInstances.empty())
        {
            routeRequest = request.route;
            routeRequest.excludedInstances = merged(
                routeRequest.excludedInstances, circuitExclusions);
            selected = selectRoute(routeRequest);
        }
        if (!selected || !selected.instance)
        {
            if (!circuitExclusions.empty())
            {
                auto probe = request.route;
                if (selectRoute(probe))
                {
                    result.status = InvocationStatus::circuitOpen;
                    result.code = "all-routes-circuit-open";
                    result.detail = "Service routes exist but their instance circuits are open";
                    return _impl->finish(std::move(result));
                }
            }
            result.status = InvocationStatus::noRoute;
            result.code = !routeFailure.empty() ? "route-failure" :
                          selected.detail.empty() ? "no-route" :
                          ServiceDirectory::toString(selected.status);
            result.detail = selected.detail.empty()
                                ? "No eligible service instance route"
                                : selected.detail;
            return _impl->finish(std::move(result));
        }

        const auto reservation = _impl->reserve(
            selected.instance->advertisement, now);
        if (reservation == Impl::Reservation::capacityExceeded)
        {
            result.status = InvocationStatus::circuitCapacityExceeded;
            result.code = "circuit-capacity-exceeded";
            result.detail = "Per-instance circuit registry has no evictable entry";
            return _impl->finish(std::move(result));
        }
        if (reservation == Impl::Reservation::unavailable)
        {
            attemptedInstances.insert({
                selected.instance->advertisement.instanceId,
                selected.instance->advertisement.runtimeId,
                selected.instance->advertisement.runtimeIncarnation});
            --attempt;
            continue;
        }

        AttemptResult attemptResult;
        try
        {
            attemptResult = invocation({*selected.instance, attempt,
                remaining(deadline, _impl->clock()), request.operation,
                request.idempotencyKey});
        }
        catch (const std::exception& exception)
        {
            attemptResult = AttemptResult::retryable(
                "invoker-exception", exception.what());
        }
        catch (...)
        {
            attemptResult = AttemptResult::retryable(
                "invoker-exception", "Unknown invocation exception");
        }
        const auto completedAt = _impl->clock();
        _impl->complete(selected.instance->advertisement, attemptResult,
                        completedAt);
        {
            std::lock_guard<std::mutex> lock(_impl->mutex);
            ++_impl->attempts;
        }
        result.attempts = attempt;
        result.instance = selected.instance;
        result.history.push_back({attempt,
            selected.instance->advertisement.instanceId,
            selected.instance->advertisement.runtimeId,
            selected.instance->advertisement.runtimeIncarnation,
            attemptResult.disposition, attemptResult.code});

        if (cancellation && cancellation())
        {
            result.status = InvocationStatus::cancelled;
            result.code = "cancelled";
            result.detail = "Invocation was cancelled during an attempt";
            return _impl->finish(std::move(result));
        }

        if (completedAt >= deadline)
        {
            result.status = InvocationStatus::deadlineExceeded;
            result.code = "deadline-exceeded";
            result.detail = "Invocation attempt completed after its deadline";
            return _impl->finish(std::move(result));
        }
        if (attemptResult.disposition == AttemptDisposition::succeeded)
        {
            result.status = InvocationStatus::succeeded;
            result.payload = std::move(attemptResult.payload);
            result.code.clear();
            result.detail = "Invocation succeeded";
            return _impl->finish(std::move(result));
        }

        result.code = attemptResult.code;
        result.detail = attemptResult.detail;
        const bool canRetry =
            attemptResult.disposition == AttemptDisposition::retryableFailure &&
            retrySafe && attempt < _impl->policy.maximumAttempts;
        if (!canRetry)
        {
            result.status = InvocationStatus::failed;
            if (!retrySafe &&
                attemptResult.disposition == AttemptDisposition::retryableFailure)
                result.detail += " (retry suppressed for non-idempotent operation)";
            return _impl->finish(std::move(result));
        }

        attemptedInstances.insert({
            selected.instance->advertisement.instanceId,
            selected.instance->advertisement.runtimeId,
            selected.instance->advertisement.runtimeIncarnation});
        const auto delay = _impl->backoff(attempt);
        const auto budget = remaining(deadline, _impl->clock());
        if (delay >= budget)
        {
            result.status = InvocationStatus::deadlineExceeded;
            result.code = "deadline-exceeded";
            result.detail = "Retry backoff would exhaust the invocation deadline";
            return _impl->finish(std::move(result));
        }
        {
            std::lock_guard<std::mutex> lock(_impl->mutex);
            ++_impl->retries;
        }
        if (delay.count() > 0) _impl->sleeper(delay);
    }

    result.status = InvocationStatus::failed;
    if (result.code.empty()) result.code = "attempts-exhausted";
    if (result.detail.empty()) result.detail = "Invocation attempts exhausted";
    return _impl->finish(std::move(result));
}

Snapshot Client::snapshot() const
{
    const auto now = _impl->clock();
    std::lock_guard<std::mutex> lock(_impl->mutex);
    _impl->prune(now);
    Snapshot result;
    result.calls = _impl->calls;
    result.succeeded = _impl->succeeded;
    result.failed = _impl->failed;
    result.attempts = _impl->attempts;
    result.retries = _impl->retries;
    result.noRoute = _impl->noRoute;
    result.circuitRejected = _impl->circuitRejected;
    result.deadlineExceeded = _impl->deadlineExceeded;
    result.cancelled = _impl->cancelled;
    result.circuits.reserve(_impl->circuits.size());
    for (const auto& [key, circuit] : _impl->circuits)
    {
        auto state = CircuitState::closed;
        if (circuit.openedAt)
            state = now - *circuit.openedAt >=
                            _impl->policy.circuitResetTimeout
                        ? CircuitState::halfOpen
                        : CircuitState::open;
        result.circuits.push_back({std::get<0>(key), std::get<1>(key),
            std::get<2>(key), std::get<3>(key), state, circuit.failures,
            circuit.probeInFlight});
    }
    return result;
}

bool Client::resetCircuit(const std::string& serviceName,
                          const std::string& instanceId)
{
    const auto now = _impl->clock();
    std::lock_guard<std::mutex> lock(_impl->mutex);
    bool changed = false;
    for (auto& [key, circuit] : _impl->circuits)
    {
        if (std::get<0>(key) != serviceName ||
            std::get<1>(key) != instanceId)
            continue;
        circuit.failures = 0;
        circuit.openedAt.reset();
        circuit.probeInFlight = false;
        circuit.lastTouched = now;
        changed = true;
    }
    return changed;
}
} // namespace PocoDDS::ServiceClient
