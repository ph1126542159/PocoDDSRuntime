#include "PocoDDS/Supervisor/Process.h"

#include <csignal>
#include <filesystem>
#include <stdexcept>
#include <sys/types.h>
#include <sys/wait.h>
#include <thread>
#include <unistd.h>

namespace PocoDDS::Supervisor
{
namespace
{
class NativeProcess final : public Process
{
  public:
    explicit NativeProcess(pid_t id) : _id(id) {}
    bool running() override
    {
        if (_exited)
            return false;
        int status = 0;
        const auto result = waitpid(_id, &status, WNOHANG);
        if (result == _id)
            _exited = true;
        return !_exited;
    }
    int processId() const override { return static_cast<int>(_id); }
    void terminate(std::chrono::milliseconds gracePeriod) override
    {
        if (!running())
            return;
        kill(_id, SIGTERM);
        const auto deadline = std::chrono::steady_clock::now() + gracePeriod;
        while (running() && std::chrono::steady_clock::now() < deadline)
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        if (running())
            kill(_id, SIGKILL);
        while (waitpid(_id, nullptr, 0) == -1 && errno == EINTR)
        {
        }
        _exited = true;
    }

  private:
    pid_t _id;
    bool _exited{false};
};

class NativeLauncher final : public ProcessLauncher
{
  public:
    std::unique_ptr<Process> start(const ProcessSpec& spec) override
    {
        const auto id = fork();
        if (id < 0)
            throw std::runtime_error("fork failed");
        if (id == 0)
        {
            if (!spec.workingDirectory.empty())
                std::filesystem::current_path(spec.workingDirectory);
            std::vector<char*> arguments;
            arguments.push_back(const_cast<char*>(spec.executable.c_str()));
            for (const auto& argument : spec.arguments)
                arguments.push_back(const_cast<char*>(argument.c_str()));
            arguments.push_back(nullptr);
            execv(spec.executable.c_str(), arguments.data());
            _exit(127);
        }
        return std::make_unique<NativeProcess>(id);
    }
};
} // namespace

std::unique_ptr<ProcessLauncher> createNativeProcessLauncher()
{
    return std::make_unique<NativeLauncher>();
}
} // namespace PocoDDS::Supervisor
