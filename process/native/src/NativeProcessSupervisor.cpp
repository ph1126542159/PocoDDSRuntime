#include "PocoDDS/NativeProcess/NativeProcessSupervisor.h"

#include <algorithm>
#include <atomic>
#include <cctype>
#include <condition_variable>
#include <cwchar>
#include <deque>
#include <filesystem>
#include <mutex>
#include <stdexcept>
#include <thread>
#include <unordered_map>
#include <utility>

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <Windows.h>
#else
#include <cerrno>
#include <csignal>
#include <fcntl.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
#endif

namespace PocoDDS::NativeProcess
{
using namespace PocoDDS::RuntimeCore;
namespace
{
RuntimeError processError(RuntimeErrorCode code, std::string message, bool retryable = false)
{
    return {code, std::move(message), retryable};
}

bool validId(const std::string& id)
{
    return !id.empty() &&
           std::all_of(
               id.begin(), id.end(), [](unsigned char value)
               { return std::isalnum(value) || value == '-' || value == '_' || value == '.'; });
}

bool containedBy(const std::filesystem::path& root, const std::filesystem::path& candidate)
{
    const auto relative = candidate.lexically_relative(root);
    if (relative.empty() && candidate != root)
        return false;
    return !relative.is_absolute() && std::none_of(relative.begin(), relative.end(),
                                                   [](const auto& part) { return part == ".."; });
}

#ifdef _WIN32
std::wstring widen(const std::string& value)
{
    if (value.empty())
        return {};
    const auto size = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, value.data(),
                                          static_cast<int>(value.size()), nullptr, 0);
    if (size <= 0)
        throw std::invalid_argument("process string is not valid UTF-8");
    std::wstring result(static_cast<std::size_t>(size), L'\0');
    MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, value.data(), static_cast<int>(value.size()),
                        result.data(), size);
    return result;
}

std::wstring quoteArgument(const std::wstring& argument)
{
    if (argument.find_first_of(L" \t\n\v\"") == std::wstring::npos)
        return argument;
    std::wstring result = L"\"";
    std::size_t slashes = 0;
    for (const auto character : argument)
    {
        if (character == L'\\')
        {
            ++slashes;
            continue;
        }
        if (character == L'\"')
        {
            result.append(slashes * 2 + 1, L'\\');
            result.push_back(L'\"');
            slashes = 0;
            continue;
        }
        result.append(slashes, L'\\');
        slashes = 0;
        result.push_back(character);
    }
    result.append(slashes * 2, L'\\');
    result.push_back(L'\"');
    return result;
}

std::wstring commandLine(const ProcessSpec& spec)
{
    std::wstring result = quoteArgument(widen(spec.executable));
    for (const auto& argument : spec.arguments)
    {
        result.push_back(L' ');
        result += quoteArgument(widen(argument));
    }
    return result;
}

std::vector<wchar_t> environmentBlock(const ProcessSpec& spec)
{
    if (spec.environment.empty())
        return {};
    std::vector<std::wstring> values;
    const auto inherited = GetEnvironmentStringsW();
    if (!inherited)
        throw std::runtime_error("GetEnvironmentStrings failed");
    for (auto cursor = inherited; *cursor != L'\0'; cursor += std::wcslen(cursor) + 1)
        values.emplace_back(cursor);
    FreeEnvironmentStringsW(inherited);
    for (const auto& [nameUtf8, valueUtf8] : spec.environment)
    {
        const auto name = widen(nameUtf8);
        values.erase(std::remove_if(values.begin(), values.end(),
                                    [&](const auto& current)
                                    {
                                        const auto separator = current.find(L'=');
                                        return separator == name.size() &&
                                               _wcsnicmp(current.c_str(), name.c_str(),
                                                         name.size()) == 0;
                                    }),
                     values.end());
        values.push_back(name + L"=" + widen(valueUtf8));
    }
    std::sort(values.begin(), values.end(), [](const auto& left, const auto& right)
              { return _wcsicmp(left.c_str(), right.c_str()) < 0; });
    std::vector<wchar_t> block;
    for (const auto& value : values)
    {
        block.insert(block.end(), value.begin(), value.end());
        block.push_back(L'\0');
    }
    block.push_back(L'\0');
    return block;
}

