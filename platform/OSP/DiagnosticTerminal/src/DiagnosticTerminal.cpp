#include "PocoDDS/DiagnosticTerminal/DiagnosticProvider.h"
#include "PocoDDS/Configuration/ConfigurationValidator.h"
#include "PocoDDS/Devices/DeviceService.h"
#include "PocoDDS/DDS/Runtime.h"
#include "PocoDDS/Health/Health.h"
#include "PocoDDS/ManagementAuth/IdentityService.h"
#include "PocoDDS/Observability/Metrics.h"
#include "PocoDDS/Observability/TraceStore.h"
#include "PocoDDS/ProcessManagement/SubprocessManager.h"
#include "PocoDDS/Protocols/ProtocolService.h"

#include "Poco/AutoPtr.h"
#include "Poco/ClassLibrary.h"
#include "Poco/Environment.h"
#include "Poco/Exception.h"
#include "Poco/File.h"
#include "Poco/FileStream.h"
#include "Poco/JSON/Array.h"
#include "Poco/JSON/Object.h"
#include "Poco/JSON/Parser.h"
#include "Poco/Net/HTTPRequest.h"
#include "Poco/Net/HTTPResponse.h"
#include "Poco/Net/HTTPServerRequest.h"
#include "Poco/Net/HTTPServerResponse.h"
#include "Poco/Net/HTTPRequestHandler.h"
#include "Poco/NumberFormatter.h"
#include "Poco/OSP/Bundle.h"
#include "Poco/OSP/BundleActivator.h"
#include "Poco/OSP/BundleContext.h"
#include "Poco/OSP/Properties.h"
#include "Poco/OSP/PreferencesService.h"
#include "Poco/OSP/Service.h"
#include "Poco/OSP/ServiceRef.h"
#include "Poco/OSP/ServiceRegistry.h"
#include "Poco/OSP/Web/WebRequestHandlerFactory.h"
#include "Poco/Path.h"
#include "Poco/Pipe.h"
#include "Poco/PipeStream.h"
#include "Poco/Process.h"
#include "Poco/Timestamp.h"
#include "Poco/Thread.h"
#include "Poco/URI.h"

#include <algorithm>
#include <atomic>
#include <cctype>
#include <deque>
#include <fstream>
#include <iomanip>
#include <iterator>
#include <map>
#include <mutex>
#include <set>
#include <sstream>
#include <string>
#include <vector>

#ifndef PDR_RUNTIME_VERSION
#define PDR_RUNTIME_VERSION "unknown"
#endif

namespace PocoDDS::DiagnosticTerminal
{
namespace
{
constexpr const char* SERVICE_NAME = "pdr.diagnostics.terminal";
constexpr const char* REQUIRED_PERMISSION = "diagnostics.read";
constexpr const char* EXECUTE_PERMISSION = "diagnostics.execute";

struct CommandResult
{
    int exitCode{0};
    std::vector<std::string> lines;
    std::vector<Finding> findings;
    std::map<std::string, std::string> facts;
};

Poco::JSON::Object::Ptr findingJson(const Finding& finding)
{
    Poco::JSON::Object::Ptr object = new Poco::JSON::Object;
    object->set("code", finding.code);
    object->set("severity", severityName(finding.severity));
    object->set("scope", finding.scope);
    object->set("target", finding.target);
    object->set("summary", finding.summary);
    object->set("detail", finding.detail);
    object->set("remediation", finding.remediation);
    object->set("confidence", finding.confidence);
    if (!finding.traceId.empty()) object->set("traceId", finding.traceId);
    Poco::JSON::Array::Ptr evidence = new Poco::JSON::Array;
    for (const auto& item : finding.evidence)
    {
        Poco::JSON::Object::Ptr entry = new Poco::JSON::Object;
        entry->set("source", item.source);
        entry->set("message", item.message);
        Poco::JSON::Object::Ptr attributes = new Poco::JSON::Object;
        for (const auto& [name, value] : item.attributes) attributes->set(name, value);
        entry->set("attributes", attributes);
        evidence->add(entry);
    }
    object->set("evidence", evidence);
    return object;
}

void appendFinding(CommandResult& result, Finding finding)
{
    std::ostringstream first;
    first << '[' << severityName(finding.severity) << "] " << finding.code;
    if (!finding.target.empty()) first << "  " << finding.target;
    result.lines.push_back(first.str());
    if (!finding.summary.empty()) result.lines.push_back("  结论: " + finding.summary);
    if (!finding.detail.empty()) result.lines.push_back("  证据: " + finding.detail);
    if (!finding.remediation.empty()) result.lines.push_back("  建议: " + finding.remediation);
    if (!finding.traceId.empty()) result.lines.push_back("  Trace: " + finding.traceId);
    if (finding.severity == Severity::error || finding.severity == Severity::critical)
        result.exitCode = 1;
    result.findings.push_back(std::move(finding));
}

std::string lower(std::string value)
{
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) {
        return static_cast<char>(std::tolower(ch));
    });
    return value;
}

bool containsInsensitive(const std::string& value, const std::string& query)
{
    return query.empty() || lower(value).find(lower(query)) != std::string::npos;
}

std::vector<std::string> tokenize(const std::string& command)
{
    std::vector<std::string> tokens;
    std::string token;
    char quote = 0;
    bool escaped = false;
    for (const char ch : command)
    {
        if (escaped)
        {
            token += ch;
            escaped = false;
        }
        else if (ch == '\\' && quote != '\'')
            escaped = true;
        else if (quote)
        {
            if (ch == quote) quote = 0;
            else token += ch;
        }
        else if (ch == '\'' || ch == '"')
            quote = ch;
        else if (std::isspace(static_cast<unsigned char>(ch)))
        {
            if (!token.empty())
            {
                tokens.push_back(token);
                token.clear();
            }
        }
        else token += ch;
    }
    if (escaped) token += '\\';
    if (quote) throw Poco::SyntaxException("命令中的引号未闭合");
    if (!token.empty()) tokens.push_back(token);
    return tokens;
}

std::string tableRow(const std::vector<std::string>& values,
                     const std::vector<std::size_t>& widths)
{
    std::ostringstream output;
    for (std::size_t index = 0; index < values.size(); ++index)
    {
        if (index) output << "  ";
        if (index + 1 == values.size()) output << values[index];
        else output << std::left << std::setw(static_cast<int>(widths[index])) << values[index];
    }
    return output.str();
}

std::string safeLogName(const std::string& value)
{
    std::string result;
    for (const char ch : value)
    {
        const auto byte = static_cast<unsigned char>(ch);
        if (std::isalnum(byte) || ch == '.' || ch == '_' || ch == '-') result += ch;
    }
    if (result.size() > 4 && lower(result.substr(result.size() - 4)) == ".exe")
        result.resize(result.size() - 4);
    return result;
}

bool sensitiveConfigurationKey(const std::string& key)
{
    const std::string normalized = lower(key);
    for (const char* fragment : {"password", "passwd", "secret", "token",
                                 "authorization", "cookie", "privatekey", "private.key"})
        if (normalized.find(fragment) != std::string::npos) return true;
    return false;
}

std::string redactedConfigurationValue(const std::string& key, const std::string& value)
{
    return sensitiveConfigurationKey(key) && !value.empty() ? "[REDACTED]" : value;
}

std::string redactedLogLine(const std::string& value)
{
    const std::string normalized = lower(value);
    for (const char* fragment : {"authorization", "bearer ", "password", "passwd",
                                 "secret", "token=", "cookie", "privatekey"})
        if (normalized.find(fragment) != std::string::npos)
            return "[REDACTED SENSITIVE LOG LINE]";
    return value;
}

void collectConfiguration(const Poco::Util::AbstractConfiguration& configuration,
                          const std::string& prefix,
                          std::map<std::string, std::string>& values)
{
    Poco::Util::AbstractConfiguration::Keys keys;
    if (prefix.empty()) configuration.keys(keys);
    else configuration.keys(prefix, keys);
    for (const auto& key : keys)
    {
        const std::string full = prefix.empty() ? key : prefix + "." + key;
        if (configuration.hasProperty(full))
            values[full] = redactedConfigurationValue(
                full, configuration.getRawString(full, ""));
        collectConfiguration(configuration, full, values);
    }
}

void sendJsonError(Poco::Net::HTTPServerResponse& response,
                   Poco::Net::HTTPResponse::HTTPStatus status,
                   const std::string& message)
{
    Poco::JSON::Object body;
    body.set("error", message);
    response.setStatus(status);
    response.setContentType("application/json; charset=utf-8");
    response.set("Cache-Control", "no-store");
    body.stringify(response.send());
}

class RuntimeDiagnosticProvider final : public DiagnosticProvider
{
public:
    explicit RuntimeDiagnosticProvider(Poco::OSP::BundleContext::Ptr context):
        _context(std::move(context))
    {
    }

    std::string providerId() const override { return "pdr.runtime.core"; }
    std::vector<std::string> scopes() const override
    {
        return {"protocol", "device", "metrics", "trace", "dds"};
    }

    Snapshot diagnose(const Query& query) const override
    {
        Snapshot snapshot;
        snapshot.provider = providerId();
        snapshot.scope = query.scope;
        snapshot.target = query.target;
        const auto wants = [&](const std::string& scope) {
            return query.scope.empty() || query.scope == "all" || query.scope == scope;
        };
        if (wants("protocol")) diagnoseProtocols(query, snapshot);
        if (wants("device")) diagnoseDevices(query, snapshot);
        if (wants("metrics")) diagnoseMetrics(query, snapshot);
        if (wants("trace")) diagnoseTraces(query, snapshot);
        if (wants("dds")) diagnoseDds(query, snapshot);
        return snapshot;
    }

private:
    static bool selected(const Query& query, const std::string& target)
    {
        return query.target.empty() || containsInsensitive(target, query.target);
    }

    void diagnoseProtocols(const Query& query, Snapshot& snapshot) const
    {
        const auto services = _context->registry().find("pdr.protocol");
        std::size_t open = 0;
        std::size_t checked = 0;
        for (const auto& reference : services)
        {
            const auto& properties = reference->properties();
            const std::string id = properties.get("pdr.protocol.id", reference->name());
            if (!selected(query, id)) continue;
            ++checked;
            const bool required = properties.getBool("pdr.protocol.required", false);
            try
            {
                const auto provider = reference->castedInstance<PocoDDS::Protocols::ProtocolService>();
                const bool isOpen = provider->isOpen();
                if (isOpen) ++open;
                const auto diagnostics = provider->diagnostics();
                const auto failure = provider->failure();
                if (!isOpen && (required || provider->desiredOpen()))
                {
                    Finding finding;
                    finding.code = failure.code.empty() ?
                        "PDR-DIAG-PROTOCOL-CLOSED" : failure.code;
                    finding.severity = required ? Severity::error : Severity::warning;
                    finding.scope = "protocol";
                    finding.target = id;
                    finding.summary = required ? "必需协议未打开" : "协议期望打开但当前关闭";
                    finding.detail = failure.message.empty() ? diagnostics.lastError : failure.message;
                    finding.remediation = "执行 protocol show " + id +
                        "，核对端点、凭据、网络和自动重连状态。";
                    finding.evidence.push_back({"ProtocolService", "protocol snapshot",
                        {{"required", required ? "true" : "false"},
                         {"desiredOpen", provider->desiredOpen() ? "true" : "false"},
                         {"failedOperations", Poco::NumberFormatter::format(
                             diagnostics.failedOperations)},
                         {"reconnectAttempts", Poco::NumberFormatter::format(
                             diagnostics.reconnectAttempts)}}});
                    snapshot.findings.push_back(std::move(finding));
                }
                else if (query.deep && diagnostics.timeouts > 0)
                {
                    snapshot.findings.push_back(Finding{
                        "PDR-DIAG-PROTOCOL-TIMEOUTS", Severity::warning, "protocol", id,
                        "协议出现过超时", "timeouts=" +
                            Poco::NumberFormatter::format(diagnostics.timeouts),
                        "结合 trace 与日志确认超时是否持续发生。"});
                }
            }
            catch (const std::exception& exception)
            {
                snapshot.findings.push_back(Finding{
                    "PDR-DIAG-PROTOCOL-SNAPSHOT-FAILED", Severity::error, "protocol", id,
                    "无法读取协议诊断快照", exception.what(),
                    "检查 ProtocolService 类型、Bundle ABI 和并发状态。"});
            }
        }
        snapshot.facts["protocols.checked"] = Poco::NumberFormatter::format(checked);
        snapshot.facts["protocols.open"] = Poco::NumberFormatter::format(open);
    }

