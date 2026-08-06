import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { createRoot } from "react-dom/client";
import {
  Activity, AppWindow, ArrowLeft, Box, Boxes, ChevronDown, ChevronRight, Clock3,
  Cpu, Download, FileText, HardDrive, Layers3, MemoryStick, Menu, Network, Play, RefreshCw, RotateCw, Search, Server,
  SlidersHorizontal, Square, Terminal, X, Zap, ShieldCheck, Undo2,
  AlertTriangle, CheckCircle2, Database, GitBranch
} from "lucide-react";
import "./styles.css";
import "./embedded.css";
import "./flow-layout.css";
import "./bright-theme.css";

const pageMeta = {
  overview: ["运行态势", "实时掌握运行时状态与资源"],
  processes: ["进程管理", "当前运行时挂载的进程"],
  services: ["服务", "OSP 服务注册中心"],
  devices: ["设备", "当前运行时已装载的设备适配器"],
  modules: ["组件与模块", "Bundle 提供的运行时模块"],
  bundles: ["Bundles", "OSP Bundle 生命周期管理"],
  plugins: ["插件治理", "外部插件兼容性、依赖与生命周期"],
  logs: ["日志中心", "快速定位运行时问题"],
  metrics: ["指标中心", "按运行域查看 OpenTelemetry Counter 与 Histogram"]
};

const navItems = [
  ["overview", Activity], ["processes", AppWindow], ["services", Server], ["devices", Cpu],
  ["modules", Layers3], ["bundles", Boxes], ["plugins", Boxes], ["metrics", Activity], ["logs", FileText]
];

