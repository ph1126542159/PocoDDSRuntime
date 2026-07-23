#include "PocoDDS/Devices/Device.h"
#include "PocoDDS/Devices/CanSignalSensor.h"
#include "PocoDDS/Devices/LinuxSysfsGpioDevice.h"
#include "PocoDDS/Devices/LinuxSysfsLedDevice.h"
#include "PocoDDS/Devices/ModbusRegisterDevice.h"
#include "PocoDDS/Devices/NmeaGnssDevice.h"
#include "PocoDDS/Devices/SerialPortDevice.h"
#include "PocoDDS/Devices/SimulatedDevice.h"
#include "PocoDDS/Devices/XBeeAnalogSensor.h"
#include "PocoDDS/DDS/DeviceBridge.h"
#include "PocoDDS/DDS/Runtime.h"

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
#include <string>
#include <typeinfo>
#include <vector>

namespace PocoDDS::Services
{
class DeviceService final : public Poco::OSP::Service
{
public:
    explicit DeviceService(PocoDDS::Devices::Device& device) : _device(device) {}

    PocoDDS::Devices::Device& device() noexcept { return _device; }

    const std::type_info& type() const override { return typeid(DeviceService); }

    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) == typeid(DeviceService).name() ||
               Poco::OSP::Service::isA(other);
    }

private:
    PocoDDS::Devices::Device& _device;
};

class DeviceGatewayActivator final : public Poco::OSP::BundleActivator
{
public:
    void addDevice(Poco::OSP::BundleContext::Ptr context,
                   std::unique_ptr<PocoDDS::Devices::Device> device)
    {
        Poco::OSP::Properties properties;
        properties.set("pdr.device", device->id());
        properties.set("pdr.deviceType", device->type());
        properties.set("pdr.bundle", context->thisBundle()->symbolicName());
        _services.push_back(context->registry().registerService(
            "pdr.device." + device->id(), new DeviceService(*device), properties));

        auto bridge =
            std::make_unique<PocoDDS::FastDDS::DeviceBridge>(*_runtime, *device);
        bridge->start();
        _devices.push_back(std::move(device));
        _bridges.push_back(std::move(bridge));
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
        addDevice(context,
                  std::make_unique<PocoDDS::Devices::SimulatedDevice>("simulation-1"));

        if (configuration->getBool("pdr.modbus.enabled", false))
        {
            const auto host = configuration->getString("pdr.modbus.host", "127.0.0.1");
            const auto port =
                static_cast<Poco::UInt16>(configuration->getUInt("pdr.modbus.port", 502));
            const auto unit =
                static_cast<std::uint8_t>(configuration->getUInt("pdr.modbus.unitId", 1));
            auto client =
                std::make_shared<PocoDDS::Protocols::Modbus::ModbusTcpClient>(
                    Poco::Net::SocketAddress(host, port));
            addDevice(context,
                      std::make_unique<PocoDDS::Devices::ModbusRegisterDevice>(
                          "modbus-1", std::move(client), unit));
        }

        if (configuration->getBool("pdr.serial.enabled", false))
        {
            const auto port =
                configuration->getString("pdr.serial.port");
            const auto baudRate =
                configuration->getInt("pdr.serial.baudRate", 115200);
            addDevice(context,
                      std::make_unique<PocoDDS::Devices::SerialPortDevice>(
                          "serial-1", port, baudRate));
        }

        if (configuration->getBool("pdr.gnss.enabled", false))
        {
            const auto port =
                configuration->getString("pdr.gnss.port");
            const auto baudRate =
                configuration->getInt("pdr.gnss.baudRate", 9600);
            addDevice(context,
                      std::make_unique<PocoDDS::Devices::NmeaGnssDevice>(
                          "gnss-1", port, baudRate));
        }

        if (configuration->getBool("pdr.gpio.enabled", false))
        {
            const auto pin =
                static_cast<unsigned>(configuration->getUInt("pdr.gpio.pin"));
            const auto direction =
                configuration->getString("pdr.gpio.direction", "in");
            if (direction != "in" && direction != "out")
                throw Poco::InvalidArgumentException(
                    "pdr.gpio.direction must be 'in' or 'out'");
            addDevice(context,
                      std::make_unique<PocoDDS::Devices::LinuxSysfsGpioDevice>(
                          "gpio-" + std::to_string(pin),
                          pin,
                          direction == "out"
                              ? PocoDDS::Devices::LinuxSysfsGpioDevice::Direction::output
                              : PocoDDS::Devices::LinuxSysfsGpioDevice::Direction::input,
                          configuration->getString(
                              "pdr.gpio.sysfsRoot", "/sys/class/gpio"),
                          configuration->getBool("pdr.gpio.manageExport", true)));
        }

        if (configuration->getBool("pdr.xbee.enabled", false))
        {
            PocoDDS::Devices::XBeeAnalogSensor::Options options;
            options.id = configuration->getString("pdr.xbee.id", "xbee-sensor-1");
            options.serialPort = configuration->getString("pdr.xbee.port");
            options.baudRate = configuration->getInt("pdr.xbee.baudRate", 9600);
            options.escapedApiMode =
                configuration->getBool("pdr.xbee.escapedApiMode", false);
            options.sourceAddress = std::stoull(
                configuration->getString("pdr.xbee.sourceAddress"), nullptr, 16);
            options.analogChannel =
                static_cast<unsigned>(configuration->getUInt("pdr.xbee.analogChannel", 0));
            options.physicalQuantity =
                configuration->getString("pdr.xbee.physicalQuantity", "raw");
            options.physicalUnit =
                configuration->getString("pdr.xbee.physicalUnit", "count");

            const auto conversion =
                configuration->getString("pdr.xbee.conversion", "raw");
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
                    "Unsupported pdr.xbee.conversion", conversion);

            addDevice(context,
                      std::make_unique<PocoDDS::Devices::XBeeAnalogSensor>(
                          std::move(options)));
        }

