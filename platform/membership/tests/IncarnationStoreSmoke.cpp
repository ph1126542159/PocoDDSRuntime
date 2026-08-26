#include "PocoDDS/Membership/IncarnationStore.h"

#include <Poco/Data/SQLite/Connector.h>
#include <Poco/TemporaryFile.h>

#include <iostream>
#include <algorithm>
#include <mutex>
#include <stdexcept>
#include <thread>
#include <vector>

int main()
{
    Poco::Data::SQLite::Connector::registerConnector();
    try
    {
        const auto path = Poco::TemporaryFile::tempName() + ".sqlite";

        PocoDDS::Membership::SqliteIncarnationStore first(path);
        if (first.next("runtime-a") != 1 || first.next("runtime-a") != 2 ||
            first.next("runtime-b") != 1)
            throw std::runtime_error("initial incarnation sequence is incorrect");
        PocoDDS::Membership::SqliteIncarnationStore reopened(path);
        if (reopened.next("runtime-a") != 3 || reopened.next("runtime-b") != 2)
            throw std::runtime_error("incarnation sequence was not durable");

        PocoDDS::Membership::SqliteIncarnationStore concurrentA(path);
        PocoDDS::Membership::SqliteIncarnationStore concurrentB(path);
        std::mutex valuesMutex;
        std::vector<std::uint64_t> values;
        auto allocate = [&](PocoDDS::Membership::SqliteIncarnationStore* store) {
            for (int index = 0; index < 20; ++index)
            {
                const auto value = store->next("runtime-a");
                std::lock_guard<std::mutex> lock(valuesMutex);
                values.push_back(value);
            }
        };
        std::thread firstWriter(allocate, &concurrentA);
        std::thread secondWriter(allocate, &concurrentB);
        firstWriter.join();
        secondWriter.join();
        std::sort(values.begin(), values.end());
        if (values.size() != 40 || values.front() != 4 || values.back() != 43 ||
            std::adjacent_find(values.begin(), values.end()) != values.end())
            throw std::runtime_error(
                "concurrent incarnation allocation reused a generation");
        if (reopened.next("runtime-a") != 44)
            throw std::runtime_error("concurrent incarnation high-water mark was not durable");

        std::cout << "MEMBERSHIP_INCARNATION_STORE_PASS runtimeA=44 runtimeB=2\n";
        Poco::Data::SQLite::Connector::unregisterConnector();
        return 0;
    }
    catch (const std::exception& error)
    {
        std::cerr << "MEMBERSHIP_INCARNATION_STORE_ERROR: " << error.what() << '\n';
        Poco::Data::SQLite::Connector::unregisterConnector();
        return 1;
    }
}