async function request(path, options = {}) {
  const token = sessionStorage.getItem("pdr.webui.token") || "";
  const method = String(options.method || "GET").toUpperCase();
  const headers = { ...(options.headers || {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) };
  if (!["GET", "HEAD"].includes(method) && !headers["X-PDR-Request-Id"]) {
    headers["X-PDR-Request-Id"] = globalThis.crypto?.randomUUID?.() ||
      `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }
  const response = await fetch(path, {
    ...options,
    headers
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
  const normalized = String(state).toLowerCase();
  const running = ["active", "running", "started", "ready"].includes(normalized);
  const failed = ["fault", "failed", "error", "down"].includes(normalized);
  return <span className={`status ${running ? "ok" : failed ? "bad" : "idle"}`}><i />{state}</span>;
}

function FailureDetail({ failure, legacy }) {
  if (!failure && !legacy) return <span className="secondary-text">—</span>;
  if (!failure) return <em className="legacy-error" title={legacy}>{legacy}</em>;
  const occurred = numeric(failure.occurredAtMicroseconds);
  return <div className={`failure-detail ${failure.active ? "active" : "resolved"}`}>
    <code>{failure.code}</code>
    <span>{failure.category} · {failure.retryable ? "可重试" : "不可重试"} · {failure.active ? "当前故障" : "已恢复"}</span>
    <em title={failure.message}>{failure.message || legacy || "无错误文本"}</em>
    {!!occurred && <small>{new Date(occurred / 1000).toLocaleString()}</small>}
  </div>;
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

function validateConfigValue(key, value) {
  const ranges = {
    "osp.web.server.port": [1, 65535],
    "pdr.fastdds.domainId": [0, 232],
    "pdr.subprocess.shutdownTimeoutMilliseconds": [1, 3600000],
    "pdr.alerts.debounceMilliseconds": [0, 604800000],
    "pdr.alerts.escalationMilliseconds": [0, 604800000],
    "pdr.alerts.retention": [1, 100000],
    "pdr.alerts.deliveryQueueCapacity": [1, 100000],
    "pdr.alerts.deliveryFailureThreshold": [1, 1000],
    "pdr.alerts.deliveryCircuitOpenMilliseconds": [100, 3600000],
    "pdr.alerts.history.maximumBytes": [1024, 1073741824],
    "pdr.alerts.webhook.timeoutMilliseconds": [100, 60000],
    "pdr.alerts.webhook.maximumAttempts": [1, 10],
    "pdr.alerts.webhook.initialBackoffMilliseconds": [0, 60000],
    "pdr.alerts.webhook.maximumBackoffMilliseconds": [0, 60000],
    "observability.history.retentionDays": [1, 36500],
    "pdr.modbus.port": [1, 65535],
    "pdr.modbus.unitId": [0, 247],
    "pdr.modbus.timeoutMilliseconds": [1, 60000],
    "pdr.modbus.readRetryAttempts": [0, 10],
    "pdr.modbus.retryDelayMilliseconds": [0, 60000],
    "pdr.serial.baudRate": [1, 4000000],
    "pdr.serial.reconnectDelayMilliseconds": [0, 60000],
    "pdr.serial.readTimeoutMilliseconds": [1, 60000],
    "pdr.can.bitOffset": [0, 511],
    "pdr.can.bitLength": [1, 64],
    "pdr.can.reconnectDelayMilliseconds": [0, 60000],
    "pdr.can.receiveTimeoutMilliseconds": [1, 60000],
    "pdr.can.staleAfterMilliseconds": [1, 60000],
    "pdr.gnss.baudRate": [1, 4000000]
  };
  const rangeKey = key
    .replace(/^pdr\.alerts\.webhook\.\d+\./, "pdr.alerts.webhook.")
    .replace(/^(pdr\.[^.]+)\.\d+\./, "$1.");
  if (!ranges[rangeKey]) return "";
  if (!/^-?\d+$/.test(String(value).trim())) return "必须是整数";
  const number = Number(value);
  const [minimum, maximum] = ranges[rangeKey];
  return number < minimum || number > maximum ? `有效范围 ${minimum}–${maximum}` : "";
}

function AlertSinkOverview({ inventory, metrics }) {
  const sinks = inventory?.sinks || [];
  const delivery = result => (metrics?.metrics || [])
    .filter(point => point.name === "pdr.alert.delivery" && point.attributes?.result === result)
    .reduce((total, point) => total + numeric(point.value), 0);
  const success = delivery("success");
  const errors = delivery("error");
  const dropped = delivery("dropped");
  const circuitOpen = delivery("circuit_open");
  return <div className="alert-sink-overview">
    <div className="alert-sink-heading"><span>投递通道</span><b>{sinks.length} 个已注册</b></div>
    <div className="alert-sink-list">{sinks.map(sink => <span key={sink.service}
      className={["degraded", "circuit-open"].includes(sink.status) ? "degraded" : sink.registered ? "registered" : "missing"}
      title={sink.lastError || sink.service}>
      <i />{sink.name}<small>{sink.type} · {sink.status || "idle"}</small>
      <em>{numeric(sink.successes)} 成功 / {numeric(sink.failures)} 失败{numeric(sink.dropped) ? ` · 丢弃 ${numeric(sink.dropped)}` : ""}{sink.delivering || numeric(sink.queueDepth) ? ` · 投递中 ${numeric(sink.queueDepth)} 排队` : ""}{sink.circuitOpen ? ` · 熔断延迟 ${numeric(sink.circuitOpenSkips)}` : ""}</em>
    </span>)}{!sinks.length && <em>当前未发现告警 Sink</em>}</div>
    <div className="alert-delivery-summary">
      <span className="ok">成功 {success}</span>
      <span className={errors ? "bad" : "idle"}>失败 {errors}</span>
      <span className={dropped ? "bad" : "idle"}>丢弃 {dropped}</span>
      <span className={circuitOpen ? "bad" : "idle"}>熔断延迟 {circuitOpen}</span>
    </div>
  </div>;
}

function HealthOverview({ health, diagnosticEvents, alertInventory, alertHistory, alertSinks, metrics }) {
  const status = String(health?.status || "UNKNOWN").toUpperCase();
  const healthy = status === "UP";
  const components = health?.components || [];
  const capabilities = [
    ["配置校验", "启动 fail-fast", ShieldCheck],
    ["Workflow", "步骤与补偿", GitBranch],
    ["可靠性", "限流、熔断与背压", Activity],
    ["持久化", "Repository 与迁移", Database]
  ];
  return <section className={`platform-health ${healthy ? "up" : "attention"}`}>
    <header>
      <div className="health-title">
        <span>{healthy ? <CheckCircle2 /> : <AlertTriangle />}</span>
        <div><small>平台健康状态</small><h2>{healthy ? "运行就绪" : status === "UNKNOWN" ? "状态获取中" : "需要关注"}</h2>
          <p>来自 /health/detail 的 Runtime、Bundle 与子进程聚合结果</p></div>
      </div>
      <div className="health-flags"><span className={health?.live ? "ok" : "bad"}>LIVE {health?.live ? "正常" : "异常"}</span>
        <span className={health?.ready ? "ok" : "bad"}>READY {health?.ready ? "就绪" : "未就绪"}</span></div>
    </header>
    <div className="health-grid">
      <div className="health-components">{components.map(component =>
        <article key={component.name} className={component.code ? "has-diagnostic" : ""}>
          <i className={String(component.status).toLowerCase()} />
          <div><b>{component.name}</b><small>{component.detail || "无详情"}</small>
            {component.code && <div className="health-diagnostic">
              <code>{component.code}</code>
              {!!component.affected?.length && <span>影响：{component.affected.join("、")}</span>}
              {component.remediation && <em>{component.remediation}</em>}
            </div>}
          </div>
          <strong>{component.status}</strong></article>)}
        {!components.length && <div className="health-loading">等待健康数据…</div>}
      </div>
      <div className="health-side">
        <div className="capability-grid">{capabilities.map(([name, detail, Icon]) =>
          <article key={name}><Icon /><div><b>{name}</b><small>{detail}</small></div><span>已接入</span></article>)}</div>
        <div className="diagnostic-event-list"><h3>告警状态</h3>
          <small className="alert-policy">去抖 {numeric(alertInventory?.policy?.debounceMilliseconds)} ms · 升级 {numeric(alertInventory?.policy?.escalationMilliseconds)} ms</small>
          <AlertSinkOverview inventory={alertSinks} metrics={metrics} />
          {(alertInventory?.alerts || []).slice(0, 4).map(alert => <article key={alert.id}>
            <Status state={alert.status === "resolved" ? "ready" : alert.status === "pending" ? "pending" : "error"} />
            <div><b>{alert.instance}</b><code>{alert.code}</code>
              <small>{alert.status} · {alert.severity}{alert.silenced ? " · 已静默" : ""}{alert.suppressedByDebounce ? " · 去抖抑制" : ""} · {alert.observations} 次观察</small></div>
          </article>)}
          {!alertInventory?.alerts?.length && (alertHistory?.records || []).slice(0, 4).map(record => <article key={`${record.alertId}-${record.event}-${record.occurredAtMicroseconds}`}>
            <Status state={record.status === "resolved" ? "ready" : "error"} />
            <div><b>{record.instance}</b><code>{record.code}</code>
              <small>历史 {record.event} · {record.severity}{record.silenced ? " · 已静默" : ""}</small></div>
          </article>)}
          {!alertInventory?.alerts?.length && !alertHistory?.records?.length && <small className="diagnostic-event-empty">暂无告警；已记录 {diagnosticEvents?.length || 0} 条诊断事件</small>}
        </div>
      </div>
    </div>
  </section>;
}

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

function RuntimeTopologyOverview({ health, topology, processDetail, childProcessDetail, history, alertInventory, onOpenProcesses, onOpenLogs }) {
  const [range, setRange] = useState("1h");
  const mainProcess = processDetail?.process || topology.mainProcess;
  const children = processDetail?.children || [];
  const qt3d = children.find(item => String(item.name || item.id).toLowerCase().includes("qt3d")) || children[0];
  const mainRunning = ["active", "running", "ready"].includes(String(mainProcess?.state || "").toLowerCase());
  const childRunning = Boolean(qt3d?.online) || ["active", "running", "ready"].includes(String(qt3d?.state || "").toLowerCase());
  const workers = childRunning ? (childProcessDetail?.children || qt3d?.workers || qt3d?.renderWorkers || []) : [];
  const resources = processDetail?.resources || topology.resources || topology.system || {};
  const unresolvedAlerts = (alertInventory?.alerts || []).filter(item => item.status !== "resolved").length;
  const healthy = health?.status === "UP" && health?.live && health?.ready;
  const cpu = numeric(resources.cpuPercent ?? resources.cpu);
  const memory = numeric(resources.memoryPercent ?? resources.memory);
  const memoryUsed = numeric(resources.memoryUsedMb) / 1024;
  const memoryTotal = numeric(resources.memoryTotalMb) / 1024;
  const threadCount = numeric(resources.threadCount);
  const bundles = topology.bundles?.length || processDetail?.bundles?.length || 0;
  const rangeSamples = { "15m": 15, "1h": 60, "6h": 60, "24h": 60 }[range];
  const visibleHistory = history.slice(-rangeSamples);
  const processCount = (mainProcess ? 1 : 0) + (qt3d ? 1 : 0) + workers.length;
  const qt3dResources = childProcessDetail?.resources || qt3d?.resources || {};
  const stateText = value => ["active", "running", "ready"].includes(String(value || "").toLowerCase()) ? "运行中" : "已停止";
  const valueOrDash = (value, suffix = "") => value == null || value === "" ? "—" : `${numeric(value).toFixed(suffix === "%" ? 1 : 0)}${suffix}`;
  const row = (item, label, level, icon, running, itemResources = {}) => {
    const Icon = icon;
    return <div className={`precision-process-row level-${level}`} key={`${label}-${item?.pid || item?.id || level}`}>
      <div className="precision-process-name"><span className="tree-branch" /><Icon size={19} />
        <div><b>{label}</b><small>{level === 0 ? "主进程" : level === 1 ? "父进程" : "渲染节点"}</small></div></div>
      <code>{item?.pid || item?.id || "—"}</code>
      <span className={`precision-state ${running ? "ok" : "bad"}`}><i />{running ? "运行中" : "已停止"}</span>
      <span>{valueOrDash(itemResources.cpuPercent ?? itemResources.cpu, "%")}</span>
      <span>{itemResources.memoryUsedMb != null ? `${(numeric(itemResources.memoryUsedMb) / 1024).toFixed(1)} GB` : "—"}</span>
      <span>{itemResources.threadCount ?? "—"}</span>
    </div>;
  };

  return <section className="precision-overview" aria-label="Runtime 运行态势">
    <div className="precision-health-strip">
      <article className={healthy ? "healthy" : "attention"}><span><ShieldCheck /></span><div><b>{healthy ? "全部服务正常" : "系统需要关注"}</b><small>{healthy ? "系统运行稳定" : "请检查异常组件"}</small></div></article>
      <article><span><Server /></span><div><small>运行环境</small><b>生产环境</b><em>{health?.ready ? "环境健康" : "等待就绪"}</em></div></article>
      <article><span><Clock3 /></span><div><small>运行时长</small><b>{mainRunning ? "持续运行" : "未运行"}</b><em>主进程 PID {mainProcess?.pid || mainProcess?.id || "—"}</em></div></article>
      <article><span><Boxes /></span><div><small>Bundles</small><b>{bundles}/{bundles || "—"}</b><em>已就绪 / 总数</em></div></article>
      <article><span><AppWindow /></span><div><small>进程总数</small><b>{processCount}</b><em>主进程 1 · 子进程 {Math.max(0, processCount - 1)}</em></div></article>
    </div>

    <div className="precision-workspace">
      <section className="precision-topology">
        <header><div><h2>运行拓扑</h2><p>Runtime 与 Qt3D 进程链路</p></div><span><i />{workers.length} 个工作进程在线</span></header>
        <div className="precision-process-head"><span>进程 / 节点</span><span>PID</span><span>状态</span><span>CPU</span><span>内存</span><span>线程</span></div>
        <div className="precision-process-tree">
          {row(mainProcess, "Runtime 主进程", 0, Box, mainRunning, resources)}
          {row(qt3d, "Qt3D 子进程", 1, Layers3, childRunning, qt3dResources)}
          <div className="precision-worker-label"><span />{workers.length || 0} 个渲染工作进程</div>
          {workers.map((worker, index) => {
            const workerName = String(worker.name || "").toLowerCase();
            const label = workerName.includes("scene") ? "场景渲染进程" : workerName.includes("material") ? "材质渲染进程" :
              workerName.includes("device") ? "设备渲染进程" : `渲染工作进程 #${index + 1}`;
            return row(worker, label, 2, AppWindow,
              ["active", "running", "ready"].includes(String(worker.state || "running").toLowerCase()), worker.resources || worker);
          })}
          {!workers.length && <div className="precision-process-empty"><AlertTriangle size={18} />当前没有渲染工作进程</div>}
        </div>
        <footer><div className="precision-legend"><span><i />父子进程关系</span><span><i />监控连接</span></div>
          <div><button className="precision-primary" onClick={onOpenProcesses}>打开进程工作台 <ChevronRight size={17} /></button>
            <button className="precision-secondary" onClick={onOpenLogs}><FileText size={17} />查看完整日志</button></div></footer>
      </section>

      <aside className="precision-attention">
        <header><h2>需要关注</h2><span>{unresolvedAlerts ? `${unresolvedAlerts} 项未处理` : "当前正常"}</span></header>
        <article className="attention-summary"><span><CheckCircle2 /></span><div><b>{unresolvedAlerts ? "存在待处理事件" : "暂无阻断问题"}</b><p>{unresolvedAlerts ? "建议查看告警详情并确认影响范围" : "当前系统运行正常，继续保持"}</p></div></article>
        {memory >= 80 && <article className="attention-item warning"><AlertTriangle /><div><b>内存使用率偏高</b><p>当前使用率 {percent(memory)}，建议持续关注</p><small>刚刚</small></div></article>}
        <article className="attention-item info"><Boxes /><div><b>Bundles 已就绪</b><p>{bundles} 个 Bundles 已成功加载</p><small>状态同步完成</small></div></article>
        <article className={`attention-item ${childRunning ? "success" : "warning"}`}>{childRunning ? <CheckCircle2 /> : <AlertTriangle />}<div>
          <b>{childRunning ? "Qt3D 链路正常" : "Qt3D 子进程未运行"}</b><p>{childRunning ? `${workers.length} 个渲染工作进程在线` : "打开进程工作台查看启动日志"}</p><small>{stateText(qt3d?.state)}</small></div></article>
        <button className="attention-more" onClick={onOpenLogs}>查看全部事件 <ChevronRight size={16} /></button>
      </aside>
    </div>

    <section className="precision-resources">
      <header><div><h2>资源趋势</h2><p>最近 {range === "15m" ? "15 分钟" : range === "1h" ? "60 分钟" : range === "6h" ? "6 小时" : "24 小时"}</p></div>
        <div className="precision-range">{[["15m", "15 分钟"], ["1h", "1 小时"], ["6h", "6 小时"], ["24h", "24 小时"]].map(([id, label]) =>
          <button key={id} className={range === id ? "active" : ""} onClick={() => setRange(id)}>{label}</button>)}</div></header>
      <div className="precision-chart-grid">
        <article><div><b><i className="blue" />CPU</b><span>当前 <strong>{percent(cpu)}</strong></span></div><Sparkline values={visibleHistory.map(item => item.cpu)} color="#246fe5" /></article>
        <article><div><b><i className="green" />内存</b><span>当前 <strong>{memoryUsed ? `${memoryUsed.toFixed(1)} GB` : percent(memory)}</strong>{memoryTotal ? ` / ${memoryTotal.toFixed(1)} GB` : ""}</span></div><Sparkline values={visibleHistory.map(item => item.memory)} color="#12a36d" /></article>
        <article><div><b><i className="violet" />线程</b><span>当前 <strong>{threadCount || "—"}</strong></span></div><Sparkline values={visibleHistory.map(item => item.threads)} color="#7756db" /></article>
      </div>
    </section>
  </section>;
}