    void diagnoseDevices(const Query& query, Snapshot& snapshot) const
    {
        const auto services = _context->registry().find("pdr.device");
        std::size_t ready = 0;
        std::size_t checked = 0;
        for (const auto& reference : services)
        {
            const auto& properties = reference->properties();
            const std::string id = properties.get("pdr.device", reference->name());
            if (!selected(query, id)) continue;
            ++checked;
            const bool required = properties.getBool("pdr.deviceRequired", true);
            try
            {
                const auto provider = reference->castedInstance<PocoDDS::Devices::DeviceService>();
                const auto state = provider->device().snapshot().state;
                if (state == PocoDDS::Devices::DeviceState::ready) ++ready;
                if (state != PocoDDS::Devices::DeviceState::ready && required)
                {
                    std::string detail = std::string("state=") + PocoDDS::Devices::toString(state);
                    if (const auto* diagnostic = dynamic_cast<const PocoDDS::Devices::DiagnosticDevice*>(
                            &provider->device()))
                    {
                        const auto values = diagnostic->diagnostics();
                        if (!values.lastError.empty()) detail += ", lastError=" + values.lastError;
                        detail += ", consecutiveFailures=" +
                            Poco::NumberFormatter::format(values.consecutiveFailures);
                    }
                    snapshot.findings.push_back(Finding{
                        "PDR-DIAG-DEVICE-NOT-READY", Severity::error, "device", id,
                        "必需设备未就绪", detail,
                        "执行 device show " + id + "，检查传输、布线、供电和设备日志。"});
                }
            }
            catch (const std::exception& exception)
            {
                snapshot.findings.push_back(Finding{
                    "PDR-DIAG-DEVICE-SNAPSHOT-FAILED", Severity::error, "device", id,
                    "无法读取设备诊断快照", exception.what(),
                    "检查 DeviceService 类型和设备驱动状态。"});
            }
        }
        snapshot.facts["devices.checked"] = Poco::NumberFormatter::format(checked);
        snapshot.facts["devices.ready"] = Poco::NumberFormatter::format(ready);
    }

    void diagnoseMetrics(const Query& query, Snapshot& snapshot) const
    {
        const auto points = PocoDDS::Observability::Metrics::global().snapshot();
        snapshot.facts["metrics.series"] = Poco::NumberFormatter::format(points.size());
        if (!query.deep) return;
        for (const auto& point : points)
        {
            if (!selected(query, point.name)) continue;
            const double observed = point.kind == PocoDDS::Observability::MetricKind::histogram ?
                point.maximum : point.value;
            double threshold = 0.0;
            if (point.name == "system.cpu.utilization" ||
                point.name == "system.memory.utilization" ||
                point.name == "system.filesystem.utilization") threshold = 0.90;
            if (threshold > 0.0 && observed >= threshold)
            {
                snapshot.findings.push_back(Finding{
                    "PDR-DIAG-RESOURCE-HIGH", observed >= 0.97 ? Severity::error : Severity::warning,
                    "metrics", point.name, "资源利用率超过诊断阈值",
                    "observed=" + Poco::NumberFormatter::format(observed) +
                        ", threshold=" + Poco::NumberFormatter::format(threshold),
                    "执行 metrics top，并结合进程资源和最近日志定位持续高占用来源。"});
            }
        }
    }

    void diagnoseTraces(const Query& query, Snapshot& snapshot) const
    {
        const auto traces = PocoDDS::Observability::globalTraceStore().recent(100);
        std::size_t failed = 0;
        for (const auto& trace : traces)
        {
            if (!selected(query, trace.traceId + " " + trace.businessName)) continue;
            if (query.sinceMicroseconds > 0 &&
                trace.startedUnixMicroseconds < query.sinceMicroseconds) continue;
            if (lower(trace.status) != "failed") continue;
            ++failed;
            if (snapshot.findings.size() >= 50) continue;
            Finding finding{
                "PDR-DIAG-TRACE-FAILED", Severity::warning, "trace", trace.businessName,
                "最近业务 Trace 执行失败",
                "instance=" + trace.businessInstanceId + ", failedOperation=" +
                    trace.failedOperation,
                "执行 trace show " + trace.traceId + " 并按 Trace ID 过滤日志。"};
            finding.traceId = trace.traceId;
            snapshot.findings.push_back(std::move(finding));
        }
        snapshot.facts["traces.recent"] = Poco::NumberFormatter::format(traces.size());
        snapshot.facts["traces.failed"] = Poco::NumberFormatter::format(failed);
    }

    void diagnoseDds(const Query& query, Snapshot& snapshot) const
    {
        const auto runtimes = PocoDDS::FastDDS::Runtime::snapshots();
        snapshot.facts["dds.localParticipants"] = Poco::NumberFormatter::format(runtimes.size());
        std::size_t active = 0;
        for (const auto& runtime : runtimes)
        {
            if (!selected(query, runtime.participantName)) continue;
            if (runtime.started) ++active;
            else snapshot.findings.push_back(Finding{
                "PDR-DIAG-DDS-PARTICIPANT-STOPPED", Severity::warning, "dds",
                runtime.participantName, "Fast DDS Participant 尚未启动",
                "domain=" + Poco::NumberFormatter::format(runtime.domainId),
                "检查 DDS owner 的生命周期和启动日志。"});
        }
        snapshot.facts["dds.activeParticipants"] = Poco::NumberFormatter::format(active);
        std::uint64_t publishErrors = 0;
        std::uint64_t handlerErrors = 0;
        for (const auto& point : PocoDDS::Observability::Metrics::global().snapshot())
        {
            if (point.name == "pdr.dds.publish.errors")
                publishErrors += static_cast<std::uint64_t>(point.value);
            else if (point.name == "pdr.dds.handler.errors")
                handlerErrors += static_cast<std::uint64_t>(point.value);
        }
        snapshot.facts["dds.publishErrors"] = Poco::NumberFormatter::format(publishErrors);
        snapshot.facts["dds.handlerErrors"] = Poco::NumberFormatter::format(handlerErrors);
        if (publishErrors || handlerErrors)
            snapshot.findings.push_back(Finding{
                "PDR-DIAG-DDS-ERRORS", publishErrors ? Severity::error : Severity::warning,
                "dds", "runtime", "Fast DDS 数据面报告错误",
                "publishErrors=" + Poco::NumberFormatter::format(publishErrors) +
                    ", handlerErrors=" + Poco::NumberFormatter::format(handlerErrors),
                "执行 metrics top pdr.dds、trace list DDS，并跟踪 DDS owner 进程日志。"});
        if (runtimes.empty())
            snapshot.findings.push_back(Finding{
                "PDR-DIAG-DDS-OUT-OF-PROCESS", Severity::info, "dds", "runtime",
                "当前 Runtime 进程内没有 Fast DDS Participant",
                "DDS 可能由托管子进程持有；进程隔离后无法安全读取其内存对象。",
                "执行 ps、agent status <进程>、trace list DDS 和 logs <进程> --follow。"});
    }

    Poco::OSP::BundleContext::Ptr _context;
};

class TerminalService final : public Poco::OSP::Service
{
public:
    explicit TerminalService(Poco::OSP::BundleContext::Ptr context):
        _context(std::move(context))
    {
        _initialConfiguration = configurationSnapshot();
    }

    CommandResult execute(const std::string& command, const std::string& principal) const
    {
        auto tokens = tokenize(command);
        for (auto iterator = tokens.begin(); iterator != tokens.end();)
        {
            if (*iterator == "--format=json" || *iterator == "--format=table")
                iterator = tokens.erase(iterator);
            else if (*iterator == "--format" && iterator + 1 != tokens.end() &&
                     (lower(*(iterator + 1)) == "json" || lower(*(iterator + 1)) == "table"))
                iterator = tokens.erase(iterator, iterator + 2);
            else ++iterator;
        }
        if (tokens.empty()) return {};
        const std::string verb = lower(tokens[0]);
        if (verb == "help" || verb == "man") return help(tokens);
        if (verb == "status") return status();
        if (verb == "health") return health(tokens);
        if (verb == "ps" || verb == "processes") return processes(tokens);
        if (verb == "bundle" || verb == "bundles") return bundles(tokens);
        if (verb == "service" || verb == "services") return services(tokens);
        if (verb == "logs" || verb == "tail") return logs(tokens);
        if (verb == "diagnose" || verb == "doctor") return diagnose(tokens);
        if (verb == "provider" || verb == "providers") return providers(tokens);
        if (verb == "protocol" || verb == "protocols") return protocols(tokens);
        if (verb == "device" || verb == "devices") return devices(tokens);
        if (verb == "metrics" || verb == "metric") return metrics(tokens);
        if (verb == "trace" || verb == "traces") return traces(tokens);
        if (verb == "dds") return dds(tokens);
        if (verb == "config" || verb == "configuration") return configuration(tokens);
        if (verb == "support") return support(tokens, principal);
        if (verb == "agent") return agent(tokens);
        if (verb == "dump") return captureDump(tokens);
        if (verb == "crash" || verb == "crashes") return crashes(tokens);
        if (verb == "version" || verb == "uname") return version();
        if (verb == "uptime") return uptime();
        if (verb == "whoami") return {0, {principal}};
        return {127, {
            "pdr: command not found: " + tokens[0],
            "输入 'help' 查看可用的受控诊断命令。"
        }};
    }

