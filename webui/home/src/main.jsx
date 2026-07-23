import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity, AppWindow, ArrowLeft, Box, Boxes, ChevronDown, ChevronRight, CircleGauge, Clock3,
  Cpu, FileText, HardDrive, Layers3, MemoryStick, Menu, Network, Play, RefreshCw, RotateCw, Search, Server,
  Settings2, SlidersHorizontal, Square, Terminal, Trash2, X, Zap
} from "lucide-react";
import "./styles.css";
import "./embedded.css";

const pageMeta = {
  overview: ["运行总览", "实时掌握运行时状态与资源"],
  processes: ["进程", "当前运行时挂载的进程"],
  services: ["服务", "OSP 服务注册中心"],
  modules: ["组件与模块", "Bundle 提供的运行时模块"],
  bundles: ["Bundles", "OSP Bundle 生命周期管理"],
  logs: ["日志查询", "快速定位运行时问题"]
};

const navItems = [
  ["overview", CircleGauge], ["processes", AppWindow], ["services", Server],
  ["modules", Layers3], ["bundles", Boxes], ["logs", FileText]
];

async function request(path, options = {}) {
  const token = sessionStorage.getItem("pdr.webui.token") || "";
  const response = await fetch(path, {
    ...options,
    headers: { ...(options.headers || {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) }
  });
  if (response.status === 401) {
    const next = window.prompt("请输入管理令牌");
    if (next) {
      sessionStorage.setItem("pdr.webui.token", next);
      return request(path, options);
    }
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || data.message || "请求失败");
  return data;
}

function Status({ state }) {
  const running = ["active", "running", "started"].includes(String(state).toLowerCase());
  return <span className={`status ${running ? "ok" : "idle"}`}><i />{state}</span>;
}

function Metric({ icon: Icon, label, value, caption, tone, onClick }) {
  return <article className={`metric ${onClick ? "clickable" : ""}`} onClick={onClick}
    onKeyDown={event => event.key === "Enter" && onClick?.()}
    role={onClick ? "button" : undefined} tabIndex={onClick ? 0 : undefined}>
    <div className={`metric-icon ${tone}`}><Icon size={20} strokeWidth={1.8} /></div>
    <div><span>{label}</span><strong>{value}</strong><small>{caption}</small></div>
    {onClick && <ChevronRight className="metric-arrow" size={19} />}
  </article>;
}

const numeric = (value, fallback = 0) => {
  const result = Number(value);
  return Number.isFinite(result) ? result : fallback;
};
const percent = value => `${numeric(value).toFixed(1)}%`;

function Sparkline({ values, color }) {
  const safe = values.length ? values.map(value => numeric(value)) : [0];
  const max = Math.max(100, ...safe);
  const points = safe.map((value, index) => {
    const x = safe.length === 1 ? 100 : (index / (safe.length - 1)) * 100;
    return `${x},${36 - Math.min(36, (value / max) * 34)}`;
  }).join(" ");
  return <svg className="sparkline" viewBox="0 0 100 38" preserveAspectRatio="none" aria-hidden="true">
    <polyline className="spark-fill" points={`0,38 ${points} 100,38`} style={{ fill: `${color}18` }} />
    <polyline className="spark-line" points={points} style={{ stroke: color }} />
  </svg>;
}

function ResourceCharts({ resources, history }) {
  const cpu = numeric(resources.cpuPercent ?? resources.cpu);
  const memory = numeric(resources.memoryPercent ?? resources.memory);
  const disk = numeric(resources.diskPercent ?? resources.disk);
  const cards = [
    { label: "CPU 使用率", value: percent(cpu), detail: `${resources.cpuCores || resources.cores || "—"} 核心`, icon: Cpu, tone: "#2563eb", values: history.map(x => x.cpu) },
    { label: "内存使用率", value: percent(memory), detail: resources.memoryUsedMb != null ? `${resources.memoryUsedMb} / ${resources.memoryTotalMb || "—"} MB` : "主进程及子进程", icon: MemoryStick, tone: "#7654d8", values: history.map(x => x.memory) },
    { label: "磁盘使用率", value: percent(disk), detail: resources.diskUsedGb != null ? `${resources.diskUsedGb} / ${resources.diskTotalGb || "—"} GB` : "运行目录", icon: HardDrive, tone: "#e7792c", values: history.map(x => x.disk) },
    { label: "网络吞吐", value: `${numeric(resources.networkReceiveKbps).toFixed(1)} KB/s`, detail: `发送 ${numeric(resources.networkSendKbps).toFixed(1)} KB/s`, icon: Network, tone: "#079669", values: history.map(x => x.networkReceive) },
    { label: "运行时线程", value: numeric(resources.threadCount), detail: "主进程线程数", icon: Activity, tone: "#d14f74", values: history.map(x => x.threads) }
  ];
  return <div className="resource-charts">{cards.map(card => {
    const Icon = card.icon;
    return <article className="resource-chart" key={card.label}>
      <header><span style={{ color: card.tone }}><Icon size={17} /></span><div><small>{card.label}</small><strong>{card.value}</strong></div></header>
      <Sparkline values={card.values} color={card.tone} />
      <footer><span>最近 {Math.max(history.length, 1)} 次采样</span><b>{card.detail}</b></footer>
    </article>;
  })}</div>;
}

function RuntimeInventory({ processes, bundles, reportedMainProcess }) {
  const mainProcess = reportedMainProcess || processes.find(item => item.main || item.role === "main");
  const visibleProcesses = processes.filter(item => String(item.name).toLowerCase() !== "conhost.exe");
  const children = mainProcess ? visibleProcesses.filter(item => item !== mainProcess) : visibleProcesses;
  return <div className="inventory-grid">
    <section className="surface inventory">
      <div className="section-head"><div><h2>主进程加载的子进程</h2><p>{mainProcess ? `${mainProcess.name} · PID ${mainProcess.pid || mainProcess.id}` : "等待运行时上报主进程"}</p></div>
        <span className="inventory-count">{children.length} 个</span></div>
      <div className="inventory-list">{children.map(item => <div className="inventory-row" key={item.id}>
        <span className="inventory-icon process"><AppWindow size={16} /></span>
        <div><b>{item.name}</b><small>PID {item.pid || item.id}{item.path ? ` · ${item.path}` : ""}</small></div><Status state={item.state} />
      </div>)}{!children.length && <div className="inventory-empty">当前没有已加载的子进程</div>}</div>
    </section>
    <section className="surface inventory">
      <div className="section-head"><div><h2>已加载 Bundles</h2><p>主进程中的 OSP Bundle 生命周期</p></div>
        <span className="inventory-count">{bundles.length} 个</span></div>
      <div className="inventory-list">{bundles.slice(0, 8).map(item => <div className="inventory-row" key={item.id}>
        <span className="inventory-icon bundle"><Boxes size={16} /></span>
        <div><b>{item.name}</b><small>{item.id} · {item.version || "版本未知"}</small></div><Status state={item.state} />
      </div>)}{!bundles.length && <div className="inventory-empty">当前没有已加载的 Bundle</div>}</div>
    </section>
  </div>;
}

function BusinessExecutionList({ process }) {
  const [executions, setExecutions] = useState([]);
  const [available, setAvailable] = useState(true);
  const [collapsed, setCollapsed] = useState(false);
  const [detail, setDetail] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);

  useEffect(() => {
    if (!process) return undefined;
    let active = true;
    const load = async () => {
      try {
        const data = await request("/api/v1/heartbeat-businesses");
        if (active) {
          setExecutions(data.records || []);
          setAvailable(true);
        }
      } catch {
        if (active) {
          setExecutions([]);
          setAvailable(false);
        }
      }
    };
    load();
    const timer = setInterval(load, 2000);
    return () => { active = false; clearInterval(timer); };
  }, [process?.id, process?.pid, process?.name]);

  const formatTime = value => {
    const numericValue = Number(value);
    if (!Number.isFinite(numericValue) || numericValue <= 0) return "—";
    const milliseconds = numericValue > 1e14 ? numericValue / 1000 : numericValue;
    const date = new Date(milliseconds);
    return `${date.toLocaleDateString()} ${date.toLocaleTimeString("zh-CN", { hour12: false })}.${String(date.getMilliseconds()).padStart(3, "0")}`;
  };
  const formatDuration = item => {
    const direct = Number(item.durationMilliseconds ?? item.durationMs);
    if (Number.isFinite(direct)) return direct < 1000 ? `${direct.toFixed(0)} ms` : `${(direct / 1000).toFixed(2)} s`;
    const microseconds = Number(item.durationMicroseconds);
    if (Number.isFinite(microseconds)) return microseconds < 1e6 ? `${(microseconds / 1000).toFixed(0)} ms` : `${(microseconds / 1e6).toFixed(2)} s`;
    const nanoseconds = Number(item.durationNanoseconds);
    if (Number.isFinite(nanoseconds)) return `${(nanoseconds / 1e6).toFixed(3)} ms`;
    return ["running", "active"].includes(String(item.status).toLowerCase()) ? "执行中" : "—";
  };
  const openDetail = async item => {
    const data = await request(`/api/v1/heartbeat-businesses?traceId=${encodeURIComponent(item.traceId)}`);
    setDetail({ item, nodes: data.nodes || [] });
    setSelectedNode(data.nodes?.[0] || null);
  };
  const linkText = status => status === "success" ? "链路走通" :
    status === "running" ? "执行中" : "链路失败";

  return <section className="surface business-execution-card">
    <div className="section-head"><div><h2>业务流程执行列表</h2><p>当前进程的业务实例与执行进度</p></div>
      <div className="section-head-actions"><span className="inventory-count">{executions.length} 条</span>
        <button className={`section-collapse ${collapsed ? "collapsed" : ""}`}
          onClick={() => setCollapsed(value => !value)} aria-expanded={!collapsed}
          title={collapsed ? "展开业务流程执行列表" : "折叠业务流程执行列表"}>
          <ChevronDown size={24} />
        </button>
      </div></div>
    {!collapsed && <div className="business-execution-list">{executions.map((item, index) =>
      <article key={item.traceId || item.businessInstanceId || index}
        onDoubleClick={() => openDetail(item)} title="双击查看业务详细流程图">
        <header><div><b>{item.businessName || item.name || "未命名业务流程"}</b>
          <small>{item.businessInstanceId || item.traceId || "实例标识未知"}</small></div>
          <span className={`business-link ${item.status}`}>{linkText(item.status)}</span></header>
        <div className="business-execution-facts">
          <span><small>当前步骤</small><strong>{item.currentStep || item.stepName || `${item.stepCount || 0} 个步骤`}</strong></span>
          <span><small>开始时间</small><strong>{formatTime(item.startedUnixMicroseconds || item.startedAt || item.startTime)}</strong></span>
          <span><small>执行耗时</small><strong>{formatDuration(item)}</strong></span>
        </div>
      </article>)}
      {!executions.length && <div className="workbench-empty">
        {available ? "当前进程暂无业务流程执行记录" : "业务流程追踪服务暂未提供数据"}
      </div>}
    </div>}
    {detail && <div className="business-modal-backdrop" onMouseDown={() => setDetail(null)}>
      <section className="business-modal" onMouseDown={event => event.stopPropagation()}>
        <header><div><h2>{detail.item.businessName}</h2><p>{detail.item.businessInstanceId}</p></div>
          <button onClick={() => setDetail(null)}><X size={28} /></button></header>
        <div className="business-flow">
          <div className="flow-nodes">{detail.nodes.map((node, index) => <React.Fragment key={node.spanId}>
            {index > 0 && <ChevronRight size={34} />}
            <button className={`${node.status} ${selectedNode?.spanId === node.spanId ? "active" : ""}`}
              onClick={() => setSelectedNode(node)}>
              <small>步骤 {index + 1}</small><b>{node.operation}</b>
              <span>{(Number(node.durationNanoseconds || 0) / 1e6).toFixed(3)} ms</span>
            </button>
          </React.Fragment>)}</div>
          <aside>{selectedNode ? <><div className="step-head"><span className={`business-link ${selectedNode.status}`}>
            {selectedNode.status === "success" ? "成功" : selectedNode.status}</span><h3>{selectedNode.operation}</h3></div>
            <dl><div><dt>耗时</dt><dd>{(Number(selectedNode.durationNanoseconds || 0) / 1e6).toFixed(3)} ms</dd></div>
              <div><dt>服务 / Bundle</dt><dd>{selectedNode.serviceName} / {selectedNode.bundleName || "—"}</dd></div>
              <div><dt>主机 / PID</dt><dd>{selectedNode.hostName} / {selectedNode.processId}</dd></div></dl>
            <h4>传入参数</h4><pre>{JSON.stringify(selectedNode.inputs || {}, null, 2)}</pre>
            <h4>传出参数</h4><pre>{JSON.stringify(selectedNode.outputs || {}, null, 2)}</pre>
            {selectedNode.errorMessage && <><h4>失败信息</h4><pre>{selectedNode.errorMessage}</pre></>}
          </> : <div className="workbench-empty">点击流程节点查看详情</div>}</aside>
        </div>
      </section>
    </div>}
  </section>;
}

