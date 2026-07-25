#pragma once

#include <functional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace PocoDDS::Persistence
{
class IUnitOfWork
{
public:
    virtual ~IUnitOfWork() = default;
    virtual void commit() = 0;
    virtual void rollback() noexcept = 0;
};

template <typename Entity, typename Id>
class IRepository
{
public:
    virtual ~IRepository() = default;
    virtual bool contains(const Id& id) const = 0;
    virtual Entity get(const Id& id) const = 0;
    virtual void save(Entity entity) = 0;
    virtual void remove(const Id& id) = 0;
};

struct Migration
{
    unsigned version;
    std::string description;
    std::function<void()> up;
};

class MigrationPlan
{
public:
    void add(Migration migration)
    {
        if (!_migrations.empty() && migration.version <= _migrations.back().version)
            throw std::invalid_argument("migration versions must be strictly increasing");
        _migrations.push_back(std::move(migration));
    }

    unsigned apply(unsigned currentVersion) const
    {
        unsigned version = currentVersion;
        for (const auto& migration : _migrations)
        {
            if (migration.version <= version)
                continue;
            migration.up();
            version = migration.version;
        }
        return version;
    }

private:
    std::vector<Migration> _migrations;
};
}
