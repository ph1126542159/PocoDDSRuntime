import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity, AppWindow, ArrowLeft, Box, Boxes, ChevronDown, ChevronRight, Clock3,
  Cpu, FileText, HardDrive, Layers3, MemoryStick, Menu, Network, Play, RefreshCw, RotateCw, Search, Server,
  SlidersHorizontal, Square, Terminal, X, Zap, ShieldCheck, Undo2,
  AlertTriangle, CheckCircle2, Database, GitBranch
} from "lucide-react";
import "./styles.css";
import "./embedded.css";
import "./flow-layout.css";
import "./bright-theme.css";
import "./business-summary.css";
import "./typography.css";

const pageMeta = {
  overview: ["运行态势", "实时掌握运行时状态与资源"],
  processes: ["进程管理", "当前运行时挂载的进程"],
  devices: ["设备与协议", "当前 Runtime 的设备、协议实例及提供方归属"],
  plugins: ["插件治理", "外部插件兼容性、依赖与生命周期"],
  metrics: ["指标中心", "按运行域查看 OpenTelemetry Counter 与 Histogram"],
  governance: ["Runtime 治理", "身份、权限、配置事务、审计与管理任务"],
  terminal: ["终端调试", "使用受控命令诊断 Bundle、Service 与子进程"],
  tracing: ["业务追踪", "机器人仿真与 OpenTelemetry 业务流程"]
};

const navItems = [
  ["overview", Activity], ["processes", AppWindow], ["devices", Cpu],
  ["plugins", Boxes], ["metrics", Activity], ["governance", ShieldCheck],
  ["terminal", Terminal],
  ["tracing", GitBranch, "/tracing/"]
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
  const running = ["active", "running", "started", "ready", "registered"].includes(normalized);
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
  const hostResources = topology.hostResources || {};
  const processResources = processDetail?.resources || {};
  const unresolvedAlerts = (alertInventory?.alerts || []).filter(item => item.status !== "resolved").length;
  const healthy = health?.status === "UP" && health?.live && health?.ready;
  const cpu = numeric(hostResources.cpuPercent ?? hostResources.cpu);
  const memory = numeric(hostResources.memoryPercent ?? hostResources.memory);
  const memoryUsed = numeric(hostResources.memoryUsedMb) / 1024;
  const memoryTotal = numeric(hostResources.memoryTotalMb) / 1024;
  const disk = numeric(hostResources.diskPercent ?? hostResources.disk);
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
      <article className={healthy ? "healthy" : "attention"}><span><ShieldCheck /></span><div><b>{healthy ? "当前 Runtime 就绪" : "当前 Runtime 需要关注"}</b><small>{healthy ? "本实例聚合健康正常" : "请检查本实例异常对象"}</small></div></article>
      <article><span><Server /></span><div><small>当前主机</small><b>{topology.host || "本地主机"}</b><em>{health?.ready ? "Runtime 就绪" : "等待就绪"}</em></div></article>
      <article><span><Clock3 /></span><div><small>运行时长</small><b>{mainRunning ? "持续运行" : "未运行"}</b><em>主进程 PID {mainProcess?.pid || mainProcess?.id || "—"}</em></div></article>
      <article><span><Boxes /></span><div><small>Bundles</small><b>{bundles}/{bundles || "—"}</b><em>已就绪 / 总数</em></div></article>
      <article><span><AppWindow /></span><div><small>进程总数</small><b>{processCount}</b><em>主进程 1 · 子进程 {Math.max(0, processCount - 1)}</em></div></article>
    </div>

    <div className="precision-workspace">
      <section className="precision-topology">
        <header><div><h2>运行拓扑</h2><p>Runtime 与 Qt3D 进程链路</p></div><span><i />{workers.length} 个工作进程在线</span></header>
        <div className="precision-process-head"><span>进程 / 节点</span><span>PID</span><span>状态</span><span>CPU</span><span>内存</span><span>线程</span></div>
        <div className="precision-process-tree">
          {row(mainProcess, "Runtime 主进程", 0, Box, mainRunning, processResources)}
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
        <article className="attention-summary"><span><CheckCircle2 /></span><div><b>{unresolvedAlerts ? "存在待处理事件" : "暂无阻断问题"}</b><p>{unresolvedAlerts ? "建议查看告警详情并确认影响范围" : "当前 Runtime 运行正常"}</p></div></article>
        {memory >= 80 && <article className="attention-item warning"><AlertTriangle /><div><b>主机内存使用率偏高</b><p>当前使用率 {percent(memory)}，不是 Runtime 进程 RSS</p><small>Host 作用域</small></div></article>}
        <article className="attention-item info"><Boxes /><div><b>Bundles 已就绪</b><p>{bundles} 个 Bundles 已成功加载</p><small>状态同步完成</small></div></article>
        <article className={`attention-item ${childRunning ? "success" : "warning"}`}>{childRunning ? <CheckCircle2 /> : <AlertTriangle />}<div>
          <b>{childRunning ? "Qt3D 链路正常" : "Qt3D 子进程未运行"}</b><p>{childRunning ? `${workers.length} 个渲染工作进程在线` : "打开进程工作台查看启动日志"}</p><small>{stateText(qt3d?.state)}</small></div></article>
        <button className="attention-more" onClick={onOpenLogs}>查看全部事件 <ChevronRight size={16} /></button>
      </aside>
    </div>

    <section className="precision-resources">
      <header><div><h2>主机资源趋势</h2><p>Host 作用域 · 最近 {range === "15m" ? "15 分钟" : range === "1h" ? "60 分钟" : range === "6h" ? "6 小时" : "24 小时"}</p></div>
        <div className="precision-range">{[["15m", "15 分钟"], ["1h", "1 小时"], ["6h", "6 小时"], ["24h", "24 小时"]].map(([id, label]) =>
          <button key={id} className={range === id ? "active" : ""} onClick={() => setRange(id)}>{label}</button>)}</div></header>
      <div className="precision-chart-grid">
        <article><div><b><i className="blue" />CPU</b><span>当前 <strong>{percent(cpu)}</strong></span></div><Sparkline values={visibleHistory.map(item => item.cpu)} color="#246fe5" /></article>
        <article><div><b><i className="green" />内存</b><span>当前 <strong>{memoryUsed ? `${memoryUsed.toFixed(1)} GB` : percent(memory)}</strong>{memoryTotal ? ` / ${memoryTotal.toFixed(1)} GB` : ""}</span></div><Sparkline values={visibleHistory.map(item => item.memory)} color="#12a36d" /></article>
        <article><div><b><i className="violet" />磁盘</b><span>当前 <strong>{percent(disk)}</strong></span></div><Sparkline values={visibleHistory.map(item => item.disk)} color="#7756db" /></article>
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
    <div className="section-head"><div><h2>协议实例</h2>
      <p>Runtime 作用域；操作由 Service 执行，生命周期归提供方 Bundle</p></div>
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
      <th>实例</th><th>类型</th><th>状态</th><th>归属</th><th>发送/接收</th><th>超时</th><th>最近错误</th><th>实例操作</th></tr></thead>
      <tbody>{instances.map(item => <tr key={item.id}>
        <td><b>{item.id}</b><small>{item.name || item.service}{item.autoReconnect ? " · 自动恢复" : ""}</small></td>
        <td>{item.type}</td><td><Status state={item.open ? "ready" :
          item.desiredOpen && item.autoReconnect ? "recovering" : "down"} /></td>
        <td><div className="owner-stack"><small>Service: {item.serviceId || item.service}</small><small>Bundle: {item.bundleId || item.bundle}</small></div></td>
        <td>{numeric(item.diagnostics?.sentMessages)} / {numeric(item.diagnostics?.receivedMessages)}</td>
        <td>{numeric(item.diagnostics?.timeouts)}</td>
        <td><FailureDetail failure={item.diagnostics?.failure}
          legacy={item.diagnostics?.lastError || item.error} /></td>
        <td><button className="icon-button" title="重新连接"
          onClick={() => onLifecycle(item, "restart")}><RotateCw size={16} /></button></td>
      </tr>)}</tbody></table></div>}
  </section>;
}

