const defaultCapabilities = {
  runtimeOverview: true,
  processManagement: true,
  deviceProtocols: true,
  bundleGovernance: true,
  metrics: true,
  runtimeGovernance: true,
  diagnosticTerminal: true,
  businessTracing: true,
  robotics: false,
  roboticsSimulation: false,
  roboticsRos2: false
};

export const DEFAULT_FRAMEWORK_MODEL = Object.freeze({
  schemaVersion: 1,
  framework: Object.freeze({
    family: "generic",
    model: "osp",
    profile: "legacy",
    displayName: "PocoDDS Runtime",
    version: "unknown"
  }),
  build: Object.freeze({ legacyRuntime: true, roboticsRuntime: false, webui: true }),
  transports: Object.freeze(["fastdds"]),
  transportResolution: Object.freeze({ builtIn: Object.freeze(["fastdds"]), externalAdapters: Object.freeze([]) }),
  capabilities: Object.freeze(defaultCapabilities),
  navigation: Object.freeze(["overview", "processes", "devices", "plugins", "metrics", "governance", "terminal", "tracing"]),
  source: "fallback"
});

const families = new Set(["generic", "robotics", "hybrid", "core"]);
const hostModels = new Set(["static", "desktop", "osp", "service", "robotics"]);

export function normalizeFrameworkModel(value) {
  if (!value || value.schemaVersion !== 1 || !families.has(value.framework?.family) ||
      !hostModels.has(value.framework?.model)) {
    throw new Error("无效的 CMake 框架模型清单");
  }
  const capabilities = Object.fromEntries(Object.keys(defaultCapabilities).map(key =>
    [key, Boolean(value.capabilities?.[key])]));
  const navigation = Array.isArray(value.navigation)
    ? [...new Set(value.navigation.filter(item => typeof item === "string" && item.length))]
    : [];
  if (!navigation.length) throw new Error("框架模型没有声明可用导航");
  return {
    ...value,
    framework: {
      ...value.framework,
      displayName: value.framework.displayName || "PocoDDS Runtime"
    },
    build: { ...(value.build || {}) },
    transports: Array.isArray(value.transports) ? value.transports.filter(item => typeof item === "string") : [],
    capabilities,
    navigation,
    source: "cmake"
  };
}

export async function loadFrameworkModel(fetchImpl = globalThis.fetch) {
  try {
    const response = await fetchImpl("./framework-model.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return normalizeFrameworkModel(await response.json());
  } catch (error) {
    console.warn(`CMake 框架模型加载失败，使用兼容模型：${error.message}`);
    return DEFAULT_FRAMEWORK_MODEL;
  }
}

export function navigationEnabled(model, route) {
  if (!model.navigation.includes(route.id)) return false;
  return !route.capability || Boolean(model.capabilities[route.capability]);
}
