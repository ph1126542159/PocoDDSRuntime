#pragma once

#include "PocoDDS/ConfigTransaction/ConfigurationParticipantService.h"
#include "PocoDDS/ConfigTransaction/TransactionStore.h"

#include <Poco/AutoPtr.h>

#include <functional>
#include <memory>
#include <string>
#include <vector>

namespace PocoDDS::ConfigTransaction
{
class PDR_CONFIG_TRANSACTION_API ParticipantRegistration
{
public:
    ParticipantRegistration() = default;
    explicit ParticipantRegistration(std::function<void()> cancel);
    ~ParticipantRegistration();
    ParticipantRegistration(const ParticipantRegistration&) = delete;
    ParticipantRegistration& operator=(const ParticipantRegistration&) = delete;
    ParticipantRegistration(ParticipantRegistration&& other) noexcept;
    ParticipantRegistration& operator=(ParticipantRegistration&& other) noexcept;
    void reset() noexcept;
    explicit operator bool() const noexcept;

private:
    std::function<void()> _cancel;
};

class PDR_CONFIG_TRANSACTION_API TransactionEngine
{
public:
    struct Hooks
    {
        std::function<void(const Snapshot&)> validate;
        std::function<void(const Snapshot&)> activate;
        std::function<void(const std::string&, const std::vector<std::string>&)> authorize;
    };

    TransactionEngine(std::unique_ptr<TransactionStore> store, Hooks hooks = {});
    ~TransactionEngine();
    TransactionEngine(const TransactionEngine&) = delete;
    TransactionEngine& operator=(const TransactionEngine&) = delete;

    void initialize(const Values& initialValues);
    ParticipantRegistration attach(Poco::AutoPtr<ConfigurationParticipantService> participant);
    Snapshot current() const;
    ApplyResult apply(const ApplyRequest& request);
    std::size_t recover();
    std::vector<TransactionSummary> history(std::size_t limit = 50) const;
    std::vector<std::string> participantIds() const;

private:
    class Impl;
    std::unique_ptr<Impl> _impl;
};
} // namespace PocoDDS::ConfigTransaction
