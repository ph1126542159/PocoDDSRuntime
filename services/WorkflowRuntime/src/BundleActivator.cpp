#include "PocoDDS/Workflow/SqliteWorkflowStore.h"
#include "PocoDDS/Workflow/WorkflowDefinitionService.h"
#include "PocoDDS/Workflow/WorkflowEngine.h"
#include "PocoDDS/Workflow/WorkflowRuntimeService.h"
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

namespace PocoDDS::Workflow
{
class RuntimeServiceImpl final : public WorkflowRuntimeService
{
public:
    explicit RuntimeServiceImpl(std::unique_ptr<WorkflowStore> store)
        : _engine(std::move(store))
    {
        _engine.initialize();
    }

    void attach(Poco::AutoPtr<WorkflowDefinitionService> definition)
    {
        _engine.attach(std::move(definition));
    }

    void detach(const std::string& type)
    {
        _engine.detach(type);
    }

    std::size_t runDue()
    {
        auto lease = _drainGate.tryEnter();
        if (!lease) return 0;
        return _engine.runDue();
    }

    Instance startWorkflow(const std::string& type,
                           const std::string& businessKey,
                           const std::string& input) override
    {
        auto lease = operation("startWorkflow");
        return _engine.start(type, businessKey, input);
    }

    Instance signalWorkflow(const std::string& id,
                            const std::string& event,
                            const std::string& payload) override
    {
        auto lease = operation("signalWorkflow");
        return _engine.signal(id, event, payload);
    }

    Instance resumeWorkflow(const std::string& id) override
    {
        auto lease = operation("resumeWorkflow");
        return _engine.resume(id);
    }

    Instance cancelWorkflow(const std::string& id) override
    {
        auto lease = operation("cancelWorkflow");
        return _engine.cancel(id);
    }

    Instance workflow(const std::string& id) const override
    {
        auto lease = operation("workflow");
        return _engine.get(id);
    }

    std::vector<Instance> workflows() const override
    {
        auto lease = operation("workflows");
        return _engine.list();
    }

    std::vector<std::string> definitionTypes() const override
    {
        auto lease = operation("definitionTypes");
        return _engine.definitionTypes();
    }

    Lifecycle::DrainResult quiesce(std::chrono::milliseconds timeout)
    {
        const bool drained = _drainGate.quiesce(timeout);
        const auto value = _drainGate.snapshot();
        return {drained,
                drained ? "DRAIN_COMPLETE" : "DRAIN_TIMEOUT",
                drained ? "Workflow operations drained"
                        : "Workflow operations did not drain before the deadline",
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
                "Workflow runtime is quiescing", name);
        return std::move(*lease);
    }

    WorkflowEngine _engine;
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
            defaultDatabase.append("instances.sqlite");
            const auto database = configuration->getString(
                "pdr.workflow.database", defaultDatabase.toString());
            _interval = std::chrono::milliseconds(configuration->getUInt(
                "pdr.workflow.schedulerIntervalMilliseconds", 100));
            _jitter = std::chrono::milliseconds(configuration->getUInt(
                "pdr.workflow.schedulerJitterMilliseconds", 0));
            _schedulerEnabled = configuration->getBool(
                "pdr.workflow.schedulerEnabled", true);
            if (_interval.count() == 0)
                throw Poco::InvalidArgumentException(
                    "pdr.workflow.schedulerIntervalMilliseconds must be greater than zero");

            _service = new RuntimeServiceImpl(
                std::make_unique<SqliteWorkflowStore>(database));
            _definitionListener = context->registry().createListener(
                "pdr.workflow.provider.kind == \"definition\"",
                Poco::delegate(this, &RuntimeBundleActivator::onDefinitionRegistered),
                Poco::delegate(this, &RuntimeBundleActivator::onDefinitionUnregistered));

            Poco::OSP::Properties properties;
            properties.set("pdr.service", "workflowRuntime");
            properties.set("pdr.workflow.runtime", "true");
            properties.set("pdr.bundle", context->thisBundle()->symbolicName());
            _serviceRef = context->registry().registerService(
                "pdr.service.workflowRuntime", _service, properties);

            _schedulerService = Poco::OSP::ServiceFinder::find<
                Scheduling::SchedulerService>(context);
            Scheduling::TaskSpec task;
            task.id = SCHEDULE_ID;
            task.owner = context->thisBundle()->symbolicName();
            task.enabled = _schedulerEnabled;
            task.initialDelay = _interval;
            task.interval = _interval;
            task.jitter = _jitter;
            task.rejectionBackoff = std::min(
                _interval, std::chrono::duration_cast<std::chrono::milliseconds>(
                               std::chrono::hours(1)));
            auto service = _service;
            const auto registration = _schedulerService->schedule(
                std::move(task),
                [service](const Scheduling::CancellationToken&) mutable {
                    service->runDue();
                },
                [context](const ResourceGovernance::Completion& completion) {
                    if (completion.status != ResourceGovernance::CompletionStatus::succeeded)
                        context->logger().error(
                            "Workflow managed schedule completed with status " +
                            std::string(ResourceGovernance::toString(completion.status)) +
                            ": " + completion.message);
                });
            if (registration.status != Scheduling::RegistrationStatus::registered)
                throw Poco::IllegalStateException(
                    "Workflow schedule registration failed", registration.message);
            _taskRegistered = true;

