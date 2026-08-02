#include "PocoDDS/Devices/Device.h"
#include "PocoDDS/Devices/DeviceService.h"
#include "PocoDDS/Devices/CanSignalSensor.h"
#include "PocoDDS/Protocols/CAN/LoopbackCanEndpoint.h"
#include "PocoDDS/Devices/LinuxSysfsGpioDevice.h"
#include "PocoDDS/Devices/LinuxSysfsLedDevice.h"
#include "PocoDDS/Devices/ModbusRegisterDevice.h"
#include "PocoDDS/Devices/NmeaGnssDevice.h"
#include "PocoDDS/Devices/SerialPortDevice.h"
#include "PocoDDS/Protocols/Serial/LoopbackSerialChannel.h"
#include "PocoDDS/Devices/SimulatedDevice.h"
#include "PocoDDS/Devices/XBeeAnalogSensor.h"
#include "PocoDDS/DDS/DeviceBridge.h"
#include "PocoDDS/DDS/Runtime.h"
#include "PocoDDS/Configuration/IndexedConfiguration.h"

#include "Poco/ClassLibrary.h"
#include "Poco/Exception.h"
#include "Poco/Net/SocketAddress.h"
#include "Poco/OSP/Bundle.h"
#include "Poco/OSP/BundleActivator.h"
#include "Poco/OSP/BundleContext.h"
#include "Poco/OSP/Properties.h"
#include "Poco/OSP/PreferencesService.h"
#include "Poco/OSP/Service.h"
#include "Poco/OSP/ServiceFinder.h"
#include "Poco/OSP/ServiceRef.h"
#include "Poco/OSP/ServiceRegistry.h"

#include <memory>
#include <chrono>
#include <string>
#include <unordered_set>
#include <vector>

namespace PocoDDS::Services
{
class DeviceGatewayActivator final : public Poco::OSP::BundleActivator
{
public:
    void addDevice(Poco::OSP::BundleContext::Ptr context,
                   std::unique_ptr<PocoDDS::Devices::Device> device,
                   bool required = true)
    {
        if (!_deviceIds.insert(device->id()).second)
            throw Poco::InvalidArgumentException("Duplicate device id", device->id());
        auto bridge =
            std::make_unique<PocoDDS::FastDDS::DeviceBridge>(*_runtime, *device);
        try
        {
            bridge->start();
        }
        catch (...)
        {
            _deviceIds.erase(device->id());
            throw;
        }
        Poco::OSP::Properties properties;
        properties.set("pdr.device", device->id());
        properties.set("pdr.deviceType", device->type());
        properties.set("pdr.deviceState", "ready");
        properties.set("pdr.deviceRequired", required ? "true" : "false");
        properties.set("pdr.bundle", context->thisBundle()->symbolicName());
        Poco::OSP::ServiceRef::Ptr service;
        try
        {
            service = context->registry().registerService(
                "pdr.device." + device->id(),
                new PocoDDS::Devices::DeviceService(*device), properties);
        }
        catch (...)
        {
            if (service)
                context->registry().unregisterService(service);
            bridge->stop();
            _deviceIds.erase(device->id());
            throw;
        }
        _devices.push_back(std::move(device));
        _bridges.push_back(std::move(bridge));
        _services.push_back(std::move(service));
    }