function ProcessWorkspace({ items }) {
  const [selectedId, setSelectedId] = useState("");
  const [filter, setFilter] = useState("");
  const [lines, setLines] = useState([]);
  const [connected, setConnected] = useState(false);
  const logRef = useRef(null);
  const selected = items.find(item => String(item.id) === String(selectedId)) || items[0];
  const filtered = items.filter(item =>
    `${item.name} ${item.id}`.toLowerCase().includes(filter.toLowerCase()));

  useEffect(() => {
    if (!selected && items.length) setSelectedId(String(items[0].id));
  }, [items, selected]);

  useEffect(() => {
    if (!selected) return undefined;
    let active = true;
    const load = async () => {
      try {
        const query = new URLSearchParams({ id: selected.id, name: selected.name, limit: "500" });
        const data = await request(`/api/v1/process-logs?${query}`);
        if (active) { setLines(data.lines || []); setConnected(true); }
      } catch {
        if (active) setConnected(false);
      }
    };
    load();
    const timer = setInterval(load, 1000);
    return () => { active = false; clearInterval(timer); };
  }, [selected?.id, selected?.name]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [lines]);

  return <section className="process-workspace">
    <section className="process-list-panel">
      <header><div><h2>进程列表</h2><p>{items.length} 个运行进程</p></div></header>
      <div className="process-search"><Search size={17} /><input value={filter}
        onChange={event => setFilter(event.target.value)} placeholder="搜索进程或 PID" /></div>
      <div className="process-list">{filtered.map(item => <button key={item.id}
        className={String(item.id) === String(selected?.id) ? "active" : ""}
        onClick={() => setSelectedId(String(item.id))}>
        <span className="inventory-icon process"><AppWindow size={17} /></span>
        <div><b>{item.name}</b><small>PID {item.pid || item.id}</small></div>
        <Status state={item.state} />
      </button>)}
      {!filtered.length && <div className="process-list-empty">没有匹配的进程</div>}</div>
    </section>
    <section className="process-log-panel">
      <header><div className="terminal-title"><span><Terminal size={18} /></span><div>
        <h2>{selected?.name || "选择一个进程"}</h2><p>{selected ? `PID ${selected.pid || selected.id} · 实时日志` : "—"}</p>
      </div></div><div className={`live-indicator ${connected ? "online" : ""}`}><i />
        {connected ? "实时连接" : "等待日志"}</div></header>
      <div className="terminal" ref={logRef}>{lines.length
        ? lines.map((line, index) => <div className="terminal-line" key={`${index}-${line.slice(0, 20)}`}>
          <span>{String(index + 1).padStart(3, "0")}</span><code>{line}</code></div>)
        : <div className="terminal-empty"><Terminal size={28} /><p>当前进程暂无日志输出</p></div>}</div>
      <footer><span>每秒自动刷新</span><span>最近 {lines.length} 行</span></footer>
    </section>
  </section>;
}

