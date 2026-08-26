#include "PocoDDS/Health/Health.h"
#include "PocoDDS/Lifecycle/LifecycleRuntimeService.h"
#include "PocoDDS/Lifecycle/MaintenanceStore.h"
#include "PocoDDS/Lifecycle/SqliteMaintenanceStore.h"
#include "PocoDDS/ManagementAuth/IdentityService.h"
#include "PocoDDS/ServiceDependency/ServiceDependencyRuntimeService.h"

#include <Poco/ClassLibrary.h>
#include <Poco/Delegate.h>
#include <Poco/Exception.h>
#include <Poco/JSON/Array.h>
#include <Poco/JSON/Object.h>
#include <Poco/JSON/Parser.h>
#include <Poco/Net/HTTPRequest.h>
#include <Poco/Net/HTTPResponse.h>
#include <Poco/Net/HTTPRequestHandler.h>
#include <Poco/Net/HTTPServerRequest.h>
#include <Poco/Net/HTTPServerResponse.h>
#include <Poco/OSP/Bundle.h>
#include <Poco/OSP/BundleActivator.h>
#include <Poco/OSP/BundleContext.h>
#include <Poco/OSP/BundleLifecycleGuard.h>
#include <Poco/OSP/Properties.h>
#include <Poco/OSP/PreferencesService.h>
#include <Poco/OSP/ServiceFinder.h>
#include <Poco/OSP/ServiceRef.h>
#include <Poco/OSP/ServiceRegistry.h>
#include <Poco/OSP/Web/WebRequestHandlerFactory.h>
#include <Poco/OSP/SystemEvents.h>
#include <Poco/Path.h>
#include <Poco/String.h>
#include <Poco/Timestamp.h>
#include <Poco/URI.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cctype>
#include <functional>
#include <map>
#include <mutex>
#include <optional>
#include <set>
#include <sstream>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

