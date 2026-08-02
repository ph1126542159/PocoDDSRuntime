//
// RuntimeLauncher.cpp
//
// The launcher/watchdog for macchina.io server
//
// Copyright (c) 2017, Applied Informatics Software Engineering GmbH.
// All rights reserved.
//
// SPDX-License-Identifier: GPL-3.0-only
//


#include "Poco/Util/ServerApplication.h"
#include "Poco/OSP/OSPSubsystem.h"
#include "PocoDDS/BundleManagement/BundleManager.h"
#include "Poco/Util/Option.h"
#include "Poco/Util/OptionSet.h"
#include "Poco/Util/HelpFormatter.h"
#include "Poco/RunnableAdapter.h"
#include "Poco/Thread.h"
#include "Poco/Event.h"
#include "Poco/ErrorHandler.h"
#include "Poco/File.h"
#include "Poco/Process.h"
#include "Poco/Format.h"
#include "Poco/Platform.h"
#if defined(POCO_OS_FAMILY_WINDOWS)
#include <Windows.h>
#endif
#include <iostream>
#include <atomic>
#include <chrono>
#include <deque>
#include <fstream>
#include <memory>
#include <utility>


using Poco::Util::Application;
using Poco::Util::ServerApplication;
using Poco::Util::Option;
using Poco::Util::OptionSet;
using Poco::Util::OptionCallback;
using Poco::Util::HelpFormatter;
using Poco::format;


class RuntimeLauncherApp: public ServerApplication
{
public:
	RuntimeLauncherApp():
		_errorHandler(*this),
		_osp(new Poco::OSP::OSPSubsystem),
		_helpRequested(false),
		_explicitConfigRequested(false),
		_stopped(false),
		_restartBudgetExhausted(false),
		_pid(0),
		_launchedAtMicroseconds(0),
		_watchdogKilledPid(0)
#if defined(POCO_OS_FAMILY_WINDOWS)
		,_job(nullptr)
#endif
	{
		Poco::ErrorHandler::set(&_errorHandler);
		addSubsystem(_osp);
	}

	~RuntimeLauncherApp()
	{
#if defined(POCO_OS_FAMILY_WINDOWS)
		if (_job) CloseHandle(_job);
#endif
	}

	static const std::string ETC_CONFIG;

protected:
	class ErrorHandler: public Poco::ErrorHandler
	{
	public:
		ErrorHandler(RuntimeLauncherApp& app):
			_app(app)
		{
		}

		void exception(const Poco::Exception& exc)
		{
			log(exc.displayText());
		}

		void exception(const std::exception& exc)
		{
			log(exc.what());
		}

		void exception()
		{
			log("unknown exception");
		}

		void log(const std::string& message)
		{
			_app.logger().error("A thread was terminated by an unhandled exception: " + message);
		}

	private:
		RuntimeLauncherApp& _app;
	};

	void initialize(Application& self)
	{
		if (!_explicitConfigRequested)
			loadConfiguration(); // load default configuration files, if present

		// load configuration from /etc/launcher.properties, if present (for deployment)
		Poco::File f(ETC_CONFIG);
		if (f.exists())
		{
			loadConfiguration(ETC_CONFIG);
		}

		ServerApplication::initialize(self);
	}

	void uninitialize()
	{
		ServerApplication::uninitialize();
	}

	void defineOptions(OptionSet& options)
	{
		ServerApplication::defineOptions(options);

		options.addOption(
			Option("help", "h", "Display help information on command line arguments.")
				.required(false)
				.repeatable(false)
				.callback(OptionCallback<RuntimeLauncherApp>(this, &RuntimeLauncherApp::handleHelp)));

		options.addOption(
			Option("config-file", "c", "Load configuration data from a file.")
				.required(false)
				.repeatable(true)
				.argument("file")
				.callback(OptionCallback<RuntimeLauncherApp>(this, &RuntimeLauncherApp::handleConfig)));
	}

	void handleHelp(const std::string& , const std::string& )
	{
		_helpRequested = true;
		displayHelp();
		stopOptionsProcessing();
	}

	void displayHelp()
	{
		HelpFormatter helpFormatter(options());
		helpFormatter.setCommand(commandName());
		helpFormatter.setUsage("[<option> ...] -- <command>");
		helpFormatter.setHeader(
			"\n"
			"Applied Informatics Launcher for server applications.\n"
			"Copyright (c) 2011-2017 by Applied Informatics Software Engineering GmbH.\n"
			"All rights reserved.\n\n"
			"This program is used to launch server applications and "
			"to automatically relaunch them in case they terminate unexpectedly.\n\n"
			"The following command line options are supported:"
		);
		helpFormatter.setIndent(8);
		helpFormatter.format(std::cout);
	}