HANDLE openOutput(const std::string& path)
{
    if (path.empty())
        return nullptr;
    SECURITY_ATTRIBUTES attributes{sizeof(SECURITY_ATTRIBUTES), nullptr, TRUE};
    return CreateFileW(widen(path).c_str(), FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
                       &attributes, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
}
#endif
} // namespace

struct NativeProcessSupervisor::State
{
    struct Entry
    {
        ProcessSnapshot snapshot;
        bool desiredStop{false};
        std::deque<std::chrono::steady_clock::time_point> restartTimes;
#ifdef _WIN32
        HANDLE process{nullptr};
        HANDLE job{nullptr};
#else
        pid_t pid{-1};
#endif
    };

    explicit State(NativeProcessSupervisorOptions value) : options(std::move(value))
    {
        if (options.monitorInterval.count() <= 0)
            throw std::invalid_argument("process monitorInterval must be positive");
        root = options.processRoot.empty() ? std::filesystem::current_path()
                                           : std::filesystem::path(options.processRoot);
        root = std::filesystem::weakly_canonical(root);
        if (!std::filesystem::is_directory(root))
            throw std::invalid_argument("process root is not a directory");
        monitor = std::thread([this] { monitorLoop(); });
    }

    ~State() = default;

    NativeProcessSupervisorOptions options;
    std::filesystem::path root;
    mutable std::mutex mutex;
    std::mutex operationMutex;
    std::condition_variable wake;
    std::vector<std::string> order;
    std::unordered_map<std::string, Entry> entries;
    std::atomic<bool> monitoring{true};
    std::thread monitor;

    Outcome<void> normalize(ProcessSpec& spec) const
    {
        if (!validId(spec.id))
            return Outcome<void>::failure(
                processError(RuntimeErrorCode::invalidArgument,
                             "process id must contain only letters, digits, '-', '_' or '.'"));
        if (spec.executable.empty())
            return Outcome<void>::failure(processError(RuntimeErrorCode::invalidArgument,
                                                       "process executable cannot be empty"));
        if (spec.restartWindow.count() <= 0 || spec.gracefulStopTimeout.count() < 0)
            return Outcome<void>::failure(processError(
                RuntimeErrorCode::invalidArgument,
                "restartWindow must be positive and gracefulStopTimeout cannot be negative"));
        for (const auto& [name, value] : spec.environment)
        {
            if (name.empty() || name.find('=') != std::string::npos ||
                name.find('\0') != std::string::npos || value.find('\0') != std::string::npos)
                return Outcome<void>::failure(processError(
                    RuntimeErrorCode::invalidArgument,
                    "process environment names cannot be empty or contain '=' or NUL"));
        }

        auto executable = std::filesystem::path(spec.executable);
        if (executable.is_relative())
            executable = root / executable;
        executable = std::filesystem::weakly_canonical(executable);
        if (!options.allowOutsideProcessRoot && !containedBy(root, executable))
            return Outcome<void>::failure(processError(RuntimeErrorCode::invalidArgument,
                                                       "process executable escapes process root"));
        if (!std::filesystem::is_regular_file(executable))
            return Outcome<void>::failure(
                processError(RuntimeErrorCode::unavailable, "process executable does not exist"));
        spec.executable = executable.string();

        auto workingDirectory =
            spec.workingDirectory.empty() ? root : std::filesystem::path(spec.workingDirectory);
        if (workingDirectory.is_relative())
            workingDirectory = root / workingDirectory;
        workingDirectory = std::filesystem::weakly_canonical(workingDirectory);
        if (!options.allowOutsideProcessRoot && !containedBy(root, workingDirectory))
            return Outcome<void>::failure(
                processError(RuntimeErrorCode::invalidArgument,
                             "process working directory escapes process root"));
        if (!std::filesystem::is_directory(workingDirectory))
            return Outcome<void>::failure(processError(RuntimeErrorCode::unavailable,
                                                       "process working directory does not exist"));
        spec.workingDirectory = workingDirectory.string();

        const auto normalizeOutput = [&](std::string& value) -> Outcome<void>
        {
            if (value.empty())
                return Outcome<void>::success();
            auto output = std::filesystem::path(value);
            if (output.is_relative())
                output = root / output;
            const auto parent = std::filesystem::weakly_canonical(output.parent_path());
            output = (parent / output.filename()).lexically_normal();
            // Resolve an existing final component as well. Checking only the canonical parent
            // would allow an in-root symlink/reparse point to redirect log writes outside the
            // configured process root.
            if (std::filesystem::exists(output))
                output = std::filesystem::weakly_canonical(output);
            if (!options.allowOutsideProcessRoot && !containedBy(root, output))
                return Outcome<void>::failure(processError(
                    RuntimeErrorCode::invalidArgument, "process output path escapes process root"));
            if (!std::filesystem::is_directory(parent))
                return Outcome<void>::failure(processError(
                    RuntimeErrorCode::unavailable, "process output directory does not exist"));
            value = output.string();
            return Outcome<void>::success();
        };
        const auto output = normalizeOutput(spec.standardOutputPath);
        if (!output)
            return output;
        const auto error = normalizeOutput(spec.standardErrorPath);
        if (!error)
            return error;
        return Outcome<void>::success();
    }

