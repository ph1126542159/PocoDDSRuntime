#include "PocoDDS/Supervisor/Process.h"

#define WIN32_LEAN_AND_MEAN
#include <Windows.h>

#include <stdexcept>

namespace PocoDDS::Supervisor
{
namespace
{
std::wstring widen(const std::string& value)
{
    if (value.empty())
        return {};
    const auto size =
        MultiByteToWideChar(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), nullptr, 0);
    std::wstring result(static_cast<std::size_t>(size), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), result.data(),
                        size);
    return result;
}

std::wstring quote(const std::string& value)
{
    auto result = widen(value);
    if (result.find_first_of(L" \t\"") == std::wstring::npos)
        return result;
    return L'"' + result + L'"';
}

class NativeProcess final : public Process
{
  public:
    NativeProcess(HANDLE handle, DWORD id) : _handle(handle), _id(id) {}
    ~NativeProcess() override
    {
        if (_handle)
            CloseHandle(_handle);
    }
    bool running() override { return WaitForSingleObject(_handle, 0) == WAIT_TIMEOUT; }
    int processId() const override { return static_cast<int>(_id); }
    void terminate(std::chrono::milliseconds gracePeriod) override
    {
        if (!running())
            return;
        if (WaitForSingleObject(_handle, static_cast<DWORD>(gracePeriod.count())) == WAIT_TIMEOUT)
            TerminateProcess(_handle, 1);
        WaitForSingleObject(_handle, 5000);
    }

  private:
    HANDLE _handle;
    DWORD _id;
};

class NativeLauncher final : public ProcessLauncher
{
  public:
    std::unique_ptr<Process> start(const ProcessSpec& spec) override
    {
        auto command = quote(spec.executable);
        for (const auto& argument : spec.arguments)
            command += L" " + quote(argument);
        std::vector<wchar_t> mutableCommand(command.begin(), command.end());
        mutableCommand.push_back(L'\0');
        STARTUPINFOW startup{};
        startup.cb = sizeof(startup);
        PROCESS_INFORMATION information{};
        const auto directory = widen(spec.workingDirectory);
        if (!CreateProcessW(nullptr, mutableCommand.data(), nullptr, nullptr, FALSE, 0, nullptr,
                            directory.empty() ? nullptr : directory.c_str(), &startup,
                            &information))
            throw std::runtime_error("CreateProcessW failed: " + std::to_string(GetLastError()));
        CloseHandle(information.hThread);
        return std::make_unique<NativeProcess>(information.hProcess, information.dwProcessId);
    }
};
} // namespace

std::unique_ptr<ProcessLauncher> createNativeProcessLauncher()
{
    return std::make_unique<NativeLauncher>();
}
} // namespace PocoDDS::Supervisor
