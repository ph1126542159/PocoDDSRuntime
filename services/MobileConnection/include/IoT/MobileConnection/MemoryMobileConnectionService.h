#pragma once

#include "IoT/MobileConnection/MobileConnectionService.h"

#include <Poco/Mutex.h>

namespace IoT::MobileConnection
{
class MemoryMobileConnectionService final : public MobileConnectionService
{
public:
    std::string deviceName() const override;
    std::string imei() const override;
    SIMState simState() const override;
    void unlockSIM(const std::string& pin) override;
    void lockSIM(const std::string& pin) override;
    void enterPIN(const std::string& pin) override;
    std::string imsi() const override;
    std::string phoneNumber() const override;
    std::string iccid() const override;
    void setAPN(const std::string& apn) override;
    std::string getAPN() const override;
    void setPDPType(PDPType type) override;
    PDPType getPDPType() const override;
    void authenticate(AuthMethod method,
                      const std::string& username,
                      const std::string& password) override;
    void enableRadio(bool enable) override;
    bool isRadioEnabled() const override;
    std::string networkOperator() const override;
    RegistrationStatus registrationStatus() const override;
    RadioAccessTechnology radioAccessTechnology() const override;
    int signalStrength() const override;
    bool isDataConnected() override;
    void connectData() override;
    void disconnectData() override;

private:
    mutable Poco::FastMutex _mutex;
    std::string _apn;
    std::string _username;
    std::string _password;
    AuthMethod _auth{MC_AUTH_NONE};
    PDPType _pdpType{MC_PDP_IPV4};
    bool _radioEnabled{false};
    bool _dataConnected{false};
};
} // namespace IoT::MobileConnection
