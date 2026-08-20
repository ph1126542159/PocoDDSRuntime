const apiRoot = "/api/v1/robotics-simulation";
const state = { catalog: null, runs: [], activeRun: null, selectedNode: "", module: "warehouse", timer: null };

const $ = id => document.getElementById(id);
const statusText = { queued: "排队中", pending: "待执行", running: "执行中", success: "成功", failed: "失败", cancelled: "已取消" };
const exportStatusText = { "local-only": "本地 Trace", pending: "等待导出", exporting: "正在导出", exported: "OTLP 已导出", failed: "OTLP 导出失败" };

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) }
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function showToast(message, error = false) {
  const toast = $("toast");
  toast.textContent = message;
  toast.className = `toast visible${error ? " error" : ""}`;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => { toast.className = "toast"; }, 3000);
}

function setStatus(element, status) {
  element.className = `status ${status}`;
  element.textContent = statusText[status] || status;
}

function formatDuration(nanoseconds) {
  if (!nanoseconds) return "—";
  if (nanoseconds >= 1e9) return `${(nanoseconds / 1e9).toFixed(2)} s`;
  return `${(nanoseconds / 1e6).toFixed(2)} ms`;
}

function renderCatalog() {
  const list = $("scenario-list");
  list.replaceChildren();
  for (const scenario of state.catalog?.scenarios || []) {
    const button = document.createElement("button");
    button.className = `scenario-card${scenario.module === state.module ? " active" : ""}`;
    button.dataset.module = scenario.module;
    const title = document.createElement("strong");
    title.textContent = scenario.title;
    const mission = document.createElement("code");
    mission.textContent = `${scenario.module}/${scenario.mission}`;
    const description = document.createElement("span");
    description.textContent = scenario.description;
    const count = document.createElement("small");
    count.textContent = `${scenario.stepCount} 个业务节点`;
    button.append(title, mission, description, count);
    button.addEventListener("click", () => {
      if (state.activeRun && ["queued", "running"].includes(state.activeRun.status)) return;
      state.module = scenario.module;
      renderCatalog();
    });
    list.append(button);
  }
}

function renderFlow(run) {
  const flow = $("flow");
  flow.replaceChildren();
  flow.className = "flow";
  if (!run?.nodes?.length) {
    flow.className = "flow empty-state";
    flow.textContent = "启动业务仿真后显示执行节点";
    return;
  }
  run.nodes.forEach((node, index) => {
    const wrapper = document.createElement("div");
    wrapper.className = "flow-step";
    if (index) {
      const connector = document.createElement("div");
      connector.className = `connector ${run.nodes[index - 1].status}`;
      connector.innerHTML = "<i></i>";
      wrapper.append(connector);
    }
    const button = document.createElement("button");
    button.className = `flow-node ${node.status}${state.selectedNode === node.spanId ? " selected" : ""}`;
    button.dataset.span = node.spanId;
    const sequence = document.createElement("span");
    sequence.className = "node-sequence";
    sequence.textContent = String(index + 1).padStart(2, "0");
    const copy = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = node.displayName || node.operation;
    const operation = document.createElement("code");
    operation.textContent = node.operation;
    copy.append(title, operation);
    const badge = document.createElement("span");
    badge.className = `node-state ${node.status}`;
    badge.textContent = statusText[node.status] || node.status;
    button.append(sequence, copy, badge);
    button.addEventListener("click", () => {
      state.selectedNode = node.spanId;
      renderFlow(state.activeRun);
      renderInspector(node);
    });
    wrapper.append(button);
    flow.append(wrapper);
  });
  const selected = run.nodes.find(node => node.spanId === state.selectedNode);
  if (selected) renderInspector(selected);
  else {
    const running = run.nodes.find(node => node.status === "running") || run.nodes.find(node => node.status === "success");
    if (running) {
      state.selectedNode = running.spanId;
      renderFlow(run);
    }
  }
}

function renderFields(container, values) {
  container.replaceChildren();
  const entries = Object.entries(values || {});
  if (!entries.length) {
    const empty = document.createElement("p");
    empty.className = "field-empty";
    empty.textContent = "无";
    container.append(empty);
    return;
  }
  for (const [key, value] of entries) {
    const field = document.createElement("div");
    const label = document.createElement("span");
    label.textContent = key;
    const output = document.createElement("code");
    output.textContent = value;
    field.append(label, output);
    container.append(field);
  }
}

