#pragma once

#include "PocoDDS/Membership/Export.h"

#include <cstdint>
#include <memory>
#include <string>

namespace PocoDDS::Membership
{
/// Durable, transactionally incremented fencing incarnation for a stable
/// Runtime instance identity. Multiple processes sharing a database cannot
/// receive the same incarnation.
class PDR_MEMBERSHIP_PERSISTENCE_API SqliteIncarnationStore
{
public:
    explicit SqliteIncarnationStore(std::string databasePath);
    ~SqliteIncarnationStore();

    SqliteIncarnationStore(const SqliteIncarnationStore&) = delete;
    SqliteIncarnationStore& operator=(const SqliteIncarnationStore&) = delete;

    std::uint64_t next(const std::string& instanceId);

private:
    class Impl;
    std::unique_ptr<Impl> _impl;
};
} // namespace PocoDDS::Membership
