#pragma once

#include "PocoDDS/ConfigTransaction/TransactionStore.h"

#include <memory>
#include <string>

namespace PocoDDS::ConfigTransaction
{
class PDR_CONFIG_TRANSACTION_API SqliteTransactionStore final : public TransactionStore
{
public:
    explicit SqliteTransactionStore(std::string path);
    ~SqliteTransactionStore() override;

    void initialize() override;
    std::optional<Snapshot> current() const override;
    void seed(const Snapshot& snapshot) override;
    void replaceBootstrap(const Snapshot& snapshot) override;
    std::optional<TransactionRecord> findByRequestId(
        const std::string& requestId) const override;
    void save(const TransactionRecord& record) override;
    void commit(const TransactionRecord& record, const Snapshot& snapshot) override;
    std::vector<TransactionRecord> incomplete() const override;
    std::vector<TransactionRecord> history(std::size_t limit) const override;

private:
    class Impl;
    std::unique_ptr<Impl> _impl;
};
} // namespace PocoDDS::ConfigTransaction