namespace PocoDDS::Lifecycle
{
namespace
{
constexpr const char* READ_PERMISSION = "resource.read";
constexpr const char* MANAGE_PERMISSION = "bundle.manage";
constexpr std::size_t MAX_PLANS = 128;
constexpr std::size_t MAX_OPEN_PLANS = 64;
constexpr const char* DEFAULT_MANAGEABLE_BUNDLES =
    "pdr.service.*,pdr.device.*,pdr.alert.*,pdr.plugin.*";

std::int64_t nowMicroseconds()
{
    return Poco::Timestamp().epochMicroseconds();
}

bool validIdentifier(const std::string& value)
{
    return !value.empty() && value.size() <= 128 &&
           std::all_of(value.begin(), value.end(), [](unsigned char ch) {
               return std::isalnum(ch) || ch == '.' || ch == '_' || ch == '-' ||
                      ch == ':';
           });
}

std::vector<std::string> splitPatterns(const std::string& encoded)
{
    std::vector<std::string> result;
    std::size_t begin = 0;
    while (begin <= encoded.size())
    {
        const auto end = encoded.find(',', begin);
        auto value = encoded.substr(begin, end == std::string::npos
            ? std::string::npos : end - begin);
        Poco::trimInPlace(value);
        if (!value.empty()) result.push_back(std::move(value));
        if (end == std::string::npos) break;
        begin = end + 1;
    }
    if (result.empty())
        throw Poco::InvalidArgumentException(
            "pdr.management.manageableBundles must not be empty");
    return result;
}

bool matchesPattern(const std::string& value, const std::string& pattern)
{
    if (pattern.back() != '*') return value == pattern;
    return value.rfind(pattern.substr(0, pattern.size() - 1), 0) == 0;
}

std::vector<Poco::OSP::Bundle::Ptr> blockManageableBundles(
    const Poco::OSP::BundleContext::Ptr& context,
    const std::vector<std::string>& patterns)
{
    std::vector<Poco::OSP::Bundle::Ptr> bundles;
    context->listBundles(bundles);
    std::vector<Poco::OSP::Bundle::Ptr> blocked;
    for (auto& bundle : bundles)
    {
        if (bundle->symbolicName() == context->thisBundle()->symbolicName() ||
            bundle->symbolicName() ==
                ServiceDependency::ServiceDependencyRuntimeService::SERVICE_NAME)
            continue;
        if (std::any_of(patterns.begin(), patterns.end(), [&](const auto& pattern) {
                return matchesPattern(bundle->symbolicName(), pattern);
            }))
        {
            bundle->setAutoStartBlocked(true);
            blocked.push_back(bundle);
        }
    }
    return blocked;
}

void prepare(Poco::Net::HTTPServerResponse& response)
{
    response.setContentType("application/json; charset=utf-8");
    response.set("Cache-Control", "no-store");
    response.set("Pragma", "no-cache");
    response.set("X-Content-Type-Options", "nosniff");
}

void send(Poco::Net::HTTPServerResponse& response,
          Poco::Net::HTTPResponse::HTTPStatus status,
          const Poco::JSON::Object& body)
{
    prepare(response);
    response.setStatus(status);
    body.stringify(response.send());
}

void sendError(Poco::Net::HTTPServerResponse& response,
               Poco::Net::HTTPResponse::HTTPStatus status,
               const std::string& code,
               const std::string& message)
{
    Poco::JSON::Object body;
    body.set("code", code);
    body.set("error", message);
    send(response, status, body);
}

std::optional<std::string> authorize(
    const Poco::OSP::BundleContext::Ptr& context,
    Poco::Net::HTTPServerRequest& request,
    Poco::Net::HTTPServerResponse& response,
    const std::string& permission)
{
    const auto reference = context->registry().findByName(
        PocoDDS::ManagementAuth::IdentityService::SERVICE_NAME);
    if (!reference)
    {
        sendError(response, Poco::Net::HTTPResponse::HTTP_SERVICE_UNAVAILABLE,
                  "LIFECYCLE_IDENTITY_UNAVAILABLE",
                  "Management identity service is unavailable");
        return std::nullopt;
    }
    const auto identity = reference->castedInstance<
        PocoDDS::ManagementAuth::IdentityService>();
    const auto matched = identity->authenticateAuthorizationHeader(
        request.get("Authorization", ""));
    if (!matched)
    {
        if (!identity->snapshot().required) return "development-anonymous";
        response.set("WWW-Authenticate", "Bearer realm=\"pdr-lifecycle\"");
        sendError(response, Poco::Net::HTTPResponse::HTTP_UNAUTHORIZED,
                  "LIFECYCLE_AUTHENTICATION_REQUIRED",
                  "A valid management Bearer token is required");
        return std::nullopt;
    }
    if (!matched->authorized(permission))
    {
        sendError(response, Poco::Net::HTTPResponse::HTTP_FORBIDDEN,
                  "LIFECYCLE_PERMISSION_DENIED",
                  "Authenticated principal lacks " + permission);
        return std::nullopt;
    }
    response.set("X-PDR-Management-Principal", matched->id);
    return matched->id;
}

Poco::JSON::Object::Ptr drainJson(const DrainSnapshot& value)
{
    Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
    item->set("state", toString(value.state));
    item->set("accepting", value.accepting);
    item->set("inFlight", static_cast<Poco::UInt64>(value.inFlight));
    item->set("generation", value.generation);
    return item;
}

Poco::JSON::Object::Ptr stepJson(const MaintenanceStep& value)
{
    Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
    item->set("phase", value.phase);
    item->set("target", value.target);
    item->set("succeeded", value.succeeded);
    item->set("detail", value.detail);
    return item;
}

Poco::JSON::Object::Ptr planJson(const MaintenancePlan& value)
{
    Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
    item->set("id", value.id);
    item->set("target", value.target);
    item->set("status", toString(value.status));
    item->set("desiredState",
              value.status == MaintenanceStatus::drained ||
                      value.status == MaintenanceStatus::restoreRolledBack
                  ? "stopped"
                  : value.status == MaintenanceStatus::restored ||
                            value.status == MaintenanceStatus::rolledBack
                        ? "active"
                        : "transitioning");
    item->set("rollbackComplete", value.rollbackComplete);
    item->set("code", value.code);
    item->set("detail", value.detail);
    item->set("createdMicroseconds", value.createdMicroseconds);
    item->set("updatedMicroseconds", value.updatedMicroseconds);
    item->set("recoveryAttempts", value.recoveryAttempts);
    Poco::JSON::Array::Ptr consumers = new Poco::JSON::Array;
    for (const auto& consumer : value.consumers) consumers->add(consumer);
    item->set("consumers", consumers);
    Poco::JSON::Array::Ptr steps = new Poco::JSON::Array;
    for (const auto& step : value.steps) steps->add(stepJson(step));
    item->set("steps", steps);
    return item;
}

class RuntimeServiceImpl final : public LifecycleRuntimeService,
                                 public Health::IHealthContributor
{
public:
    RuntimeServiceImpl(Poco::OSP::BundleContext::Ptr context,
                       std::unique_ptr<MaintenanceStore> store)
        : _context(std::move(context)),
          _owner(_context->thisBundle()->symbolicName()),
          _store(std::move(store))
    {
        if (!_store)
            throw Poco::InvalidArgumentException(
                "Lifecycle maintenance store is required");
        _store->initialize();
        _plans = _store->history(MAX_PLANS);
        for (const auto& open : _store->incomplete())
        {
            const auto found = std::find_if(
                _plans.begin(), _plans.end(), [&](const auto& item) {
                    return item.id == open.id;
                });
            if (found == _plans.end()) _plans.push_back(open);
        }
        std::sort(_plans.begin(), _plans.end(), [](const auto& lhs, const auto& rhs) {
            return std::tie(lhs.createdMicroseconds, lhs.id) <
                   std::tie(rhs.createdMicroseconds, rhs.id);
        });
        for (auto& plan : _plans)
        {
            if (plan.status == MaintenanceStatus::draining)
                plan.status = MaintenanceStatus::drainRecoveryPending;
            else if (plan.status == MaintenanceStatus::restoring)
                plan.status = MaintenanceStatus::restoreRecoveryPending;
            else continue;
            plan.rollbackComplete = false;
            plan.code = "LIFECYCLE_CRASH_RECOVERY_PENDING";
            plan.detail =
                "Runtime stopped while maintenance was in progress; topology recovery is pending";
            plan.steps.push_back({"restart-recovery-detected", plan.target, false,
                                  "Durable maintenance state requires topology reconciliation after Runtime restart"});
            touch(plan);
            _store->save(plan);
        }
        for (const auto& plan : _plans)
            if (desiredStopped(plan.status)) setDesiredStopped(plan, true);
    }

    MaintenanceOperation drain(const std::string& target,
                               std::chrono::milliseconds timeout,
                               const std::string& requestId) override
    {
        if (!validIdentifier(target) || protectedTarget(target))
            throw Poco::InvalidArgumentException("invalid maintenance target");
        if (!validIdentifier(requestId))
            throw Poco::InvalidArgumentException("invalid maintenance request ID");
        if (timeout < std::chrono::milliseconds(10) ||
            timeout > std::chrono::seconds(30))
            throw Poco::InvalidArgumentException(
                "timeoutMilliseconds must be between 10 and 30000");

        std::lock_guard<std::mutex> lock(_mutex);
        const auto fingerprint = "drain:" + target + ":" +
                                 std::to_string(timeout.count());
        if (const auto replay = replayFor(requestId, fingerprint)) return *replay;
        ensureRunning();
        const auto openPlans = std::count_if(
            _plans.begin(), _plans.end(), [](const auto& item) {
                return item.status == MaintenanceStatus::drained ||
                       item.status == MaintenanceStatus::restoreRolledBack ||
                       item.status == MaintenanceStatus::draining ||
                       item.status == MaintenanceStatus::restoring ||
                       recoveryPending(item.status);
            });
        if (openPlans >= MAX_OPEN_PLANS)
            throw Poco::IllegalStateException(
                "maximum open lifecycle maintenance plans reached");

        MaintenancePlan plan;
        plan.id = _store->allocatePlanId();
        plan.target = target;
        plan.status = MaintenanceStatus::draining;
        plan.code = "DRAIN_IN_PROGRESS";
        plan.detail = "Transactional drain is in progress";
        plan.createdMicroseconds = nowMicroseconds();
        plan.updatedMicroseconds = plan.createdMicroseconds;
        _store->save(plan);
        std::vector<std::string> quiesced;
        std::vector<std::string> stopped;
        try
        {
            auto bundle = mutableBundle(target);
            if (!bundle || bundle->state() != Poco::OSP::Bundle::BUNDLE_ACTIVE)
                throw Poco::IllegalStateException(
                    "maintenance target must be active", target);

            const auto dependency = dependencyService();
            plan.consumers = maintenanceConsumers(dependency, target);
            checkpoint(plan);
            for (const auto& consumer : plan.consumers)
            {
                auto consumerBundle = mutableBundle(consumer);
                if (!consumerBundle ||
                    consumerBundle->state() != Poco::OSP::Bundle::BUNDLE_ACTIVE)
                    throw Poco::IllegalStateException(
                        "impacted Consumer changed state during preflight", consumer);
                if (!participant(consumer))
                    throw Poco::NotFoundException(
                        "active Consumer has no DrainParticipant", consumer);
                plan.steps.push_back(
                    {"preflight", consumer, true, "DrainParticipant available"});
                checkpoint(plan);
            }

            const auto deadline = std::chrono::steady_clock::now() + timeout;
            for (const auto& consumer : plan.consumers)
            {
                const auto now = std::chrono::steady_clock::now();
                const auto remaining = now < deadline
                    ? std::chrono::duration_cast<std::chrono::milliseconds>(deadline - now)
                    : std::chrono::milliseconds::zero();
                auto current = participant(consumer);
                if (!current)
                    throw Poco::NotFoundException(
                        "DrainParticipant disappeared", consumer);
                const auto result = current->quiesce(remaining);
                plan.steps.push_back(
                    {"quiesce", consumer, result.drained, result.detail});
                quiesced.push_back(consumer);
                checkpoint(plan);
                if (!result.drained)
                    throw Poco::TimeoutException("Consumer drain timed out", consumer);
            }

            for (const auto& consumer : plan.consumers)
            {
                auto consumerBundle = mutableBundle(consumer);
                if (!consumerBundle ||
                    consumerBundle->state() != Poco::OSP::Bundle::BUNDLE_ACTIVE)
                    throw Poco::IllegalStateException(
                        "Consumer changed state before stop", consumer);
                consumerBundle->stop();
                stopped.push_back(consumer);
                plan.steps.push_back(
                    {"stop-consumer", consumer, true, "Consumer stopped after drain"});
                checkpoint(plan);
            }

            const auto finalImpact = dependencyService()->analyzeStop(target);
            if (!finalImpact.allowed)
                throw Poco::IllegalStateException(
                    "Provider remains blocked after Consumer drain", target);
            bundle = mutableBundle(target);
            if (!bundle || bundle->state() != Poco::OSP::Bundle::BUNDLE_ACTIVE)
                throw Poco::IllegalStateException(
                    "maintenance target changed state before stop", target);
            bundle->stop();
            plan.steps.push_back(
                {"stop-provider", target, true, "Provider stopped after admission recheck"});
            plan.status = MaintenanceStatus::drained;
            plan.rollbackComplete = true;
            plan.code = "DRAIN_COMPLETE";
            plan.detail = "Provider and impacted Consumers stopped transactionally";
            touch(plan);
            setDesiredStopped(plan, true);
            MaintenanceOperation result{true, false, plan};
            store(plan, requestId, fingerprint, result);
            return result;
        }
        catch (const std::exception& exception)
        {
            setDesiredStopped(plan, false);
            plan.steps.push_back(
                {"failure", target, false, exception.what()});
            const bool rollback = rollbackDrain(quiesced, stopped, plan.steps);
            plan.rollbackComplete = rollback;
            plan.status = rollback ? MaintenanceStatus::rolledBack
                                   : MaintenanceStatus::failed;
            plan.code = rollback ? "DRAIN_ROLLED_BACK"
                                 : "DRAIN_ROLLBACK_INCOMPLETE";
            plan.detail = rollback
                ? "Drain failed and all affected Consumers were restored"
                : "Drain failed and rollback requires operator recovery";
            touch(plan);
            MaintenanceOperation result{false, false, plan};
            store(plan, requestId, fingerprint, result);
            return result;
        }
    }

    MaintenanceOperation restore(const std::string& planId,
                                 const std::string& requestId) override
    {
        if (!validIdentifier(planId) || !validIdentifier(requestId))
            throw Poco::InvalidArgumentException("invalid restore request");
        std::lock_guard<std::mutex> lock(_mutex);
        const auto fingerprint = "restore:" + planId;
        if (const auto replay = replayFor(requestId, fingerprint)) return *replay;
        ensureRunning();
        auto found = std::find_if(_plans.begin(), _plans.end(),
                                  [&](const auto& item) { return item.id == planId; });
        if (found == _plans.end())
            throw Poco::NotFoundException("maintenance plan not found", planId);
        if (found->status != MaintenanceStatus::drained &&
            found->status != MaintenanceStatus::restoreRolledBack)
            throw Poco::IllegalStateException(
                "maintenance plan is not restorable", planId);

        MaintenancePlan plan = *found;
        std::vector<std::string> started;
        bool providerStarted = false;
        setDesiredStopped(plan, false);
        try
        {
            plan.status = MaintenanceStatus::restoring;
            plan.rollbackComplete = false;
            plan.code = "RESTORE_IN_PROGRESS";
            plan.detail = "Transactional restore is in progress";
            checkpoint(plan);
            auto provider = mutableBundle(plan.target);
            if (!provider || provider->state() != Poco::OSP::Bundle::BUNDLE_RESOLVED)
                throw Poco::IllegalStateException(
                    "drained Provider is not resolved", plan.target);
            for (const auto& consumer : plan.consumers)
            {
                const auto bundle = mutableBundle(consumer);
                if (!bundle || bundle->state() != Poco::OSP::Bundle::BUNDLE_RESOLVED)
                    throw Poco::IllegalStateException(
                        "drained Consumer is not resolved", consumer);
            }

            provider->start();
            providerStarted = true;
            plan.steps.push_back(
                {"restore-provider", plan.target, true, "Provider started"});
            checkpoint(plan);
            for (auto consumer = plan.consumers.rbegin();
                 consumer != plan.consumers.rend(); ++consumer)
            {
                auto bundle = mutableBundle(*consumer);
                bundle->start();
                started.push_back(*consumer);
                plan.steps.push_back(
                    {"restore-consumer", *consumer, true, "Consumer started"});
                checkpoint(plan);
            }
            plan.status = MaintenanceStatus::restored;
            plan.rollbackComplete = true;
            plan.code = "RESTORE_COMPLETE";
            plan.detail = "Provider and Consumers restored in dependency order";
            touch(plan);
            *found = plan;
            MaintenanceOperation result{true, false, plan};
            remember(requestId, fingerprint, result);
            return result;
        }
        catch (const std::exception& exception)
        {
            plan.steps.push_back(
                {"restore-failure", plan.target, false, exception.what()});
            bool rollback = true;
            for (auto item = started.rbegin(); item != started.rend(); ++item)
            {
                try
                {
                    auto bundle = mutableBundle(*item);
                    if (bundle && bundle->state() == Poco::OSP::Bundle::BUNDLE_ACTIVE)
                        bundle->stop();
                    plan.steps.push_back(
                        {"rollback-restore-consumer", *item, true,
                         "Consumer returned to drained state"});
                }
                catch (const std::exception& rollbackError)
                {
                    rollback = false;
                    plan.steps.push_back(
                        {"rollback-restore-consumer", *item, false,
                         rollbackError.what()});
                }
            }
            if (providerStarted)
            {
                try
                {
                    auto provider = mutableBundle(plan.target);
                    if (provider && provider->state() == Poco::OSP::Bundle::BUNDLE_ACTIVE)
                        provider->stop();
                    plan.steps.push_back(
                        {"rollback-restore-provider", plan.target, true,
                         "Provider returned to drained state"});
                }
                catch (const std::exception& rollbackError)
                {
                    rollback = false;
                    plan.steps.push_back(
                        {"rollback-restore-provider", plan.target, false,
                         rollbackError.what()});
                }
            }
            plan.rollbackComplete = rollback;
            plan.status = rollback ? MaintenanceStatus::restoreRolledBack
                                   : MaintenanceStatus::failed;
            plan.code = rollback ? "RESTORE_ROLLED_BACK"
                                 : "RESTORE_ROLLBACK_INCOMPLETE";
            plan.detail = rollback
                ? "Restore failed and the drained maintenance state was preserved"
                : "Restore failed and rollback requires operator recovery";
            touch(plan);
            if (rollback) setDesiredStopped(plan, true);
            *found = plan;
            MaintenanceOperation result{false, false, plan};
            remember(requestId, fingerprint, result);
            return result;
        }
    }

    MaintenanceOperation recover(const std::string& planId,
                                 const std::string& requestId) override
    {
        if (!validIdentifier(planId) || !validIdentifier(requestId))
            throw Poco::InvalidArgumentException("invalid recovery request");
        std::lock_guard<std::mutex> lock(_mutex);
        const auto fingerprint = "recover:" + planId;
        if (const auto replay = replayFor(requestId, fingerprint)) return *replay;
        ensureRunning();
        auto found = std::find_if(_plans.begin(), _plans.end(),
                                  [&](const auto& item) { return item.id == planId; });
        if (found == _plans.end())
            throw Poco::NotFoundException("maintenance plan not found", planId);
        if (!recoveryPending(found->status))
            throw Poco::IllegalStateException(
                "maintenance plan has no pending crash recovery", planId);
        auto operation = recoverPlan(*found);
        _store->complete(*found,
            {requestId, fingerprint, operation});
        return operation;
    }

    void recoverIncomplete()
    {
        std::lock_guard<std::mutex> lock(_mutex);
        if (_stopping.load()) return;
        for (auto& plan : _plans)
        {
            if (!recoveryPending(plan.status)) continue;
            const auto operation = recoverPlan(plan);
            _store->save(plan);
            _context->logger().information(
                "Lifecycle crash recovery plan=" + plan.id +
                " status=" + toString(plan.status) +
                " succeeded=" + (operation.succeeded ? "true" : "false"));
        }
    }

    std::vector<MaintenancePlan> plans() const override
    {
        std::lock_guard<std::mutex> lock(_mutex);
        return _plans;
    }

    std::vector<DrainParticipantSnapshot> participants() const override
    {
        std::vector<DrainParticipantSnapshot> result;
        const auto references = _context->registry().find(
            std::string(DrainParticipantService::PROPERTY_KIND) + " == true");
        for (const auto& reference : references)
        {
            try
            {
                const auto service = reference->castedInstance<DrainParticipantService>();
                result.push_back({service->owner(), service->drainSnapshot()});
            }
            catch (...) {}
        }
        std::sort(result.begin(), result.end(), [](const auto& lhs, const auto& rhs) {
            return lhs.owner < rhs.owner;
        });
        return result;
    }

    Poco::OSP::BundleLifecycleDecision desiredStartDecision(
        const std::string& symbolicName) const
    {
        std::lock_guard<std::mutex> lock(_desiredMutex);
        if (_desiredStoppedOwners.count(symbolicName) == 0)
            return {true, {}, {}, {}};
        return {false, "PDR-BUNDLE-DESIRED-STATE-STOPPED",
                "Bundle belongs to a durable drained maintenance plan; restore the plan before starting it",
                {symbolicName}};
    }

    Poco::OSP::BundleLifecycleDecision desiredStopDecision(
        const std::string&) const
    {
        return {true, {}, {}, {}};
    }

    void releaseStartupAdmission(
        const std::vector<Poco::OSP::Bundle::Ptr>& preblocked)
    {
        std::lock_guard<std::mutex> lock(_desiredMutex);
        for (const auto& item : preblocked)
        {
            Poco::OSP::Bundle::Ptr bundle = item;
            bundle->setAutoStartBlocked(
                _desiredStoppedOwners.count(bundle->symbolicName()) != 0);
        }
    }

    Health::Report health() const override
    {
        const auto values = plans();
        std::vector<std::string> affected;
        std::size_t pending = 0;
        std::size_t failed = 0;
        std::size_t desiredStoppedCount = 0;
        for (const auto& plan : values)
        {
            if (recoveryPending(plan.status))
            {
                ++pending;
                affected.push_back(plan.target);
            }
            else if (plan.status == MaintenanceStatus::failed)
            {
                ++failed;
                affected.push_back(plan.target);
            }
            else if (desiredStopped(plan.status))
            {
                ++desiredStoppedCount;
                for (const auto& owner : desiredOwners(plan))
                {
                    const auto bundle = mutableBundle(owner);
                    if (!bundle || bundle->state() != Poco::OSP::Bundle::BUNDLE_RESOLVED)
                        affected.push_back(owner);
                }
            }
        }
        std::sort(affected.begin(), affected.end());
        affected.erase(std::unique(affected.begin(), affected.end()),
                       affected.end());
        Health::Report report;
        report.component = "lifecycle-maintenance";
        report.status = affected.empty() ? Health::Status::up : Health::Status::degraded;
        report.detail = std::to_string(values.size()) + " maintenance plan(s); " +
                        std::to_string(pending) + " crash recovery pending; " +
                        std::to_string(failed) + " incomplete rollback(s); " +
                        std::to_string(desiredStoppedCount) +
                        " durable desired-stopped plan(s)";
        report.affected = std::move(affected);
        if (report.status == Health::Status::degraded)
        {
            report.code = pending > 0
                ? "PDR-HEALTH-LIFECYCLE-RECOVERY_PENDING"
                : failed > 0
                    ? "PDR-HEALTH-LIFECYCLE-ROLLBACK_INCOMPLETE"
                    : "PDR-HEALTH-LIFECYCLE-DESIRED-STATE-MISMATCH";
            report.remediation = pending > 0
                ? "Retry the persisted plan with action recover after required Bundles are available."
                : failed > 0
                    ? "Inspect the failed maintenance plan and restore affected Bundles in dependency order."
                    : "Restore the desired-stopped plan or inspect Bundles that are missing or unexpectedly active.";
        }
        return report;
    }

    void shutdown() noexcept
    {
        std::lock_guard<std::mutex> lock(_mutex);
        _stopping.store(true);
    }

private:
    static bool desiredStopped(MaintenanceStatus status) noexcept
    {
        return status == MaintenanceStatus::drained ||
               status == MaintenanceStatus::restoreRolledBack;
    }

    bool protectedTarget(const std::string& target) const
    {
        return target == _owner || target ==
                   ServiceDependency::ServiceDependencyRuntimeService::SERVICE_NAME ||
               target.rfind("osp.", 0) == 0 || target.rfind("poco.", 0) == 0 ||
               target.rfind("pdr.platform.", 0) == 0;
    }

    static std::vector<std::string> desiredOwners(const MaintenancePlan& plan)
    {
        std::vector<std::string> result = plan.consumers;
        result.push_back(plan.target);
        std::sort(result.begin(), result.end());
        result.erase(std::unique(result.begin(), result.end()), result.end());
        return result;
    }

    void setDesiredStopped(const MaintenancePlan& plan, bool blocked)
    {
        const auto owners = desiredOwners(plan);
        std::lock_guard<std::mutex> lock(_desiredMutex);
        for (const auto& owner : owners)
        {
            if (blocked)
                _desiredStoppedOwners[owner].insert(plan.id);
            else
            {
                const auto found = _desiredStoppedOwners.find(owner);
                if (found != _desiredStoppedOwners.end())
                {
                    found->second.erase(plan.id);
                    if (found->second.empty()) _desiredStoppedOwners.erase(found);
                }
            }
            auto bundle = mutableBundle(owner);
            if (bundle)
                bundle->setAutoStartBlocked(
                    _desiredStoppedOwners.count(owner) != 0);
        }
    }

    void ensureRunning() const
    {
        if (_stopping.load())
            throw Poco::IllegalStateException("Lifecycle runtime is stopping");
    }

    Poco::OSP::Bundle::Ptr mutableBundle(const std::string& owner) const
    {
        return _context->findBundle(owner);
    }

    ServiceDependency::ServiceDependencyRuntimeService::Ptr
    dependencyService() const
    {
        return Poco::OSP::ServiceFinder::find<
            ServiceDependency::ServiceDependencyRuntimeService>(_context);
    }

    DrainParticipantService::Ptr participant(const std::string& owner) const
    {
        const auto reference = _context->registry().findByName(
            std::string(DrainParticipantService::SERVICE_PREFIX) + owner);
        if (!reference ||
            reference->properties().get(DrainParticipantService::PROPERTY_OWNER, "") !=
                owner)
            return nullptr;
        return reference->castedInstance<DrainParticipantService>();
    }

    std::vector<std::string> maintenanceConsumers(
        const ServiceDependency::ServiceDependencyRuntimeService::Ptr& dependency,
        const std::string& target) const
    {
        std::set<std::string> visited;
        std::set<std::string> visiting;
        std::vector<std::string> ordered;
        std::function<void(const std::string&)> visit =
            [&](const std::string& provider) {
                if (visited.count(provider) != 0) return;
                if (!visiting.insert(provider).second)
                    throw Poco::IllegalStateException(
                        "cyclic active Service dependency cannot be drained safely",
                        provider);
                const auto impact = dependency->analyzeStop(provider);
                for (const auto& consumer : impact.affectedConsumers)
                {
                    if (consumer == target || visiting.count(consumer) != 0)
                        throw Poco::IllegalStateException(
                            "cyclic active Service dependency cannot be drained safely",
                            consumer);
                    visit(consumer);
                }
                visiting.erase(provider);
                if (visited.insert(provider).second && provider != target)
                    ordered.push_back(provider);
            };
        visit(target);
        return ordered;
    }

    bool rollbackDrain(const std::vector<std::string>& quiesced,
                       const std::vector<std::string>& stopped,
                       std::vector<MaintenanceStep>& steps) noexcept
    {
        bool complete = true;
        for (auto item = stopped.rbegin(); item != stopped.rend(); ++item)
        {
            try
            {
                auto bundle = mutableBundle(*item);
                if (bundle && bundle->state() == Poco::OSP::Bundle::BUNDLE_RESOLVED)
                    bundle->start();
                if (!bundle || bundle->state() != Poco::OSP::Bundle::BUNDLE_ACTIVE)
                    throw Poco::IllegalStateException(
                        "Consumer did not return to active", *item);
                steps.push_back(
                    {"rollback-start-consumer", *item, true, "Consumer restarted"});
            }
            catch (const std::exception& exception)
            {
                complete = false;
                steps.push_back(
                    {"rollback-start-consumer", *item, false, exception.what()});
            }
        }
        for (const auto& owner : quiesced)
        {
            if (std::find(stopped.begin(), stopped.end(), owner) != stopped.end())
                continue;
            try
            {
                auto current = participant(owner);
                if (!current)
                    throw Poco::NotFoundException(
                        "DrainParticipant unavailable during rollback", owner);
                current->resume();
                steps.push_back(
                    {"rollback-resume-consumer", owner, true,
                     "Consumer acceptance resumed"});
            }
            catch (const std::exception& exception)
            {
                complete = false;
                steps.push_back(
                    {"rollback-resume-consumer", owner, false, exception.what()});
            }
        }
        return complete;
    }

    MaintenanceOperation recoverPlan(MaintenancePlan& plan)
    {
        const bool restoring =
            plan.status == MaintenanceStatus::restoreRecoveryPending;
        ++plan.recoveryAttempts;
        plan.steps.push_back({"crash-recovery", plan.target, false,
                              "Restoring the pre-crash Bundle topology"});
        checkpoint(plan);
        try
        {
            startForRecovery(plan.target, plan.steps, "recover-provider");
            checkpoint(plan);
            for (auto consumer = plan.consumers.rbegin();
                 consumer != plan.consumers.rend(); ++consumer)
            {
                startForRecovery(*consumer, plan.steps, "recover-consumer");
                checkpoint(plan);
            }
            for (const auto& owner : plan.consumers)
            {
                auto current = participant(owner);
                if (!current) continue;
                current->resume();
                plan.steps.push_back({"recover-resume", owner, true,
                                      "Consumer acceptance is enabled"});
            }
            plan.status = restoring ? MaintenanceStatus::restored
                                    : MaintenanceStatus::rolledBack;
            plan.rollbackComplete = true;
            plan.code = restoring ? "RESTORE_CRASH_RECOVERED"
                                  : "DRAIN_CRASH_RECOVERED";
            plan.detail = restoring
                ? "Interrupted restore completed after Runtime restart"
                : "Interrupted drain was safely rolled back after Runtime restart";
            touch(plan);
            return {true, false, plan};
        }
        catch (const std::exception& exception)
        {
            plan.steps.push_back({"crash-recovery-failure", plan.target, false,
                                  exception.what()});
            plan.rollbackComplete = false;
            plan.code = "LIFECYCLE_CRASH_RECOVERY_INCOMPLETE";
            plan.detail =
                "Persisted maintenance intent could not restore the Bundle topology";
            touch(plan);
            return {false, false, plan};
        }
    }

    void startForRecovery(const std::string& owner,
                          std::vector<MaintenanceStep>& steps,
                          const std::string& phase)
    {
        auto bundle = mutableBundle(owner);
        if (!bundle)
            throw Poco::NotFoundException(
                "Bundle required by crash recovery was not found", owner);
        if (bundle->state() == Poco::OSP::Bundle::BUNDLE_RESOLVED)
            bundle->start();
        if (bundle->state() != Poco::OSP::Bundle::BUNDLE_ACTIVE)
            throw Poco::IllegalStateException(
                "Bundle required by crash recovery is not active", owner);
        steps.push_back({phase, owner, true, "Bundle is active"});
    }

    static void touch(MaintenancePlan& plan)
    {
        const auto current = nowMicroseconds();
        plan.updatedMicroseconds =
            std::max(current, plan.createdMicroseconds);
    }

    void checkpoint(MaintenancePlan& plan)
    {
        touch(plan);
        _store->save(plan);
    }

    std::optional<MaintenanceOperation> replayFor(
        const std::string& requestId, const std::string& fingerprint) const
    {
        const auto found = _store->findByRequestId(requestId);
        if (!found) return std::nullopt;
        if (found->fingerprint != fingerprint)
            throw Poco::InvalidArgumentException(
                "maintenance request ID reused with different input");
        auto result = found->operation;
        result.idempotentReplay = true;
        return result;
    }

    void remember(const std::string& requestId, const std::string& fingerprint,
                  const MaintenanceOperation& operation)
    {
        _store->complete(operation.plan,
            {requestId, fingerprint, operation});
    }

    void store(const MaintenancePlan& plan, const std::string& requestId,
               const std::string& fingerprint,
               const MaintenanceOperation& operation)
    {
        _store->complete(plan, {requestId, fingerprint, operation});
        _plans.push_back(plan);
        while (_plans.size() > MAX_PLANS)
        {
            const auto removable = std::find_if(
                _plans.begin(), _plans.end(), [](const auto& item) {
                    return !recoveryPending(item.status) &&
                           !desiredStopped(item.status);
                });
            if (removable == _plans.end()) break;
            _plans.erase(removable);
        }
    }

    Poco::OSP::BundleContext::Ptr _context;
    std::string _owner;
    mutable std::mutex _mutex;
    mutable std::mutex _desiredMutex;
    std::map<std::string, std::set<std::string>> _desiredStoppedOwners;
    std::vector<MaintenancePlan> _plans;
    std::unique_ptr<MaintenanceStore> _store;
    std::atomic<bool> _stopping{false};
};

class DesiredStateGuardImpl final : public Poco::OSP::BundleLifecycleGuard,
                                    public Health::IHealthContributor
{
public:
    explicit DesiredStateGuardImpl(RuntimeServiceImpl* runtime)
        : _runtime(runtime)
    {
        if (!_runtime)
            throw Poco::InvalidArgumentException(
                "Lifecycle desired-state guard requires a runtime service");
    }

    DesiredStateGuardImpl(std::vector<std::string> patterns,
                          std::string failure)
        : _patterns(std::move(patterns)), _failure(std::move(failure))
    {
        if (_patterns.empty() || _failure.empty())
            throw Poco::InvalidArgumentException(
                "Lifecycle desired-state failure guard requires policy and detail");
    }

    Poco::OSP::BundleLifecycleDecision evaluateStart(
        const std::string& symbolicName) const override
    {
        if (_runtime) return _runtime->desiredStartDecision(symbolicName);
        const bool manageable = std::any_of(
            _patterns.begin(), _patterns.end(), [&](const auto& pattern) {
                return matchesPattern(symbolicName, pattern);
            });
        if (!manageable) return {true, {}, {}, {}};
        return {false, "PDR-BUNDLE-DESIRED-STATE-UNAVAILABLE",
                "Durable desired state could not be loaded; lifecycle admission is fail-closed",
                {symbolicName}};
    }

    Poco::OSP::BundleLifecycleDecision evaluateStop(
        const std::string& symbolicName) const override
    {
        return _runtime ? _runtime->desiredStopDecision(symbolicName)
                        : Poco::OSP::BundleLifecycleDecision{true, {}, {}, {}};
    }

    Health::Report health() const override
    {
        if (_runtime) return _runtime->health();
        return {"lifecycle-maintenance", Health::Status::degraded,
                "Durable desired-state store is unavailable: " + _failure,
                "PDR-HEALTH-LIFECYCLE-DESIRED-STATE-UNAVAILABLE",
                "Stop the Runtime, repair or restore the maintenance database, and restart before enabling business Bundles.",
                {"pdr.management.manageableBundles"}};
    }

private:
    RuntimeServiceImpl* _runtime{nullptr};
    std::vector<std::string> _patterns;
    std::string _failure;
};

class Handler final : public Poco::Net::HTTPRequestHandler
{
public:
    explicit Handler(Poco::OSP::BundleContext::Ptr context)
        : _context(std::move(context))
    {
    }

    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        const Poco::URI uri(request.getURI());
        if (uri.getPath() != "/api/v1/lifecycle-maintenance")
        {
            sendError(response, Poco::Net::HTTPResponse::HTTP_NOT_FOUND,
                      "LIFECYCLE_ENDPOINT_NOT_FOUND",
                      "Unknown lifecycle maintenance endpoint");
            return;
        }
        const bool write = request.getMethod() == Poco::Net::HTTPRequest::HTTP_POST;
        if (!write && request.getMethod() != Poco::Net::HTTPRequest::HTTP_GET)
        {
            response.set("Allow", "GET, POST");
            sendError(response, Poco::Net::HTTPResponse::HTTP_METHOD_NOT_ALLOWED,
                      "LIFECYCLE_METHOD_NOT_ALLOWED",
                      "Lifecycle maintenance supports GET and POST");
            return;
        }
        const auto principal = authorize(
            _context, request, response, write ? MANAGE_PERMISSION : READ_PERMISSION);
        if (!principal) return;
        try
        {
            auto service = Poco::OSP::ServiceFinder::find<
                LifecycleRuntimeService>(_context);
            if (!write)
            {
                std::string planId;
                bool seen = false;
                for (const auto& parameter : uri.getQueryParameters())
                {
                    if (parameter.first != "planId" || seen ||
                        !validIdentifier(parameter.second))
                        throw Poco::InvalidArgumentException(
                            "only one valid planId filter is supported");
                    planId = parameter.second;
                    seen = true;
                }
                Poco::JSON::Array::Ptr plans = new Poco::JSON::Array;
                for (const auto& plan : service->plans())
                    if (planId.empty() || plan.id == planId)
                        plans->add(planJson(plan));
                Poco::JSON::Array::Ptr participants = new Poco::JSON::Array;
                for (const auto& participant : service->participants())
                {
                    Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
                    item->set("owner", participant.owner);
                    item->set("drain", drainJson(participant.drain));
                    participants->add(item);
                }
                Poco::JSON::Object body;
                body.set("schemaVersion", 1);
                body.set("principal", *principal);
                body.set("scope", "runtime-process/bundle-lifecycle-maintenance");
                body.set("planCount", static_cast<Poco::UInt64>(plans->size()));
                body.set("participantCount",
                         static_cast<Poco::UInt64>(participants->size()));
                body.set("plans", plans);
                body.set("participants", participants);
                send(response, Poco::Net::HTTPResponse::HTTP_OK, body);
                return;
            }

            if (request.getContentLength64() > 65536)
            {
                sendError(response, Poco::Net::HTTPResponse::HTTP_REQUEST_ENTITY_TOO_LARGE,
                          "LIFECYCLE_REQUEST_TOO_LARGE",
                          "Lifecycle request must not exceed 64 KiB");
                return;
            }
            const auto requestId = request.get("X-PDR-Request-Id", "");
            if (!validIdentifier(requestId))
            {
                sendError(response, Poco::Net::HTTPResponse::HTTP_PRECONDITION_REQUIRED,
                          "LIFECYCLE_REQUEST_ID_REQUIRED",
                          "A valid X-PDR-Request-Id is required");
                return;
            }
            std::string encoded;
            char chunk[4096];
            while (request.stream())
            {
                request.stream().read(chunk, sizeof(chunk));
                const auto count = request.stream().gcount();
                if (count <= 0) break;
                if (encoded.size() + static_cast<std::size_t>(count) > 65536)
                {
                    sendError(
                        response,
                        Poco::Net::HTTPResponse::HTTP_REQUEST_ENTITY_TOO_LARGE,
                        "LIFECYCLE_REQUEST_TOO_LARGE",
                        "Lifecycle request must not exceed 64 KiB");
                    return;
                }
                encoded.append(chunk, static_cast<std::size_t>(count));
            }
            Poco::JSON::Object::Ptr body;
            try
            {
                body = Poco::JSON::Parser().parse(encoded)
                           .extract<Poco::JSON::Object::Ptr>();
            }
            catch (const Poco::Exception& exception)
            {
                throw Poco::InvalidArgumentException(
                    "invalid lifecycle JSON object", exception.displayText());
            }
            if (!body) throw Poco::InvalidArgumentException("JSON object required");
            const std::set<std::string> allowed{
                "action", "target", "planId", "timeoutMilliseconds"};
            for (const auto& name : body->getNames())
                if (allowed.count(name) == 0)
                    throw Poco::InvalidArgumentException(
                        "unknown lifecycle request field", name);
            const auto action = body->optValue<std::string>("action", "");
            MaintenanceOperation operation;
            if (action == "drain")
            {
                if (!body->has("target") || body->has("planId"))
                    throw Poco::InvalidArgumentException(
                        "drain requires target and forbids planId");
                operation = service->drain(
                    body->getValue<std::string>("target"),
                    std::chrono::milliseconds(
                        body->optValue<int>("timeoutMilliseconds", 5000)),
                    requestId);
            }
            else if (action == "restore")
            {
                if (!body->has("planId") || body->has("target") ||
                    body->has("timeoutMilliseconds"))
                    throw Poco::InvalidArgumentException(
                        "restore requires planId only");
                operation = service->restore(
                    body->getValue<std::string>("planId"), requestId);
            }
            else if (action == "recover")
            {
                if (!body->has("planId") || body->has("target") ||
                    body->has("timeoutMilliseconds"))
                    throw Poco::InvalidArgumentException(
                        "recover requires planId only");
                operation = service->recover(
                    body->getValue<std::string>("planId"), requestId);
            }
            else
                throw Poco::InvalidArgumentException(
                    "action must be drain, restore or recover");

            Poco::JSON::Object result;
            result.set("schemaVersion", 1);
            result.set("principal", *principal);
            result.set("scope", "runtime-process/bundle-lifecycle-maintenance");
            result.set("succeeded", operation.succeeded);
            result.set("idempotentReplay", operation.idempotentReplay);
            result.set("requestId", requestId);
            result.set("plan", planJson(operation.plan));
            _context->logger().information(
                "Lifecycle maintenance " + action + " by " + *principal +
                " requestId=" + requestId + " plan=" + operation.plan.id +
                " status=" + toString(operation.plan.status) +
                " replay=" + (operation.idempotentReplay ? "true" : "false"));
            const auto status = operation.succeeded
                ? Poco::Net::HTTPResponse::HTTP_OK
                : (operation.plan.status == MaintenanceStatus::failed ||
                   recoveryPending(operation.plan.status))
                      ? Poco::Net::HTTPResponse::HTTP_SERVICE_UNAVAILABLE
                      : Poco::Net::HTTPResponse::HTTP_CONFLICT;
            send(response, status, result);
        }
        catch (const Poco::NotFoundException& exception)
        {
            sendError(response, Poco::Net::HTTPResponse::HTTP_NOT_FOUND,
                      "LIFECYCLE_RESOURCE_NOT_FOUND", exception.displayText());
        }
        catch (const Poco::InvalidArgumentException& exception)
        {
            sendError(response, Poco::Net::HTTPResponse::HTTP_BAD_REQUEST,
                      "LIFECYCLE_REQUEST_INVALID", exception.displayText());
        }
        catch (const std::exception& exception)
        {
            sendError(response, Poco::Net::HTTPResponse::HTTP_CONFLICT,
                      "LIFECYCLE_OPERATION_CONFLICT", exception.what());
        }
    }

private:
    Poco::OSP::BundleContext::Ptr _context;
};
} // namespace

