#include "PocoDDS/Control/ControlPlaneClient.h"

#include "PocoDDS/Control/ContractCodec.h"

#include <condition_variable>
#include <optional>
#include <stdexcept>
#include <utility>

namespace PocoDDS::Control
{
class ControlPlaneClient::Pending
{
  public:
    std::mutex mutex;
    std::condition_variable ready;
    std::optional<CommandResult> result;
    bool cancelled{false};
};

ControlPlaneClient::ControlPlaneClient(Transport::ITransport& transport, std::string clientId)
    : _transport(transport), _clientId(std::move(clientId))
{
    if (_clientId.empty())
        throw std::invalid_argument("control-plane client id is required");
    _resultSubscription = _transport.subscribe(
        ResultTopic, [this](const Transport::Message& message) { receive(message); });
}

ControlPlaneClient::~ControlPlaneClient()
{
    _resultSubscription.reset();
    std::unordered_map<std::string, std::shared_ptr<Pending>> pending;
    {
        std::lock_guard lock(_mutex);
        _stopping = true;
        pending.swap(_pending);
    }
    for (const auto& item : pending)
    {
        std::lock_guard lock(item.second->mutex);
        item.second->cancelled = true;
        item.second->ready.notify_all();
    }
}

CommandResult ControlPlaneClient::applyConfiguration(
    const std::string& targetComponentId, const std::map<std::string, std::string>& changes,
    std::uint64_t expectedRevision, std::chrono::milliseconds timeout,
    const std::string& traceParent)
{
    const auto id = correlationId();
    ConfigurationTransaction transaction{ContractVersion, id, targetComponentId, expectedRevision,
                                         changes};
    return request({ConfigurationTopic, "PocoDDS.ConfigurationTransaction.v1", encode(transaction),
                    traceParent},
                   id, timeout);
}

CommandResult ControlPlaneClient::executeLifecycle(const std::string& targetComponentId,
                                                   LifecycleAction action,
                                                   std::chrono::milliseconds gracefulTimeout,
                                                   std::chrono::milliseconds responseTimeout,
                                                   const std::string& traceParent)
{
    const auto id = correlationId();
    LifecycleCommand command{ContractVersion, id, targetComponentId, action,
                             static_cast<std::uint32_t>(gracefulTimeout.count())};
    return request({LifecycleTopic, "PocoDDS.LifecycleCommand.v1", encode(command), traceParent},
                   id, responseTimeout);
}

std::string ControlPlaneClient::correlationId()
{
    return _clientId + "-" + std::to_string(++_sequence);
}

CommandResult ControlPlaneClient::request(const Transport::Message& message, const std::string& id,
                                          std::chrono::milliseconds timeout)
{
    if (timeout <= std::chrono::milliseconds::zero())
        throw std::invalid_argument("control response timeout must be positive");
    auto pending = std::make_shared<Pending>();
    {
        std::lock_guard lock(_mutex);
        if (_stopping)
            throw std::runtime_error("control-plane client is stopping");
        _pending.emplace(id, pending);
    }
    try
    {
        _transport.publish(message);
    }
    catch (...)
    {
        std::lock_guard lock(_mutex);
        _pending.erase(id);
        throw;
    }

    std::unique_lock pendingLock(pending->mutex);
    const bool completed = pending->ready.wait_for(
        pendingLock, timeout, [&] { return pending->result.has_value() || pending->cancelled; });
    {
        std::lock_guard lock(_mutex);
        _pending.erase(id);
    }
    if (!completed)
        throw std::runtime_error("control command timed out");
    if (pending->cancelled)
        throw std::runtime_error("control-plane client stopped");
    return *pending->result;
}

void ControlPlaneClient::receive(const Transport::Message& message)
{
    if (message.type != "PocoDDS.CommandResult.v1")
        return;
    CommandResult result;
    try
    {
        result = decodeCommandResult(message.payload);
    }
    catch (...)
    {
        return;
    }
    std::shared_ptr<Pending> pending;
    {
        std::lock_guard lock(_mutex);
        const auto found = _pending.find(result.correlationId);
        if (found == _pending.end())
            return;
        pending = found->second;
    }
    {
        std::lock_guard lock(pending->mutex);
        pending->result = std::move(result);
    }
    pending->ready.notify_all();
}
} // namespace PocoDDS::Control
