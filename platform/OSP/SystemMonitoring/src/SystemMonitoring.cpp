#include "Poco/ClassLibrary.h"
#include "Poco/AutoPtr.h"
#include "Poco/Environment.h"
#include "Poco/File.h"
#include "Poco/DirectoryIterator.h"
#include "Poco/JSON/Array.h"
#include "Poco/JSON/Object.h"
#include "Poco/JSON/Parser.h"
#include "Poco/Net/HTTPServerRequest.h"
#include "Poco/Net/HTTPServerResponse.h"
#include "Poco/Net/HTTPRequestHandler.h"
#include "Poco/OSP/BundleActivator.h"
#include "Poco/OSP/BundleContext.h"
#include "Poco/OSP/Properties.h"
#include "Poco/OSP/PreferencesService.h"
#include "Poco/OSP/Service.h"
#include "Poco/OSP/ServiceRef.h"
#include "Poco/OSP/ServiceRegistry.h"
#include "Poco/OSP/Web/WebRequestHandlerFactory.h"
#include "Poco/NumberParser.h"
#include "Poco/Path.h"
#include "Poco/Process.h"
#include "Poco/Runnable.h"
#include "Poco/Thread.h"
#include "Poco/Timestamp.h"
#include "Poco/Timespan.h"
#include "Poco/Mutex.h"
#include "Poco/URI.h"
#include "Poco/UnicodeConverter.h"
#include "Poco/Util/AbstractConfiguration.h"
#include "Poco/Util/Application.h"
#include "Poco/Util/PropertyFileConfiguration.h"
#include "PocoDDS/Observability/TraceStore.h"
#include "PocoDDS/ProcessManagement/SubprocessManager.h"

#include <algorithm>
#include <atomic>
#include <cctype>
#include <cstdint>
#include <deque>
#include <fstream>
#include <functional>
#include <sstream>
#include <string>
#include <unordered_map>

#if defined(POCO_OS_FAMILY_WINDOWS)
#include <Windows.h>
#include <Iphlpapi.h>
#include <Psapi.h>
#include <TlHelp32.h>
#elif defined(POCO_OS_FAMILY_UNIX)
#include <sys/sysinfo.h>
#include <unistd.h>
#endif

namespace PocoDDS::SystemMonitoring
{
namespace
{
constexpr const char* SERVICE_NAME = "pdr.platform.systemMonitoring";

bool manageableBundle(const std::string& id)
{
    return id.rfind("pdr.service.", 0) == 0 || id.rfind("pdr.device.", 0) == 0;
}

bool editableConfiguration(const std::string& key)
{
    return key == "logging.loggers.root.level" ||
        key.rfind("deviceStatus.", 0) == 0 ||
        key.rfind("mobile.", 0) == 0 ||
        key.rfind("pdr.modbus.", 0) == 0 ||
        key.rfind("pdr.serial.", 0) == 0 ||
        key.rfind("pdr.gnss.", 0) == 0 ||
        key.rfind("pdr.gpio.", 0) == 0 ||
        key.rfind("pdr.xbee.", 0) == 0 ||
        key.rfind("pdr.can.", 0) == 0 ||
        key.rfind("pdr.led.", 0) == 0;
}

std::string configurationOwner(const std::string& key)
{
    if (key.rfind("deviceStatus.", 0) == 0) return "pdr.service.deviceStatus";
    if (key.rfind("mobile.", 0) == 0) return "pdr.service.mobile";
    if (key.rfind("pdr.", 0) == 0) return "pdr.device.gateway";
    return {};
}

void sendJsonError(Poco::Net::HTTPServerResponse& response,
                   Poco::Net::HTTPResponse::HTTPStatus status,
                   const std::string& message)
{
    Poco::JSON::Object result;
    result.set("error", message);
    response.setStatus(status);
    response.setContentType("application/json");
    result.stringify(response.send());
}

struct Sample
{
    Poco::Int64 timestamp{0};
    double cpuPercent{0};
    double memoryPercent{0};
    Poco::UInt64 memoryUsedMb{0};
    Poco::UInt64 memoryTotalMb{0};
    double diskPercent{0};
    Poco::UInt64 diskUsedGb{0};
    Poco::UInt64 diskTotalGb{0};
    double networkReceiveKbps{0};
    double networkSendKbps{0};
    Poco::UInt64 threadCount{0};
};

class SystemMonitoringService final : public Poco::OSP::Service, public Poco::Runnable
{
public:
    void start()
    {
        _stopping = false;
        _thread.start(*this);
    }

    void stop()
    {
        _stopping = true;
        if (_thread.isRunning())
            _thread.join();
    }

    void run() override
    {
        while (!_stopping)
        {
            const Sample sample = collect();
            {
                Poco::FastMutex::ScopedLock lock(_mutex);
                _history.push_back(sample);
                while (_history.size() > 60)
                    _history.pop_front();
            }
            for (int wait = 0; wait < 10 && !_stopping; ++wait)
                Poco::Thread::sleep(100);
        }
    }

    std::deque<Sample> history() const
    {
        Poco::FastMutex::ScopedLock lock(_mutex);
        return _history;
    }

