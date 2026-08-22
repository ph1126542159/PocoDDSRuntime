#include "Poco/Exception.h"
#include "Poco/File.h"
#include "Poco/JSON/Array.h"
#include "Poco/JSON/Object.h"
#include "Poco/NumberFormatter.h"
#include "Poco/Path.h"
#include "Poco/Process.h"
#include "Poco/Timestamp.h"

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <map>
#include <string>
#include <vector>

#if defined(_WIN32)
#include <WinSock2.h>
#include <Windows.h>
#include <DbgHelp.h>
#include <Iphlpapi.h>
#include <Psapi.h>
#include <TlHelp32.h>
#else
#include <cerrno>
#include <csignal>
#include <dirent.h>
#include <unistd.h>
#endif

namespace
{
using Arguments = std::map<std::string, std::string>;

Arguments parseArguments(int argc, char** argv, int start)
{
    Arguments result;
    for (int index = start; index < argc; ++index)
    {
        const std::string key = argv[index];
        if (key.rfind("--", 0) != 0)
            throw Poco::InvalidArgumentException("unexpected argument", key);
        if (index + 1 >= argc)
            throw Poco::InvalidArgumentException("missing value", key);
        result[key.substr(2)] = argv[++index];
    }
    return result;
}

unsigned long processId(const Arguments& arguments)
{
    const auto iterator = arguments.find("pid");
    if (iterator == arguments.end())
        throw Poco::InvalidArgumentException("--pid is required");
    if (iterator->second == "self") return static_cast<unsigned long>(Poco::Process::id());
    try
    {
        const auto parsed = std::stoull(iterator->second);
        if (parsed == 0 || parsed > 0xffffffffULL)
            throw Poco::InvalidArgumentException("invalid --pid");
        return static_cast<unsigned long>(parsed);
    }
    catch (const Poco::Exception&)
    {
        throw;
    }
    catch (...)
    {
        throw Poco::InvalidArgumentException("invalid --pid", iterator->second);
    }
}

void writeJson(const Poco::JSON::Object& value)
{
    value.stringify(std::cout, 2);
    std::cout << '\n';
}

Poco::JSON::Object baseResult(const std::string& command, unsigned long pid)
{
    Poco::JSON::Object result;
    result.set("schemaVersion", "pdr.diagnostic-agent/1");
    result.set("command", command);
    result.set("pid", static_cast<Poco::UInt64>(pid));
    result.set("timestampMicroseconds", Poco::Timestamp().epochMicroseconds());
    return result;
}

#if defined(_WIN32)
std::vector<unsigned long> threadIds(unsigned long pid)
{
    std::vector<unsigned long> result;
    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
    if (snapshot == INVALID_HANDLE_VALUE) return result;
    THREADENTRY32 entry{};
    entry.dwSize = sizeof(entry);
    if (Thread32First(snapshot, &entry))
    {
        do
        {
            if (entry.th32OwnerProcessID == pid) result.push_back(entry.th32ThreadID);
        }
        while (Thread32Next(snapshot, &entry));
    }
    CloseHandle(snapshot);
    std::sort(result.begin(), result.end());
    return result;
}

Poco::JSON::Object status(unsigned long pid)
{
    auto result = baseResult("status", pid);
    HANDLE process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ,
                                 FALSE, pid);
    if (!process)
    {
        result.set("running", false);
        result.set("healthy", false);
        result.set("error", "OpenProcess failed: " +
            Poco::NumberFormatter::format(GetLastError()));
        return result;
    }
    DWORD exitCode = 0;
    GetExitCodeProcess(process, &exitCode);
    result.set("running", exitCode == STILL_ACTIVE);
    result.set("exitCode", static_cast<Poco::UInt64>(exitCode));
    PROCESS_MEMORY_COUNTERS_EX memory{};
    memory.cb = sizeof(memory);
    if (GetProcessMemoryInfo(process, reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&memory),
                             sizeof(memory)))
    {
        result.set("workingSetBytes", static_cast<Poco::UInt64>(memory.WorkingSetSize));
        result.set("privateBytes", static_cast<Poco::UInt64>(memory.PrivateUsage));
    }
    DWORD handles = 0;
    if (GetProcessHandleCount(process, &handles))
        result.set("handleCount", static_cast<Poco::UInt64>(handles));
    FILETIME created{}, exited{}, kernel{}, user{};
    if (GetProcessTimes(process, &created, &exited, &kernel, &user))
    {
        ULARGE_INTEGER creation{};
        creation.LowPart = created.dwLowDateTime;
        creation.HighPart = created.dwHighDateTime;
        ULARGE_INTEGER kernelTime{};
        kernelTime.LowPart = kernel.dwLowDateTime;
        kernelTime.HighPart = kernel.dwHighDateTime;
        ULARGE_INTEGER userTime{};
        userTime.LowPart = user.dwLowDateTime;
        userTime.HighPart = user.dwHighDateTime;
        result.set("createdWindows100ns", static_cast<Poco::UInt64>(creation.QuadPart));
        result.set("cpuKernel100ns", static_cast<Poco::UInt64>(kernelTime.QuadPart));
        result.set("cpuUser100ns", static_cast<Poco::UInt64>(userTime.QuadPart));
    }
    result.set("threadCount", static_cast<Poco::UInt64>(threadIds(pid).size()));
    result.set("healthy", exitCode == STILL_ACTIVE);
    CloseHandle(process);
    return result;
}

