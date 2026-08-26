import React from "react";
import { AlertTriangle, ArrowRight, CheckCircle2, Database, GitBranch, Layers3 } from "lucide-react";
import {
  blockingReasonLabel,
  desiredStatePersistencePresentation,
  edgeStateLabel,
  orderedDependencyNodes,
  processStateLabel
} from "./process-dependency-model.js";

const list = value => Array.isArray(value) ? value : [];

function Sequence({ label, values, reverse = false }) {
  return <div className="dependency-sequence">
    <span>{label}</span>
    <ol className={reverse ? "reverse" : ""}>{list(values).map((name, index) =>
      <li key={`${name}-${index}`}><code>{name}</code>{index < values.length - 1 && <ArrowRight aria-hidden="true" />}</li>)}</ol>
  </div>;
}

export default function ProcessDependencyView({ graph, error = "" }) {
  const nodes = orderedDependencyNodes(graph);
  const edges = list(graph?.edges);
  const summary = graph?.summary || {};
  const persistence = desiredStatePersistencePresentation(graph);
  const integrityCheck = Number(
    graph?.desiredStatePersistence?.lastIntegrityCheckEpochMicroseconds) || 0;
  const integrityCheckedAt = integrityCheck > 0
    ? new Date(Math.floor(integrityCheck / 1000)).toISOString() : "";

  if (!graph && error) return <section className="surface dependency-unavailable" role="alert"
    data-process-dependency-view="unavailable">
    <AlertTriangle aria-hidden="true" />
    <div><h2>进程依赖数据暂不可用</h2><p>{error}。进程详情的其他功能不受影响，页面会自动重试。</p></div>
  </section>;

  return <section className="surface process-dependency-view" data-process-dependency-view="ready">
    <header className="section-head">
      <div><h2>受管进程依赖拓扑</h2><p>权威来源：Runtime Process · PID {graph?.runtimeProcessId || "—"} · 第 {graph?.generation || 0} 代快照</p></div>
      <span className="dependency-authority"><CheckCircle2 aria-hidden="true" />后端权威顺序</span>
    </header>

    {error && <p className="dependency-stale-warning" role="status"><AlertTriangle aria-hidden="true" />
      当前刷新失败，正在保留上一份快照：{error}</p>}

    <div className={`dependency-persistence persistence-${persistence.tone}`} role="status">
      <Database aria-hidden="true" />
      <span><b>进程期望状态</b><strong>{persistence.title}</strong><small>{persistence.detail}
        {integrityCheckedAt && <> · 巡检时间 <time dateTime={integrityCheckedAt}>
          {new Date(integrityCheckedAt).toLocaleString()}</time></>}</small></span>
    </div>

    <div className="dependency-summary" aria-label="进程依赖摘要">
      <article><span>已配置</span><strong>{summary.configured ?? nodes.length}</strong></article>
      <article className="running"><span>运行中</span><strong>{summary.running ?? 0}</strong></article>
      <article className="waiting"><span>等待依赖</span><strong>{summary.waiting ?? 0}</strong></article>
      <article className="blocked"><span>被阻塞</span><strong>{summary.blocked ?? 0}</strong></article>
    </div>

    {!nodes.length ? <div className="dependency-empty"><Layers3 aria-hidden="true" />
      <h3>当前没有配置受管子进程依赖</h3><p>Runtime 仍可运行；新增依赖后这里会按后端快照自动呈现。</p></div> : <>
      <div className="dependency-order-panel">
        <Sequence label="启动顺序" values={graph?.startupOrder} />
        <Sequence label="关闭顺序" values={graph?.shutdownOrder} reverse />
      </div>

      <ol className="dependency-node-grid" aria-label="按权威启动顺序排列的进程">
        {nodes.map((node, index) => {
          const blockers = list(node.blockedBy);
          const state = String(node.state || "unknown").toLowerCase();
          return <li className={`dependency-node state-${state}`} key={node.id || node.name}>
            <div className="dependency-node-head"><span className="dependency-order">{index + 1}</span>
              <div><h3>{node.name || node.id}</h3><p>{node.processId ? `PID ${node.processId}` : "尚未分配 PID"} ·
                {node.location === "remote" ? "远程" : "本地"} · {node.required ? "必需进程" : "可选进程"}</p></div>
              <span className={`dependency-state state-${state}`}>{processStateLabel(node.state)}</span>
            </div>
            <dl className="dependency-node-relations">
              <div><dt>依赖上游</dt><dd>{list(node.dependencies).length
                ? list(node.dependencies).map(name => <code key={name}>{name}</code>) : <span>无</span>}</dd></div>
              <div><dt>下游进程</dt><dd>{list(node.dependents).length
                ? list(node.dependents).map(name => <code key={name}>{name}</code>) : <span>无</span>}</dd></div>
            </dl>
            <div className={`dependency-readiness ${node.readyForDependents ? "ready" : "not-ready"}`}>
              {node.readyForDependents ? <CheckCircle2 aria-hidden="true" /> : <AlertTriangle aria-hidden="true" />}
              <span><b>{node.readyForDependents ? "可供下游启动" : "尚不可供下游启动"}</b>
                <small>期望状态：{node.desiredState === "running" ? "运行" : node.desiredState || "未知"}</small></span>
            </div>
            {blockers.length > 0 && <div className="dependency-blockers" role="status">
              <b>阻塞链</b>{blockers.map(blocker => <span key={`${blocker.name}-${blocker.reason}`}>
                <AlertTriangle aria-hidden="true" /><code>{blocker.name}</code> · {blockingReasonLabel(blocker.reason)}
                （{processStateLabel(blocker.state)}）</span>)}
            </div>}
          </li>;
        })}
      </ol>

      <div className="dependency-edge-panel">
        <h3><GitBranch aria-hidden="true" />依赖边明细</h3>
        <div className="dependency-edge-list" role="list">{edges.map((edge, index) =>
          <div className={`dependency-edge edge-${edge.state}`} role="listitem" key={`${edge.from}-${edge.to}-${index}`}>
            <code>{edge.from}</code><ArrowRight aria-hidden="true" /><code>{edge.to}</code>
            <span>{edgeStateLabel(edge.state)}</span><small>{blockingReasonLabel(edge.reason)}</small>
          </div>)}</div>
        {!edges.length && <p className="dependency-no-edges">节点之间没有依赖边。</p>}
      </div>
    </>}
  </section>;
}