    const std::type_info& type() const override { return typeid(SystemMonitoringService); }
    bool isA(const std::type_info& other) const override
    {
        return other == typeid(SystemMonitoringService) || Poco::OSP::Service::isA(other);
    }

private:
    Sample collect()
    {
        Sample result;
        result.timestamp = Poco::Timestamp().epochMicroseconds() / 1000;
        collectCpu(result);
        collectMemory(result);
        collectDisk(result);
        collectNetwork(result);
        collectThreads(result);
        return result;
    }

    void collectDisk(Sample& sample)
    {
        try
        {
            Poco::File current(".");
            const Poco::UInt64 total = current.totalSpace();
            const Poco::UInt64 free = current.usableSpace();
            if (total)
            {
                const Poco::UInt64 used = total - free;
                sample.diskPercent =
                    100.0 * static_cast<double>(used) / static_cast<double>(total);
                sample.diskUsedGb = used / (1024ULL * 1024ULL * 1024ULL);
                sample.diskTotalGb = total / (1024ULL * 1024ULL * 1024ULL);
            }
        }
        catch (...) {}
    }

#if defined(POCO_OS_FAMILY_WINDOWS)
    static Poco::UInt64 fileTimeValue(const FILETIME& value)
    {
        return (static_cast<Poco::UInt64>(value.dwHighDateTime) << 32) |
            value.dwLowDateTime;
    }

    void collectCpu(Sample& sample)
    {
        FILETIME idleTime;
        FILETIME kernelTime;
        FILETIME userTime;
        if (!GetSystemTimes(&idleTime, &kernelTime, &userTime))
            return;
        const Poco::UInt64 idle = fileTimeValue(idleTime);
        const Poco::UInt64 kernel = fileTimeValue(kernelTime);
        const Poco::UInt64 user = fileTimeValue(userTime);
        const Poco::UInt64 totalDelta = (kernel - _previousKernel) + (user - _previousUser);
        const Poco::UInt64 idleDelta = idle - _previousIdle;
        if (_previousKernel && totalDelta)
            sample.cpuPercent = 100.0 * static_cast<double>(totalDelta - idleDelta) /
                static_cast<double>(totalDelta);
        _previousIdle = idle;
        _previousKernel = kernel;
        _previousUser = user;
    }

    void collectMemory(Sample& sample)
    {
        MEMORYSTATUSEX status{};
        status.dwLength = sizeof(status);
        if (!GlobalMemoryStatusEx(&status))
            return;
        sample.memoryPercent = static_cast<double>(status.dwMemoryLoad);
        sample.memoryTotalMb = status.ullTotalPhys / (1024ULL * 1024ULL);
        sample.memoryUsedMb =
            (status.ullTotalPhys - status.ullAvailPhys) / (1024ULL * 1024ULL);
    }

    void collectNetwork(Sample& sample)
    {
        MIB_IF_TABLE2* table = nullptr;
        if (GetIfTable2(&table) != NO_ERROR)
            return;
        Poco::UInt64 received = 0;
        Poco::UInt64 sent = 0;
        for (ULONG index = 0; index < table->NumEntries; ++index)
        {
            const auto& row = table->Table[index];
            if (row.OperStatus == IfOperStatusUp &&
                row.Type != IF_TYPE_SOFTWARE_LOOPBACK)
            {
                received += row.InOctets;
                sent += row.OutOctets;
            }
        }
        FreeMibTable(table);
        calculateNetworkRates(sample, received, sent);
    }

    void collectThreads(Sample& sample)
    {
        HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
        if (snapshot == INVALID_HANDLE_VALUE)
            return;
        THREADENTRY32 entry{};
        entry.dwSize = sizeof(entry);
        if (Thread32First(snapshot, &entry))
        {
            do
            {
                if (entry.th32OwnerProcessID == GetCurrentProcessId())
                    ++sample.threadCount;
            }
            while (Thread32Next(snapshot, &entry));
        }
        CloseHandle(snapshot);
    }
#else
    void collectCpu(Sample& sample)
    {
        std::ifstream input("/proc/stat");
        std::string name;
        Poco::UInt64 user = 0, nice = 0, system = 0, idle = 0, ioWait = 0;
        if (!(input >> name >> user >> nice >> system >> idle >> ioWait))
            return;
        const Poco::UInt64 total = user + nice + system + idle + ioWait;
        const Poco::UInt64 totalDelta = total - _previousCpuTotal;
        const Poco::UInt64 idleDelta = (idle + ioWait) - _previousCpuIdle;
        if (_previousCpuTotal && totalDelta)
            sample.cpuPercent = 100.0 * static_cast<double>(totalDelta - idleDelta) /
                static_cast<double>(totalDelta);
        _previousCpuTotal = total;
        _previousCpuIdle = idle + ioWait;
    }

    void collectMemory(Sample& sample)
    {
        struct sysinfo info {};
        if (sysinfo(&info) != 0)
            return;
        const Poco::UInt64 total = info.totalram * info.mem_unit;
        const Poco::UInt64 free = (info.freeram + info.bufferram) * info.mem_unit;
        sample.memoryTotalMb = total / (1024ULL * 1024ULL);
        sample.memoryUsedMb = (total - free) / (1024ULL * 1024ULL);
        if (total)
            sample.memoryPercent =
                100.0 * static_cast<double>(total - free) / static_cast<double>(total);
    }

