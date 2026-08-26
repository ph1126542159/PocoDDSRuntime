#pragma once

#include "PocoDDS/ConfigTransaction/ConfigTransaction.h"

#include <optional>

namespace PocoDDS::ConfigTransaction
{
class TransactionStore
{
public:
    virtual ~TransactionStore() = default;
    virtual void initialize() = 0;
    virtual std::optional<Snapshot> current() const = 0;
    virtual void seed(const Snapshot& snapshot) = 0;
    virtual void replaceBootstrap(const Snapshot& snapshot) = 0;
    virtual std::optional<TransactionRecord> findByRequestId(
        const std::string& requestId) const = 0;
    virtual void save(const TransactionRecord& record) = 0;
    virtual void commit(const TransactionRecord& record, const Snapshot& snapshot) = 0;
    virtual std::vector<TransactionRecord> incomplete() const = 0;
    virtual std::vector<TransactionRecord> history(std::size_t limit) const = 0;
};
} // namespace PocoDDS::ConfigTransaction