    const std::type_info& type() const override { return typeid(TerminalService); }
    bool isA(const std::type_info& other) const override
    {
        return std::string(other.name()) == typeid(TerminalService).name() ||
               Poco::OSP::Service::isA(other);
    }

private:
    CommandResult help(const std::vector<std::string>& tokens) const
    {
        if (tokens.size() > 1)
        {
            const std::string command = lower(tokens[1]);
            if (command == "logs" || command == "tail")
                return {0, {"用法: logs [runtime|进程名] [--tail N] [--grep 文本]",
                            "读取已知 Runtime/子进程日志；不会访问任意文件路径。"}};
            if (command == "bundle" || command == "bundles")
                return {0, {"用法: bundle list [过滤词]", "      bundle show <bundle-id>",
                            "      bundle deps|history|quarantine <bundle-id>"}};
            if (command == "service" || command == "services")
                return {0, {"用法: service list [过滤词]", "      service show|check <service-name>",
                            "      service providers|consumers <service-name>"}};
            if (command == "diagnose" || command == "doctor")
                return {0, {"用法: diagnose all", "      diagnose bundle <bundle-id>",
                            "      diagnose service <service-name>",
                            "      diagnose process <进程名或 PID>"}};
            if (command == "provider" || command == "providers")
                return {0, {"用法: provider list", "      provider check <provider-id> [目标]",
                            "模块可通过 pdr.diagnostics.provider Service 扩展统一诊断。"}};
            if (command == "protocol" || command == "protocols")
                return {0, {"用法: protocol list [过滤词]", "      protocol check <id> [--deep]"}};
            if (command == "device" || command == "devices")
                return {0, {"用法: device list [过滤词]", "      device check <id> [--deep]"}};
            if (command == "metrics" || command == "metric")
                return {0, {"用法: metrics top [过滤词]", "      metrics anomalies"}};
            if (command == "trace" || command == "traces")
                return {0, {"用法: trace list [过滤词]", "      trace show <trace-id>"}};
            if (command == "dds")
                return {0, {"用法: dds participants", "      dds discovery", "      dds qos",
                            "      dds check [participant] [--deep]"}};
            if (command == "config" || command == "configuration")
                return {0, {"用法: config effective [前缀]", "      config diff [前缀]",
                            "      config validate", "敏感配置值始终脱敏。"}};
            if (command == "support")
                return {0, {"用法: support collect", "生成脱敏的一键 Runtime 诊断包。"}};
            if (command == "agent")
                return {0, {"用法: agent status|threads|net [进程名或 PID]",
                            "通过独立进程检查 Runtime 或已托管子进程。"}};
            if (command == "dump")
                return {0, {"用法: dump process <进程名或 PID> --confirm",
                            "需要 diagnostics.execute；仅生成受控 MiniDump 诊断文件。"}};
            if (command == "crash" || command == "crashes")
                return {0, {"用法: crash list", "      crash show <dump-id>"}};
        }
        return {0, {
            "PocoDDS Runtime 受控诊断终端",
            "",
            "  status                         Runtime、Bundle、Service、进程概况",
            "  health tree                    深度健康树和稳定错误码",
            "  ps [过滤词]                    查看主进程和托管子进程",
            "  bundle list [过滤词]           列出 Bundle",
            "  bundle show <id>               查看 Bundle 状态与提供的 Service",
            "  bundle deps|history|quarantine 依赖、启动历史和隔离状态",
            "  service list [过滤词]          列出已注册 Service",
            "  service show <name>            查看 Service 所属 Bundle",
            "  service check/providers/consumers 健康、提供者和依赖消费者",
            "  logs [进程] --tail N           查看 Runtime/子进程日志",
            "  logs [进程] --grep <文本>      过滤日志",
            "  diagnose all                   执行综合只读诊断",
            "  diagnose bundle|service|process <目标>",
            "  provider list|check            查看或调用模块诊断 Provider",
            "  protocol list|check            协议状态、失败和重连诊断",
            "  device list|check              设备状态和连续失败诊断",
            "  metrics top|anomalies          指标排序和资源异常检测",
            "  trace list|show                最近业务 Trace 与失败节点",
            "  dds participants|discovery|qos Fast DDS Participant、数据面和 QoS 摘要",
            "  config effective|diff|validate 有效配置、启动差异和规则校验",
            "  support collect                生成可下载的脱敏诊断包",
            "  agent status|threads|net       Runtime 外部进程诊断",
            "  crash list|show                查看受控崩溃转储清单",
            "  dump process <目标> --confirm  通过独立 Agent 采集 MiniDump（需执行权限）",
            "  version | uptime | whoami      查看运行环境与当前身份",
            "",
            "终端内建: clear、history、watch <秒> <命令>、Ctrl+L、Ctrl+C、Tab 补全",
            "安全边界: 不执行 PowerShell/cmd/bash，不支持任意文件、网络或脚本命令。"
        }};
    }

    CommandResult status() const
    {
        std::vector<Poco::OSP::Bundle::Ptr> bundleList;
        _context->listBundles(bundleList);
        const auto serviceList = _context->registry().find("name");
        std::size_t active = 0;
        for (const auto& bundle : bundleList)
            if (lower(bundle->stateString()) == "active") ++active;
        std::size_t processCount = 0;
        std::size_t runningCount = 0;
        if (auto* manager = PocoDDS::ProcessManagement::SubprocessManager::active())
        {
            const auto managed = manager->processes();
            processCount = managed.size();
            runningCount = static_cast<std::size_t>(std::count_if(
                managed.begin(), managed.end(), [](const auto& process) {
                    return lower(process.state) == "running";
                }));
        }
        return {active == bundleList.size() ? 0 : 1, {
            "Runtime      : pdr-runtime (PID " + Poco::NumberFormatter::format(Poco::Process::id()) + ")",
            "Host         : " + Poco::Environment::nodeName(),
            "Bundles      : " + Poco::NumberFormatter::format(active) + "/" +
                Poco::NumberFormatter::format(bundleList.size()) + " active",
            "Services     : " + Poco::NumberFormatter::format(serviceList.size()) + " registered",
            "Subprocesses : " + Poco::NumberFormatter::format(runningCount) + "/" +
                Poco::NumberFormatter::format(processCount) + " running",
            std::string("Result       : ") + (active == bundleList.size() ? "OK" : "ATTENTION")
        }};
    }

    CommandResult health(const std::vector<std::string>& tokens) const
    {
        if (tokens.size() > 1 && lower(tokens[1]) != "tree" && lower(tokens[1]) != "check")
            return {2, {"用法: health [tree|check]"}};
        auto result = diagnose({"diagnose", "all", "--deep"});
        result.lines.insert(result.lines.begin(), "Runtime health tree (deep)");
        return result;
    }

    CommandResult providerDomain(const std::string& scope, const std::string& target,
                                 bool deep) const
    {
        CommandResult result;
        Query query;
        query.scope = scope;
        query.target = target;
        query.deep = deep;
        std::size_t matched = 0;
        for (const auto& reference : _context->registry().find(
                 DiagnosticProvider::SERVICE_PROPERTY))
        {
            try
            {
                const auto provider = reference->castedInstance<DiagnosticProvider>();
                const auto scopes = provider->scopes();
                if (std::find(scopes.begin(), scopes.end(), scope) == scopes.end()) continue;
                ++matched;
                const auto snapshot = provider->diagnose(query);
                for (const auto& [name, value] : snapshot.facts)
                    result.facts[provider->providerId() + "." + name] = value;
                for (const auto& finding : snapshot.findings) appendFinding(result, finding);
            }
            catch (const std::exception& exception)
            {
                appendFinding(result, Finding{
                    "PDR-DIAG-PROVIDER-FAILED", Severity::error, "provider",
                    reference->name(), "诊断 Provider 执行失败", exception.what(),
                    "检查 Provider 所属 Bundle 日志。"});
            }
        }
        result.facts["providers.matched"] = Poco::NumberFormatter::format(matched);
        if (matched == 0) return {1, {"没有 Provider 覆盖诊断域: " + scope}};
        if (result.findings.empty())
            result.lines.push_back("[OK] " + scope + " 诊断域未报告异常。");
        return result;
    }

    CommandResult protocols(const std::vector<std::string>& tokens) const
    {
        const std::string action = tokens.size() > 1 ? lower(tokens[1]) : "list";
        if (action == "check" || action == "show")
        {
            if (tokens.size() < 3) return {2, {"用法: protocol check <id> [--deep]"}};
            return providerDomain("protocol", tokens[2], true);
        }
        if (action != "list") return {2, {"用法: protocol list [过滤词] | protocol check <id>"}};
        const std::string filter = tokens.size() > 2 ? tokens[2] : "";
        CommandResult result;
        result.lines.push_back(tableRow(
            {"STATE", "REQUIRED", "FAILED", "RECONNECT", "PROTOCOL"},
            {10, 10, 10, 10, 0}));
        for (const auto& reference : _context->registry().find("pdr.protocol"))
        {
            const auto& properties = reference->properties();
            const std::string id = properties.get("pdr.protocol.id", reference->name());
            if (!containsInsensitive(id, filter)) continue;
            try
            {
                const auto provider = reference->castedInstance<PocoDDS::Protocols::ProtocolService>();
                const auto diagnostics = provider->diagnostics();
                result.lines.push_back(tableRow({provider->isOpen() ? "open" : "closed",
                    properties.getBool("pdr.protocol.required", false) ? "yes" : "no",
                    Poco::NumberFormatter::format(diagnostics.failedOperations),
                    Poco::NumberFormatter::format(diagnostics.reconnectAttempts), id},
                    {10, 10, 10, 10, 0}));
            }
            catch (const std::exception& exception)
            {
                result.lines.push_back(tableRow(
                    {"error", "?", "?", "?", id + " (" + exception.what() + ")"},
                    {10, 10, 10, 10, 0}));
                result.exitCode = 1;
            }
        }
        if (result.lines.size() == 1) result.lines.push_back("未找到匹配协议。");
        return result;
    }

    CommandResult devices(const std::vector<std::string>& tokens) const
    {
        const std::string action = tokens.size() > 1 ? lower(tokens[1]) : "list";
        if (action == "check" || action == "show")
        {
            if (tokens.size() < 3) return {2, {"用法: device check <id> [--deep]"}};
            return providerDomain("device", tokens[2], true);
        }
        if (action != "list") return {2, {"用法: device list [过滤词] | device check <id>"}};
        const std::string filter = tokens.size() > 2 ? tokens[2] : "";
        CommandResult result;
        result.lines.push_back(tableRow(
            {"STATE", "REQUIRED", "FAILURES", "DEVICE"}, {10, 10, 12, 0}));
        for (const auto& reference : _context->registry().find("pdr.device"))
        {
            const auto& properties = reference->properties();
            const std::string id = properties.get("pdr.device", reference->name());
            if (!containsInsensitive(id, filter)) continue;
            try
            {
                const auto provider = reference->castedInstance<PocoDDS::Devices::DeviceService>();
                const auto state = provider->device().snapshot().state;
                std::uint64_t failures = 0;
                if (const auto* diagnostic = dynamic_cast<const PocoDDS::Devices::DiagnosticDevice*>(
                        &provider->device()))
                    failures = diagnostic->diagnostics().consecutiveFailures;
                result.lines.push_back(tableRow({PocoDDS::Devices::toString(state),
                    properties.getBool("pdr.deviceRequired", true) ? "yes" : "no",
                    Poco::NumberFormatter::format(failures), id}, {10, 10, 12, 0}));
            }
            catch (const std::exception& exception)
            {
                result.lines.push_back(tableRow(
                    {"error", "?", "?", id + " (" + exception.what() + ")"},
                    {10, 10, 12, 0}));
                result.exitCode = 1;
            }
        }
        if (result.lines.size() == 1) result.lines.push_back("未找到匹配设备。");
        return result;
    }

    CommandResult metrics(const std::vector<std::string>& tokens) const
    {
        const std::string action = tokens.size() > 1 ? lower(tokens[1]) : "top";
        if (action == "anomalies" || action == "check")
            return providerDomain("metrics", tokens.size() > 2 ? tokens[2] : "", true);
        if (action != "top") return {2, {"用法: metrics top [过滤词] | metrics anomalies"}};
        const std::string filter = tokens.size() > 2 ? tokens[2] : "";
        auto points = PocoDDS::Observability::Metrics::global().snapshot();
        std::sort(points.begin(), points.end(), [](const auto& left, const auto& right) {
            const double leftValue = left.kind == PocoDDS::Observability::MetricKind::histogram ?
                left.maximum : left.value;
            const double rightValue = right.kind == PocoDDS::Observability::MetricKind::histogram ?
                right.maximum : right.value;
            return leftValue > rightValue;
        });
        CommandResult result;
        result.lines.push_back(tableRow({"VALUE", "COUNT", "UNIT", "METRIC"}, {14, 10, 12, 0}));
        std::size_t emitted = 0;
        for (const auto& point : points)
        {
            if (!containsInsensitive(point.name, filter)) continue;
            const double value = point.kind == PocoDDS::Observability::MetricKind::histogram ?
                point.maximum : point.value;
            result.lines.push_back(tableRow({Poco::NumberFormatter::format(value),
                Poco::NumberFormatter::format(point.count), point.unit, point.name},
                {14, 10, 12, 0}));
            if (++emitted >= 30) break;
        }
        if (result.lines.size() == 1) result.lines.push_back("未找到匹配指标。");
        result.facts["metrics.totalSeries"] = Poco::NumberFormatter::format(points.size());
        return result;
    }