	void handleConfig(const std::string& , const std::string& value)
	{
		_explicitConfigRequested = true;
		loadConfiguration(value);
	}

	void watch()
	{
		const int timeout = std::max(1, config().getInt("watchdog.timeout", 600000));
		const int interval = std::max(1, config().getInt("watchdog.interval", 60000));
		const int startupGrace = std::max(
			0, config().getInt("watchdog.startupGraceMilliseconds", timeout));
		const bool requireFile = config().getBool("watchdog.requireFile", false);

		while (!_stopWatching.tryWait(interval))
		{
			try
			{
				std::string path = config().getString("watchdog.file", "");
				if (!path.empty())
				{
					Poco::File f(path);
					const auto pid = _pid.load();
					const auto launchedAt = _launchedAtMicroseconds.load();
					const bool graceElapsed = pid != 0 && launchedAt != 0 &&
						Poco::Timestamp().epochMicroseconds() - launchedAt >=
						static_cast<Poco::Timestamp::TimeVal>(startupGrace) * 1000;
					bool unhealthy = false;
					if (f.exists())
					{
						Poco::Timestamp lastModified = f.getLastModified();
						unhealthy = graceElapsed && lastModified.isElapsed(
							static_cast<Poco::Timestamp::TimeVal>(1000) * timeout);
					}
					else unhealthy = graceElapsed && requireFile;
					if (unhealthy && _watchdogKilledPid.exchange(pid) != pid)
					{
						logger().error(f.exists()
							? "Watchdog is killing %s after heartbeat timeout"
							: "Watchdog is killing %s because the required heartbeat file is missing",
							_command);
						if (pid != 0) Poco::Process::kill(pid);
					}
				}
			}
			catch (Poco::Exception& exc)
			{
				logger().log(exc);
			}
		}
	}

	void launch()
	{
		const int delay = std::max(0, config().getInt("relaunchDelay", 1000));
		const int maximumRestarts = std::max(0, config().getInt("restartBudget.maxRestarts", 5));
		const auto restartWindow = std::chrono::milliseconds(
			std::max(1, config().getInt("restartBudget.windowMilliseconds", 60000)));
		std::deque<std::chrono::steady_clock::time_point> restarts;
		while (!_stopped.load())
		{
			try
			{
				logger().information(format("Launching %s...", _command));
				Poco::ProcessHandle ph = Poco::Process::launch(_command, _args);
				try
				{
					assignResourceBoundary(ph.id());
				}
				catch (...)
				{
					if (Poco::Process::isRunning(ph)) Poco::Process::kill(ph);
					throw;
				}
				_pid.store(ph.id());
				_launchedAtMicroseconds.store(Poco::Timestamp().epochMicroseconds());
				_watchdogKilledPid.store(0);
				logger().information(format("Launched %s (%?d).", _command, ph.id()));
				int rc = ph.wait();
				logger().information(format("%s exited with status %d.", _command, rc));
				_pid.store(0);
				_launchedAtMicroseconds.store(0);
			}
			catch (Poco::Exception& exc)
			{
				logger().log(exc);
			}
			if (!_stopped.load())
			{
				const auto now = std::chrono::steady_clock::now();
				while (!restarts.empty() && now - restarts.front() >= restartWindow)
					restarts.pop_front();
				if (maximumRestarts == 0 || static_cast<int>(restarts.size()) >= maximumRestarts)
				{
					_restartBudgetExhausted.store(true);
					logger().critical(format(
						"Restart budget exhausted for %s: maximum %d restart(s) in %?d ms.",
						_command, maximumRestarts, restartWindow.count()));
					ServerApplication::terminate();
					break;
				}
				restarts.push_back(now);
				logger().information(format("Waiting %d ms before relaunch...", delay));
				Poco::Timestamp ts;
				while (!_stopped.load() && !ts.isElapsed(delay*1000))
				{
					Poco::Thread::sleep(100);
				}
			}
		}
	}

