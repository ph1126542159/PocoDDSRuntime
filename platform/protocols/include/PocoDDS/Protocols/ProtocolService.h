#pragma once

#include "PocoDDS/Protocols/ProtocolDiagnostics.h"

#include <Poco/OSP/Service.h>

#include <atomic>
#include <mutex>
#include <string>
#include <typeinfo>

namespace PocoDDS::Protocols
{
class ProtocolService final : public Poco::OSP::Service
{
public:
    explicit ProtocolService(DiagnosticProtocol& protocol):
        _protocol(protocol),
        _name(protocol.name()),
        _knownOpen(protocol.isOpen()),
        _knownDiagnostics(protocol.diagnostics())
    {
        if (auto* provider = dynamic_cast<FailureDiagnosticProtocol*>(&_protocol))
            _knownFailure = provider->failure();
    }

    std::string name() const
    {
        return _name;
    }

    bool isOpen() const
    {
        std::unique_lock<std::mutex> lock(_mutex, std::try_to_lock);
        if (lock.owns_lock()) _knownOpen = _protocol.isOpen();
        return _knownOpen.load();
    }

    ProtocolDiagnostics diagnostics() const
    {
        std::unique_lock<std::mutex> operationLock(_mutex, std::try_to_lock);
        if (operationLock.owns_lock())
        {
            auto snapshot = _protocol.diagnostics();
            auto failure = failureSnapshot();
            std::lock_guard<std::mutex> snapshotLock(_snapshotMutex);
            _knownDiagnostics = snapshot;
            _knownFailure = std::move(failure);
            return snapshot;
        }
        std::lock_guard<std::mutex> snapshotLock(_snapshotMutex);
        return _knownDiagnostics;
    }

    PocoDDS::Reliability::Failure failure() const
    {
        std::lock_guard<std::mutex> snapshotLock(_snapshotMutex);
        return _knownFailure;
    }

    void open()
    {
        std::lock_guard<std::mutex> lock(_mutex);
        _desiredOpen = true;
        try
        {
            if (!_protocol.isOpen())
            {
                _knownOpen = false;
                _protocol.open();
            }
            _knownOpen = _protocol.isOpen();
        }
        catch (...)
        {
            _knownOpen = false;
            throw;
        }
    }

    void close()
    {
        std::lock_guard<std::mutex> lock(_mutex);
        _desiredOpen = false;
        if (_protocol.isOpen()) _protocol.close();
        _knownOpen = false;
    }

    void restart()
    {
        std::lock_guard<std::mutex> lock(_mutex);
        _desiredOpen = true;
        _protocol.close();
        _knownOpen = false;
        try
        {
            _knownOpen = false;
            _protocol.open();
            _knownOpen = _protocol.isOpen();
        }
        catch (...)
        {
            _knownOpen = false;
            throw;
        }
    }

    bool recoverIfDesired()
    {
        std::lock_guard<std::mutex> lock(_mutex);
        if (!_desiredOpen) return false;
        if (_protocol.isOpen())
        {
            _knownOpen = true;
            return false;
        }
        try
        {
            _protocol.open();
            _knownOpen = _protocol.isOpen();
        }
        catch (...)
        {
            _knownOpen = false;
            throw;
        }
        return true;
    }

    bool desiredOpen() const
    {
        return _desiredOpen.load();
    }

    const std::type_info& type() const override { return typeid(ProtocolService); }
    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) == typeid(ProtocolService).name() ||
               Poco::OSP::Service::isA(other);
    }

private:
    PocoDDS::Reliability::Failure failureSnapshot() const
    {
        if (auto* provider = dynamic_cast<const FailureDiagnosticProtocol*>(&_protocol))
            return provider->failure();
        PocoDDS::Reliability::Failure fallback;
        const auto legacy = _protocol.diagnostics().lastError;
        if (!legacy.empty())
        {
            fallback.code = "PDR-PROTOCOL-UNCLASSIFIED";
            fallback.active = true;
            fallback.message = legacy;
        }
        return fallback;
    }

    DiagnosticProtocol& _protocol;
    const std::string _name;
    mutable std::mutex _mutex;
    mutable std::mutex _snapshotMutex;
    std::atomic<bool> _desiredOpen{true};
    mutable std::atomic<bool> _knownOpen{false};
    mutable ProtocolDiagnostics _knownDiagnostics;
    mutable PocoDDS::Reliability::Failure _knownFailure;
};
}
