#pragma once

#include "PocoDDS/StoreForward/StoreForward.h"

#include <optional>
#include <string>
#include <vector>

namespace PocoDDS::StoreForward
{
class OutboxStore
{
public:
    virtual ~OutboxStore() = default;
    virtual void initialize() = 0;
    virtual void save(const Message& message) = 0;
    virtual std::optional<Message> find(const std::string& id) const = 0;
    virtual std::optional<Message> findByIdempotencyKey(
        const std::string& provider, const std::string& idempotencyKey) const = 0;
    virtual std::size_t activeCount() const = 0;
    virtual std::vector<Message> due(Poco::Int64 nowMicroseconds,
                                     std::size_t limit) const = 0;
    virtual std::vector<Message> list() const = 0;
    virtual std::size_t recoverDelivering(Poco::Int64 nowMicroseconds) = 0;
    virtual std::size_t purgeTerminalBefore(Poco::Int64 cutoffMicroseconds) = 0;
};
} // namespace PocoDDS::StoreForward