Poco::JSON::Object threads(unsigned long pid)
{
    auto result = baseResult("threads", pid);
    Poco::JSON::Array::Ptr values = new Poco::JSON::Array;
    for (const auto id : threadIds(pid)) values->add(static_cast<Poco::UInt64>(id));
    result.set("threads", values);
    result.set("threadCount", static_cast<Poco::UInt64>(values->size()));
    result.set("healthy", values->size() > 0);
    return result;
}

const char* tcpState(DWORD state)
{
    switch (state)
    {
    case MIB_TCP_STATE_CLOSED: return "CLOSED";
    case MIB_TCP_STATE_LISTEN: return "LISTEN";
    case MIB_TCP_STATE_SYN_SENT: return "SYN_SENT";
    case MIB_TCP_STATE_SYN_RCVD: return "SYN_RCVD";
    case MIB_TCP_STATE_ESTAB: return "ESTABLISHED";
    case MIB_TCP_STATE_FIN_WAIT1: return "FIN_WAIT1";
    case MIB_TCP_STATE_FIN_WAIT2: return "FIN_WAIT2";
    case MIB_TCP_STATE_CLOSE_WAIT: return "CLOSE_WAIT";
    case MIB_TCP_STATE_CLOSING: return "CLOSING";
    case MIB_TCP_STATE_LAST_ACK: return "LAST_ACK";
    case MIB_TCP_STATE_TIME_WAIT: return "TIME_WAIT";
    case MIB_TCP_STATE_DELETE_TCB: return "DELETE_TCB";
    default: return "UNKNOWN";
    }
}