        if (configuration->getBool("pdr.can.enabled", false))
        {
            PocoDDS::Devices::CanSignalSensor::Options options;
            options.id = configuration->getString("pdr.can.id", "can-sensor-1");
            options.interfaceName =
                configuration->getString("pdr.can.interface", "can0");
            options.frameId = static_cast<std::uint32_t>(std::stoul(
                configuration->getString("pdr.can.frameId", "0"), nullptr, 0));
            options.bitOffset =
                static_cast<std::size_t>(configuration->getUInt("pdr.can.bitOffset", 0));
            options.bitLength =
                static_cast<std::size_t>(configuration->getUInt("pdr.can.bitLength", 1));
            options.bitOrder =
                configuration->getString("pdr.can.bitOrder", "little") == "big"
                    ? PocoDDS::Protocols::CAN::BitOrder::bigEndian
                    : PocoDDS::Protocols::CAN::BitOrder::littleEndian;
            options.signedValue =
                configuration->getBool("pdr.can.signed", false);
            options.factor = configuration->getDouble("pdr.can.factor", 1);
            options.offset = configuration->getDouble("pdr.can.offset", 0);
            options.physicalQuantity =
                configuration->getString("pdr.can.physicalQuantity", "raw");
            options.physicalUnit =
                configuration->getString("pdr.can.physicalUnit", "count");
            addDevice(context,
                      std::make_unique<PocoDDS::Devices::CanSignalSensor>(
                          std::move(options)));
        }

        if (configuration->getBool("pdr.led.enabled", false))
        {
            addDevice(context,
                      std::make_unique<PocoDDS::Devices::LinuxSysfsLedDevice>(
                          configuration->getString("pdr.led.id", "status-led"),
                          configuration->getString("pdr.led.path")));
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
    std::vector<std::unique_ptr<PocoDDS::FastDDS::DeviceBridge>> _bridges;
};
} // namespace PocoDDS::Services

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
POCO_EXPORT_CLASS(PocoDDS::Services::DeviceGatewayActivator)
POCO_END_MANIFEST
