#pragma once

#include "PocoDDS/Robotics/Backend.h"

#include <atomic>
#include <chrono>
#include <functional>
#include <mutex>
#include <optional>
#include <string>

namespace PocoDDS::Robotics
{
class SimulationAdapter : public RobotBackend
{
  public:
    virtual ~SimulationAdapter() = default;
    BackendKind kind() const noexcept final { return BackendKind::simulation; }
    std::string name() const final { return backendName(); }
    bool configure(const std::string& world) final { return connect(world); }
    bool activate() final
    {
        _backendActive = connected();
        return _backendActive;
    }
    void deactivate() noexcept final;
    RobotFrame read(std::chrono::nanoseconds period) final;
    bool write(const RobotCommand& command, std::chrono::nanoseconds period) final;
    virtual std::string backendName() const = 0;
    virtual bool connect(const std::string& world) = 0;
    virtual void reset() = 0;
    virtual void applyCommand(const RobotCommand& command) = 0;
    virtual RobotFrame step(std::chrono::nanoseconds duration) = 0;
    virtual bool connected() const noexcept = 0;
    virtual BackendHealth health() const override = 0;

  protected:
    std::atomic<bool> _backendActive{false};
};

class InMemorySimulator final : public SimulationAdapter
{
  public:
    std::string backendName() const override;
    bool connect(const std::string& world) override;
    void reset() override;
    void applyCommand(const RobotCommand& command) override;
    RobotFrame step(std::chrono::nanoseconds duration) override;
    bool connected() const noexcept override;
    BackendHealth health() const override;

  private:
    bool _connected{false};
    std::string _world;
    RobotFrame _frame;
    RobotCommand _command;
    double _yaw{0.0};
    mutable std::mutex _mutex;
    std::uint64_t _readCount{0};
    std::uint64_t _writeCount{0};
};

class ExternalSimulator final : public SimulationAdapter
{
  public:
    using CommandSink = std::function<bool(const RobotCommand&)>;
    using Clock = std::function<std::chrono::steady_clock::time_point()>;

    ExternalSimulator(
        std::string backend, CommandSink commandSink,
        std::chrono::steady_clock::duration feedbackTimeout,
        Clock clock = [] { return std::chrono::steady_clock::now(); });

    std::string backendName() const override;
    bool connect(const std::string& world) override;
    void reset() override;
    void applyCommand(const RobotCommand& command) override;
    RobotFrame step(std::chrono::nanoseconds duration) override;
    bool connected() const noexcept override;
    BackendHealth health() const override;
    void updateFrame(RobotFrame frame);

  private:
    const std::string _backend;
    CommandSink _commandSink;
    const std::chrono::steady_clock::duration _feedbackTimeout;
    Clock _clock;
    mutable std::mutex _mutex;
    bool _connected{false};
    std::optional<RobotFrame> _frame;
    std::optional<std::chrono::steady_clock::time_point> _lastFeedback;
    std::uint64_t _readCount{0};
    std::uint64_t _writeCount{0};
    std::string _detail{"disconnected"};
};
} // namespace PocoDDS::Robotics