    void collectNetwork(Sample& sample)
    {
        std::ifstream input("/proc/net/dev");
        std::string line;
        Poco::UInt64 received = 0;
        Poco::UInt64 sent = 0;
        while (std::getline(input, line))
        {
            const auto colon = line.find(':');
            if (colon == std::string::npos)
                continue;
            std::string interfaceName = line.substr(0, colon);
            interfaceName.erase(
                std::remove_if(interfaceName.begin(), interfaceName.end(), ::isspace),
                interfaceName.end());
            if (interfaceName == "lo")
                continue;
            std::istringstream fields(line.substr(colon + 1));
            Poco::UInt64 receiveBytes = 0;
            Poco::UInt64 sendBytes = 0;
            Poco::UInt64 ignored = 0;
            fields >> receiveBytes;
            for (int index = 0; index < 7; ++index) fields >> ignored;
            fields >> sendBytes;
            received += receiveBytes;
            sent += sendBytes;
        }
        calculateNetworkRates(sample, received, sent);
    }

    void collectThreads(Sample& sample)
    {
        std::ifstream input("/proc/self/status");
        std::string key;
        while (input >> key)
        {
            if (key == "Threads:")
            {
                input >> sample.threadCount;
                return;
            }
            std::string ignored;
            std::getline(input, ignored);
        }
    }
#endif

    void calculateNetworkRates(Sample& sample, Poco::UInt64 received, Poco::UInt64 sent)
    {
        const Poco::Timestamp now;
        if (_previousNetworkTime.epochMicroseconds() != 0)
        {
            const double seconds =
                static_cast<double>(now - _previousNetworkTime) / 1000000.0;
            if (seconds > 0 && received >= _previousReceived && sent >= _previousSent)
            {
                sample.networkReceiveKbps =
                    static_cast<double>(received - _previousReceived) / 1024.0 / seconds;
                sample.networkSendKbps =
                    static_cast<double>(sent - _previousSent) / 1024.0 / seconds;
            }
        }
        _previousReceived = received;
        _previousSent = sent;
        _previousNetworkTime = now;
    }

    mutable Poco::FastMutex _mutex;
    std::deque<Sample> _history;
    std::atomic<bool> _stopping{false};
    Poco::Thread _thread{"SystemMonitoring"};
    Poco::UInt64 _previousIdle{0};
    Poco::UInt64 _previousKernel{0};
    Poco::UInt64 _previousUser{0};
    Poco::UInt64 _previousCpuTotal{0};
    Poco::UInt64 _previousCpuIdle{0};
    Poco::UInt64 _previousReceived{0};
    Poco::UInt64 _previousSent{0};
    Poco::Timestamp _previousNetworkTime{0};
};

Poco::JSON::Object::Ptr sampleJson(const Sample& sample)
{
    auto result = new Poco::JSON::Object;
    result->set("timestamp", sample.timestamp);
    result->set("cpuPercent", sample.cpuPercent);
    result->set("memoryPercent", sample.memoryPercent);
    result->set("memoryUsedMb", sample.memoryUsedMb);
    result->set("memoryTotalMb", sample.memoryTotalMb);
    result->set("diskPercent", sample.diskPercent);
    result->set("diskUsedGb", sample.diskUsedGb);
    result->set("diskTotalGb", sample.diskTotalGb);
    result->set("networkReceiveKbps", sample.networkReceiveKbps);
    result->set("networkSendKbps", sample.networkSendKbps);
    result->set("threadCount", sample.threadCount);
    return result;
}

class MetricsHandler final : public Poco::Net::HTTPRequestHandler
{
public:
    explicit MetricsHandler(Poco::OSP::BundleContext::Ptr context) : _context(context) {}

    void handleRequest(Poco::Net::HTTPServerRequest&,
                       Poco::Net::HTTPServerResponse& response) override
    {
        auto serviceRef = _context->registry().findByName(SERVICE_NAME);
        if (!serviceRef)
        {
            response.setStatus(Poco::Net::HTTPResponse::HTTP_SERVICE_UNAVAILABLE);
            response.send() << "{\"error\":\"system monitoring service unavailable\"}";
            return;
        }
        auto service = serviceRef->castedInstance<SystemMonitoringService>();
        const auto history = service->history();
        Poco::JSON::Array::Ptr samples = new Poco::JSON::Array;
        for (const auto& sample : history)
            samples->add(sampleJson(sample));
        Poco::JSON::Object root;
        root.set("host", Poco::Environment::nodeName());
        root.set("intervalMilliseconds", 1000);
        root.set("samples", samples);
        if (!history.empty())
            root.set("current", sampleJson(history.back()));
        response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
        response.setContentType("application/json");
        root.stringify(response.send());
    }

private:
    Poco::OSP::BundleContext::Ptr _context;
};

class ProcessLogsHandler final : public Poco::Net::HTTPRequestHandler
{
public:
    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        Poco::URI uri(request.getURI());
        std::string processId;
        std::string processName;
        int limit = 500;
        for (const auto& parameter : uri.getQueryParameters())
        {
            if (parameter.first == "id") processId = parameter.second;
            else if (parameter.first == "name") processName = parameter.second;
            else if (parameter.first == "limit")
            {
                try { limit = Poco::NumberParser::parse(parameter.second); }
                catch (...) {}
            }
        }
        limit = std::max(20, std::min(limit, 1000));