    CommandResult traces(const std::vector<std::string>& tokens) const
    {
        const std::string action = tokens.size() > 1 ? lower(tokens[1]) : "list";
        if (action == "show")
        {
            if (tokens.size() < 3) return {2, {"用法: trace show <trace-id>"}};
            const auto spans = PocoDDS::Observability::globalTraceStore().trace(tokens[2]);
            if (spans.empty()) return {1, {"未找到 Trace: " + tokens[2]}};
            CommandResult result;
            result.lines.push_back(tableRow(
                {"STATUS", "DURATION_MS", "SERVICE", "OPERATION"}, {10, 14, 28, 0}));
            for (const auto& span : spans)
            {
                const double milliseconds = static_cast<double>(span.durationNanoseconds) / 1e6;
                result.lines.push_back(tableRow({span.status,
                    Poco::NumberFormatter::format(milliseconds), span.serviceName,
                    span.operation + (span.errorCode.empty() ? "" : " [" + span.errorCode + "]")},
                    {10, 14, 28, 0}));
                if (lower(span.status) == "failed")
                {
                    Finding finding{span.errorCode.empty() ? "PDR-DIAG-TRACE-SPAN-FAILED" :
                        span.errorCode, Severity::error, "trace", span.operation,
                        "Trace 节点执行失败", span.errorMessage,
                        "按 Trace ID 检索对应进程日志并检查父子 Span 参数。"};
                    finding.traceId = span.traceId;
                    appendFinding(result, std::move(finding));
                }
            }
            return result;
        }
        if (action != "list") return {2, {"用法: trace list [过滤词] | trace show <trace-id>"}};
        const std::string filter = tokens.size() > 2 ? tokens[2] : "";
        const auto items = PocoDDS::Observability::globalTraceStore().recent(100);
        CommandResult result;
        result.lines.push_back(tableRow(
            {"STATUS", "STEPS", "BUSINESS", "TRACE"}, {10, 8, 30, 0}));
        for (const auto& item : items)
        {
            if (!containsInsensitive(item.traceId + " " + item.businessName, filter)) continue;
            result.lines.push_back(tableRow({item.status,
                Poco::NumberFormatter::format(item.stepCount), item.businessName, item.traceId},
                {10, 8, 30, 0}));
        }
        if (result.lines.size() == 1) result.lines.push_back("未找到匹配 Trace。");
        return result;
    }

    CommandResult dds(const std::vector<std::string>& tokens) const
    {
        const std::string action = tokens.size() > 1 ? lower(tokens[1]) : "participants";
        if (action == "check" || action == "diagnose")
            return providerDomain("dds", tokens.size() > 2 ? tokens[2] : "", true);
        if (action == "discovery")
        {
            auto result = providerDomain("dds", "", true);
            result.lines.insert(result.lines.begin(),
                "DDS discovery/data-plane evidence (local process + exported metrics)");
            return result;
        }
        if (action != "participants" && action != "list" && action != "qos")
            return {2, {"用法: dds participants|discovery|qos|check [participant]"}};
        const auto runtimes = PocoDDS::FastDDS::Runtime::snapshots();
        CommandResult result;
        if (action == "qos")
            result.lines.push_back(tableRow(
                {"DOMAIN", "TRANSPORT", "QOS", "PARTICIPANT"}, {8, 12, 22, 0}));
        else result.lines.push_back(tableRow(
            {"STATE", "DOMAIN", "TOPICS", "WRITERS", "READERS", "PARTICIPANT"},
            {9, 8, 8, 9, 9, 0}));
        for (const auto& runtime : runtimes)
        {
            if (action == "qos")
                result.lines.push_back(tableRow({Poco::NumberFormatter::format(runtime.domainId),
                    runtime.transport, runtime.qosProfile, runtime.participantName},
                    {8, 12, 22, 0}));
            else result.lines.push_back(tableRow({runtime.started ? "started" : "stopped",
                    Poco::NumberFormatter::format(runtime.domainId),
                    Poco::NumberFormatter::format(runtime.topicCount),
                    Poco::NumberFormatter::format(runtime.writerCount),
                    Poco::NumberFormatter::format(runtime.readerCount), runtime.participantName},
                    {9, 8, 8, 9, 9, 0}));
        }
        if (runtimes.empty())
            result.lines.push_back("当前 Runtime 进程内无 Participant；对子进程使用 agent/trace/logs 组合诊断。");
        result.facts["dds.localParticipants"] = Poco::NumberFormatter::format(runtimes.size());
        return result;
    }

    std::map<std::string, std::string> configurationSnapshot() const
    {
        std::map<std::string, std::string> values;
        auto reference = _context->registry().findByName(
            Poco::OSP::PreferencesService::SERVICE_NAME);
        if (!reference) return values;
        auto preferences = reference->castedInstance<Poco::OSP::PreferencesService>();
        const auto configuration = preferences->configuration();
        if (configuration) collectConfiguration(*configuration, "", values);
        return values;
    }

    CommandResult configuration(const std::vector<std::string>& tokens) const
    {
        const std::string action = tokens.size() > 1 ? lower(tokens[1]) : "effective";
        const std::string prefix = tokens.size() > 2 ? tokens[2] : "";
        const auto current = configurationSnapshot();
        if (action == "effective")
        {
            CommandResult result;
            result.lines.push_back(tableRow({"KEY", "VALUE"}, {52, 0}));
            for (const auto& [key, value] : current)
            {
                if (!containsInsensitive(key, prefix)) continue;
                result.lines.push_back(tableRow({key, value}, {52, 0}));
                if (result.lines.size() >= 202)
                {
                    result.lines.push_back("输出已限制为 200 个配置项，请使用前缀缩小范围。");
                    break;
                }
            }
            if (result.lines.size() == 1) result.lines.push_back("未找到匹配配置。");
            result.facts["configuration.totalKeys"] = Poco::NumberFormatter::format(current.size());
            return result;
        }
        if (action == "diff")
        {
            CommandResult result;
            result.lines.push_back(tableRow({"CHANGE", "KEY", "STARTUP", "CURRENT"},
                                            {10, 42, 24, 0}));
            std::set<std::string> keys;
            for (const auto& [key, value] : _initialConfiguration)
            {
                static_cast<void>(value);
                keys.insert(key);
            }
            for (const auto& [key, value] : current)
            {
                static_cast<void>(value);
                keys.insert(key);
            }
            std::size_t changes = 0;
            for (const auto& key : keys)
            {
                if (!containsInsensitive(key, prefix)) continue;
                const auto before = _initialConfiguration.find(key);
                const auto after = current.find(key);
                if (before != _initialConfiguration.end() && after != current.end() &&
                    before->second == after->second) continue;
                const std::string kind = before == _initialConfiguration.end() ? "added" :
                    after == current.end() ? "removed" : "changed";
                result.lines.push_back(tableRow({kind, key,
                    before == _initialConfiguration.end() ? "-" : before->second,
                    after == current.end() ? "-" : after->second}, {10, 42, 24, 0}));
                ++changes;
            }
            if (!changes) result.lines.push_back("[OK] 当前有效配置与终端启动快照一致。");
            result.facts["configuration.changes"] = Poco::NumberFormatter::format(changes);
            return result;
        }
        if (action == "validate")
        {
            auto reference = _context->registry().findByName(
                Poco::OSP::PreferencesService::SERVICE_NAME);
            if (!reference) return {1, {"PreferencesService 尚未就绪。"}};
            auto preferences = reference->castedInstance<Poco::OSP::PreferencesService>();
            const auto values = preferences->configuration();
            if (!values) return {1, {"Runtime 有效配置不可用。"}};
            PocoDDS::Configuration::ConfigurationValidator validator;
            const auto issues = validator.validate(*values);
            CommandResult result;
            for (const auto& issue : issues)
                appendFinding(result, Finding{
                    "PDR-DIAG-CONFIG-INVALID", Severity::error, "configuration", issue.key,
                    "配置校验失败", issue.message,
                    "修正配置文件后通过 Runtime 治理事务重新应用。"});
            if (issues.empty()) result.lines.push_back("[OK] 当前有效配置通过完整规则校验。");
            result.facts["configuration.issues"] = Poco::NumberFormatter::format(issues.size());
            return result;
        }
        return {2, {"用法: config effective [前缀] | config diff [前缀] | config validate"}};
    }

    CommandResult support(const std::vector<std::string>& tokens,
                          const std::string& principal) const
    {
        if (tokens.size() < 2 || lower(tokens[1]) != "collect")
            return {2, {"用法: support collect"}};

        const Poco::Int64 created = Poco::Timestamp().epochMicroseconds();
        const std::string artifactId = "support-" + Poco::NumberFormatter::format(created) + ".json";
        Poco::JSON::Object root;
        root.set("schemaVersion", "pdr.support.bundle/1");
        root.set("createdMicroseconds", created);
        root.set("runtimeVersion", PDR_RUNTIME_VERSION);
        root.set("host", Poco::Environment::nodeName());
        root.set("processId", static_cast<Poco::UInt64>(Poco::Process::id()));
        root.set("principal", principal);

        Poco::JSON::Array::Ptr bundles = new Poco::JSON::Array;
        std::vector<Poco::OSP::Bundle::Ptr> bundleList;
        _context->listBundles(bundleList);
        for (const auto& bundle : bundleList)
        {
            Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
            item->set("id", bundle->symbolicName());
            item->set("name", bundle->name());
            item->set("version", bundle->version().toString());
            item->set("state", bundle->stateString());
            item->set("runLevel", bundle->runLevel());
            item->set("autoStartBlocked", bundle->autoStartBlocked());
            Poco::JSON::Array::Ptr dependencies = new Poco::JSON::Array;
            for (const auto& dependency : bundle->requiredBundles())
            {
                Poco::JSON::Object::Ptr value = new Poco::JSON::Object;
                value->set("id", dependency.symbolicName);
                value->set("versions", dependency.versions.toString());
                dependencies->add(value);
            }
            item->set("dependencies", dependencies);
            bundles->add(item);
        }
        root.set("bundles", bundles);

        Poco::JSON::Array::Ptr services = new Poco::JSON::Array;
        for (const auto& reference : _context->registry().find("name"))
        {
            Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
            item->set("name", reference->name());
            item->set("bundle", reference->properties().get("pdr.bundle", "unknown"));
            item->set("type", reference->properties().get("type", "unknown"));
            services->add(item);
        }
        root.set("services", services);

        Poco::JSON::Array::Ptr processes = new Poco::JSON::Array;
        Poco::JSON::Object::Ptr runtime = new Poco::JSON::Object;
        runtime->set("name", "pdr-runtime");
        runtime->set("pid", static_cast<Poco::UInt64>(Poco::Process::id()));
        runtime->set("state", "running");
        runtime->set("location", "local");
        processes->add(runtime);
        if (auto* manager = PocoDDS::ProcessManagement::SubprocessManager::active())
            for (const auto& process : manager->processes())
            {
                Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
                item->set("name", process.name);
                item->set("pid", static_cast<Poco::UInt64>(process.processId));
                item->set("state", process.state);
                item->set("location", process.location);
                item->set("required", process.required);
                item->set("manageable", process.manageable);
                processes->add(item);
            }
        root.set("processes", processes);

        Poco::JSON::Object::Ptr configuration = new Poco::JSON::Object;
        for (const auto& [key, value] : configurationSnapshot()) configuration->set(key, value);
        root.set("configuration", configuration);

        Poco::JSON::Array::Ptr metrics = new Poco::JSON::Array;
        for (const auto& point : PocoDDS::Observability::Metrics::global().snapshot())
        {
            Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
            item->set("name", point.name);
            item->set("kind", point.kind == PocoDDS::Observability::MetricKind::counter ?
                "counter" : "histogram");
            item->set("unit", point.unit);
            item->set("value", point.value);
            item->set("count", static_cast<Poco::UInt64>(point.count));
            item->set("minimum", point.minimum);
            item->set("maximum", point.maximum);
            Poco::JSON::Object::Ptr attributes = new Poco::JSON::Object;
            for (const auto& [key, value] : point.attributes) attributes->set(key, value);
            item->set("attributes", attributes);
            metrics->add(item);
        }
        root.set("metrics", metrics);

        Poco::JSON::Array::Ptr traces = new Poco::JSON::Array;
        for (const auto& trace : PocoDDS::Observability::globalTraceStore().recent(100))
        {
            Poco::JSON::Object::Ptr item = new Poco::JSON::Object;
            item->set("traceId", trace.traceId);
            item->set("businessName", trace.businessName);
            item->set("businessInstanceId", trace.businessInstanceId);
            item->set("status", trace.status);
            item->set("startedMicroseconds", trace.startedUnixMicroseconds);
            item->set("stepCount", static_cast<Poco::UInt64>(trace.stepCount));
            item->set("failedOperation", trace.failedOperation);
            traces->add(item);
        }
        root.set("traces", traces);

        const auto doctor = diagnose({"diagnose", "all", "--deep"});
        Poco::JSON::Object::Ptr diagnosis = new Poco::JSON::Object;
        diagnosis->set("exitCode", doctor.exitCode);
        Poco::JSON::Array::Ptr findings = new Poco::JSON::Array;
        for (const auto& finding : doctor.findings) findings->add(findingJson(finding));
        diagnosis->set("findings", findings);
        Poco::JSON::Object::Ptr facts = new Poco::JSON::Object;
        for (const auto& [key, value] : doctor.facts) facts->set(key, value);
        diagnosis->set("facts", facts);
        root.set("diagnosis", diagnosis);

        const auto logResult = logs({"logs", "runtime", "--tail", "500"});
        Poco::JSON::Array::Ptr logLines = new Poco::JSON::Array;
        for (const auto& line : logResult.lines) logLines->add(redactedLogLine(line));
        root.set("runtimeLogs", logLines);

        Poco::Path directory("data/diagnostics");
        directory.makeAbsolute();
        Poco::File(directory).createDirectories();
        Poco::Path artifact(directory);
        artifact.append(artifactId);
        Poco::FileOutputStream output(artifact.toString());
        root.stringify(output, 2);
        output.close();
        if (!output.good()) return {1, {"写入诊断包失败: " + artifact.toString()}};

        CommandResult result{0, {
            "[OK] 脱敏诊断包已生成。",
            "Artifact : " + artifactId,
            "Download : /api/v1/diagnostic-terminal?artifact=" + artifactId
        }};
        result.facts["artifact.id"] = artifactId;
        result.facts["artifact.url"] = "/api/v1/diagnostic-terminal?artifact=" + artifactId;
        result.facts["artifact.path"] = artifact.toString();
        return result;
    }