function ProcessWorkbench({ mainProcess, onNotify }) {
  const [selected, setSelected] = useState(null);
  const [trail, setTrail] = useState([]);
  const [detail, setDetail] = useState(null);
  const [history, setHistory] = useState([]);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState("");
  const [drafts, setDrafts] = useState({});
  const [collapsedSections, setCollapsedSections] = useState({});
  const toggleSection = section => setCollapsedSections(current => ({
    ...current, [section]: !current[section]
  }));

  useEffect(() => {
    if (!mainProcess || selected) return;
    setSelected(mainProcess);
    setTrail([mainProcess]);
  }, [mainProcess, selected]);

  useEffect(() => {
    if (!selected) return undefined;
    let active = true;
    const load = async () => {
      try {
        const query = new URLSearchParams({ id: selected.pid ?? selected.id, name: selected.name });
        const data = await request(`/api/v1/process-detail?${query}`);
        if (!active) return;
        setDetail(data);
        const resources = data.resources || {};
        setHistory(current => [...current, {
          cpu: numeric(resources.cpuPercent), memory: numeric(resources.memoryPercent),
          disk: numeric(resources.diskPercent), networkReceive: numeric(resources.networkReceiveKbps),
          networkSend: numeric(resources.networkSendKbps), threads: numeric(resources.threadCount)
        }].slice(-60));
      } catch { if (active) setDetail(null); }
    };
    setHistory([]);
    load();
    const timer = setInterval(load, 2000);
    return () => { active = false; clearInterval(timer); };
  }, [selected?.id, revision]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setDrafts(detail?.configuration || {});
  }, [detail?.process?.id, revision]); // eslint-disable-line react-hooks/exhaustive-deps

  const selectProcess = process => {
    setSelected(process);
    setTrail(current => {
      const existing = current.findIndex(item => String(item.id) === String(process.id));
      return existing >= 0 ? current.slice(0, existing + 1) : [...current, process];
    });
  };
  const goBack = () => {
    if (trail.length < 2) return;
    const nextTrail = trail.slice(0, -1);
    setTrail(nextTrail);
    setSelected(nextTrail[nextTrail.length - 1]);
  };
  const configEntries = Object.entries(detail?.configuration || {});
  const editable = new Set(detail?.editableConfiguration || []);
  const bundles = detail?.bundles || [];
  const children = detail?.children || [];
  const operateBundle = async (bundle, action) => {
    const verb = action === "start" ? "启动" : action === "stop" ? "停止" : "重启";
    if (action !== "start" && !window.confirm(`确认${verb} ${bundle.name}？`)) return;
    setBusy(`bundle:${bundle.id}`);
    try {
      const result = await request("/api/v1/bundle-lifecycle", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: bundle.id, action })
      });
      onNotify?.(result.message || `${verb}完成`);
      setRevision(value => value + 1);
    } catch (error) { onNotify?.(error.message, true); }
    finally { setBusy(""); }
  };
  const operateProcess = async (process, action) => {
    const verb = action === "start" ? "启动" : action === "stop" ? "停止" : "重启";
    if (action !== "start" && !window.confirm(`确认${verb} ${process.name}？`)) return;
    setBusy(`process:${process.id}`);
    try {
      const result = await request("/api/v1/process-lifecycle", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: process.id, action })
      });
      onNotify?.(result.message || `${verb}完成`);
      setRevision(value => value + 1);
    } catch (error) { onNotify?.(error.message, true); }
    finally { setBusy(""); }
  };
  const applyConfiguration = async key => {
    setBusy(`config:${key}`);
    try {
      const result = await request("/api/v1/process-config", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key, value: String(drafts[key] ?? "") })
      });
      onNotify?.(result.message || "配置已立即生效");
      setRevision(value => value + 1);
    } catch (error) { onNotify?.(error.message, true); }
    finally { setBusy(""); }
  };

  return <div className="process-workbench">
    <div className="process-guide">
      <div className="guide-label"><span>进程引导</span>{trail.map((item, index) =>
        <React.Fragment key={item.id}>
          {index > 0 && <ChevronRight size={22} />}
          <button className={String(item.id) === String(selected?.id) ? "active" : ""}
            onClick={() => selectProcess(item)}><AppWindow size={20} />{item.name}</button>
        </React.Fragment>)}</div>
      <button className="guide-back" disabled={trail.length < 2} onClick={goBack}>
        <ArrowLeft size={24} />返回上一个
      </button>
    </div>

    <section className="selected-process-head">
      <div><span className="inventory-icon process"><AppWindow size={28} /></span><div>
        <p>{detail?.process?.main ? "当前主进程" : "当前子进程"}</p>
        <h2>{detail?.process?.name || selected?.name || "加载中"}</h2>
        <small>PID {detail?.process?.pid || selected?.pid || selected?.id || "—"}</small>
      </div></div><Status state={detail?.process?.state || "running"} />
    </section>

    <div className="workbench-grid">
      <section className="surface child-process-card">
        <div className="section-head"><div><h2>加载的子进程</h2><p>点击进入子进程工作台</p></div>
          <div className="section-head-actions"><span className="inventory-count">{children.length} 个</span>
            <button className={`section-collapse ${collapsedSections.children ? "collapsed" : ""}`}
              onClick={() => toggleSection("children")} aria-expanded={!collapsedSections.children}
              title={collapsedSections.children ? "展开子进程列表" : "折叠子进程列表"}>
              <ChevronDown size={24} />
            </button>
          </div></div>
        {!collapsedSections.children && <div className="child-process-list">{children.map(child => <div className="child-process-item" key={child.id}>
          <button className="child-process-open" onClick={() => selectProcess(child)}>
            <div className="child-process-title"><span className="inventory-icon process"><AppWindow size={24} /></span>
              <div><b>{child.name}</b><small>{child.pid ? `PID ${child.pid}` : "尚未分配 PID"}</small></div>
              <ChevronRight size={27} /></div>
            <div className="child-process-facts">
              <span><small>在线状态</small><strong className={child.online ? "online" : "offline"}>
                <i />{child.online ? "在线" : "离线"}</strong></span>
              <span><small>进程位置</small><strong>
                <span className={`location-badge ${child.location || "local"}`}>
                  {(child.location || "local") === "remote" ? "远程进程" : "本地进程"}
                </span></strong></span>
              <span><small>运行状态</small><Status state={child.state} /></span>
              <span><small>所在主机</small><strong>{child.host || (child.location === "remote" ? "远程主机" : "本机")}</strong></span>
            </div>
          </button>
          <div className="process-life-actions">
            <button title="启动" disabled={busy || !child.manageable || child.state === "running"}
              onClick={() => operateProcess(child, "start")}><Play size={18} /></button>
            <button title="停止" disabled={busy || !child.manageable || child.state !== "running"}
              onClick={() => operateProcess(child, "stop")}><Square size={18} /></button>
            <button title="重启" disabled={busy || !child.manageable || child.state !== "running"}
              onClick={() => operateProcess(child, "restart")}><RotateCw size={18} /></button>
          </div>
        </div>)}
        {!children.length && <div className="workbench-empty">当前进程没有加载子进程</div>}</div>}
      </section>
      <section className="surface process-resource-card">
        <div className="section-head"><div><h2>当前进程资源消耗</h2><p>CPU、内存、磁盘、网络与线程</p></div>
          <span className="healthy"><i />每 2 秒刷新</span></div>
        <ResourceCharts resources={detail?.resources || {}} history={history} />
      </section>
    </div>

    <div className="workbench-detail-grid">
      <div className="workbench-detail-stack">
        <section className="surface process-bundles-card">
        <div className="section-head"><div><h2>当前进程加载的 Bundles</h2><p>实际 Bundle 生命周期状态</p></div>
          <div className="section-head-actions"><span className="inventory-count">{bundles.length} 个</span>
            <button className={`section-collapse ${collapsedSections.bundles ? "collapsed" : ""}`}
              onClick={() => toggleSection("bundles")} aria-expanded={!collapsedSections.bundles}
              title={collapsedSections.bundles ? "展开 Bundle 列表" : "折叠 Bundle 列表"}>
              <ChevronDown size={24} />
            </button>
          </div></div>
        {!collapsedSections.bundles && <div className="bundle-detail-list">{bundles.map(bundle => <div key={bundle.id}>
          <span className="inventory-icon bundle"><Boxes size={24} /></span>
          <div><b>{bundle.name}</b><small>{bundle.id} · {bundle.version || "版本未知"}</small></div>
          <Status state={bundle.state} />
          <div className="bundle-lifecycle">{bundle.manageable ? <>
            <button disabled={busy || String(bundle.state).toLowerCase() === "active"}
              onClick={() => operateBundle(bundle, "start")}><Play size={23} />启动</button>
            <button disabled={busy || String(bundle.state).toLowerCase() !== "active"}
              onClick={() => operateBundle(bundle, "stop")}><Square size={22} />停止</button>
            <button disabled={busy || String(bundle.state).toLowerCase() !== "active"}
              onClick={() => operateBundle(bundle, "restart")}><RotateCw size={22} />重启</button>
          </> : <span className="protected-bundle">核心组件 · 只读</span>}</div>
        </div>)}{!bundles.length && <div className="workbench-empty">当前进程没有 Bundle 数据</div>}</div>}
        </section>
        <section className="surface process-config-card">
        <div className="section-head"><div><h2>当前进程配置信息</h2><p>敏感字段已自动隐藏</p></div>
          <div className="section-head-actions"><span className="inventory-count">{configEntries.length} 项</span>
            <button className={`section-collapse ${collapsedSections.configuration ? "collapsed" : ""}`}
              onClick={() => toggleSection("configuration")} aria-expanded={!collapsedSections.configuration}
              title={collapsedSections.configuration ? "展开配置信息" : "折叠配置信息"}>
              <ChevronDown size={24} />
            </button>
          </div></div>
        {!collapsedSections.configuration && <div className="config-detail-list">{configEntries.map(([key, value]) => <div key={key}>
          <b>{key}</b><code>{String(value)}</code>
          {editable.has(key) ? <div className="config-edit">
            <input value={String(drafts[key] ?? value)}
              onChange={event => setDrafts(current => ({ ...current, [key]: event.target.value }))} />
            <button disabled={busy || String(drafts[key] ?? value) === String(value)}
              onClick={() => applyConfiguration(key)}><Zap size={21} />立即生效</button>
          </div> : <span className="readonly-config">只读</span>}
        </div>)}{!configEntries.length && <div className="workbench-empty">当前进程没有可读取的配置</div>}</div>}
        </section>
      </div>
    </div>
    <BusinessExecutionList process={detail?.process || selected} />
  </div>;
}

