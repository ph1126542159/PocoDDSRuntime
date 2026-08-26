#pragma once

#include "PocoDDS/StoreForward/OutboxStore.h"

#include <memory>
#include <string>

namespace PocoDDS::StoreForward
{
class SqliteOutboxStore final : public OutboxStore
{
public:
    explicit SqliteOutboxStore(std::string path);
    ~SqliteOutboxStore() override;

    void initialize() override;
    void save(const Message& message) override;
    std::optional<Message> find(const std::string& id) const override;
    std::optional<Message> findByIdempotencyKey(
        const std::string& provider, const std::string& idempotencyKey) const override;
    std::size_t activeCount() const override;
    std::vector<Message> due(Poco::Int64 nowMicroseconds,
                             std::size_t limit) const override;
    std::vector<Message> list() const override;
    std::size_t recoverDelivering(Poco::Int64 nowMicroseconds) override;
    std::size_t purgeTerminalBefore(Poco::Int64 cutoffMicroseconds) override;

private:
    class Impl;
    std::unique_ptr<Impl> _impl;
};
} // namespace PocoDDS::StoreForward
