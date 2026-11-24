const summaryStyleLabels = {
  general: "通用", course_notes: "课程笔记", academic: "学术", tutorial: "教程", sharing: "分享",
  task_oriented: "任务导向", business: "商业风格", meeting_minutes: "会议纪要",
};

const state = {
  activeJobId: null,
  activeContentId: null,
  activeJobTitle: null,
  activeContentSnapshot: null,
  activeSummaryVersionId: null,
  showingTrash: false,
  favoriteFolders: [],
  activeFavoriteFolderId: "",
  pollTimer: null,
  bilibiliQrTimer: null,
  bilibiliQrKey: null,
  bilibiliQrGeneration: 0,
  bilibiliQrPhase: "waiting",
  localAsrPollTimer: null,
  localAsrRuntimePollTimer: null,
  localAsrModels: {},
  localAsrRuntimeAvailable: undefined,
  settings: null,
  taskEvents: [],
  taskEventsJobId: null,
  taskEventsLastSequence: 0,
  taskEventsFetchedAt: 0,
  taskEventsLoadingJobId: null,
  taskEventsError: "",
  taskTimelineOpen: false,
  activeJobSnapshot: null,
  summaryDiscoveryTimer: null,
  summaryPromptSaveTimer: null,
  summaryPromptSaveSequence: 0,
  summaryPromptDraft: null,
  summaryPromptSaveStatus: "saved",
  summaryPromptSaveError: "",
  asrConnection: {
    status: "unconfigured",
    models: [],
    modelsSupported: null,
    generation: 0,
    discoveryFingerprint: "",
    testFingerprint: "",
  },
  asrSavedIdentity: null,
  asrCopySummaryKeyOnSave: false,
  asrModelActiveIndex: -1,
  summaryConnection: {
    status: "unconfigured",
    models: [],
    generation: 0,
    discoveryFingerprint: "",
    testFingerprint: "",
    validationToken: null,
  },
  summarySavedIdentity: null,
  summaryFormLock: null,
  summaryModelActiveIndex: -1,
  summaryModelPage: 0,
  summaryModelPullGesture: null,
  summaryModelSuppressClickUntil: 0,
  noticeTimer: null,
  sourceProbeTimer: null,
  sourceProbe: null,
  linkQuery: null,
  linkQueryRequestId: 0,
  linkQuerySelectedIds: new Set(),
  linkQueryPollTimer: null,
  collectionImportContext: null,
  contentCategories: [],
  tags: [],
  activeTagId: "",
  activeTagName: "",
  libraryEntries: [],
  libraryPageSize: 50,
  libraryHasMore: false,
  libraryLoading: false,
  libraryPendingHistoryRequest: null,
  libraryHistoryRequestSequence: 0,
  libraryPageStart: 0,
  libraryGridObserver: null,
  libraryMenu: null,
  favoriteAddContext: null,
  favoriteAddBatch: null,
  favoriteAddAssociationFailures: [],
  favoriteAddFailedLinks: [],
  favoriteAddChoices: [],
  favoriteAddSelectedIds: new Set(),
  introductionBackfillId: null,
  introductionBackfillTimer: null,
  returnContext: null,
  resultSequence: [],
  resultIndex: -1,
  resultIntroductionDirty: false,
  activeImportBatchId: null,
  batchReturnContext: null,
  batchReport: null,
  batchJobIds: [],
  batchPollTimer: null,
  creatorScanId: null,
  creatorScanRequestId: 0,
  creatorScanTimer: null,
  creatorScan: null,
  creatorScanSourceType: null,
  pendingCollectionScan: null,
  creatorSelectedIds: new Set(),
  creatorFilterQuery: "",
  creatorFilterStatus: "all",
  bilibiliFavoriteBrowser: false,
  bilibiliFavoriteFolders: [],
  bilibiliFavoriteFolderId: null,
  autoScannedQueryIds: new Set(),
  localQuery: null,
  settingsReturnNeedsQuery: null,
  localFileName: "",
  taskEntries: [],
  taskFilter: "all",
  taskSelectionMode: false,
  taskEditing: false,
  taskSelectedIds: new Set(),
  taskBatchBusy: false,
  taskDragJobId: null,
  taskExpandedJobId: null,
  taskSwitching: false,
  taskListRequest: null,
  taskListRequestSequence: 0,
  taskPollRequest: null,
  taskPollRequestSequence: 0,
  taskStats: null,
  tagManagementMode: false,
  tagRenamingId: null,
  favoriteManagementMode: false,
  favoriteRenamingId: null,
  settingsSection: "platform",
  settingsScrollTops: {},
  settingsReturnView: null,
  currentView: "intake",
  intakeMode: "link",
  apiContractStatus: "pending",
  apiContractVersion: null,
  ask: {
    settings: null,
    sessions: [],
    sessionId: null,
    session: null,
    queryId: null,
    pollTimer: null,
    contentOptions: [],
    tags: [],
    folders: [],
    loaded: false,
  },
};

const API_ORIGIN = window.location.protocol === "file:" ? "http://127.0.0.1:8765" : "";
// Keep this mirror synchronized with app.meta.API_CONTRACT_VERSION. The
// contract-version test parses this value so a release cannot silently ship a
// frontend that expects a different backend.
const FRONTEND_API_CONTRACT_VERSION = "2026-09-15.2";
const CONTRACT_MISMATCH_MESSAGE = "运行服务版本过旧，请重启产品";

function createIcon(name, className = "icon-control") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.classList.add(className);
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#icon-${name}`);
  svg.append(use);
  return svg;
}

function setIconLabel(element, iconName, label, { iconFirst = true } = {}) {
  if (!element) return;
  const icon = createIcon(iconName);
  const text = document.createTextNode(label);
  element.replaceChildren(...(iconFirst ? [icon, text] : [text, icon]));
}

const views = [...document.querySelectorAll(".view")];
const navButtons = [...document.querySelectorAll("[data-view-target]")];
const notice = document.querySelector("#notice");
const intakeModeTabs = document.querySelector("#intake-mode-tabs");
const intakeModeButtons = [...(intakeModeTabs?.querySelectorAll("[data-intake-mode]") || [])];
const settingsContent = document.querySelector("#settings-content");
const settingsReturnButton = document.querySelector("#settings-return");
const jobPanel = document.querySelector("#job-panel");
const jobFocusPanel = document.querySelector("#job-focus-panel");
const historyPanel = document.querySelector("#history-panel");
const settingsPanel = document.querySelector("#settings-panel");
const bilibiliQrPanel = document.querySelector("#bilibili-qr-panel");
const asrModelDialog = document.querySelector("#asr-local-model-dialog");
const linkQueryDialog = document.querySelector("#link-query-dialog");
const textEntryDialog = document.querySelector("#text-entry-dialog");
const taskSuccessDialog = document.querySelector("#task-success-dialog");
const sourceProbePanel = document.querySelector("#source-probe");
const navAskButton = document.querySelector("#nav-ask");
const batchPanel = document.querySelector("#batch-panel");
const intakeTaskStatusPanel = document.querySelector("#intake-task-status");
const sourceCapabilitiesPanel = document.querySelector("#source-capabilities");
const queryLocalButton = document.querySelector("#query-local");
const askSessionList = document.querySelector("#ask-session-list");
const askMessages = document.querySelector("#ask-messages");
const askQueryStatus = document.querySelector("#ask-query-status");
const localDropzone = document.querySelector("#local-dropzone");
const taskFilterButtons = [...document.querySelectorAll("[data-task-filter]")];
const taskListSummary = document.querySelector("#task-list-summary");
const settingsSubnavButtons = [...document.querySelectorAll("[data-settings-target]")];
const ASR_PROVIDER_PRESETS = {
  custom: {
    endpoint: "",
    hint: "自定义服务商：填写服务商提供的完整 audio/transcriptions 接口地址和模型名。",
  },
  groq: {
    endpoint: "https://api.groq.com/openai/v1/audio/transcriptions",
    hint: "Groq Whisper：速度快、有免费额度；接口已自动填入，请获取或手动填写账户支持的 ASR 模型。",
  },
  openai: {
    endpoint: "https://api.openai.com/v1/audio/transcriptions",
    hint: "OpenAI 官方转写：接口已自动填入，请获取或手动填写账户支持的 ASR 模型。",
  },
  siliconflow: {
    endpoint: "https://api.siliconflow.cn/v1/audio/transcriptions",
    hint: "硅基流动：国内访问稳定；已填入兼容端点，请按账户支持的模型填写模型名。",
  },
  zhipu: {
    endpoint: "https://open.bigmodel.cn/api/paas/v4/audio/transcriptions",
    hint: "智谱 BigModel：国内访问稳定；已填入兼容端点，请按服务商文档确认接口和模型。",
  },
  deepseek: {
    endpoint: "",
    hint: "DeepSeek 服务商标识已复制；请填写其提供的 ASR 转写接口地址。",
  },
  minimax: {
    endpoint: "",
    hint: "MiniMax 服务商标识已复制；请填写其提供的 ASR 转写接口地址。",
  },
  qwen: {
    endpoint: "",
    hint: "Qwen 服务商标识已复制；请填写其提供的 ASR 转写接口地址。",
  },
  doubao: {
    endpoint: "",
    hint: "豆包服务商标识已复制；请填写其提供的 ASR 转写接口地址。",
  },
  hunyuan: {
    endpoint: "",
    hint: "混元服务商标识已复制；请填写其提供的 ASR 转写接口地址。",
  },
  glm: {
    endpoint: "",
    hint: "GLM 服务商标识已复制；请填写其提供的 ASR 转写接口地址。",
  },
  grok: {
    endpoint: "",
    hint: "Grok 服务商标识已复制；请填写其提供的 ASR 转写接口地址。",
  },
};

const SUMMARY_MODEL_INLINE_LIMIT = 10;
const SUMMARY_MODEL_PAGE_SIZE = 10;
const SUMMARY_MODEL_PULL_REFRESH_THRESHOLD = 56;
const SUMMARY_MODEL_CATALOG_STORAGE_KEY = "content-knowledge-summary-model-catalog";

const SUMMARY_PROVIDER_PRESETS = {
  custom: {
    endpoint: "",
    model: "",
  },
  openai: {
    endpoint: "https://api.openai.com/v1",
    model: "",
  },
  deepseek: {
    endpoint: "https://api.deepseek.com",
    model: "",
  },
  minimax: {
    endpoint: "https://api.minimaxi.com/v1",
    model: "",
  },
  qwen: {
    endpoint: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    model: "",
  },
  doubao: {
    endpoint: "https://ark.cn-beijing.volces.com/api/v3",
    model: "",
  },
  hunyuan: {
    endpoint: "https://api.hunyuan.cloud.tencent.com/v1",
    model: "",
  },
  glm: {
    endpoint: "https://open.bigmodel.cn/api/paas/v4",
    model: "",
  },
  grok: {
    endpoint: "https://api.x.ai/v1",
    model: "",
  },
};

const SUMMARY_PROVIDER_ALIASES = {
  "openai-compatible": "openai",
  builtin: "openai",
  openai: "openai",
  deepseek: "deepseek",
  minimax: "minimax",
  qwen: "qwen",
  tongyi: "qwen",
  doubao: "doubao",
  volcengine: "doubao",
  ark: "doubao",
  hunyuan: "hunyuan",
  tencent: "hunyuan",
  glm: "glm",
  zhipu: "glm",
  grok: "grok",
  xai: "grok",
  cloud: "custom",
  crooks: "custom",
  custom: "custom",
};

function showSummaryValidation(message) {
  const panel = document.querySelector("#summary-validation");
  if (!panel) return;
  panel.textContent = message || "";
  panel.hidden = !message;
}

function renderSummaryStatus(settings, isDraft = false) {
  const status = document.querySelector("#summary-status");
  const badge = document.querySelector("#summary-config-badge");
  const connectionStatus = state.summaryConnection?.status || "unconfigured";
  const savedConfigured = Boolean(settings?.summary_configured);
  const draftConfigured = ["verified", "saved"].includes(connectionStatus);
  const configured = savedConfigured || draftConfigured;
  const labels = {
    unconfigured: ["外部未配置", "未配置"],
    editing: ["配置已修改", "待识别"],
    discovering: ["正在连接", "识别中"],
    awaiting_model: ["接口已连接", "请选择模型"],
    model_selected: ["模型待验证", "待验证"],
    verifying: ["正在验证", "验证中"],
    verified: ["接口已验证", "已验证"],
    saved: ["外部已配置", "已保存"],
    input_invalid: ["外部 API 配置不完整", "配置不完整"],
    discovery_failed: ["总结模型列表获取失败", "模型列表获取失败"],
    validation_failed: ["总结模型连接验证失败", "模型连接验证失败"],
    save_failed: ["总结 API 配置保存失败", "API 配置保存失败"],
  };
  const [draftStatusLabel, draftBadgeLabel] = labels[connectionStatus] || labels.editing;
  // Keep the running/saved configuration visible while the user edits a
  // separate draft.  Only the compact badge reflects discovery/validation
  // state, so a changed field cannot make the saved configuration look dead.
  const statusLabel = savedConfigured ? labels.saved[0] : (isDraft ? draftStatusLabel : labels.unconfigured[0]);
  const badgeLabel = isDraft ? draftBadgeLabel : (savedConfigured ? labels.saved[1] : draftBadgeLabel);
  if (status) {
    status.textContent = statusLabel;
    status.className = "asr-status-badge" + (configured ? " is-ready" : "");
  }
  if (badge) {
    badge.textContent = badgeLabel;
    badge.className = "asr-config-badge" + (configured ? " is-ready" : "");
  }
  const dot = document.querySelector("#summary-config-dot");
  if (dot) {
    dot.className = "summary-status-dot" + (configured ? " is-ready" : "");
    dot.title = configured ? "总结接口已验证" : "总结接口尚未验证";
  }
}

function renderSummarySkills(settings) {
  const select = document.querySelector("#summary-skill");
  const meta = document.querySelector("#summary-skill-meta");
  if (!select || !meta) return;
  select.replaceChildren();
  const empty = document.createElement("option");
  empty.value = "";
  empty.textContent = "不使用 Skill 文件";
  select.append(empty);
  (settings.summary_skill_options || []).forEach((item) => {
    const option = document.createElement("option");
    option.value = item.path;
    option.textContent = item.name + " · " + item.path;
    select.append(option);
  });
  select.value = settings.summary_skill_path || "";
  const rootLabel = settings.summary_skills_root
    ? "存储目录：" + settings.summary_skills_root + " · "
    : "";
  if (settings.summary_skill_error) {
    meta.textContent = rootLabel + settings.summary_skill_error + "；请重新选择可用 Skill。";
  } else if (settings.summary_skill_path) {
    meta.textContent = rootLabel + [
      settings.summary_skill_name || settings.summary_skill_path,
      settings.summary_skill_path,
      settings.summary_skill_hash ? "SHA-256 " + settings.summary_skill_hash.slice(0, 12) : null,
    ].filter(Boolean).join(" · ");
  } else {
    meta.textContent = rootLabel + "未选择 Skill；Skill 只提供总结规则，不作为视频事实来源。";
  }
}

function renderSummaryPromptMeta(settings, isDraft = state.summaryPromptDraft !== null) {
  const meta = document.querySelector("#summary-prompt-meta");
  const hint = document.querySelector("#summary-prompt-hint");
  if (!meta || !hint) return;
  const configured = Boolean(settings?.summary_prompt_configured);
  const modified = configured || isDraft;
  meta.textContent = modified ? "已修改" : "内置 Prompt";
  meta.className = "asr-config-badge" + (configured && !isDraft ? " is-ready" : "");
  const dot = document.querySelector("#summary-prompt-dot");
  if (dot) {
    dot.className = "summary-status-dot" + (modified ? " is-ready" : "");
    dot.title = modified ? "总结 Prompt 已修改" : "总结 Prompt 使用内置内容";
  }
  const saveStatus = document.querySelector("#summary-prompt-save-status");
  const retryButton = document.querySelector("#retry-summary-prompt");
  const saveLabels = {
    saving: "正在保存",
    saved: "已保存",
    failed: "保存失败",
  };
  const saveState = state.summaryPromptSaveStatus || "saved";
  if (saveStatus) {
    saveStatus.textContent = saveLabels[saveState] || saveLabels.saved;
    saveStatus.className = `asr-config-badge summary-prompt-save-status is-${saveState}`;
    saveStatus.title = saveState === "failed" ? state.summaryPromptSaveError : "";
  }
  if (retryButton) retryButton.hidden = saveState !== "failed";
  hint.textContent = saveState === "saving"
    ? "正在保存 Prompt…"
    : saveState === "failed"
      ? `保存失败：${state.summaryPromptSaveError || "请求未完成"}；请再次修改或点击重试。`
      : (modified ? "Prompt 已自动保存。" : "当前使用产品内置 Prompt。");
}

function normalizeSummaryProvider(provider) {
  return SUMMARY_PROVIDER_ALIASES[String(provider || "").trim().toLowerCase()] || "custom";
}

function normalizeSummaryUrl(url) {
  return String(url || "").trim().replace(/\/+$/, "").toLowerCase();
}

function summaryApiModeForEndpoint(endpoint, fallback = "chat_completions") {
  try {
    const path = new URL(endpoint).pathname.replace(/\/+$/, "").toLowerCase();
    if (path.endsWith("/responses")) return "responses";
    if (path.endsWith("/chat/completions")) return "chat_completions";
  } catch (_error) {
    return fallback;
  }
  return ["chat_completions", "responses"].includes(fallback) ? fallback : "chat_completions";
}

function summaryBaseUrlForIdentity(url) {
  return normalizeSummaryUrl(url).replace(/\/(chat\/completions|responses)$/, "");
}

function currentSummaryIdentity() {
  return {
    provider: normalizeSummaryProvider(document.querySelector("#summary-provider")?.value),
    endpoint: summaryBaseUrlForIdentity(document.querySelector("#summary-api-url")?.value),
    mode: document.querySelector("#summary-api-mode")?.value || "chat_completions",
  };
}

function summaryIdentityMatchesSaved() {
  const saved = state.summarySavedIdentity;
  const current = currentSummaryIdentity();
  return Boolean(
    saved
    && saved.provider === current.provider
    && saved.endpoint === current.endpoint,
  );
}

function summaryApiKeyAvailable() {
  const entered = document.querySelector("#summary-api-key")?.value.trim() || "";
  if (entered) return true;
  return Boolean(state.settings?.summary_api_key_configured && summaryIdentityMatchesSaved());
}

function applySummaryProviderPreset(event) {
  const provider = normalizeSummaryProvider(event.target.value);
  const urlField = document.querySelector("#summary-api-url");
  const currentUrl = urlField?.value.trim() || "";
  // A provider switch only fills an empty URL; a non-empty URL stays user-owned.
  if (provider !== "custom" && !currentUrl) {
    urlField.value = SUMMARY_PROVIDER_PRESETS[provider]?.endpoint || "";
  }
  showSummaryValidation("");
  invalidateSummaryConnection();
  scheduleSummaryModelDiscovery();
}

const ASR_PROVIDER_ALIASES = {
  "openai-compatible": "openai",
  builtin: "openai",
  openai: "openai",
  groq: "groq",
  deepseek: "deepseek",
  minimax: "minimax",
  qwen: "qwen",
  tongyi: "qwen",
  doubao: "doubao",
  volcengine: "doubao",
  ark: "doubao",
  hunyuan: "hunyuan",
  tencent: "hunyuan",
  glm: "glm",
  zhipu: "zhipu",
  siliconflow: "siliconflow",
  grok: "grok",
  xai: "grok",
  custom: "custom",
};

function normalizeAsrProvider(provider) {
  const normalized = String(provider || "").trim().toLowerCase();
  return ASR_PROVIDER_ALIASES[normalized] || "custom";
}

function asrProviderForEndpoint(endpoint) {
  const normalized = String(endpoint || "").trim().replace(/\/+$/, "");
  return Object.entries(ASR_PROVIDER_PRESETS).find(([, preset]) => {
    return preset.endpoint && preset.endpoint.replace(/\/+$/, "") === normalized;
  })?.[0] || "custom";
}

function normalizeAsrUrl(url) {
  return String(url || "").trim().replace(/\/+$/, "").toLowerCase();
}

function asrBaseUrlForIdentity(url) {
  return normalizeAsrUrl(url).replace(/\/(audio\/transcriptions|chat\/completions|responses)$/, "");
}

function currentAsrIdentity() {
  return {
    provider: normalizeAsrProvider(document.querySelector("#asr-provider")?.value),
    endpoint: asrBaseUrlForIdentity(document.querySelector("#asr-api-url")?.value),
  };
}

function asrIdentityMatchesSaved() {
  const saved = state.asrSavedIdentity;
  const current = currentAsrIdentity();
  return Boolean(saved && saved.provider === current.provider && saved.endpoint === current.endpoint);
}

function asrSavedKeyAvailable() {
  return Boolean(state.settings?.asr_cloud_configured && asrIdentityMatchesSaved());
}

function asrRequestKey() {
  const entered = document.querySelector("#asr-api-key")?.value.trim() || "";
  return entered || null;
}

function asrConnectionPayload(includeModel = false) {
  const provider = normalizeAsrProvider(document.querySelector("#asr-provider")?.value);
  const payload = {
    provider,
    asr_provider: provider,
    asr_api_url: document.querySelector("#asr-api-url")?.value.trim() || null,
    asr_api_key: asrRequestKey(),
  };
  if (includeModel) {
    payload.asr_model = document.querySelector("#asr-model")?.value.trim() || null;
  }
  return payload;
}

function asrDiscoveryFingerprint() {
  const key = asrRequestKey();
  return JSON.stringify({
    ...currentAsrIdentity(),
    url: normalizeAsrUrl(document.querySelector("#asr-api-url")?.value),
    key: key || (asrSavedKeyAvailable() ? "<saved-key>" : (state.asrCopySummaryKeyOnSave ? "<copy-summary-key>" : "")),
  });
}

function setAsrModelPickerOpen(open) {
  const input = document.querySelector("#asr-model");
  const toggle = document.querySelector("#asr-model-toggle");
  const options = document.querySelector("#asr-model-options");
  if (!input || !toggle || !options) return;
  const visible = Boolean(open && state.asrConnection.models.length);
  options.hidden = !visible;
  input.setAttribute("aria-expanded", String(visible));
  toggle.setAttribute("aria-expanded", String(visible));
}

function renderAsrModelOptions(models = state.asrConnection.models) {
  const options = document.querySelector("#asr-model-options");
  if (!options) return;
  const query = document.querySelector("#asr-model")?.value.trim().toLowerCase() || "";
  const filtered = (models || []).filter((model) => !query || String(model).toLowerCase().includes(query));
  options.replaceChildren();
  state.asrModelActiveIndex = -1;
  if (!filtered.length) {
    const empty = document.createElement("div");
    empty.className = "asr-model-empty";
    empty.textContent = models?.length ? "没有匹配的模型，可手动填写模型 ID。" : "获取模型后将在这里显示 ASR 模型。";
    options.append(empty);
    setAsrModelPickerOpen(false);
    return;
  }
  filtered.forEach((model, index) => {
    const option = document.createElement("button");
    option.className = "asr-model-option";
    option.type = "button";
    option.dataset.model = String(model);
    option.id = `asr-model-option-${index}`;
    option.textContent = String(model);
    options.append(option);
  });
}

function selectAsrModel(model) {
  const input = document.querySelector("#asr-model");
  if (!input) return;
  input.value = String(model || "");
  setAsrModelPickerOpen(false);
  handleAsrModelChange();
}

function handleAsrModelInput() {
  renderAsrModelOptions();
  setAsrModelPickerOpen(true);
  handleAsrModelChange();
}

function handleAsrModelChange() {
  state.asrConnection.status = document.querySelector("#asr-model")?.value.trim()
    ? "model_selected"
    : "awaiting_model";
  state.asrConnection.testFingerprint = "";
  updateAsrSettingsSummary(true);
}

function handleAsrModelKeydown(event) {
  const options = document.querySelector("#asr-model-options");
  const items = [...(options?.querySelectorAll(".asr-model-option") || [])];
  if (!items.length || options?.hidden) return;
  if (event.key === "ArrowDown") {
    event.preventDefault();
    state.asrModelActiveIndex = Math.min(state.asrModelActiveIndex + 1, items.length - 1);
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    state.asrModelActiveIndex = Math.max(state.asrModelActiveIndex - 1, 0);
  } else if (event.key === "Enter" && state.asrModelActiveIndex >= 0) {
    event.preventDefault();
    selectAsrModel(items[state.asrModelActiveIndex].dataset.model);
    return;
  } else if (event.key === "Escape") {
    setAsrModelPickerOpen(false);
    return;
  } else {
    return;
  }
  items.forEach((item, index) => item.classList.toggle("is-active", index === state.asrModelActiveIndex));
}

function invalidateAsrConnection() {
  state.asrConnection.generation += 1;
  state.asrConnection.status = "editing";
  state.asrConnection.models = [];
  state.asrConnection.modelsSupported = null;
  state.asrConnection.discoveryFingerprint = "";
  state.asrConnection.testFingerprint = "";
  renderAsrModelOptions([]);
  setAsrModelPickerOpen(false);
  renderAsrModelAvailability();
}

// 参考语音输入模块的做法：引擎选项直接暴露未配置/不可用状态，避免用户选了才发现不能用。
// localRuntimeAvailable 为 undefined 时表示尚未探测本地组件，不附加后缀。
function renderAsrEngineLabels(asrConfigured, engine, localRuntimeAvailable) {
  const cloudOption = document.querySelector('#asr-engine option[value="cloud"]');
  const localOption = document.querySelector('#asr-engine option[value="local"]');
  const cloudReady = state.settings ? Boolean(state.settings.asr_cloud_configured) : asrConfigured && engine !== "local";
  if (cloudOption) {
    cloudOption.textContent = "云端 API" + (cloudReady ? "（已配置）" : "（未配置）");
  }
  if (localOption) {
    localOption.textContent = localRuntimeAvailable === undefined
      ? "本地模型（离线）"
      : "本地模型（离线" + (localRuntimeAvailable ? " · 组件就绪）" : " · 组件未装）");
  }
}

function renderAsrModelAvailability() {
  const field = document.querySelector("#asr-model-field");
  const input = document.querySelector("#asr-model");
  const hint = document.querySelector("#asr-model-prerequisite");
  const engine = document.querySelector("#asr-engine")?.value;
  if (!field || !input || !hint) return;
  input.setAttribute("aria-describedby", "asr-model-prerequisite");
  if (engine !== "cloud") {
    input.disabled = false;
    field.classList.remove("is-disabled");
    hint.hidden = true;
    hint.textContent = "";
    return;
  }
  const endpoint = document.querySelector("#asr-api-url")?.value.trim() || "";
  let endpointReady = false;
  try {
    const parsed = new URL(endpoint);
    endpointReady = ["http:", "https:"].includes(parsed.protocol) && Boolean(parsed.hostname);
  } catch (_error) {
    endpointReady = false;
  }
  const keyInput = document.querySelector("#asr-api-key")?.value.trim() || "";
  const keyReady = Boolean(keyInput) || asrSavedKeyAvailable() || state.asrCopySummaryKeyOnSave;
  // Manual model IDs are always allowed.  Discovery is helpful but not a
  // prerequisite, because some ASR services do not expose /models.
  input.disabled = false;
  field.classList.remove("is-disabled");
  field.setAttribute("aria-disabled", "false");
  hint.hidden = endpointReady && keyReady && state.asrConnection.modelsSupported !== false;
  if (endpointReady && keyReady && state.asrConnection.modelsSupported !== false) {
    hint.textContent = "";
  } else if (!endpointReady) {
    hint.textContent = "先填写有效的 ASR 接口地址。";
  } else if (!keyReady) {
    hint.textContent = "先填写 ASR API Key；已保存密钥不会回显。也可以手动填写模型 ID。";
  } else if (state.asrConnection.modelsSupported === false) {
    hint.textContent = "当前接口不支持模型列表查询，请手动填写 ASR 模型 ID。";
  } else {
    hint.textContent = "模型列表尚未获取，可先手动填写 ASR 模型 ID。";
  }
}
function renderAsrProviderHint(provider) {
  const hint = document.querySelector("#asr-provider-hint");
  const preset = ASR_PROVIDER_PRESETS[provider] || ASR_PROVIDER_PRESETS.custom;
  if (hint) {
    hint.textContent = preset.hint;
  }
}

function renderAsrStatus(configured, engine = "cloud") {
  const status = document.querySelector("#asr-status");
  const badge = document.querySelector("#asr-config-badge");
  if (status) {
    status.textContent = configured ? (engine === "local" ? "本地已就绪" : "已配置") : "未配置";
    status.className = "asr-status-badge" + (configured ? " is-ready" : "");
  }
  if (badge) {
    setIconLabel(
      badge,
      configured ? "check" : "error",
      configured ? (engine === "local" ? "本地 ASR " : "云 ASR ") : "ASR ",
    );
    badge.className = "asr-config-badge" + (configured ? " is-ready" : "");
  }
}

function showAsrValidation(message) {
  const panel = document.querySelector("#asr-validation");
  if (!panel) {
    return;
  }
  panel.textContent = message || "";
  panel.hidden = !message;
}

function updateAsrSettingsSummary(isDraft = false) {
  if (!state.settings) return;
  const definition = [...settingsPanel.querySelectorAll("dt")]
    .find((item) => item.textContent === "公开 ASR")?.nextElementSibling;
  if (!definition) return;
  const engine = document.querySelector("#asr-engine").value;
  const model = engine === "local"
    ? document.querySelector("#asr-local-model").value
    : document.querySelector("#asr-model").value;
  const configured = engine === "local"
    ? Boolean(state.localAsrModels[model]?.installed && state.localAsrRuntimeAvailable)
    : Boolean(state.settings.asr_cloud_configured);
  const preview = configured
    ? (engine === "local" ? "本地模型（" + model + "）" : "云端 ASR（" + model + "）")
    : (engine === "local" ? "本地 ASR 未就绪" : "云端 ASR 未配置");
  const active = state.settings.asr_configured
    ? (state.settings.asr_engine === "local" ? "本地模型（" + state.settings.asr_local_model + "）" : "云端 ASR（" + state.settings.asr_cloud_model + "）")
    : "未配置";
  definition.textContent = "当前生效：" + active + (isDraft ? "；配置预览：" + preview + "（未保存）" : "");
}

function renderAsrEngine(engine) {
  const local = engine === "local";
  document.querySelector("#asr-provider-field").hidden = local;
  document.querySelector("#asr-model-field").hidden = local;
  document.querySelector("#test-asr").hidden = local;
  document.querySelector("#asr-api-details").hidden = local;
  document.querySelector("#asr-api-help").hidden = local;
  document.querySelector("#asr-local-panel").hidden = !local;
  renderAsrModelAvailability();
}

function localAsrModelReady(item) {
  return Boolean(item?.model_ready || (item?.installed && item?.validation_status === "ready"));
}

function localAsrStatusLabel(item) {
  if (item.status === "downloading") {
    return `下载中 ${item.progress || 0}%`;
  }
  if (item.status === "validating") {
    return "校验中…";
  }
  if (item.status === "error") {
    return "下载/校验失败";
  }
  if (item.validation_status === "corrupt") {
    return "文件损坏";
  }
  if (localAsrModelReady(item)) {
    if (item.status === "reused") {
      return "已复用";
    }
    if (item.status === "imported") {
      return "已导入";
    }
    if (!state.localAsrRuntimeAvailable) {
      return "模型文件已就绪（待安装组件）";
    }
    return "可用于本地 ASR";
  }
  if (item.validation_status === "incomplete") {
    return "文件不完整";
  }
  if (item.installed) {
    return "已安装但未通过校验";
  }
  return "未下载";
}

function renderLocalAsrModels(payload) {
  const select = document.querySelector("#asr-local-model");
  const downloadSelect = document.querySelector("#asr-local-download-model");
  const list = document.querySelector("#asr-local-model-list");
  const runtimeStatus = document.querySelector("#asr-local-runtime-status");
  const runtimeInstallButton = document.querySelector("#install-asr-runtime");
  const runtimeInstallHint = document.querySelector("#asr-local-runtime-install-status");
  const countBadge = document.querySelector("#asr-local-count");
  const installedBadge = document.querySelector("#asr-local-installed-badge");
  const selectedModel = select.dataset.selectedModel || select.value;
  state.localAsrModels = Object.fromEntries(payload.models.map((item) => [item.id, item]));
  state.localAsrRuntimeAvailable = payload.runtime_available;

  const runtimeInstalling = Boolean(payload.runtime_installing);
  runtimeStatus.textContent = payload.runtime_available
    ? "本地组件已安装"
    : runtimeInstalling
      ? "本地组件安装中…"
      : "本地组件未安装";
  runtimeStatus.className =
    "asr-local-runtime-status" + (payload.runtime_available ? " is-ready" : "");
  if (runtimeInstallButton) {
    runtimeInstallButton.hidden = payload.runtime_available;
    runtimeInstallButton.disabled = runtimeInstalling;
    runtimeInstallButton.textContent = runtimeInstalling ? "正在安装…" : "安装缺失组件";
  }
  if (runtimeInstallHint) {
    runtimeInstallHint.textContent = payload.runtime_install_error
      || (runtimeInstalling
        ? `${payload.runtime_install_message || "正在下载并安装本地 ASR 组件"} ${payload.runtime_install_progress || 0}%`
        : payload.runtime_available
          ? "模型文件和运行组件状态已分开显示；扫描或下载完成的模型可直接选择。"
          : "模型文件可以先扫描和导入；要执行语音识别，请安装本地运行组件。");
  }
  renderAsrEngineLabels(
    document.querySelector("#asr-form").dataset.asrConfigured === "true",
    document.querySelector("#asr-engine").value,
    payload.runtime_available,
  );

  const installedModels = payload.models.filter(localAsrModelReady);
  const installedCount = installedModels.length;
  countBadge.hidden = false;
  countBadge.textContent = `模型文件已就绪 ${installedCount}/${payload.models.length}`;
  countBadge.className =
    "asr-local-runtime-status" + (installedCount > 0 ? " is-ready" : "");

  select.replaceChildren();
  const readyModel = selectedModel && localAsrModelReady(state.localAsrModels[selectedModel])
    ? selectedModel
    : "";
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = installedCount
    ? "选择已扫描或下载的本地模型"
    : "暂无完整模型，请先扫描或下载";
  select.append(placeholder);

  payload.models.forEach((item) => {
    const modelReady = localAsrModelReady(item);
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = item.label + " · " + item.size + (
      modelReady
        ? (payload.runtime_available ? " · 可用" : " · 模型已就绪")
        : " · " + localAsrStatusLabel(item)
    );
    option.disabled = !modelReady;
    select.append(option);
  });
  select.value = readyModel;
  if (installedBadge) {
    installedBadge.textContent = readyModel
      ? (payload.runtime_available ? "可用于识别" : "模型已就绪")
      : "未选择";
    installedBadge.className =
      "asr-config-badge" + (readyModel && payload.runtime_available ? " is-ready" : "");
  }
  const selectedStatus = document.querySelector("#asr-local-model-status");
  if (selectedStatus) {
    selectedStatus.textContent = readyModel
      ? (payload.runtime_available
        ? `${state.localAsrModels[readyModel].label} 已就绪，可保存为本地 ASR`
        : `${state.localAsrModels[readyModel].label} 模型文件已就绪；安装运行组件后即可识别`)
      : "扫描或下载完成后，模型会出现在这里并自动选中。";
  }

  if (downloadSelect) {
    downloadSelect.replaceChildren();
    const downloadPlaceholder = document.createElement("option");
    downloadPlaceholder.value = "";
    downloadPlaceholder.textContent = payload.runtime_available
      ? "选择要下载的公开模型"
      : "请先安装本地组件后下载";
    downloadSelect.append(downloadPlaceholder);
    payload.models.forEach((item) => {
      const option = document.createElement("option");
      option.value = item.id;
      option.textContent = item.label + " · " + item.size
        + (item.installed ? " · 已安装" : "");
      option.disabled = localAsrModelReady(item)
        || ["downloading", "validating"].includes(item.status)
        || !payload.runtime_available
        || !item.repo_id;
      downloadSelect.append(option);
    });
  }

  list.replaceChildren();
  payload.models.forEach((item) => {
    const card = document.createElement("div");
    card.className = "asr-local-model-card";
    const modelReady = localAsrModelReady(item);

    const heading = document.createElement("div");
    heading.className = "asr-local-model-heading";
    const title = document.createElement("strong");
    title.textContent = item.label;
    const status = document.createElement("span");
    status.className = "asr-local-model-status" + (modelReady ? " is-ready" : "");
    status.textContent = localAsrStatusLabel(item);
    heading.append(title, status);

    const meta = document.createElement("p");
    meta.className = "settings-form-hint";
    meta.textContent = [
      item.size,
      item.languages,
      `速度 ${item.speed}`,
      `质量 ${item.quality}`,
      `内存约 ${item.memory_required_mb} MB`,
      item.device_requirements,
      item.description,
    ].join(" · ");

    const action = document.createElement("div");
    action.className = "asr-local-model-action";
    const repo = document.createElement("code");
    repo.textContent = item.repo_id || item.path || "用户导入模型";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "button";
    button.dataset.localModelId = item.id;
    button.textContent = modelReady
      ? (item.status === "reused" ? "已复用" : item.status === "imported" ? "已导入" : "已下载")
      : item.status === "downloading"
        ? `下载中 ${item.progress || 0}%`
        : item.status === "validating"
          ? "校验中…"
          : item.repo_id
            ? "下载到本地"
            : "不可用";
    button.disabled = modelReady
      || ["downloading", "validating"].includes(item.status)
      || !payload.runtime_available
      || !item.repo_id;
    action.append(repo, button);
    if (item.update_status) {
      meta.textContent += item.update_available ? " · 有可用更新" : ` · 更新检查：${item.update_status}`;
    }
    if (item.installed) {
      const management = document.createElement("div");
      management.className = "actions";
      const validateButton = document.createElement("button");
      validateButton.type = "button";
      validateButton.className = "button";
      validateButton.textContent = "重新校验";
      validateButton.addEventListener("click", async () => {
        await api(`/api/v1/asr/local-models/${encodeURIComponent(item.id)}/validate`, { method: "POST" });
        await loadLocalAsrModels();
      });
      const updateButton = document.createElement("button");
      updateButton.type = "button";
      updateButton.className = "button";
      updateButton.textContent = "检查更新";
      updateButton.addEventListener("click", async () => {
        await api(`/api/v1/asr/local-models/${encodeURIComponent(item.id)}/update-check`, { method: "POST" });
        await loadLocalAsrModels();
      });
      const removeButton = document.createElement("button");
      removeButton.type = "button";
      removeButton.className = "button";
      removeButton.textContent = "移入回收站";
      removeButton.addEventListener("click", async () => {
        if (!window.confirm(`确认将 ${item.label} 移入可恢复回收站？`)) return;
        await api(`/api/v1/asr/local-models/${encodeURIComponent(item.id)}`, { method: "DELETE" });
        await loadLocalAsrModels();
      });
      management.append(validateButton, updateButton, removeButton);
      card.append(management);
    }

    card.append(heading, meta, action);
    if (["downloading", "validating"].includes(item.status)) {
      const progress = document.createElement("div");
      progress.className = "asr-local-progress";
      const bar = document.createElement("progress");
      bar.max = 100;
      bar.value = item.progress || 0;
      bar.setAttribute("aria-label", `${item.label} 下载进度`);
      const message = document.createElement("span");
      message.textContent = `${item.progress || 0}% · ${item.progress_message || "处理中…"}`;
      progress.append(bar, message);
      card.append(progress);
    }
    if (item.error || ["incomplete", "corrupt"].includes(item.validation_status)) {
      const error = document.createElement("p");
      error.className = "asr-validation";
      error.textContent = item.error || `校验状态：${item.validation_status}`;
      card.append(error);
    }
    list.append(card);
    button.addEventListener("click", downloadLocalAsrModel);
  });

  const downloading = payload.models.some((item) => ["downloading", "validating"].includes(item.status));
  if (downloading && state.localAsrPollTimer === null) {
    state.localAsrPollTimer = window.setTimeout(async () => {
      state.localAsrPollTimer = null;
      await loadLocalAsrModels();
    }, 1500);
  }
  if (payload.runtime_installing && state.localAsrRuntimePollTimer === null) {
    state.localAsrRuntimePollTimer = window.setTimeout(async () => {
      state.localAsrRuntimePollTimer = null;
      await loadLocalAsrModels();
    }, 1500);
  }
}
function clearLocalAsrModelDialog() {
  if (!asrModelDialog) {
    return;
  }
  if (asrModelDialog.open) {
    asrModelDialog.close();
  }
  asrModelDialog.replaceChildren();
}

function showLocalAsrModelDialog(candidates, onSelect) {
  if (!asrModelDialog) {
    return;
  }
  asrModelDialog.replaceChildren();

  const close = document.createElement("button");
  close.type = "button";
  close.className = "asr-model-dialog-close";
  close.setAttribute("aria-label", "关闭模型选择窗口");
  close.setAttribute("aria-label", "关闭");
  close.replaceChildren(createIcon("close"));
  close.addEventListener("click", clearLocalAsrModelDialog);

  const body = document.createElement("div");
  body.className = "asr-model-dialog-body";
  const title = document.createElement("h3");
  title.id = "asr-local-model-dialog-title";
  title.textContent = "选择要导入的本地模型";
  const intro = document.createElement("p");
  intro.className = "settings-form-hint";
  intro.textContent = "扫描到多个完整模型，选择后会继续复制并导入。";
  const list = document.createElement("div");
  list.className = "asr-model-candidate-list";

  candidates.forEach((candidate) => {
    const row = document.createElement("div");
    row.className = "asr-model-candidate";
    const info = document.createElement("div");
    info.className = "asr-model-candidate-info";
    const label = document.createElement("strong");
    label.textContent = candidate.label || candidate.id;
    const meta = document.createElement("span");
    meta.textContent = (candidate.id || "") + (candidate.size ? " · " + candidate.size : "");
    const path = document.createElement("small");
    path.textContent = candidate.path || "";
    info.append(label, meta, path);

    const choose = document.createElement("button");
    choose.type = "button";
    choose.className = "button";
    choose.textContent = "选择并导入";
    choose.addEventListener("click", () => {
      clearLocalAsrModelDialog();
      if (onSelect) {
        void onSelect(candidate);
      }
    });
    row.append(info, choose);
    list.append(row);
  });

  body.append(title, intro, list);
  asrModelDialog.append(close, body);
  if (typeof asrModelDialog.showModal === "function") {
    asrModelDialog.showModal();
  }
}

async function importLocalAsrModel(path, modelId, status) {
  const item = await api("/api/v1/asr/local-models/import", {
    method: "POST",
    body: JSON.stringify({ path, model_id: modelId || null }),
  });
  const select = document.querySelector("#asr-local-model");
  select.dataset.selectedModel = item.id || modelId || "";
  status.textContent = item.error
    || (item.status === "reused"
      ? item.label + " 已存在且校验通过，已直接复用"
      : item.label + " 已导入并校验，路径：" + (item.path || "本地模型目录"));
  await loadLocalAsrModels();
}

async function scanAndImportLocalAsrModel() {
  const path = document.querySelector("#asr-local-import-path").value.trim();
  const status = document.querySelector("#asr-local-import-status");
  const button = document.querySelector("#scan-import-asr-model");
  if (!path) {
    status.textContent = "请先填写模型目录或 Hugging Face 缓存路径。";
    return;
  }
  button.disabled = true;
  try {
    const item = await api("/api/v1/asr/local-models/discover", {
      method: "POST",
      body: JSON.stringify({ path, model_id: null }),
    });
    if (!Object.prototype.hasOwnProperty.call(item, "scan_scope")) {
      status.textContent = "本地服务仍在运行旧版本，请重启 8765 服务后再扫描。";
      return;
    }
    if (item.selection_required && item.candidates?.length) {
      status.textContent = item.error || item.progress_message || "请选择一个本地模型。";
      showLocalAsrModelDialog(
        item.candidates,
        async (candidate) => {
          status.textContent = "正在复制并导入 " + (candidate.label || candidate.id) + "…";
          try {
            await importLocalAsrModel(path, candidate.id, status);
          } catch (error) {
            status.textContent = error.message;
          }
        },
      );
      return;
    }
    await importLocalAsrModel(path, item.id || null, status);
  } catch (error) {
    status.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}
async function loadLocalAsrModels() {
  try {
    const payload = await api("/api/v1/asr/local-models");
    renderLocalAsrModels(payload);
  } catch (error) {
    showNotice(error.message, true);
  }
}

async function downloadLocalAsrModel(event) {
  const button = event.currentTarget;
  const modelId = button.dataset.localModelId;
  document.querySelector("#asr-local-model").dataset.selectedModel = modelId;
  button.disabled = true;
  try {
    await api("/api/v1/asr/local-models/" + encodeURIComponent(modelId) + "/download", {
      method: "POST",
    });
    showNotice("本地 ASR 模型开始下载，完成后可选择并保存");
    await loadLocalAsrModels();
  } catch (error) {
    button.disabled = false;
    showNotice(error.message, true);
  }
}

async function installLocalAsrRuntime() {
  const button = document.querySelector("#install-asr-runtime");
  const status = document.querySelector("#asr-local-runtime-install-status");
  if (button) {
    button.disabled = true;
    button.textContent = "正在安装…";
  }
  if (status) {
    status.textContent = "正在使用当前服务的 Python 环境下载并安装本地 ASR 组件，请稍候…";
  }
  try {
    const result = await api("/api/v1/asr/local-runtime/install", { method: "POST" });
    if (status) {
      status.textContent = result.error || result.message || "本地组件安装任务已开始。";
    }
    await loadLocalAsrModels();
  } catch (error) {
    if (status) status.textContent = error.message;
    if (button) {
      button.disabled = false;
      button.textContent = "重试安装组件";
    }
  }
}

async function downloadSelectedLocalAsrModel() {
  const select = document.querySelector("#asr-local-download-model");
  const button = document.querySelector("#download-selected-asr-model");
  const status = document.querySelector("#asr-local-download-status");
  const modelId = select?.value || "";
  if (!modelId) {
    status.textContent = "请先选择一个公开模型。";
    return;
  }
  button.disabled = true;
  document.querySelector("#asr-local-model").dataset.selectedModel = modelId;
  try {
    await api("/api/v1/asr/local-models/" + encodeURIComponent(modelId) + "/download", {
      method: "POST",
    });
    status.textContent = "模型已开始下载，完成后会自动选中并更新状态。";
    await loadLocalAsrModels();
  } catch (error) {
    status.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

function applyAsrProviderPreset(event) {
  const provider = normalizeAsrProvider(event.target.value);
  const preset = ASR_PROVIDER_PRESETS[provider] || ASR_PROVIDER_PRESETS.custom;
  const urlField = document.querySelector("#asr-api-url");
  // Provider changes only suggest an endpoint; an existing ASR URL/model is
  // user-owned and must remain available for independent configuration.
  if (provider !== "custom" && preset.endpoint && !urlField.value.trim()) {
    urlField.value = preset.endpoint;
  }
  renderAsrProviderHint(provider);
  invalidateAsrConnection();
  showAsrValidation("");
}

function syncAsrProviderFromEndpoint(event) {
  const provider = asrProviderForEndpoint(event.target.value);
  document.querySelector("#asr-provider").value = normalizeAsrProvider(provider);
  renderAsrProviderHint(provider);
  invalidateAsrConnection();
}

const platformConnectionsPanel = document.querySelector("#platform-connections");
const sourceUrlInput = document.querySelector("#source-url");
const importSubmitButton = document.querySelector("#import-form button[type='submit']");
const queryLinksButton = document.querySelector("#query-links");
const linkHint = document.querySelector("#link-hint");
const connectionStatus = document.querySelector("#connection-status");
const shellBridgeRequests = new Map();
let shellBridgeRequestSequence = 0;
const shellBridgeStatuses = new Set([
  "NOT_CONNECTED",
  "CONNECTED",
  "EXPIRED",
  "REAUTH_REQUIRED",
  "RISK_CONTROLLED",
]);

function hasShellBridge() {
  return Boolean(window.chrome?.webview && typeof window.chrome.webview.postMessage === "function");
}

if (window.chrome?.webview?.addEventListener) {
  window.chrome.webview.addEventListener("message", (event) => {
    const result = event.data;
    if (result?.type !== "platform-session-result"
      || !["xiaohongshu", "zhihu"].includes(result.platform)
      || typeof result.requestId !== "string"
      || !shellBridgeStatuses.has(result.status)) {
      return;
    }
    const pending = shellBridgeRequests.get(result.requestId);
    if (!pending) return;
    window.clearTimeout(pending.timeout);
    shellBridgeRequests.delete(result.requestId);
    pending.resolve(result);
  });
}

function requestXhsShellAction(action) {
  if (!hasShellBridge()) {
    return Promise.reject(new Error("请在桌面壳中连接或检查小红书登录状态"));
  }
  const requestId = `xhs-${Date.now()}-${++shellBridgeRequestSequence}`;
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      shellBridgeRequests.delete(requestId);
      reject(new Error("小红书窗口未返回结果，请确认登录窗口已关闭后重试"));
    }, 30 * 60 * 1000);
    shellBridgeRequests.set(requestId, { resolve, reject, timeout });
    try {
      window.chrome.webview.postMessage({
        type: "platform-session-action",
        platform: "xiaohongshu",
        action,
        requestId,
      });
    } catch (error) {
      window.clearTimeout(timeout);
      shellBridgeRequests.delete(requestId);
      reject(new Error("无法联系桌面壳，请重新打开产品窗口"));
    }
  });
}

function requestZhihuShellAction(action, payload = {}) {
  if (!hasShellBridge()) {
    return Promise.reject(new Error("请在桌面壳中连接或读取知乎内容"));
  }
  const requestId = `zhihu-${Date.now()}-${++shellBridgeRequestSequence}`;
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      shellBridgeRequests.delete(requestId);
      reject(new Error("知乎窗口未返回结果，请确认窗口已关闭后重试"));
    }, 30 * 60 * 1000);
    shellBridgeRequests.set(requestId, { resolve, reject, timeout });
    try {
      window.chrome.webview.postMessage({
        type: "platform-session-action",
        platform: "zhihu",
        action,
        requestId,
        ...payload,
      });
    } catch (error) {
      window.clearTimeout(timeout);
      shellBridgeRequests.delete(requestId);
      reject(new Error("无法联系桌面壳，请重新打开产品窗口"));
    }
  });
}

async function saveXhsShellResult(result) {
  return api("/api/v1/platform-connections/xiaohongshu/browser-login", {
    method: "POST",
    body: JSON.stringify({
      status: result.status,
      message: String(result.message || "小红书登录状态暂时无法确认").slice(0, 500),
      browser_profile: result.browser_profile || null,
    }),
  });
}

async function saveZhihuShellResult(result) {
  return api("/api/v1/platform-connections/zhihu/browser-login", {
    method: "POST",
    body: JSON.stringify({
      status: result.status,
      message: String(result.message || "知乎登录状态暂时无法确认").slice(0, 500),
      browser_profile: result.browser_profile || null,
    }),
  });
}

function showIntakeMode(name = state.intakeMode || "link") {
  const mode = ["link", "local"].includes(name) ? name : "link";
  state.intakeMode = mode;
  document.querySelectorAll("[data-intake-mode-panel]").forEach((panel) => {
    const active = panel.dataset.intakeModePanel === mode;
    panel.hidden = !active;
    panel.setAttribute("aria-hidden", String(!active));
  });
  intakeModeButtons.forEach((button) => {
    const active = button.dataset.intakeMode === mode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
  if (importSubmitButton) {
    importSubmitButton.textContent = "查询";
  }
  updateInputPanelSummary();
}

function syncImportAction() {
  if (state.intakeMode === "link") {
    const value = sourceUrlInput?.value.trim() || "";
    const queried = Boolean(value && state.linkQuery?.rawInput === value);
    const overLimit = parseLinkInput(value).length > 50;
    if (importSubmitButton) {
      importSubmitButton.disabled = !value || overLimit;
      importSubmitButton.textContent = queried ? "打开确认" : "查询";
    }
    if (queryLinksButton) {
      queryLinksButton.hidden = !value || overLimit;
      queryLinksButton.disabled = overLimit;
    }
    if (queryLocalButton) queryLocalButton.hidden = true;
    if (importSubmitButton && overLimit) {
      importSubmitButton.title = "单次最多查询 50 条链接，请分批提交";
    }
    return;
  }
  const hasLocalSource = Boolean(
    document.querySelector("#source-text")?.value.trim()
      || document.querySelector("#source-path")?.value.trim(),
  );
  if (importSubmitButton) {
    importSubmitButton.disabled = !hasLocalSource;
    importSubmitButton.textContent = "查询";
  }
  if (queryLinksButton) queryLinksButton.hidden = true;
  if (queryLocalButton) queryLocalButton.hidden = !hasLocalSource;
}

function showSettingsSection(name = state.settingsSection || "platform", { scroll = false } = {}) {
  const allowed = new Set(["platform", "asr", "summary", "ask-model", "ai-ask-cloud", "storage", "operations"]);
  const section = allowed.has(name) ? name : "platform";
  if (settingsContent && state.settingsSection) {
    state.settingsScrollTops[state.settingsSection] = settingsContent.scrollTop;
  }
  state.settingsSection = section;
  document.querySelectorAll("[data-settings-section]").forEach((panel) => {
    const active = panel.dataset.settingsSection === section;
    panel.hidden = !active;
    panel.setAttribute("aria-hidden", String(!active));
  });
  settingsSubnavButtons.forEach((button) => {
    const active = button.dataset.settingsTarget === section;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-current", active ? "page" : "false");
    button.setAttribute("aria-expanded", String(active));
  });
  if (settingsContent) {
    settingsContent.scrollTop = state.settingsScrollTops[section] || 0;
  }
}

function showNotice(message, isError = false) {
  window.clearTimeout(state.noticeTimer);
  notice.textContent = message;
  notice.hidden = false;
  notice.classList.toggle("is-error", isError);
  state.noticeTimer = window.setTimeout(clearNotice, isError ? 8000 : 4000);
}

function clearNotice() {
  window.clearTimeout(state.noticeTimer);
  state.noticeTimer = null;
  notice.hidden = true;
  notice.textContent = "";
}

function openProductTextDialog({
  title,
  label,
  initialValue = "",
  placeholder = "",
  confirmLabel = "保存",
  maxLength = 120,
} = {}) {
  if (!textEntryDialog) return Promise.resolve(null);
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      resolve(value);
    };
    textEntryDialog.replaceChildren();
    const shell = document.createElement("div");
    shell.className = "product-text-dialog-shell";
    const heading = document.createElement("h2");
    heading.id = "text-entry-dialog-title";
    heading.textContent = title || "编辑名称";
    const form = document.createElement("form");
    form.className = "product-text-dialog-form";
    const field = document.createElement("label");
    field.className = "field field-wide";
    const caption = document.createElement("span");
    caption.textContent = label || "名称";
    const input = document.createElement("input");
    input.type = "text";
    input.value = initialValue;
    input.placeholder = placeholder;
    input.maxLength = maxLength;
    input.required = true;
    field.append(caption, input);
    const actions = document.createElement("div");
    actions.className = "actions product-text-dialog-actions";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "button";
    cancel.textContent = "取消";
    cancel.addEventListener("click", () => {
      finish(null);
      textEntryDialog.close();
    });
    const confirm = document.createElement("button");
    confirm.type = "submit";
    confirm.className = "button button-primary";
    confirm.textContent = confirmLabel;
    actions.append(cancel, confirm);
    form.append(field, actions);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const value = input.value.trim();
      if (!value) {
        input.classList.add("is-invalid");
        input.focus();
        return;
      }
      finish(value);
      textEntryDialog.close();
    });
    textEntryDialog.addEventListener("close", () => finish(null), { once: true });
    shell.append(heading, form);
    textEntryDialog.append(shell);
    if (typeof textEntryDialog.showModal === "function") textEntryDialog.showModal();
    else textEntryDialog.open = true;
    window.requestAnimationFrame(() => input.focus());
  });
}

function openProductConfirmDialog({
  title = "确认操作",
  message = "确定继续吗？",
  confirmLabel = "确认",
} = {}) {
  if (!textEntryDialog) return Promise.resolve(false);
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      resolve(value);
    };
    textEntryDialog.replaceChildren();
    const shell = document.createElement("div");
    shell.className = "product-text-dialog-shell";
    const heading = document.createElement("h2");
    heading.id = "text-entry-dialog-title";
    heading.textContent = title;
    const copy = document.createElement("p");
    copy.className = "product-confirm-dialog-message";
    copy.textContent = message;
    const actions = document.createElement("div");
    actions.className = "actions product-text-dialog-actions";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "button";
    cancel.textContent = "取消";
    cancel.addEventListener("click", () => {
      finish(false);
      textEntryDialog.close();
    });
    const confirm = document.createElement("button");
    confirm.type = "button";
    confirm.className = "button button-danger";
    confirm.textContent = confirmLabel;
    confirm.addEventListener("click", () => {
      finish(true);
      textEntryDialog.close();
    });
    actions.append(cancel, confirm);
    shell.append(heading, copy, actions);
    textEntryDialog.addEventListener("close", () => finish(false), { once: true });
    textEntryDialog.append(shell);
    if (typeof textEntryDialog.showModal === "function") textEntryDialog.showModal();
    else textEntryDialog.open = true;
    window.requestAnimationFrame(() => cancel.focus());
  });
}

function applyUiTheme(theme) {
  const selected = theme === "night" ? "night" : "day";
  document.documentElement.dataset.theme = selected;
  const select = document.querySelector("#ui-theme");
  if (select) select.value = selected;
  try {
    window.localStorage.setItem("content-knowledge-ui-theme", selected);
  } catch (_error) {
    // The theme is a convenience preference; the product remains usable if
    // the file-origin browser denies local storage.
  }
}

function restoreUiTheme() {
  let selected = "day";
  try {
    selected = window.localStorage.getItem("content-knowledge-ui-theme") || "day";
  } catch (_error) {
    // Use the warm daytime palette when local storage is unavailable.
  }
  applyUiTheme(selected);
}

function contractError() {
  const error = new Error(CONTRACT_MISMATCH_MESSAGE);
  error.code = "API_CONTRACT_MISMATCH";
  return error;
}

function assertApiContractCompatible(path = "") {
  const bootstrapPath = String(path).split("?", 1)[0];
  if (
    !["/health", "/api/v1/meta"].includes(bootstrapPath)
    && state.apiContractStatus !== "compatible"
  ) {
    const error = new Error(
      state.apiContractStatus === "mismatch"
        ? CONTRACT_MISMATCH_MESSAGE
        : state.apiContractStatus === "unavailable"
          ? "无法连接本地服务，请确认 API 正在运行后重试"
          : "正在检查本地服务，请稍后重试",
    );
    error.code = state.apiContractStatus === "mismatch"
      ? "API_CONTRACT_MISMATCH"
      : "API_CONTRACT_PENDING";
    throw error;
  }
}

async function api(path, options = {}) {
  assertApiContractCompatible(path);
  let response;
  try {
    response = await fetch(`${API_ORIGIN}${path}`, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
  } catch (error) {
    throw new Error(
      API_ORIGIN
        ? "无法连接本地服务，请先启动 API（127.0.0.1:8765）后重试"
        : "无法连接本地服务，请确认 API 正在运行后重试",
    );
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail = payload.detail;
    if (detail && typeof detail === "object" && !Array.isArray(detail)) {
      const error = new Error(detail.user_message || detail.message || "请求未完成");
      error.status = response.status;
      error.code = detail.code;
      error.retryable = Boolean(detail.retryable);
      error.suggestedAction = detail.suggested_action;
      throw error;
    }
    if (Array.isArray(detail)) {
      const error = new Error(
        detail.map((item) => item.msg || item.message || "输入不合法").join("；")
          || "输入不合法",
      );
      error.status = response.status;
      throw error;
    }
    const error = new Error(
      detail === "Not Found"
        ? "未找到请求的内容，请检查链接或刷新页面后重试"
        : detail || "请求未完成",
    );
    error.status = response.status;
    throw error;
  }
  if (response.status === 204 || response.status === 205) return null;
  const rawBody = await response.text();
  if (!rawBody.trim()) return null;
  return JSON.parse(rawBody);
}

function setConnectionStatus(connected) {
  if (!connectionStatus) {
    return;
  }
  connectionStatus.classList.toggle("is-error", !connected);
  connectionStatus.lastChild.textContent = connected ? " 本地服务 · 已连接" : " 本地服务 · 未连接";
}

async function checkService() {
  try {
    const [health, meta] = await Promise.all([
      api("/health"),
      api("/api/v1/meta"),
    ]);
    const runtimeVersions = [health?.api_contract_version, meta?.api_contract_version];
    if (runtimeVersions.some((version) => version !== FRONTEND_API_CONTRACT_VERSION)) {
      throw contractError();
    }
    state.apiContractVersion = meta.api_contract_version;
    state.apiContractStatus = "compatible";
    setConnectionStatus(true);
    return true;
  } catch (error) {
    // A legacy service may expose /health but not /api/v1/meta, or return an
    // otherwise valid response without the contract field. Both cases must
    // stop all business calls and use the actionable restart message.
    state.apiContractStatus =
      error.code === "API_CONTRACT_MISMATCH" || error.status
        ? "mismatch"
        : "unavailable";
    state.apiContractVersion = null;
    setConnectionStatus(false);
    showNotice(
      state.apiContractStatus === "mismatch"
        ? CONTRACT_MISMATCH_MESSAGE
        : error.message,
      true,
    );
    return false;
  }
}

async function restoreActiveJob() {
  try {
    const queue = await api("/api/v1/queue");
    if (!queue.active_job_id) return;
    const job = await api(`/api/v1/jobs/${encodeURIComponent(queue.active_job_id)}`);
    const content = taskContentFromJob(job);
    state.activeJobId = job.id;
    state.activeContentId = content.id;
    state.activeJobTitle = content.title;
    state.activeContentSnapshot = content;
    renderJob(job, state.activeJobTitle, content);
    showNotice(`已恢复当前任务：${state.activeJobTitle}`);
    pollJob();
  } catch (error) {
    showNotice("读取未完成任务失败：" + error.message, true);
  }
}
function statusLabel(value) {
  return {
    waiting: "等待中",
    running: "进行中",
    switching: "保存进度",
    queued: "等待中",
    acquiring: "准备来源",
    extracting: "读取内容",
    transcribing: "整理文本",
    chunking: "分段中",
    summarizing: "总结中",
    archiving: "归档中",
    indexing: "索引中",
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消",
    paused: "已暂停",
  }[value] || value;
}

function jobStage(job) {
  if (job.state === "failed") {
    const resume = job.resume_stage ? statusLabel(job.resume_stage) : null;
    return {
      label: "处理失败",
      detail: resume ? `已保存阶段；重试后从${resume}开始` : "请查看原因并按提示处理",
    };
  }
  if (job.state === "cancelled") return { label: "任务已取消", detail: "任务不会继续执行" };
  if (job.state === "completed") return { label: "已保存到内容库", detail: "可以查看总结和来源" };
  if (job.state === "paused") {
    const stableState = {
      source_ready: "acquiring",
      text_loaded: "extracting",
      transcript_ready: "transcribing",
      chunks_ready: "chunking",
      summary_ready: "summarizing",
      indexed: "indexing",
    }[job.checkpoint] || job.last_stable_stage || "queued";
    const stableStage = {
      queued: { label: "检查来源", detail: "等待开始处理" },
      acquiring: { label: "检查来源", detail: "正在确认链接、权限和材料" },
      extracting: { label: "获取内容", detail: "正在读取字幕、正文或音频" },
      transcribing: { label: "转换文字", detail: job.source_note || "正在使用字幕或语音识别" },
      chunking: { label: "生成总结", detail: "正在整理内容结构" },
      summarizing: { label: "生成总结", detail: "正在提炼重点" },
      archiving: { label: "保存完成", detail: "正在写入归档" },
      indexing: { label: "保存完成", detail: "正在更新内容库" },
    }[stableState] || { label: "检查来源", detail: "等待开始处理" };
    const resume = job.resume_stage ? statusLabel(job.resume_stage) : null;
    return {
      ...stableStage,
      detail: resume
        ? `已暂停 · 已保存到${stableStage.label}；继续后从${resume}开始`
        : `已暂停 · ${stableStage.detail}`,
    };
  }
  return {
    queued: { label: "检查来源", detail: "等待开始处理" },
    acquiring: { label: "检查来源", detail: "正在确认链接、权限和材料" },
    extracting: { label: "获取内容", detail: "正在读取字幕、正文或音频" },
    transcribing: { label: "转换文字", detail: job.source_note || "正在使用字幕或语音识别" },
    chunking: { label: "生成总结", detail: "正在整理内容结构" },
    summarizing: { label: "生成总结", detail: "正在提炼重点" },
    archiving: { label: "保存完成", detail: "正在写入归档" },
    indexing: { label: "保存完成", detail: "正在更新内容库" },
  }[job.state] || { label: statusLabel(job.state), detail: "正在处理" };
}

const TASK_STAGE_LABELS = ["检查来源", "获取内容", "转换文字", "生成总结", "保存完成"];

function jobStageIndex(job) {
  if (job.state === "completed") return TASK_STAGE_LABELS.length - 1;
  if (["archiving", "indexing"].includes(job.state)) return 4;
  if (["chunking", "summarizing"].includes(job.state)) return 3;
  if (job.state === "transcribing") return 2;
  if (job.state === "extracting") return 1;
  if (job.state === "paused") {
    const resumeStage = job.resume_stage || job.last_stable_stage;
    return {
      acquiring: 0,
      extracting: 1,
      transcribing: 2,
      chunking: 3,
      summarizing: 3,
      archiving: 4,
      indexing: 4,
    }[resumeStage] ?? ({
      source_ready: 0,
      text_loaded: 1,
      transcript_ready: 2,
      chunks_ready: 3,
      summary_ready: 4,
      indexed: 4,
    }[job.checkpoint] ?? Math.max(0, Math.min(4, Math.floor(Number(job.progress || 0) / 21))));
  }
  if (job.state === "failed") {
    return Math.max(0, Math.min(4, Math.floor(Number(job.progress || 0) / 21)));
  }
  return 0;
}

function sourceIdentity(job, content = null, title = null) {
  const item = content || state.activeContentSnapshot || {};
  return {
    title: item.title || title || "未命名内容",
    thumbnail: job?.thumbnail_url || item.thumbnail_url || null,
    platform: item.platform || (job?.source_url ? detectLinkPlatform(job.source_url) : "web"),
    author: item.author || null,
    sourceUrl: job?.source_url || item.canonical_url || null,
  };
}

function createSourceCover({ title, thumbnail, platform, className = "source-cover" }) {
  const cover = document.createElement("div");
  const modifierClasses = String(className || "")
    .split(/\s+/)
    .filter(Boolean)
    .filter((name) => name !== "source-cover");
  cover.className = ["source-cover", ...modifierClasses].join(" ");
  cover.setAttribute("role", "img");
  cover.setAttribute("aria-label", `${title || "来源"}封面`);
  const showFallback = (message) => {
    cover.replaceChildren();
    cover.dataset.coverState = "missing";
    const label = document.createElement("span");
    label.className = "source-cover-fallback-title";
    label.textContent = title || message;
    label.title = title || message;
    cover.append(label);
  };
  if (thumbnail) {
    const image = document.createElement("img");
    image.src = thumbnail;
    image.alt = `${title || "来源"}封面`;
    image.loading = "lazy";
    image.referrerPolicy = "no-referrer";
    image.addEventListener("error", () => showFallback("封面不可用"));
    cover.append(image);
  } else {
    cover.dataset.coverState = "empty";
    showFallback(platform === "local" ? "LOCAL" : platformLabel(platform || "web"));
  }
  return cover;
}

function renderTaskStages(job) {
  const wrapper = document.createElement("div");
  wrapper.className = "pixel-task-stages";
  const activeIndex = jobStageIndex(job);
  wrapper.dataset.stageIndex = String(activeIndex);
  const track = document.createElement("div");
  track.className = "pixel-task-stage-track";
  const line = document.createElement("span");
  line.className = "pixel-task-stage-line";
  line.setAttribute("aria-hidden", "true");
  track.append(line);
  TASK_STAGE_LABELS.forEach((label, index) => {
    const item = document.createElement("div");
    item.className = "pixel-task-stage";
    if (index < activeIndex || job.state === "completed") item.classList.add("is-done");
    if (index === activeIndex && job.state !== "completed") item.classList.add("is-active");
    const dot = document.createElement("span");
    dot.className = "pixel-task-stage-dot";
    dot.setAttribute("aria-hidden", "true");
    const text = document.createElement("span");
    text.textContent = label;
    item.append(dot, text);
    track.append(item);
  });
  const cat = renderPixelCat(job);
  if (cat) {
    cat.classList.add("pixel-cat-on-track");
    const progressPercent = job.state === "completed"
      ? 100
      : Math.max(0, Math.min(100, Number(job.progress || 0)));
    cat.style.setProperty("--pixel-cat-position", `${progressPercent}%`);
    track.append(cat);
  }
  wrapper.append(track);
  return wrapper;
}

function renderPixelCat(job) {
  if (["failed", "cancelled"].includes(job.state)) return null;
  const stateName = job.state === "completed"
    ? "success"
    : ["queued", "acquiring"].includes(job.state) ? "walking" : "working";
  const cat = document.createElement("span");
  cat.className = "pixel-cat";
  cat.dataset.state = stateName;
  cat.setAttribute(
    "aria-label",
    stateName === "walking"
      ? "小猫行走中"
      : stateName === "working"
        ? "小猫使用电脑工作中"
        : "小猫完成任务",
  );
  cat.setAttribute("role", "img");
  const art = document.createElement("span");
  art.className = "pixel-cat-art";
  art.setAttribute("aria-hidden", "true");
  cat.append(art);
  return cat;
}

function renderIntakeTaskStatus(job, title = "当前任务", content = null) {
  if (!intakeTaskStatusPanel || !job) return;
  intakeTaskStatusPanel.hidden = false;
  intakeTaskStatusPanel.replaceChildren();
  const heading = document.createElement("div");
  heading.className = "intake-task-status-heading";
  const name = document.createElement("strong");
  const identity = sourceIdentity(job, content, title);
  name.textContent = identity.title;
  const status = document.createElement("span");
  status.className = `status status-${job.state}`;
  status.textContent = statusLabel(job.state);
  heading.append(
    createSourceCover({
      title: identity.title,
      thumbnail: identity.thumbnail,
      platform: identity.platform,
      className: "intake-task-status-cover",
    }),
    name,
    status,
  );
  const body = document.createElement("div");
  body.className = "intake-task-status-body";
  body.append(renderTaskStages(job));
  const detail = document.createElement("span");
  detail.className = "intake-task-status-detail";
  detail.textContent = `${jobStage(job).label} · ${job.progress || 0}%`;
  const viewTask = document.createElement("button");
  viewTask.type = "button";
  viewTask.className = "button button-small";
  viewTask.textContent = "查看任务";
  viewTask.addEventListener("click", () => {
    state.activeJobId = job.id;
    state.activeContentId = content?.id || job.content_id || null;
    state.activeJobTitle = identity.title;
    state.activeContentSnapshot = content || state.activeContentSnapshot;
    showView("tasks");
  });
  body.append(detail, viewTask);
  intakeTaskStatusPanel.append(heading, body);
}

function jobFailure(job) {
  const fallback = {
    asr_runtime_unavailable: {
      title: "本地语音识别组件未安装",
      action: "settings",
      suggestion: "请在设置页安装本地语音识别组件后重试。",
    },
    asr_local_model_not_installed: {
      title: "本地语音识别模型未下载",
      action: "settings",
      suggestion: "请在设置页下载并选择本地语音识别模型后重试。",
    },
    asr_cloud_not_configured: {
      title: "云端语音识别未配置",
      action: "settings",
      suggestion: "请在设置页配置云端语音识别后重试。",
    },
    asr_timeout: {
      title: "语音识别超时",
      action: "retry",
      suggestion: "已保留已完成阶段，请重试当前任务。",
    },
    summary_generation_failed: {
      title: "总结生成失败",
      action: "retry",
      suggestion: "已保留已完成阶段，请重试当前任务。",
    },
    invalid_output: {
      title: "模型返回结果无效",
      action: "retry",
      suggestion: "已保留已完成阶段，请重试当前任务。",
    },
    transcript_incomplete: {
      title: "视频内容未完整识别",
      action: "change_source",
      suggestion: "转写内容不足，请更换内容；无需再次提交当前来源。",
    },
    auth_required: {
      title: "需要重新登录平台",
      action: "login_recheck",
      suggestion: "请登录来源平台后重新检测来源。",
    },
    access_restricted: {
      title: "当前内容受访问限制",
      action: "login_recheck",
      suggestion: "请登录来源平台后重新检测来源。",
    },
    source_not_found: {
      title: "来源内容不存在或已删除",
      action: "change_source",
      suggestion: "该来源无法由当前应用修复，请更换内容。",
    },
    unsupported_source: {
      title: "当前来源暂不支持",
      action: "change_source",
      suggestion: "该来源无法由当前应用处理，请更换内容。",
    },
    transient_network: {
      title: "网络连接失败",
      action: "retry",
      suggestion: "请检查网络连接后重试当前任务。",
    },
    model_unavailable: {
      title: "模型不可用",
      action: "settings",
      suggestion: "请检查模型配置或更换可用模型后重试。",
    },
    disk_space: {
      title: "可用磁盘空间不足",
      action: "settings",
      suggestion: "请清理可用磁盘空间或更换归档目录后重试。",
    },
    unknown: {
      title: "任务未能完成",
      action: "diagnostics",
      suggestion: "当前错误无法由用户直接修复，请保留诊断信息反馈。",
    },
  }[job.error_code] || {
    title: "任务未能完成",
    action: "diagnostics",
    suggestion: "当前错误无法由用户直接修复，请保留诊断信息反馈。",
  };
  return {
    ...fallback,
    action: job.recovery_action || fallback.action,
    suggestion: job.recovery_suggestion || fallback.suggestion,
  };
}

function recoveryActionLabel(action) {
  return {
    login_recheck: "登录并重新检测",
    change_source: "更换来源",
    diagnostics: "查看诊断",
    retry: "重试",
    settings: "前往设置",
  }[action] || "查看诊断";
}

function appendJobRecoveryAction(actions, job, { compact = false } = {}) {
  const failure = jobFailure(job);
  // 任务列表页没有任务日志面板：诊断类失败在列表页改提供「重试」，
  // 失败原因原文已在行内展开详情里；诊断入口只保留在任务详情卡（2026-09-20）。
  const action = compact && failure.action === "diagnostics" ? "retry" : failure.action;
  const button = document.createElement("button");
  button.type = "button";
  button.className = compact ? "button button-small" : "button";
  button.textContent = recoveryActionLabel(action);
  button.addEventListener("click", () => {
    if (action === "retry") {
      void retryJob(job.id);
      return;
    }
    if (action === "settings" || action === "login_recheck") {
      showView("settings");
      return;
    }
    if (action === "change_source") {
      showView("intake");
      if (sourceUrlInput) {
        sourceUrlInput.value = "";
        sourceUrlInput.focus();
      }
      showNotice("请更换来源后重新查询");
      return;
    }
    const timeline = document.querySelector("#task-timeline");
    if (timeline) {
      timeline.open = true;
      timeline.scrollIntoView?.({ block: "nearest" });
    }
    refreshTaskEvents(job.id, { force: true });
  });
  actions.append(button);
}

function platformLabel(value) {
  return {
    local: "本地内容",
    bilibili: "B站",
    zhihu: "知乎",
    xiaohongshu: "小红书",
    wechat: "微信公众号",
    douyin: "抖音",
    web: "网页",
    youtube: "YouTube",
  }[value] || value;
}


function detectLinkPlatform(value) {
  try {
    const parsed = new URL(value.trim());
    const host = parsed.hostname.toLowerCase();
    if (host === "b23.tv" || host.endsWith(".b23.tv") || host === "bilibili.com" || host.endsWith(".bilibili.com")) {
      if (parsed.pathname.toLowerCase().includes("/favlist")) return "B站收藏夹";
      return host === "space.bilibili.com" || host === "space.b23.tv" ? "B站UP主主页" : "B站";
    }
    if (host === "zhihu.com" || host.endsWith(".zhihu.com")) {
      return "知乎";
    }
    if (host === "xhslink.com" || host.endsWith(".xiaohongshu.com")) {
      return "小红书";
    }
    if (host === "mp.weixin.qq.com" || host.endsWith(".weixin.qq.com")) {
      return "微信公众号";
    }
    if (host === "douyin.com" || host.endsWith(".douyin.com") || host.endsWith(".iesdouyin.com")) {
      return "抖音";
    }
    if (host === "youtu.be" || host === "youtube.com" || host.endsWith(".youtube.com")) {
      return "YouTube";
    }
    return "网页";
  } catch {
    return null;
  }
}


function renderSourceCapabilities(capabilities) {
  if (!sourceCapabilitiesPanel) return;
  sourceCapabilitiesPanel.hidden = false;
  sourceCapabilitiesPanel.replaceChildren();
  const heading = document.createElement("h2");
  heading.textContent = "来源能力";
  const list = document.createElement("div");
  list.className = "source-capability-list";
  capabilities.forEach((capability) => {
    const item = document.createElement("article");
    item.className = "source-capability-card";
    const title = document.createElement("strong");
    title.textContent = capability.display_name;
    const status = document.createElement("span");
    status.textContent = capability.public_import_available ? "可完整导入" : "仅识别";
    const note = document.createElement("p");
    note.textContent = capability.note;
    item.append(title, status, note);
    list.append(item);
  });
  sourceCapabilitiesPanel.append(heading, list);
}

async function loadSourceCapabilities() {
  try {
    const response = await api("/api/v1/source-capabilities");
    renderSourceCapabilities(response.capabilities);
  } catch (_error) {
    // 来源能力卡是辅助信息，不影响导入主流程。
  }
}
function renderSourceProbe(probe) {
  state.sourceProbe = probe;
  if (!sourceProbePanel) return;
  sourceProbePanel.hidden = false;
  sourceProbePanel.className = "source-probe" + (probe.can_import ? "" : " is-warning");
  sourceProbePanel.textContent = [
    "平台：" + platformLabel(probe.platform),
    probe.kind === "collection" ? "集合来源" : "单条内容",
    probe.duplicate ? "发现重复，将创建新内容" : probe.material_hint,
    "下一步：" + probe.next_action,
  ].join(" · ");
}

async function probeSource(url) {
  try {
    const probe = await api("/api/v1/imports/probe", {
      method: "POST",
      body: JSON.stringify({ url }),
    });
    if (sourceUrlInput.value.trim() === url) {
      renderSourceProbe(probe);
    }
  } catch (error) {
    if (sourceUrlInput.value.trim() === url && sourceProbePanel) {
      sourceProbePanel.hidden = false;
      sourceProbePanel.className = "source-probe is-error";
      sourceProbePanel.textContent = error.message;
    }
  }
}

function renderBatchSummary(report, jobs = [], creatorName = "") {
  if (!batchPanel) return;
  if ((report.accepted || []).length === 1
    && !(report.failed || []).length
    && !(report.skipped || []).length) {
    batchPanel.hidden = true;
    batchPanel.replaceChildren();
    return;
  }
  if (creatorName) state.batchName = `${creatorName} · 批量总结`;
  const name = state.batchName || "批量任务";
  const counts = jobs.reduce((result, job) => {
    result[job.state] = (result[job.state] || 0) + 1;
    return result;
  }, {});
  const processing = jobs.length
    ? jobs.length - (counts.completed || 0) - (counts.failed || 0) - (counts.cancelled || 0)
    : report.accepted.length;
  batchPanel.hidden = false;
  batchPanel.replaceChildren();
  const details = document.createElement("details");
  details.open = true;
  const summary = document.createElement("summary");
  summary.textContent = `${name} · 处理中 ${Math.max(0, processing)} · 已完成 ${counts.completed || 0} · 失败 ${(counts.failed || 0) + report.failed.length} · 已跳过 ${report.skipped.length}`;
  details.append(summary);
  const list = document.createElement("div");
  list.className = "batch-task-list";
  report.accepted.forEach((item) => {
    const row = document.createElement("div");
    row.className = "batch-task-row";
    const job = jobs.find((candidate) => candidate.id === item.job.id);
    const identity = sourceIdentity(job || item.job, item.content, item.content?.title);
    const copy = document.createElement("div");
    copy.className = "batch-task-copy";
    const title = document.createElement("strong");
    title.className = "batch-task-title";
    title.textContent = identity.title;
    title.title = identity.title;
    const meta = document.createElement("span");
    meta.className = "batch-task-meta";
    meta.textContent = [
      identity.platform ? platformLabel(identity.platform) : null,
      identity.author ? `作者：${identity.author}` : null,
      statusLabel(job?.state || item.job.state || "queued"),
    ].filter(Boolean).join(" · ");
    copy.append(title, meta);
    row.append(
      createSourceCover({
        title: identity.title,
        thumbnail: identity.thumbnail,
        platform: identity.platform,
        className: "batch-task-cover",
      }),
      copy,
    );
    list.append(row);
  });
  report.failed.forEach((item) => {
    const row = document.createElement("div");
    row.className = "batch-task-row is-error";
    const copy = document.createElement("div");
    copy.className = "batch-task-copy";
    const title = document.createElement("strong");
    title.className = "batch-task-title";
    title.textContent = item.url;
    title.title = item.url;
    const reason = document.createElement("span");
    reason.className = "batch-task-meta";
    reason.textContent = item.reason;
    copy.append(title, reason);
    row.append(
      createSourceCover({
        title: item.url,
        platform: detectLinkPlatform(item.url) || "web",
        className: "batch-task-cover",
      }),
      copy,
    );
    list.append(row);
  });
  details.append(list);
  batchPanel.append(details);
  if (report.failed.length) {
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "button button-small";
    retry.textContent = "重新查询失败项";
    retry.addEventListener("click", () => retryLinkUrls(report.failed.map((item) => item.url)));
    batchPanel.append(retry);
  }
}
async function pollBatchJobs() {
  if (!state.batchReport || !state.batchJobIds.length) return;
  const report = state.batchReport;
  const jobIds = [...state.batchJobIds];
  try {
    const jobs = await Promise.all(jobIds.map((id) => api("/api/v1/jobs/" + id)));
    if (state.batchReport !== report || state.batchJobIds.join("|") !== jobIds.join("|")) {
      return;
    }
    renderBatchSummary(report, jobs);
    const favoriteBatch = state.favoriteAddBatch;
    const favoriteBatchMatches = favoriteBatch
      && favoriteBatch.jobIds.join("|") === jobIds.join("|");
    if (favoriteBatchMatches && state.favoriteAddContext?.folderId === favoriteBatch.folderId) {
      state.favoriteAddContext.batchJobs = jobs;
      if (["progress", "association-retry", "link-retry"].includes(state.favoriteAddContext.mode)) {
        renderFavoriteContentAddDialog({ mode: state.favoriteAddContext.mode });
      }
    }
    if (jobs.some((job) => !["completed", "failed", "cancelled"].includes(job.state))) {
      state.batchPollTimer = window.setTimeout(pollBatchJobs, 700);
    } else if (favoriteBatchMatches) {
      const targetFolderId = favoriteBatch.folderId;
      if (state.favoriteAddContext?.folderId === targetFolderId) {
        state.favoriteAddContext.batchJobs = jobs;
        state.favoriteAddContext.batchCompleted = true;
      }
      state.favoriteAddBatch = null;
      state.activeFavoriteFolderId = targetFolderId;
      state.showingTrash = false;
      if (state.currentView === "history") await loadHistory();
      const failed = jobs.filter((job) => job.state !== "completed").length;
      showNotice(
        failed
          ? `处理完成，${failed} 条任务失败；成功内容已归入当前收藏夹`
          : "处理完成，内容已归入当前收藏夹",
        Boolean(failed),
      );
      if (state.favoriteAddContext?.folderId === targetFolderId
        && ["progress", "association-retry", "link-retry"].includes(state.favoriteAddContext.mode)) {
        renderFavoriteContentAddDialog({ mode: state.favoriteAddContext.mode });
      }
    }
  } catch (error) {
    showNotice(error.message, true);
  }
}

function creatorScanDialog() {
  return linkQueryDialog;
}

function collectionSourceLabel(sourceType) {
  return {
    creator: "UP 主主页",
    favorite: "收藏夹",
    watchlater: "稍后再看",
    collection: "合集",
  }[sourceType] || "集合来源";
}

function setCreatorDialogOpen(open) {
  const dialog = creatorScanDialog();
  if (!dialog) return;
  if (open) {
    dialog.classList.add("creator-scan-dialog");
    dialog.oncancel = (event) => {
      event.preventDefault();
      void cancelCreatorScan({ closeDialog: true });
    };
    if (!dialog.open) {
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.open = true;
    }
    return;
  }
  if (state.creatorScanId && ["queued", "running"].includes(state.creatorScan?.status)) {
    void cancelCreatorScan({ closeDialog: true });
    return;
  }
  dialog.oncancel = null;
  dialog.classList.remove("creator-scan-dialog");
  if (dialog.open) {
    if (typeof dialog.close === "function") dialog.close();
    else dialog.open = false;
  }
}

function creatorScanProgressText(scan) {
  if (scan.bilibiliFavoriteDirectoryLoading) return "正在读取收藏夹目录";
  if (scan.platform === "zhihu") return "正在读取知乎收藏夹";
  const label = collectionSourceLabel(scan.source_type);
  if (scan.status === "queued") return `已排队，准备读取${label}…`;
  if (scan.status === "running") {
    return scan.total
      ? `正在读取${label}：${scan.fetched_count}/${scan.total}`
      : `正在读取${label}：已获取 ${scan.fetched_count} 条`;
  }
  if (scan.status === "cancelled") return "扫描已取消，未创建总结任务";
  return "扫描未完成";
}

function creatorCandidatesForView(scan) {
  const query = (state.creatorFilterQuery || "").trim().toLowerCase();
  const status = state.creatorFilterStatus || "all";
  return (scan.candidates || []).filter((candidate) => {
    if (query && !(candidate.title || "").toLowerCase().includes(query)
      && !(candidate.url || "").toLowerCase().includes(query)) return false;
    if (status !== "all" && candidate.duplicate_status !== status) return false;
    return true;
  });
}

function updateCreatorSelectionCount() {
  const count = document.querySelector("#creator-selected-count");
  const button = document.querySelector("#creator-import-selected");
  const selected = state.creatorSelectedIds?.size || 0;
  const total = state.creatorScan?.candidates?.length || 0;
  if (count) {
    count.textContent = `共 ${total} 条 · 已选择 ${selected} 条`;
    if (state.creatorScan?.platform === "zhihu") {
      count.textContent = `前 ${total} 条候选 · 已选择 ${selected} 条`;
    }
  }
  if (button) button.disabled = selected === 0 || (state.creatorScan?.platform === "zhihu" && selected !== 1);
}

function bilibiliFavoriteFolderUrl(folderId) {
  return `https://space.bilibili.com/favlist?fid=${encodeURIComponent(folderId)}`;
}

function renderCreatorScan(scan) {
  state.creatorScan = scan;
  if (scan.source_type) state.creatorScanSourceType = scan.source_type;
  const dialog = creatorScanDialog();
  if (!dialog) return;
  const isFavoriteBrowser = state.bilibiliFavoriteBrowser
    && scan.source_type === "favorite" && scan.platform !== "zhihu";
  dialog.oncancel = (event) => {
    if (["queued", "running"].includes(state.creatorScan?.status)) {
      event.preventDefault();
      cancelCreatorScan();
    }
  };
  dialog.replaceChildren();
  const shell = document.createElement("div");
  shell.className = "creator-scan-shell";
  const header = document.createElement("header");
  header.className = "creator-scan-header";
  const title = document.createElement("h2");
  title.id = "link-query-title";
  title.textContent = scan.platform === "zhihu"
    ? "知乎收藏夹 · 前 10 条候选"
    : scan.source_type === "watchlater"
    ? "稍后再看"
    : scan.up_name
    ? `${collectionSourceLabel(scan.source_type)}：${scan.up_name}`
    : `扫描${collectionSourceLabel(scan.source_type)}`;
  const close = document.createElement("button");
  close.type = "button";
  close.className = "creator-scan-close";
  close.textContent = "关闭";
  close.addEventListener("click", () => setCreatorDialogOpen(false));
  header.append(title, close);
  shell.append(header);

  let body = shell;
  if (isFavoriteBrowser) {
    const browser = document.createElement("div");
    browser.className = "creator-scan-favorite-browser";
    const folderPanel = document.createElement("aside");
    folderPanel.className = "creator-scan-favorite-folders";
    const folderHeader = document.createElement("div");
    folderHeader.className = "creator-scan-favorite-folders-heading";
    const folderTitle = document.createElement("h3");
    folderTitle.textContent = "收藏夹";
    const refresh = document.createElement("button");
    refresh.type = "button";
    refresh.className = "button button-small";
    refresh.textContent = "刷新";
    refresh.disabled = ["queued", "running"].includes(scan.status);
    refresh.addEventListener("click", () => {
      if (state.bilibiliFavoriteFolderId) {
        void startFavoriteScan(bilibiliFavoriteFolderUrl(state.bilibiliFavoriteFolderId), true);
      } else {
        void startBilibiliFavoriteBrowser();
      }
    });
    folderHeader.append(folderTitle, refresh);
    const folderList = document.createElement("div");
    folderList.className = "creator-scan-favorite-folder-list";
    state.bilibiliFavoriteFolders.forEach((folder) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "creator-scan-favorite-folder";
      if (String(folder.id) === String(state.bilibiliFavoriteFolderId)) {
        button.classList.add("is-active");
        button.setAttribute("aria-current", "true");
      }
      const name = document.createElement("span");
      name.textContent = folder.title;
      const count = document.createElement("span");
      count.className = "creator-scan-favorite-folder-count";
      count.textContent = String(folder.media_count);
      button.append(name, count);
      button.addEventListener("click", () => {
        if (String(folder.id) === String(state.bilibiliFavoriteFolderId)
          && ["queued", "running"].includes(state.creatorScan?.status)) return;
        state.bilibiliFavoriteFolderId = folder.id;
        void startFavoriteScan(bilibiliFavoriteFolderUrl(folder.id));
      });
      folderList.append(button);
    });
    folderPanel.append(folderHeader, folderList);
    const content = document.createElement("div");
    content.className = "creator-scan-favorite-content";
    browser.append(folderPanel, content);
    shell.append(browser);
    body = content;
  }

  // 完成态不再渲染状态行：候选列表与底栏计数已经表达"扫描完成"，再多一行是重复。
  if (scan.status !== "completed" && !scan.bilibiliFavoriteDirectoryLoading) {
    const statusLine = document.createElement("div");
    statusLine.className = `creator-scan-status is-${scan.status}`;
    statusLine.textContent = creatorScanProgressText(scan);
    body.append(statusLine);
  }

  if (scan.bilibiliFavoriteDirectoryLoading) {
    const progress = document.createElement("div");
    progress.className = "creator-scan-loading";
    const spinner = document.createElement("span");
    spinner.className = "loading-spinner";
    spinner.setAttribute("aria-hidden", "true");
    const copy = document.createElement("span");
    copy.textContent = "正在读取收藏夹目录";
    progress.append(spinner, copy);
    body.append(progress);
  } else if (["queued", "running"].includes(scan.status)) {
    const progress = document.createElement("div");
    progress.className = "creator-scan-loading";
    const spinner = document.createElement("span");
    spinner.className = "loading-spinner";
    spinner.setAttribute("aria-hidden", "true");
    const copy = document.createElement("span");
    copy.textContent = scan.platform === "zhihu"
      ? "知乎收藏夹前 10 条候选"
      : "只读取标题、发布时间和时长，不会下载视频或生成总结。";
    progress.append(spinner, copy);
    body.append(progress);
    const actions = document.createElement("div");
    actions.className = "creator-scan-actions";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "button button-danger";
    cancel.textContent = "取消扫描";
    cancel.addEventListener("click", () => cancelCreatorScan({ closeDialog: true }));
    actions.append(cancel);
    body.append(actions);
  } else if (scan.bilibiliFavoriteDirectoryError) {
    const error = document.createElement("div");
    error.className = "creator-scan-error";
    error.textContent = scan.error?.user_message || "B站收藏夹目录读取失败";
    body.append(error);
    const actions = document.createElement("div");
    actions.className = "creator-scan-actions";
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "button button-primary";
    retry.textContent = "重试";
    retry.addEventListener("click", () => void startBilibiliFavoriteBrowser());
    const login = document.createElement("button");
    login.type = "button";
    login.className = "button";
    login.textContent = "二维码登录";
    login.addEventListener("click", () => void startBilibiliQrLogin(login));
    actions.append(retry, login);
    body.append(actions);
  } else if (scan.bilibiliFavoriteNoFolders) {
    const empty = document.createElement("div");
    empty.className = "creator-scan-empty";
    empty.textContent = "没有收藏夹";
    body.append(empty);
  } else if (scan.error) {
    const error = document.createElement("div");
    error.className = "creator-scan-error";
    error.textContent = scan.error.user_message;
    body.append(error);
    const actions = document.createElement("div");
    actions.className = "creator-scan-actions";
    if (scan.error.retryable) {
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "button button-primary";
      retry.textContent = "重新扫描";
      retry.addEventListener("click", () => startCollectionScan(scan.source_type, scan.url, true, scan.platform));
      actions.append(retry);
    }
    const close = document.createElement("button");
    close.type = "button";
    close.className = "button";
    close.textContent = isFavoriteBrowser ? "关闭" : "返回输入";
    close.addEventListener("click", () => setCreatorDialogOpen(false));
    actions.append(close);
    body.append(actions);
  } else if (scan.status === "completed" && (scan.candidates || []).length > 0) {
    const toolbar = document.createElement("div");
    toolbar.className = "creator-scan-toolbar";
    const search = document.createElement("input");
    search.type = "search";
    search.placeholder = "搜索标题或链接";
    search.value = state.creatorFilterQuery || "";
    search.addEventListener("input", (event) => {
      state.creatorFilterQuery = event.target.value;
      renderCreatorScan(state.creatorScan);
    });
    const filter = document.createElement("select");
    filter.setAttribute("aria-label", "按重复状态筛选");
    const options = isFavoriteBrowser
      ? [["all", "全部"], ["new", "未导入"], ["processing", "处理中"], ["summarized", "已导入"], ["failed", "导入失败"]]
      : [["all", "全部视频"], ["new", "未总结"], ["summarized", "已有总结"], ["processing", "处理中"]];
    options.forEach(([value, label]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      option.selected = value === (state.creatorFilterStatus || "all");
      filter.append(option);
    });
    filter.addEventListener("change", (event) => {
      state.creatorFilterStatus = event.target.value;
      renderCreatorScan(state.creatorScan);
    });
    if (scan.platform !== "zhihu") {
      const selectVisible = document.createElement("button");
      selectVisible.type = "button";
      selectVisible.className = "button";
      selectVisible.textContent = "全选";
      selectVisible.addEventListener("click", () => {
        creatorCandidatesForView(scan).forEach((candidate) => {
          if (candidate.selectable !== false) state.creatorSelectedIds.add(candidate.candidate_id);
        });
        renderCreatorScan(scan);
      });
      toolbar.append(search, filter, selectVisible);
      body.append(toolbar);
    }

    const list = document.createElement("div");
    list.className = "creator-scan-list";
    creatorCandidatesForView(scan).forEach((candidate) => {
      const row = document.createElement("article");
      row.className = "creator-scan-item";
      if (candidate.selectable === false) row.classList.add("is-disabled");
      const checkbox = document.createElement("input");
      checkbox.type = scan.platform === "zhihu" ? "radio" : "checkbox";
      if (scan.platform === "zhihu") checkbox.name = "zhihu-favorite-candidate";
      checkbox.setAttribute("aria-label", `选择${candidate.title || (scan.platform === "zhihu" ? "文章" : "视频")}`);
      checkbox.checked = state.creatorSelectedIds.has(candidate.candidate_id);
      checkbox.disabled = candidate.selectable === false;
      checkbox.addEventListener("change", (event) => {
        if (event.target.checked && scan.platform === "zhihu") {
          state.creatorSelectedIds = new Set([candidate.candidate_id]);
        } else if (event.target.checked) state.creatorSelectedIds.add(candidate.candidate_id);
        else state.creatorSelectedIds.delete(candidate.candidate_id);
        updateCreatorSelectionCount();
      });
      const cover = document.createElement("span");
      cover.className = "creator-scan-item-cover";
      cover.append(createSourceCover({
        title: candidate.title,
        thumbnail: candidate.thumbnail_url,
        platform: scan.platform || "bilibili",
        className: "creator-scan-cover",
      }));
      const body = document.createElement("span");
      body.className = "creator-scan-item-body";
      const itemTitle = document.createElement("strong");
      itemTitle.className = "creator-scan-item-title";
      itemTitle.textContent = candidate.title;
      itemTitle.title = candidate.title;
      const itemMeta = document.createElement("span");
      itemMeta.className = "creator-scan-item-meta";
      const duplicateLabel = candidate.duplicate_status === "summarized"
        ? (isFavoriteBrowser ? "已导入" : "已有总结")
        : candidate.duplicate_status === "processing" ? "处理中"
        : candidate.duplicate_status === "failed" ? "导入失败"
        : candidate.imported_page_count > 0 ? "部分导入"
        : (isFavoriteBrowser ? "未导入" : "未总结");
      const partLabel = candidate.page_count
        ? `${candidate.imported_page_count || 0}/${candidate.page_count} P 已导入`
        : candidate.imported_page_count > 0 ? `已导入 ${candidate.imported_page_count} P · 总P数未知` : null;
      const partStatusLabels = { new: "未导入", summarized: "已导入", processing: "处理中", failed: "导入失败" };
      itemMeta.textContent = [
        candidate.published_at,
        candidate.duration_seconds ? formatDuration(candidate.duration_seconds) : null,
        duplicateLabel,
        isFavoriteBrowser ? partLabel : null,
      ]
        .filter(Boolean).join(" · ");
      if (isFavoriteBrowser && candidate.part_statuses?.length) {
        itemMeta.title = candidate.part_statuses
          .map((status, index) => `P${index + 1} ${partStatusLabels[status] || status}`)
          .join(" · ");
      }
      body.append(itemTitle, itemMeta);
      const link = document.createElement("a");
      link.href = candidate.url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = "打开";
      link.addEventListener("click", (event) => event.stopPropagation());
      row.tabIndex = candidate.selectable === false ? -1 : 0;
      const toggle = () => {
        if (checkbox.disabled) return;
        checkbox.checked = !checkbox.checked;
        checkbox.dispatchEvent(new Event("change", { bubbles: true }));
      };
      row.addEventListener("click", (event) => {
        if (event.target.closest("a, input, button")) return;
        toggle();
      });
      row.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        toggle();
      });
      checkbox.addEventListener("click", (event) => event.stopPropagation());
      row.append(checkbox, cover, body, link);
      list.append(row);
    });
    body.append(list);
    const footer = document.createElement("footer");
    footer.className = "creator-scan-footer";
    const selected = document.createElement("span");
    selected.id = "creator-selected-count";
    const importButton = document.createElement("button");
    importButton.id = "creator-import-selected";
    importButton.type = "button";
    importButton.className = "button button-primary";
    importButton.textContent = scan.platform === "zhihu" ? "添加到知识库" : isFavoriteBrowser ? "导入所选视频" : "解析并生成总结";
    importButton.addEventListener("click", () => importSelectedVideos(importButton));
    const closeButton = document.createElement("button");
    closeButton.type = "button";
    closeButton.className = "button";
    closeButton.textContent = "稍后处理";
    closeButton.addEventListener("click", () => setCreatorDialogOpen(false));
    footer.append(selected, closeButton, importButton);
    body.append(footer);
  } else {
    const empty = document.createElement("div");
    empty.className = "creator-scan-empty";
    const label = collectionSourceLabel(scan.source_type);
    empty.textContent = scan.platform === "zhihu"
      ? "该收藏夹没有可导入的回答或文章。"
      : scan.fetched_count
      ? "扫描已结束，但没有可展示的视频。"
      : `该${label}没有可访问的视频。`;
    body.append(empty);
  }
  dialog.append(shell);
  setCreatorDialogOpen(true);
  updateCreatorSelectionCount();
}

async function pollCreatorScan() {
  if (!state.creatorScanId) return;
  const scanId = state.creatorScanId;
  const requestId = state.creatorScanRequestId;
  try {
    const scan = await api(`/api/v1/imports/bilibili/creator-scans/${encodeURIComponent(scanId)}`);
    if (state.creatorScanId !== scanId || state.creatorScanRequestId !== requestId) return;
    renderCreatorScan(scan);
    if (["queued", "running"].includes(scan.status)) {
      state.creatorScanTimer = window.setTimeout(pollCreatorScan, 700);
    }
  } catch (error) {
    if (state.creatorScanId !== scanId || state.creatorScanRequestId !== requestId) return;
    showNotice(error.message, true);
  }
}

async function startCreatorScan(url, refresh = false) {
  state.creatorScanSourceType = "creator";
  state.bilibiliFavoriteBrowser = false;
  const requestId = ++state.creatorScanRequestId;
  state.creatorScanId = null;
  window.clearTimeout(state.creatorScanTimer);
  state.creatorSelectedIds = new Set();
  state.creatorFilterQuery = "";
  state.creatorFilterStatus = "all";
  renderCreatorScan({ scan_id: null, url, status: "queued", candidates: [], fetched_count: 0 });
  try {
    const accepted = await api("/api/v1/imports/bilibili/creator-scans", {
      method: "POST",
      body: JSON.stringify({ url, refresh }),
    });
    if (state.creatorScanRequestId !== requestId) {
      await api(`/api/v1/imports/bilibili/creator-scans/${encodeURIComponent(accepted.scan_id)}`, { method: "DELETE" }).catch(() => {});
      return;
    }
    state.creatorScanId = accepted.scan_id;
    renderCreatorScan({ scan_id: accepted.scan_id, url, status: accepted.status, candidates: [], fetched_count: 0 });
    pollCreatorScan();
  } catch (error) {
    if (state.creatorScanRequestId !== requestId) return;
    renderCreatorScan({ scan_id: null, url, status: "failed", candidates: [], fetched_count: 0, error: {
      user_message: error.message, retryable: Boolean(error.retryable),
    } });
  }
}

async function pollFavoriteScan() {
  if (!state.creatorScanId) return;
  const scanId = state.creatorScanId;
  const requestId = state.creatorScanRequestId;
  try {
    const scan = await api(`/api/v1/imports/bilibili/favorite-scans/${encodeURIComponent(scanId)}`);
    if (state.creatorScanId !== scanId || state.creatorScanRequestId !== requestId) return;
    renderCreatorScan(scan);
    if (["queued", "running"].includes(scan.status)) {
      state.creatorScanTimer = window.setTimeout(pollFavoriteScan, 700);
    }
  } catch (error) {
    if (state.creatorScanId !== scanId || state.creatorScanRequestId !== requestId) return;
    renderCreatorScan({ scan_id: null, status: "failed", candidates: [], fetched_count: 0, source_type: "favorite", error: {
      user_message: error.message, retryable: true,
    } });
  }
}

async function startFavoriteScan(url, refresh = false) {
  state.creatorScanSourceType = "favorite";
  const previousScanId = state.creatorScanId;
  const previousFavoriteId = (() => {
    try { return new URL(state.creatorScan?.url || "").searchParams.get("fid"); } catch { return null; }
  })();
  const nextFavoriteId = (() => {
    try { return new URL(url).searchParams.get("fid"); } catch { return null; }
  })();
  if (previousScanId && previousFavoriteId !== nextFavoriteId
    && ["queued", "running"].includes(state.creatorScan?.status)) {
    void api(`/api/v1/imports/bilibili/favorite-scans/${encodeURIComponent(previousScanId)}`, { method: "DELETE" }).catch(() => {});
  }
  const requestId = ++state.creatorScanRequestId;
  state.creatorScanId = null;
  window.clearTimeout(state.creatorScanTimer);
  state.creatorSelectedIds = new Set();
  state.creatorFilterQuery = "";
  state.creatorFilterStatus = "all";
  renderCreatorScan({ scan_id: null, url, status: "queued", candidates: [], fetched_count: 0, source_type: "favorite" });
  try {
    const accepted = await api("/api/v1/imports/bilibili/favorite-scans", {
      method: "POST",
      body: JSON.stringify({ url, refresh }),
    });
    if (state.creatorScanRequestId !== requestId) {
      await api(`/api/v1/imports/bilibili/favorite-scans/${encodeURIComponent(accepted.scan_id)}`, { method: "DELETE" }).catch(() => {});
      return;
    }
    state.creatorScanId = accepted.scan_id;
    renderCreatorScan({ scan_id: accepted.scan_id, url, status: accepted.status, candidates: [], fetched_count: 0, source_type: "favorite" });
    pollFavoriteScan();
  } catch (error) {
    if (state.creatorScanRequestId !== requestId) return;
    renderCreatorScan({ scan_id: null, url, status: "failed", candidates: [], fetched_count: 0, source_type: "favorite", error: {
      user_message: error.message, retryable: Boolean(error.retryable),
    } });
  }
}

async function startBilibiliFavoriteBrowser() {
  const previousScanId = state.creatorScanId;
  const previousSourceType = state.creatorScanSourceType || state.creatorScan?.source_type || "favorite";
  const previousFavoriteId = (() => {
    try { return new URL(state.creatorScan?.url || "").searchParams.get("fid"); } catch { return null; }
  })();
  const selectedFavoriteId = String(state.bilibiliFavoriteFolderId || "");
  if (previousScanId && ["queued", "running"].includes(state.creatorScan?.status)
    && !(previousSourceType === "favorite" && previousFavoriteId === selectedFavoriteId)) {
    void api(`/api/v1/imports/bilibili/${previousSourceType}-scans/${encodeURIComponent(previousScanId)}`, { method: "DELETE" }).catch(() => {});
  }

  const requestId = ++state.creatorScanRequestId;
  state.creatorScanId = null;
  state.creatorScanSourceType = "favorite";
  state.bilibiliFavoriteBrowser = true;
  window.clearTimeout(state.creatorScanTimer);
  state.creatorSelectedIds = new Set();
  state.creatorFilterQuery = "";
  state.creatorFilterStatus = "all";
  renderCreatorScan({
    scan_id: null,
    status: "running",
    source_type: "favorite",
    bilibiliFavoriteDirectoryLoading: true,
    candidates: [],
    fetched_count: 0,
  });
  try {
    const folders = await api("/api/v1/imports/bilibili/favorite-folders");
    if (state.creatorScanRequestId !== requestId) return;
    state.bilibiliFavoriteFolders = folders;
    if (!folders.length) {
      state.bilibiliFavoriteFolderId = null;
      renderCreatorScan({
        scan_id: null,
        status: "completed",
        source_type: "favorite",
        bilibiliFavoriteNoFolders: true,
        candidates: [],
        fetched_count: 0,
      });
      return;
    }
    const folder = folders.find((item) => String(item.id) === String(state.bilibiliFavoriteFolderId)) || folders[0];
    state.bilibiliFavoriteFolderId = folder.id;
    await startFavoriteScan(bilibiliFavoriteFolderUrl(folder.id));
  } catch (error) {
    if (state.creatorScanRequestId !== requestId) return;
    renderCreatorScan({
      scan_id: null,
      status: "failed",
      source_type: "favorite",
      bilibiliFavoriteDirectoryError: true,
      error: { user_message: error.message },
      candidates: [],
      fetched_count: 0,
    });
  }
}

async function startZhihuFavoriteScan(url, refresh = false) {
  state.bilibiliFavoriteBrowser = false;
  const requestId = ++state.creatorScanRequestId;
  state.creatorScanId = `zhihu-${requestId}`;
  window.clearTimeout(state.creatorScanTimer);
  state.creatorSelectedIds = new Set();
  state.creatorFilterQuery = "";
  state.creatorFilterStatus = "all";
  state.creatorScanSourceType = "favorite";
  renderCreatorScan({
    scan_id: state.creatorScanId,
    url,
    status: "running",
    candidates: [],
    fetched_count: 0,
    source_type: "favorite",
    platform: "zhihu",
  });
  try {
    const result = await requestZhihuShellAction("scan_favorites", { url });
    if (state.creatorScanRequestId !== requestId) return;
    if (result.status !== "CONNECTED" || !Array.isArray(result.candidates)) {
      throw new Error(result.message || "知乎收藏夹读取失败");
    }
    state.creatorScanId = null;
    renderCreatorScan({
      scan_id: null,
      url,
      status: "completed",
      candidates: result.candidates,
      fetched_count: result.candidates.length,
      source_type: "favorite",
      platform: "zhihu",
    });
  } catch (error) {
    if (state.creatorScanRequestId !== requestId) return;
    state.creatorScanId = null;
    renderCreatorScan({
      scan_id: null,
      url,
      status: "failed",
      candidates: [],
      fetched_count: 0,
      source_type: "favorite",
      platform: "zhihu",
      error: { user_message: error.message, retryable: true },
    });
  }
}

async function pollWatchlaterScan() {
  if (!state.creatorScanId) return;
  const scanId = state.creatorScanId;
  const requestId = state.creatorScanRequestId;
  try {
    const scan = await api(`/api/v1/imports/bilibili/watchlater-scans/${encodeURIComponent(scanId)}`);
    if (state.creatorScanId !== scanId || state.creatorScanRequestId !== requestId) return;
    renderCreatorScan(scan);
    if (["queued", "running"].includes(scan.status)) {
      state.creatorScanTimer = window.setTimeout(pollWatchlaterScan, 700);
    }
  } catch (error) {
    if (state.creatorScanId !== scanId || state.creatorScanRequestId !== requestId) return;
    renderCreatorScan({
      scan_id: null,
      status: "failed",
      candidates: [],
      fetched_count: 0,
      source_type: "watchlater",
      error: { user_message: error.message, retryable: true },
    });
  }
}

async function startWatchlaterScan(url, refresh = false) {
  const requestId = ++state.creatorScanRequestId;
  state.bilibiliFavoriteBrowser = false;
  state.creatorScanSourceType = "watchlater";
  state.creatorScanId = null;
  window.clearTimeout(state.creatorScanTimer);
  state.creatorSelectedIds = new Set();
  state.creatorFilterQuery = "";
  state.creatorFilterStatus = "all";
  renderCreatorScan({
    scan_id: null,
    url,
    status: "queued",
    candidates: [],
    fetched_count: 0,
    source_type: "watchlater",
  });
  try {
    const accepted = await api("/api/v1/imports/bilibili/watchlater-scans", {
      method: "POST",
      body: JSON.stringify({ url, refresh }),
    });
    if (state.creatorScanRequestId !== requestId) {
      await api(`/api/v1/imports/bilibili/watchlater-scans/${encodeURIComponent(accepted.scan_id)}`, { method: "DELETE" }).catch(() => {});
      return;
    }
    state.creatorScanId = accepted.scan_id;
    renderCreatorScan({
      scan_id: accepted.scan_id,
      url,
      status: accepted.status,
      candidates: [],
      fetched_count: 0,
      source_type: "watchlater",
    });
    pollWatchlaterScan();
  } catch (error) {
    if (state.creatorScanRequestId !== requestId) return;
    renderCreatorScan({
      scan_id: null,
      url,
      status: "failed",
      candidates: [],
      fetched_count: 0,
      source_type: "watchlater",
      error: { user_message: error.message, retryable: Boolean(error.retryable) },
    });
  }
}

function openCollectionScanInput(platform) {
  state.bilibiliFavoriteBrowser = false;
  clearLinkQueryPolling();
  state.linkQueryRequestId += 1;
  state.linkQuery = null;
  state.linkQuerySelectedIds = new Set();
  setLinkQueryDialogOpen(false);
  state.pendingCollectionScan = { platform, sourceType: "favorite" };
  showView("intake");
  showIntakeMode("link");
  sourceUrlInput.value = "";
  syncImportAction();
  sourceUrlInput.focus();
  showNotice(`请输入一个${platformLabel(platform)}收藏夹链接并点击“查询”`);
}

function startCollectionScan(sourceType, url, refresh = false, platform = null) {
  if (platform === "zhihu") return startZhihuFavoriteScan(url, refresh);
  if (sourceType === "favorite") return startFavoriteScan(url, refresh);
  if (sourceType === "watchlater") return startWatchlaterScan(url, refresh);
  return startCreatorScan(url, refresh);
}

async function cancelCreatorScan({ closeDialog = false } = {}) {
  const scanId = state.creatorScanId;
  const scan = state.creatorScan;
  if (scan?.platform === "zhihu") {
    state.creatorScanRequestId += 1;
    state.creatorScanId = null;
    if (closeDialog) closeCreatorScanDialog();
    return;
  }
  if (!scanId) {
    if (closeDialog) closeCreatorScanDialog();
    return;
  }
  const requestId = ++state.creatorScanRequestId;
  state.creatorScanId = null;
  window.clearTimeout(state.creatorScanTimer);
  if (closeDialog) closeCreatorScanDialog();
  try {
    const scanType = state.creatorScanSourceType || scan?.source_type || "creator";
    const cancelled = await api(`/api/v1/imports/bilibili/${scanType}-scans/${encodeURIComponent(scanId)}`, { method: "DELETE" });
    if (closeDialog || state.creatorScanRequestId !== requestId) return;
    state.creatorScan = cancelled;
    renderCreatorScan(cancelled);
  } catch (error) {
    if (!closeDialog && state.creatorScanRequestId === requestId) showNotice(error.message, true);
  }
}

function closeCreatorScanDialog() {
  const dialog = creatorScanDialog();
  if (!dialog) return;
  dialog.oncancel = null;
  dialog.classList.remove("creator-scan-dialog");
  if (dialog.open) {
    if (typeof dialog.close === "function") dialog.close();
    else dialog.open = false;
  }
}

function parseLinkInput(value) {
  return [...new Set(
    String(value || "")
      .split(/[\s,，]+/)
      .map((item) => item.trim())
      .filter(Boolean),
  )];
}

function retryLinkUrls(urls) {
  const retryUrls = [...new Set((urls || []).map((url) => String(url || "").trim()).filter(Boolean))];
  if (!retryUrls.length) return;
  sourceUrlInput.value = retryUrls.join("\n");
  setLinkQueryDialogOpen(false);
  updateLinkHint();
  void queryLinks();
}

function updateLinkCount() {
  const badge = document.querySelector("#link-count-badge");
  const count = parseLinkInput(sourceUrlInput?.value || "").length;
  if (badge) {
    badge.textContent = count >= 50
      ? `已识别 ${count} 条${count > 50 ? "，超过上限 50 条" : "（已达上限）"}`
      : `已识别 ${count} 条${count >= 40 ? " · 接近上限 50 条" : ""}`;
    badge.classList.toggle("is-warning", count >= 40 && count <= 50);
    badge.classList.toggle("is-error", count > 50);
  }
  const overLimit = count > 50;
  [importSubmitButton, queryLinksButton].forEach((button) => {
    if (!button) return;
    if (overLimit) {
      button.disabled = true;
      button.title = "单次最多查询 50 条链接，请分批提交";
    } else {
      button.removeAttribute("title");
    }
  });
  if (!overLimit) syncImportAction();
}

function updateLinkHint() {
  const value = sourceUrlInput.value.trim();
  if (state.linkQuery?.loading && state.linkQuery.rawInput !== value) {
    state.linkQueryRequestId += 1;
    state.linkQuery = null;
  }
  const urls = parseLinkInput(value);
  state.sourceProbe = null;
  window.clearTimeout(state.sourceProbeTimer);
  if (sourceProbePanel) sourceProbePanel.hidden = true;
  if (!value) {
    state.linkQuery = null;
    state.linkQuerySelectedIds = new Set();
    linkHint.textContent = "支持单条或多条内容链接；必须点击“查询”后确认提交";
    clearSpacePreview();
    if (queryLinksButton) queryLinksButton.hidden = true;
    updateLinkCount();
    syncImportAction();
    return;
  }
  const platform = urls.length === 1 ? detectLinkPlatform(urls[0]) : null;
  if (queryLinksButton) {
    queryLinksButton.textContent = "查询";
  }
  if (platform === "B站UP主主页") {
    linkHint.textContent = "已识别：B站 UP 主主页；点击查询后再确认扫描范围";
  } else if (urls.length > 1) {
    linkHint.textContent = `已填写 ${urls.length} 条链接；查询后逐条校验`;
  } else {
    linkHint.textContent = platform ? "已识别：" + platform : "暂不支持此链接";
  }
  clearSpacePreview();
  updateLinkCount();
  syncImportAction();
}

function setLinkQueryDialogOpen(open) {
  if (!linkQueryDialog) return;
  linkQueryDialog.oncancel = () => {
    void cancelLinkQuery();
  };
  if (open && !linkQueryDialog.open) {
    if (typeof linkQueryDialog.showModal === "function") linkQueryDialog.showModal();
    else linkQueryDialog.open = true;
  } else if (!open) {
    window.clearTimeout(state.linkQueryPollTimer);
    state.linkQueryPollTimer = null;
    state.linkQueryRequestId += 1;
    if (!linkQueryDialog.open) return;
    if (typeof linkQueryDialog.close === "function") linkQueryDialog.close();
    else linkQueryDialog.open = false;
  }
}

function linkQueryStatusLabel(item) {
  return {
    pending: "正在查询",
    ready: "可提交",
    duplicate: "重复内容·将新建",
    failed: "校验失败",
    timed_out: "查询超时",
    collection: "需要选择范围",
  }[item.status] || "待处理";
}

function clearLinkQueryPolling() {
  window.clearTimeout(state.linkQueryPollTimer);
  state.linkQueryPollTimer = null;
}

function linkQueryHasPendingItems(query) {
  return (query?.items || []).some((item) => item.status === "pending");
}

function linkQueryIsProcessing(query) {
  return query?.status === "processing" || linkQueryHasPendingItems(query);
}

function linkQueryIsRetryable(item) {
  return ["failed", "timed_out", "collection"].includes(item?.status);
}

function automaticCollectionItem(query) {
  const items = Array.isArray(query?.items) ? query.items : [];
  if (!items.length) return null;
  const isCollectionFailure = (item) => item.status === "collection"
    || (item.status === "failed"
      && ["creator", "favorite", "watchlater"].includes(item.source_type));
  if (!items.every(isCollectionFailure)) return null;
  const first = items[0];
  if (!(first.source_type === "creator" || first.source_type === "favorite" || first.source_type === "watchlater")) {
    return null;
  }
  return first.status === "timed_out"
    ? null
    : items.every((item) => item.source_type === first.source_type && item.input_url === first.input_url)
      ? first
      : null;
}

async function cancelLinkQuerySession(queryId) {
  if (!queryId) return;
  try {
    await api(`/api/v1/imports/query/${encodeURIComponent(queryId)}/cancel`, { method: "POST" });
  } catch (error) {
    if (error?.status !== 404) throw error;
  }
}

async function cancelLinkQuery() {
  const queryId = state.linkQuery?.query_id;
  const favoriteAdd = Boolean(state.favoriteAddContext?.folderId);
  clearLinkQueryPolling();
  state.linkQueryRequestId += 1;
  if (favoriteAdd) closeFavoriteAddDialog();
  else setLinkQueryDialogOpen(false);
  if (!queryId) return;
  try {
    const cancelled = await api(
      `/api/v1/imports/query/${encodeURIComponent(queryId)}/cancel`,
      { method: "POST" },
    );
    if (state.linkQuery?.query_id === queryId) {
      state.linkQuery = { ...state.linkQuery, ...cancelled };
    }
  } catch (error) {
    if (error?.status !== 404) showNotice(error.message, true);
  }
}

function mergeLinkQuerySnapshot(snapshot, previous) {
  const query = {
    ...previous,
    ...snapshot,
    rawInput: previous?.rawInput,
    collection_import: previous?.collection_import,
    favorite_add: previous?.favorite_add,
    classify: previous?.classify || false,
    category: previous?.category || "",
    tagIds: previous?.tagIds || [],
    newTagIds: previous?.newTagIds || [],
    favoriteFolderIds: previous?.favoriteFolderIds || [],
  };
  const oldItems = new Map((previous?.items || []).map((item) => [item.item_id, item]));
  const selected = new Set(state.linkQuerySelectedIds || []);
  (query.items || []).forEach((item) => {
    const oldItem = oldItems.get(item.item_id);
    if (item.selectable && (!oldItem || oldItem.status === "pending")) selected.add(item.item_id);
  });
  state.linkQuerySelectedIds = selected;
  return query;
}

function scheduleLinkQueryPoll(requestId, queryId) {
  clearLinkQueryPolling();
  state.linkQueryPollTimer = window.setTimeout(
    () => void pollLinkQuery(requestId, queryId),
    700,
  );
}

async function pollLinkQuery(requestId, queryId) {
  if (requestId !== state.linkQueryRequestId || state.linkQuery?.query_id !== queryId) return;
  try {
    const snapshot = await api(`/api/v1/imports/query/${encodeURIComponent(queryId)}`);
    if (requestId !== state.linkQueryRequestId || state.linkQuery?.query_id !== queryId) return;
    const query = mergeLinkQuerySnapshot(snapshot, state.linkQuery);
    query.error = "";
    state.linkQuery = query;
    renderLinkQueryDialog(query);
    if (linkQueryIsProcessing(query)) {
      scheduleLinkQueryPoll(requestId, queryId);
      return;
    }
    clearLinkQueryPolling();
    const automaticItem = automaticCollectionItem(query);
    query.auto_scan_started = Boolean(automaticItem);
    if (automaticItem && !state.autoScannedQueryIds.has(query.query_id)) {
      state.autoScannedQueryIds.add(query.query_id);
      void startCollectionScan(automaticItem.source_type, automaticItem.input_url, false, automaticItem.platform);
    }
    renderLinkQueryDialog(query);
    showNotice(
      query.status === "timed_out"
        ? "查询已截止，成功项仍可提交；请重试超时项"
        : query.status === "cancelled"
          ? "查询已取消，成功项仍可提交"
          : "查询完成，请逐项检查后确认提交",
      query.status === "timed_out" || query.status === "cancelled",
    );
  } catch (error) {
    if (requestId !== state.linkQueryRequestId || state.linkQuery?.query_id !== queryId) return;
    state.linkQuery = { ...state.linkQuery, error: error.message || "读取查询进度失败" };
    renderLinkQueryDialog(state.linkQuery);
    scheduleLinkQueryPoll(requestId, queryId);
  }
}

function isConfigurationError(error) {
  const message = String(error?.message || "");
  return /配置|模型|ASR|API Key|授权|登录|密钥|凭据/i.test(message);
}

function appendSettingsRecovery(shell, message, source = "link") {
  if (!shell || shell.querySelector(".configuration-recovery")) return;
  const warning = document.createElement("div");
  warning.className = "configuration-recovery is-warning";
  const text = document.createElement("span");
  text.textContent = message || "提交前还缺少必要配置。";
  const action = document.createElement("button");
  action.type = "button";
  action.className = "button button-small";
  action.textContent = "前往设置";
  action.addEventListener("click", () => {
    state.settingsReturnNeedsQuery = source;
    showView("settings");
  });
  warning.append(text, action);
  shell.prepend(warning);
}

function updateTagPickerInputWidth(input) {
  if (!input) return;
  const length = [...(input.value || "")].length;
  input.style.width = `${Math.min(220, Math.max(88, length * 14 + 32))}px`;
}

function renderIntakeTagPicker(query, rerender) {
  const section = document.createElement("section");
  section.className = "intake-tag-picker";
  const heading = document.createElement("div");
  heading.className = "intake-picker-heading";
  const title = document.createElement("span");
  title.textContent = "标签";

  const row = document.createElement("div");
  row.className = "intake-tag-picker-row";
  const selected = document.createElement("div");
  selected.className = "intake-tag-selected";
  const input = document.createElement("input");
  input.type = "text";
  input.className = "tag-picker-input";
  input.placeholder = "输入或选择标签";
  input.autocomplete = "off";
  updateTagPickerInputWidth(input);
  selected.append(input);
  const suggestions = document.createElement("div");
  suggestions.className = "tag-picker-suggestions";
  suggestions.hidden = true;
  const field = document.createElement("div");
  field.className = "intake-tag-field";
  field.append(selected, suggestions);

  const candidateViewport = document.createElement("div");
  candidateViewport.className = "tag-picker-candidate-viewport";
  const candidates = document.createElement("div");
  candidates.className = "tag-picker-candidates";
  candidateViewport.append(candidates);
  const add = document.createElement("button");
  add.type = "button";
  add.className = "button button-small tag-picker-add";
  add.textContent = "+";
  add.title = "新建标签";
  add.setAttribute("aria-label", "新建标签");
  add.addEventListener("click", async () => {
    await createTag({
      selectInLibrary: false,
      onCreated: async (tag) => {
        query.tagIds = [...new Set([...(query.tagIds || []), tag.id])];
        query.newTagIds = [...new Set([...(query.newTagIds || []), tag.id])];
        if (rerender) rerender();
      },
    });
  });
  row.append(field, add);
  heading.append(title, row);
  const candidateRow = document.createElement("div");
  candidateRow.className = "intake-tag-picker-candidates-row";
  candidateRow.append(candidateViewport);

  const renderSelected = () => {
    selected.replaceChildren();
    const selectedIds = new Set(query.tagIds || []);
    (state.tags || []).filter((tag) => selectedIds.has(tag.id)).forEach((tag) => {
      const chip = document.createElement("span");
      chip.className = "tag-picker-chip";
      chip.textContent = tag.name;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "tag-picker-chip-remove";
      remove.textContent = "×";
      remove.setAttribute("aria-label", `移除标签 ${tag.name}`);
      remove.addEventListener("click", () => {
        query.tagIds = (query.tagIds || []).filter((id) => id !== tag.id);
        renderSelected();
        renderCandidates();
      });
      chip.append(remove);
      selected.append(chip);
    });
    selected.append(input);
    updateTagPickerInputWidth(input);
  };

  const selectTag = (tag) => {
    query.tagIds = [...new Set([...(query.tagIds || []), tag.id])];
    query.newTagIds = (query.newTagIds || []).filter((id) => id !== tag.id);
    input.value = "";
    suggestions.hidden = true;
    renderSelected();
    renderCandidates();
    input.focus();
  };

  const renderCandidates = () => {
    candidates.replaceChildren();
    const selectedIds = new Set(query.tagIds || []);
    (state.tags || []).forEach((tag) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "tag-picker-candidate";
      if (selectedIds.has(tag.id)) button.classList.add("is-selected");
      if ((query.newTagIds || []).includes(tag.id)) button.classList.add("is-new");
      button.textContent = tag.name;
      button.addEventListener("click", () => selectTag(tag));
      candidates.append(button);
    });
  };

  input.addEventListener("input", () => {
    updateTagPickerInputWidth(input);
    const needle = input.value.trim().toLocaleLowerCase();
    suggestions.replaceChildren();
    const matches = needle
      ? (state.tags || []).filter((tag) => tag.name.toLocaleLowerCase().includes(needle))
      : [];
    matches.slice(0, 8).forEach((tag) => {
      const option = document.createElement("button");
      option.type = "button";
      option.className = "tag-picker-suggestion";
      option.textContent = tag.name;
      option.addEventListener("click", () => selectTag(tag));
      suggestions.append(option);
    });
    suggestions.hidden = !matches.length;
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      suggestions.hidden = true;
      input.value = "";
      updateTagPickerInputWidth(input);
    }
  });

  renderSelected();
  renderCandidates();
  section.append(heading, candidateRow);
  return section;
}

function renderIntakeFolderPicker(query, rerender) {
  const section = document.createElement("section");
  section.className = "intake-folder-picker";
  const heading = document.createElement("div");
  heading.className = "intake-picker-heading";
  const title = document.createElement("span");
  title.textContent = "收藏夹";
  heading.append(title);
  const list = document.createElement("div");
  list.className = "intake-folder-options";
  const selectedIds = new Set(query.favoriteFolderIds || []);
  (state.favoriteFolders || []).filter((folder) => !folder.is_system).forEach((folder) => {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = folder.id;
    input.checked = selectedIds.has(folder.id);
    input.addEventListener("change", () => {
      query.favoriteFolderIds = [...list.querySelectorAll("input:checked")].map((item) => item.value);
    });
    label.append(input, document.createTextNode(folder.name));
    list.append(label);
  });
  const add = document.createElement("button");
  add.type = "button";
  add.className = "button button-small";
  add.textContent = "+ 新建收藏夹";
  add.addEventListener("click", async () => {
    const name = await openProductTextDialog({
      title: "新建收藏夹",
      label: "收藏夹名称",
      placeholder: "例如：重点课程",
      confirmLabel: "创建收藏夹",
    });
    if (!name) return;
    try {
      const folder = await api("/api/v1/favorite-folders", {
        method: "POST",
        body: JSON.stringify({ name }),
      });
      state.favoriteFolders = [...state.favoriteFolders, folder];
      query.favoriteFolderIds = [folder.id];
      if (rerender) rerender();
    } catch (error) {
      showNotice(error.message, true);
    }
  });
  section.append(heading, list, add);
  return section;
}

function closeTaskSuccessDialog() {
  if (!taskSuccessDialog) return;
  if (taskSuccessDialog.open) taskSuccessDialog.close();
  taskSuccessDialog.replaceChildren();
}

function showTaskSuccessDialog(report, first = null) {
  if (!taskSuccessDialog || !first) return;
  const accepted = report.accepted || [];
  const failed = report.failed || [];
  taskSuccessDialog.replaceChildren();
  const shell = document.createElement("div");
  shell.className = "task-success-dialog-shell";
  const heading = document.createElement("h2");
  heading.id = "task-success-title";
  heading.textContent = "已加入任务栏";
  const message = document.createElement("p");
  message.className = "task-success-dialog-message";
  message.textContent = failed.length
    ? `已加入 ${accepted.length} 条任务，${failed.length} 条失败，可返回查询结果重试。`
    : `已加入 ${accepted.length} 条任务，当前任务将按队列顺序处理。`;
  const actions = document.createElement("div");
  actions.className = "actions task-success-dialog-actions";
  const view = document.createElement("button");
  view.type = "button";
  view.className = "button button-primary";
  view.textContent = "查看";
  view.addEventListener("click", async () => {
    closeTaskSuccessDialog();
    await loadTaskList();
    showView("tasks");
  });
  const confirm = document.createElement("button");
  confirm.type = "button";
  confirm.className = "button";
  confirm.textContent = "确认";
  confirm.addEventListener("click", () => {
    closeTaskSuccessDialog();
    if (failed.length && state.linkQuery) renderLinkQueryDialog(state.linkQuery);
  });
  actions.append(view, confirm);
  shell.append(heading, message, actions);
  taskSuccessDialog.append(shell);
  taskSuccessDialog.oncancel = (event) => {
    event.preventDefault();
    closeTaskSuccessDialog();
    if (failed.length && state.linkQuery) renderLinkQueryDialog(state.linkQuery);
  };
  if (typeof taskSuccessDialog.showModal === "function") taskSuccessDialog.showModal();
  else taskSuccessDialog.open = true;
}

function renderIntakeClassificationPickers(query, rerender) {
  const row = document.createElement("div");
  row.className = "intake-classification-row";
  row.append(
    renderIntakeTagPicker(query, rerender),
    renderIntakeFolderPicker(query, rerender),
  );
  return row;
}

function renderLinkQueryDialog(query) {
  if (!linkQueryDialog) return;
  linkQueryDialog.classList.remove("creator-scan-dialog");
  const items = Array.isArray(query?.items) ? query.items : [];
  const selectableIds = new Set(items.filter((item) => item.selectable).map((item) => item.item_id));
  if (!(state.linkQuerySelectedIds instanceof Set)) {
    state.linkQuerySelectedIds = new Set(selectableIds);
  } else {
    state.linkQuerySelectedIds = new Set(
      [...state.linkQuerySelectedIds].filter((itemId) => selectableIds.has(itemId)),
    );
  }

  linkQueryDialog.replaceChildren();
  const shell = document.createElement("div");
  shell.className = "link-query-shell";
  const header = document.createElement("header");
  header.className = "link-query-header";
  const title = document.createElement("h2");
  title.id = "link-query-title";
  title.textContent = query?.loading && !query?.query_id ? "正在识别链接" : "确认导入内容";
  const close = document.createElement("button");
  close.type = "button";
  close.className = "creator-scan-close";
  close.textContent = "关闭";
  close.addEventListener("click", () => void cancelLinkQuery());
  header.append(title, close);
  shell.append(header);
  if (state.favoriteAddContext?.folderId) {
    const target = favoriteAddTargetFolder();
    const back = document.createElement("button");
    back.type = "button";
    back.className = "button button-small";
    back.textContent = "返回添加视频";
    back.addEventListener("click", () => renderFavoriteContentAddDialog({ mode: "link" }));
    header.insertBefore(back, title);
    const targetHint = document.createElement("p");
    targetHint.className = "link-query-summary";
    targetHint.textContent = `目标收藏夹：${target?.name || "当前收藏夹"}`;
    shell.append(targetHint);
  }

  if ((query?.loading && !query?.query_id) || (query?.error && !query?.query_id)) {
    const summary = document.createElement("div");
    summary.className = "link-query-summary is-loading";
    summary.textContent = query.error || "正在识别链接并读取标题、封面和来源信息…";
    const loadingList = document.createElement("div");
    loadingList.className = "link-query-list link-query-loading-list";
    const count = Math.min(Math.max(items.length, 1), 3);
    for (let index = 0; index < count; index += 1) {
      const row = document.createElement("article");
      row.className = "link-query-loading-item";
      row.innerHTML = "<span class=\"link-query-loading-cover\"></span><span class=\"link-query-loading-copy\"><i></i><i></i><i></i></span>";
      loadingList.append(row);
    }
    shell.append(summary, loadingList);
    const footer = document.createElement("footer");
    footer.className = "link-query-footer";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "button";
    cancel.textContent = "关闭";
    cancel.addEventListener("click", () => void cancelLinkQuery());
    footer.append(cancel);
    if (query.error) {
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "button button-primary";
      retry.textContent = "重新查询";
      retry.addEventListener("click", () => queryLinks());
      footer.append(retry);
    }
    shell.append(footer);
    linkQueryDialog.append(shell);
    setLinkQueryDialogOpen(true);
    return;
  }

  const readyCount = items.filter((item) => item.selectable).length;
  const pendingCount = items.filter((item) => item.status === "pending").length;
  const failedCount = items.filter((item) => linkQueryIsRetryable(item)).length;
  const summary = document.createElement("div");
  summary.className = "link-query-summary";
  const summaryText = document.createElement("span");
  const statusHint = query?.status === "processing"
    ? `正在查询 ${pendingCount} 项`
    : query?.status === "timed_out"
      ? "已达到 180 秒截止"
      : query?.status === "cancelled"
        ? "查询已取消"
        : "查询完成";
  summaryText.textContent = `${statusHint} · 共 ${items.length} 项 · 可提交 ${readyCount} 项 · 需处理 ${failedCount} 项`;
  if (query?.error) {
    const errorHint = document.createElement("p");
    errorHint.className = "field-hint is-error";
    errorHint.textContent = query.error;
    shell.append(errorHint);
  }
  const selectAll = document.createElement("button");
  selectAll.type = "button";
  selectAll.className = "button button-small link-query-select-all";
  selectAll.textContent = "全选";
  const syncSelectAll = () => {
    const selectableInputs = [...list.querySelectorAll("input[data-query-item-id]:not(:disabled)")];
    const allSelected = selectableInputs.length > 0
      && selectableInputs.every((input) => input.checked);
    selectAll.textContent = allSelected ? "取消全选" : "全选";
    selectAll.disabled = selectableInputs.length === 0;
  };
  selectAll.addEventListener("click", () => {
    const selectableInputs = [...list.querySelectorAll("input[data-query-item-id]:not(:disabled)")];
    const shouldSelect = !selectableInputs.length || !selectableInputs.every((input) => input.checked);
    selectableInputs.forEach((input) => {
      input.checked = shouldSelect;
      if (shouldSelect) state.linkQuerySelectedIds.add(input.dataset.queryItemId);
      else state.linkQuerySelectedIds.delete(input.dataset.queryItemId);
    });
    const submit = linkQueryDialog.querySelector("#confirm-link-query");
    if (submit) submit.disabled = !state.linkQuerySelectedIds.size;
    syncSelectAll();
  });
  summary.append(summaryText, selectAll);
  shell.append(summary);

  const list = document.createElement("div");
  list.className = "link-query-list";
  items.forEach((item) => {
    const row = document.createElement("article");
    row.className = `link-query-item is-${item.status}`;
    const select = document.createElement("input");
    select.type = "checkbox";
    select.dataset.queryItemId = item.item_id;
    select.checked = state.linkQuerySelectedIds.has(item.item_id);
    select.disabled = !item.selectable;
    select.setAttribute("aria-label", `选择${item.title || item.input_url}`);
    select.addEventListener("change", (event) => {
      if (event.target.checked) state.linkQuerySelectedIds.add(item.item_id);
      else state.linkQuerySelectedIds.delete(item.item_id);
      const submit = linkQueryDialog.querySelector("#confirm-link-query");
      if (submit) submit.disabled = !linkQueryDialog.querySelector("input[data-query-item-id]:checked");
      syncSelectAll();
    });

    const cover = createSourceCover({
      title: item.title || item.input_url,
      thumbnail: item.thumbnail_url,
      platform: item.platform,
      className: "link-query-cover",
    });

    const body = document.createElement("div");
    body.className = "link-query-item-body";
    const itemTitle = document.createElement("strong");
    itemTitle.className = "link-query-item-title";
    itemTitle.textContent = item.title || item.input_url;
    itemTitle.title = item.title || item.input_url;
    const meta = document.createElement("span");
    meta.className = "link-query-item-meta";
    meta.textContent = [
      item.platform ? platformLabel(item.platform) : "未知来源",
      item.author || null,
      item.duration_seconds ? formatDuration(item.duration_seconds) : null,
      linkQueryStatusLabel(item),
    ].filter(Boolean).join(" · ");
    body.append(itemTitle, meta);
    const url = document.createElement("a");
    url.href = item.source_url || item.input_url;
    url.target = "_blank";
    url.rel = "noreferrer";
    url.textContent = "打开来源";
    url.addEventListener("click", (event) => event.stopPropagation());
    body.append(url);
    if (item.reason) {
      const reason = document.createElement("p");
      reason.className = "link-query-item-reason";
      reason.textContent = item.reason;
      body.append(reason);
    }
    row.classList.add("link-query-selectable");
    row.tabIndex = item.selectable ? 0 : -1;
    const toggle = () => {
      if (select.disabled) return;
      select.checked = !select.checked;
      select.dispatchEvent(new Event("change", { bubbles: true }));
    };
    row.addEventListener("click", (event) => {
      if (event.target.closest("a, input, button")) return;
      toggle();
    });
    row.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      toggle();
    });
    select.addEventListener("click", (event) => event.stopPropagation());
    row.append(select, cover, body);
    list.append(row);
  });
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "field-hint";
    empty.textContent = "没有可展示的查询结果，请返回输入区重试。";
    list.append(empty);
  }
  shell.append(list);
  syncSelectAll();

  shell.append(
    renderIntakeClassificationPickers(
      state.linkQuery,
      () => renderLinkQueryDialog(state.linkQuery),
    ),
  );

  const footer = document.createElement("footer");
  footer.className = "link-query-footer";
  const retry = document.createElement("button");
  retry.type = "button";
  retry.className = "button";
  retry.textContent = failedCount ? "重新查询失败项" : "重新查询";
  retry.disabled = !failedCount;
  retry.addEventListener("click", () => {
    retryLinkUrls(
      items
        .filter((item) => linkQueryIsRetryable(item))
        .map((item) => item.input_url),
    );
  });
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "button";
  cancel.textContent = "稍后处理";
  cancel.addEventListener("click", () => void cancelLinkQuery());
  const submit = document.createElement("button");
  submit.id = "confirm-link-query";
  submit.type = "button";
  submit.className = "button button-primary";
  submit.textContent = "确认提交";
  submit.disabled = !state.linkQuerySelectedIds.size;
  submit.addEventListener("click", () => confirmLinkQuery(submit));
  if (!linkQueryIsProcessing(query) && !query.auto_scan_started) {
    items
      .filter((item) => item.status === "collection" || (
        item.status === "failed"
        && ["creator", "favorite", "watchlater"].includes(item.source_type)
      ))
      .forEach((item) => {
        const scan = document.createElement("button");
        scan.type = "button";
        scan.className = "button";
        scan.textContent = item.platform === "zhihu" ? "扫描前 10 条候选" : `扫描${collectionSourceLabel(item.source_type)}`;
        scan.addEventListener("click", () => startCollectionScan(item.source_type, item.input_url, false, item.platform));
        footer.append(scan);
      });
  }
  footer.append(retry, cancel, submit);
  shell.append(footer);
  linkQueryDialog.append(shell);
  setLinkQueryDialogOpen(true);
}

function renderLocalQueryDialog(query) {
  if (!linkQueryDialog) return;
  linkQueryDialog.classList.remove("creator-scan-dialog");
  linkQueryDialog.replaceChildren();
  const shell = document.createElement("div");
  shell.className = "link-query-shell local-query-shell";
  const header = document.createElement("header");
  header.className = "link-query-header";
  const title = document.createElement("h2");
  title.id = "link-query-title";
  title.textContent = "确认本地内容";
  const close = document.createElement("button");
  close.type = "button";
  close.className = "creator-scan-close";
  close.textContent = "关闭";
  close.addEventListener("click", () => setLinkQueryDialogOpen(false));
  header.append(title, close);
  shell.append(header);

  const summary = document.createElement("p");
  summary.className = "link-query-summary";
  summary.textContent = "本地来源已读取；请确认文件、文本和归类设置后再创建任务。";
  shell.append(summary);

  const list = document.createElement("div");
  list.className = "link-query-list local-query-list";
  const item = document.createElement("article");
  item.className = "link-query-item is-ready";
  const select = document.createElement("input");
  select.type = "checkbox";
  select.checked = true;
  select.disabled = true;
  select.setAttribute("aria-label", "选择本地内容");
  const cover = createSourceCover({
    title: query.fileName || query.sourcePath || "粘贴的本地文本",
    platform: "local",
    className: "link-query-cover local-query-cover",
  });
  const body = document.createElement("div");
  body.className = "link-query-item-body";
  const itemTitle = document.createElement("strong");
  itemTitle.className = "link-query-item-title";
  itemTitle.textContent = query.fileName || query.sourcePath || "粘贴的本地文本";
  itemTitle.title = itemTitle.textContent;
  const meta = document.createElement("span");
  meta.className = "link-query-item-meta";
  meta.textContent = [
    "本地来源",
    query.sourcePath ? "文件路径" : "文本内容",
    query.preflight?.ready ? "可提交" : "需处理",
  ].join(" · ");
  body.append(itemTitle, meta);
  if (query.sourcePath) {
    const path = document.createElement("span");
    path.className = "link-query-item-path";
    path.textContent = query.sourcePath;
    body.append(path);
  }
  if (query.text) {
    const textPreview = document.createElement("p");
    textPreview.className = "link-query-item-reason local-query-preview";
    textPreview.textContent = query.text.replace(/\s+/g, " ").slice(0, 180);
    body.append(textPreview);
  }
  item.append(select, cover, body);
  list.append(item);
  shell.append(list);

  shell.append(
    renderIntakeClassificationPickers(query, () => renderLocalQueryDialog(query)),
  );
  const footer = document.createElement("footer");
  footer.className = "link-query-footer";
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "button";
  cancel.textContent = "返回修改";
  cancel.addEventListener("click", () => setLinkQueryDialogOpen(false));
  const submit = document.createElement("button");
  submit.type = "button";
  submit.id = "confirm-local-query";
  submit.className = "button button-primary";
  submit.textContent = "确认创建任务";
  submit.disabled = Boolean(query.preflight && !query.preflight.ready);
  submit.addEventListener("click", () => confirmLocalQuery(submit));
  footer.append(cancel, submit);
  shell.append(footer);
  linkQueryDialog.append(shell);
  setLinkQueryDialogOpen(true);
}

async function queryLocalSource() {
  const text = document.querySelector("#source-text")?.value || "";
  const sourcePath = document.querySelector("#source-path")?.value.trim() || "";
  const sourceUrl = sourceUrlInput?.value.trim() || "";
  if (sourceUrl) {
    showNotice("请先清空链接，再查询本地来源", true);
    return;
  }
  if (!text.trim() && !sourcePath) {
    showNotice("请先选择文件、填写本地路径或粘贴文本", true);
    return;
  }
  if (text.trim() && sourcePath) {
    showNotice("本地文本和文件路径只能选择一种来源", true);
    return;
  }
  const actionButton = state.intakeMode === "local" ? importSubmitButton : queryLocalButton;
  if (actionButton) {
    actionButton.disabled = true;
    actionButton.textContent = "检查中…";
  }
  try {
    const preflight = await runTaskPreflight(buildTaskPreflightPayload({ text, sourcePath }));
    state.localQuery = {
      text,
      sourcePath,
      fileName: state.localFileName,
      preflight,
      classify: false,
      category: "",
      tagIds: [],
      newTagIds: [],
      favoriteFolderIds: [],
    };
    await Promise.allSettled([loadHistoryCategories(), loadFavoriteFolders(), loadTags()]);
    renderLocalQueryDialog(state.localQuery);
    if (!preflight.ready) {
      appendSettingsRecovery(
        linkQueryDialog.querySelector(".local-query-shell"),
        "提交前检查未通过，请先补齐设置后再确认创建任务。",
        "local",
      );
    }
    if (preflight.ready) {
      showNotice("本地来源查询完成，请确认后提交");
    } else {
      showNotice("本地来源检查未通过，请先补齐设置", true);
    }
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    if (actionButton) {
      actionButton.disabled = false;
      actionButton.textContent = "查询";
    }
    syncImportAction();
  }
}

async function confirmLocalQuery(button) {
  if (!state.localQuery) return;
  const classify = Boolean(state.localQuery.tagIds?.length || state.localQuery.favoriteFolderIds?.length);
  const category = null;
  const tagIds = [...(state.localQuery.tagIds || [])];
  const favoriteFolderIds = [...(state.localQuery.favoriteFolderIds || [])];
  button.disabled = true;
  try {
    const result = await api("/api/v1/imports/local", {
      method: "POST",
      body: JSON.stringify({
        text: state.localQuery.text || null,
        source_path: state.localQuery.sourcePath || null,
        summary_style: document.querySelector("#summary-style").value,
        strength: document.querySelector("#summary-strength").value,
        classify,
        category: classify ? category : null,
        tag_ids: classify ? tagIds : [],
        favorite_folder_ids: classify ? favoriteFolderIds : [],
      }),
    });
    state.localQuery = null;
    state.localFileName = "";
    state.activeJobId = result.job.id;
    state.activeContentId = result.content.id;
    state.activeJobTitle = result.content.title;
    state.activeContentSnapshot = result.content;
    renderJob(result.job, state.activeJobTitle, result.content);
    setLinkQueryDialogOpen(false);
    showView("intake");
    await loadTaskList();
    showTaskSuccessDialog({ accepted: [result], failed: [] }, result);
    pollJob();
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    if (button && linkQueryDialog.open) button.disabled = false;
  }
}

async function queryLinks(urlsOverride = null, { preserveInput = false } = {}) {
  const previousQueryId = state.linkQuery?.query_id;
  if (previousQueryId && typeof cancelLinkQuerySession === "function") {
    void cancelLinkQuerySession(previousQueryId);
  }
  if (typeof clearLinkQueryPolling === "function") clearLinkQueryPolling();
  const urls = urlsOverride ? parseLinkInput(urlsOverride.join("\n")) : parseLinkInput(sourceUrlInput.value);
  if (state.pendingCollectionScan && !urlsOverride) {
    if (urls.length !== 1) {
      state.linkQuery = null;
      state.linkQuerySelectedIds = new Set();
      setLinkQueryDialogOpen(false);
      showNotice(urls.length ? "收藏扫描一次只支持一个链接" : "请先输入一个收藏夹链接", true);
      return;
    }
    const pending = state.pendingCollectionScan;
    state.pendingCollectionScan = null;
    void startCollectionScan(pending.sourceType, urls[0], false, pending.platform);
    return;
  }
  if (!urls.length) {
    state.linkQueryRequestId += 1;
    state.linkQuery = null;
    setLinkQueryDialogOpen(false);
    showNotice("请先在链接框中输入链接", true);
    return;
  }
  if (urls.length > 50) {
    state.linkQueryRequestId += 1;
    state.linkQuery = null;
    setLinkQueryDialogOpen(false);
    showNotice("一次最多查询 50 条链接", true);
    return;
  }
  const requestId = ++state.linkQueryRequestId;
  const rawInput = preserveInput ? urls.join("\n") : sourceUrlInput.value.trim();
  const actionButton = state.intakeMode === "link" ? importSubmitButton : queryLinksButton;
  if (actionButton) {
    actionButton.disabled = true;
    actionButton.textContent = "逐条校验中…";
  }
  state.linkQuery = {
    query_id: null,
    items: urls.map((url, index) => ({ item_id: `pending-${index}`, input_url: url })),
    rawInput,
    collection_import: preserveInput,
    loading: true,
    error: "",
    classify: false,
    category: "",
    tagIds: [],
    newTagIds: [],
    favoriteFolderIds: [],
  };
  state.linkQuerySelectedIds = new Set();
  renderLinkQueryDialog(state.linkQuery);
  try {
    const query = await api("/api/v1/imports/query", {
      method: "POST",
      body: JSON.stringify({ urls }),
    });
    if (requestId !== state.linkQueryRequestId) return;
    query.rawInput = rawInput;
    query.collection_import = preserveInput;
    query.classify = false;
    query.category = "";
    query.tagIds = [];
    query.newTagIds = [];
    query.favoriteFolderIds = [];
    if (state.favoriteAddContext?.folderId) {
      query.favoriteFolderIds = [state.favoriteAddContext.folderId];
      query.favorite_add = true;
    }
    query.loading = false;
    query.error = "";
    state.linkQuery = query;
    state.linkQuerySelectedIds = new Set(
      (query.items || []).filter((item) => item.selectable).map((item) => item.item_id),
    );
    await Promise.allSettled([loadHistoryCategories(), loadFavoriteFolders(), loadTags()]);
    renderLinkQueryDialog(query);
    const processing = query.status === "processing"
      || (query.items || []).some((item) => item.status === "pending");
    if (processing) {
      if (typeof scheduleLinkQueryPoll === "function") {
        scheduleLinkQueryPoll(requestId, query.query_id);
      }
      if (queryLinksButton) queryLinksButton.textContent = "查询中…";
      showNotice("已开始逐项查询，可等待完成或取消");
      return;
    }
    const automaticItem = automaticCollectionItem(query);
    query.auto_scan_started = Boolean(automaticItem);
    state.linkQuery = query;
    if (automaticItem && !state.autoScannedQueryIds.has(query.query_id)) {
      state.autoScannedQueryIds.add(query.query_id);
      void startCollectionScan(automaticItem.source_type, automaticItem.input_url, false, automaticItem.platform);
    }
    if (queryLinksButton) queryLinksButton.textContent = "打开确认";
    showNotice("查询完成，请逐项检查后确认提交");
  } catch (error) {
    if (requestId !== state.linkQueryRequestId) return;
    state.linkQuery = {
      ...state.linkQuery,
      loading: false,
      error: error.message || "链接查询失败，请重试",
      items: [],
    };
    renderLinkQueryDialog(state.linkQuery);
    showNotice(error.message, true);
  } finally {
    if (actionButton && requestId === state.linkQueryRequestId) {
      actionButton.disabled = false;
      actionButton.textContent = "查询";
    }
    syncImportAction();
  }
}

function updateLinkQueryAfterConfirm(report) {
  if (!state.linkQuery) return;
  const acceptedUrls = new Set(
    (report.accepted || []).map((item) => item.content?.canonical_url).filter(Boolean),
  );
  const skippedUrls = new Set(report.skipped || []);
  const failures = new Map((report.failed || []).map((item) => [item.url, item.reason]));
  const remaining = (state.linkQuery.items || [])
    .filter((item) => !acceptedUrls.has(item.source_url) && !skippedUrls.has(item.source_url))
    .map((item) => {
      const reason = failures.get(item.input_url);
      if (reason) return { ...item, status: "failed", selectable: false, reason };
      return item;
    });
  state.linkQuery.items = remaining;
  state.linkQuerySelectedIds = new Set(remaining.filter((item) => item.selectable).map((item) => item.item_id));
}

function clearCompletedLinkInputs(report) {
  const query = state.linkQuery;
  if (!query?.rawInput || query.collection_import || query.favorite_add) return;
  const accepted = new Set(
    (report.accepted || []).map((item) => item.content?.canonical_url).filter(Boolean),
  );
  const skipped = new Set(report.skipped || []);
  const failed = new Set((report.failed || []).map((item) => item.url));
  const byInput = new Map();
  (query.items || []).forEach((item) => {
    if (!byInput.has(item.input_url)) byInput.set(item.input_url, []);
    byInput.get(item.input_url).push(item);
  });
  const completedInputs = new Set();
  byInput.forEach((items, inputUrl) => {
    if (failed.has(inputUrl) || !items.length) return;
    if (items.every((item) => accepted.has(item.source_url) || skipped.has(item.source_url))) {
      completedInputs.add(inputUrl);
    }
  });
  if (!completedInputs.size) return;
  sourceUrlInput.value = query.rawInput
    .split(/\r?\n/)
    .filter((line) => !completedInputs.has(line.trim()))
    .join("\n")
    .trim();
  updateLinkHint();
  updateInputPanelSummary();
}

function restoreCollectionImportContext() {
  const context = state.collectionImportContext;
  if (!context) return;
  state.collectionImportContext = null;
  state.linkQuery = context.query;
  state.linkQuerySelectedIds = new Set(context.selectedIds || []);
  sourceUrlInput.value = context.rawInput || "";
  updateLinkHint();
  updateInputPanelSummary();
}

function isExpiredLinkQueryError(error) {
  return error?.code === "link_query_expired"
    || error?.message === "link_query_expired";
}

function recoverFromExpiredLinkQuery() {
  state.linkQueryRequestId += 1;
  state.linkQuery = null;
  state.linkQuerySelectedIds = new Set();
  state.collectionImportContext = null;
  if (state.favoriteAddContext?.folderId) {
    closeFavoriteAddDialog();
  } else {
    setLinkQueryDialogOpen(false);
  }
  showView("intake");
  updateLinkHint();
  syncImportAction();
  updateInputPanelSummary();
}

async function confirmLinkQuery(button) {
  const itemIds = [...linkQueryDialog.querySelectorAll("input[data-query-item-id]:checked")]
    .map((input) => input.dataset.queryItemId)
    .filter(Boolean);
  if (!itemIds.length) {
    showNotice("请至少选择一条查询通过的内容", true);
    return;
  }
  const favoriteAddContext = state.favoriteAddContext?.folderId
    ? { ...state.favoriteAddContext }
    : null;
  const category = null;
  const tagIds = [...(state.linkQuery?.tagIds || [])];
  const favoriteFolderIds = [...new Set([
    ...(state.linkQuery?.favoriteFolderIds || []),
    ...(favoriteAddContext?.folderId ? [favoriteAddContext.folderId] : []),
  ])];
  const classify = Boolean(tagIds.length || favoriteFolderIds.length);
  state.linkQuery.classify = classify;
  state.linkQuery.category = category || "";
  state.linkQuery.tagIds = tagIds;
  state.linkQuery.favoriteFolderIds = favoriteFolderIds;
  button.disabled = true;
  try {
    const report = await api("/api/v1/imports/query/confirm", {
      method: "POST",
      body: JSON.stringify({
        query_id: state.linkQuery.query_id,
        item_ids: itemIds,
        summary_style: document.querySelector("#summary-style").value,
        strength: document.querySelector("#summary-strength").value,
        classify,
        category: classify ? category : null,
        tag_ids: classify ? tagIds : [],
        favorite_folder_ids: classify ? favoriteFolderIds : [],
      }),
    });
    clearCompletedLinkInputs(report);
    updateLinkQueryAfterConfirm(report);
    if (report.accepted?.length) {
      if (favoriteAddContext?.folderId) {
        const associationFailures = report.association_failures || [];
        const failedUrls = (report.failed || [])
          .map((item) => item.url)
          .filter(Boolean);
        setFavoriteAddFailedLinks(favoriteAddContext.folderId, failedUrls);
        const existingAssociationFailures = favoriteAddAssociationFailuresForFolder(
          favoriteAddContext.folderId,
        );
        const associationFailuresByContent = new Map(
          [...existingAssociationFailures, ...associationFailures]
            .map((failure) => [failure.content?.id || failure.job?.id, failure]),
        );
        const unresolvedAssociationFailures = [...associationFailuresByContent.values()];
        state.favoriteAddAssociationFailures = [
          ...(state.favoriteAddAssociationFailures || []).filter(
            (failure) => !(failure.folder_ids || []).includes(favoriteAddContext.folderId),
          ),
          ...unresolvedAssociationFailures,
        ];
        const existingBatchJobIds = state.favoriteAddBatch?.folderId === favoriteAddContext.folderId
          ? state.favoriteAddBatch.jobIds || []
          : [];
        state.favoriteAddBatch = {
          folderId: favoriteAddContext.folderId,
          jobIds: [...new Set([
            ...existingBatchJobIds,
            ...report.accepted.map((item) => item.job.id),
          ])],
        };
        state.activeFavoriteFolderId = favoriteAddContext.folderId;
        state.showingTrash = false;
        state.batchReport = report;
        state.batchJobIds = [...state.favoriteAddBatch.jobIds];
        const recoveryMode = unresolvedAssociationFailures.length
          ? "association-retry"
          : failedUrls.length ? "link-retry" : null;
        state.favoriteAddContext = recoveryMode
          ? {
              ...favoriteAddContext,
              mode: recoveryMode,
              failedUrls,
              loading: false,
              batchJobs: [],
              batchCompleted: false,
            }
          : null;
        setLinkQueryDialogOpen(false);
        showView("history", { preserveReturnContext: true });
        showNotice(
          recoveryMode
            ? `已提交 ${report.accepted.length} 条${failedUrls.length ? `，${failedUrls.length} 条链接待重试` : ""}${unresolvedAssociationFailures.length ? `，${unresolvedAssociationFailures.length} 条未归入收藏夹` : ""}`
            : `已提交 ${report.accepted.length} 条，处理完成后自动归入当前收藏夹`,
          Boolean(report.failed?.length || unresolvedAssociationFailures.length),
        );
        await loadTaskList();
        pollBatchJobs();
        if (recoveryMode) renderFavoriteContentAddDialog({ mode: recoveryMode });
        return;
      }
      if (!report.failed?.length) restoreCollectionImportContext();
      state.batchReport = report;
      state.batchJobIds = report.accepted.map((item) => item.job.id);
      window.clearTimeout(state.batchPollTimer);
      const first = report.accepted[0];
      state.activeJobId = first.job.id;
      state.activeContentId = first.content.id;
      state.activeJobTitle = first.content.title;
      state.activeContentSnapshot = first.content;
      window.clearTimeout(state.pollTimer);
      renderJob(first.job, state.activeJobTitle, first.content);
      setLinkQueryDialogOpen(false);
      showView("intake");
      await loadTaskList();
      showTaskSuccessDialog(report, first);
      pollJob();
    } else if (report.failed?.length) {
      if (favoriteAddContext?.folderId) {
        const failedUrls = report.failed.map((item) => item.url).filter(Boolean);
        setFavoriteAddFailedLinks(favoriteAddContext.folderId, failedUrls);
        state.favoriteAddContext = {
          ...favoriteAddContext,
          mode: "link-retry",
          failedUrls,
          loading: false,
        };
      }
      renderLinkQueryDialog(state.linkQuery);
      showNotice("没有成功创建任务，请处理失败项后重试", true);
    } else {
      if (favoriteAddContext?.folderId) {
        state.favoriteAddContext = null;
        setLinkQueryDialogOpen(false);
        showView("history", { preserveReturnContext: true });
        showNotice("所选内容已跳过，未创建新任务", true);
        return;
      }
      restoreCollectionImportContext();
      setLinkQueryDialogOpen(false);
      showNotice("所选内容已跳过，未创建新任务", true);
    }
  } catch (error) {
    if (isExpiredLinkQueryError(error)) {
      recoverFromExpiredLinkQuery();
      showNotice("查询会话已过期，请重新查询后提交", true);
      return;
    }
    if (isConfigurationError(error)) {
      renderLinkQueryDialog(state.linkQuery);
      appendSettingsRecovery(linkQueryDialog.querySelector(".link-query-shell"), error.message, "link");
      setLinkQueryDialogOpen(true);
    }
    showNotice(error.message, true);
  } finally {
    if (button && linkQueryDialog.open) button.disabled = false;
  }
}

function selectedVideoUrls() {
  const candidates = state.creatorScan?.candidates || [];
  return candidates
    .filter((candidate) => state.creatorSelectedIds?.has(candidate.candidate_id))
    .map((candidate) => candidate.url)
    .filter(Boolean);
}

async function importSelectedVideos(button) {
  const urls = selectedVideoUrls();
  if (state.creatorScan?.platform === "zhihu") {
    if (urls.length !== 1) {
      showNotice("请选择一条知乎回答或文章", true);
      return;
    }
    button.disabled = true;
    const candidate = state.creatorScan.candidates.find((item) => item.url === urls[0]);
    try {
      const read = await requestZhihuShellAction("read_content", { url: urls[0] });
      if (read.status !== "CONNECTED" || !read.content?.text?.trim()) {
        throw new Error(read.message || "知乎原文正文读取失败");
      }
      const result = await api("/api/v1/imports/local", {
        method: "POST",
        body: JSON.stringify({
          zhihu_source: {
            url: candidate.url,
            title: candidate.title || read.content.title || "知乎内容",
            author: candidate.author || read.content.author || null,
            text: read.content.text,
          },
          summary_style: document.querySelector("#summary-style")?.value || "general",
          strength: document.querySelector("#summary-strength")?.value || "standard",
        }),
      });
      state.activeJobId = result.job.id;
      state.activeContentId = result.content.id;
      state.activeJobTitle = result.content.title;
      state.activeContentSnapshot = result.content;
      renderJob(result.job, state.activeJobTitle, result.content);
      closeCreatorScanDialog();
      showView("intake");
      await loadTaskList();
      showTaskSuccessDialog({ accepted: [result], failed: [] }, result);
      pollJob();
    } catch (error) {
      showNotice(error.message, true);
    } finally {
      button.disabled = false;
    }
    return;
  }
  if (!urls.length) {
    showNotice("请先勾选要解析的视频", true);
    return;
  }
  button.disabled = true;
  const parentQuery = state.linkQuery;
  const preserveInput = Boolean(parentQuery && (parentQuery.items || []).length > 1);
  if (preserveInput) {
    state.collectionImportContext = {
      query: parentQuery,
      selectedIds: new Set(state.linkQuerySelectedIds || []),
      rawInput: sourceUrlInput.value.trim(),
    };
  } else {
    sourceUrlInput.value = urls.join("\n");
  }
  state.creatorScanRequestId += 1;
  state.creatorScanId = null;
  window.clearTimeout(state.creatorScanTimer);
  updateLinkHint();
  try {
    await queryLinks(preserveInput ? urls : null, { preserveInput });
  } finally {
    button.disabled = false;
  }
}

function clearSpacePreview() {
  const panel = document.querySelector("#space-preview");
  if (panel) {
    panel.hidden = true;
    panel.replaceChildren();
  }
}

function formatDuration(seconds) {
  const whole = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;
  return minutes > 0 ? minutes + ":" + String(rest).padStart(2, "0") : rest + "秒";
}


function formatTimestamp(value) {
  if (!value) {
    return "未记录";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? String(value)
    : date.toLocaleString("zh-CN", { hour12: false });
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${Math.round(bytes / 1024 ** 2)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${bytes} B`;
}

function updateInputPanelSummary() {
  const summary = document.querySelector("#input-panel-status");
  const text = document.querySelector("#source-text")?.value.trim();
  const path = document.querySelector("#source-path")?.value.trim();
  const url = sourceUrlInput?.value.trim();
  if (summary) {
    summary.textContent = url
      ? `链接待查询 · ${parseLinkInput(url).length} 项`
      : state.localFileName
        ? `已选择本地文件 · ${state.localFileName}`
        : path
          ? "本地路径待查询"
          : text
            ? "本地文本待查询"
            : "等待内容或链接";
  }
  syncImportAction();
}

function clearTaskPreflight() {
  const panel = document.querySelector("#task-preflight");
  if (!panel) return;
  panel.hidden = true;
  panel.className = "task-preflight field-wide";
  panel.replaceChildren();
}

function sourceKindForPreflight({ text, sourcePath, sourceUrl }) {
  if (text.trim()) return { kind: "article", has_transcript: true };
  if (sourceUrl.trim()) {
    const platform = detectLinkPlatform(sourceUrl);
    const needsAsr = ["B站", "YouTube", "抖音"].includes(platform);
    return { kind: needsAsr ? "video" : "article", has_transcript: !needsAsr };
  }
  const extension = sourcePath.toLowerCase().split(/[?#]/)[0].split(".").pop();
  const mediaExtensions = new Set(["mp3", "m4a", "wav", "ogg", "mp4", "mkv", "mov", "webm"]);
  return mediaExtensions.has(extension)
    ? { kind: "video", has_transcript: false }
    : { kind: "article", has_transcript: true };
}

function buildTaskPreflightPayload({ text = "", sourcePath = "", sourceUrl = "" } = {}) {
  const source = sourceKindForPreflight({ text, sourcePath, sourceUrl });
  return {
    ...source,
    text_length: text.trim().length,
    asr_engine: state.settings?.asr_engine || null,
    local_model: state.settings?.asr_local_model || null,
    model: state.settings?.summary_model || null,
    max_chunk_tokens: 800,
    source_url: sourceUrl.trim() || null,
  };
}

function renderTaskPreflight(result) {
  const panel = document.querySelector("#task-preflight");
  if (!panel) return;
  panel.hidden = false;
  panel.className = `task-preflight field-wide ${result.ready ? "is-ready" : "is-blocked"}`;
  panel.replaceChildren();

  const heading = document.createElement("div");
  heading.className = "task-preflight-heading";
  const title = document.createElement("strong");
  title.textContent = result.ready ? "提交前检查通过" : "提交前检查未通过";
  const status = document.createElement("span");
  status.className = "asr-config-badge" + (result.ready ? " is-ready" : "");
  status.textContent = result.ready ? "可以开始" : "需要处理";
  heading.append(title, status);

  const checks = document.createElement("div");
  checks.className = "task-preflight-checks";
  (result.checks || []).forEach((check) => {
    const item = document.createElement("div");
    item.className = "task-preflight-check" + (check.status === "error" ? " is-error" : "");
    const line = document.createElement("span");
    const iconName = check.status === "ok" ? "check" : check.status === "warning" ? "warning" : "error";
    setIconLabel(line, iconName, ` ${check.label}：${check.message}`);
    item.append(line);
    if (check.action) {
      const action = document.createElement("small");
      action.textContent = "建议：" + check.action;
      item.append(action);
    }
    checks.append(item);
  });

  const estimate = result.estimate;
  const estimateLine = document.createElement("div");
  estimateLine.className = "task-preflight-estimate";
  estimateLine.textContent = estimate
    ? `预计耗时 ${formatDuration(estimate.estimated_duration_seconds_min)}–${formatDuration(estimate.estimated_duration_seconds_max)} · 磁盘约 ${formatBytes(estimate.estimated_disk_bytes)} · 内存约 ${estimate.memory_required_mb} MB · 输入约 ${estimate.cloud_input_tokens_min}–${estimate.cloud_input_tokens_max} tokens`
    : "暂时无法估算资源";
  panel.append(heading, checks, estimateLine);
}

async function runTaskPreflight(payload) {
  const panel = document.querySelector("#task-preflight");
  if (panel) {
    panel.hidden = false;
    panel.className = "task-preflight field-wide";
    panel.textContent = "正在检查配置、来源和预计资源…";
  }
  try {
    const result = await api("/api/v1/tasks/preflight", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    renderTaskPreflight(result);
    return result;
  } catch (error) {
    if (panel) {
      panel.className = "task-preflight field-wide is-error";
      panel.textContent = "提交前检查失败：" + error.message;
    }
    return { ready: false, checks: [], estimate: null, error: error.message };
  }
}
const TASK_FEEDBACK_LABELS = {
  accuracy: "结果不准确",
  missing: "缺少内容",
  bug: "执行失败",
  other: "其他",
};

async function submitTaskFeedback(jobId, category, note, button) {
  if (button) button.disabled = true;
  try {
    await api("/api/v1/jobs/" + encodeURIComponent(jobId) + "/feedback", {
      method: "POST",
      body: JSON.stringify({ category, note: note.trim() || null }),
    });
    showNotice("已记录反馈，内容已脱敏保存");
    const panel = document.querySelector("#job-feedback");
    if (panel) panel.dataset.submitted = "true";
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    if (button) button.disabled = false;
  }
}

function renderTaskFeedback(job) {
  const panel = document.createElement("section");
  panel.id = "job-feedback";
  panel.className = "job-feedback";
  const heading = document.createElement("strong");
  heading.textContent = "告诉我们这次任务哪里需要改进";
  const hint = document.createElement("p");
  hint.textContent = "只保存任务状态、失败阶段和版本等脱敏信息，不会保存标题、正文、路径或密钥。";
  const note = document.createElement("textarea");
  note.rows = 2;
  note.maxLength = 2000;
  note.placeholder = "可选：补充问题描述";
  note.setAttribute("aria-label", "任务反馈说明");
  const actions = document.createElement("div");
  actions.className = "actions";
  Object.entries(TASK_FEEDBACK_LABELS).forEach(([category, label]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "button";
    button.textContent = label;
    button.addEventListener("click", () => submitTaskFeedback(job.id, category, note.value, button));
    actions.append(button);
  });
  panel.append(heading, hint, note, actions);
  return panel;
}

const TASK_EVENT_TYPE_LABELS = {
  created: "已创建",
  started: "开始执行",
  progress: "进度更新",
  stage_changed: "阶段更新",
  attempt: "新的尝试",
  requeued: "重新排队",
  resumed: "继续执行",
  paused: "已暂停",
  completed: "已完成",
  failed: "执行失败",
  cancelled: "已取消",
  error: "错误更新",
};

const TASK_EVENT_STAGE_LABELS = {
  queue: "队列",
  source: "来源",
  transcription: "转写",
  chunking: "分段",
  summary: "总结",
  archive: "归档",
  task: "任务",
};

function taskEventTypeLabel(value) {
  return TASK_EVENT_TYPE_LABELS[value] || value || "任务事件";
}

function taskEventStageLabel(value) {
  return TASK_EVENT_STAGE_LABELS[value] || value || "未分阶段";
}

function taskEventAttemptLabel(value) {
  const attempt = Number(value);
  return Number.isFinite(attempt) && attempt > 0 ? `第 ${attempt} 次尝试` : "排队阶段";
}

function taskEventTimestamp(value) {
  if (!value) return "未记录";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? String(value)
    : date.toLocaleString("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
}

function sortedTaskEvents(events) {
  return [...(Array.isArray(events) ? events : [])].sort((left, right) => {
    const leftSequence = Number(left?.sequence);
    const rightSequence = Number(right?.sequence);
    if (Number.isFinite(leftSequence) && Number.isFinite(rightSequence) && leftSequence !== rightSequence) {
      return leftSequence - rightSequence;
    }
    const leftTime = new Date(left?.occurred_at || 0).getTime();
    const rightTime = new Date(right?.occurred_at || 0).getTime();
    if (Number.isFinite(leftTime) && Number.isFinite(rightTime) && leftTime !== rightTime) {
      return leftTime - rightTime;
    }
    return String(left?.id || "").localeCompare(String(right?.id || ""));
  });
}

function isTaskEventFailure(event) {
  return event?.event_type === "failed"
    || event?.event_type === "error"
    || event?.state === "failed"
    || Boolean(event?.error_code);
}

function renderTaskEventList(list, events) {
  if (!list) return;
  list.replaceChildren();
  const orderedEvents = sortedTaskEvents(events);
  if (!orderedEvents.length) {
    const empty = document.createElement("li");
    empty.className = "task-event-empty";
    empty.textContent = "暂无任务事件";
    list.append(empty);
    return;
  }
  const groups = [];
  orderedEvents.forEach((event) => {
    const key = event?.stage || "task";
    let group = groups[groups.length - 1];
    if (!group || group.stage !== key) {
      group = { stage: key, events: [] };
      groups.push(group);
    }
    group.events.push(event);
  });
  groups.forEach((group) => {
    const item = document.createElement("li");
    item.className = "task-event" + (group.events.some(isTaskEventFailure) ? " is-error" : "");
    item.dataset.stage = group.stage;

    const marker = document.createElement("span");
    marker.className = "task-event-marker";
    marker.setAttribute("aria-hidden", "true");

    const body = document.createElement("div");
    body.className = "task-event-body";
    const heading = document.createElement("div");
    heading.className = "task-event-heading";
    const stageTitle = document.createElement("strong");
    stageTitle.textContent = taskEventStageLabel(group.stage);
    const stageCount = document.createElement("span");
    stageCount.className = "task-event-sequence";
    stageCount.textContent = `${group.events.length} 条`;
    heading.append(stageTitle, stageCount);
    body.append(heading);
    group.events.forEach((event) => {
      const line = document.createElement("div");
      line.className = "task-event-log";
      const label = document.createElement("span");
      label.className = "task-event-log-label";
      label.textContent = `${taskEventTypeLabel(event.event_type)} #${event.sequence ?? "?"}`;
      const message = document.createElement("span");
      message.className = "task-event-message";
      message.textContent = event.message || "任务状态已更新";
      const meta = document.createElement("span");
      meta.className = "task-event-meta";
      const progress = Number(event.progress);
      meta.textContent = [
        taskEventTimestamp(event.occurred_at),
        taskEventAttemptLabel(event.attempt),
        event.state ? statusLabel(event.state) : null,
        Number.isFinite(progress) ? `${progress}%` : null,
        event.error_code ? `错误码：${event.error_code}` : null,
      ].filter(Boolean).join(" · ");
      line.append(label, message, meta);
      body.append(line);
    });
    item.append(marker, body);
    list.append(item);
  });
}

function updateTaskTimelinePanel(job = state.activeJobSnapshot) {
  const timeline = document.querySelector("#task-timeline");
  if (!timeline || !job || timeline.dataset.jobId !== String(job.id)) return;
  const events = state.taskEventsJobId === job.id ? sortedTaskEvents(state.taskEvents) : [];
  const list = timeline.querySelector(".task-timeline-list");
  renderTaskEventList(list, events);
  const count = timeline.querySelector(".task-timeline-count");
  if (count) count.textContent = `${events.length} 条`;
  const status = timeline.querySelector(".task-timeline-status");
  if (status) {
    const loading = state.taskEventsLoadingJobId === job.id;
    status.hidden = !loading && !state.taskEventsError && events.length > 0;
    status.textContent = loading
      ? "正在读取任务日志…"
      : state.taskEventsError
        ? `读取任务日志失败：${state.taskEventsError}`
        : "暂无任务日志";
  }
  const hasFailure = job.state === "failed" || events.some(isTaskEventFailure);
  timeline.open = hasFailure || state.taskTimelineOpen;
}

function resetTaskEventState(jobId) {
  if (state.taskEventsJobId === jobId) return;
  state.taskEventsJobId = jobId;
  state.taskEvents = [];
  state.taskEventsLastSequence = 0;
  state.taskEventsFetchedAt = 0;
  state.taskEventsError = "";
  state.taskTimelineOpen = false;
}

function refreshTaskEvents(jobId, { force = false } = {}) {
  if (!jobId) return;
  resetTaskEventState(jobId);
  if (state.taskEventsLoadingJobId === jobId) return;
  const recentlyFetched = state.taskEventsFetchedAt
    && Date.now() - state.taskEventsFetchedAt < 1500;
  if (!force && recentlyFetched) return;
  void loadTaskEvents(jobId, { force });
}

async function loadTaskEvents(jobId, { force = false } = {}) {
  resetTaskEventState(jobId);
  if (state.taskEventsLoadingJobId === jobId) return;
  state.taskEventsLoadingJobId = jobId;
  state.taskEventsError = "";
  updateTaskTimelinePanel();
  const afterSequence = force ? 0 : state.taskEventsLastSequence;
  const query = new URLSearchParams({ after_sequence: String(afterSequence), limit: "200" });
  try {
    const events = await api(`/api/v1/jobs/${encodeURIComponent(jobId)}/events?${query.toString()}`);
    if (state.activeJobId !== jobId || state.taskEventsJobId !== jobId) return;
    const bySequence = new Map(
      (force ? [] : state.taskEvents).map((event) => [String(event.sequence), event]),
    );
    (Array.isArray(events) ? events : []).forEach((event) => {
      bySequence.set(String(event.sequence), event);
    });
    state.taskEvents = sortedTaskEvents([...bySequence.values()]);
    state.taskEventsLastSequence = state.taskEvents.reduce(
      (maximum, event) => Math.max(maximum, Number(event.sequence) || 0),
      0,
    );
    state.taskEventsFetchedAt = Date.now();
    state.taskEventsError = "";
  } catch (error) {
    if (state.activeJobId === jobId && state.taskEventsJobId === jobId) {
      state.taskEventsError = error.message || "请求未完成";
      state.taskEventsFetchedAt = Date.now();
    }
  } finally {
    if (state.taskEventsLoadingJobId === jobId) state.taskEventsLoadingJobId = null;
    if (state.activeJobId === jobId) updateTaskTimelinePanel();
  }
}

function taskLogText(jobId, events) {
  const lines = [
    `任务日志：${state.activeJobTitle || "当前任务"}`,
    `任务 ID：${jobId}`,
    "",
  ];
  sortedTaskEvents(events).forEach((event) => {
    const metadata = [
      `#${event.sequence ?? "?"}`,
      taskEventTypeLabel(event.event_type),
      taskEventAttemptLabel(event.attempt),
      taskEventStageLabel(event.stage),
      event.state ? statusLabel(event.state) : null,
      event.error_code ? `错误码：${event.error_code}` : null,
    ].filter(Boolean).join(" · ");
    lines.push(`[${taskEventTimestamp(event.occurred_at)}] ${metadata}：${event.message || "任务状态已更新"}`);
  });
  return lines.join("\n");
}

async function copyText(text) {
  if (navigator.clipboard?.writeText && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const input = document.createElement("textarea");
  input.value = text;
  input.setAttribute("readonly", "");
  input.style.position = "fixed";
  input.style.opacity = "0";
  document.body.append(input);
  input.select();
  const copied = document.execCommand("copy");
  input.remove();
  if (!copied) throw new Error("浏览器未允许复制，请手动选择日志文本");
}

async function copyTaskLogs(jobId, button) {
  if (button) button.disabled = true;
  try {
    let events = state.taskEventsJobId === jobId ? state.taskEvents : [];
    try {
      const diagnostics = await api(`/api/v1/jobs/${encodeURIComponent(jobId)}/diagnostics`);
      if (Array.isArray(diagnostics.events)) events = diagnostics.events;
    } catch (error) {
      if (!events.length) throw error;
    }
    if (!events.length) throw new Error("暂无可复制的任务日志");
    await copyText(taskLogText(jobId, events));
    showNotice("任务日志已复制");
  } catch (error) {
    showNotice(error.message || "复制任务日志失败", true);
  } finally {
    if (button) button.disabled = false;
  }
}

function diagnosticFilename(jobId, response) {
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="?([^";]+)"?/i);
  return match?.[1] || `diagnostic-${jobId}.json`;
}

async function downloadTaskDiagnostics(jobId, button) {
  if (button) button.disabled = true;
  try {
    assertApiContractCompatible();
    const response = await fetch(
      `${API_ORIGIN}/api/v1/jobs/${encodeURIComponent(jobId)}/diagnostics/export`,
    );
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || "下载诊断信息失败");
    }
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = diagnosticFilename(jobId, response);
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
    showNotice("诊断信息已下载");
  } catch (error) {
    showNotice(error.message || "下载诊断信息失败", true);
  } finally {
    if (button) button.disabled = false;
  }
}

function renderTaskTimeline(job) {
  const timeline = document.createElement("details");
  timeline.id = "task-timeline";
  timeline.className = "task-timeline";
  timeline.dataset.jobId = String(job.id);
  timeline.addEventListener("toggle", () => {
    state.taskTimelineOpen = timeline.open;
  });

  const summary = document.createElement("summary");
  const summaryTitle = document.createElement("span");
  summaryTitle.className = "task-timeline-title";
  summaryTitle.textContent = "任务日志";
  const count = document.createElement("span");
  count.className = "task-timeline-count";
  count.textContent = "0 条";
  summary.append(summaryTitle, count);

  const toolbar = document.createElement("div");
  toolbar.className = "task-timeline-toolbar";
  const copy = document.createElement("button");
  copy.type = "button";
  copy.className = "button button-small";
  copy.textContent = "复制日志";
  copy.addEventListener("click", () => copyTaskLogs(job.id, copy));
  const download = document.createElement("button");
  download.type = "button";
  download.className = "button button-small";
  download.textContent = "下载诊断";
  download.addEventListener("click", () => downloadTaskDiagnostics(job.id, download));
  toolbar.append(copy, download);

  const status = document.createElement("p");
  status.className = "task-timeline-status";
  status.setAttribute("aria-live", "polite");
  const list = document.createElement("ol");
  list.className = "task-timeline-list";
  timeline.append(summary, toolbar, status, list);
  updateTaskTimelinePanel(job);
  return timeline;
}

function renderAsrStats(job) {
  const hasStats = job?.asr_skipped != null
    || job?.asr_segment_total != null
    || job?.asr_elapsed_seconds != null
    || job?.asr_eta_seconds != null
    || job?.asr_fallback_reason;
  if (!hasStats) return null;
  const panel = document.createElement("p");
  panel.className = "job-asr-stats";
  const parts = [];
  if (job.asr_skipped) {
    parts.push(job.asr_subtitle_hit ? "字幕命中，已跳过 ASR" : "已有文本，已跳过 ASR");
  } else if (job.asr_segment_total != null) {
    parts.push(`ASR ${Number(job.asr_segment_completed || 0)}/${Number(job.asr_segment_total)} 片`);
    if (job.asr_audio_seconds != null && job.asr_completed_audio_seconds != null) {
      parts.push(`已转写 ${formatDuration(job.asr_completed_audio_seconds)}/${formatDuration(job.asr_audio_seconds)}`);
    }
  }
  if (job.asr_rtf != null && Number.isFinite(Number(job.asr_rtf))) {
    parts.push(`RTF ${Number(job.asr_rtf).toFixed(2)}`);
  }
  if (job.asr_eta_seconds != null && Number.isFinite(Number(job.asr_eta_seconds))) {
    parts.push(`预计剩余 ${formatDuration(job.asr_eta_seconds)}`);
  }
  if (job.asr_vad_effective_audio_seconds != null) {
    parts.push(`有效音频 ${formatDuration(job.asr_vad_effective_audio_seconds)}`);
  }
  if (job.asr_batch_size != null) {
    parts.push(`batch ${Number(job.asr_batch_size)}`);
  }
  if (job.asr_worker_cold_start != null) {
    parts.push(job.asr_worker_cold_start ? "冷启动" : "热 Worker");
  }
  if (Number(job.asr_recovery_count || 0) > 0) {
    parts.push(`已恢复 ${Number(job.asr_recovery_count)} 次`);
  }
  if (job.asr_budget_warning) {
    parts.push("超过软预算，仍持续推进");
  }
  if (!job.asr_skipped && job.asr_fallback_reason === "subtitle_unavailable") {
    parts.push("未命中字幕，已回退本地 ASR");
  }
  panel.textContent = parts.join(" · ");
  return panel;
}

function renderJob(job, title = null, content = null) {
  if (!jobFocusPanel) return;
  resetTaskEventState(job.id);
  state.activeJobSnapshot = job;
  if (content) state.activeContentSnapshot = content;
  const refresh = document.querySelector("#refresh-job");
  if (refresh) {
    refresh.disabled = false;
    refresh.textContent = "刷新";
    refresh.removeAttribute("title");
  }
  const displayTitle = title || state.activeJobTitle || "当前任务";
  if (title) state.activeJobTitle = title;
  const identity = sourceIdentity(job, content, displayTitle);
  jobFocusPanel.hidden = false;
  jobFocusPanel.classList.remove("empty-state");
  jobFocusPanel.replaceChildren();
  const card = document.createElement("article");
  card.className = "job-card";

  const heading = document.createElement("div");
  heading.className = "job-heading";
  const name = document.createElement("h2");
  name.className = "job-title";
  name.textContent = displayTitle;
  const badge = document.createElement("span");
  badge.className = `status status-${job.state}`;
  badge.textContent = statusLabel(job.state);
  heading.append(
    createSourceCover({
      title: identity.title,
      thumbnail: identity.thumbnail,
      platform: identity.platform,
      className: "job-heading-cover",
    }),
    name,
    badge,
  );

  const progress = document.createElement("div");
  progress.className = "progress-track";
  const value = document.createElement("div");
  value.className = "progress-value";
  value.style.width = `${Math.max(0, Math.min(100, Number(job.progress || 0)))}%`;
  progress.append(value);

  const details = document.createElement("div");
  details.className = "job-details";
  const stage = jobStage(job);
  details.textContent = `${stage.label} · ${stage.detail}`;
  const stageVisual = renderTaskStages(job);

  const timing = document.createElement("dl");
  timing.className = "job-timing";
  const addTiming = (label, valueText) => {
    const item = document.createElement("div");
    item.className = "job-timing-item";
    const term = document.createElement("dt");
    term.textContent = label;
    const definition = document.createElement("dd");
    definition.textContent = valueText;
    item.append(term, definition);
    timing.append(item);
  };
  const elapsed = job.elapsed_seconds == null
    ? (job.started_at && !["completed", "failed", "cancelled"].includes(job.state) ? "计时中" : "未记录")
    : formatDuration(job.elapsed_seconds);
  addTiming("创建时间", formatTimestamp(job.created_at));
  addTiming("开始时间", formatTimestamp(job.started_at));
  addTiming("最后更新", formatTimestamp(job.updated_at));
  addTiming("耗时", elapsed);
  const asrStats = renderAsrStats(job);

  const actions = document.createElement("div");
  actions.className = "actions";
  if (!["completed", "failed", "cancelled"].includes(job.state)) {
    if (job.state === "paused") {
      const resume = document.createElement("button");
      resume.type = "button";
      resume.className = "button button-primary";
      resume.textContent = "继续处理";
      resume.addEventListener("click", () => resumeJob(job.id));
      actions.append(resume);
    } else {
      const pause = document.createElement("button");
      pause.type = "button";
      pause.className = "button";
      pause.textContent = "暂停";
      pause.addEventListener("click", () => pauseJob(job.id));
      actions.append(pause);
    }
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "button button-danger";
    cancel.textContent = "取消";
    cancel.addEventListener("click", () => cancelJob(job.id));
    actions.append(cancel);
  }

  if (job.state === "failed") {
    const failure = jobFailure(job);
    const error = document.createElement("div");
    error.className = "job-error";
    const errorTitle = document.createElement("strong");
    errorTitle.textContent = failure.title;
    const errorMessage = document.createElement("p");
    errorMessage.textContent = job.error_message;
    const recovery = document.createElement("p");
    recovery.className = "job-error-recovery";
    recovery.textContent = failure.suggestion;
    error.append(errorTitle);
    if (job.error_message) error.append(errorMessage);
    error.append(recovery);
    card.append(heading, progress, stageVisual, details);
    if (asrStats) card.append(asrStats);
    card.append(error, timing);
    appendJobRecoveryAction(actions, job);
  } else {
    card.append(heading, progress, stageVisual);
    card.append(details);
    if (asrStats) card.append(asrStats);
    card.append(timing);
  }

  if (job.state === "cancelled") {
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "button";
    retry.textContent = "重新开始";
    retry.addEventListener("click", () => retryJob(job.id));
    actions.append(retry);
  }
  if (job.state === "completed" && state.activeContentId) {
    const result = document.createElement("button");
    result.type = "button";
    result.className = "button button-primary";
    result.textContent = "查看";
    result.addEventListener("click", () => loadResult(state.activeContentId));
    actions.append(result);
  }
  card.append(actions);
  card.append(renderTaskTimeline(job));
  if (job.state === "failed" || job.state === "cancelled") {
    card.append(renderTaskFeedback(job));
  }
  jobFocusPanel.append(card);
  renderIntakeTaskStatus(job, displayTitle, content);
  updateTaskTimelinePanel(job);
  refreshTaskEvents(job.id);
}

function taskFilterMatches(job, filter = state.taskFilter) {
  const execution = taskExecutionState(job);
  if (filter === "all") return true;
  if (filter === "completed") return execution === "completed";
  if (filter === "failed") return execution === "failed";
  if (filter === "cancelled") return execution === "cancelled";
  if (filter === "queued" || filter === "waiting") return execution === "waiting";
  return execution === "running" || execution === "switching";
}

function taskExecutionState(job) {
  if (job?.execution_state) return job.execution_state;
  if (["completed", "failed", "cancelled"].includes(job?.state)) return job.state;
  if (job?.state === "paused") return "paused";
  if (job?.state === "queued") return "waiting";
  return "running";
}

function taskIsWaiting(job) {
  return taskExecutionState(job) === "waiting";
}

function taskIsPaused(job) {
  return taskExecutionState(job) === "paused";
}

function taskIsRunning(job) {
  return ["running", "switching"].includes(taskExecutionState(job));
}

function taskIsTerminal(job) {
  return ["completed", "failed", "cancelled"].includes(taskExecutionState(job));
}

async function pollJob({ forceEvents = false } = {}) {
  if (state.taskPollRequest) return state.taskPollRequest;
  if (!state.activeJobId) {
    showNotice("暂无可刷新的任务", true);
    return;
  }
  const jobId = state.activeJobId;
  const requestId = ++state.taskPollRequestSequence;
  const viewAtStart = state.currentView;
  const request = (async () => {
    const refresh = document.querySelector("#refresh-job");
    if (refresh) {
      refresh.disabled = true;
      refresh.textContent = "刷新中…";
    }
    try {
      const job = await api(`/api/v1/jobs/${encodeURIComponent(jobId)}`);
      if (requestId !== state.taskPollRequestSequence || state.activeJobId !== jobId) return;
      if (taskExecutionState(job) === "waiting") {
        await pollQueueActiveStatus({ requestId, viewAtStart });
        return;
      }
      const activeEntry = state.taskEntries.find((entry) => entry.job.id === jobId);
      if (state.currentView === viewAtStart && viewAtStart !== "tasks") {
        renderJob(job, state.activeJobTitle, activeEntry?.content || state.activeContentSnapshot);
      }
      if (activeEntry) {
        activeEntry.job = job;
        if (state.currentView === "tasks") renderTaskList();
      }
      if (state.currentView === viewAtStart && state.activeJobId === jobId) {
        refreshTaskEvents(jobId, { force: forceEvents });
      }
      if (!["completed", "failed", "cancelled", "paused"].includes(job.state)) {
        window.clearTimeout(state.pollTimer);
        if (requestId === state.taskPollRequestSequence && state.activeJobId === jobId) {
          state.pollTimer = window.setTimeout(() => pollJob(), 700);
        }
      } else if (["completed", "failed", "cancelled"].includes(job.state)) {
        clearNotice();
        if (state.currentView === viewAtStart) pollQueueActiveStatus({ requestId, viewAtStart });
      }
    } catch (error) {
      if (requestId === state.taskPollRequestSequence && state.currentView === viewAtStart) {
        showNotice(error.message, true);
      }
    } finally {
      if (refresh && requestId === state.taskPollRequestSequence) {
        refresh.disabled = !state.activeJobId;
        refresh.textContent = "刷新";
      }
    }
  })();
  state.taskPollRequest = request;
  try {
    return await request;
  } finally {
    if (state.taskPollRequest === request) state.taskPollRequest = null;
  }
}

async function pollQueueActiveStatus({ requestId = null, viewAtStart = state.currentView } = {}) {
  try {
    const queue = await api("/api/v1/queue");
    if (requestId !== null && (requestId !== state.taskPollRequestSequence || state.currentView !== viewAtStart)) return;
    const activeJobId = queue.active_job_id || null;
    if (!activeJobId) return;
    if (activeJobId === state.activeJobId) {
      if (state.currentView === "intake") {
        window.clearTimeout(state.pollTimer);
        state.pollTimer = window.setTimeout(pollJob, 700);
      } else if (state.currentView === "tasks") {
        window.clearTimeout(state.pollTimer);
        state.pollTimer = window.setTimeout(() => loadTaskList(), 700);
      }
      return;
    }
    const job = await api(`/api/v1/jobs/${encodeURIComponent(activeJobId)}`);
    if (requestId !== null && (requestId !== state.taskPollRequestSequence || state.currentView !== viewAtStart)) return;
    const content = taskContentFromJob(job);
    state.activeJobId = job.id;
    state.activeContentId = content.id;
    state.activeJobTitle = content.title;
    state.activeContentSnapshot = content;
    if (state.currentView === "intake") renderJob(job, content.title, content);
    if (state.currentView === "intake") {
      window.clearTimeout(state.pollTimer);
      state.pollTimer = window.setTimeout(pollJob, 700);
    } else if (state.currentView === "tasks") {
      window.clearTimeout(state.pollTimer);
      state.pollTimer = window.setTimeout(() => loadTaskList(), 700);
    }
  } catch (error) {
    showNotice(error.message, true);
  }
}
async function startImport(event) {
  event.preventDefault();
  clearNotice();
  const text = document.querySelector("#source-text").value;
  const sourcePath = document.querySelector("#source-path").value;
  const sourceUrl = sourceUrlInput.value.trim();
  const hasLocalSource = text.trim() || sourcePath.trim();
  if (state.intakeMode === "link") {
    if (state.pendingCollectionScan) {
      await queryLinks();
      return;
    }
    if (!sourceUrl) {
      showNotice("请先切换到“本地识别”输入本地内容，或在当前页粘贴平台链接", true);
      return;
    }
    if (hasLocalSource) {
      showNotice("当前是平台链接页，请清空本地内容或切换到“本地识别”", true);
      return;
    }
    if (!state.linkQuery || state.linkQuery.rawInput !== sourceUrl) {
      await queryLinks();
      return;
    }
    renderLinkQueryDialog(state.linkQuery);
    return;
  }
  if (sourceUrl) {
    showNotice("当前是本地识别页，请清空平台链接或切换到“平台链接”", true);
    return;
  }
  if (!hasLocalSource) {
    showNotice("请先选择文件、填写本地路径或粘贴本地文本", true);
    return;
  }
  await queryLocalSource();
}
async function pauseJob(jobId) {
  if (state.taskSwitching) return;
  state.taskSwitching = true;
  renderTaskList();
  try {
    const job = await api(`/api/v1/jobs/${encodeURIComponent(jobId)}/pause`, { method: "POST" });
    window.clearTimeout(state.pollTimer);
    if (state.activeJobId === jobId && (state.currentView !== "tasks" || !jobFocusPanel?.hidden)) {
      renderJob(job, state.activeJobTitle, state.activeContentSnapshot);
    }
    await loadTaskList();
    showNotice("任务已暂停；需要时可以继续处理");
    pollQueueActiveStatus();
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    state.taskSwitching = false;
    renderTaskList();
  }
}

async function resumeJob(jobId) {
  if (state.taskSwitching) return;
  state.taskSwitching = true;
  renderTaskList();
  try {
    const job = await api(`/api/v1/jobs/${encodeURIComponent(jobId)}/resume`, { method: "POST" });
    if (state.activeJobId === jobId && (state.currentView !== "tasks" || !jobFocusPanel?.hidden)) {
      renderJob(job, state.activeJobTitle, state.activeContentSnapshot);
    }
    await loadTaskList();
    showNotice("任务已继续，等待执行…");
    pollJob();
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    state.taskSwitching = false;
    renderTaskList();
  }
}

async function cancelJob(jobId) {
  try {
    const job = await api(`/api/v1/jobs/${jobId}/cancel`, { method: "POST" });
    window.clearTimeout(state.pollTimer);
    renderJob(job, state.activeJobTitle, state.activeContentSnapshot);
    await loadTaskList();
    showNotice("任务已取消");
  } catch (error) {
    showNotice(error.message, true);
  }
}
async function retryJob(jobId) {
  try {
    const result = await api(`/api/v1/jobs/${jobId}/retry`, { method: "POST" });
    state.activeJobId = result.job.id;
    state.activeContentId = result.content.id;
    state.activeJobTitle = result.content.title;
    state.activeContentSnapshot = result.content;
    renderJob(result.job, state.activeJobTitle, result.content);
    await loadTaskList();
    showNotice("任务已重新排队，正在处理…");
    pollJob();
  } catch (error) {
    showNotice(error.message, true);
  }
}
async function loadFavoriteFolders() {
  const folders = await api("/api/v1/favorite-folders");
  state.favoriteFolders = folders;
  if (
    state.activeFavoriteFolderId &&
    !folders.some((folder) => folder.id === state.activeFavoriteFolderId)
  ) {
    state.activeFavoriteFolderId = "";
  }
  renderFavoriteFolders();
}

async function createFavoriteFolder() {
  const name = await openProductTextDialog({
    title: "新建收藏夹",
    label: "收藏夹名称",
    placeholder: "例如：待整理、重点课程",
    confirmLabel: "创建收藏夹",
  });
  if (!name) return;
  try {
    const folder = await api("/api/v1/favorite-folders", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    state.activeFavoriteFolderId = folder.id;
    state.showingTrash = false;
    showNotice(`已创建收藏夹“${folder.name}”`);
    await loadHistory();
  } catch (error) {
    showNotice(error.message, true);
  }
}

async function updateFavoriteFolders(contentId, folderIds, picker) {
  picker.querySelectorAll("input").forEach((input) => { input.disabled = true; });
  try {
    await api(`/api/v1/contents/${encodeURIComponent(contentId)}`, {
      method: "PATCH",
      body: JSON.stringify({ favorite_folder_ids: folderIds }),
    });
    picker.open = false;
    showNotice("收藏夹归属已更新");
    await loadHistory();
  } catch (error) {
    showNotice(error.message, true);
    picker.querySelectorAll("input").forEach((input) => { input.disabled = false; });
  }
}

function renderFavoriteFolderPicker(entry) {
  const picker = document.createElement("details");
  picker.className = "favorite-folder-picker";
  const summary = document.createElement("summary");
  summary.textContent = "收藏夹";
  picker.append(summary);
  const list = document.createElement("div");
  list.className = "favorite-folder-picker-list";
  const folders = state.favoriteFolders.filter((folder) => !folder.is_system);
  if (!folders.length) {
    const empty = document.createElement("span");
    empty.className = "favorite-folder-picker-empty";
    empty.textContent = "请先新建收藏夹";
    list.append(empty);
  } else {
    const selected = new Set(entry.content.favorite_folder_ids || []);
    folders.forEach((folder) => {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = folder.id;
      input.checked = selected.has(folder.id);
      input.addEventListener("change", () => {
        const ids = [...list.querySelectorAll("input:checked")].map((item) => item.value);
        updateFavoriteFolders(entry.content.id, ids, picker);
      });
      label.append(input, document.createTextNode(folder.name));
      list.append(label);
    });
  }
  picker.append(list);
  return picker;
}
async function loadHistoryCategories() {
  const categories = await api("/api/v1/content-categories");
  state.contentCategories = Array.isArray(categories)
    ? categories.map((item) => item.name).filter(Boolean)
    : [];
  const selects = [
    document.querySelector("#history-category"),
  ];
  selects.forEach((select) => {
    if (!select) return;
    const current = select.value;
    const first = select.firstElementChild;
    select.replaceChildren(first);
    categories.forEach((item) => {
      const option = document.createElement("option");
      option.value = item.name;
      option.textContent = item.name;
      select.append(option);
    });
    if (current && categories.some((item) => item.name === current)) {
      select.value = current;
    }
  });
}

const EXPORT_FORMAT_LABELS = { markdown: "Markdown", text: "纯文本", subtitle: "字幕 SRT", json: "JSON" };
const EXPORT_FORMAT_EXTENSIONS = { markdown: "md", text: "txt", subtitle: "srt", json: "json" };
const EXPORT_FORMAT_VALUES = Object.keys(EXPORT_FORMAT_LABELS);

function currentExportFormat() {
  const picked = document.querySelector('input[name="export-format"]:checked');
  return EXPORT_FORMAT_VALUES.includes(picked?.value) ? picked.value : "markdown";
}

function currentExportDestination() {
  const picked = document.querySelector('input[name="export-destination"]:checked');
  return picked?.value === "archive" ? "archive" : "download";
}

async function exportSingleHistory(contentId, options = {}) {
  const format = options.format || currentExportFormat();
  const destination = options.destination || currentExportDestination();
  try {
    assertApiContractCompatible();
    const response = await fetch(
      `${API_ORIGIN}/api/v1/contents/${encodeURIComponent(contentId)}/export?format=${encodeURIComponent(format)}&destination=${encodeURIComponent(destination)}`,
    );
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || "导出失败");
    }
    if (destination === "archive") {
      await response.json().catch(() => ({}));
      showNotice(`已导出 ${EXPORT_FORMAT_LABELS[format]} 到归档目录`);
      return;
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `content-${contentId}.${EXPORT_FORMAT_EXTENSIONS[format]}`;
    anchor.click();
    URL.revokeObjectURL(url);
    showNotice(`已导出 ${EXPORT_FORMAT_LABELS[format]}`);
  } catch (error) {
    showNotice(error.message, true);
  }
}

async function updateHistoryCategory(contentId, category, select) {
  if (!category) return;
  select.disabled = true;
  try {
    await api(`/api/v1/contents/${encodeURIComponent(contentId)}`, {
      method: "PATCH",
      body: JSON.stringify({ category }),
    });
    showNotice("分类已更新");
    await loadHistoryCategories();
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    select.disabled = false;
  }
}

const SUMMARY_TEMPLATE_LABELS = {
  general: "通用知识总结",
  course_notes: "课程笔记",
  meeting_minutes: "会议纪要",
  interview_outline: "访谈提纲",
  opinion_summary: "观点摘要",
};

function summaryTemplateLabel(value) {
  return SUMMARY_TEMPLATE_LABELS[value] || value || "通用知识总结";
}

function formatTimecode(seconds) {
  const whole = Math.max(0, Math.round(Number(seconds) || 0));
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const rest = whole % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}

function clearResultSupport() {
  ["#result-evidence", "#result-versions", "#result-feedback"].forEach((selector) => {
    const panel = document.querySelector(selector);
    if (panel) {
      panel.hidden = true;
      panel.replaceChildren();
    }
  });
  state.activeSummaryVersionId = null;
}

function resultHeadingId(text, index) {
  const slug = String(text || "")
    .toLowerCase()
    .replace(/[^\p{Letter}\p{Number}]+/gu, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
  return `result-heading-${slug || "section"}-${index}`;
}

function resultHeadingScrollTop(heading, container) {
  const containerRect = container.getBoundingClientRect();
  const headingRect = heading.getBoundingClientRect();
  return container.scrollTop + headingRect.top - containerRect.top;
}

function updateResultOutlineActive(headings, container) {
  const items = [...document.querySelectorAll("#result-outline-list .result-outline-item")];
  if (!headings.length || !items.length) return;
  let activeIndex = 0;
  const threshold = container.scrollTop + 48;
  headings.forEach((heading, index) => {
    if (resultHeadingScrollTop(heading, container) <= threshold) activeIndex = index;
  });
  items.forEach((item, index) => item.classList.toggle("is-active", index === activeIndex));
}

function renderResultOutline(headings, container) {
  const outline = document.querySelector("#result-outline");
  const list = document.querySelector("#result-outline-list");
  const toggle = document.querySelector("#result-outline-toggle");
  const top = document.querySelector("#result-outline-top");
  const source = document.querySelector("#result-outline-source");
  const actions = document.querySelector("#result-outline-actions");
  if (!outline || !list || !toggle || !top) return;
  const content = state.activeContentSnapshot;
  if (source) {
    source.hidden = !content?.canonical_url;
    if (typeof fillResultSourceCard === "function") fillResultSourceCard(content);
  }
  list.replaceChildren();
  if (!headings.length) {
    const empty = document.createElement("p");
    empty.className = "result-outline-empty";
    empty.textContent = "本篇无章节结构";
    list.append(empty);
  } else {
    headings.forEach((heading) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "result-outline-item";
      item.dataset.level = String(heading.level);
      item.textContent = heading.text;
      item.addEventListener("click", () => {
        container.scrollTo({
          top: Math.max(0, resultHeadingScrollTop(heading.node, container) - 20),
          behavior: "smooth",
        });
        updateResultOutlineActive(headings.map((entry) => entry.node), container);
      });
      list.append(item);
    });
  }
  let collapsed = false;
  try { collapsed = window.localStorage.getItem("content-knowledge-result-outline") === "closed"; } catch (_error) {}
  const applyCollapsed = () => {
    outline.classList.toggle("is-collapsed", collapsed);
    list.hidden = collapsed;
    if (actions) actions.hidden = collapsed;
    if (source) source.hidden = collapsed || !content?.canonical_url;
    const regenerate = document.querySelector("#result-outline-regenerate");
    if (regenerate) regenerate.hidden = collapsed;
    toggle.setAttribute("aria-expanded", String(!collapsed));
  if (collapsed) {
    toggle.replaceChildren(createIcon("chevron-left"));
  } else {
    toggle.textContent = "目录";
  }
  };
  toggle.onclick = () => {
    collapsed = !collapsed;
    try { window.localStorage.setItem("content-knowledge-result-outline", collapsed ? "closed" : "open"); } catch (_error) {}
    applyCollapsed();
  };
  top.onclick = () => container.scrollTo({ top: 0, behavior: "smooth" });
  applyCollapsed();
  updateResultOutlineActive(headings.map((entry) => entry.node), container);
}

function stripResultDocumentHeader(markdown) {
  const lines = String(markdown || "").split(/\r?\n/);
  let cursor = 0;
  while (cursor < lines.length && !lines[cursor].trim()) cursor += 1;
  const hasTitle = /^#\s+/.test(lines[cursor] || "");
  if (!hasTitle) return lines;
  cursor += 1;
  while (cursor < lines.length && !lines[cursor].trim()) cursor += 1;
  const metadataStart = cursor;
  while (cursor < lines.length && /^-\s*(平台|作者|来源|发布时间|标签|简介|分析时间)\s*[:：]/.test(lines[cursor] || "")) cursor += 1;
  if (cursor === metadataStart) return lines;
  while (cursor < lines.length && !lines[cursor].trim()) cursor += 1;
  if (!/^---+$/.test((lines[cursor] || "").trim())) return lines;
  cursor += 1;
  while (cursor < lines.length && !lines[cursor].trim()) cursor += 1;
  return lines.slice(cursor);
}

function renderResultDocument(markdown) {
  const container = document.querySelector("#result-markdown");
  const scrollRoot = document.querySelector(".main-content");
  if (!container || !scrollRoot) return;
  container.classList.remove("is-editing");
  container.replaceChildren();
  scrollRoot.scrollTop = 0;
  const headings = [];
  const lines = stripResultDocumentHeader(markdown);
  lines.forEach((line, index) => {
    const match = /^(#{1,6})\s+(.+?)\s*$/.exec(line);
    const node = document.createElement(match ? `h${match[1].length}` : "div");
    node.className = "result-markdown-line";
    if (match) {
      const text = match[2].replace(/\s+#+\s*$/, "").trim();
      node.textContent = text;
      node.id = resultHeadingId(text, index);
      headings.push({ node, level: match[1].length, text });
    } else {
      node.textContent = line || "\u00a0";
    }
    container.append(node);
  });
  renderResultOutline(headings, scrollRoot);
  scrollRoot.onscroll = () => updateResultOutlineActive(headings.map((entry) => entry.node), scrollRoot);
  window.requestAnimationFrame(() => updateResultOutlineActive(headings.map((entry) => entry.node), scrollRoot));
}

function renderResultEvidence(evidence, content) {
  const panel = document.querySelector("#result-evidence");
  if (!panel) return;
  panel.hidden = false;
  panel.replaceChildren();
  const details = document.createElement("details");
  details.className = "result-evidence-details";
  const summary = document.createElement("summary");
  summary.textContent = `来源证据（${evidence.length} 段）`;
  details.append(summary);
  const metadata = document.createElement("dl");
  metadata.className = "result-evidence-metadata";
  [
    ["平台", platformLabel(content?.platform)],
    ["作者", content?.author],
    ["发布时间", content?.published_at ? formatTimestamp(content.published_at) : null],
  ].forEach(([label, value]) => {
    if (!value) return;
    const term = document.createElement("dt");
    term.textContent = label;
    const description = document.createElement("dd");
    description.textContent = value;
    metadata.append(term, description);
  });
  if (metadata.childElementCount) details.append(metadata);
  if (content?.canonical_url) {
    const source = document.createElement("a");
    source.href = content.canonical_url;
    source.target = "_blank";
    source.rel = "noreferrer";
    source.className = "result-link result-evidence-source";
    source.textContent = `打开${platformLabel(content.platform)}原始来源`;
    details.append(source);
  }
  if (!evidence.length) {
    const empty = document.createElement("p");
    empty.className = "field-hint";
    empty.textContent = "当前归档没有可展示的时间戳字幕证据。";
    details.append(empty);
  } else {
    const list = document.createElement("div");
    list.className = "result-evidence-list";
    evidence.forEach((item) => {
      const row = document.createElement("article");
      row.className = "result-evidence-item";
      const time = document.createElement("strong");
      time.textContent = item.location_kind === "timestamp"
        && Number.isFinite(item.start_seconds)
        && Number.isFinite(item.end_seconds)
        ? `${formatTimecode(item.start_seconds)}–${formatTimecode(item.end_seconds)}`
        : "详情定位";
      const quote = document.createElement("p");
      quote.textContent = item.text;
      row.append(time, quote);
      list.append(row);
    });
    details.append(list);
  }
  panel.append(details);
}

async function compareSummaryVersions(contentId, leftId, rightId, container) {
  container.textContent = "正在读取版本差异…";
  try {
    const result = await api(
      `/api/v1/contents/${contentId}/summary-versions/compare?left_id=${encodeURIComponent(leftId)}&right_id=${encodeURIComponent(rightId)}`,
    );
    container.textContent = result.diff || "两个版本没有文本差异。";
  } catch (error) {
    container.textContent = error.message;
  }
}

async function saveSummaryVersion(contentId, versionId, editor, button) {
  button.disabled = true;
  try {
    await api(`/api/v1/contents/${contentId}/summary-versions/${versionId}`, {
      method: "PUT",
      body: JSON.stringify({ markdown: editor.value }),
    });
    showNotice("已保存为新版本，原版本仍保留");
    await loadResult(contentId);
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function generatePartialSummary(contentId, form, button) {
  button.disabled = true;
  try {
    const result = await api(`/api/v1/contents/${contentId}/summary-versions/partial`, {
      method: "POST",
      body: JSON.stringify({
        start_seconds: Number(form.elements.start_seconds.value),
        end_seconds: Number(form.elements.end_seconds.value),
        chapter_title: form.elements.chapter_title.value.trim() || null,
        template: form.elements.template.value,
      }),
    });
    showNotice(`局部总结已生成 v${result.version_number}`);
    await loadResult(contentId);
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    button.disabled = false;
  }
}

function renderSummaryVersions(contentId, versions) {
  const panel = document.querySelector("#result-versions");
  if (!panel) return;
  panel.hidden = false;
  panel.replaceChildren();
  state.activeSummaryVersionId = versions[0]?.id || null;
  panel.open = false;
  const heading = document.createElement("summary");
  heading.textContent = "总结版本";
  panel.append(heading);

  const partial = document.createElement("form");
  partial.className = "summary-partial-form";
  partial.innerHTML = "<strong>局部生成</strong>";
  const start = document.createElement("input");
  start.name = "start_seconds";
  start.type = "number";
  start.min = "0";
  start.step = "1";
  start.value = "0";
  start.title = "开始秒数";
  const end = document.createElement("input");
  end.name = "end_seconds";
  end.type = "number";
  end.min = "1";
  end.step = "1";
  end.value = "60";
  end.title = "结束秒数";
  const chapter = document.createElement("input");
  chapter.name = "chapter_title";
  chapter.placeholder = "章节名称（可选）";
  const template = document.createElement("select");
  template.name = "template";
  Object.entries(SUMMARY_TEMPLATE_LABELS).forEach(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    template.append(option);
  });
  const generate = document.createElement("button");
  generate.type = "submit";
  generate.className = "button";
  generate.textContent = "生成局部总结";
  partial.append(start, end, chapter, template, generate);
  partial.addEventListener("submit", (event) => {
    event.preventDefault();
    generatePartialSummary(contentId, partial, generate);
  });
  panel.append(partial);

  const list = document.createElement("div");
  list.className = "summary-version-list";
  versions.forEach((version, index) => {
    const card = document.createElement("article");
    card.className = "summary-version-card";
    const title = document.createElement("strong");
    title.textContent = `v${version.version_number} · ${version.origin === "original" ? "原始" : version.origin === "partial" ? "局部生成" : "手工编辑"}`;
    const meta = document.createElement("small");
    meta.textContent = [
      summaryTemplateLabel(version.template),
      version.chapter_title,
      version.source_start_seconds != null
        ? `${formatTimecode(version.source_start_seconds)}–${formatTimecode(version.source_end_seconds)}`
        : null,
      formatTimestamp(version.created_at),
    ].filter(Boolean).join(" · ");
    const actions = document.createElement("div");
    actions.className = "actions";
    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "button";
    edit.textContent = "编辑并保留新版本";
    edit.addEventListener("click", () => {
      if (card.querySelector(".summary-version-editor")) return;
      const editor = document.createElement("textarea");
      editor.className = "summary-version-editor";
      editor.value = version.markdown;
      const save = document.createElement("button");
      save.type = "button";
      save.className = "button button-primary";
      save.textContent = "保存新版本";
      save.addEventListener("click", () => saveSummaryVersion(contentId, version.id, editor, save));
      card.append(editor, save);
    });
    actions.append(edit);
    if (index < versions.length - 1) {
      const compare = document.createElement("button");
      compare.type = "button";
      compare.className = "button";
      compare.textContent = "与上一版对比";
      compare.addEventListener("click", () => {
        const diff = panel.querySelector(".summary-version-diff");
        compareSummaryVersions(contentId, version.id, versions[index + 1].id, diff);
      });
      actions.append(compare);
    }
    card.append(title, meta, actions);
    list.append(card);
  });
  panel.append(list);
  const diff = document.createElement("pre");
  diff.className = "summary-version-diff";
  diff.textContent = "选择两个版本后在此查看差异。";
  panel.append(diff);
}

async function submitSummaryFeedback(contentId, category, note, button) {
  button.disabled = true;
  try {
    await api(`/api/v1/contents/${contentId}/feedback`, {
      method: "POST",
      body: JSON.stringify({
        version_id: state.activeSummaryVersionId,
        category,
        note: note.value.trim() || null,
      }),
    });
    showNotice("感谢反馈，已保存到本机");
    note.value = "";
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    button.disabled = false;
  }
}

function renderSummaryFeedback(contentId, feedback) {
  const panel = document.querySelector("#result-feedback");
  if (!panel) return;
  panel.hidden = false;
  panel.replaceChildren();
  panel.open = false;
  const heading = document.createElement("summary");
  heading.textContent = "总结反馈";
  const hint = document.createElement("p");
  hint.className = "field-hint";
  hint.textContent = feedback.length ? `已记录 ${feedback.length} 条本机反馈` : "标记问题，帮助后续改进总结";
  const note = document.createElement("textarea");
  note.rows = 2;
  note.placeholder = "补充说明（可选）";
  const actions = document.createElement("div");
  actions.className = "actions";
  [["accurate", "准确"], ["omission", "有遗漏"], ["poor_wording", "表述不佳"]].forEach(([category, label]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "button";
    button.textContent = label;
    button.addEventListener("click", () => submitSummaryFeedback(contentId, category, note, button));
    actions.append(button);
  });
  panel.append(heading, hint, note, actions);
}

function renderResultAssets(result) {
  renderResultEvidence(result.evidence || [], result.content);
  renderSummaryVersions(result.content.id, result.versions || []);
  renderSummaryFeedback(result.content.id, result.feedback || []);
}
function showContentDetail(entry) {
  clearResultSupport();
  state.activeContentId = entry.content.id;
  state.activeContentSnapshot = entry.content;
  state.activeArchivePath = entry.job?.archive_path || "";
  document.querySelector("#result-title").textContent = entry.content.title;
  const resultMeta = document.querySelector("#result-meta");
  resultMeta.replaceChildren();
  const status = document.createElement("div");
  status.textContent = "状态：" + statusLabel(entry.job.state);
  resultMeta.append(status);
  // 来源入口按设计稿统一收进目录栏的深色来源卡，顶部不再放文字链接。
  if (entry.job.source_note) {
    const note = document.createElement("div");
    note.textContent = entry.job.source_note;
    resultMeta.append(note);
  }
  const stage = jobStage(entry.job);
  const failure = entry.job.state === "failed" ? jobFailure(entry.job) : null;
  renderResultDocument(
    failure
      ? failure.title + "\n\n" + (entry.job.error_message || "请按提示处理后重试")
      : stage.label + "：" + stage.detail,
  );
  configureResultInlineEdit(entry.content.id, null);
  renderResultQuickRail();
  showView("result");
}

const platformStatusLabel = {
  NOT_CONNECTED: "未连接",
  CHECKING: "检查中",
  CONNECTED: "已连接",
  EXPIRED: "已过期",
  REAUTH_REQUIRED: "需重新登录",
  RISK_CONTROLLED: "需要人工验证",
  UNSUPPORTED: "暂未适配",
};

function connectionAuthLabel(value) {
  return {
    qrcode_session: "B站二维码登录",
    browser_session: "浏览器会话",
    official_api: "官方 API",
  }[value] || value || "未设置";
}

function connectionStatusClass(value) {
  if (value === "CONNECTED") {
    return "is-success";
  }
  if (value === "NOT_CONNECTED" || value === "UNSUPPORTED" || value === "CHECKING") {
    return "is-muted";
  }
  return "is-error";
}

function stopBilibiliQrPoll({ cancelServer = false, silent = false } = {}) {
  const key = state.bilibiliQrKey;
  if (state.bilibiliQrTimer) {
    window.clearTimeout(state.bilibiliQrTimer);
    state.bilibiliQrTimer = null;
  }
  state.bilibiliQrKey = null;
  state.bilibiliQrGeneration += 1;
  state.bilibiliQrPhase = "waiting";
  if (cancelServer && key) {
    void api(`/api/v1/platform-connections/bilibili/qrcode/${encodeURIComponent(key)}`, {
      method: "DELETE",
    }).catch(() => {});
    if (!silent) showNotice("已取消连接");
  }
}

function clearBilibiliQrPanel({ cancelServer = true, silent = false } = {}) {
  stopBilibiliQrPoll({ cancelServer, silent });
  if (bilibiliQrPanel) {
    if (bilibiliQrPanel.open) {
      bilibiliQrPanel.close();
    }
    bilibiliQrPanel.replaceChildren();
  }
}

function renderBilibiliQrPanel(qr) {
  if (!bilibiliQrPanel) {
    return;
  }
  bilibiliQrPanel.replaceChildren();
  const close = document.createElement("button");
  close.type = "button";
  close.className = "bilibili-qr-dialog-close";
  close.setAttribute("aria-label", "关闭二维码窗口");
  close.setAttribute("aria-label", "关闭");
  close.replaceChildren(createIcon("close"));
  close.addEventListener("click", clearBilibiliQrPanel);
  const body = document.createElement("div");
  body.className = "bilibili-qr-dialog-body";
  const image = document.createElement("img");
  image.alt = "B站登录二维码";
  image.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(qr.qrcode_svg);
  const copy = document.createElement("div");
  copy.className = "bilibili-qr-panel-copy";
  const title = document.createElement("h3");
  title.id = "bilibili-qr-title";
  title.textContent = "使用 B站 App 扫码登录";
  const status = document.createElement("p");
  status.id = "bilibili-qr-status";
  status.textContent = "等待扫码；二维码约 " + qr.expires_in + " 秒有效";
  const spinner = document.createElement("span");
  spinner.id = "bilibili-qr-spinner";
  spinner.className = "bilibili-qr-spinner";
  spinner.setAttribute("aria-hidden", "true");
  const hint = document.createElement("p");
  hint.textContent = "扫码并在手机上确认后，产品会自动保存本机授权会话。";
  const regenerate = document.createElement("button");
  regenerate.type = "button";
  regenerate.className = "button";
  regenerate.textContent = "重新生成";
  regenerate.addEventListener("click", () => startBilibiliQrLogin(regenerate));
  copy.append(title, status, spinner, hint, regenerate);
  body.append(image, copy);
  bilibiliQrPanel.append(close, body);
  if (!bilibiliQrPanel.open) {
    bilibiliQrPanel.showModal();
  }
}

function updateBilibiliQrStatus(message, phase = state.bilibiliQrPhase) {
  const status = document.querySelector("#bilibili-qr-status");
  if (status) {
    status.textContent = message;
  }
  const panel = document.querySelector(".bilibili-qr-dialog-body");
  if (panel) panel.dataset.phase = phase;
  state.bilibiliQrPhase = phase;
}

function scheduleBilibiliQrPoll() {
  const key = state.bilibiliQrKey;
  const generation = state.bilibiliQrGeneration;
  if (!key) {
    return;
  }
  const poll = async () => {
    state.bilibiliQrTimer = null;
    if (state.bilibiliQrKey !== key || state.bilibiliQrGeneration !== generation) {
      return;
    }
    if (state.bilibiliQrPhase === "scanned") {
      updateBilibiliQrStatus("等待手机确认并检查登录结果…", "verifying");
    }
    try {
      const connection = await api("/api/v1/platform-connections/bilibili/qrcode/poll", {
        method: "POST",
        body: JSON.stringify({ qrcode_key: key }),
      });
      if (state.bilibiliQrKey !== key || state.bilibiliQrGeneration !== generation) return;
      if (connection.status === "CONNECTED") {
        updateBilibiliQrStatus("登录成功，账号信息已保存", "success");
        const title = document.querySelector("#bilibili-qr-title");
        if (title) title.textContent = connection.account_label
          ? `B站登录成功 · ${connection.account_label}`
          : "B站登录成功";
        stopBilibiliQrPoll();
        showNotice("B站登录已确认，后续链接将复用该会话");
        await Promise.allSettled([loadSettings(), loadPlatformConnections()]);
        return;
      }
      if (["REAUTH_REQUIRED", "RISK_CONTROLLED", "EXPIRED"].includes(connection.status)) {
        updateBilibiliQrStatus(
          connection.message || (connection.status === "EXPIRED" ? "二维码已过期，请重新生成" : "登录未完成，请重新生成"),
          connection.status === "EXPIRED" ? "expired" : "failed",
        );
        stopBilibiliQrPoll();
        await loadPlatformConnections();
        return;
      }
      updateBilibiliQrStatus(
        connection.message || "等待使用 B站 App 扫码",
        String(connection.message || "").includes("已扫码") ? "scanned" : "waiting",
      );
      state.bilibiliQrTimer = window.setTimeout(poll, 2000);
    } catch (error) {
      if (state.bilibiliQrKey !== key || state.bilibiliQrGeneration !== generation) return;
      if (error.code === "bilibili_qr_attempt_expired") {
        updateBilibiliQrStatus("二维码已过期，请重新生成", "expired");
        stopBilibiliQrPoll();
        await loadPlatformConnections();
        return;
      }
      updateBilibiliQrStatus("暂时无法检查登录状态，将自动重试…", "retrying");
      state.bilibiliQrTimer = window.setTimeout(poll, 3000);
    }
  };
  state.bilibiliQrTimer = window.setTimeout(poll, 1500);
}

async function startBilibiliQrLogin(button) {
  stopBilibiliQrPoll({ cancelServer: true, silent: true });
  const generation = state.bilibiliQrGeneration;
  if (button) {
    button.disabled = true;
  }
  try {
    const qr = await api("/api/v1/platform-connections/bilibili/qrcode", { method: "POST" });
    if (state.bilibiliQrGeneration !== generation) return;
    state.bilibiliQrKey = qr.qrcode_key;
    state.bilibiliQrPhase = "waiting";
    renderBilibiliQrPanel(qr);
    showNotice("B站登录二维码已生成，请使用 B站 App 扫码并确认");
    scheduleBilibiliQrPoll();
  } catch (error) {
    if (state.bilibiliQrGeneration !== generation) return;
    showNotice(error.message, true);
  } finally {
    if (button && state.bilibiliQrGeneration === generation) {
      button.disabled = false;
    }
  }
}

function renderPlatformConnections(report) {
  if (!platformConnectionsPanel) {
    return;
  }
  platformConnectionsPanel.replaceChildren();
  report.connections.forEach((connection) => {
    const card = document.createElement("article");
    card.className = "platform-card";
    const heading = document.createElement("div");
    heading.className = "platform-card-heading";
    const title = document.createElement("h3");
    title.textContent = connection.display_name;
    const status = document.createElement("span");
    status.className = "platform-status " + connectionStatusClass(connection.status);
    status.textContent = platformStatusLabel[connection.status] || connection.status;
    heading.append(title, status);

    const meta = document.createElement("div");
    meta.className = "platform-card-meta";
    const auth = document.createElement("span");
    auth.textContent = connectionAuthLabel(connection.auth_type);
    const account = document.createElement("span");
    account.textContent = connection.account_label ? "账号：" + connection.account_label : "账号：未确认";
    meta.append(auth, account);

    const message = document.createElement("p");
    message.className = "platform-card-message";
    message.textContent = connection.message || "尚未检查连接";

    if (connection.platform === "bilibili") {
      const actions = document.createElement("div");
      actions.className = "platform-card-actions";
      const login = document.createElement("button");
      login.type = "button";
      login.className = "button";
      login.textContent = "生成二维码";
      login.addEventListener("click", () => startBilibiliQrLogin(login));
      actions.append(login);

      const scanFavorite = document.createElement("button");
      scanFavorite.type = "button";
      scanFavorite.className = "button";
      scanFavorite.textContent = "扫描收藏";
      scanFavorite.addEventListener("click", () => void startBilibiliFavoriteBrowser());
      actions.append(scanFavorite);

      const scanWatchlater = document.createElement("button");
      scanWatchlater.type = "button";
      scanWatchlater.className = "button";
      scanWatchlater.textContent = "扫描稍后再看";
      scanWatchlater.addEventListener("click", () => {
        if (connection.status !== "CONNECTED") {
          showNotice("请先生成二维码并登录后扫描稍后再看", true);
          return;
        }
        void startWatchlaterScan("https://www.bilibili.com/watchlater");
      });
      actions.append(scanWatchlater);

      const check = document.createElement("button");
      check.type = "button";
      check.className = "button button-primary";
      check.textContent = "检查登录状态";
      check.disabled = connection.status === "CHECKING";
      check.addEventListener("click", () => checkPlatformConnection(connection.platform, check));
      actions.append(check);

      if (connection.status === "CONNECTED" || connection.account_label) {
        const disconnect = document.createElement("button");
        disconnect.type = "button";
        disconnect.className = "button";
        disconnect.textContent = "断开";
        disconnect.addEventListener("click", () => disconnectPlatform(connection.platform, disconnect));
        actions.append(disconnect);
      }
      card.append(heading, meta, message, actions);
    } else if ((connection.platform === "xiaohongshu" || connection.platform === "zhihu")
      && connection.supported
      && connection.auth_type === "browser_session") {
      const actions = document.createElement("div");
      actions.className = "platform-card-actions";
      const connect = document.createElement("button");
      connect.type = "button";
      connect.className = "button button-primary";
      connect.textContent = "连接";
      if (connection.platform === "xiaohongshu") {
        connect.addEventListener("click", () => startXhsBrowserLogin(connect));
      } else {
        connect.addEventListener("click", () => startZhihuBrowserLogin(connect));
      }
      actions.append(connect);

      if (connection.platform === "zhihu") {
        const scanFavorite = document.createElement("button");
        scanFavorite.type = "button";
        scanFavorite.className = "button";
        scanFavorite.textContent = "扫描收藏";
        scanFavorite.addEventListener("click", () => {
          if (connection.status !== "CONNECTED") {
            showNotice("请先点击连接完成知乎登录", true);
            return;
          }
          openCollectionScanInput("zhihu");
        });
        actions.append(scanFavorite);
      }

      const check = document.createElement("button");
      check.type = "button";
      check.className = "button";
      check.textContent = "检查连接";
      check.addEventListener("click", () => checkPlatformConnection(connection.platform, check));
      actions.append(check);

      const disconnect = document.createElement("button");
      disconnect.type = "button";
      disconnect.className = "button";
      disconnect.textContent = "断开";
      disconnect.addEventListener("click", () => disconnectPlatform(connection.platform, disconnect));
      actions.append(disconnect);

      if (!hasShellBridge()) {
        message.textContent = `请在桌面壳中连接或检查${connection.display_name}登录状态`;
      }
      card.append(heading, meta, message, actions);
    } else {
      // 仅接入只读信息的平台保持 0 个可点击连接控件。
      card.append(heading, meta, message);
    }
    platformConnectionsPanel.append(card);
  });
}

async function loadPlatformConnections() {
  const report = await api("/api/v1/platform-connections");
  renderPlatformConnections(report);
  return report;
}

async function startXhsBrowserLogin(button) {
  if (button) button.disabled = true;
  try {
    if (!hasShellBridge()) {
      throw new Error("请在桌面壳中连接小红书");
    }
    await api("/api/v1/platform-connections/xiaohongshu/connect", {
      method: "POST",
      body: JSON.stringify({}),
    });
    const result = await requestXhsShellAction("open_login");
    const connection = await saveXhsShellResult(result);
    const isError = ["EXPIRED", "REAUTH_REQUIRED", "RISK_CONTROLLED"].includes(connection.status);
    showNotice(connection.message || "小红书登录状态已更新", isError);
    await loadPlatformConnections();
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    if (button) button.disabled = false;
  }
}

async function startZhihuBrowserLogin(button) {
  if (button) button.disabled = true;
  try {
    if (!hasShellBridge()) {
      throw new Error("请在桌面壳中连接知乎");
    }
    await api("/api/v1/platform-connections/zhihu/connect", {
      method: "POST",
      body: JSON.stringify({}),
    });
    const connection = await saveZhihuShellResult(await requestZhihuShellAction("open_login"));
    showNotice(connection.message || "知乎登录状态已更新", ["EXPIRED", "REAUTH_REQUIRED", "RISK_CONTROLLED"].includes(connection.status));
    await loadPlatformConnections();
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    if (button) button.disabled = false;
  }
}

async function checkPlatformConnection(platform, button) {
  if (button) {
    button.disabled = true;
  }
  try {
    let connection;
    if (platform === "xiaohongshu") {
      connection = await saveXhsShellResult(await requestXhsShellAction("check_session"));
    } else if (platform === "zhihu") {
      connection = await saveZhihuShellResult(await requestZhihuShellAction("check_session"));
    } else {
      connection = await api("/api/v1/platform-connections/" + platform + "/check", { method: "POST" });
    }
    showNotice(connection.status === "CONNECTED" ? connection.display_name + "连接可用" : connection.message, connection.status !== "CONNECTED" && connection.status !== "UNSUPPORTED");
    await loadPlatformConnections();
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    if (button) {
      button.disabled = false;
    }
  }
}

async function disconnectPlatform(platform, button) {
  if (button) {
    button.disabled = true;
  }
  try {
    if (platform === "xiaohongshu" || platform === "zhihu") {
      const zhihu = platform === "zhihu";
      const result = zhihu
        ? await requestZhihuShellAction("disconnect_session")
        : await requestXhsShellAction("disconnect_session");
      if (result.status !== "NOT_CONNECTED" || result.session_invalidated !== true) {
        throw new Error(result.message || `${zhihu ? "知乎" : "小红书"}会话未能确认失效，连接记录已保留`);
      }
      await api(`/api/v1/platform-connections/${platform}`, { method: "DELETE" });
      showNotice(`${zhihu ? "知乎" : "小红书"}会话已清除并确认失效`);
      await loadPlatformConnections();
      return;
    }
    stopBilibiliQrPoll();
    await api("/api/v1/platform-connections/" + platform, { method: "DELETE" });
    clearBilibiliQrPanel();
    showNotice("平台连接已断开");
    await loadSettings();
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    if (button) {
      button.disabled = false;
    }
  }
}

async function checkAllPlatformConnections() {
  const button = document.querySelector("#refresh-platform-connections");
  if (button) {
    button.disabled = true;
  }
  try {
    const report = await api("/api/v1/platform-connections");
    let browserCheckDeferred = false;
    for (const connection of report.connections) {
      if (connection.platform === "xiaohongshu" || connection.platform === "zhihu") {
        if (hasShellBridge()) {
          if (connection.platform === "zhihu") {
            await saveZhihuShellResult(await requestZhihuShellAction("check_session"));
          } else {
            await saveXhsShellResult(await requestXhsShellAction("check_session"));
          }
        } else {
          browserCheckDeferred = true;
        }
      } else {
        await api("/api/v1/platform-connections/" + connection.platform + "/check", { method: "POST" });
      }
    }
    await loadPlatformConnections();
    if (browserCheckDeferred) {
      showNotice("小红书和知乎登录状态需在桌面壳中检查");
    }
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    if (button) {
      button.disabled = false;
    }
  }
}
function renderDataGovernance(report) {
  const source = document.querySelector("#retention-source-days");
  const cache = document.querySelector("#retention-cache-days");
  const status = document.querySelector("#data-governance-status");
  const meta = document.querySelector("#data-governance-meta");
  if (source) source.value = report.source_retention_days || 30;
  if (cache) cache.value = report.cache_retention_days || 7;
  if (status) {
    status.className = "environment-check-status is-ok";
    status.textContent = "可回收 " + report.candidate_count + " 项 · " + formatBytes(report.candidate_bytes);
  }
  if (meta) {
    meta.textContent = "归档目录：" + report.archive_root
      + " · 回收站：" + report.trash_root
      + " · 原始媒体 " + (report.by_kind?.source || 0)
      + " · 字幕 " + (report.by_kind?.subtitle || 0)
      + " · 缓存 " + (report.by_kind?.cache || 0);
  }
}

async function loadDataGovernance() {
  try {
    renderDataGovernance(await api("/api/v1/data-governance"));
  } catch (error) {
    const status = document.querySelector("#data-governance-status");
    if (status) {
      status.className = "environment-check-status is-error";
      status.textContent = "加载失败：" + error.message;
    }
  }
}

async function loadMeta() {
  try {
    const meta = await api("/api/v1/meta");
    const target = document.querySelector("#app-meta-status");
    if (target) {
      target.textContent = "版本 " + meta.version + " · 已知问题 " + (meta.known_issues || []).length + " 项："
        + (meta.known_issues || []).join("；");
    }
  } catch (error) {
    const target = document.querySelector("#app-meta-status");
    if (target) target.textContent = "版本信息加载失败：" + error.message;
  }
}

async function saveRetention() {
  const button = document.querySelector("#save-retention");
  if (button) button.disabled = true;
  try {
    const report = await api("/api/v1/data-governance", {
      method: "PUT",
      body: JSON.stringify({
        source_retention_days: Number(document.querySelector("#retention-source-days").value || 30),
        cache_retention_days: Number(document.querySelector("#retention-cache-days").value || 7),
      }),
    });
    renderDataGovernance(report);
    showNotice("数据保留策略已保存");
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    if (button) button.disabled = false;
  }
}

async function cleanupData() {
  const button = document.querySelector("#cleanup-data");
  if (button) button.disabled = true;
  try {
    const preview = await api("/api/v1/data-governance/cleanup", {
      method: "POST",
      body: JSON.stringify({ execute: false }),
    });
    renderDataGovernance(preview);
    if (!preview.candidate_count) {
      showNotice("当前没有达到保留期限的可回收数据");
      return;
    }
    if (!window.confirm("将把 " + preview.candidate_count + " 项数据移动到可恢复回收站，继续吗？")) {
      showNotice("已取消清理");
      return;
    }
    const result = await api("/api/v1/data-governance/cleanup", {
      method: "POST",
      body: JSON.stringify({ execute: true }),
    });
    renderDataGovernance(result);
    showNotice("已清理 " + result.moved.length + " 项，可从本机回收站回撤");
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    if (button) button.disabled = false;
  }
}

async function backupData() {
  const button = document.querySelector("#backup-data");
  if (button) button.disabled = true;
  try {
    const result = await api("/api/v1/data-governance/backup", { method: "POST" });
    document.querySelector("#restore-backup-path").value = result.path;
    showNotice("备份已生成：" + result.path);
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    if (button) button.disabled = false;
  }
}

async function restoreData() {
  const input = document.querySelector("#restore-backup-path");
  const path = input.value.trim();
  if (!path) {
    showNotice("请先填写备份文件路径", true);
    return;
  }
  const button = document.querySelector("#restore-data");
  if (button) button.disabled = true;
  try {
    const result = await api("/api/v1/data-governance/restore", {
      method: "POST",
      body: JSON.stringify({ path }),
    });
    showNotice("已恢复 " + result.restored_content_count + " 条内容和 " + result.restored_archive_files + " 个归档文件");
    await loadDataGovernance();
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    if (button) button.disabled = false;
  }
}

async function loadSettings() {
  try {
    const settings = await api("/api/v1/settings");
    applyAiAskSwitch(settings);
    settingsPanel.replaceChildren();
    const asrEngine = settings.asr_engine || "cloud";
    const asrLabel = asrEngine === "local" ? "本地模型" : "云端 ASR";
    const entries = [
      ["默认总结方式", settings.default_model || "未选择"],
      ["总结模型", settings.summary_configured
        ? settings.summary_model + "（已配置）"
        : (settings.summary_model || "未选择") + "（未配置）"],
      ["外部 AI", settings.external_ai_configured ? "已配置" : "未配置"],
      ["B站授权会话", settings.bilibili_connected ? "已连接（二维码会话）" : "未连接（请在下方生成 B站二维码）"],
      ["公开 ASR", ""],
    ];
    entries.forEach(([label, value]) => {
      const term = document.createElement("dt");
      term.textContent = label;
      const definition = document.createElement("dd");
      definition.textContent = value;
      settingsPanel.append(term, definition);
    });
    const asrForm = document.querySelector("#asr-form");
    document.querySelector("#archive-root").value = settings.archive_root || "";
    state.settings = settings;
    const askCloudKey = document.querySelector("#ai-ask-cloud-api-key");
    if (askCloudKey) {
      askCloudKey.value = "";
      askCloudKey.placeholder = settings.ai_ask_cloud_configured
        ? "已保存 ·••••••••（输入新 Key 可替换）"
        : "粘贴 API Key（保存后不会回显）";
    }
    const askCloudStatus = document.querySelector("#ai-ask-cloud-status");
    if (askCloudStatus) {
      askCloudStatus.textContent = settings.ai_ask_cloud_configured
        ? "已配置"
        : "未配置 · AI 问答无法检索";
    }
    const savedSummaryProvider = normalizeSummaryProvider(settings.summary_provider);
    const savedSummaryUrl = settings.summary_api_url || "";
    const savedSummaryMode = settings.summary_api_mode || summaryApiModeForEndpoint(savedSummaryUrl);
    document.querySelector("#summary-api-key").value = "";
    // A persisted URL is always user-owned; a provider preset never replaces
    // a non-empty URL during a later provider switch.
    state.summarySavedIdentity = settings.summary_configured
      ? {
        provider: savedSummaryProvider,
        endpoint: summaryBaseUrlForIdentity(savedSummaryUrl),
        mode: savedSummaryMode,
      }
      : null;
    document.querySelector("#summary-provider").value = savedSummaryProvider;
    document.querySelector("#summary-api-url").value = savedSummaryUrl;
    document.querySelector("#summary-api-mode").value = savedSummaryMode;
    document.querySelector("#summary-model").value = settings.summary_model || "";
    const cachedSummaryModels = settings.summary_configured && settings.summary_api_key_configured
      ? await loadSummaryModelCatalog({
        provider: savedSummaryProvider,
        endpoint: summaryBaseUrlForIdentity(savedSummaryUrl),
        mode: savedSummaryMode,
      })
      : [];
    state.summaryConnection = {
      status: settings.summary_configured ? "saved" : "unconfigured",
      models: cachedSummaryModels,
      generation: 0,
      discoveryFingerprint: "",
      testFingerprint: "",
      validationToken: null,
    };
    renderSummaryModelOptions(cachedSummaryModels);
    setSummaryModelPickerEnabled(settings.summary_configured);
    document.querySelector("#summary-api-key").placeholder = settings.summary_api_key_configured
      ? "已保存 ·••••••••（输入新 Key 可替换）"
      : "粘贴 API Key（保存后不会回显）";
    const summaryPrompt = document.querySelector("#summary-prompt");
    const hasPromptDraft = state.summaryPromptDraft !== null;
    if (summaryPrompt && !hasPromptDraft) {
      summaryPrompt.value = settings.summary_prompt || "";
      state.summaryPromptSaveStatus = "saved";
      state.summaryPromptSaveError = "";
    }
    document.querySelector("#summary-skills-root").value = settings.summary_skills_root || "";
    const aiTagToggle = document.querySelector("#ai-tag-recommendation-enabled");
    if (aiTagToggle) aiTagToggle.checked = Boolean(settings.ai_tag_recommendation_enabled);
    renderSummarySkills(settings);
    renderSummaryPromptMeta(settings, hasPromptDraft);
    renderSummaryStatus(settings);
    showSummaryValidation("");
    const asrProvider = normalizeAsrProvider(
      settings.asr_provider || asrProviderForEndpoint(settings.asr_cloud_api_url || settings.asr_api_url),
    );
    document.querySelector("#asr-provider").value = asrProvider;
    document.querySelector("#asr-engine").value = asrEngine;
    renderAsrEngineLabels(settings.asr_configured, asrEngine, state.localAsrRuntimeAvailable);
    renderAsrEngine(asrEngine);
    renderAsrProviderHint(asrProvider);
    renderAsrStatus(settings.asr_configured, asrEngine);
    document.querySelector("#asr-api-details").open = !settings.asr_cloud_configured;
    asrForm.dataset.asrConfigured = settings.asr_configured ? "true" : "false";
    document.querySelector("#asr-api-url").value = settings.asr_cloud_api_url || settings.asr_api_url || "";
    document.querySelector("#asr-model").value = settings.asr_cloud_model || settings.asr_model || "";
    state.asrSavedIdentity = settings.asr_cloud_configured
      ? {
        provider: asrProvider,
        endpoint: asrBaseUrlForIdentity(settings.asr_cloud_api_url || settings.asr_api_url),
      }
      : null;
    state.asrConnection = {
      status: settings.asr_cloud_configured ? "saved" : "unconfigured",
      models: [],
      modelsSupported: null,
      generation: 0,
      discoveryFingerprint: "",
      testFingerprint: "",
    };
    state.asrCopySummaryKeyOnSave = false;
    renderAsrModelOptions([]);
    document.querySelector("#asr-local-model").dataset.selectedModel = settings.asr_local_model || "";
    document.querySelector("#asr-api-key").value = "";
    document.querySelector("#asr-api-key").placeholder = settings.asr_cloud_configured
      ? "已保存 ·••••••••（输入新 Key 可替换）"
      : "粘贴 API Key（保存后不会回显）";
    renderAsrModelAvailability();
    document.querySelector("#asr-copy-status").textContent = "";
    showAsrValidation("");
    // 始终加载本地模型状态：让引擎选项与“本地模型”面板的组件状态从一开始就准确
    await loadLocalAsrModels();
    updateAsrSettingsSummary();
    await loadPlatformConnections();
    await loadDataGovernance();
    await loadMeta();
    showSettingsSection(state.settingsSection);
  } catch (error) {
    showNotice(error.message, true);
  }
}

function resetSummarySkillSelection() {
  const select = document.querySelector("#summary-skill");
  const meta = document.querySelector("#summary-skill-meta");
  if (select) select.value = "";
  if (meta) meta.textContent = "目录已更换；保存后会重新加载该目录下的 Skill 文件。";
}

async function pickSummarySkillsRoot() {
  const button = document.querySelector("#pick-summary-skills-root");
  if (button) button.disabled = true;
  try {
    const result = await api("/api/v1/settings/summary/skills-root/pick", { method: "POST" });
    if (result.path) {
      document.querySelector("#summary-skills-root").value = result.path;
      resetSummarySkillSelection();
      showSummaryValidation("Skill 存储目录已选择，保存总结配置后生效。");
    }
  } catch (error) {
    showSummaryValidation(error.message);
  } finally {
    if (button) button.disabled = false;
  }
}

async function pickArchiveRoot() {
  const button = document.querySelector("#pick-archive-root");
  if (button) {
    button.disabled = true;
  }
  try {
    const result = await api("/api/v1/settings/archive-root/pick", { method: "POST" });
    if (result.path) {
      document.querySelector("#archive-root").value = result.path;
    }
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    if (button) {
      button.disabled = false;
    }
  }
}

async function saveArchiveSettings() {
  const archiveRoot = document.querySelector("#archive-root").value.trim();
  if (!archiveRoot) {
    showNotice("请选择或填写归档位置", true);
    return;
  }
  const button = document.querySelector("#save-archive-root");
  if (button) {
    button.disabled = true;
  }
  try {
    const settings = await api("/api/v1/settings", {
      method: "PUT",
      body: JSON.stringify({ archive_root: archiveRoot }),
    });
    showNotice("归档位置已保存：" + settings.archive_root);
    await loadSettings();
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    if (button) {
      button.disabled = false;
    }
  }
}
function renderEnvironmentCheck(report) {
  const status = document.querySelector("#environment-check-status");
  const list = document.querySelector("#environment-check-list");
  if (!status || !list) return;
  const labels = { ok: "检查通过", warning: "存在提醒", error: "存在阻断项" };
  status.className = `environment-check-status is-${report.status}`;
  status.textContent = `${labels[report.status] || "检查完成"} · ${report.checked_at || ""}`;
  list.replaceChildren();
  for (const item of report.checks || []) {
    const row = document.createElement("div");
    row.className = `environment-check-item is-${item.status}`;
    const heading = document.createElement("strong");
    heading.textContent = `${item.label}：${item.status === "ok" ? "通过" : item.status === "warning" ? "提醒" : "阻断"}`;
    const message = document.createElement("span");
    message.textContent = item.message || "";
    row.append(heading, message);
    if (item.action) {
      const action = document.createElement("small");
      action.textContent = `建议：${item.action}`;
      row.append(action);
    }
    list.append(row);
  }
}

async function checkEnvironment() {
  const button = document.querySelector("#check-environment");
  const status = document.querySelector("#environment-check-status");
  if (button) button.disabled = true;
  if (status) {
    status.className = "environment-check-status is-loading";
    status.textContent = "检查中…";
  }
  try {
    const report = await api("/api/v1/environment/check?check_network=true");
    renderEnvironmentCheck(report);
  } catch (error) {
    if (status) {
      status.className = "environment-check-status is-error";
      status.textContent = `检查失败：${error.message}`;
    }
    showNotice(error.message, true);
  } finally {
    if (button) button.disabled = false;
  }
}
function summaryConfigFromForm(includeKey = true) {
  const payload = {
    summary_engine: "openai-compatible",
    summary_provider: document.querySelector("#summary-provider").value,
    summary_api_url: document.querySelector("#summary-api-url").value.trim() || null,
    summary_api_mode: document.querySelector("#summary-api-mode").value,
    summary_model: document.querySelector("#summary-model").value.trim() || null,
    summary_skill_path: document.querySelector("#summary-skill").value || null,
    summary_skills_root: document.querySelector("#summary-skills-root").value.trim() || null,
    ai_tag_recommendation_enabled: Boolean(document.querySelector("#ai-tag-recommendation-enabled")?.checked),
  };
  const apiKey = document.querySelector("#summary-api-key").value.trim();
  if (includeKey && apiKey) {
    payload.summary_api_key = apiKey;
  }
  return payload;
}

function scheduleSummaryPromptSave() {
  const input = document.querySelector("#summary-prompt");
  if (!input) return;
  const prompt = input.value;
  state.summaryPromptDraft = prompt;
  state.summaryPromptSaveSequence += 1;
  const sequence = state.summaryPromptSaveSequence;
  window.clearTimeout(state.summaryPromptSaveTimer);
  state.summaryPromptSaveStatus = "saving";
  state.summaryPromptSaveError = "";
  renderSummaryPromptMeta(state.settings, true);
  state.summaryPromptSaveTimer = window.setTimeout(() => {
    state.summaryPromptSaveTimer = null;
    saveSummaryPrompt(prompt, sequence);
  }, 700);
}

async function saveSummaryPrompt(prompt, sequence) {
  if (sequence !== state.summaryPromptSaveSequence || state.summaryPromptDraft !== prompt) return;
  try {
    const settings = await api("/api/v1/settings", {
      method: "PUT",
      body: JSON.stringify({ summary_prompt: prompt }),
    });
    if (sequence !== state.summaryPromptSaveSequence || state.summaryPromptDraft !== prompt) return;
    state.settings = settings;
    state.summaryPromptDraft = null;
    state.summaryPromptSaveStatus = "saved";
    state.summaryPromptSaveError = "";
    renderSummaryPromptMeta(settings);
  } catch (error) {
    if (sequence !== state.summaryPromptSaveSequence || state.summaryPromptDraft !== prompt) return;
    state.summaryPromptSaveStatus = "failed";
    state.summaryPromptSaveError = error?.message || "请求未完成";
    renderSummaryPromptMeta(state.settings, true);
  }
}

function retrySummaryPromptSave() {
  scheduleSummaryPromptSave();
}

function validateSummaryDraft(payload) {
  const endpointError = summaryEndpointError(payload.summary_api_url, payload.summary_api_mode);
  if (endpointError) {
    showSummaryValidation(endpointError);
    return false;
  }
  if (!payload.summary_model) {
    showSummaryValidation("请填写总结模型 ID。");
    return false;
  }
  const apiKey = document.querySelector("#summary-api-key").value.trim();
  if (!apiKey && !summaryApiKeyAvailable()) {
    showSummaryValidation("请填写 API 密钥；切换服务商或地址后不能复用旧密钥。");
    return false;
  }
  if (apiKey && apiKey.length < 8) {
    showSummaryValidation("API Key 太短，请检查是否粘贴完整。");
    return false;
  }
  return true;
}

function summaryEndpointError(endpoint, apiMode = "chat_completions") {
  if (!endpoint) return "请填写完整的大模型接口地址，或选择一个服务商预设。";
  if (!["chat_completions", "responses"].includes(apiMode)) {
    return "接口类型不受支持。";
  }
  try {
    const parsedUrl = new URL(endpoint);
    if (!["http:", "https:"].includes(parsedUrl.protocol) || !parsedUrl.hostname) {
      return "接口地址必须使用 http 或 https。";
    }
    const path = parsedUrl.pathname.replace(/\/+$/, "").toLowerCase();
    if (path.endsWith("/chat/completions") && apiMode !== "chat_completions") {
      return "接口类型与地址末尾的 /chat/completions 不匹配。";
    }
    if (path.endsWith("/responses") && apiMode !== "responses") {
      return "接口类型与地址末尾的 /responses 不匹配。";
    }
  } catch (_error) {
    return "接口地址格式不正确。";
  }
  return "";
}


function summaryConnectionPayload(includeModel = false) {
  const payload = {
    summary_engine: "openai-compatible",
    summary_provider: normalizeSummaryProvider(document.querySelector("#summary-provider")?.value),
    summary_api_url: document.querySelector("#summary-api-url")?.value.trim() || null,
    summary_api_mode: document.querySelector("#summary-api-mode")?.value || "chat_completions",
    summary_api_key: document.querySelector("#summary-api-key")?.value.trim() || null,
  };
  if (includeModel) {
    payload.summary_model = document.querySelector("#summary-model")?.value.trim() || null;
  }
  return payload;
}

function setSummaryFormBusy(busy) {
  const form = document.querySelector("#summary-form");
  if (!form) return;
  if (busy) {
    if (state.summaryFormLock) return;
    const controls = Array.from(form.querySelectorAll("input, select, textarea, button"));
    state.summaryFormLock = controls.map((control) => ({ control, disabled: control.disabled }));
    controls.forEach((control) => { control.disabled = true; });
    return;
  }
  const snapshot = state.summaryFormLock;
  state.summaryFormLock = null;
  snapshot?.forEach(({ control, disabled }) => { control.disabled = disabled; });
}

function abortSummarySave(message) {
  state.summaryConnection.status = "editing";
  state.summaryConnection.validationToken = null;
  showSummaryValidation(message);
  renderSummaryStatus(state.settings, true);
}

async function saveSummarySettings(event = null) {
  event?.preventDefault();
  if (state.summaryFormLock) return;
  const payload = summaryConfigFromForm(true);
  if (!validateSummaryDraft(payload)) return;
  window.clearTimeout(state.summaryDiscoveryTimer);
  state.summaryDiscoveryTimer = null;
  const generation = state.summaryConnection?.generation || 0;
  const fingerprint = summaryTestFingerprint();
  setSummaryFormBusy(true);
  state.summaryConnection.status = "verifying";
  renderSummaryStatus(state.settings, true);
  showSummaryValidation("正在验证所选总结模型…");
  let saveStage = "validation";
  try {
    const validation = await api("/api/v1/settings/summary/test", {
      method: "POST",
      body: JSON.stringify(summaryConnectionPayload(true)),
    });
    if (generation !== state.summaryConnection?.generation || fingerprint !== summaryTestFingerprint()) {
      abortSummarySave("配置已修改，已忽略旧的验证结果，请重新验证。");
      return;
    }
    if (!validation.validation_token) {
      throw new Error("连接验证未返回保存凭证，请重新验证。");
    }
    payload.summary_validation_token = validation.validation_token;
    if (generation !== state.summaryConnection?.generation || fingerprint !== summaryTestFingerprint()) {
      abortSummarySave("配置已修改，已忽略旧的验证结果，请重新验证。");
      return;
    }
    state.summaryConnection.status = "verified";
    state.summaryConnection.testFingerprint = fingerprint;
    state.summaryConnection.validationToken = validation.validation_token;
    renderSummaryStatus(state.settings, true);
    saveStage = "save";
    const settings = await api("/api/v1/settings", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    if (generation !== state.summaryConnection?.generation) {
      await loadSettings();
      showNotice("总结配置已保存；检测到期间有新改动，请重新编辑");
      return;
    }
    document.querySelector("#summary-api-key").value = "";
    showNotice(settings.summary_configured ? "总结模型配置已保存" : "总结配置已保存，请补充 API Key 或测试连接");
    await loadSettings();
  } catch (error) {
    const failedDuringSave = saveStage === "save";
    state.summaryConnection.status = failedDuringSave ? "save_failed" : "validation_failed";
    state.summaryConnection.validationToken = null;
    showSummaryValidation(`${failedDuringSave ? "API 配置保存失败" : "模型连接验证失败"}：${error.message || "请求未完成"}`);
    renderSummaryStatus(state.settings, true);
  } finally {
    setSummaryFormBusy(false);
  }
}

async function clearSummarySettings() {
  try {
    await api("/api/v1/settings", {
      method: "PUT",
      body: JSON.stringify({
        summary_engine: "openai-compatible",
        summary_provider: "custom",
        summary_api_url: null,
        summary_api_mode: null,
        summary_api_key: null,
        summary_model: null,
        summary_skill_path: null,
      }),
    });
    showNotice("总结模型配置已清除，请重新配置模型服务");
    await loadSettings();
  } catch (error) {
    showSummaryValidation(error.message);
  }
}

function asrEndpointError(endpoint) {
  if (!endpoint) return "请填写完整的 ASR 转写接口地址，或先从 AI 接口复制。";
  try {
    const parsed = new URL(endpoint);
    if (!["http:", "https:"].includes(parsed.protocol) || !parsed.hostname) {
      return "ASR 接口地址必须使用 http 或 https。";
    }
  } catch (_error) {
    return "ASR 接口地址格式不正确。";
  }
  return "";
}

function asrUrlFromSummaryUrl(url) {
  const normalized = String(url || "").trim().replace(/\/+$/, "");
  return normalized.replace(/\/(chat\/completions|responses)$/i, "") + "/audio/transcriptions";
}

function summaryKeyForAsrCopy() {
  const entered = document.querySelector("#summary-api-key")?.value.trim() || "";
  if (entered) return { source: "entered", key: entered };
  if (state.settings?.summary_api_key_configured && summaryIdentityMatchesSaved()) {
    return { source: "saved", key: null };
  }
  return null;
}

function copySummaryConfigToAsr() {
  const summaryUrl = document.querySelector("#summary-api-url")?.value.trim() || "";
  if (!summaryUrl) {
    showAsrValidation("请先填写总结 API 地址，再从 AI 接口复制。");
    return;
  }
  const provider = normalizeAsrProvider(document.querySelector("#summary-provider")?.value);
  const asrProvider = document.querySelector("#asr-provider");
  if (asrProvider) asrProvider.value = provider;
  document.querySelector("#asr-api-url").value = asrUrlFromSummaryUrl(summaryUrl);
  const keySource = summaryKeyForAsrCopy();
  const asrKey = document.querySelector("#asr-api-key");
  const copyStatus = document.querySelector("#asr-copy-status");
  if (keySource?.source === "entered") {
    // This is an in-memory handoff only; it is sent to ASR when the user
    // explicitly fetches models or saves the ASR form.
    asrKey.value = keySource.key;
    state.asrCopySummaryKeyOnSave = false;
    asrKey.placeholder = "已从当前总结输入复制（保存后不会回显）";
    if (copyStatus) copyStatus.textContent = "已复制接口和当前输入的 API Key；尚未保存 ASR。";
  } else if (keySource?.source === "saved") {
    // Never read the saved summary secret in the browser.  The next ASR PUT
    // carries only this explicit marker for backend-side secure copying.
    asrKey.value = "";
    state.asrCopySummaryKeyOnSave = true;
    asrKey.placeholder = "保存时从已保存的总结 API Key 复制";
    if (copyStatus) copyStatus.textContent = "已复制接口；保存 ASR 时由后端复制已保存的总结 API Key。";
  } else {
    asrKey.value = "";
    state.asrCopySummaryKeyOnSave = false;
    asrKey.placeholder = "请填写 API Key（保存后不会回显）";
    if (copyStatus) copyStatus.textContent = "已复制接口；当前没有可复制的总结 API Key，请填写 ASR API Key。";
  }
  invalidateAsrConnection();
  renderAsrProviderHint(provider);
  renderAsrModelAvailability();
  document.querySelector("#asr-api-details").open = true;
  showAsrValidation("");
}

async function discoverAsrModels() {
  const endpoint = document.querySelector("#asr-api-url")?.value.trim() || "";
  const endpointError = asrEndpointError(endpoint);
  if (endpointError) {
    showAsrValidation(endpointError);
    return;
  }
  if (!asrRequestKey() && !asrSavedKeyAvailable()) {
    showAsrValidation(state.asrCopySummaryKeyOnSave
      ? "当前只有已保存的总结 API Key；获取模型前请填写 ASR API Key，或手动填写模型 ID 后直接保存。"
      : "请填写 ASR API Key；已保存的总结 API Key 只会在保存 ASR 时由后端复制。" );
    return;
  }
  const generation = (state.asrConnection?.generation || 0) + 1;
  const fingerprint = asrDiscoveryFingerprint();
  state.asrConnection = {
    status: "discovering",
    models: [],
    modelsSupported: null,
    generation,
    discoveryFingerprint: fingerprint,
    testFingerprint: "",
  };
  renderAsrModelOptions([]);
  setAsrModelPickerOpen(false);
  renderAsrModelAvailability();
  showAsrValidation("正在获取 ASR 模型…");
  const button = document.querySelector("#test-asr");
  if (button) button.disabled = true;
  try {
    const result = await api("/api/v1/settings/asr/models", {
      method: "POST",
      body: JSON.stringify(asrConnectionPayload(false)),
    });
    if (generation !== state.asrConnection?.generation || fingerprint !== asrDiscoveryFingerprint()) return;
    const models = result.models || [];
    state.asrConnection = {
      status: result.models_supported === false ? "manual" : "awaiting_model",
      models,
      modelsSupported: result.models_supported !== false,
      generation,
      discoveryFingerprint: fingerprint,
      testFingerprint: "",
    };
    renderAsrModelOptions(models);
    renderAsrModelAvailability();
    showAsrValidation(result.message || (models.length ? "识别成功，请选择 ASR 模型" : "请手动填写 ASR 模型 ID"));
  } catch (error) {
    if (generation !== state.asrConnection?.generation) return;
    state.asrConnection.status = "failed";
    state.asrConnection.testFingerprint = "";
    showAsrValidation(error.message);
    renderAsrModelAvailability();
  } finally {
    if (button) button.disabled = false;
  }
}

async function testAsrConnection(payload) {
  const result = await api("/api/v1/settings/asr/test", {
    method: "POST",
    body: JSON.stringify({
      provider: payload.asr_provider,
      ...payload,
    }),
  });
  state.asrConnection.status = "verified";
  state.asrConnection.testFingerprint = asrDiscoveryFingerprint();
  showAsrValidation(result.message || "ASR 模型连接成功");
  return result;
}

async function saveAsrSettings(event) {
  event.preventDefault();
  const engine = document.querySelector("#asr-engine").value;
  const apiKey = asrRequestKey();
  let payload;

  if (engine === "local") {
    const model = document.querySelector("#asr-local-model").value;
    const selected = state.localAsrModels[model];
    if (!selected || !localAsrModelReady(selected)) {
      showAsrValidation("请先扫描或下载一个完整的本地模型。");
      return;
    }
    if (!selected.usable && !state.localAsrRuntimeAvailable) {
      showAsrValidation("模型文件已经就绪，但本地运行组件尚未安装，请先点击“安装缺失组件”。");
      return;
    }
    payload = { asr_engine: "local", asr_model: model };
  } else {
    const apiUrl = document.querySelector("#asr-api-url").value.trim();
    const model = document.querySelector("#asr-model").value.trim();
    const endpointError = asrEndpointError(apiUrl);
    if (endpointError) {
      showAsrValidation(endpointError);
      return;
    }
    if (!model) {
      showAsrValidation("请填写识别模型。");
      return;
    }
    if (apiKey && apiKey.length < 8) {
      showAsrValidation("API Key 太短，请检查是否粘贴完整。");
      return;
    }
    if (!apiKey && !asrSavedKeyAvailable() && !state.asrCopySummaryKeyOnSave) {
      showAsrValidation("请填写 ASR API Key；或先使用“从 AI 接口复制”并确认保存时复制已保存的总结密钥。");
      return;
    }
    payload = {
      asr_engine: "cloud",
      asr_provider: normalizeAsrProvider(document.querySelector("#asr-provider").value),
      asr_api_url: apiUrl,
      asr_model: model,
    };
    if (apiKey) {
      payload.asr_api_key = apiKey;
    }
    if (state.asrCopySummaryKeyOnSave && !apiKey) {
      payload.copy_summary_key = true;
    }
  }

  const saveButton = document.querySelector("#save-asr");
  if (saveButton) saveButton.disabled = true;
  try {
    // Normal cloud drafts are checked before the one and only settings PUT.
    // A saved-summary-key copy has no browser-readable credential, so its
    // explicit PUT is the backend's first secure handoff and must not be
    // preceded by a second save.
    if (engine === "cloud" && !(state.asrCopySummaryKeyOnSave && !apiKey)) {
      state.asrConnection.status = "verifying";
      showAsrValidation("正在验证 ASR 模型…");
      await testAsrConnection({
        ...payload,
        asr_api_key: apiKey,
      });
    }
    const settings = await api("/api/v1/settings", { method: "PUT", body: JSON.stringify(payload) });
    document.querySelector("#asr-api-key").value = "";
    state.asrCopySummaryKeyOnSave = false;
    showNotice(
      settings.asr_configured
        ? (engine === "local" ? "本地 ASR 已保存" : "公开 ASR 已保存")
        : "参数已保存，请补充配置",
    );
    await loadSettings();
  } catch (error) {
    state.asrConnection.status = "failed";
    showAsrValidation(error.message);
  } finally {
    if (saveButton) saveButton.disabled = false;
  }
}

async function clearAsrSettings() {
  const engine = document.querySelector("#asr-engine").value;
  const payload = engine === "local"
    ? { asr_local_model: null }
    : { asr_engine: "cloud", asr_api_key: null, asr_api_url: null, asr_model: null };
  try {
    await api("/api/v1/settings", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    showNotice(engine === "local" ? "本地 ASR 默认模型已清除（已下载模型不会删除）" : "云端 ASR 配置已清除");
    await loadSettings();
  } catch (error) {
    showNotice(error.message, true);
  }
}


document.querySelector("#pick-archive-root").addEventListener("click", pickArchiveRoot);
document.querySelector("#save-archive-root").addEventListener("click", saveArchiveSettings);
document.querySelector("#check-environment").addEventListener("click", checkEnvironment);
document.querySelector("#save-retention").addEventListener("click", saveRetention);
document.querySelector("#cleanup-data").addEventListener("click", cleanupData);
document.querySelector("#backup-data").addEventListener("click", backupData);
document.querySelector("#restore-data").addEventListener("click", restoreData);
document.querySelector("#pick-summary-skills-root").addEventListener("click", pickSummarySkillsRoot);
document.querySelector("#import-form").addEventListener("submit", startImport);
queryLinksButton?.addEventListener("click", () => {
  const value = sourceUrlInput?.value.trim() || "";
  if (!state.pendingCollectionScan && state.linkQuery && state.linkQuery.rawInput === value) {
    renderLinkQueryDialog(state.linkQuery);
    return;
  }
  queryLinks();
});
queryLocalButton?.addEventListener("click", queryLocalSource);
document.querySelector("#import-form").addEventListener("reset", () => {
  window.setTimeout(() => {
    const inputPanel = document.querySelector("#input-panel");
    if (inputPanel) inputPanel.open = true;
    clearTaskPreflight();
    state.linkQuery = null;
    state.linkQuerySelectedIds = new Set();
    state.pendingCollectionScan = null;
    state.localQuery = null;
    state.localFileName = "";
    const localFileName = document.querySelector("#local-file-name");
    if (localFileName) localFileName.textContent = "支持 TXT、MD、SRT、VTT";
    if (intakeTaskStatusPanel) intakeTaskStatusPanel.hidden = true;
    updateLinkHint();
    updateInputPanelSummary();
  }, 0);
});
document.querySelector("#refresh-job").addEventListener("click", async () => {
  await loadTaskList();
  if (state.activeJobId) await pollJob({ forceEvents: true });
});
taskFilterButtons.forEach((button) => button.addEventListener("click", () => {
  state.taskFilter = button.dataset.taskFilter || "all";
  taskFilterButtons.forEach((item) => {
    const active = item === button;
    item.classList.toggle("is-active", active);
    item.setAttribute("aria-selected", String(active));
  });
  renderTaskList();
}));
const historyFilterPanel = document.querySelector("#history-filter-panel");
const historyFilterToggle = document.querySelector("#open-history-filters");
const historySearchForm = document.querySelector("#history-search-form");
const setHistoryFiltersOpen = (open, focus = false) => {
  if (!historyFilterPanel || !historyFilterToggle) return;
  historyFilterPanel.hidden = !open;
  historyFilterToggle.setAttribute("aria-expanded", String(open));
  if (open && focus) document.querySelector("#history-query")?.focus();
};
historySearchForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  loadHistory();
});
historyFilterToggle?.addEventListener("click", () => {
  setHistoryFiltersOpen(Boolean(historyFilterPanel?.hidden));
});
document.querySelector("#apply-history-filters")?.addEventListener("click", () => loadHistory());
document.querySelector("#create-favorite-folder").addEventListener("click", createFavoriteFolder);
document.querySelector("#add-favorite-content")?.addEventListener("click", () => {
  const folder = state.favoriteFolders.find((item) => item.id === state.activeFavoriteFolderId);
  if (!folder) {
    showNotice("请先点击要添加内容的收藏夹", true);
    return;
  }
  openFavoriteContentAdd(folder);
});
document.querySelector("#backfill-introductions")?.addEventListener("click", (event) => {
  previewIntroductionBackfill(event.currentTarget);
});
document.querySelector("#show-trash").addEventListener("click", () => loadHistory({ trash: !state.showingTrash }));
document.querySelector("#history-sort").addEventListener("change", () => loadHistory());
document.querySelector("#history-category").addEventListener("change", () => loadHistory());
document.querySelector("#history-platform").addEventListener("change", () => loadHistory());
document.querySelector("#history-author").addEventListener("change", () => loadHistory());
function returnToResultParent() {
  const source = state.returnContext?.sourceView;
  if (source === "ask") {
    showView("ask", { preserveReturnContext: true });
    return;
  }
  if (source === "batch-detail" && state.activeImportBatchId) {
    loadImportBatch(state.activeImportBatchId, { sourceView: "batch-detail" });
    return;
  }
  showView(source === "tasks" ? "tasks" : "history", { preserveReturnContext: true });
}
document.querySelector("#back-to-history")?.addEventListener("click", returnToResultParent);
document.querySelector("#result-header-back")?.addEventListener("click", returnToResultParent);
document.querySelector("#refresh-platform-connections").addEventListener("click", checkAllPlatformConnections);
document.querySelector("#summary-provider").addEventListener("change", applySummaryProviderPreset);
document.querySelector("#summary-api-url").addEventListener("input", invalidateSummaryConnection);
document.querySelector("#summary-api-url").addEventListener("change", scheduleSummaryModelDiscovery);
document.querySelector("#summary-api-mode").addEventListener("change", invalidateSummaryConnection);
document.querySelector("#summary-api-mode").addEventListener("change", scheduleSummaryModelDiscovery);
document.querySelector("#summary-api-key").addEventListener("input", invalidateSummaryConnection);
document.querySelector("#summary-api-key").addEventListener("change", scheduleSummaryModelDiscovery);
document.querySelector("#summary-model").addEventListener("input", handleSummaryModelInput);
document.querySelector("#summary-model").addEventListener("change", handleSummaryModelChange);
document.querySelector("#summary-model").addEventListener("keydown", handleSummaryModelKeydown);
document.querySelector("#summary-model").addEventListener("focus", () => {
  if (!summaryModelUsesDialog()) setSummaryModelPickerOpen(true);
});
document.querySelector("#summary-model-toggle").addEventListener("click", async () => {
  if (!await ensureSummaryModelsCurrent()) return;
  if (summaryModelUsesDialog()) {
    openSummaryModelDialog();
    return;
  }
  const options = document.querySelector("#summary-model-options");
  setSummaryModelPickerOpen(Boolean(options?.hidden));
});
document.querySelector("#summary-model-options").addEventListener("click", (event) => {
  if (event.detail > 0 && Date.now() < state.summaryModelSuppressClickUntil) return;
  const option = event.target?.closest?.(".summary-model-option");
  if (option?.dataset.model) selectSummaryModel(option.dataset.model);
});
bindSummaryModelPullToRefresh(document.querySelector("#summary-model-options"));
document.querySelector("#summary-model-dialog-search").addEventListener("input", () => {
  state.summaryModelPage = 0;
  renderSummaryModelDialogOptions();
});
document.querySelector("#summary-model-dialog-options").addEventListener("click", (event) => {
  if (event.detail > 0 && Date.now() < state.summaryModelSuppressClickUntil) return;
  const option = event.target?.closest?.(".summary-model-dialog-option");
  if (option?.dataset.model) selectSummaryModel(option.dataset.model);
});
bindSummaryModelPullToRefresh(document.querySelector("#summary-model-dialog-options"));
document.querySelector("#summary-model-page-previous").addEventListener("click", () => {
  state.summaryModelPage -= 1;
  renderSummaryModelDialogOptions();
});
document.querySelector("#summary-model-page-next").addEventListener("click", () => {
  state.summaryModelPage += 1;
  renderSummaryModelDialogOptions();
});
document.querySelector("#summary-model-dialog-close").addEventListener("click", () => {
  document.querySelector("#summary-model-dialog").close();
});
document.querySelector("#summary-model-dialog").addEventListener("close", () => {
  document.querySelector("#summary-model-toggle")?.setAttribute("aria-expanded", "false");
});
document.addEventListener("click", (event) => {
  const picker = document.querySelector(".summary-model-picker");
  if (picker && !picker.contains(event.target)) setSummaryModelPickerOpen(false);
  const asrPicker = document.querySelector(".asr-model-picker");
  if (asrPicker && !asrPicker.contains(event.target)) setAsrModelPickerOpen(false);
});
document.querySelector("#summary-skills-root").addEventListener("change", resetSummarySkillSelection);
document.querySelector("#summary-prompt").addEventListener("input", () => {
  scheduleSummaryPromptSave();
});
document.querySelector("#retry-summary-prompt")?.addEventListener("click", retrySummaryPromptSave);
document.querySelector("#summary-form").addEventListener("submit", saveSummarySettings);
document.querySelector("#ai-ask-cloud-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const key = document.querySelector("#ai-ask-cloud-api-key")?.value.trim();
  if (!key) {
    showNotice("请填写硅基流动 API 密钥");
    return;
  }
  try {
    await api("/api/v1/settings", {
      method: "PUT",
      body: JSON.stringify({ ai_ask_siliconflow_api_key: key }),
    });
    await loadSettings();
    showNotice("问答检索配置已保存，正在为已有归档建立索引");
  } catch (error) {
    showNotice(error.message || "问答检索配置保存失败");
  }
});
document.querySelector("#clear-summary").addEventListener("click", clearSummarySettings);
document.querySelector("#ui-theme")?.addEventListener("change", (event) => {
  applyUiTheme(event.target.value);
  showNotice(event.target.value === "night" ? "已切换到夜间 D 黑白像素主题" : "已切换到白天暖色掌机主题");
});
settingsReturnButton?.addEventListener("click", () => {
  const target = state.settingsReturnView || "intake";
  const preserve = target === "history" && state.returnContext?.sourceView === "history";
  showView(target, { preserveReturnContext: preserve });
});
settingsContent?.addEventListener("scroll", () => {
  state.settingsScrollTops[state.settingsSection] = settingsContent.scrollTop;
});

document.querySelector("#asr-engine").addEventListener("change", async (event) => {
  renderAsrEngine(event.target.value);
  if (event.target.value === "local") {
    await loadLocalAsrModels();
  } else {
    const asrForm = document.querySelector("#asr-form");
    renderAsrEngineLabels(
      asrForm.dataset.asrConfigured === "true",
      event.target.value,
      state.localAsrRuntimeAvailable,
    );
  }
  updateAsrSettingsSummary(true);
});
document.querySelector("#asr-local-source").addEventListener("change", (event) => {
  const source = event.target.value;
  document.querySelector("#asr-local-existing-panel").hidden = source !== "existing";
  document.querySelector("#asr-local-download-panel").hidden = source !== "download";
});
document.querySelector("#asr-provider").addEventListener("change", (event) => {
  applyAsrProviderPreset(event);
  updateAsrSettingsSummary(true);
});
document.querySelector("#asr-api-url").addEventListener("input", (event) => {
  syncAsrProviderFromEndpoint(event);
  updateAsrSettingsSummary(true);
});
document.querySelector("#asr-api-key").addEventListener("input", () => {
  state.asrCopySummaryKeyOnSave = false;
  invalidateAsrConnection();
  updateAsrSettingsSummary(true);
});
document.querySelector("#asr-model").addEventListener("input", handleAsrModelInput);
document.querySelector("#asr-model").addEventListener("change", handleAsrModelChange);
document.querySelector("#asr-model").addEventListener("keydown", handleAsrModelKeydown);
document.querySelector("#asr-model").addEventListener("focus", () => setAsrModelPickerOpen(true));
document.querySelector("#asr-model-toggle").addEventListener("click", () => {
  const options = document.querySelector("#asr-model-options");
  setAsrModelPickerOpen(Boolean(options?.hidden));
});
document.querySelector("#asr-model-options").addEventListener("click", (event) => {
  const option = event.target?.closest?.(".asr-model-option");
  if (option?.dataset.model) selectAsrModel(option.dataset.model);
});
document.querySelector("#asr-local-model").addEventListener("change", (event) => {
  event.target.dataset.selectedModel = event.target.value;
  updateAsrSettingsSummary(true);
});
document.querySelector("#install-asr-runtime").addEventListener("click", installLocalAsrRuntime);
document.querySelector("#scan-import-asr-model").addEventListener("click", scanAndImportLocalAsrModel);
document.querySelector("#download-selected-asr-model").addEventListener("click", downloadSelectedLocalAsrModel);
document.querySelector("#asr-form").addEventListener("submit", saveAsrSettings);
document.querySelector("#test-asr").addEventListener("click", discoverAsrModels);
document.querySelector("#copy-summary-to-asr").addEventListener("click", copySummaryConfigToAsr);
document.querySelector("#clear-asr").addEventListener("click", clearAsrSettings);
bilibiliQrPanel?.addEventListener("close", () => {
  if (state.bilibiliQrKey) {
    stopBilibiliQrPoll({ cancelServer: true });
  } else {
    stopBilibiliQrPoll();
  }
  bilibiliQrPanel.replaceChildren();
});
asrModelDialog?.addEventListener("close", () => asrModelDialog.replaceChildren());
linkQueryDialog?.addEventListener("close", () => {
  if (state.collectionImportContext && state.linkQuery?.collection_import) {
    restoreCollectionImportContext();
  }
  state.linkQueryRequestId += 1;
  if (state.creatorScanId && ["queued", "running"].includes(state.creatorScan?.status)) {
    void cancelCreatorScan();
  }
  state.creatorScanRequestId += 1;
  state.creatorScanId = null;
  window.clearTimeout(state.creatorScanTimer);
  linkQueryDialog.classList.remove("creator-scan-dialog");
  linkQueryDialog.replaceChildren();
});
navButtons.forEach((button) => button.addEventListener("click", () => showView(button.dataset.viewTarget)));

function applyAiAskSwitch(settings) {
  if (settings && settings.enable_ai_ask === false) {
    navAskButton?.remove();
    document.querySelector('[data-view="ask"]')?.remove();
  }
}

function askSelectedValues(selector) {
  return [...(document.querySelector(selector)?.selectedOptions || [])].map((option) => option.value);
}

function renderAskScopeOptions() {
  const contentSelect = document.querySelector("#ask-content-ids");
  const tagSelect = document.querySelector("#ask-tag-ids");
  const folderSelect = document.querySelector("#ask-folder-ids");
  if (!contentSelect || !tagSelect || !folderSelect) return;
  contentSelect.replaceChildren(...state.ask.contentOptions.map((item) => new Option(item.title, item.id)));
  tagSelect.replaceChildren(...state.ask.tags.map((item) => new Option(item.name, item.id)));
  folderSelect.replaceChildren(...state.ask.folders.filter((item) => item.id !== "all")
    .map((item) => new Option(item.name, item.id)));
}

function setAskScopeDisabled(disabled) {
  ["#ask-scope-kind", "#ask-material-scope", "#ask-content-ids", "#ask-tag-ids", "#ask-folder-ids"]
    .forEach((selector) => { const field = document.querySelector(selector); if (field) field.disabled = disabled; });
}

function updateAskScopeFields(scope = null) {
  const selected = document.querySelector("#ask-scope-kind");
  const material = document.querySelector("#ask-material-scope");
  const contentPicker = document.querySelector("#ask-content-picker");
  const scopeStatus = document.querySelector("#ask-scope-status");
  if (scope && selected && material) {
    selected.value = scope.kind || "all";
    material.value = scope.material_scope || "full";
    const choices = [
      ["#ask-content-ids", scope.content_ids || []],
      ["#ask-tag-ids", scope.tag_ids || []],
      ["#ask-folder-ids", scope.favorite_folder_ids || []],
    ];
    choices.forEach(([selector, values]) => {
      const selectedValues = new Set(values);
      [...(document.querySelector(selector)?.options || [])].forEach((option) => {
        option.selected = selectedValues.has(option.value);
      });
    });
  }
  const kind = selected?.value;
  const scopeBlock = document.querySelector("#ask-selected-scope");
  if (scopeBlock) scopeBlock.hidden = !kind || kind === "all";
  if (contentPicker) contentPicker.hidden = kind !== "selected";
  if (scopeStatus) {
    const count = scope?.count;
    scopeStatus.textContent = Number.isInteger(count) ? `${count} 项` : "";
  }
}

function renderAskSessions() {
  if (!askSessionList) return;
  askSessionList.replaceChildren();
  if (!state.ask.sessions.length) {
    const empty = document.createElement("p");
    empty.className = "ask-empty";
    empty.textContent = "暂无会话";
    askSessionList.append(empty);
    return;
  }
  state.ask.sessions.forEach((session) => {
    const row = document.createElement("div");
    row.className = "ask-session-row";
    const open = document.createElement("button");
    open.type = "button";
    open.className = "ask-session-button";
    open.textContent = session.title || "新会话";
    open.setAttribute("aria-current", String(session.id === state.ask.sessionId));
    open.addEventListener("click", () => loadAskSession(session.id));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "ask-session-delete";
    remove.textContent = "删除";
    remove.setAttribute("aria-label", `删除会话：${session.title || "新会话"}`);
    remove.addEventListener("click", async () => {
      if (!window.confirm("删除问答会话？")) return;
      try {
        await api(`/api/v1/ask/sessions/${encodeURIComponent(session.id)}`, { method: "DELETE" });
        if (state.ask.sessionId === session.id) newAskSession();
        await refreshAskSessions();
      } catch (error) { showNotice(error.message, true); }
    });
    row.append(open, remove);
    askSessionList.append(row);
  });
}

async function refreshAskSessions() {
  state.ask.sessions = await api("/api/v1/ask/sessions");
  renderAskSessions();
}

async function loadAskSettings() {
  const settings = await api("/api/v1/ask/settings");
  state.ask.settings = settings;
  const fieldValues = {
    "#ask-provider": settings.provider || "openai-compatible",
    "#ask-api-url": settings.api_url || "",
    "#ask-api-mode": settings.api_mode || "chat_completions",
    "#ask-model": settings.model || "",
  };
  Object.entries(fieldValues).forEach(([selector, value]) => {
    const field = document.querySelector(selector);
    if (field) field.value = value;
  });
  const key = document.querySelector("#ask-api-key");
  if (key) {
    key.value = "";
    key.placeholder = settings.api_key_configured ? "已保存 ·••••••••（输入新 Key 可替换）" : "API Key";
  }
  const reuse = document.querySelector("#ask-reuse-summary");
  if (reuse) reuse.checked = Boolean(settings.reuse_summary_config);
  const status = document.querySelector("#ask-model-status");
  if (status) status.textContent = settings.configured ? "已配置" : "未配置";
  const fieldsDisabled = Boolean(settings.reuse_summary_config);
  ["#ask-provider", "#ask-api-url", "#ask-api-mode", "#ask-model", "#ask-api-key"]
    .forEach((selector) => { const field = document.querySelector(selector); if (field) field.disabled = fieldsDisabled; });
  return settings;
}

async function loadAskHome() {
  try {
    const settings = await loadAskSettings();
    await refreshAskSessions();
    if (!state.ask.loaded) {
      const [historyCount, tags, folders] = await Promise.all([
        api("/api/v1/history/count"), api("/api/v1/tags"), api("/api/v1/favorite-folders"),
      ]);
      state.ask.tags = tags;
      state.ask.folders = folders;
      const total = Math.min(historyCount.total || 0, 5000);
      const entries = [];
      for (let offset = 0; offset < total; offset += 50) {
        const page = await api(`/api/v1/history?archived_only=true&limit=50&offset=${offset}`);
        entries.push(...page);
        if (page.length < 50) break;
      }
      state.ask.contentOptions = entries.map((entry) => ({ id: entry.content.id, title: entry.content.title }));
      state.ask.loaded = true;
    }
    renderAskScopeOptions();
    if (state.ask.sessionId) await loadAskSession(state.ask.sessionId);
    else {
      renderAskSessions();
      renderAskConversation(null);
      updateAskScopeFields();
      document.querySelector("#ask-query-status").textContent = settings.configured ? "" : "未配置回答模型";
    }
  } catch (error) { showNotice(error.message, true); }
}

async function loadAskSession(sessionId) {
  try {
    window.clearTimeout(state.ask.pollTimer);
    state.ask.session = await api(`/api/v1/ask/sessions/${encodeURIComponent(sessionId)}`);
    state.ask.sessionId = sessionId;
    const lastPending = [...(state.ask.session.messages || [])].reverse()
      .find((message) => ["queued", "running", "cancelling", "paused"].includes(message.status));
    state.ask.queryId = lastPending?.id || null;
    updateAskScopeFields(state.ask.session.scope);
    setAskScopeDisabled(true);
    renderAskSessions();
    renderAskConversation(state.ask.session);
    if (lastPending && lastPending.status !== "paused") pollAskQuery(lastPending.id);
  } catch (error) { showNotice(error.message, true); }
}

function renderAskConversation(session) {
  if (!askMessages) return;
  askMessages.replaceChildren();
  if (!session?.messages?.length) {
    const empty = document.createElement("p");
    empty.className = "ask-empty";
    empty.textContent = "开始提问";
    askMessages.append(empty);
  } else {
    session.messages.forEach((message) => {
      const card = document.createElement("article");
      card.className = "ask-message";
      const question = document.createElement("h3");
      question.textContent = message.question;
      card.append(question);
      const result = message.result;
      if (result?.answer) {
        if (result.status && result.status !== "answer") {
          const status = document.createElement("p");
          status.className = "ask-answer-status";
          status.textContent = ({ partial: "部分结果", insufficient: "证据不足", unknown: "状态未知", no_match: "未找到" })[result.status] || result.status;
          card.append(status);
        }
        if (result.coverage && result.coverage.exact === false) {
          const coverage = document.createElement("p");
          coverage.className = "ask-answer-status";
          coverage.textContent = "范围未完整覆盖";
          card.append(coverage);
        }
        const answer = document.createElement("p");
        answer.className = "ask-answer";
        answer.textContent = result.answer;
        card.append(answer);
      } else {
        const status = document.createElement("p");
        status.className = "ask-answer-status";
        status.textContent = ({ queued: "排队中", running: "处理中", cancelling: "正在取消", paused: "已暂停", cancelled: "已取消", failed: "失败" })[message.status]
          || (result?.status ? ({ clarify: "需要补充", insufficient: "证据不足", unavailable: "不可用" })[result.status] || result.status : "处理中");
        card.append(status);
      }
      (result?.citations || []).forEach((citation) => card.append(renderAskCitation(message.id, citation)));
      if (result?.citations?.length) {
        const feedback = document.createElement("div");
        feedback.className = "ask-feedback";
        [[true, "有帮助"], [false, "没帮助"]].forEach(([helpful, label]) => {
          const button = document.createElement("button");
          button.type = "button";
          button.className = "button button-small";
          button.textContent = label;
          button.addEventListener("click", async () => {
            try {
              await api("/api/v1/ask/feedback", { method: "POST", body: JSON.stringify({
                query_id: message.id, content_id: result.citations[0].content_id, helpful, detail_tag_ids: [],
              }) });
              feedback.textContent = "已记录";
            } catch (error) { showNotice(error.message, true); }
          });
          feedback.append(button);
        });
        card.append(feedback);
      }
      askMessages.append(card);
    });
  }
  const active = [...(session?.messages || [])].reverse()
    .find((message) => ["queued", "running", "cancelling", "paused"].includes(message.status));
  state.ask.queryId = active?.id || null;
  document.querySelector("#ask-cancel-query").hidden = !active || !["queued", "running", "cancelling"].includes(active.status);
  document.querySelector("#ask-continue-query").hidden = !active || active.status !== "paused";
  document.querySelector("#ask-submit-query").disabled = Boolean(active && active.status !== "paused");
  if (askQueryStatus) askQueryStatus.textContent = active
    ? ({ queued: "排队中", running: "处理中", cancelling: "正在取消", paused: "已暂停" })[active.status] || ""
    : "";
}

function renderAskCitation(queryId, citation) {
  const item = document.createElement("div");
  item.className = "ask-citation";
  const heading = document.createElement("strong");
  const kind = citation.source_kind === "summary" ? "总结" : "原文";
  const seconds = Number(citation.start_seconds);
  const time = Number.isFinite(seconds) ? ` · ${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}` : "";
  heading.textContent = `${citation.title} · ${kind}${time}`;
  const quote = document.createElement("p");
  quote.textContent = citation.text;
  const open = document.createElement("button");
  open.type = "button";
  open.className = "button button-small";
  open.textContent = "打开资料";
  open.addEventListener("click", async () => {
    state.returnContext = { sourceView: "ask", anchorContentId: citation.content_id };
    state.resultSequence = [citation.content_id];
    await loadResult(citation.content_id);
  });
  item.append(heading, quote, open);
  return item;
}

function currentAskScope() {
  const kind = document.querySelector("#ask-scope-kind").value;
  const contentIds = askSelectedValues("#ask-content-ids");
  if (kind === "selected" && !contentIds.length) throw new Error("请选择问答内容");
  return {
    kind,
    material_scope: document.querySelector("#ask-material-scope").value,
    content_ids: kind === "selected" ? contentIds : [],
    tag_ids: askSelectedValues("#ask-tag-ids"),
    favorite_folder_ids: askSelectedValues("#ask-folder-ids"),
  };
}

function newAskSession() {
  window.clearTimeout(state.ask.pollTimer);
  state.ask.sessionId = null;
  state.ask.session = null;
  state.ask.queryId = null;
  setAskScopeDisabled(false);
  ["#ask-scope-kind", "#ask-material-scope"].forEach((selector) => { document.querySelector(selector).value = selector.endsWith("kind") ? "all" : "full"; });
  ["#ask-content-ids", "#ask-tag-ids", "#ask-folder-ids"].forEach((selector) => {
    [...document.querySelector(selector).options].forEach((option) => { option.selected = false; });
  });
  document.querySelector("#ask-question").value = "";
  renderAskSessions();
  renderAskConversation(null);
  updateAskScopeFields();
}

async function submitAskQuestion(event) {
  event.preventDefault();
  const question = document.querySelector("#ask-question").value.trim();
  if (!question) return;
  try {
    if (!state.ask.settings?.configured) {
      showView("settings");
      showSettingsSection("ask-model");
      showNotice("请先配置回答模型");
      return;
    }
    let sessionId = state.ask.sessionId;
    if (!sessionId) {
      const session = await api("/api/v1/ask/sessions", {
        method: "POST", body: JSON.stringify({ scope: currentAskScope() }),
      });
      sessionId = session.id;
      state.ask.sessionId = sessionId;
      state.ask.session = session;
      setAskScopeDisabled(true);
      updateAskScopeFields(session.scope);
    }
    const accepted = await api("/api/v1/ask/queries", {
      method: "POST", body: JSON.stringify({ session_id: sessionId, question }),
    });
    state.ask.queryId = accepted.query_id;
    document.querySelector("#ask-question").value = "";
    syncAskSubmitState();
    await refreshAskSessions();
    await loadAskSession(sessionId);
    pollAskQuery(accepted.query_id);
  } catch (error) { showNotice(error.message, true); }
}

async function pollAskQuery(queryId) {
  window.clearTimeout(state.ask.pollTimer);
  try {
    const query = await api(`/api/v1/ask/queries/${encodeURIComponent(queryId)}`);
    if (["completed", "paused", "cancelled", "failed"].includes(query.status)) {
      state.ask.queryId = query.status === "paused" ? queryId : null;
      if (state.ask.sessionId) await loadAskSession(state.ask.sessionId);
      await refreshAskSessions();
      return;
    }
    if (askQueryStatus) askQueryStatus.textContent = query.status === "queued" ? "排队中" : "处理中";
    state.ask.pollTimer = window.setTimeout(() => pollAskQuery(queryId), 700);
  } catch (error) {
    if (askQueryStatus) askQueryStatus.textContent = error.message;
    state.ask.pollTimer = window.setTimeout(() => pollAskQuery(queryId), 1500);
  }
}

async function cancelAskQuery() {
  if (!state.ask.queryId) return;
  try {
    await api(`/api/v1/ask/queries/${encodeURIComponent(state.ask.queryId)}/cancel`, { method: "POST" });
    pollAskQuery(state.ask.queryId);
  } catch (error) { showNotice(error.message, true); }
}

async function continueAskQuery() {
  if (!state.ask.queryId) return;
  try {
    const result = await api(`/api/v1/ask/queries/${encodeURIComponent(state.ask.queryId)}/continue`, { method: "POST" });
    pollAskQuery(result.query_id);
  } catch (error) { showNotice(error.message, true); }
}

document.querySelector("#ask-open-settings")?.addEventListener("click", () => {
  showView("settings");
  showSettingsSection("ask-model");
});
document.querySelector("#ask-new-session")?.addEventListener("click", newAskSession);
document.querySelector("#ask-question-form")?.addEventListener("submit", submitAskQuestion);
document.querySelector("#ask-cancel-query")?.addEventListener("click", cancelAskQuery);
document.querySelector("#ask-continue-query")?.addEventListener("click", continueAskQuery);
document.querySelector("#ask-scope-kind")?.addEventListener("change", () => updateAskScopeFields());

const askQuestionInput = document.querySelector("#ask-question");
const askSubmitButton = document.querySelector("#ask-submit-query");

function syncAskSubmitState() {
  if (!askQuestionInput || !askSubmitButton) return;
  askSubmitButton.disabled = !askQuestionInput.value.trim();
}

askQuestionInput?.addEventListener("input", syncAskSubmitState);
syncAskSubmitState();

// 开发期刷新：地址带 ?dev=1 才显示按钮。点一次强制丢弃 style.css / app.js 的
// 缓存再整页重载，改完前端不用关窗口重开。
function isDevMode() {
  return new URLSearchParams(window.location.search).get("dev") === "1";
}

async function reloadLatestApp() {
  const button = document.querySelector("#reload-app");
  if (button) {
    button.disabled = true;
    button.textContent = "刷新中";
  }
  const urls = [
    document.querySelector("#ui-style")?.href,
    document.querySelector('script[src*="app.js"]')?.src,
  ].filter(Boolean);
  await Promise.all(urls.map((url) => fetch(url, { cache: "reload" }).catch(() => null)));
  window.location.reload();
}

const reloadAppButton = document.querySelector("#reload-app");
if (reloadAppButton && isDevMode()) {
  reloadAppButton.hidden = false;
  reloadAppButton.addEventListener("click", reloadLatestApp);
}
document.querySelector("#ask-model-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const reuse = document.querySelector("#ask-reuse-summary").checked;
  const body = reuse ? { reuse_summary_config: true } : {
    provider: document.querySelector("#ask-provider").value.trim(),
    api_url: document.querySelector("#ask-api-url").value.trim(),
    api_mode: document.querySelector("#ask-api-mode").value,
    model: document.querySelector("#ask-model").value.trim(),
    api_key: document.querySelector("#ask-api-key").value.trim() || null,
  };
  try {
    await api("/api/v1/ask/settings", { method: "PUT", body: JSON.stringify(body) });
    await loadAskSettings();
    showNotice("回答模型配置已保存");
  } catch (error) { showNotice(error.message, true); }
});
document.querySelector("#ask-model-test")?.addEventListener("click", async () => {
  const reuse = document.querySelector("#ask-reuse-summary").checked;
  const body = reuse ? { reuse_summary_config: true } : {
    provider: document.querySelector("#ask-provider").value.trim(),
    api_url: document.querySelector("#ask-api-url").value.trim(),
    api_mode: document.querySelector("#ask-api-mode").value,
    model: document.querySelector("#ask-model").value.trim(),
    api_key: document.querySelector("#ask-api-key").value.trim() || null,
  };
  const status = document.querySelector("#ask-model-status");
  try {
    const result = await api("/api/v1/ask/settings/check", { method: "POST", body: JSON.stringify(body) });
    status.textContent = result.message || "连接成功";
  } catch (error) { status.textContent = error.message; }
});
document.querySelector("#ask-reuse-summary")?.addEventListener("change", (event) => {
  ["#ask-provider", "#ask-api-url", "#ask-api-mode", "#ask-model", "#ask-api-key"]
    .forEach((selector) => { document.querySelector(selector).disabled = event.target.checked; });
});

intakeModeButtons.forEach((button) => button.addEventListener("click", () => {
  showIntakeMode(button.dataset.intakeMode);
}));
intakeModeTabs?.addEventListener("keydown", (event) => {
  if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
  event.preventDefault();
  const currentIndex = intakeModeButtons.findIndex(
    (button) => button.dataset.intakeMode === state.intakeMode,
  );
  const step = ["ArrowRight", "ArrowDown"].includes(event.key) ? 1 : -1;
  const nextIndex = (currentIndex + step + intakeModeButtons.length) % intakeModeButtons.length;
  const nextButton = intakeModeButtons[nextIndex];
  if (!nextButton) return;
  showIntakeMode(nextButton.dataset.intakeMode);
  nextButton.focus();
});
settingsSubnavButtons.forEach((button) => button.addEventListener("click", () => {
  showSettingsSection(button.dataset.settingsTarget);
}));
showIntakeMode("link");
showSettingsSection("platform");
sourceUrlInput.addEventListener("input", () => {
  updateLinkHint();
  updateInputPanelSummary();
});
document.querySelector("#source-text").addEventListener("input", updateInputPanelSummary);
document.querySelector("#source-path").addEventListener("input", updateInputPanelSummary);
function handleLocalFile(file) {
  if (!file) return;
  const extension = file.name.toLowerCase().split(".").pop();
  const textExtensions = new Set(["txt", "md", "markdown", "srt", "vtt"]);
  if (!textExtensions.has(extension)) {
    showNotice("当前文件选择器支持 TXT、MD、SRT、VTT；音视频请填写本地路径", true);
    return;
  }
  state.localFileName = file.name;
  const fileName = document.querySelector("#local-file-name");
  if (fileName) fileName.textContent = `已选择：${file.name}`;
  const sourcePath = document.querySelector("#source-path");
  if (sourcePath) sourcePath.value = "";
  const reader = new FileReader();
  reader.addEventListener("load", () => {
    document.querySelector("#source-text").value = String(reader.result || "");
    updateInputPanelSummary();
  });
  reader.readAsText(file);
}

/* -------------------------------------------------------------------------
 * Knowledge-library refactor
 *
 * The legacy controls above remain available to the intake flow.  The
 * library-specific rendering below keeps the new product rules in one small
 * surface: tags filter the library, folders only collect content, and the
 * bookshelf is driven by completed history entries.
 * ------------------------------------------------------------------------- */

const tagNavigation = document.querySelector("#tag-navigation");
const tagNavList = document.querySelector("#tag-nav-list");
const allTagsButton = document.querySelector("#all-tags-button");
const createTagButton = document.querySelector("#create-tag-button");
const tagScrollLeft = document.querySelector("#tag-scroll-left");
const tagScrollRight = document.querySelector("#tag-scroll-right");

function activeHistoryFilters() {
  const query = document.querySelector("#history-query")?.value.trim() || "";
  const platform = document.querySelector("#history-platform")?.value || "";
  const author = document.querySelector("#history-author")?.value.trim() || "";
  const sortValue = document.querySelector("#history-sort")?.value || "created_at:desc";
  const [sortMode, order] = sortValue.split(":");
  return {
    query,
    platform,
    author,
    sortMode: `${sortMode || "created_at"}:${order || "desc"}`,
  };
}

function captureReturnContext(anchorContentId = state.activeContentId) {
  if (state.currentView !== "history") return;
  const filters = activeHistoryFilters();
  const anchorIndex = state.libraryEntries.findIndex((entry) => entry.content?.id === anchorContentId);
  const absoluteIndex = state.libraryPageStart + Math.max(0, anchorIndex);
  state.returnContext = {
    sourceView: "history",
    selectedTagIds: state.activeTagId ? [state.activeTagId] : [],
    selectedFolderId: state.activeFavoriteFolderId || "",
    searchQuery: filters.query,
    sortMode: filters.sortMode,
    platform: filters.platform,
    author: filters.author,
    anchorContentId: anchorContentId || null,
    libraryOffset: Math.floor(absoluteIndex / state.libraryPageSize) * state.libraryPageSize,
    scrollOffset: window.scrollY || 0,
  };
}

function restoreReturnContext() {
  const context = state.returnContext;
  if (!context || context.sourceView !== "history") return;
  state.activeTagId = context.selectedTagIds?.[0] || "";
  state.activeFavoriteFolderId = context.selectedFolderId || "";
  const query = document.querySelector("#history-query");
  const platform = document.querySelector("#history-platform");
  const author = document.querySelector("#history-author");
  const sort = document.querySelector("#history-sort");
  if (query) query.value = context.searchQuery || "";
  if (platform) platform.value = context.platform || "";
  if (author) author.value = context.author || "";
  if (sort) sort.value = context.sortMode || "created_at:desc";
}

function invalidateReturnContext() {
  state.returnContext = null;
}

function updateReturnControls() {
  const hasResultParent = Boolean(state.returnContext?.sourceView);
  const label = hasResultParent
    ? state.returnContext.sourceView === "batch-detail"
      ? "返回批次"
      : state.returnContext.sourceView === "tasks" ? "返回任务"
        : state.returnContext.sourceView === "ask" ? "返回问答" : "返回知识库"
    : "返回知识库";
  const headerBack = document.querySelector("#result-header-back");
  if (headerBack) {
    headerBack.hidden = state.currentView !== "result";
    headerBack.setAttribute("aria-label", label);
    headerBack.title = label;
  }
  [document.querySelector("#back-to-history"), document.querySelector("#result-footer-back")]
    .filter(Boolean)
    .forEach((button) => {
      button.hidden = state.currentView !== "result";
      button.textContent = label;
    });
  const batchBack = document.querySelector("#batch-detail-back");
  if (batchBack) batchBack.hidden = !state.batchReturnContext?.sourceView;
  if (settingsReturnButton) {
    settingsReturnButton.hidden = !state.settingsReturnView;
    const labels = { intake: "内容接入", tasks: "任务", history: "知识库", ask: "AI 问答", result: "结果" };
    if (state.settingsReturnView) {
      settingsReturnButton.textContent = `返回${labels[state.settingsReturnView] || "上一页"}`;
    }
  }
}

function updateLibraryCountPill() {
  const pill = document.querySelector("#library-count-pill");
  if (!pill) return;
  const tag = (state.tags || []).find((item) => item.id === state.activeTagId);
  const folder = (state.favoriteFolders || []).find((item) => item.id === state.activeFavoriteFolderId);
  const label = tag ? tag.name : (folder ? folder.name : "总库");
  const count = tag ? Number(tag.content_count || 0) : Number(state.libraryTotal ?? 0);
  pill.textContent = `${label} · ${count} 条`;
  pill.dataset.scope = tag ? "tag" : (folder ? "folder" : "all");
}

function renderTagNavigation() {
  if (!tagNavigation || !tagNavList) return;
  tagNavList.replaceChildren();
  allTagsButton?.classList.toggle("is-active", !state.activeTagId);
  if (allTagsButton) allTagsButton.textContent = `总库 ${state.libraryTotal ?? 0}`;
  updateLibraryCountPill();
  const manage = document.querySelector("#manage-tags-button");
  if (manage) {
    manage.textContent = state.tagManagementMode ? "完成" : "管理";
    manage.setAttribute("aria-pressed", String(state.tagManagementMode));
  }
  (state.tags || []).forEach((tag) => {
    const item = document.createElement("span");
    item.className = "tag-nav-item";
    if (state.tagManagementMode && state.tagRenamingId === tag.id) {
      const input = document.createElement("input");
      input.type = "text";
      input.className = "tag-nav-rename-input";
      input.value = tag.name;
      input.setAttribute("aria-label", `重命名标签 ${tag.name}`);
      let saving = false;
      const save = async () => {
        if (saving) return;
        const name = input.value.trim();
        if (!name) {
          showNotice("标签名称不能为空", true);
          input.focus();
          return;
        }
        if (name === tag.name) {
          state.tagRenamingId = null;
          renderTagNavigation();
          return;
        }
        saving = true;
        try {
          const updated = await api(`/api/v1/tags/${encodeURIComponent(tag.id)}`, {
            method: "PATCH",
            body: JSON.stringify({ name }),
          });
          state.tags = state.tags.map((item) => item.id === tag.id ? updated : item);
          state.tagRenamingId = null;
          renderTagNavigation();
          showNotice(`标签已改为“${updated.name}”`);
        } catch (error) {
          saving = false;
          showNotice(error.message, true);
          input.focus();
        }
      };
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          save();
        } else if (event.key === "Escape") {
          event.preventDefault();
          state.tagRenamingId = null;
          renderTagNavigation();
        }
      });
      input.addEventListener("blur", save);
      item.append(input);
      window.requestAnimationFrame(() => { input.focus(); input.select(); });
    } else {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "tag-nav-button";
      button.textContent = `${tag.name} (${tag.content_count || 0})`;
      button.dataset.tagId = tag.id;
      button.classList.toggle("is-active", state.activeTagId === tag.id);
      button.setAttribute("role", "listitem");
      button.addEventListener("click", () => {
        state.activeTagId = tag.id;
        state.activeTagName = tag.name;
        state.activeFavoriteFolderId = "";
        state.showingTrash = false;
        invalidateReturnContext();
        renderTagNavigation();
        loadHistory();
      });
      item.append(button);
      if (state.tagManagementMode) {
        const edit = document.createElement("button");
        edit.type = "button";
        edit.className = "tag-nav-edit";
        edit.textContent = "✎";
        edit.title = `重命名标签 ${tag.name}`;
        edit.setAttribute("aria-label", `重命名标签 ${tag.name}`);
        edit.addEventListener("click", (event) => {
          event.stopPropagation();
          state.tagRenamingId = tag.id;
          renderTagNavigation();
        });
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "tag-nav-remove";
        remove.replaceChildren(createIcon("close"));
        remove.title = `删除标签 ${tag.name}`;
        remove.setAttribute("aria-label", `删除标签 ${tag.name}`);
        remove.addEventListener("click", (event) => {
          event.stopPropagation();
          deleteTag(tag);
        });
        item.append(edit, remove);
      }
    }
    tagNavList.append(item);
  });
  updateTagScrollButtons();
}

function updateTagScrollButtons() {
  if (!tagNavigation || !tagNavList) return;
  const overflowing = tagNavList.scrollWidth > tagNavList.clientWidth + 2;
  tagNavigation.classList.toggle("is-overflowing", overflowing);
  if (tagScrollLeft) tagScrollLeft.hidden = !overflowing || tagNavList.scrollLeft <= 1;
  if (tagScrollRight) tagScrollRight.hidden = !overflowing || tagNavList.scrollLeft + tagNavList.clientWidth >= tagNavList.scrollWidth - 1;
}

async function loadTags() {
  state.tags = await api("/api/v1/tags");
  const current = state.tags.find((tag) => tag.id === state.activeTagId);
  if (!current) {
    state.activeTagId = "";
    state.activeTagName = "";
  } else {
    state.activeTagName = current.name;
  }
  renderTagNavigation();
}

async function createTag({ selectInLibrary = true, onCreated = null } = {}) {
  const name = await openProductTextDialog({
    title: "新建标签",
    label: "标签名称",
    placeholder: "例如：教程、会议、科创",
    confirmLabel: "创建标签",
  });
  if (!name) return null;
  try {
    const tag = await api("/api/v1/tags", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    state.tags = [tag, ...state.tags.filter((item) => item.id !== tag.id)];
    if (selectInLibrary) {
      state.activeTagId = tag.id;
      state.activeTagName = tag.name;
      invalidateReturnContext();
    }
    renderTagNavigation();
    if (selectInLibrary) await loadHistory();
    if (onCreated) await onCreated(tag);
    showNotice(`已创建标签“${tag.name}”`);
    return tag;
  } catch (error) {
    showNotice(error.message, true);
    return null;
  }
}

async function renameTag(tag) {
  state.tagManagementMode = true;
  state.tagRenamingId = tag.id;
  renderTagNavigation();
}

async function exportHistorySelection(contentIds) {
  assertApiContractCompatible();
  const response = await fetch(`${API_ORIGIN}/api/v1/contents/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids: [...new Set(contentIds || [])], format: currentExportFormat() }),
  });
  if (!response.ok) throw new Error("批量导出失败");
  return response.blob();
}

async function deleteTag(tag) {
  if (!window.confirm(`删除标签“${tag.name}”？视频内容不会被删除。`)) return;
  try {
    await api(`/api/v1/tags/${encodeURIComponent(tag.id)}`, { method: "DELETE" });
    state.tags = state.tags.filter((item) => item.id !== tag.id);
    if (state.activeTagId === tag.id) state.activeTagId = "";
    invalidateReturnContext();
    renderTagNavigation();
    await loadHistory();
    showNotice(`已删除标签“${tag.name}”`);
  } catch (error) {
    showNotice(error.message, true);
  }
}

function renderFavoriteFolderChip(folder) {
  const chip = document.createElement("div");
  chip.className = "favorite-folder-chip";
  chip.setAttribute("role", "listitem");
  if (state.favoriteManagementMode && state.favoriteRenamingId === folder.id) {
    const input = document.createElement("input");
    input.type = "text";
    input.className = "favorite-folder-rename-input";
    input.value = folder.name;
    input.setAttribute("aria-label", `重命名收藏夹 ${folder.name}`);
    let saving = false;
    const save = async () => {
      if (saving) return;
      const name = input.value.trim();
      if (!name) {
        showNotice("收藏夹名称不能为空", true);
        input.focus();
        return;
      }
      if (name === folder.name) {
        state.favoriteRenamingId = null;
        renderFavoriteFolders();
        return;
      }
      saving = true;
      try {
        const updated = await api(`/api/v1/favorite-folders/${encodeURIComponent(folder.id)}`, {
          method: "PATCH",
          body: JSON.stringify({ name, parent_id: folder.parent_id || null }),
        });
        state.favoriteFolders = state.favoriteFolders.map((item) => item.id === folder.id ? updated : item);
        state.favoriteRenamingId = null;
        renderFavoriteFolders();
        showNotice("收藏夹已重命名");
      } catch (error) {
        saving = false;
        showNotice(error.message, true);
        input.focus();
      }
    };
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        save();
      } else if (event.key === "Escape") {
        event.preventDefault();
        state.favoriteRenamingId = null;
        renderFavoriteFolders();
      }
    });
    input.addEventListener("blur", save);
    chip.append(input);
    window.requestAnimationFrame(() => { input.focus(); input.select(); });
    return chip;
  }
  const button = document.createElement("button");
  button.type = "button";
  button.className = "favorite-folder-button";
  button.classList.toggle("is-active", folder.id === state.activeFavoriteFolderId);
  button.setAttribute("aria-pressed", String(folder.id === state.activeFavoriteFolderId));
  button.disabled = state.showingTrash;
  const label = document.createElement("span");
  label.textContent = folder.name;
  const count = document.createElement("span");
  count.className = "favorite-folder-count";
  count.textContent = String(folder.content_count || 0);
  button.append(label, count);
  button.addEventListener("click", () => {
    state.activeFavoriteFolderId = folder.id;
    state.showingTrash = false;
    invalidateReturnContext();
    renderFavoriteFolders();
    loadHistory();
  });
  chip.append(button);
  if (state.favoriteManagementMode) {
    const menu = document.createElement("details");
    menu.className = "favorite-folder-menu";
    const summary = document.createElement("summary");
    summary.textContent = "⋯";
    summary.title = `管理收藏夹 ${folder.name}`;
    summary.setAttribute("aria-label", `管理收藏夹 ${folder.name}`);
    const panel = document.createElement("div");
    panel.className = "favorite-folder-menu-panel";
    const rename = document.createElement("button");
    rename.type = "button";
    rename.textContent = "重命名";
    rename.addEventListener("click", () => {
      menu.open = false;
      state.favoriteRenamingId = folder.id;
      renderFavoriteFolders();
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "删除";
    remove.className = "is-danger";
    remove.addEventListener("click", () => {
      menu.open = false;
      deleteFavoriteFolder(folder);
    });
    panel.append(rename, remove);
    menu.append(summary, panel);
    chip.append(menu);
  }
  return chip;
}

function favoriteAddTargetFolder() {
  return state.favoriteFolders.find((folder) => folder.id === state.favoriteAddContext?.folderId);
}

function favoriteAddAssociationFailuresForFolder(folderId) {
  return (state.favoriteAddAssociationFailures || []).filter((failure) =>
    (failure.folder_ids || []).includes(folderId),
  );
}

function favoriteAddFailedLinksForFolder(folderId) {
  return (state.favoriteAddFailedLinks || []).find((entry) => entry.folderId === folderId)?.urls || [];
}

function setFavoriteAddFailedLinks(folderId, urls) {
  const normalized = [...new Set((urls || []).map((url) => String(url || "").trim()).filter(Boolean))];
  state.favoriteAddFailedLinks = [
    ...(state.favoriteAddFailedLinks || []).filter((entry) => entry.folderId !== folderId),
    ...(normalized.length ? [{ folderId, urls: normalized }] : []),
  ];
}

function closeFavoriteAddDialog() {
  state.favoriteAddContext = null;
  state.favoriteAddChoices = [];
  state.favoriteAddSelectedIds = new Set();
  if (state.linkQuery?.favorite_add) {
    state.linkQuery = null;
    state.linkQuerySelectedIds = new Set();
  }
  setLinkQueryDialogOpen(false);
}

async function addExistingContentToFavorite(button) {
  const targetFolder = favoriteAddTargetFolder();
  const selectedIds = [...state.favoriteAddSelectedIds];
  if (!targetFolder || !selectedIds.length) return;
  button.disabled = true;
  const failedIds = new Set();
  for (const contentId of selectedIds) {
    const entry = state.favoriteAddChoices.find((item) => item.content?.id === contentId);
    if (!entry) continue;
    const folderIds = [...new Set([...(entry.content.favorite_folder_ids || []), targetFolder.id])];
    try {
      const content = await api(`/api/v1/contents/${encodeURIComponent(contentId)}`, {
        method: "PATCH",
        body: JSON.stringify({ favorite_folder_ids: folderIds }),
      });
      entry.content = content;
    } catch (error) {
      failedIds.add(contentId);
    }
  }
  if (failedIds.size) {
    state.favoriteAddSelectedIds = failedIds;
    renderFavoriteContentAddDialog({ mode: "existing" });
    showNotice(`${failedIds.size} 条内容加入失败，可保留选择后重试`, true);
    return;
  }
  state.activeFavoriteFolderId = targetFolder.id;
  state.showingTrash = false;
  closeFavoriteAddDialog();
  await loadHistory();
  showNotice(`已将 ${selectedIds.length} 条内容加入“${targetFolder.name}”`);
}

async function retryFavoriteAssociations(button) {
  const targetFolder = favoriteAddTargetFolder();
  const failures = favoriteAddAssociationFailuresForFolder(targetFolder?.id);
  if (!targetFolder || !failures.length) return;
  button.disabled = true;
  const remaining = [];
  for (const failure of failures) {
    const content = failure.content || {};
    try {
      const latestContent = await api(
        `/api/v1/contents/${encodeURIComponent(content.id)}`,
      );
      const folderIds = [...new Set([
        ...(latestContent.favorite_folder_ids || []),
        ...(failure.folder_ids || []),
        targetFolder.id,
      ])];
      await api(`/api/v1/contents/${encodeURIComponent(content.id)}`, {
        method: "PATCH",
        body: JSON.stringify({ favorite_folder_ids: folderIds }),
      });
    } catch (_error) {
      remaining.push(failure);
    }
  }
  state.favoriteAddAssociationFailures = [
    ...(state.favoriteAddAssociationFailures || []).filter(
      (failure) => !failures.includes(failure),
    ),
    ...remaining,
  ];
  if (remaining.length) {
    renderFavoriteContentAddDialog({ mode: "association-retry" });
    showNotice(`${remaining.length} 条收藏夹关联仍失败，可继续重试`, true);
    button.disabled = false;
    return;
  }
  const failedUrls = state.favoriteAddContext?.failedUrls
    || favoriteAddFailedLinksForFolder(targetFolder.id);
  if (state.favoriteAddContext) {
    state.favoriteAddContext.failedUrls = failedUrls;
    state.favoriteAddContext.mode = state.favoriteAddBatch
      ? failedUrls.length ? "link-retry" : "progress"
      : failedUrls.length ? "link-retry" : "existing";
  }
  if (state.favoriteAddBatch) {
    renderFavoriteContentAddDialog({ mode: "progress" });
  } else {
    closeFavoriteAddDialog();
    await loadHistory();
  }
  showNotice(`已将 ${failures.length} 条任务结果归入“${targetFolder.name}”`);
  button.disabled = false;
}

async function retryFavoriteAddLinks(button) {
  const targetFolder = favoriteAddTargetFolder();
  const failedUrls = state.favoriteAddContext?.failedUrls
    || favoriteAddFailedLinksForFolder(targetFolder?.id);
  if (!targetFolder || !failedUrls.length) return;
  button.disabled = true;
  try {
    await queryLinks(failedUrls, { preserveInput: true });
  } finally {
    button.disabled = false;
  }
}

async function queryFavoriteAddLink(button, input) {
  const value = input.value.trim();
  if (!value) {
    showNotice("请先粘贴视频链接", true);
    return;
  }
  if (!state.favoriteAddContext) return;
  state.favoriteAddContext.linkValue = value;
  button.disabled = true;
  try {
    await queryLinks([value], { preserveInput: true });
  } finally {
    button.disabled = false;
  }
}

function renderFavoriteContentAddDialog({ mode = "existing" } = {}) {
  const targetFolder = favoriteAddTargetFolder();
  if (!linkQueryDialog || !targetFolder || !state.favoriteAddContext) return;
  state.favoriteAddContext.mode = mode;
  linkQueryDialog.classList.remove("creator-scan-dialog");
  linkQueryDialog.replaceChildren();
  const shell = document.createElement("div");
  shell.className = "link-query-shell favorite-add-shell";
  const header = document.createElement("header");
  header.className = "link-query-header";
  const title = document.createElement("h2");
  title.id = "link-query-title";
  title.textContent = `添加视频到“${targetFolder.name}”`;
  const close = document.createElement("button");
  close.type = "button";
  close.className = "creator-scan-close";
  close.textContent = "关闭";
  close.addEventListener("click", closeFavoriteAddDialog);
  header.append(title, close);
  shell.append(header);

  const recoveryMode = ["progress", "association-retry", "link-retry"].includes(mode);
  if (!recoveryMode) {
    const tabs = document.createElement("div");
    tabs.className = "favorite-add-tabs";
    [["existing", "从知识库选择"], ["link", "粘贴视频链接"]].forEach(([value, label]) => {
      const tab = document.createElement("button");
      tab.type = "button";
      tab.className = "button button-small favorite-add-tab";
      tab.classList.toggle("is-active", value === mode);
      tab.textContent = label;
      tab.addEventListener("click", () => renderFavoriteContentAddDialog({ mode: value }));
      tabs.append(tab);
    });
    shell.append(tabs);
  }

  if (recoveryMode) {
    const jobs = state.favoriteAddContext.batchJobs || [];
    const completed = jobs.filter((job) => job.state === "completed").length;
    const failed = jobs.filter((job) => ["failed", "cancelled"].includes(job.state)).length;
    const active = Math.max(0, jobs.length - completed - failed);
    const summary = document.createElement("p");
    summary.className = "link-query-summary";
    summary.textContent = state.favoriteAddContext.batchCompleted
      ? `任务处理完成：成功 ${completed} 条${failed ? `，失败 ${failed} 条` : ""}`
      : jobs.length
        ? `正在处理：已完成 ${completed}/${jobs.length}${active ? `，进行中 ${active} 条` : ""}`
        : "正在恢复添加批次进度…";
    shell.append(summary);
    const associationFailures = favoriteAddAssociationFailuresForFolder(targetFolder.id);
    if (associationFailures.length) {
      const error = document.createElement("div");
      error.className = "creator-scan-error";
      error.textContent = `${associationFailures.length} 条任务已创建，但尚未归入当前收藏夹。`;
      shell.append(error);
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "button button-primary";
      retry.textContent = "仅重试收藏夹关联";
      retry.addEventListener("click", () => retryFavoriteAssociations(retry));
      shell.append(retry);
      associationFailures.forEach((failure) => {
        const item = document.createElement("p");
        item.className = "field-hint";
        item.textContent = `${failure.content?.title || failure.job?.content_title || "任务"}：${failure.reason}`;
        shell.append(item);
      });
    }
    const failedUrls = state.favoriteAddContext.failedUrls
      || favoriteAddFailedLinksForFolder(targetFolder.id);
    if (failedUrls.length) {
      const error = document.createElement("div");
      error.className = "creator-scan-error";
      error.textContent = `${failedUrls.length} 条链接未创建任务，可在当前收藏夹中重试。`;
      shell.append(error);
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "button button-primary";
      retry.textContent = "重新查询失败项";
      retry.addEventListener("click", () => retryFavoriteAddLinks(retry));
      shell.append(retry);
      failedUrls.forEach((url) => {
        const item = document.createElement("p");
        item.className = "field-hint";
        item.textContent = url;
        shell.append(item);
      });
    }
    const close = document.createElement("button");
    close.type = "button";
    close.className = "button";
    close.textContent = "关闭";
    close.addEventListener("click", closeFavoriteAddDialog);
    shell.append(close);
  } else if (mode === "link") {
    const toolbar = document.createElement("div");
    toolbar.className = "favorite-add-toolbar";
    const input = document.createElement("input");
    input.type = "url";
    input.placeholder = "粘贴一个视频链接";
    input.value = state.favoriteAddContext.linkValue || "";
    input.setAttribute("aria-label", "要加入收藏夹的视频链接");
    const query = document.createElement("button");
    query.type = "button";
    query.className = "button button-primary";
    query.textContent = "查询";
    query.addEventListener("click", () => queryFavoriteAddLink(query, input));
    toolbar.append(input, query);
    shell.append(toolbar);
    const hint = document.createElement("p");
    hint.className = "link-query-summary";
    hint.textContent = "查询和确认仍在当前面板完成；任务提交后会保留当前收藏夹目标。";
    shell.append(hint);
  } else if (!state.favoriteAddChoices.length && state.favoriteAddContext.loading) {
    const loading = document.createElement("p");
    loading.className = "link-query-summary is-loading";
    loading.textContent = "正在读取可加入的知识内容…";
    shell.append(loading);
  } else {
    const toolbar = document.createElement("div");
    toolbar.className = "favorite-add-toolbar";
    const search = document.createElement("input");
    search.type = "search";
    search.placeholder = "搜索标题、作者或来源";
    search.value = state.favoriteAddContext.search || "";
    search.setAttribute("aria-label", "搜索要加入收藏夹的内容");
    search.addEventListener("input", (event) => {
      state.favoriteAddContext.search = event.target.value;
      renderFavoriteContentAddDialog({ mode: "existing" });
    });
    toolbar.append(search);
    shell.append(toolbar);
    const query = state.favoriteAddContext.search.trim().toLowerCase();
    const entries = state.favoriteAddChoices.filter((entry) => {
      const content = entry.content || {};
      return !query || [content.title, content.author, content.canonical_url]
        .filter(Boolean).join(" ").toLowerCase().includes(query);
    });
    const list = document.createElement("div");
    list.className = "favorite-add-list";
    entries.forEach((entry) => {
      const content = entry.content || {};
      const row = document.createElement("label");
      row.className = "favorite-add-item";
      const alreadyAdded = (content.favorite_folder_ids || []).includes(targetFolder.id);
      const select = document.createElement("input");
      select.type = "checkbox";
      select.checked = alreadyAdded || state.favoriteAddSelectedIds.has(content.id);
      select.disabled = alreadyAdded;
      select.addEventListener("change", () => {
        if (select.checked) state.favoriteAddSelectedIds.add(content.id);
        else state.favoriteAddSelectedIds.delete(content.id);
        row.classList.toggle("is-selected", select.checked);
        const submit = linkQueryDialog.querySelector("#add-existing-favorite-content");
        if (submit) submit.disabled = state.favoriteAddSelectedIds.size === 0;
      });
      const cover = createSourceCover({
        title: content.title,
        thumbnail: entry.job?.thumbnail_url || content.thumbnail_url,
        platform: content.platform,
        className: "source-cover favorite-add-item-cover",
      });
      const copy = document.createElement("span");
      copy.className = "favorite-add-item-copy";
      const itemTitle = document.createElement("strong");
      itemTitle.className = "favorite-add-item-title";
      itemTitle.textContent = content.title || "未命名内容";
      const meta = document.createElement("span");
      meta.className = "favorite-add-item-meta";
      meta.textContent = alreadyAdded ? "已在当前收藏夹" : [content.author, platformLabel(content.platform)].filter(Boolean).join(" · ");
      copy.append(itemTitle, meta);
      row.classList.toggle("is-selected", select.checked);
      row.append(select, cover, copy);
      list.append(row);
    });
    if (!entries.length) {
      const empty = document.createElement("p");
      empty.className = "field-hint";
      empty.textContent = query ? "没有匹配的内容" : "暂无可加入的已归档内容";
      list.append(empty);
    }
    shell.append(list);
    const footer = document.createElement("footer");
    footer.className = "link-query-footer";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "button";
    cancel.textContent = "关闭";
    cancel.addEventListener("click", closeFavoriteAddDialog);
    const submit = document.createElement("button");
    submit.id = "add-existing-favorite-content";
    submit.type = "button";
    submit.className = "button button-primary";
    submit.textContent = "加入收藏夹";
    submit.disabled = state.favoriteAddSelectedIds.size === 0;
    submit.addEventListener("click", () => addExistingContentToFavorite(submit));
    footer.append(cancel, submit);
    shell.append(footer);
  }
  linkQueryDialog.append(shell);
  setLinkQueryDialogOpen(true);
  linkQueryDialog.oncancel = (event) => {
    event.preventDefault();
    closeFavoriteAddDialog();
  };
}

async function openFavoriteContentAdd(folder) {
  if (!folder || folder.is_system) {
    showNotice("请先选择一个普通收藏夹", true);
    return;
  }
  closeLibraryCardMenu({ restoreFocus: false });
  const associationFailures = favoriteAddAssociationFailuresForFolder(folder.id);
  const failedUrls = favoriteAddFailedLinksForFolder(folder.id);
  const activeBatch = state.favoriteAddBatch?.folderId === folder.id
    && state.favoriteAddBatch.jobIds?.length;
  const mode = activeBatch
    ? (associationFailures.length ? "association-retry" : "progress")
    : associationFailures.length ? "association-retry" : failedUrls.length ? "link-retry" : "existing";
  state.favoriteAddContext = {
    folderId: folder.id,
    mode,
    search: "",
    loading: false,
    batchJobs: [],
    batchCompleted: false,
    failedUrls,
  };
  state.favoriteAddChoices = [];
  state.favoriteAddSelectedIds = new Set();
  if (activeBatch) {
    state.batchJobIds = [...state.favoriteAddBatch.jobIds];
    state.batchReport = state.batchReport || { accepted: [], failed: [], skipped: [] };
    renderFavoriteContentAddDialog({ mode });
    window.clearTimeout(state.batchPollTimer);
    pollBatchJobs();
    return;
  }
  if (associationFailures.length) {
    renderFavoriteContentAddDialog({ mode });
    return;
  }
  state.favoriteAddContext.loading = true;
  renderFavoriteContentAddDialog({ mode: "existing" });
  try {
    const entries = [];
    let offset = 0;
    const pageSize = 50;
    while (true) {
      const page = await api(
        `/api/v1/history?archived_only=true&limit=${pageSize}&offset=${offset}&sort_by=updated_at&order=desc`,
      );
      if (!Array.isArray(page) || !page.length) break;
      entries.push(...page);
      offset += page.length;
      if (page.length < pageSize) break;
    }
    if (!state.favoriteAddContext || state.favoriteAddContext.folderId !== folder.id) return;
    state.favoriteAddChoices = entries;
    state.favoriteAddContext.loading = false;
    renderFavoriteContentAddDialog({ mode: "existing" });
  } catch (error) {
    if (!state.favoriteAddContext || state.favoriteAddContext.folderId !== folder.id) return;
    state.favoriteAddContext.loading = false;
    renderFavoriteContentAddDialog({ mode: "existing" });
    showNotice(error.message, true);
  }
}

function renderFavoriteFolders() {
  const panel = document.querySelector("#favorite-folder-list");
  if (!panel) return;
  const heading = document.querySelector("#favorite-folders .favorite-folders-heading > div");
  const existingBack = heading?.querySelector("#favorite-folder-back");
  existingBack?.remove();
  if (heading && state.activeFavoriteFolderId && !state.showingTrash) {
    const back = document.createElement("button");
    back.id = "favorite-folder-back";
    back.type = "button";
    back.className = "button button-small favorite-folder-back";
    back.textContent = "← 内容库";
    back.addEventListener("click", () => {
      state.activeFavoriteFolderId = "";
      invalidateReturnContext();
      loadHistory();
    });
    heading.insertBefore(back, heading.firstChild);
  }
  panel.replaceChildren();
  const folders = (state.favoriteFolders || []).filter((folder) => !folder.is_system);
  if (!folders.length) {
    const empty = document.createElement("span");
    empty.className = "favorite-folder-picker-empty";
    empty.textContent = "暂无收藏夹";
    panel.append(empty);
  }
  folders.forEach((folder) => panel.append(renderFavoriteFolderChip(folder)));
}

async function loadFavoriteFolders() {
  state.favoriteFolders = await api("/api/v1/favorite-folders");
  if (state.activeFavoriteFolderId && !state.favoriteFolders.some(
    (folder) => folder.id === state.activeFavoriteFolderId
  )) {
    state.activeFavoriteFolderId = "";
  }
  renderFavoriteFolders();
}

async function createFavoriteFolder() {
  const name = await openProductTextDialog({
    title: "新建收藏夹",
    label: "收藏夹名称",
    placeholder: "例如：待整理、重点课程",
    confirmLabel: "创建收藏夹",
  });
  if (!name) return;
  try {
    const folder = await api("/api/v1/favorite-folders", {
      method: "POST",
      body: JSON.stringify({ name, parent_id: null }),
    });
    state.favoriteFolders = [...state.favoriteFolders, folder];
    state.activeFavoriteFolderId = folder.id;
    renderFavoriteFolders();
    await loadHistory();
    showNotice(`已创建收藏夹“${folder.name}”`);
  } catch (error) {
    showNotice(error.message, true);
  }
}

async function renameFavoriteFolder(folder) {
  state.favoriteManagementMode = true;
  state.favoriteRenamingId = folder.id;
  renderFavoriteFolders();
}

async function deleteFavoriteFolder(folder) {
  if (!window.confirm(`删除收藏夹“${folder.name}”？其中内容仍保留在总库。`)) return;
  try {
    await api(`/api/v1/favorite-folders/${encodeURIComponent(folder.id)}`, { method: "DELETE" });
    state.favoriteFolders = state.favoriteFolders.filter((item) => item.id !== folder.id);
    if (state.activeFavoriteFolderId === folder.id) state.activeFavoriteFolderId = "";
    renderFavoriteFolders();
    await loadHistory();
    showNotice("收藏夹已删除");
  } catch (error) {
    showNotice(error.message, true);
  }
}

async function updateContentIntroduction(contentId, value, button) {
  const clean = String(value || "").trim();
  if (clean.length > 30) {
    showNotice("简介最多 30 个字", true);
    return;
  }
  if (button) button.disabled = true;
  try {
    const content = await api(`/api/v1/contents/${encodeURIComponent(contentId)}`, {
      method: "PATCH",
      body: JSON.stringify({ introduction: clean }),
    });
    const entry = state.libraryEntries.find((item) => item.content.id === contentId);
    if (entry) entry.content = content;
    state.activeContentSnapshot = content;
    state.resultIntroductionDirty = false;
    const overview = document.querySelector("#result-overview");
    if (overview) overview.textContent = content.introduction || "暂无总览";
    showNotice("简介已保存");
    if (state.currentView === "history") renderHistoryEntries(state.libraryEntries);
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    if (button) button.disabled = false;
  }
}

function renderIntroductionBackfillStatus(record) {
  const panel = document.querySelector("#introduction-backfill-status");
  if (!panel || !record) return;
  panel.hidden = false;
  panel.replaceChildren();
  const summary = document.createElement("span");
  summary.textContent = record.status === "completed"
    ? `简介补齐完成：成功 ${record.succeeded} · 跳过 ${record.skipped} · 失败 ${record.failed}`
    : `简介补齐处理中：${record.completed}/${record.total} · 成功 ${record.succeeded} · 失败 ${record.failed}`;
  panel.append(summary);
  if (record.status === "completed" && record.failed_ids?.length) {
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "button button-small";
    retry.textContent = "仅重试失败项";
    retry.addEventListener("click", () => startIntroductionBackfill(record.failed_ids));
    panel.append(retry);
  }
}

async function pollIntroductionBackfill() {
  const runId = state.introductionBackfillId;
  if (!runId) return;
  try {
    const record = await api(`/api/v1/content-introductions/backfill/${encodeURIComponent(runId)}`);
    if (state.introductionBackfillId !== runId) return;
    renderIntroductionBackfillStatus(record);
    if (record.status !== "completed") {
      state.introductionBackfillTimer = window.setTimeout(pollIntroductionBackfill, 800);
      return;
    }
    state.introductionBackfillTimer = null;
    if (state.currentView === "history") await loadHistory();
  } catch (error) {
    showNotice(error.message, true);
  }
}

async function startIntroductionBackfill(contentIds = []) {
  window.clearTimeout(state.introductionBackfillTimer);
  try {
    const record = await api("/api/v1/content-introductions/backfill", {
      method: "POST",
      body: JSON.stringify({ content_ids: contentIds }),
    });
    state.introductionBackfillId = record.run_id;
    renderIntroductionBackfillStatus(record);
    if (record.status !== "completed") pollIntroductionBackfill();
    else if (state.currentView === "history") await loadHistory();
  } catch (error) {
    showNotice(error.message, true);
  }
}

async function previewIntroductionBackfill(button) {
  if (button) button.disabled = true;
  try {
    const preview = await api("/api/v1/content-introductions/backfill/preview");
    if (!preview.eligible_count) {
      showNotice(
        preview.no_summary_count
          ? `没有可补齐的简介；${preview.no_summary_count} 条内容缺少有效总结`
          : "当前没有缺失简介且已有有效总结的内容",
      );
      return;
    }
    const confirmed = await openProductConfirmDialog({
      title: "补齐缺失简介",
      message: `检测到 ${preview.eligible_count} 条内容可根据已保存总结生成简介。${preview.no_summary_count ? `另有 ${preview.no_summary_count} 条因没有有效总结会跳过。` : ""}`,
      confirmLabel: "开始生成",
    });
    if (confirmed) await startIntroductionBackfill();
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    if (button) button.disabled = false;
  }
}

function renderLibraryIntroduction(content) {
  const text = document.createElement("p");
  text.className = "library-card-introduction";
  text.textContent = content.introduction || "暂无简介";
  text.title = content.introduction || "暂无简介";
  return text;
}

function renderLibraryPlatformBadge(platform) {
  const files = {
    bilibili: "bilibili.ico",
    zhihu: "zhihu.ico",
    xiaohongshu: "xiaohongshu.ico",
    wechat: "wechat.png",
    douyin: "douyin.ico",
    youtube: "youtube.ico",
  };
  const badge = document.createElement("span");
  badge.className = "library-card-platform";
  const label = platformLabel(platform || "web");
  badge.title = `${label}来源`;
  badge.setAttribute("role", "img");
  badge.setAttribute("aria-label", `${label}来源`);
  const filename = files[platform];
  if (!filename) {
    badge.classList.add("is-generic");
    badge.textContent = label;
    return badge;
  }

  const icon = document.createElement("img");
  const assetBase = window.location.protocol === "file:" ? "." : "/ui";
  icon.src = `${assetBase}/platform-icons/${filename}`;
  icon.alt = "";
  badge.append(icon);
  return badge;
}

function positionLibraryMenu() {
  const current = state.libraryMenu;
  if (!current?.trigger?.isConnected) {
    if (current) closeLibraryCardMenu({ restoreFocus: false });
    return;
  }
  const triggerRect = current.trigger.getBoundingClientRect();
  const portal = current.portal;
  portal.style.visibility = "hidden";
  const margin = 8;
  const cardRect = current.trigger.classList.contains("library-card-introduction-toggle")
    ? current.trigger.closest(".library-card")?.getBoundingClientRect()
    : null;
  portal.style.width = cardRect
    ? `${Math.min(cardRect.width, 320, window.innerWidth - margin * 2)}px`
    : "";
  const width = portal.offsetWidth;
  const height = portal.offsetHeight;
  const maxLeft = Math.max(margin, window.innerWidth - width - margin);
  const left = Math.min(Math.max(margin, (cardRect || triggerRect).right - width), maxLeft);
  let top = (cardRect || triggerRect).bottom + 6;
  if (top + height > window.innerHeight - margin) {
    top = (cardRect || triggerRect).top - height - 6;
  }
  if (top < margin) {
    top = Math.min(Math.max(margin, window.innerHeight - height - margin), (cardRect || triggerRect).bottom + 6);
  }
  portal.style.left = `${left}px`;
  portal.style.top = `${top}px`;
  portal.style.visibility = "visible";
}

function closeLibraryCardMenu({ restoreFocus = true } = {}) {
  const current = state.libraryMenu;
  if (!current) return;
  document.removeEventListener("pointerdown", current.onPointerDown, true);
  document.removeEventListener("keydown", current.onKeyDown, true);
  window.removeEventListener("resize", current.reposition);
  window.removeEventListener("scroll", current.reposition, true);
  current.trigger?.setAttribute("aria-expanded", "false");
  if (current.trigger?.classList.contains("library-card-introduction-toggle")) {
    current.trigger.title = "展开简介";
    current.trigger.setAttribute("aria-label", "展开简介");
  }
  current.portal.hidden = true;
  current.portal.replaceChildren();
  current.portal.style.visibility = "";
  current.portal.style.width = "";
  state.libraryMenu = null;
  if (restoreFocus && current.trigger?.isConnected) current.trigger.focus();
}

function renderLibraryMenuItems(entry) {
  const content = entry.content;
  const menuItems = document.createElement("div");
  menuItems.className = "library-card-menu-items";
  menuItems.setAttribute("role", "menu");
  menuItems.append(renderFavoriteFolderPicker(entry));
  if (content.canonical_url) {
    const source = document.createElement("a");
    source.className = "library-card-menu-item";
    source.href = content.canonical_url;
    source.target = "_blank";
    source.rel = "noreferrer";
    source.textContent = "打开来源";
    source.setAttribute("role", "menuitem");
    menuItems.append(source);
  }
  const exportButton = document.createElement("button");
  exportButton.type = "button";
  exportButton.className = "library-card-menu-item";
  exportButton.textContent = "导出";
  exportButton.setAttribute("role", "menuitem");
  exportButton.addEventListener("click", () => {
    closeLibraryCardMenu({ restoreFocus: false });
    exportSingleHistory(content.id);
  });
  menuItems.append(exportButton);
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "library-card-menu-item is-danger";
  remove.textContent = "移入回收站";
  remove.setAttribute("role", "menuitem");
  remove.addEventListener("click", async () => {
    if (!window.confirm(`确认将“${content.title}”移入可恢复回收站？`)) return;
    closeLibraryCardMenu({ restoreFocus: false });
    try {
      await api(`/api/v1/contents/${encodeURIComponent(content.id)}`, { method: "DELETE" });
      showNotice("内容已移入回收站");
      await loadHistory();
    } catch (error) {
      showNotice(error.message, true);
    }
  });
  menuItems.append(remove);
  return menuItems;
}

function openLibraryCardPopover(trigger, content) {
  if (state.libraryMenu?.trigger === trigger) {
    closeLibraryCardMenu({ restoreFocus: false });
    return;
  }
  closeLibraryCardMenu({ restoreFocus: false });
  const portal = document.querySelector("#library-menu-portal");
  if (!portal) return;
  portal.replaceChildren(content);
  portal.hidden = false;
  const current = {
    portal,
    trigger,
    reposition: () => positionLibraryMenu(),
    onPointerDown: (event) => {
      if (event.target === trigger || trigger.contains(event.target) || portal.contains(event.target)) return;
      closeLibraryCardMenu({ restoreFocus: false });
    },
    onKeyDown: (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeLibraryCardMenu();
      }
    },
  };
  state.libraryMenu = current;
  trigger.setAttribute("aria-expanded", "true");
  document.addEventListener("pointerdown", current.onPointerDown, true);
  document.addEventListener("keydown", current.onKeyDown, true);
  window.addEventListener("resize", current.reposition);
  window.addEventListener("scroll", current.reposition, true);
  portal.querySelector(".favorite-folder-picker")?.addEventListener("toggle", current.reposition);
  window.requestAnimationFrame(current.reposition);
}

function openLibraryCardMenu(trigger, entry) {
  openLibraryCardPopover(trigger, renderLibraryMenuItems(entry));
}

function openLibraryCardIntroduction(trigger, content) {
  const introduction = renderLibraryIntroduction(content);
  introduction.classList.add("library-card-introduction-popover");
  introduction.setAttribute("role", "region");
  introduction.setAttribute("aria-label", "内容简介");
  trigger.title = "收起简介";
  trigger.setAttribute("aria-label", "收起简介");
  openLibraryCardPopover(trigger, introduction);
}

function renderLibraryCard(entry) {
  const content = entry.content;
  const card = document.createElement("article");
  card.className = "library-card";
  card.dataset.contentId = content.id;
  const coverWrap = document.createElement("div");
  coverWrap.className = "library-card-cover-wrap";
  const cover = createSourceCover({
    title: content.title,
    thumbnail: entry.job?.thumbnail_url || content.thumbnail_url,
    platform: content.platform,
    className: "source-cover library-card-cover",
  });
  const openDetails = () => {
    if (state.currentView === "history") captureReturnContext(content.id);
    loadResult(content.id);
  };
  const openDetailsByKeyboard = (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    openDetails();
  };
  cover.classList.add("library-card-cover-link");
  cover.setAttribute("role", "button");
  cover.setAttribute("tabindex", "0");
  cover.setAttribute("aria-label", `打开${content.title || "内容"}详情`);
  cover.addEventListener("click", openDetails);
  cover.addEventListener("keydown", openDetailsByKeyboard);
  coverWrap.append(cover);
  coverWrap.append(renderLibraryPlatformBadge(content.platform));
  const title = document.createElement("h2");
  title.className = "library-card-title";
  title.tabIndex = 0;
  title.textContent = content.title || "未命名内容";
  title.title = title.textContent;
  title.setAttribute("aria-label", `打开${content.title || "内容"}详情`);
  title.addEventListener("click", openDetails);
  title.addEventListener("keydown", openDetailsByKeyboard);
  const tags = document.createElement("div");
  tags.className = "library-card-tags";
  const visibleTagNames = (content.tag_names || []).slice(0, 2);
  visibleTagNames.forEach((name) => {
    const chip = document.createElement("span");
    chip.className = "library-tag-chip";
    chip.textContent = name;
    tags.append(chip);
  });
  if ((content.tag_names || []).length > visibleTagNames.length) {
    const more = document.createElement("span");
    more.className = "library-tag-chip";
    more.textContent = `+${content.tag_names.length - visibleTagNames.length}`;
    tags.append(more);
  }
  const actions = document.createElement("div");
  actions.className = "library-card-actions";
  const menuToggle = document.createElement("button");
  menuToggle.type = "button";
  menuToggle.className = "library-card-menu-toggle";
  menuToggle.title = "更多操作";
  menuToggle.setAttribute("aria-label", "更多操作");
  menuToggle.setAttribute("aria-haspopup", "menu");
  menuToggle.setAttribute("aria-controls", "library-menu-portal");
  menuToggle.setAttribute("aria-expanded", "false");
  menuToggle.addEventListener("click", (event) => {
    event.stopPropagation();
    openLibraryCardMenu(menuToggle, entry);
  });
  const introductionToggle = document.createElement("button");
  introductionToggle.type = "button";
  introductionToggle.className = "library-card-introduction-toggle";
  introductionToggle.title = "展开简介";
  introductionToggle.setAttribute("aria-label", "展开简介");
  introductionToggle.setAttribute("aria-controls", "library-menu-portal");
  introductionToggle.setAttribute("aria-expanded", "false");
  introductionToggle.addEventListener("click", () => {
    if (introductionToggle.getAttribute("aria-expanded") === "true") {
      closeLibraryCardMenu({ restoreFocus: false });
      return;
    }
    openLibraryCardIntroduction(introductionToggle, content);
  });
  actions.append(menuToggle, introductionToggle);
  card.append(coverWrap, title, tags, actions);
  return card;
}

function renderHistoryEntries(entries) {
  closeLibraryCardMenu({ restoreFocus: false });
  state.libraryEntries = Array.isArray(entries) ? entries : [];
  if (state.libraryGridObserver) {
    state.libraryGridObserver.disconnect();
    state.libraryGridObserver = null;
  }
  state.resultSequence = [...new Set(state.libraryEntries.map((entry) => entry.content.id).filter(Boolean))];
  if (typeof renderResultQuickRail === "function") renderResultQuickRail();
  historyPanel.replaceChildren();
  historyPanel.className = "panel library-panel";
  if (!state.libraryEntries.length) {
    historyPanel.className = "panel empty-state";
    historyPanel.textContent = state.showingTrash ? "回收站为空" : "暂无归档内容";
    renderFavoriteFolders();
    return;
  }
  const grid = document.createElement("div");
  grid.className = "library-grid";
  state.libraryEntries.forEach((entry) => {
    grid.append(renderLibraryCard(entry));
  });
  historyPanel.append(grid);
  const updateColumns = () => {
    const width = grid.getBoundingClientRect().width;
    const columns = width < 420 ? 2 : width < 560 ? 3 : width < 700 ? 4 : 5;
    grid.dataset.columns = String(columns);
  };
  updateColumns();
  if (typeof ResizeObserver === "function") {
    state.libraryGridObserver = new ResizeObserver(updateColumns);
    state.libraryGridObserver.observe(grid);
  }
  if (state.libraryHasMore && !state.showingTrash) {
    const pagination = document.createElement("div");
    pagination.className = "library-pagination";
    const more = document.createElement("button");
    more.type = "button";
    more.className = "button";
    more.textContent = state.libraryLoading ? "正在加载…" : "加载更多";
    more.disabled = state.libraryLoading;
    more.addEventListener("click", () => loadHistory({ append: true }));
    pagination.append(more);
    historyPanel.append(pagination);
  }
  renderFavoriteFolders();
}

function importBatchStateLabel(job) {
  return {
    completed: "成功",
    failed: "失败",
    cancelled: "已取消",
    queued: "等待中",
    paused: "已暂停",
  }[job?.state] || job?.state || "处理中";
}

function renderImportBatchDetail(batch) {
  const title = document.querySelector("#batch-detail-title");
  const meta = document.querySelector("#batch-detail-meta");
  const progress = document.querySelector("#batch-detail-progress");
  const panel = document.querySelector("#batch-detail-panel");
  if (!title || !meta || !progress || !panel) return;
  title.textContent = batch.name || "导入批次";
  meta.textContent = [
    batch.source_type ? platformLabel(batch.source_type) : null,
    `共 ${batch.total} 项`,
    `成功 ${batch.completed || 0}`,
    `失败 ${batch.failed || 0}`,
    `已取消 ${batch.cancelled || 0}`,
    `等待 ${batch.queued || 0}`,
  ].filter(Boolean).join(" · ");
  const done = Number(batch.completed || 0) + Number(batch.failed || 0) + Number(batch.cancelled || 0);
  const ratio = batch.total ? Math.round(done * 100 / batch.total) : 0;
  progress.replaceChildren();
  const line = document.createElement("div");
  line.textContent = `处理进度 ${done}/${batch.total} · ${ratio}%`;
  const bar = document.createElement("div");
  bar.className = "batch-detail-progress-bar";
  const fill = document.createElement("span");
  fill.style.width = `${ratio}%`;
  bar.append(fill);
  progress.append(line, bar);
  panel.replaceChildren();
  const list = document.createElement("div");
  list.className = "batch-detail-list";
  (batch.members || []).forEach((member) => {
    const job = member.job || {};
    const content = member.content || taskContentFromJob(job);
    const row = document.createElement("article");
    row.className = "batch-detail-member";
    const cover = createSourceCover({
      title: content.title,
      thumbnail: job.thumbnail_url || content.thumbnail_url,
      platform: content.platform,
      className: "source-cover batch-detail-member-cover",
    });
    const copy = document.createElement("div");
    copy.className = "batch-detail-member-copy";
    const heading = document.createElement("strong");
    heading.className = "batch-detail-member-title";
    heading.textContent = content.title || "未命名内容";
    const status = document.createElement("p");
    status.className = "batch-detail-member-meta";
    status.textContent = `${importBatchStateLabel(job)} · ${job.progress || 0}%`;
    copy.append(heading, status);
    if (job.error_message) {
      const error = document.createElement("p");
      error.className = "batch-detail-member-error";
      error.textContent = job.error_message;
      copy.append(error);
    }
    const actions = document.createElement("div");
    actions.className = "batch-detail-member-actions actions";
    if (job.state === "completed" && content.id) {
      const open = document.createElement("button");
      open.type = "button";
      open.className = "button button-small button-primary";
      open.textContent = "查看内容";
      open.addEventListener("click", () => {
        state.libraryEntries = (batch.members || []).filter((item) => item.content?.id).map((item) => item);
        state.resultSequence = [...new Set(state.libraryEntries.map((item) => item.content.id).filter(Boolean))];
        state.returnContext = {
          sourceView: "batch-detail",
          importBatchId: batch.id,
          selectedTagIds: [],
          selectedFolderId: "",
          searchQuery: "",
          sortMode: "created_at:desc",
          anchorContentId: content.id,
          scrollOffset: 0,
        };
        loadResult(content.id);
      });
      actions.append(open);
    }
    if (["failed", "cancelled"].includes(job.state)) {
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "button button-small";
      retry.textContent = "重试";
      retry.addEventListener("click", async () => {
        retry.disabled = true;
        try {
          await retryJob(job.id);
          await loadImportBatch(batch.id, { sourceView: "batch-detail" });
        } finally {
          retry.disabled = false;
        }
      });
      actions.append(retry);
    }
    row.append(cover, copy, actions);
    list.append(row);
  });
  if (!list.childElementCount) {
    panel.className = "panel batch-detail-panel empty-state";
    panel.textContent = "该批次暂无成员，建议重新导入。";
  } else {
    panel.className = "panel batch-detail-panel";
    panel.append(list);
  }
}

async function loadImportBatch(batchId, { sourceView = "history", anchorContentId = null } = {}) {
  if (!batchId) return;
  try {
    const batch = await api(`/api/v1/import-batches/${encodeURIComponent(batchId)}`);
    state.activeImportBatchId = batch.id;
    if (sourceView !== "batch-detail") {
      if (sourceView === "history" && state.currentView === "history") {
        captureReturnContext(anchorContentId);
      }
      state.batchReturnContext = state.returnContext
        ? { ...state.returnContext, sourceView }
        : { sourceView, anchorContentId, scrollOffset: window.scrollY || 0 };
    }
    renderImportBatchDetail(batch);
    showView("batch-detail");
  } catch (error) {
    showNotice(error.message, true);
  }
}

async function loadHistory({ trash = state.showingTrash, append = false } = {}) {
  if (state.libraryLoading) {
    state.libraryPendingHistoryRequest = { trash, append };
    return;
  }
  const requestId = ++state.libraryHistoryRequestSequence;
  const returnContext = state.returnContext && !trash && state.returnContext.sourceView === "history"
    ? state.returnContext
    : null;
  if (returnContext) {
    restoreReturnContext();
    state.returnContext = null;
  }
  state.showingTrash = trash;
  if (!append) state.libraryHasMore = false;
  state.libraryLoading = true;
  const requestedOffset = append
    ? state.libraryPageStart + state.libraryEntries.length
    : (returnContext?.libraryOffset || 0);
  const query = document.querySelector("#history-query")?.value.trim() || "";
  const platform = document.querySelector("#history-platform")?.value || "";
  const author = document.querySelector("#history-author")?.value.trim() || "";
  const [sortBy, order] = (document.querySelector("#history-sort")?.value || "created_at:desc").split(":");
  try {
    const metadataResults = await Promise.allSettled([loadFavoriteFolders(), loadTags(), api("/api/v1/history/count")]);
    const metadataError = metadataResults.find((result) => result.status === "rejected")?.reason;
    if (metadataResults[2].status === "fulfilled") {
      state.libraryTotal = metadataResults[2].value.total;
      renderTagNavigation();
    }
    const params = new URLSearchParams();
    if (query) params.set("q", query);
    if (platform && !state.showingTrash) params.set("platform", platform);
    if (author && !state.showingTrash) params.set("author", author);
    if (state.activeFavoriteFolderId && !state.showingTrash) {
      params.set("favorite_folder_id", state.activeFavoriteFolderId);
    }
    if (state.activeTagId && !state.showingTrash) params.set("tag_id", state.activeTagId);
    if (!state.showingTrash) {
      params.set("archived_only", "true");
      params.set("sort_by", sortBy || "created_at");
      params.set("order", order || "desc");
      params.set("limit", String(state.libraryPageSize));
      params.set("offset", String(requestedOffset));
    }
    const path = state.showingTrash
      ? `/api/v1/trash${params.toString() ? `?${params}` : ""}`
      : `/api/v1/history?${params}`;
    const entries = await api(path);
    if (requestId !== state.libraryHistoryRequestSequence) return;
    const title = document.querySelector("#history-title");
    if (title) {
      const folder = state.favoriteFolders.find((item) => item.id === state.activeFavoriteFolderId);
      title.textContent = state.showingTrash
        ? "回收站"
        : state.activeTagName
          ? `内容库 · ${state.activeTagName}`
          : folder ? `内容库 · ${folder.name}` : "内容库";
    }
    const trashButton = document.querySelector("#show-trash");
    if (trashButton) trashButton.textContent = state.showingTrash ? "返回内容库" : "回收站";
    const page = Array.isArray(entries) ? entries : [];
    const combined = append ? [...state.libraryEntries, ...page] : page;
    const unique = new Map();
    combined.forEach((entry) => {
      if (entry?.content?.id) unique.set(entry.content.id, entry);
    });
    state.libraryHasMore = !state.showingTrash && page.length === state.libraryPageSize;
    if (!append) state.libraryPageStart = requestedOffset;
    state.libraryLoading = false;
    renderHistoryEntries([...unique.values()]);
    if (metadataError) {
      showNotice(`标签或收藏夹暂时无法加载：${metadataError.message || "请稍后重试"}`, true);
    }
    if (returnContext?.anchorContentId) {
      const anchor = [...document.querySelectorAll("[data-content-id]")]
        .find((item) => item.dataset.contentId === returnContext.anchorContentId);
      if (anchor) {
        const targetTop = anchor.getBoundingClientRect().top + window.scrollY - Math.max(24, window.innerHeight * 0.2);
        window.scrollTo({ top: Math.max(0, targetTop), behavior: "auto" });
      } else {
        window.setTimeout(() => window.scrollTo({ top: returnContext.scrollOffset || 0, behavior: "auto" }), 0);
      }
    }
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    state.libraryLoading = false;
    const pendingHistoryRequest = state.libraryPendingHistoryRequest;
    if (pendingHistoryRequest) {
      state.libraryPendingHistoryRequest = null;
      loadHistory(pendingHistoryRequest);
    }
  }
}

function updateResultNavigation() {
  const previous = document.querySelector("#result-prev");
  const next = document.querySelector("#result-next");
  const footerPrevious = document.querySelector("#result-footer-prev");
  const footerNext = document.querySelector("#result-footer-next");
  const select = document.querySelector("#result-quick-select");
  const position = document.querySelector("#result-position");
  const index = state.resultSequence.indexOf(state.activeContentId);
  state.resultIndex = index;
  const atFirst = index <= 0;
  const atLast = index < 0 || index >= state.resultSequence.length - 1;
  if (previous) {
    previous.disabled = atFirst;
    previous.title = atFirst ? "已是第一条" : "上一条内容";
  }
  if (next) {
    next.disabled = atLast;
    next.title = atLast ? "已是最后一条" : "下一条内容";
  }
  if (footerPrevious) footerPrevious.disabled = atFirst;
  if (footerNext) footerNext.disabled = atLast;
  if (position) position.textContent = index >= 0 ? `${index + 1} / ${state.resultSequence.length}` : "";
  if (!select) return;
  select.replaceChildren();
  state.resultSequence.forEach((id, itemIndex) => {
    const entry = state.libraryEntries.find((item) => item.content.id === id);
    if (!entry) return;
    select.append(new Option(`${itemIndex + 1}. ${entry.content.title}`, id, false, id === state.activeContentId));
  });
  select.hidden = state.resultSequence.length < 2;
}

async function navigateResult(delta) {
  if (state.resultIntroductionDirty && !window.confirm("简介有未保存修改，确定放弃并切换吗？")) return;
  const index = state.resultSequence.indexOf(state.activeContentId);
  const target = state.resultSequence[index + delta];
  if (!target) return;
  await loadResult(target, { preserveContext: true });
}

function renderResultIntroduction(content) {
  const input = document.querySelector("#result-introduction");
  const count = document.querySelector("#result-introduction-count");
  if (!input) return;
  input.value = content.introduction || "";
  const overview = document.querySelector("#result-overview");
  if (overview) overview.textContent = content.introduction || "暂无总览";
  state.resultIntroductionDirty = false;
  if (count) count.textContent = `${input.value.length}/30`;
  input.oninput = () => {
    state.resultIntroductionDirty = input.value !== (state.activeContentSnapshot?.introduction || "");
    if (count) count.textContent = `${input.value.length}/30`;
  };
  const save = document.querySelector("#save-result-introduction");
  if (save) save.onclick = () => updateContentIntroduction(content.id, input.value, save);
}

function renderResultTags(content, suggestions = []) {
  const list = document.querySelector("#result-tag-list");
  const suggestionPanel = document.querySelector("#result-tag-suggestions");
  if (!list || !suggestionPanel) return;
  list.replaceChildren();
  (content.tag_names || []).forEach((name) => {
    const chip = document.createElement("span");
    chip.className = "library-tag-chip";
    chip.textContent = name;
    list.append(chip);
  });
  suggestionPanel.replaceChildren();
  const candidates = (suggestions || []).filter((item) => Number(item.confidence) >= 0.8);
  if (!candidates.length) {
    suggestionPanel.hidden = true;
    return;
  }
  suggestionPanel.hidden = false;
  const label = document.createElement("span");
  label.textContent = "AI 候选（确认后写入）：";
  suggestionPanel.append(label);
  candidates.forEach((item) => {
    const chip = document.createElement("span");
    chip.className = "tag-suggestion";
    chip.dataset.tagName = item.name;
    chip.textContent = `${item.name} ${(Number(item.confidence) * 100).toFixed(0)}%`;
    const discard = document.createElement("button");
    discard.type = "button";
    discard.replaceChildren(createIcon("close"));
    discard.setAttribute("aria-label", `丢弃候选 ${item.name}`);
    discard.addEventListener("click", () => chip.remove());
    chip.append(discard);
    suggestionPanel.append(chip);
  });
  const addAll = document.createElement("button");
  addAll.type = "button";
  addAll.className = "button button-small";
  addAll.textContent = "全部添加";
  addAll.addEventListener("click", () => {
    const names = [...suggestionPanel.querySelectorAll(".tag-suggestion")].map((item) => item.dataset.tagName);
    const tagIds = state.tags.filter((tag) => names.includes(tag.name)).map((tag) => tag.id);
    updateContentTags(content.id, [...new Set([...(content.tag_ids || []), ...tagIds])]);
  });
  suggestionPanel.append(addAll);
}

async function updateContentTags(contentId, tagIds) {
  try {
    const content = await api(`/api/v1/contents/${encodeURIComponent(contentId)}`, {
      method: "PATCH",
      body: JSON.stringify({ tag_ids: [...new Set(tagIds)] }),
    });
    state.activeContentSnapshot = content;
    await loadTags();
    renderResultTags(content, []);
    const entry = state.libraryEntries.find((item) => item.content.id === contentId);
    if (entry) entry.content = content;
    showNotice("标签已更新");
  } catch (error) {
    showNotice(error.message, true);
  }
}

async function editResultTags(content) {
  await loadTags();
  const dialog = document.createElement("dialog");
  dialog.className = "tag-editor-dialog";
  const heading = document.createElement("h2");
  heading.textContent = "编辑标签";
  const form = document.createElement("form");
  form.method = "dialog";
  const selected = new Set(content.tag_ids || []);
  const history = document.createElement("div");
  history.className = "tag-editor-history";
  state.tags.forEach((tag) => {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = tag.id;
    input.checked = selected.has(tag.id);
    input.addEventListener("change", () => input.checked ? selected.add(tag.id) : selected.delete(tag.id));
    label.append(input, document.createTextNode(tag.name));
    history.append(label);
  });
  const custom = document.createElement("input");
  custom.placeholder = "输入自定义标签，回车添加";
  custom.addEventListener("keydown", async (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    const name = custom.value.trim();
    if (!name) return;
    try {
      const tag = await api("/api/v1/tags", { method: "POST", body: JSON.stringify({ name }) });
      state.tags.push(tag);
      selected.add(tag.id);
      custom.value = "";
      await editResultTags(content);
      dialog.close();
    } catch (error) {
      showNotice(error.message, true);
    }
  });
  const actions = document.createElement("div");
  actions.className = "actions";
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "button";
  cancel.textContent = "取消";
  cancel.addEventListener("click", () => dialog.close());
  const save = document.createElement("button");
  save.type = "submit";
  save.className = "button button-primary";
  save.textContent = "保存标签";
  actions.append(cancel, save);
  form.append(history, custom, actions);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    await updateContentTags(content.id, [...selected]);
    dialog.close();
  });
  dialog.append(heading, form);
  document.body.append(dialog);
  dialog.addEventListener("close", () => dialog.remove(), { once: true });
  dialog.showModal();
}

function configureResultInlineEdit(contentId, version) {
  const edit = document.querySelector("#result-outline-edit");
  const save = document.querySelector("#result-outline-save");
  const documentBody = document.querySelector("#result-markdown");
  const scrollRoot = document.querySelector(".main-content");
  if (!edit || !save || !documentBody || !scrollRoot) return;
  edit.disabled = !version;
  edit.title = version ? "编辑当前总结版本" : "当前正文没有可编辑版本";
  edit.hidden = false;
  save.hidden = true;
  save.disabled = false;
  save.textContent = "保存";
  documentBody.classList.remove("is-editing");
  edit.onclick = () => {
    if (!version) {
      showNotice("当前正文没有可编辑版本", true);
      return;
    }
    const position = scrollRoot.scrollTop;
    const documentHeight = documentBody.getBoundingClientRect().height;
    const editor = document.createElement("textarea");
    editor.className = "result-inline-editor";
    editor.value = version.markdown;
    editor.style.minHeight = `${Math.max(documentHeight, scrollRoot.clientHeight * 0.65)}px`;
    documentBody.replaceChildren(editor);
    documentBody.classList.add("is-editing");
    edit.hidden = true;
    save.hidden = false;
    scrollRoot.scrollTop = position;
    save.onclick = async () => {
      const draft = editor.value;
      const savePosition = scrollRoot.scrollTop;
      save.disabled = true;
      try {
        await api(`/api/v1/contents/${contentId}/summary-versions/${version.id}`, {
          method: "PUT",
          body: JSON.stringify({ markdown: draft }),
        });
        const loaded = await loadResult(contentId, { preserveContext: true });
        if (!loaded) {
          save.textContent = "刷新";
          save.onclick = async () => {
            save.disabled = true;
            const refreshed = await loadResult(contentId, { preserveContext: true });
            if (refreshed) scrollRoot.scrollTop = savePosition;
            else save.disabled = false;
          };
          save.disabled = false;
          showNotice("新版本已保存，但页面刷新失败，请点击刷新", true);
          return;
        }
        scrollRoot.scrollTop = savePosition;
        showNotice("已保存为新版本，原版本仍保留");
      } catch (error) {
        showNotice(error.message, true);
        save.disabled = false;
      }
    };
  };
}

async function loadResult(contentId, { preserveContext = false } = {}) {
  try {
    const result = await api(`/api/v1/contents/${encodeURIComponent(contentId)}/result`);
    await loadTags();
    if (!preserveContext && state.currentView === "history") captureReturnContext(contentId);
    state.activeContentId = contentId;
    state.activeContentSnapshot = result.content;
    state.activeArchivePath = result.archive_path || "";
    document.querySelector("#result-title").textContent = result.content.title;
    const resultMeta = document.querySelector("#result-meta");
    resultMeta.replaceChildren();
    const analyzedAt = result.versions?.[0]?.created_at || result.job.completed_at || result.job.updated_at;
    if (analyzedAt) {
      const analysisTime = document.createElement("time");
      analysisTime.className = "result-analysis-time";
      analysisTime.dateTime = analyzedAt;
      analysisTime.textContent = `分析于 ${formatTimestamp(analyzedAt)}`;
      resultMeta.append(analysisTime);
    }
    // 设计稿：顶部不再铺「总结模型」标签与重新总结按钮，重新生成统一收到目录栏。
    const currentVersion = result.versions?.[0] || null;
    renderResultDocument(currentVersion?.markdown || result.markdown);
    configureResultInlineEdit(contentId, currentVersion);
    renderResultTags(result.content, result.tag_suggestions || []);
    document.querySelector("#edit-result-tags").onclick = () => editResultTags(result.content);
    renderResultIntroduction(result.content);
    renderResultAssets(result);
    updateResultNavigation();
    renderResultQuickRail();
    showView("result");
    return true;
  } catch (error) {
    showNotice(error.message, true);
    return false;
  }
}

function resummarizeContent(contentId, triggerButton) {
  if (!textEntryDialog || textEntryDialog.open) return;
  if (triggerButton) triggerButton.disabled = true;
  textEntryDialog.replaceChildren();
  const shell = document.createElement("div");
  shell.className = "product-text-dialog-shell resummarize-dialog-shell";
  const heading = document.createElement("h2");
  heading.id = "text-entry-dialog-title";
  heading.textContent = "重新总结";
  const description = document.createElement("p");
  description.className = "resummarize-dialog-description";
  description.textContent = "将从头重新处理原来源，完成后创建一条新知识内容，不读取或覆盖当前总结。";
  const form = document.createElement("form");
  form.className = "product-text-dialog-form";
  const styleField = document.createElement("label");
  styleField.className = "field field-wide";
  const styleCaption = document.createElement("span");
  styleCaption.textContent = "表达风格";
  const style = document.createElement("select");
  style.setAttribute("aria-label", "重新总结表达风格");
  Object.entries(summaryStyleLabels).forEach(([value, label]) => style.append(new Option(label, value)));
  style.value = document.querySelector("#summary-style")?.value || "general";
  styleField.append(styleCaption, style);
  const strengthField = document.createElement("label");
  strengthField.className = "field field-wide";
  const strengthCaption = document.createElement("span");
  strengthCaption.textContent = "总结强度";
  const strength = document.createElement("select");
  strength.setAttribute("aria-label", "重新总结强度");
  [["quick", "简要"], ["standard", "标准"], ["deep", "详细"]]
    .forEach(([value, label]) => strength.append(new Option(label, value)));
  strength.value = "standard";
  strengthField.append(strengthCaption, strength);
  const errorPanel = document.createElement("p");
  errorPanel.className = "resummarize-dialog-error";
  errorPanel.hidden = true;
  const actions = document.createElement("div");
  actions.className = "actions product-text-dialog-actions";
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "button";
  cancel.textContent = "取消";
  cancel.addEventListener("click", () => textEntryDialog.close());
  const submit = document.createElement("button");
  submit.type = "submit";
  submit.className = "button button-primary";
  submit.textContent = "开始重新总结";
  actions.append(cancel, submit);
  form.append(styleField, strengthField, errorPanel, actions);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorPanel.hidden = true;
    submit.disabled = true;
    try {
      const result = await api(`/api/v1/contents/${encodeURIComponent(contentId)}/resummarize`, {
        method: "POST",
        body: JSON.stringify({ summary_style: style.value, strength: strength.value, max_chunk_tokens: 800 }),
      });
      state.activeJobId = result.job.id;
      state.activeContentId = result.content.id;
      state.activeJobTitle = result.content.title;
      state.activeContentSnapshot = result.content;
      renderJob(result.job, state.activeJobTitle, result.content);
      textEntryDialog.close();
      showView("intake");
      showNotice("已创建重新总结任务；原内容保持不变");
      await loadTaskList();
      pollJob();
    } catch (error) {
      errorPanel.textContent = error.message || "重新总结失败，请稍后重试";
      errorPanel.hidden = false;
      submit.disabled = false;
      if (isConfigurationError(error) && !actions.querySelector(".resummarize-settings-button")) {
        const settings = document.createElement("button");
        settings.type = "button";
        settings.className = "button button-small resummarize-settings-button";
        settings.textContent = "前往设置";
        settings.addEventListener("click", () => {
          textEntryDialog.close();
          showView("settings");
        });
        actions.insertBefore(settings, submit);
      }
    }
  });
  textEntryDialog.append(shell);
  shell.append(heading, description, form);
  textEntryDialog.oncancel = () => textEntryDialog.close();
  textEntryDialog.addEventListener("close", () => {
    if (triggerButton) triggerButton.disabled = false;
    textEntryDialog.oncancel = null;
  }, { once: true });
  if (typeof textEntryDialog.showModal === "function") textEntryDialog.showModal();
  else textEntryDialog.open = true;
  window.requestAnimationFrame(() => template.focus());
}

function showView(name, { preserveReturnContext = false } = {}) {
  const viewName = name === "workspace" ? "intake" : name;
  const previousView = state.currentView || "intake";
  const topLevelViews = new Set(["intake", "tasks", "history", "ask", "settings"]);
  if (previousView === "tasks" && viewName !== "tasks") {
    state.taskExpandedJobId = null;
    state.taskEditing = false;
    state.taskSelectionMode = false;
    state.taskSelectedIds.clear();
  }
  if (
    !preserveReturnContext
    && topLevelViews.has(viewName)
    && viewName !== "settings"
    && viewName !== previousView
  ) {
    invalidateReturnContext();
  }
  if (viewName === "settings" && previousView !== "settings") {
    if (previousView === "history" && !state.returnContext) captureReturnContext();
    state.settingsReturnView = previousView;
  }
  state.currentView = viewName;
  clearNotice();
  views.forEach((view) => {
    const active = view.dataset.view === viewName;
    view.hidden = !active;
    view.classList.toggle("is-view-entering", active);
    if (active) window.requestAnimationFrame(() => view.classList.remove("is-view-entering"));
  });
  if (viewName === "intake") showIntakeMode(state.intakeMode);
  navButtons.forEach((button) => button.classList.toggle("is-active", button.dataset.viewTarget === viewName));
  if (settingsReturnButton) {
    const labels = { intake: "内容接入", tasks: "任务", history: "知识库", ask: "AI 问答", result: "结果" };
    settingsReturnButton.textContent = `返回${labels[state.settingsReturnView] || "上一页"}`;
  }
  updateReturnControls();
  if (viewName === "history") loadHistory();
  if (viewName === "tasks") loadTaskList();
  if (viewName === "settings") loadSettings();
  if (viewName === "settings") loadAskSettings().catch((error) => showNotice(error.message, true));
  if (viewName === "ask") loadAskHome();
  if (viewName === "intake" && state.settingsReturnNeedsQuery) {
    const source = state.settingsReturnNeedsQuery;
    state.settingsReturnNeedsQuery = null;
    window.setTimeout(() => {
      if (source === "local") {
        queryLocalSource();
      } else if (state.linkQuery) {
        renderLinkQueryDialog(state.linkQuery);
      }
    }, 0);
  }
}

function taskContentFromJob(job) {
  return {
    id: job.content_id,
    title: job.content_title || "未命名任务",
    platform: job.content_platform || (job.source_url ? detectLinkPlatform(job.source_url) : "web"),
    author: job.content_author || null,
    category: job.content_category || "未分类",
    canonical_url: job.source_url || null,
    thumbnail_url: job.thumbnail_url || null,
    favorite_folder_ids: [],
    tag_ids: [],
    tag_names: [],
    introduction: "",
  };
}

function taskFilterMatches(job, filter = state.taskFilter) {
  const execution = taskExecutionState(job);
  if (filter === "all") return true;
  if (filter === "completed") return execution === "completed";
  if (filter === "failed") return execution === "failed";
  if (filter === "cancelled") return execution === "cancelled";
  if (filter === "queued" || filter === "waiting") return execution === "waiting";
  return execution === "running" || execution === "switching";
}

function renderTaskExpandedDetails(entry) {
  const { job } = entry;
  const content = entry.content || taskContentFromJob(job);
  const details = document.createElement("div");
  details.className = "task-list-card-details";
  details.append(renderTaskStages(job));
  const stage = document.createElement("p");
  stage.className = "task-list-card-detail-stage";
  stage.textContent = `${jobStage(job).label} · ${jobStage(job).detail} · ${job.progress || 0}%`;
  details.append(stage);
  const asrStats = renderAsrStats(job);
  if (asrStats) details.append(asrStats);
  if (job.error_message) {
    const error = document.createElement("p");
    error.className = "task-list-card-detail-error";
    error.textContent = job.error_message;
    details.append(error);
  }
  if (job.state === "failed") {
    const recovery = document.createElement("p");
    recovery.className = "task-list-card-detail-recovery";
    recovery.textContent = jobFailure(job).suggestion;
    details.append(recovery);
  }
  const timing = document.createElement("dl");
  timing.className = "task-list-card-detail-timing";
  [["创建", job.created_at], ["开始", job.started_at], ["完成", job.completed_at]].forEach(([label, value]) => {
    const item = document.createElement("div");
    const term = document.createElement("dt");
    term.textContent = label;
    const definition = document.createElement("dd");
    definition.textContent = formatTimestamp(value);
    item.append(term, definition);
    timing.append(item);
  });
  details.append(timing);
  if (content.canonical_url || job.source_url) {
    const source = document.createElement("a");
    source.href = content.canonical_url || job.source_url;
    source.target = "_blank";
    source.rel = "noreferrer";
    source.className = "task-list-card-source";
    source.textContent = "打开来源";
    details.append(source);
  }
  return details;
}

function renderTaskListCard(entry) {
  const { job } = entry;
  const content = entry.content || taskContentFromJob(job);
  const execution = taskExecutionState(job);
  const waiting = taskIsWaiting(job);
  const paused = taskIsPaused(job);
  const running = taskIsRunning(job);
  const terminal = taskIsTerminal(job);
  const expanded = state.taskExpandedJobId === job.id;
  const row = document.createElement("article");
  row.className = "task-list-card" + (job.id === state.activeJobId ? " is-focused" : "");
  row.dataset.jobId = job.id;
  row.dataset.executionState = execution;
  row.draggable = false;
  const leading = document.createElement("div");
  leading.className = "task-list-card-leading";
  const expand = document.createElement("button");
  expand.type = "button";
  expand.className = "task-expand-toggle";
  expand.textContent = expanded ? "⌃" : "⌄";
  expand.setAttribute("aria-expanded", String(expanded));
  expand.setAttribute("aria-label", `${expanded ? "收起" : "展开"}任务详情：${content.title || "未命名任务"}`);
  expand.addEventListener("click", () => {
    state.taskExpandedJobId = expanded ? null : job.id;
    state.activeJobId = job.id;
    state.activeContentId = content.id || null;
    state.activeJobTitle = content.title;
    state.activeContentSnapshot = content;
    renderTaskList();
  });
  leading.append(expand);
  if (state.taskEditing) {
    const check = document.createElement("input");
    check.type = "checkbox";
    check.className = "task-list-selection";
    check.checked = state.taskSelectedIds.has(job.id);
    check.setAttribute("aria-label", `选择任务 ${content.title || "未命名任务"}`);
    check.addEventListener("click", (event) => event.stopPropagation());
    check.addEventListener("change", () => {
      if (check.checked) state.taskSelectedIds.add(job.id);
      else state.taskSelectedIds.delete(job.id);
      updateTaskBatchToolbar();
    });
    leading.append(check);
  }
  let handle = null;
  if (waiting) {
    handle = document.createElement("span");
    handle.className = "task-drag-handle";
    handle.replaceChildren(createIcon("drag"));
    handle.title = "拖动调整等待顺序";
    handle.setAttribute("aria-label", "拖动调整等待顺序");
    handle.draggable = true;
    handle.addEventListener("dragstart", (event) => {
      state.taskDragJobId = job.id;
      row.classList.add("is-dragging");
      event.dataTransfer?.setData("text/plain", job.id);
      if (event.dataTransfer) event.dataTransfer.effectAllowed = "move";
    });
    handle.addEventListener("dragend", () => {
      state.taskDragJobId = null;
      row.classList.remove("is-dragging");
      document.querySelectorAll(".task-list-card.is-drop-target").forEach((item) => item.classList.remove("is-drop-target"));
    });
    leading.append(handle);
  }
  const cover = createSourceCover({
    title: content.title,
    thumbnail: job.thumbnail_url || content.thumbnail_url,
    platform: content.platform,
    className: "task-list-cover",
  });
  const body = document.createElement("div");
  body.className = "task-list-card-body";
  const heading = document.createElement("div");
  heading.className = "task-list-card-heading";
  const title = document.createElement("h2");
  title.className = "task-list-card-title";
  title.textContent = content.title || "未命名任务";
  title.title = title.textContent;
  const badge = document.createElement("span");
  badge.className = `status status-${execution}`;
  const statusIcon = execution === "switching" ? "running" : execution === "cancelled" ? "failed" : execution;
  badge.title = statusLabel(execution);
  badge.setAttribute("aria-label", statusLabel(execution));
  badge.replaceChildren(createIcon(`status-${statusIcon}`, "icon-status"));
  heading.append(title, badge);
  const meta = document.createElement("p");
  meta.className = "task-list-card-meta";
  meta.textContent = [
    platformLabel(content.platform),
    content.author ? `作者：${content.author}` : null,
  ].filter(Boolean).join(" · ");
  body.append(heading, meta);  const actions = document.createElement("div");
  actions.className = "task-list-card-actions";
  const disabled = state.taskSwitching;
  if (waiting && !terminal) {
    const promote = document.createElement("button");
    promote.type = "button";
    promote.className = "button button-small";
    promote.textContent = "⇧";
    promote.title = "移到队首";
    promote.setAttribute("aria-label", `将任务移到队首：${content.title || "未命名任务"}`);
    promote.disabled = disabled;
    promote.addEventListener("click", () => promoteTask(job.id));
    const start = document.createElement("button");
    start.type = "button";
    start.className = "button button-small button-primary";
    start.textContent = "▶";
    start.title = "立即处理此任务";
    start.setAttribute("aria-label", `立即处理任务：${content.title || "未命名任务"}`);
    start.disabled = disabled;
    start.addEventListener("click", () => switchTask(job.id));
    actions.append(promote, start);
  } else if (paused) {
    const resume = document.createElement("button");
    resume.type = "button";
    resume.className = "button button-small button-primary";
    resume.textContent = "▶";
    resume.title = "继续处理此任务";
    resume.setAttribute("aria-label", `继续处理任务：${content.title || "未命名任务"}`);
    resume.disabled = disabled;
    resume.addEventListener("click", () => resumeJob(job.id));
    actions.append(resume);
  } else if (running) {
    const pause = document.createElement("button");
    pause.type = "button";
    pause.className = "button button-small";
    pause.textContent = "⏸";
    pause.title = "暂停当前任务";
    pause.setAttribute("aria-label", `暂停任务：${content.title || "未命名任务"}`);
    pause.disabled = disabled;
    pause.addEventListener("click", () => pauseJob(job.id));
    actions.append(pause);
  }
  if (state.taskEditing && !terminal) {
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "button button-small button-danger";
    cancel.textContent = "取消";
    cancel.disabled = disabled;
    cancel.addEventListener("click", () => cancelJob(job.id));
    actions.append(cancel);
  }
  if (job.state === "failed") {
    appendJobRecoveryAction(actions, job, { compact: true });
  } else if (job.state === "cancelled") {
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "button button-small";
    retry.textContent = "重新开始";
    retry.addEventListener("click", () => retryJob(job.id));
    actions.append(retry);
  }
  if (job.state === "completed" && content.id) {
    const result = document.createElement("button");
    result.type = "button";
    result.className = "button button-small button-primary";
    result.textContent = "查看";
    result.addEventListener("click", () => {
      state.returnContext = { sourceView: "tasks" };
      loadResult(content.id);
    });
    actions.append(result);
  }
  if (terminal) {
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "task-delete-icon";
    remove.title = "删除记录";
    remove.setAttribute("aria-label", `删除任务记录：${content.title || "未命名任务"}`);
    remove.replaceChildren(createIcon("trash"));
    remove.addEventListener("click", () => deleteJob(job.id, remove));
    actions.append(remove);
  }
  if (actions.childElementCount) body.append(actions);
  row.append(leading, cover, body);
  if (expanded) row.append(renderTaskExpandedDetails(entry));
  if (waiting) {
    row.addEventListener("dragover", (event) => {
      if (!state.taskDragJobId || state.taskDragJobId === job.id) return;
      event.preventDefault();
      row.classList.add("is-drop-target");
    });
    row.addEventListener("dragleave", () => row.classList.remove("is-drop-target"));
    row.addEventListener("drop", async (event) => {
      event.preventDefault();
      row.classList.remove("is-drop-target");
      const sourceId = state.taskDragJobId || event.dataTransfer?.getData("text/plain");
      state.taskDragJobId = null;
      if (sourceId && sourceId !== job.id) await reorderTaskQueue(sourceId, job.id);
    });
  }
  return row;
}

function renderTaskList() {
  if (!jobPanel) return;
  const visible = (state.taskEntries || []).filter((entry) => taskFilterMatches(entry.job));
  if (jobFocusPanel) jobFocusPanel.hidden = true;
  const localStats = state.taskEntries.reduce((result, entry) => {
    const execution = taskExecutionState(entry.job);
    if (execution === "waiting") result.waiting += 1;
    else if (["running", "switching"].includes(execution)) result.running += 1;
    else if (execution === "completed") result.completed += 1;
    else if (execution === "failed") result.failed += 1;
    else if (execution === "cancelled") result.cancelled += 1;
    else if (execution === "paused") result.paused += 1;
    return result;
  }, { waiting: 0, running: 0, completed: 0, failed: 0, cancelled: 0, paused: 0 });
  const hasQueueStats = Number.isFinite(Number(state.taskStats?.total));
  const stats = hasQueueStats ? {
    total: Number(state.taskStats.total),
    waiting: Number(state.taskStats.waiting || 0),
    running: Number(state.taskStats.running || 0),
    paused: Number(state.taskStats.paused || 0),
    completed: Number(state.taskStats.completed || 0),
    failed: Number(state.taskStats.failed || 0),
    cancelled: Number(state.taskStats.cancelled || 0),
  } : { total: state.taskEntries.length, ...localStats };
  state.taskStats = stats;
  if (taskListSummary) {
    taskListSummary.textContent = `共 ${stats.total} 项 · 等待 ${stats.waiting} · 暂停 ${stats.paused} · 已完成 ${stats.completed} · 失败 ${stats.failed}`;
  }
  jobPanel.replaceChildren();
  jobPanel.className = "panel task-list";
  if (!visible.length) {
    jobPanel.classList.add("empty-state");
    jobPanel.textContent = state.taskEntries.length ? "当前筛选没有任务" : "暂无任务；提交内容后会在这里显示完整任务列表";
    updateTaskBatchToolbar();
    return;
  }
  const sections = [
    // renderTaskDisplayGroup was removed; one card
    // renderer now owns the compact and expanded task presentation.
    ["正在处理", visible.filter((entry) => taskIsRunning(entry.job))],
    ["等待处理", visible.filter((entry) => taskIsWaiting(entry.job))],
    ["已暂停", visible.filter((entry) => taskIsPaused(entry.job))],
    ["最近任务", visible.filter((entry) => taskIsTerminal(entry.job))],
  ];
  sections.forEach(([label, entries]) => {
    if (!entries.length) return;
    const section = document.createElement("section");
    section.className = "task-list-section";
    const heading = document.createElement("h2");
    heading.className = "task-list-section-title";
    heading.textContent = `${label}（${entries.length}）`;
    section.append(heading, ...entries.map((entry) => renderTaskListCard(entry)));
    jobPanel.append(section);
  });
  // Batch grouping is intentionally not used; every visible task is independently actionable.
  updateTaskBatchToolbar();
}

function updateTaskBatchToolbar() {
  const toolbar = document.querySelector("#task-batch-toolbar");
  const toggle = document.querySelector("#task-batch-toggle");
  const count = document.querySelector("#task-selection-count");
  if (toggle) {
    toggle.setAttribute("aria-pressed", String(state.taskEditing));
    toggle.textContent = state.taskEditing ? "退出编辑" : "编辑";
  }
  if (!toolbar || !count) return;
  toolbar.hidden = !state.taskEditing;
  const selected = [...state.taskSelectedIds]
    .map((id) => state.taskEntries.find((entry) => entry.job.id === id))
    .filter(Boolean);
  count.textContent = `已选 ${selected.length} 项`;
  const byState = (states) => selected.some((entry) => states.includes(taskExecutionState(entry.job)));
  const buttonStates = {
    "#task-batch-pause": byState(["waiting", "running", "switching"]),
    "#task-batch-resume": byState(["paused"]),
    "#task-batch-retry": byState(["failed", "cancelled"]),
    "#task-batch-delete": selected.length > 0,
  };
  Object.entries(buttonStates).forEach(([selector, enabled]) => {
    const button = document.querySelector(selector);
    if (button) button.disabled = !enabled || state.taskBatchBusy;
  });
}

async function reorderTaskQueue(sourceId, targetId) {
  const waiting = state.taskEntries.filter((entry) => taskIsWaiting(entry.job));
  const before = [...state.taskEntries];
  const queued = waiting.map((entry) => entry.job.id);
  if (!queued.includes(sourceId) || !queued.includes(targetId)) return;
  const sourceIndex = queued.indexOf(sourceId);
  const targetIndex = queued.indexOf(targetId);
  const insertionIndex = sourceIndex < targetIndex ? targetIndex - 1 : targetIndex;
  queued.splice(sourceIndex, 1);
  queued.splice(queued.indexOf(targetId), 0, sourceId);
  const order = new Map(queued.map((id, index) => [id, index]));
  state.taskEntries = [...state.taskEntries].sort((left, right) => {
    const leftIndex = order.get(left.job.id);
    const rightIndex = order.get(right.job.id);
    if (leftIndex == null || rightIndex == null) return 0;
    return leftIndex - rightIndex;
  });
  renderTaskList();
  try {
    await api("/api/v1/queue/move", {
      method: "POST",
      body: JSON.stringify({ job_id: sourceId, target_index: insertionIndex }),
    });
    await loadTaskList();
    showNotice("队列顺序已更新");
  } catch (error) {
    state.taskEntries = before;
    renderTaskList();
    showNotice(`顺序保存失败，已恢复原顺序：${error.message}`, true);
    await loadTaskList();
  }
}

async function promoteTask(jobId) {
  if (state.taskSwitching) return;
  try {
    await api(`/api/v1/queue/promote/${encodeURIComponent(jobId)}`, { method: "POST" });
    await loadTaskList();
    showNotice("任务已移到等待队首");
  } catch (error) {
    showNotice(`队列顺序保存失败：${error.message}`, true);
  }
}

async function switchTask(jobId, targetJobId = null) {
  if (state.taskSwitching) return;
  state.taskSwitching = true;
  renderTaskList();
  try {
    await api(`/api/v1/jobs/${encodeURIComponent(jobId)}/switch`, {
      method: "POST",
      body: JSON.stringify({ target_job_id: targetJobId }),
    });
    await loadTaskList();
    showNotice(targetJobId ? "当前任务已暂停，等待目标任务接替" : "任务已暂停；需要时可以继续处理");
    pollQueueActiveStatus();
  } catch (error) {
    showNotice(`切换失败：${error.message}`, true);
    await loadTaskList();
  } finally {
    state.taskSwitching = false;
    renderTaskList();
  }
}

async function updateTaskPriority(job) {
  if (job.state !== "queued") return;
  try {
    const updated = await api(`/api/v1/jobs/${encodeURIComponent(job.id)}/priority`, {
      method: "PATCH",
      body: JSON.stringify({ priority: Number(job.priority || 0) > 0 ? 0 : 1 }),
    });
    const entry = state.taskEntries.find((item) => item.job.id === job.id);
    if (entry) entry.job = updated;
    await loadTaskList();
    showNotice(Number(updated.priority || 0) > 0 ? "已提升为高优先级" : "已恢复普通优先级");
  } catch (error) {
    showNotice(`优先级保存失败：${error.message}`, true);
  }
}

async function runTaskBatchAction(action) {
  if (state.taskBatchBusy) return;
  const selected = [...state.taskSelectedIds]
    .map((id) => state.taskEntries.find((entry) => entry.job.id === id))
    .filter(Boolean);
  const states = {
    pause: ["queued", "acquiring", "extracting", "transcribing", "chunking", "summarizing", "archiving", "indexing"],
    resume: ["paused"],
    retry: ["failed", "cancelled"],
    delete: null,
  };
  const targets = action === "delete"
    ? selected
    : selected.filter((entry) => states[action].includes(entry.job.state));
  if (!targets.length) return;
  if (action === "delete") {
    const confirmed = await openProductConfirmDialog({
      title: "删除任务记录",
      message: `将删除选中的 ${targets.length} 条任务记录，已归档内容不会被删除。`,
      confirmLabel: "删除记录",
    });
    if (!confirmed) return;
  }
  const labels = { pause: "暂停", resume: "继续", retry: "重试", delete: "删除" };
  state.taskBatchBusy = true;
  updateTaskBatchToolbar();
  let succeeded = 0;
  let failed = 0;
  try {
    for (let index = 0; index < targets.length; index += 1) {
      const entry = targets[index];
      const progress = document.querySelector("#task-selection-count");
      if (progress) progress.textContent = `正在${labels[action]} ${index + 1}/${targets.length}…`;
      const path = action === "delete"
        ? `/api/v1/jobs/${encodeURIComponent(entry.job.id)}`
        : action === "retry"
          ? `/api/v1/jobs/${encodeURIComponent(entry.job.id)}/retry`
          : `/api/v1/jobs/${encodeURIComponent(entry.job.id)}/${action}`;
      try {
        await api(path, { method: action === "delete" ? "DELETE" : "POST" });
        succeeded += 1;
      } catch (_error) {
        failed += 1;
      }
    }
    if (action === "delete" && targets.some((entry) => entry.job.id === state.activeJobId)) {
      state.activeJobId = null;
      state.taskPollRequestSequence += 1;
    }
    state.taskSelectedIds.clear();
    await loadTaskList();
    showNotice(`已${labels[action]} ${succeeded} 项${failed ? `，失败 ${failed} 项` : ""}`, Boolean(failed));
  } finally {
    state.taskBatchBusy = false;
    updateTaskBatchToolbar();
  }
}

async function loadTaskList() {
  if (state.taskListRequest) return state.taskListRequest;
  const requestId = ++state.taskListRequestSequence;
  const viewAtStart = state.currentView;
  const request = (async () => {
    const refresh = document.querySelector("#refresh-job");
    if (refresh) {
      refresh.disabled = true;
      refresh.textContent = "刷新中…";
    }
    try {
      const [jobs, queue] = await Promise.all([
        api("/api/v1/jobs?limit=200"),
        api("/api/v1/queue"),
      ]);
      if (requestId !== state.taskListRequestSequence) return;
      state.taskEntries = jobs.map((job) => ({ job, content: taskContentFromJob(job) }));
      if (queue?.stats) state.taskStats = queue.stats;
      if (state.currentView === viewAtStart || state.currentView === "tasks") {
        if (refresh) {
          refresh.disabled = jobs.length === 0;
          refresh.title = jobs.length ? "刷新任务列表" : "暂无可刷新的任务";
        }
        renderTaskList();
        if (state.currentView !== "tasks" && state.activeJobId) {
          const active = state.taskEntries.find((entry) => entry.job.id === state.activeJobId);
          if (active && !jobFocusPanel?.hidden) renderJob(active.job, active.content.title, active.content);
        }
      }
    } catch (error) {
      if (requestId === state.taskListRequestSequence && state.currentView === viewAtStart && jobPanel) {
        jobPanel.className = "panel empty-state is-error";
        jobPanel.textContent = "读取任务失败：" + error.message;
      }
    } finally {
      if (refresh && requestId === state.taskListRequestSequence) {
        refresh.disabled = !state.activeJobId;
        refresh.textContent = "刷新";
      }
    }
  })();
  state.taskListRequest = request;
  try {
    return await request;
  } finally {
    if (state.taskListRequest === request) state.taskListRequest = null;
  }
}

async function deleteJob(jobId, trigger = null) {
  if (trigger) trigger.disabled = true;
  const confirmed = await openProductConfirmDialog({
    title: "删除任务记录",
    message: "删除后仅移除任务记录，已归档内容不会被删除。",
    confirmLabel: "删除记录",
  });
  if (!confirmed) {
    if (trigger) trigger.disabled = false;
    return;
  }
  try {
    await api(`/api/v1/jobs/${encodeURIComponent(jobId)}`, { method: "DELETE" });
    if (state.activeJobId === jobId) {
      state.activeJobId = null;
      state.taskPollRequestSequence += 1;
    }
    await loadTaskList();
    showNotice("任务记录已删除");
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    if (trigger?.isConnected) trigger.disabled = false;
  }
}
document.querySelector("#text-file").addEventListener("change", (event) => {
  handleLocalFile(event.target.files?.[0]);
});
localDropzone?.addEventListener("click", () => document.querySelector("#text-file")?.click());
localDropzone?.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    document.querySelector("#text-file")?.click();
  }
});
localDropzone?.addEventListener("dragover", (event) => {
  event.preventDefault();
  localDropzone.classList.add("is-dragging");
});
localDropzone?.addEventListener("dragleave", () => localDropzone.classList.remove("is-dragging"));
localDropzone?.addEventListener("drop", (event) => {
  event.preventDefault();
  localDropzone.classList.remove("is-dragging");
  handleLocalFile(event.dataTransfer?.files?.[0]);
});
restoreUiTheme();
updateLinkHint();
updateInputPanelSummary();
checkService().then((connected) => {
  if (connected) restoreActiveJob();
  if (connected) {
    api("/api/v1/settings").then(applyAiAskSwitch).catch(() => {});
    const contentId = new URLSearchParams(window.location.search).get("content_id");
    if (contentId) {
      loadResult(contentId).then(() => {
        if (state.activeContentId !== contentId) return;
        const url = new URL(window.location.href);
        url.searchParams.delete("content_id");
        window.history.replaceState(null, "", url);
      });
    }
  }
});
function summaryModelUsesDialog() {
  return (state.summaryConnection?.models || []).length > SUMMARY_MODEL_INLINE_LIMIT;
}

function setSummaryModelPickerOpen(open) {
  const input = document.querySelector("#summary-model");
  const toggle = document.querySelector("#summary-model-toggle");
  const options = document.querySelector("#summary-model-options");
  if (!input || !toggle || !options) return;
  const isOpen = Boolean(open && !input.disabled && !summaryModelUsesDialog());
  options.hidden = !isOpen;
  input.setAttribute("aria-expanded", String(isOpen));
  toggle.setAttribute("aria-expanded", String(isOpen));
  if (!isOpen) {
    state.summaryModelActiveIndex = -1;
    input.removeAttribute("aria-activedescendant");
  }
}

function setSummaryModelPickerEnabled(enabled, preserveOpen = false) {
  const input = document.querySelector("#summary-model");
  const toggle = document.querySelector("#summary-model-toggle");
  const usesDialog = summaryModelUsesDialog();
  if (input) {
    input.disabled = !enabled;
    if (usesDialog) {
      input.removeAttribute("role");
      input.removeAttribute("aria-autocomplete");
      input.removeAttribute("aria-controls");
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
    } else {
      input.setAttribute("role", "combobox");
      input.setAttribute("aria-autocomplete", "list");
      input.setAttribute("aria-controls", "summary-model-options");
    }
  }
  if (toggle) {
    toggle.disabled = !enabled;
    toggle.setAttribute("aria-haspopup", usesDialog ? "dialog" : "listbox");
    toggle.setAttribute("aria-controls", usesDialog ? "summary-model-dialog" : "summary-model-options");
    toggle.setAttribute("aria-label", usesDialog ? "打开模型选择窗口" : "展开模型列表");
  }
  if (!enabled && !preserveOpen) document.querySelector("#summary-model-dialog")?.close();
  if (!enabled && !preserveOpen) setSummaryModelPickerOpen(false);
  document.querySelectorAll("#summary-model-options, #summary-model-dialog-options").forEach((list) => {
    list.setAttribute("aria-busy", String(!enabled));
    list.querySelectorAll("button").forEach((button) => { button.disabled = !enabled; });
  });
  const dialog = document.querySelector("#summary-model-dialog");
  if (dialog) {
    dialog.inert = !enabled;
    dialog.setAttribute("aria-busy", String(!enabled));
  }
}

function renderSummaryModelOptions(models) {
  const options = document.querySelector("#summary-model-options");
  const input = document.querySelector("#summary-model");
  if (!options) return;
  if ((models || []).length > SUMMARY_MODEL_INLINE_LIMIT) {
    options.replaceChildren();
    options.hidden = true;
    state.summaryModelActiveIndex = -1;
    input?.removeAttribute("aria-activedescendant");
    return;
  }
  const wasOpen = !options.hidden;
  const query = input?.value.trim().toLowerCase() || "";
  const filtered = (models || []).filter((model) => {
    return !query || String(model).toLowerCase().includes(query);
  });
  options.replaceChildren();
  state.summaryModelActiveIndex = -1;
  if (!filtered.length) {
    const empty = document.createElement("div");
    empty.className = "summary-model-empty";
    empty.textContent = query
      ? "没有匹配的模型，可直接输入模型 ID。"
      : "暂无候选模型，可直接输入模型 ID；向下拖动列表可重新获取。";
    options.append(empty);
  } else {
    filtered.forEach((model, index) => {
      const option = document.createElement("button");
      option.type = "button";
      option.className = "summary-model-option";
      option.setAttribute("role", "option");
      option.dataset.model = String(model);
      option.id = `summary-model-option-${index}`;
      option.textContent = String(model);
      options.append(option);
    });
  }
  options.hidden = !wasOpen;
}

function renderSummaryModelDialogOptions() {
  const list = document.querySelector("#summary-model-dialog-options");
  const search = document.querySelector("#summary-model-dialog-search");
  const status = document.querySelector("#summary-model-page-status");
  const previous = document.querySelector("#summary-model-page-previous");
  const next = document.querySelector("#summary-model-page-next");
  if (!list || !search || !status || !previous || !next) return;
  const query = search.value.trim().toLowerCase();
  const filtered = (state.summaryConnection?.models || []).filter((model) => {
    return !query || String(model).toLowerCase().includes(query);
  });
  const pageCount = Math.max(1, Math.ceil(filtered.length / SUMMARY_MODEL_PAGE_SIZE));
  state.summaryModelPage = Math.min(Math.max(state.summaryModelPage, 0), pageCount - 1);
  const pageStart = state.summaryModelPage * SUMMARY_MODEL_PAGE_SIZE;
  const selectedModel = document.querySelector("#summary-model")?.value.trim() || "";
  list.replaceChildren();
  if (!filtered.length) {
    const empty = document.createElement("div");
    empty.className = "summary-model-dialog-empty";
    empty.textContent = "没有匹配的模型";
    list.append(empty);
  } else {
    filtered.slice(pageStart, pageStart + SUMMARY_MODEL_PAGE_SIZE).forEach((model) => {
      const option = document.createElement("button");
      option.type = "button";
      option.className = "summary-model-dialog-option";
      option.setAttribute("role", "option");
      option.setAttribute("aria-selected", String(String(model) === selectedModel));
      option.dataset.model = String(model);
      option.textContent = String(model);
      list.append(option);
    });
  }
  status.textContent = `第 ${state.summaryModelPage + 1} / ${pageCount} 页 · 共 ${filtered.length} 个模型`;
  previous.disabled = state.summaryModelPage === 0;
  next.disabled = state.summaryModelPage >= pageCount - 1;
}

function openSummaryModelDialog() {
  const dialog = document.querySelector("#summary-model-dialog");
  const search = document.querySelector("#summary-model-dialog-search");
  if (!dialog || !search || !summaryModelUsesDialog()) return;
  state.summaryModelPage = 0;
  search.value = "";
  renderSummaryModelDialogOptions();
  if (!dialog.open) dialog.showModal();
  document.querySelector("#summary-model-toggle")?.setAttribute("aria-expanded", "true");
  search.focus();
}

function bindSummaryModelPullToRefresh(container) {
  if (!container) return;
  container.addEventListener("pointerdown", (event) => {
    if ((event.pointerType === "mouse" && event.button !== 0) || container.scrollTop > 0) return;
    if (state.summaryConnection?.status === "discovering") return;
    state.summaryModelPullGesture = {
      container,
      pointerId: event.pointerId,
      startY: event.clientY,
      ready: false,
    };
  }, { passive: true });
}

document.addEventListener("pointermove", (event) => {
  const gesture = state.summaryModelPullGesture;
  if (!gesture || gesture.pointerId !== event.pointerId) return;
  if (gesture.container.scrollTop > 0 || event.clientY < gesture.startY) {
    gesture.container.classList.remove("is-pull-refresh-ready");
    state.summaryModelPullGesture = null;
    return;
  }
  const ready = event.clientY - gesture.startY >= SUMMARY_MODEL_PULL_REFRESH_THRESHOLD;
  gesture.container.classList.toggle("is-pull-refresh-ready", ready);
  gesture.ready = ready;
  if (ready && event.cancelable) event.preventDefault();
}, { passive: false });

document.addEventListener("pointerup", (event) => {
  const gesture = state.summaryModelPullGesture;
  if (!gesture || gesture.pointerId !== event.pointerId) return;
  const shouldRefresh = gesture.ready
    && gesture.container.scrollTop === 0
    && event.clientY - gesture.startY >= SUMMARY_MODEL_PULL_REFRESH_THRESHOLD;
  gesture.container.classList.remove("is-pull-refresh-ready");
  state.summaryModelPullGesture = null;
  if (shouldRefresh) {
    state.summaryModelSuppressClickUntil = Date.now() + 500;
    void refreshSummaryModelsFromGesture();
  }
});

document.addEventListener("pointercancel", (event) => {
  const gesture = state.summaryModelPullGesture;
  if (!gesture || gesture.pointerId !== event.pointerId) return;
  gesture.container.classList.remove("is-pull-refresh-ready");
  state.summaryModelPullGesture = null;
});

async function refreshSummaryModelsFromGesture() {
  const dialog = document.querySelector("#summary-model-dialog");
  const search = document.querySelector("#summary-model-dialog-search");
  const options = document.querySelector("#summary-model-options");
  const wasDialogOpen = Boolean(dialog?.open);
  const wasInlineOpen = Boolean(options && !options.hidden);
  const previousSearch = search?.value || "";
  const previousPage = state.summaryModelPage;
  const fingerprint = summaryDiscoveryFingerprint();
  await discoverSummaryModels({ preservePicker: true });
  if (fingerprint !== summaryDiscoveryFingerprint()) return;
  const toggle = document.querySelector("#summary-model-toggle");
  if (toggle?.disabled || (!wasDialogOpen && !wasInlineOpen)) return;
  if (summaryModelUsesDialog()) {
    if (search) search.value = previousSearch;
    state.summaryModelPage = previousPage;
    renderSummaryModelDialogOptions();
    if (dialog && !dialog.open) dialog.showModal();
    toggle?.setAttribute("aria-expanded", "true");
  } else {
    if (dialog?.open) dialog.close();
    setSummaryModelPickerOpen(true);
  }
}

function setSummaryModelActiveIndex(index) {
  const options = document.querySelector("#summary-model-options");
  const input = document.querySelector("#summary-model");
  if (!options || !input) return;
  const items = [...options.querySelectorAll(".summary-model-option")];
  if (!items.length) {
    state.summaryModelActiveIndex = -1;
    input.removeAttribute("aria-activedescendant");
    return;
  }
  const nextIndex = (index + items.length) % items.length;
  state.summaryModelActiveIndex = nextIndex;
  items.forEach((item, itemIndex) => {
    const active = itemIndex === nextIndex;
    item.classList.toggle("is-active", active);
    item.setAttribute("aria-selected", String(active));
  });
  input.setAttribute("aria-activedescendant", items[nextIndex].id);
  const activeItem = items[nextIndex];
  if (activeItem.offsetTop < options.scrollTop) {
    options.scrollTop = activeItem.offsetTop;
  } else if (activeItem.offsetTop + activeItem.offsetHeight > options.scrollTop + options.clientHeight) {
    options.scrollTop = activeItem.offsetTop + activeItem.offsetHeight - options.clientHeight;
  }
}

function selectSummaryModel(model) {
  const input = document.querySelector("#summary-model");
  if (!input) return;
  document.querySelector("#summary-model-dialog")?.close();
  input.value = String(model);
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
  input.focus();
  setSummaryModelPickerOpen(false);
  void saveSummarySettings();
}

function handleSummaryModelInput() {
  renderSummaryModelOptions(state.summaryConnection?.models || []);
  handleSummaryModelChange();
  const options = document.querySelector("#summary-model-options");
  if (options && !options.hidden) setSummaryModelPickerOpen(true);
}

function handleSummaryModelKeydown(event) {
  const input = event.currentTarget;
  const options = document.querySelector("#summary-model-options");
  if (!options || input.disabled) return;
  if (summaryModelUsesDialog()) return;
  const items = [...options.querySelectorAll(".summary-model-option")];
  if (event.key === "ArrowDown") {
    event.preventDefault();
    if (options.hidden) setSummaryModelPickerOpen(true);
    setSummaryModelActiveIndex(state.summaryModelActiveIndex + 1);
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    if (options.hidden) setSummaryModelPickerOpen(true);
    setSummaryModelActiveIndex(
      state.summaryModelActiveIndex < 0 ? items.length - 1 : state.summaryModelActiveIndex - 1,
    );
  } else if (event.key === "Enter" && !options.hidden && state.summaryModelActiveIndex >= 0) {
    event.preventDefault();
    selectSummaryModel(items[state.summaryModelActiveIndex].dataset.model);
  } else if (event.key === "Escape") {
    setSummaryModelPickerOpen(false);
  }
}

function summaryDiscoveryFingerprint() {
  const identity = currentSummaryIdentity();
  const enteredKey = document.querySelector("#summary-api-key")?.value.trim() || "";
  const keyPart = enteredKey || (summaryIdentityMatchesSaved() ? "<saved-key>" : "");
  return [identity.provider, identity.endpoint, identity.mode, keyPart].join("\u0000");
}

async function summaryModelCatalogFingerprint(identity) {
  if (!window.crypto?.subtle) return "";
  const value = [identity.provider, identity.endpoint, identity.mode].join("\u0000");
  const digest = await window.crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function loadSummaryModelCatalog(identity) {
  try {
    const fingerprint = await summaryModelCatalogFingerprint(identity);
    if (!fingerprint) return [];
    const saved = JSON.parse(window.localStorage.getItem(SUMMARY_MODEL_CATALOG_STORAGE_KEY) || "null");
    if (saved?.fingerprint !== fingerprint || !Array.isArray(saved.models)) return [];
    return saved.models.filter((model) => typeof model === "string");
  } catch (_error) {
    return [];
  }
}

async function saveSummaryModelCatalog(models, requestFingerprint, generation, supported) {
  if (!supported) return;
  try {
    const fingerprint = await summaryModelCatalogFingerprint(currentSummaryIdentity());
    if (
      !fingerprint
      || generation !== state.summaryConnection?.generation
      || requestFingerprint !== summaryDiscoveryFingerprint()
    ) return;
    window.localStorage.setItem(SUMMARY_MODEL_CATALOG_STORAGE_KEY, JSON.stringify({
      fingerprint,
      models: (models || []).filter((model) => typeof model === "string"),
    }));
  } catch (_error) {}
}

async function ensureSummaryModelsCurrent() {
  if (state.summaryConnection?.discoveryFingerprint === summaryDiscoveryFingerprint()) return true;
  const discovered = await discoverSummaryModels();
  const endpoint = document.querySelector("#summary-api-url")?.value.trim() || "";
  const apiMode = document.querySelector("#summary-api-mode")?.value || "chat_completions";
  const canRetry = summaryApiKeyAvailable() && !summaryEndpointError(endpoint, apiMode);
  return discovered || Boolean(state.summaryConnection?.models?.length) || canRetry;
}

function summaryTestFingerprint() {
  return [
    summaryDiscoveryFingerprint(),
    document.querySelector("#summary-model")?.value.trim() || "",
  ].join("\u0000");
}

function scheduleSummaryModelDiscovery() {
  window.clearTimeout(state.summaryDiscoveryTimer);
  state.summaryDiscoveryTimer = window.setTimeout(() => {
    state.summaryDiscoveryTimer = null;
    void discoverSummaryModels();
  }, 700);
}

function invalidateSummaryConnection() {
  window.clearTimeout(state.summaryDiscoveryTimer);
  const generation = (state.summaryConnection?.generation || 0) + 1;
  const hasEndpoint = Boolean(document.querySelector("#summary-api-url")?.value.trim());
  state.summaryConnection = {
    status: hasEndpoint ? "editing" : "unconfigured",
    models: [],
    generation,
    discoveryFingerprint: "",
    testFingerprint: "",
    validationToken: null,
  };
  showSummaryValidation("");
  renderSummaryModelOptions([]);
  const model = document.querySelector("#summary-model");
  if (model) {
    // Keep a user's model draft while invalidating only the fetched list and
    // validation state.  The old saved configuration remains active until a
    // new configuration is explicitly saved.
    setSummaryModelPickerEnabled(false);
  }
  renderSummaryStatus(state.settings, true);
}

function handleSummaryModelChange() {
  const model = document.querySelector("#summary-model")?.value.trim() || "";
  if (model && state.summaryConnection?.discoveryFingerprint === summaryDiscoveryFingerprint()) {
    state.summaryConnection.status = "model_selected";
  } else if (state.summaryConnection?.discoveryFingerprint === summaryDiscoveryFingerprint()) {
    state.summaryConnection.status = "awaiting_model";
  } else {
    state.summaryConnection.status = model ? "model_selected" : "editing";
  }
  renderSummaryStatus(state.settings, true);
}

async function discoverSummaryModels({ preservePicker = false } = {}) {
  window.clearTimeout(state.summaryDiscoveryTimer);
  state.summaryDiscoveryTimer = null;
  const endpoint = document.querySelector("#summary-api-url")?.value.trim() || "";
  const apiMode = document.querySelector("#summary-api-mode")?.value || "chat_completions";
  const endpointError = summaryEndpointError(endpoint, apiMode);
  if (endpointError) {
    state.summaryConnection.status = "input_invalid";
    showSummaryValidation(endpointError);
    renderSummaryStatus(state.settings, true);
    return false;
  }
  if (!summaryApiKeyAvailable()) {
    state.summaryConnection.status = "input_invalid";
    showSummaryValidation("请先填写 API 密钥；已切换地址后不能复用旧密钥。");
    renderSummaryStatus(state.settings, true);
    return false;
  }
  const generation = (state.summaryConnection?.generation || 0) + 1;
  const fingerprint = summaryDiscoveryFingerprint();
  const cachedModels = state.summaryConnection?.models || [];
  state.summaryConnection = {
    status: "discovering",
    models: cachedModels,
    generation,
    discoveryFingerprint: "",
    testFingerprint: "",
    validationToken: null,
  };
  renderSummaryModelOptions(cachedModels);
  setSummaryModelPickerEnabled(false, preservePicker);
  renderSummaryStatus(state.settings, true);
  showSummaryValidation("正在连接并获取当前服务的模型…");
  try {
    const result = await api("/api/v1/settings/summary/models", {
      method: "POST",
      body: JSON.stringify(summaryConnectionPayload(false)),
    });
    if (generation !== state.summaryConnection?.generation || fingerprint !== summaryDiscoveryFingerprint()) {
      return false;
    }
    const models = result.models_supported === false
      ? cachedModels
      : (result.models || []);
    state.summaryConnection = {
      status: "awaiting_model",
      models,
      generation,
      discoveryFingerprint: fingerprint,
      testFingerprint: "",
      validationToken: null,
    };
    renderSummaryModelOptions(models);
    if (document.querySelector("#summary-model-dialog")?.open) renderSummaryModelDialogOptions();
    setSummaryModelPickerEnabled(true);
    showSummaryValidation(result.models_supported === false
      ? (cachedModels.length
        ? "服务暂未提供模型列表，继续显示上次获取的候选模型。"
        : "连接成功，但当前服务不提供模型列表，请手动填写模型 ID。")
      : (result.message || "连接成功，请选择总结模型。"));
    renderSummaryStatus(state.settings, true);
    await saveSummaryModelCatalog(models, fingerprint, generation, result.models_supported !== false);
    return generation === state.summaryConnection?.generation && fingerprint === summaryDiscoveryFingerprint();
  } catch (error) {
    if (generation !== state.summaryConnection?.generation || fingerprint !== summaryDiscoveryFingerprint()) {
      return false;
    }
    state.summaryConnection.status = "discovery_failed";
    state.summaryConnection.discoveryFingerprint = "";
    renderSummaryModelOptions(cachedModels);
    const canRetry = summaryApiKeyAvailable() && !summaryEndpointError(endpoint, apiMode);
    setSummaryModelPickerEnabled(cachedModels.length > 0 || canRetry);
    showSummaryValidation(`总结模型列表获取失败：${error.message || "请检查接口地址和 API 密钥"}`);
    renderSummaryStatus(state.settings, true);
    return false;
  }
}

// New library controls are attached after the DOM and refactored handlers
// have been initialized. Existing intake/settings listeners remain unchanged.
allTagsButton?.addEventListener("click", () => {
  state.activeTagId = "";
  state.activeTagName = "";
  state.activeFavoriteFolderId = "";
  state.showingTrash = false;
  invalidateReturnContext();
  renderTagNavigation();
  loadHistory();
});
createTagButton?.addEventListener("click", createTag);
document.querySelector("#manage-tags-button")?.addEventListener("click", () => {
  state.tagManagementMode = !state.tagManagementMode;
  state.tagRenamingId = null;
  renderTagNavigation();
});
document.querySelector("#manage-favorite-folders")?.addEventListener("click", () => {
  state.favoriteManagementMode = !state.favoriteManagementMode;
  state.favoriteRenamingId = null;
  renderFavoriteFolders();
});
document.querySelector("#result-prev")?.addEventListener("click", () => navigateResult(-1));
document.querySelector("#result-next")?.addEventListener("click", () => navigateResult(1));
document.querySelector("#result-footer-prev")?.addEventListener("click", () => navigateResult(-1));
document.querySelector("#result-footer-next")?.addEventListener("click", () => navigateResult(1));
document.querySelector("#result-footer-back")?.addEventListener("click", returnToResultParent);
document.querySelector("#result-quick-select")?.addEventListener("change", (event) => {
  if (event.target.value) loadResult(event.target.value, { preserveContext: true });
});
window.addEventListener("keydown", (event) => {
  if (state.currentView !== "result" || event.target.matches("input, textarea, select")) return;
  if (event.altKey && event.key === "ArrowLeft") navigateResult(-1);
  if (event.altKey && event.key === "ArrowRight") navigateResult(1);
});
tagScrollLeft?.addEventListener("click", () => tagNavList?.scrollBy({ left: -240, behavior: "smooth" }));
tagScrollRight?.addEventListener("click", () => tagNavList?.scrollBy({ left: 240, behavior: "smooth" }));
tagNavList?.addEventListener("scroll", updateTagScrollButtons);
let tagDragStart = null;
tagNavList?.addEventListener("pointerdown", (event) => {
  tagDragStart = { x: event.clientX, scrollLeft: tagNavList.scrollLeft };
  tagNavList.classList.add("is-dragging");
  tagNavList.setPointerCapture?.(event.pointerId);
});
tagNavList?.addEventListener("pointermove", (event) => {
  if (!tagDragStart) return;
  tagNavList.scrollLeft = tagDragStart.scrollLeft - (event.clientX - tagDragStart.x);
});
tagNavList?.addEventListener("pointerup", () => {
  tagDragStart = null;
  tagNavList.classList.remove("is-dragging");
});
tagNavList?.addEventListener("pointercancel", () => {
  tagDragStart = null;
  tagNavList.classList.remove("is-dragging");
});

document.querySelector("#task-batch-toggle")?.addEventListener("click", () => {
  state.taskEditing = !state.taskEditing;
  state.taskSelectionMode = state.taskEditing;
  if (!state.taskEditing) state.taskSelectedIds.clear();
  renderTaskList();
  updateTaskBatchToolbar();
});
document.querySelector("#task-batch-pause")?.addEventListener("click", () => runTaskBatchAction("pause"));
document.querySelector("#task-batch-resume")?.addEventListener("click", () => runTaskBatchAction("resume"));
document.querySelector("#task-batch-retry")?.addEventListener("click", () => runTaskBatchAction("retry"));
document.querySelector("#task-batch-delete")?.addEventListener("click", () => runTaskBatchAction("delete"));
document.querySelector("#batch-detail-back")?.addEventListener("click", () => {
  const context = state.batchReturnContext;
  const source = context?.sourceView;
  state.batchReturnContext = null;
  if (source === "history" && context) {
    state.returnContext = context;
    showView("history", { preserveReturnContext: true });
  } else if (source === "tasks") {
    showView("tasks");
  } else {
    showView("history");
  }
});
updateReturnControls();

/**
 * 壳的返回键先问这里：能在产品内部回退一级就别关掉 App。
 *
 * 返回 "handled" 表示已回退一级；返回 "root" 表示当前已在根视图，
 * 由壳决定要不要提示「再按一次退出」。
 */
window.__kbBack = function () {
  const view = state.currentView || "intake";
  if (view === "settings") {
    const target = state.settingsReturnView || "intake";
    const preserve = target === "history" && state.returnContext?.sourceView === "history";
    showView(target, { preserveReturnContext: preserve });
    return "handled";
  }
  if (view === "result") {
    returnToResultParent();
    return "handled";
  }
  if (view === "batch-detail") {
    const back = document.querySelector("#batch-detail-back");
    if (back) {
      back.click();
      return "handled";
    }
  }
  return "root";
};


/* -------------------------------------------------------------------------
   11-10 R1 · 88px 图标 rail 的 Tooltip 与文字展开态（设计稿图六）
   桌面：mouseenter / focus 显示，mouseleave / blur 收起；
   触屏：touchstart 长按 >=450ms 显示，touchend / touchcancel / touchmove 收起。
   只读取 data-tooltip，不改既有 showView / navButtons 逻辑。
   ------------------------------------------------------------------------- */
(function initRailTooltip() {
  const tip = document.querySelector("#ui-tooltip");
  if (!tip) return;
  const LONG_PRESS_MS = 450;
  let pressTimer = null;
  let touchStart = null;
  let current = null;

  const prefersReducedMotion = () =>
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function place(anchor) {
    const box = anchor.getBoundingClientRect();
    tip.hidden = false;
    tip.classList.toggle("is-reduced", prefersReducedMotion());
    const tipBox = tip.getBoundingClientRect();
    const top = Math.max(8, Math.min(
      window.innerHeight - tipBox.height - 8,
      box.top + box.height / 2 - tipBox.height / 2,
    ));
    tip.style.top = `${top + window.scrollY}px`;
    tip.style.left = `${box.right + 10 + window.scrollX}px`;
  }

  function show(anchor) {
    const label = anchor.dataset.tooltip || anchor.getAttribute("aria-label");
    if (!label) return;
    if (current && current !== anchor) hide();
    current = anchor;
    tip.textContent = label;
    place(anchor);
  }

  function hide() {
    current = null;
    tip.hidden = true;
  }

  document.addEventListener("pointerover", (event) => {
    if (event.pointerType === "touch") return;
    const anchor = event.target.closest?.("[data-tooltip]");
    if (anchor) show(anchor);
  });
  document.addEventListener("pointerout", (event) => {
    if (event.pointerType === "touch") return;
    const anchor = event.target.closest?.("[data-tooltip]");
    if (anchor && !anchor.contains(event.relatedTarget)) hide();
  });
  document.addEventListener("focusin", (event) => {
    const anchor = event.target.closest?.("[data-tooltip]");
    if (anchor) show(anchor);
  });
  document.addEventListener("focusout", (event) => {
    if (event.target.closest?.("[data-tooltip]")) hide();
  });
  document.addEventListener("touchstart", (event) => {
    const anchor = event.target.closest?.("[data-tooltip]");
    if (!anchor) return;
    touchStart = { x: event.touches[0].clientX, y: event.touches[0].clientY };
    window.clearTimeout(pressTimer);
    pressTimer = window.setTimeout(() => show(anchor), LONG_PRESS_MS);
  }, { passive: true });
  const cancelPress = () => { window.clearTimeout(pressTimer); hide(); };
  document.addEventListener("touchend", () => {
    window.clearTimeout(pressTimer);
    if (current) window.setTimeout(hide, 1200);
  }, { passive: true });
  document.addEventListener("touchcancel", cancelPress, { passive: true });
  document.addEventListener("touchmove", (event) => {
    if (!touchStart) return;
    const dx = Math.abs(event.touches[0].clientX - touchStart.x);
    const dy = Math.abs(event.touches[0].clientY - touchStart.y);
    if (dx > 8 || dy > 8) cancelPress();
  }, { passive: true });
  window.addEventListener("scroll", hide, { passive: true });
  window.addEventListener("resize", hide);

  const toggle = document.querySelector("#rail-expand-toggle");
  if (toggle) {
    const apply = (expanded) => {
      document.documentElement.classList.toggle("sidebar-expanded", expanded);
      toggle.setAttribute("aria-pressed", String(expanded));
      toggle.setAttribute("aria-label", expanded ? "收起侧栏名称" : "展开侧栏名称");
      toggle.dataset.tooltip = expanded ? "收起侧栏名称" : "展开侧栏名称";
      hide();
    };
    let saved = false;
    try { saved = window.localStorage.getItem("kb-rail-expanded") === "1"; } catch (_error) {}
    if (saved) apply(true);
    toggle.addEventListener("click", () => {
      const next = !document.documentElement.classList.contains("sidebar-expanded");
      apply(next);
      try { window.localStorage.setItem("kb-rail-expanded", next ? "1" : "0"); } catch (_error) {}
    });
  }
})();


/* -------------------------------------------------------------------------
   11-10 R4 · 问答范围侧栏（设计稿图四）
   D3 保守实现：勾选镜像只同步既有 select 的 option.selected，
   绝不修改 #ask-scope-kind 取值，也绝不改动 currentAskScope() 的请求字段。
   选项来自 renderAskScopeOptions() 填充的既有 select，用 MutationObserver
   保持同步，不新增数据源、不新增请求参数。
   ------------------------------------------------------------------------- */
(function initAskScopePanel() {
  const panel = document.querySelector("#ask-scope-panel");
  const tagSelect = document.querySelector("#ask-tag-ids");
  const folderSelect = document.querySelector("#ask-folder-ids");
  if (!panel || !tagSelect || !folderSelect) return;

  const tagBox = document.querySelector("#ask-tag-checks");
  const folderBox = document.querySelector("#ask-folder-checks");
  const empty = document.querySelector("#ask-scope-empty");
  const summary = document.querySelector("#ask-scope-summary");
  const tabs = [...panel.querySelectorAll("[data-ask-scope-tab]")];
  let activeTab = "all";

  function buildChecks(select, box, group) {
    if (!box) return;
    const selected = new Set([...select.selectedOptions].map((o) => o.value));
    box.replaceChildren();
    if (!select.options.length) {
      const note = document.createElement("p");
      note.className = "ask-scope-check-empty";
      note.textContent = group === "tag" ? "暂无标签" : "暂无收藏夹";
      box.append(note);
      return;
    }
    [...select.options].forEach((option) => {
      const label = document.createElement("label");
      label.className = "ask-scope-check";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = option.value;
      input.checked = selected.has(option.value);
      input.dataset.askScopeGroup = group;
      input.addEventListener("change", () => {
        option.selected = input.checked;
        updateSummary();
      });
      const text = document.createElement("span");
      text.textContent = option.textContent;
      label.append(input, text);
      box.append(label);
    });
  }

  function rebuild() {
    buildChecks(tagSelect, tagBox, "tag");
    buildChecks(folderSelect, folderBox, "folder");
    updateSummary();
  }

  function updateSummary() {
    const tagCount = tagSelect.selectedOptions.length;
    const folderCount = folderSelect.selectedOptions.length;
    const picked = activeTab === "tag" ? tagCount : (activeTab === "folder" ? folderCount : 0);
    const label = activeTab === "tag" ? "标签" : "收藏夹";
    if (summary) {
      summary.textContent = activeTab === "all"
        ? `全库 ${Number(state.libraryTotal ?? 0)} 条内容`
        : `已选 ${picked} 个${label} · 检索口径不变`;
    }
    if (empty) empty.hidden = activeTab !== "all";
    if (tagBox) tagBox.hidden = activeTab !== "tag";
    if (folderBox) folderBox.hidden = activeTab !== "folder";
  }

  function setTab(tab) {
    activeTab = tab;
    tabs.forEach((button) => {
      const active = button.dataset.askScopeTab === tab;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    if (tab === "all") {
      [...tagSelect.options].forEach((o) => { o.selected = false; });
      [...folderSelect.options].forEach((o) => { o.selected = false; });
      rebuild();
    }
    updateSummary();
  }

  tabs.forEach((button) => button.addEventListener("click", () => setTab(button.dataset.askScopeTab)));

  const apply = document.querySelector("#ask-scope-apply");
  if (apply) {
    apply.addEventListener("click", () => {
      // 复用既有刷新逻辑，不发送任何新请求、不改 currentAskScope() 字段
      if (typeof updateAskScopeFields === "function") updateAskScopeFields();
      if (typeof showNotice === "function") showNotice("范围已应用");
      updateSummary();
    });
  }

  if (typeof MutationObserver === "function") {
    const observer = new MutationObserver(rebuild);
    [tagSelect, folderSelect].forEach((select) => {
      observer.observe(select, { childList: true });
    });
  }
  rebuild();
})();


/* -------------------------------------------------------------------------
   11-10 R5 · 内容详情快捷栏与深色来源卡（设计稿图七、八）
   D5：快捷栏数据源 = 当前知识库列表 state.libraryEntries，不新增请求、不新增数据实体。
   来源卡只呈现 state.activeContentSnapshot 已有字段，整卡点击打开 canonical_url。
   ------------------------------------------------------------------------- */
function fillResultSourceCard(content) {
  const card = document.querySelector("#result-outline-source");
  if (!card) return;
  const setText = (selector, value) => {
    const node = document.querySelector(selector);
    if (node) node.textContent = value || "";
  };
  card.href = content?.canonical_url || "#";
  setText("#result-source-title", content?.title || "未命名内容");
  setText("#result-source-badge", content?.platform ? platformLabel(content.platform) : "");
  const bits = [];
  if (content?.published_at) bits.push(formatTimestamp(content.published_at));
  if (content?.duration_seconds) bits.push(formatDuration(content.duration_seconds));
  setText("#result-source-time", bits.join(" · "));
  const thumb = document.querySelector("#result-source-thumb");
  if (thumb) {
    thumb.replaceChildren();
    if (content?.thumbnail_url) {
      const image = document.createElement("img");
      image.src = content.thumbnail_url;
      image.alt = "";
      image.loading = "lazy";
      image.referrerPolicy = "no-referrer";
      image.addEventListener("error", () => thumb.replaceChildren());
      thumb.append(image);
    }
  }
}

function renderResultQuickRail() {
  const list = document.querySelector("#result-quick-list");
  if (!list) return;
  const search = document.querySelector("#result-quick-search");
  const query = String(search?.value || "").trim().toLowerCase();
  const entries = (state.libraryEntries || []).filter((entry) => entry?.content?.id);
  const visible = query
    ? entries.filter((entry) => [entry.content.title, entry.content.author, ...(entry.content.tag_names || [])]
        .filter(Boolean).some((value) => String(value).toLowerCase().includes(query)))
    : entries;
  // 11-10 R9：从 ?content_id= 直达或刷新结果页时，知识库列表尚未进入 state，
  // 250px 快捷栏会一直显示空态。这里只补一次默认全库列表，不覆盖用户已有的筛选结果。
  if (!query && !entries.length && !state.quickRailLoaded && !state.quickRailLoading) {
    state.quickRailLoading = true;
    state.quickRailLoaded = true;
    fetch(`${API_ORIGIN}/api/v1/history`)
      .then((resp) => (resp.ok ? resp.json() : []))
      .then((items) => {
        if (Array.isArray(items) && items.length) {
          state.libraryEntries = items.filter((item) => item?.content?.id);
          renderResultQuickRail();
        }
      })
      .catch(() => {})
      .finally(() => { state.quickRailLoading = false; });
  }
  list.replaceChildren();
  if (!visible.length) {
    const empty = document.createElement("p");
    empty.className = "result-quick-empty";
    empty.textContent = query ? "没有匹配的内容" : "暂无归档内容";
    list.append(empty);
    return;
  }
  visible.slice(0, 60).forEach((entry) => {
    const content = entry.content;
    const item = document.createElement("button");
    item.type = "button";
    item.className = "result-quick-item";
    item.dataset.contentId = content.id;
    item.setAttribute("role", "listitem");
    item.classList.toggle("is-active", content.id === state.activeContentId);
    const cover = createSourceCover({
      title: content.title,
      thumbnail: entry.job?.thumbnail_url || content.thumbnail_url,
      platform: content.platform,
      className: "source-cover result-quick-cover",
    });
    const body = document.createElement("span");
    body.className = "result-quick-body";
    const title = document.createElement("span");
    title.className = "result-quick-title";
    title.textContent = content.title || "未命名内容";
    title.title = title.textContent;
    const meta = document.createElement("span");
    meta.className = "result-quick-meta";
    const tag = document.createElement("span");
    tag.className = "result-quick-tag";
    tag.textContent = (content.tag_names || [])[0] || "";
    const duration = document.createElement("span");
    duration.textContent = content.duration_seconds ? formatDuration(content.duration_seconds) : "";
    meta.append(tag, duration);
    body.append(title, meta);
    item.append(cover, body);
    item.addEventListener("click", () => {
      if (state.currentView === "history") captureReturnContext(content.id);
      loadResult(content.id);
    });
    list.append(item);
  });
}

(function initResultQuickRail() {
  const back = document.querySelector("#result-quick-back");
  if (back) back.addEventListener("click", () => showView("history"));
  const search = document.querySelector("#result-quick-search");
  if (search) search.addEventListener("input", renderResultQuickRail);
  renderResultQuickRail();
})();


/* -------------------------------------------------------------------------
   11-10 R6 · 结果页顶部图标工具栏（设计稿图七、八；D6）
   四个图标接的都是既有能力：复制正文 / 单条导出 / 回收站 DELETE / 更多菜单。
   R7 会把 handleResultToolbarExport() 替换为「打开导出浮层」。
   ------------------------------------------------------------------------- */
function handleResultToolbarExport() {
  if (typeof openExportPopover === "function") openExportPopover();
}

(function initResultToolbar() {
  const toolbar = document.querySelector("#result-toolbar");
  if (!toolbar) return;
  const menu = document.querySelector("#result-toolbar-menu");
  const more = document.querySelector("#result-toolbar-more");
  const notify = (message, isError = false) => {
    if (typeof showNotice === "function") showNotice(message, isError);
  };

  const copy = document.querySelector("#result-toolbar-copy");
  if (copy) {
    copy.addEventListener("click", async () => {
      const body = document.querySelector("#result-markdown");
      const text = body ? body.innerText : "";
      if (!text.trim()) { notify("当前没有可复制的正文", true); return; }
      try {
        await navigator.clipboard.writeText(text);
        notify("正文已复制");
      } catch (_error) {
        notify("复制失败", true);
      }
    });
  }

  const exportButton = document.querySelector("#result-toolbar-export");
  if (exportButton) exportButton.addEventListener("click", () => handleResultToolbarExport());

  const remove = document.querySelector("#result-toolbar-delete");
  if (remove) {
    remove.addEventListener("click", async () => {
      const content = state.activeContentSnapshot;
      if (!content?.id) return;
      // 与知识库卡片「移入回收站」同源：同一接口、同样的二次确认。
      if (!window.confirm(`确认将“${content.title || "该内容"}”移入可恢复回收站？`)) return;
      try {
        await api(`/api/v1/contents/${encodeURIComponent(content.id)}`, { method: "DELETE" });
        notify("内容已移入回收站");
        await loadHistory();
        showView("history");
      } catch (error) {
        notify(error.message, true);
      }
    });
  }

  const toggleMenu = (open) => {
    if (!menu) return;
    menu.hidden = !open;
    if (more) more.setAttribute("aria-expanded", String(open));
  };
  if (more) more.addEventListener("click", () => toggleMenu(!!menu && menu.hidden));
  document.addEventListener("click", (event) => {
    if (menu && !menu.hidden && !menu.contains(event.target) && !(more && more.contains(event.target))) {
      toggleMenu(false);
    }
  });

  const regenerate = () => {
    toggleMenu(false);
    if (!state.activeContentId) return;
    // 传 null：resummarizeContent 会 disable triggerButton，常驻按钮不能被永久禁用。
    resummarizeContent(state.activeContentId, null);
  };
  const moreRegenerate = document.querySelector("#result-more-regenerate");
  if (moreRegenerate) moreRegenerate.addEventListener("click", regenerate);
  const moreBack = document.querySelector("#result-more-back");
  if (moreBack) moreBack.addEventListener("click", () => { toggleMenu(false); showView("history"); });
  const outlineRegenerate = document.querySelector("#result-outline-regenerate");
  if (outlineRegenerate) outlineRegenerate.addEventListener("click", regenerate);
})();


/* -------------------------------------------------------------------------
   11-10 R7 · 导出浮层（设计稿图八；D1 / D2）
   格式四项与后端 main.py / schemas.py 白名单同源；位置两项中的「归档目录」
   由后端受控写入该内容已有的 archive_path，不开放自定义本地路径。
   单条导出、批量导出、工具栏导出共用 currentExportFormat()。
   ------------------------------------------------------------------------- */
function syncExportPopoverHint() {
  const popover = document.querySelector("#export-popover");
  const hint = popover?.querySelector(".export-popover-hint");
  if (!hint) return;
  const archived = currentExportDestination() === "archive";
  const archivePath = state.activeArchivePath || "";
  hint.textContent = archived
    ? (archivePath ? `写入归档目录：${archivePath}` : "写入该内容的产品归档目录")
    : "下载到浏览器配置的下载文件夹";
}

function openExportPopover() {
  const popover = document.querySelector("#export-popover");
  const trigger = document.querySelector("#result-toolbar-export");
  if (!popover) return;
  syncExportPopoverHint();
  popover.hidden = false;
  if (trigger) {
    trigger.classList.add("is-active");
    trigger.setAttribute("aria-expanded", "true");
  }
}

function closeExportPopover() {
  const popover = document.querySelector("#export-popover");
  const trigger = document.querySelector("#result-toolbar-export");
  if (!popover) return;
  popover.hidden = true;
  if (trigger) {
    trigger.classList.remove("is-active");
    trigger.setAttribute("aria-expanded", "false");
  }
}

(function initExportPopover() {
  const popover = document.querySelector("#export-popover");
  const trigger = document.querySelector("#result-toolbar-export");
  if (!popover || !trigger) return;
  const cancel = document.querySelector("#export-popover-cancel");
  const close = document.querySelector("#export-popover-close");
  const submit = document.querySelector("#export-popover-submit");

  popover.querySelectorAll('input[name="export-destination"]').forEach((input) => {
    input.addEventListener("change", syncExportPopoverHint);
  });
  if (cancel) cancel.addEventListener("click", closeExportPopover);
  if (close) close.addEventListener("click", closeExportPopover);
  document.addEventListener("click", (event) => {
    if (!popover.hidden && !popover.contains(event.target) && !trigger.contains(event.target)) {
      closeExportPopover();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !popover.hidden) closeExportPopover();
  });
  if (submit) {
    submit.addEventListener("click", async () => {
      if (!state.activeContentId) {
        showNotice("请先选择要导出的内容", true);
        return;
      }
      submit.disabled = true;
      try {
        await exportSingleHistory(state.activeContentId);
        closeExportPopover();
      } finally {
        submit.disabled = false;
      }
    });
  }
  syncExportPopoverHint();
})();