	int main(const std::vector<std::string>& args)
	{
		if (_helpRequested) return Application::EXIT_OK;
		if (args.empty())
		{
			displayHelp();
			return Application::EXIT_USAGE;
		}

		_command = args[0];
		_args.assign(args.begin() + 1, args.end());
		const int configuredChildArguments = config().getInt("childArgument.count", 0);
		if (configuredChildArguments < 0)
			throw Poco::InvalidArgumentException("childArgument.count must be non-negative");
		for (int index = 0; index < configuredChildArguments; ++index)
			_args.push_back(config().getString("childArgument." + std::to_string(index)));
		validateSupervisionConfiguration();
		configureResourceBoundary();

		if (config().getBool("osp.bundleMonitor.enabled", true))
		{
			PocoDDS::BundleManagement::BundleManagerOptions options;
			options.repositories = config().getString(
				"osp.bundleRepository", config().expand("${application.dir}bundles/"));
			options.intervalMilliseconds =
				config().getInt64("osp.bundleMonitor.intervalMilliseconds", 1000);
			_bundleManager = std::make_unique<PocoDDS::BundleManagement::BundleManager>(
				*_osp, logger(), std::move(options));
			_bundleManager->start();
		}

		Poco::RunnableAdapter<RuntimeLauncherApp> launchRunnable(*this, &RuntimeLauncherApp::launch);
		Poco::Thread launchThread;
		launchThread.start(launchRunnable);

		Poco::RunnableAdapter<RuntimeLauncherApp> watchRunnable(*this, &RuntimeLauncherApp::watch);
		Poco::Thread watchThread;
		watchThread.start(watchRunnable);

		waitForTerminationRequest();

		_stopWatching.set();
		watchThread.join();

		const auto pid = _pid.load();
		if (pid != 0)
		{
			logger().information(format("Stopping %s (%?d)...", _command, pid));
			try
			{
				Poco::Process::requestTermination(pid);
			}
			catch (Poco::Exception& exc)
			{
				logger().log(exc);
			}
		}
		_stopped.store(true);
		if (!launchThread.tryJoin(1000))
		{
			try
			{
				const auto activePid = _pid.load();
				if (activePid != 0) Poco::Process::kill(activePid);
			}
			catch (Poco::Exception& exc)
			{
				logger().log(exc);
			}
			launchThread.join();
		}
		if (_bundleManager)
			_bundleManager->stop();
		releaseResourceBoundary();

		return _restartBudgetExhausted.load() ? Application::EXIT_SOFTWARE : Application::EXIT_OK;
	}

private:
	void validateSupervisionConfiguration()
	{
		const auto requireAtLeast = [this](const char* key, int minimum, int fallback)
		{
			const int value = config().getInt(key, fallback);
			if (value < minimum)
				throw Poco::InvalidArgumentException(
					format("%s must be at least %d", std::string(key), minimum));
		};
		requireAtLeast("relaunchDelay", 0, 1000);
		requireAtLeast("restartBudget.maxRestarts", 0, 5);
		requireAtLeast("restartBudget.windowMilliseconds", 1, 60000);
		requireAtLeast("watchdog.timeout", 1, 600000);
		requireAtLeast("watchdog.interval", 1, 60000);
		requireAtLeast("watchdog.startupGraceMilliseconds", 0, 600000);
		const std::string heartbeat = config().getString("watchdog.file", "");
		if (config().getBool("watchdog.requireFile", false) && heartbeat.empty())
			throw Poco::InvalidArgumentException(
				"watchdog.file is required when watchdog.requireFile is true");
		if (!heartbeat.empty())
		{
			const Poco::Path heartbeatPath(heartbeat);
			(void) heartbeatPath; // Validate syntax before starting the supervised child.
		}
	}