function renderInspector(node) {
  $("node-empty").classList.add("hidden");
  $("node-detail").classList.remove("hidden");
  setStatus($("node-status"), node.status);
  $("node-title").textContent = node.displayName || node.operation;
  $("node-operation").textContent = node.operation;
  $("node-service").textContent = `${node.serviceName} · PID ${node.processId || "—"}`;
  $("node-duration").textContent = node.status === "running" ? "执行中" : formatDuration(node.durationNanoseconds);
  $("node-trace").textContent = node.traceId;
  $("node-span").textContent = node.spanId;
  $("node-parent-span").textContent = node.parentSpanId;
  $("node-traceparent").textContent = node.traceParent;
  $("node-span-kind").textContent = node.spanKind || "INTERNAL";
  $("node-otel-status").textContent = node.otelStatusCode || "STATUS_CODE_UNSET";
  renderFields($("node-inputs"), node.inputs);
  renderFields($("node-outputs"), node.outputs);
  const logs = $("node-logs");
  logs.replaceChildren();
  if (!node.logs?.length) {
    const empty = document.createElement("p");
    empty.className = "field-empty";
    empty.textContent = "暂无节点日志";
    logs.append(empty);
  } else {
    [...node.logs].reverse().forEach(log => {
      const item = document.createElement("article");
      item.className = `log-entry ${log.level}`;
      const head = document.createElement("header");
      const level = document.createElement("b");
      level.textContent = log.level.toUpperCase();
      const time = document.createElement("time");
      time.textContent = new Date(log.timestampUnixMicroseconds / 1000).toLocaleTimeString();
      head.append(level, time);
      const message = document.createElement("p");
      message.textContent = log.message;
      item.append(head, message);
      const fields = Object.entries(log.fields || {});
      if (fields.length) {
        const meta = document.createElement("code");
        meta.textContent = fields.map(([key, value]) => `${key}=${value}`).join("  ");
        item.append(meta);
      }
      logs.append(item);
    });
  }
}

function renderTrace(run) {
  $("trace-id").textContent = run?.traceId || "—";
  $("root-span-id").textContent = run?.rootSpanId || "—";
  $("instrumentation-scope").textContent = run?.telemetry?.instrumentationScope?.name || "—";
  $("trace-span-count").textContent = run?.nodes?.length ? String(run.nodes.length + 1) : "0";

  const exportState = run?.telemetry?.export?.status || "local-only";
  const exportBadge = $("otel-export-status");
  exportBadge.className = `otel-export ${exportState}`;
  exportBadge.textContent = exportStatusText[exportState] || exportState;
  exportBadge.title = run?.telemetry?.export?.error || run?.telemetry?.export?.endpoint || "未配置 Collector，Trace 保存在本机内存";

  const waterfall = $("trace-waterfall");
  waterfall.replaceChildren();
  waterfall.className = "trace-waterfall";
  if (!run?.nodes?.length) {
    waterfall.className = "trace-waterfall empty-state";
    waterfall.textContent = "启动业务仿真后显示 OpenTelemetry Span 瀑布图";
    return;
  }

  const traceStart = run.startedUnixMicroseconds;
  const liveEnd = run.endedUnixMicroseconds || Date.now() * 1000;
  const traceDuration = Math.max(1, liveEnd - traceStart);
  run.nodes.forEach((node, index) => {
    const row = document.createElement("button");
    row.className = `waterfall-row ${node.status}${state.selectedNode === node.spanId ? " selected" : ""}`;
    const identity = document.createElement("div");
    identity.className = "waterfall-identity";
    const name = document.createElement("strong");
    name.textContent = `${String(index + 1).padStart(2, "0")} ${node.displayName || node.operation}`;
    const span = document.createElement("code");
    span.textContent = node.spanId;
    identity.append(name, span);

    const lane = document.createElement("div");
    lane.className = "waterfall-lane";
    const bar = document.createElement("i");
    const start = node.startedUnixMicroseconds || traceStart;
    const end = node.endedUnixMicroseconds || (node.status === "running" ? liveEnd : start);
    const left = Math.max(0, Math.min(96, ((start - traceStart) / traceDuration) * 100));
    const width = node.status === "pending" ? 0 : Math.max(2.5, Math.min(100 - left, ((end - start) / traceDuration) * 100));
    bar.style.left = `${left}%`;
    bar.style.width = `${width}%`;
    lane.append(bar);

    const duration = document.createElement("span");
    duration.textContent = node.status === "running" ? "执行中" : node.status === "pending" ? "待执行" : formatDuration(node.durationNanoseconds);
    row.append(identity, lane, duration);
    row.addEventListener("click", () => {
      state.selectedNode = node.spanId;
      renderAll();
    });
    waterfall.append(row);
  });
}

function renderWorld(run) {
  const running = run?.nodes?.find(node => node.status === "running");
  const completed = run?.nodes?.filter(node => node.status === "success").length || 0;
  const total = run?.nodes?.length || 0;
  const ratio = total ? Math.min(1, completed / total + (running ? 0.09 : 0)) : 0;
  const simulatedX = run?.result?.x;
  const positionRatio = simulatedX === undefined ? ratio : Math.max(0, Math.min(1, Number(simulatedX) / 2));
  $("robot").style.left = `${10 + positionRatio * 76}%`;
  const obstacleActive = run?.events?.some(event => event.fields?.event === "obstacle-injected") &&
    !run?.events?.some(event => event.fields?.event === "obstacle-cleared");
  $("obstacle").classList.toggle("visible", Boolean(obstacleActive));
  const events = $("world-events");
  events.replaceChildren();
  const recent = [...(run?.events || [])].slice(-4).reverse();
  if (!recent.length) {
    const empty = document.createElement("span");
    empty.textContent = "等待仿真事件";
    events.append(empty);
  } else recent.forEach(event => {
    const line = document.createElement("div");
    line.className = event.level;
    const time = document.createElement("time");
    time.textContent = new Date(event.timestampUnixMicroseconds / 1000).toLocaleTimeString();
    const message = document.createElement("span");
    message.textContent = event.message;
    line.append(time, message);
    events.append(line);
  });
}

