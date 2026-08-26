#include <PocoDDS/Membership/IncarnationStore.h>
#include <PocoDDS/Membership/Membership.h>
#include <PocoDDS/Membership/MembershipRuntimeService.h>

#include <Poco/Data/SQLite/Connector.h>
#include <Poco/TemporaryFile.h>

#include <cstdint>
#include <type_traits>

int main()
{
    static_assert(std::is_base_of_v<
                  Poco::OSP::Service,
                  PocoDDS::Membership::MembershipRuntimeService>);
    PocoDDS::Membership::Registry registry;
    PocoDDS::Membership::Heartbeat heartbeat;
    heartbeat.instanceId = "sdk-consumer";
    heartbeat.incarnation = 1;
    heartbeat.sequence = 1;
    heartbeat.role = "test";
    if (!registry.observe(heartbeat) || registry.snapshot().alive != 1) return 1;

    Poco::Data::SQLite::Connector::registerConnector();
    try
    {
        PocoDDS::Membership::SqliteIncarnationStore store(
            Poco::TemporaryFile::tempName() + ".sqlite");
        if (store.next("sdk-consumer") != 1) return 2;
    }
    catch (...)
    {
        Poco::Data::SQLite::Connector::unregisterConnector();
        return 3;
    }
    Poco::Data::SQLite::Connector::unregisterConnector();
    return 0;
}