    Outcome<void> spawnLocked(Entry& entry)
    {
        entry.snapshot.state = ProcessState::starting;
        entry.snapshot.lastError = {};
        entry.snapshot.lastExitCode.reset();
        entry.desiredStop = false;
#ifdef _WIN32
        STARTUPINFOW startup{};
        startup.cb = sizeof(startup);
        startup.dwFlags = STARTF_USESHOWWINDOW;
        startup.wShowWindow = entry.snapshot.spec.hidden ? SW_HIDE : SW_SHOW;
        HANDLE standardOutput = openOutput(entry.snapshot.spec.standardOutputPath);
        HANDLE standardError = openOutput(entry.snapshot.spec.standardErrorPath);
        if ((!entry.snapshot.spec.standardOutputPath.empty() &&
             standardOutput == INVALID_HANDLE_VALUE) ||
            (!entry.snapshot.spec.standardErrorPath.empty() &&
             standardError == INVALID_HANDLE_VALUE))
        {
            if (standardOutput && standardOutput != INVALID_HANDLE_VALUE)
                CloseHandle(standardOutput);
            if (standardError && standardError != INVALID_HANDLE_VALUE)
                CloseHandle(standardError);
            const auto error = processError(RuntimeErrorCode::unavailable,
                                            "failed to open subprocess output file");
            entry.snapshot.state = ProcessState::failed;
            entry.snapshot.lastError = error;
            return Outcome<void>::failure(error);
        }
        const bool redirect = standardOutput || standardError;
        if (redirect)
        {
            startup.dwFlags |= STARTF_USESTDHANDLES;
            startup.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
            startup.hStdOutput = standardOutput ? standardOutput : GetStdHandle(STD_OUTPUT_HANDLE);
            startup.hStdError = standardError ? standardError : GetStdHandle(STD_ERROR_HANDLE);
        }
        auto command = commandLine(entry.snapshot.spec);
        std::vector<wchar_t> environment;
        try
        {
            environment = environmentBlock(entry.snapshot.spec);
        }
        catch (const std::exception& exception)
        {
            if (standardOutput)
                CloseHandle(standardOutput);
            if (standardError)
                CloseHandle(standardError);
            const auto error = processError(RuntimeErrorCode::internalError, exception.what());
            entry.snapshot.state = ProcessState::failed;
            entry.snapshot.lastError = error;
            return Outcome<void>::failure(error);
        }
        PROCESS_INFORMATION process{};
        const auto workingDirectory = widen(entry.snapshot.spec.workingDirectory);
        const BOOL created =
            CreateProcessW(widen(entry.snapshot.spec.executable).c_str(), command.data(), nullptr,
                           nullptr, redirect ? TRUE : FALSE,
                           CREATE_NEW_PROCESS_GROUP | CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT,
                           environment.empty() ? nullptr : environment.data(),
                           workingDirectory.c_str(), &startup, &process);
        if (standardOutput)
            CloseHandle(standardOutput);
        if (standardError)
            CloseHandle(standardError);
        if (!created)
        {
            const auto error = processError(
                RuntimeErrorCode::unavailable,
                "CreateProcess failed with error " + std::to_string(GetLastError()), true);
            entry.snapshot.state = ProcessState::failed;
            entry.snapshot.lastError = error;
            return Outcome<void>::failure(error);
        }
        entry.process = process.hProcess;
        entry.job = CreateJobObjectW(nullptr, nullptr);
        if (!entry.job)
        {
            TerminateProcess(entry.process, 126);
            WaitForSingleObject(entry.process, 1000);
            CloseHandle(process.hThread);
            CloseHandle(entry.process);
            entry.process = nullptr;
            const auto error =
                processError(RuntimeErrorCode::internalError, "CreateJobObject failed");
            entry.snapshot.state = ProcessState::failed;
            entry.snapshot.lastError = error;
            return Outcome<void>::failure(error);
        }
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        if (!SetInformationJobObject(entry.job, JobObjectExtendedLimitInformation, &limits,
                                     sizeof(limits)) ||
            !AssignProcessToJobObject(entry.job, entry.process))
        {
            TerminateJobObject(entry.job, 126);
            WaitForSingleObject(entry.process, 1000);
            CloseHandle(process.hThread);
            CloseHandle(entry.process);
            CloseHandle(entry.job);
            entry.process = nullptr;
            entry.job = nullptr;
            const auto error = processError(RuntimeErrorCode::internalError,
                                            "failed to assign subprocess to Job Object");
            entry.snapshot.state = ProcessState::failed;
            entry.snapshot.lastError = error;
            return Outcome<void>::failure(error);
        }
        if (ResumeThread(process.hThread) == static_cast<DWORD>(-1))
        {
            TerminateJobObject(entry.job, 126);
            WaitForSingleObject(entry.process, 1000);
            CloseHandle(process.hThread);
            CloseHandle(entry.process);
            CloseHandle(entry.job);
            entry.process = nullptr;
            entry.job = nullptr;
            const auto error = processError(RuntimeErrorCode::internalError,
                                            "failed to resume subprocess main thread");
            entry.snapshot.state = ProcessState::failed;
            entry.snapshot.lastError = error;
            return Outcome<void>::failure(error);
        }
        CloseHandle(process.hThread);
        entry.snapshot.processId = process.dwProcessId;
#else
        const auto pid = fork();
        if (pid < 0)
        {
            const auto error =
                processError(RuntimeErrorCode::unavailable,
                             "fork failed with errno " + std::to_string(errno), true);
            entry.snapshot.state = ProcessState::failed;
            entry.snapshot.lastError = error;
            return Outcome<void>::failure(error);
        }
        if (pid == 0)
        {
            setpgid(0, 0);
            if (chdir(entry.snapshot.spec.workingDirectory.c_str()) != 0)
                _exit(126);
            for (const auto& [name, value] : entry.snapshot.spec.environment)
                setenv(name.c_str(), value.c_str(), 1);
            if (!entry.snapshot.spec.standardOutputPath.empty())
            {
                const auto output = open(entry.snapshot.spec.standardOutputPath.c_str(),
                                         O_WRONLY | O_CREAT | O_APPEND, 0600);
                if (output < 0 || dup2(output, STDOUT_FILENO) < 0)
                    _exit(126);
                close(output);
            }
            if (!entry.snapshot.spec.standardErrorPath.empty())
            {
                const auto output = open(entry.snapshot.spec.standardErrorPath.c_str(),
                                         O_WRONLY | O_CREAT | O_APPEND, 0600);
                if (output < 0 || dup2(output, STDERR_FILENO) < 0)
                    _exit(126);
                close(output);
            }
            std::vector<char*> arguments;
            arguments.reserve(entry.snapshot.spec.arguments.size() + 2);
            arguments.push_back(const_cast<char*>(entry.snapshot.spec.executable.c_str()));
            for (auto& argument : entry.snapshot.spec.arguments)
                arguments.push_back(const_cast<char*>(argument.c_str()));
            arguments.push_back(nullptr);
            execv(entry.snapshot.spec.executable.c_str(), arguments.data());
            _exit(127);
        }
        setpgid(pid, pid);
        entry.pid = pid;
        entry.snapshot.processId = static_cast<std::uint64_t>(pid);
#endif
        entry.snapshot.state = ProcessState::running;
        return Outcome<void>::success();
    }

