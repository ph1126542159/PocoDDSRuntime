import React, { useCallback, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity, AppWindow, Box, Boxes, ChevronRight, CircleGauge, Clock3,
  FileText, Layers3, Menu, Play, RefreshCw, RotateCw, Search, Server,
  Settings2, SlidersHorizontal, Square, Trash2, X, Zap
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

function Metric({ icon: Icon, label, value, caption, tone }) {
  return <article className="metric">
    <div className={`metric-icon ${tone}`}><Icon size={20} strokeWidth={1.8} /></div>
    <div><span>{label}</span><strong>{value}</strong><small>{caption}</small></div>
  </article>;
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
  const [updated, setUpdated] = useState(null);
  const [configTarget, setConfigTarget] = useState(null);
  const [toast, setToast] = useState(null);
  const refresh = useCallback(async () => {
    const data = await request("/api/v1/topology");
    setTopology(data); setUpdated(new Date());
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
    process: topology.processes.length, service: topology.services.length,
    module: topology.modules.length, bundle: topology.bundles.length
  }), [topology]);
  const currentItems = page === "processes" ? topology.processes : page === "services" ? topology.services :
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
        {page === "overview" && <><div className="metrics">
          <Metric icon={AppWindow} label="运行进程" value={counts.process} caption="当前主机" tone="blue" />
          <Metric icon={Server} label="注册服务" value={counts.service} caption="OSP Registry" tone="green" />
          <Metric icon={Layers3} label="组件模块" value={counts.module} caption="已加载" tone="violet" />
          <Metric icon={Boxes} label="Bundles" value={counts.bundle} caption="运行时集合" tone="orange" />
        </div><section className="surface overview-panel"><div className="section-head"><div><h2>运行时资源</h2><p>全部资源的实时状态</p></div>
          <span className="healthy"><i />系统运行正常</span></div>
          <EntityTable items={[...topology.processes, ...topology.services, ...topology.bundles].slice(0, 8)}
            onConfig={setConfigTarget} onLife={life} searchable={false} /></section></>}
        {["processes", "services", "modules", "bundles"].includes(page) &&
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