function EntityActions({ item, onConfig, onLife }) {
  const canStart = item.kind === "bundle" && item.state !== "active";
  return <div className="entity-actions">
    <button className="icon-button" title="配置" onClick={() => onConfig(item)}><Settings2 size={16} /></button>
    <button className="icon-button" title={canStart ? "启动" : "重启"}
      onClick={() => onLife(item, canStart ? "start" : "restart")}>
      {canStart ? <Play size={16} /> : <RotateCw size={16} />}
    </button>
    {item.kind !== "process" &&
      <button className="icon-button danger" title="卸载" onClick={() => onLife(item, "uninstall")}><Trash2 size={16} /></button>}
  </div>;
}

function EntityTable({ items, onConfig, onLife, searchable = true }) {
  const [filter, setFilter] = useState("");
  const filtered = items.filter(item =>
    `${item.name} ${item.id} ${item.owner || ""}`.toLowerCase().includes(filter.toLowerCase()));
  return <section className="surface">
    {searchable && <div className="table-tools"><div className="search"><Search size={17} /><input value={filter}
      onChange={event => setFilter(event.target.value)} placeholder="搜索名称、标识或所属 Bundle" /></div>
      <span>{filtered.length} 项</span></div>}
    <div className="table-scroll">
      <table className="entity-table">
        <thead><tr><th>名称</th><th>状态</th><th>所属 / 版本</th><th /></tr></thead>
        <tbody>{filtered.map(item => <tr key={`${item.kind}-${item.id}`}>
          <td><div className="entity-name"><span className={`entity-glyph ${item.kind}`}><Box size={17} /></span>
            <div><b>{item.name}</b><small>{item.id}</small></div></div></td>
          <td><Status state={item.state} /></td>
          <td className="secondary-text">{item.owner || item.version || item.type || "—"}</td>
          <td><EntityActions item={item} onConfig={onConfig} onLife={onLife} /></td>
        </tr>)}</tbody>
      </table>
      {!filtered.length && <div className="empty"><Boxes size={26} /><p>没有匹配的项目</p></div>}
    </div>
  </section>;
}