            _configurationParticipant = new Scheduling::ScheduleConfigurationParticipant(
                {"workflow-scheduler", SCHEDULE_ID,
                 context->thisBundle()->symbolicName(),
                 "pdr.workflow.schedulerEnabled",
                 "pdr.workflow.schedulerIntervalMilliseconds",
                 "pdr.workflow.schedulerJitterMilliseconds"},
                _schedulerService);
            Poco::OSP::Properties participantProperties;
            participantProperties.set(
                ConfigTransaction::ConfigurationParticipantService::PROPERTY_KIND,
                ConfigTransaction::ConfigurationParticipantService::PARTICIPANT_KIND);
            participantProperties.set(
                ConfigTransaction::ConfigurationParticipantService::PROPERTY_ID,
                "workflow-scheduler");
            participantProperties.set("pdr.bundle", context->thisBundle()->symbolicName());
            _configurationParticipantRef = context->registry().registerService(
                "pdr.configuration.participant.workflowScheduler",
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
                "Workflow runtime started with database " + database +
                "; runDue is managed by the central scheduler.");
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
        _definitionListener = nullptr;
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
        _definitionRefs.clear();
        _service = nullptr;
        _context = nullptr;
    }

private:
    struct DefinitionRef
    {
        Poco::OSP::ServiceRef::Ptr reference;
        std::string type;
    };

    void onDefinitionRegistered(const Poco::OSP::ServiceRef::Ptr& reference)
    {
        if (!_service) return;
        if (std::any_of(_definitionRefs.begin(), _definitionRefs.end(),
                        [&](const auto& item) { return item.reference->name() == reference->name(); }))
            return;
        auto definition = reference->castedInstance<WorkflowDefinitionService>();
        const auto descriptor = definition->descriptor();
        const auto registeredType = reference->properties().get(
            WorkflowDefinitionService::PROPERTY_TYPE, "");
        if (registeredType != descriptor.type)
            throw Poco::InvalidArgumentException(
                "Workflow definition property/type mismatch", reference->name());
        _service->attach(definition);
        _definitionRefs.push_back({reference, descriptor.type});
        if (_context)
            _context->logger().information(
                "Workflow definition " + descriptor.type + " attached through registry.");
    }

    void onDefinitionUnregistered(const Poco::OSP::ServiceRef::Ptr& reference)
    {
        if (!_service) return;
        const auto found = std::find_if(
            _definitionRefs.begin(), _definitionRefs.end(),
            [&](const auto& item) { return item.reference->name() == reference->name(); });
        if (found == _definitionRefs.end()) return;
        try
        {
            _service->detach(found->type);
            _definitionRefs.erase(found);
        }
        catch (const Poco::IllegalStateException& exception)
        {
            // The retained AutoPtr keeps an in-flight definition alive until recovery finishes.
            if (_context)
                _context->logger().critical(
                    "Workflow definition retained after unregister: " +
                    exception.displayText());
        }
    }

    static constexpr const char* SCHEDULE_ID =
        "pdr.service.workflowRuntime.runDue";
    Poco::OSP::BundleContext::Ptr _context;
    Poco::AutoPtr<RuntimeServiceImpl> _service;
    Poco::OSP::ServiceRef::Ptr _serviceRef;
    Poco::OSP::ServiceListener::Ptr _definitionListener;
    std::vector<DefinitionRef> _definitionRefs;
    Scheduling::SchedulerService::Ptr _schedulerService;
    Poco::AutoPtr<Scheduling::ScheduleConfigurationParticipant>
        _configurationParticipant;
    Poco::OSP::ServiceRef::Ptr _configurationParticipantRef;
    Poco::AutoPtr<DrainParticipantImpl> _drainParticipant;
    Poco::OSP::ServiceRef::Ptr _drainParticipantRef;
    bool _taskRegistered{false};
    bool _schedulerEnabled{true};
    std::chrono::milliseconds _interval{100};
    std::chrono::milliseconds _jitter{0};
};
} // namespace PocoDDS::Workflow

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
    POCO_EXPORT_CLASS(PocoDDS::Workflow::RuntimeBundleActivator)
POCO_END_MANIFEST
