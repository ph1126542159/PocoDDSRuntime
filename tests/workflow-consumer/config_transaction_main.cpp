#include <PocoDDS/ConfigTransaction/SqliteTransactionStore.h>
#include <PocoDDS/ConfigTransaction/TransactionEngine.h>

#include <Poco/File.h>
#include <Poco/TemporaryFile.h>

#include <iostream>
#include <memory>

int main()
{
    using namespace PocoDDS::ConfigTransaction;
    const std::string database = Poco::TemporaryFile::tempName();
    {
        TransactionEngine engine(std::make_unique<SqliteTransactionStore>(database));
        engine.initialize({{"external.value", "1"}});
        if (engine.current().generation != 1 || engine.current().digest.empty()) return 1;
    }
    try { Poco::File(database).remove(); } catch (...) {}
    try { Poco::File(database + "-wal").remove(); } catch (...) {}
    try { Poco::File(database + "-shm").remove(); } catch (...) {}
    std::cout << "PDR_CONFIG_TRANSACTION_EXTERNAL_PASS\n";
    return 0;
}