    bool pollExitedLocked(Entry& entry)
    {
        if (entry.snapshot.state != ProcessState::running &&
            entry.snapshot.state != ProcessState::stopping)
            return entry.snapshot.state == ProcessState::exited ||
                   entry.snapshot.state == ProcessState::stopped;
#ifdef _WIN32
        DWORD code = STILL_ACTIVE;
        if (!entry.process || !GetExitCodeProcess(entry.process, &code) || code == STILL_ACTIVE)
            return false;
        entry.snapshot.lastExitCode = static_cast<int>(code);
        CloseHandle(entry.process);
        CloseHandle(entry.job);
        entry.process = nullptr;
        entry.job = nullptr;
#else
        int status = 0;
        const auto waited = waitpid(entry.pid, &status, WNOHANG);
        if (waited == 0 || waited < 0)
            return false;
        entry.snapshot.lastExitCode =
            WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
        entry.pid = -1;
#endif
        entry.snapshot.processId = 0;
        entry.snapshot.state = entry.desiredStop ? ProcessState::stopped : ProcessState::exited;
        wake.notify_all();
        return true;
    }

    bool shouldRestart(const Entry& entry) const
    {
        if (entry.desiredStop || !entry.snapshot.lastExitCode)
            return false;
        return entry.snapshot.spec.restartPolicy == RestartPolicy::always ||
               (entry.snapshot.spec.restartPolicy == RestartPolicy::onFailure &&
                *entry.snapshot.lastExitCode != 0);
    }

