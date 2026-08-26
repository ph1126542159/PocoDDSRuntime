#include "PocoDDS/StoreForward/DeliveryProviderService.h"
#include "PocoDDS/StoreForward/OutboxEngine.h"
#include "PocoDDS/StoreForward/OutboxRuntimeService.h"
#include "PocoDDS/StoreForward/SqliteOutboxStore.h"
#include "PocoDDS/Scheduling/SchedulerService.h"
#include "PocoDDS/Scheduling/ScheduleConfigurationParticipant.h"
#include "PocoDDS/Lifecycle/DrainParticipantService.h"

#include <Poco/ClassLibrary.h>
#include <Poco/Delegate.h>
#include <Poco/Exception.h>
#include <Poco/OSP/Bundle.h>
#include <Poco/OSP/BundleActivator.h>
#include <Poco/OSP/BundleContext.h>
#include <Poco/OSP/PreferencesService.h>
#include <Poco/OSP/Properties.h>
#include <Poco/OSP/ServiceFinder.h>
#include <Poco/OSP/ServiceListener.h>
#include <Poco/OSP/ServiceRef.h>
#include <Poco/OSP/ServiceRegistry.h>
#include <Poco/Path.h>
#include <Poco/Util/AbstractConfiguration.h>

#include <algorithm>
#include <chrono>
#include <memory>
#include <string>
#include <utility>
#include <vector>

namespace PocoDDS::StoreForward
{
class RuntimeServiceImpl final : public OutboxRuntimeService
{
public:
    RuntimeServiceImpl(std::unique_ptr<OutboxStore> store, Policy policy,
                       std::chrono::seconds maintenanceInterval)
        : _engine(std::move(store), std::move(policy)),
          _maintenanceInterval(maintenanceInterval),
          _nextMaintenance(std::chrono::steady_clock::now() + maintenanceInterval)
    {
        _engine.initialize();
    }

    void attach(Poco::AutoPtr<DeliveryProviderService> provider)
    {
        _engine.attach(std::move(provider));
    }

    void detach(const std::string& type)
    {
        _engine.detach(type);
    }

    std::size_t pump()
    {
        auto lease = _drainGate.tryEnter();
        if (!lease) return 0;
        return _engine.pump();
    }

    std::size_t purge()
    {
        auto lease = _drainGate.tryEnter();
        if (!lease) return 0;
        return _engine.purge();
    }

    void pumpAndMaintain()
    {
        auto lease = _drainGate.tryEnter();
        if (!lease) return;
        _engine.pump();
        const auto now = std::chrono::steady_clock::now();
        if (now >= _nextMaintenance)
        {
            _engine.purge();
            _nextMaintenance = now + _maintenanceInterval;
        }
    }

    Message enqueue(const EnqueueRequest& request) override
    {
        auto lease = operation("enqueue");
        return _engine.enqueue(request);
    }

    Message cancel(const std::string& id) override
    {
        auto lease = operation("cancel");
        return _engine.cancel(id);
    }

    Message redrive(const std::string& id) override
    {
        auto lease = operation("redrive");
        return _engine.redrive(id);
    }

    Message message(const std::string& id) const override
    {
        auto lease = operation("message");
        return _engine.get(id);
    }

    std::vector<Message> messages() const override
    {
        auto lease = operation("messages");
        return _engine.list();
    }

    Snapshot snapshot() const override
    {
        auto lease = operation("snapshot");
        return _engine.snapshot();
    }

    std::vector<std::string> providerTypes() const override
    {
        auto lease = operation("providerTypes");
        return _engine.providerTypes();
    }

    Lifecycle::DrainResult quiesce(std::chrono::milliseconds timeout)
    {
        const bool drained = _drainGate.quiesce(timeout);
        const auto value = _drainGate.snapshot();
        return {drained,
                drained ? "DRAIN_COMPLETE" : "DRAIN_TIMEOUT",
                drained ? "Outbox operations drained"
                        : "Outbox operations did not drain before the deadline",
                value};
    }