function BusinessMetrics({ data }) {
  const points = data?.metrics || [];
  const sum = (name, predicate = () => true) => points
    .filter(point => point.name === name && predicate(point.attributes || {}))
    .reduce((total, point) => total + numeric(point.value), 0);
  const histogram = name => points.find(point => point.name === name);
  const dds = sum("pdr.dds.messages.published") + sum("pdr.dds.messages.received");
  const deviceOk = sum("pdr.device.commands", labels => labels.result === "success");
  const deviceError = sum("pdr.device.commands", labels => labels.result === "error");
  const workflowOk = sum("pdr.workflow.executions", labels => labels.result === "success");
  const workflowFailed = sum("pdr.workflow.executions", labels => labels.result === "failed");
  const latency = histogram("pdr.dds.service.duration");
  return <section className="surface">
    <div className="section-head"><div><h2>OpenTelemetry 业务指标</h2>
      <p>来自 /api/v1/metrics 的 Counter 与 Histogram</p></div>
      <span className="inventory-count">{points.length} 条序列</span></div>
    <div className="metrics business-metrics-grid">
      <Metric icon={Network} label="DDS 消息" value={dds} caption="发布与接收总量" tone="blue" />
      <Metric icon={Zap} label="设备命令" value={deviceOk} caption={`${deviceError} 次失败`} tone="green" />
      <Metric icon={GitBranch} label="Workflow" value={workflowOk} caption={`${workflowFailed} 次失败`} tone="violet" />
      <Metric icon={Clock3} label="DDS 平均耗时"
        value={latency?.count ? `${(numeric(latency.sum) / numeric(latency.count, 1)).toFixed(2)} ms` : "—"}
        caption={latency?.count ? `${latency.count} 次采样` : "等待业务请求"} tone="orange" />
    </div>
  </section>;
}

function ProtocolSummary({ data, inventory, onLifecycle }) {
  const points = data?.metrics || [];
  const instances = inventory?.protocols || [];
  const protocols = [
    { id: "mqtt", label: "MQTT", detail: "Broker 发布订阅", tone: "blue" },
    { id: "rosbridge", label: "ROS Bridge", detail: "WebSocket Topic", tone: "violet" },
    { id: "udp", label: "UDP", detail: "数据报收发", tone: "green" }
  ];
  const sum = (name, protocol, predicate = () => true) => points
    .filter(point => point.name === name && point.attributes?.protocol === protocol &&
      predicate(point.attributes || {}))
    .reduce((total, point) => total + numeric(point.value), 0);
  return <section className="surface">
    <div className="section-head"><div><h2>现场协议运行诊断</h2>
      <p>来自 /api/v1/metrics 的操作、错误与字节统计</p></div>
      <span className="inventory-count">MQTT · ROS · UDP</span></div>
    <div className="metrics business-metrics-grid">{protocols.map(protocol => {
      const operations = sum("pdr.protocol.operations", protocol.id);
      const errors = sum("pdr.protocol.operations", protocol.id,
        labels => labels.result === "error");
      const bytes = sum("pdr.protocol.io", protocol.id);
      const managed = instances.filter(item => item.type === protocol.id);
      const open = managed.filter(item => item.open).length;
      return <Metric key={protocol.id} icon={Network} label={protocol.label}
        value={operations} caption={`${open}/${managed.length} 已打开 · ${errors} 次错误 · ${bytes.toLocaleString()} B`}
        tone={protocol.tone} />;
    })}</div>
    {!!instances.length && <div className="table-scroll"><table className="metrics-table"><thead><tr>
      <th>实例</th><th>类型</th><th>状态</th><th>发送/接收</th><th>超时</th><th>最近错误</th><th>操作</th></tr></thead>
      <tbody>{instances.map(item => <tr key={item.id}>
        <td><b>{item.id}</b><small>{item.name || item.service}{item.autoReconnect ? " · 自动恢复" : ""}</small></td>
        <td>{item.type}</td><td><Status state={item.open ? "ready" :
          item.desiredOpen && item.autoReconnect ? "recovering" : "down"} /></td>
        <td>{numeric(item.diagnostics?.sentMessages)} / {numeric(item.diagnostics?.receivedMessages)}</td>
        <td>{numeric(item.diagnostics?.timeouts)}</td>
        <td><FailureDetail failure={item.diagnostics?.failure}
          legacy={item.diagnostics?.lastError || item.error} /></td>
        <td><button className="icon-button" title="重新连接"
          onClick={() => onLifecycle(item, "restart")}><RotateCw size={16} /></button></td>
      </tr>)}</tbody></table></div>}
  </section>;
}

const metricDomains = [
  { id: "runtime", label: "Runtime", prefixes: ["pdr.runtime.", "process."] },
  { id: "dds", label: "DDS", prefixes: ["pdr.dds."] },
  { id: "device", label: "设备", prefixes: ["pdr.device."] },
  { id: "workflow", label: "工作流", prefixes: ["pdr.workflow."] },
  { id: "health", label: "健康诊断", prefixes: ["pdr.health.", "pdr.diagnostics."] },
  { id: "protocol", label: "协议汇总", prefixes: ["pdr.protocol."] },
  { id: "mqtt", label: "MQTT", prefixes: ["pdr.protocol."], protocol: "mqtt" },
  { id: "rosbridge", label: "ROS Bridge", prefixes: ["pdr.protocol."], protocol: "rosbridge" },
  { id: "udp", label: "UDP", prefixes: ["pdr.protocol."], protocol: "udp" },
  { id: "btle", label: "Bluetooth LE", prefixes: ["pdr.btle.", "pdr.protocol."], protocol: "btle" },
  { id: "webtunnel", label: "WebTunnel", prefixes: ["pdr.webtunnel.", "pdr.protocol."], protocol: "webtunnel" },
  { id: "http", label: "HTTP", prefixes: ["http.server."] },
  { id: "system", label: "系统", prefixes: ["system."] },
  { id: "export", label: "导出与缓存", prefixes: ["pdr.metrics."] }
];

function MetricValue({ point }) {
  if (point.kind === "histogram") {
    const average = numeric(point.count) ? numeric(point.sum) / numeric(point.count, 1) : 0;
    return <div className="metric-value-stack"><b>{numeric(point.value).toFixed(2)}</b>
      <small>最新 · 平均 {average.toFixed(2)} · {numeric(point.count)} 样本</small></div>;
  }
  return <b>{numeric(point.value).toLocaleString()}</b>;
}