    unsigned long managedProcessId(const std::string& target) const
    {
        if (target.empty() || lower(target) == "runtime" || lower(target) == "pdr-runtime" ||
            target == Poco::NumberFormatter::format(Poco::Process::id()))
            return static_cast<unsigned long>(Poco::Process::id());
        if (auto* manager = PocoDDS::ProcessManagement::SubprocessManager::active())
            for (const auto& process : manager->processes())
                if (process.name == target ||
                    Poco::NumberFormatter::format(process.processId) == target)
                    return process.processId;
        return 0;
    }

    CommandResult runAgent(const std::string& action, const std::string& target,
                           const Poco::Process::Args& extraArguments = {}) const
    {
        const unsigned long pid = managedProcessId(target);
        if (!pid) return {1, {"未知进程；Agent 只允许检查 Runtime 或已托管子进程。"}};
        Poco::Path executable;
        executable.pushDirectory("processes");
        executable.pushDirectory("pdr-diagnostic-agent");
#if defined(POCO_OS_FAMILY_WINDOWS)
        executable.setFileName("pdr-diagnostic-agent.exe");
#else
        executable.setFileName("pdr-diagnostic-agent");
#endif
        executable.makeAbsolute();
        if (!Poco::File(executable).exists())
            return {1, {"独立诊断 Agent 尚未部署: " + executable.toString()}};

        Poco::Pipe outputPipe;
        Poco::Process::Args arguments{action, "--pid", Poco::NumberFormatter::format(pid)};
        arguments.insert(arguments.end(), extraArguments.begin(), extraArguments.end());
        const auto handle = Poco::Process::launch(executable.toString(), arguments,
            nullptr, &outputPipe, &outputPipe);
        Poco::PipeInputStream input(outputPipe);
        std::ostringstream output;
        std::string line;
        while (std::getline(input, line)) output << line;
        const int exitCode = Poco::Process::wait(handle);
        try
        {
            Poco::JSON::Parser parser;
            const auto object = parser.parse(output.str()).extract<Poco::JSON::Object::Ptr>();
            CommandResult result;
            result.exitCode = exitCode;
            std::ostringstream compact;
            object->stringify(compact);
            result.lines.push_back(compact.str());
            for (const auto& [name, value] : *object)
            {
                if (value.isString()) result.facts["agent." + name] = value.convert<std::string>();
                else if (value.isBoolean()) result.facts["agent." + name] =
                    value.convert<bool>() ? "true" : "false";
                else if (value.isNumeric()) result.facts["agent." + name] = value.toString();
            }
            if (exitCode != 0)
                appendFinding(result, Finding{
                    "PDR-DIAG-AGENT-CHECK-FAILED", Severity::error, "process", target,
                    "独立 Agent 检查未通过",
                    object->optValue<std::string>("error", compact.str()),
                    "确认 PID、运行账户权限和目标进程状态。"});
            return result;
        }
        catch (const std::exception& exception)
        {
            return {1, {"Agent 返回无效 JSON: " + std::string(exception.what()), output.str()}};
        }
    }

    CommandResult agent(const std::vector<std::string>& tokens) const
    {
        if (tokens.size() < 2)
            return {2, {"用法: agent status|threads|net [进程名或 PID]"}};
        const std::string action = lower(tokens[1]);
        if (action != "status" && action != "threads" && action != "net")
            return {2, {"只读 Agent 命令只允许 status、threads 和 net；"
                        "采集转储请使用 dump process <目标> --confirm。"}};
        return runAgent(action, tokens.size() > 2 ? tokens[2] : "runtime");
    }

    CommandResult captureDump(const std::vector<std::string>& tokens) const
    {
        if (tokens.size() < 4 || lower(tokens[1]) != "process" ||
            std::find(tokens.begin(), tokens.end(), "--confirm") == tokens.end())
            return {2, {"用法: dump process <进程名或 PID> --confirm"}};
        if (!managedProcessId(tokens[2]))
            return {1, {"未知进程；只允许采集 Runtime 或已托管子进程。"}};
        Poco::Path directory("data/diagnostics/dumps");
        directory.makeAbsolute();
        Poco::File(directory).createDirectories();
        const auto timestamp = Poco::Timestamp().epochMicroseconds();
        const std::string id = "dump-" + safeLogName(tokens[2]) + "-" +
            Poco::NumberFormatter::format(timestamp) + ".dmp";
        Poco::Path output(directory);
        output.append(id);
        auto result = runAgent("dump", tokens[2], {"--output", output.toString()});
        if (!result.exitCode)
        {
            result.lines.push_back("Dump ID: " + id);
            result.facts["dump.id"] = id;
            result.facts["dump.path"] = output.toString();
        }
        return result;
    }

    CommandResult crashes(const std::vector<std::string>& tokens) const
    {
        const std::string action = tokens.size() > 1 ? lower(tokens[1]) : "list";
        Poco::Path directory("data/diagnostics/dumps");
        directory.makeAbsolute();
        if (action == "show")
        {
            if (tokens.size() < 3 || safeLogName(tokens[2]) != tokens[2] ||
                tokens[2].rfind("dump-", 0) != 0)
                return {2, {"用法: crash show <dump-id>"}};
            Poco::Path path(directory);
            path.append(tokens[2]);
            Poco::File file(path);
            if (!file.exists() || !file.isFile()) return {1, {"未找到 Dump: " + tokens[2]}};
            return {0, {"Dump ID : " + tokens[2],
                        "Size    : " + Poco::NumberFormatter::format(file.getSize()) + " bytes",
                        "Updated : " + Poco::NumberFormatter::format(
                            file.getLastModified().epochMicroseconds()),
                        "Path    : " + path.toString()}};
        }
        if (action != "list") return {2, {"用法: crash list | crash show <dump-id>"}};
        CommandResult result;
        result.lines.push_back(tableRow({"SIZE", "UPDATED_US", "DUMP"}, {14, 20, 0}));
        Poco::File folder(directory);
        if (folder.exists())
        {
            std::vector<std::string> files;
            folder.list(files);
            std::sort(files.rbegin(), files.rend());
            for (const auto& name : files)
            {
                if (name.rfind("dump-", 0) != 0 ||
                    name.size() < 4 || lower(name.substr(name.size() - 4)) != ".dmp") continue;
                Poco::Path path(directory); path.append(name);
                Poco::File file(path);
                result.lines.push_back(tableRow({Poco::NumberFormatter::format(file.getSize()),
                    Poco::NumberFormatter::format(file.getLastModified().epochMicroseconds()), name},
                    {14, 20, 0}));
                if (result.lines.size() >= 101) break;
            }
        }
        if (result.lines.size() == 1) result.lines.push_back("尚无受控崩溃转储。");
        return result;
    }

    CommandResult processes(const std::vector<std::string>& tokens) const
    {
        const std::string filter = tokens.size() > 1 ? tokens[1] : "";
        CommandResult result;
        result.lines.push_back(tableRow({"PID", "STATE", "LOCATION", "MANAGED", "NAME"},
                                        {10, 12, 12, 9, 0}));
        const std::string runtimePid = Poco::NumberFormatter::format(Poco::Process::id());
        if (containsInsensitive("pdr-runtime " + runtimePid, filter))
            result.lines.push_back(tableRow({runtimePid, "running", "local", "external", "pdr-runtime"},
                                            {10, 12, 12, 9, 0}));
        if (auto* manager = PocoDDS::ProcessManagement::SubprocessManager::active())
        {
            auto items = manager->processes();
            std::sort(items.begin(), items.end(), [](const auto& left, const auto& right) {
                return left.name < right.name;
            });
            for (const auto& item : items)
            {
                if (!containsInsensitive(item.name + " " +
                    Poco::NumberFormatter::format(item.processId), filter)) continue;
                result.lines.push_back(tableRow({Poco::NumberFormatter::format(item.processId),
                    item.state, item.location, item.manageable ? "yes" : "no", item.name},
                    {10, 12, 12, 9, 0}));
            }
        }
        if (result.lines.size() == 1) result.lines.push_back("未找到匹配进程。");
        return result;
    }

