#include "PocoDDS/Supervisor/Supervisor.h"
#include <gtest/gtest.h>
#include <thread>

namespace
{
struct ProcessState
{
    bool running{true};
    int id{100};
};

class FakeProcess final : public PocoDDS::Supervisor::Process
{
  public:
    explicit FakeProcess(std::shared_ptr<ProcessState> state) : _state(std::move(state)) {}
    bool running() override { return _state->running; }
    int processId() const override { return _state->id; }
    void terminate(std::chrono::milliseconds) override { _state->running = false; }

  private:
    std::shared_ptr<ProcessState> _state;
};

class FakeLauncher final : public PocoDDS::Supervisor::ProcessLauncher
{
  public:
    std::unique_ptr<PocoDDS::Supervisor::Process>
    start(const PocoDDS::Supervisor::ProcessSpec&) override
    {
        auto state = std::make_shared<ProcessState>();
        state->id += static_cast<int>(states.size());
        states.push_back(state);
        return std::make_unique<FakeProcess>(state);
    }
    std::vector<std::shared_ptr<ProcessState>> states;
};
} // namespace

TEST(SupervisorTest, RestartsUnexpectedExitAndStopsCleanly)
{
    PocoDDS::Core::ComponentRegistry registry;
    auto launcher = std::make_unique<FakeLauncher>();
    auto* observedLauncher = launcher.get();
    PocoDDS::Supervisor::Supervisor supervisor(registry, std::move(launcher));
    supervisor.add({"renderer", "renderer-child", {}, {}, {}}, {2, std::chrono::minutes(1)});
    supervisor.start("renderer");
    ASSERT_EQ(observedLauncher->states.size(), 1U);
    observedLauncher->states.front()->running = false;
    supervisor.poll();
    ASSERT_EQ(observedLauncher->states.size(), 2U);
    EXPECT_EQ(registry.find("renderer")->state, PocoDDS::Core::ComponentState::Running);
    supervisor.stop("renderer");
    EXPECT_FALSE(observedLauncher->states.back()->running);
    EXPECT_EQ(registry.find("renderer")->state, PocoDDS::Core::ComponentState::Stopped);
}

TEST(SupervisorTest, StopsRestartingAfterCrashLoopLimit)
{
    PocoDDS::Core::ComponentRegistry registry;
    auto launcher = std::make_unique<FakeLauncher>();
    auto* observedLauncher = launcher.get();
    PocoDDS::Supervisor::Supervisor supervisor(registry, std::move(launcher));
    supervisor.add({"worker", "worker-child", {}, {}, {}}, {1, std::chrono::minutes(1)});
    supervisor.start("worker");
    observedLauncher->states.back()->running = false;
    supervisor.poll();
    observedLauncher->states.back()->running = false;
    supervisor.poll();
    EXPECT_EQ(observedLauncher->states.size(), 2U);
    EXPECT_EQ(registry.find("worker")->state, PocoDDS::Core::ComponentState::Failed);
}

TEST(NativeProcessTest, StartsAndTerminatesRealChild)
{
    auto launcher = PocoDDS::Supervisor::createNativeProcessLauncher();
    auto process = launcher->start({"native-child", PDR_TEST_CHILD_PATH, {}, {}, {}});
    ASSERT_NE(process, nullptr);
    EXPECT_GT(process->processId(), 0);
    EXPECT_TRUE(process->running());
    process->terminate(std::chrono::milliseconds(50));
    EXPECT_FALSE(process->running());
}

TEST(NativeProcessTest, SupervisorRestartsAndRemovesRealChild)
{
    PocoDDS::Core::ComponentRegistry registry;
    PocoDDS::Supervisor::Supervisor supervisor(registry,
                                               PocoDDS::Supervisor::createNativeProcessLauncher());
    supervisor.add({"managed-native-child", PDR_TEST_CHILD_PATH, {}, {}, {}});
    supervisor.start("managed-native-child");
    const auto first = registry.find("managed-native-child");
    ASSERT_TRUE(first.has_value());
    ASSERT_GT(first->processId, 0);

    supervisor.restart("managed-native-child");
    const auto restarted = registry.find("managed-native-child");
    ASSERT_TRUE(restarted.has_value());
    EXPECT_EQ(restarted->state, PocoDDS::Core::ComponentState::Running);
    EXPECT_GT(restarted->processId, 0);
    EXPECT_NE(restarted->processId, first->processId);

    supervisor.remove("managed-native-child");
    EXPECT_FALSE(registry.find("managed-native-child").has_value());
}

TEST(SupervisorTest, RestartsAProcessAfterHeartbeatTimeout)
{
    PocoDDS::Core::ComponentRegistry registry;
    auto launcher = std::make_unique<FakeLauncher>();
    auto* observedLauncher = launcher.get();
    PocoDDS::Supervisor::Supervisor supervisor(registry, std::move(launcher));
    supervisor.add({"heartbeat-worker", "worker-child", {}, {}, std::chrono::milliseconds(1)},
                   {2, std::chrono::minutes(1)});
    supervisor.start("heartbeat-worker");
    std::this_thread::sleep_for(std::chrono::milliseconds(3));
    supervisor.poll();
    EXPECT_EQ(observedLauncher->states.size(), 2U);
    EXPECT_FALSE(observedLauncher->states.front()->running);
    EXPECT_TRUE(observedLauncher->states.back()->running);
}