function MetricsCenter({ data }) {
  const [domain, setDomain] = useState("runtime");
  const [filter, setFilter] = useState("");
  const selected = metricDomains.find(item => item.id === domain) || metricDomains[0];
  const all = data?.metrics || [];
  const points = all.filter(point => selected.prefixes.some(prefix => point.name.startsWith(prefix)))
    .filter(point => !selected.protocol || point.attributes?.protocol === selected.protocol ||
      point.name.startsWith(`pdr.${selected.protocol}.`))
    .filter(point => !filter || point.name.toLowerCase().includes(filter.toLowerCase()) ||
      JSON.stringify(point.attributes || {}).toLowerCase().includes(filter.toLowerCase()));
  const counters = points.filter(point => point.kind === "counter");
  const histograms = points.filter(point => point.kind === "histogram");
  return <section className="metrics-center">
    <div className="metrics-domain-tabs" role="tablist">{metricDomains.map(item =>
      <button key={item.id} role="tab" aria-selected={domain === item.id}
        className={domain === item.id ? "active" : ""} onClick={() => setDomain(item.id)}>{item.label}</button>)}</div>
    <div className="surface metrics-page">
      <div className="section-head"><div><h2>{selected.label} 指标</h2>
        <p>{data?.serviceName || "pdr-runtime"} · {data?.serviceInstanceId || "本机实例"}</p></div>
        <div className="metrics-page-tools"><span className="inventory-count">{points.length} 条序列</span>
          <label className="search"><Search size={16} /><input value={filter} placeholder="筛选指标或标签"
            onChange={event => setFilter(event.target.value)} /></label></div></div>
      <div className="metrics metrics-domain-summary">
        <Metric icon={Activity} label="Counter 序列" value={counters.length} caption="累计事件" tone="blue" />
        <Metric icon={Clock3} label="Histogram 序列" value={histograms.length} caption="采样与耗时分布" tone="orange" />
        <Metric icon={Database} label="样本总数" value={histograms.reduce((sum, point) => sum + numeric(point.count), 0)}
          caption="直方图累计采样" tone="violet" />
      </div>
      <div className="table-scroll"><table className="metrics-table"><thead><tr>
        <th>指标</th><th>类型</th><th>当前值</th><th>单位</th><th>标签</th></tr></thead>
        <tbody>{points.map((point, index) => <tr key={`${point.name}-${index}`}>
          <td><b>{point.name}</b><small>{point.description || "—"}</small></td>
          <td><span className={`metric-kind ${point.kind}`}>{point.kind}</span></td>
          <td><MetricValue point={point} /></td><td>{point.unit || "1"}</td>
          <td><div className="metric-labels">{Object.entries(point.attributes || {}).map(([key, value]) =>
            <span key={key}><i>{key}</i>={String(value)}</span>)}{!Object.keys(point.attributes || {}).length && "—"}</div></td>
        </tr>)}</tbody></table>{!points.length && <div className="empty"><Activity size={26} />
          <p>当前分类尚无指标样本</p></div>}</div>
    </div>
  </section>;
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

function ProcessSwimlanes({ nodes, selectedNode, onSelect }) {
  const layout = useMemo(() => {
    const ordered = [...nodes].sort((a, b) =>
      Number(a.startedUnixMicroseconds || 0) - Number(b.startedUnixMicroseconds || 0));
    const laneKeys = [];
    const laneByKey = new Map();
    ordered.forEach(node => {
      // A process can publish spans through multiple tracer service names.
      // Swimlanes represent actual processes, so PID is the stable lane key.
      const key = String(node.processId || node.serviceName || "unknown");
      if (!laneByKey.has(key)) {
        laneByKey.set(key, laneKeys.length);
        laneKeys.push({ key, pid: node.processId, service: node.serviceName || "未知进程" });
      }
    });
    const laneWidth = 350, rowHeight = 182, headerHeight = 92;
    const nodeWidth = 286, nodeHeight = 142;
    const positioned = ordered.map((node, index) => ({
      ...node, index, lane: laneByKey.get(String(node.processId || node.serviceName || "unknown")),
      x: laneByKey.get(String(node.processId || node.serviceName || "unknown")) * laneWidth + 32,
      y: headerHeight + index * rowHeight + 22
    }));
    const bySpan = new Map(positioned.map(node => [node.spanId, node]));
    return {
      lanes: laneKeys, nodes: positioned,
      edges: positioned.map(node => ({ from: bySpan.get(node.parentSpanId), to: node })).filter(edge => edge.from),
      laneWidth, nodeWidth, nodeHeight,
      width: Math.max(1050, laneKeys.length * laneWidth + 60),
      // Include the full final card plus a generous bottom reveal area so the
      // native horizontal scrollbar never covers the last business step.
      height: Math.max(460, headerHeight + positioned.length * rowHeight + 220)
    };
  }, [nodes]);
  const laneTitle = lane => {
    if (lane.service === "pdr-runtime") return "主进程";
    if (lane.service.includes("window-scene")) return "场景窗口";
    if (lane.service.includes("window-material")) return "材质窗口";
    if (lane.service.includes("window-device")) return "设备窗口";
    return lane.service.includes("qt3d") ? "Qt3D 编排进程" : lane.service;
  };
  return <div className="multi-flow-scroll"><div className="multi-flow"
    style={{ width: layout.width, height: layout.height }}>
    <div className="multi-flow-head">{layout.lanes.map((lane, index) =>
      <div key={lane.key} style={{ left: index * layout.laneWidth + 22, width: layout.laneWidth - 44 }}>
        <AppWindow size={21} /><span><b>{laneTitle(lane)}</b>
          <small>{lane.service} · PID {lane.pid || "—"}</small></span>
      </div>)}</div>
    {layout.lanes.map((lane, index) => <i className="multi-lifeline" key={lane.key}
      style={{ left: index * layout.laneWidth + layout.laneWidth / 2 }} />)}
    <svg className="multi-flow-edges" width={layout.width} height={layout.height}>
      {layout.edges.map(({ from, to }) => {
        const x1 = from.x + layout.nodeWidth / 2, y1 = from.y + layout.nodeHeight;
        const x2 = to.x + layout.nodeWidth / 2, y2 = to.y;
        const middle = (y1 + y2) / 2;
        return <path key={`${from.spanId}-${to.spanId}`}
          d={`M ${x1} ${y1} C ${x1} ${middle}, ${x2} ${middle}, ${x2} ${y2}`}
          className={to.status === "failed" ? "failed" : ""} />;
      })}
    </svg>
    {layout.nodes.map(node => <button key={node.spanId}
      className={`multi-flow-node ${node.status} ${selectedNode?.spanId === node.spanId ? "active" : ""}`}
      style={{ left: node.x, top: node.y, width: layout.nodeWidth }}
      onClick={() => onSelect(node)} title={node.operation}>
      <small>步骤 {String(node.index + 1).padStart(2, "0")}</small>
      <b>{node.operation}</b>
      <span>{(Number(node.durationNanoseconds || 0) / 1e6).toFixed(3)} ms</span>
      <em>{node.serviceName}</em>
    </button>)}
  </div></div>;
}

function BusinessExecutionList({ process }) {
  const [executions, setExecutions] = useState([]);
  const [available, setAvailable] = useState(true);
  const [collapsed, setCollapsed] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [detail, setDetail] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);
  const inspectorRef = useRef(null);

  useEffect(() => {
    if (!detail && !historyOpen) return undefined;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previous; };
  }, [detail, historyOpen]);

  useEffect(() => {
    if (inspectorRef.current) inspectorRef.current.scrollTop = 0;
  }, [selectedNode?.spanId]);

  useEffect(() => {
    if (!process) return undefined;
    let active = true;
    const load = async () => {
      try {
        const data = await request("/api/v1/heartbeat-businesses");
        if (active) {
          setExecutions((data.records || []).slice(0, 1000));
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
  const exportDiagnosis = () => {
    if (!detail) return;
    const byId = new Map(detail.nodes.map(node => [node.spanId, node]));
    const failed = detail.nodes.filter(node => node.status === "failed");
    const failedParents = new Set(failed.map(node => node.parentSpanId).filter(Boolean));
    const rootFailures = failed.filter(node => !failedParents.has(node.spanId));
    const primary = rootFailures[0] || failed[0] || null;
    const chain = [];
    for (let current = primary; current; current = byId.get(current.parentSpanId)) {
      chain.unshift({
        operation: current.operation, serviceName: current.serviceName,
        processId: current.processId, status: current.status,
        errorCode: current.errorCode || "", errorMessage: current.errorMessage || ""
      });
    }
    const errorCode = primary?.errorCode || detail.item.failedOperation || "UNKNOWN_FAILURE";
    const recommendations = [];
    if (/WINDOW_BRANCH|window/i.test(`${errorCode} ${primary?.operation || ""}`)) {
      recommendations.push("检查失败窗口进程是否仍在运行，以及窗口命令的 correlationId 是否收到对应响应。");
      recommendations.push("核对失败窗口的输入参数、局部资源初始化和渲染线程日志。");
      recommendations.push("确认 Qt3D 编排进程已执行补偿，并检查其他窗口结果是否可继续使用。");
    } else if (failed.length) {
      recommendations.push("从 primaryFailure 开始，沿 causalChain 向上核对输入输出与父子 Span。");
      recommendations.push("结合失败节点 logs、errorCode 和 processId 查询对应进程日志。");
    } else {
      recommendations.push("当前 Trace 未发现 failed 节点，建议检查超时、丢失响应或业务状态汇总逻辑。");
    }
    const report = {
      schemaVersion: "pdr-business-diagnosis/1.0",
      exportedAt: new Date().toISOString(),
      summary: {
        businessName: detail.item.businessName,
        businessInstanceId: detail.item.businessInstanceId,
        traceId: detail.item.traceId,
        status: detail.item.status,
        nodeCount: detail.nodes.length,
        failedNodeCount: failed.length
      },
      analysis: {
        conclusion: primary
          ? `首要失败点为“${primary.operation}”，错误码 ${errorCode}：${primary.errorMessage || "未提供更详细错误信息"}`
          : "未找到明确失败节点。",
        primaryFailure: primary,
        causalChain: chain,
        allFailures: failed,
        recommendations
      },
      processes: [...new Map(detail.nodes.map(node => [
        `${node.processId}:${node.serviceName}`,
        { processId: node.processId, serviceName: node.serviceName, hostName: node.hostName }
      ])).values()],
      nodes: detail.nodes
    };
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `business-diagnosis-${detail.item.traceId || Date.now()}.json`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  };

  return <section className="surface business-execution-card">
    <div className="section-head"><div><h2>业务流程执行列表</h2><p>当前进程的业务实例与执行进度</p></div>
      <div className="section-head-actions">
        <button className="business-history-query" onClick={() => setHistoryOpen(true)}
          title="进入业务历史查询页面"><Search size={20} />查询</button>
        <span className="inventory-count">{executions.length} 条</span>
        <button className={`section-collapse ${collapsed ? "collapsed" : ""}`}
          onClick={() => setCollapsed(value => !value)} aria-expanded={!collapsed}
          title={collapsed ? "展开业务流程执行列表" : "折叠业务流程执行列表"}>
          <ChevronDown size={24} />
        </button>
      </div></div>
    {!collapsed && <div className="business-execution-list">
      <div className="business-execution-columns"><span>业务流程 / 实例</span><span>状态</span>
        <span>步骤</span><span>开始时间</span><span>执行耗时</span></div>
      {executions.map((item, index) =>
      <article key={item.traceId || item.businessInstanceId || index}
        onDoubleClick={() => openDetail(item)} title="双击查看业务详细流程图">
        <div><b>{item.businessName || item.name || "未命名业务流程"}</b>
          <small>{item.businessInstanceId || item.traceId || "实例标识未知"}</small></div>
        <span className={`business-link ${item.status}`}>{linkText(item.status)}</span>
        <strong>{item.currentStep || item.stepName || `${item.stepCount || 0} 个步骤`}</strong>
        <strong>{formatTime(item.startedUnixMicroseconds || item.startedAt || item.startTime)}</strong>
        <strong>{formatDuration(item)}</strong>
      </article>)}
      {!executions.length && <div className="workbench-empty">
        {available ? "当前进程暂无业务流程执行记录" : "业务流程追踪服务暂未提供数据"}
      </div>}
    </div>}
    {detail && createPortal(<div className="business-modal-backdrop">
      <section className="business-modal">
        <nav className="flow-page-tabs">
          <button onClick={() => setDetail(null)}><Activity size={24} />运行总览</button>
          <ChevronRight size={25} />
          <button className="active"><Activity size={24} />流程-{detail.item.businessName}</button>
          <span><i />当前：业务流程页面</span>
          <button className="flow-page-close" onClick={() => setDetail(null)}><X size={27} />返回总览</button>
        </nav>
        <header><div><span className={`business-link ${detail.item.status}`}>
          {linkText(detail.item.status)}</span><h2>{detail.item.businessName}</h2>
          <p>业务实例：{detail.item.businessInstanceId} · 共 {detail.nodes.length} 个执行节点</p></div></header>
        <div className="business-flow">
          <main className="flow-canvas"><div className="flow-canvas-title"><div><h3>业务执行流程</h3>
            <p>点击任意节点查看该步骤的耗时、传入及传出参数</p></div>
            <div className="flow-canvas-actions"><button onClick={exportDiagnosis}
              title="导出完整链路和失败原因分析"><Download size={20} />导出诊断报告</button>
              <span>{detail.nodes.length} 个节点</span></div></div>
            <ProcessSwimlanes nodes={detail.nodes} selectedNode={selectedNode} onSelect={setSelectedNode} />
          </main>
          <aside className="flow-inspector" ref={inspectorRef}>{selectedNode ? <><div className="step-head">
            <div><span className={`business-link ${selectedNode.status}`}>
              {selectedNode.status === "success" ? "执行成功" : selectedNode.status === "failed" ? "执行失败" : selectedNode.status}</span>
              <small>当前选中节点</small></div><h3>{selectedNode.operation}</h3></div>
            {selectedNode.status === "failed" && <section className="flow-error-panel">
              <div><b>错误码</b><strong>{selectedNode.errorCode || "UNKNOWN_ERROR"}</strong></div>
              <div><b>失败原因</b><strong>{selectedNode.errorMessage || "未提供失败原因"}</strong></div>
              <div><b>失败节点</b><strong>{selectedNode.operation}</strong></div>
            </section>}
            <dl><div><dt>节点耗时</dt><dd>{(Number(selectedNode.durationNanoseconds || 0) / 1e6).toFixed(3)} ms</dd></div>
              <div><dt>服务 / Bundle</dt><dd>{selectedNode.serviceName} / {selectedNode.bundleName || "—"}</dd></div>
              <div><dt>主机 / PID</dt><dd>{selectedNode.hostName} / {selectedNode.processId}</dd></div></dl>
            <div className="flow-parameters"><section><h4>传入参数</h4>
              <pre>{JSON.stringify(selectedNode.inputs || {}, null, 2)}</pre></section>
              <section><h4>传出参数</h4>
                <pre>{JSON.stringify(selectedNode.outputs || {}, null, 2)}</pre></section></div>
          </> : <div className="workbench-empty">点击流程节点查看详情</div>}</aside>
        </div>
      </section>
    </div>, document.body)}
    {historyOpen && createPortal(<div className="business-history-page">
      <nav className="flow-page-tabs">
        <button onClick={() => setHistoryOpen(false)}><Activity size={24} />运行总览</button>
        <ChevronRight size={25} />
        <button className="active"><Search size={24} />业务历史查询</button>
        <span><i />当前：业务历史查询页面</span>
        <button className="flow-page-close" onClick={() => setHistoryOpen(false)}>
          <X size={27} />返回总览
        </button>
      </nav>
      <main><BusinessHistoryPanel /></main>
    </div>, document.body)}
  </section>;
}

function BusinessHistoryPanel() {
  const localDateTime = date => {
    const offset = date.getTimezoneOffset() * 60000;
    return new Date(date.getTime() - offset).toISOString().slice(0, 16);
  };
  const [collapsed, setCollapsed] = useState(false);
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
    } catch (requestError) {
      setRecords([]); setHasMore(false); setError(requestError.message);
    } finally { setLoading(false); }
  };
  const formatTime = value => value
    ? new Date(Number(value) / 1000).toLocaleString()
    : "—";
  const formatDuration = value => {
    const milliseconds = Number(value) / 1e6;
    if (!Number.isFinite(milliseconds)) return "—";
    return milliseconds < 1000 ? `${milliseconds.toFixed(3)} ms` : `${(milliseconds / 1000).toFixed(2)} s`;
  };

  return <section className="surface business-history-card">
    <div className="section-head"><div><h2>业务流程历史记录查询</h2><p>按小时 SQLite 分片，保留最近 10 天</p></div>
      <div className="section-head-actions"><span className="inventory-count">{records.length} 条</span>
        <button className={`section-collapse ${collapsed ? "collapsed" : ""}`}
          onClick={() => setCollapsed(value => !value)} aria-expanded={!collapsed}
          title={collapsed ? "展开历史记录查询" : "折叠历史记录查询"}>
          <ChevronDown size={24} />
        </button>
      </div></div>
    {!collapsed && <><form className="business-history-filters" onSubmit={event => {
      event.preventDefault(); load(0);
    }}>
      <label><span>开始时间</span><input type="datetime-local" value={from}
        onChange={event => setFrom(event.target.value)} /></label>
      <label><span>结束时间</span><input type="datetime-local" value={to}
        onChange={event => setTo(event.target.value)} /></label>
      <label><span>流程名称</span><input value={name}
        onChange={event => setName(event.target.value)} placeholder="支持模糊查询" /></label>
      <label><span>状态</span><select value={status} onChange={event => setStatus(event.target.value)}>
        <option value="">全部</option><option value="running">执行中</option>
        <option value="success">成功</option><option value="failed">失败</option>
        <option value="cancelled">已取消</option>
      </select></label>
      <button type="submit" disabled={loading}><Search size={20} />{loading ? "查询中" : "查询"}</button>
    </form>
    {error && <div className="business-history-error">{error}</div>}
    <div className="business-history-table">
      <div className="business-history-columns"><span>业务流程 / 实例</span><span>状态</span>
        <span>步骤</span><span>开始时间</span><span>执行耗时</span></div>
      {records.map(item => <div className="business-history-row" key={item.traceId}>
        <div><b>{item.businessName}</b><small>{item.businessInstanceId || item.traceId}</small></div>
        <Status state={item.status} /><strong>{item.stepCount} 个步骤</strong>
        <strong>{formatTime(item.startedUnixMicroseconds)}</strong>
        <strong>{formatDuration(item.durationNanoseconds)}</strong>
      </div>)}
      {!records.length && !loading && <div className="workbench-empty">请选择条件查询历史记录</div>}
    </div>
    <footer className="business-history-pagination">
      <span>每页 {limit} 条 · 第 {Math.floor(offset / limit) + 1} 页</span>
      <div><button type="button" disabled={loading || offset === 0}
        onClick={() => load(Math.max(0, offset - limit))}>上一页</button>
        <button type="button" disabled={loading || !hasMore}
          onClick={() => load(offset + limit)}>下一页</button></div>
    </footer></>}
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
  const [configurationControl, setConfigurationControl] = useState(null);
  const [managementAudit, setManagementAudit] = useState([]);
  const [managementTasks, setManagementTasks] = useState([]);
  const [managementTaskPersistence, setManagementTaskPersistence] = useState(null);
  const [managementIdempotency, setManagementIdempotency] = useState(null);
  const [managementTaskScheduler, setManagementTaskScheduler] = useState(null);
  const [identitySnapshot, setIdentitySnapshot] = useState(null);
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

  useEffect(() => {
    if (!selected || !(detail?.process?.main ?? selected.main)) {
      setConfigurationControl(null);
      setManagementAudit([]);
      setManagementTasks([]);
      setManagementTaskPersistence(null);
      setManagementIdempotency(null);
      setManagementTaskScheduler(null);
      setIdentitySnapshot(null);
      return;
    }
    let active = true;
    request("/api/v1/process-config")
      .then(async data => {
        if (!active) return;
        setConfigurationControl(data);
        if ((data.managementSession?.permissions || []).includes("audit.read")) {
          try {
            const audit = await request("/api/v1/management-audit?limit=20");
            if (active) setManagementAudit(audit.events || []);
          } catch { if (active) setManagementAudit([]); }
        } else setManagementAudit([]);
        if ((data.managementSession?.permissions || []).includes("task.read")) {
          try {
            const tasks = await request("/api/v1/management-tasks?limit=20");
            if (active) {
              setManagementTasks(tasks.tasks || []);
              setManagementTaskPersistence(tasks.persistence || null);
              setManagementIdempotency(tasks.idempotency || null);
              setManagementTaskScheduler(tasks.scheduler || null);
            }
          } catch { if (active) { setManagementTasks([]); setManagementTaskPersistence(null); setManagementIdempotency(null); setManagementTaskScheduler(null); } }
        } else { setManagementTasks([]); setManagementTaskPersistence(null); setManagementIdempotency(null); setManagementTaskScheduler(null); }
        if ((data.managementSession?.permissions || []).includes("identity.manage")) {
          try {
            const identity = await request("/api/v1/identity");
            if (active) setIdentitySnapshot(identity);
          } catch { if (active) setIdentitySnapshot(null); }
        } else setIdentitySnapshot(null);
      })
      .catch(() => { if (active) setConfigurationControl(null); });
    return () => { active = false; };
  }, [selected?.id, detail?.process?.main, revision]);

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
  const managementPermissions = new Set(configurationControl?.managementSession?.permissions || []);
  const canManageBundles = managementPermissions.has("bundle.manage");
  const canManageConfiguration = managementPermissions.has("configuration.manage");
  const canCancelTasks = managementPermissions.has("task.cancel");
  const canManageIdentity = managementPermissions.has("identity.manage");
  const operateBundle = async (bundle, action) => {
    const resetQuarantine = action === "reset-quarantine";
    const verb = action === "start" ? "启动" : action === "stop" ? "停止" :
      resetQuarantine ? "解除隔离" : "重启";
    let confirmPersistenceRecovery = false;
    if (resetQuarantine && bundle.quarantineRecoveryRequired) {
      confirmPersistenceRecovery = window.confirm(
        `隔离持久化数据不可用。确认重建隔离快照并解除 ${bundle.name} 的隔离？` +
        "\n\n损坏快照中无法读取的其他隔离记录可能会丢失。"
      );
      if (!confirmPersistenceRecovery) return;
    } else if (action !== "start" && !window.confirm(`确认${verb} ${bundle.name}？`)) return;
    setBusy(`bundle:${bundle.id}`);
    try {
      const result = await request("/api/v1/bundle-lifecycle", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: bundle.id, action, ...(confirmPersistenceRecovery ? { confirmPersistenceRecovery: true } : {}) })
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
    const validationError = validateConfigValue(key, drafts[key] ?? "");
    if (validationError) {
      onNotify?.(`${key}：${validationError}`, true);
      return;
    }
    setBusy(`config:${key}`);
    try {
      const result = await request("/api/v1/process-config", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key, value: String(drafts[key] ?? "") })
      });
      const outcome = result.ownerRestarted ? "已校验、持久化并重启所属 Bundle" :
        "已校验、持久化并应用";
      onNotify?.(`${result.message || "配置已立即生效"}（${outcome}）`);
      setRevision(value => value + 1);
    } catch (error) { onNotify?.(error.message, true); }
    finally { setBusy(""); }
  };
  const rollbackConfiguration = async () => {
    const rollback = configurationControl?.rollback;
    if (!rollback || !window.confirm(`确认回退最近一次配置事务 ${rollback.key}？`)) return;
    setBusy("config:rollback");
    try {
      const result = await request("/api/v1/process-config", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "rollback", transactionId: rollback.transactionId })
      });
      onNotify?.(`${result.message}（事务 ${result.transactionId}，审计已记录）`);
      setRevision(value => value + 1);
    } catch (error) { onNotify?.(error.message, true); }
    finally { setBusy(""); }
  };
  const cancelManagementTask = async task => {
    if (!window.confirm(`确认${task.state === "running" ? "请求停止运行中" : "取消排队"}任务 ${task.id}？`)) return;
    setBusy(`task:${task.id}`);
    try {
      const result = await request("/api/v1/management-tasks", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: task.id, action: "cancel" })
      });
      onNotify?.(result.message || "任务已取消");
      setRevision(value => value + 1);
    } catch (error) { onNotify?.(error.message, true); }
    finally { setBusy(""); }
  };
  const reloadIdentity = async () => {
    if (!window.confirm("确认已经用原子替换方式更新所有 tokenFile？成功后当前旧令牌将立即失效。")) return;
    setBusy("identity:reload");
    try {
      const result = await request("/api/v1/identity", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: "{}"
      });
      setIdentitySnapshot(result);
      sessionStorage.removeItem("pdr.webui.token");
      onNotify?.(`身份快照已从第 ${result.generationBefore} 代切换到第 ${result.generation} 代；下次管理请求请输入新令牌。`);
    } catch (error) { onNotify?.(error.message, true); }
    finally { setBusy(""); }
  };
  const isChildOnline = child => child.online ??
    ((child.location || "local") === "local" &&
      String(child.state).toLowerCase() === "running");

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
              <span><small>在线状态</small><strong className={isChildOnline(child) ? "online" : "offline"}>
                <i />{isChildOnline(child) ? "在线" : "离线"}</strong></span>
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
            <button disabled={busy || !canManageBundles || bundle.quarantined || String(bundle.state).toLowerCase() === "active"}
              onClick={() => operateBundle(bundle, "start")}><Play size={23} />启动</button>
            <button disabled={busy || !canManageBundles || String(bundle.state).toLowerCase() !== "active"}
              onClick={() => operateBundle(bundle, "stop")}><Square size={22} />停止</button>
            <button disabled={busy || !canManageBundles || bundle.quarantined || String(bundle.state).toLowerCase() !== "active"}
              onClick={() => operateBundle(bundle, "restart")}><RotateCw size={22} />重启</button>
            {bundle.quarantined && <button disabled={busy || !canManageBundles}
              title={bundle.quarantineLastError || "清除失败预算并允许再次启动"}
              onClick={() => operateBundle(bundle, "reset-quarantine")}><Undo2 size={22} />解除隔离</button>}
          </> : <span className="protected-bundle">核心组件 · 只读</span>}</div>
          {bundle.plugin && <small className={bundle.quarantined ? "plugin-incompatible" : "plugin-ready"}>
            {bundle.quarantined ? "已隔离" : "故障预算正常"} · 连续失败 {bundle.quarantineConsecutiveFailures || 0}/
            {bundle.quarantineFailureThreshold || 0} · 累计 {bundle.quarantineTotalFailures || 0}
            {!bundle.quarantinePersistenceHealthy && " · 持久化异常"}
          </small>}
        </div>)}{!bundles.length && <div className="workbench-empty">当前进程没有 Bundle 数据</div>}</div>}
        </section>
        <section className="surface process-config-card">
        <div className="section-head"><div><h2>当前进程配置信息</h2><p>敏感字段已自动隐藏</p></div>
          <div className="section-head-actions">
            {configurationControl && <span title={(configurationControl.managementSession?.permissions || []).join(", ")}
              className={`management-auth ${!configurationControl.managementAuthenticationRequired || configurationControl.managementSession?.authenticated ? "enabled" : "disabled"}`}>
              <ShieldCheck size={21} />{configurationControl.managementAuthenticationRequired ?
                (configurationControl.managementSession?.authenticated ?
                  `管理身份：${configurationControl.managementSession.principal}` : "管理身份未认证") :
                "开发模式未认证"}
            </span>}
            {configurationControl?.rollback && <button className="config-rollback"
              disabled={busy || !canManageConfiguration} onClick={rollbackConfiguration}
              title={`回退事务 ${configurationControl.rollback.transactionId}`}>
              <Undo2 size={22} />回退 {configurationControl.rollback.key}
            </button>}
            <span className="inventory-count">{configEntries.length} 项</span>
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
              className={validateConfigValue(key, drafts[key] ?? value) ? "invalid" : ""}
              onChange={event => setDrafts(current => ({ ...current, [key]: event.target.value }))} />
            {validateConfigValue(key, drafts[key] ?? value) &&
              <small className="config-validation">{validateConfigValue(key, drafts[key] ?? value)}</small>}
            <button disabled={busy || !canManageConfiguration || String(drafts[key] ?? value) === String(value) ||
                Boolean(validateConfigValue(key, drafts[key] ?? value))}
              onClick={() => applyConfiguration(key)}><Zap size={21} />立即生效</button>
          </div> : <span className="readonly-config">只读</span>}
        </div>)}{!configEntries.length && <div className="workbench-empty">当前进程没有可读取的配置</div>}</div>}
        {!collapsedSections.configuration && configurationControl?.transactions?.length > 0 &&
          <div className="config-transactions"><h3>最近配置事务</h3>
            {configurationControl.transactions.slice(0, 5).map(item => <div key={item.transactionId}>
              <code>{item.transactionId}</code><b>{item.key || "请求未解析"}</b>
              <span>{item.action} · {item.status}</span>
            </div>)}</div>}
        {!collapsedSections.configuration && identitySnapshot &&
          <div className="identity-snapshot"><div><ShieldCheck size={25} />
            <span><b>管理身份快照</b><small>第 {identitySnapshot.generation} 代 · {identitySnapshot.principalCount} 个身份 ·
              {identitySnapshot.required ? " 强制认证" : " 开发模式"} · 文件 {identitySnapshot.fileBackedPrincipalCount || 0} / 环境 {identitySnapshot.environmentBackedPrincipalCount || 0}
              {identitySnapshot.insecureFileCount > 0 ? ` · ${identitySnapshot.insecureFileCount} 个文件 ACL 过宽` :
                !identitySnapshot.filePermissionChecksComplete ? " · 文件权限未能完整核验" : " · 文件权限已核验"}</small></span></div>
            <button disabled={busy || !canManageIdentity} onClick={reloadIdentity}>
              <RefreshCw size={20} />{busy === "identity:reload" ? "正在重载" : "重载文件令牌"}
            </button></div>}
        {!collapsedSections.configuration && managementAudit.length > 0 &&
          <div className="config-transactions"><h3>最近管理操作审计</h3>
            {managementAudit.slice(0, 10).map(item => <div key={item.eventId}>
              <code>{item.principal || "未认证"}</code><b>{item.operation} · {item.target || "—"}</b>
              <span>{item.action || "—"} · {item.status} · HTTP {item.httpStatus} · {item.durationMicroseconds} μs</span>
            </div>)}</div>}
        {!collapsedSections.configuration && (managementTasks.length > 0 || managementTaskScheduler) &&
          <div className="config-transactions"><h3>异步管理任务
            {managementTaskPersistence && <small> · 任务快照 v{managementTaskPersistence.schemaVersion || 1}/{managementTaskPersistence.integrityAlgorithm || "无校验"} {managementTaskPersistence.healthy ? "正常" : managementTaskPersistence.recoveryRequired ? "异常，需运维恢复" : "异常"}{managementTaskPersistence.previousAvailable ? " · 上一版可用" : ""}</small>}
            {managementIdempotency && <small> · 幂等账本 v{managementIdempotency.schemaVersion || 1}/{managementIdempotency.integrityAlgorithm || "无校验"} {managementIdempotency.healthy ? "正常" : managementIdempotency.recoveryRequired ? "异常，需运维恢复" : "异常"}{managementIdempotency.previousAvailable ? " · 上一版可用" : ""}（{managementIdempotency.completed} 完成 / {managementIdempotency.interrupted} 待核对）</small>}
            {managementTaskScheduler && <small> · {managementTaskScheduler.running}/{managementTaskScheduler.workerCount} worker · 排队 {managementTaskScheduler.queued} · 等锁 {managementTaskScheduler.waitingResource}{managementTaskScheduler.degraded ? " · 调度降级" : ""}</small>}
          </h3>
            {(managementTaskPersistence?.recoveryRequired || managementIdempotency?.recoveryRequired) &&
              <p className="persistence-recovery-guidance"><AlertTriangle /> 当前持久化文件需要人工恢复：
                停止 Runtime，使用 <code>pdr persistence inspect</code> 校验当前文件和上一版，
                核对真实目标状态后再执行带哈希保护的 <code>pdr persistence recover</code>。
                Web 不会自动回退幂等账本。</p>}
            {managementTasks.slice(0, 10).map(item => <div key={item.id}>
              <code>{item.state}</code><b>{item.operation} · {item.target}</b>
               <span>{item.action} · {item.principal} · {item.phase || "—"}{item.phase === "waiting-resource" ?
                 ` · 等待 ${item.resourceKey}${item.blockingTaskId ? `（占用任务 ${item.blockingTaskId}）` : ""}` : ""}{item.state === "interrupted" ?
                 " · 需核对目标真实状态后重新提交" : item.phase === "cancellation-requested" ?
                 " · 等待底层操作到达协作取消点" : ""}</span>
               {["queued", "running"].includes(item.state) && canCancelTasks && <button disabled={busy}
                 onClick={() => cancelManagementTask(item)}>{item.state === "running" ? "请求停止" : "取消"}</button>}
            </div>)}</div>}
        </section>
      </div>
    </div>
    <BusinessExecutionList process={detail?.process || selected} />
  </div>;
}