    CommandResult bundles(const std::vector<std::string>& tokens) const
    {
        const std::string action = tokens.size() > 1 ? lower(tokens[1]) : "list";
        std::vector<Poco::OSP::Bundle::Ptr> items;
        _context->listBundles(items);
        std::sort(items.begin(), items.end(), [](const auto& left, const auto& right) {
            return left->symbolicName() < right->symbolicName();
        });
        const auto findBundle = [&](const std::string& id) -> Poco::OSP::Bundle::Ptr {
            const auto iterator = std::find_if(items.begin(), items.end(),
                [&](const auto& item) { return item->symbolicName() == id; });
            return iterator == items.end() ? Poco::OSP::Bundle::Ptr{} : *iterator;
        };
        if (action == "deps")
        {
            if (tokens.size() < 3) return {2, {"用法: bundle deps <bundle-id>"}};
            const auto item = findBundle(tokens[2]);
            if (!item) return {1, {"未找到 Bundle: " + tokens[2]}};
            CommandResult result;
            result.lines.push_back("Required dependencies:");
            for (const auto& dependency : item->requiredBundles())
                result.lines.push_back("  - " + dependency.symbolicName + " " +
                                       dependency.versions.toString());
            if (item->requiredBundles().empty()) result.lines.push_back("  (none)");
            result.lines.push_back("Resolved providers:");
            for (const auto& dependency : item->resolvedDependencies())
                result.lines.push_back("  - " + dependency.symbolicName + " " +
                                       dependency.version.toString());
            if (item->resolvedDependencies().empty()) result.lines.push_back("  (none)");
            result.facts["bundle.state"] = item->stateString();
            result.facts["bundle.runLevel"] = item->runLevel();
            return result;
        }
        if (action == "history")
        {
            if (tokens.size() < 3) return {2, {"用法: bundle history <bundle-id>"}};
            if (!findBundle(tokens[2])) return {1, {"未找到 Bundle: " + tokens[2]}};
            auto result = logs({"logs", "runtime", "--tail", "100", "--grep", tokens[2]});
            result.facts["bundle.id"] = tokens[2];
            return result;
        }
        if (action == "quarantine")
        {
            if (tokens.size() < 3) return {2, {"用法: bundle quarantine <bundle-id>"}};
            const auto item = findBundle(tokens[2]);
            if (!item) return {1, {"未找到 Bundle: " + tokens[2]}};
            CommandResult result{0, {
                "Bundle           : " + item->symbolicName(),
                "State            : " + item->stateString(),
                std::string("Auto-start block : ") + (item->autoStartBlocked() ? "yes" : "no"),
                "Run level        : " + item->runLevel()
            }};
            if (item->autoStartBlocked())
                appendFinding(result, Finding{
                    "PDR-DIAG-BUNDLE-QUARANTINED", Severity::error, "bundle",
                    item->symbolicName(), "Bundle 自动启动已被隔离策略阻断",
                    "autoStartBlocked=true", "在插件治理页检查失败预算和 quarantineLastError，"
                    "确认根因后执行受控 reset-quarantine。"});
            else result.lines.push_back("[OK] 当前没有 Bundle 级自动启动隔离。");
            return result;
        }
        if (action == "show")
        {
            if (tokens.size() < 3) return {2, {"用法: bundle show <bundle-id>"}};
            for (const auto& item : items)
            {
                if (item->symbolicName() != tokens[2]) continue;
                CommandResult result{0, {
                    "ID       : " + item->symbolicName(),
                    "Name     : " + item->name(),
                    "Version  : " + item->version().toString(),
                    "State    : " + item->stateString(),
                    "RunLevel : " + item->runLevel(),
                    std::string("Blocked  : ") + (item->autoStartBlocked() ? "yes" : "no"),
                    "Services :"
                }};
                bool found = false;
                for (const auto& service : _context->registry().find("name"))
                {
                    if (service->properties().get("pdr.bundle", "") == item->symbolicName())
                    {
                        result.lines.push_back("  - " + service->name());
                        found = true;
                    }
                }
                if (!found) result.lines.push_back("  (none reported)");
                return result;
            }
            return {1, {"未找到 Bundle: " + tokens[2]}};
        }
        if (action != "list" && tokens.size() > 1)
            return {2, {"用法: bundle list [过滤词] | bundle show|deps|history|quarantine <bundle-id>"}};
        const std::string filter = tokens.size() > 2 ? tokens[2] : "";
        CommandResult result;
        result.lines.push_back(tableRow({"STATE", "VERSION", "BUNDLE"}, {12, 12, 0}));
        for (const auto& item : items)
        {
            if (!containsInsensitive(item->symbolicName() + " " + item->name(), filter)) continue;
            result.lines.push_back(tableRow({item->stateString(), item->version().toString(),
                                             item->symbolicName()}, {12, 12, 0}));
        }
        if (result.lines.size() == 1) result.lines.push_back("未找到匹配 Bundle。");
        return result;
    }

    CommandResult services(const std::vector<std::string>& tokens) const
    {
        const std::string action = tokens.size() > 1 ? lower(tokens[1]) : "list";
        auto items = _context->registry().find("name");
        std::sort(items.begin(), items.end(), [](const auto& left, const auto& right) {
            return left->name() < right->name();
        });
        const auto findService = [&](const std::string& name) -> Poco::OSP::ServiceRef::Ptr {
            const auto iterator = std::find_if(items.begin(), items.end(),
                [&](const auto& item) { return item->name() == name; });
            return iterator == items.end() ? Poco::OSP::ServiceRef::Ptr{} : *iterator;
        };
        if (action == "providers")
        {
            if (tokens.size() < 3) return {2, {"用法: service providers <service-name>"}};
            const auto item = findService(tokens[2]);
            if (!item) return {1, {"未找到 Service: " + tokens[2]}};
            const auto& properties = item->properties();
            return {0, {
                "Service  : " + item->name(),
                "Bundle   : " + properties.get("pdr.bundle", "unknown"),
                "Type     : " + properties.get("type", "unknown"),
                "Provider : " + properties.get("pdr.service", "-")
            }};
        }
        if (action == "consumers")
        {
            if (tokens.size() < 3) return {2, {"用法: service consumers <service-name>"}};
            const auto item = findService(tokens[2]);
            if (!item) return {1, {"未找到 Service: " + tokens[2]}};
            const std::string owner = item->properties().get("pdr.bundle", "");
            CommandResult result;
            result.lines.push_back("Bundle dependency consumers (owner=" +
                                   (owner.empty() ? "unknown" : owner) + "):");
            std::vector<Poco::OSP::Bundle::Ptr> bundles;
            _context->listBundles(bundles);
            for (const auto& bundle : bundles)
                for (const auto& dependency : bundle->requiredBundles())
                    if (!owner.empty() && dependency.symbolicName == owner)
                    {
                        result.lines.push_back("  - " + bundle->symbolicName());
                        break;
                    }
            if (result.lines.size() == 1)
                result.lines.push_back("  (未发现静态 Bundle 依赖；动态 Service 使用者无法从 Registry 反推)");
            return result;
        }
        if (action == "check")
        {
            if (tokens.size() < 3) return {2, {"用法: service check <service-name>"}};
            const auto item = findService(tokens[2]);
            if (!item) return {1, {"未找到 Service: " + tokens[2]}};
            CommandResult result;
            const std::string owner = item->properties().get("pdr.bundle", "");
            const auto bundle = owner.empty() ? Poco::OSP::Bundle::Ptr{} :
                _context->findBundle(owner);
            if (owner.empty())
                appendFinding(result, Finding{
                    "PDR-DIAG-SERVICE-OWNER-UNKNOWN", Severity::warning, "service", item->name(),
                    "Service 未声明生命周期 owner", "pdr.bundle property missing",
                    "在注册 Service 时设置 pdr.bundle。"});
            else if (!bundle || !bundle->isActive())
                appendFinding(result, Finding{
                    "PDR-DIAG-SERVICE-OWNER-INACTIVE", Severity::error, "service", item->name(),
                    "Service owner Bundle 不处于 active 状态",
                    "owner=" + owner + (bundle ? ", state=" + bundle->stateString() : ", missing"),
                    "执行 bundle deps " + owner + " 并检查启动日志。"});
            try
            {
                const auto instance = item->instance();
                if (const auto* contributor = dynamic_cast<const PocoDDS::Health::IHealthContributor*>(
                        instance.get()))
                {
                    const auto report = contributor->health();
                    result.facts["health.component"] = report.component;
                    result.facts["health.detail"] = report.detail;
                    if (report.status != PocoDDS::Health::Status::up)
                        appendFinding(result, Finding{
                            report.code.empty() ? "PDR-DIAG-SERVICE-UNHEALTHY" : report.code,
                            report.status == PocoDDS::Health::Status::down ? Severity::error :
                                Severity::warning,
                            "service", item->name(), "Service 健康探针报告异常",
                            report.detail, report.remediation});
                }
                else result.facts["health.probe"] = "not-registered";
            }
            catch (const std::exception& exception)
            {
                appendFinding(result, Finding{
                    "PDR-DIAG-SERVICE-INSTANCE-FAILED", Severity::error, "service", item->name(),
                    "无法获取 Service 实例", exception.what(), "检查 ServiceFactory 和 Bundle ABI。"});
            }
            if (result.findings.empty()) result.lines.push_back("[OK] Service 已注册且 owner 正常。");
            return result;
        }
        if (action == "show")
        {
            if (tokens.size() < 3) return {2, {"用法: service show <service-name>"}};
            for (const auto& item : items)
            {
                if (item->name() != tokens[2]) continue;
                const auto& properties = item->properties();
                return {0, {
                    "Name    : " + item->name(),
                    "State   : registered",
                    "Type    : " + properties.get("type", "unknown"),
                    "Bundle  : " + properties.get("pdr.bundle", "unknown"),
                    "Service : " + properties.get("pdr.service", "-")
                }};
            }
            return {1, {"未找到 Service: " + tokens[2]}};
        }
        if (action != "list" && tokens.size() > 1)
            return {2, {"用法: service list [过滤词] | service show|check|providers|consumers <service-name>"}};
        const std::string filter = tokens.size() > 2 ? tokens[2] : "";
        CommandResult result;
        result.lines.push_back(tableRow({"STATE", "BUNDLE", "SERVICE"}, {12, 34, 0}));
        for (const auto& item : items)
        {
            const std::string owner = item->properties().get("pdr.bundle", "unknown");
            if (!containsInsensitive(item->name() + " " + owner, filter)) continue;
            result.lines.push_back(tableRow({"registered", owner, item->name()}, {12, 34, 0}));
        }
        if (result.lines.size() == 1) result.lines.push_back("未找到匹配 Service。");
        return result;
    }

    CommandResult logs(const std::vector<std::string>& tokens) const
    {
        std::string process = "pdr-runtime";
        int tail = 80;
        std::string filter;
        std::size_t index = 1;
        if (index < tokens.size() && tokens[index].rfind("--", 0) != 0)
            process = tokens[index++];
        while (index < tokens.size())
        {
            if (tokens[index] == "--tail" && index + 1 < tokens.size())
            {
                try { tail = std::stoi(tokens[++index]); }
                catch (...) { return {2, {"--tail 必须是数字。"}}; }
            }
            else if (tokens[index] == "--grep" && index + 1 < tokens.size())
                filter = tokens[++index];
            else return {2, {"用法: logs [runtime|进程名] [--tail N] [--grep 文本]"}};
            ++index;
        }
        tail = std::max(1, std::min(tail, 500));
        if (lower(process) == "runtime" || process == Poco::NumberFormatter::format(Poco::Process::id()))
            process = "pdr-runtime";
        bool known = process == "pdr-runtime";
        if (auto* manager = PocoDDS::ProcessManagement::SubprocessManager::active())
            for (const auto& item : manager->processes())
                if (item.name == process || Poco::NumberFormatter::format(item.processId) == process)
                {
                    process = item.name;
                    known = true;
                    break;
                }
        if (!known) return {1, {"未知进程；只允许读取 Runtime 或已托管子进程日志。"}};
        const std::string logName = safeLogName(process);
        Poco::Path path("logs");
        path.append(logName + ".log");
        path.makeAbsolute();
        std::ifstream input(path.toString());
        if (!input) return {1, {"日志文件尚不存在: logs/" + logName + ".log"}};
        std::deque<std::string> selected;
        std::string line;
        while (std::getline(input, line))
        {
            if (!containsInsensitive(line, filter)) continue;
            selected.push_back(line);
            if (selected.size() > static_cast<std::size_t>(tail)) selected.pop_front();
        }
        CommandResult result;
        result.lines.assign(selected.begin(), selected.end());
        if (result.lines.empty()) result.lines.push_back("没有匹配的日志行。");
        return result;
    }

