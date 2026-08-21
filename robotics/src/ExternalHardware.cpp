#include "PocoDDS/Robotics/ExternalHardware.h"

#include <utility>

namespace PocoDDS::Robotics
{
ExternalHardware::ExternalHardware(std::string backend, CommandSink commandSink,
                                   std::chrono::steady_clock::duration feedbackTimeout, Clock clock)
    : _transport(std::move(backend), std::move(commandSink), feedbackTimeout, std::move(clock))
{
}

std::string ExternalHardware::name() const { return _transport.backendName(); }

bool ExternalHardware::configure(const std::string& hardwareDescription)
{
    return _transport.connect(hardwareDescription);
}

bool ExternalHardware::activate() { return _transport.activate(); }

void ExternalHardware::deactivate() noexcept { _transport.deactivate(); }

void ExternalHardware::reset() { _transport.reset(); }

RobotFrame ExternalHardware::read(std::chrono::nanoseconds period)
{
    return _transport.read(period);
}

bool ExternalHardware::write(const RobotCommand& command, std::chrono::nanoseconds period)
{
    return _transport.write(command, period);
}

BackendHealth ExternalHardware::health() const { return _transport.health(); }

void ExternalHardware::updateFrame(RobotFrame frame) { _transport.updateFrame(std::move(frame)); }
} // namespace PocoDDS::Robotics