        std::string logName = "pdr-runtime";
        if (!processId.empty() &&
            processId != std::to_string(Poco::Process::id()))
        {
            logName.clear();
            for (const char character : processName)
            {
                const unsigned char value = static_cast<unsigned char>(character);
                if (std::isalnum(value) || character == '.' || character == '_' ||
                    character == '-')
                    logName += character;
            }
            const auto executableSuffix = logName.rfind(".exe");
            if (executableSuffix != std::string::npos &&
                executableSuffix + 4 == logName.size())
                logName.resize(executableSuffix);
        }

        std::deque<std::string> lines;
        if (!logName.empty())
        {
            Poco::Path path("logs");
            path.append(logName + ".log");
            path.makeAbsolute();
            std::ifstream input(path.toString());
            std::string line;
            while (std::getline(input, line))
            {
                lines.push_back(line);
                if (lines.size() > static_cast<std::size_t>(limit))
                    lines.pop_front();
            }
        }

        Poco::JSON::Array::Ptr jsonLines = new Poco::JSON::Array;
        for (const auto& line : lines)
            jsonLines->add(line);
        Poco::JSON::Object root;
        root.set("processId", processId);
        root.set("lines", jsonLines);
        response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
        response.setContentType("application/json");
        root.stringify(response.send());
    }
};

class ProcessDetailHandler final : public Poco::Net::HTTPRequestHandler
{
public:
    explicit ProcessDetailHandler(Poco::OSP::BundleContext::Ptr context)
        : _context(context)
    {
    }

    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        Poco::URI uri(request.getURI());
        std::string processId;
        std::string processName;
        for (const auto& parameter : uri.getQueryParameters())
        {
            if (parameter.first == "id") processId = parameter.second;
            else if (parameter.first == "name") processName = parameter.second;
        }
        const std::string mainId = std::to_string(Poco::Process::id());
        const bool mainProcess = processId.empty() || processId == mainId;
        if (mainProcess)
        {
            processId = mainId;
            processName = "pdr-runtime";
        }
        std::string processState = "running";
        std::string processLocation = "local";
        if (!mainProcess)
        {
            if (auto* manager = PocoDDS::ProcessManagement::SubprocessManager::active())
            {
                for (const auto& info : manager->processes())
                {
                    if (info.name == processName)
                    {
                        processId = std::to_string(info.processId);
                        processState = info.state;
                        processLocation = info.location;
                        break;
                    }
                }
            }
        }

        Poco::JSON::Object root;
        Poco::JSON::Object::Ptr process = new Poco::JSON::Object;
        process->set("id", processId);
        process->set("pid", processId);
        process->set("name", processName);
        process->set("main", mainProcess);
        process->set("state", processState);
        process->set("location", processLocation);
        root.set("process", process);

        Poco::JSON::Array::Ptr children = new Poco::JSON::Array;
        if (mainProcess)
            appendChildren(children);
        else if (auto status = readChildStatus(processName))
        {
            if (status->has("children"))
                children = status->getArray("children");
        }
        root.set("children", children);

        Poco::JSON::Array::Ptr bundles = new Poco::JSON::Array;
        if (mainProcess)
        {
            std::vector<Poco::OSP::Bundle::Ptr> loadedBundles;
            _context->listBundles(loadedBundles);
            for (const auto& loadedBundle : loadedBundles)
            {
                Poco::JSON::Object::Ptr bundle = new Poco::JSON::Object;
                bundle->set("id", loadedBundle->symbolicName());
                bundle->set("name", loadedBundle->name());
                bundle->set("version", loadedBundle->version().toString());
                bundle->set("state", loadedBundle->stateString());
                bundle->set("manageable", manageableBundle(loadedBundle->symbolicName()));
                bundles->add(bundle);
            }
        }
        else
        {
            if (auto status = readChildStatus(processName))
            {
                if (status->has("bundles"))
                    bundles = status->getArray("bundles");
            }
            if (bundles->size() == 0)
                appendRepositoryBundles(processName, bundles);
        }
        root.set("bundles", bundles);

        Poco::JSON::Object::Ptr resources = new Poco::JSON::Object;
        appendResources(processId, mainProcess, resources);
        root.set("resources", resources);

        Poco::JSON::Object::Ptr configuration = new Poco::JSON::Object;
        appendConfiguration(processName, mainProcess, configuration);
        root.set("configuration", configuration);
        Poco::JSON::Array::Ptr editable = new Poco::JSON::Array;
        if (mainProcess)
        {
            for (const auto& item : *configuration)
                if (editableConfiguration(item.first)) editable->add(item.first);
        }
        root.set("editableConfiguration", editable);

