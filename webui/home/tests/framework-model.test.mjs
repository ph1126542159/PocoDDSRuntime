import assert from "node:assert/strict";
import {
  DEFAULT_FRAMEWORK_MODEL,
  loadFrameworkModel,
  navigationEnabled,
  normalizeFrameworkModel
} from "../src/framework-model.js";

const hybrid = normalizeFrameworkModel({
  schemaVersion: 1,
  framework: { family: "hybrid", model: "osp", profile: "custom", displayName: "Hybrid" },
  build: { legacyRuntime: true, roboticsRuntime: true, webui: true },
  transports: ["fastdds", "ros2"],
  transportResolution: { builtIn: ["fastdds"], externalAdapters: ["ros2"] },
  capabilities: {
    runtimeOverview: true,
    processManagement: true,
    businessTracing: true,
    robotics: true,
    roboticsSimulation: true,
    roboticsRos2: true
  },
  navigation: ["overview", "processes", "tracing"]
});
assert.equal(hybrid.source, "cmake");
assert.equal(hybrid.framework.family, "hybrid");
assert.deepEqual(hybrid.transports, ["fastdds", "ros2"]);
assert.equal(navigationEnabled(hybrid, { id: "tracing", capability: "businessTracing" }), true);
assert.equal(navigationEnabled(hybrid, { id: "metrics", capability: "metrics" }), false);

const robotics = normalizeFrameworkModel({
  schemaVersion: 1,
  framework: { family: "robotics", model: "robotics", profile: "robotics" },
  transportResolution: { builtIn: ["inproc"], externalAdapters: ["ros2"] },
  capabilities: { robotics: true, roboticsSimulation: true, roboticsRos2: true },
  navigation: ["robotics-overview", "robotics-missions", "robotics-traces"]
});
assert.equal(robotics.capabilities.runtimeOverview, false);
assert.equal(robotics.capabilities.robotics, true);

assert.throws(() => normalizeFrameworkModel({ schemaVersion: 9 }), /无效/);
const fallback = await loadFrameworkModel(async () => { throw new Error("offline"); });
assert.equal(fallback, DEFAULT_FRAMEWORK_MODEL);
console.log("PDR_WEBUI_FRAMEWORK_MODEL_PASS");
