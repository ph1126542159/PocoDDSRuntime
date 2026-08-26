#include "PocoDDS/Workflow/SqliteWorkflowStore.h"
#include "PocoDDS/Workflow/WorkflowEngine.h"

#include <Poco/Exception.h>
#include <Poco/File.h>
#include <Poco/Path.h>
#include <Poco/UUIDGenerator.h>

#include <chrono>
#include <iostream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace
{
using namespace PocoDDS::Workflow;

void require(bool condition, const std::string& message)
{
    if (!condition) throw std::runtime_error(message);
}

std::string temporaryDatabase()
{
    Poco::Path path(Poco::Path::temp());
    path.append("pdr-workflow-" +
                Poco::UUIDGenerator::defaultGenerator().createRandom().toString() + ".sqlite");
    return path.toString();
}

class TestDefinition final : public WorkflowDefinitionService
{
public:
    DefinitionDescriptor descriptor() const override
    {
        return {"release-device", "1.0.0", {"prepare", "approve", "publish"}, 3};
    }

    StepResult execute(const std::string& step, const StepContext& context) override
    {
        executed.push_back(step + ":" + std::to_string(context.attempt));
        if (step == "prepare") return StepResult::completed();
        if (step == "approve" && context.signalPayload.empty())
            return StepResult::waiting("approved");
        if (step == "publish" && context.attempt == 1)
            return StepResult::retryAfter(std::chrono::milliseconds(0),
                                          "temporarily-unavailable", "retry publish");
        return StepResult::completed();
    }

    void compensate(const std::string& step, const StepContext&) override
    {
        compensated.push_back(step);
    }

    std::vector<std::string> executed;
    std::vector<std::string> compensated;
};

class FailingDefinition final : public WorkflowDefinitionService
{
public:
    DefinitionDescriptor descriptor() const override
    {
        return {"failing-release", "1.0.0", {"allocate", "deploy"}, 2};
    }

    StepResult execute(const std::string& step, const StepContext&) override
    {
        if (step == "deploy") return StepResult::failed("deploy-failed", "deployment failed");
        return StepResult::completed();
    }

    void compensate(const std::string& step, const StepContext&) override
    {
        compensated.push_back(step);
    }

    std::vector<std::string> compensated;
};

class RecoveringCompensationDefinition final : public WorkflowDefinitionService
{
public:
    DefinitionDescriptor descriptor() const override
    {
        return {"recover-compensation", "1.0.0", {"allocate", "stage", "fail"}, 2};
    }

    StepResult execute(const std::string& step, const StepContext&) override
    {
        return step == "fail" ? StepResult::failed("publish-failed", "publish failed")
                              : StepResult::completed();
    }

    void compensate(const std::string& step, const StepContext&) override
    {
        calls.push_back(step);
        if (step == "allocate" && failAllocateOnce)
        {
            failAllocateOnce = false;
            throw Poco::RuntimeException("simulated compensation interruption");
        }
    }

    bool failAllocateOnce{true};
    std::vector<std::string> calls;
};

void removeDatabase(const std::string& path)
{
    for (const auto& suffix : {std::string{}, std::string{"-wal"}, std::string{"-shm"}})
    {
        Poco::File file(path + suffix);
        if (file.exists()) file.remove();
    }
}
} // namespace

