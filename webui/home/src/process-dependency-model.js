const PROCESS_STATE_LABELS = Object.freeze({
  running: "运行中",
  starting: "启动中",
  "waiting-dependency": "等待依赖",
  "dependency-failed": "依赖失败",
  "restart-pending": "等待重启",
  failed: "失败",
  stopped: "已停止",
  exited: "已退出",
  remote: "远程"
});

const BLOCKING_REASON_LABELS = Object.freeze({
  none: "无阻塞",
  "dependency-starting": "上游正在启动",
  "dependency-waiting": "上游等待其依赖",
  "dependency-recovering": "上游正在恢复",
  "dependency-stopped": "上游已停止",
  "dependency-failed": "上游失败",
  "dependency-unavailable": "上游不可用",
  "dependency-not-ready": "上游尚未就绪"
});

const EDGE_STATE_LABELS = Object.freeze({
  satisfied: "已满足",
  waiting: "等待",
  failed: "失败"
});

export const processStateLabel = state =>
  PROCESS_STATE_LABELS[String(state || "").toLowerCase()] || state || "未知";

export const blockingReasonLabel = reason =>
  BLOCKING_REASON_LABELS[String(reason || "").toLowerCase()] || reason || "未知原因";

export const edgeStateLabel = state =>
  EDGE_STATE_LABELS[String(state || "").toLowerCase()] || state || "未知";

export function desiredStatePersistencePresentation(graph) {
  const persistence = graph?.desiredStatePersistence || {};
  const generation = Number(persistence.generation) || 0;
  if (!persistence.enabled) return {
    tone: "disabled",
    title: "未启用",
    detail: "Runtime 重启时按进程配置恢复默认运行授权"
  };
  if (!persistence.healthy) return {
    tone: "degraded",
    title: persistence.integrityState === "primary-invalid"
      ? "主快照完整性异常"
      : persistence.integrityState === "previous-invalid"
        ? "恢复快照完整性异常" : "持久化异常",
    detail: `第 ${generation} 代 · 在线巡检 ${persistence.integrityState || "degraded"} · 新操作保持 fail-closed`
  };
  if (!persistence.leaseHeld) return {
    tone: "degraded",
    title: "未持有单写者租约",
    detail: `第 ${generation} 代 · 检查是否有另一 Runtime 共用状态文件`
  };
  if (persistence.recoveredFromPrevious || persistence.state === "recovered") return {
    tone: "recovered",
    title: "已从上一完整快照恢复",
    detail: `第 ${generation} 代 · ${persistence.previousAvailable ? "主/备份已验证" : "主快照已验证"} · 单写者租约已持有`
  };
  return {
    tone: "healthy",
    title: "状态已持久化",
    detail: `第 ${generation} 代 · ${persistence.previousAvailable ? "主/备份已验证" : "主快照已验证"} · 单写者租约已持有`
  };
}

const lifecycleActionLabel = action => ({
  start: "启动",
  stop: "停止",
  restart: "重启"
})[action] || action || "操作";

export function formatProcessLifecycleImpact(plan) {
  const lines = [
    `后端影响预检 · DAG 第 ${plan?.generation || 0} 代`,
    `目标：${lifecycleActionLabel(plan?.action)} ${plan?.target || "未知进程"}`
  ];
  if (plan?.prerequisites?.length)
    lines.push(`依赖前置：${plan.prerequisites.join(" → ")}`);
  if (plan?.affectedDependents?.length)
    lines.push(`受影响下游：${plan.affectedDependents.join("、")}`);
  if (plan?.stopOrder?.length)
    lines.push(`停止顺序：${plan.stopOrder.join(" → ")}`);
  if (plan?.startOrder?.length)
    lines.push(`启动/就绪顺序：${plan.startOrder.join(" → ")}`);
  lines.push("\n该计划是当前快照；提交后由 SubprocessManager 在锁内按实际 DAG 执行。");
  return lines.join("\n");
}

export function orderedDependencyNodes(graph) {
  const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
  const byName = new Map(nodes.map(node => [node.name || node.id, node]));
  const ordered = [];
  const consumed = new Set();
  for (const name of graph?.startupOrder || []) {
    const node = byName.get(name);
    if (node && !consumed.has(node)) {
      ordered.push(node);
      consumed.add(node);
    }
  }
  for (const node of nodes) {
    if (!consumed.has(node)) ordered.push(node);
  }
  return ordered;
}
