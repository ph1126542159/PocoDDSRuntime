#include "PocoDDS/Health/Health.h"

#include <iostream>
#include <memory>

namespace
{
class Probe final : public PocoDDS::Health::IHealthContributor
{
public:
    Probe(std::string name, PocoDDS::Health::Status status):
        _name(std::move(name)), _status(status)
    {
    }
    PocoDDS::Health::Report health() const override { return {_name, _status, "probe"}; }

private:
    std::string _name;
    PocoDDS::Health::Status _status;
};
}

int main()
{
    PocoDDS::Health::HealthRegistry registry;
    registry.add(std::make_shared<Probe>("dds", PocoDDS::Health::Status::up));
    registry.add(std::make_shared<Probe>("device", PocoDDS::Health::Status::degraded));
    const auto report = registry.collect();
    if (report.status != PocoDDS::Health::Status::degraded || report.ready() || !report.live())
        return 1;
    PocoDDS::Health::Report diagnostic{
        "device", PocoDDS::Health::Status::down, "required device fault",
        "PDR-HEALTH-DEVICE-REQUIRED_NOT_READY", "inspect device diagnostics", {"sensor-1"}};
    if (diagnostic.code.empty() || diagnostic.remediation.empty() ||
        diagnostic.affected.size() != 1 || diagnostic.affected.front() != "sensor-1")
        return 2;
    std::cout << "HEALTH_SMOKE_PASS\n";
}