function EntityActions({ item, onLife }) {
  if (item.kind !== "bundle" || !item.manageable) return <span className="readonly-config">只读</span>;
  const canStart = item.kind === "bundle" && item.state !== "active";
  return <div className="entity-actions">
    <button className="icon-button" disabled={item.quarantined} title={item.quarantined ? "插件已隔离" : canStart ? "启动" : "重启"}
      onClick={() => onLife(item, canStart ? "start" : "restart")}>
      {canStart ? <Play size={16} /> : <RotateCw size={16} />}
    </button>
    {item.quarantined && <button className="icon-button" title="解除隔离"
      onClick={() => onLife(item, "reset-quarantine")}><Undo2 size={16} /></button>}
  </div>;
}

function EntityTable({ items, onLife, searchable = true }) {
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
          <td className="secondary-text">{item.owner || item.version || item.type || "—"}
            {item.plugin && <small className={item.compatible ? "plugin-ready" : "plugin-incompatible"}>
              {item.governanceStatus} · {(item.dependencies || []).length} 个依赖
            </small>}
            {item.plugin && <small title={(item.compatibilityIssues || []).join("；")}>
              API {item.pluginApiVersion || "缺失"} · ABI {item.pluginAbiVersion || "缺失"}
              {(item.compatibilityIssues || []).length > 0 &&
                ` · ${(item.compatibilityIssues || []).join("；")}`}
            </small>}</td>
          <td><EntityActions item={item} onLife={onLife} /></td>
        </tr>)}</tbody>
      </table>
      {!filtered.length && <div className="empty"><Boxes size={26} /><p>没有匹配的项目</p></div>}
    </div>
  </section>;
}

