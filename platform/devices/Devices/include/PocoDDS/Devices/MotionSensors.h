#pragma once

#include "PocoDDS/Devices/Device.h"
#include "PocoDDS/Devices/DeviceTypes.h"

#include <functional>

namespace PocoDDS::Devices
{
class Accelerometer : public Device
{
public:
    using Handler = std::function<void(const Vector3&)>;
    virtual Vector3 acceleration() const = 0;
    virtual void setAccelerationHandler(Handler handler) = 0;
};

class Gyroscope : public Device
{
public:
    using Handler = std::function<void(const Vector3&)>;
    virtual Vector3 angularVelocity() const = 0;
    virtual void setAngularVelocityHandler(Handler handler) = 0;
};

class Magnetometer : public Device
{
public:
    using Handler = std::function<void(const Vector3&)>;
    virtual Vector3 magneticField() const = 0;
    virtual void setMagneticFieldHandler(Handler handler) = 0;
};
} // namespace PocoDDS::Devices
