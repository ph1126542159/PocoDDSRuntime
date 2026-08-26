#pragma once

#include "PocoDDS/ServiceClient/InvocationJournal.h"

#include <chrono>
#include <memory>
#include <string>

namespace PocoDDS::ServiceClient
{
class SqliteInvocationJournal final : public InvocationJournal
{
public:
    SqliteInvocationJournal(std::string databasePath,
                            std::size_t maximumEntries,
                            std::chrono::milliseconds retention);
    ~SqliteInvocationJournal() override;

    SqliteInvocationJournal(const SqliteInvocationJournal&) = delete;
    SqliteInvocationJournal& operator=(const SqliteInvocationJournal&) = delete;

    InvocationJournalClaim claim(
        const InvocationJournalClaimRequest& request) override;
    void complete(const std::string& scopeDigest,
                  const std::string& requestDigest,
                  const std::string& invocationId,
                  const InvocationCompletion& completion,
                  std::int64_t nowUnixMicroseconds) override;
    bool release(const std::string& scopeDigest,
                 const std::string& requestDigest,
                 const std::string& invocationId) override;
    InvocationJournalSnapshot snapshot() const override;

private:
    class Impl;
    std::unique_ptr<Impl> _impl;
};
} // namespace PocoDDS::ServiceClient
