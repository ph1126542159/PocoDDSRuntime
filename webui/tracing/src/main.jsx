import React, { useCallback, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { Activity, AlertCircle, AppWindow, Bot, Box, Boxes, CheckCircle2, ChevronRight, Clock3, Cpu, Download, FileJson, GitBranch, PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen, PauseCircle, Play, RefreshCw, Search, Server, ShieldCheck, Wifi, WifiOff } from "lucide-react";
import "./styles.css";
import "./workspace.css";
import "./typography.css";
import "./shell.css";

const ROBOTICS_ORIGIN = window.location.port === "9096" ? "" : "http://127.0.0.1:9096";
async function request(path, { robotics = false, method = "GET", body } = {}) {
  const token = sessionStorage.getItem("pdr.webui.token") || "";
  const response = await fetch(`${robotics ? ROBOTICS_ORIGIN : ""}${path}`, {
    method, headers: { ...(body ? { "Content-Type": "application/json" } : {}), ...(!robotics && token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `请求失败（HTTP ${response.status}）`);
  return data;
}

const statusText = { pending: "等待中", queued: "排队中", running: "执行中", active: "执行中", success: "成功", succeeded: "成功", failed: "失败", cancelled: "已取消", canceled: "已取消" };
const internalTransportBusinesses = new Set(["主子进程Fast-DDS心跳"]);
const requestedTraceId = new URLSearchParams(window.location.search).get("traceId") || "";
const normalizedStatus = value => ({ queued: "running", active: "running", succeeded: "success", canceled: "cancelled" }[value] || value || "pending");
const duration = node => normalizedStatus(node.status) === "running" ? "执行中" : `${(Number(node.durationNanoseconds || 0) / 1e6).toFixed(3)} ms`;
const dateText = value => Number(value) > 0 ? new Date(Number(value) / 1000).toLocaleString("zh-CN", { hour12: false }) : "尚未开始";

function Status({ value }) {
  const status = normalizedStatus(value);
  return <span className={`status ${status}`}>{status === "success" ? <CheckCircle2 size={15} /> : <Clock3 size={15} />}{statusText[status] || status}</span>;
}
function Fields({ values }) {
  const entries = Object.entries(values || {});
  return entries.length ? entries.map(([key, value]) => <div className="field" key={key}><label>{key}</label><pre>{String(value)}</pre></div>) : <p className="none">无</p>;
}
function Detail({ node }) {
  if (!node) return <div className="empty"><FileJson size={32} /><p>点击流程节点查看详情</p></div>;
  return <div className="detail">
    <div className="detail-head"><Status value={node.status} /><h2>{node.displayName || node.operation}</h2><p>{node.operation} · {node.serviceName}{node.bundleName ? ` · ${node.bundleName}` : ""}</p></div>
    <dl><div><dt>耗时</dt><dd>{duration(node)}</dd></div><div><dt>主机 / 进程</dt><dd>{node.hostName || "—"} / {node.processId || "—"}</dd></div><div><dt>Trace ID</dt><dd>{node.traceId}</dd></div><div><dt>Span ID</dt><dd>{node.spanId}</dd></div></dl>
    {node.errorMessage && <section><h3>失败信息</h3><div className="error"><b>{node.errorCode}</b><pre>{node.errorMessage}</pre></div></section>}
    <section><h3>传入参数</h3><Fields values={node.inputs} /></section><section><h3>传出参数</h3><Fields values={node.outputs} /></section>
    <section><h3>节点日志</h3>{node.logs?.length ? node.logs.map((log, index) => <div className="log" key={`${log.timestampUnixMicroseconds}-${index}`}><header><b>{log.level}</b><time>{dateText(log.timestampUnixMicroseconds)}</time></header><pre>{log.message}</pre><Fields values={log.fields} /></div>) : <p className="none">无</p>}</section>
  </div>;
}

function Flow({ nodes, selected, onSelect }) {
  const layout = useMemo(() => {
    const ordered = [...nodes].sort((a, b) => Number(a.sequence || 0) - Number(b.sequence || 0));
    const byId = Object.fromEntries(ordered.map(node => [node.spanId, node]));
    const hierarchical = ordered.some(node => byId[node.parentSpanId]);
    const positions = {};
    ordered.forEach((node, index) => {
      let column = index;
      if (hierarchical) {
        column = 0; let current = node; const seen = new Set();
        while (current.parentSpanId && byId[current.parentSpanId] && !seen.has(current.parentSpanId)) { seen.add(current.parentSpanId); current = byId[current.parentSpanId]; column += 1; }
      }
      const row = Object.values(positions).filter(point => point.column === column).length;
      positions[node.spanId] = { x: 38 + column * 270, y: 58 + row * 145, column };
    });
    const edges = ordered.slice(1).map((node, index) => ({ from: hierarchical && byId[node.parentSpanId] ? byId[node.parentSpanId] : ordered[index], to: node }));
    return { ordered, positions, edges, width: Math.max(820, ...Object.values(positions).map(p => p.x + 245)), height: Math.max(520, ...Object.values(positions).map(p => p.y + 125)) };
  }, [nodes]);
  return <div className="flow" style={{ width: layout.width, height: layout.height }}><svg viewBox={`0 0 ${layout.width} ${layout.height}`}>{layout.edges.map(({ from, to }) => {
    const start = layout.positions[from.spanId], end = layout.positions[to.spanId];
    return <path key={`${from.spanId}-${to.spanId}`} d={`M ${start.x + 220} ${start.y + 45} C ${start.x + 250} ${start.y + 45},${end.x - 30} ${end.y + 45},${end.x} ${end.y + 45}`} />;
  })}</svg>{layout.ordered.map(node => {
    const point = layout.positions[node.spanId], status = normalizedStatus(node.status);
    return <button key={node.spanId} className={`node ${status} ${selected?.spanId === node.spanId ? "active" : ""}`} style={{ left: point.x, top: point.y }} onClick={() => onSelect(node)}><span>{statusText[status] || status}</span><b>{node.displayName || node.operation}</b><small>{node.operation}</small><small>{duration(node)}</small></button>;
  })}</div>;
}

function SimulationPanel({ catalog, available, busy, onStart }) {
  const [module, setModule] = useState("warehouse"), [periodMs, setPeriodMs] = useState(10), [streamDelayMs, setStreamDelayMs] = useState(80);
  const scenario = catalog?.scenarios?.find(item => item.module === module);
  return <section className="simulation-panel"><div className="simulation-title"><span><Bot size={22} /></span><div><h2>机器人业务仿真</h2><p>启动真实 C++ SIL，执行记录进入下方原业务追踪列表与节点详情。</p></div></div>
    <div className="simulation-fields"><label>业务模块<select value={module} onChange={event => setModule(event.target.value)} disabled={!available || busy}>{(catalog?.scenarios || []).map(item => <option key={item.module} value={item.module}>{item.title}</option>)}</select></label>
      <label>控制周期（ms）<input type="number" min="1" max="1000" value={periodMs} onChange={event => setPeriodMs(event.target.value)} /></label><label>节点演示间隔（ms）<input type="number" min="1" max="1000" value={streamDelayMs} onChange={event => setStreamDelayMs(event.target.value)} /></label>
      <button disabled={!available || busy} onClick={() => onStart({ module, periodMs: Number(periodMs), streamDelayMs: Number(streamDelayMs), maxSteps: 5000 })}><Play size={18} />{busy ? "仿真执行中" : "启动仿真"}</button></div>
    <footer><span className={available ? "connected" : "disconnected"}>{available ? <Wifi size={16} /> : <WifiOff size={16} />}仿真服务{available ? "已连接" : "未连接"}</span><strong>{scenario?.description || "请先启动本机机器人仿真服务"}</strong></footer>
  </section>;
}
function TraceSummary({ trace, selected, onSelect }) {
  return <button className={selected ? "active" : ""} onClick={onSelect}><div className="trace-meta"><Status value={trace.status} /><span className={`source ${trace.source}`}>{trace.source === "robotics" ? "机器人仿真" : "运行时"}</span></div><b>{trace.businessName}</b><small>{trace.businessInstanceId}</small><small>{trace.completedStepCount != null ? `${trace.completedStepCount} / ` : ""}{trace.stepCount} 个节点 · {dateText(trace.startedUnixMicroseconds)}</small>{trace.failedOperation && <em>失败于 {trace.failedOperation}</em>}</button>;
}
function RunOverview({ trace, detail, onCancel }) {
  if (!trace || trace.source !== "robotics") return null;
  const result = detail?.result || {}, completed = trace.completedStepCount || 0, percent = trace.stepCount ? Math.round(completed / trace.stepCount * 100) : 0;
  return <div className="run-overview"><div><span>执行进度</span><b>{completed} / {trace.stepCount}</b><progress max="100" value={percent} /></div><div><span>机器人位置</span><b>{result.x == null ? "—" : `X = ${Number(result.x).toFixed(3)} m`}</b></div><div><span>安全看门狗</span><b>{result.watchdogStop == null ? "等待验证" : result.watchdogStop ? "已验证" : "未通过"}</b></div><div><span>OTel 导出</span><b>{detail?.telemetry?.export?.status || "local-only"}</b></div>{normalizedStatus(trace.status) === "running" && <button onClick={onCancel}><PauseCircle size={17} />取消任务</button>}</div>;
}

function exportDiagnosis(trace, nodes) {
  if (!trace || !nodes.length) return;
  const byId = new Map(nodes.map(node => [node.spanId, node]));
  const failed = nodes.filter(node => normalizedStatus(node.status) === "failed");
  const failedParents = new Set(failed.map(node => node.parentSpanId).filter(Boolean));
  const primary = failed.find(node => !failedParents.has(node.spanId)) || failed[0] || null;
  const causalChain = [];
  for (let current = primary; current; current = byId.get(current.parentSpanId)) {
    causalChain.unshift({
      operation: current.operation,
      serviceName: current.serviceName,
      processId: current.processId,
      status: current.status,
      errorCode: current.errorCode || "",
      errorMessage: current.errorMessage || ""
    });
  }
  const errorCode = primary?.errorCode || trace.failedOperation || "UNKNOWN_FAILURE";
  const recommendations = failed.length ? [
    "从 primaryFailure 开始，沿 causalChain 核对父子 Span、输入和输出。",
    "结合失败节点日志、errorCode、processId 和 Trace ID 查询对应进程日志。"
  ] : ["当前 Trace 未发现 failed 节点，建议检查超时、丢失响应或业务状态汇总逻辑。"];
  const report = {
    schemaVersion: "pdr-business-diagnosis/1.0",
    exportedAt: new Date().toISOString(),
    summary: {
      businessName: trace.businessName,
      businessInstanceId: trace.businessInstanceId,
      traceId: trace.traceId,
      status: trace.status,
      nodeCount: nodes.length,
      failedNodeCount: failed.length
    },
    analysis: {
      conclusion: primary
        ? `首要失败点为“${primary.operation}”，错误码 ${errorCode}：${primary.errorMessage || "未提供更详细错误信息"}`
        : "未找到明确失败节点。",
      primaryFailure: primary,
      causalChain,
      allFailures: failed,
      recommendations
    },
    processes: [...new Map(nodes.map(node => [
      `${node.processId}:${node.serviceName}`,
      { processId: node.processId, serviceName: node.serviceName, hostName: node.hostName }
    ])).values()],
    nodes
  };
  const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `business-diagnosis-${trace.traceId || Date.now()}.json`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function HistoryPanel({ onOpenWorkspace }) {
  const localDateTime = date => {
    const offset = date.getTimezoneOffset() * 60000;
    return new Date(date.getTime() - offset).toISOString().slice(0, 16);
  };
  const [from, setFrom] = useState(() => localDateTime(new Date(Date.now() - 3600000)));
  const [to, setTo] = useState(() => localDateTime(new Date()));
  const [name, setName] = useState("");
  const [status, setStatus] = useState("");
  const [records, setRecords] = useState([]);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const limit = 100;
  const load = async nextOffset => {
    setLoading(true); setError("");
    try {
      const query = new URLSearchParams({
        from: String(new Date(from).getTime() * 1000),
        to: String(new Date(to).getTime() * 1000 + 59999999),
        name, status, limit: String(limit), offset: String(nextOffset)
      });
      const data = await request(`/api/v1/business-trace-history?${query}`);
      setRecords(data.records || []);
      setHasMore(Boolean(data.hasMore));
      setOffset(nextOffset);
    } catch (exception) {
      setRecords([]); setHasMore(false); setError(exception.message);
    } finally { setLoading(false); }
  };
  return <div className="history-page">
    <header><div><Search size={24} /><div><h2>业务追踪历史</h2><p>查询 SQLite 持久化记录；完整实时节点仍在业务追踪主页面查看</p></div></div>
      <button onClick={onOpenWorkspace}><Activity size={18} />查看实时追踪</button></header>
    <form onSubmit={event => { event.preventDefault(); load(0); }}>
      <label>开始时间<input type="datetime-local" value={from} onChange={event => setFrom(event.target.value)} /></label>
      <label>结束时间<input type="datetime-local" value={to} onChange={event => setTo(event.target.value)} /></label>
      <label>业务名称<input value={name} onChange={event => setName(event.target.value)} placeholder="支持模糊查询" /></label>
      <label>状态<select value={status} onChange={event => setStatus(event.target.value)}><option value="">全部</option><option value="running">执行中</option><option value="success">成功</option><option value="failed">失败</option><option value="cancelled">已取消</option></select></label>
      <button type="submit" disabled={loading}><Search size={18} />{loading ? "查询中" : "查询"}</button>
    </form>
    <div className={`history-error ${error ? "" : "empty-slot"}`} aria-live="polite">{error}</div>
    <div className="history-table"><div className="history-columns"><span>业务 / 实例</span><span>状态</span><span>步骤</span><span>开始时间</span><span>执行耗时</span></div>
      {records.map(item => <div className="history-row" key={item.traceId}><div><b>{item.businessName}</b><small>{item.businessInstanceId || item.traceId}</small></div><Status value={item.status} /><strong>{item.stepCount} 个步骤</strong><strong>{dateText(item.startedUnixMicroseconds)}</strong><strong>{duration(item)}</strong></div>)}
      {!records.length && !loading && <div className="empty"><Search size={30} /><p>请选择条件查询历史记录</p></div>}
    </div>
    <footer><span>每页 {limit} 条 · 第 {Math.floor(offset / limit) + 1} 页</span><div><button disabled={loading || offset === 0} onClick={() => load(Math.max(0, offset - limit))}>上一页</button><button disabled={loading || !hasMore} onClick={() => load(offset + limit)}>下一页</button></div></footer>
  </div>;
}

function App() {
  const [runtimeTraces, setRuntimeTraces] = useState([]), [roboticsTraces, setRoboticsTraces] = useState([]), [catalog, setCatalog] = useState(null), [roboticsAvailable, setRoboticsAvailable] = useState(false);
  const [selectedKey, setSelectedKey] = useState(""), [nodes, setNodes] = useState([]), [runDetail, setRunDetail] = useState(null), [selectedNode, setSelectedNode] = useState(null), [error, setError] = useState("");
  const [subpage, setSubpage] = useState(() => new URLSearchParams(window.location.search).get("page") === "history" ? "history" : "workspace");
  const [instancesCollapsed, setInstancesCollapsed] = useState(false);
  const [detailCollapsed, setDetailCollapsed] = useState(false);
  const [updated, setUpdated] = useState(null);
  const traces = useMemo(() => [...roboticsTraces, ...runtimeTraces].sort((a, b) => Number(b.startedUnixMicroseconds || 0) - Number(a.startedUnixMicroseconds || 0)), [roboticsTraces, runtimeTraces]);
  const active = traces.find(trace => `${trace.source}:${trace.traceId}` === selectedKey);
  const simulationBusy = roboticsTraces.some(trace => ["queued", "running"].includes(trace.status));
  const loadList = useCallback(async () => {
    const [runtimeResult, roboticsResult, catalogResult] = await Promise.allSettled([request("/api/v1/business-traces"), request("/api/v1/robotics-simulation/runs", { robotics: true }), request("/api/v1/robotics-simulation/catalog", { robotics: true })]);
    const runtime = runtimeResult.status === "fulfilled" ? (runtimeResult.value.traces || [])
      .filter(item => !internalTransportBusinesses.has(item.businessName) || item.traceId === requestedTraceId)
      .map(item => ({ ...item, source: "runtime" })) : [];
    const robotics = roboticsResult.status === "fulfilled" ? (roboticsResult.value.runs || []).map(item => ({ ...item, source: "robotics" })) : [];
    setRuntimeTraces(runtime); setRoboticsTraces(robotics); setRoboticsAvailable(roboticsResult.status === "fulfilled" && catalogResult.status === "fulfilled");
    setUpdated(new Date());
    if (catalogResult.status === "fulfilled") setCatalog(catalogResult.value);
    const combined = [...robotics, ...runtime].sort((a, b) => Number(b.startedUnixMicroseconds || 0) - Number(a.startedUnixMicroseconds || 0));
    setSelectedKey(current => {
      if (combined.some(item => `${item.source}:${item.traceId}` === current)) return current;
      const requested = combined.find(item => item.source === "runtime" && item.traceId === requestedTraceId);
      return requested ? `runtime:${requested.traceId}` : combined[0] ? `${combined[0].source}:${combined[0].traceId}` : "";
    });
    if (runtimeResult.status === "rejected" && roboticsResult.status === "rejected") setError("运行时与机器人仿真服务均不可用"); else if (roboticsResult.status === "rejected") setError("机器人仿真服务未启动；原业务追踪仍可使用"); else setError("");
  }, []);
  const loadTrace = useCallback(async trace => {
    if (!trace) { setNodes([]); setRunDetail(null); return; }
    try {
      if (trace.source === "robotics") { const detail = await request(`/api/v1/robotics-simulation/runs/${encodeURIComponent(trace.runId)}`, { robotics: true }); setRunDetail(detail); setNodes(detail.nodes || []); setSelectedNode(current => detail.nodes?.find(node => node.spanId === current?.spanId) || detail.nodes?.[0] || null); }
      else { const detail = await request(`/api/v1/business-traces/${encodeURIComponent(trace.traceId)}`); setRunDetail(null); setNodes(detail.nodes || []); setSelectedNode(current => detail.nodes?.find(node => node.spanId === current?.spanId) || detail.nodes?.[0] || null); }
    } catch (exception) { setError(exception.message); }
  }, []);
  useEffect(() => { loadList(); const timer = setInterval(loadList, 1500); return () => clearInterval(timer); }, [loadList]);
  useEffect(() => { loadTrace(active); const timer = setInterval(() => loadTrace(active), 1000); return () => clearInterval(timer); }, [active?.source, active?.traceId, active?.runId, loadTrace]);
  useEffect(() => {
    const onPopState = () => setSubpage(new URLSearchParams(window.location.search).get("page") === "history" ? "history" : "workspace");
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);
  const openSubpage = next => {
    const url = new URL(window.location.href);
    if (next === "history") url.searchParams.set("page", "history");
    else url.searchParams.delete("page");
    window.history.pushState({}, "", url);
    setSubpage(next);
  };
  const startSimulation = async parameters => { try { const started = await request("/api/v1/robotics-simulation/runs", { robotics: true, method: "POST", body: parameters }); setSelectedNode(null); setSelectedKey(`robotics:${started.traceId}`); await loadList(); setError(""); } catch (exception) { setError(exception.message); } };
  const cancelSimulation = async () => { if (!active?.runId) return; try { await request(`/api/v1/robotics-simulation/runs/${encodeURIComponent(active.runId)}/cancel`, { robotics: true, method: "POST", body: {} }); await loadList(); } catch (exception) { setError(exception.message); } };
  const primaryNav = [
    ["运行态势", Activity, "/home/?page=overview"],
    ["进程管理", AppWindow, "/home/?page=processes"],
    ["设备与协议", Cpu, "/home/?page=devices"],
    ["插件治理", Boxes, "/home/?page=plugins"],
    ["指标中心", Activity, "/home/?page=metrics"],
    ["Runtime 治理", ShieldCheck, "/home/?page=governance"]
  ];
  return <div className="tracing-shell precision-shell">
    <header className="command-bar">
      <div className="command-brand"><span><Box size={23} /></span><b>PocoDDS Runtime</b></div>
      <i className="command-divider" />
      <strong className="command-title">业务追踪</strong>
      <div className="command-actions"><span className="last-update">最后刷新：{updated ? updated.toLocaleString() : "连接中"}</span>
        <button className="command-refresh" aria-label="刷新" onClick={loadList}><RefreshCw size={18} /></button>
        <span className={`command-online ${error ? "degraded" : ""}`}><i />{error ? "部分服务异常" : "已连接"}</span></div>
    </header>
    <aside className="tracing-navigation">
      <nav>{primaryNav.map(([label, Icon, href]) => <a key={label} href={href}><Icon size={18} /><span>{label}</span><ChevronRight size={15} /></a>)}
        <button className="active tracing-parent" onClick={() => openSubpage("workspace")}><GitBranch size={18} /><span>业务追踪</span><ChevronRight size={15} /></button>
        <div className="tracing-subnav" aria-label="业务追踪子页面">
          <button className={subpage === "workspace" ? "active" : ""} onClick={() => openSubpage("workspace")}><Activity size={15} />追踪工作台</button>
          <button className={subpage === "history" ? "active" : ""} onClick={() => openSubpage("history")}><Search size={15} />历史查询</button>
        </div>
      </nav>
      <div className={`runtime-state ${error ? "degraded" : ""}`}><i /><div><b>{error ? "追踪服务受限" : "追踪服务在线"}</b><small>{roboticsAvailable ? "Runtime + 仿真" : "Runtime 本地链路"}</small></div></div>
    </aside>
    <main className="tracing-main"><div className="tracing-content">
      {subpage === "workspace" ? <>
        {error && <div className="banner"><AlertCircle size={19} />{error}</div>}
        <SimulationPanel catalog={catalog} available={roboticsAvailable} busy={simulationBusy} onStart={startSimulation} />
        <section className={`tracking-workspace${instancesCollapsed ? " instances-collapsed" : ""}${detailCollapsed ? " detail-collapsed" : ""}`}>
          <aside className={`traces workspace-panel${instancesCollapsed ? " collapsed" : ""}`} id="trace-instance-panel">
            {instancesCollapsed ? <button className="panel-rail-toggle" type="button" aria-label="展开业务实例" title="展开业务实例" aria-expanded="false" aria-controls="trace-instance-panel" onClick={() => setInstancesCollapsed(false)}><PanelLeftOpen size={19} /><span>业务实例</span><b>{traces.length}</b></button> : <><h2><span className="panel-title">业务实例</span><span className="panel-count">{traces.length}</span><button className="panel-collapse-button" type="button" aria-label="收起业务实例" title="收起业务实例" aria-expanded="true" aria-controls="trace-instance-panel" onClick={() => setInstancesCollapsed(true)}><PanelLeftClose size={18} /></button></h2>{traces.map(trace => <TraceSummary key={`${trace.source}:${trace.traceId}`} trace={trace} selected={`${trace.source}:${trace.traceId}` === selectedKey} onSelect={() => { setSelectedKey(`${trace.source}:${trace.traceId}`); setSelectedNode(null); }} />)}{!traces.length && <div className="empty"><Activity /><p>暂无业务追踪</p></div>}</>}
          </aside>
          <section className="graph"><header><div><h2>{active?.businessName || "业务流程图"}</h2><p>{active?.businessInstanceId || "选择一个业务实例"}</p></div><div className="graph-actions">{active && <Status value={active.status} />}<button disabled={!active || !nodes.length} onClick={() => exportDiagnosis(active, nodes)}><Download size={17} />导出诊断报告</button></div></header><RunOverview trace={active} detail={runDetail} onCancel={cancelSimulation} /><div className="scroll"><Flow nodes={nodes} selected={selectedNode} onSelect={setSelectedNode} /></div></section>
          <aside className={`inspector workspace-panel${detailCollapsed ? " collapsed" : ""}`} id="trace-detail-panel">
            {detailCollapsed ? <button className="panel-rail-toggle" type="button" aria-label="展开节点详情" title="展开节点详情" aria-expanded="false" aria-controls="trace-detail-panel" onClick={() => setDetailCollapsed(false)}><PanelRightOpen size={19} /><span>节点详情</span></button> : <><h2><Server size={18} /><span className="panel-title">节点详情</span><button className="panel-collapse-button" type="button" aria-label="收起节点详情" title="收起节点详情" aria-expanded="true" aria-controls="trace-detail-panel" onClick={() => setDetailCollapsed(true)}><PanelRightClose size={18} /></button></h2><Detail node={selectedNode} /></>}
          </aside>
        </section>
        <footer className="safety"><ShieldCheck size={17} />当前页面为软件在环仿真与框架验收；真机部署仍需硬件急停、限速、碰撞区和独立安全控制器。</footer>
      </> : <HistoryPanel onOpenWorkspace={() => openSubpage("workspace")} />}
    </div></main>
  </div>;
}
createRoot(document.getElementById("root")).render(<App />);
