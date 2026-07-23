#include "PocoDDS/Observability/TraceHttpServer.h"

#include <Poco/JSON/Array.h>
#include <Poco/JSON/Object.h>
#include <Poco/Net/HTTPRequestHandler.h>
#include <Poco/Net/HTTPRequestHandlerFactory.h>
#include <Poco/Net/HTTPServer.h>
#include <Poco/Net/HTTPServerRequest.h>
#include <Poco/Net/HTTPServerResponse.h>
#include <Poco/Net/ServerSocket.h>
#include <Poco/Net/SocketAddress.h>
#include <Poco/URI.h>

#include <algorithm>
#include <memory>
#include <utility>

namespace PocoDDS::Observability
{
namespace
{
using Poco::JSON::Array;
using Poco::JSON::Object;
using Poco::Net::HTTPServerRequest;
using Poco::Net::HTTPServerResponse;

const char TracePage[] = R"HTML(<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PocoDDS 业务追踪</title><style>
:root{--bg:#08111f;--panel:#101c2e;--panel2:#15243a;--line:#2a3d59;--text:#edf4ff;--muted:#94a7c4;--run:#38bdf8;--ok:#34d399;--bad:#fb7185;--cancel:#a8b1c2}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px Inter,system-ui,sans-serif}header{height:64px;display:flex;align-items:center;padding:0 24px;border-bottom:1px solid var(--line);gap:16px}header h1{font-size:18px;margin:0}header span{color:var(--muted)}main{display:grid;grid-template-columns:320px minmax(500px,1fr) 390px;height:calc(100vh - 64px)}aside,section{min-width:0;border-right:1px solid var(--line);overflow:auto}.title{padding:18px 20px 10px;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em}.trace{margin:6px 10px;padding:12px;border:1px solid transparent;border-radius:10px;background:var(--panel);cursor:pointer}.trace:hover,.trace.active{border-color:#4b78ae}.trace b{display:block;margin-bottom:5px}.meta{font-size:12px;color:var(--muted)}.badge{float:right;padding:2px 7px;border-radius:999px;font-size:11px}.success{color:var(--ok)}.failed{color:var(--bad)}.running{color:var(--run)}.cancelled{color:var(--cancel)}#canvas{position:relative;min-width:900px;min-height:700px;padding:40px}.node{position:absolute;width:220px;min-height:78px;padding:12px;background:var(--panel2);border:2px solid var(--line);border-radius:10px;cursor:pointer;z-index:2;box-shadow:0 8px 24px #0005}.node:hover,.node.active{transform:translateY(-2px);filter:brightness(1.15)}.node.success{border-color:var(--ok)}.node.failed{border-color:var(--bad)}.node.running{border-color:var(--run)}.node.cancelled{border-color:var(--cancel)}.node b{display:block;color:var(--text);margin-bottom:7px}.node small{display:block;color:var(--muted)}svg{position:absolute;inset:0;width:100%;height:100%;z-index:1;pointer-events:none}.detail{padding:8px 18px 24px}.detail h2{font-size:17px}.group{margin:16px 0}.group h3{font-size:12px;color:var(--muted);text-transform:uppercase}.kv,.log{background:var(--panel);padding:10px;border-radius:7px;margin:6px 0;overflow-wrap:anywhere}.kv label{color:#8eb9ee}.empty{color:var(--muted);padding:20px}.toolbar{margin-left:auto}.toolbar input{background:var(--panel);border:1px solid var(--line);border-radius:7px;color:var(--text);padding:8px;width:220px}
</style></head><body><header><h1>OpenTelemetry 业务追踪</h1><span>流程、参数、状态、耗时与关联日志</span><div class="toolbar"><input id="token" type="password" placeholder="Bearer Token（如已配置）"></div></header>
<main><aside><div class="title">业务实例</div><div id="traces"></div></aside><section><div class="title" id="flowTitle">选择一个业务实例</div><div id="canvas"><svg id="edges"></svg></div></section><aside><div class="title">节点详情</div><div id="detail" class="detail empty">点击流程节点查看详情</div></aside></main>
<script>
const $=id=>document.getElementById(id), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
token.value=sessionStorage.pdrTraceToken||'';token.onchange=()=>{sessionStorage.pdrTraceToken=token.value;loadList()};
const api=async p=>{let h={};if(token.value)h.Authorization='Bearer '+token.value;let r=await fetch(p,{headers:h});if(!r.ok)throw Error((await r.json()).error||r.statusText);return r.json()};
let selectedTrace='', nodes=[];
const duration=n=>n.status==='running'?'执行中':(n.durationNanoseconds/1e6).toFixed(3)+' ms';
async function loadList(){try{let d=await api('/api/v1/business-traces');traces.innerHTML=d.traces.map(t=>`<div class="trace ${t.traceId===selectedTrace?'active':''}" data-id="${esc(t.traceId)}"><span class="badge ${esc(t.status)}">${esc(t.status)}</span><b>${esc(t.businessName)}</b><div class="meta">${esc(t.businessInstanceId)}</div><div class="meta">${t.stepCount} 个节点 · ${new Date(t.startedUnixMicroseconds/1000).toLocaleString()}</div></div>`).join('')||'<div class="empty">还没有业务追踪数据</div>';document.querySelectorAll('.trace').forEach(x=>x.onclick=()=>loadTrace(x.dataset.id))}catch(e){traces.innerHTML='<div class="empty">'+esc(e.message)+'</div>'}}
function depth(n,map){let d=0,p=n;while(p.parentSpanId&&map[p.parentSpanId]&&d<20){d++;p=map[p.parentSpanId]}return d}
async function loadTrace(id){selectedTrace=id;let d=await api('/api/v1/business-traces/'+encodeURIComponent(id));nodes=d.nodes;flowTitle.textContent=(nodes[0]?.businessName||'业务流程')+' · '+id;draw();loadList()}
function draw(){let map=Object.fromEntries(nodes.map(n=>[n.spanId,n])),levels={};nodes.forEach(n=>{let d=depth(n,map);(levels[d]??=[]).push(n)});let canvas=$('canvas');canvas.querySelectorAll('.node').forEach(x=>x.remove());let pos={};Object.entries(levels).forEach(([d,list])=>list.forEach((n,i)=>{let x=40+Number(d)*270,y=40+i*125;pos[n.spanId]={x,y};let el=document.createElement('div');el.className='node '+n.status;el.style.left=x+'px';el.style.top=y+'px';el.innerHTML=`<b>${esc(n.operation)}</b><small>${esc(n.serviceName)}${n.bundleName?' · '+esc(n.bundleName):''}</small><small>${esc(n.status)} · ${duration(n)}</small>`;el.onclick=()=>show(n,el);canvas.append(el)}));let w=Math.max(900,...Object.values(pos).map(p=>p.x+260)),h=Math.max(700,...Object.values(pos).map(p=>p.y+130));canvas.style.width=w+'px';canvas.style.height=h+'px';edges.setAttribute('viewBox',`0 0 ${w} ${h}`);edges.innerHTML=nodes.filter(n=>n.parentSpanId&&pos[n.parentSpanId]).map(n=>{let a=pos[n.parentSpanId],b=pos[n.spanId];return `<path d="M ${a.x+220} ${a.y+39} C ${a.x+245} ${a.y+39},${b.x-25} ${b.y+39},${b.x} ${b.y+39}" fill="none" stroke="#45698f" stroke-width="2"/><path d="M ${b.x-8} ${b.y+34} L ${b.x} ${b.y+39} L ${b.x-8} ${b.y+44}" fill="none" stroke="#45698f" stroke-width="2"/>`}).join('')}
const fields=o=>Object.entries(o||{}).map(([k,v])=>`<div class="kv"><label>${esc(k)}</label><br>${esc(v)}</div>`).join('')||'<div class="empty">无</div>';
function show(n,el){document.querySelectorAll('.node').forEach(x=>x.classList.remove('active'));el.classList.add('active');detail.className='detail';detail.innerHTML=`<h2>${esc(n.operation)}</h2><div class="${esc(n.status)}">${esc(n.status)} · ${duration(n)}</div><div class="meta">${esc(n.hostName)} · PID ${n.processId}<br>Trace ${esc(n.traceId)}<br>Span ${esc(n.spanId)}</div>${n.errorMessage?`<div class="group"><h3>失败信息</h3><div class="kv">${esc(n.errorCode)}<br>${esc(n.errorMessage)}</div></div>`:''}<div class="group"><h3>传入参数</h3>${fields(n.inputs)}</div><div class="group"><h3>传出参数</h3>${fields(n.outputs)}</div><div class="group"><h3>关联日志</h3>${(n.logs||[]).map(l=>`<div class="log"><span class="${esc(l.level)}">${esc(l.level)}</span> · ${new Date(l.timestampUnixMicroseconds/1000).toLocaleTimeString()}<br>${esc(l.message)}${fields(l.fields)}</div>`).join('')||'<div class="empty">无</div>'}</div>`}
loadList();setInterval(()=>{loadList();if(selectedTrace)loadTrace(selectedTrace)},2000);
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

Object fieldObject(const Fields& fields)
{
    Object result;
    for (const auto& field : fields)
        result.set(field.first, field.second);
    return result;
}

Object logObject(const TraceLog& log)
{
    Object value;
    value.set("timestampUnixMicroseconds", log.timestampUnixMicroseconds);
    value.set("level", log.level);
    value.set("message", log.message);
    value.set("fields", fieldObject(log.fields));
    return value;
}

Object spanObject(const SpanSnapshot& span)
{
    Object value;
    value.set("businessName", span.businessName);
    value.set("businessInstanceId", span.businessInstanceId);
    value.set("operation", span.operation);
    value.set("serviceName", span.serviceName);
    value.set("bundleName", span.bundleName);
    value.set("hostName", span.hostName);
    value.set("processId", span.processId);
    value.set("traceId", span.traceId);
    value.set("spanId", span.spanId);
    value.set("parentSpanId", span.parentSpanId);
    value.set("status", span.status);
    value.set("errorCode", span.errorCode);
    value.set("errorMessage", span.errorMessage);
    value.set("startedUnixMicroseconds", span.startedUnixMicroseconds);
    value.set("endedUnixMicroseconds", span.endedUnixMicroseconds);
    value.set("durationNanoseconds", span.durationNanoseconds);
    value.set("inputs", fieldObject(span.inputs));
    value.set("outputs", fieldObject(span.outputs));
    Array logs;
    for (const auto& log : span.logs)
        logs.add(logObject(log));
    value.set("logs", logs);
    return value;
}

void sendJson(HTTPServerResponse& response, const Object& object,
              HTTPServerResponse::HTTPStatus status = HTTPServerResponse::HTTP_OK)
{
    response.setStatus(status);
    response.setContentType("application/json; charset=utf-8");
    response.set("Cache-Control", "no-store");
    object.stringify(response.send());
}

class Handler final : public Poco::Net::HTTPRequestHandler
{
public:
    Handler(TraceStore& store, TraceHttpOptions options)
        : _store(store), _options(std::move(options))
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
            response.send() << TracePage;
            return;
        }
        if (!_options.bearerToken.empty() &&
            !constantTimeEqual(request.get("Authorization", ""),
                               "Bearer " + _options.bearerToken))
        {
            Object error;
            error.set("error", "unauthorized");
            sendJson(response, error, HTTPServerResponse::HTTP_UNAUTHORIZED);
            return;
        }
        const std::string prefix = "/api/v1/business-traces/";
        if (request.getMethod() == "GET" && uri.getPath() == "/api/v1/business-traces")
        {
            Array traces;
            for (const auto& summary : _store.recent())
            {
                Object value;
                value.set("traceId", summary.traceId);
                value.set("businessName", summary.businessName);
                value.set("businessInstanceId", summary.businessInstanceId);
                value.set("status", summary.status);
                value.set("startedUnixMicroseconds", summary.startedUnixMicroseconds);
                value.set("durationNanoseconds", summary.durationNanoseconds);
                value.set("stepCount", summary.stepCount);
                value.set("failedOperation", summary.failedOperation);
                traces.add(value);
            }
            Object body;
            body.set("traces", traces);
            sendJson(response, body);
            return;
        }
        if (request.getMethod() == "GET" && uri.getPath().rfind(prefix, 0) == 0)
        {
            std::string traceId;
            Poco::URI::decode(uri.getPath().substr(prefix.size()), traceId);
            Array nodes;
            for (const auto& span : _store.trace(traceId))
                nodes.add(spanObject(span));
            Object body;
            body.set("nodes", nodes);
            sendJson(response, body);
            return;
        }
        Object error;
        error.set("error", "not found");
        sendJson(response, error, HTTPServerResponse::HTTP_NOT_FOUND);
    }

private:
    TraceStore& _store;
    TraceHttpOptions _options;
};

class Factory final : public Poco::Net::HTTPRequestHandlerFactory
{
public:
    Factory(TraceStore& store, TraceHttpOptions options)
        : _store(store), _options(std::move(options))
    {
    }
    Poco::Net::HTTPRequestHandler* createRequestHandler(const HTTPServerRequest&) override
    {
        return new Handler(_store, _options);
    }

private:
    TraceStore& _store;
    TraceHttpOptions _options;
};
} // namespace

class TraceHttpServer::Impl
{
public:
    Impl(TraceStore& store, TraceHttpOptions options) : _options(std::move(options))
    {
        if (!_options.bearerToken.empty() && _options.bearerToken.size() < 16)
            throw std::invalid_argument("trace WebUI bearer token must contain 16 characters");
        Poco::Net::ServerSocket socket(
            Poco::Net::SocketAddress(_options.bindAddress, _options.port));
        _port = socket.address().port();
        _server = std::make_unique<Poco::Net::HTTPServer>(
            new Factory(store, _options), socket, new Poco::Net::HTTPServerParams);
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

    TraceHttpOptions _options;
    std::unique_ptr<Poco::Net::HTTPServer> _server;
    std::uint16_t _port{0};
    bool _started{false};
};

TraceHttpServer::TraceHttpServer(TraceStore& store, TraceHttpOptions options)
    : _impl(std::make_unique<Impl>(store, std::move(options)))
{
}
TraceHttpServer::~TraceHttpServer() { _impl->stop(); }
void TraceHttpServer::start() { _impl->start(); }
void TraceHttpServer::stop() { _impl->stop(); }
std::uint16_t TraceHttpServer::port() const { return _impl->_port; }
} // namespace PocoDDS::Observability
