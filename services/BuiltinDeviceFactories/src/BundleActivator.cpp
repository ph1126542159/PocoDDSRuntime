#include "PocoDDS/Devices/CanSignalSensor.h"
#include "PocoDDS/Devices/LinuxSysfsGpioDevice.h"
#include "PocoDDS/Devices/LinuxSysfsLedDevice.h"
#include "PocoDDS/Devices/ModbusRegisterDevice.h"
#include "PocoDDS/Devices/NmeaGnssDevice.h"
#include "PocoDDS/Devices/SerialPortDevice.h"
#include "PocoDDS/Devices/SimulatedDevice.h"
#include "PocoDDS/Devices/XBeeAnalogSensor.h"
#include "PocoDDS/Gateways/FactoryService.h"
#include "PocoDDS/Protocols/CAN/LoopbackCanEndpoint.h"
#include "PocoDDS/Protocols/Serial/LoopbackSerialChannel.h"

#include <Poco/AutoPtr.h>
#include <Poco/ClassLibrary.h>
#include <Poco/Exception.h>
#include <Poco/Net/SocketAddress.h>
#include <Poco/OSP/BundleActivator.h>
#include <Poco/OSP/BundleContext.h>
#include <Poco/OSP/Properties.h>
#include <Poco/OSP/ServiceRef.h>
#include <Poco/OSP/ServiceRegistry.h>

#include <chrono>
#include <cstdint>
#include <memory>
#include <string>
#include <utility>
#include <vector>

namespace PocoDDS::Services
{
namespace
{
using PocoDDS::Gateways::DeviceFactoryService;
using PocoDDS::Gateways::FactoryDescriptor;
using PocoDDS::Gateways::FactoryInstance;

enum class DeviceKind { simulation, modbus, serial, gnss, gpio, xbee, can, led };

std::string key(const FactoryInstance& instance, const char* name)
{
    return instance.key(name);
}

class BuiltinDeviceFactory final : public DeviceFactoryService
{
public:
    explicit BuiltinDeviceFactory(DeviceKind kind): _kind(kind) {}

    FactoryDescriptor descriptor() const override
    {
        switch (_kind)
        {
        case DeviceKind::simulation: return {"simulation", "pdr.simulation", "simulation", true, 1};
        case DeviceKind::modbus: return {"modbus", "pdr.modbus", "modbus", false, 0};
        case DeviceKind::serial: return {"serial", "pdr.serial", "serial", false, 0};
        case DeviceKind::gnss: return {"gnss", "pdr.gnss", "gnss", false, 0};
        case DeviceKind::gpio: return {"gpio", "pdr.gpio", "gpio", false, 0};
        case DeviceKind::xbee: return {"xbee", "pdr.xbee", "xbee-sensor", false, 0};
        case DeviceKind::can: return {"can", "pdr.can", "can-sensor", false, 0};
        case DeviceKind::led: return {"led", "pdr.led", "led", false, 0};
        }
        throw Poco::IllegalStateException("Unknown built-in device factory kind");
    }

    std::unique_ptr<PocoDDS::Devices::Device> create(
        const Poco::Util::AbstractConfiguration& configuration,
        const FactoryInstance& instance) const override
    {
        switch (_kind)
        {
        case DeviceKind::simulation:
            return std::make_unique<PocoDDS::Devices::SimulatedDevice>(instance.id);
        case DeviceKind::modbus:
            return createModbus(configuration, instance);
        case DeviceKind::serial:
            return createSerial(configuration, instance);
        case DeviceKind::gnss:
            return createGnss(configuration, instance);
        case DeviceKind::gpio:
            return createGpio(configuration, instance);
        case DeviceKind::xbee:
            return createXbee(configuration, instance);
        case DeviceKind::can:
            return createCan(configuration, instance);
        case DeviceKind::led:
            return createLed(configuration, instance);
        }
        throw Poco::IllegalStateException("Unknown built-in device factory kind");
    }

private:
    static std::shared_ptr<PocoDDS::Protocols::Serial::ISerialChannel> serialChannel(
        const Poco::Util::AbstractConfiguration& configuration,
        const FactoryInstance& instance,
        int defaultBaudRate)
    {
        const auto transport = configuration.getString(key(instance, "transport"), "port");
        if (transport != "port" && transport != "loopback")
            throw Poco::InvalidArgumentException(
                "Unsupported " + key(instance, "transport"), transport);
        const auto port = configuration.getString(
            key(instance, "port"), transport == "loopback" ? instance.id : "");
        const auto baudRate = configuration.getInt(key(instance, "baudRate"), defaultBaudRate);
        if (transport == "loopback")
            return std::make_shared<PocoDDS::Protocols::Serial::LoopbackSerialChannel>(
                instance.id);
        return std::make_shared<PocoDDS::Protocols::Serial::SerialChannel>(port, baudRate);
    }