function ConfigModal({ target, onClose, onDone }) {
  const [rows, setRows] = useState([]);
  const [restart, setRestart] = useState(true);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (!target) return;
    request(`/api/v1/config?kind=${encodeURIComponent(target.kind)}&id=${encodeURIComponent(target.id)}`)
      .then(data => setRows(Object.entries(data.values || {}).map(([key, value]) => ({ key, value }))))
      .catch(error => onDone(error.message, true));
  }, [target, onDone]);
  if (!target) return null;
  const update = (index, field, value) => setRows(current =>
    current.map((row, rowIndex) => rowIndex === index ? { ...row, [field]: value } : row));
  const save = async () => {
    setSaving(true);
    try {
      const changes = Object.fromEntries(rows.filter(row => row.key.trim()).map(row => [row.key.trim(), row.value]));
      const data = await request("/api/v1/config", {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: target.kind, id: target.id, changes, restart })
      });
      onDone(data.message || "配置已应用");
      onClose();
    } catch (error) { onDone(error.message, true); }
    finally { setSaving(false); }
  };
  return <div className="modal-backdrop" onMouseDown={event => event.target === event.currentTarget && onClose()}>
    <div className="modal">
      <header><div><span>运行时配置</span><h2>{target.name}</h2><p>{target.kind} · {target.id}</p></div>
        <button className="close" onClick={onClose}><X size={20} /></button></header>
      <div className="config-list">
        {rows.map((row, index) => <div className="config-row" key={index}>
          <input value={row.key} placeholder="配置键" onChange={event => update(index, "key", event.target.value)} />
          <input value={row.value} placeholder="配置值" onChange={event => update(index, "value", event.target.value)} />
          <button onClick={() => setRows(current => current.filter((_, i) => i !== index))}><X size={16} /></button>
        </div>)}
        {!rows.length && <div className="modal-empty">暂无配置项，可在下方添加</div>}
      </div>
      <button className="add-config" onClick={() => setRows(current => [...current, { key: "", value: "" }])}>＋ 添加配置项</button>
      <label className="toggle-row"><input type="checkbox" checked={restart} onChange={event => setRestart(event.target.checked)} />
        <span><b>应用后重启所属 Bundle</b><small>让 Bundle Activator 重新读取配置</small></span></label>
      <footer><button className="ghost" onClick={onClose}>取消</button><button className="primary" disabled={saving} onClick={save}>
        <Zap size={16} />{saving ? "应用中…" : "立即应用"}</button></footer>
    </div>
  </div>;
}