    void resume() noexcept { _drainGate.resume(); }
    void closeAndWait() noexcept { _drainGate.closeAndWait(); }
    Lifecycle::DrainSnapshot drainSnapshot() const noexcept
    {
        return _drainGate.snapshot();
    }

private:
    Lifecycle::DrainGate::Lease operation(const char* name) const
    {
        auto lease = _drainGate.tryEnter();
        if (!lease)
            throw Poco::IllegalStateException(
                "Outbox runtime is quiescing", name);
        return std::move(*lease);
    }

    OutboxEngine _engine;
    std::chrono::seconds _maintenanceInterval;
    std::chrono::steady_clock::time_point _nextMaintenance;
    mutable Lifecycle::DrainGate _drainGate;
};

class DrainParticipantImpl final : public Lifecycle::DrainParticipantService
{
public:
    DrainParticipantImpl(std::string owner, Poco::AutoPtr<RuntimeServiceImpl> runtime)
        : _owner(std::move(owner)), _runtime(std::move(runtime))
    {
    }

    std::string owner() const override { return _owner; }
    Lifecycle::DrainResult quiesce(std::chrono::milliseconds timeout) override
    {
        return _runtime->quiesce(timeout);
    }
    void resume() noexcept override { _runtime->resume(); }
    Lifecycle::DrainSnapshot drainSnapshot() const noexcept override
    {
        return _runtime->drainSnapshot();
    }

private:
    std::string _owner;
    Poco::AutoPtr<RuntimeServiceImpl> _runtime;
};

class RuntimeBundleActivator final : public Poco::OSP::BundleActivator
{
public:
    void start(Poco::OSP::BundleContext::Ptr context) override
    {
        try
        {
            _context = context;
            auto preferences =
                Poco::OSP::ServiceFinder::find<Poco::OSP::PreferencesService>(context);
            auto configuration = preferences->configuration();
            Poco::Path defaultDatabase(context->persistentDirectory());
            defaultDatabase.append("messages.sqlite");
            const auto database = configuration->getString(
                "pdr.outbox.database", defaultDatabase.toString());

            Policy policy;
            policy.maximumActiveMessages = static_cast<std::size_t>(
                configuration->getUInt64("pdr.outbox.maximumActiveMessages", 10000));
            policy.maximumPayloadBytes = static_cast<std::size_t>(
                configuration->getUInt64("pdr.outbox.maximumPayloadBytes", 1024 * 1024));
            policy.maximumAttempts =
                configuration->getUInt("pdr.outbox.maximumAttempts", 8);
            policy.initialRetryDelay = std::chrono::milliseconds(
                configuration->getUInt("pdr.outbox.initialRetryDelayMilliseconds", 1000));
            policy.maximumRetryDelay = std::chrono::milliseconds(
                configuration->getUInt("pdr.outbox.maximumRetryDelayMilliseconds", 60000));
            policy.deliveryBatchSize = static_cast<std::size_t>(
                configuration->getUInt64("pdr.outbox.deliveryBatchSize", 100));
            policy.terminalRetention = std::chrono::hours(
                configuration->getUInt("pdr.outbox.terminalRetentionHours", 24 * 7));

            _schedulerInterval = std::chrono::milliseconds(configuration->getUInt(
                "pdr.outbox.schedulerIntervalMilliseconds", 100));
            _schedulerJitter = std::chrono::milliseconds(configuration->getUInt(
                "pdr.outbox.schedulerJitterMilliseconds", 0));
            _schedulerEnabled = configuration->getBool(
                "pdr.outbox.schedulerEnabled", true);
            _maintenanceInterval = std::chrono::seconds(configuration->getUInt(
                "pdr.outbox.maintenanceIntervalSeconds", 60));
            if (_schedulerInterval.count() == 0 || _maintenanceInterval.count() == 0)
                throw Poco::InvalidArgumentException(
                    "Outbox scheduler and maintenance intervals must be positive");

            _service = new RuntimeServiceImpl(
                std::make_unique<SqliteOutboxStore>(database), policy,
                _maintenanceInterval);
            _providerListener = context->registry().createListener(
                "pdr.delivery.provider.kind == \"outbox\"",
                Poco::delegate(this, &RuntimeBundleActivator::onProviderRegistered),
                Poco::delegate(this, &RuntimeBundleActivator::onProviderUnregistered));

            Poco::OSP::Properties properties;
            properties.set("pdr.service", "outboxRuntime");
            properties.set("pdr.outbox.runtime", "true");
            properties.set("pdr.bundle", context->thisBundle()->symbolicName());
            _serviceRef = context->registry().registerService(
                "pdr.service.outboxRuntime", _service, properties);

            _schedulerService = Poco::OSP::ServiceFinder::find<
                Scheduling::SchedulerService>(context);
            Scheduling::TaskSpec task;
            task.id = SCHEDULE_ID;
            task.owner = context->thisBundle()->symbolicName();
            task.enabled = _schedulerEnabled;
            task.initialDelay = _schedulerInterval;
            task.interval = _schedulerInterval;
            task.jitter = _schedulerJitter;
            task.rejectionBackoff = std::min(
                _schedulerInterval,
                std::chrono::duration_cast<std::chrono::milliseconds>(
                    std::chrono::hours(1)));
            auto service = _service;
            const auto registration = _schedulerService->schedule(
                std::move(task),
                [service](const Scheduling::CancellationToken&) mutable {
                    service->pumpAndMaintain();
                },
                [context](const ResourceGovernance::Completion& completion) {
                    if (completion.status != ResourceGovernance::CompletionStatus::succeeded)
                        context->logger().error(
                            "Outbox managed schedule completed with status " +
                            std::string(ResourceGovernance::toString(completion.status)) +
                            ": " + completion.message);
                });
            if (registration.status != Scheduling::RegistrationStatus::registered)
                throw Poco::IllegalStateException(
                    "Outbox schedule registration failed", registration.message);
            _taskRegistered = true;

            _configurationParticipant = new Scheduling::ScheduleConfigurationParticipant(
                {"outbox-scheduler", SCHEDULE_ID,
                 context->thisBundle()->symbolicName(),
                 "pdr.outbox.schedulerEnabled",
                 "pdr.outbox.schedulerIntervalMilliseconds",
                 "pdr.outbox.schedulerJitterMilliseconds"},
                _schedulerService);
            Poco::OSP::Properties participantProperties;
            participantProperties.set(
                ConfigTransaction::ConfigurationParticipantService::PROPERTY_KIND,
                ConfigTransaction::ConfigurationParticipantService::PARTICIPANT_KIND);
            participantProperties.set(
                ConfigTransaction::ConfigurationParticipantService::PROPERTY_ID,
                "outbox-scheduler");
            participantProperties.set("pdr.bundle", context->thisBundle()->symbolicName());
            _configurationParticipantRef = context->registry().registerService(
                "pdr.configuration.participant.outboxScheduler",
                _configurationParticipant, participantProperties);

            const auto owner = context->thisBundle()->symbolicName();
            _drainParticipant = new DrainParticipantImpl(owner, _service);
            Poco::OSP::Properties drainProperties;
            drainProperties.set(Lifecycle::DrainParticipantService::PROPERTY_KIND,
                                "true");
            drainProperties.set(Lifecycle::DrainParticipantService::PROPERTY_OWNER,
                                owner);
            _drainParticipantRef = context->registry().registerService(
                std::string(Lifecycle::DrainParticipantService::SERVICE_PREFIX) + owner,
                _drainParticipant, drainProperties);
            context->logger().information(
                "Store-and-forward Outbox runtime started with database " + database +
                "; pump and maintenance are managed by the central scheduler.");
        }
        catch (...)
        {
            stop(context);
            throw;
        }
    }

