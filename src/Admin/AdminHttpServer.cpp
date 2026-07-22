#include "PocoDDS/Admin/AdminHttpServer.h"

#include <Poco/JSON/Array.h>
#include <Poco/JSON/Object.h>
#include <Poco/JSON/Parser.h>
#include <Poco/Net/HTTPRequestHandler.h>
#include <Poco/Net/HTTPRequestHandlerFactory.h>
#include <Poco/Net/HTTPServer.h>
#include <Poco/Net/HTTPServerRequest.h>
#include <Poco/Net/HTTPServerResponse.h>
#include <Poco/Net/ServerSocket.h>
#include <Poco/Net/SocketAddress.h>
#include <Poco/URI.h>

#include <chrono>
#include <sstream>
#include <stdexcept>
#include <utility>

namespace PocoDDS::Admin
{
namespace
{
using Poco::JSON::Array;
using Poco::JSON::Object;
using Poco::Net::HTTPServerRequest;
using Poco::Net::HTTPServerResponse;

const char AdminPage[] = R"HTML(<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PocoDDS Runtime</title><style>
:root{color-scheme:dark;--bg:#0b1020;--panel:#121a2e;--line:#293653;--text:#e5ecff;--muted:#91a0bd;--ok:#4ade80;--bad:#fb7185;--accent:#60a5fa}
*{box-sizing:border-box}body{margin:0;font:14px system-ui;background:var(--bg);color:var(--text)}header{display:flex;gap:18px;align-items:center;padding:16px 24px;border-bottom:1px solid var(--line)}header b{font-size:18px}button,input{background:#17223a;color:var(--text);border:1px solid var(--line);border-radius:6px;padding:8px}button{cursor:pointer}.tabs button.active{border-color:var(--accent)}main{padding:20px}.view{display:none}.view.active{display:block}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}.card,table,pre{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:9px;border-bottom:1px solid var(--line)}.muted{color:var(--muted)}.ok{color:var(--ok)}.bad{color:var(--bad)}#traceGraph{width:100%;height:480px;background:var(--panel);border:1px solid var(--line)}
</style></head><body><header><b>PocoDDS Runtime</b><span class="muted">Local administration</span><div class="tabs"><button data-view="topology" class="active">拓扑</button><button data-view="logs">日志</button><button data-view="config">配置</button><button data-view="traces">业务追踪</button></div></header><main>
<section id="topology" class="view active"><h2>进程 / 服务 / Bundle / 模块</h2><div id="components" class="grid"></div></section>
<section id="logs" class="view"><h2>日志</h2><input id="logComponent" placeholder="组件 ID"><button onclick="loadLogs()">查询</button><table><thead><tr><th>时间</th><th>组件</th><th>级别</th><th>消息</th><th>Trace</th></tr></thead><tbody id="logRows"></tbody></table></section>
<section id="config" class="view"><h2>实时配置</h2><p><input id="configTarget" placeholder="目标组件 ID；留空表示本地运行时"><input id="configRevision" type="number" min="0" value="0" title="期望配置版本"></p><div id="configRows"></div><button onclick="addConfig()">添加配置项</button> <button onclick="saveConfig()">立即应用</button></section>
<section id="traces" class="view"><h2>业务流程</h2><select id="traceIds" onchange="loadTrace()"></select><svg id="traceGraph"></svg><pre id="traceDetail">点击节点查看输入、输出、状态、耗时和日志</pre></section>
</main><script>
let token=sessionStorage.getItem('pdrToken')||prompt('管理令牌');if(token)sessionStorage.setItem('pdrToken',token);
const api=async(path,opt={})=>{opt.headers={...(opt.headers||{}),Authorization:'Bearer '+token};let r=await fetch(path,opt);if(!r.ok)throw new Error((await r.json()).error||r.statusText);return r.json()};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function showView(id){document.querySelectorAll('.tabs button,.view').forEach(x=>x.classList.remove('active'));document.querySelector(`.tabs button[data-view="${id}"]`).classList.add('active');document.getElementById(id).classList.add('active')}
document.querySelectorAll('.tabs button').forEach(b=>b.onclick=()=>showView(b.dataset.view));
async function loadTopology(){let d=await api('/api/v1/topology');components.textContent='';d.components.forEach(c=>{let a=document.createElement('article');a.className='card';let b=document.createElement('b');b.textContent=c.name;a.append(b);let p=document.createElement('p');p.className='muted';p.textContent=`${c.id} · ${c.kind} · ${c.host}:${c.processId}`;a.append(p);p=document.createElement('p');p.className=c.state==='running'?'ok':'';p.textContent=c.state;a.append(p);[['restart','重启'],['stop','停止'],['uninstall','卸载']].forEach(([x,t])=>{let q=document.createElement('button');q.textContent=t;q.onclick=()=>life(c.id,x);a.append(q,' ')});let q=document.createElement('button');q.textContent='配置';q.onclick=()=>openConfig(c.id);a.append(q,' ');q=document.createElement('button');q.textContent='日志';q.onclick=()=>openLogs(c.id);a.append(q);components.append(a)})}
async function life(id,action){await api('/api/v1/lifecycle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({targetId:id,action})});await loadTopology()}
async function loadLogs(){let q=logComponent.value?'?component='+encodeURIComponent(logComponent.value):'';let d=await api('/api/v1/logs'+q);logRows.innerHTML=d.logs.map(x=>`<tr><td>${esc(new Date(x.timestamp).toLocaleString())}</td><td>${esc(x.componentId)}</td><td>${esc(x.level)}</td><td>${esc(x.message)}</td><td>${esc(x.traceId)}</td></tr>`).join('')}
function openLogs(id){logComponent.value=id;showView('logs');loadLogs().catch(e=>alert(e.message))}
async function loadConfig(){let d=await api('/api/v1/config');configRevision.value=d.revision;configRows.innerHTML=Object.entries(d.values).map(([k,v])=>`<p><input class="config-key" value="${esc(k)}" placeholder="键"> <input class="config-value" value="${esc(v)}" placeholder="值"></p>`).join('')||'<p class="muted">暂无本地配置；可添加配置项并指定远程组件</p>'}
function addConfig(){let p=document.createElement('p');p.innerHTML='<input class="config-key" placeholder="键"> <input class="config-value" placeholder="值">';configRows.append(p)}
function openConfig(id){configTarget.value=id;configRevision.value=0;configRows.textContent='';addConfig();showView('config')}
async function saveConfig(){let changes={};document.querySelectorAll('#configRows p').forEach(p=>{let k=p.querySelector('.config-key'),v=p.querySelector('.config-value');if(k&&k.value)changes[k.value]=v.value});let d=await api('/api/v1/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({targetComponentId:configTarget.value,expectedRevision:Number(configRevision.value),changes})});configRevision.value=d.revision;if(!configTarget.value)await loadConfig()}
async function loadTraceIds(){let d=await api('/api/v1/traces');traceIds.innerHTML=d.traceIds.map(x=>`<option>${x}</option>`).join('');if(d.traceIds.length)loadTrace()}
async function loadTrace(){let d=await api('/api/v1/traces/'+encodeURIComponent(traceIds.value)),svg=traceGraph;svg.innerHTML='';d.nodes.forEach((n,i)=>{let y=30+i*90,p=d.nodes.findIndex(x=>x.spanId===n.parentSpanId);if(p>=0)svg.innerHTML+=`<line x1="180" y1="${30+p*90+24}" x2="180" y2="${y}" stroke="#60a5fa"/>`;svg.innerHTML+=`<g data-i="${i}"><rect x="30" y="${y}" width="300" height="52" rx="7" fill="#17223a" stroke="${n.status==='success'?'#4ade80':'#fb7185'}"/><text x="45" y="${y+22}" fill="#e5ecff">${esc(n.operation)}</text><text x="45" y="${y+42}" fill="#91a0bd">${esc(n.componentId)} · ${(n.durationNanoseconds/1e6).toFixed(2)} ms</text></g>`});svg.querySelectorAll('g').forEach(g=>g.onclick=()=>traceDetail.textContent=JSON.stringify(d.nodes[g.dataset.i],null,2))}
Promise.all([loadTopology(),loadLogs(),loadConfig(),loadTraceIds()]).catch(e=>alert(e.message));setInterval(loadTopology,3000);
</script></body></html>)HTML";

bool constantTimeEqual(const std::string& first, const std::string& second)
{
    std::size_t difference = first.size() ^ second.size();
    const auto count = std::max(first.size(), second.size());
    for (std::size_t index = 0; index < count; ++index)
    {
        const auto left = index < first.size() ? static_cast<unsigned char>(first[index]) : 0;
        const auto right = index < second.size() ? static_cast<unsigned char>(second[index]) : 0;
        difference |= left ^ right;
    }
    return difference == 0;
}

std::string kindName(Core::ComponentKind kind)
{
    switch (kind)
    {
    case Core::ComponentKind::Process:
        return "process";
    case Core::ComponentKind::Service:
        return "service";
    case Core::ComponentKind::Bundle:
        return "bundle";
    case Core::ComponentKind::Module:
        return "module";
    }
    return "unknown";
}

std::string stateName(Core::ComponentState state)
{
    switch (state)
    {
    case Core::ComponentState::Discovered:
        return "discovered";
    case Core::ComponentState::Starting:
        return "starting";
    case Core::ComponentState::Running:
        return "running";
    case Core::ComponentState::Stopping:
        return "stopping";
    case Core::ComponentState::Stopped:
        return "stopped";
    case Core::ComponentState::Failed:
        return "failed";
    }
    return "unknown";
}

void sendJson(HTTPServerResponse& response, const Object& object,
              HTTPServerResponse::HTTPStatus status = HTTPServerResponse::HTTP_OK)
{
    response.setStatus(status);
    response.setContentType("application/json; charset=utf-8");
    response.set("Cache-Control", "no-store");
    object.stringify(response.send());
}

template <typename Value> Object singleValue(const std::string& key, const Value& value)
{
    Object object;
    object.set(key, value);
    return object;
}

Object stringMap(const std::map<std::string, std::string>& values)
{
    Object object;
    for (const auto& value : values)
        object.set(value.first, value.second);
    return object;
}

Object::Ptr parseObject(HTTPServerRequest& request, std::size_t maximumBytes)
{
    if (request.getContentLength64() < 0 ||
        static_cast<std::uint64_t>(request.getContentLength64()) > maximumBytes)
        throw std::invalid_argument("request body is too large or has no length");
    return Poco::JSON::Parser().parse(request.stream()).extract<Object::Ptr>();
}

class RequestHandler final : public Poco::Net::HTTPRequestHandler
{
  public:
    RequestHandler(AdminService& service, const AdminHttpOptions& options)
        : _service(service), _options(options)
    {
    }

    void handleRequest(HTTPServerRequest& request, HTTPServerResponse& response) override
    {
        response.set("X-Content-Type-Options", "nosniff");
        response.set("X-Frame-Options", "DENY");
        response.set("Content-Security-Policy",
                     "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'");
        Poco::URI uri(request.getURI());
        if (request.getMethod() == "GET" && uri.getPath() == "/")
        {
            response.setContentType("text/html; charset=utf-8");
            response.set("Cache-Control", "no-store");
            response.send() << AdminPage;
            return;
        }
        const auto expected = "Bearer " + _options.bearerToken;
        if (!constantTimeEqual(request.get("Authorization", ""), expected))
        {
            response.set("WWW-Authenticate", "Bearer");
            sendJson(response, singleValue("error", "unauthorized"),
                     HTTPServerResponse::HTTP_UNAUTHORIZED);
            return;
        }
        try
        {
            route(request, response);
        }
        catch (const std::exception& exception)
        {
            sendJson(response, singleValue("error", exception.what()),
                     HTTPServerResponse::HTTP_BAD_REQUEST);
        }
    }

  private:
    void route(HTTPServerRequest& request, HTTPServerResponse& response)
    {
        Poco::URI uri(request.getURI());
        const auto path = uri.getPath();
        if (request.getMethod() == "GET" && path == "/api/v1/topology")
            return topology(response);
        if (request.getMethod() == "GET" && path == "/api/v1/config")
            return configuration(response);
        if (request.getMethod() == "PUT" && path == "/api/v1/config")
            return updateConfiguration(request, response);
        if (request.getMethod() == "POST" && path == "/api/v1/lifecycle")
            return lifecycle(request, response);
        if (request.getMethod() == "GET" && path == "/api/v1/logs")
            return logs(uri, response);
        if (request.getMethod() == "GET" && path == "/api/v1/traces")
            return traces(response);
        const std::string prefix = "/api/v1/traces/";
        if (request.getMethod() == "GET" && path.rfind(prefix, 0) == 0)
        {
            std::string decoded;
            Poco::URI::decode(path.substr(prefix.size()), decoded);
            return trace(decoded, response);
        }
        sendJson(response, singleValue("error", "not found"), HTTPServerResponse::HTTP_NOT_FOUND);
    }

    void topology(HTTPServerResponse& response)
    {
        Array components;
        for (const auto& component : _service.topology())
        {
            Object value;
            value.set("id", component.id);
            value.set("name", component.name);
            value.set("host", component.host);
            value.set("processId", component.processId);
            value.set("kind", kindName(component.kind));
            value.set("state", stateName(component.state));
            value.set("metadata", stringMap(component.metadata));
            components.add(value);
        }
        sendJson(response, singleValue("components", components));
    }

    void configuration(HTTPServerResponse& response)
    {
        Object value;
        value.set("values", stringMap(_service.configuration()));
        value.set("revision", _service.configurationRevision());
        sendJson(response, value);
    }

    void updateConfiguration(HTTPServerRequest& request, HTTPServerResponse& response)
    {
        auto body = parseObject(request, _options.maximumRequestBytes);
        auto changes = body->getObject("changes");
        if (!changes)
            throw std::invalid_argument("changes object is required");
        Core::Configuration::Values values;
        for (const auto& item : *changes)
            values[item.first] = item.second.convert<std::string>();
        const auto target = body->has("targetComponentId")
                                ? body->getValue<std::string>("targetComponentId")
                                : std::string{};
        const auto revision =
            body->has("expectedRevision") ? body->getValue<std::uint64_t>("expectedRevision") : 0;
        const auto result = _service.applyConfiguration(target, values, revision);
        Object responseBody;
        responseBody.set("applied", result.success);
        responseBody.set("message", result.message);
        responseBody.set("revision", result.revision);
        sendJson(response, responseBody,
                 result.success ? HTTPServerResponse::HTTP_OK : HTTPServerResponse::HTTP_CONFLICT);
    }

    void lifecycle(HTTPServerRequest& request, HTTPServerResponse& response)
    {
        auto body = parseObject(request, _options.maximumRequestBytes);
        auto result = _service.execute(body->getValue<std::string>("targetId"),
                                       body->getValue<std::string>("action"));
        Object value;
        value.set("success", result.success);
        value.set("message", result.message);
        sendJson(response, value,
                 result.success ? HTTPServerResponse::HTTP_OK : HTTPServerResponse::HTTP_CONFLICT);
    }

    void logs(const Poco::URI& uri, HTTPServerResponse& response)
    {
        std::optional<std::string> component;
        std::optional<std::string> traceId;
        for (const auto& parameter : uri.getQueryParameters())
        {
            if (parameter.first == "component")
                component = parameter.second;
            if (parameter.first == "traceId")
                traceId = parameter.second;
        }
        Array values;
        for (const auto& record : _service.logs(component, traceId))
        {
            Object value;
            value.set("timestamp", std::chrono::duration_cast<std::chrono::milliseconds>(
                                       record.timestamp.time_since_epoch())
                                       .count());
            value.set("componentId", record.componentId);
            value.set("level", record.level);
            value.set("message", record.message);
            value.set("traceId", record.traceId);
            value.set("spanId", record.spanId);
            values.add(value);
        }
        sendJson(response, singleValue("logs", values));
    }

    void traces(HTTPServerResponse& response)
    {
        Array ids;
        for (const auto& id : _service.recentTraceIds())
            ids.add(id);
        sendJson(response, singleValue("traceIds", ids));
    }

    void trace(const std::string& traceId, HTTPServerResponse& response)
    {
        Array nodes;
        for (const auto& node : _service.trace(traceId))
        {
            Object value;
            value.set("traceId", node.traceId);
            value.set("spanId", node.spanId);
            value.set("parentSpanId", node.parentSpanId);
            value.set("operation", node.operation);
            value.set("componentId", node.componentId);
            value.set("status", node.status);
            value.set("durationNanoseconds", node.durationNanoseconds);
            value.set("inputs", stringMap(node.inputs));
            value.set("outputs", stringMap(node.outputs));
            nodes.add(value);
        }
        sendJson(response, singleValue("nodes", nodes));
    }

    AdminService& _service;
    AdminHttpOptions _options;
};

class HandlerFactory final : public Poco::Net::HTTPRequestHandlerFactory
{
  public:
    HandlerFactory(AdminService& service, AdminHttpOptions options)
        : _service(service), _options(std::move(options))
    {
    }

    Poco::Net::HTTPRequestHandler* createRequestHandler(const HTTPServerRequest&) override
    {
        return new RequestHandler(_service, _options);
    }

  private:
    AdminService& _service;
    AdminHttpOptions _options;
};
} // namespace

class AdminHttpServer::Impl
{
  public:
    Impl(AdminService& service, AdminHttpOptions options) : _options(std::move(options))
    {
        if (_options.bearerToken.size() < 16)
            throw std::invalid_argument("admin bearer token must contain at least 16 characters");
        Poco::Net::ServerSocket socket(
            Poco::Net::SocketAddress(_options.bindAddress, _options.port));
        _port = socket.address().port();
        _server = std::make_unique<Poco::Net::HTTPServer>(new HandlerFactory(service, _options),
                                                          socket, new Poco::Net::HTTPServerParams);
    }

    void start()
    {
        if (!_started)
        {
            _server->start();
            _started = true;
        }
    }

    void stop()
    {
        if (_started)
        {
            _server->stop();
            _started = false;
        }
    }

    AdminHttpOptions _options;
    std::unique_ptr<Poco::Net::HTTPServer> _server;
    std::uint16_t _port{};
    bool _started{false};
};

AdminHttpServer::AdminHttpServer(AdminService& service, AdminHttpOptions options)
    : _impl(std::make_unique<Impl>(service, std::move(options)))
{
}

AdminHttpServer::~AdminHttpServer() { _impl->stop(); }

void AdminHttpServer::start() { _impl->start(); }

void AdminHttpServer::stop() { _impl->stop(); }

std::uint16_t AdminHttpServer::port() const { return _impl->_port; }
} // namespace PocoDDS::Admin