        response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
        response.setContentType("application/json");
        root.stringify(response.send());
    }

private:
    static Poco::JSON::Object::Ptr readChildStatus(const std::string& processName)
    {
        Poco::Path path("processes");
        path.append(safeName(processName));
        path.append("pdr-process-status.json");
        path.makeAbsolute();
        if (!Poco::File(path).exists())
            return {};
        try
        {
            std::ifstream input(path.toString());
            Poco::JSON::Parser parser;
            return parser.parse(input).extract<Poco::JSON::Object::Ptr>();
        }
        catch (...)
        {
            return {};
        }
    }

    static std::string safeName(const std::string& name)
    {
        std::string result;
        for (const char character : name)
        {
            const unsigned char value = static_cast<unsigned char>(character);
            if (std::isalnum(value) || character == '.' || character == '_' ||
                character == '-')
                result += character;
        }
        if (result.size() > 4 && result.substr(result.size() - 4) == ".exe")
            result.resize(result.size() - 4);
        return result;
    }

    static void appendChildren(Poco::JSON::Array::Ptr children)
    {
        if (auto* manager = PocoDDS::ProcessManagement::SubprocessManager::active())
        {
            for (const auto& info : manager->processes())
            {
                Poco::JSON::Object::Ptr child = new Poco::JSON::Object;
                child->set("id", info.name);
                child->set("pid", info.processId);
                child->set("name", info.name);
                child->set("state", info.state);
                child->set("location", info.location);
                child->set("online", info.state == "running");
                child->set("host", info.location == "local" ?
                                       Poco::Environment::nodeName() : "远程主机");
                child->set("manageable", info.manageable);
                children->add(child);
            }
            return;
        }
#if defined(POCO_OS_FAMILY_WINDOWS)
        HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
        if (snapshot == INVALID_HANDLE_VALUE)
            return;
        PROCESSENTRY32W entry{};
        entry.dwSize = sizeof(entry);
        if (Process32FirstW(snapshot, &entry))
        {
            do
            {
                if (entry.th32ParentProcessID != GetCurrentProcessId() ||
                    _wcsicmp(entry.szExeFile, L"conhost.exe") == 0)
                    continue;
                std::string name;
                Poco::UnicodeConverter::toUTF8(entry.szExeFile, name);
                Poco::JSON::Object::Ptr child = new Poco::JSON::Object;
                child->set("id", std::to_string(entry.th32ProcessID));
                child->set("pid", entry.th32ProcessID);
                child->set("name", name);
                child->set("state", "running");
                child->set("location", "local");
                child->set("online", true);
                child->set("host", Poco::Environment::nodeName());
                child->set("manageable", false);
                children->add(child);
            }
            while (Process32NextW(snapshot, &entry));
        }
        CloseHandle(snapshot);
#endif
    }

    static void appendRepositoryBundles(const std::string& processName,
                                        Poco::JSON::Array::Ptr bundles)
    {
        Poco::Path path("processes");
        path.append(safeName(processName));
        path.append("bundles");
        path.makeAbsolute();
        Poco::File directory(path);
        if (!directory.exists() || !directory.isDirectory())
            return;
        for (Poco::DirectoryIterator iterator(path); iterator != Poco::DirectoryIterator();
             ++iterator)
        {
            if (!iterator->isFile() || Poco::Path(iterator.path()).getExtension() != "bndl")
                continue;
            const std::string baseName = Poco::Path(iterator.path()).getBaseName();
            const auto separator = baseName.rfind('_');
            Poco::JSON::Object::Ptr bundle = new Poco::JSON::Object;
            bundle->set("id", separator == std::string::npos ?
                                    baseName : baseName.substr(0, separator));
            bundle->set("name", separator == std::string::npos ?
                                      baseName : baseName.substr(0, separator));
            bundle->set("version", separator == std::string::npos ?
                                         "" : baseName.substr(separator + 1));
            bundle->set("state", "installed");
            bundles->add(bundle);
        }
    }

    void appendResources(const std::string& processId, bool mainProcess,
                         Poco::JSON::Object::Ptr resources)
    {
        if (mainProcess)
        {
            const auto serviceRef = _context->registry().findByName(SERVICE_NAME);
            if (serviceRef)
            {
                const auto history =
                    serviceRef->castedInstance<SystemMonitoringService>()->history();
                if (!history.empty())
                {
                    const auto& sample = history.back();
                    resources->set("cpuPercent", sample.cpuPercent);
                    resources->set("memoryPercent", sample.memoryPercent);
                    resources->set("memoryUsedMb", sample.memoryUsedMb);
                    resources->set("memoryTotalMb", sample.memoryTotalMb);
                    resources->set("networkReceiveKbps", sample.networkReceiveKbps);
                    resources->set("networkSendKbps", sample.networkSendKbps);
                    resources->set("threadCount", sample.threadCount);
                    resources->set("diskPercent", sample.diskPercent);
                }
            }
            return;
        }

#if defined(POCO_OS_FAMILY_WINDOWS)
        DWORD pid = 0;
        try { pid = static_cast<DWORD>(std::stoul(processId)); }
        catch (...) { return; }
        HANDLE processHandle =
            OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, FALSE, pid);
        if (processHandle)
        {
            PROCESS_MEMORY_COUNTERS_EX counters{};
            if (GetProcessMemoryInfo(
                    processHandle, reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&counters),
                    sizeof(counters)))
            {
                resources->set("memoryUsedMb",
                               counters.WorkingSetSize / (1024ULL * 1024ULL));
                MEMORYSTATUSEX memory{};
                memory.dwLength = sizeof(memory);
                if (GlobalMemoryStatusEx(&memory) && memory.ullTotalPhys != 0)
                    resources->set(
                        "memoryPercent",
                        100.0 * static_cast<double>(counters.WorkingSetSize) /
                            static_cast<double>(memory.ullTotalPhys));
            }