const metricViews = [
  { id: "overview", label: "运行概览", description: "先确认整体是否正常" },
  { id: "robot", label: "机器人与设备", description: "设备、工作流和诊断" },
  { id: "system", label: "系统资源", description: "CPU、内存、磁盘和进程" },
  { id: "service", label: "接口服务", description: "接口请求、耗时和协议" },
  { id: "all", label: "全部指标", description: "工程排障时使用" }
];

const metricNames = {
  "pdr.runtime.starts": ["运行时启动次数", "Runtime 本次及历史启动累计"],
  "pdr.runtime.subprocesses": ["子进程数量", "Runtime 已启动的业务子进程"],
  "process.thread.count": ["运行线程数", "当前 Runtime 进程线程数量"],
  "pdr.device.online": ["设备在线状态", "1 表示在线，0 表示离线"],
  "pdr.device.starts": ["设备启动次数", "设备适配器启动累计"],
  "pdr.device.commands": ["设备命令数", "发送到设备的命令累计"],
  "system.cpu.utilization": ["CPU 使用率", "主机 CPU 当前负载"],
  "system.memory.utilization": ["内存使用率", "主机内存当前占用比例"],
  "system.memory.usage": ["已用内存", "主机当前已使用内存"],
  "system.filesystem.utilization": ["磁盘使用率", "Runtime 所在磁盘占用比例"],
  "system.network.io": ["网络吞吐", "主机网络接收或发送速率"],
  "http.server.request.duration": ["接口响应耗时", "Web API 请求处理时间"],
  "http.server.request.count": ["接口请求数", "Web API 请求累计"],
  "http.server.response.count": ["接口响应数", "Web API 响应累计"],
  "pdr.management.tasks.queue.utilization": ["任务队列使用率", "管理任务队列容量占用"],
  "pdr.metrics.cardinality.dropped": ["被丢弃的指标序列", "超过标签基数上限后被保护性丢弃的数量"]
};

function metricAverage(point) {
  return point?.kind === "histogram" && numeric(point.count)
    ? numeric(point.sum) / numeric(point.count, 1) : numeric(point?.value);
}

function utilizationValue(point) {
  const value = numeric(point?.value);
  return point?.unit === "%" || value > 1 ? value : value * 100;
}

function metricDisplay(point, useAverage = false) {
  if (!point) return "暂无数据";
  const value = useAverage ? metricAverage(point) : numeric(point.value);
  if (point.name.endsWith(".utilization")) return `${utilizationValue({ ...point, value }).toFixed(1)}%`;
  if (point.unit === "%") return `${value.toFixed(1)}%`;
  if (point.unit === "ms") return `${value.toFixed(value < 10 ? 2 : 1)} ms`;
  if (point.unit === "MiBy") return value >= 1024 ? `${(value / 1024).toFixed(1)} GiB` : `${value.toFixed(0)} MiB`;
  if (point.unit === "KiBy/s") return `${value.toFixed(value < 100 ? 1 : 0)} KiB/s`;
  if (point.kind === "counter") return value.toLocaleString();
  return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(2);
}

function metricText(point) {
  if (metricNames[point.name]) return metricNames[point.name];
  const protocol = point.attributes?.protocol;
  if (point.name.startsWith("pdr.protocol.")) {
    return [`${protocol ? String(protocol).toUpperCase() + " " : ""}协议指标`, point.description || "接口协议运行数据"];
  }
  if (point.name.startsWith("pdr.workflow.")) return ["工作流指标", point.description || "机器人业务工作流运行数据"];
  if (point.name.startsWith("pdr.health.") || point.name.startsWith("pdr.diagnostics.")) {
    return ["健康诊断指标", point.description || "运行健康与故障诊断数据"];
  }
  return [point.description || point.name, "工程指标，展开标签可查看具体对象"];
}

function metricState(point) {
  if (point.name === "pdr.device.online") {
    return numeric(point.value) >= 1
      ? { tone: "ok", label: "在线", detail: "设备通信正常" }
      : { tone: "bad", label: "离线", detail: "检查设备或适配器" };
  }
  if (point.name.endsWith(".utilization")) {
    const value = utilizationValue(point);
    if (value >= 90) return { tone: "bad", label: "过高", detail: "已超过 90%" };
    if (value >= 75) return { tone: "warn", label: "注意", detail: "已超过 75%" };
    return { tone: "ok", label: "正常", detail: "低于 75%" };
  }
  if (point.name === "http.server.request.duration") {
    const average = metricAverage(point);
    if (average >= 500) return { tone: "bad", label: "缓慢", detail: "平均超过 500 ms" };
    if (average >= 100) return { tone: "warn", label: "注意", detail: "平均超过 100 ms" };
    return { tone: "ok", label: "正常", detail: "平均低于 100 ms" };
  }
  if (point.name === "pdr.metrics.cardinality.dropped" && numeric(point.value) > 0) {
    return { tone: "warn", label: "有丢弃", detail: "检查标签数量" };
  }
  return { tone: "neutral", label: "已采集", detail: point.kind === "counter" ? "累计值" : "最新采样" };
}

function MetricValue({ point }) {
  if (point.kind === "histogram") {
    return <div className="metric-value-stack"><b>{metricDisplay(point)}</b>
      <small>平均 {metricDisplay(point, true)} · {numeric(point.count)} 次采样</small></div>;
  }
  return <b>{metricDisplay(point)}</b>;
}

