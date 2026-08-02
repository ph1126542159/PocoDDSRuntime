#pragma once

#include <memory>
#include <string>
#include <utility>
#include <vector>

namespace PocoDDS::Health
{
enum class Status
{
    up,
    degraded,
    down
};

struct Report
{
    std::string component;
    Status status{Status::up};
    std::string detail;
    std::string code;
    std::string remediation;
    std::vector<std::string> affected;
};

class IHealthContributor
{
public:
    virtual ~IHealthContributor() = default;
    [[nodiscard]] virtual Report health() const = 0;
};

struct AggregateReport
{
    Status status{Status::up};
    std::vector<Report> components;

    [[nodiscard]] bool live() const noexcept { return status != Status::down; }
    [[nodiscard]] bool ready() const noexcept { return status == Status::up; }
};

class HealthRegistry
{
public:
    void add(std::shared_ptr<IHealthContributor> contributor)
    {
        _contributors.push_back(std::move(contributor));
    }

    [[nodiscard]] AggregateReport collect() const
    {
        AggregateReport aggregate;
        for (const auto& contributor : _contributors)
        {
            auto report = contributor->health();
            if (report.status == Status::down)
                aggregate.status = Status::down;
            else if (report.status == Status::degraded && aggregate.status == Status::up)
                aggregate.status = Status::degraded;
            aggregate.components.push_back(std::move(report));
        }
        return aggregate;
    }

private:
    std::vector<std::shared_ptr<IHealthContributor>> _contributors;
};
}