    static std::unique_ptr<PocoDDS::Devices::Device> createModbus(
        const Poco::Util::AbstractConfiguration& configuration,
        const FactoryInstance& instance)
    {
        const auto host = configuration.getString(key(instance, "host"), "127.0.0.1");
        const auto port = static_cast<Poco::UInt16>(
            configuration.getUInt(key(instance, "port"), 502));
        const auto unit = static_cast<std::uint8_t>(
            configuration.getUInt(key(instance, "unitId"), 1));
        const auto timeoutMilliseconds =
            configuration.getUInt(key(instance, "timeoutMilliseconds"), 2000);
        PocoDDS::Devices::ModbusReconnectPolicy policy;
        policy.readRetryAttempts =
            configuration.getUInt(key(instance, "readRetryAttempts"), 1);
        policy.retryDelay = std::chrono::milliseconds(
            configuration.getUInt(key(instance, "retryDelayMilliseconds"), 50));
        auto client = std::make_shared<PocoDDS::Protocols::Modbus::ModbusTcpClient>(
            Poco::Net::SocketAddress(host, port),
            Poco::Timespan(static_cast<Poco::Timespan::TimeDiff>(timeoutMilliseconds) *
                           Poco::Timespan::MILLISECONDS));
        return std::make_unique<PocoDDS::Devices::ModbusRegisterDevice>(
            instance.id, std::move(client), unit, policy);
    }

    static std::unique_ptr<PocoDDS::Devices::Device> createSerial(
        const Poco::Util::AbstractConfiguration& configuration,
        const FactoryInstance& instance)
    {
        const auto transport = configuration.getString(key(instance, "transport"), "port");
        if (transport != "port" && transport != "loopback")
            throw Poco::InvalidArgumentException(
                "Unsupported " + key(instance, "transport"), transport);
        const auto port = configuration.getString(
            key(instance, "port"), transport == "loopback" ? instance.id : "");
        const auto baudRate = configuration.getInt(key(instance, "baudRate"), 115200);
        const auto parameters = configuration.getString(key(instance, "parameters"), "8N1");
        const auto flowName = configuration.getString(key(instance, "flowControl"), "none");
        if (flowName != "none" && flowName != "rtscts")
            throw Poco::InvalidArgumentException(
                "Unsupported " + key(instance, "flowControl"), flowName);
        const auto flow = flowName == "rtscts" ? Poco::Serial::SerialPort::FLOW_RTSCTS
                                                : Poco::Serial::SerialPort::FLOW_NONE;
        PocoDDS::Devices::SerialReconnectPolicy policy;
        policy.enabled = configuration.getBool(key(instance, "reconnectEnabled"), true);
        policy.delay = std::chrono::milliseconds(
            configuration.getUInt(key(instance, "reconnectDelayMilliseconds"), 250));
        policy.readTimeout = std::chrono::milliseconds(
            configuration.getUInt(key(instance, "readTimeoutMilliseconds"), 250));
        std::shared_ptr<PocoDDS::Protocols::Serial::ISerialChannel> channel;
        if (transport == "loopback")
            channel = std::make_shared<PocoDDS::Protocols::Serial::LoopbackSerialChannel>(
                instance.id);
        else
            channel = std::make_shared<PocoDDS::Protocols::Serial::SerialChannel>(
                port, baudRate, parameters, flow);
        return std::make_unique<PocoDDS::Devices::SerialPortDevice>(
            instance.id, std::move(channel), policy);
    }

    static std::unique_ptr<PocoDDS::Devices::Device> createGnss(
        const Poco::Util::AbstractConfiguration& configuration,
        const FactoryInstance& instance)
    {
        PocoDDS::Devices::GnssRecoveryPolicy policy;
        policy.enabled = configuration.getBool(key(instance, "reconnectEnabled"), true);
        policy.reconnectDelay = std::chrono::milliseconds(
            configuration.getUInt(key(instance, "reconnectDelayMilliseconds"), 250));
        policy.readTimeout = std::chrono::milliseconds(
            configuration.getUInt(key(instance, "readTimeoutMilliseconds"), 250));
        policy.staleAfter = std::chrono::milliseconds(
            configuration.getUInt(key(instance, "staleAfterMilliseconds"), 5000));
        return std::make_unique<PocoDDS::Devices::NmeaGnssDevice>(
            instance.id, serialChannel(configuration, instance, 9600), policy);
    }

