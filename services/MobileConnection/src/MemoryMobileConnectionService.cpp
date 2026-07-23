#include "IoT/MobileConnection/MemoryMobileConnectionService.h"

#include <Poco/Exception.h>

namespace IoT::MobileConnection
{
std::string MemoryMobileConnectionService::deviceName() const { return "memory-modem"; }
std::string MemoryMobileConnectionService::imei() const { return {}; }
SIMState MemoryMobileConnectionService::simState() const { return MC_SIM_READY; }
void MemoryMobileConnectionService::unlockSIM(const std::string&) {}
void MemoryMobileConnectionService::lockSIM(const std::string&) {}
void MemoryMobileConnectionService::enterPIN(const std::string&) {}
std::string MemoryMobileConnectionService::imsi() const { return {}; }
std::string MemoryMobileConnectionService::phoneNumber() const { return {}; }
std::string MemoryMobileConnectionService::iccid() const { return {}; }

void MemoryMobileConnectionService::setAPN(const std::string& apn)
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    _apn = apn;
}

std::string MemoryMobileConnectionService::getAPN() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    return _apn;
}

void MemoryMobileConnectionService::setPDPType(PDPType type)
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    _pdpType = type;
}

PDPType MemoryMobileConnectionService::getPDPType() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    return _pdpType;
}

void MemoryMobileConnectionService::authenticate(
    AuthMethod method, const std::string& username, const std::string& password)
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    _auth = method;
    _username = username;
    _password = password;
}

void MemoryMobileConnectionService::enableRadio(bool enable)
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    _radioEnabled = enable;
    if (!enable)
        _dataConnected = false;
}

bool MemoryMobileConnectionService::isRadioEnabled() const
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    return _radioEnabled;
}

std::string MemoryMobileConnectionService::networkOperator() const { return "simulated"; }

RegistrationStatus MemoryMobileConnectionService::registrationStatus() const
{
    return isRadioEnabled() ? MC_REG_HOME : MC_REG_NONE;
}

RadioAccessTechnology MemoryMobileConnectionService::radioAccessTechnology() const
{
    return isRadioEnabled() ? MC_RAT_LTE : MC_RAT_UNKNOWN;
}

int MemoryMobileConnectionService::signalStrength() const
{
    return isRadioEnabled() ? 5 : 0;
}

bool MemoryMobileConnectionService::isDataConnected()
{
    Poco::FastMutex::ScopedLock lock(_mutex);
    return _dataConnected;
}

void MemoryMobileConnectionService::connectData()
{
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        if (!_radioEnabled)
            throw Poco::IllegalStateException("mobile radio is disabled");
        if (_dataConnected)
            return;
        _dataConnected = true;
    }
    dataConnected(this);
}

void MemoryMobileConnectionService::disconnectData()
{
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        if (!_dataConnected)
            return;
        _dataConnected = false;
    }
    dataDisconnected(this);
}
} // namespace IoT::MobileConnection