function renderMetrics(run) {
  $("metric-scene").textContent = run?.title || "—";
  const completed = run?.nodes?.filter(node => node.status === "success").length || 0;
  $("metric-progress").textContent = `${completed} / ${run?.nodes?.length || 0}`;
  $("metric-position").textContent = run?.result?.x === undefined ? "—" : Number(run.result.x).toFixed(3);
  $("metric-watchdog").textContent = run?.module !== "warehouse" ? "不适用" : run?.result?.watchdogStop === true ? "已验证" : run?.status === "running" ? "验证中" : "待验证";
  const duration = run?.status === "running" ? (Date.now() * 1000 - run.startedUnixMicroseconds) * 1000 : run?.durationNanoseconds || 0;
  $("metric-duration").textContent = duration ? `${(duration / 1e9).toFixed(2)} s` : "0.00 s";
}

function renderHistory() {
  const container = $("run-history");
  container.replaceChildren();
  if (!state.runs.length) {
    container.textContent = "暂无仿真记录";
    return;
  }
  state.runs.forEach(run => {
    const button = document.createElement("button");
    button.className = `history-item ${run.status}${state.activeRun?.runId === run.runId ? " active" : ""}`;
    const status = document.createElement("span");
    status.className = `history-status ${run.status}`;
    status.textContent = statusText[run.status] || run.status;
    const copy = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = run.businessName;
    const meta = document.createElement("small");
    meta.textContent = `${run.module}/${run.mission} · ${run.completedStepCount}/${run.stepCount} Span · Trace ${run.traceId.slice(0, 8)}… · ${new Date(run.startedUnixMicroseconds / 1000).toLocaleString()}`;
    copy.append(title, meta);
    button.append(status, copy);
    button.addEventListener("click", async () => {
      state.activeRun = await request(`${apiRoot}/runs/${encodeURIComponent(run.runId)}`);
      state.selectedNode = "";
      renderAll();
    });
    container.append(button);
  });
}

function renderAll() {
  const run = state.activeRun;
  setStatus($("run-status"), run?.status || "pending");
  const active = run && ["queued", "running"].includes(run.status);
  $("start-button").disabled = active;
  $("cancel-button").disabled = !active;
  document.querySelectorAll(".scenario-card").forEach(button => { button.disabled = active; });
  renderMetrics(run);
  renderTrace(run);
  renderWorld(run);
  renderFlow(run);
  renderHistory();
}

async function refresh() {
  try {
    const data = await request(`${apiRoot}/runs`);
    state.runs = data.runs || [];
    if (state.activeRun) {
      const latest = state.runs.find(run => run.runId === state.activeRun.runId);
      if (latest) state.activeRun = await request(`${apiRoot}/runs/${encodeURIComponent(latest.runId)}`);
      else {
        state.activeRun = null;
        state.selectedNode = "";
      }
    }
    if (!state.activeRun && state.runs.length) {
      state.activeRun = await request(`${apiRoot}/runs/${encodeURIComponent(state.runs[0].runId)}`);
    }
    $("connection-text").textContent = "仿真服务在线";
    document.querySelector(".connection").classList.add("online");
    renderAll();
  } catch (error) {
    $("connection-text").textContent = "仿真服务离线";
    document.querySelector(".connection").classList.remove("online");
    showToast(error.message, true);
  }
}

async function startRun() {
  try {
    const body = {
      module: state.module,
      periodMs: Number($("period-ms").value),
      streamDelayMs: Number($("stream-delay-ms").value),
      maxSteps: Number($("max-steps").value)
    };
    const summary = await request(`${apiRoot}/runs`, { method: "POST", body: JSON.stringify(body) });
    state.activeRun = await request(`${apiRoot}/runs/${encodeURIComponent(summary.runId)}`);
    state.selectedNode = "";
    showToast("机器人业务仿真已启动");
    await refresh();
  } catch (error) { showToast(error.message, true); }
}

async function cancelRun() {
  if (!state.activeRun) return;
  try {
    await request(`${apiRoot}/runs/${encodeURIComponent(state.activeRun.runId)}/cancel`, { method: "POST", body: "{}" });
    showToast("已请求停止仿真任务");
    await refresh();
  } catch (error) { showToast(error.message, true); }
}

async function init() {
  try {
    state.catalog = await request(`${apiRoot}/catalog`);
    renderCatalog();
    await refresh();
    state.timer = setInterval(refresh, 500);
  } catch (error) { showToast(error.message, true); }
}

$("start-button").addEventListener("click", startRun);
$("cancel-button").addEventListener("click", cancelRun);
$("refresh-button").addEventListener("click", refresh);
window.addEventListener("beforeunload", () => clearInterval(state.timer));
init();