    void monitorLoop()
    {
        while (monitoring)
        {
            std::unique_lock<std::mutex> waitLock(mutex);
            wake.wait_for(waitLock, options.monitorInterval);
            waitLock.unlock();
            if (!monitoring)
                break;
            std::lock_guard<std::mutex> operationLock(operationMutex);
            std::lock_guard<std::mutex> lock(mutex);
            const auto now = std::chrono::steady_clock::now();
            for (auto& [_, entry] : entries)
            {
                if (entry.snapshot.state == ProcessState::running)
                    pollExitedLocked(entry);
                if (entry.snapshot.state != ProcessState::exited || !shouldRestart(entry))
                    continue;
                const auto windowStart = now - entry.snapshot.spec.restartWindow;
                while (!entry.restartTimes.empty() && entry.restartTimes.front() < windowStart)
                    entry.restartTimes.pop_front();
                if (entry.restartTimes.size() >= entry.snapshot.spec.maximumRestarts)
                {
                    entry.snapshot.state = ProcessState::quarantined;
                    entry.snapshot.lastError =
                        processError(RuntimeErrorCode::unavailable,
                                     "subprocess restart budget exhausted", false);
                    continue;
                }
                entry.restartTimes.push_back(now);
                ++entry.snapshot.restartCount;
                const auto result = spawnLocked(entry);
                if (!result)
                    entry.snapshot.lastError = result.error();
            }
        }
    }