function MetricsCenter({ data }) {
  const [view, setView] = useState("overview");
  const [filter, setFilter] = useState("");
  const selected = metricViews.find(item => item.id === view) || metricViews[0];
  const all = (data?.metrics || []).filter(point => !point.name.startsWith("pdr.dds."));
  const belongsToView = point => {
    if (view === "overview") return [
      "system.cpu.utilization", "system.memory.utilization", "system.filesystem.utilization",
      "process.thread.count", "pdr.runtime.starts", "pdr.runtime.subprocesses",
      "pdr.device.online", "http.server.request.duration"
    ].includes(point.name);
    if (view === "robot") return ["pdr.device.", "pdr.workflow.", "pdr.health.", "pdr.diagnostics.", "pdr.robot."].some(prefix => point.name.startsWith(prefix));
    if (view === "system") return ["system.", "process.", "pdr.runtime.", "pdr.management."].some(prefix => point.name.startsWith(prefix));
    if (view === "service") return ["http.server.", "pdr.protocol.", "pdr.mqtt.", "pdr.rosbridge.", "pdr.udp.", "pdr.btle.", "pdr.webtunnel."].some(prefix => point.name.startsWith(prefix));
    return true;
  };
  const query = filter.trim().toLowerCase();
  const rawPoints = all.filter(belongsToView);
  const viewPoints = view === "overview" ? rawPoints.filter((point, index, collection) => {
    if (point.name === "pdr.device.online") return true;
    const sameName = collection.filter(candidate => candidate.name === point.name);
    if (point.name === "http.server.request.duration") {
      return point === sameName.reduce((slowest, candidate) =>
        metricAverage(candidate) > metricAverage(slowest) ? candidate : slowest, sameName[0]);
    }
    return index === collection.findIndex(candidate => candidate.name === point.name);
  }) : rawPoints;
  const points = viewPoints.filter(point => {
    const [title, help] = metricText(point);
    return !query || `${title} ${help} ${point.name} ${JSON.stringify(point.attributes || {})}`.toLowerCase().includes(query);
  });
  const cpu = all.find(point => point.name === "system.cpu.utilization");
  const memory = all.find(point => point.name === "system.memory.utilization");
  const disk = all.find(point => point.name === "system.filesystem.utilization");
  const devices = all.filter(point => point.name === "pdr.device.online");
  const onlineDevices = devices.filter(point => numeric(point.value) >= 1).length;
  const durations = all.filter(point => point.name === "http.server.request.duration" && numeric(point.count));
  const durationCount = durations.reduce((sum, point) => sum + numeric(point.count), 0);
  const durationAverage = durationCount ? durations.reduce((sum, point) => sum + numeric(point.sum), 0) / durationCount : 0;
  const resourceAttention = [cpu, memory, disk].some(point => point && utilizationValue(point) >= 75);
  const needsAttention = resourceAttention || devices.some(point => numeric(point.value) < 1) || durationAverage >= 100;
  const summaryCards = [
    { icon: needsAttention ? AlertTriangle : CheckCircle2, label: "系统状态", value: needsAttention ? "需要关注" : "运行正常", caption: "综合资源、设备与接口", tone: needsAttention ? "warn" : "ok" },
    { icon: Cpu, label: "CPU", value: metricDisplay(cpu), caption: cpu ? "超过 75% 提醒" : "等待系统采样", tone: cpu && utilizationValue(cpu) >= 75 ? "warn" : "blue" },
    { icon: MemoryStick, label: "内存", value: metricDisplay(memory), caption: memory ? "超过 75% 提醒" : "等待系统采样", tone: memory && utilizationValue(memory) >= 75 ? "warn" : "violet" },
    { icon: Server, label: "接口平均耗时", value: durationCount ? `${durationAverage.toFixed(durationAverage < 10 ? 2 : 1)} ms` : "暂无数据", caption: durationCount ? `${durationCount.toLocaleString()} 次请求采样` : "等待接口调用", tone: durationAverage >= 100 ? "warn" : "orange" },
    { icon: Network, label: "设备在线", value: devices.length ? `${onlineDevices} / ${devices.length}` : "暂无设备", caption: devices.length ? "在线 / 已发现" : "等待设备上报", tone: devices.some(point => numeric(point.value) < 1) ? "warn" : "green" }
  ];

  return <section className="metrics-center">
    <div className="metrics-intro">
      <div><span>怎么用</span><h2>先看状态，有异常再下钻</h2>
        <p>这里用于回答“系统现在是否正常、哪里需要处理”。黄色或红色表示需要关注；原始指标只在工程排障时查看。</p></div>
      <ol><li><b>1</b>看顶部状态</li><li><b>2</b>进入异常分类</li><li><b>3</b>按名称或设备搜索</li></ol>
    </div>
    <div className="metrics-status-grid">{summaryCards.map(card => {
      const Icon = card.icon;
      return <article key={card.label} className={`metrics-status-card ${card.tone}`}>
        <span><Icon size={21} /></span><div><small>{card.label}</small><strong>{card.value}</strong><em>{card.caption}</em></div>
      </article>;
    })}</div>
    <div className="metrics-domain-tabs" role="tablist" aria-label="指标分类">{metricViews.map(item =>
      <button key={item.id} role="tab" aria-selected={view === item.id}
        className={view === item.id ? "active" : ""} onClick={() => setView(item.id)}>
        <b>{item.label}</b><small>{item.description}</small></button>)}</div>
    <div className="surface metrics-page">
      <div className="section-head"><div><h2>{selected.label}</h2>
        <p>{selected.description} · {data?.serviceName || "pdr-runtime"} · {data?.serviceInstanceId || "本机实例"}</p></div>
        <div className="metrics-page-tools"><span className="inventory-count">{points.length} 条</span>
          <label className="search"><Search size={16} /><input value={filter} placeholder="搜索指标、设备或接口"
            onChange={event => setFilter(event.target.value)} /></label></div></div>
      <details className="metrics-help"><summary>这些数据怎么读？</summary>
        <div><p><b>当前值</b>用于快速判断现在的状态；有平均值时，可避免单次波动造成误判。</p>
          <p><b>累计次数（Counter）</b>只会增加，适合启动、请求和错误计数。</p>
          <p><b>采样数据（Histogram）</b>记录最新值、平均值和采样次数，适合资源占用与响应耗时。</p></div>
      </details>
      <div className="table-scroll"><table className="metrics-table operator-metrics-table"><thead><tr>
        <th>指标含义</th><th>当前值</th><th>状态</th><th>判断依据</th><th>对象 / 标签</th></tr></thead>
        <tbody>{points.map((point, index) => {
          const [title, help] = metricText(point);
          const state = metricState(point);
          return <tr key={`${point.name}-${index}`}>
            <td><b>{title}</b><small>{help}</small><code>{point.name}</code></td>
            <td><MetricValue point={point} /></td>
            <td><span className={`metric-state ${state.tone}`}><i />{state.label}</span></td>
            <td><span className="metric-rule">{state.detail}</span></td>
            <td><details className="metric-label-details"><summary>{Object.keys(point.attributes || {}).length ? "查看标签" : "无标签"}</summary>
              <div className="metric-labels">{Object.entries(point.attributes || {}).map(([key, value]) =>
                <span key={key}><i>{key}</i>={String(value)}</span>)}</div></details></td>
          </tr>;
        })}</tbody></table>{!points.length && <div className="empty"><Activity size={26} />
          <p>当前分类尚无数据，可换一个分类或清除搜索条件</p></div>}</div>
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

function BusinessExecutionList({ process }) {
  const [executions, setExecutions] = useState([]);
  const [available, setAvailable] = useState(true);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    if (!process) return undefined;
    let active = true;
    const load = async () => {
      try {
        const data = await request("/api/v1/heartbeat-businesses");
        if (active) {
          setExecutions((data.records || []).slice(0, 20));
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
  const linkText = status => status === "success" ? "链路走通" :
    status === "running" ? "执行中" : "链路失败";
  const openTracing = item => window.location.assign(
    `/tracing/?traceId=${encodeURIComponent(item.traceId)}`);

  return <section className="surface business-execution-card">
    <div className="section-head"><div><h2>内部链路摘要</h2>
      <p>只显示主子进程心跳与跨进程协同状态；完整流程、参数、日志和历史记录统一在业务追踪查看</p></div>
      <div className="section-head-actions">
        <span className="inventory-count">{executions.length} 条</span>
        <button className={`section-collapse ${collapsed ? "collapsed" : ""}`}
          onClick={() => setCollapsed(value => !value)} aria-expanded={!collapsed}
          title={collapsed ? "展开内部链路摘要" : "折叠内部链路摘要"}>
          <ChevronDown size={24} />
        </button>
      </div></div>
    {!collapsed && <div className="business-execution-list">
      <div className="business-execution-columns"><span>内部业务 / 实例</span><span>状态</span>
        <span>步骤</span><span>开始时间</span><span>执行耗时</span></div>
      {executions.map((item, index) =>
      <article key={item.traceId || item.businessInstanceId || index}
        title="在业务追踪中查看完整链路">
        <button className="business-trace-link" onClick={() => openTracing(item)}>
          <b>{item.businessName || item.name || "未命名业务流程"}</b>
          <small>{item.businessInstanceId || item.traceId || "实例标识未知"}</small>
          <em>查看完整追踪</em>
        </button>
        <span className={`business-link ${item.status}`}>{linkText(item.status)}</span>
        <strong>{item.currentStep || item.stepName || `${item.stepCount || 0} 个步骤`}</strong>
        <strong>{formatTime(item.startedUnixMicroseconds || item.startedAt || item.startTime)}</strong>
        <strong>{formatDuration(item)}</strong>
      </article>)}
      {!executions.length && <div className="workbench-empty">
        {available ? "当前暂无内部链路状态记录" : "内部链路监测服务暂未提供数据"}
      </div>}
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
        const query = new URLSearchParams({
          id: selected.id,
          name: selected.name,
          limit: "500",
          _ts: String(Date.now())
        });
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

function ProcessScopedLogs({ process }) {
  const [lines, setLines] = useState([]);
  const [connected, setConnected] = useState(false);
  const [filter, setFilter] = useState("");
  const logRef = useRef(null);
  const visibleLines = lines.filter(line => line.toLowerCase().includes(filter.trim().toLowerCase()));

  useEffect(() => {
    if (!process) return undefined;
    let active = true;
    const load = async () => {
      try {
        const query = new URLSearchParams({
          id: process.pid ?? process.id,
          name: process.name,
          limit: "500",
          _ts: String(Date.now())
        });
        const data = await request(`/api/v1/process-logs?${query}`);
        if (active) { setLines(data.lines || []); setConnected(true); }
      } catch {
        if (active) setConnected(false);
      }
    };
    setLines([]);
    load();
    const timer = setInterval(load, 1000);
    return () => { active = false; clearInterval(timer); };
  }, [process?.id, process?.name, process?.pid]);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [lines]);

  return <section className="process-log-panel process-scoped-log">
    <header><div className="terminal-title"><span><Terminal size={18} /></span><div>
      <h2>{process?.name || "当前进程"}</h2>
      <p>PID {process?.pid || process?.id || "—"} · 仅显示该进程日志</p>
    </div></div><div className={`live-indicator ${connected ? "online" : ""}`}><i />
      {connected ? "实时连接" : "等待日志"}</div></header>
    <label className="process-log-toolbar"><Search size={16} /><input value={filter}
      onChange={event => setFilter(event.target.value)} placeholder="在当前进程日志中搜索" /></label>
    <div className="terminal" ref={logRef}>{visibleLines.length
      ? visibleLines.map((line, index) => <div className="terminal-line" key={`${index}-${line.slice(0, 20)}`}>
        <span>{String(index + 1).padStart(3, "0")}</span><code>{line}</code></div>)
      : <div className="terminal-empty"><Terminal size={28} /><p>{filter ? "没有匹配的日志" : "当前进程暂无日志输出"}</p></div>}</div>
    <footer><span>每秒自动刷新</span><span>显示 {visibleLines.length} / {lines.length} 行</span></footer>
  </section>;
}

function ProcessWorkbench({ mainProcess, activeSection, onSectionChange, onNotify, governanceOnly = false }) {
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
        if (governanceOnly && (data.managementSession?.permissions || []).includes("audit.read")) {
          try {
            const audit = await request("/api/v1/management-audit?limit=20");
            if (active) setManagementAudit(audit.events || []);
          } catch { if (active) setManagementAudit([]); }
        } else setManagementAudit([]);
        if (governanceOnly && (data.managementSession?.permissions || []).includes("task.read")) {
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
        if (governanceOnly && (data.managementSession?.permissions || []).includes("identity.manage")) {
          try {
            const identity = await request("/api/v1/identity");
            if (active) setIdentitySnapshot(identity);
          } catch { if (active) setIdentitySnapshot(null); }
        } else setIdentitySnapshot(null);
      })
      .catch(() => { if (active) setConfigurationControl(null); });
    return () => { active = false; };
  }, [selected?.id, detail?.process?.main, revision, governanceOnly]);

  const selectProcess = process => {
    setDetail(null);
    setHistory([]);
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
  const selectedProcess = detail?.process || selected;
  const isMainProcess = Boolean(detail?.process?.main ?? selected?.main ?? selected?.role === "main");
  const processServices = detail?.services || [];
  const processSections = [
    ["overview", Activity, "概览"],
    ["services", Server, "服务", processServices.length],
    ["bundles", Boxes, "Bundles", bundles.length],
    ["logs", FileText, "日志"],
    ["configuration", SlidersHorizontal, "进程配置"],
    ["business", GitBranch, "链路摘要"]
  ];
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
    {!governanceOnly && <><div className="process-guide">
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
        <p>{isMainProcess ? "当前主进程" : "当前子进程"}</p>
        <h2>{detail?.process?.name || selected?.name || "加载中"}</h2>
        <small>PID {detail?.process?.pid || selected?.pid || selected?.id || "—"}</small>
      </div></div><Status state={detail?.process?.state || selected?.state || "unknown"} />
    </section>

    <nav className="process-section-tabs" aria-label="当前进程功能">
      {processSections.map(([id, Icon, label, count]) => <button key={id}
        className={activeSection === id ? "active" : ""}
        onClick={() => onSectionChange(id)} aria-current={activeSection === id ? "page" : undefined}>
        <Icon size={17} /><span>{label}</span>{count !== undefined && <small>{count}</small>}
      </button>)}
    </nav></>}

    {!governanceOnly && activeSection === "overview" && <>
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
    </>}

    {activeSection === "bundles" &&
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
      </div>
    </div>}
    {!governanceOnly && activeSection === "services" && <section className="process-entity-section">
      <div className="section-head"><div><h2>当前进程注册的服务</h2><p>
        {detail?.serviceInventoryAuthority === "local-registry" ? "权威来源：当前进程 OSP ServiceRegistry" :
          detail?.serviceInventoryAuthority === "child-status" ? "权威来源：子进程状态快照" :
            "当前子进程没有可验证的 Service 清单；不会继承主进程服务"}</p></div>
        <span className="inventory-count">{processServices.length} 项</span></div>
      <EntityTable items={processServices} onLife={() => {}} />
    </section>}
    {!governanceOnly && activeSection === "logs" && <ProcessScopedLogs process={selectedProcess} />}
    {!governanceOnly && activeSection === "configuration" && <section className="surface process-config-card">
      <div className="section-head"><div><h2>当前进程配置</h2><p>只读展示该 OS 进程实际加载的 properties；Runtime 治理操作位于全局治理页</p></div>
        <span className="inventory-count">{configEntries.length} 项</span></div>
      <div className="config-detail-list">{configEntries.map(([key, value]) => <div key={key}>
        <b>{key}</b><code>{String(value)}</code><span className="readonly-config">进程作用域 · 只读</span>
      </div>)}{!configEntries.length && <div className="workbench-empty">当前进程没有可读取的配置</div>}</div>
    </section>}
    {governanceOnly && <section className="surface process-config-card">
      <div className="section-head"><div><h2>Runtime 控制面治理</h2><p>当前 Runtime 实例的身份、权限、配置事务、审计、幂等账本和管理任务</p></div>
        <div className="section-head-actions">
          {configurationControl && <span title={(configurationControl.managementSession?.permissions || []).join(", ")}
            className={`management-auth ${!configurationControl.managementAuthenticationRequired || configurationControl.managementSession?.authenticated ? "enabled" : "disabled"}`}>
            <ShieldCheck size={21} />{configurationControl.managementAuthenticationRequired ?
              (configurationControl.managementSession?.authenticated ? `管理身份：${configurationControl.managementSession.principal}` : "管理身份未认证") :
              "开发模式未认证"}
          </span>}
          {configurationControl?.rollback && <button className="config-rollback"
            disabled={busy || !canManageConfiguration} onClick={rollbackConfiguration}
            title={`回退事务 ${configurationControl.rollback.transactionId}`}>
            <Undo2 size={22} />回退 {configurationControl.rollback.key}
          </button>}
          <span className="inventory-count">{configEntries.length} 项</span>
        </div></div>
      <div className="config-detail-list">{configEntries.map(([key, value]) => <div key={key}>
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
      </div>)}{!configEntries.length && <div className="workbench-empty">当前进程没有可读取的配置</div>}</div>
      {configurationControl?.transactions?.length > 0 && <div className="config-transactions"><h3>最近配置事务</h3>
        {configurationControl.transactions.slice(0, 5).map(item => <div key={item.transactionId}>
          <code>{item.transactionId}</code><b>{item.key || "请求未解析"}</b><span>{item.action} · {item.status}</span>
        </div>)}</div>}
      {identitySnapshot && <div className="identity-snapshot"><div><ShieldCheck size={25} /><span><b>管理身份快照</b>
        <small>第 {identitySnapshot.generation} 代 · {identitySnapshot.principalCount} 个身份 ·
          {identitySnapshot.required ? " 强制认证" : " 开发模式"} · 文件 {identitySnapshot.fileBackedPrincipalCount || 0} / 环境 {identitySnapshot.environmentBackedPrincipalCount || 0}
          {identitySnapshot.insecureFileCount > 0 ? ` · ${identitySnapshot.insecureFileCount} 个文件 ACL 过宽` :
            !identitySnapshot.filePermissionChecksComplete ? " · 文件权限未能完整核验" : " · 文件权限已核验"}</small>
      </span></div><button disabled={busy || !canManageIdentity} onClick={reloadIdentity}>
        <RefreshCw size={20} />{busy === "identity:reload" ? "正在重载" : "重载文件令牌"}</button></div>}
      {managementAudit.length > 0 && <div className="config-transactions"><h3>最近管理操作审计</h3>
        {managementAudit.slice(0, 10).map(item => <div key={item.eventId}><code>{item.principal || "未认证"}</code>
          <b>{item.operation} · {item.target || "—"}</b><span>{item.action || "—"} · {item.status} · HTTP {item.httpStatus} · {item.durationMicroseconds} μs</span>
        </div>)}</div>}
      {(managementTasks.length > 0 || managementTaskScheduler) && <div className="config-transactions"><h3>异步管理任务
        {managementTaskPersistence && <small> · 任务快照 v{managementTaskPersistence.schemaVersion || 1}/{managementTaskPersistence.integrityAlgorithm || "无校验"} {managementTaskPersistence.healthy ? "正常" : managementTaskPersistence.recoveryRequired ? "异常，需运维恢复" : "异常"}{managementTaskPersistence.previousAvailable ? " · 上一版可用" : ""}</small>}
        {managementIdempotency && <small> · 幂等账本 v{managementIdempotency.schemaVersion || 1}/{managementIdempotency.integrityAlgorithm || "无校验"} {managementIdempotency.healthy ? "正常" : managementIdempotency.recoveryRequired ? "异常，需运维恢复" : "异常"}{managementIdempotency.previousAvailable ? " · 上一版可用" : ""}（{managementIdempotency.completed} 完成 / {managementIdempotency.interrupted} 待核对）</small>}
        {managementTaskScheduler && <small> · {managementTaskScheduler.running}/{managementTaskScheduler.workerCount} worker · 排队 {managementTaskScheduler.queued} · 等锁 {managementTaskScheduler.waitingResource}{managementTaskScheduler.degraded ? " · 调度降级" : ""}</small>}
      </h3>
        {(managementTaskPersistence?.recoveryRequired || managementIdempotency?.recoveryRequired) &&
          <p className="persistence-recovery-guidance"><AlertTriangle /> 当前持久化文件需要人工恢复：
            停止 Runtime，使用 <code>pdr persistence inspect</code> 校验当前文件和上一版，
            核对真实目标状态后再执行带哈希保护的 <code>pdr persistence recover</code>。
            Web 不会自动回退幂等账本。</p>}
        {managementTasks.slice(0, 10).map(item => <div key={item.id}><code>{item.state}</code>
          <b>{item.operation} · {item.target}</b>
          <span>{item.action} · {item.principal} · {item.phase || "—"}{item.phase === "waiting-resource" ?
            ` · 等待 ${item.resourceKey}${item.blockingTaskId ? `（占用任务 ${item.blockingTaskId}）` : ""}` : ""}{item.state === "interrupted" ?
            " · 需核对目标真实状态后重新提交" : item.phase === "cancellation-requested" ?
            " · 等待底层操作到达协作取消点" : ""}</span>
          {["queued", "running"].includes(item.state) && canCancelTasks && <button disabled={busy}
            onClick={() => cancelManagementTask(item)}>{item.state === "running" ? "请求停止" : "取消"}</button>}
        </div>)}</div>}
    </section>}
    {activeSection === "business" && <BusinessExecutionList process={selectedProcess} />}
  </div>;
}

function EntityActions({ item, onLife }) {
  if (item.kind === "service") return <span className="readonly-config">
    {item.bundleId ? `生命周期：${item.bundleId}` : "提供方未知 · 不允许通用启停"}
  </span>;
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
  const ownerLabel = item => typeof item.owner === "object" && item.owner
    ? `${item.owner.kind}: ${item.owner.id}` : item.bundleId || item.owner || item.version || item.type || "所有者未上报";
  const filtered = items.filter(item =>
    `${item.name} ${item.id} ${ownerLabel(item)}`.toLowerCase().includes(filter.toLowerCase()));
  return <section className="surface">
    {searchable && <div className="table-tools"><div className="search"><Search size={17} /><input value={filter}
      onChange={event => setFilter(event.target.value)} placeholder="搜索名称、标识或所属 Bundle" /></div>
      <span>{filtered.length} 项</span></div>}
    <div className="table-scroll">
      <table className="entity-table">
        <thead><tr><th>名称</th><th>注册 / 生命周期状态</th><th>所有者 / 版本</th><th>生命周期控制</th></tr></thead>
        <tbody>{filtered.map(item => <tr key={`${item.kind}-${item.id}`}>
          <td><div className="entity-name"><span className={`entity-glyph ${item.kind}`}><Box size={17} /></span>
            <div><b>{item.name}</b><small>{item.id}</small></div></div></td>
          <td><Status state={item.state} /></td>
          <td className="secondary-text">{ownerLabel(item)}
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

function PluginGovernance({ plugins, bundles, onLife, onOpenBundles }) {
  const incompatible = plugins.filter(item => item.compatible === false || item.governanceStatus === "incompatible").length;
  const quarantined = plugins.filter(item => item.quarantined || item.governanceStatus === "quarantined").length;
  const manageable = plugins.filter(item => item.manageable).length;
  return <div className="plugin-governance">
    <section className="surface plugin-summary">
      <div className="section-head"><div><h2>外部插件治理</h2><p>只管理采用 pdr.plugin.* 契约的扩展；内置 Bundle 仍归进程管理</p></div>
        <span className={`plugin-governance-state ${incompatible || quarantined ? "attention" : "ready"}`}>
          <i />{plugins.length ? incompatible || quarantined ? "需要处理" : "插件正常" : "等待安装"}
        </span></div>
      <div className="plugin-stats">
        <article><small>已安装外部插件</small><b>{plugins.length}</b><span>pdr.plugin.*</span></article>
        <article><small>可执行生命周期操作</small><b>{manageable}</b><span>由 Runtime 白名单授权</span></article>
        <article className={incompatible ? "bad" : ""}><small>兼容性异常</small><b>{incompatible}</b><span>API / ABI / Runtime 契约</span></article>
        <article className={quarantined ? "bad" : ""}><small>已隔离</small><b>{quarantined}</b><span>连续失败预算保护</span></article>
      </div>
    </section>
    {plugins.length ? <EntityTable items={plugins} onLife={onLife} /> : <section className="surface plugin-empty-state">
      <Boxes size={42} />
      <h2>当前未安装外部插件</h2>
      <p>Runtime 已加载 {bundles.length} 个内置 Bundle，运行状态正常；它们不属于外部插件治理，因此不会混入此列表。</p>
      <div className="plugin-contract"><span>插件标识：<code>pdr.plugin.*</code></span><span>必需元数据：Plugin-API、Plugin-ABI、Runtime-Version</span></div>
      <button type="button" onClick={onOpenBundles}><AppWindow size={17} />查看进程中的全部 Bundles</button>
    </section>}
  </div>;
}

function DeviceInventory({ inventory }) {
  const [filter, setFilter] = useState("");
  const devices = (inventory?.devices || []).filter(device =>
    !filter || `${device.id} ${device.type} ${device.bundle}`.toLowerCase().includes(filter.toLowerCase()));
  return <section className="surface">
    <div className="section-head"><div><h2>设备实例</h2>
      <p>Runtime 作用域；由 Service 提供，生命周期归提供方 Bundle</p></div>
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
        <td className="secondary-text"><div className="owner-stack"><small>Service: {device.serviceId || device.service || "—"}</small>
          <small>Bundle: {device.bundleId || device.bundle || "—"}</small></div></td>
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

const defaultTerminalCommands = [
  "help", "status", "ps", "bundle list", "bundle show", "service list", "service show",
  "logs runtime --tail 80", "logs runtime --follow", "diagnose all --deep", "health tree",
  "protocol list", "protocol check", "device list", "device check", "metrics top",
  "metrics anomalies", "trace list", "trace show", "config effective", "config diff",
  "config validate", "provider list", "agent status", "agent threads", "agent net",
  "support collect", "jobs", "job show", "cancel", "repair bundle", "repair process",
  "repair protocol", "crash list", "crash show", "dump process", "dds participants",
  "dds discovery", "dds qos", "version", "uptime", "whoami", "clear", "history", "watch -n 2"
];

function DiagnosticTerminalPage({ host }) {
  const [entries, setEntries] = useState([{ id: "welcome", kind: "system", lines: [
    "PocoDDS Runtime Diagnostic Terminal",
    "输入 help 查看命令；按 Tab 补全，↑/↓ 浏览历史，Ctrl+L 清屏。",
    "这是受控诊断终端，不会执行 PowerShell、cmd、bash 或任意脚本。"
  ] }]);
  const [input, setInput] = useState("");
  const [history, setHistory] = useState([]);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const [catalog, setCatalog] = useState(defaultTerminalCommands);
  const [prompt, setPrompt] = useState(`pdr@${host || "runtime"}:runtime$`);
  const [principal, setPrincipal] = useState("connecting");
  const [mayExecute, setMayExecute] = useState(false);
  const [busy, setBusy] = useState(false);
  const [watching, setWatching] = useState(false);
  const [completion, setCompletion] = useState([]);
  const inputRef = useRef(null);
  const endRef = useRef(null);
  const watchRef = useRef(null);
  const streamRef = useRef(null);
  const sequenceRef = useRef(0);

  const append = useCallback(entry => {
    sequenceRef.current += 1;
    setEntries(current => [...current, { id: `${Date.now()}-${sequenceRef.current}`, ...entry }].slice(-1500));
  }, []);

  useEffect(() => {
    let active = true;
    request("/api/v1/diagnostic-terminal").then(data => {
      if (!active) return;
      setCatalog([...new Set([...(data.commands || []), ...defaultTerminalCommands])]);
      setPrompt(data.prompt || `pdr@${host || "runtime"}:runtime$`);
      setPrincipal(data.principal || "unknown");
      setMayExecute(Boolean(data.mayExecute));
    }).catch(error => {
      if (active) append({ kind: "error", lines: [`终端服务连接失败: ${error.message}`] });
    });
    return () => {
      active = false;
      if (watchRef.current) clearInterval(watchRef.current);
      streamRef.current?.abort();
    };
  }, [append, host]);

  useEffect(() => { endRef.current?.scrollIntoView({ block: "end" }); }, [entries, busy]);

  const executeBackend = useCallback(async (command, watch = false) => {
    setBusy(true);
    try {
      const result = await request("/api/v1/diagnostic-terminal", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command })
      });
      const jsonFormat = /(?:^|\s)--format(?:=|\s+)json(?:\s|$)/i.test(command);
      const lines = jsonFormat ? [JSON.stringify({ schemaVersion: result.schemaVersion,
        exitCode: result.exitCode, facts: result.facts || {}, findings: result.findings || [] }, null, 2)] :
        (result.lines || []);
      append({ kind: watch ? "watch" : "command", command, lines,
        findings: result.findings || [], facts: result.facts || {},
        artifactUrl: result.facts?.["artifact.url"] || "",
        exitCode: Number(result.exitCode || 0), duration: Number(result.durationMilliseconds || 0) });
    } catch (error) {
      append({ kind: "error", command, lines: [error.message], exitCode: 1 });
    } finally { setBusy(false); }
  }, [append]);

  const stopWatch = useCallback(() => {
    let stopped = false;
    if (watchRef.current) {
      clearInterval(watchRef.current);
      watchRef.current = null;
      stopped = true;
    }
    if (streamRef.current) {
      streamRef.current.active = false;
      streamRef.current.controller?.abort();
      streamRef.current = null;
      stopped = true;
    }
    if (!stopped) return false;
    setWatching(false);
    setBusy(false);
    append({ kind: "system", lines: ["^C", "持续诊断任务已停止。"] });
    return true;
  }, [append]);

  const streamLogs = useCallback(async command => {
    stopWatch();
    const processMatch = command.match(/^logs(?:\s+([^\s-][^\s]*))?/i);
    const tailMatch = command.match(/--tail\s+(\d+)/i);
    const grepMatch = command.match(/--grep\s+(?:"([^"]*)"|'([^']*)'|([^\s]+))/i);
    const process = processMatch?.[1] || "runtime";
    const tail = Math.max(0, Math.min(Number(tailMatch?.[1] || 40), 500));
    const grep = grepMatch?.[1] ?? grepMatch?.[2] ?? grepMatch?.[3] ?? "";
    const state = { active: true, controller: null };
    streamRef.current = state;
    setWatching(true);
    setBusy(true);
    append({ kind: "command", command, lines: [
      `正在跟踪 ${process} 日志（初始 ${tail} 行）；按 Ctrl+C 停止。`
    ], exitCode: 0 });
    let reconnectTail = tail;
    try {
      while (state.active) {
        state.controller = new AbortController();
        const query = new URLSearchParams({ process, tail: String(reconnectTail), duration: "60" });
        if (grep) query.set("grep", grep);
        const token = sessionStorage.getItem("pdr.webui.token") || "";
        const response = await fetch(`/api/v1/diagnostic-log-stream?${query}`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          signal: state.controller.signal
        });
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(body.error || body.message || `日志流连接失败 (${response.status})`);
        }
        setBusy(false);
        const reader = response.body?.getReader();
        if (!reader) throw new Error("浏览器不支持流式响应读取");
        const decoder = new TextDecoder();
        let buffer = "";
        while (state.active) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
          let boundary;
          while ((boundary = buffer.indexOf("\n\n")) >= 0) {
            const frame = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);
            const eventName = frame.split("\n").find(line => line.startsWith("event:"))?.slice(6).trim();
            const data = frame.split("\n").filter(line => line.startsWith("data:"))
              .map(line => line.slice(5).trimStart()).join("\n");
            if (!data) continue;
            const event = JSON.parse(data);
            if (eventName === "log") append({ kind: "stream", lines: [event.line || " "] });
            else if (eventName === "end" && event.line === "output-limit")
              append({ kind: "error", lines: ["实时日志达到单段 2000 行上限，正在从当前位置续接。"] });
          }
        }
        reconnectTail = 0;
      }
    } catch (error) {
      if (state.active && error.name !== "AbortError")
        append({ kind: "error", command, lines: [`实时日志中断: ${error.message}`], exitCode: 1 });
    } finally {
      if (streamRef.current === state) streamRef.current = null;
      setWatching(false);
      setBusy(false);
    }
  }, [append, stopWatch]);

  const downloadArtifact = useCallback(async (url, suggestedName) => {
    try {
      const token = sessionStorage.getItem("pdr.webui.token") || "";
      const response = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
      if (!response.ok) throw new Error(`下载失败 (${response.status})`);
      const blobUrl = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a");
      anchor.href = blobUrl;
      anchor.download = suggestedName || "pdr-support.json";
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
    } catch (error) {
      append({ kind: "error", lines: [`诊断包下载失败: ${error.message}`], exitCode: 1 });
    }
  }, [append]);

  const executeGoverned = useCallback(async command => {
    const tokens = command.match(/"[^"]*"|'[^']*'|\S+/g)?.map(token =>
      token.replace(/^(?:"|')|(?:"|')$/g, "")) || [];
    const verb = tokens[0]?.toLowerCase();
    try {
      if (verb === "jobs") {
        const stateToken = tokens.find(token => token.startsWith("--state="));
        const query = new URLSearchParams({ limit: "50" });
        if (stateToken) query.set("state", stateToken.slice(8));
        const result = await request(`/api/v1/management-tasks?${query}`);
        const lines = ["STATE       OPERATION             TARGET                 TASK ID"];
        for (const task of result.tasks || []) lines.push(
          `${String(task.state || "-").padEnd(11)} ${String(task.operation || "-").padEnd(21)} ` +
          `${String(task.target || task.id || "-").padEnd(22)} ${task.id || "-"}`);
        if (lines.length === 1) lines.push("暂无管理任务。");
        append({ kind: "command", command, lines, exitCode: 0,
          facts: { "scheduler.state": result.scheduler?.state || "unknown" } });
        return;
      }
      if (verb === "job") {
        if (tokens[1]?.toLowerCase() !== "show" || !tokens[2])
          throw new Error("用法: job show <task-id>");
        const task = await request(`/api/v1/management-tasks/${encodeURIComponent(tokens[2])}`);
        append({ kind: "command", command, lines: [JSON.stringify(task, null, 2)], exitCode: 0 });
        return;
      }
      if (verb === "cancel") {
        if (!tokens[1] || !tokens.includes("--confirm"))
          throw new Error("用法: cancel <task-id> --confirm");
        const result = await request("/api/v1/management-tasks", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: tokens[1], action: "cancel" })
        });
        append({ kind: "command", command, lines: [result.message || "取消请求已提交",
          JSON.stringify(result.task || {}, null, 2)], exitCode: 0 });
        return;
      }
      if (verb !== "repair") return;
      const kind = tokens[1]?.toLowerCase();
      const id = tokens[2];
      let action = tokens[3]?.toLowerCase();
      if (!kind || !id || !action || !tokens.includes("--confirm"))
        throw new Error("用法: repair <bundle|process|protocol> <id> <动作> --confirm");
      const routes = { bundle: "/api/v1/bundle-lifecycle", process: "/api/v1/process-lifecycle",
        protocol: "/api/v1/protocols" };
      if (!routes[kind]) throw new Error("修复类型仅支持 bundle、process、protocol。");
      if (kind === "protocol" && action === "reconnect") action = "restart";
      const allowed = kind === "protocol" ? ["open", "close", "restart"] :
        kind === "bundle" ? ["start", "stop", "restart", "reset-quarantine"] :
          ["start", "stop", "restart"];
      if (!allowed.includes(action)) throw new Error(`${kind} 不支持动作 ${action}`);
      const payload = { id, action, async: action !== "reset-quarantine",
        startTimeoutMilliseconds: 30000, executionTimeoutMilliseconds: 30000,
        ...(kind === "protocol" ? { stabilityWindowMilliseconds: 1000 } : {}),
        ...(tokens.includes("--recover-persistence") ? { confirmPersistenceRecovery: true } : {}) };
      const result = await request(routes[kind], { method: "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const task = result.task || {};
      append({ kind: "command", command, lines: [
        result.message || "受控修复已提交", task.id ? `task: ${task.id} · state: ${task.state}` : "操作已完成",
        "所有修复均通过 Runtime 治理接口执行，包含权限、幂等、超时和审计控制。"
      ], exitCode: 0, facts: task.id ? { "task.id": task.id } : {} });
    } catch (error) {
      append({ kind: "error", command, lines: [error.message], exitCode: 1 });
    }
  }, [append]);

  useEffect(() => {
    const interrupt = event => {
      if (!event.ctrlKey || event.key.toLowerCase() !== "c") return;
      event.preventDefault();
      event.stopPropagation();
      if (!stopWatch()) append({ kind: "system", lines: ["^C"] });
      setInput("");
    };
    window.addEventListener("keydown", interrupt, true);
    return () => window.removeEventListener("keydown", interrupt, true);
  }, [append, stopWatch]);

  const run = useCallback(async raw => {
    const command = raw.trim();
    if (!command) return;
    setHistory(current => [command, ...current.filter(item => item !== command)].slice(0, 100));
    setHistoryIndex(-1);
    setCompletion([]);
    if (command === "clear") { setEntries([]); return; }
    if (command === "history") {
      append({ kind: "command", command, lines: history.length ?
        history.slice().reverse().map((item, index) => `${String(index + 1).padStart(3, " ")}  ${item}`) :
        ["history is empty"] });
      return;
    }
    const watchMatch = command.match(/^watch(?:\s+-n)?\s+(\d+(?:\.\d+)?)\s+(.+)$/i);
    if (watchMatch) {
      stopWatch();
      const seconds = Math.max(0.5, Math.min(Number(watchMatch[1]), 60));
      const watchedCommand = watchMatch[2].trim();
      append({ kind: "system", lines: [`watch: 每 ${seconds}s 执行 ${watchedCommand}；按 Ctrl+C 停止。`] });
      await executeBackend(watchedCommand, true);
      watchRef.current = setInterval(() => executeBackend(watchedCommand, true), seconds * 1000);
      setWatching(true);
      return;
    }
    if (/^watch\b/i.test(command)) {
      append({ kind: "error", command, lines: ["用法: watch -n <秒> <命令>，例如 watch -n 2 status"], exitCode: 2 });
      return;
    }
    if (/^logs\b.*(?:^|\s)(?:-f|--follow)(?:\s|$)/i.test(command)) {
      await streamLogs(command);
      return;
    }
    if (/^(?:jobs|job\s+show|cancel|repair)\b/i.test(command)) {
      await executeGoverned(command);
      return;
    }
    await executeBackend(command);
  }, [append, executeBackend, executeGoverned, history, stopWatch, streamLogs]);

  const handleKeyDown = event => {
    if (event.ctrlKey && event.key.toLowerCase() === "l") {
      event.preventDefault(); setEntries([]); return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      if (!history.length) return;
      const next = Math.min(historyIndex + 1, history.length - 1);
      setHistoryIndex(next); setInput(history[next]); return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      const next = historyIndex - 1;
      setHistoryIndex(next);
      setInput(next >= 0 ? history[next] : ""); return;
    }
    if (event.key === "Tab") {
      event.preventDefault();
      const needle = input.trimStart().toLowerCase();
      const matches = catalog.filter(command => command.toLowerCase().startsWith(needle));
      setCompletion(matches);
      if (matches.length === 1) setInput(`${matches[0]} `);
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const command = input; setInput(""); run(command);
    }
  };

  return <section className="diagnostic-terminal-page">
    <header className="diagnostic-terminal-head">
      <div><span><Terminal size={24} /></span><div><h2>Runtime 诊断终端</h2>
        <p>Linux 风格交互 · 受控只读命令 · Bundle 内诊断 Service</p></div></div>
      <div className="terminal-session-meta"><span><i />已连接</span><small>身份：{principal} · {mayExecute ? "可执行受控修复" : "只读诊断"}</small></div>
    </header>
    <div className="terminal-safety"><ShieldCheck size={17} /><b>安全模式</b>
      <span>仅允许 Runtime 诊断命令，不提供操作系统 Shell；生命周期操作继续使用治理页面。</span></div>
    <div className="diagnostic-command-chips">
      {["status", "health tree", "diagnose all --deep", "protocol check", "metrics anomalies", "logs runtime --follow", "support collect"].map(command =>
        <button key={command} onClick={() => run(command)}>{command}</button>)}
    </div>
    <div className="diagnostic-console" onClick={() => inputRef.current?.focus()} role="application"
      aria-label="Runtime 诊断终端">
      {entries.map(entry => <div key={entry.id} className={`diagnostic-entry ${entry.kind || ""}`}>
        {entry.command && <div className="diagnostic-command"><span>{prompt}</span><b>{entry.command}</b></div>}
        {(entry.lines || []).map((line, index) => <pre key={`${entry.id}-${index}`}>{line || " "}</pre>)}
        {!!entry.findings?.length && <div className="diagnostic-findings">{entry.findings.map((finding, index) =>
          <article key={`${entry.id}-finding-${index}`} className={finding.severity || "info"}>
            <b>{finding.code} · {finding.target || finding.scope}</b><span>{finding.summary}</span>
            {finding.detail && <small>证据：{finding.detail}</small>}
            {finding.remediation && <small>建议：{finding.remediation}</small>}
          </article>)}</div>}
        {entry.artifactUrl && <button className="diagnostic-artifact" onClick={event => {
          event.stopPropagation();
          downloadArtifact(entry.artifactUrl, entry.facts?.["artifact.id"]);
        }}><FileText size={15} />下载脱敏诊断包</button>}
        {entry.command && <small className={entry.exitCode ? "failed" : ""}>
          exit {entry.exitCode || 0}{entry.duration != null ? ` · ${entry.duration.toFixed(1)} ms` : ""}</small>}
      </div>)}
      {completion.length > 1 && <div className="terminal-completions">{completion.join("    ")}</div>}
      <div className="diagnostic-prompt"><span>{prompt}</span><input ref={inputRef} value={input}
        onChange={event => { setInput(event.target.value); setCompletion([]); }} onKeyDown={handleKeyDown}
        autoCapitalize="off" autoComplete="off" autoCorrect="off" spellCheck="false"
        aria-label="输入诊断命令" autoFocus /><i className={busy ? "busy" : ""} /></div>
      <div ref={endRef} />
    </div>
    <footer className="diagnostic-terminal-footer"><span>Tab 补全 · ↑↓ 历史 · Ctrl+L 清屏 · Ctrl+C 停止 watch/日志流</span>
      {watching ? <button onClick={stopWatch}>停止持续任务</button> : <span>ready</span>}</footer>
  </section>;
}

function App() {
  const initialPage = new URLSearchParams(window.location.search).get("page");
  const [page, setPage] = useState(pageMeta[initialPage] && initialPage !== "tracing" ? initialPage : "overview");
  const [processSection, setProcessSection] = useState("overview");
  const [menuOpen, setMenuOpen] = useState(false);
  const [topology, setTopology] = useState({ processes: [], services: [], bundles: [], hostResources: {} });
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
    const monitoredHostResources = monitoring.current || {};
    if (mainDetail?.bundles) {
      const management = new Map(mainDetail.bundles.map(bundle => [bundle.id, bundle]));
      data.bundles = (data.bundles || []).map(bundle => ({
        ...bundle, ...(management.get(bundle.id) || {})
      }));
    }
    if (Object.keys(monitoredHostResources).length)
      data.hostResources = { ...(data.hostResources || {}), ...monitoredHostResources, scope: "host", hostId: data.host };
    setTopology(data);
    const resources = data.hostResources || {};
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
  const pluginItems = (topology.bundles || []).filter(item => item.plugin || String(item.id).startsWith("pdr.plugin."));
  const openProcessSection = section => {
    setProcessSection(section);
    setPage("processes");
    const url = new URL(window.location.href);
    url.searchParams.set("page", "processes");
    window.history.replaceState({}, "", url);
  };

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
      <nav>{navItems.map(([id, Icon, href]) => <button key={id} className={page === id ? "active" : ""}
        onClick={() => {
          setMenuOpen(false);
          if (href) window.location.assign(href);
          else {
            setPage(id);
            const url = new URL(window.location.href);
            if (id === "overview") url.searchParams.delete("page");
            else url.searchParams.set("page", id);
            window.history.replaceState({}, "", url);
          }
        }}><Icon size={18} /><span>{pageMeta[id][0]}</span><ChevronRight size={15} /></button>)}</nav>
      <div className={`runtime-state ${health?.ready === false ? "degraded" : ""}`}><i /><div>
        <b>{health?.ready === false ? "Runtime 异常" : "Runtime 在线"}</b>
        <small>{topology.host || "本地主机"}</small></div></div>
    </aside>
    <main>
      <div className="content">
        {page === "overview" && <RuntimeTopologyOverview health={health} topology={topology}
          processDetail={processDetail} childProcessDetail={childProcessDetail} history={resourceHistory} alertInventory={alertInventory}
          onOpenProcesses={() => openProcessSection("overview")} onOpenLogs={() => openProcessSection("logs")} />}
        {page === "processes" && <ProcessWorkbench mainProcess={topology.mainProcess}
          activeSection={processSection} onSectionChange={setProcessSection} onNotify={notify} />}
        {page === "devices" && <><DeviceInventory inventory={deviceInventory} />
          <ProtocolSummary data={businessMetrics} inventory={protocolInventory} onLifecycle={protocolLife} /></>}
        {page === "plugins" && <PluginGovernance plugins={pluginItems} bundles={topology.bundles || []} onLife={life}
          onOpenBundles={() => openProcessSection("bundles")} />}
        {page === "metrics" && <MetricsCenter data={businessMetrics} />}
        {page === "governance" && <ProcessWorkbench mainProcess={topology.mainProcess}
          activeSection="configuration" onSectionChange={() => {}} onNotify={notify} governanceOnly />}
        {page === "terminal" && <DiagnosticTerminalPage host={topology.host} />}
      </div>
    </main>
    {menuOpen && <button className="mobile-overlay" onClick={() => setMenuOpen(false)} />}
    {toast && <div className={`toast ${toast.error ? "error" : ""}`}>{toast.error ? <X size={17} /> : <Zap size={17} />}{toast.message}</div>}
  </div>;
}

createRoot(document.getElementById("root")).render(<App />);