            FILETIME creation;
            FILETIME exit;
            FILETIME kernel;
            FILETIME user;
            FILETIME now;
            GetSystemTimeAsFileTime(&now);
            if (GetProcessTimes(processHandle, &creation, &exit, &kernel, &user))
            {
                const auto ticks = [](const FILETIME& value) {
                    return (static_cast<unsigned long long>(value.dwHighDateTime) << 32) |
                        value.dwLowDateTime;
                };
                static Poco::FastMutex cpuMutex;
                static std::unordered_map<DWORD, std::pair<unsigned long long,
                                                           unsigned long long>> previous;
                Poco::FastMutex::ScopedLock lock(cpuMutex);
                const auto processTicks = ticks(kernel) + ticks(user);
                const auto wallTicks = ticks(now);
                const auto found = previous.find(pid);
                if (found != previous.end() && wallTicks > found->second.second)
                {
                    const double cores =
                        static_cast<double>(
                            std::max(1U, Poco::Environment::processorCount()));
                    resources->set(
                        "cpuPercent",
                        100.0 * static_cast<double>(processTicks - found->second.first) /
                            static_cast<double>(wallTicks - found->second.second) / cores);
                }
                previous[pid] = {processTicks, wallTicks};
            }
            CloseHandle(processHandle);
        }
        Poco::UInt64 threads = 0;
        HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
        if (snapshot != INVALID_HANDLE_VALUE)
        {
            THREADENTRY32 entry{};
            entry.dwSize = sizeof(entry);
            if (Thread32First(snapshot, &entry))
            {
                do
                {
                    if (entry.th32OwnerProcessID == pid) ++threads;
                }
                while (Thread32Next(snapshot, &entry));
            }
            CloseHandle(snapshot);
        }
        resources->set("threadCount", threads);
#endif
        if (!resources->has("cpuPercent")) resources->set("cpuPercent", 0);
        resources->set("diskPercent", 0);
        resources->set("networkReceiveKbps", 0);
        resources->set("networkSendKbps", 0);
    }

    static bool sensitiveKey(const std::string& key)
    {
        std::string lower = key;
        std::transform(lower.begin(), lower.end(), lower.begin(),
                       [](unsigned char value) { return static_cast<char>(std::tolower(value)); });
        return lower.find("password") != std::string::npos ||
            lower.find("secret") != std::string::npos ||
            lower.find("token") != std::string::npos ||
            lower.find("privatekey") != std::string::npos;
    }

    static void appendConfiguration(const std::string& processName, bool mainProcess,
                                    Poco::JSON::Object::Ptr configuration)
    {
        Poco::Path path;
        if (mainProcess)
        {
            path = Poco::Path("pdr-runtime.properties").makeAbsolute();
        }
        else
        {
            path = Poco::Path("processes");
            path.append(safeName(processName));
            path.append(safeName(processName) + ".properties");
            path.makeAbsolute();
        }
        if (!Poco::File(path).exists())
            return;
        try
        {
            Poco::AutoPtr<Poco::Util::PropertyFileConfiguration> values =
                new Poco::Util::PropertyFileConfiguration(path.toString());
            std::function<void(const std::string&)> appendKeys;
            appendKeys = [&](const std::string& prefix) {
                Poco::Util::AbstractConfiguration::Keys keys;
                values->keys(prefix, keys);
                for (const auto& key : keys)
                {
                    const std::string fullKey = prefix.empty() ? key : prefix + "." + key;
                    Poco::Util::AbstractConfiguration::Keys children;
                    values->keys(fullKey, children);
                    if (!children.empty())
                        appendKeys(fullKey);
                    else
                        configuration->set(
                            fullKey, sensitiveKey(fullKey) ?
                                         "••••••••" : values->getRawString(fullKey, ""));
                }
            };
            appendKeys("");
        }
        catch (...) {}
    }

    Poco::OSP::BundleContext::Ptr _context;
};