    Outcome<void> startLocked(const std::string& id)
    {
        const auto found = entries.find(id);
        if (found == entries.end())
            return Outcome<void>::failure(
                processError(RuntimeErrorCode::invalidArgument, "unknown process '" + id + "'"));
        auto& entry = found->second;
        if (entry.snapshot.state == ProcessState::running)
            return Outcome<void>::success();
        for (const auto& dependency : entry.snapshot.spec.dependencies)
        {
            const auto required = entries.find(dependency);
            if (required == entries.end() ||
                required->second.snapshot.state != ProcessState::running)
                return Outcome<void>::failure(processError(
                    RuntimeErrorCode::dependencyFailure,
                    "process '" + id + "' requires running dependency '" + dependency + "'"));
        }
        entry.restartTimes.clear();
        return spawnLocked(entry);
    }

    Outcome<std::vector<std::string>> resolveOrderLocked() const
    {
        std::unordered_map<std::string, std::size_t> indegrees;
        std::unordered_map<std::string, std::vector<std::string>> dependents;
        for (const auto& id : order)
            indegrees[id] = 0;
        for (const auto& id : order)
        {
            for (const auto& dependency : entries.at(id).snapshot.spec.dependencies)
            {
                if (entries.count(dependency) == 0)
                    return Outcome<std::vector<std::string>>::failure(processError(
                        RuntimeErrorCode::dependencyFailure,
                        "process '" + id + "' requires missing dependency '" + dependency + "'"));
                ++indegrees[id];
                dependents[dependency].push_back(id);
            }
        }
        std::deque<std::string> ready;
        for (const auto& id : order)
        {
            if (indegrees[id] == 0)
                ready.push_back(id);
        }
        std::vector<std::string> result;
        while (!ready.empty())
        {
            auto current = std::move(ready.front());
            ready.pop_front();
            result.push_back(current);
            for (const auto& dependent : dependents[current])
            {
                if (--indegrees[dependent] == 0)
                    ready.push_back(dependent);
            }
        }
        if (result.size() != order.size())
            return Outcome<std::vector<std::string>>::failure(processError(
                RuntimeErrorCode::dependencyFailure, "process dependency graph contains a cycle"));
        return Outcome<std::vector<std::string>>::success(std::move(result));
    }

