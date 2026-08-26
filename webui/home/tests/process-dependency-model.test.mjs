import assert from "node:assert/strict";
import {
  blockingReasonLabel,
  desiredStatePersistencePresentation,
  edgeStateLabel,
  formatProcessLifecycleImpact,
  orderedDependencyNodes,
  processStateLabel
} from "../src/process-dependency-model.js";

const worker = { id: "worker", name: "worker", state: "waiting-dependency" };
const foundation = { id: "foundation", name: "foundation", state: "running" };
const observer = { id: "observer", name: "observer", state: "stopped" };
const sourceNodes = [worker, observer, foundation];
const ordered = orderedDependencyNodes({
  nodes: sourceNodes,
  startupOrder: ["foundation", "worker"]
});

assert.deepEqual(ordered.map(node => node.name), ["foundation", "worker", "observer"]);
assert.deepEqual(sourceNodes.map(node => node.name), ["worker", "observer", "foundation"]);
assert.equal(processStateLabel("waiting-dependency"), "等待依赖");
assert.equal(processStateLabel("vendor-state"), "vendor-state");
assert.equal(blockingReasonLabel("dependency-failed"), "上游失败");
assert.equal(edgeStateLabel("satisfied"), "已满足");
assert.equal(formatProcessLifecycleImpact({
  generation: 9,
  action: "restart",
  target: "foundation",
  affectedDependents: ["worker"],
  stopOrder: ["worker", "foundation"],
  startOrder: ["foundation", "worker"]
}), "后端影响预检 · DAG 第 9 代\n目标：重启 foundation\n受影响下游：worker\n停止顺序：worker → foundation\n启动/就绪顺序：foundation → worker\n\n该计划是当前快照；提交后由 SubprocessManager 在锁内按实际 DAG 执行。");
assert.deepEqual(orderedDependencyNodes(null), []);
assert.deepEqual(desiredStatePersistencePresentation(null), {
  tone: "disabled",
  title: "未启用",
  detail: "Runtime 重启时按进程配置恢复默认运行授权"
});
assert.deepEqual(desiredStatePersistencePresentation({
  desiredStatePersistence: {
    enabled: true, healthy: true, leaseHeld: true,
    recoveredFromPrevious: false, previousAvailable: false,
    generation: 4, state: "healthy", integrityState: "healthy"
  }
}), {
  tone: "healthy",
  title: "状态已持久化",
  detail: "第 4 代 · 主快照已验证 · 单写者租约已持有"
});
assert.equal(desiredStatePersistencePresentation({
  desiredStatePersistence: {
    enabled: true, healthy: true, leaseHeld: true,
    recoveredFromPrevious: true, generation: 5, state: "recovered"
  }
}).tone, "recovered");
assert.equal(desiredStatePersistencePresentation({
  desiredStatePersistence: {
    enabled: true, healthy: false, leaseHeld: true, generation: 6
  }
}).tone, "degraded");
assert.equal(desiredStatePersistencePresentation({
  desiredStatePersistence: {
    enabled: true, healthy: false, leaseHeld: true, generation: 7,
    integrityState: "primary-invalid"
  }
}).title, "主快照完整性异常");
assert.equal(desiredStatePersistencePresentation({
  desiredStatePersistence: {
    enabled: true, healthy: false, leaseHeld: true, generation: 8,
    integrityState: "previous-invalid"
  }
}).title, "恢复快照完整性异常");
assert.equal(desiredStatePersistencePresentation({
  desiredStatePersistence: {
    enabled: true, healthy: true, leaseHeld: false, generation: 6
  }
}).title, "未持有单写者租约");

console.log("PDR_WEBUI_PROCESS_DEPENDENCY_MODEL_PASS");