class LifecycleHandlerFactory final :
    public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new Handler(context());
    }
};

class LifecycleRuntimeBundleActivator final : public Poco::OSP::BundleActivator
{
public:
    void start(Poco::OSP::BundleContext::Ptr context) override
    {
        try
        {
            _context = context;
            auto preferences = Poco::OSP::ServiceFinder::find<
                Poco::OSP::PreferencesService>(context);
            const auto manageablePatterns = splitPatterns(
                preferences->configuration()->getString(
                    "pdr.management.manageableBundles",
                    DEFAULT_MANAGEABLE_BUNDLES));
            const auto startupAdmission = blockManageableBundles(
                context, manageablePatterns);
            Poco::Path defaultDatabase(context->persistentDirectory());
            defaultDatabase.append("maintenance.sqlite");
            const auto database = preferences->configuration()->getString(
                "pdr.lifecycleRuntime.database", defaultDatabase.toString());
            try
            {
                _service = new RuntimeServiceImpl(
                    context, std::make_unique<SqliteMaintenanceStore>(database));
            }
            catch (const std::exception& exception)
            {
                Poco::OSP::Properties guardProperties;
                guardProperties.set("pdr.bundle",
                                    context->thisBundle()->symbolicName());
                guardProperties.set("pdr.lifecycle.guard",
                                    "durable-desired-state-unavailable");
                _guard = new DesiredStateGuardImpl(
                    manageablePatterns, exception.what());
                _guardRef = context->registry().registerService(
                    "pdr.lifecycle.guard.durableDesiredState", _guard,
                    guardProperties);

                Poco::OSP::Properties healthProperties;
                healthProperties.set(
                    "pdr.bundle", context->thisBundle()->symbolicName());
                healthProperties.set("pdr.healthContributor", "true");
                healthProperties.set("pdr.healthContributor.component",
                                     "lifecycle-maintenance");
                _healthRef = context->registry().registerService(
                    "pdr.healthContributor.lifecycleMaintenance", _guard,
                    healthProperties);
                context->logger().error(
                    "Lifecycle desired-state store unavailable; manageable "
                    "Bundle startup remains fail-closed: " +
                    std::string(exception.what()));
                return;
            }
            context->systemEvents().systemStarted += Poco::delegate(
                this, &LifecycleRuntimeBundleActivator::onSystemStarted);
            _subscribed = true;
            Poco::OSP::Properties properties;
            properties.set("pdr.bundle", context->thisBundle()->symbolicName());
            properties.set("pdr.service", "lifecycleRuntime");
            _serviceRef = context->registry().registerService(
                LifecycleRuntimeService::SERVICE_NAME, _service, properties);

            Poco::OSP::Properties guardProperties;
            guardProperties.set("pdr.bundle",
                                context->thisBundle()->symbolicName());
            guardProperties.set("pdr.lifecycle.guard",
                                "durable-desired-state");
            _guard = new DesiredStateGuardImpl(_service.get());
            _guardRef = context->registry().registerService(
                "pdr.lifecycle.guard.durableDesiredState", _guard,
                guardProperties);

            Poco::OSP::Properties healthProperties;
            healthProperties.set("pdr.bundle", context->thisBundle()->symbolicName());
            healthProperties.set("pdr.healthContributor", "true");
            healthProperties.set("pdr.healthContributor.component",
                                 "lifecycle-maintenance");
            _healthRef = context->registry().registerService(
                "pdr.healthContributor.lifecycleMaintenance", _service,
                healthProperties);
            _service->releaseStartupAdmission(startupAdmission);
            context->logger().information(
                "Lifecycle maintenance runtime started with durable transactional drain, "
                "restore and crash recovery at " + database + ".");
        }
        catch (...)
        {
            stop(context);
            throw;
        }
    }

