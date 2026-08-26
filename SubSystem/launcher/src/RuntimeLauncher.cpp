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
#include "PocoDDS/BundleManagement/BundleDeploymentCoordinator.h"
#include "Poco/Util/Option.h"
#include "Poco/Util/OptionSet.h"
#include "Poco/Util/HelpFormatter.h"
#include "Poco/RunnableAdapter.h"
#include "Poco/Thread.h"
#include "Poco/Event.h"
#include "Poco/ErrorHandler.h"
#include "Poco/File.h"
#include "Poco/FileStream.h"
#include "Poco/Process.h"
#include "Poco/Path.h"
#include "Poco/Format.h"
#include "Poco/Platform.h"
#if defined(POCO_OS_FAMILY_WINDOWS)
#include <Windows.h>
#include "Poco/UnicodeConverter.h"
#endif
#include <algorithm>
#include <cctype>
#include <cwchar>
#include <iostream>
#include <atomic>
#include <chrono>
#include <deque>
#include <fstream>
#include <iterator>
#include <memory>
#include <utility>

#if !defined(POCO_OS_FAMILY_WINDOWS)
extern "C" char** environ;
#endif


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
		const auto deploymentPoll = std::chrono::milliseconds(
			std::max(50, config().getInt("deployment.pollMilliseconds", 250)));
		const auto deploymentStartupTimeout = std::chrono::milliseconds(
			std::max(1, config().getInt("deployment.startupTimeoutMilliseconds", 120000)));
		const auto deploymentProbation = std::chrono::milliseconds(
			std::max(0, config().getInt("deployment.probationMilliseconds", 10000)));
		const auto deploymentStopTimeout = std::chrono::milliseconds(
			std::max(1, config().getInt("deployment.stopTimeoutMilliseconds", 30000)));
		std::deque<std::chrono::steady_clock::time_point> restarts;
		std::string activationId;
		try
		{
			if (_deploymentCoordinator && _deploymentCoordinator->recoverInterruptedActivation())
				logger().warning("Recovered an interrupted Bundle activation before launching the child.");
		}
		catch (Poco::Exception& recoveryError)
		{
			logger().fatal("Cannot recover interrupted Bundle activation: %s",
				recoveryError.displayText());
			_restartBudgetExhausted.store(true);
			ServerApplication::terminate();
			return;
		}
		while (!_stopped.load())
		{
			bool plannedDeploymentStop = false;
			const bool candidateLaunch = !activationId.empty();
			bool childLaunched = false;
			bool preflightCompleted = false;
			bool fatalDeploymentConflict = false;
			int rc = -1;
			try
			{
				runPreflightChecks();
				preflightCompleted = true;
				logger().information(format("Launching %s...", _command));
				Poco::ProcessHandle ph = launchChild();
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
				childLaunched = true;
				logger().information(format("Launched %s (%?d).", _command, ph.id()));

				const auto launchedAt = std::chrono::steady_clock::now();
				auto readySince = std::chrono::steady_clock::time_point{};
				auto stopRequestedAt = std::chrono::steady_clock::time_point{};
				while (!_stopped.load() && (rc = ph.tryWait()) == -1)
				{
					const auto now = std::chrono::steady_clock::now();
					if (_deploymentCoordinator)
					{
						if (candidateLaunch && !activationId.empty())
						{
							if (_deploymentCoordinator->activationReady(activationId) &&
								deploymentReadinessHealthy(activationId))
							{
								if (readySince == std::chrono::steady_clock::time_point{})
								{
									readySince = now;
									logger().information(
										"Bundle deployment %s entered readiness probation.", activationId);
								}
								if (now - readySince >= deploymentProbation)
								{
									_deploymentCoordinator->commit(activationId);
									logger().information("Bundle deployment %s committed.", activationId);
									activationId.clear();
								}
							}
							else readySince = std::chrono::steady_clock::time_point{};

							if (!activationId.empty() && now - launchedAt >= deploymentStartupTimeout)
							{
								logger().error("Bundle deployment %s failed its startup/readiness gate.",
									activationId);
								Poco::Process::kill(ph);
							}
						}
						else if (activationId.empty() && _deploymentCoordinator->activationRequested())
						{
							try
							{
								activationId = _deploymentCoordinator->beginActivation();
							}
							catch (Poco::FileAccessDeniedException& leaseError)
							{
								fatalDeploymentConflict = true;
								logger().fatal(
									"Another Launcher owns the Bundle deployment lease: %s",
									leaseError.displayText());
								Poco::Process::kill(ph);
								throw;
							}
							catch (Poco::Exception& rejected)
							{
								logger().error(
									"Bundle deployment candidate rejected; current child remains active: %s",
									rejected.displayText());
								continue;
							}
							plannedDeploymentStop = true;
							stopRequestedAt = now;
							logger().information(
								"Stopping child for Bundle deployment transaction %s.", activationId);
							try { Poco::Process::requestTermination(ph.id()); }
							catch (Poco::Exception& stopError)
							{
								logger().warning("Graceful deployment stop failed, forcing child stop: %s",
									stopError.displayText());
								Poco::Process::kill(ph);
							}
						}
						else if (plannedDeploymentStop &&
							 now - stopRequestedAt >= deploymentStopTimeout)
						{
							logger().warning("Force-stopping child at the Bundle deployment boundary.");
							Poco::Process::kill(ph);
						}
					}
					Poco::Thread::sleep(static_cast<long>(deploymentPoll.count()));
				}
				if (rc == -1)
					rc = ph.wait();
				logger().information(format("%s exited with status %d.", _command, rc));
				_pid.store(0);
				_launchedAtMicroseconds.store(0);
			}
			catch (Poco::Exception& exc)
			{
				const bool childStopped =
					!childLaunched || ensureDeploymentChildStopped(deploymentStopTimeout);
				if (plannedDeploymentStop && childStopped)
					logger().information("Child stopped at the planned Bundle deployment boundary.");
				else if (candidateLaunch && !activationId.empty() && childStopped)
					logger().error("Candidate child stopped before Bundle deployment commit.");
				else
					logger().log(exc);
				if (!childStopped)
				{
					logger().fatal("Cannot prove supervised child stopped after launcher failure; "
						"refusing Bundle repository rollback or relaunch.");
					_restartBudgetExhausted.store(true);
					ServerApplication::terminate();
					break;
				}
			}
			if (!_stopped.load())
			{
				if (!preflightCompleted && !candidateLaunch)
				{
					logger().fatal(
						"Child preflight failed; refusing initial launch or crash-loop retry.");
					_restartBudgetExhausted.store(true);
					ServerApplication::terminate();
					break;
				}
				if (fatalDeploymentConflict)
				{
					_restartBudgetExhausted.store(true);
					ServerApplication::terminate();
					break;
				}
				if (plannedDeploymentStop)
				{
					logger().information("Launching the preflighted Bundle deployment candidate.");
					continue;
				}
				if (candidateLaunch && !activationId.empty())
				{
					const std::string failedActivation = activationId;
					try
					{
						_deploymentCoordinator->rollback(
							failedActivation,
							childLaunched ? "candidate child exited before deployment commit"
							              : "candidate child could not be launched");
						logger().error("Bundle deployment %s rolled back; relaunching last-known-good.",
							failedActivation);
						activationId.clear();
						continue;
					}
					catch (Poco::Exception& rollbackError)
					{
						logger().fatal("Bundle deployment %s rollback failed: %s",
							failedActivation, rollbackError.displayText());
						_restartBudgetExhausted.store(true);
						ServerApplication::terminate();
						break;
					}
				}
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
		_childWorkingDirectory = config().getString("childWorkingDirectory", "");
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
			options.stateDirectory = config().getString(
				"osp.bundleMonitor.stateDirectory",
				config().expand("${application.dir}data/bundle-manager/"));
			options.intervalMilliseconds =
				config().getInt64("osp.bundleMonitor.intervalMilliseconds", 1000);
			options.stableScanCount = static_cast<std::size_t>(
				std::max(2, config().getInt("osp.bundleMonitor.stableScanCount", 2)));
			options.inProcessReloadEnabled =
				config().getBool("osp.bundleMonitor.inProcessReloadEnabled", false);
			options.authorization.required =
				config().getBool("osp.bundleMonitor.authorization.required", false);
			options.authorization.repositoryId =
				config().getString("osp.bundleMonitor.authorization.repositoryId", "");
			options.authorization.evidenceDirectory =
				config().getString("osp.bundleMonitor.authorization.evidenceDirectory", "");
			options.authorization.trustPolicyFile =
				config().getString("osp.bundleMonitor.authorization.trustPolicyFile", "");
			options.authorization.expectedTrustPolicyId =
				config().getString("osp.bundleMonitor.authorization.expectedTrustPolicyId", "");
			options.authorization.expectedTrustPolicySha256 =
				config().getString("osp.bundleMonitor.authorization.expectedTrustPolicySha256", "");
			options.authorization.trustedKeysDirectory =
				config().getString("osp.bundleMonitor.authorization.trustedKeysDirectory", "");
			_bundleManager = std::make_unique<PocoDDS::BundleManagement::BundleManager>(
				*_osp, logger(), std::move(options));
			_bundleManager->start();
		}

		if (config().getBool("deployment.enabled", false))
		{
			PocoDDS::BundleManagement::BundleDeploymentOptions options;
			options.repositoryDirectory = config().getString("deployment.repository");
			options.stateDirectory = config().getString("deployment.stateDirectory");
			options.authorization.required =
				config().getBool("deployment.authorization.required", false);
			options.authorization.repositoryId =
				config().getString("deployment.authorization.repositoryId", "");
			options.authorization.evidenceDirectory =
				config().getString("deployment.authorization.evidenceDirectory", "");
			options.authorization.trustPolicyFile =
				config().getString("deployment.authorization.trustPolicyFile", "");
			options.authorization.expectedTrustPolicyId =
				config().getString("deployment.authorization.expectedTrustPolicyId", "");
			options.authorization.expectedTrustPolicySha256 =
				config().getString("deployment.authorization.expectedTrustPolicySha256", "");
			options.authorization.trustedKeysDirectory =
				config().getString("deployment.authorization.trustedKeysDirectory", "");
			_deploymentCoordinator =
				std::make_unique<PocoDDS::BundleManagement::BundleDeploymentCoordinator>(
					std::move(options));
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
	struct PreflightStep
	{
		std::string name;
		std::string executable;
		Poco::Process::Args arguments;
		std::string workingDirectory;
		std::chrono::milliseconds timeout{10000};
	};

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
		requireAtLeast("deployment.pollMilliseconds", 50, 250);
		requireAtLeast("deployment.startupTimeoutMilliseconds", 1, 120000);
		requireAtLeast("deployment.probationMilliseconds", 0, 10000);
		requireAtLeast("deployment.stopTimeoutMilliseconds", 1, 30000);
		const std::string heartbeat = config().getString("watchdog.file", "");
		if (config().getBool("watchdog.requireFile", false) && heartbeat.empty())
			throw Poco::InvalidArgumentException(
				"watchdog.file is required when watchdog.requireFile is true");
		if (!heartbeat.empty())
		{
			const Poco::Path heartbeatPath(heartbeat);
			(void) heartbeatPath; // Validate syntax before starting the supervised child.
		}
		if (!_childWorkingDirectory.empty())
		{
			Poco::File directory(_childWorkingDirectory);
			if (!directory.exists() || !directory.isDirectory())
				throw Poco::InvalidArgumentException(
					"childWorkingDirectory must be an existing directory",
					_childWorkingDirectory);
		}
		configureChildEnvironment();
		configurePreflightChecks();
	}

	void configureChildEnvironment()
	{
		_childEnvironment.clear();
		const int count = config().getInt("childEnvironment.count", 0);
		if (count < 0 || count > 64)
			throw Poco::InvalidArgumentException(
				"childEnvironment.count must be in range 0..64");
		if (count == 0)
			return;
		_childEnvironment = currentEnvironment();
		std::vector<std::string> configuredNames;
		configuredNames.reserve(static_cast<std::size_t>(count));
		for (int index = 0; index < count; ++index)
		{
			const std::string prefix = "childEnvironment." + std::to_string(index) + ".";
			const std::string name = config().getString(prefix + "name", "");
			if (name.empty() || name.size() > 128 || name.find('=') != std::string::npos)
				throw Poco::InvalidArgumentException(
					prefix + "name must contain 1..128 characters and no '='");
			const auto sameName = [&name](const std::string& existing)
			{
#if defined(POCO_OS_FAMILY_WINDOWS)
				return std::equal(existing.begin(), existing.end(), name.begin(), name.end(),
					[](unsigned char left, unsigned char right)
					{ return std::tolower(left) == std::tolower(right); });
#else
				return existing == name;
#endif
			};
			if (std::find_if(configuredNames.begin(), configuredNames.end(), sameName) !=
				configuredNames.end())
				throw Poco::InvalidArgumentException(
					"duplicate childEnvironment variable: " + name);
			configuredNames.push_back(name);
			const std::string value = config().expand(config().getString(prefix + "value", ""));
			if (value.size() > 32768)
				throw Poco::InvalidArgumentException(
					prefix + "value exceeds 32768 characters");
#if defined(POCO_OS_FAMILY_WINDOWS)
			const auto inherited = std::find_if(
				_childEnvironment.begin(), _childEnvironment.end(),
				[&sameName](const auto& item) { return sameName(item.first); });
			if (inherited != _childEnvironment.end()) _childEnvironment.erase(inherited);
#endif
			_childEnvironment[name] = value;
		}
	}

	static Poco::Process::Env currentEnvironment()
	{
		Poco::Process::Env result;
#if defined(POCO_OS_FAMILY_WINDOWS)
		wchar_t* block = GetEnvironmentStringsW();
		if (!block)
			throw Poco::SystemException("GetEnvironmentStringsW failed", GetLastError());
		const std::unique_ptr<wchar_t, decltype(&FreeEnvironmentStringsW)>
			environmentBlock(block, &FreeEnvironmentStringsW);
		for (const wchar_t* entry = block; *entry; entry += std::wcslen(entry) + 1)
		{
			const std::wstring item(entry);
			const auto separator = item.find(L'=', item.front() == L'=' ? 1 : 0);
			if (separator == std::wstring::npos) continue;
			std::string name;
			std::string value;
			Poco::UnicodeConverter::toUTF8(item.substr(0, separator), name);
			Poco::UnicodeConverter::toUTF8(item.substr(separator + 1), value);
			result[std::move(name)] = std::move(value);
		}
#else
		for (char** entry = environ; entry && *entry; ++entry)
		{
			const std::string item(*entry);
			const auto separator = item.find('=');
			if (separator != std::string::npos)
				result[item.substr(0, separator)] = item.substr(separator + 1);
		}
#endif
		return result;
	}

	void configurePreflightChecks()
	{
		_preflightSteps.clear();
		const int count = config().getInt("preflight.count", 0);
		if (count < 0 || count > 16)
			throw Poco::InvalidArgumentException("preflight.count must be in range 0..16");
		_preflightSteps.reserve(static_cast<std::size_t>(count));
		for (int index = 0; index < count; ++index)
		{
			const std::string prefix = "preflight." + std::to_string(index) + ".";
			PreflightStep step;
			step.name = config().getString(prefix + "name", "preflight-" + std::to_string(index));
			if (step.name.empty())
				throw Poco::InvalidArgumentException(prefix + "name cannot be empty");
			step.executable = config().expand(config().getString(prefix + "executable", ""));
			if (step.executable.empty())
				throw Poco::InvalidArgumentException(prefix + "executable is required");
			const Poco::Path executablePath(step.executable);
			const Poco::File executableFile(step.executable);
			if (!executablePath.isAbsolute() || !executableFile.exists() ||
				!executableFile.isFile() || !executableFile.canExecute())
				throw Poco::InvalidArgumentException(
					prefix + "executable must be an existing executable absolute file");

			const int argumentCount = config().getInt(prefix + "argument.count", 0);
			if (argumentCount < 0 || argumentCount > 64)
				throw Poco::InvalidArgumentException(
					prefix + "argument.count must be in range 0..64");
			for (int argument = 0; argument < argumentCount; ++argument)
				step.arguments.push_back(config().expand(config().getString(
					prefix + "argument." + std::to_string(argument))));

			step.workingDirectory = config().expand(
				config().getString(prefix + "workingDirectory", ""));
			if (!step.workingDirectory.empty())
			{
				const Poco::Path directoryPath(step.workingDirectory);
				const Poco::File directory(step.workingDirectory);
				if (!directoryPath.isAbsolute() || !directory.exists() || !directory.isDirectory())
					throw Poco::InvalidArgumentException(
						prefix + "workingDirectory must be an existing absolute directory");
			}

			const int timeout = config().getInt(prefix + "timeoutMilliseconds", 10000);
			if (timeout < 1 || timeout > 300000)
				throw Poco::InvalidArgumentException(
					prefix + "timeoutMilliseconds must be in range 1..300000");
			step.timeout = std::chrono::milliseconds(timeout);
			_preflightSteps.push_back(std::move(step));
		}
	}

	void runPreflightChecks()
	{
		for (const auto& step : _preflightSteps)
		{
			logger().information("Running child preflight: %s", step.name);
			Poco::ProcessHandle process = _childEnvironment.empty()
				? (step.workingDirectory.empty()
					? Poco::Process::launch(step.executable, step.arguments)
					: Poco::Process::launch(
						step.executable, step.arguments, step.workingDirectory))
				: Poco::Process::launch(
					step.executable, step.arguments, step.workingDirectory,
					nullptr, nullptr, nullptr, _childEnvironment);
			const auto deadline = std::chrono::steady_clock::now() + step.timeout;
			int result = -1;
			while (!_stopped.load() && (result = process.tryWait()) == -1 &&
				std::chrono::steady_clock::now() < deadline)
				Poco::Thread::sleep(10);
			if (result == -1)
			{
				if (Poco::Process::isRunning(process)) Poco::Process::kill(process);
				if (_stopped.load())
					throw Poco::ApplicationException(
						"child preflight cancelled during Launcher shutdown", step.name);
				throw Poco::TimeoutException("child preflight timed out", step.name);
			}
			if (result != 0)
				throw Poco::ApplicationException(
					format("child preflight %s exited with status %d", step.name, result));
			logger().information("Child preflight passed: %s", step.name);
		}
	}

	Poco::ProcessHandle launchChild() const
	{
		if (_childEnvironment.empty())
			return _childWorkingDirectory.empty()
				? Poco::Process::launch(_command, _args)
				: Poco::Process::launch(_command, _args, _childWorkingDirectory);
		return Poco::Process::launch(
			_command, _args, _childWorkingDirectory,
			nullptr, nullptr, nullptr, _childEnvironment);
	}

	bool deploymentReadinessHealthy(const std::string& transactionId) const
	{
		const std::string path = config().getString("deployment.readiness.file", "");
		if (path.empty())
			return true;
		Poco::File file(path);
		if (!file.exists() || !file.isFile())
			return false;
		if (file.getLastModified().epochMicroseconds() < _launchedAtMicroseconds.load())
			return false;
		if (!config().getBool("deployment.readiness.requireTransactionId", false))
			return true;
		Poco::FileInputStream stream(path);
		std::string content((std::istreambuf_iterator<char>(stream)),
			std::istreambuf_iterator<char>());
		return content.find(transactionId) != std::string::npos;
	}

	bool ensureDeploymentChildStopped(std::chrono::milliseconds timeout)
	{
		const auto pid = _pid.load();
		if (pid == 0)
			return true;
		try
		{
			if (Poco::Process::isRunning(pid))
				Poco::Process::kill(pid);
			const auto deadline = std::chrono::steady_clock::now() + timeout;
			while (Poco::Process::isRunning(pid) && std::chrono::steady_clock::now() < deadline)
				Poco::Thread::sleep(25);
			if (Poco::Process::isRunning(pid))
				return false;
			_pid.store(0);
			_launchedAtMicroseconds.store(0);
			return true;
		}
		catch (Poco::Exception& stopError)
		{
			logger().error("Cannot stop supervised child at deployment boundary: %s",
				stopError.displayText());
			return false;
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
	std::unique_ptr<PocoDDS::BundleManagement::BundleDeploymentCoordinator>
		_deploymentCoordinator;
	bool _helpRequested;
	bool _explicitConfigRequested;
	std::string _command;
	std::vector<std::string> _args;
	std::string _childWorkingDirectory;
	Poco::Process::Env _childEnvironment;
	std::vector<PreflightStep> _preflightSteps;
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

