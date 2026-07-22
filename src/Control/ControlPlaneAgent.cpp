#include "PocoDDS/Control/ControlPlaneAgent.h"

#include "PocoDDS/Control/ContractCodec.h"

#include <stdexcept>

namespace PocoDDS::Control
{
ControlPlaneAgent::ControlPlaneAgent(Transport::ITransport& transport,
                                     Core::Configuration& configuration, std::string componentId,
                                     LifecycleHandler lifecycleHandler)
    : _transport(transport), _configuration(configuration), _componentId(std::move(componentId)),
      _lifecycleHandler(std::move(lifecycleHandler))
{
    if (_componentId.empty())
        throw std::invalid_argument("control-plane component id is required");
    if (!_lifecycleHandler)
        throw std::invalid_argument("lifecycle handler is required");
    _configurationSubscription =
        _transport.subscribe(ConfigurationTopic, [this](const Transport::Message& message)
                             { receiveConfiguration(message); });
    _lifecycleSubscription = _transport.subscribe(
        LifecycleTopic, [this](const Transport::Message& message) { receiveLifecycle(message); });
}

std::uint64_t ControlPlaneAgent::configurationRevision() const { return _revision.load(); }

void ControlPlaneAgent::receiveConfiguration(const Transport::Message& message)
{
    if (message.type != "PocoDDS.ConfigurationTransaction.v1")
        return;
    std::lock_guard lock(_commandMutex);
    ConfigurationTransaction transaction;
    try
    {
        transaction = decodeConfigurationTransaction(message.payload);
    }
    catch (const std::exception& error)
    {
        send({ContractVersion, {}, _componentId, false, error.what(), _revision},
             message.traceParent);
        return;
    }
    if (transaction.targetComponentId != _componentId)
        return;
    if (transaction.expectedRevision != _revision)
    {
        send({ContractVersion, transaction.correlationId, _componentId, false,
              "configuration revision conflict", _revision},
             message.traceParent);
        return;
    }
    try
    {
        _configuration.apply(transaction.changes);
        ++_revision;
        send({ContractVersion, transaction.correlationId, _componentId, true, {}, _revision},
             message.traceParent);
    }
    catch (const std::exception& error)
    {
        send({ContractVersion, transaction.correlationId, _componentId, false, error.what(),
              _revision},
             message.traceParent);
    }
}

void ControlPlaneAgent::receiveLifecycle(const Transport::Message& message)
{
    if (message.type != "PocoDDS.LifecycleCommand.v1")
        return;
    std::lock_guard lock(_commandMutex);
    LifecycleCommand command;
    try
    {
        command = decodeLifecycleCommand(message.payload);
    }
    catch (const std::exception& error)
    {
        send({ContractVersion, {}, _componentId, false, error.what(), _revision},
             message.traceParent);
        return;
    }
    if (command.targetComponentId != _componentId)
        return;
    try
    {
        _lifecycleHandler(command);
        send({ContractVersion, command.correlationId, _componentId, true, {}, _revision},
             message.traceParent);
    }
    catch (const std::exception& error)
    {
        send({ContractVersion, command.correlationId, _componentId, false, error.what(), _revision},
             message.traceParent);
    }
}

void ControlPlaneAgent::send(CommandResult result, const std::string& traceParent)
{
    _transport.publish({ResultTopic, "PocoDDS.CommandResult.v1", encode(result), traceParent});
}
} // namespace PocoDDS::Control