    void stop(Poco::OSP::BundleContext::Ptr context) override
    {
        if (_subscribed)
        {
            try
            {
                context->systemEvents().systemStarted -= Poco::delegate(
                    this, &LifecycleRuntimeBundleActivator::onSystemStarted);
            }
            catch (...) {}
            _subscribed = false;
        }
        if (_service) _service->shutdown();
        if (_healthRef)
        {
            try { context->registry().unregisterService(_healthRef); }
            catch (...) {}
        }
        _healthRef = nullptr;
        if (_guardRef)
        {
            try { context->registry().unregisterService(_guardRef); }
            catch (...) {}
        }
        _guardRef = nullptr;
        _guard = nullptr;
        if (_serviceRef)
        {
            try { context->registry().unregisterService(_serviceRef); }
            catch (...) {}
        }
        _serviceRef = nullptr;
        _service = nullptr;
        _context = nullptr;
    }

private:
    void onSystemStarted(const void*, Poco::OSP::SystemEvents::EventKind&)
    {
        if (_service) _service->recoverIncomplete();
    }

    Poco::OSP::BundleContext::Ptr _context;
    Poco::AutoPtr<RuntimeServiceImpl> _service;
    Poco::AutoPtr<DesiredStateGuardImpl> _guard;
    Poco::OSP::ServiceRef::Ptr _serviceRef;
    Poco::OSP::ServiceRef::Ptr _healthRef;
    Poco::OSP::ServiceRef::Ptr _guardRef;
    bool _subscribed{false};
};
} // namespace PocoDDS::Lifecycle

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
    POCO_EXPORT_CLASS(PocoDDS::Lifecycle::LifecycleRuntimeBundleActivator)
POCO_END_MANIFEST

POCO_BEGIN_NAMED_MANIFEST(WebServer, Poco::OSP::Web::WebRequestHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::Lifecycle::LifecycleHandlerFactory)
POCO_END_MANIFEST
