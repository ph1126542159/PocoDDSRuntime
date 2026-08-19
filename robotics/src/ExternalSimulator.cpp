#include "PocoDDS/Robotics/SimulationAdapter.h"

#include <stdexcept>
#include <utility>

namespace PocoDDS::Robotics
{
ExternalSimulator::ExternalSimulator(std::string backend, CommandSink commandSink,
                                     std::chrono::steady_clock::duration feedbackTimeout,
                                     Clock clock)
    : _backend(std::move(backend)), _commandSink(std::move(commandSink)),
      _feedbackTimeout(feedbackTimeout), _clock(std::move(clock))
{
    if (_backend.empty() || !_commandSink || !_clock ||
        _feedbackTimeout <= std::chrono::steady_clock::duration::zero())
        throw std::invalid_argument(
            "external simulator requires backend, command sink, timeout and clock");
}

std::string ExternalSimulator::backendName() const { return _backend; }

bool ExternalSimulator::connect(const std::string& world)
{
    std::lock_guard<std::mutex> lock(_mutex);
    if (world.empty())
        return false;
    _connected = true;
    _backendActive = false;
    _frame.reset();
    _lastFeedback.reset();
    _readCount = 0;
    _writeCount = 0;
    _detail = "waiting for simulator feedback";
    return true;
}

void ExternalSimulator::reset()
{
    std::lock_guard<std::mutex> lock(_mutex);
    _connected = false;
    _backendActive = false;
    _frame.reset();
    _lastFeedback.reset();
    _readCount = 0;
    _writeCount = 0;
    _detail = "disconnected";
}

void ExternalSimulator::applyCommand(const RobotCommand& command)
{
    {
        std::lock_guard<std::mutex> lock(_mutex);
        if (!_connected)
            throw std::logic_error("external simulator is not connected");
    }
    if (!_commandSink(command))
        throw std::runtime_error("external simulator command sink rejected command");
    std::lock_guard<std::mutex> lock(_mutex);
    ++_writeCount;
}

RobotFrame ExternalSimulator::step(std::chrono::nanoseconds)
{
    std::lock_guard<std::mutex> lock(_mutex);
    if (!_connected || !_frame || !_lastFeedback)
        throw std::runtime_error("external simulator feedback is unavailable");
    if (_clock() - *_lastFeedback > _feedbackTimeout)
    {
        _detail = "external simulator feedback timed out";
        throw std::runtime_error(_detail);
    }
    ++_readCount;
    _detail = "ready";
    return *_frame;
}

bool ExternalSimulator::connected() const noexcept
{
    std::lock_guard<std::mutex> lock(_mutex);
    return _connected && _lastFeedback.has_value();
}

BackendHealth ExternalSimulator::health() const
{
    std::lock_guard<std::mutex> lock(_mutex);
    const auto feedbackReady = _lastFeedback && _clock() - *_lastFeedback <= _feedbackTimeout;
    return {_connected, _backendActive, _connected && _backendActive && feedbackReady,
            _readCount, _writeCount,    _detail};
}

void ExternalSimulator::updateFrame(RobotFrame frame)
{
    std::lock_guard<std::mutex> lock(_mutex);
    if (!_connected)
        return;
    _frame = std::move(frame);
    _lastFeedback = _clock();
    _detail = "ready";
}
} // namespace PocoDDS::Robotics