Poco::JSON::Object network(unsigned long pid)
{
    auto result = baseResult("net", pid);
    Poco::JSON::Array::Ptr endpoints = new Poco::JSON::Array;
    DWORD size = 0;
    GetExtendedTcpTable(nullptr, &size, FALSE, AF_INET, TCP_TABLE_OWNER_PID_ALL, 0);
    std::vector<unsigned char> tcpBuffer(size);
    if (size && GetExtendedTcpTable(tcpBuffer.data(), &size, FALSE, AF_INET,
                                    TCP_TABLE_OWNER_PID_ALL, 0) == NO_ERROR)
    {
        const auto* table = reinterpret_cast<const MIB_TCPTABLE_OWNER_PID*>(tcpBuffer.data());
        for (DWORD index = 0; index < table->dwNumEntries; ++index)
        {
            const auto& row = table->table[index];
            if (row.dwOwningPid != pid) continue;
            Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
            item->set("protocol", "tcp4");
            item->set("localPort", ntohs(static_cast<u_short>(row.dwLocalPort)));
            item->set("remotePort", ntohs(static_cast<u_short>(row.dwRemotePort)));
            item->set("state", tcpState(row.dwState));
            endpoints->add(item);
        }
    }
    size = 0;
    GetExtendedUdpTable(nullptr, &size, FALSE, AF_INET, UDP_TABLE_OWNER_PID, 0);
    std::vector<unsigned char> udpBuffer(size);
    if (size && GetExtendedUdpTable(udpBuffer.data(), &size, FALSE, AF_INET,
                                    UDP_TABLE_OWNER_PID, 0) == NO_ERROR)
    {
        const auto* table = reinterpret_cast<const MIB_UDPTABLE_OWNER_PID*>(udpBuffer.data());
        for (DWORD index = 0; index < table->dwNumEntries; ++index)
        {
            const auto& row = table->table[index];
            if (row.dwOwningPid != pid) continue;
            Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
            item->set("protocol", "udp4");
            item->set("localPort", ntohs(static_cast<u_short>(row.dwLocalPort)));
            item->set("state", "BOUND");
            endpoints->add(item);
        }
    }
    result.set("endpoints", endpoints);
    result.set("endpointCount", static_cast<Poco::UInt64>(endpoints->size()));
    result.set("healthy", true);
    return result;
}

Poco::JSON::Object dump(unsigned long pid, const std::string& outputPath)
{
    auto result = baseResult("dump", pid);
    HANDLE process = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ |
                                 PROCESS_DUP_HANDLE, FALSE, pid);
    if (!process)
    {
        result.set("healthy", false);
        result.set("error", "OpenProcess failed: " +
            Poco::NumberFormatter::format(GetLastError()));
        return result;
    }
    const std::wstring path(outputPath.begin(), outputPath.end());
    HANDLE file = CreateFileW(path.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS,
                              FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE)
    {
        CloseHandle(process);
        throw Poco::FileException("cannot create dump", outputPath);
    }
    const BOOL written = MiniDumpWriteDump(process, pid, file,
        static_cast<MINIDUMP_TYPE>(
            MiniDumpWithThreadInfo | MiniDumpWithIndirectlyReferencedMemory),
        nullptr, nullptr, nullptr);
    const DWORD error = written ? ERROR_SUCCESS : GetLastError();
    CloseHandle(file);
    CloseHandle(process);
    result.set("healthy", written != FALSE);
    result.set("path", outputPath);
    if (!written) result.set("error", "MiniDumpWriteDump failed: " +
        Poco::NumberFormatter::format(error));
    return result;
}
#else
bool running(unsigned long pid)
{
    return kill(static_cast<pid_t>(pid), 0) == 0 || errno == EPERM;
}

std::vector<unsigned long> threadIds(unsigned long pid)
{
    std::vector<unsigned long> result;
    const std::string path = "/proc/" + std::to_string(pid) + "/task";
    if (DIR* directory = opendir(path.c_str()))
    {
        while (const auto* entry = readdir(directory))
        {
            const std::string name = entry->d_name;
            if (!name.empty() && std::all_of(name.begin(), name.end(),
                [](unsigned char value) { return std::isdigit(value) != 0; }))
                result.push_back(static_cast<unsigned long>(std::stoul(name)));
        }
        closedir(directory);
    }
    std::sort(result.begin(), result.end());
    return result;
}

Poco::JSON::Object status(unsigned long pid)
{
    auto result = baseResult("status", pid);
    const bool active = running(pid);
    result.set("running", active);
    result.set("healthy", active);
    result.set("threadCount", static_cast<Poco::UInt64>(threadIds(pid).size()));
    std::ifstream input("/proc/" + std::to_string(pid) + "/status");
    std::string line;
    while (std::getline(input, line))
    {
        if (line.rfind("VmRSS:", 0) == 0) result.set("vmRss", line.substr(6));
        else if (line.rfind("VmSize:", 0) == 0) result.set("vmSize", line.substr(7));
    }
    return result;
}