function Logs() {
  const [filters, setFilters] = useState({ text: "", level: "", source: "", limit: 300 });
  const [logs, setLogs] = useState([]);
  const load = useCallback(async () => {
    const query = new URLSearchParams(filters);
    const data = await request(`/api/v1/logs?${query}`);
    setLogs(data.logs || []);
  }, [filters]);
  useEffect(() => { load().catch(() => {}); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return <section className="surface logs">
    <div className="log-tools">
      <div className="search grow"><Search size={17} /><input placeholder="搜索日志内容" value={filters.text}
        onChange={e => setFilters({ ...filters, text: e.target.value })} /></div>
      <select value={filters.level} onChange={e => setFilters({ ...filters, level: e.target.value })}>
        <option value="">全部级别</option>{["fatal", "critical", "error", "warning", "notice", "information", "debug", "trace"].map(x => <option key={x}>{x}</option>)}
      </select>
      <input className="source-filter" placeholder="Logger 来源" value={filters.source}
        onChange={e => setFilters({ ...filters, source: e.target.value })} />
      <button className="primary" onClick={() => load().catch(() => {})}><SlidersHorizontal size={16} />查询</button>
    </div>
    <div className="table-scroll"><table className="log-table"><thead><tr><th>时间</th><th>级别</th><th>来源</th><th>消息</th></tr></thead>
      <tbody>{logs.map((log, index) => <tr key={index}><td>{log.time}</td><td><span className={`level ${log.level}`}>{log.level}</span></td>
        <td>{log.source}</td><td>{log.message}</td></tr>)}</tbody></table>
      {!logs.length && <div className="empty"><FileText size={26} /><p>暂无匹配日志</p></div>}</div>
  </section>;
}

function App() {
  const [page, setPage] = useState("overview");
  const [menuOpen, setMenuOpen] = useState(false);
  const [topology, setTopology] = useState({ processes: [], services: [], modules: [], bundles: [] });
  const [resourceHistory, setResourceHistory] = useState([]);
  const [updated, setUpdated] = useState(null);
  const [configTarget, setConfigTarget] = useState(null);
  const [toast, setToast] = useState(null);
  const refresh = useCallback(async () => {
    const [data, monitoring] = await Promise.all([
      request("/api/v1/topology"),
      request("/api/v1/system-metrics").catch(() => ({ samples: [] }))
    ]);
    const samples = monitoring.samples || [];
    const monitoredResources = monitoring.current || {};
    if (Object.keys(monitoredResources).length)
      data.resources = { ...(data.resources || {}), ...monitoredResources };
    setTopology(data);
    const resources = data.resources || data.system || {};
    setResourceHistory(current => samples.length ? samples.map(sample => ({
      cpu: numeric(sample.cpuPercent), memory: numeric(sample.memoryPercent),
      disk: numeric(sample.diskPercent), networkReceive: numeric(sample.networkReceiveKbps),
      networkSend: numeric(sample.networkSendKbps), threads: numeric(sample.threadCount)
    })).slice(-60) : [...current, {
      cpu: numeric(resources.cpuPercent ?? resources.cpu),
      memory: numeric(resources.memoryPercent ?? resources.memory),
      disk: numeric(resources.diskPercent ?? resources.disk),
      networkReceive: numeric(resources.networkReceiveKbps),
      networkSend: numeric(resources.networkSendKbps),
      threads: numeric(resources.threadCount)
    }].slice(-60));
    setUpdated(new Date());
  }, []);
  useEffect(() => {
    refresh().catch(error => setToast({ message: error.message, error: true }));
    const timer = setInterval(() => refresh().catch(() => {}), 5000);
    return () => clearInterval(timer);
  }, [refresh]);
  const notify = useCallback((message, error = false) => {
    setToast({ message, error }); setTimeout(() => setToast(null), 2800);
  }, []);
  const life = async (item, action) => {
    if (["restart", "uninstall"].includes(action) && !window.confirm(`确认${action === "restart" ? "重启" : "卸载"} ${item.name}？`)) return;
    try {
      const data = await request("/api/v1/lifecycle", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: item.kind, id: item.id, action }) });
      notify(data.message || "操作已完成"); setTimeout(refresh, 400);
    } catch (error) { notify(error.message, true); }
  };
  const counts = useMemo(() => ({
    process: (topology.mainProcess ? 1 : 0) +
      topology.processes.filter(item => String(item.name).toLowerCase() !== "conhost.exe").length,
    module: topology.modules.length, bundle: topology.bundles.length
  }), [topology]);
  const processItems = [
    ...(topology.mainProcess ? [{ ...topology.mainProcess, name: `${topology.mainProcess.name}（主进程）` }] : []),
    ...topology.processes.filter(item => String(item.name).toLowerCase() !== "conhost.exe")
  ];
  const currentItems = page === "processes" ? processItems : page === "services" ? topology.services :
    page === "modules" ? topology.modules : topology.bundles;

  return <div className="app-shell">
    <aside className={menuOpen ? "open" : ""}>
      <div className="brand"><span><Activity size={21} /></span><div><b>PocoDDS</b><small>Runtime Console</small></div></div>
      <nav>{navItems.map(([id, Icon]) => <button key={id} className={page === id ? "active" : ""}
        onClick={() => { setPage(id); setMenuOpen(false); }}><Icon size={18} /><span>{pageMeta[id][0]}</span><ChevronRight size={15} /></button>)}</nav>
      <div className="runtime-state"><i /><div><b>Runtime Online</b><small>{topology.host || "Local host"}</small></div></div>
    </aside>
    <main>
      <header className="topbar">
        <button className="mobile-menu" onClick={() => setMenuOpen(!menuOpen)}><Menu size={20} /></button>
        <div><p>管理控制台</p><h1>{pageMeta[page][0]}</h1><span>{pageMeta[page][1]}</span></div>
        <div className="top-actions"><span className="last-update"><Clock3 size={15} />{updated ? updated.toLocaleTimeString() : "连接中"}</span>
          <button className="refresh" onClick={() => refresh().catch(error => notify(error.message, true))}><RefreshCw size={17} />刷新</button></div>
      </header>
      <div className="content">
        {page === "overview" && <ProcessWorkbench mainProcess={topology.mainProcess} onNotify={notify} />}
        {page === "processes" && <ProcessWorkspace items={processItems} />}
        {["services", "modules", "bundles"].includes(page) &&
          <EntityTable items={currentItems} onConfig={setConfigTarget} onLife={life} />}
        {page === "logs" && <Logs />}
      </div>
    </main>
    {menuOpen && <button className="mobile-overlay" onClick={() => setMenuOpen(false)} />}
    <ConfigModal target={configTarget} onClose={() => setConfigTarget(null)} onDone={notify} />
    {toast && <div className={`toast ${toast.error ? "error" : ""}`}>{toast.error ? <X size={17} /> : <Zap size={17} />}{toast.message}</div>}
  </div>;
}

createRoot(document.getElementById("root")).render(<App />);