    void start(Poco::OSP::BundleContext::Ptr context) override
    {
        auto preferences =
            Poco::OSP::ServiceFinder::find<Poco::OSP::PreferencesService>(context);
        auto configuration = preferences->configuration();
        const auto domainId =
            static_cast<std::uint32_t>(configuration->getUInt("pdr.fastdds.domainId", 0));
        _runtime =
            std::make_unique<PocoDDS::FastDDS::Runtime>(domainId, "pdr-device-gateway");
        _runtime->start();
        const auto instances = [&](const std::string& base,
                                   bool legacyEnabled,
                                   std::size_t defaultCount,
                                   const std::string& idPrefix) {
            return PocoDDS::Configuration::indexedInstances(
                *configuration, base, legacyEnabled, defaultCount, idPrefix);
        };
        const auto key = [](const auto& instance, const char* name) {
            return instance.prefix + "." + name;
        };
        const auto addConfiguredDevice = [&](const auto& instance, auto device) {
            addDevice(context, std::move(device),
                      configuration->getBool(key(instance, "required"), true));
        };

        for (const auto& instance : instances("pdr.simulation", true, 1, "simulation"))
            if (instance.enabled)
                addConfiguredDevice(instance,
                          std::make_unique<PocoDDS::Devices::SimulatedDevice>(instance.id));

        for (const auto& instance : instances("pdr.modbus", false, 0, "modbus"))
        {
            if (!instance.enabled)
                continue;
            const auto host = configuration->getString(key(instance, "host"), "127.0.0.1");
            const auto port =
                static_cast<Poco::UInt16>(configuration->getUInt(key(instance, "port"), 502));
            const auto unit =
                static_cast<std::uint8_t>(configuration->getUInt(key(instance, "unitId"), 1));
            const auto timeoutMilliseconds =
                configuration->getUInt(key(instance, "timeoutMilliseconds"), 2000);
            PocoDDS::Devices::ModbusReconnectPolicy reconnectPolicy;
            reconnectPolicy.readRetryAttempts =
                configuration->getUInt(key(instance, "readRetryAttempts"), 1);
            reconnectPolicy.retryDelay = std::chrono::milliseconds(
                configuration->getUInt(key(instance, "retryDelayMilliseconds"), 50));
            auto client =
                std::make_shared<PocoDDS::Protocols::Modbus::ModbusTcpClient>(
                    Poco::Net::SocketAddress(host, port),
                    Poco::Timespan(static_cast<Poco::Timespan::TimeDiff>(
                        timeoutMilliseconds) * Poco::Timespan::MILLISECONDS));
            addConfiguredDevice(instance,
                      std::make_unique<PocoDDS::Devices::ModbusRegisterDevice>(
                          instance.id, std::move(client), unit, reconnectPolicy));
        }

        for (const auto& instance : instances("pdr.serial", false, 0, "serial"))
        {
            if (!instance.enabled)
                continue;
            const auto transport =
                configuration->getString(key(instance, "transport"), "port");
            if (transport != "port" && transport != "loopback")
                throw Poco::InvalidArgumentException(
                    "Unsupported " + key(instance, "transport"), transport);
            const auto port = configuration->getString(
                key(instance, "port"), transport == "loopback" ? instance.id : "");
            const auto baudRate = configuration->getInt(key(instance, "baudRate"), 115200);
            const auto parameters = configuration->getString(key(instance, "parameters"), "8N1");
            const auto flowControlName =
                configuration->getString(key(instance, "flowControl"), "none");
            if (flowControlName != "none" && flowControlName != "rtscts")
                throw Poco::InvalidArgumentException(
                    "Unsupported " + key(instance, "flowControl"), flowControlName);
            const auto flowControl = flowControlName == "rtscts"
                ? Poco::Serial::SerialPort::FLOW_RTSCTS
                : Poco::Serial::SerialPort::FLOW_NONE;
            PocoDDS::Devices::SerialReconnectPolicy reconnectPolicy;
            reconnectPolicy.enabled =
                configuration->getBool(key(instance, "reconnectEnabled"), true);
            reconnectPolicy.delay = std::chrono::milliseconds(
                configuration->getUInt(key(instance, "reconnectDelayMilliseconds"), 250));
            reconnectPolicy.readTimeout = std::chrono::milliseconds(
                configuration->getUInt(key(instance, "readTimeoutMilliseconds"), 250));
            std::shared_ptr<PocoDDS::Protocols::Serial::ISerialChannel> channel;
            if (transport == "loopback")
                channel = std::make_shared<
                    PocoDDS::Protocols::Serial::LoopbackSerialChannel>(instance.id);
            else
                channel = std::make_shared<PocoDDS::Protocols::Serial::SerialChannel>(
                    port, baudRate, parameters, flowControl);
            addConfiguredDevice(instance,
                      std::make_unique<PocoDDS::Devices::SerialPortDevice>(
                          instance.id, std::move(channel), reconnectPolicy));
        }

        for (const auto& instance : instances("pdr.gnss", false, 0, "gnss"))
        {
            if (!instance.enabled)
                continue;
            const auto transport =
                configuration->getString(key(instance, "transport"), "port");
            if (transport != "port" && transport != "loopback")
                throw Poco::InvalidArgumentException(
                    "Unsupported " + key(instance, "transport"), transport);
            const auto port = configuration->getString(
                key(instance, "port"), transport == "loopback" ? instance.id : "");
            const auto baudRate = configuration->getInt(key(instance, "baudRate"), 9600);
            PocoDDS::Devices::GnssRecoveryPolicy recoveryPolicy;
            recoveryPolicy.enabled =
                configuration->getBool(key(instance, "reconnectEnabled"), true);
            recoveryPolicy.reconnectDelay = std::chrono::milliseconds(
                configuration->getUInt(key(instance, "reconnectDelayMilliseconds"), 250));
            recoveryPolicy.readTimeout = std::chrono::milliseconds(
                configuration->getUInt(key(instance, "readTimeoutMilliseconds"), 250));
            recoveryPolicy.staleAfter = std::chrono::milliseconds(
                configuration->getUInt(key(instance, "staleAfterMilliseconds"), 5000));
            std::shared_ptr<PocoDDS::Protocols::Serial::ISerialChannel> channel;
            if (transport == "loopback")
                channel = std::make_shared<
                    PocoDDS::Protocols::Serial::LoopbackSerialChannel>(instance.id);
            else
                channel = std::make_shared<PocoDDS::Protocols::Serial::SerialChannel>(
                    port, baudRate);
            addConfiguredDevice(instance,
                      std::make_unique<PocoDDS::Devices::NmeaGnssDevice>(
                          instance.id, std::move(channel), recoveryPolicy));
        }

        for (const auto& instance : instances("pdr.gpio", false, 0, "gpio"))
        {
            if (!instance.enabled)
                continue;
            const auto pin =
                static_cast<unsigned>(configuration->getUInt(key(instance, "pin")));
            const auto direction =
                configuration->getString(key(instance, "direction"), "in");
            if (direction != "in" && direction != "out")
                throw Poco::InvalidArgumentException(
                    key(instance, "direction") + " must be 'in' or 'out'");
            const auto id = instance.legacy &&
                    !configuration->hasProperty(key(instance, "id"))
                ? "gpio-" + std::to_string(pin)
                : instance.id;
            addConfiguredDevice(instance,
                      std::make_unique<PocoDDS::Devices::LinuxSysfsGpioDevice>(
                          id,
                          pin,
                          direction == "out"
                              ? PocoDDS::Devices::LinuxSysfsGpioDevice::Direction::output
                              : PocoDDS::Devices::LinuxSysfsGpioDevice::Direction::input,
                          configuration->getString(key(instance, "sysfsRoot"),
                                                   "/sys/class/gpio"),
                          configuration->getBool(key(instance, "manageExport"), true),
                          std::chrono::milliseconds(configuration->getUInt(
                              key(instance, "exportTimeoutMilliseconds"), 1000))));
        }

        for (const auto& instance : instances("pdr.xbee", false, 0, "xbee-sensor"))
        {
            if (!instance.enabled)
                continue;
            const auto transport =
                configuration->getString(key(instance, "transport"), "port");
            if (transport != "port" && transport != "loopback")
                throw Poco::InvalidArgumentException(
                    "Unsupported " + key(instance, "transport"), transport);
            PocoDDS::Devices::XBeeAnalogSensor::Options options;
            options.id = instance.id;
            options.serialPort = configuration->getString(
                key(instance, "port"), transport == "loopback" ? instance.id : "");
            options.baudRate = configuration->getInt(key(instance, "baudRate"), 9600);
            options.escapedApiMode =
                configuration->getBool(key(instance, "escapedApiMode"), false);
            options.sourceAddress = std::stoull(
                configuration->getString(key(instance, "sourceAddress")), nullptr, 16);
            options.analogChannel =
                static_cast<unsigned>(configuration->getUInt(key(instance, "analogChannel"), 0));
            options.physicalQuantity =
                configuration->getString(key(instance, "physicalQuantity"), "raw");
            options.physicalUnit =
                configuration->getString(key(instance, "physicalUnit"), "count");

            const auto conversion =
                configuration->getString(key(instance, "conversion"), "raw");
            if (conversion == "raw")
                options.conversion =
                    PocoDDS::Devices::XBeeAnalogSensor::Conversion::raw;
            else if (conversion == "millivolts")
                options.conversion =
                    PocoDDS::Devices::XBeeAnalogSensor::Conversion::millivolts;
            else if (conversion == "temperature")
                options.conversion =
                    PocoDDS::Devices::XBeeAnalogSensor::Conversion::temperatureCelsius;
            else if (conversion == "humidity")
                options.conversion =
                    PocoDDS::Devices::XBeeAnalogSensor::Conversion::relativeHumidity;
            else
                throw Poco::InvalidArgumentException(
                    "Unsupported " + key(instance, "conversion"), conversion);

            PocoDDS::Devices::XBeeRecoveryPolicy recoveryPolicy;
            recoveryPolicy.enabled =
                configuration->getBool(key(instance, "reconnectEnabled"), true);
            recoveryPolicy.reconnectDelay = std::chrono::milliseconds(
                configuration->getUInt(key(instance, "reconnectDelayMilliseconds"), 250));
            recoveryPolicy.receiveTimeout = std::chrono::milliseconds(
                configuration->getUInt(key(instance, "receiveTimeoutMilliseconds"), 250));
            recoveryPolicy.staleAfter = std::chrono::milliseconds(
                configuration->getUInt(key(instance, "staleAfterMilliseconds"), 5000));
            std::shared_ptr<PocoDDS::Protocols::Serial::ISerialChannel> channel;
            if (transport == "loopback")
                channel = std::make_shared<
                    PocoDDS::Protocols::Serial::LoopbackSerialChannel>(instance.id);
            else
                channel = std::make_shared<PocoDDS::Protocols::Serial::SerialChannel>(
                    options.serialPort, options.baudRate);
            addConfiguredDevice(instance,
                std::make_unique<PocoDDS::Devices::XBeeAnalogSensor>(
                    std::move(options), std::move(channel), recoveryPolicy));
        }

        for (const auto& instance : instances("pdr.can", false, 0, "can-sensor"))
        {
            if (!instance.enabled)
                continue;
            PocoDDS::Devices::CanSignalSensor::Options options;
            options.id = instance.id;
            const auto transport =
                configuration->getString(key(instance, "transport"), "socketcan");
            if (transport != "socketcan" && transport != "loopback")
                throw Poco::InvalidArgumentException(
                    "Unsupported " + key(instance, "transport"), transport);
            options.interfaceName =
                configuration->getString(key(instance, "interface"), "can0");
            const auto frameId = std::stoull(
                configuration->getString(key(instance, "frameId"), "0"), nullptr, 0);
            if (frameId > 0x1FFFFFFFULL)
                throw Poco::InvalidArgumentException(
                    key(instance, "frameId") + " exceeds 29-bit CAN identifier");
            options.frameId = static_cast<std::uint32_t>(frameId);
            options.extended =
                configuration->getBool(key(instance, "extended"), false);
            if (!options.extended && frameId > 0x7FFULL)
                throw Poco::InvalidArgumentException(
                    key(instance, "frameId") + " exceeds 11-bit standard CAN identifier");
            options.bitOffset =
                static_cast<std::size_t>(configuration->getUInt(key(instance, "bitOffset"), 0));
            options.bitLength =
                static_cast<std::size_t>(configuration->getUInt(key(instance, "bitLength"), 1));
            options.bitOrder =
                configuration->getString(key(instance, "bitOrder"), "little") == "big"
                    ? PocoDDS::Protocols::CAN::BitOrder::bigEndian
                    : PocoDDS::Protocols::CAN::BitOrder::littleEndian;
            options.signedValue =
                configuration->getBool(key(instance, "signed"), false);
            options.factor = configuration->getDouble(key(instance, "factor"), 1);
            options.offset = configuration->getDouble(key(instance, "offset"), 0);
            options.physicalQuantity =
                configuration->getString(key(instance, "physicalQuantity"), "raw");
            options.physicalUnit =
                configuration->getString(key(instance, "physicalUnit"), "count");
            PocoDDS::Devices::CanRecoveryPolicy recoveryPolicy;
            recoveryPolicy.enabled =
                configuration->getBool(key(instance, "reconnectEnabled"), true);
            recoveryPolicy.reconnectDelay = std::chrono::milliseconds(
                configuration->getUInt(key(instance, "reconnectDelayMilliseconds"), 250));
            recoveryPolicy.receiveTimeout = std::chrono::milliseconds(
                configuration->getUInt(key(instance, "receiveTimeoutMilliseconds"), 250));
            recoveryPolicy.staleAfter = std::chrono::milliseconds(
                configuration->getUInt(key(instance, "staleAfterMilliseconds"), 2000));
            std::shared_ptr<PocoDDS::Protocols::CAN::CanEndpoint> endpoint;
            if (transport == "loopback")
                endpoint = std::make_shared<
                    PocoDDS::Protocols::CAN::LoopbackCanEndpoint>(instance.id);
            else
                endpoint = std::make_shared<PocoDDS::Protocols::CAN::SocketCanEndpoint>(
                    options.interfaceName);
            addConfiguredDevice(instance,
                      std::make_unique<PocoDDS::Devices::CanSignalSensor>(
                          std::move(options), std::move(endpoint), recoveryPolicy));
        }

        for (const auto& instance : instances("pdr.led", false, 0, "led"))
        {
            if (!instance.enabled)
                continue;
            addConfiguredDevice(instance,
                      std::make_unique<PocoDDS::Devices::LinuxSysfsLedDevice>(
                          instance.legacy &&
                                  !configuration->hasProperty(key(instance, "id"))
                              ? "status-led"
                              : instance.id,
                          configuration->getString(key(instance, "path"))));
        }

        _context = context;
        context->logger().information("Fast DDS device gateway started with %z device(s) "
                                      "on domain %u.",
                                      _devices.size(), domainId);
    }

    void stop(Poco::OSP::BundleContext::Ptr context) override
    {
        for (auto& bridge : _bridges)
            bridge->stop();
        for (auto& service : _services)
            context->registry().unregisterService(service);
        _services.clear();
        _bridges.clear();
        _devices.clear();
        _deviceIds.clear();
        if (_runtime)
            _runtime->stop();
        _runtime.reset();
        _context = nullptr;
    }

private:
    Poco::OSP::BundleContext::Ptr _context;
    std::vector<Poco::OSP::ServiceRef::Ptr> _services;
    std::unique_ptr<PocoDDS::FastDDS::Runtime> _runtime;
    std::vector<std::unique_ptr<PocoDDS::Devices::Device>> _devices;
    std::unordered_set<std::string> _deviceIds;
    std::vector<std::unique_ptr<PocoDDS::FastDDS::DeviceBridge>> _bridges;
};
} // namespace PocoDDS::Services

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
POCO_EXPORT_CLASS(PocoDDS::Services::DeviceGatewayActivator)
POCO_END_MANIFEST