    static std::unique_ptr<PocoDDS::Devices::Device> createGpio(
        const Poco::Util::AbstractConfiguration& configuration,
        const FactoryInstance& instance)
    {
        const auto pin = static_cast<unsigned>(configuration.getUInt(key(instance, "pin")));
        const auto direction = configuration.getString(key(instance, "direction"), "in");
        if (direction != "in" && direction != "out")
            throw Poco::InvalidArgumentException(
                key(instance, "direction") + " must be 'in' or 'out'");
        const auto id = instance.legacy && !configuration.hasProperty(key(instance, "id"))
            ? "gpio-" + std::to_string(pin) : instance.id;
        return std::make_unique<PocoDDS::Devices::LinuxSysfsGpioDevice>(
            id, pin,
            direction == "out" ? PocoDDS::Devices::LinuxSysfsGpioDevice::Direction::output
                               : PocoDDS::Devices::LinuxSysfsGpioDevice::Direction::input,
            configuration.getString(key(instance, "sysfsRoot"), "/sys/class/gpio"),
            configuration.getBool(key(instance, "manageExport"), true),
            std::chrono::milliseconds(
                configuration.getUInt(key(instance, "exportTimeoutMilliseconds"), 1000)));
    }

    static std::unique_ptr<PocoDDS::Devices::Device> createXbee(
        const Poco::Util::AbstractConfiguration& configuration,
        const FactoryInstance& instance)
    {
        const auto transport = configuration.getString(key(instance, "transport"), "port");
        if (transport != "port" && transport != "loopback")
            throw Poco::InvalidArgumentException(
                "Unsupported " + key(instance, "transport"), transport);
        PocoDDS::Devices::XBeeAnalogSensor::Options options;
        options.id = instance.id;
        options.serialPort = configuration.getString(
            key(instance, "port"), transport == "loopback" ? instance.id : "");
        options.baudRate = configuration.getInt(key(instance, "baudRate"), 9600);
        options.escapedApiMode = configuration.getBool(key(instance, "escapedApiMode"), false);
        options.sourceAddress = std::stoull(
            configuration.getString(key(instance, "sourceAddress")), nullptr, 16);
        options.analogChannel = static_cast<unsigned>(
            configuration.getUInt(key(instance, "analogChannel"), 0));
        options.physicalQuantity =
            configuration.getString(key(instance, "physicalQuantity"), "raw");
        options.physicalUnit = configuration.getString(key(instance, "physicalUnit"), "count");
        const auto conversion = configuration.getString(key(instance, "conversion"), "raw");
        if (conversion == "raw")
            options.conversion = PocoDDS::Devices::XBeeAnalogSensor::Conversion::raw;
        else if (conversion == "millivolts")
            options.conversion = PocoDDS::Devices::XBeeAnalogSensor::Conversion::millivolts;
        else if (conversion == "temperature")
            options.conversion =
                PocoDDS::Devices::XBeeAnalogSensor::Conversion::temperatureCelsius;
        else if (conversion == "humidity")
            options.conversion =
                PocoDDS::Devices::XBeeAnalogSensor::Conversion::relativeHumidity;
        else
            throw Poco::InvalidArgumentException(
                "Unsupported " + key(instance, "conversion"), conversion);
        PocoDDS::Devices::XBeeRecoveryPolicy policy;
        policy.enabled = configuration.getBool(key(instance, "reconnectEnabled"), true);
        policy.reconnectDelay = std::chrono::milliseconds(
            configuration.getUInt(key(instance, "reconnectDelayMilliseconds"), 250));
        policy.receiveTimeout = std::chrono::milliseconds(
            configuration.getUInt(key(instance, "receiveTimeoutMilliseconds"), 250));
        policy.staleAfter = std::chrono::milliseconds(
            configuration.getUInt(key(instance, "staleAfterMilliseconds"), 5000));
        std::shared_ptr<PocoDDS::Protocols::Serial::ISerialChannel> channel;
        if (transport == "loopback")
            channel = std::make_shared<PocoDDS::Protocols::Serial::LoopbackSerialChannel>(
                instance.id);
        else
            channel = std::make_shared<PocoDDS::Protocols::Serial::SerialChannel>(
                options.serialPort, options.baudRate);
        return std::make_unique<PocoDDS::Devices::XBeeAnalogSensor>(
            std::move(options), std::move(channel), policy);
    }

