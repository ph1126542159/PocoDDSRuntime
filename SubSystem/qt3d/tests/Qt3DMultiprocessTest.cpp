#include "PocoDDS/Observability/BusinessTracer.h"
#include "PocoDDS/ProcessManagement/SubprocessManager.h"

#include <Poco/File.h>
#include <Poco/Logger.h>
#include <Poco/Path.h>
#include <Poco/Process.h>
#include <Poco/Thread.h>
#include <Poco/TemporaryFile.h>

#include <chrono>
#include <algorithm>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace
{
struct Result
{
    std::string traceId;
    unsigned long processId{0};
    std::string businessId;
    std::string status;
};

Result readResult(const std::string& path)
{
    std::ifstream input(path);
    Result result;
    std::string processId;
    std::getline(input, result.traceId);
    std::getline(input, processId);
    std::getline(input, result.businessId);
    std::getline(input, result.status);
    if (!input || result.traceId.empty())
        throw std::runtime_error("Qt3D child did not write a valid trace result: " + path);
    result.processId = std::stoul(processId);
    return result;
}

bool resultReady(const std::string& path)
{
    Poco::File file(path);
    return file.exists() && file.getSize() > 0;
}
} // namespace

int main(int argc, char** argv)
{
    if (argc != 2)
    {
        std::cerr << "usage: pdr-qt3d-multiprocess-test <qt3d-executable>\n";
        return 2;
    }

    std::vector<std::string> resultFiles;
    try
    {
        PocoDDS::Observability::BusinessTracer tracer("pdr-qt3d-test-coordinator");
        auto business = tracer.startBusiness(
            "Qt3D多进程架构测试",
            {{"childCount", "2"}},
            "qt3d-multiprocess-acceptance");
        const std::string traceParent = business.traceParent();
        const std::string businessId = business.businessInstanceId();

        Poco::Path executable(argv[1]);
        executable.makeAbsolute();
        Poco::Path processRoot(executable);
        processRoot.makeParent();
        Poco::Path configurationPath(Poco::TemporaryFile::tempName());
        resultFiles.push_back(configurationPath.toString());
        std::ofstream configuration(configurationPath.toString(), std::ios::trunc);
        configuration << "subprocess.count = 2\n";
        for (int index = 0; index < 2; ++index)
        {
            Poco::Path resultPath(Poco::TemporaryFile::tempName());
            std::string resultFile = resultPath.toString();
            std::replace(resultFile.begin(), resultFile.end(), '\\', '/');
            resultFiles.push_back(std::move(resultFile));
            const std::string prefix = "subprocess." + std::to_string(index) + ".";
            configuration << prefix << "enabled = true\n"
                          << prefix << "name = qt3d-child-" << index + 1 << '\n'
                          << prefix << "path = " << executable.getFileName() << '\n'
                          << prefix << "argument.count = 9\n"
                          << prefix << "argument.0 = --self-test\n"
                          << prefix << "argument.1 = --traceparent\n"
                          << prefix << "argument.2 = " << traceParent << '\n'
                          << prefix << "argument.3 = --business-id\n"
                          << prefix << "argument.4 = " << businessId << '\n'
                          << prefix << "argument.5 = --instance\n"
                          << prefix << "argument.6 = child-" << index + 1 << '\n'
                          << prefix << "argument.7 = --result-file\n"
                          << prefix << "argument.8 = " << resultFiles.back() << '\n';
        }
        configuration.close();

        PocoDDS::ProcessManagement::SubprocessManager manager(Poco::Logger::root());
        const auto started =
            manager.startFromConfiguration(configurationPath.toString(), processRoot.toString());
        if (started != 2 || manager.runningCount() != 2)
            throw std::runtime_error("SubprocessManager did not start both Qt3D processes");

        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(10);
        while ((!resultReady(resultFiles[1]) ||
                !resultReady(resultFiles[2])) &&
               std::chrono::steady_clock::now() < deadline)
        {
            Poco::Thread::sleep(25);
        }

        const Result first = readResult(resultFiles[1]);
        const Result second = readResult(resultFiles[2]);
        if (first.traceId != second.traceId)
            throw std::runtime_error("child trace IDs do not match");
        if (first.processId == second.processId ||
            first.processId == Poco::Process::id() ||
            second.processId == Poco::Process::id())
            throw std::runtime_error("process isolation was not established");
        if (first.businessId != businessId || second.businessId != businessId)
            throw std::runtime_error("business instance context was not propagated");
        if (first.status != "success" || second.status != "success")
            throw std::runtime_error("a child business span did not finish successfully");

        business.success({{"childrenReady", "2"},
                          {"traceId", first.traceId}});
        manager.stopAll();
        for (const auto& path : resultFiles)
            Poco::File(path).remove();
        std::cout << "QT3D_MULTIPROCESS_TRACE_PASS coordinatorPid="
                  << Poco::Process::id() << " childPid1=" << first.processId
                  << " childPid2=" << second.processId
                  << " traceId=" << first.traceId << '\n';
        return 0;
    }
    catch (const std::exception& exception)
    {
        for (const auto& path : resultFiles)
        {
            Poco::File file(path);
            if (file.exists())
                file.remove();
        }
        std::cerr << "QT3D_MULTIPROCESS_TRACE_FAIL " << exception.what() << '\n';
        return 1;
    }
}