    CommandResult diagnose(const std::vector<std::string>& tokens) const
    {
        if (tokens.size() < 2 || lower(tokens[1]) == "all")
        {
            CommandResult result;
            std::vector<Poco::OSP::Bundle::Ptr> bundleList;
            _context->listBundles(bundleList);
            result.lines.push_back("Diagnostic summary");
            result.lines.push_back("------------------");
            for (const auto& bundle : bundleList)
                if (lower(bundle->stateString()) != "active")
                    appendFinding(result, Finding{
                        "PDR-DIAG-BUNDLE-NOT-ACTIVE", Severity::warning, "bundle",
                        bundle->symbolicName(), "Bundle 未处于 active 状态",
                        "state=" + bundle->stateString(),
                        "执行 bundle show " + bundle->symbolicName() +
                            "，检查依赖和启动日志。"});
            if (auto* manager = PocoDDS::ProcessManagement::SubprocessManager::active())
                for (const auto& process : manager->processes())
                    if (lower(process.state) != "running" && process.required)
                        appendFinding(result, Finding{
                            "PDR-DIAG-PROCESS-REQUIRED-NOT-RUNNING", Severity::error,
                            "process", process.name, "必需子进程未运行",
                            "state=" + process.state + ", pid=" +
                                Poco::NumberFormatter::format(process.processId),
                            "检查 logs " + process.name +
                                " --tail 100，然后从进程治理页执行受控重启。"});
            std::size_t ownerUnknown = 0;
            for (const auto& service : _context->registry().find("name"))
                if (service->properties().get("pdr.bundle", "").empty()) ++ownerUnknown;
            if (ownerUnknown)
            {
                appendFinding(result, Finding{
                    "PDR-DIAG-SERVICE-OWNER-UNKNOWN", Severity::warning, "service", "registry",
                    "存在没有声明 Bundle owner 的 Service",
                    "count=" + Poco::NumberFormatter::format(ownerUnknown),
                    "为 Service 注册属性补充 pdr.bundle，并核对生命周期所有者。"});
            }
            result.facts["bundles.checked"] = Poco::NumberFormatter::format(bundleList.size());
            result.facts["services.checked"] = Poco::NumberFormatter::format(
                _context->registry().find("name").size());
            result.facts["services.unknownOwners"] = Poco::NumberFormatter::format(ownerUnknown);

            const auto providerRefs = _context->registry().find(
                DiagnosticProvider::SERVICE_PROPERTY);
            result.facts["providers.checked"] = Poco::NumberFormatter::format(providerRefs.size());
            Query query;
            query.scope = "all";
            query.deep = std::find(tokens.begin(), tokens.end(), "--deep") != tokens.end();
            for (const auto& reference : providerRefs)
            {
                try
                {
                    const auto provider = reference->castedInstance<DiagnosticProvider>();
                    const auto snapshot = provider->diagnose(query);
                    for (const auto& [name, value] : snapshot.facts)
                        result.facts[provider->providerId() + "." + name] = value;
                    for (const auto& finding : snapshot.findings) appendFinding(result, finding);
                }
                catch (const std::exception& exception)
                {
                    appendFinding(result, Finding{
                        "PDR-DIAG-PROVIDER-FAILED", Severity::error, "provider",
                        reference->name(), "诊断 Provider 执行失败", exception.what(),
                        "检查 Provider 所属 Bundle 日志和线程安全实现。"});
                }
            }
            if (result.findings.empty())
                result.lines.push_back("[OK] 未发现已覆盖诊断域中的运行异常。");
            result.lines.push_back("建议继续: logs runtime --tail 100 --grep ERR");
            return result;
        }
        if (tokens.size() < 3)
            return {2, {"用法: diagnose all|bundle|service|process <目标>"}};
        const std::string kind = lower(tokens[1]);
        if (kind == "bundle")
        {
            const auto detail = bundles({"bundle", "show", tokens[2]});
            if (detail.exitCode) return detail;
            CommandResult result = detail;
            const auto bundle = _context->findBundle(tokens[2]);
            if (bundle && lower(bundle->stateString()) == "active")
                result.lines.push_back("[OK] Bundle 已激活；若功能异常，请检查其 Service 和日志。");
            else
            {
                result.exitCode = 1;
                result.lines.push_back("[WARN] Bundle 未处于 active 状态。");
            }
            return result;
        }
        if (kind == "service")
        {
            auto result = services({"service", "show", tokens[2]});
            if (!result.exitCode) result.lines.push_back("[OK] Service 当前已注册。");
            return result;
        }
        if (kind == "process")
        {
            auto result = processes({"ps", tokens[2]});
            if (result.lines.size() <= 1) return {1, {"未找到进程: " + tokens[2]}};
            bool healthy = true;
            for (const auto& line : result.lines)
                if (containsInsensitive(line, "stopped") || containsInsensitive(line, "failed")) healthy = false;
            result.exitCode = healthy ? 0 : 1;
            result.lines.push_back(healthy ? "[OK] 进程状态正常。" : "[WARN] 进程未运行。 ");
            return result;
        }
        return {2, {"未知诊断类型: " + tokens[1]}};
    }

    CommandResult providers(const std::vector<std::string>& tokens) const
    {
        const std::string action = tokens.size() > 1 ? lower(tokens[1]) : "list";
        const auto references = _context->registry().find(DiagnosticProvider::SERVICE_PROPERTY);
        if (action == "list")
        {
            CommandResult result;
            result.lines.push_back(tableRow({"PROVIDER", "SCOPES", "SERVICE"}, {32, 28, 0}));
            for (const auto& reference : references)
            {
                try
                {
                    const auto provider = reference->castedInstance<DiagnosticProvider>();
                    std::ostringstream scopes;
                    const auto values = provider->scopes();
                    for (std::size_t index = 0; index < values.size(); ++index)
                    {
                        if (index) scopes << ',';
                        scopes << values[index];
                    }
                    result.lines.push_back(tableRow(
                        {provider->providerId(), scopes.str(), reference->name()}, {32, 28, 0}));
                }
                catch (...) {}
            }
            if (result.lines.size() == 1)
                result.lines.push_back("尚无模块注册 pdr.diagnostics.provider。");
            result.facts["providers.count"] = Poco::NumberFormatter::format(references.size());
            return result;
        }
        if (action != "check" || tokens.size() < 3)
            return {2, {"用法: provider list | provider check <provider-id> [目标]"}};
        for (const auto& reference : references)
        {
            try
            {
                const auto provider = reference->castedInstance<DiagnosticProvider>();
                if (provider->providerId() != tokens[2]) continue;
                Query query;
                query.target = tokens.size() > 3 ? tokens[3] : "";
                query.deep = std::find(tokens.begin(), tokens.end(), "--deep") != tokens.end();
                const auto snapshot = provider->diagnose(query);
                CommandResult result;
                result.facts = snapshot.facts;
                for (const auto& finding : snapshot.findings) appendFinding(result, finding);
                if (result.findings.empty()) result.lines.push_back("[OK] Provider 未报告异常。");
                return result;
            }
            catch (const std::exception& exception)
            {
                return {1, {"Provider 执行失败: " + std::string(exception.what())}};
            }
        }
        return {1, {"未找到诊断 Provider: " + tokens[2]}};
    }

    CommandResult version() const
    {
        return {0, {
            std::string("PocoDDS Runtime ") + PDR_RUNTIME_VERSION,
            Poco::Environment::osName() + " " + Poco::Environment::osVersion(),
            "Host " + Poco::Environment::nodeName()
        }};
    }

    CommandResult uptime() const
    {
        const auto seconds = static_cast<long long>(_started.elapsed() / 1000000);
        const auto hours = seconds / 3600;
        const auto minutes = (seconds % 3600) / 60;
        const auto remainder = seconds % 60;
        return {0, {Poco::NumberFormatter::format(hours) + "h " +
                    Poco::NumberFormatter::format(minutes) + "m " +
                    Poco::NumberFormatter::format(remainder) + "s"}};
    }

    Poco::OSP::BundleContext::Ptr _context;
    Poco::Timestamp _started;
    std::map<std::string, std::string> _initialConfiguration;
};

struct AuthorizationContext
{
    std::string principal;
    bool mayExecute{false};
};

bool commandRateAllowed(const std::string& principal)
{
    static std::mutex mutex;
    static std::map<std::string, std::deque<Poco::Timestamp::TimeVal>> recent;
    const auto now = Poco::Timestamp().epochMicroseconds();
    const auto cutoff = now - 10000000;
    std::lock_guard<std::mutex> lock(mutex);
    auto& entries = recent[principal];
    while (!entries.empty() && entries.front() < cutoff) entries.pop_front();
    if (entries.size() >= 30) return false;
    entries.push_back(now);
    if (recent.size() > 256)
        for (auto iterator = recent.begin(); iterator != recent.end();)
        {
            while (!iterator->second.empty() && iterator->second.front() < cutoff)
                iterator->second.pop_front();
            if (iterator->second.empty() && iterator->first != principal)
                iterator = recent.erase(iterator);
            else ++iterator;
        }
    return true;
}

void enforceOutputLimit(CommandResult& result)
{
    bool truncated = false;
    if (result.lines.size() > 2000)
    {
        result.lines.resize(2000);
        result.lines.push_back("[OUTPUT-LIMIT] 输出已截断为 2000 行。");
        truncated = true;
    }
    if (result.findings.size() > 200)
    {
        result.findings.resize(200);
        truncated = true;
    }
    while (result.facts.size() > 500)
    {
        result.facts.erase(std::prev(result.facts.end()));
        truncated = true;
    }
    if (truncated) result.facts["output.truncated"] = "true";
}

bool authorize(Poco::OSP::BundleContext::Ptr context,
               Poco::Net::HTTPServerRequest& request,
               Poco::Net::HTTPServerResponse& response,
               AuthorizationContext& authorization)
{
    const auto identityRef = context->registry().findByName(
        PocoDDS::ManagementAuth::IdentityService::SERVICE_NAME);
    if (!identityRef)
    {
        sendJsonError(response, Poco::Net::HTTPResponse::HTTP_SERVICE_UNAVAILABLE,
                      "管理身份服务尚未就绪。");
        return false;
    }
    const auto identity = identityRef->castedInstance<
        PocoDDS::ManagementAuth::IdentityService>();
    if (!identity->snapshot().required)
    {
        authorization.principal = "development-anonymous";
        authorization.mayExecute = true;
        return true;
    }
    const auto matched = identity->authenticateAuthorizationHeader(
        request.get("Authorization", ""));
    if (!matched)
    {
        response.set("WWW-Authenticate", "Bearer realm=\"pdr-diagnostics\"");
        sendJsonError(response, Poco::Net::HTTPResponse::HTTP_UNAUTHORIZED,
                      "诊断终端需要有效的 Bearer 令牌。");
        return false;
    }
    if (!matched->authorized(REQUIRED_PERMISSION))
    {
        sendJsonError(response, Poco::Net::HTTPResponse::HTTP_FORBIDDEN,
                      "当前管理身份没有 diagnostics.read 权限。");
        return false;
    }
    authorization.principal = matched->id;
    authorization.mayExecute = matched->authorized(EXECUTE_PERMISSION);
    response.set("X-PDR-Management-Principal", authorization.principal);
    return true;
}