class ProcessLifecycleHandler final : public Poco::Net::HTTPRequestHandler
{
public:
    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        try
        {
            Poco::JSON::Parser parser;
            auto body = parser.parse(request.stream()).extract<Poco::JSON::Object::Ptr>();
            const std::string id = body->getValue<std::string>("id");
            const std::string action = body->getValue<std::string>("action");
            auto* manager = PocoDDS::ProcessManagement::SubprocessManager::active();
            if (!manager)
                return sendJsonError(response,
                                     Poco::Net::HTTPResponse::HTTP_SERVICE_UNAVAILABLE,
                                     "子进程管理器尚未就绪。");

            bool completed = false;
            if (action == "start") completed = manager->start(id);
            else if (action == "stop") completed = manager->stop(id);
            else if (action == "restart") completed = manager->restart(id);
            else
                return sendJsonError(response, Poco::Net::HTTPResponse::HTTP_BAD_REQUEST,
                                     "不支持的进程生命周期操作。");
            if (!completed)
                return sendJsonError(response, Poco::Net::HTTPResponse::HTTP_FORBIDDEN,
                                     "远程进程或未知进程不能由本机直接操作。");

            Poco::JSON::Object result;
            result.set("message", "子进程操作已完成");
            result.set("id", id);
            result.set("action", action);
            response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
            response.setContentType("application/json");
            result.stringify(response.send());
        }
        catch (const std::exception& exception)
        {
            sendJsonError(response, Poco::Net::HTTPResponse::HTTP_BAD_REQUEST, exception.what());
        }
    }
};

class BundleLifecycleHandler final : public Poco::Net::HTTPRequestHandler
{
public:
    explicit BundleLifecycleHandler(Poco::OSP::BundleContext::Ptr context): _context(context) {}

    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        try
        {
            Poco::JSON::Parser parser;
            auto body = parser.parse(request.stream()).extract<Poco::JSON::Object::Ptr>();
            const std::string id = body->getValue<std::string>("id");
            const std::string action = body->getValue<std::string>("action");
            if (!manageableBundle(id))
                return sendJsonError(response, Poco::Net::HTTPResponse::HTTP_FORBIDDEN,
                                     "该 Bundle 属于核心基础设施，禁止在线操作。");
            Poco::OSP::Bundle::Ptr bundle = _context->findBundle(id);
            if (!bundle)
                return sendJsonError(response, Poco::Net::HTTPResponse::HTTP_NOT_FOUND,
                                     "未找到 Bundle。");
            if (action == "start")
            {
                if (bundle->state() == Poco::OSP::Bundle::BUNDLE_RESOLVED) bundle->start();
            }
            else if (action == "stop")
            {
                if (bundle->state() == Poco::OSP::Bundle::BUNDLE_ACTIVE) bundle->stop();
            }
            else if (action == "restart")
            {
                if (bundle->state() == Poco::OSP::Bundle::BUNDLE_ACTIVE) bundle->stop();
                bundle->start();
            }
            else
                return sendJsonError(response, Poco::Net::HTTPResponse::HTTP_BAD_REQUEST,
                                     "不支持的生命周期操作。");

            Poco::JSON::Object result;
            result.set("message", "Bundle 操作已完成");
            result.set("id", id);
            result.set("state", bundle->stateString());
            response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
            response.setContentType("application/json");
            result.stringify(response.send());
        }
        catch (const std::exception& exception)
        {
            sendJsonError(response, Poco::Net::HTTPResponse::HTTP_BAD_REQUEST, exception.what());
        }
    }
private:
    Poco::OSP::BundleContext::Ptr _context;
};

class ProcessConfigHandler final : public Poco::Net::HTTPRequestHandler
{
public:
    explicit ProcessConfigHandler(Poco::OSP::BundleContext::Ptr context): _context(context) {}

    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        try
        {
            Poco::JSON::Parser parser;
            auto body = parser.parse(request.stream()).extract<Poco::JSON::Object::Ptr>();
            const std::string key = body->getValue<std::string>("key");
            const std::string value = body->getValue<std::string>("value");
            if (!editableConfiguration(key))
                return sendJsonError(response, Poco::Net::HTTPResponse::HTTP_FORBIDDEN,
                                     "该配置项为只读。");

            Poco::Path path("pdr-runtime.properties");
            path.makeAbsolute();
            Poco::AutoPtr<Poco::Util::PropertyFileConfiguration> file =
                new Poco::Util::PropertyFileConfiguration(path.toString());
            if (!file->hasProperty(key))
                return sendJsonError(response, Poco::Net::HTTPResponse::HTTP_NOT_FOUND,
                                     "配置项不存在。");
            file->setString(key, value);
            file->save(path.toString());
            const auto preferencesRef =
                _context->registry().findByName(Poco::OSP::PreferencesService::SERVICE_NAME);
            if (!preferencesRef)
                throw Poco::NullPointerException("全局配置服务不可用");
            preferencesRef->castedInstance<Poco::OSP::PreferencesService>()
                ->setConfiguration(key, value);
            if (key == "logging.loggers.root.level")
                Poco::Logger::root().setLevel(value);

            const std::string owner = configurationOwner(key);
            if (!owner.empty())
            {
                Poco::OSP::Bundle::Ptr bundle = _context->findBundle(owner);
                if (bundle && manageableBundle(owner) &&
                    bundle->state() == Poco::OSP::Bundle::BUNDLE_ACTIVE)
                {
                    bundle->stop();
                    bundle->start();
                }
            }
            Poco::JSON::Object result;
            result.set("message", owner.empty() ? "配置已立即生效" : "配置已保存，相关 Bundle 已重启");
            result.set("key", key);
            result.set("value", value);
            response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
            response.setContentType("application/json");
            result.stringify(response.send());
        }
        catch (const std::exception& exception)
        {
            sendJsonError(response, Poco::Net::HTTPResponse::HTTP_BAD_REQUEST, exception.what());
        }
    }
