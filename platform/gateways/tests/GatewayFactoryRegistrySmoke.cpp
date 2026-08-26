#include "PocoDDS/Gateways/FactoryService.h"

#include "Poco/Delegate.h"
#include "Poco/OSP/Properties.h"
#include "Poco/OSP/ServiceRef.h"
#include "Poco/OSP/ServiceRegistry.h"
#include "Poco/OSP/ServiceListener.h"

#include <memory>
#include <string>
#include <utility>

namespace
{
class TestDevice final : public PocoDDS::Devices::Device
{
public:
    explicit TestDevice(std::string id) : _id(std::move(id)) {}
    const std::string& id() const noexcept override { return _id; }
    const std::string& type() const noexcept override { return _type; }
    void start() override { _state = PocoDDS::Devices::DeviceState::ready; }
    void stop() noexcept override { _state = PocoDDS::Devices::DeviceState::offline; }
    PocoDDS::Devices::DeviceSnapshot snapshot() const override
    {
        return {_id, _type, _state, 0, 0, "{}"};
    }
    std::string execute(const std::string&, const std::string& payload) override
    {
        return payload;
    }
    void setSnapshotHandler(SnapshotHandler) override {}

private:
    std::string _id;
    std::string _type{"test-device"};
    PocoDDS::Devices::DeviceState _state{PocoDDS::Devices::DeviceState::offline};
};

class TestDeviceFactory final : public PocoDDS::Gateways::DeviceFactoryService
{
public:
    PocoDDS::Gateways::FactoryDescriptor descriptor() const override
    {
        return {"test-device", "pdr.testDevice", "test-device", false, 0};
    }

    std::unique_ptr<PocoDDS::Devices::Device> create(
        const Poco::Util::AbstractConfiguration&,
        const PocoDDS::Gateways::FactoryInstance& instance) const override
    {
        return std::make_unique<TestDevice>(instance.id);
    }
};

class TestProtocol final : public PocoDDS::Protocols::DiagnosticProtocol
{
public:
    std::string name() const override { return "test-protocol"; }
    void open() override { _open = true; }
    void close() noexcept override { _open = false; }
    bool isOpen() const noexcept override { return _open; }
    PocoDDS::Protocols::ProtocolDiagnostics diagnostics() const override { return {}; }

private:
    bool _open{false};
};

class TestProtocolFactory final : public PocoDDS::Gateways::ProtocolFactoryService
{
public:
    PocoDDS::Gateways::FactoryDescriptor descriptor() const override
    {
        return {"test-protocol", "pdr.testProtocol", "test-protocol", false, 0};
    }

    std::unique_ptr<PocoDDS::Protocols::DiagnosticProtocol> create(
        const Poco::Util::AbstractConfiguration&,
        const PocoDDS::Gateways::FactoryInstance&) const override
    {
        return std::make_unique<TestProtocol>();
    }
};

class RegistrationObserver
{
public:
    void registered(const Poco::OSP::ServiceRef::Ptr&) { ++registeredCount; }
    void unregistered(const Poco::OSP::ServiceRef::Ptr&) { ++unregisteredCount; }

    int registeredCount{0};
    int unregisteredCount{0};
};
}

int main()
{
    Poco::OSP::ServiceRegistry registry;
    RegistrationObserver observer;
    auto listener = registry.createListener(
        "pdr.gateway.factory.kind",
        Poco::delegate(&observer, &RegistrationObserver::registered),
        Poco::delegate(&observer, &RegistrationObserver::unregistered));
    if (!listener) return 1;

    Poco::OSP::Properties properties;
    properties.set(PocoDDS::Gateways::DeviceFactoryService::PROPERTY_KIND,
                   PocoDDS::Gateways::DeviceFactoryService::FACTORY_KIND);
    properties.set(PocoDDS::Gateways::DeviceFactoryService::PROPERTY_TYPE,
                   "test-device");
    auto registered = registry.registerService(
        "pdr.deviceFactory.test-device", new TestDeviceFactory, properties);
    Poco::OSP::Properties protocolProperties;
    protocolProperties.set(PocoDDS::Gateways::ProtocolFactoryService::PROPERTY_KIND,
                           PocoDDS::Gateways::ProtocolFactoryService::FACTORY_KIND);
    protocolProperties.set(PocoDDS::Gateways::ProtocolFactoryService::PROPERTY_TYPE,
                           "test-protocol");
    auto registeredProtocol = registry.registerService(
        "pdr.protocolFactory.test-protocol", new TestProtocolFactory,
        protocolProperties);
    if (observer.registeredCount != 2) return 1;

    auto matches = registry.find(
        "pdr.gateway.factory.kind == \"device\"");
    if (matches.size() != 1) return 2;
    auto factory = matches.front()->castedInstance<
        PocoDDS::Gateways::DeviceFactoryService>();
    const auto descriptor = factory->descriptor();
    if (descriptor.type != "test-device" ||
        descriptor.configurationBase != "pdr.testDevice") return 3;

    auto protocolMatches = registry.find(
        "pdr.gateway.factory.kind == \"protocol\"");
    if (protocolMatches.size() != 1) return 4;
    auto protocolFactory = protocolMatches.front()->castedInstance<
        PocoDDS::Gateways::ProtocolFactoryService>();
    if (protocolFactory->descriptor().type != "test-protocol") return 5;

    PocoDDS::Gateways::FactoryInstance instance{0, "pdr.testDevice.0", "test-1", false};
    // Registry discovery and ABI-safe cast are the contract under test. The
    // real Gateway supplies the runtime AbstractConfiguration to create().
    if (instance.key("enabled") != "pdr.testDevice.0.enabled") return 6;

    registry.unregisterService(registered);
    registry.unregisterService(registeredProtocol);
    if (observer.unregisteredCount != 2) return 7;
    return registry.find("pdr.gateway.factory.kind").empty() ? 0 : 8;
}
