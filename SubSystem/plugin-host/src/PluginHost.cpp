#include "Poco/Exception.h"
#include "Poco/Environment.h"
#include "Poco/File.h"
#include "Poco/JSON/Array.h"
#include "Poco/JSON/Object.h"
#include "Poco/OSP/BundleFilter.h"
#include "Poco/OSP/BundleLoader.h"
#include "Poco/OSP/OSPSubsystem.h"
#include "Poco/Path.h"
#include "Poco/Process.h"
#include "Poco/RunnableAdapter.h"
#include "Poco/String.h"
#include "Poco/Thread.h"
#include "Poco/Timestamp.h"
#include "Poco/Util/Application.h"
#include "Poco/Util/Option.h"
#include "Poco/Util/OptionSet.h"
#include "Poco/Util/ServerApplication.h"

#include <atomic>
#include <algorithm>
#include <fstream>
#include <set>
#include <sstream>
#include <string>
#include <vector>

namespace
{
class AllowlistFilter final : public Poco::OSP::BundleFilter
{
  public:
    explicit AllowlistFilter(std::set<std::string> allowed) : _allowed(std::move(allowed)) {}
    bool accept(Poco::OSP::Bundle::Ptr bundle) override
    {
        return _allowed.find(bundle->symbolicName()) != _allowed.end();
    }
  private:
    std::set<std::string> _allowed;
};

class PluginHost final : public Poco::Util::ServerApplication
{
  public:
    PluginHost()
        : _osp(new Poco::OSP::OSPSubsystem),
          _heartbeatRunnable(*this, &PluginHost::heartbeatLoop)
    {
        addSubsystem(_osp);
    }

  protected:
    void defineOptions(Poco::Util::OptionSet& options) override
    {
        ServerApplication::defineOptions(options);
        options.addOption(Poco::Util::Option("config-file", "c", "Load plugin host configuration")
            .required(false).repeatable(true).argument("file")
            .callback(Poco::Util::OptionCallback<PluginHost>(this, &PluginHost::handleConfig)));
    }

    void handleConfig(const std::string&, const std::string& value)
    {
        _explicitConfiguration = true;
        _configurationFiles.push_back(value);
    }

    void initialize(Application& self) override
    {
        if (Poco::Environment::has("PDR_PLUGIN_HOST_CONFIG"))
        {
            _explicitConfiguration = true;
            _configurationFiles.push_back(Poco::Environment::get("PDR_PLUGIN_HOST_CONFIG"));
        }
        if (!_explicitConfiguration) loadConfiguration();
        for (const auto& file : _configurationFiles) loadConfiguration(file);
        _pluginId = Poco::trim(config().getString("pluginHost.pluginId", ""));
        if (_pluginId.rfind("pdr.plugin.", 0) != 0)
            throw Poco::InvalidArgumentException(
                "pluginHost.pluginId must be an exact pdr.plugin.* symbolic name");
        std::set<std::string> allowed{"osp.core", _pluginId};
        std::stringstream dependencies(config().getString("pluginHost.allowedBundles", ""));
        std::string dependency;
        while (std::getline(dependencies, dependency, ','))
        {
            dependency = Poco::trim(dependency);
            if (!dependency.empty()) allowed.insert(dependency);
        }
        _heartbeatFile = config().expand(config().getString("pluginHost.heartbeatFile"));
        _stateFile = config().expand(config().getString("pluginHost.stateFile"));
        _interval = config().getInt("pluginHost.heartbeatIntervalMilliseconds", 1000);
        if (_heartbeatFile.empty() || _stateFile.empty() || _interval < 10)
            throw Poco::InvalidArgumentException(
                "plugin host heartbeat/state paths must be set and interval must be at least 10 ms");
        ensureParent(_heartbeatFile);
        ensureParent(_stateFile);
        _osp->setBundleFilter(new AllowlistFilter(std::move(allowed)));
        ServerApplication::initialize(self);
    }

    int main(const std::vector<std::string>&) override
    {
        auto plugin = _osp->bundleLoader().findBundle(_pluginId);
        if (!plugin)
            throw Poco::NotFoundException("isolated plugin Bundle not found", _pluginId);
        if (plugin->state() != Poco::OSP::Bundle::BUNDLE_ACTIVE)
            throw Poco::IllegalStateException("isolated plugin did not become active", _pluginId);
        _pluginVersion = plugin->version().toString();
        writeState("running", _pluginVersion, "");
        _running.store(true);
        _heartbeatThread.start(_heartbeatRunnable);
        waitForTerminationRequest();
        _running.store(false);
        _heartbeatThread.join();
        writeState("stopped", _pluginVersion, "termination requested");
        return Application::EXIT_OK;
    }

    void heartbeatLoop()
    {
        while (_running.load())
        {
            const Poco::Timestamp now;
            std::ofstream heartbeat(_heartbeatFile, std::ios::trunc);
            heartbeat << now.epochMicroseconds() << '\n';
            heartbeat.close();
            writeState("running", _pluginVersion, "");
            for (int waited = 0; _running.load() && waited < _interval; waited += 25)
                Poco::Thread::sleep(std::min(25, _interval - waited));
        }
    }

  private:
    static void ensureParent(const std::string& file)
    {
        Poco::Path path(file); path.makeParent();
        if (!path.toString().empty()) Poco::File(path).createDirectories();
    }

    void writeState(const std::string& state, const std::string& version,
                    const std::string& detail)
    {
        Poco::JSON::Object object;
        object.set("schemaVersion", 1);
        object.set("pluginId", _pluginId);
        object.set("pluginVersion", version);
        object.set("state", state);
        object.set("hostPid", static_cast<Poco::UInt64>(Poco::Process::id()));
        object.set("updatedMicroseconds", Poco::Timestamp().epochMicroseconds());
        if (!detail.empty()) object.set("detail", detail);
        Poco::JSON::Array::Ptr children = new Poco::JSON::Array;
        object.set("children", children);
        Poco::JSON::Array::Ptr bundles = new Poco::JSON::Array;
        Poco::JSON::Object::Ptr plugin = new Poco::JSON::Object;
        plugin->set("id", _pluginId);
        plugin->set("name", _pluginId);
        plugin->set("version", version);
        plugin->set("state", state == "running" ? "active" : "resolved");
        plugin->set("manageable", false);
        plugin->set("plugin", true);
        plugin->set("isolation", "process");
        bundles->add(plugin);
        object.set("bundles", bundles);
        const std::string temporary = _stateFile + ".new";
        std::ofstream output(temporary, std::ios::trunc);
        object.stringify(output);
        output << '\n'; output.close();
        Poco::File target(_stateFile);
        if (target.exists()) target.remove(false);
        Poco::File(temporary).moveTo(_stateFile);
    }

    Poco::OSP::OSPSubsystem* _osp;
    bool _explicitConfiguration{false};
    std::vector<std::string> _configurationFiles;
    std::string _pluginId;
    std::string _heartbeatFile;
    std::string _stateFile;
    std::string _pluginVersion;
    int _interval{1000};
    std::atomic<bool> _running{false};
    Poco::RunnableAdapter<PluginHost> _heartbeatRunnable;
    Poco::Thread _heartbeatThread;
};
}

POCO_SERVER_MAIN(PluginHost)
