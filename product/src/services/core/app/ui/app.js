/* ============================================================
   内容知识库 · 全新行为层（按 2026-11-10 八张定稿图从零建立）
   不引用任何旧状态对象、旧渲染函数、旧 IIFE。
   ============================================================ */
(() => {
  "use strict";

  const API = "/api/v1";
  const CONTRACT = "__API_CONTRACT_VERSION__";
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  const S = {
    route: "intake", previous: "intake",
    settingsReturnRoute: null, contentReturn: { route: "library" },
    history: [], historyLoadFailed: false, jobs: [], queue: null, tags: [], folders: [], sessions: [],
    settings: {}, connections: [], trash: null,
    activeTagIds: [], activeFolderIds: [], libQuery: "",
    libFilters: { platform: null, kind: null, duration: null, introduction: null },
    libFilterOpen: false, libFilterDimension: null,
    libMode: null, libModeKind: null, libModeTargetId: null, pickedContents: new Set(),
    libEditMode: false, selectedContents: new Set(), libCollection: null,
    libGroupMenu: null, libManageOpen: false, libManageScrollTop: 0, libGridScrollTop: 0,
    jobFilter: "all", jobEditMode: false, selectedJobs: new Set(),
    scopeKind: "all", scopeTags: new Set(), scopeFolders: new Set(),
    scopeContents: new Set(), scopeLevel: null,
    applied: { kind: "all", tags: new Set(), folders: new Set(), contents: new Set() },
    sessionId: null, sessionDetail: null, lastQueryId: null,
    askPending: null, askSubmitting: false, askQueries: new Map(),
    askState: "collapsed", askWidths: { sessions: null, settings: null },
    asrLocalModels: null, asrLocalModelsLoading: false, asrLocalModelsError: null,
    summaryModels: [], asrModels: [],
    environmentCheck: null, environmentChecking: false, environmentCheckError: null,
    jobsRefreshing: false, libraryRefreshing: false,
    settingsSection: "platform",
    intakeTab: "link", intakeQuery: null,
    intakeSeq: 0, intakePreviewSnapshot: null, intakePreviewItems: [],
    intakeSubmitting: false, intakeQuerying: false, intakePhase: null,
    confirmAction: null,
    confirmPrompt: false,
    /* 11-22 R5：重复分流双主动作弹窗（继续导入 / 舍弃），回调式，Esc/遮罩不触发分流。 */
    triageImportAction: null, triageDiscardAction: null, triageDismissAction: null,
    triageReturnFocus: null,
    accountImport: null,
    contentId: null, content: null, markdown: "", versions: [], versionIndex: 0,
    contentRefreshing: false,
    quickQuery: "", quickOpen: null, quickContext: null, editing: false, exportSubdir: "",
    confirmReturnFocus: null,
  };
  /* U-7：来源标签点击后按 key 取真实引用内容 id，不在 DOM 里塞长串数据。 */
  const sourceRefs = new Map();
  let sourceSeq = 0;
  let shellRequestSeq = 0;
  let intakeProbeTimer = null;
  let jobsSyncPromise = null;
  let librarySyncPromise = null;

  /* ------------------------- 基础工具 ------------------------- */
  /* sticky：批量操作期间常驻显示，由下一次 toast 覆盖或结束时正常收起。
     默认 2.6 秒自动消失，短提示仍按原节奏。 */
  function toast(message, options = {}) {
    const box = $("#toast");
    box.textContent = message;
    box.hidden = false;
    clearTimeout(toast._timer);
    if (options.sticky) return;
    toast._timer = setTimeout(() => { box.hidden = true; }, 2600);
  }
  function requestConfirmation(message, confirmLabel, action) {
    S.confirmPrompt = false;
    $("#confirm-dialog-input-wrap").hidden = true;
    S.confirmAction = action;
    S.confirmReturnFocus = document.activeElement;
    $("#confirm-dialog-message").textContent = message;
    $("#confirm-dialog-submit").textContent = confirmLabel;
    $("#confirm-dialog").hidden = false;
    $("button[data-act='confirm-cancel']", $("#confirm-dialog")).focus();
  }
  function requestProductPrompt(title, label, value, action) {
    S.confirmPrompt = true;
    S.confirmAction = action;
    S.confirmReturnFocus = document.activeElement;
    $("#confirm-dialog-message").textContent = title;
    $("#confirm-dialog-submit").textContent = "确定";
    $("#confirm-dialog-input-label").textContent = label;
    $("#confirm-dialog-input").value = value;
    $("#confirm-dialog-input-wrap").hidden = false;
    $("#confirm-dialog").hidden = false;
    $("#confirm-dialog-input").focus();
    $("#confirm-dialog-input").select();
  }
  function closeConfirmation() {
    $("#confirm-dialog").hidden = true;
    $("#confirm-dialog-input-wrap").hidden = true;
    $("#confirm-dialog-input").value = "";
    S.confirmAction = null;
    S.confirmPrompt = false;
    const target = S.confirmReturnFocus;
    S.confirmReturnFocus = null;
    if (target?.isConnected) target.focus();
  }
  /* 11-22 R5：重复分流双主动作弹窗。沿用 requestConfirmation 的回调式契约，
     不用 Promise。onImport/onDiscard 各自绑定；onDismiss 用于 Esc/遮罩关闭但不分流。
     lines 里的清单逐条用 textContent 填充，绝不拼 HTML（审核要求防 XSS）。 */
  function requestTriageConfirmation(summary, lines, onImport, onDiscard, onDismiss) {
    S.triageImportAction = onImport;
    S.triageDiscardAction = onDiscard;
    S.triageDismissAction = onDismiss || null;
    S.triageReturnFocus = document.activeElement;
    $("#triage-dialog-summary").textContent = summary;
    const list = $("#triage-dialog-list");
    list.replaceChildren();
    lines.forEach((line) => {
      const row = document.createElement("div");
      row.className = "triage-dialog__row";
      row.textContent = line;
      list.appendChild(row);
    });
    $("#triage-dialog").hidden = false;
    $("#triage-import").focus();
  }
  function closeTriageConfirmation() {
    $("#triage-dialog").hidden = true;
    S.triageImportAction = null;
    S.triageDiscardAction = null;
    S.triageDismissAction = null;
    const target = S.triageReturnFocus;
    S.triageReturnFocus = null;
    if (target?.isConnected) target.focus();
  }
  /* 只关闭、不执行任何分流（Esc / 遮罩）。onDismiss 由 jobAction 用于释放锁。 */
  function dismissTriage() {
    if ($("#triage-dialog").hidden) return;
    const onDismiss = S.triageDismissAction;
    closeTriageConfirmation();
    if (onDismiss) onDismiss();
  }
  function fmtDuration(seconds) {
    const n = Math.max(0, Math.round(Number(seconds) || 0));
    const h = Math.floor(n / 3600), m = Math.floor((n % 3600) / 60), s = n % 60;
    const pad = (v) => String(v).padStart(2, "0");
    return h ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
  }
  function fmtDate(value) {
    if (!value) return "—";
    const s = String(value).slice(0, 10);
    return /^\d{4}-\d{2}-\d{2}$/.test(s) ? s : "—";
  }
  function platformLabel(p) {
    return ({ bilibili: "B站", xiaohongshu: "小红书", douyin: "抖音",
      zhihu: "知乎", wechat: "微信", youtube: "YouTube", local: "本地" })[p] || (p || "来源");
  }
  function inline(text) {
    return esc(text)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`(.+?)`/g, "<code>$1</code>");
  }
  function markdownTableCells(line) {
    return line.trim().replace(/^\||(?<!\\)\|$/g, "")
      .split(/(?<!\\)\|/).map((cell) => cell.trim().replace(/\\\|/g, "|"));
  }
  function readMarkdownTable(lines, start) {
    if (!lines[start].includes("|")) return null;
    const headers = markdownTableCells(lines[start]);
    let separator = start + 1;
    while (separator < lines.length && !lines[separator].trim()) separator++;
    if (separator === lines.length) return null;
    const framed = /^\s*\|.*\|\s*$/;
    const separators = markdownTableCells(lines[separator]);
    if (headers.length !== separators.length || !separators.every((cell) => /^:?-{3,}:?$/.test(cell))) return null;
    const framedTable = framed.test(lines[start]) && framed.test(lines[separator]);
    if ((headers.length === 1 || separator > start + 1) && !framedTable) return null;

    const rows = [];
    let end = separator;
    for (let index = separator + 1; index < lines.length; index++) {
      const line = lines[index];
      if (!line.trim()) continue;
      if (index > end + 1 && !(framedTable && framed.test(line))) break;
      if (!line.includes("|") || /^(?:#{1,6}|[-*+>]|[0-9]+[.)])\s/.test(line.trimStart())) break;
      const cells = markdownTableCells(line);
      if (cells.length !== headers.length) break;
      rows.push(cells);
      end = index;
    }
    return { headers, rows, end };
  }
  function mdToHtml(source, { tables = false } = {}) {
    const lines = String(source || "").split(/\r?\n/);
    const out = [];
    let list = null;
    const close = () => { if (list) { out.push(`</${list}>`); list = null; } };
    for (let index = 0; index < lines.length; index++) {
      const line = lines[index].trimEnd();
      const heading = /^(#{1,4})\s+(.*)$/.exec(line);
      if (heading) {
        close();
        const level = Math.min(heading[1].length + 1, 4);
        out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
        continue;
      }
      const ordered = /^\d+[.)]\s+(.*)$/.exec(line);
      const bullet = /^[-*]\s+(.*)$/.exec(line);
      if (ordered || bullet) {
        const tag = ordered ? "ol" : "ul";
        if (list !== tag) { close(); list = tag; out.push(`<${tag}>`); }
        out.push(`<li>${inline((ordered || bullet)[1])}</li>`);
        continue;
      }
      close();
      if (!line.trim()) continue;
      const table = tables ? readMarkdownTable(lines, index) : null;
      if (table) {
        const head = table.headers.map((cell) => "<th>" + inline(cell) + "</th>").join("");
        const body = table.rows.map((row) =>
          "<tr>" + row.map((cell) => "<td>" + inline(cell) + "</td>").join("") + "</tr>").join("");
        out.push('<div class="doc-table"><table><thead><tr>' + head + "</tr></thead><tbody>" + body + "</tbody></table></div>");
        index = table.end;
        continue;
      }
      out.push(`<p>${inline(line)}</p>`);
    }
    close();
    return out.join("");
  }
  function plainText(source) {
    return String(source || "")
      .replace(/^#{1,4}\s+/gm, "").replace(/^\d+[.)]\s+/gm, "")
      .replace(/^[-*]\s+/gm, "").replace(/\*\*|`/g, "");
  }
  async function api(path, options = {}) {
    const init = { ...options };
    init.headers = { ...(options.headers || {}) };
    if (init.body && typeof init.body !== "string") {
      init.body = JSON.stringify(init.body);
      init.headers["Content-Type"] = "application/json";
    }
    const response = await fetch(options.absolute ? path : (path.startsWith("/api") ? path : API + path), init);
    if (!response.ok) {
      let detail = `HTTP ${response.status}`;
      try {
        const body = (await response.json()).detail;
        // 参数校验失败时 detail 是数组，取第一条可读原因，不把整段 JSON 甩给用户。
        if (typeof body === "string") detail = body;
        else if (Array.isArray(body) && body[0]?.msg) detail = body[0].msg;
        else if (body) detail = JSON.stringify(body);
      } catch (_) { /* noop */ }
      // 11-17 R1：后端机器错误码与英文异常原文不直接甩给用户。
      throw new Error(humanizeApiError(detail));
    }
    return response.status === 204 ? null : response.json();
  }
  const post = (path, body, headers) => api(path, { method: "POST", body, headers });
  const patch = (path, body) => api(path, { method: "PATCH", body });
  const del = (path) => api(path, { method: "DELETE" });
  const contentOf = (entry) => entry?.content || entry || {};
  const idOf = (entry) => contentOf(entry).id;
  const thumbSrc = (id) => id ? `/api/v1/contents/${encodeURIComponent(id)}/thumbnail` : "";
  function categoryOf(content) {
    const tags = (content?.tag_names || []).filter(Boolean);
    if (tags.length) return tags[0];
    const value = String(content?.category || "").trim();
    return value && value !== "未分类" ? value : "";
  }
  function thumbImg(id, cls) {
    return id
      ? `<img class="${cls}" src="${thumbSrc(id)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.style.visibility='hidden'" />`
      : `<span class="${cls}"></span>`;
  }

  /* C3/C6：平台标志只用六个原文件；未知平台沿用通用文字回退，不发明新图标。
     尺寸（8.2% / 2.7%）与 contain / opacity 全部由 CSS 控制，JS 不写 inline 尺寸。 */
  const PLATFORM_BADGE_FILES = {
    bilibili: "bilibili.ico", zhihu: "zhihu.ico",
    xiaohongshu: "xiaohongshu.ico", wechat: "wechat.png",
    douyin: "douyin.ico", youtube: "youtube.ico",
  };
  function platformBadgeHtml(platform) {
    const file = PLATFORM_BADGE_FILES[String(platform || "").toLowerCase()];
    if (file) {
      return `<img class="platform-badge" src="/ui/platform-icons/${file}" alt="" referrerpolicy="no-referrer" />`;
    }
    const label = platformLabel(platform || "web");
    // 1-11/2-06：未知平台（含 local）沿用通用回退，改紧凑单字 + nowrap，不竖排、不发明新图标。
    const glyph = Array.from(label)[0] || "源";
    return `<span class="platform-badge platform-badge--generic" role="img" title="${esc(label)}来源" aria-label="${esc(label)}来源">${esc(glyph)}</span>`;
  }
  /* 1-10/2-05：无 thumbnail_url 的记录（本地识别导入）生成中性程序化占位封面，
     用真实标题排成两行小字 + 中性几何图标，不铺满巨大单字、不抢内容；
     内联 SVG data URI，不含任何其它条目的封面数据、不写入产品数据。
     圆角与平台标志由外层 .cover 提供。 */
  function placeholderThumb(title) {
    const text = String(title || "").replace(/\s+/g, " ").trim();
    const chars = Array.from(text).slice(0, 14);
    const lines = [chars.slice(0, 7).join(""), chars.slice(7, 14).join("")].filter(Boolean);
    const label = lines.map((line, i) =>
      `<text x="26" y="${92 + i * 30}" font-family="Microsoft YaHei,PingFang SC,sans-serif" `
      + `font-size="20" font-weight="400" fill="#7c8bab">${esc(line)}</text>`).join("");
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180" viewBox="0 0 320 180">`
      + `<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">`
      + `<stop offset="0" stop-color="#f3f6fc"/><stop offset="1" stop-color="#e4ecfa"/></linearGradient></defs>`
      + `<rect width="320" height="180" fill="url(#g)"/>`
      + `<g fill="none" stroke="#c3d2ec" stroke-width="2">`
      + `<rect x="26" y="30" width="34" height="26" rx="4"/>`
      + `<path d="M32 38h22M32 44h16"/></g>`
      + label
      + `<path d="M26 154h268" stroke="#d5e0f2" stroke-width="1.5"/></svg>`;
    return `data:image/svg+xml,${encodeURIComponent(svg)}`;
  }
  /* 知识库卡片与任务缩略图共用一套封面模板；任务页不输出时长胶囊。 */
  function coverHtml(content, withDuration, cornerText) {
    const id = content?.id;
    // 任务页只传 {id, platform}：按 id 从真实 history 记录补齐 thumbnail_url/title/duration（不伪造）。
    const ref = id ? contentOf(S.history.find((e) => idOf(e) === id) || {}) : {};
    const thumbUrl = content?.thumbnail_url || ref.thumbnail_url || "";
    const title = content?.title || ref.title || "";
    const dur = Math.round(Number(content?.duration_seconds ?? ref.duration_seconds) || 0);
    const ph = placeholderThumb(title);
    const img = thumbUrl
      ? `<img class="cover__img" src="${thumbSrc(id)}" alt="" loading="lazy" referrerpolicy="no-referrer" data-fallback="${ph}" onerror="this.onerror=null;this.src=this.dataset.fallback" />`
      : `<img class="cover__img" src="${ph}" alt="" loading="lazy" referrerpolicy="no-referrer" />`;
    const badge = platformBadgeHtml(content?.platform || ref.platform);
    // 1-12：仅当存在真实时长才输出右下时长胶囊（空/0 不再显示「00:00」）。
    const duration = withDuration && dur > 0
      ? `<span class="duration-badge">${fmtDuration(dur)}</span>` : "";
    // 11-18 R1：只有父集合行传 cornerText；其余封面输出与改动前逐字一致。
    const corner = cornerText ? `<span class="cover__corner">${esc(cornerText)}</span>` : "";
    return `<span class="cover">${img}${badge}${duration}${corner}</span>`;
  }
  /* C8：把接口里持久化的 ISO 时间格式化为「YYYY-MM-DD HH:mm」，绝不 new Date()/硬编码。 */
  function fmtDateTime(value) {
    if (!value) return "";
    const m = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})/.exec(String(value));
    return m ? `${m[1]} ${m[2]}:${m[3]}` : "";
  }

  /* ------------------------- 数据加载 ------------------------- */
  async function loadArchivedHistory() {
    const pageSize = 50;
    const entries = [];
    for (let offset = 0; ; offset += pageSize) {
      const page = await api(`/history?archived_only=true&limit=${pageSize}&offset=${offset}`);
      entries.push(...page);
      if (page.length < pageSize) return entries;
    }
  }
  async function loadBase() {
    const jobs = [
      ["history", loadArchivedHistory()], ["jobs", api("/jobs")], ["queue", api("/queue")],
      ["tags", api("/tags")], ["folders", api("/favorite-folders")],
      ["sessions", api("/ask/sessions")], ["settings", api("/settings")],
      ["connections", api("/platform-connections")],
    ];
    const result = await Promise.allSettled(jobs.map(([, promise]) => promise));
    result.forEach((item, index) => {
      const key = jobs[index][0];
      if (key === "history") S.historyLoadFailed = item.status !== "fulfilled";
      if (item.status === "fulfilled") {
        if (key === "connections") S.connections = item.value.connections || [];
        else S[key] = item.value;
      } else {
        console.warn(`[loadBase] ${key}`, item.reason);
      }
    });
    S.tags = Array.isArray(S.tags) ? S.tags : [];
    S.folders = Array.isArray(S.folders) ? S.folders : [];
    S.sessions = Array.isArray(S.sessions) ? S.sessions : [];
    S.history = Array.isArray(S.history) ? S.history : [];
    S.jobs = Array.isArray(S.jobs) ? S.jobs : [];
    S.queue = S.queue && typeof S.queue === "object" ? S.queue : null;
  }
  async function refresh(key, options = {}) {
    const map = {
      jobs: "/jobs?limit=2000", queue: "/queue", tags: "/tags",
      folders: "/favorite-folders", sessions: "/ask/sessions", settings: "/settings",
      trash: "/trash",
      connections: "/platform-connections",
    };
    if (key !== "history" && !map[key]) return;
    try {
      const value = key === "history" ? await loadArchivedHistory() : await api(map[key]);
      if (key === "history") S.historyLoadFailed = false;
      if (key === "connections") S.connections = value.connections || [];
      else S[key] = value;
      return true;
    } catch (error) {
      if (key === "history") S.historyLoadFailed = true;
      if (!options.quiet) toast(`刷新失败：${error.message}`);
    }
    return false;
  }
  /* 11-22：任务变更后统一刷新 jobs + queue 并重绘。编辑态下轮询被 !S.jobEditMode
     挡住，所有改状态的入口都要走这里，不能只刷 jobs——队列位次同样会变。 */
  async function syncJobsAfterMutation(options = {}) {
    if (jobsSyncPromise) {
      await jobsSyncPromise;
      return syncJobsAfterMutation(options);
    }
    S.jobsRefreshing = true;
    if (S.route === "tasks") renderJobs();
    jobsSyncPromise = Promise.all([
      refresh("jobs", { quiet: true }), refresh("queue", { quiet: true }),
    ]).then(([jobsRefreshed, queueRefreshed]) => jobsRefreshed && queueRefreshed);
    try {
      const refreshed = await jobsSyncPromise;
      if (!refreshed && !options.quiet) toast("任务列表刷新失败，保留现有数据");
      if (refreshed && options.feedback) toast("任务列表已刷新");
      return refreshed;
    } finally {
      jobsSyncPromise = null;
      S.jobsRefreshing = false;
      if (S.route === "tasks") renderJobs();
    }
  }
  async function syncLibraryData(options = {}) {
    if (librarySyncPromise) return librarySyncPromise;
    S.libraryRefreshing = true;
    renderLibraryToolbar();
    librarySyncPromise = Promise.all([
      refresh("history", { quiet: true }), refresh("tags", { quiet: true }),
      refresh("folders", { quiet: true }),
    ]).then((results) => results.every(Boolean));
    try {
      const refreshed = await librarySyncPromise;
      if (S.route === "library") renderLibrary();
      if (!refreshed && !options.quiet) toast("知识库刷新失败，保留现有数据");
      if (refreshed && options.feedback) toast("知识库已刷新");
      return refreshed;
    } finally {
      librarySyncPromise = null;
      S.libraryRefreshing = false;
      if (S.route === "library") renderLibraryToolbar();
    }
  }

  /* ------------------------- 路由 ------------------------- */
  function go(route, options = {}) {
    if (!["intake", "tasks", "library", "ask", "settings", "content", "trash"].includes(route)) return;
    if (route === "settings" && S.route !== "settings") S.settingsReturnRoute = S.route;
    if (route !== "content") S.previous = route;
    S.route = route;
    $$(".rail__item").forEach((button) => {
      const current = button.dataset.route === route ||
        ((route === "content" || route === "trash") && button.dataset.route === "library");
      button.classList.toggle("is-current", current);
      if (current) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
    $$(".screen").forEach((screen) => { screen.hidden = screen.dataset.screen !== route; });
    closeSheet(); closePopmenu(); closeRestyle();
    if (route === "library") {
      renderLibrary();
      void syncLibraryData();
    }
    if (route === "tasks") { renderJobs(); void syncJobsAfterMutation(); }
    else stopJobsWatch();
    if (route === "ask") {
      renderAsk();
      if (S.sessionId) void loadAskSession(S.sessionId);
    }
    if (route === "trash") renderTrash();
    if (route === "settings") renderSettingsPane();
    if (route === "content" && options.contentId) openContent(options.contentId);
    if (route === "content" && !S.contentId && S.history.length) openContent(idOf(S.history[0]));
    window.scrollTo({ top: 0, behavior: "instant" });
  }

  /* ------------------------- 图六：Tooltip ------------------------- */
  let longPressTimer = null;
  function showTip(target) {
    const tip = $("#tip");
    const text = target.dataset.tip || target.getAttribute("aria-label");
    if (!text) return;
    tip.textContent = text;
    tip.hidden = false;
    const rect = target.getBoundingClientRect();
    const width = tip.getBoundingClientRect().width;
    const left = Math.min(rect.right + 10, window.innerWidth - width - 8);
    tip.style.left = `${Math.max(8, left)}px`;
    tip.style.top = `${rect.top + rect.height / 2 - tip.getBoundingClientRect().height / 2}px`;
  }
  function hideTip() { $("#tip").hidden = true; }
  function initTooltip() {
    document.addEventListener("pointerover", (event) => {
      const target = event.target.closest?.("[data-tip]");
      if (target) showTip(target);
    });
    document.addEventListener("pointerout", (event) => {
      if (event.target.closest?.("[data-tip]")) hideTip();
    });
    document.addEventListener("focusin", (event) => {
      const target = event.target.closest?.("[data-tip]");
      if (target) showTip(target);
    });
    document.addEventListener("focusout", hideTip);
    document.addEventListener("touchstart", (event) => {
      const target = event.target.closest?.("[data-tip]");
      if (!target) return;
      clearTimeout(longPressTimer);
      longPressTimer = setTimeout(() => showTip(target), 450);
    }, { passive: true });
    ["touchend", "touchcancel", "touchmove"].forEach((name) =>
      document.addEventListener(name, () => { clearTimeout(longPressTimer); setTimeout(hideTip, 900); }, { passive: true }));
    window.addEventListener("scroll", hideTip, { passive: true });
  }

  /* ------------------------- 图一：内容接入 ------------------------- */
  function intakeRows() {
    return $("#intake-links").value.split(/\r?\n/).map((v) => v.trim()).filter(Boolean);
  }
  function renderIntakeCount() {
    const count = intakeRows().length;
    $("#intake-count").textContent = `识别${count}条`;
  }
  function renderIntakeControls() {
    const query = $('[data-act="intake-query"]');
    const submit = $('[data-act="intake-submit"]');
    const clear = $('[data-act="intake-clear"]');
    if (query) {
      query.disabled = S.intakeQuerying || S.intakeSubmitting;
      query.textContent = S.intakeQuerying && !S.intakeSubmitting ? "查询中…" : "查询";
    }
    if (submit) {
      submit.disabled = S.intakeQuerying || S.intakeSubmitting;
      submit.textContent = S.intakeSubmitting
        ? (S.intakePhase === "query" ? "正在查询…" : "提交中…") : "提交";
    }
    if (clear) clear.disabled = S.intakeQuerying || S.intakeSubmitting;
  }
  function intakeSnapshot(urls) { return urls.join("\n"); }
  function intakeIsCurrent(seq, snapshot) {
    return seq === S.intakeSeq && intakeSnapshot(intakeRows()) === snapshot;
  }
  function renderIntakePreview(state, items = [], message = "", options = {}) {
    const box = $("#intake-preview");
    box.hidden = !state;
    if (!state) { box.innerHTML = ""; return; }
    const stateText = state === "pending" ? "正在识别链接…" : state === "failed" ? (message || "识别失败") : "";
    box.innerHTML = `${stateText ? `<div class="intake-preview__state">${esc(stateText)}</div>` : ""}${items.map((item) => {
      const status = item.status || (item.duplicate ? "duplicate" : "ready");
      const title = item.title || item.input_url || item.source_url || "链接";
      const meta = [item.author, item.platform ? platformLabel(item.platform) : "", item.page_number ? `P${item.page_number}` : ""]
        .filter(Boolean).join(" · ");
      const statusText = options.submitting && ["ready", "duplicate"].includes(status) ? "提交中"
        : status === "pending" ? "识别中" : status === "duplicate" ? "已存在"
          : status === "failed" || status === "timed_out" ? (item.reason || "识别失败") : "可提交";
      const placeholder = placeholderThumb(title);
      const cover = item.thumbnail_url
        ? `<img src="${esc(item.thumbnail_url)}" alt="" loading="lazy" referrerpolicy="no-referrer" data-fallback="${esc(placeholder)}" onerror="this.onerror=null;this.src=this.dataset.fallback">`
        : `<img class="intake-preview__thumb" src="${esc(placeholder)}" alt="">`;
      return `<article class="intake-preview__item">${cover}<span class="intake-preview__body"><strong class="intake-preview__title" title="${esc(title)}">${esc(title)}</strong><span class="intake-preview__meta">${esc(meta || item.source_url || item.input_url || "")}</span></span><span class="intake-preview__status${status === "duplicate" ? " intake-preview__status--duplicate" : ""}">${esc(statusText)}</span></article>`;
    }).join("")}${message && state === "ready" ? `<div class="intake-preview__error">${esc(message)}</div>` : ""}`;
  }
  function invalidateIntakePreview() {
    S.intakeSeq += 1;
    S.intakeQuery = null;
    S.intakePreviewSnapshot = null;
    S.intakePreviewItems = [];
    renderIntakePreview(null);
  }
  function previewItemsFromQuery(items) {
    return (items || []).map((item) => {
      let pageNumber = item.page_number;
      if (!pageNumber) {
        try {
          const parsed = new URL(item.source_url || item.input_url, window.location.origin);
          const value = Number(parsed.searchParams.get("p"));
          if (value > 0) pageNumber = value;
        } catch (_) { /* use available metadata */ }
      }
      return { ...item, page_number: pageNumber, title: item.title || item.input_url || item.source_url };
    });
  }
  async function intakeQuery({ fromSubmit = false } = {}) {
    if (S.intakeQuerying || (S.intakeSubmitting && !fromSubmit)) return false;
    const urls = intakeRows();
    if (!urls.length) return toast("请先粘贴链接");
    S.intakeQuerying = true;
    renderIntakeControls();
    clearTimeout(intakeProbeTimer);
    intakeProbeTimer = null;
    const snapshot = intakeSnapshot(urls);
    const seq = ++S.intakeSeq;
    S.intakeQuery = null;
    S.intakePreviewSnapshot = null;
    S.intakePreviewItems = [];
    renderIntakePreview("pending");
    try {
      const results = await Promise.all(urls.map(async (url) => {
        try { return { url, probe: await post("/imports/probe", { url }) }; }
        catch (error) { return { url, error: error.message }; }
      }));
      if (!intakeIsCurrent(seq, snapshot)) return false;
      const items = results.flatMap(({ url, probe, error }) => {
        if (error || !probe || probe.preview_status !== "ready" || !probe.items?.length) {
          return [{ input_url: url, status: "failed", reason: error || probe?.preview_error || probe?.material_hint || "无法读取链接信息" }];
        }
        return probe.items.map((item) => ({ ...item, status: item.duplicate ? "duplicate" : "ready" }));
      });
      S.intakePreviewItems = items;
      S.intakePreviewSnapshot = snapshot;
      const failed = items.filter((item) => !["ready", "duplicate"].includes(item.status));
      renderIntakePreview(failed.length === items.length ? "failed" : "ready", items,
        failed.length ? `有 ${failed.length} 条链接未能预览` : "");
      return failed.length === 0;
    } finally {
      S.intakeQuerying = false;
      renderIntakeControls();
    }
  }
  function lockIntake(locked) {
    $("#intake-links").disabled = locked;
    renderIntakeControls();
  }
  /* R8：界面选项直接用后端合法枚举，导入与重新总结共用同一组值。 */
  function summaryConfig() {
    return {
      summary_style: $("#intake-style").value,
      strength: $("#intake-strength").value,
      extra_instruction: $("#intake-extra-instruction").value,
    };
  }
  async function intakeSubmit() {
    const urls = intakeRows();
    if (S.intakeSubmitting) return;
    if (S.intakeTab !== "link") return toast("请先识别本地文件");
    if (!urls.length) return toast("请先粘贴链接");
    const snapshot = intakeSnapshot(urls);
    S.intakeSubmitting = true;
    S.intakePhase = "query";
    renderIntakeControls();
    try {
      if (S.intakePreviewSnapshot !== snapshot || !S.intakePreviewItems.length
        || !S.intakePreviewItems.every((item) => ["ready", "duplicate"].includes(item.status))) {
        const previewReady = await intakeQuery({ fromSubmit: true });
        if (!previewReady) return;
      }
      if (S.intakePreviewSnapshot !== snapshot
        || !S.intakePreviewItems.every((item) => ["ready", "duplicate"].includes(item.status))) {
        return toast("请先检查无法识别的链接");
      }
      const submitSeq = S.intakeSeq;
      S.intakePhase = "query";
      renderIntakeControls();
      const query = await post("/imports/query", { urls });
      S.intakeQuery = query;
      let result = query;
      while (result.status === "processing") {
        if (!intakeIsCurrent(submitSeq, snapshot)) {
          await post(`/imports/query/${query.query_id}/cancel`, {}).catch(() => {});
          return toast("链接内容已更改，已取消提交");
        }
        await new Promise((resolve) => setTimeout(resolve, 350));
        result = await api(`/imports/query/${query.query_id}`);
        S.intakeQuery = result;
        if (intakeIsCurrent(submitSeq, snapshot)) {
          S.intakePreviewItems = previewItemsFromQuery(result.items);
          renderIntakePreview("ready", S.intakePreviewItems);
        }
      }
      if (!intakeIsCurrent(submitSeq, snapshot)) return toast("链接内容已更改，已取消提交");
      const items = result.items || [];
      const itemIds = items
        .filter((item) => item.selectable !== false && ["ready", "duplicate"].includes(item.status))
        .map((item) => item.item_id);
      if (!itemIds.length || itemIds.length !== items.length) {
        S.intakePreviewItems = previewItemsFromQuery(items);
        renderIntakePreview("failed", S.intakePreviewItems, "部分链接未能读取，请修正后重试");
        return toast("部分链接未能读取，请修正后重试");
      }
      S.intakePhase = "submit";
      renderIntakeControls();
      renderIntakePreview("ready", S.intakePreviewItems, "", { submitting: true });
      lockIntake(true);
      const confirmation = await post("/imports/query/confirm", {
        query_id: query.query_id,
        item_ids: itemIds,
        duplicate_action: "reuse",
        ...summaryConfig(),
      });
      if (!intakeIsCurrent(submitSeq, snapshot)) return toast("链接内容已更改，提交结果未应用到当前输入");
      const accepted = confirmation.accepted || [];
      const skipped = confirmation.skipped || [];
      const failed = confirmation.failed || [];
      const createdItems = accepted.filter((item) => !item.reused);
      const reusedCount = skipped.length + accepted.filter((item) => item.reused).length;
      if (failed.length) {
        const matchedFailures = new Set();
        const resultItems = previewItemsFromQuery(items).map((item) => {
          const failureIndex = failed.findIndex((entry, index) =>
            !matchedFailures.has(index) && [item.input_url, item.source_url].includes(entry.url));
          if (failureIndex < 0) return item;
          matchedFailures.add(failureIndex);
          return { ...item, status: "failed", reason: failed[failureIndex].reason };
        });
        failed.forEach((entry, index) => {
          if (!matchedFailures.has(index)) {
            resultItems.push({ input_url: entry.url, title: entry.url, status: "failed", reason: entry.reason });
          }
        });
        S.intakePreviewItems = resultItems;
        S.intakePreviewSnapshot = null;
        renderIntakePreview("ready", resultItems, "部分提交失败；输入已保留，再次提交将重新查询");
        const jobsRefreshed = createdItems.length ? await refresh("jobs") : true;
        const parts = [`已接受 ${createdItems.length} 项`, `复用 ${reusedCount} 项`, `失败 ${failed.length} 项`];
        if (!jobsRefreshed) parts.push("任务列表刷新失败");
        toast(`${parts.join("，")}；输入已保留，再次提交将重新查询`);
        return;
      }
      if (!createdItems.length) {
        if (reusedCount) {
          $("#intake-links").value = "";
          invalidateIntakePreview();
          renderIntakeCount();
          toast(`复用 ${reusedCount} 项，未新建任务`);
          go("tasks");
          return;
        }
        return toast("没有创建新任务");
      }
      const jobsRefreshed = await refresh("jobs");
      const created = jobsRefreshed
        ? createdItems.filter((item) => S.jobs.some((job) => job.id === item.job?.id))
        : [];
      if (created.length !== createdItems.length) {
        S.intakePreviewSnapshot = null;
        const reason = jobsRefreshed ? "部分任务未出现在任务列表" : "任务列表刷新失败";
        toast(`已接受 ${createdItems.length} 项，复用 ${reusedCount} 项，失败 0 项；${reason}，输入已保留`);
        return;
      }
      $("#intake-links").value = "";
      invalidateIntakePreview();
      renderIntakeCount();
      S.jobFilter = "all";
      $$("[data-job-filter]").forEach((item) => {
        const current = item.dataset.jobFilter === "all";
        item.classList.toggle("is-current", current);
        item.setAttribute("aria-selected", String(current));
      });
      go("tasks");
      toast(`已创建 ${created.length} 项，复用 ${reusedCount} 项，失败 0 项`);
    } catch (error) {
      // R8：提交失败不重置已选风格与强度。
      S.intakePreviewSnapshot = null;
      renderIntakePreview("ready", S.intakePreviewItems, "提交失败；输入已保留，再次提交将重新查询");
      toast(`提交失败：${error.message}；再次提交将重新查询`);
    } finally {
      S.intakeSubmitting = false;
      S.intakePhase = null;
      lockIntake(false);
      renderIntakeControls();
    }
  }

  const accountImportTitles = { favorite: "B站收藏", watchlater: "B站稍后再看", xiaohongshu: "小红书收藏" };
  const accountScanPath = (source) => `/imports/bilibili/${source}-scans`;
  function renderAccountImport() {
    const state = S.accountImport;
    const modal = $("#account-import-modal");
    modal.hidden = !state;
    if (!state) return;
    $("#account-import-title").textContent = state.title;
    const tools = $("#account-import-tools");
    const body = $("#account-import-body");
    const footer = $("#account-import-count");
    const submit = $("#account-import-submit");
    tools.hidden = state.step !== "candidates";
    const backToFolders = $("#account-import-back-folders");
    backToFolders.hidden = state.source !== "xiaohongshu" || state.step !== "candidates" || !state.folders.length;
    const allCandidates = state.candidates || [];
    const candidates = state.onlyNew && state.step === "candidates"
      ? allCandidates.filter((item) => item.duplicate_status === "new")
      : allCandidates;
    if (state.step === "folders") {
      body.innerHTML = state.folders.length ? `<div class="account-import__folders">${state.folders.map((folder) => `
        <button class="account-import__folder" type="button" data-act="account-import-folder" data-folder-id="${esc(folder.id)}" data-folder-title="${esc(folder.title)}">
          <span>${esc(folder.title)}</span>${folder.media_count == null ? "" : `<span class="account-import__meta">${Number(folder.media_count) || 0}</span>`}
        </button>`).join("")}</div>` : '<div class="account-import__empty">暂无收藏夹</div>';
    } else if (state.step === "candidates" || (state.step === "scanning" && allCandidates.length)) {
      const itemHtml = (item) => {
        const id = item.candidate_id || item.id || item.url;
        const status = ({ new: "未导入", summarized: "已导入", processing: "处理中", failed: "失败", unknown: "待核对" })[item.duplicate_status] || "待核对";
        const count = item.page_count > 1 ? `<span class="account-import__meta">${Number(item.imported_page_count) || 0}/${item.page_count} P</span>` : "";
        const importError = item.importError
          ? `<span class="account-import__error" title="${esc(item.importError.message)}">${esc(item.importError.stage)}</span>`
          : "";
        return `<label class="account-import__item ${item.selectable === false ? "is-disabled" : ""}" data-candidate-id="${esc(id)}">
          <input type="checkbox" data-import-pick="${esc(id)}" ${state.selected.has(id) ? "checked" : ""} ${item.selectable === false ? "disabled" : ""} />
          ${item.thumbnail_url ? `<img src="${esc(item.thumbnail_url)}" alt="" referrerpolicy="no-referrer" />` : '<span class="account-import__thumb"></span>'}
          <span class="account-import__item-title">${esc(item.title || "未命名内容")}</span><span class="account-import__meta">${status}</span>${count}${importError}
        </label>`;
      };
      if (state.step === "scanning") {
        // 读取中只追加新条目：每秒整体重绘会把用户正在看的滚动位置清掉。
        let list = body.querySelector(".account-import__list");
        if (!list) {
          body.innerHTML = '<div class="account-import__list"></div>';
          list = body.querySelector(".account-import__list");
        }
        const shown = new Set(Array.from(list.children).map((node) => node.dataset.candidateId));
        const added = candidates.filter((item) => !shown.has(String(item.candidate_id || item.id || item.url)));
        if (added.length) list.insertAdjacentHTML("beforeend", added.map(itemHtml).join(""));
      } else {
        body.innerHTML = candidates.length
          ? `<div class="account-import__list">${candidates.map(itemHtml).join("")}</div>`
          : `<div class="account-import__empty">${allCandidates.length ? `共 ${allCandidates.length} 条全部已导入` : "暂无内容"}</div>`;
      }
    } else {
      body.innerHTML = `<div class="account-import__empty">${esc(state.message || "正在读取…")}</div>`;
    }
    const onlyNew = $("[data-import-new-only]");
    if (onlyNew) onlyNew.checked = Boolean(state.onlyNew);
    const pickedVisible = candidates.filter(
      (item) => state.selected.has(item.candidate_id || item.id || item.url)).length;
    const countText = state.onlyNew
      ? `已选 ${pickedVisible} 条 · 未导入 ${candidates.length} / 共 ${allCandidates.length} 条`
      : `已选 ${pickedVisible} 条 · 共 ${allCandidates.length} 条`;
    footer.textContent = state.step === "candidates"
      ? `${countText}${state.xhsScanPartial ? " · 未读完整" : ""}`
      : state.step === "scanning" && allCandidates.length ? `已读取 ${allCandidates.length} 条 · 读取中…` : "";
    submit.hidden = state.step !== "candidates";
    submit.disabled = pickedVisible === 0 || Boolean(state.submitting);
    submit.textContent = state.submitting ? "提交中…" : "导入所选";
    modal.classList.toggle("is-busy", Boolean(state.submitting));
  }
  function closeAccountImport() {
    const state = S.accountImport;
    if (state?.submitting) return;
    S.accountImport = null;
    renderAccountImport();
    if (state?.scanId && ["queued", "running"].includes(state.scanStatus)) {
      del(`${accountScanPath(state.source)}/${state.scanId}`).catch(() => {});
    }
    if (state?.source === "xiaohongshu" && state.shellRequestId && window.chrome?.webview) {
      window.chrome.webview.postMessage({
        platform: "xiaohongshu", action: "cancel_favorites",
        requestId: `account-import-cancel-${++shellRequestSeq}`,
        scanRequestId: state.shellRequestId,
      });
    }
  }
  const XHS_SESSION_STATUSES = ["CONNECTED", "NOT_CONNECTED", "EXPIRED", "REAUTH_REQUIRED", "RISK_CONTROLLED", "PARTIAL"];
  function xhsOperationId() {
    return crypto.randomUUID().replaceAll("-", "");
  }
  function traceXhsFavorites(operationId, event, fields = {}) {
    window.chrome?.webview?.postMessage({
      platform: "xiaohongshu", action: "trace_favorites", requestId: operationId, event, ...fields,
    });
  }
  function requestDesktopShell(platform, action, onRequestId, payload = {}, options = {}) {
    const bridge = window.chrome?.webview;
    if (!bridge?.postMessage || !bridge.addEventListener) return Promise.reject(new Error("请在产品桌面壳中打开"));
    const scanningXhs = platform === "xiaohongshu" && action === "scan_favorites";
    const requestId = scanningXhs ? xhsOperationId() : `account-import-${++shellRequestSeq}`;
    const started = performance.now();
    const traceScan = (event, count = 0) => {
      if (scanningXhs) traceXhsFavorites(requestId, event, { count, ms: Math.round(performance.now() - started) });
    };
    const accepted = options.accepted || ["CONNECTED", "PARTIAL"];
    const onProgress = options.onProgress || null;
    onRequestId?.(requestId);
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        traceScan("scan_timeout");
        bridge.removeEventListener("message", receive);
        if (action === "scan_favorites") {
          bridge.postMessage({
            platform: "xiaohongshu", action: "cancel_favorites",
            requestId: `account-import-timeout-${++shellRequestSeq}`, scanRequestId: requestId,
          });
        }
        reject(new Error(action === "scan_favorites" ? "小红书收藏读取超时" : "小红书操作超时"));
      }, options.timeoutMs || 120000);
      const receive = (event) => {
        const result = event.data;
        if (result?.requestId !== requestId) return;
        if (result.progress) { onProgress?.(result); return; }
        clearTimeout(timer);
        bridge.removeEventListener("message", receive);
        traceScan(result.status === "PARTIAL" ? "scan_partial" : accepted.includes(result.status) ? "scan_complete" : "scan_failed",
          result.candidates?.length || result.albums?.length || 0);
        if (accepted.includes(result.status)) resolve(result);
        else reject(new Error(result.message || "小红书操作失败"));
      };
      bridge.addEventListener("message", receive);
      traceScan("scan_start");
      bridge.postMessage({ platform, action, requestId, ...payload });
    });
  }
  async function saveXhsSession(result) {
    const status = XHS_SESSION_STATUSES.includes(result.status) && result.status !== "PARTIAL"
      ? result.status : "REAUTH_REQUIRED";
    return post("/platform-connections/xiaohongshu/browser-login", {
      status,
      message: String(result.message || "小红书登录状态暂时无法确认").slice(0, 500),
      browser_profile: result.browser_profile || null,
    });
  }
  async function checkXhsConnection() {
    const result = await requestDesktopShell("xiaohongshu", "check_session", null, {}, { accepted: XHS_SESSION_STATUSES });
    await saveXhsSession(result);
    await refresh("connections");
    return result;
  }
  /* 一键检查：B站走 HTTP 探测，小红书走桌面壳会话检查。 */
  async function checkAllConnections() {
    const parts = [];
    for (const conn of S.connections.filter((item) => PLATFORM_LABELS[item.platform])) {
      const label = conn.display_name || PLATFORM_LABELS[conn.platform];
      try {
        const result = conn.platform === "xiaohongshu"
          ? await checkXhsConnection()
          : await post(`/platform-connections/${conn.platform}/check`, {});
        parts.push(`${label}${result.status === "CONNECTED" ? "已连接" : "未连接"}`);
      } catch (error) {
        parts.push(`${label}检查失败`);
      }
    }
    await refresh("connections");
    renderSettingsPane();
    toast(parts.length ? parts.join(" · ") : "没有可检查的平台");
  }
  function collectXhsProgress(state, result) {
    const incoming = Array.isArray(result.candidates) ? result.candidates : [];
    if (!incoming.length) return;
    state.candidates = incoming;
    state.message = `已读取 ${state.candidates.length} 条…`;
    renderAccountImport();
  }
  function xhsNoteId(value) {
    const match = /\/(?:explore|discovery\/item)\/([^/?#]+)/i.exec(String(value || ""));
    return match?.[1] || "";
  }
  function xhsCandidateImported(candidate, history) {
    const noteId = String(candidate.id || candidate.candidate_id || "").replace(/^note:/, "") || xhsNoteId(candidate.url);
    if (!noteId || !Array.isArray(history)) return null;
    return history.some((entry) => {
      const content = contentOf(entry);
      return content.platform === "xiaohongshu"
        && xhsNoteId(content.canonical_url) === noteId;
    });
  }
  function mapXhsCandidates(candidates, history) {
    return (candidates || []).map((item) => {
      const imported = xhsCandidateImported(item, history);
      return {
        ...item,
        duplicate_status: imported === true ? "summarized" : imported === false ? "new" : "unknown",
        selectable: true,
      };
    });
  }
  async function startXhsScan(state) {
    state.step = "scanning";
    state.message = "正在读取…";
    renderAccountImport();
    try {
      const result = await requestDesktopShell("xiaohongshu", "scan_favorites", (id) => { state.shellRequestId = id; }, { scope: "directory" });
      if (S.accountImport !== state) return;
      if (result.status === "PARTIAL") toast(result.message || "小红书收藏读取未完成");
      state.folders = [{ id: "__all_notes__", title: "笔记收藏" }, ...(result.albums || []).map((album) => ({
        id: album.album_id,
        title: album.title,
        media_count: album.media_count,
      }))];
      state.selected.clear();
      state.onlyNew = false;
      state.step = "folders";
      state.shellRequestId = null;
      renderAccountImport();
    } catch (error) {
      if (S.accountImport !== state) return;
      state.step = "error";
      state.message = error.message;
      state.shellRequestId = null;
      toast(error.message);
      renderAccountImport();
    }
  }
  async function startXhsAlbumScan(state, albumId) {
    if (albumId === "__all_notes__") {
      return startXhsNotesScan(state);
    }
    state.activeAlbumId = albumId;
    state.xhsScanPartial = false;
    state.step = "scanning";
    state.message = "正在读取…";
    state.candidates = [];
    state.selected.clear();
    renderAccountImport();
    try {
      const result = await requestDesktopShell("xiaohongshu", "scan_favorites", (id) => { state.shellRequestId = id; }, { scope: "album", albumId }, { onProgress: (partial) => collectXhsProgress(state, partial) });
      if (S.accountImport !== state) return;
      state.xhsScanPartial = result.status === "PARTIAL";
      if (result.status === "PARTIAL") toast(result.message || "小红书专辑读取未完成");
      const history = await api("/history?platform=xiaohongshu");
      if (S.accountImport !== state) return;
      state.candidates = mapXhsCandidates(result.candidates?.length ? result.candidates : state.candidates, history);
      state.selected.clear();
      state.onlyNew = false;
      state.step = "candidates";
      state.shellRequestId = null;
      renderAccountImport();
    } catch (error) {
      if (S.accountImport !== state) return;
      state.shellRequestId = null;
      if (state.candidates.length) {
        state.xhsScanPartial = true;
        const history = await api("/history?platform=xiaohongshu").catch(() => null);
        if (S.accountImport !== state) return;
        state.candidates = mapXhsCandidates(state.candidates, history);
        state.step = "candidates";
        toast(error.message);
        renderAccountImport();
      } else {
        state.step = "error";
        state.message = error.message;
        toast(error.message);
        renderAccountImport();
      }
    }
  }
  async function startXhsNotesScan(state) {
    state.activeAlbumId = null;
    state.xhsScanPartial = false;
    state.step = "scanning";
    state.message = "正在读取…";
    state.candidates = [];
    state.selected.clear();
    renderAccountImport();
    try {
      const result = await requestDesktopShell("xiaohongshu", "scan_favorites", (id) => { state.shellRequestId = id; }, { scope: "notes" }, { onProgress: (partial) => collectXhsProgress(state, partial) });
      if (S.accountImport !== state) return;
      state.xhsScanPartial = result.status === "PARTIAL";
      if (result.status === "PARTIAL") toast(result.message || "小红书收藏读取未完成");
      const history = await api("/history?platform=xiaohongshu");
      if (S.accountImport !== state) return;
      state.candidates = mapXhsCandidates(result.candidates?.length ? result.candidates : state.candidates, history);
      state.selected.clear();
      state.onlyNew = false;
      state.step = "candidates";
      state.shellRequestId = null;
      renderAccountImport();
    } catch (error) {
      if (S.accountImport !== state) return;
      state.shellRequestId = null;
      if (state.candidates.length) {
        state.xhsScanPartial = true;
        const history = await api("/history?platform=xiaohongshu").catch(() => null);
        if (S.accountImport !== state) return;
        state.candidates = mapXhsCandidates(state.candidates, history);
        state.step = "candidates";
        toast(error.message);
        renderAccountImport();
      } else {
        state.step = "error";
        state.message = error.message;
        toast(error.message);
        renderAccountImport();
      }
    }
  }
  async function pollAccountScan(state, accepted) {
    if (S.accountImport !== state) {
      del(`${accountScanPath(state.source)}/${accepted.scan_id}`).catch(() => {});
      return;
    }
    state.scanId = accepted.scan_id;
    state.scanStatus = accepted.status;
    state.step = "scanning";
    renderAccountImport();
    while (S.accountImport === state) {
      const scan = await api(`${accountScanPath(state.source)}/${state.scanId}`);
      if (S.accountImport !== state) return;
      state.scanStatus = scan.status;
      if (scan.status === "failed") throw new Error(scan.error?.user_message || "扫描失败");
      if (scan.status === "cancelled") throw new Error("已取消扫描");
      if (["completed", "partial"].includes(scan.status)) {
        state.candidates = scan.candidates || [];
        state.selected.clear();
        state.onlyNew = false;
        state.step = "candidates";
        renderAccountImport();
        if (scan.status === "partial") toast(scan.error?.user_message || "扫描未完成，已显示已获取内容");
        return;
      }
      renderAccountImport();
      await new Promise((resolve) => setTimeout(resolve, scan.poll_after_ms || accepted.poll_after_ms || 500));
    }
  }
  async function startFavoriteScan(folder) {
    const state = S.accountImport;
    state.step = "scanning";
    state.scanStatus = "queued";
    state.message = "正在读取…";
    renderAccountImport();
    try {
      const url = `https://space.bilibili.com/favlist?fid=${encodeURIComponent(folder.id)}`;
      const accepted = await post(accountScanPath("favorite"), { url });
      await pollAccountScan(state, accepted);
    } catch (error) {
      if (S.accountImport !== state) return;
      state.step = "error";
      state.message = error.message;
      toast(error.message);
      renderAccountImport();
    }
  }
  async function startAccountImport(source) {
    const state = {
      source, title: accountImportTitles[source], step: "loading", folders: [], candidates: [],
      selected: new Set(), onlyNew: false, scanId: null, scanStatus: null,
    };
    S.accountImport = state;
    renderAccountImport();
    try {
      if (source === "favorite") {
        state.folders = await api("/imports/bilibili/favorite-folders");
        if (S.accountImport !== state) return;
        state.step = "folders";
        renderAccountImport();
      } else if (source === "watchlater") {
        const accepted = await post(accountScanPath(source), { url: "https://www.bilibili.com/watchlater" });
        await pollAccountScan(state, accepted);
      } else {
        const conn = (S.connections || []).find((item) => item.platform === "xiaohongshu");
        if (!conn || conn.status !== "CONNECTED") {
          state.step = "error";
          state.message = conn?.message || "小红书账号未连接";
          renderAccountImport();
          return;
        }
        await startXhsScan(state);
      }
    } catch (error) {
      if (S.accountImport !== state) return;
      state.step = "error";
      state.message = error.message;
      toast(error.message);
      renderAccountImport();
    }
  }
  async function submitAccountImport() {
    const state = S.accountImport;
    if (!state || !state.selected.size || state.submitting) return;
    state.submitting = true;
    renderAccountImport();
    try {
      if (state.source === "xiaohongshu") {
        const picked = state.candidates.filter((item) =>
          state.selected.has(item.candidate_id || item.id || item.url)
          && (!state.onlyNew || item.duplicate_status === "new"));
        const operationId = xhsOperationId();
        const started = performance.now();
        traceXhsFavorites(operationId, "import_start", { count: picked.length });
        let created = 0;
        let reused = 0;
        let shellFailed = 0;
        let importFailed = 0;
        for (const item of picked) {
          const id = item.candidate_id || item.id || item.url;
          const noteId = item.id || xhsNoteId(item.url);
          item.importError = null;
          let note;
          try {
            const read = await requestDesktopShell("xiaohongshu", "read_note", null, {
              operationId,
              url: item.url,
              scope: state.activeAlbumId ? "album" : "notes",
              albumId: state.activeAlbumId || null,
            }, { timeoutMs: 45000 });
            note = read.note || {};
            if (!String(note.text || "").trim()) throw new Error("没有读到正文");
            if (typeof read.collectionRestored === "boolean") {
              traceXhsFavorites(operationId,
                read.collectionRestored ? "restore_complete" : "restore_failed", { noteId });
            }
          } catch (error) {
            item.importError = { stage: "壳读取失败", message: error.message };
            shellFailed += 1;
            traceXhsFavorites(operationId, "read_failed", { noteId });
            continue;
          }
          try {
            const result = await post("/imports/local", {
              xiaohongshu_source: {
                url: note.url || item.url,
                title: note.title || item.title || "",
                author: note.author || item.author || null,
                text: note.text,
                thumbnail_url: note.thumbnail_url || item.thumbnail_url || null,
              },
              duplicate_action: "reuse",
            }, { "X-Xhs-Operation-Id": operationId });
            if (result.reused) reused += 1;
            else created += 1;
            traceXhsFavorites(operationId, result.reused ? "reused" : "created", { noteId, jobId: result.job.id });
            item.duplicate_status = "summarized";
            state.selected.delete(id);
          } catch (error) {
            item.importError = { stage: "后端导入失败", message: error.message };
            importFailed += 1;
            traceXhsFavorites(operationId, "import_failed", { noteId });
          }
        }
        traceXhsFavorites(operationId, "import_end", { created, reused, shellFailed, importFailed,
          ms: Math.round(performance.now() - started) });
        state.submitting = false;
        const summary = `新建 ${created} 条，复用 ${reused} 条`;
        if (shellFailed + importFailed) {
          renderAccountImport();
          toast(`${summary}，壳读取失败 ${shellFailed} 条，后端导入失败 ${importFailed} 条；失败项可重试`);
        } else {
          closeAccountImport();
          toast(summary);
        }
        if (created + reused) { await refresh("jobs"); renderJobs(); }
        return;
      } else {
        // 筛选隐藏的已选项不参与本次提交；关闭筛选后选择仍在。
        const visibleIds = new Set(state.candidates
          .filter((item) => !state.onlyNew || item.duplicate_status === "new")
          .map((item) => item.candidate_id || item.id || item.url));
        const candidateIds = Array.from(state.selected).filter((id) => visibleIds.has(id));
        if (!candidateIds.length) {
          state.submitting = false;
          renderAccountImport();
          return toast("当前筛选下没有已选内容");
        }
        await post("/imports/bilibili/scans/confirm", {
          scan_id: state.scanId, candidate_ids: candidateIds,
        });
      }
      state.submitting = false;
      closeAccountImport();
      await refresh("jobs");
      renderJobs();
      toast("已提交，任务已生成");
    } catch (error) {
      state.submitting = false;
      renderAccountImport();
      toast(`导入失败：${error.message}`);
    }
  }

  /* ------------------------- 图二：任务 ------------------------- */
  function jobTitle(job) {
    // 任务未归档前 history 里还没有内容记录，标题由 job 自带的内容标题提供。
    if (job.content_title) return job.content_title;
    const matched = S.history.find((entry) => entry?.job?.id === job.id);
    if (matched) return contentOf(matched).title;
    const archive = String(job.archive_path || "");
    const tail = archive.split(/[\\/]/).pop() || "";
    return tail.replace(/--content_[a-f0-9]+$/, "") || job.source_url || job.id;
  }
  /* C4：7 状态文字逐字按裁定表；状态由真实任务数据计算，不另建体系。
     R2：父任务另有「部分失败」，仅在集内既有成功又有失败时使用。 */
  const JOB_STATE_LABEL = {
    completed: "已完成", running: "进行中", switching: "保存进度",
    waiting: "排队中", paused: "已暂停", failed: "失败", cancelled: "已取消",
  };
  /* R3：默认 4 条，每次继续展开 +4。 */
  const JOB_PAGE_SIZE = 4;
  /* R6：阶段轴用接口真实 stage 值（queue/source/transcription/chunking/summary/archive）；
     state 只用于判断进行/完成/失败，不新增采集。 */
  const JOB_STAGE_ORDER = ["source", "transcription", "chunking", "summary", "archive"];
  const JOB_STAGE_LABEL = {
    queue: "排队", source: "取材", transcription: "转写",
    chunking: "分段", summary: "总结", archive: "归档",
  };
  /* 11-17 R3：阶段轴合并成一条轨道后，只有当前段挂一个符号；符号随阶段换，统一 18px 网格、1.9 描边。 */
  const JOB_STAGE_ICON = {
    source: '<path d="M7 16.6h9.3a3.4 3.4 0 0 0 .3-6.8A5.3 5.3 0 0 0 7.3 9A3.8 3.8 0 0 0 7 16.6Z"/><path d="M12 8v4.8m0 0 1.9-1.9M12 12.8l-1.9-1.9"/>',
    transcription: '<path d="M5 10.5v3M9 7.5v9M13 9.5v5M17 11.2v1.6"/>',
    chunking: '<rect x="4.5" y="5" width="6.4" height="14" rx="1.8"/><rect x="13.1" y="5" width="6.4" height="14" rx="1.8"/>',
    summary: '<path d="M12 3.9a5.3 5.3 0 0 0-2.7 9.9v2.2h5.4v-2.2A5.3 5.3 0 0 0 12 3.9Z"/><path d="M10 18.8h4"/>',
    archive: '<path d="M4.3 8.2h15.4v10.6a1.5 1.5 0 0 1-1.5 1.5H5.8a1.5 1.5 0 0 1-1.5-1.5V8.2Z"/><path d="M4.3 8.2 6 4.9h12l1.7 3.3"/><path d="M10 11.6h4"/>',
  };
  /* checkpoint 是持久化的细粒度标记，映射到阶段轴，供子行显示当前阶段。 */
  const JOB_CHECKPOINT_STAGE = {
    source_ready: "source", text_loaded: "source",
    transcribing: "transcription", transcript_ready: "transcription",
    chunking: "chunking", chunks_ready: "chunking",
    summarizing: "summary", summary_ready: "summary",
    archiving: "archive", indexing: "archive", indexed: "archive",
  };
  /* R1/11-17：全链路失败提示统一中文。后端 error_message 保留原始异常供诊断，
     用户可见区域一律走这张表，不回显英文原文与系统错误码。
     规则按优先级排列：先具体成因，后通用兜底；stage 用阶段轴同一套键。 */
  const FAILURE_RULES = [
    { match: "WinError 206", stage: "archive", reason: "归档目录或文件名超过系统长度上限，笔记无法写入", suggestion: "请在设置页缩短归档目录，或更换较短的标题后重试" },
    { match: "文件名或扩展名太长", stage: "archive", reason: "归档目录或文件名超过系统长度上限，笔记无法写入", suggestion: "请在设置页缩短归档目录，或更换较短的标题后重试" },
    { match: "WinError 3", stage: "archive", reason: "归档路径不可用，笔记写入失败", suggestion: "请检查归档目录是否存在、是否被移动，然后重试" },
    { match: "Errno 2", stage: "archive", reason: "归档路径不可用，笔记写入失败", suggestion: "请检查归档目录是否存在、是否被移动，然后重试" },
    { match: "No such file or directory", stage: "archive", reason: "归档路径不可用，笔记写入失败", suggestion: "请检查归档目录是否存在、是否被移动，然后重试" },
    { match: "Unable to allocate", stage: "transcription", reason: "本地语音识别内存不足，无法处理这段音频", suggestion: "请更换较短的视频，或关闭其他占用内存的程序后重试" },
    { match: "Unable to download webpage", stage: "source", reason: "来源页面或音频下载超时、连接被中断", suggestion: "这是网络波动，请稍后单独重试；避免多个任务同时导入" },
    { match: "UNEXPECTED_EOF_WHILE_READING", stage: "source", reason: "与来源站点的加密连接在传输中被中断", suggestion: "请检查网络后重试，连续多条同时导入容易触发" },
    { match: "read operation timed out", stage: "source", reason: "读取来源页面或音频时超时", suggestion: "请稍后单独重试；避免多个任务同时导入" },
    { match: "TransportError", stage: "source", reason: "下载来源音频时网络中断", suggestion: "请检查网络后重试" },
    { match: "Got error", stage: "source", reason: "来源音频下载失败", suggestion: "请稍后单独重试；反复失败请检查登录状态" },
    { match: "音频下载失败", stage: "source", reason: "来源音频下载失败", suggestion: "请稍后单独重试；反复失败请检查登录状态" },
    { match: "网页响应不完整", stage: "source", reason: "来源公开页返回内容不完整，没有取到页面信息", suggestion: "请稍后重试；连续多条同时导入容易触发，建议逐条进行" },
    { match: "HTTP 403", stage: "summary", reason: "总结模型拒绝访问：账号未开通该模型或额度不足", suggestion: "请在设置页更换已开通的模型，或检查账户额度" },
    { match: "AccessDenied", stage: "summary", reason: "总结模型拒绝访问：账号未开通该模型或额度不足", suggestion: "请在设置页更换已开通的模型，或检查账户额度" },
    { match: "无法连接总结服务", stage: "summary", reason: "无法连接总结服务", suggestion: "请检查网络、接口地址与密钥，在设置页测试连接后重试" },
    { match: "总结服务请求超时", stage: "summary", reason: "总结服务请求超时，没有及时返回结果", suggestion: "请稍后重试；反复超时可在设置页调大超时时间" },
    { match: "未产生可用总结内容", stage: "summary", reason: "总结模型没有返回可用的内容", suggestion: "请重试当前任务；反复出现请更换模型" },
    { match: "总结生成失败", stage: "summary", reason: "生成总结时失败", suggestion: "请重试当前任务；反复出现请更换模型" },
    { match: "没有返回转写文本", stage: "transcription", reason: "视频里没有识别到可转写的人声（纯音乐、纯画面演示或静音）", suggestion: "这类素材语音识别无法生成文字，重试不会改善，请更换有语音的内容" },
    { match: "缺少可转写的音频文件", stage: "source", reason: "没有找到可转写的音频文件", suggestion: "临时音频已过期或被清理，请重试让系统重新下载音频" },
    { match: "可转写的音频文件为空", stage: "source", reason: "下载到的音频文件是空的", suggestion: "请重试；反复出现请更换来源" },
    { match: "ASR 转写在 120 秒内未返回", stage: "transcription", reason: "语音识别超时，未在限定时间内返回结果", suggestion: "请重试当前任务；长视频建议分段处理" },
    { match: "asr_timeout", stage: "transcription", reason: "语音识别超时，未在限定时间内返回结果", suggestion: "请重试当前任务；长视频建议分段处理" },
    { match: "视频内容未完整识别", stage: "transcription", reason: "转写内容不完整，只覆盖了视频的一部分", suggestion: "请更换内容来源；反复重试同一来源通常不会改善" },
    { match: "transcript_incomplete", stage: "transcription", reason: "转写内容不完整，只覆盖了视频的一部分", suggestion: "请更换内容来源；反复重试同一来源通常不会改善" },
    { match: "没有公开字幕", stage: "source", reason: "该视频没有公开字幕，且没有配置语音识别", suggestion: "请在设置页配置或安装语音识别后重试" },
    { match: "没有可读取的", stage: "source", reason: "该视频没有可读取的公开字幕", suggestion: "请在设置页配置或安装语音识别后重试" },
    { match: "asr_runtime_unavailable", stage: "transcription", reason: "本地语音识别组件尚未安装", suggestion: "请在设置页安装本地语音识别组件后重试" },
    { match: "本地 ASR 组件尚未安装", stage: "transcription", reason: "本地语音识别组件尚未安装", suggestion: "请在设置页安装本地语音识别组件后重试" },
    { match: "asr_local_model_not_installed", stage: "transcription", reason: "本地语音识别模型尚未下载完成", suggestion: "请在设置页下载并选择一个模型后重试" },
    { match: "模型尚未下载完成", stage: "transcription", reason: "本地语音识别模型尚未下载完成", suggestion: "请在设置页下载并选择一个模型后重试" },
    { match: "asr_cloud_not_configured", stage: "source", reason: "没有配置云端语音识别", suggestion: "请在设置页配置云端语音识别，或改用本地模型" },
    { match: "disk_space", stage: "archive", reason: "磁盘空间不足，归档写入失败", suggestion: "请清理磁盘空间或更换归档目录后重试" },
    { match: "分段失败", stage: "chunking", reason: "内容分段处理失败，没有生成可用的分段", suggestion: "请重试当前任务；反复出现请更换内容来源" },
    { match: "分块失败", stage: "chunking", reason: "内容分段处理失败，没有生成可用的分段", suggestion: "请重试当前任务；反复出现请更换内容来源" },
    { match: "chunk", stage: "chunking", reason: "内容分段处理失败，没有生成可用的分段", suggestion: "请重试当前任务；反复出现请更换内容来源" },
    { match: "auth_required", stage: "source", reason: "来源平台需要登录后才能读取", suggestion: "请在设置页完成登录并重新检测来源" },
    { match: "access_restricted", stage: "source", reason: "来源平台限制了本次访问", suggestion: "请稍后再试，或在设置页完成登录后重新检测" },
    { match: "请先在设置页完成 B站二维码登录", stage: "source", reason: "来源平台需要登录后才能读取", suggestion: "请在设置页完成登录并重新检测来源" },
    { match: "source_not_found", stage: "source", reason: "找不到该来源，可能已删除或不可访问", suggestion: "请更换内容来源" },
    { match: "unsupported_source", stage: "source", reason: "当前版本无法处理这类来源", suggestion: "请更换内容来源" },
    { match: "model_unavailable", stage: "summary", reason: "总结模型当前不可用", suggestion: "请在设置页更换可用模型后重试" },
    { match: "invalid_output", stage: "summary", reason: "模型返回的内容格式不符合要求", suggestion: "请重试当前任务" },
    { match: "transient_network", stage: "source", reason: "网络连接中断，来源读取失败", suggestion: "请检查网络后重试" },
    { match: "URLError", stage: "source", reason: "网络连接中断，来源读取失败", suggestion: "请检查网络后重试" },
  ];
  /* R1/11-17：把任务失败翻译成「阶段 + 中文原因 + 下一步」，绝不回显原始英文。 */
  function humanizeFailure(job) {
    const raw = String(job?.error_message || "");
    const code = String(job?.error_code || "");
    const haystack = `${raw}\n${code}`;
    const rule = FAILURE_RULES.find((item) => haystack.includes(item.match));
    const stageKey = (rule && rule.stage)
      || JOB_CHECKPOINT_STAGE[String(job?.checkpoint || "")]
      || "";
    const stage = JOB_STAGE_LABEL[stageKey] || "处理";
    const reason = rule ? rule.reason : "任务在该阶段意外中止，系统没有拿到可解释的原因";
    const suggestion = rule ? rule.suggestion : "请重试当前任务；若反复失败，请保留诊断信息反馈";
    return { stage, stageKey, reason, suggestion, text: `【${stage}阶段】${reason}。${suggestion}` };
  }
  /* R1/11-17：接口返回的机器错误码／英文原文同样不直接甩给用户，覆盖所有操作类提示。 */
  function humanizeApiError(detail) {
    const raw = String(detail == null ? "" : detail).trim();
    if (!raw) return "操作未成功，请稍后重试";
    /* 11-22 R2：任务状态类机器码单独给出可行动文案，不再落进 snake_case 泛化分支。 */
    const TASK_CODE_TEXT = {
      job_not_deletable: "该任务状态暂不允许删除，请先取消再删除",
      job_not_retryable: "该任务状态不支持重试，请改用继续或先取消",
      job_not_cancellable: "该任务状态暂不允许取消，请刷新后重试",
    };
    if (TASK_CODE_TEXT[raw]) return TASK_CODE_TEXT[raw];
    if (FAILURE_RULES.some((item) => raw.includes(item.match))) {
      return humanizeFailure({ error_message: raw, error_code: "", checkpoint: "" }).text;
    }
    if (/^[a-z][a-z0-9_]*$/.test(raw)) return "操作未成功：该项当前不可用。请刷新后重试；若反复出现请查看诊断信息";
    if (/^HTTP \d+/.test(raw)) return "请求未成功，服务暂时不可用。请稍后重试";
    if (/^[\x00-\x7F]+$/.test(raw)) return "操作未成功：服务返回了无法识别的错误。请稍后重试，若反复出现请查看诊断信息";
    return raw;
  }
  /* R1/R3/R10：跨重绘保留滚动、展开与已选。 */
  const expandedCollections = new Set();
  const expandedJobs = new Set();
  const jobEvents = new Map();
  const jobViewLimit = new Map();
  /* 11-21 R1（v2）：批量操作锁。锁的范围覆盖「请求 → 刷新 → 重绘」整段，
     期间批量按钮、行内按钮、合集按钮都不接新操作，避免同一批任务被重复触发。 */
  let jobsBatchBusy = false;
  const jobActionsInFlight = new Map();
  const JOB_MUTATING_ACTS = new Set([
    "jobs-pause", "jobs-resume", "jobs-retry", "jobs-delete",
    "job-pause", "job-resume", "job-retry", "job-start",
    "job-group-pause", "job-group-delete",
  ]);

  function jobState(job) {
    // execution_state 是后端算好的用户可见状态：被抢占让出执行权的任务虽然存
    // 的是 paused，但对用户就是「排队中」，因为轮到它时会自动接力。
    // 11-18c R2：只有用户自己停的（含重启遗留）才是「已暂停」，必须点「继续」。
    const raw = String(job.execution_state || job.state || job.status || "").toLowerCase();
    let key = "waiting";
    if (raw === "completed") key = "completed";
    else if (raw === "running" || raw === "processing" || ["acquiring", "extracting", "transcribing", "chunking", "summarizing", "archiving", "indexing"].includes(raw)) key = "running";
    else if (raw === "switching") key = "switching";
    else if (raw === "paused") key = "paused";
    else if (raw === "failed" || raw === "error") key = "failed";
    else if (raw === "cancelled" || raw === "canceled") key = "cancelled";
    /* 队列已认领但还没进第一阶段的任务仍是 queued，接口按 state 报 waiting。
       补上队列的认领事实，顶部才不会出现「排队中」的真空帧。 */
    if (key === "waiting" && S.queue && S.queue.active_job_id === job.id) key = "running";
    let action = "查看结果", act = "job-open";
    if (key === "running" || key === "switching") { action = "暂停"; act = "job-pause"; }
    /* 11-18c R2：排队中 = 系统会自己接手（点它是插队抢占），已暂停 = 必须人点才走。 */
    else if (key === "waiting") { action = "插队"; act = "job-start"; }
    else if (key === "paused") { action = "继续"; act = "job-resume"; }
    else if (key !== "completed") { action = "重试"; act = "job-retry"; }
    return { key, label: JOB_STATE_LABEL[key], action, act };
  }
  function jobPlatform(job) {
    const matched = S.history.find((entry) => entry?.job?.id === job.id);
    return job.content_platform || contentOf(matched).platform || "";
  }
  function jobInFilter(job) {
    /* 11-18c R2：判据只有一条——系统还会不会自己接手。会 → 进行中（含排队中），
       不会 → 未完成（失败 / 已取消 / 已暂停）。 */
    const key = jobState(job).key;
    if (S.jobFilter === "all") return true;
    if (S.jobFilter === "completed") return key === "completed";
    if (S.jobFilter === "incomplete") return key === "failed" || key === "cancelled" || key === "paused";
    return key !== "completed" && key !== "failed" && key !== "cancelled" && key !== "paused";
  }
  /* 内容身份：重试沿用 content_id，缺失时用源地址+P 兜底。去重与排序锚点共用同一把键。 */
  function contentKey(job) {
    return job.content_id ? `content:${job.content_id}` : jobIdentity(job);
  }
  /* 内容首次入库时间：重试新建任务也不变，作为稳定排序锚点；缺失时退回任务创建时间。 */
  function jobAnchorTime(job) {
    return String(job.content_created_at || job.created_at || "");
  }
  function filteredJobs() {
    /* 11-21 R4：归并必须发生在筛选之前。重试会新建任务并共用 content_id，
       若先按「未完成」筛掉新的进行中任务，旧失败记录就会躲过归并、又留在失败区。
       先对全量按内容身份取最新一条，再套当前筛选，同一内容全局只保留一条。 */
    const latest = new Map();
    S.jobs.forEach((job) => {
      const mergeKey = contentKey(job);
      const previous = latest.get(mergeKey);
      if (!previous || String(job.created_at || "") >= String(previous.created_at || "")) {
        latest.set(mergeKey, job);
      }
    });
    // R10：全选范围 = 当前筛选结果，与列表用同一份归并后的筛选。
    return Array.from(latest.values()).filter(jobInFilter);
  }
  /* 合集标题去掉归档批次前缀（batch_<hex>-），只留用户能读的标题。 */
  function cleanCollectionTitle(value) {
    return String(value || "").replace(/^batch_[0-9a-f]{6,}-/i, "").trim();
  }
  /* 同一 BVID+P 的重试与重复导入归为一条；不同 P 各自保留，父集仍按 BVID 聚合。 */
  function jobIdentity(job) {
    const url = String(job.source_url || "");
    const matched = url.match(/\/(BV[0-9A-Za-z]{10})(?:\/|\?|$)/i);
    if (matched) {
      const page = new URL(url, window.location.href).searchParams.get("p") || "1";
      return `bili:${matched[1]}:p${page}`;
    }
    return job.content_id || job.source_url || job.id;
  }
  /* R2/裁定 B：父任务按 collection_id 聚合；无合集字段的单条任务平铺成一行。 */
  function jobCollections() {
    const buckets = new Map();
    /* 队列的运行时顺序比 job.queue_position 权威：持久化位置常常只有部分任务有值。 */
    const queueIndex = new Map(
      ((S.queue && Array.isArray(S.queue.items)) ? S.queue.items : [])
        .map((item) => [item.job_id, Number(item.queue_position)])
    );
    const queuePositionOf = (group) => {
      const live = queueIndex.get(group.jobs[0].id);
      if (Number.isFinite(live)) return live;
      const raw = group.jobs[0].queue_position;
      const stored = raw === null || raw === undefined ? NaN : Number(raw);
      return Number.isFinite(stored) ? stored : NaN;
    };
    /* 11-21 R3（v2）：排序锚点改用后端返回的内容首次入库时间（content_created_at）。
       它在重试、删除旧尝试、列表截断之后都不变，比在前端扫 S.jobs 取最早 created_at 稳。
       合集锚点取全量任务里的最早值，与当前筛选无关——切标签不改变同一组的位置。 */
    const groupAnchor = new Map();
    S.jobs.forEach((job) => {
      const key = job.collection_id || jobIdentity(job);
      const at = jobAnchorTime(job);
      const previous = groupAnchor.get(key);
      if (!previous || at < previous) groupAnchor.set(key, at);
    });
    /* 11-18b R4 / 11-21 R2（v2）：按内容取最新一条已由 filteredJobs() 统一完成。
       这里不再二次归并——同一份数据上重复归并是幂等空转，还会掩盖上游顺序问题。 */
    filteredJobs().forEach((job) => {
      /* 无合集时按内容身份分桶，恢复「重试项归原集」；job:<id> 会让每个任务独占一桶。 */
      const key = job.collection_id || jobIdentity(job);
      if (!buckets.has(key)) {
        buckets.set(key, { key, collectionId: job.collection_id || null, jobs: [] });
      }
      buckets.get(key).jobs.push(job);
    });
    const groups = [];
    buckets.forEach((bucket) => {
      // 重试项归原集：同一 BVID+P 只保留最新一条任务，避免重复导入显示成几十行。
      const latest = new Map();
      bucket.jobs.forEach((job) => {
        const identity = jobIdentity(job);
        const previous = latest.get(identity);
        if (!previous || String(job.created_at || "") >= String(previous.created_at || "")) {
          latest.set(identity, job);
        }
      });
      const jobs = Array.from(latest.values());
      // 原始序号：优先用归档序号，缺失时按创建先后补位，不重排用户看到的顺序含义。
      const createdOrder = jobs.slice()
        .sort((a, b) => String(a.created_at || "").localeCompare(String(b.created_at || "")));
      const fallbackOrder = new Map(createdOrder.map((job, index) => [job.id, index + 1]));
      const orderOf = (job) => {
        const numbered = Number(job.batch_item_number);
        return Number.isFinite(numbered) && numbered > 0 ? numbered : (fallbackOrder.get(job.id) || 0);
      };
      // 位置只由导入序号决定：成功或失败都不改变所在位置，队列按序号依次往前走。
      jobs.sort((a, b) => orderOf(a) - orderOf(b));
      const states = jobs.map((job) => jobState(job).key);
      const countOf = (key) => states.filter((item) => item === key).length;
      /* 11-18c R2：父集合行不再挂状态词，stateKey 只服务排序与分组；
         「部分失败」已删——「3 成功 + 2 取消」不再被误标成失败。 */
      let stateKey = "cancelled";
      if (states.includes("running") || states.includes("switching")) stateKey = "running";
      else if (states.includes("waiting")) stateKey = "running";
      else if (states.includes("paused")) stateKey = "paused";
      else if (states.length && countOf("completed") === states.length) stateKey = "completed";
      else if (countOf("failed") > 0) stateKey = "failed";
      const representative = jobs[0];
      // 只导入了一个 P 时不建空父集，仍按单条任务显示。
      const isCollection = Boolean(bucket.collectionId) && jobs.length > 1;
      const total = Number(representative.collection_total) || jobs.length;
      const completed = countOf("completed");
      const runningJob = jobs.find((job) => ["running", "switching"].includes(jobState(job).key));
      const current = runningJob ? orderOf(runningJob) : Math.min(total, completed + 1);
      /* 11-18c R2：两个区——组内还有会自己跑的任务（进行中 / 排队中）在最上，其余算已结束。
         已暂停不再单独占一区：它归「未完成」，要等用户点「继续」。 */
      const hasRunning = states.includes("running") || states.includes("switching");
      const hasQueued = states.includes("waiting");
      const zone = hasRunning || hasQueued ? 0 : 1;
      groups.push({
        key: bucket.key,
        collectionId: bucket.collectionId,
        isCollection,
        jobs,
        orderOf,
        zone,
        anchor: jobs.map(jobAnchorTime).sort()[0] || "",
        /* 组锚点独立于当前筛选：同一合集在「全部」与「未完成」下停在同一位置。 */
        sortAnchor: groupAnchor.get(bucket.key) || jobs.map(jobAnchorTime).sort()[0] || "",
        title: cleanCollectionTitle(representative.collection_title)
          || (isCollection ? `导入 ${jobs.length} 条` : jobTitle(representative)),
        total,
        completed,
        current,
        stateKey,
        hasRunning,
        createdAt: String(representative.created_at || ""),
      });
    });
    /* 有活任务的组在最上（跑着的先于排队的，排队按队列位次）；已结束的按内容首次入库时间倒序。
       锚点相同时用合集键兜底，顺序不再依赖后端返回顺序。 */
    const anchorOf = (group) => group.sortAnchor || group.anchor || "";
    groups.sort((a, b) => {
      if (a.zone !== b.zone) return a.zone - b.zone;
      if (a.zone === 0) {
        if (a.hasRunning !== b.hasRunning) return a.hasRunning ? -1 : 1;
        const posA = queuePositionOf(a);
        const posB = queuePositionOf(b);
        const liveA = Number.isFinite(posA), liveB = Number.isFinite(posB);
        if (liveA && liveB && posA !== posB) return posA - posB;
        if (liveA !== liveB) return liveA ? -1 : 1;
        return anchorOf(a).localeCompare(anchorOf(b)) || String(a.key).localeCompare(String(b.key));
      }
      return anchorOf(b).localeCompare(anchorOf(a)) || String(a.key).localeCompare(String(b.key));
    });
    return groups;
  }
  function jobStagesHtml(job) {
    const state = jobState(job);
    const events = jobEvents.get(job.id);
    if (!events) return `<div class="job-stages"><p class="job-stages__hint">正在读取阶段…</p></div>`;
    const latest = new Map();
    events.forEach((event) => { if (event.stage) latest.set(event.stage, event); });
    const reached = JOB_STAGE_ORDER.filter((stage) => latest.has(stage));
    const lastReached = reached[reached.length - 1] || "";
    /* 11-17 R3：五段等宽合成一条轨道。已完成段满格、当前段按百分比、未到段留空。 */
    const segs = JOB_STAGE_ORDER.map((stage) => {
      const event = latest.get(stage);
      const current = stage === lastReached;
      // R6：该阶段之后已有新阶段就说明它已走完；未执行阶段不带任何完成态。
      const done = Boolean(event) && (state.key === "completed" || !current);
      const failed = Boolean(event) && current && state.key === "failed";
      const paused = Boolean(event) && current && state.key === "paused";
      const progress = event && Number.isFinite(Number(event.progress))
        ? Math.max(0, Math.min(100, Number(event.progress))) : null;
      const cls = failed ? "is-failed" : paused ? "is-paused" : done ? "is-done" : event ? "is-active" : "";
      // R6：没有数据就不画进度。
      const width = done ? 100 : (progress == null ? 0 : progress);
      return `<li class="job-stage ${cls}"><span class="job-stage__bar"><span style="width:${width}%"></span></span></li>`;
    }).join("");
    const labels = JOB_STAGE_ORDER.map((stage) => {
      const event = latest.get(stage);
      const current = stage === lastReached;
      const progress = event && Number.isFinite(Number(event.progress))
        ? Math.max(0, Math.min(100, Number(event.progress))) : null;
      const cls = current && state.key === "failed" ? "is-failed"
        : current && state.key === "paused" ? "is-paused"
          : current ? "is-active" : event ? "is-done" : "";
      // R6：百分比只写当前段，已完成段不重复数字。
      const pct = current && state.key !== "failed" && progress != null ? ` ${progress}%` : "";
      return `<span class="job-stage__label ${cls}">${esc(JOB_STAGE_LABEL[stage] || stage)}${pct}</span>`;
    }).join("");
    /* 11-17 R3：只有当前段挂符号，位置由阶段序号决定，和轨道等宽列对齐。 */
    const stageIndex = JOB_STAGE_ORDER.indexOf(lastReached);
    const mark = stageIndex < 0 ? "" : `<div class="job-stages__marks"><span class="job-stages__mark ${
      state.key === "failed" ? "is-failed" : state.key === "paused" ? "is-paused" : state.key === "completed" ? "is-done" : ""
    }" style="grid-column:${stageIndex + 1}"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${
      JOB_STAGE_ICON[lastReached] || ""}</svg></span></div>`;
    let note = "";
    if (state.key === "waiting") {
      // 11-18 R2：排队改在状态行显示且只在展开态出现；这里只留恢复建议，避免同屏重复。
      note = job.recovery_suggestion || "等待前序任务结束";
    } else if (state.key === "failed") {
      // 11-17 R1：不再展示后端原始英文异常，改为「阶段 + 中文原因 + 下一步」。
      note = humanizeFailure(job).text;
    } else if (state.key === "paused") {
      const pausedStage = JOB_CHECKPOINT_STAGE[job.checkpoint];
      note = `已暂停在「${JOB_STAGE_LABEL[pausedStage] || "当前阶段"}」`;
    }
    /* 整条轨道作为一个进度条朗读，不逐段念五个数字。 */
    const overallProof = stageIndex < 0 ? null : (() => {
      const event = latest.get(lastReached);
      const progress = event && Number.isFinite(Number(event.progress))
        ? Math.max(0, Math.min(100, Number(event.progress))) : 0;
      return {
        value: Math.round(((stageIndex + progress / 100) / JOB_STAGE_ORDER.length) * 100),
        text: `${JOB_STAGE_LABEL[lastReached] || lastReached} ${progress}%，第 ${stageIndex + 1} / ${JOB_STAGE_ORDER.length} 阶段`,
      };
    })();
    const attrs = overallProof
      ? ` role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${overallProof.value}" aria-valuetext="${esc(overallProof.text)}"`
      : "";
    return `<div class="job-stages"${attrs}>${mark}<ol class="job-stage-list">${segs}</ol><div class="job-stage-labels">${labels}</div>${note ? `<p class="job-stages__hint">${esc(note)}</p>` : ""}</div>`;
  }
  /* 11-18 R2：排队位次以运行时队列为准，持久化 queue_position 只作回退。 */
  function jobQueueBadge(job) {
    const items = (S.queue && Array.isArray(S.queue.items)) ? S.queue.items : [];
    const index = items.findIndex((item) => item.job_id === job.id);
    const position = index >= 0 ? index + 1 : Number(job.queue_position);
    const total = items.length || (Number.isFinite(position) && position > 0 ? position : 0);
    return Number.isFinite(position) && position > 0 && total > 0
      ? `排队 第${position}/共${total}` : "等待前序任务结束";
  }
  function jobCover(job, cornerText) {
    return coverHtml({ id: job.content_id, platform: jobPlatform(job), title: job.content_title, thumbnail_url: job.thumbnail_url }, false, cornerText);
  }
  function jobRowHtml(job, options = {}) {
    const state = jobState(job);
    const pendingAction = jobActionsInFlight.get(job.id);
    const actionDisabled = Boolean(pendingAction || jobsBatchBusy);
    const expanded = expandedJobs.has(job.id);
    const selected = S.selectedJobs.has(job.id);
    const note = options.index ? `<span class="job-index">${esc(String(options.index))}</span>` : "";
    const stageKey = JOB_CHECKPOINT_STAGE[job.checkpoint] || "";
    const stage = stageKey ? JOB_STAGE_LABEL[stageKey] : "";
    /* 11-17 R2：失败态收起时也能看到阶段与中文原因，不用先展开阶段轴。 */
    const failure = state.key === "failed" ? humanizeFailure(job) : null;
    /* 只有等待中的任务能被拖拽换位；进行中、已结束的位置由状态决定。 */
    const draggable = !options.child && options.zone === 1 && state.key === "waiting";
    /* 11-18 R2：排队只在按下阶段、展开之后出现，接在状态行右侧而非进度轴中央。 */
    const queueBadge = expanded && state.key === "waiting" ? jobQueueBadge(job) : "";
    const stageLabel = expanded ? "收起阶段" : "展开阶段";
    return `<div class="job-card ${options.child ? "job-card--child" : ""} ${selected ? "is-selected" : ""}"${draggable ? ` draggable="true" data-drag-job="${esc(job.id)}"` : ""} role="listitem">
      <input class="job-card__pick" type="checkbox" data-job-pick="${esc(job.id)}" ${selected ? "checked" : ""} aria-label="选择任务" />
      ${note}
      ${options.child ? "" : jobCover(job)}
      <div class="job-card__main"><div>
        <div class="job-card__title" title="${esc(jobTitle(job))}">${esc(jobTitle(job))}</div>
        <div class="job-card__meta">
          <span class="job-state" data-state="${state.key}" aria-label="任务状态：${state.label}">${state.label}</span>
          ${stage && state.key !== "completed" ? `<span class="job-card__stage">${esc(stage)}</span>` : ""}
          ${queueBadge ? `<span class="job-card__queue">${esc(queueBadge)}</span>` : ""}
        </div>
        ${failure ? `<div class="job-card__failure" title="${esc(failure.text)}">${esc(failure.text)}</div>` : ""}
      </div></div>
      <button class="link-btn job-stage-toggle" type="button" data-act="job-stage" data-job-id="${esc(job.id)}" aria-expanded="${expanded}" aria-label="${stageLabel}" title="${stageLabel}"><svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg></button>
      <button class="btn btn--quiet" type="button" data-act="${state.act}" data-job-id="${esc(job.id)}"${actionDisabled ? " disabled" : ""}>${esc(pendingAction || state.action)}</button>
      ${expanded ? jobStagesHtml(job) : ""}
    </div>`;
  }
  function collectionRowHtml(group) {
    const expanded = expandedCollections.has(group.key);
    const limit = jobViewLimit.get(group.key) || JOB_PAGE_SIZE;
    const shown = expanded ? group.jobs.slice(0, limit) : [];
    const everySelected = group.jobs.every((job) => S.selectedJobs.has(job.id));
    const someSelected = !everySelected && group.jobs.some((job) => S.selectedJobs.has(job.id));
    /* 11-18 R1：下拉入口移到「已完成」旁，封面直接接复选框，前端与普通行对齐。 */
    const expandBtn = `<button class="job-expand" type="button" data-act="job-expand" data-group-key="${esc(group.key)}" aria-expanded="${expanded}" aria-label="${expanded ? "收起视频集" : "展开视频集"}"><svg class="ico"><use href="#i-${expanded ? "down" : "chev-right"}"/></svg></button>`;
    const head = `<div class="job-card job-card--group ${everySelected ? "is-selected" : ""}" role="listitem">
      <input class="job-card__pick" type="checkbox" data-job-group="${esc(group.key)}" data-group-state="${someSelected ? "some" : "all"}" ${everySelected ? "checked" : ""} aria-label="选择整集" />
      ${jobCover(group.jobs[0], "合集")}
      <div class="job-card__main"><div>
        <div class="job-card__title" title="${esc(group.title)}">${esc(group.title)}</div>
        <div class="job-card__note">第 ${group.current} 项 · 已完成 ${group.completed} / ${group.total}</div>
      </div></div>
      ${expandBtn}
      <button class="btn btn--quiet" type="button" data-act="job-group-pause" data-group-key="${esc(group.key)}">暂停整集</button>
      <button class="btn btn--quiet" type="button" data-act="job-group-delete" data-group-key="${esc(group.key)}">删除整集</button>
      <span class="job-card__count">${group.jobs.length} 项</span>
    </div>`;
    if (!expanded) return head;
    const children = shown.map((job) => jobRowHtml(job, { child: true, index: group.orderOf(job) })).join("");
    const more = group.jobs.length > shown.length
      ? `<button class="job-more" type="button" data-act="job-expand-more" data-group-key="${esc(group.key)}">继续展开</button>`
      : "";
    return `${head}<div class="job-children">${children}${more}</div>`;
  }
  /* 任务页进入后状态不会自己变：可见且有未结束任务时每 4 秒刷新一次列表。
     刷新只换状态标签，位置由导入序号决定，不重排。 */
  /* 11-22：paused 计入终态——页面只剩暂停任务时它不会自行变化（必须点继续），
     继续/重试等入口都走 syncJobsAfterMutation 显式刷新，不需要轮询空转。 */
  const JOB_TERMINAL_STATES = new Set(["completed", "failed", "cancelled", "paused"]);
  let jobsWatchTimer = null;
  let dragJobId = null;
  function stopJobsWatch() {
    if (jobsWatchTimer) clearTimeout(jobsWatchTimer);
    jobsWatchTimer = null;
  }
  function startJobsWatch() {
    stopJobsWatch();
    if (S.route !== "tasks") return;
    jobsWatchTimer = setTimeout(jobsWatchTick, 4000);
  }
  function jobsSignature() {
    const states = (S.jobs || []).map((job) => `${job.id}:${job.state}:${job.progress}:${job.checkpoint}:${job.error_code}`).join("|");
    const queue = ((S.queue && Array.isArray(S.queue.items)) ? S.queue.items : [])
      .map((item) => item.job_id).join(",");
    return `${states}#${queue}`;
  }
  async function jobsWatchTick() {
    jobsWatchTimer = null;
    if (S.route !== "tasks") return;
    if (dragJobId) { jobsWatchTimer = setTimeout(jobsWatchTick, 4000); return; }   // 拖拽中不重绘
    const live = S.jobs.some((job) => !JOB_TERMINAL_STATES.has(jobState(job).key));
    if (document.visibilityState === "visible" && !S.jobEditMode && live) {
      const before = jobsSignature();
      await Promise.all([refresh("jobs", { quiet: true }), refresh("queue", { quiet: true })]);
      // 状态没变就不重绘，避免整列表每几秒重建一次。
      if (S.route === "tasks" && jobsSignature() !== before) { renderJobs({ keepOrder: true }); return; }
    }
    jobsWatchTimer = setTimeout(jobsWatchTick, 4000);
  }
  /* 轮询重绘保持组顺序：队列位次每完成一项就整体前移，按它排序会让整列表跳动。
     唯一例外是「当前位」——正在跑的组；没有运行项时取队列第一个。它永远固定在最上，
     上一条结束后下一条即使还在待机也立刻顶上来。 */
  let lastGroupOrder = new Map();
  function currentGroupKey(groups) {
    const running = groups.find((group) => group.hasRunning);
    if (running) return running.key;
    const queueIds = ((S.queue && Array.isArray(S.queue.items)) ? S.queue.items : [])
      .map((item) => item.job_id);
    for (const id of queueIds) {
      const hit = groups.find((group) => group.jobs.some((job) => job.id === id));
      if (hit) return hit.key;
    }
    const waiting = groups.find((group) => group.jobs.some((job) => jobState(job).key === "waiting"));
    return waiting ? waiting.key : "";
  }
  function renderJobs(options = {}) {
    const list = $("#jobs-list");
    const scrollTop = list.scrollTop;
    const groups = jobCollections();
    if (options.keepOrder && lastGroupOrder.size) {
      /* 轮询只更新状态：当前位固定最上，其余组保持原位，新出现的组追加末尾。 */
      const current = currentGroupKey(groups);
      const rank = (group) => {
        if (group.key === current) return -1;
        return lastGroupOrder.has(group.key) ? lastGroupOrder.get(group.key) : 9999;
      };
      groups.sort((a, b) => rank(a) - rank(b));
    }
    lastGroupOrder = new Map(groups.map((group, index) => [group.key, index]));
    const totalJobs = groups.reduce((sum, group) => sum + group.jobs.length, 0);
    $("#jobs-total").textContent = `共 ${totalJobs} 项`;
    // C5：常驻复选框 DOM，编辑态由 #jobs-list.is-editing 切换显隐（默认零占位）。
    list.classList.toggle("is-editing", S.jobEditMode);
    list.innerHTML = groups.length ? groups.map((group) =>
      (group.isCollection ? collectionRowHtml(group) : jobRowHtml(group.jobs[0], { zone: group.zone }))).join("")
      : `<div class="card" style="color:var(--ink-3)">当前筛选下没有任务</div>`;
    /* 11-21 R1（v2）：批量操作未走完时，重绘出来的行内按钮同样保持禁用。 */
    if (jobsBatchBusy || S.jobsRefreshing) {
      $$("#jobs-list [data-act]", list).forEach((button) => {
        if (JOB_MUTATING_ACTS.has(button.dataset.act)) button.disabled = true;
      });
    }
    // R10：父集半选由 DOM 属性表达，重绘后按已选状态回填。
    $$("[data-job-group]", list).forEach((box) => {
      const group = groups.find((item) => item.key === box.dataset.jobGroup);
      if (!group) return;
      const picked = group.jobs.filter((job) => S.selectedJobs.has(job.id)).length;
      box.indeterminate = picked > 0 && picked < group.jobs.length;
    });
    list.scrollTop = scrollTop;   // R1：重排后保留滚动位置
    renderJobsToolbar();
    startJobsWatch();
  }
  function visibleJobIds() {
    // R10：全选与「共 N 项」用同一批去重后的代表任务，重试产生的重复任务不参与。
    return jobCollections().flatMap((group) => group.jobs.map((job) => job.id));
  }
  function renderJobsToolbar() {
    const editing = S.jobEditMode;
    $("#jobs-edit-btn").textContent = editing ? "退出编辑" : "编辑";
    $("#jobs-refresh-btn").hidden = editing;
    $("#jobs-refresh-btn").disabled = S.jobsRefreshing;
    $("#jobs-refresh-btn").textContent = S.jobsRefreshing ? "刷新中…" : "刷新列表";
    $("#jobs-batch-inline").hidden = !(editing && S.selectedJobs.size > 0);
    $("#jobs-selected-inline").textContent = `已选 ${S.selectedJobs.size} 项`;
    const selectAll = $("#jobs-select-all");
    if (selectAll) {
      selectAll.hidden = !editing;
      const visible = visibleJobIds();
      const allPicked = visible.length > 0 && visible.every((id) => S.selectedJobs.has(id));
      selectAll.textContent = allPicked ? "取消全选" : "全选";
      selectAll.disabled = visible.length === 0;
    }
  }
  /* 11-22 R2/R3：唯一删除路径——批量删除与「舍弃」共用，复用现成 cancel+DELETE
     两端点，不新增接口。终态直接 DELETE；paused→cancel→DELETE；
     running/waiting/switching→pause 成功后走 cancel→DELETE（pause 失败计入 skip）。
     cancel 成功但 DELETE 失败 → 任务已是 cancelled 终态、未卡中间态，返回 cancelled:true，
     再次点删除会按终态直接 DELETE 完成清理（重试安全）。 */
  async function deleteJobWithState(job) {
    const id = job?.id;
    if (!id) return { ok: false, reason: "missing-id" };
    const key = jobState(job).key;
    try {
      if (["running", "switching", "waiting"].includes(key)) {
        try { await post(`/jobs/${id}/pause`, {}); }
        catch (error) { return { ok: false, skipped: true, reason: error.message }; }
      }
      if (["paused", "running", "switching", "waiting"].includes(key)) {
        await post(`/jobs/${id}/cancel`, {});
        try {
          await del(`/jobs/${id}`);
          return { ok: true, mode: key === "paused" ? "cancel-delete" : "pause-cancel-delete" };
        } catch (error) {
          return { ok: false, cancelled: true, reason: error.message };
        }
      }
      await del(`/jobs/${id}`);
      return { ok: true, mode: "direct-delete" };
    } catch (error) {
      return { ok: false, reason: error.message };
    }
  }
  /* 11-22 R1：服务端判重（活跃归档口径 + 两层匹配）。失败返回 null，调用方跳过
     查重弹窗、直接走原流程，不让判重接口故障阻断批量操作。 */
  async function checkDuplicateJobs(ids) {
    try {
      const result = await post("/jobs/duplicate-check", { job_ids: ids });
      return Array.isArray(result?.items) ? result.items : [];
    } catch (error) {
      console.warn("[duplicate-check]", error.message);
      return null;
    }
  }
  /* 11-22 R4：继续导入——走现成 resummarize 管线新建带「（N）」后缀内容，
     返回新 job id；同一 matched_content_id 只调用一次（由 runBatch 去重）。 */
  async function resummarizeDuplicate(matchedContentId) {
    const result = await post(`/contents/${encodeURIComponent(matchedContentId)}/resummarize`, {});
    return result?.job?.id || "";
  }

  async function runJobRowAction(jobId, pendingLabel, request, feedback) {
    if (jobsBatchBusy) return toast("上一批操作还在进行中，请稍候");
    if (jobActionsInFlight.has(jobId)) return;
    const activeBefore = S.queue?.active_job_id || null;
    jobActionsInFlight.set(jobId, pendingLabel);
    renderJobs();
    try {
      const result = await request();
      const refreshed = await syncJobsAfterMutation({ quiet: true });
      if (!refreshed) return toast("状态刷新失败，请刷新任务列表");
      const job = (S.jobs || []).find((item) => item.id === jobId) || null;
      const state = job ? jobState(job).key : "";
      toast(feedback({ result, state, job, activeBefore, queue: S.queue }));
    } catch (error) {
      toast(error.message);
    } finally {
      jobActionsInFlight.delete(jobId);
      renderJobs();
    }
  }

  async function jobAction(action) {
    /* 11-21 R1（v2）：锁一直持有到刷新与重绘结束，刷新窗口期不再接同一批操作。 */
    if (jobsBatchBusy) return toast("上一批操作还在进行中，请稍候");
    /* 11-18c R3：批量按列表顺序接力，不按勾选顺序——否则队列里的先后跟用户看到的相反。 */
    const listOrder = new Map((S.jobs || []).map((job, index) => [job.id, index]));
    const ids = Array.from(S.selectedJobs)
      .sort((a, b) => (listOrder.get(a) ?? 0) - (listOrder.get(b) ?? 0));
    if (!ids.length) return toast("请先勾选任务");
    const route = { pause: "pause", resume: "resume", retry: "retry", delete: "" }[action];
    /* 批量继续走队尾（front=false）；单条行内「继续」仍默认插队。 */
    const query = action === "resume" ? "?front=false" : "";
    const batchButtons = $$('#jobs-batch-inline [data-act]');
    jobsBatchBusy = true;
    batchButtons.forEach((button) => { button.disabled = true; });
    /* R5：锁的三条释放路径都收敛到 finish——① 动作执行完 ② Esc/遮罩 ③ 执行中失败。
       finish 幂等，弹窗期间锁保持，勾选集在 dismiss 时保留。 */
    const retryProgress = $("#jobs-batch-progress");
    const showRetryProgress = (message) => {
      retryProgress.hidden = false;
      retryProgress.textContent = message;
    };
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      if (action === "retry") retryProgress.hidden = true;
      jobsBatchBusy = false;
      batchButtons.forEach((button) => { button.disabled = false; });
      $$("#jobs-list [data-act]").forEach((button) => {
        if (JOB_MUTATING_ACTS.has(button.dataset.act)) button.disabled = false;
      });
      renderJobsToolbar();
    };

    /* plan = null 或 { mode: "import"|"discard", dupById, handledContents? }。
       import 按 matched_content_id 去重，同批同内容只建一份副本。 */
    const runBatch = async (plan) => {
      const mode = plan?.mode || "";
      /* 成功与失败分开计数：慢请求不等于卡死，失败项也要在进度里看得见。 */
      let ok = 0;
      let failed = 0;
      let resumed = 0;
      let skipped = 0;
      let directDeleted = 0;
      let cancelDeleted = 0;
      let deleteSkipped = 0;
      let imported = 0;
      let discarded = 0;
      let cleanupFailed = 0;
      let pauseConfirmed = 0;
      let pauseUnconfirmed = 0;
      let resumeQueued = 0;
      let resumeStarted = 0;
      let resumeUnconfirmed = 0;
      let refreshFailed = 0;
      const retriedIds = [];
      /* R7：逐项记录旧→新 job ID，迁移点以服务端返回的新 ID 为准，
         最终用两个 ID 分别核对「新卡进入进行区」与「旧卡离开失败区」。 */
      const retryPairs = [];
      try {
        if (action === "retry") showRetryProgress(`正在重试 ${ids.length} 项…`);
        for (let index = 0; index < ids.length; index += 1) {
          const id = ids[index];
          /* 请求发出前先报「第几项」，单条慢请求期间反馈也不会断。 */
          if (action === "retry") {
            showRetryProgress(`正在重试第 ${index + 1}/${ids.length} 项（成功 ${ok}，失败 ${failed}）`);
          }
          let changed = false;
          try {
            const item = (S.jobs || []).find((jobItem) => jobItem.id === id) || {};
            const dup = plan?.dupById.get(id);
            if (dup && mode === "discard") {
              /* R3 舍弃：与批量删除共用 deleteJobWithState，只删任务不动 content。 */
              const result = await deleteJobWithState(item);
              if (result.ok) { discarded += 1; ok += 1; }
              else { failed += 1; }
            } else if (dup && mode === "import") {
              /* R4 继续导入：走 resummarize 新建带「（N）」后缀内容；同批同内容一份副本。 */
              const contentKey = dup.matched_content_id || id;
              if (!plan.handledContents.has(contentKey)) {
                plan.handledContents.add(contentKey);
                const newId = await resummarizeDuplicate(contentKey);
                if (newId) {
                  imported += 1;
                  ok += 1;
                  retriedIds.push(newId);
                  /* 新任务成功入队后才清理同一内容的全部旧任务。 */
                  ids.forEach((siblingId) => {
                    const siblingDup = plan.dupById.get(siblingId);
                    if (siblingDup && (siblingDup.matched_content_id || siblingId) === contentKey) {
                      plan.handledContents.add(siblingId);
                    }
                  });
                  for (const siblingId of ids) {
                    const siblingDup = plan.dupById.get(siblingId);
                    if (!siblingDup || (siblingDup.matched_content_id || siblingId) !== contentKey) continue;
                    const clean = await deleteJobWithState((S.jobs || []).find((jobItem) => jobItem.id === siblingId) || {});
                    if (clean.ok) discarded += 1; else cleanupFailed += 1;
                  }
                } else {
                  failed += 1;
                }
              }
            } else if (action === "delete") {
              /* R2：三态分流——终态直接删，暂停 cancel→删，进行中 pause→cancel→删。
                 失败原因由 humanizeApiError 呈现，四类结果分别计数。 */
              const result = await deleteJobWithState(item);
              if (result.ok) {
                ok += 1;
                if (result.mode === "direct-delete") directDeleted += 1;
                else cancelDeleted += 1;
              } else if (result.skipped) deleteSkipped += 1;
              else failed += 1;
            } else if (action === "retry") {
              /* 11-22：后端 /retry 只接受 failed/cancelled，暂停任务返回 409 job_not_retryable。
                 按每项当前状态分流：暂停→继续（resume，返回 JobResponse.id），
                 排队/进行中→跳过（系统本就会接手，重试无意义），其余才走 retry（返回 ImportResponse.job.id）。 */
              const current = jobState(item).key;
              if (current === "paused") {
                const result = await post(`/jobs/${id}/resume?front=false`, {});
                resumed += 1;
                if (result?.id) retriedIds.push(result.id);
              } else if (["running", "switching", "waiting", "completed"].includes(current)) {
                skipped += 1;
              } else {
                const result = await post(`/jobs/${id}/retry`, {});
                if (result?.job?.id) {
                  retriedIds.push(result.job.id);
                  retryPairs.push({ oldId: id, newId: result.job.id });
                }
              }
              ok += 1;
            } else {
              const result = await post(`/jobs/${id}/${route}${query}`, {});
              ok += 1;
            }
            changed = true;
          } catch (error) {
            failed += 1;
            console.warn("[jobAction]", id, error.message);
          }
          if (changed) {
            /* 11-22：每项成功后立即刷新 jobs+queue 并重绘。四类批量动作都会改变
               任务的筛选归属（继续/重试离开未完成区、暂停进入未完成区、删除消失），
               等整批结束才刷会让前几项滞留在原区。 */
            const refreshed = await syncJobsAfterMutation({ quiet: true });
            if (!refreshed) refreshFailed += 1;
            else if (action === "pause" || action === "resume") {
              const latest = (S.jobs || []).find((jobItem) => jobItem.id === id);
              const key = latest ? jobState(latest).key : "";
              if (action === "pause") {
                if (key === "paused") pauseConfirmed += 1;
                else pauseUnconfirmed += 1;
              } else if (key === "waiting") resumeQueued += 1;
              else if (key === "running") resumeStarted += 1;
              else resumeUnconfirmed += 1;
            }
          }
          if (action === "retry") {
            showRetryProgress(`已处理 ${index + 1}/${ids.length} 项（成功 ${ok}，失败 ${failed}）`);
          }
        }
        S.selectedJobs.clear();
        const finalRefreshed = await syncJobsAfterMutation({ quiet: true });
        if (!finalRefreshed) refreshFailed += 1;
        if (action === "retry") {
          if (!finalRefreshed) {
            const parts = [`已处理 ${ok}/${ids.length} 项`];
            if (failed) parts.push(`${failed} 项请求失败`);
            parts.push("状态刷新失败，结果未核实");
            toast(parts.join("，"));
            return;
          }
          /* 最终提示只报刷新后核对到的结果：HTTP 成功不等于真的进了进行区。 */
          const stateOf = (jobId) => {
            const job = (S.jobs || []).find((item) => item.id === jobId);
            return job ? jobState(job).key : "";
          };
          const liveKeys = ["running", "switching", "waiting"];
          const endedKeys = ["completed", "failed", "cancelled", "paused"];
          const entered = retriedIds.filter((jobId) => liveKeys.includes(stateOf(jobId))).length;
          const ended = retriedIds.filter((jobId) => endedKeys.includes(stateOf(jobId))).length;
          const missing = retriedIds.length - entered - ended;
          /* R7：新版进入进行区后，旧失败卡应被按内容归并顶掉；不整批隐藏，
             只按每个旧 ID 的真实展示结果核对，避免掩盖未刷新或再次失败。 */
          const shownIds = new Set(filteredJobs().map((job) => job.id));
          const oldStillShown = retryPairs.filter((pair) => shownIds.has(pair.oldId)).length;
          const parts = [`已进入进行区 ${entered} 项`];
          if (oldStillShown) parts.push(`${oldStillShown} 项旧卡仍在原区`);
          if (imported) parts.push(`${imported} 项已生成带序号副本`);
          if (discarded) parts.push(`${discarded} 项重复任务已舍弃`);
          if (cleanupFailed) parts.push(`${cleanupFailed} 项副本已生成但旧任务待清理`);
          if (resumed) parts.push(`${resumed} 项已暂停转继续`);
          if (skipped) parts.push(`${skipped} 项进行中/已完成已跳过`);
          if (failed) parts.push(`${failed} 项请求失败`);
          if (ended) parts.push(`${ended} 项已结束`);
          if (missing > 0) parts.push(`${missing} 项未出现在列表中`);
          toast(parts.join("，"));
        } else if (mode === "import" || mode === "discard") {
          const parts = [];
          if (imported) parts.push(`继续导入 ${imported} 份副本`);
          if (discarded) parts.push(`舍弃 ${discarded} 条重复任务`);
          if (cleanupFailed) parts.push(`${cleanupFailed} 项旧任务待清理，可再次舍弃`);
          if (resumed) parts.push(`${resumed} 项已暂停转继续`);
          if (skipped) parts.push(`${skipped} 项已跳过`);
          if (failed) parts.push(`${failed} 项请求失败`);
          toast(parts.length ? parts.join("，") : "没有可处理的项目");
        } else if (action === "delete") {
          /* R2 四类反馈：直接删除 N / 暂停转取消删除 M / 跳过 K / 失败 J。 */
          const parts = [`直接删除 ${directDeleted} 项`];
          if (cancelDeleted) parts.push(`暂停转取消删除 ${cancelDeleted} 项`);
          if (deleteSkipped) parts.push(`跳过保留 ${deleteSkipped} 项`);
          if (failed) parts.push(`失败 ${failed} 项`);
          toast(parts.join("，"));
        } else if (action === "pause") {
          const parts = [`已暂停 ${pauseConfirmed} 项`];
          if (pauseUnconfirmed) parts.push(`${pauseUnconfirmed} 项状态未确认`);
          if (failed) parts.push(`${failed} 项操作失败`);
          if (refreshFailed) parts.push(`${refreshFailed} 次状态刷新失败`);
          toast(parts.join("，"));
        } else if (action === "resume") {
          const parts = [`已重新排队 ${resumeQueued} 项`, `已开始处理 ${resumeStarted} 项`];
          if (resumeUnconfirmed) parts.push(`${resumeUnconfirmed} 项状态未确认`);
          if (failed) parts.push(`${failed} 项操作失败`);
          if (refreshFailed) parts.push(`${refreshFailed} 次状态刷新失败`);
          toast(parts.join("，"));
        } else {
          toast(`已处理 ${ok}/${ids.length} 项${failed ? `，${failed} 项未成功` : ""}`);
        }
      } finally {
        finish();
      }
    };

    /* R1：重试/继续前服务端判重；删除入口不弹查重（唯一口径）。查重失败返回 null，
       不阻断、直接走原流程，避免判重接口故障拖垮批量操作。 */
    if (action === "retry" || action === "resume") {
      const checked = await checkDuplicateJobs(ids);
      if (checked) {
        const dupById = new Map();
        const byContent = new Map();
        checked.forEach((entry) => {
          if (!entry?.is_duplicate) return;
          dupById.set(entry.job_id, entry);
          const key = entry.matched_content_id || entry.job_id;
          if (!byContent.has(key)) byContent.set(key, { title: entry.matched_title || "未命名内容", count: 0 });
          byContent.get(key).count += 1;
        });
        if (dupById.size) {
          const allLines = [];
          byContent.forEach((group) => allLines.push(`《${group.title}》— ${group.count} 条任务命中`));
          const lines = allLines.slice(0, 8);
          if (allLines.length > 8) lines.push(`……等 ${allLines.length} 条内容`);
          const summary = `选中 ${ids.length} 项中有 ${dupById.size} 条在知识库已有内容（${byContent.size} 条内容）。继续导入将新建 ${byContent.size} 份带序号副本并移除对应旧任务；舍弃则只移除这 ${dupById.size} 条任务、知识库内容保留。其余任务照常处理。`;
          requestTriageConfirmation(
            summary, lines,
            () => runBatch({ mode: "import", dupById, handledContents: new Set() }),
            () => runBatch({ mode: "discard", dupById }),
            () => finish(),
          );
          return;
        }
      }
    }
    return runBatch(null);
  }
  async function loadJobStages(jobId) {
    try {
      jobEvents.set(jobId, await api(`/jobs/${encodeURIComponent(jobId)}/events`));
    } catch (error) {
      /* 11-22：失败不能写空数组缓存——[] 会让加载骨架消失、渲染出空白轨道，
         且缓存命中后再点展开也不重试。删掉条目保留重试能力，错误交给 toast。 */
      jobEvents.delete(jobId);
      toast(`读取阶段失败：${error.message}`);
    }
    renderJobs();
  }

  /* ------------------------- 图三：知识库 ------------------------- */
  function libraryEntries() {
    const query = S.libQuery.trim().toLowerCase();
    const ctx = {
      tagIds: S.activeTagIds, folderIds: S.activeFolderIds, filters: S.libFilters,
      mode: S.libMode, modeKind: S.libModeKind, modeTargetId: S.libModeTargetId,
    };
    return S.history.filter((entry) => {
      const content = contentOf(entry);
      if (!contentMatchesFilters(content, ctx)) return false;
      if (!query) return true;
      return [content.title, content.author, ...(content.tag_names || [])]
        .filter(Boolean).some((value) => String(value).toLowerCase().includes(query));
    });
  }
  /* 11-23：结构化筛选的唯一实现——知识库列表与详情左栏共用，保证类内 OR、类间 AND 的口径一致。 */
  function contentMatchesFilters(content, ctx) {
    const f = ctx.filters || {};
    const tagIds = ctx.tagIds || [];
    const folderIds = ctx.folderIds || [];
    const bounds = { short: [0, 300], medium: [300, 900], long: [900, 1800], xl: [1800, Infinity] };
    if (ctx.mode === "remove") {
      const ids = ctx.modeKind === "tag" ? content.tag_ids || [] : content.favorite_folder_ids || [];
      if (!ids.includes(ctx.modeTargetId)) return false;
    } else {
      if (tagIds.length && !tagIds.some((id) => (content.tag_ids || []).includes(id))) return false;
      if (folderIds.length && !folderIds.some((id) => (content.favorite_folder_ids || []).includes(id))) return false;
    }
    if (f.platform && content.platform !== f.platform) return false;
    if (f.kind && content.kind !== f.kind) return false;
    if (f.introduction === "missing" && String(content.introduction || "").trim()) return false;
    if (f.duration) {
      const seconds = Number(content.duration_seconds || 0);
      const range = bounds[f.duration];
      if (!range || seconds < range[0] || seconds >= range[1]) return false;
    }
    return true;
  }
  /* 11-23：进入详情时冻结当时的筛选条件；左栏只看这个快照，与知识库后续改动解耦。 */
  function currentQuickContext() {
    const filters = S.libFilters;
    const active = S.activeTagIds.length || S.activeFolderIds.length ||
      Object.keys(filters).some((key) => filters[key]);
    return active ? {
      tagIds: [...S.activeTagIds], folderIds: [...S.activeFolderIds], filters: { ...filters },
    } : null;
  }
  /* R4：合集归属与归档资格来自该内容最新的成功任务；失败重试不覆盖已保存的笔记归属。 */
  function archivedJobByContent() {
    const map = new Map();
    S.jobs.forEach((job) => {
      if (!job.content_id || String(job.state || "").toLowerCase() !== "completed") return;
      const previous = map.get(job.content_id);
      if (!previous || String(job.created_at || "") >= String(previous.created_at || "")) {
        map.set(job.content_id, job);
      }
    });
    return map;
  }
  /* 11-22：合集归属统一取数——history 自带 job（含 paused/failed）优先，
     archivedJobByContent（只认 completed）兜底。内容页侧栏与知识库页共用，避免口径分叉。 */
  function collectionInfoOf(entry, jobMap) {
    const entryJob = entry && typeof entry.job === "object" ? entry.job : null;
    const archived = jobMap.get(idOf(entry));
    const source = entryJob?.collection_id ? entryJob : archived;
    return {
      collectionId: String(source?.collection_id || ""),
      title: String(source?.collection_title || ""),
      total: Number(source?.collection_total) || 0,
    };
  }
  /* R4：失败/进行中的最新重试不移出已有归档内容；从未成功归档的内容仍保持单条。 */
  function libraryGroups() {
    const jobMap = archivedJobByContent();
    const buckets = new Map();
    const singles = [];
    libraryEntries().forEach((entry) => {
      const info = collectionInfoOf(entry, jobMap);
      if (!info.collectionId) { singles.push({ type: "single", entry }); return; }
      if (!buckets.has(info.collectionId)) {
        buckets.set(info.collectionId, {
          type: "collection", id: info.collectionId,
          rawTitle: info.title, total: info.total, entries: [],
        });
      }
      buckets.get(info.collectionId).entries.push(entry);
    });
    // 进集标题：优先合集名，缺名时用集内条数，不留「导入 条」这种空位。
    buckets.forEach((bucket) => {
      bucket.title = cleanCollectionTitle(bucket.rawTitle)
        || `导入 ${bucket.total || bucket.entries.length} 条`;
    });
    // 进入某个集后只列该集的已归档内容；单条内容不成集，避免只含一项的父集。
    if (S.libCollection) {
      const bucket = buckets.get(S.libCollection);
      return { collections: [], singles: (bucket?.entries || []).map((entry) => ({ type: "single", entry })) };
    }
    const collections = [];
    buckets.forEach((bucket) => {
      if (bucket.entries.length > 1) collections.push(bucket);
      else bucket.entries.forEach((entry) => singles.push({ type: "single", entry }));
    });
    return { collections, singles };
  }
  function tileHtml(entry) {
    const content = contentOf(entry);
    const pickSet = S.libMode ? S.pickedContents : S.selectedContents;
    // C1/C6/C7：共用封面模板、平台标志内置、右下时长胶囊、title 保留完整原始标题。
    return `<article class="tile ${pickSet.has(content.id) ? "is-selected" : ""}" role="listitem" data-content-id="${esc(content.id)}">
        <input class="tile__pick" type="checkbox" data-content-pick="${esc(content.id)}" data-mode-pick="${esc(content.id)}" ${pickSet.has(content.id) ? "checked" : ""} aria-label="选择内容" />
        ${coverHtml(content, true)}
        <button class="tile__more" type="button" data-act="tile-more" data-content-id="${esc(content.id)}" aria-label="更多操作"><svg class="ico"><use href="#i-dots"/></svg></button>
        <div class="tile__body">
          <span class="tile__title" title="${esc(content.title || "")}">${esc(content.title || "未命名内容")}</span>
          ${categoryOf(content) ? `<div class="tile__meta"><span class="tile__tag">${esc(categoryOf(content))}</span></div>` : ""}
        </div>
      </article>`;
  }
  function collectionTileHtml(group) {
    const first = contentOf(group.entries[0]);
    const count = group.entries.length;
    // 合集总数来自扫描记录，历史导入可能让已归档数超过它；下限取已归档数，避免出现「3 / 2」。
    const total = Math.max(count, Number(group.total) || 0);
    return `<article class="tile tile--collection" role="listitem" data-collection-id="${esc(group.id)}">
        ${coverHtml(first, true)}
        <span class="tile__collection-count">${count} 条</span>
        <div class="tile__body">
          <span class="tile__title" title="${esc(group.title)}">${esc(group.title)}</span>
          <div class="tile__meta"><span class="tile__tag">${count} / ${total} 条</span></div>
        </div>
      </article>`;
  }
  function renderLibrary() {
    const adding = S.libMode === "add";
    const browser = $("#lib-browser-view");
    const groupsView = $("#lib-groups-view");
    browser.hidden = S.libManageOpen;
    groupsView.hidden = !S.libManageOpen;
    if (S.libManageOpen) {
      renderLibraryGroups();
      return;
    }
    const tagIds = new Set(S.tags.map((tag) => tag.id));
    const folderIds = new Set(S.folders.filter((folder) => !folder.is_system).map((folder) => folder.id));
    S.activeTagIds = S.activeTagIds.filter((id) => tagIds.has(id));
    S.activeFolderIds = S.activeFolderIds.filter((id) => folderIds.has(id));
    renderLibraryGroupFilters();
    const entries = adding ? candidateEntries() : libraryEntries();
    $("#lib-count").textContent = `共 ${entries.length} 条`;
    renderFilterPanel();
    renderLibraryModeBar();
    let cards = "";
    if (adding) cards = entries.map((entry) => tileHtml(entry)).join("");
    else {
      const groups = libraryGroups();
      const createdAtOf = (entry) => String(contentOf(entry).created_at || "");
      // A：合集卡与单条卡统一按内容创建时间倒序；合集卡取集内最新成员时间。
      const tiles = groups.collections.map((group) => ({
        at: group.entries.map(createdAtOf).sort().pop() || "",
        html: collectionTileHtml(group),
      })).concat(groups.singles.map((item) => ({
        at: createdAtOf(item.entry),
        html: tileHtml(item.entry),
      })));
      tiles.sort((a, b) => (a.at === b.at ? 0 : (a.at > b.at ? -1 : 1)));
      cards = tiles.map((tile) => tile.html).join("");
    }
    const back = S.libCollection
      ? `<button class="lib-back" type="button" data-act="lib-collection-back">‹ 返回知识库</button>`
      : "";
    const grid = $("#lib-grid");
    const scrollTop = grid.scrollTop;
    const emptyMessage = S.historyLoadFailed ? "知识库加载失败，请点击「刷新」重试" : "没有符合条件的内容";
    grid.innerHTML = back + (cards || `<p style="color:var(--ink-3)">${emptyMessage}</p>`);
    grid.scrollTop = S.libGridScrollTop || scrollTop;
    renderLibraryToolbar();
  }
  function renderLibraryGroupFilters() {
    const renderFilter = (kind) => {
      const isTag = kind === "tag";
      const groups = isTag ? S.tags : S.folders.filter((folder) => !folder.is_system);
      const selectedIds = isTag ? S.activeTagIds : S.activeFolderIds;
      const label = isTag ? "标签" : "收藏夹";
      const first = groups.find((group) => group.id === selectedIds[0]);
      const filterLabel = first
        ? `${first.name}${selectedIds.length > 1 ? ` +${selectedIds.length - 1}` : ""}`
        : label;
      $(`#lib-${isTag ? "tag" : "folder"}-filter-label`).textContent = filterLabel;
      const menu = $(`#lib-${isTag ? "tag" : "folder"}-filter-menu`);
      menu.innerHTML = `<div class="lib-group-filter__items">${groups.length ? groups.map((group) => {
        const selected = selectedIds.includes(group.id);
        return `<button class="lib-group-filter__option ${selected ? "is-selected" : ""}" type="button" data-act="lib-group-select" data-kind="${kind}" data-id="${esc(group.id)}" aria-pressed="${selected}"><span>${esc(group.name)}</span><small>${group.content_count ?? 0}</small><span class="lib-group-filter__check" aria-hidden="true">✓</span></button>`;
      }).join("") : `<span class="lib-group-filter__empty">暂无${label}</span>`}</div><button class="lib-group-filter__clear" type="button" data-act="lib-group-clear" data-kind="${kind}" ${selectedIds.length ? "" : "disabled"}>清除所选</button>`;
      menu.hidden = S.libGroupMenu !== kind;
      $(`[data-act="lib-group-menu-toggle"][data-kind="${kind}"]`).setAttribute("aria-expanded", String(!menu.hidden));
    };
    renderFilter("folder");
    renderFilter("tag");
  }
  function closeLibraryGroupMenu() {
    S.libGroupMenu = null;
    $$(".lib-group-filter__menu").forEach((menu) => { menu.hidden = true; });
    $$(".lib-group-filter__trigger").forEach((trigger) => trigger.setAttribute("aria-expanded", "false"));
  }
  function renderLibraryGroups() {
    const renderList = (kind, groups, label) => {
      const list = $(`#lib-${kind === "tag" ? "tag" : "folder"}-list`);
      list.innerHTML = groups.length ? groups.map((group) => `<div class="lib-group-row"><span class="lib-group-row__name">${esc(group.name)}</span><small class="lib-group-row__count">${group.content_count ?? 0}</small><div class="lib-group-row__tools"><button class="icon-btn icon-btn--sm" type="button" data-act="lib-group-more" data-kind="${kind}" data-id="${esc(group.id)}" aria-label="${label} ${esc(group.name)} 的更多操作" title="更多操作"><svg class="ico"><use href="#i-more"/></svg></button></div></div>`).join("") : `<p class="lib-group-list__empty">暂无${label}</p>`;
    };
    renderList("folder", S.folders.filter((folder) => !folder.is_system), "收藏夹");
    renderList("tag", S.tags, "标签");
  }
  function renderLibraryToolbar() {
    const editing = S.libEditMode;
    const hasCategoryFilters = S.activeTagIds.length > 0 || S.activeFolderIds.length > 0;
    const hasFilters = hasCategoryFilters || Object.values(S.libFilters).some(Boolean);
    $("#lib-refresh-btn").disabled = S.libraryRefreshing;
    $("#lib-refresh-btn").textContent = S.libraryRefreshing ? "刷新中…" : "刷新";
    $("#lib-edit-btn").textContent = editing ? "退出编辑" : "编辑";
    $("#lib-delete-btn").hidden = !(editing && S.selectedContents.size > 0);
    $("#lib-filter-btn").classList.toggle("is-active", Object.values(S.libFilters).some(Boolean));
    $("#lib-group-toolbar").hidden = Boolean(S.libMode);
    $("#lib-filter-panel").hidden = Boolean(S.libMode) || !S.libFilterOpen;
    $("#lib-filter-clear-all").hidden = !hasFilters;
    const total = $('[data-act="lib-total"]');
    const totalSelected = !hasCategoryFilters && !S.libFilters.platform;
    total.setAttribute("aria-pressed", String(totalSelected));
    total.classList.toggle("is-current", totalSelected);
    $$('#lib-group-toolbar [data-dim="platform"]').forEach((button) => {
      button.setAttribute("aria-pressed", String(S.libFilters.platform === button.dataset.value));
    });
    $("#lib-organize-btn").disabled = !S.tags.length && !S.folders.some((folder) => !folder.is_system);
    $("#lib-grid").classList.toggle("is-editing", editing);
    $("#lib-grid").classList.toggle("is-managing", S.libMode !== null);
  }

  const FILTER_DIMENSIONS = [
    ["platform", "来源平台"], ["kind", "内容形态"],
    ["duration", "时长"], ["introduction", "简介是否缺失"],
  ];
  const FILTER_VALUES = {
    platform: [["bilibili", "B站"], ["xiaohongshu", "小红书"], ["zhihu", "知乎"],
      ["douyin", "抖音"], ["wechat", "微信"], ["youtube", "YouTube"],
      ["web", "网页"], ["local", "本地"]],
    kind: [["video", "视频"], ["article", "图文"], ["web", "网页（规划中）"]],
    duration: [["short", "5 分钟内"], ["medium", "5-15 分钟"],
      ["long", "15-30 分钟"], ["xl", "30 分钟以上"]],
    introduction: [["missing", "简介缺失"]],
  };
  function renderFilterPanel() {
    const panel = $("#lib-filter-panel");
    panel.hidden = !S.libFilterOpen;
    if (!S.libFilterOpen) { panel.innerHTML = ""; return; }
    const clear = `<button class="link-btn" type="button" data-act="lib-filter-clear">清除</button>`;
    if (!S.libFilterDimension) {
      panel.innerHTML = `<div class="lib-filter-panel__row">${FILTER_DIMENSIONS.map(([key, label]) =>
        `<button class="lib-filter-panel__item ${S.libFilters[key] ? "is-current" : ""}" type="button" data-act="lib-filter-dim" data-dim="${key}">${label}</button>`).join("")}${clear}</div>`;
      return;
    }
    const dim = S.libFilterDimension;
    const label = FILTER_DIMENSIONS.find(([key]) => key === dim)?.[1] || "";
    panel.innerHTML = `<div class="lib-filter-panel__row"><button class="link-btn" type="button" data-act="lib-filter-back">‹ ${label}</button>${FILTER_VALUES[dim].map(([value, text]) =>
      `<button class="lib-filter-panel__item ${S.libFilters[dim] === value ? "is-current" : ""}" type="button" data-act="lib-filter-value" data-dim="${dim}" data-value="${value}">${text}</button>`).join("")}${clear}</div>`;
  }
  function candidateEntries() {
    const key = S.libModeKind === "tag" ? "tag_ids" : "favorite_folder_ids";
    const scopeId = S.libModeTargetId;
    return S.history.filter((entry) => !(contentOf(entry)[key] || []).includes(scopeId));
  }
  function renderLibraryModeBar() {
    const bar = $("#lib-mode-bar");
    bar.hidden = !S.libMode;
    if (!S.libMode) { bar.innerHTML = ""; return; }
    const isTag = S.libModeKind === "tag";
    const group = (isTag ? S.tags : S.folders).find((item) => item.id === S.libModeTargetId);
    const groupName = group?.name || (isTag ? "标签" : "收藏夹");
    const action = S.libMode === "add"
      ? `<button class="btn btn--primary" type="button" data-act="lib-mode-add">添加到「${esc(groupName)}」</button>`
      : `<button class="link-btn link-btn--danger" type="button" data-act="lib-mode-remove">从「${esc(groupName)}」移除</button>`;
    const operation = S.libMode === "add" ? `添加到${isTag ? "标签" : "收藏夹"}「${esc(groupName)}」` : `从${isTag ? "标签" : "收藏夹"}「${esc(groupName)}」移除`;
    bar.innerHTML = `<button class="link-btn" type="button" data-act="lib-mode-cancel">取消</button><span class="lib-mode-bar__count">${operation} · 已选 ${S.pickedContents.size} 项</span>${action}`;
  }
  function renderTrash() {
    const items = S.trash || [];
    $("#trash-list").innerHTML = items.length ? items.map((entry) => {
      const content = contentOf(entry);
      return `<div class="trash-row" role="listitem">${coverHtml(content, true)}<span class="trash-row__title">${esc(content.title || "未命名内容")}</span><div class="trash-row__tools"><button class="link-btn" type="button" data-act="trash-restore" data-id="${esc(content.id)}">恢复</button><button class="link-btn link-btn--danger" type="button" data-act="trash-purge" data-id="${esc(content.id)}">彻底删除</button></div></div>`;
    }).join("") : `<p style="color:var(--ink-3)">回收站为空</p>`;
  }

  /* ------------------------- 图四：AI 问答 ------------------------- */
  function renderAsk() {
    // C10/图三：只显示会话标题，去掉日期前缀与重复信息；删除键仅当前选中会话显示。
    $("#ask-sessions").innerHTML = S.sessions.length ? S.sessions.map((session) => {
      const current = S.sessionId === session.id;
      const title = esc(session.title || "新会话");
      return `<div class="session-row"><button class="session ${current ? "is-current" : ""}" type="button" data-session="${esc(session.id)}" title="${title}">${title}</button>
        <button class="session__del" type="button" data-act="ask-session-delete" data-session-id="${esc(session.id)}" data-tip="删除会话" aria-label="删除会话"><svg class="ico"><use href="#i-trash"/></svg></button></div>`;
    }).join("") : `<p style="color:var(--ink-3)">暂无会话</p>`;
    renderScopeList();
    updateScopeSummary();
    renderAskStream();
  }
  function scopeEntries(level) {
    return S.history.filter((entry) => {
      const content = contentOf(entry);
      if (level.kind === "tag") {
        if (level.id === "other") return !(content.tag_ids || []).length;
        return (content.tag_ids || []).includes(level.id);
      }
      return (content.favorite_folder_ids || []).includes(level.id);
    });
  }
  function renderScopeList() {
    const box = $("#ask-scope-list");
    const title = $("#ask-scope-title");
    if (!box || !title) return;
    const level = S.scopeLevel;
    if (S.scopeKind === "all" || level) {
      // 图四/C10：全库逐条列出全部内容，可逐条勾选进 content_ids；标签/收藏夹保持两级下钻。
      const entries = S.scopeKind === "all" ? S.history : scopeEntries(level);
      title.textContent = level ? `${level.name} · ${entries.length} 条` : `全部内容 · ${entries.length} 条`;
      const back = level ? `<button class="scope-back" type="button" data-act="scope-back">‹ 返回${S.scopeKind === "tag" ? "标签" : "收藏夹"}</button>` : "";
      box.innerHTML = back + (entries.length ? entries.map((entry) => {
        const content = contentOf(entry);
        const label = esc(content.title || "未命名内容");
        return `<label class="scope-item"><input type="checkbox" data-scope-content="${esc(content.id)}" ${S.scopeContents.has(content.id) ? "checked" : ""} /><span title="${label}">${label}</span></label>`;
      }).join("") : `<p class="scope-empty">该分组下暂无内容</p>`);
      return;
    }
    const groups = S.scopeKind === "tag"
      ? [...S.tags.map((tag) => ({ id: tag.id, name: tag.name, count: tag.content_count ?? 0 })),
         { id: "other", name: "其他", count: S.history.filter((e) => !(contentOf(e).tag_ids || []).length).length }]
      : S.folders.map((folder) => ({ id: folder.id, name: folder.name, count: folder.content_count ?? 0 }));
    title.textContent = S.scopeKind === "tag" ? "选择标签" : "选择收藏夹";
    box.innerHTML = groups.length ? groups.map((group) =>
      `<button class="scope-group" type="button" data-scope-group="${esc(group.id)}" data-scope-group-name="${esc(group.name)}"><span>${esc(group.name)}</span><span>${group.count} 条 ›</span></button>`).join("")
      : `<p class="scope-empty">暂无可选分组</p>`;
  }
  function scopePayload() {
    // 图四/C10：全库逐条勾选的内容通过 content_ids 提交；未逐条勾选时按范围类型。
    const contents = Array.from(S.applied.contents || []);
    let kind = "all";
    if (contents.length) kind = "selected";
    else if (S.applied.kind === "folder") kind = "favorites";
    else if (S.applied.kind === "tag") kind = "selected";
    return {
      kind, material_scope: "full",
      content_ids: contents,
      tag_ids: Array.from(S.applied.tags).filter((id) => id !== "other"),
      favorite_folder_ids: Array.from(S.applied.folders),
    };
  }
  function updateScopeSummary() {
    // 图四：底部只保留「已选 N 条 · 共 M 条」，不新增说明副标题。
    $("#ask-scope-summary").textContent = `已选 ${S.scopeContents.size} 条 · 共 ${S.history.length} 条`;
  }
  /* C8：真实回答时间取自消息自身持久化的时间字段，重开同一会话值不变。 */
  function answerTime(query, detail) {
    return query?.updated_at || query?.created_at || detail?.updated_at || detail?.created_at || "";
  }
  const ASK_ACTIVE_STATUSES = new Set(["queued", "running", "cancelling"]);
  const ASK_TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled", "paused"]);
  const askQueryWatchers = new Map();
  let askQueryUpdateSeq = 0;
  function askMessagesForCurrentSession() {
    const sessionId = S.sessionId;
    const detailId = S.sessionDetail?.id || S.sessionDetail?.session_id;
    const messages = detailId === sessionId ? [...(S.sessionDetail.messages || [])] : [];
    const seen = new Set(messages.map((item) => String(item.id || item.query_id || "")));
    S.askQueries.forEach((query) => {
      if (query.session_id === sessionId && !seen.has(String(query.id || query.query_id || ""))) {
        messages.push(query);
      }
    });
    if (S.askPending && (!S.askPending.session_id || S.askPending.session_id === sessionId)) {
      messages.push(S.askPending);
    }
    return messages;
  }
  function renderAskControls() {
    const input = $("#ask-input");
    const clear = $('[data-act="ask-clear"]');
    const stop = $('[data-act="ask-stop"]');
    const resume = $('[data-act="ask-continue"], [data-act="ask-retry"]');
    const send = $('[data-act="ask-send"]');
    if (!input || !clear || !stop || !resume || !send) return;
    const messages = askMessagesForCurrentSession();
    const active = [...messages].reverse().find((item) => ASK_ACTIVE_STATUSES.has(item.status));
    const recoverable = active ? null : [...messages].reverse().find((item) => ["paused", "failed"].includes(item.status));
    const idOfQuery = (item) => String(item?.id || item?.query_id || "");
    clear.disabled = S.askSubmitting;
    send.disabled = S.askSubmitting || Boolean(active);
    send.textContent = S.askSubmitting ? "发送中…" : "发送";
    stop.hidden = !active;
    stop.disabled = Boolean(active?.status === "cancelling" || active?.cancelSubmitting);
    stop.textContent = active?.status === "cancelling" ? "正在停止…" : "停止生成";
    stop.dataset.queryId = idOfQuery(active);
    resume.hidden = !recoverable;
    resume.disabled = Boolean(recoverable?.continuing);
    resume.dataset.act = recoverable?.status === "failed" ? "ask-retry" : "ask-continue";
    resume.dataset.queryId = idOfQuery(recoverable);
    resume.textContent = recoverable?.status === "failed" ? "重试问题" : "继续生成";
    S.lastQueryId = idOfQuery(active || recoverable || messages.at(-1));
  }
  function askStatusHtml(query) {
    const labels = {
      submitting: "正在发送", queued: "排队中", running: "正在生成回答",
      cancelling: "正在停止", paused: "已暂停", failed: "回答失败",
      cancelled: "已停止", completed: "已完成",
    };
    const label = query.readError ? "状态读取失败" : (labels[query.command] || labels[query.status] || "");
    if (!label || (query.status === "completed" && !query.readError && query.result?.answer)) return "";
    const retry = query.readError && query.id
      ? `<button class="link-btn" type="button" data-act="ask-query-refresh" data-query-id="${esc(query.id)}">重试读取</button>` : "";
    return `<div class="ask-query-status${query.readError ? " is-error" : ""}" role="status">${esc(label)}${retry}</div>`;
  }
  function renderAskStream() {
    const stream = $("#ask-stream");
    const detail = S.sessionDetail;
    const messages = askMessagesForCurrentSession();
    if (!messages.length) {
      // 图三/四：空会话铺一屏对话骨架。骨架没有真实回答，故不伪造时间（C8）。
      sourceRefs.set("skel", S.history.map(idOf));
      $("#ask-talk-head").textContent = "今天 · AI 产品拆解";
      stream.innerHTML = `<div class="bubble">按当前范围里的内容，帮我拆解一个 AI 产品的核心模块</div>
        <div class="answer"><div class="answer__label"><svg class="ico"><use href="#i-spark"/></svg> AI 回答</div>
          <div class="answer__body">${mdToHtml("1. 内容接入：链接与本地文件统一进入任务队列\n2. 知识库：按标签与收藏夹整理归档\n3. AI 问答：限定范围后回答并附来源")}</div>
          <button class="answer__sources" type="button" data-act="answer-sources" data-source-key="skel">来源：所选范围 · ${S.history.length} 条内容<svg class="ico"><use href="#i-chev-right"/></svg></button></div>`;
      renderAskControls();
      return;
    }
    $("#ask-talk-head").textContent = detail?.title ? `今天 · ${detail.title}` : "今天 · 新会话";
    stream.innerHTML = messages.flatMap((source, index) => {
      const queryId = String(source.id || source.query_id || "");
      const query = { ...source, ...(S.askQueries.get(queryId) || {}) };
      const blocks = [`<div class="bubble">${esc(query.question || query.text || "")}</div>`];
      const status = askStatusHtml(query);
      const result = query.result || {};
      const answer = result.answer || query.answer_markdown || query.answer || query.response || "";
      if (answer) {
        const time = fmtDateTime(answerTime(query, detail));
        const citations = Array.isArray(result.citations) ? result.citations : [];
        const citedIds = citations.map((item) => typeof item === "string" ? item : (item?.content_id || item?.id)).filter(Boolean);
        const scopeIds = Array.isArray(query.scope?.content_ids) ? query.scope.content_ids : [];
        const ids = citedIds.length ? citedIds : (scopeIds.length ? scopeIds : S.history.map(idOf));
        const key = `q${index}`;
        sourceRefs.set(key, ids);
        const label = citedIds.length
          ? `来源：${citedIds.length} 条内容`
          : (query.scope?.count != null ? `来源：所选范围 · ${query.scope.count} 条内容` : `来源：${ids.length} 条内容`);
        blocks.push(`<div class="answer"><div class="answer__label"><svg class="ico"><use href="#i-spark"/></svg> AI 回答</div>
          <div class="answer__body">${mdToHtml(answer)}</div>
          <button class="answer__sources" type="button" data-act="answer-sources" data-source-key="${key}">${esc(label)}<svg class="ico"><use href="#i-chev-right"/></svg></button>
          ${time ? `<div class="answer__time">${esc(time)}</div>` : ""}</div>`);
      }
      if (status) blocks.push(status);
      return blocks;
    }).join("");
    stream.scrollTop = stream.scrollHeight;
    renderAskControls();
  }
  function updateAskQuery(query, sessionId, { keepReadError = false, requestSeq = null, render = true } = {}) {
    const id = String(query.id || query.query_id || "");
    if (!id) return null;
    const previous = S.askQueries.get(id) || {};
    if (requestSeq !== null && Number(previous._updateSeq || 0) > requestSeq) return previous;
    const updateSeq = requestSeq === null ? ++askQueryUpdateSeq : requestSeq;
    const record = { ...previous, ...query, id, session_id: query.session_id || previous.session_id || sessionId,
      _updateSeq: updateSeq };
    if (!keepReadError) record.readError = null;
    S.askQueries.set(id, record);
    if (render && S.sessionId === record.session_id) {
      const detailId = S.sessionDetail?.id || S.sessionDetail?.session_id;
      const detail = detailId === record.session_id ? S.sessionDetail : { id: record.session_id, messages: [] };
      const messages = [...(detail.messages || [])];
      const index = messages.findIndex((item) => String(item.id || item.query_id || "") === id);
      if (index < 0) messages.push(record);
      else messages[index] = { ...messages[index], ...record };
      S.sessionDetail = { ...detail, messages };
      renderAskStream();
    }
    return record;
  }
  async function watchAskQuery(queryId, sessionId) {
    if (askQueryWatchers.has(queryId)) return askQueryWatchers.get(queryId);
    const watching = (async () => {
      while (true) {
        let query;
        const requestSeq = ++askQueryUpdateSeq;
        try {
          query = await api(`/ask/queries/${encodeURIComponent(queryId)}`);
        } catch (error) {
          const current = S.askQueries.get(queryId);
          if (current) {
            current.readError = error.message;
            updateAskQuery(current, sessionId, { keepReadError: true });
          }
          return;
        }
        const record = updateAskQuery(query, sessionId, { requestSeq });
        if (!record || ASK_TERMINAL_STATUSES.has(record.status)) return;
        await new Promise((resolve) => setTimeout(resolve, 500));
      }
    })();
    askQueryWatchers.set(queryId, watching);
    try { await watching; }
    finally {
      if (askQueryWatchers.get(queryId) === watching) askQueryWatchers.delete(queryId);
    }
  }
  async function loadAskSession(sessionId) {
    if (!sessionId) return;
    const requestSeq = ++askQueryUpdateSeq;
    try {
      const detail = await api(`/ask/sessions/${encodeURIComponent(sessionId)}`);
      if (S.sessionId !== sessionId) return;
      const messages = detail.messages || detail.queries || detail.items || [];
      messages.forEach((query) => {
        const id = String(query.id || query.query_id || "");
        if (!id) return;
        updateAskQuery({ ...query, id, session_id: query.session_id || sessionId }, sessionId,
          { requestSeq, render: false });
      });
      const mergedMessages = messages.map((query) =>
        S.askQueries.get(String(query.id || query.query_id || "")) || query);
      S.sessionDetail = { ...detail, messages: mergedMessages };
      S.lastQueryId = String(mergedMessages.at(-1)?.id || mergedMessages.at(-1)?.query_id || "") || null;
      renderAskStream();
      mergedMessages.filter((query) => ASK_ACTIVE_STATUSES.has(query.status)).forEach((query) => {
        void watchAskQuery(String(query.id || query.query_id), sessionId);
      });
    } catch (error) {
      if (S.sessionId === sessionId) toast(`会话读取失败：${error.message}`);
    }
  }
  async function askSend() {
    const input = $("#ask-input");
    const question = input.value.trim();
    if (!question) return toast("请输入问题");
    if (S.askSubmitting) return;
    if (askMessagesForCurrentSession().some((item) => ASK_ACTIVE_STATUSES.has(item.status))) {
      return toast("当前回答仍在生成中");
    }
    const sessionBeforeSend = S.sessionId;
    const scope = scopePayload();
    S.askPending = { id: `pending-${Date.now()}`, session_id: sessionBeforeSend,
      question, scope, status: "submitting" };
    S.askSubmitting = true;
    renderAskStream();
    try {
      const result = await post("/ask/queries", {
        question, session_id: sessionBeforeSend, confirmed_scope: scope,
      });
      const queryId = String(result.query_id || result.id || "");
      const sessionId = result.session_id || sessionBeforeSend;
      if (!queryId || !sessionId) throw new Error("服务未返回问答任务编号");
      if (S.sessionId === sessionBeforeSend) S.sessionId = sessionId;
      if (input.value.trim() === question) input.value = "";
      S.askPending = null;
      updateAskQuery({ id: queryId, session_id: sessionId, question, scope,
        status: result.status || "queued" }, sessionId);
      void refresh("sessions").then(() => { if (S.route === "ask") renderAsk(); });
      void watchAskQuery(queryId, sessionId);
    } catch (error) {
      S.askPending = null;
      toast(`发送失败：${error.message}`);
    } finally {
      S.askSubmitting = false;
      renderAskStream();
    }
  }
  async function stopAskQuery(queryId) {
    const current = S.askQueries.get(queryId);
    if (!current || !ASK_ACTIVE_STATUSES.has(current.status) || current.cancelSubmitting) return;
    const sessionId = current.session_id;
    updateAskQuery({ id: queryId, status: "cancelling", cancelSubmitting: true }, sessionId);
    try {
      await post(`/ask/queries/${encodeURIComponent(queryId)}/cancel`, {});
      const latest = S.askQueries.get(queryId);
      const changes = { id: queryId, cancelSubmitting: false };
      if (latest && !ASK_TERMINAL_STATUSES.has(latest.status)) changes.status = "cancelling";
      updateAskQuery(changes, sessionId);
      void watchAskQuery(queryId, sessionId);
    } catch (error) {
      updateAskQuery({ id: queryId, cancelSubmitting: false }, sessionId);
      toast(`停止失败：${error.message}`);
      void watchAskQuery(queryId, sessionId);
    }
  }
  async function continueAskQuery(queryId) {
    const current = S.askQueries.get(queryId);
    if (!current || !["paused", "failed"].includes(current.status) || current.continuing) return;
    const previousStatus = current.status;
    const sessionId = current.session_id;
    updateAskQuery({ id: queryId, continuing: true, command: "continuing" }, sessionId);
    let accepted;
    try {
      accepted = await post(`/ask/queries/${encodeURIComponent(queryId)}/continue`, {});
    } catch (error) {
      updateAskQuery({ id: queryId, continuing: false, command: null }, sessionId);
      toast(`继续失败：${error.message}`);
      return;
    }
    const latest = S.askQueries.get(queryId);
    const changes = { id: queryId, continuing: false, command: null };
    if (latest?.status === previousStatus) changes.status = accepted.status || "queued";
    updateAskQuery(changes, sessionId);
    const requestSeq = ++askQueryUpdateSeq;
    try {
      const latest = await api(`/ask/queries/${encodeURIComponent(queryId)}`);
      updateAskQuery(latest, sessionId, { requestSeq });
    } catch (error) {
      const latest = S.askQueries.get(queryId);
      if (latest) {
        latest.readError = error.message;
        updateAskQuery(latest, sessionId, { keepReadError: true });
      }
    }
    const finalState = S.askQueries.get(queryId)?.status;
    toast(finalState === "running" ? "已开始处理" : "已重新排队");
    void watchAskQuery(queryId, sessionId);
  }

  /* ------------------------- 图五：设置（左侧分区，右侧面板；ASR 按引擎分支） ------------------------- */
  const PLATFORM_LABELS = { bilibili: "B站", xiaohongshu: "小红书" };
  const SECTION_TITLES = { platform: "平台", asr: "ASR", model: "模型", storage: "存储" };
  function setField(label, body) {
    return `<div class="set-field"><span class="set-field__label">${esc(label)}</span>${body}</div>`;
  }
  function settingInput(key, value, attrs = "") {
    const placeholder = value ? "" : ' placeholder="未填写"';
    return `<input class="set-input"${placeholder}${attrs} data-setting-key="${esc(key)}" value="${esc(value ?? "")}" />`;
  }
  function modelPickerInput(key, value) {
    const id = key.replaceAll("_", "-");
    return `<div class="model-picker">
      ${settingInput(key, value, `id="${id}-input" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="${id}-options" data-model-picker="${key}"`)}
      <div class="model-picker__options" id="${id}-options" role="listbox" hidden></div>
    </div>`;
  }
  function modelPickerOptions(input) {
    const list = $(`#${input.id.replace(/-input$/, "-options")}`);
    return list ? $$('[data-act="model-candidate"]', list) : [];
  }
  function closeModelCandidates(input) {
    if (!input) return;
    const list = $(`#${input.id.replace(/-input$/, "-options")}`);
    if (!list) return;
    list.hidden = true;
    list.replaceChildren();
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    delete input.dataset.modelActiveIndex;
  }
  function closeAllModelCandidates() {
    $$('[data-model-picker]').forEach(closeModelCandidates);
  }
  function renderModelCandidates(input) {
    const list = $(`#${input.id.replace(/-input$/, "-options")}`);
    if (!list) return;
    const models = input.dataset.modelPicker === "summary_model" ? S.summaryModels : S.asrModels;
    const query = input.value.trim().toLocaleLowerCase();
    const candidates = models.filter((model) => String(model).toLocaleLowerCase().includes(query));
    if (!candidates.length) return closeModelCandidates(input);
    list.innerHTML = candidates.map((model, index) => `<button class="model-picker__option" type="button" tabindex="-1" role="option" id="${list.id}-option-${index}" aria-selected="false" data-act="model-candidate" data-setting-key="${esc(input.dataset.settingKey)}" data-model-value="${esc(model)}">${esc(model)}</button>`).join("");
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
    input.dataset.modelActiveIndex = "-1";
    input.removeAttribute("aria-activedescendant");
  }
  function moveModelCandidate(input, direction) {
    if (input.getAttribute("aria-expanded") !== "true") renderModelCandidates(input);
    const options = modelPickerOptions(input);
    if (!options.length) return;
    const current = Number(input.dataset.modelActiveIndex ?? -1);
    const next = current < 0 ? (direction > 0 ? 0 : options.length - 1)
      : (current + direction + options.length) % options.length;
    options.forEach((option, index) => option.setAttribute("aria-selected", String(index === next)));
    input.dataset.modelActiveIndex = String(next);
    input.setAttribute("aria-activedescendant", options[next].id);
    options[next].scrollIntoView?.({ block: "nearest" });
  }
  function selectModelCandidate(input, value) {
    if (!input) return;
    input.value = value;
    closeModelCandidates(input);
    input.focus();
  }
  function enhanceProductSelect(select) {
    if (!select || select.dataset.productSelectEnhanced) return;
    const oldWrap = select.parentElement?.classList.contains("select-wrap") ? select.parentElement : null;
    const host = oldWrap || document.createElement("span");
    if (oldWrap) {
      oldWrap.classList.remove("select-wrap");
      oldWrap.classList.add("product-select");
      $(".ico", oldWrap)?.remove();
    } else {
      host.className = "product-select";
      select.before(host);
      host.appendChild(select);
    }
    select.dataset.productSelectEnhanced = "true";
    select.classList.add("product-select__native");
    select.hidden = true;
    select.tabIndex = -1;
    select.setAttribute("aria-hidden", "true");

    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "input product-select__trigger";
    trigger.id = `${select.id}-trigger`;
    trigger.dataset.productSelectTrigger = "";
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-expanded", "false");
    trigger.setAttribute("aria-controls", `${select.id}-options`);
    const fieldLabel = select.closest(".field")?.querySelector(".field__label")
      || select.closest(".set-field, .set-inline")?.querySelector(".set-field__label");
    if (fieldLabel) {
      if (!fieldLabel.id) fieldLabel.id = `${select.id}-label`;
      trigger.setAttribute("aria-labelledby", fieldLabel.id);
    } else {
      trigger.setAttribute("aria-label", select.getAttribute("aria-label") || select.id);
    }
    const selectedLabel = document.createElement("span");
    selectedLabel.className = "product-select__label";
    const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    icon.classList.add("ico");
    icon.setAttribute("aria-hidden", "true");
    const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", "#i-down");
    icon.appendChild(use);
    trigger.append(selectedLabel, icon);

    const menu = document.createElement("div");
    menu.className = "model-picker__options product-select__options";
    menu.id = `${select.id}-options`;
    menu.setAttribute("role", "listbox");
    menu.setAttribute("aria-labelledby", trigger.id);
    menu.hidden = true;
    Array.from(select.options).forEach((nativeOption, index) => {
      const option = document.createElement("button");
      option.type = "button";
      option.className = "model-picker__option product-select__option";
      option.id = `${select.id}-product-option-${index}`;
      option.dataset.productSelectOption = String(index);
      option.tabIndex = -1;
      option.setAttribute("role", "option");
      option.textContent = nativeOption.textContent.trim();
      menu.appendChild(option);
    });
    host.append(trigger, menu);

    const update = () => {
      selectedLabel.textContent = select.selectedOptions[0]?.textContent.trim() || "";
      Array.from(menu.children).forEach((option, index) =>
        option.setAttribute("aria-selected", String(index === select.selectedIndex)));
    };
    select.addEventListener("change", update);
    update();
  }
  function closeProductSelect(host) {
    if (!host) return;
    const menu = $(".product-select__options", host);
    const trigger = $("[data-product-select-trigger]", host);
    if (menu) menu.hidden = true;
    trigger?.setAttribute("aria-expanded", "false");
  }
  function closeProductSelects(except = null) {
    $$(".product-select").forEach((host) => {
      if (host !== except) closeProductSelect(host);
    });
  }
  function openProductSelect(trigger, focusIndex = null) {
    const host = trigger.closest(".product-select");
    const select = $("select", host);
    const menu = $(".product-select__options", host);
    closeProductSelects(host);
    menu.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
    if (focusIndex !== null) {
      const options = $$('[data-product-select-option]', menu);
      const index = Math.max(0, Math.min(focusIndex, options.length - 1));
      options[index]?.focus();
    }
    if (!select) closeProductSelect(host);
  }
  function moveProductSelectOption(host, direction) {
    const options = $$('[data-product-select-option]', host);
    if (!options.length) return;
    const current = options.indexOf(document.activeElement);
    const select = $("select", host);
    const selected = select?.selectedIndex ?? 0;
    const next = current < 0 ? selected
      : (current + direction + options.length) % options.length;
    options[next]?.focus();
  }
  function chooseProductSelectOption(option) {
    const host = option.closest(".product-select");
    const select = $("select", host);
    const trigger = $("[data-product-select-trigger]", host);
    if (!select || !trigger) return;
    select.selectedIndex = Number(option.dataset.productSelectOption);
    select.dispatchEvent(new Event("change", { bubbles: true }));
    closeProductSelect(host);
    trigger.focus();
  }
  function secretInput(key, configured) {
    const placeholder = configured ? "已保存，留空不修改" : "未填写";
    const input = `<input class="set-input" type="password" autocomplete="off" data-setting-key="${esc(key)}" value="" placeholder="${placeholder}" />`;
    if (!configured) return input;
    /* R4：显式清除入口，与「留空不修改」区分；清除密钥时同步清已选模型。 */
    const provider = key === "summary_api_key" ? "summary" : "asr";
    return input + `<div class="set-field__actions">
         <button class="btn btn--mini" type="button" data-act="clear-secret" data-provider="${provider}">清除密钥与模型</button>
       </div>`;
  }
  function settingValue(key) {
    return $(`[data-setting-key='${key}']`, $("#set-pane"))?.value.trim() || "";
  }
  function platformPane() {
    return S.connections.filter((conn) => PLATFORM_LABELS[conn.platform]).map((conn) => {
      const on = conn.status === "CONNECTED";
      return `<div class="conn-row">
        <div class="conn-row__name">${esc(conn.display_name || PLATFORM_LABELS[conn.platform])}</div>
        <div class="conn-row__right">
          <span class="conn-row__state ${on ? "is-on" : "is-off"}">${on ? "已连接" : "未连接"}</span>
          <button class="btn btn--mini ${on ? "btn--quiet" : "btn--primary"}" type="button" data-act="conn-toggle" data-platform="${esc(conn.platform)}" data-on="${on}">${on ? "断开" : "连接"}</button>
        </div></div>`;
    }).join("");
  }
  function asrPane() {
    const engine = S.settings.asr_engine === "local" ? "local" : "cloud";
    const models = (S.asrLocalModels?.models || []).filter((item) => item.installed !== false);
    const current = S.settings.asr_local_model || "";
    const modelBody = S.asrLocalModelsError
      ? `<div class="set-value set-value--error">加载失败：${esc(S.asrLocalModelsError)}</div>
           <button class="btn btn--mini" type="button" data-act="asr-retry">重试</button>`
      : S.asrLocalModelsLoading || S.asrLocalModels === null
        ? `<div class="set-value" role="status">加载中…</div>`
        : models.length
      ? `<select class="set-input" id="asr-local-model">${models.map((item) =>
          `<option value="${esc(item.id)}"${item.id === current ? " selected" : ""}>${esc(item.label || item.id)}</option>`).join("")}</select>`
      : `<div class="set-value">未安装</div>`;
    return `<div class="set-inline"><span class="set-field__label">转写方式</span>
        <div class="set-choice">
          <label class="radio"><input type="radio" name="asr-engine" value="local"${engine === "local" ? " checked" : ""} /><span>本地</span></label>
          <label class="radio"><input type="radio" name="asr-engine" value="cloud"${engine === "cloud" ? " checked" : ""} /><span>云端</span></label>
        </div></div>
      <div class="set-branch" data-branch="local"${engine === "local" ? "" : " hidden"}>
        ${setField("模型", modelBody)}
        ${setField("状态", `<div class="set-value">${S.settings.asr_local_configured ? "已就绪" : "未就绪"}</div>`)}
      </div>
      <div class="set-branch" data-branch="cloud"${engine === "cloud" ? "" : " hidden"}>
        ${setField("接口地址", settingInput("asr_api_url", S.settings.asr_cloud_api_url))}
        ${setField("密钥", secretInput("asr_api_key", S.settings.asr_cloud_configured))}
        ${setField("模型", modelPickerInput("asr_model", S.settings.asr_cloud_model)
          + `<div class="set-field__actions">
               <button class="btn btn--mini" type="button" data-act="asr-models">识别模型</button>
               <button class="btn btn--mini" type="button" data-act="asr-test">测试连接</button>
             </div>`)}
      </div>`;
  }
  function modelPane() {
    return setField("接口地址", settingInput("summary_api_url", S.settings.summary_api_url))
      + setField("密钥", secretInput("summary_api_key", S.settings.summary_api_key_configured))
      + setField("模型", modelPickerInput("summary_model", S.settings.summary_model)
        + `<div class="set-field__actions">
             <button class="btn btn--mini" type="button" data-act="summary-models">识别模型</button>
             <button class="btn btn--mini" type="button" data-act="summary-test">测试连接</button>
           </div>`)
      + setField("总结 Prompt", `<textarea class="set-input" rows="10" data-setting-key="summary_prompt" placeholder="未填写">${esc(S.settings.summary_prompt || "")}</textarea>`);
  }
  function storagePane() {
    return setField("归档目录", settingInput("archive_root", S.settings.archive_root));
  }
  function environmentCheckPane() {
    const report = S.environmentCheck;
    const statusLabel = { ok: "正常", warning: "待处理", error: "异常" };
    const checkLabel = { ok: "正常", warning: "待处理", error: "异常" };
    const checks = report?.checks || [];
    return `<section class="environment-check" aria-live="polite">
      ${S.environmentChecking ? `<div class="environment-check__progress">检查中…</div>` : ""}
      ${S.environmentCheckError ? `<div class="environment-check__error">环境自检失败：${esc(S.environmentCheckError)}</div>` : ""}
      ${report ? `<h3 class="environment-check__title">${esc(statusLabel[report.status] || report.status)}</h3>
        <ul class="environment-check__list">${checks.map((check) => `<li class="environment-check__item is-${esc(check.status)}">
          <strong>${esc(check.label)}</strong><span>${esc(check.message)}</span>
          ${check.action ? `<span class="environment-check__action">${esc(check.action)}</span>` : ""}
          ${check.blocking ? `<span class="environment-check__blocking">阻断</span>` : ""}
        </li>`).join("")}</ul>` : ""}
    </section>`;
  }
  const SETTINGS_PANES = {
    platform: platformPane, asr: asrPane, model: modelPane, storage: storagePane,
  };
  function renderSettingsPane() {
    const pane = $("#set-pane");
    if (!pane) return;
    $$(".set-nav__item").forEach((item) =>
      item.classList.toggle("is-current", item.dataset.section === S.settingsSection));
    const build = SETTINGS_PANES[S.settingsSection];
    const selfCheck = S.settingsSection === "platform"
      ? `<button class="btn btn--mini" type="button" data-act="conn-check-all">检查连接</button>
         <button class="btn btn--mini" type="button" data-act="conn-check"${S.environmentChecking ? " disabled" : ""}>${S.environmentChecking ? "检查中…" : "环境自检"}</button>` : "";
    const save = S.settingsSection === "platform"
      ? "" : `<button class="btn btn--primary" type="button" data-act="settings-save">保存更改</button>`;
    pane.innerHTML = `<h2 class="set-pane__title">${esc(SECTION_TITLES[S.settingsSection] || "")}</h2>
      <div class="set-pane__divider"></div>${build ? build() : ""}
      <div class="set-pane__tools">${selfCheck}${save}</div>
      ${S.settingsSection === "platform" ? environmentCheckPane() : ""}`;
    enhanceProductSelect($("#asr-local-model", pane));
    if (S.settingsSection === "asr" && S.asrLocalModels === null && !S.asrLocalModelsLoading && !S.asrLocalModelsError) {
      void loadAsrLocalModels();
    }
  }
  async function loadAsrLocalModels() {
    S.asrLocalModelsLoading = true;
    renderSettingsPane();
    try { S.asrLocalModels = await api("/asr/local-models"); }
    catch (error) { S.asrLocalModelsError = error.message; }
    finally {
      S.asrLocalModelsLoading = false;
      if (S.route === "settings" && S.settingsSection === "asr") renderSettingsPane();
    }
  }

  /* ------------------------- 图七：内容详情 ------------------------- */
  function quickEntries() {
    const query = S.quickQuery.trim().toLowerCase();
    const ctx = S.quickContext;
    return S.history.filter((entry) => {
      const content = contentOf(entry);
      if (ctx && !contentMatchesFilters(content, ctx)) return false;
      return !query || String(content.title || "").toLowerCase().includes(query);
    });
  }
  /* 11-18 R4：按最新成功任务的 collection_id 归并父级，保持首次出现顺序；
     只有一个成员的集合退化为普通单条，避免出现无意义的下拉。 */
  function quickGroups() {
    const jobMap = archivedJobByContent();
    const buckets = new Map();
    const result = [];
    quickEntries().forEach((entry) => {
      const content = contentOf(entry);
      const id = idOf(entry);
      const info = collectionInfoOf(entry, jobMap);
      if (!info.collectionId) {
        result.push({ type: "single", key: `s:${id}`, content, items: [{ id, content }] });
        return;
      }
      let group = buckets.get(info.collectionId);
      if (!group) {
        group = {
          type: "group", key: info.collectionId,
          title: info.title || content.title || "未命名合集",
          content, items: [],
        };
        buckets.set(info.collectionId, group);
        result.push(group);
      }
      group.items.push({ id, content });
    });
    result.forEach((item) => {
      if (item.type === "group" && item.items.length < 2) {
        item.type = "single";
        item.content = item.items[0].content;
      }
    });
    return result;
  }
  function quickItemHtml(content, current) {
    const thumb = thumbImg(content.id, "quick-item__thumb");
    return `<button class="quick-item ${current ? "is-current" : ""}" type="button" data-quick="${esc(content.id)}">
        ${thumb}<span class="quick-item__body"><span class="quick-item__title">${esc(content.title || "未命名内容")}</span>
        <span class="quick-item__meta"><span>${esc(categoryOf(content))}</span><span>${fmtDuration(content.duration_seconds)}</span></span></span></button>`;
  }
  function renderQuickList() {
    const groups = quickGroups();
    $("#doc-quick-list").innerHTML = groups.length ? groups.map((group) => {
      if (group.type === "single") return quickItemHtml(group.content, S.contentId === group.content.id);
      const open = S.quickOpen === group.key;
      const current = group.items.some((item) => item.id === S.contentId);
      const thumb = thumbImg(group.content.id, "quick-item__thumb");
      const main = `<button class="quick-item__main" type="button" data-quick-group="${esc(group.key)}" aria-expanded="${open}" aria-label="展开合集：${esc(group.title)}">
        ${thumb}<span class="quick-item__body"><span class="quick-item__title">${esc(group.title)}</span>
        <span class="quick-item__meta quick-item__meta--count">合集 · ${group.items.length} 项</span></span></button>`;
      const toggle = `<button class="quick-item__toggle ${open ? "is-open" : ""}" type="button" data-quick-group="${esc(group.key)}" aria-expanded="${open}" aria-label="${open ? "收起合集列表" : "展开合集列表"}"><svg class="ico"><use href="#i-down"/></svg></button>`;
      const panel = open
        ? `<div class="quick-group__panel" role="list">${group.items.map((item) => quickItemHtml(item.content, S.contentId === item.id)).join("")}</div>` : "";
      return `<div class="quick-group"><div class="quick-item quick-item--group ${current ? "is-current" : ""}">${main}${toggle}</div>${panel}</div>`;
    }).join("") : `<p style="color:var(--ink-3);font-size:11px">没有匹配的内容</p>`;
    renderDocPager();
  }
  function renderDocPager() {
    const list = quickEntries();
    const index = list.findIndex((entry) => idOf(entry) === S.contentId);
    const prev = $("#doc-prev"), next = $("#doc-next");
    if (!prev || !next) return;
    prev.disabled = index <= 0;
    next.disabled = index < 0 || index >= list.length - 1;
    $("#doc-back-bottom").textContent = S.contentReturn?.route === "tasks" ? "返回任务" : "返回知识库";
  }
  function renderOutline() {
    const headings = String(S.markdown || "").split(/\r?\n/)
      .map((line) => /^(#{2,3})\s+(.*)$/.exec(line.trim()))
      .filter(Boolean).map((match) => match[2]);
    const items = headings.length ? headings : ["正文"];
    $("#doc-outline").innerHTML = items.map((title, index) =>
      `<button class="outline-item ${index === 0 ? "is-current" : ""}" type="button" data-outline="${index}">${index + 1} ${esc(title)}</button>`).join("");
  }
  function renderContentBody() {
    const content = S.content || {};
    $("#doc-title").textContent = content.title || "未命名内容";
    $("#doc-time").textContent = fmtDate(S.versions[S.versionIndex]?.created_at || content.created_at);
    $("#doc-intro").textContent = content.introduction || "暂无简介，可点击「编辑标签」补充内容信息。";
    const names = (content.tag_names || []).filter(Boolean);
    // 6-05：无 tag_names 时按内容真实 category 回退显示蓝色标签（真实数据，不写死「教程」）。
    const fallback = String(content.category || "").trim();
    const shown = names.length ? names : (fallback ? [fallback] : []);
    $("#doc-tags").innerHTML = shown.map((name) => `<span class="chip--tag">${esc(name)}</span>`).join("");
    $("#doc-article").innerHTML = mdToHtml(S.markdown, { tables: true }) || `<p style="color:var(--ink-3)">暂无正文</p>`;
    const card = $("#doc-source");
    const sourceUrl = content.canonical_url || "";
    // R12：来源卡只留标题与元信息，不再重复放缩略图；R13：URL 交给系统浏览器。
    card.hidden = !sourceUrl;
    card.dataset.url = sourceUrl;
    $("#doc-source-title").firstChild.textContent = content.title || "未命名内容";
    $("#doc-source-badge").textContent = platformLabel(content.platform);
    $("#doc-source-time").textContent = `${fmtDate(content.published_at)} · ${fmtDuration(content.duration_seconds)}`;
    const version = S.versions[S.versionIndex];
    $(".version").firstChild.textContent = `v${version?.version_number || 1} `;
    renderOutline();
    renderDocPager();
  }
  async function openContent(contentId) {
    if (!contentId) return;
    S.contentId = contentId;
    S.editing = false;
    try {
      const [entry, versions] = await Promise.all([
        api(`/contents/${contentId}/result`).catch(() => null),
        api(`/contents/${contentId}/summary-versions`).catch(() => []),
      ]);
      S.content = entry?.content || S.history.find((item) => idOf(item) === contentId)?.content
        || (await api(`/contents/${contentId}`).catch(() => null)) || {};
      S.versions = Array.isArray(versions) ? versions : [];
      S.versionIndex = Math.max(0, S.versions.length - 1);
      S.markdown = S.versions[S.versionIndex]?.markdown || entry?.summary_markdown || "";
    } catch (error) {
      S.content = {}; S.markdown = ""; S.versions = [];
      toast(`读取内容失败：${error.message}`);
    }
    renderContentBody();
    renderQuickList();
    const url = new URL(window.location.href);
    url.searchParams.set("content_id", contentId);
    window.history.replaceState({}, "", url);
  }
  function neighbour(step) {
    const list = quickEntries();
    const index = list.findIndex((entry) => idOf(entry) === S.contentId);
    const nextIndex = index + step;
    if (index < 0 || nextIndex < 0 || nextIndex >= list.length) return;
    openContent(idOf(list[nextIndex]));
  }
  function setDocQuickCollapsed(collapsed) {
    $(".doc-quick").hidden = collapsed;
    $(".doc-columns").classList.toggle("is-quick-collapsed", collapsed);
    $("#doc-restore-btn").hidden = !collapsed;
  }
  function setDocOutlineCollapsed(collapsed) {
    $(".doc-outline").hidden = collapsed;
    $(".doc-columns").classList.toggle("is-outline-collapsed", collapsed);
    $("#outline-restore-btn").hidden = !collapsed;
  }
  function returnFromContent() {
    const context = S.contentReturn || { route: "library" };
    if (context.route === "tasks") {
      S.jobFilter = context.jobFilter || "all";
      go("tasks");
      $("#jobs-list").scrollTop = context.scrollTop || 0;
      return;
    }
    S.libGridScrollTop = context.scrollTop || 0;
    go("library");
    $("#lib-grid").scrollTop = S.libGridScrollTop;
  }
  async function refreshCurrentContent() {
    if (!S.contentId || S.contentRefreshing) return;
    const contentId = S.contentId;
    const button = $("#doc-refresh-btn");
    S.contentRefreshing = true;
    button.disabled = true;
    button.textContent = "刷新中…";
    try {
      const [content, result, versions, historyRefreshed] = await Promise.all([
        api(`/contents/${contentId}`), api(`/contents/${contentId}/result`).catch(() => null),
        api(`/contents/${contentId}/summary-versions`), refresh("history", { quiet: true }),
      ]);
      if (S.route !== "content" || S.contentId !== contentId) return;
      S.content = content;
      S.versions = Array.isArray(versions) ? versions : [];
      S.versionIndex = Math.max(0, S.versions.length - 1);
      S.markdown = S.versions[S.versionIndex]?.markdown || result?.summary_markdown || S.markdown;
      renderContentBody();
      renderQuickList();
      toast(historyRefreshed ? "笔记已刷新" : "笔记已刷新，列表未能更新");
    } catch (error) {
      if (S.contentId === contentId) toast(`笔记刷新失败：${error.message}`);
    } finally {
      S.contentRefreshing = false;
      button.disabled = false;
      button.textContent = "刷新笔记";
    }
  }
  /* R5：重新总结先选风格与强度；取消不建任务，提交中禁重复提交，失败保留选择。 */
  function openRestyle() {
    if (!S.contentId) return toast("请先选择内容");
    $("#restyle-sheet").hidden = false;
    $("#restyle-error").hidden = true;
    $("#restyle-extra-instruction").value = "";
    $("#restyle-submit").disabled = false;
    $("#restyle-submit").textContent = "提交";
  }
  function closeRestyle() {
    if (S.restyleSubmitting) return;
    $("#restyle-sheet").hidden = true;
  }
  async function submitRestyle() {
    if (S.restyleSubmitting || !S.contentId) return;
    const button = $("#restyle-submit");
    const errorLine = $("#restyle-error");
    S.restyleSubmitting = true;
    button.disabled = true;
    button.textContent = "提交中…";
    errorLine.hidden = true;
    try {
      await post(`/contents/${S.contentId}/resummarize`, {
        summary_style: $("#restyle-style").value,
        strength: $("#restyle-strength").value,
        extra_instruction: $("#restyle-extra-instruction").value,
        reuse_content: true,
      });
      $("#restyle-sheet").hidden = true;
      toast("已提交重新总结");
      await refresh("jobs");
    } catch (error) {
      errorLine.textContent = `提交失败：${error.message}`;
      errorLine.hidden = false;
    } finally {
      S.restyleSubmitting = false;
      button.disabled = false;
      button.textContent = "提交";
    }
  }
  /* R13：来源链接交系统默认浏览器；失败时给原因并复制链接，不退回壳内浏览。 */
  async function openSourceUrl(url) {
    const target = url || S.content?.canonical_url || "";
    if (!target) return toast("该内容没有来源链接");
    try {
      await post("/system/open-url", { url: target });
    } catch (error) {
      try {
        await navigator.clipboard.writeText(target);
        toast(`打开失败：${error.message}；链接已复制`);
      } catch (_) {
        toast(`打开失败：${error.message}`);
      }
    }
  }

  /* ------------------------- 图八：导出 ------------------------- */
  function closeSheet() {
    $("#export-sheet").hidden = true;
    $("#doc-export-btn")?.classList.remove("is-active");
    $("#doc-export-btn")?.setAttribute("aria-expanded", "false");
  }
  function closePopmenu() { const menu = $("#popmenu"); menu.hidden = true; menu.classList.remove("is-sources", "is-library-actions"); }
  function openSheet(anchor) {
    const sheet = $("#export-sheet");
    sheet.hidden = false;
    const rect = anchor.getBoundingClientRect();
    const outline = $(".doc-outline")?.getBoundingClientRect();
    const width = sheet.getBoundingClientRect().width;
    const maxRight = outline ? outline.left - 8 : window.innerWidth - 8;
    const left = Math.max(8, Math.min(rect.left - 40, maxRight - width));
    sheet.style.left = `${left}px`;
    sheet.style.top = `${rect.bottom + 8}px`;
    $("#doc-export-btn").classList.add("is-active");
    $("#doc-export-btn").setAttribute("aria-expanded", "true");
    $("#export-path").textContent = S.exportSubdir
      ? `${S.settings.archive_root || "归档根"}\\${S.exportSubdir}`
      : (S.settings.archive_root || "未设置归档目录");
  }
  function downloadBlob(content, filename, type) {
    const blob = content instanceof Blob ? content : new Blob([content], { type: type || "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url; anchor.download = filename;
    document.body.append(anchor); anchor.click(); anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1500);
  }
  function docHtml(title, html) {
    return `<!doctype html><html><head><meta charset="utf-8"><title>${esc(title)}</title>
      <style>body{font-family:"Microsoft YaHei",sans-serif;line-height:1.9;padding:32px;color:#1d1d1f}
      h1{font-size:22px}h2{font-size:17px;margin-top:24px}h3{font-size:14px}p{margin:8px 0}</style>
      </head><body><h1>${esc(title)}</h1>${html}</body></html>`;
  }
  function printAsPdf(title, html) {
    const win = window.open("", "_blank");
    if (!win) return toast("浏览器拦截了打印窗口，请允许弹出窗口后重试");
    win.document.write(docHtml(title, html));
    win.document.close();
    win.focus();
    setTimeout(() => win.print(), 350);
    toast("在打印窗口选择「另存为 PDF」");
  }
  async function writeArchive(filename, content, subdir) {
    return post(`/contents/${S.contentId}/export/write`,
      { filename, content, subdir: subdir || "" });
  }
  async function submitExport() {
    if (!S.contentId) return toast("请先选择内容");
    const format = $("input[name='export-format']:checked").value;
    const where = $("input[name='export-where']:checked").value;
    const title = S.content?.title || "内容导出";
    const bodyHtml = mdToHtml(S.markdown);
    const subdir = where === "custom" ? S.exportSubdir : "";
    try {
      if (format === "markdown" || format === "text") {
        const ext = format === "markdown" ? "md" : "txt";
        const filename = `content-${S.contentId}.${ext}`;
        if (where === "download") {
          const anchor = document.createElement("a");
          anchor.href = `${API}/contents/${S.contentId}/export?format=${format}&destination=download`;
          anchor.download = filename;
          document.body.append(anchor); anchor.click(); anchor.remove();
          toast(`已下载 ${filename}`);
        } else {
          const text = format === "text" ? plainText(S.markdown) : S.markdown;
          const result = await writeArchive(filename, text, subdir);
          toast(`已导出到 ${result.path}`);
        }
      } else if (format === "word") {
        const html = docHtml(title, bodyHtml);
        if (where === "download") downloadBlob(html, `content-${S.contentId}.doc`, "application/msword;charset=utf-8");
        else {
          const result = await writeArchive(`content-${S.contentId}.doc`, html, subdir);
          toast(`已导出到 ${result.path}`);
        }
      } else if (format === "pdf") {
        printAsPdf(title, bodyHtml);
      }
      closeSheet();
    } catch (error) { toast(`导出失败：${error.message}`); }
  }
  function openPopmenu(anchor, items) {
    const menu = $("#popmenu");
    menu.classList.remove("is-sources", "is-library-actions");
    menu.innerHTML = items.map((item) => `<button type="button" data-act="${item.act}" ${item.arg ? `data-arg="${esc(item.arg)}"` : ""}>${esc(item.label)}</button>`).join("");
    menu.hidden = false;
    const rect = anchor.getBoundingClientRect();
    menu.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - 180))}px`;
    menu.style.top = `${rect.bottom + 6}px`;
  }

  /* ------------------------- 事件委托 ------------------------- */
  async function onAction(act, target) {
    switch (act) {
      /* 图一 */
      case "account-import-start": return startAccountImport(target.dataset.source);
      case "account-import-folder": {
        const state = S.accountImport;
        if (state?.source === "xiaohongshu") return startXhsAlbumScan(state, target.dataset.folderId);
        return startFavoriteScan({ id: target.dataset.folderId, title: target.dataset.folderTitle });
      }
      case "account-import-back-folders": {
        const state = S.accountImport;
        if (!state || state.source !== "xiaohongshu" || !state.folders.length) return;
        state.activeAlbumId = null;
        state.step = "folders";
        state.selected.clear();
        state.onlyNew = false;
        return renderAccountImport();
      }
      case "account-import-close": return closeAccountImport();
      case "account-import-select-visible": {
        const state = S.accountImport;
        if (!state || state.step !== "candidates") return;
        const visible = state.candidates.filter((item) => item.selectable !== false && (!state.onlyNew || item.duplicate_status === "new"));
        const ids = visible.map((item) => item.candidate_id || item.id || item.url).filter(Boolean);
        const allSelected = ids.length > 0 && ids.every((id) => state.selected.has(id));
        ids.forEach((id) => allSelected ? state.selected.delete(id) : state.selected.add(id));
        return renderAccountImport();
      }
      case "account-import-submit": return submitAccountImport();
      case "intake-query": return intakeQuery();
      case "intake-clear":
        $("#intake-links").value = ""; invalidateIntakePreview(); renderIntakeCount();
        return toast("已清空");
      case "intake-submit": return intakeSubmit();
      case "confirm-cancel": closeConfirmation(); return;
      case "confirm-submit": {
        const action = S.confirmAction;
        const value = S.confirmPrompt ? $("#confirm-dialog-input").value : undefined;
        closeConfirmation();
        if (action) await action(value);
        return;
      }
      case "model-candidate": {
        const input = $(`[data-model-picker='${target.dataset.settingKey}']`, $("#set-pane"));
        return selectModelCandidate(input, target.dataset.modelValue);
      }
      /* 11-22 R5：双主动作——先关弹窗再执行分流；dismiss 不执行任何分流。 */
      case "triage-import": {
        const action = S.triageImportAction;
        closeTriageConfirmation();
        if (action) await action();
        return;
      }
      case "triage-discard": {
        const action = S.triageDiscardAction;
        closeTriageConfirmation();
        if (action) await action();
        return;
      }
      case "triage-dismiss": dismissTriage(); return;
      case "intake-local":
        if (!$("#intake-file").files.length) return toast("请先选择本地文件");
        try {
          const names = Array.from($("#intake-file").files).map((f) => f.name);
          await post("/imports/local", { paths: names });
          $("#intake-local-count").textContent = `识别 ${names.length} 个`;
          return toast(`已提交 ${names.length} 个本地文件`);
        } catch (error) { return toast(`识别失败：${error.message}`); }
      /* 图二 */
      case "jobs-refresh": {
        const refreshed = await syncJobsAfterMutation({ quiet: true });
        return toast(refreshed ? "任务列表已刷新" : "任务列表刷新失败，保留现有数据");
      }
      case "jobs-edit":
        S.jobEditMode = !S.jobEditMode;
        if (!S.jobEditMode) S.selectedJobs.clear();
        return renderJobs();
      case "jobs-pause": return jobAction("pause");
      case "jobs-resume": return jobAction("resume");
      case "jobs-retry": return jobAction("retry");
      case "jobs-delete": return jobAction("delete");
      case "jobs-select-all": {
        // R10：范围 = 当前筛选结果（去重后的代表任务）；父集子项一并计入，不重复计数。
        const visible = visibleJobIds();
        const allPicked = visible.length > 0 && visible.every((id) => S.selectedJobs.has(id));
        visible.forEach((id) => (allPicked ? S.selectedJobs.delete(id) : S.selectedJobs.add(id)));
        return renderJobs();
      }
      case "job-expand": {
        // R3：展开父集只补前 4 条，已展开数量在状态刷新后不回缩。
        const key = target.dataset.groupKey;
        if (expandedCollections.has(key)) expandedCollections.delete(key);
        else {
          expandedCollections.add(key);
          if (!jobViewLimit.has(key)) jobViewLimit.set(key, JOB_PAGE_SIZE);
        }
        return renderJobs();
      }
      case "job-expand-more": {
        const key = target.dataset.groupKey;
        jobViewLimit.set(key, (jobViewLimit.get(key) || JOB_PAGE_SIZE) + JOB_PAGE_SIZE);
        return renderJobs();
      }
      case "job-group-pause": {
        const key = target.dataset.groupKey;
        if (!jobCollections().some((item) => item.key === key)) return;
        try {
          const result = await post(`/job-collections/${encodeURIComponent(key)}/pause`);
          await syncJobsAfterMutation();
          toast(`已暂停 ${result.paused} 项${result.skipped ? `，跳过 ${result.skipped} 项` : ""}`);
        } catch (error) { toast(error.message); }
        return;
      }
      case "job-group-delete": {
        const key = target.dataset.groupKey;
        const group = jobCollections().find((item) => item.key === key);
        if (!group) return;
        return requestConfirmation(
          `确认删除整个合集（${group.jobs.length} 项任务）？已生成的知识库内容与归档会保留`,
          "删除",
          async () => {
            try {
              const result = await post(`/job-collections/${encodeURIComponent(key)}/delete`);
              await syncJobsAfterMutation();
              toast(`已删除 ${result.deleted} 项${result.cancelled ? `，其中 ${result.cancelled} 项先取消` : ""}`);
            } catch (error) { toast(error.message); }
          });
      }
      case "job-stage": {
        // R6：展开才拉真实阶段事件，不预先伪造阶段。
        const id = target.dataset.jobId;
        if (expandedJobs.has(id)) { expandedJobs.delete(id); return renderJobs(); }
        expandedJobs.add(id);
        if (jobEvents.has(id)) return renderJobs();
        return loadJobStages(id);
      }
      case "job-open": {
        const job = S.jobs.find((item) => item.id === target.dataset.jobId);
        const contentId = job?.content_id || idOf(S.history.find((entry) => entry?.job?.id === job?.id) || {});
        if (contentId) {
          S.contentReturn = { route: "tasks", jobFilter: S.jobFilter, scrollTop: $("#jobs-list").scrollTop };
          S.quickContext = null;
          go("content"); return openContent(contentId);
        }
        return toast("该任务还没有生成可查看的内容");
      }
      case "job-pause":
        return runJobRowAction(target.dataset.jobId, "正在暂停…",
          () => post(`/jobs/${target.dataset.jobId}/pause`, {}),
          ({ state }) => state === "paused" ? "已暂停" : `当前状态：${JOB_STATE_LABEL[state] || state}`);
      case "job-start":
        return runJobRowAction(target.dataset.jobId, "正在切换…",
          () => post(`/jobs/${target.dataset.jobId}/switch`, {}),
          ({ state, activeBefore, queue }) => {
            const message = state === "waiting" ? "已移到队首"
              : state === "running" ? "已开始处理"
                : `当前状态：${JOB_STATE_LABEL[state] || state}`;
            const oldJobReturned = activeBefore && activeBefore !== target.dataset.jobId
              && queue?.items?.some((item) => item.job_id === activeBefore);
            return oldJobReturned ? `${message}，原任务已回队列` : message;
          });
      case "job-resume":
        return runJobRowAction(target.dataset.jobId, "正在恢复…",
          () => post(`/jobs/${target.dataset.jobId}/resume`, {}),
          ({ state }) => state === "waiting" ? "已重新排队"
            : state === "running" ? "已开始处理"
              : `当前状态：${JOB_STATE_LABEL[state] || state}`);
      case "job-retry":
        return runJobRowAction(target.dataset.jobId, "正在重试…",
          () => post(`/jobs/${target.dataset.jobId}/retry`, {}),
          ({ result }) => {
            const retriedId = result?.job?.id;
            const retried = (S.jobs || []).find((item) => item.id === retriedId);
            if (!retried) return "状态刷新成功，但新任务未出现在列表中";
            const state = jobState(retried).key;
            return state === "waiting" ? "已重新排队"
              : state === "running" ? "已开始处理"
                : `当前状态：${JOB_STATE_LABEL[state] || state}`;
          });
      /* 图三 */
      case "lib-collection-back": S.libCollection = null; return renderLibrary();
      case "lib-refresh": {
        const refreshed = await syncLibraryData({ quiet: true });
        return toast(refreshed ? "知识库已刷新" : "知识库刷新失败，保留现有数据");
      }
      case "lib-trash":
        try { await refresh("trash"); go("trash"); }
        catch (error) { toast(error.message); }
        return;
      case "lib-total":
        S.activeTagIds = []; S.activeFolderIds = []; S.libCollection = null;
        S.libFilters.platform = null;
        closeLibraryGroupMenu();
        return renderLibrary();
      case "lib-group-menu-toggle":
        S.libGroupMenu = S.libGroupMenu === target.dataset.kind ? null : target.dataset.kind;
        return renderLibrary();
      case "lib-group-select": {
        const selectedIds = target.dataset.kind === "tag" ? S.activeTagIds : S.activeFolderIds;
        const index = selectedIds.indexOf(target.dataset.id);
        if (index >= 0) selectedIds.splice(index, 1);
        else selectedIds.push(target.dataset.id);
        S.libCollection = null;
        return renderLibrary();
      }
      case "lib-group-clear":
        if (target.dataset.kind === "tag") S.activeTagIds = [];
        else S.activeFolderIds = [];
        S.libCollection = null;
        return renderLibrary();
      case "lib-filter-clear-all":
        S.activeTagIds = []; S.activeFolderIds = [];
        S.libFilters = { platform: null, kind: null, duration: null, introduction: null };
        S.libFilterDimension = null; S.libFilterOpen = false; S.libCollection = null;
        closeLibraryGroupMenu();
        return renderLibrary();
      case "lib-groups-open":
        S.libManageScrollTop = $("#lib-grid").scrollTop;
        S.libManageOpen = true;
        closeLibraryGroupMenu();
        closePopmenu();
        return renderLibrary();
      case "lib-groups-back":
        S.libManageOpen = false;
        renderLibrary();
        $("#lib-grid").scrollTop = S.libManageScrollTop;
        S.libGridScrollTop = S.libManageScrollTop;
        return;
      case "lib-organize": {
        const items = [];
        S.folders.filter((folder) => !folder.is_system).forEach((folder) => {
          items.push({ label: `添加到收藏夹「${folder.name}」`, act: "lib-group-content-add", arg: `folder:${folder.id}` });
          items.push({ label: `从收藏夹「${folder.name}」移除`, act: "lib-group-content-remove", arg: `folder:${folder.id}` });
        });
        S.tags.forEach((tag) => {
          items.push({ label: `添加到标签「${tag.name}」`, act: "lib-group-content-add", arg: `tag:${tag.id}` });
          items.push({ label: `从标签「${tag.name}」移除`, act: "lib-group-content-remove", arg: `tag:${tag.id}` });
        });
        if (!items.length) return;
        openPopmenu(target, items);
        const menu = $("#popmenu");
        menu.classList.add("is-library-actions");
        const anchorRect = target.getBoundingClientRect();
        menu.style.left = `${Math.max(8, Math.min(anchorRect.left, window.innerWidth - menu.offsetWidth - 8))}px`;
        const below = anchorRect.bottom + 6;
        menu.style.top = `${below + menu.offsetHeight <= window.innerHeight ? below : Math.max(8, anchorRect.top - menu.offsetHeight - 6)}px`;
        return;
      }
      case "lib-filter":
        S.libFilterOpen = !S.libFilterOpen;
        if (!S.libFilterOpen) S.libFilterDimension = null;
        return renderLibrary();
      case "lib-edit":
        S.libEditMode = !S.libEditMode;
        if (!S.libEditMode) S.selectedContents.clear();
        return renderLibrary();
      case "lib-delete": {
        const ids = Array.from(S.selectedContents);
        if (!ids.length) return toast("请先勾选内容");
        return requestConfirmation(`确认将 ${ids.length} 条内容移入回收站？`, "移入回收站", async () => {
          let done = 0;
          for (const id of ids) {
            try { await del(`/contents/${id}`); done += 1; }
            catch (error) { console.warn("[lib-delete]", id, error.message); }
          }
          S.selectedContents.clear();
          await refresh("history"); renderLibrary();
          toast(`已删除 ${done}/${ids.length} 条`);
        });
      }
      case "lib-group-create": {
        const isTag = target.dataset.kind === "tag";
        return requestProductPrompt(isTag ? "新标签名称" : "新收藏夹名称", "名称", "", async (name) => {
          if (!name.trim()) return;
          try {
            await post(isTag ? "/tags" : "/favorite-folders", { name: name.trim() });
            await refresh(isTag ? "tags" : "folders");
            renderLibrary();
            toast("已创建");
          } catch (error) { toast(error.message); }
        });
      }
      case "lib-group-rename": {
        closePopmenu();
        const [kind, id] = (target.dataset.arg || "").split(":", 2);
        const isTag = kind === "tag";
        const groups = isTag ? S.tags : S.folders;
        const group = groups.find((item) => item.id === id);
        if (!group) return;
        return requestProductPrompt(`重命名${isTag ? "标签" : "收藏夹"}`, "名称", group.name, async (name) => {
          if (!name.trim()) return;
          try {
            await patch(`${isTag ? "/tags" : "/favorite-folders"}/${group.id}`, { name: name.trim() });
            await refresh(isTag ? "tags" : "folders");
            renderLibrary();
            toast("已重命名");
          } catch (error) { toast(error.message); }
        });
      }
      case "lib-group-delete": {
        closePopmenu();
        const [kind, id] = (target.dataset.arg || "").split(":", 2);
        const isTag = kind === "tag";
        const groups = isTag ? S.tags : S.folders;
        const group = groups.find((item) => item.id === id);
        if (!group) return;
        return requestConfirmation(
          `确认删除${isTag ? "标签" : "收藏夹"}「${group.name}」？内容会保留在总库。`,
          "删除分组",
          async () => {
            try {
              await del(`${isTag ? "/tags" : "/favorite-folders"}/${group.id}`);
              if (isTag) S.activeTagIds = S.activeTagIds.filter((id) => id !== group.id);
              else S.activeFolderIds = S.activeFolderIds.filter((id) => id !== group.id);
              await refresh(isTag ? "tags" : "folders");
              renderLibrary();
              toast("已删除");
            } catch (error) { toast(error.message); }
          });
      }
      case "lib-group-more": {
        const kind = target.dataset.kind;
        const groupId = target.dataset.id;
        openPopmenu(target, [
          { label: "重命名", act: "lib-group-rename", arg: `${kind}:${groupId}` },
          { label: "删除", act: "lib-group-delete", arg: `${kind}:${groupId}` },
        ]);
        return;
      }
      case "tag-create": case "folder-create": {
        const isTag = act === "tag-create";
        return requestProductPrompt(isTag ? "新标签名称" : "新收藏夹名称", "名称", "", async (name) => {
          if (!name) return;
          try {
            await post(isTag ? "/tags" : "/favorite-folders", { name });
            await refresh(isTag ? "tags" : "folders"); renderLibrary();
            return toast("已创建");
          } catch (error) { return toast(error.message); }
        });
      }
      case "lib-group-content-add": case "lib-group-content-remove": {
        const [kind, scopeId] = (target.dataset.arg || "").split(":", 2);
        const group = (kind === "tag" ? S.tags : S.folders).find((item) => item.id === scopeId);
        if (!group) return;
        S.libMode = act === "lib-group-content-add" ? "add" : "remove";
        S.libModeKind = kind;
        S.libModeTargetId = scopeId;
        S.pickedContents.clear();
        closePopmenu();
        return renderLibrary();
      }
      case "tag-manage": case "folder-manage": {
        const isTag = act === "tag-manage";
        const selectedIds = isTag ? S.activeTagIds : S.activeFolderIds;
        if (selectedIds.length !== 1) return toast("请先选择一个具体分组");
        S.libMode = "remove"; S.libModeKind = isTag ? "tag" : "folder"; S.libModeTargetId = selectedIds[0];
        S.pickedContents.clear();
        return renderLibrary();
      }
      case "tag-add": case "folder-add": {
        const isTag = act === "tag-add";
        const selectedIds = isTag ? S.activeTagIds : S.activeFolderIds;
        if (selectedIds.length !== 1) return toast("请先选择一个具体分组");
        S.libMode = "add"; S.libModeKind = isTag ? "tag" : "folder"; S.libModeTargetId = selectedIds[0];
        S.pickedContents.clear();
        return renderLibrary();
      }
      case "lib-mode-cancel":
        S.libMode = null; S.libModeKind = null; S.libModeTargetId = null; S.pickedContents.clear();
        return renderLibrary();
      case "lib-mode-add": {
        const ids = Array.from(S.pickedContents);
        if (!ids.length) return toast("请先选择内容");
        const isTag = S.libModeKind === "tag";
        const key = isTag ? "tag_ids" : "favorite_folder_ids";
        const scopeId = S.libModeTargetId;
        const scopeName = (isTag ? S.tags : S.folders).find((item) => item.id === scopeId)?.name || "分组";
        let done = 0;
        for (const id of ids) {
          const entry = S.history.find((item) => idOf(item) === id);
          if (!entry) continue;
          const values = new Set(contentOf(entry)[key] || []);
          values.add(scopeId);
          try { await patch(`/contents/${id}`, { [key]: Array.from(values) }); done += 1; }
          catch (error) { toast(error.message); }
        }
        if (done) await Promise.all([refresh("history"), refresh(isTag ? "tags" : "folders")]);
        S.libMode = null; S.libModeKind = null; S.libModeTargetId = null; S.pickedContents.clear();
        renderLibrary();
        return toast(`已添加 ${done} 条到「${scopeName}」`);
      }
      case "lib-mode-remove": {
        const ids = Array.from(S.pickedContents);
        if (!ids.length) return toast("请先选择内容");
        const isTag = S.libModeKind === "tag";
        const scopeId = S.libModeTargetId;
        const scopeName = (isTag ? S.tags : S.folders).find((item) => item.id === scopeId)?.name || "分组";
        const scopeKind = isTag ? "标签" : "收藏夹";
        return requestConfirmation(`确认将 ${ids.length} 条内容从${scopeKind}「${scopeName}」移除？内容仍保留在总库。`, "移出分组", async () => {
          const key = isTag ? "tag_ids" : "favorite_folder_ids";
          let done = 0;
          for (const id of ids) {
            const entry = S.history.find((item) => idOf(item) === id);
            if (!entry) continue;
            const values = new Set(contentOf(entry)[key] || []);
            values.delete(scopeId);
            try { await patch(`/contents/${id}`, { [key]: Array.from(values) }); done += 1; }
            catch (error) { toast(error.message); }
          }
          if (done) await Promise.all([refresh("history"), refresh(isTag ? "tags" : "folders")]);
          S.pickedContents.clear();
          S.libMode = null; S.libModeKind = null; S.libModeTargetId = null;
          renderLibrary();
          toast(`已从「${scopeName}」移出 ${done} 条`);
        });
      }
      case "lib-filter-dim":
        S.libFilterDimension = target.dataset.dim;
        return renderLibrary();
      case "lib-filter-back":
        S.libFilterDimension = null;
        return renderLibrary();
      case "lib-filter-value":
        S.libFilters[target.dataset.dim] =
          S.libFilters[target.dataset.dim] === target.dataset.value ? null : target.dataset.value;
        return renderLibrary();
      case "lib-filter-clear":
        S.libFilters = { platform: null, kind: null, duration: null, introduction: null };
        S.libFilterDimension = null;
        return renderLibrary();
      case "trash-back": return go("library");
      case "trash-restore": {
        try {
          await post(`/contents/${target.dataset.id}/restore`, {});
          await Promise.all([refresh("history"), refresh("trash")]);
          renderTrash(); toast("已恢复");
        } catch (error) { toast(error.message); }
        return;
      }
      case "trash-purge": {
        const id = target.dataset.id;
        const title = contentOf((S.trash || []).find((item) => idOf(item) === id))?.title || "这条内容";
        return requestConfirmation(`确认彻底删除「${title}」？归档文件也会一并删除，且无法恢复`, "彻底删除", async () => {
          try {
            await del(`/contents/${id}/purge`);
            await Promise.all([refresh("history"), refresh("trash")]);
            renderTrash(); toast("已彻底删除");
          } catch (error) { toast(error.message); }
        });
      }
      case "tag-delete": case "folder-delete": {
        const isTag = act === "tag-delete";
        const item = (isTag ? S.tags : S.folders).find((entry) => entry.id === target.dataset.arg);
        const label = isTag ? "标签" : "收藏夹";
        return requestConfirmation(`确认删除${item?.name ? `「${item.name}」` : label}？`, "删除", async () => {
          try {
            await del(`${isTag ? "/tags" : "/favorite-folders"}/${target.dataset.arg}`);
            await refresh(isTag ? "tags" : "folders"); renderLibrary();
            toast("已删除");
          } catch (error) { toast(error.message); }
        });
      }
      case "tag-more": return toast(`共 ${S.tags.length} 个标签`);
      case "folder-backfill":
        try { const result = await api("/content-introductions/backfill/preview"); toast(`可补齐 ${result.eligible_count ?? 0} 条简介`); }
        catch (error) { toast(error.message); }
        return;
      case "tile-more":
        return openPopmenu(target, [
          { label: "打开内容", act: "tile-open", arg: target.dataset.contentId },
          { label: "复制来源链接", act: "tile-copy", arg: target.dataset.contentId },
          { label: "删除", act: "tile-delete", arg: target.dataset.contentId },
        ]);
      case "tile-open":
        S.quickContext = currentQuickContext();
        go("content");
        return openContent(target.dataset.arg);
      case "tile-copy": {
        const entry = S.history.find((item) => idOf(item) === target.dataset.arg);
        const url = contentOf(entry).canonical_url || "";
        if (!url) return toast("该内容没有来源链接");
        await navigator.clipboard.writeText(url); return toast("已复制来源链接");
      }
      case "tile-delete":
        return requestConfirmation("确认移入回收站？", "移入回收站", async () => {
          try { await del(`/contents/${target.dataset.arg}`); await refresh("history"); renderLibrary(); toast("已移入回收站"); }
          catch (error) { toast(error.message); }
        });
      /* 图四 */
      case "answer-sources": {
        const ids = sourceRefs.get(target.dataset.sourceKey) || [];
        const items = ids.map((id) => {
          const matched = S.history.find((entry) => idOf(entry) === id);
          return { label: matched ? (contentOf(matched).title || id) : `内容 · ${String(id).slice(-8)}`, act: "source-open", arg: id };
        });
        openPopmenu(target, items.length ? items : [{ label: "暂无来源内容", act: "noop" }]);
        $("#popmenu").classList.add("is-sources");
        return;
      }
      case "source-open":
        closePopmenu();
        S.quickContext = null;
        go("content");
        return openContent(target.dataset.arg);
      case "ask-expand": return setAskState("expanded");
      case "ask-collapse": return setAskState("collapsed");
      case "ask-open-settings": return go("settings");
      case "ask-new":
        try {
          const session = await post("/ask/sessions", { title: "新会话", scope: scopePayload() });
          S.sessionId = session.id; S.sessionDetail = null; S.lastQueryId = null;
          $("#ask-talk-head").textContent = "今天 · 新会话";
          renderAskStream(); await refresh("sessions"); renderAsk(); toast("已创建新会话");
        } catch (error) { toast(error.message); }
        return;
      case "ask-send": return askSend();
      case "ask-clear": $("#ask-input").value = ""; return;
      case "ask-stop": return stopAskQuery(target.dataset.queryId);
      case "ask-continue": case "ask-retry":
        return continueAskQuery(target.dataset.queryId || S.lastQueryId);
      case "ask-query-refresh": {
        const queryId = target.dataset.queryId;
        const query = S.askQueries.get(queryId);
        if (query) void watchAskQuery(queryId, query.session_id);
        return;
      }
      case "ask-apply": {
        S.applied = { kind: S.scopeKind, tags: new Set(S.scopeTags),
          folders: new Set(S.scopeFolders), contents: new Set(S.scopeContents) };
        const label = ({ all: "全库", tag: "标签", folder: "收藏夹" })[S.scopeKind];
        const n = S.applied.contents.size;
        $("#ask-scope-note").textContent = n
          ? `范围已设为「${label}」· 已选 ${n} 条内容`
          : `范围已设为「${label}」· ${S.history.length} 条内容`;
        return toast(n ? `已应用 ${n} 条内容` : "范围已应用");
      }
      case "ask-session-delete": {
        const id = target.dataset.sessionId;
        if (!id) return;
        return requestConfirmation("确认删除这个会话？", "删除", async () => {
          try {
            await del(`/ask/sessions/${id}`);
            if (S.sessionId === id) { S.sessionId = null; S.sessionDetail = null; renderAskStream(); }
            await refresh("sessions"); renderAsk(); toast("会话已删除");
          } catch (error) { toast(error.message); }
        });
      }
      case "scope-back": S.scopeLevel = null; return renderScopeList();
      case "scope-select-all": {
        const boxes = $$("[data-scope-content]");
        const allOn = boxes.length > 0 && boxes.every((box) => box.checked);
        boxes.forEach((box) => {
          box.checked = !allOn;
          if (!allOn) S.scopeContents.add(box.dataset.scopeContent);
          else S.scopeContents.delete(box.dataset.scopeContent);
        });
        return updateScopeSummary();
      }
      case "clear-secret": {
        /* R4：显式清除密钥，后端同步清掉该 provider 已选模型；不经过连通性测试。 */
        const provider = target.dataset.provider;
        if (!["summary", "asr"].includes(provider)) return;
        try {
          const body = { clear_secret_provider: provider };
          if (provider === "summary") body.summary_api_key = "";
          else body.asr_api_key = "";
          await api("/settings", { method: "PUT", body });
          if (provider === "summary") S.summaryModels = [];
          else S.asrModels = [];
          await refresh("settings");
          await renderSettingsPane();
          toast("已清除密钥与模型");
        } catch (error) { toast(error.message); }
        return;
      }
      case "settings-save": {
        const pane = $("#set-pane");
        const saved = S.settings;
        const field = (key) => $(`[data-setting-key='${key}']`, pane);
        const body = {};
        const archive = field("archive_root")?.value.trim();
        if (archive && archive !== (saved.archive_root || "")) body.archive_root = archive;
        const engine = $("input[name='asr-engine']:checked", pane)?.value || saved.asr_engine || "cloud";
        let asrTouched = false;
        if (engine === "local") {
          const model = $("#asr-local-model", pane)?.value || "";
          if (engine !== saved.asr_engine || model !== (saved.asr_local_model || "")) {
            body.asr_engine = "local";
            if (model) body.asr_model = model;
            asrTouched = true;
          }
        } else {
          if (engine !== saved.asr_engine) { body.asr_engine = "cloud"; asrTouched = true; }
          const apiUrl = field("asr_api_url")?.value.trim() || "";
          const asrModel = field("asr_model")?.value.trim() || "";
          const asrKey = field("asr_api_key")?.value.trim() || "";
          if (apiUrl && apiUrl !== (saved.asr_cloud_api_url || "")) { body.asr_api_url = apiUrl; asrTouched = true; }
          if (asrModel && asrModel !== (saved.asr_cloud_model || "")) { body.asr_model = asrModel; asrTouched = true; }
          if (asrKey) { body.asr_api_key = asrKey; asrTouched = true; }
        }
        const summaryUrl = field("summary_api_url")?.value.trim() || "";
        const summaryModel = field("summary_model")?.value.trim() || "";
        const summaryKey = field("summary_api_key")?.value || "";
        const summaryPrompt = field("summary_prompt")?.value ?? "";
        if (summaryPrompt !== (saved.summary_prompt || "")) body.summary_prompt = summaryPrompt;
        const summaryChanged = (summaryUrl && summaryUrl !== (saved.summary_api_url || ""))
          || (summaryModel && summaryModel !== (saved.summary_model || ""))
          || Boolean(summaryKey);
        if (summaryChanged) {
          /* 总结配置必须先过连通性测试换 token，否则 PUT 会被后端 422 拒绝。 */
          try {
            const tested = await post("/settings/summary/test", {
              summary_api_url: summaryUrl || undefined,
              summary_api_key: summaryKey || undefined,
              summary_model: summaryModel || undefined,
            });
            body.summary_validation_token = tested.validation_token;
          } catch (error) { return toast(error.message); }
          if (summaryUrl) body.summary_api_url = summaryUrl;
          if (summaryModel) body.summary_model = summaryModel;
          if (summaryKey) body.summary_api_key = summaryKey;
        }
        if (!Object.keys(body).length) return toast("没有需要保存的修改");
        try {
          await api("/settings", { method: "PUT", body });
          await refresh("settings");
          await renderSettingsPane();
          if (asrTouched && S.settings.asr_engine === "cloud" && !S.settings.asr_cloud_configured) {
            return toast("云端 ASR 未配置，已按本地识别");
          }
          toast("设置已保存");
        } catch (error) { toast(error.message); }
        return;
      }
      case "summary-models": {
        try {
          const result = await post("/settings/summary/models", {
            summary_api_url: settingValue("summary_api_url") || undefined,
            summary_api_key: settingValue("summary_api_key") || undefined,
          });
          const models = result.models || [];
          if (!models.length) return toast(result.message || "未获取到模型");
          S.summaryModels = models.map(String);
          const input = $("#summary-model-input");
          if (input) renderModelCandidates(input);
          toast(`已获取 ${models.length} 个模型`);
        } catch (error) { toast(error.message); }
        return;
      }
      case "summary-test": {
        try {
          const result = await post("/settings/summary/test", {
            summary_api_url: settingValue("summary_api_url") || undefined,
            summary_api_key: settingValue("summary_api_key") || undefined,
            summary_model: settingValue("summary_model") || undefined,
          });
          toast(result.message || "连接成功");
        } catch (error) { toast(error.message); }
        return;
      }
      case "asr-models": {
        try {
          const result = await post("/settings/asr/models", {
            asr_api_url: settingValue("asr_api_url") || undefined,
            asr_api_key: settingValue("asr_api_key") || undefined,
          });
          const models = result.models || [];
          if (!models.length) return toast(result.message || "未获取到模型");
          S.asrModels = models.map(String);
          const input = $("#asr-model-input");
          if (input) renderModelCandidates(input);
          toast(`已获取 ${models.length} 个模型`);
        } catch (error) { toast(error.message); }
        return;
      }
      case "asr-test": {
        try {
          const result = await post("/settings/asr/test", {
            asr_api_url: settingValue("asr_api_url") || undefined,
            asr_api_key: settingValue("asr_api_key") || undefined,
            asr_model: settingValue("asr_model") || undefined,
          });
          toast(result.message || "连接成功");
        } catch (error) { toast(error.message); }
        return;
      }
      case "asr-retry":
        S.asrLocalModels = null;
        S.asrLocalModelsError = null;
        return loadAsrLocalModels();
      /* 图五 */
      case "settings-back": return go(S.settingsReturnRoute || "intake");
      case "conn-toggle": {
        const platform = target.dataset.platform;
        try {
          if (target.dataset.on === "true") await del(`/platform-connections/${platform}`);
          else if (platform === "xiaohongshu") {
            const result = await requestDesktopShell("xiaohongshu", "open_login", null, {}, { timeoutMs: 30 * 60 * 1000, accepted: XHS_SESSION_STATUSES });
            await saveXhsSession(result);
          } else await post(`/platform-connections/${platform}/connect`, {});
          await refresh("connections"); renderSettingsPane(); toast("连接状态已更新");
        } catch (error) { toast(error.message); }
        return;
      }
      case "conn-check-all": return checkAllConnections();
      case "conn-check": {
        if (S.environmentChecking) return;
        S.environmentChecking = true;
        S.environmentCheckError = null;
        renderSettingsPane();
        try {
          S.environmentCheck = await api("/environment/check?check_network=false");
          toast(S.environmentCheck.status === "ok" ? "环境自检完成：正常"
            : S.environmentCheck.status === "warning" ? "环境自检完成：有待处理项" : "环境自检完成：存在异常");
        } catch (error) {
          S.environmentCheckError = error.message;
          toast("环境自检失败，保留上次结果");
        } finally {
          S.environmentChecking = false;
          renderSettingsPane();
        }
        return;
      }
      /* 图七 */
      case "doc-back": case "doc-back-bottom": return returnFromContent();
      case "doc-collapse": return setDocQuickCollapsed(true);
      case "doc-restore": return setDocQuickCollapsed(false);
      case "outline-collapse": return setDocOutlineCollapsed(true);
      case "outline-restore": return setDocOutlineCollapsed(false);
      case "doc-refresh": return refreshCurrentContent();
      case "doc-copy":
        try { await navigator.clipboard.writeText(plainText(S.markdown)); toast("已复制正文"); }
        catch (error) { toast(error.message); }
        return;
      case "doc-export": return $("#export-sheet").hidden ? openSheet(target) : closeSheet();
      case "doc-delete":
        return requestConfirmation("确认删除这条内容？", "删除", async () => {
          try { await del(`/contents/${S.contentId}`); await refresh("history"); toast("已删除"); go("library"); }
          catch (error) { toast(error.message); }
        });
      case "doc-more": return openPopmenu(target, [
        { label: "复制来源链接", act: "doc-copy-link" },
        { label: "查看版本", act: "doc-versions" },
        { label: "切换外观", act: "doc-theme" },
      ]);
      case "doc-copy-link":
        await navigator.clipboard.writeText(S.content?.canonical_url || "");
        return toast("已复制来源链接");
      case "doc-versions": return openPopmenu(target, S.versions.length
        ? S.versions.map((version, index) => ({ label: `v${version.version_number}`, act: "doc-version-pick", arg: String(index) }))
        : [{ label: "仅有一个版本", act: "noop" }]);
      case "doc-version-pick":
        S.versionIndex = Number(target.dataset.arg) || 0;
        S.markdown = S.versions[S.versionIndex]?.markdown || "";
        renderContentBody(); return toast("已切换版本");
      case "doc-version": return openPopmenu(target, S.versions.length
        ? S.versions.map((version, index) => ({ label: `v${version.version_number}`, act: "doc-version-pick", arg: String(index) }))
        : [{ label: "仅有一个版本", act: "noop" }]);
      case "doc-theme": {
        const next = document.documentElement.dataset.theme === "night" ? "light" : "night";
        document.documentElement.dataset.theme = next;
        return toast(`已切换为${next === "night" ? "深色" : "浅色"}`);
      }
      case "doc-edit-tags": {
        const editor = $("#doc-tag-editor");
        editor.hidden = !editor.hidden;
        if (!editor.hidden) {
          editor.innerHTML = `<input class="input" id="doc-tag-input" placeholder="输入标签名，逗号分隔" value="${esc((S.content?.tag_names || []).join(", "))}" />
            <button class="btn btn--primary" type="button" data-act="doc-save-tags">保存</button>`;
        }
        return;
      }
      case "doc-save-tags": {
        const names = ($("#doc-tag-input")?.value || "").split(/[,，]/).map((v) => v.trim()).filter(Boolean);
        try {
          await patch(`/contents/${S.contentId}`, { category: names[0] || "未分类" });
          S.content.category = names[0] || "未分类";
          $("#doc-tag-editor").hidden = true; toast("已保存");
        } catch (error) { toast(error.message); }
        return;
      }
      case "doc-edit": {
        S.editing = !S.editing;
        if (S.editing) {
          $("#doc-intro").innerHTML = `<textarea class="input" id="doc-intro-input" rows="2">${esc(S.content?.introduction || "")}</textarea>
            <button class="btn btn--primary" type="button" data-act="doc-save">保存</button>`;
        } else renderContentBody();
        return;
      }
      case "doc-save": {
        const value = $("#doc-intro-input")?.value || "";
        try {
          await patch(`/contents/${S.contentId}`, { introduction: value.slice(0, 30) });
          S.content.introduction = value.slice(0, 30);
          S.editing = false; renderContentBody(); toast("已保存");
        } catch (error) { toast(error.message); }
        return;
      }
      case "doc-regenerate": return openRestyle();
      case "restyle-close": return closeRestyle();
      case "restyle-submit": return submitRestyle();
      case "doc-open-source": return openSourceUrl(target.dataset.url);
      case "doc-prev": return neighbour(-1);
      case "doc-next": return neighbour(1);
      case "doc-top": $("#doc-scroll").scrollTop = 0; return;
      /* 图八 */
      case "export-close": return closeSheet();
      case "export-change": {
        return requestProductPrompt("自定义位置", "子文件夹", S.exportSubdir || "导出", (value) => {
          S.exportSubdir = value.trim().replace(/[\\/:*?"<>|]/g, "");
          $("input[name='export-where'][value='custom']").checked = true;
          $("#export-path").textContent = `${S.settings.archive_root || "归档根"}\\${S.exportSubdir}`;
          return toast("已更新导出位置");
        });
      }
      case "export-submit": return submitExport();
      case "noop": return;
      default:
        // 40 个 data-act 已逐一核对有分支；真正的未知 action 给可见反馈，不做静默死按钮。
        console.warn("[unhandled action]", act);
        return toast(`未接线的操作：${act}`);
    }
  }

  /* ------------------------- 图三/四：问答两态 + 双分隔线拖动（C10） ------------------------- */
  const ASK_RESIZER_RANGES = {
    sessions: { varName: "--sess-w", min: 220, max: 360, dir: 1 },
    settings: { varName: "--set-w", min: 260, max: 420, dir: -1 },
  };
  const ASK_MIN_CENTER = 420;   // 中央对话最小可读宽度
  const ASK_GUTTER = 12;        // 两条分隔线各占 12px 列
  function askColumns() { return $("#ask-columns"); }
  function askVar(name) {
    const columns = askColumns();
    if (!columns) return 0;
    const value = parseFloat(getComputedStyle(columns).getPropertyValue(name));
    return Number.isFinite(value) ? value : 0;
  }
  function initAskState() {
    const columns = askColumns();
    if (!columns) return;
    if (!columns.dataset.askState) columns.dataset.askState = S.askState;
    S.askState = columns.dataset.askState;
  }
  function setAskState(state) {
    const columns = askColumns();
    if (!columns) return;
    const next = state === "expanded" ? "expanded" : "collapsed";
    S.askState = next;
    columns.dataset.askState = next;
    // C10：折叠只切构图、把宽度释放给对话区；内联宽度保持不动，
    // 再次展开回填折叠前宽度。绝不清空范围选择 / 已应用范围 / 当前会话 / 会话详情。
    if (S.askWidths.sessions != null) {
      columns.style.setProperty("--sess-w", `${S.askWidths.sessions}px`);
    }
    if (S.askWidths.settings != null) {
      columns.style.setProperty("--set-w", `${S.askWidths.settings}px`);
    }
  }
  function initAskResizers() {
    const columns = askColumns();
    if (!columns) return;
    $$(".ask-resizer").forEach((resizer) => {
      resizer.addEventListener("pointerdown", (event) => {
        const cfg = ASK_RESIZER_RANGES[resizer.dataset.resizer];
        if (!cfg) return;
        const startX = event.clientX;
        const startW = askVar(cfg.varName);
        const totalW = columns.getBoundingClientRect().width;
        const expanded = columns.dataset.askState !== "collapsed";
        const otherSess = askVar("--sess-w");
        const otherSet = askVar("--set-w");
        // 中央 >= 420px：窗口不足时收紧可拖上限，不能把对话挤成窄条。
        const maxByCenter = cfg.dir === 1
          ? (expanded ? totalW - otherSet - ASK_GUTTER * 2 - ASK_MIN_CENTER
                      : totalW - ASK_GUTTER - ASK_MIN_CENTER)
          : totalW - otherSess - ASK_GUTTER * 2 - ASK_MIN_CENTER;
        const upper = Math.max(cfg.min, Math.min(cfg.max, maxByCenter));
        resizer.classList.add("is-dragging");
        event.preventDefault();

        const onMove = (moveEvent) => {
          let width = startW + (moveEvent.clientX - startX) * cfg.dir;
          width = Math.max(cfg.min, Math.min(upper, width));
          const rounded = Math.round(width);
          columns.style.setProperty(cfg.varName, `${rounded}px`);
          S.askWidths[resizer.dataset.resizer] = rounded;
        };
        const onUp = () => {
          resizer.classList.remove("is-dragging");
          document.removeEventListener("pointermove", onMove);
          document.removeEventListener("pointerup", onUp);
          document.removeEventListener("pointercancel", onUp);
        };
        document.addEventListener("pointermove", onMove);
        document.addEventListener("pointerup", onUp);
        document.addEventListener("pointercancel", onUp);
      });
    });
  }

  function bindEvents() {
    $("#lib-grid").addEventListener("scroll", () => { S.libGridScrollTop = $("#lib-grid").scrollTop; }, { passive: true });
    /* 等待中的任务可拖拽换位：只改队列顺序，不改任务状态。 */
    document.addEventListener("dragstart", (event) => {
      const card = event.target.closest?.("[data-drag-job]");
      if (!card) return;
      dragJobId = card.dataset.dragJob;
      card.classList.add("is-dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", dragJobId);
    });
    document.addEventListener("dragend", () => {
      dragJobId = null;
      $$("#jobs-list .is-dragging, #jobs-list .is-drop-target").forEach((el) =>
        el.classList.remove("is-dragging", "is-drop-target"));
    });
    document.addEventListener("dragover", (event) => {
      const card = event.target.closest?.("[data-drag-job]");
      if (!dragJobId || !card || card.dataset.dragJob === dragJobId) return;
      event.preventDefault();
      $$("#jobs-list .is-drop-target").forEach((el) => el.classList.remove("is-drop-target"));
      card.classList.add("is-drop-target");
    });
    document.addEventListener("drop", async (event) => {
      const card = event.target.closest?.("[data-drag-job]");
      if (!dragJobId || !card || card.dataset.dragJob === dragJobId) return;
      event.preventDefault();
      const moving = dragJobId;
      dragJobId = null;
      const ids = $$("#jobs-list [data-drag-job]").map((el) => el.dataset.dragJob);
      const target = ids.indexOf(card.dataset.dragJob);
      if (target < 0) return;
      try {
        await post("/queue/move", { job_id: moving, target_index: target });
        await syncJobsAfterMutation();
      } catch (error) { toast(`调整顺序失败：${error.message}`); }
    });
    document.addEventListener("click", async (event) => {
      const target = event.target;
      if (S.libGroupMenu && !target.closest?.(".lib-group-filter")) closeLibraryGroupMenu();
      if (!target.closest?.(".model-picker")) closeAllModelCandidates();
      if (!target.closest?.(".product-select")) closeProductSelects();
      const selectTrigger = target.closest?.("[data-product-select-trigger]");
      if (selectTrigger) {
        const menu = $(".product-select__options", selectTrigger.closest(".product-select"));
        if (menu.hidden) openProductSelect(selectTrigger);
        else closeProductSelect(selectTrigger.closest(".product-select"));
        return;
      }
      const selectOption = target.closest?.("[data-product-select-option]");
      if (selectOption) return chooseProductSelectOption(selectOption);
      const route = target.closest?.("[data-route]");
      if (route) return go(route.dataset.route);
      const tab = target.closest?.("[data-intake-tab]");
      if (tab) {
        S.intakeTab = tab.dataset.intakeTab;
        $$("[data-intake-tab]").forEach((item) => {
          const current = item === tab;
          item.classList.toggle("is-current", current);
          item.setAttribute("aria-selected", String(current));
        });
        $$("[data-intake-panel]").forEach((panel) => { panel.hidden = panel.dataset.intakePanel !== S.intakeTab; });
        return;
      }
      const filter = target.closest?.("[data-job-filter]");
      if (filter) {
        S.jobFilter = filter.dataset.jobFilter;
        $$("[data-job-filter]").forEach((item) => {
          const current = item === filter;
          item.classList.toggle("is-current", current);
          item.setAttribute("aria-selected", String(current));
        });
        return renderJobs();
      }
      const section = target.closest?.("[data-section]");
      if (section) { S.settingsSection = section.dataset.section; return renderSettingsPane(); }
      const kind = target.closest?.("[data-scope-kind]");
      if (kind) {
        S.scopeKind = kind.dataset.scopeKind;
        S.scopeLevel = null;
        S.scopeContents.clear();
        $$("[data-scope-kind]").forEach((item) => item.classList.toggle("is-current", item === kind));
        renderScopeList(); return updateScopeSummary();
      }
      const group = target.closest?.("[data-scope-group]");
      if (group) {
        S.scopeLevel = { kind: S.scopeKind, id: group.dataset.scopeGroup, name: group.dataset.scopeGroupName };
        return renderScopeList();
      }
      const collectionTile = target.closest?.("[data-collection-id]");
      if (collectionTile && !target.closest("[data-act]")) {
        S.libCollection = collectionTile.dataset.collectionId;
        return renderLibrary();
      }
      const tile = target.closest?.(".tile[data-content-id]");
      if (tile && !target.closest("[data-act]") && !target.closest(".tile__pick")) {
        if (S.libMode) {
          const id = tile.dataset.contentId;
          if (S.pickedContents.has(id)) S.pickedContents.delete(id);
          else S.pickedContents.add(id);
          return renderLibrary();
        }
        if (S.libEditMode) {
          const id = tile.dataset.contentId;
          if (S.selectedContents.has(id)) S.selectedContents.delete(id);
          else S.selectedContents.add(id);
          return renderLibrary();
        }
        S.contentReturn = { route: "library", scrollTop: $("#lib-grid").scrollTop };
        S.quickContext = currentQuickContext();
        go("content");
        await openContent(tile.dataset.contentId);
        return;
      }
      /* 11-18 R4：父集合先展开子集选择面板，不默认进入内容界面；选中子集才走 data-quick。 */
      const quickGroup = target.closest?.("[data-quick-group]");
      if (quickGroup) {
        const key = quickGroup.dataset.quickGroup;
        S.quickOpen = S.quickOpen === key ? null : key;
        return renderQuickList();
      }
      const quick = target.closest?.("[data-quick]");
      if (quick) return openContent(quick.dataset.quick);
      const session = target.closest?.("[data-session]");
      if (session) {
        S.sessionId = session.dataset.session;
        S.sessionDetail = null;
        renderAskStream();
        await loadAskSession(S.sessionId);
        return renderAsk();
      }
      const outline = target.closest?.("[data-outline]");
      if (outline) {
        $$(".outline-item").forEach((item) => item.classList.toggle("is-current", item === outline));
        const heading = $("#doc-article")?.querySelectorAll("h2, h3")[Number(outline.dataset.outline)];
        return heading?.scrollIntoView({ behavior: "smooth", block: "start" });
      }
      const action = target.closest?.("[data-act]");
      if (action) {
        if (!target.closest("#popmenu")) closePopmenu();
        /* 11-21 R1（v2）：批量操作未走完（含刷新窗口期），改状态的入口一律不接。 */
        if (jobsBatchBusy && JOB_MUTATING_ACTS.has(action.dataset.act)) {
          return toast("上一批操作还在进行中，请稍候");
        }
        try { await onAction(action.dataset.act, action); }
        catch (error) { toast(error.message || "操作失败"); }
        return;
      }
      if (!target.closest("#confirm-dialog") && !target.closest("#export-sheet") && !target.closest("#doc-export-btn")) closeSheet();
      if (!target.closest("#popmenu")) closePopmenu();
    });
    document.addEventListener("change", (event) => {
      const target = event.target;
      const importedPick = target.dataset?.importPick;
      if (importedPick && S.accountImport) {
        if (target.checked) S.accountImport.selected.add(importedPick);
        else S.accountImport.selected.delete(importedPick);
        return renderAccountImport();
      }
      if (target.hasAttribute?.("data-import-new-only") && S.accountImport) {
        S.accountImport.onlyNew = target.checked;
        return renderAccountImport();
      }
      const groupPick = target.dataset?.jobGroup;
      if (groupPick) {
        // R10/裁定 D：勾父集 = 勾其全部子项；子项部分选中时父集半选。
        const group = jobCollections().find((item) => item.key === groupPick);
        if (group) {
          const allPicked = group.jobs.every((job) => S.selectedJobs.has(job.id));
          group.jobs.forEach((job) =>
            (allPicked ? S.selectedJobs.delete(job.id) : S.selectedJobs.add(job.id)));
        }
        return renderJobs();
      }
      const pick = target.dataset?.jobPick;
      if (pick) {
        if (target.checked) S.selectedJobs.add(pick); else S.selectedJobs.delete(pick);
        return renderJobs();
      }
      const contentCheck = target.dataset?.scopeContent;
      if (contentCheck) {
        if (target.checked) S.scopeContents.add(contentCheck); else S.scopeContents.delete(contentCheck);
        return updateScopeSummary();
      }
      const modePick = target.dataset?.modePick;
      if (modePick && S.libMode) {
        if (target.checked) S.pickedContents.add(modePick); else S.pickedContents.delete(modePick);
        return renderLibrary();
      }
      const contentPick = target.dataset?.contentPick;
      if (contentPick) {
        if (target.checked) S.selectedContents.add(contentPick); else S.selectedContents.delete(contentPick);
        return renderLibrary();
      }
      if (target.id === "intake-file") {
        $("#intake-local-count").textContent = `识别 ${target.files.length} 个`;
      }
      if (target.name === "export-where") {
        const row = $("#export-path-row");
        row.hidden = target.value === "download";
        if (target.value === "archive") $("#export-path").textContent = S.settings.archive_root || "未设置归档目录";
        if (target.value === "custom") $("#export-path").textContent = `${S.settings.archive_root || "归档根"}\\${S.exportSubdir || "—"}`;
      }
      if (target.name === "asr-engine") {
        $$(".set-branch", $("#set-pane")).forEach((branch) => {
          branch.hidden = branch.dataset.branch !== target.value;
        });
      }
    });
    document.addEventListener("input", (event) => {
      const modelPicker = event.target.closest?.("[data-model-picker]");
      if (modelPicker) renderModelCandidates(modelPicker);
      if (event.target.id === "intake-links") {
        invalidateIntakePreview();
        renderIntakeCount();
        clearTimeout(intakeProbeTimer);
        if (intakeRows().length) intakeProbeTimer = setTimeout(() => intakeQuery(), 350);
      }
      if (event.target.id === "lib-search") { S.libQuery = event.target.value; S.libCollection = null; renderLibrary(); }
      if (event.target.id === "doc-quick-search") { S.quickQuery = event.target.value; renderQuickList(); }
    });
    document.addEventListener("focusin", (event) => {
      const modelPicker = event.target.closest?.("[data-model-picker]");
      if (modelPicker) renderModelCandidates(modelPicker);
    });
    document.addEventListener("focusout", (event) => {
      const modelPicker = event.target.closest?.("[data-model-picker]");
      if (modelPicker) window.setTimeout(() => {
        if (!modelPicker.closest(".model-picker")?.contains(document.activeElement)) closeModelCandidates(modelPicker);
      }, 0);
    });
    document.addEventListener("pointerdown", (event) => {
      if (event.target.closest?.('[data-act="model-candidate"]')) event.preventDefault();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && S.libGroupMenu) {
        event.preventDefault();
        const trigger = $(`[data-act="lib-group-menu-toggle"][data-kind="${S.libGroupMenu}"]`);
        closeLibraryGroupMenu();
        trigger?.focus();
        return;
      }
      if (event.target.id === "confirm-dialog-input" && event.key === "Enter") {
        event.preventDefault();
        $("#confirm-dialog-submit").click();
        return;
      }
      const selectTrigger = event.target.closest?.("[data-product-select-trigger]");
      if (selectTrigger) {
        const host = selectTrigger.closest(".product-select");
        const menu = $(".product-select__options", host);
        const select = $("select", host);
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.preventDefault();
          const direction = event.key === "ArrowDown" ? 1 : -1;
          if (menu.hidden) {
            const count = $$('[data-product-select-option]', menu).length;
            const selected = select?.selectedIndex ?? 0;
            openProductSelect(selectTrigger, (selected + direction + count) % count);
          } else moveProductSelectOption(host, direction);
          return;
        }
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          if (menu.hidden) openProductSelect(selectTrigger, select?.selectedIndex ?? 0);
          else closeProductSelect(host);
          return;
        }
        if (event.key === "Escape" && !menu.hidden) {
          event.preventDefault();
          closeProductSelect(host);
          return;
        }
      }
      const selectOption = event.target.closest?.("[data-product-select-option]");
      if (selectOption) {
        const host = selectOption.closest(".product-select");
        const options = $$('[data-product-select-option]', host);
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.preventDefault();
          moveProductSelectOption(host, event.key === "ArrowDown" ? 1 : -1);
          return;
        }
        if (event.key === "Home" || event.key === "End") {
          event.preventDefault();
          options[event.key === "Home" ? 0 : options.length - 1]?.focus();
          return;
        }
        if (event.key === "Escape") {
          event.preventDefault();
          closeProductSelect(host);
          $("[data-product-select-trigger]", host)?.focus();
          return;
        }
      }
      const modelPicker = event.target.closest?.("[data-model-picker]");
      if (modelPicker && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
        event.preventDefault();
        moveModelCandidate(modelPicker, event.key === "ArrowDown" ? 1 : -1);
        return;
      }
      if (modelPicker && event.key === "Enter" && modelPicker.getAttribute("aria-expanded") === "true") {
        const selected = $('[aria-selected="true"]', $(`#${modelPicker.id.replace(/-input$/, "-options")}`));
        if (selected) {
          event.preventDefault();
          selectModelCandidate(modelPicker, selected.dataset.modelValue);
          return;
        }
      }
      if (modelPicker && event.key === "Escape" && modelPicker.getAttribute("aria-expanded") === "true") {
        event.preventDefault();
        closeModelCandidates(modelPicker);
        return;
      }
      if (event.key === "Escape") { closeAccountImport(); closeSheet(); closePopmenu(); closeRestyle(); closeConfirmation(); dismissTriage(); hideTip(); }
      if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && S.route === "ask") askSend();
    });
    window.addEventListener("popstate", () => {
      const id = new URL(window.location.href).searchParams.get("content_id");
      if (id) { go("content"); openContent(id); } else go("intake");
    });
  }

  /* ------------------------- 启动 ------------------------- */
  async function boot() {
    initTooltip();
    bindEvents();
    ["intake-style", "intake-strength", "restyle-style", "restyle-strength"]
      .forEach((id) => enhanceProductSelect(document.getElementById(id)));
    initAskState();
    initAskResizers();
    renderIntakeCount();
    $("#export-path-row").hidden = false;
    try {
      const [health, meta] = await Promise.all([api("/health", { absolute: true }), api("/api/v1/meta", { absolute: true })]);
      if (CONTRACT.startsWith("__") || health.api_contract_version === CONTRACT) {
        console.info("[boot] 本地服务已连接", meta.version);
      } else {
        toast("本地服务版本与前端不一致，请刷新页面");
      }
    } catch (error) {
      toast("本地服务未连接，请启动产品服务");
    }
    await loadBase();
    // 默认选中首个会话：与图三「选中会话蓝底 + 仅该条显示删除键」一致。
    // 详情取真实接口数据，回答时间由 renderAskStream 从消息字段渲染。
    if (!S.sessionId && S.sessions.length) {
      S.sessionId = S.sessions[0].id;
      try { S.sessionDetail = await api(`/ask/sessions/${S.sessionId}`); }
      catch (error) { S.sessionDetail = null; }
    }
    const params = new URL(window.location.href).searchParams;
    const contentId = params.get("content_id");
    if (contentId) { go("content"); await openContent(contentId); }
    else if (S.route === "intake") go("intake");
    renderLibrary(); renderJobs(); renderAsk(); renderAskStream(); renderSettingsPane();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