private:
    Poco::OSP::BundleContext::Ptr _context;
};

Poco::JSON::Object::Ptr traceFields(const PocoDDS::Observability::Fields& fields)
{
    Poco::JSON::Object::Ptr result = new Poco::JSON::Object;
    for (const auto& field : fields) result->set(field.first, field.second);
    return result;
}

class HeartbeatBusinessHandler final : public Poco::Net::HTTPRequestHandler
{
public:
    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        Poco::URI uri(request.getURI());
        std::string traceId;
        for (const auto& parameter : uri.getQueryParameters())
            if (parameter.first == "traceId") traceId = parameter.second;
        Poco::JSON::Object root;
        if (traceId.empty())
        {
            Poco::JSON::Array::Ptr records = new Poco::JSON::Array;
            for (const auto& summary :
                 PocoDDS::Observability::globalTraceStore().recent(100))
            {
                if (summary.businessName != "主子进程Fast-DDS心跳") continue;
                Poco::JSON::Object::Ptr record = new Poco::JSON::Object;
                record->set("traceId", summary.traceId);
                record->set("businessName", summary.businessName);
                record->set("businessInstanceId", summary.businessInstanceId);
                record->set("status", summary.status);
                record->set("startedUnixMicroseconds", summary.startedUnixMicroseconds);
                record->set("durationNanoseconds", summary.durationNanoseconds);
                record->set("stepCount", summary.stepCount);
                record->set("failedOperation", summary.failedOperation);
                records->add(record);
            }
            root.set("records", records);
        }
        else
        {
            Poco::JSON::Array::Ptr nodes = new Poco::JSON::Array;
            for (const auto& span :
                 PocoDDS::Observability::globalTraceStore().trace(traceId))
            {
                Poco::JSON::Object::Ptr node = new Poco::JSON::Object;
                node->set("operation", span.operation);
                node->set("serviceName", span.serviceName);
                node->set("bundleName", span.bundleName);
                node->set("hostName", span.hostName);
                node->set("processId", span.processId);
                node->set("traceId", span.traceId);
                node->set("spanId", span.spanId);
                node->set("parentSpanId", span.parentSpanId);
                node->set("status", span.status);
                node->set("errorCode", span.errorCode);
                node->set("errorMessage", span.errorMessage);
                node->set("startedUnixMicroseconds", span.startedUnixMicroseconds);
                node->set("endedUnixMicroseconds", span.endedUnixMicroseconds);
                node->set("durationNanoseconds", span.durationNanoseconds);
                node->set("inputs", traceFields(span.inputs));
                node->set("outputs", traceFields(span.outputs));
                nodes->add(node);
            }
            root.set("nodes", nodes);
        }
        response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
        response.setContentType("application/json; charset=utf-8");
        response.set("Cache-Control", "no-store");
        root.stringify(response.send());
    }
};
} // namespace

class MetricsHandlerFactory final : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new MetricsHandler(context());
    }
};

class ProcessLogsHandlerFactory final : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new ProcessLogsHandler;
    }
};

class ProcessDetailHandlerFactory final : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new ProcessDetailHandler(context());
    }
};

class BundleLifecycleHandlerFactory final : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new BundleLifecycleHandler(context());
    }
};

class ProcessLifecycleHandlerFactory final : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new ProcessLifecycleHandler;
    }
};

class ProcessConfigHandlerFactory final : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new ProcessConfigHandler(context());
    }
};

class HeartbeatBusinessHandlerFactory final : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new HeartbeatBusinessHandler;
    }
};

class BundleActivator final : public Poco::OSP::BundleActivator
{
public:
    void start(Poco::OSP::BundleContext::Ptr context) override
    {
        _service = new SystemMonitoringService;
        Poco::OSP::Properties properties;
        properties.set("pdr.service", "systemMonitoring");
        properties.set("pdr.bundle", context->thisBundle()->symbolicName());
        _serviceRef = context->registry().registerService(SERVICE_NAME, _service, properties);
        _service->start();
        context->logger().information(
            "System monitoring started: CPU, memory, disk, network and threads.");
    }

    void stop(Poco::OSP::BundleContext::Ptr context) override
    {
        if (_service)
            _service->stop();
        if (_serviceRef)
            context->registry().unregisterService(_serviceRef);
        _serviceRef = nullptr;
        _service = nullptr;
    }

private:
    Poco::AutoPtr<SystemMonitoringService> _service;
    Poco::OSP::ServiceRef::Ptr _serviceRef;
};
} // namespace PocoDDS::SystemMonitoring

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
    POCO_EXPORT_CLASS(PocoDDS::SystemMonitoring::BundleActivator)
POCO_END_MANIFEST

POCO_BEGIN_NAMED_MANIFEST(WebServer, Poco::OSP::Web::WebRequestHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::SystemMonitoring::MetricsHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::SystemMonitoring::ProcessLogsHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::SystemMonitoring::ProcessDetailHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::SystemMonitoring::ProcessLifecycleHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::SystemMonitoring::BundleLifecycleHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::SystemMonitoring::ProcessConfigHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::SystemMonitoring::HeartbeatBusinessHandlerFactory)
POCO_END_MANIFEST
