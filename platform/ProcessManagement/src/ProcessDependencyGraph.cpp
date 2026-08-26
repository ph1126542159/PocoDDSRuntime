#include "PocoDDS/ProcessManagement/ProcessDependencyGraph.h"
#include "PocoDDS/ProcessManagement/ProcessDesiredStateMaintenance.h"

#include "ProcessDependencyGraphRegistry.h"

#include "Poco/Mutex.h"

#include <utility>

namespace PocoDDS::ProcessManagement
{
namespace
{
Poco::FastMutex providerMutex;
const void* providerOwner = nullptr;
Detail::ProcessDependencyGraphCallback providerCallback;
const void* maintenanceProviderOwner = nullptr;
Detail::ProcessDesiredStateMaintenanceCallback maintenanceProviderCallback;
} // namespace

namespace Detail
{
void registerProcessDependencyGraphProvider(
    const void* owner, ProcessDependencyGraphCallback callback)
{
    Poco::FastMutex::ScopedLock lock(providerMutex);
    providerOwner = owner;
    providerCallback = std::move(callback);
}

void unregisterProcessDependencyGraphProvider(const void* owner)
{
    Poco::FastMutex::ScopedLock lock(providerMutex);
    if (providerOwner == owner)
    {
        providerOwner = nullptr;
        providerCallback = {};
    }
}

void registerProcessDesiredStateMaintenanceProvider(
    const void* owner, ProcessDesiredStateMaintenanceCallback callback)
{
    Poco::FastMutex::ScopedLock lock(providerMutex);
    maintenanceProviderOwner = owner;
    maintenanceProviderCallback = std::move(callback);
}

void unregisterProcessDesiredStateMaintenanceProvider(const void* owner)
{
    Poco::FastMutex::ScopedLock lock(providerMutex);
    if (maintenanceProviderOwner == owner)
    {
        maintenanceProviderOwner = nullptr;
        maintenanceProviderCallback = {};
    }
}
} // namespace Detail

ProcessDependencyGraphSnapshot activeProcessDependencyGraph()
{
    Poco::FastMutex::ScopedLock lock(providerMutex);
    if (!providerCallback)
        return {};
    return providerCallback();
}

ProcessDesiredStateRecommitResult recommitActiveProcessDesiredState(
    std::uint64_t expectedGeneration)
{
    Poco::FastMutex::ScopedLock lock(providerMutex);
    if (!maintenanceProviderCallback)
    {
        ProcessDesiredStateRecommitResult result;
        result.expectedGeneration = expectedGeneration;
        return result;
    }
    return maintenanceProviderCallback(expectedGeneration);
}
} // namespace PocoDDS::ProcessManagement
