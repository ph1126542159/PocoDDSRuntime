#include "IoT/DeviceStatus/DeviceStatusServiceImpl.h"

#include <Poco/Data/SQLite/Connector.h>
#include <Poco/TemporaryFile.h>

#include <iostream>

int main()
{
    Poco::Data::SQLite::Connector::registerConnector();
    Poco::TemporaryFile database;
    database.keepUntilExit();
    try
    {
        IoT::DeviceStatus::DeviceStatusServiceImpl service(database.path(), 24);
        IoT::DeviceStatus::StatusUpdate update;
        update.messageClass = "test";
        update.source = "smoke";
        update.status = IoT::DeviceStatus::DEVICE_STATUS_WARNING;
        update.text = "warning";
        const auto change = service.postStatus(update);
        if (change.currentStatus != IoT::DeviceStatus::DEVICE_STATUS_WARNING ||
            service.messages(0).size() != 1)
        {
            std::cerr << "DeviceStatus smoke test failed\n";
            return 1;
        }
        service.reset();
    }
    catch (...)
    {
        Poco::Data::SQLite::Connector::unregisterConnector();
        throw;
    }
    Poco::Data::SQLite::Connector::unregisterConnector();
    return 0;
}