    static std::unique_ptr<PocoDDS::Devices::Device> createCan(
        const Poco::Util::AbstractConfiguration& configuration,
        const FactoryInstance& instance)
    {
        PocoDDS::Devices::CanSignalSensor::Options options;
        options.id = instance.id;
        const auto transport = configuration.getString(key(instance, "transport"), "socketcan");
        if (transport != "socketcan" && transport != "loopback")
            throw Poco::InvalidArgumentException(
                "Unsupported " + key(instance, "transport"), transport);
        options.interfaceName = configuration.getString(key(instance, "interface"), "can0");
        const auto frameId = std::stoull(
            configuration.getString(key(instance, "frameId"), "0"), nullptr, 0);
        if (frameId > 0x1FFFFFFFULL)
            throw Poco::InvalidArgumentException(
                key(instance, "frameId") + " exceeds 29-bit CAN identifier");
        options.frameId = static_cast<std::uint32_t>(frameId);
        options.extended = configuration.getBool(key(instance, "extended"), false);
        if (!options.extended && frameId > 0x7FFULL)
            throw Poco::InvalidArgumentException(
                key(instance, "frameId") + " exceeds 11-bit standard CAN identifier");
        options.bitOffset = static_cast<std::size_t>(
            configuration.getUInt(key(instance, "bitOffset"), 0));
        options.bitLength = static_cast<std::size_t>(
            configuration.getUInt(key(instance, "bitLength"), 1));
        options.bitOrder = configuration.getString(key(instance, "bitOrder"), "little") == "big"
            ? PocoDDS::Protocols::CAN::BitOrder::bigEndian
            : PocoDDS::Protocols::CAN::BitOrder::littleEndian;
        options.signedValue = configuration.getBool(key(instance, "signed"), false);
        options.factor = configuration.getDouble(key(instance, "factor"), 1);
        options.offset = configuration.getDouble(key(instance, "offset"), 0);
        options.physicalQuantity =
            configuration.getString(key(instance, "physicalQuantity"), "raw");
        options.physicalUnit = configuration.getString(key(instance, "physicalUnit"), "count");
        PocoDDS::Devices::CanRecoveryPolicy policy;
        policy.enabled = configuration.getBool(key(instance, "reconnectEnabled"), true);
        policy.reconnectDelay = std::chrono::milliseconds(
            configuration.getUInt(key(instance, "reconnectDelayMilliseconds"), 250));
        policy.receiveTimeout = std::chrono::milliseconds(
            configuration.getUInt(key(instance, "receiveTimeoutMilliseconds"), 250));
        policy.staleAfter = std::chrono::milliseconds(
            configuration.getUInt(key(instance, "staleAfterMilliseconds"), 2000));
        std::shared_ptr<PocoDDS::Protocols::CAN::CanEndpoint> endpoint;
        if (transport == "loopback")
            endpoint = std::make_shared<PocoDDS::Protocols::CAN::LoopbackCanEndpoint>(instance.id);
        else
            endpoint = std::make_shared<PocoDDS::Protocols::CAN::SocketCanEndpoint>(
                options.interfaceName);
        return std::make_unique<PocoDDS::Devices::CanSignalSensor>(
            std::move(options), std::move(endpoint), policy);
    }

    static std::unique_ptr<PocoDDS::Devices::Device> createLed(
        const Poco::Util::AbstractConfiguration& configuration,
        const FactoryInstance& instance)
    {
        const auto id = instance.legacy && !configuration.hasProperty(key(instance, "id"))
            ? "status-led" : instance.id;
        return std::make_unique<PocoDDS::Devices::LinuxSysfsLedDevice>(
            id, configuration.getString(key(instance, "path")));
    }

    DeviceKind _kind;
};
}

class BuiltinDeviceFactoriesActivator final : public Poco::OSP::BundleActivator
{
public:
    void start(Poco::OSP::BundleContext::Ptr context) override
    {
        try
        {
            for (const auto kind : {DeviceKind::simulation, DeviceKind::modbus,
                                   DeviceKind::serial, DeviceKind::gnss,
                                   DeviceKind::gpio, DeviceKind::xbee,
                                   DeviceKind::can, DeviceKind::led})
                registerFactory(context, new BuiltinDeviceFactory(kind));
        }
        catch (...)
        {
            stop(context);
            throw;
        }
    }

    void stop(Poco::OSP::BundleContext::Ptr context) override
    {
        for (auto iterator = _references.rbegin(); iterator != _references.rend(); ++iterator)
            context->registry().unregisterService(*iterator);
        _references.clear();
        _factories.clear();
    }

private:
    void registerFactory(Poco::OSP::BundleContext::Ptr context, DeviceFactoryService* factory)
    {
        Poco::AutoPtr<DeviceFactoryService> owned(factory);
        const auto descriptor = factory->descriptor();
        Poco::OSP::Properties properties;
        properties.set(DeviceFactoryService::PROPERTY_KIND, DeviceFactoryService::FACTORY_KIND);
        properties.set(DeviceFactoryService::PROPERTY_TYPE, descriptor.type);
        _references.push_back(context->registry().registerService(
            "pdr.deviceFactory." + descriptor.type, owned, properties));
        _factories.push_back(std::move(owned));
    }

    std::vector<Poco::AutoPtr<DeviceFactoryService>> _factories;
    std::vector<Poco::OSP::ServiceRef::Ptr> _references;
};
}

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
    POCO_EXPORT_CLASS(PocoDDS::Services::BuiltinDeviceFactoriesActivator)
POCO_END_MANIFEST