class TerminalHandler final : public Poco::Net::HTTPRequestHandler
{
public:
    explicit TerminalHandler(Poco::OSP::BundleContext::Ptr context):
        _context(std::move(context))
    {
    }

    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        AuthorizationContext authorization;
        if (!authorize(_context, request, response, authorization)) return;
        response.set("Cache-Control", "no-store");
        response.setContentType("application/json; charset=utf-8");
        if (request.getMethod() == Poco::Net::HTTPRequest::HTTP_GET)
        {
            std::string artifactId;
            for (const auto& parameter : Poco::URI(request.getURI()).getQueryParameters())
                if (parameter.first == "artifact") artifactId = parameter.second;
            if (!artifactId.empty())
            {
                if (safeLogName(artifactId) != artifactId ||
                    artifactId.rfind("support-", 0) != 0 ||
                    artifactId.size() < 6 ||
                    artifactId.substr(artifactId.size() - 5) != ".json")
                {
                    sendJsonError(response, Poco::Net::HTTPResponse::HTTP_BAD_REQUEST,
                                  "诊断包标识非法。");
                    return;
                }
                Poco::Path artifact("data/diagnostics");
                artifact.append(artifactId);
                artifact.makeAbsolute();
                if (!Poco::File(artifact).exists())
                {
                    sendJsonError(response, Poco::Net::HTTPResponse::HTTP_NOT_FOUND,
                                  "诊断包不存在或已清理。");
                    return;
                }
                response.set("Content-Disposition", "attachment; filename=\"" + artifactId + "\"");
                response.sendFile(artifact.toString(), "application/json; charset=utf-8");
                return;
            }
            Poco::JSON::Array::Ptr commands = new Poco::JSON::Array;
            for (const char* command : {"help", "status", "ps", "bundle list",
                 "bundle show", "service list", "service show", "logs runtime --tail 80",
                 "diagnose all", "diagnose bundle", "diagnose service", "diagnose process",
                 "health tree", "provider list", "provider check", "protocol list",
                 "protocol check", "device list", "device check", "metrics top",
                 "metrics anomalies", "trace list", "trace show", "config effective",
                 "config diff", "config validate", "dds participants", "dds discovery",
                 "dds qos", "dds check", "support collect", "agent status",
                 "agent threads", "agent net", "crash list", "crash show",
                 "dump process", "version", "uptime", "whoami",
                 "clear", "history", "watch"})
                commands->add(command);
            Poco::JSON::Object body;
            body.set("service", SERVICE_NAME);
            body.set("mode", "allowlisted-read-only");
            body.set("permission", REQUIRED_PERMISSION);
            body.set("principal", authorization.principal);
            body.set("mayExecute", authorization.mayExecute);
            body.set("prompt", "pdr@" + Poco::Environment::nodeName() + ":runtime$");
            body.set("commands", commands);
            body.stringify(response.send());
            return;
        }
        if (request.getMethod() != Poco::Net::HTTPRequest::HTTP_POST)
        {
            response.set("Allow", "GET, POST");
            sendJsonError(response, Poco::Net::HTTPResponse::HTTP_METHOD_NOT_ALLOWED,
                          "仅支持 GET 和 POST。");
            return;
        }
        if (!commandRateAllowed(authorization.principal))
        {
            sendJsonError(response, Poco::Net::HTTPResponse::HTTP_TOO_MANY_REQUESTS,
                          "诊断命令速率超过每 10 秒 30 次的限制。");
            return;
        }
        try
        {
            Poco::JSON::Parser parser;
            const auto body = parser.parse(request.stream()).extract<Poco::JSON::Object::Ptr>();
            const std::string command = body->getValue<std::string>("command");
            if (command.size() > 512)
                throw Poco::InvalidArgumentException("命令长度不能超过 512 字节");
            const auto commandTokens = tokenize(command);
            const std::string commandVerb = commandTokens.empty() ? "" : lower(commandTokens.front());
            if ((commandVerb == "repair" || commandVerb == "dump") &&
                !authorization.mayExecute)
            {
                sendJsonError(response, Poco::Net::HTTPResponse::HTTP_FORBIDDEN,
                              "该命令需要 diagnostics.execute 权限。");
                return;
            }
            const auto serviceRef = _context->registry().findByName(SERVICE_NAME);
            if (!serviceRef)
                return sendJsonError(response,
                    Poco::Net::HTTPResponse::HTTP_SERVICE_UNAVAILABLE,
                    "诊断命令服务尚未就绪。");
            const auto service = serviceRef->castedInstance<TerminalService>();
            const Poco::Timestamp started;
            auto result = service->execute(command, authorization.principal);
            enforceOutputLimit(result);
            Poco::JSON::Array::Ptr lines = new Poco::JSON::Array;
            for (const auto& line : result.lines) lines->add(line);
            Poco::JSON::Array::Ptr findings = new Poco::JSON::Array;
            for (const auto& finding : result.findings) findings->add(findingJson(finding));
            Poco::JSON::Object::Ptr facts = new Poco::JSON::Object;
            for (const auto& [name, value] : result.facts) facts->set(name, value);
            Poco::JSON::Object reply;
            reply.set("command", command);
            reply.set("exitCode", result.exitCode);
            reply.set("lines", lines);
            reply.set("findings", findings);
            reply.set("facts", facts);
            reply.set("schemaVersion", "pdr.diagnostics.command/2");
            reply.set("principal", authorization.principal);
            reply.set("durationMilliseconds",
                static_cast<double>(started.elapsed()) / 1000.0);
            reply.set("timestampMicroseconds", Poco::Timestamp().epochMicroseconds());
            response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
            reply.stringify(response.send());
            _context->logger().information("Diagnostic terminal command: principal=" +
                authorization.principal + " command=" +
                (commandTokens.empty() ? std::string("empty") : commandTokens.front()) +
                " exitCode=" + Poco::NumberFormatter::format(result.exitCode) +
                " durationMs=" + Poco::NumberFormatter::format(
                    static_cast<double>(started.elapsed()) / 1000.0) +
                " requestId=" + request.get("X-PDR-Request-Id", "none"));
        }
        catch (const std::exception& exception)
        {
            sendJsonError(response, Poco::Net::HTTPResponse::HTTP_BAD_REQUEST, exception.what());
        }
    }

private:
    Poco::OSP::BundleContext::Ptr _context;
};

class DiagnosticStreamHandler final : public Poco::Net::HTTPRequestHandler
{
public:
    explicit DiagnosticStreamHandler(Poco::OSP::BundleContext::Ptr context):
        _context(std::move(context))
    {
    }

    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        AuthorizationContext authorization;
        if (!authorize(_context, request, response, authorization)) return;
        if (request.getMethod() != Poco::Net::HTTPRequest::HTTP_GET)
        {
            response.set("Allow", "GET");
            sendJsonError(response, Poco::Net::HTTPResponse::HTTP_METHOD_NOT_ALLOWED,
                          "日志流仅支持 GET。");
            return;
        }
        if (_activeStreams.fetch_add(1) >= 4)
        {
            --_activeStreams;
            sendJsonError(response, Poco::Net::HTTPResponse::HTTP_TOO_MANY_REQUESTS,
                          "实时诊断流已达到并发上限 4。");
            return;
        }
        StreamGuard guard;

        try
        {
            std::map<std::string, std::string> parameters;
            for (const auto& parameter : Poco::URI(request.getURI()).getQueryParameters())
                parameters[parameter.first] = parameter.second;
            std::string process = parameters.count("process") ? parameters["process"] : "runtime";
            int tail = parameters.count("tail") ? std::stoi(parameters["tail"]) : 40;
            int durationSeconds = parameters.count("duration") ?
                std::stoi(parameters["duration"]) : 30;
            tail = std::max(0, std::min(tail, 500));
            durationSeconds = std::max(1, std::min(durationSeconds, 60));
            const std::string filter = parameters.count("grep") ? parameters["grep"] : "";
            if (lower(process) == "runtime" || process ==
                Poco::NumberFormatter::format(Poco::Process::id())) process = "pdr-runtime";
            bool known = process == "pdr-runtime";
            if (auto* manager = PocoDDS::ProcessManagement::SubprocessManager::active())
                for (const auto& item : manager->processes())
                    if (item.name == process || Poco::NumberFormatter::format(item.processId) == process)
                    {
                        process = item.name;
                        known = true;
                        break;
                    }
            if (!known)
            {
                sendJsonError(response, Poco::Net::HTTPResponse::HTTP_BAD_REQUEST,
                              "未知进程；只允许跟踪 Runtime 或已托管子进程日志。");
                return;
            }
            Poco::Path path("logs");
            path.append(safeLogName(process) + ".log");
            path.makeAbsolute();
            if (!Poco::File(path).exists())
            {
                sendJsonError(response, Poco::Net::HTTPResponse::HTTP_NOT_FOUND,
                              "日志文件尚不存在。");
                return;
            }

            response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
            response.setContentType("text/event-stream; charset=utf-8");
            response.set("Cache-Control", "no-store");
            response.set("X-Accel-Buffering", "no");
            auto& output = response.send();
            const auto sendEvent = [&](const std::string& type, const std::string& line) {
                Poco::JSON::Object event;
                event.set("type", type);
                event.set("process", process);
                event.set("line", redactedLogLine(line));
                event.set("timestampMicroseconds", Poco::Timestamp().epochMicroseconds());
                std::ostringstream json;
                event.stringify(json);
                output << "event: " << type << "\ndata: " << json.str() << "\n\n";
                output.flush();
            };

            std::ifstream initial(path.toString());
            std::deque<std::string> selected;
            std::string line;
            while (std::getline(initial, line))
            {
                if (!containsInsensitive(line, filter)) continue;
                selected.push_back(line);
                if (selected.size() > static_cast<std::size_t>(tail)) selected.pop_front();
            }
            for (const auto& value : selected) sendEvent("log", value);
            std::uintmax_t position = Poco::File(path).getSize();
            const Poco::Timestamp started;
            Poco::Timestamp lastHeartbeat;
            std::size_t emitted = selected.size();
            while (started.elapsed() < static_cast<Poco::Timestamp::TimeDiff>(
                       durationSeconds) * 1000000 && emitted < 2000)
            {
                Poco::Thread::sleep(250);
                const std::uintmax_t size = Poco::File(path).exists() ? Poco::File(path).getSize() : 0;
                if (size < position) position = 0;
                if (size > position)
                {
                    std::ifstream stream(path.toString());
                    stream.seekg(static_cast<std::streamoff>(position));
                    while (std::getline(stream, line) && emitted < 2000)
                    {
                        if (!containsInsensitive(line, filter)) continue;
                        sendEvent("log", line);
                        ++emitted;
                    }
                    position = size;
                }
                if (lastHeartbeat.elapsed() >= 5000000)
                {
                    sendEvent("heartbeat", "");
                    lastHeartbeat.update();
                }
            }
            sendEvent("end", emitted >= 2000 ? "output-limit" : "duration-complete");
            _context->logger().information("Diagnostic log stream: principal=" +
                authorization.principal + " process=" + process + " lines=" +
                Poco::NumberFormatter::format(emitted));
        }
        catch (const std::exception& exception)
        {
            try
            {
                _context->logger().warning("Diagnostic log stream ended: " +
                                           std::string(exception.what()));
            }
            catch (...) {}
        }
    }

private:
    struct StreamGuard
    {
        ~StreamGuard() { --_activeStreams; }
    };
    Poco::OSP::BundleContext::Ptr _context;
    static std::atomic<unsigned> _activeStreams;
};

std::atomic<unsigned> DiagnosticStreamHandler::_activeStreams{0};
} // namespace

class TerminalHandlerFactory final : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new TerminalHandler(context());
    }
};

class DiagnosticStreamHandlerFactory final : public Poco::OSP::Web::WebRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new DiagnosticStreamHandler(context());
    }
};

class BundleActivator final : public Poco::OSP::BundleActivator
{
public:
    void start(Poco::OSP::BundleContext::Ptr context) override
    {
        _service = new TerminalService(context);
        Poco::OSP::Properties properties;
        properties.set("pdr.service", "diagnosticTerminal");
        properties.set("pdr.diagnostics", "terminal");
        properties.set("pdr.bundle", context->thisBundle()->symbolicName());
        properties.set("mode", "allowlisted-read-only");
        _serviceRef = context->registry().registerService(SERVICE_NAME, _service, properties);
        _provider = new RuntimeDiagnosticProvider(context);
        Poco::OSP::Properties providerProperties;
        providerProperties.set(DiagnosticProvider::SERVICE_PROPERTY, "true");
        providerProperties.set("pdr.bundle", context->thisBundle()->symbolicName());
        providerProperties.set("pdr.diagnostics.provider.id", _provider->providerId());
        _providerRef = context->registry().registerService(
            "pdr.diagnostics.provider.runtime", _provider, providerProperties);
        context->logger().information(
            "Controlled diagnostic terminal started; operating-system shell execution is disabled.");
    }

    void stop(Poco::OSP::BundleContext::Ptr context) override
    {
        if (_providerRef) context->registry().unregisterService(_providerRef);
        _providerRef = nullptr;
        _provider = nullptr;
        if (_serviceRef) context->registry().unregisterService(_serviceRef);
        _serviceRef = nullptr;
        _service = nullptr;
    }

private:
    Poco::AutoPtr<TerminalService> _service;
    Poco::OSP::ServiceRef::Ptr _serviceRef;
    Poco::AutoPtr<RuntimeDiagnosticProvider> _provider;
    Poco::OSP::ServiceRef::Ptr _providerRef;
};
} // namespace PocoDDS::DiagnosticTerminal

POCO_BEGIN_MANIFEST(Poco::OSP::BundleActivator)
    POCO_EXPORT_CLASS(PocoDDS::DiagnosticTerminal::BundleActivator)
POCO_END_MANIFEST

POCO_BEGIN_NAMED_MANIFEST(WebServer, Poco::OSP::Web::WebRequestHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::DiagnosticTerminal::TerminalHandlerFactory)
    POCO_EXPORT_CLASS(PocoDDS::DiagnosticTerminal::DiagnosticStreamHandlerFactory)
POCO_END_MANIFEST