function DeviceInventory({ inventory }) {
  const [filter, setFilter] = useState("");
  const devices = (inventory?.devices || []).filter(device =>
    !filter || `${device.id} ${device.type} ${device.bundle}`.toLowerCase().includes(filter.toLowerCase()));
  return <section className="surface">
    <div className="section-head"><div><h2>设备适配器</h2>
      <p>来自 /api/v1/devices 的实时状态与适配器诊断</p></div>
      <span className="inventory-count">{inventory?.count || 0} 个</span></div>
    <div className="table-tools"><span>设备 ID 在整个 Runtime 内全局唯一</span>
      <label className="search"><Search size={16} /><input value={filter} placeholder="筛选 ID、类型或 Bundle"
        onChange={event => setFilter(event.target.value)} /></label></div>
    <div className="table-scroll"><table className="entity-table device-table"><thead><tr>
      <th>设备</th><th>状态</th><th>类型</th><th>诊断</th><th>提供方</th></tr></thead>
      <tbody>{devices.map(device => <tr key={device.id}>
        <td><div className="entity-name"><span className="entity-glyph device"><Cpu size={17} /></span>
          <div><b>{device.id}</b><small>{device.service} · {device.required === false ? "可选" : "必需"}</small></div></div></td>
        <td><Status state={device.state} /></td><td><code>{device.type}</code></td>
        <td>{device.diagnostics ? <div className="device-diagnostics">
          <b>{numeric(device.diagnostics.successfulOperations)} 成功 / {numeric(device.diagnostics.failedOperations)} 失败</b>
          <small>重连 {numeric(device.diagnostics.reconnectAttempts)} · 连续失败 {numeric(device.diagnostics.consecutiveFailures)}</small>
          <FailureDetail failure={device.diagnostics.failure} legacy={device.diagnostics.lastError} />
        </div> : <span className="secondary-text">未提供</span>}</td>
        <td className="secondary-text">{device.bundle || "—"}</td>
      </tr>)}</tbody></table>
      {!devices.length && <div className="empty"><Cpu size={26} /><p>没有匹配的活跃设备</p></div>}</div>
  </section>;
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
  const [health, setHealth] = useState(null);
  const [processDetail, setProcessDetail] = useState(null);
  const [childProcessDetail, setChildProcessDetail] = useState(null);
  const [businessMetrics, setBusinessMetrics] = useState({ metrics: [] });
  const [deviceInventory, setDeviceInventory] = useState({ count: 0, devices: [] });
  const [protocolInventory, setProtocolInventory] = useState({ count: 0, protocols: [] });
  const [diagnosticEvents, setDiagnosticEvents] = useState([]);
  const [alertInventory, setAlertInventory] = useState({ count: 0, policy: {}, alerts: [] });
  const [alertHistory, setAlertHistory] = useState({ count: 0, records: [] });
  const [alertSinks, setAlertSinks] = useState({ count: 0, sinks: [] });
  const [updated, setUpdated] = useState(null);
  const [toast, setToast] = useState(null);
  const refresh = useCallback(async () => {
    const [data, mainDetail, monitoring, healthDetail, metricData, devices, protocols, diagnostics, alerts, history, sinks] = await Promise.all([
      request("/api/v1/topology"),
      request("/api/v1/process-detail").catch(() => null),
      request("/api/v1/system-metrics").catch(() => ({ samples: [] })),
      request("/health/detail").catch(() => null),
      request("/api/v1/metrics").catch(() => ({ metrics: [] })),
      request("/api/v1/devices").catch(() => ({ count: 0, devices: [] })),
      request("/api/v1/protocols").catch(() => ({ count: 0, protocols: [] })),
      request("/api/v1/diagnostic-events").catch(() => ({ count: 0, events: [] })),
      request("/api/v1/alerts").catch(() => ({ count: 0, policy: {}, alerts: [] })),
      request("/api/v1/alert-history?limit=20").catch(() => ({ count: 0, records: [] })),
      request("/api/v1/alert-sinks").catch(() => ({ count: 0, sinks: [] }))
    ]);
    setDeviceInventory(devices);
    setProtocolInventory(protocols);
    setDiagnosticEvents(diagnostics.events || []);
    setAlertInventory(alerts);
    setAlertHistory(history);
    setAlertSinks(sinks);
    setBusinessMetrics(metricData);
    setProcessDetail(mainDetail);
    const managedChild = (mainDetail?.children || []).find(item =>
      String(item.name || item.id).toLowerCase().includes("qt3d")) || mainDetail?.children?.[0];
    if (managedChild) {
      const query = new URLSearchParams({ id: managedChild.pid ?? managedChild.id, name: managedChild.name });
      setChildProcessDetail(await request(`/api/v1/process-detail?${query}`).catch(() => null));
    } else setChildProcessDetail(null);
    if (healthDetail) setHealth(healthDetail);
    const samples = monitoring.samples || [];
    const monitoredResources = monitoring.current || {};
    if (mainDetail?.bundles) {
      const management = new Map(mainDetail.bundles.map(bundle => [bundle.id, bundle]));
      data.bundles = (data.bundles || []).map(bundle => ({
        ...bundle, ...(management.get(bundle.id) || {})
      }));
    }
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
    if (action === "restart" && !window.confirm(`确认重启 ${item.name}？`)) return;
    try {
      const data = await request("/api/v1/bundle-lifecycle", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: item.id, action }) });
      notify(data.message || "操作已完成"); setTimeout(refresh, 400);
    } catch (error) { notify(error.message, true); }
  };
  const protocolLife = async (item, action) => {
    if (!window.confirm(`确认重新连接协议实例 ${item.id}？`)) return;
    try {
      const data = await request("/api/v1/protocols", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: item.id, action }) });
      notify(data.message || "协议操作已完成");
      await refresh();
    } catch (error) { notify(error.message, true); await refresh(); }
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
    page === "modules" ? topology.modules : page === "plugins" ?
      topology.bundles.filter(item => item.plugin || String(item.id).startsWith("pdr.plugin.")) : topology.bundles;

  return <div className="app-shell precision-shell">
    <header className="command-bar">
      <button className="mobile-menu" onClick={() => setMenuOpen(!menuOpen)}><Menu size={20} /></button>
      <div className="command-brand"><span><Box size={23} /></span><b>PocoDDS Runtime</b></div>
      <i className="command-divider" />
      <strong className="command-title">{pageMeta[page][0]}</strong>
      <div className="command-actions"><span className="last-update">最后刷新：{updated ? updated.toLocaleString() : "连接中"}</span>
        <button className="command-refresh" aria-label="刷新" onClick={() => refresh().catch(error => notify(error.message, true))}><RefreshCw size={18} /></button>
        <span className={`command-online ${health?.ready === false ? "degraded" : ""}`}><i />{health?.ready === false ? "异常" : "已连接"}</span></div>
    </header>
    <aside className={menuOpen ? "open" : ""}>
      <nav>{navItems.map(([id, Icon]) => <button key={id} className={page === id ? "active" : ""}
        onClick={() => { setPage(id); setMenuOpen(false); }}><Icon size={18} /><span>{pageMeta[id][0]}</span><ChevronRight size={15} /></button>)}</nav>
      <div className={`runtime-state ${health?.ready === false ? "degraded" : ""}`}><i /><div>
        <b>{health?.ready === false ? "Runtime 异常" : "Runtime 在线"}</b>
        <small>{topology.host || "本地主机"}</small></div></div>
    </aside>
    <main>
      <div className="content">
        {page === "overview" && <RuntimeTopologyOverview health={health} topology={topology}
          processDetail={processDetail} childProcessDetail={childProcessDetail} history={resourceHistory} alertInventory={alertInventory}
          onOpenProcesses={() => setPage("processes")} onOpenLogs={() => setPage("logs")} />}
        {page === "processes" && <ProcessWorkbench mainProcess={topology.mainProcess} onNotify={notify} />}
        {page === "devices" && <DeviceInventory inventory={deviceInventory} />}
        {["services", "modules", "bundles", "plugins"].includes(page) &&
          <EntityTable items={currentItems} onLife={life} />}
        {page === "metrics" && <MetricsCenter data={businessMetrics} />}
        {page === "logs" && <Logs />}
      </div>
    </main>
    {menuOpen && <button className="mobile-overlay" onClick={() => setMenuOpen(false)} />}
    {toast && <div className={`toast ${toast.error ? "error" : ""}`}>{toast.error ? <X size={17} /> : <Zap size={17} />}{toast.message}</div>}
  </div>;
}

createRoot(document.getElementById("root")).render(<App />);