Poco::JSON::Object threads(unsigned long pid)
{
    auto result = baseResult("threads", pid);
    Poco::JSON::Array::Ptr values = new Poco::JSON::Array;
    for (const auto id : threadIds(pid)) values->add(static_cast<Poco::UInt64>(id));
    result.set("threads", values);
    result.set("threadCount", static_cast<Poco::UInt64>(values->size()));
    result.set("healthy", values->size() > 0);
    return result;
}

Poco::JSON::Object network(unsigned long pid)
{
    auto result = baseResult("net", pid);
    result.set("healthy", running(pid));
    result.set("detail", "Linux endpoint ownership requires netlink/inet_diag; use ss -p in a privileged support environment.");
    return result;
}

Poco::JSON::Object dump(unsigned long pid, const std::string& outputPath)
{
    auto result = baseResult("dump", pid);
    result.set("healthy", false);
    result.set("path", outputPath);
    result.set("error", "Direct core dump capture is platform-policy dependent; configure coredumpctl/gcore externally.");
    return result;
}
#endif

Poco::JSON::Object heartbeat(unsigned long pid, const Arguments& arguments)
{
    auto result = baseResult("heartbeat", pid);
    const auto path = arguments.find("heartbeat");
    if (path == arguments.end())
        throw Poco::InvalidArgumentException("--heartbeat is required");
    long long timeoutSeconds = 30;
    if (const auto value = arguments.find("timeout"); value != arguments.end())
        timeoutSeconds = std::max(1LL, std::stoll(value->second));
    Poco::File file(path->second);
    const bool exists = file.exists();
    const auto age = exists ?
        (Poco::Timestamp().epochMicroseconds() - file.getLastModified().epochMicroseconds()) /
            1000000 : -1;
    result.set("path", path->second);
    result.set("exists", exists);
    result.set("ageSeconds", age);
    result.set("timeoutSeconds", timeoutSeconds);
    result.set("healthy", exists && age <= timeoutSeconds);
    return result;
}

void usage()
{
    std::cerr << "Usage:\n"
              << "  pdr-diagnostic-agent status --pid <pid|self>\n"
              << "  pdr-diagnostic-agent threads --pid <pid|self>\n"
              << "  pdr-diagnostic-agent net --pid <pid|self>\n"
              << "  pdr-diagnostic-agent heartbeat --pid <pid|self> --heartbeat <file> --timeout <seconds>\n"
              << "  pdr-diagnostic-agent dump --pid <pid|self> --output <file>\n";
}
}

int main(int argc, char** argv)
{
    try
    {
        if (argc < 2)
        {
            usage();
            return 2;
        }
        const std::string command = argv[1];
        const auto arguments = parseArguments(argc, argv, 2);
        const auto pid = processId(arguments);
        Poco::JSON::Object result;
        if (command == "status") result = status(pid);
        else if (command == "threads") result = threads(pid);
        else if (command == "net") result = network(pid);
        else if (command == "heartbeat") result = heartbeat(pid, arguments);
        else if (command == "dump")
        {
            const auto output = arguments.find("output");
            if (output == arguments.end())
                throw Poco::InvalidArgumentException("--output is required");
            result = dump(pid, Poco::Path(output->second).makeAbsolute().toString());
        }
        else
        {
            usage();
            return 2;
        }
        writeJson(result);
        return result.optValue<bool>("healthy", false) ? 0 : 1;
    }
    catch (const std::exception& exception)
    {
        Poco::JSON::Object error;
        error.set("schemaVersion", "pdr.diagnostic-agent/1");
        error.set("healthy", false);
        error.set("error", exception.what());
        writeJson(error);
        return 2;
    }
}