    void stop(Poco::OSP::BundleContext::Ptr context) override
    {
        if (_drainParticipantRef)
        {
            try { context->registry().unregisterService(_drainParticipantRef); }
            catch (...) {}
        }
        _drainParticipantRef = nullptr;
        _drainParticipant = nullptr;
        if (_configurationParticipantRef)
        {
            try { context->registry().unregisterService(_configurationParticipantRef); }
            catch (...) {}
        }
        _configurationParticipantRef = nullptr;
        _configurationParticipant = nullptr;
        if (_schedulerService && _taskRegistered)
            _schedulerService->cancelAndWait(SCHEDULE_ID);
        _taskRegistered = false;
        _schedulerService = nullptr;
        _providerListener = nullptr;
        if (_service) _service->closeAndWait();
        if (_serviceRef)
        {
            try
            {
                context->registry().unregisterService(_serviceRef);
            }
            catch (...) {}
        }
        _serviceRef = nullptr;
        _providerRefs.clear();
        _service = nullptr;
        _context = nullptr;
    }

private:
    struct ProviderRef
    {
        Poco::OSP::ServiceRef::Ptr reference;
        std::string type;
    };

    void onProviderRegistered(const Poco::OSP::ServiceRef::Ptr& reference)
    {
        if (!_service) return;
        if (std::any_of(_providerRefs.begin(), _providerRefs.end(),
                        [&](const auto& item) {
                            return item.reference->name() == reference->name();
                        }))
            return;
        auto provider = reference->castedInstance<DeliveryProviderService>();
        const auto descriptor = provider->descriptor();
        const auto registeredType = reference->properties().get(
            DeliveryProviderService::PROPERTY_TYPE, "");
        if (registeredType != descriptor.type)
            throw Poco::InvalidArgumentException(
                "Delivery provider property/type mismatch", reference->name());
        _service->attach(provider);
        _providerRefs.push_back({reference, descriptor.type});
        if (_context)
            _context->logger().information(
                "Outbox delivery provider " + descriptor.type + " attached through registry.");
    }