    Outcome<void> stopLocked(const std::string& id)
    {
        Entry* entry = nullptr;
        {
            std::lock_guard<std::mutex> lock(mutex);
            const auto found = entries.find(id);
            if (found == entries.end())
                return Outcome<void>::failure(processError(RuntimeErrorCode::invalidArgument,
                                                           "unknown process '" + id + "'"));
            entry = &found->second;
            if (entry->snapshot.state != ProcessState::running)
            {
                entry->desiredStop = true;
                entry->snapshot.state = ProcessState::stopped;
                return Outcome<void>::success();
            }
            entry->desiredStop = true;
            entry->snapshot.state = ProcessState::stopping;
#ifdef _WIN32
            GenerateConsoleCtrlEvent(CTRL_BREAK_EVENT,
                                     static_cast<DWORD>(entry->snapshot.processId));
#else
            kill(-entry->pid, SIGTERM);
#endif
        }

        const auto deadline =
            std::chrono::steady_clock::now() + entry->snapshot.spec.gracefulStopTimeout;
        while (std::chrono::steady_clock::now() < deadline)
        {
            {
                std::lock_guard<std::mutex> lock(mutex);
                if (pollExitedLocked(*entry))
                    return Outcome<void>::success();
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }

        {
            std::lock_guard<std::mutex> lock(mutex);
#ifdef _WIN32
            if (entry->job)
                TerminateJobObject(entry->job, 137);
            else if (entry->process)
                TerminateProcess(entry->process, 137);
#else
            if (entry->pid > 0)
                kill(-entry->pid, SIGKILL);
#endif
        }
        const auto forceDeadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
        while (std::chrono::steady_clock::now() < forceDeadline)
        {
            {
                std::lock_guard<std::mutex> lock(mutex);
                if (pollExitedLocked(*entry))
                    return Outcome<void>::success();
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
        return Outcome<void>::failure(
            processError(RuntimeErrorCode::timeout, "timed out stopping process '" + id + "'"));
    }
};

NativeProcessSupervisor::NativeProcessSupervisor(NativeProcessSupervisorOptions options)
    : _state(std::make_unique<State>(std::move(options)))
{
}

NativeProcessSupervisor::~NativeProcessSupervisor()
{
    stopAll();
    _state->monitoring = false;
    _state->wake.notify_all();
    if (_state->monitor.joinable())
        _state->monitor.join();
}

Outcome<void> NativeProcessSupervisor::registerProcess(ProcessSpec spec)
{
    std::lock_guard<std::mutex> operationLock(_state->operationMutex);
    const auto normalized = _state->normalize(spec);
    if (!normalized)
        return Outcome<void>::failure(normalized.error());
    std::lock_guard<std::mutex> lock(_state->mutex);
    if (_state->entries.count(spec.id) != 0)
        return Outcome<void>::failure(processError(RuntimeErrorCode::invalidArgument,
                                                   "duplicate process id '" + spec.id + "'"));
    const auto id = spec.id;
    ProcessSnapshot snapshot;
    snapshot.spec = std::move(spec);
    _state->entries.emplace(id, State::Entry{std::move(snapshot)});
    _state->order.push_back(id);
    return Outcome<void>::success();
}

Outcome<void> NativeProcessSupervisor::start(const std::string& id)
{
    std::lock_guard<std::mutex> operationLock(_state->operationMutex);
    std::lock_guard<std::mutex> lock(_state->mutex);
    return _state->startLocked(id);
}

Outcome<void> NativeProcessSupervisor::startAll()
{
    std::lock_guard<std::mutex> operationLock(_state->operationMutex);
    std::vector<std::string> started;
    std::unique_lock<std::mutex> lock(_state->mutex);
    const auto resolved = _state->resolveOrderLocked();
    if (!resolved)
        return Outcome<void>::failure(resolved.error());
    for (const auto& id : resolved.value())
    {
        const auto result = _state->startLocked(id);
        if (!result)
        {
            lock.unlock();
            for (auto iterator = started.rbegin(); iterator != started.rend(); ++iterator)
                _state->stopLocked(*iterator);
            return Outcome<void>::failure(result.error());
        }
        started.push_back(id);
    }
    lock.unlock();
    return Outcome<void>::success();
}

Outcome<void> NativeProcessSupervisor::stop(const std::string& id)
{
    std::lock_guard<std::mutex> operationLock(_state->operationMutex);
    return _state->stopLocked(id);
}

void NativeProcessSupervisor::stopAll() noexcept
{
    std::lock_guard<std::mutex> operationLock(_state->operationMutex);
    std::vector<std::string> ids;
    {
        std::lock_guard<std::mutex> lock(_state->mutex);
        ids = _state->order;
    }
    for (auto iterator = ids.rbegin(); iterator != ids.rend(); ++iterator)
        _state->stopLocked(*iterator);
}

Outcome<void> NativeProcessSupervisor::restart(const std::string& id)
{
    std::lock_guard<std::mutex> operationLock(_state->operationMutex);
    const auto stopped = _state->stopLocked(id);
    if (!stopped)
        return stopped;
    std::lock_guard<std::mutex> lock(_state->mutex);
    return _state->startLocked(id);
}

std::vector<ProcessSnapshot> NativeProcessSupervisor::snapshots() const
{
    std::lock_guard<std::mutex> operationLock(_state->operationMutex);
    std::lock_guard<std::mutex> lock(_state->mutex);
    std::vector<ProcessSnapshot> result;
    result.reserve(_state->order.size());
    for (const auto& id : _state->order)
    {
        auto& entry = _state->entries.at(id);
        _state->pollExitedLocked(entry);
        result.push_back(entry.snapshot);
    }
    return result;
}

} // namespace PocoDDS::NativeProcess