	void configureResourceBoundary()
	{
		const auto memoryBytes = config().getUInt64("resourceLimits.memoryBytes", 0);
		const auto activeProcesses = config().getUInt("resourceLimits.activeProcessLimit", 0);
		const auto cpuPercent = config().getUInt("resourceLimits.cpuRatePercent", 0);
		if (cpuPercent > 100)
			throw Poco::InvalidArgumentException("resourceLimits.cpuRatePercent must be 0..100");
#if defined(POCO_OS_FAMILY_WINDOWS)
		const bool killTree = config().getBool("resourceLimits.killProcessTreeOnExit", true);
		if (!killTree && memoryBytes == 0 && activeProcesses == 0 && cpuPercent == 0) return;
		_job = CreateJobObjectW(nullptr, nullptr);
		if (!_job) throw Poco::SystemException("CreateJobObject failed", GetLastError());
		JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
		if (killTree) limits.BasicLimitInformation.LimitFlags |= JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
		if (memoryBytes > 0)
		{
			limits.BasicLimitInformation.LimitFlags |= JOB_OBJECT_LIMIT_PROCESS_MEMORY;
			limits.ProcessMemoryLimit = static_cast<SIZE_T>(memoryBytes);
		}
		if (activeProcesses > 0)
		{
			limits.BasicLimitInformation.LimitFlags |= JOB_OBJECT_LIMIT_ACTIVE_PROCESS;
			limits.BasicLimitInformation.ActiveProcessLimit = activeProcesses;
		}
		if (!SetInformationJobObject(_job, JobObjectExtendedLimitInformation,
			&limits, sizeof(limits)))
			throw Poco::SystemException("SetInformationJobObject limits failed", GetLastError());
		if (cpuPercent > 0)
		{
			JOBOBJECT_CPU_RATE_CONTROL_INFORMATION cpu{};
			cpu.ControlFlags = JOB_OBJECT_CPU_RATE_CONTROL_ENABLE |
				JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP;
			cpu.CpuRate = cpuPercent * 100;
			if (!SetInformationJobObject(_job, JobObjectCpuRateControlInformation,
				&cpu, sizeof(cpu)))
				throw Poco::SystemException("SetInformationJobObject CPU rate failed", GetLastError());
		}
		logger().information("Windows Job Object resource boundary configured.");
#else
		_linuxCgroupPath = config().getString("resourceLimits.linuxCgroupPath", "");
		_linuxKillTree = config().getBool("resourceLimits.killProcessTreeOnExit", true);
		if ((memoryBytes || activeProcesses || cpuPercent) && _linuxCgroupPath.empty())
			throw Poco::NotImplementedException(
				"numeric resourceLimits require resourceLimits.linuxCgroupPath on Linux");
		if (!_linuxCgroupPath.empty())
		{
			Poco::Path cgroup(_linuxCgroupPath);
			if (!cgroup.isAbsolute() || !Poco::File(cgroup).isDirectory())
				throw Poco::InvalidArgumentException("resourceLimits.linuxCgroupPath must be an existing absolute cgroup v2 directory");
			if (memoryBytes) writeCgroupControl("memory.max", std::to_string(memoryBytes));
			if (activeProcesses) writeCgroupControl("pids.max", std::to_string(activeProcesses));
			if (cpuPercent) writeCgroupControl("cpu.max", std::to_string(cpuPercent * 1000) + " 100000");
			logger().information("Linux cgroup v2 resource boundary configured: %s", _linuxCgroupPath);
		}
#endif
	}

	void assignResourceBoundary(Poco::ProcessHandle::PID pid)
	{
#if defined(POCO_OS_FAMILY_WINDOWS)
		if (!_job) return;
		HANDLE process = OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, FALSE, pid);
		if (!process) throw Poco::SystemException("OpenProcess for Job Object failed", GetLastError());
		const BOOL assigned = AssignProcessToJobObject(_job, process);
		const DWORD error = assigned ? ERROR_SUCCESS : GetLastError();
		CloseHandle(process);
		if (!assigned) throw Poco::SystemException("AssignProcessToJobObject failed", error);
#else
		if (!_linuxCgroupPath.empty()) writeCgroupControl("cgroup.procs", std::to_string(pid));
#endif
	}

	void releaseResourceBoundary()
	{
#if !defined(POCO_OS_FAMILY_WINDOWS)
		if (_linuxKillTree && !_linuxCgroupPath.empty())
		{
			Poco::Path kill(_linuxCgroupPath); kill.append("cgroup.kill");
			if (Poco::File(kill).exists()) writeCgroupControl("cgroup.kill", "1");
		}
#endif
	}

#if !defined(POCO_OS_FAMILY_WINDOWS)
	void writeCgroupControl(const std::string& name, const std::string& value)
	{
		Poco::Path path(_linuxCgroupPath); path.append(name);
		std::ofstream output(path.toString(), std::ios::trunc);
		if (!output) throw Poco::FileAccessDeniedException("cannot open cgroup control", path.toString());
		output << value;
		output.flush();
		if (!output) throw Poco::WriteFileException("cannot write cgroup control", path.toString());
	}
#endif

	ErrorHandler _errorHandler;
	Poco::OSP::OSPSubsystem* _osp;
	std::unique_ptr<PocoDDS::BundleManagement::BundleManager> _bundleManager;
	bool _helpRequested;
	bool _explicitConfigRequested;
	std::string _command;
	std::vector<std::string> _args;
	std::atomic<bool> _stopped;
	std::atomic<bool> _restartBudgetExhausted;
	Poco::Event _stopWatching;
	std::atomic<Poco::ProcessHandle::PID> _pid;
	std::atomic<Poco::Timestamp::TimeVal> _launchedAtMicroseconds;
	std::atomic<Poco::ProcessHandle::PID> _watchdogKilledPid;
#if defined(POCO_OS_FAMILY_WINDOWS)
	HANDLE _job;
#else
	std::string _linuxCgroupPath;
	bool _linuxKillTree{true};
#endif
};


const std::string RuntimeLauncherApp::ETC_CONFIG("/etc/pdr-launcher.properties");


POCO_SERVER_MAIN(RuntimeLauncherApp)