    void onProviderUnregistered(const Poco::OSP::ServiceRef::Ptr& reference)
    {
        if (!_service) return;
        const auto found = std::find_if(
            _providerRefs.begin(), _providerRefs.end(),
            [&](const auto& item) { return item.reference->name() == reference->name(); });
        if (found == _providerRefs.end()) return;
        _service->detach(found->type);
        _providerRefs.erase(found);
    }

    static constexpr const char* SCHEDULE_ID =
        "pdr.service.outboxRuntime.pump";
    Poco::OSP::BundleContext::Ptr _context;
    Poco::AutoPtr<RuntimeServiceImpl> _service;
    Poco::OSP::ServiceRef::Ptr _serviceRef;
    Poco::OSP::ServiceListener::Ptr _providerListener;
    std::vector<ProviderRef> _providerRefs;
    Scheduling::SchedulerService::Ptr _schedulerService;
    Poco::AutoPtr<Scheduling::ScheduleConfigurationParticipant>
        _configurationParticipant;
    Poco::OSP::ServiceRef::Ptr _configurationParticipantRef;
    Poco::AutoPtr<DrainParticipantImpl> _drainParticipant;
    Poco::OSP::ServiceRef::Ptr _drainParticipantRef;
    bool _taskRegistered{false};
    bool _schedulerEnabled{true};
    std::chrono::milliseconds _schedulerInterval{100};
    std::chrono::milliseconds _schedulerJitter{0};
    std::chrono::seconds _maintenanceInterval{60};
};
} // namespace PocoDDS::StoreForward

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
    POCO_EXPORT_CLASS(PocoDDS::StoreForward::RuntimeBundleActivator)
POCO_END_MANIFEST