int main()
{
    const std::string path = temporaryDatabase();
    try
    {
        std::string waitingId;
        Poco::AutoPtr<TestDefinition> definition = new TestDefinition;
        {
            WorkflowEngine engine(std::make_unique<SqliteWorkflowStore>(path));
            engine.initialize();
            engine.attach(definition);

            auto waiting = engine.start("release-device", "device-42:release-7", "payload");
            require(waiting.state == State::waiting, "workflow did not wait for approval");
            require(waiting.waitingEvent == "approved", "unexpected wait event");
            waitingId = waiting.id;

            const auto duplicate = engine.start(
                "release-device", "device-42:release-7", "different-payload");
            require(duplicate.id == waiting.id, "business-key start is not idempotent");
            require(definition->executed.size() == 2,
                    "idempotent start unexpectedly executed provider code");

            bool rejectedWrongEvent = false;
            try
            {
                engine.signal(waiting.id, "rejected-event", "yes");
            }
            catch (const Poco::InvalidArgumentException&)
            {
                rejectedWrongEvent = true;
            }
            require(rejectedWrongEvent, "wrong workflow event was accepted");

            auto retry = engine.signal(waiting.id, "approved", "yes");
            require(retry.state == State::retryScheduled, "retry was not persisted");
            require(engine.runDue() == 1, "due workflow was not executed");
            require(engine.get(waiting.id).state == State::succeeded,
                    "workflow did not succeed after retry");

            Poco::AutoPtr<FailingDefinition> failing = new FailingDefinition;
            engine.attach(failing);
            const auto failed = engine.start("failing-release", "failure-1", "payload");
            require(failed.state == State::failed, "failed workflow is not terminal");
            require(failed.compensated, "failed workflow was not compensated");
            require(failed.compensatedSteps == std::vector<std::string>{"allocate"},
                    "compensation checkpoint was not persisted");
            require(failing->compensated == std::vector<std::string>{"allocate"},
                    "compensation order is incorrect");

            Poco::AutoPtr<RecoveringCompensationDefinition> recovering =
                new RecoveringCompensationDefinition;
            engine.attach(recovering);
            auto interrupted = engine.start(
                "recover-compensation", "compensation-recovery-1", "payload");
            require(interrupted.state == State::interrupted,
                    "compensation failure did not interrupt workflow");
            require(interrupted.compensatedSteps == std::vector<std::string>{"stage"},
                    "successful compensation checkpoint was lost");
            const auto resumed = engine.resume(interrupted.id);
            require(resumed.state == State::failed && resumed.compensated,
                    "compensation did not finish after resume");
            require(recovering->calls ==
                        std::vector<std::string>{"stage", "allocate", "allocate"},
                    "resume repeated an already checkpointed compensation");
            require(resumed.lastErrorCode == "publish-failed",
                    "root workflow failure was lost during compensation recovery");
        }

        // A new engine/store pair proves that state survives actual SQLite close/reopen.
        {
            WorkflowEngine recovered(std::make_unique<SqliteWorkflowStore>(path));
            recovered.initialize();
            recovered.attach(new TestDefinition);
            require(recovered.get(waitingId).state == State::succeeded,
                    "completed workflow did not survive restart");
            require(recovered.list().size() == 3, "workflow list did not survive restart");
        }

        // Simulate a process dying after its pre-callback durable running checkpoint.
        const std::string interruptedPath = temporaryDatabase();
        std::string interruptedId;
        {
            SqliteWorkflowStore store(interruptedPath);
            store.initialize();
            Instance instance;
            instance.id = Poco::UUIDGenerator::defaultGenerator().createRandom().toString();
            interruptedId = instance.id;
            instance.type = "release-device";
            instance.definitionVersion = "1.0.0";
            instance.businessKey = "recovery-1";
            instance.state = State::running;
            instance.createdMicroseconds = 1;
            instance.updatedMicroseconds = 1;
            store.save(instance);
        }
        {
            WorkflowEngine recovered(std::make_unique<SqliteWorkflowStore>(interruptedPath));
            recovered.initialize();
            recovered.attach(new TestDefinition);
            require(recovered.get(interruptedId).state == State::interrupted,
                    "active workflow was not marked interrupted after restart");
            require(recovered.resume(interruptedId).state == State::waiting,
                    "interrupted workflow could not resume from its checkpoint");
        }
        removeDatabase(interruptedPath);
        removeDatabase(path);
        std::cout << "workflow-runtime-smoke: PASS\n";
        return 0;
    }
    catch (const Poco::Exception& exception)
    {
        removeDatabase(path);
        std::cerr << "workflow-runtime-smoke: FAIL: " << exception.displayText() << '\n';
        return 1;
    }
    catch (const std::exception& exception)
    {
        removeDatabase(path);
        std::cerr << "workflow-runtime-smoke: FAIL: " << exception.what() << '\n';
        return 1;
    }
}
