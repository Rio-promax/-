const sessionSelect = document.querySelector("#session-select");
const querySelect = document.querySelector("#query-select");
const notice = document.querySelector("#notice");
const recordContent = document.querySelector("#record-content");
const tagReviewList = document.querySelector("#tag-review-list");
const graphQuery = document.querySelector("#graph-query");
const graphResults = document.querySelector("#graph-results");
const graphPage = document.querySelector("#graph-page");
const graphCoverage = document.querySelector("#graph-coverage");
const graphBack = document.querySelector("#graph-back");
const graphPrevious = document.querySelector("#graph-previous");
const graphNext = document.querySelector("#graph-next");
const chunkingSamples = document.querySelector("#chunking-samples");
const chunkingPage = document.querySelector("#chunking-page");
const chunkingPrevious = document.querySelector("#chunking-previous");
const chunkingNext = document.querySelector("#chunking-next");
const chunkingRun = document.querySelector("#chunking-run");
const chunkingResults = document.querySelector("#chunking-results");
const indexRebuild = document.querySelector("#index-rebuild");
let graphState = { query: "", contentId: "", facetId: "", offset: 0 };
const graphHistory = [];
let chunkingSampleState = { offset: 0, limit: 50, hasMore: false };
let indexRebuildTimer = null;

function element(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined && value !== null) node.textContent = String(value);
  return node;
}

function clear(node) {
  node.replaceChildren();
}

function display(value) {
  if (value === undefined || value === null || value === "") return "未记录";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function safeErrorText(value) {
  return String(value)
    .replace(/https?:\/\/\S+/gi, "[URL]")
    .replace(/\bBearer\s+[^\s,;]+/gi, "Bearer [已隐藏]")
    .replace(/((?:api[_-]?key|authorization)\s*[:=]\s*)[^\s,;]+/gi, "$1[已隐藏]");
}

function addRows(target, values) {
  clear(target);
  for (const [label, value] of values) {
    const row = element("div", "row");
    row.append(element("span", "row-label", label), element("span", "row-value", display(value)));
    target.append(row);
  }
}

function addDetails(target, title, body) {
  const details = element("details");
  const summary = element("summary", "", title);
  const content = element("div", "detail-body");
  body(content);
  details.append(summary, content);
  target.append(details);
}

function addItem(target, title, meta, text) {
  const item = element("div", "item");
  if (title) item.append(element("div", "item-title", title));
  if (meta) item.append(element("div", "item-meta", meta));
  if (text !== undefined && text !== null && text !== "") item.append(element("div", "item-text", text));
  target.append(item);
}

function addPre(target, value) {
  target.append(element("pre", "pre", display(value)));
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { Accept: "application/json", ...(options.headers || {}) },
    cache: "no-store",
    ...options,
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function renderOverview(data) {
  addRows(document.querySelector("#answer-model"), [
    ["Provider", data.answer_model?.provider],
    ["Model", data.answer_model?.model],
    ["协议", data.answer_model?.api_mode],
    ["已配置", data.answer_model?.configured],
    ["复用总结配置", data.answer_model?.reuse_summary_config],
  ]);

  addRows(document.querySelector("#retrieval-models"), [
    ["Embedding", data.retrieval?.embedding_model],
    ["Embedding 状态", data.retrieval?.configured],
    ["Rerank", data.retrieval?.rerank_model],
    ["Rerank 默认启用", data.retrieval?.rerank_default_enabled],
  ]);

  addRows(document.querySelector("#chunking"), [
    ["模型", data.chunking?.model ?? "未配置"],
    ["实现", data.chunking?.implementation],
    ["块大小", data.chunking?.chunk_limit],
    ["建议窗口", data.chunking?.proposal_window_utf8_bytes],
    ["模型调用", data.chunking?.limits?.max_calls_per_content],
    ["模型总时限秒", data.chunking?.limits?.max_total_seconds_per_content],
    ["单次输入字节", data.chunking?.limits?.max_input_bytes_per_call],
    ["单篇输入字节", data.chunking?.limits?.max_total_input_bytes_per_content],
    ["单篇输出Token上限", data.chunking?.limits?.max_output_tokens_per_content],
    ["Embedding上下文Token", data.chunking?.embedding_context_limit_tokens],
    ["Embedding token bound", data.chunking?.embedding_token_bound_method],
    ["状态", data.chunking?.statuses],
    ["累计调用", data.chunking?.calls],
    ["累计输入字节", data.chunking?.input_bytes],
    ["累计输出Token", data.chunking?.output_tokens],
    ["回退原因", data.chunking?.fallback_reason],
  ]);

  const text = data.index?.text;
  const vector = data.index?.vector;
  const rebuild = data.index?.rebuild;
  const rebuildStatus = ({
    not_started: "未开始", not_initialized: "未初始化", running: "重建中",
    complete: "已完成", failed: "有失败项",
  })[rebuild?.status] ?? rebuild?.status;
  addRows(document.querySelector("#index-coverage"), [
    ["索引状态", data.index?.status === "ready" ? "可用" : data.index?.status === "not_initialized" ? "未初始化" : data.index?.status],
    ["索引 Profile", data.index?.profile_id],
    ["文本索引", text ? `${text.indexed}/${text.total_completed} · partial ${text.partial} · failed ${text.failed} · pending ${text.pending}` : data.index?.status === "not_initialized" ? "未初始化" : undefined],
    ["向量状态", ({ available: "可用", state_records_available: "状态记录可用", not_configured: "未配置", not_initialized: "未初始化", unavailable: "不可用" })[data.index?.vector_status] ?? data.index?.vector_status],
    ["向量状态记录覆盖", vector ? `${vector.status_record_covered_chunks}/${vector.total_chunks} · indexed ${vector.indexed} · partial ${vector.partial}` : undefined],
    ["向量点核验", vector ? (vector.vector_points_verified ? "已核验" : "未核验") : undefined],
    ["重建状态", rebuildStatus],
    ["文本重建进度", rebuild ? `${rebuild.processed}/${rebuild.total} · 待建 ${rebuild.pending} · 失败 ${rebuild.failed}` : undefined],
    ["向量重建进度", rebuild?.vector_processed !== null && rebuild?.vector_processed !== undefined
      ? `${rebuild.vector_processed}/${rebuild.total} · 待建 ${rebuild.vector_pending} · 失败 ${rebuild.vector_failed}`
      : "未配置"],
  ]);
  if (indexRebuild) {
    const failed = (rebuild?.failed || 0) + (rebuild?.vector_failed || 0);
    indexRebuild.textContent = rebuild?.status === "running"
      ? "重建中"
      : failed > 0 ? "重试失败项" : "重建索引";
    indexRebuild.disabled = rebuild?.status === "running" || !rebuild?.retryable;
  }
}

function selectedChunkingContentIds() {
  return [...chunkingSamples.querySelectorAll("input[data-content-id]:checked")]
    .map((input) => input.dataset.contentId);
}

function updateChunkingSelection() {
  const selected = selectedChunkingContentIds();
  chunkingRun.disabled = selected.length === 0;
  chunkingRun.textContent = `重建选中 · ${selected.length}/5`;
}

function renderChunkingSamples(data) {
  clear(chunkingSamples);
  const page = data.page || { offset: 0, limit: 50, count: 0, has_more: false };
  chunkingSampleState = {
    offset: page.offset,
    limit: page.limit,
    hasMore: page.has_more,
  };
  chunkingPage.textContent = `${page.count} 条`;
  chunkingPrevious.disabled = page.offset <= 0;
  chunkingNext.disabled = !page.has_more;
  for (const item of data.items || []) {
    const row = element("div", "row chunk-sample");
    const label = element("label", "chunk-sample-select");
    const checkbox = element("input", "", "");
    checkbox.type = "checkbox";
    checkbox.dataset.contentId = item.content_id;
    label.append(checkbox, element("span", "", item.title || item.content_id));
    const chunking = item.chunking || {};
    const metadata = [
      item.index_status || "未索引",
      `${item.chunk_count || 0} 块`,
      chunking.status || "未切块",
      `${chunking.calls || 0} 次 · ${chunking.input_bytes || 0} bytes · ${chunking.output_tokens ?? "未知"} tokens`,
    ].join(" · ");
    row.append(label, element("span", "row-value", metadata));
    if (chunking.trace?.length) {
      row.append(element("span", "row-value", `边界 · ${chunking.trace.map((item) =>
        `${item.source_kind} [${(item.boundary_ends || []).join(",")}] ${item.accepted ? "接受" : "回退"}`
      ).join(" · ")}`));
    }
    row.dataset.contentId = item.content_id;
    chunkingSamples.append(row);
  }
  if (!data.items?.length) chunkingSamples.append(element("div", "empty", "无样本"));
  updateChunkingSelection();
}

function renderChunkingResults(results) {
  clear(chunkingResults);
  for (const item of results || []) {
    const chunking = item.chunking || {};
    const row = element("div", "row");
    row.append(
      element("span", "row-label", item.content_id),
      element("span", "row-value", [
        item.status,
        `${item.chunk_count} 块`,
        chunking.status,
        `${chunking.calls} 次 · ${chunking.input_bytes} bytes · ${chunking.output_tokens ?? "未知"} tokens`,
        chunking.error_code,
      ].filter(Boolean).join(" · ")),
    );
    chunkingResults.append(row);
    if (chunking.trace?.length) {
      chunkingResults.append(element("div", "row-value", `边界 · ${chunking.trace.map((entry) =>
        `${entry.source_kind} [${(entry.boundary_ends || []).join(",")}] ${entry.accepted ? "接受" : "回退"}`
      ).join(" · ")}`));
    }
  }
}

async function loadChunkingSamples(offset = chunkingSampleState.offset) {
  const params = new URLSearchParams({
    limit: String(chunkingSampleState.limit),
    offset: String(offset),
  });
  renderChunkingSamples(await request(`/api/v1/dev/rag/chunking/samples?${params.toString()}`));
}

function renderTagReviews(items) {
  clear(tagReviewList);
  if (!items.length) {
    tagReviewList.append(element("div", "empty", "无待审核候选"));
    return;
  }
  for (const candidate of items) {
    const card = element("article", "tag-review");
    card.dataset.tagId = candidate.id;
    card.append(element("h3", "", candidate.name));
    card.append(element("div", "item-text", candidate.definition));
    for (const context of candidate.contexts || []) {
      const item = element("div", "item");
      item.append(element("div", "item-title", context.content_id));
      for (const evidence of context.evidence || []) {
        item.append(element("div", "item-meta", `${evidence.source_kind} · ${evidence.source_ref}`));
        item.append(element("div", "item-text", evidence.text));
      }
      card.append(item);
    }
    const controls = element("div", "review-controls");
    const noteLabel = element("label", "review-note");
    noteLabel.append(element("span", "", "审核备注"));
    const note = element("input", "", "");
    note.type = "text";
    note.maxLength = 300;
    note.dataset.reviewNote = "true";
    noteLabel.append(note);
    controls.append(noteLabel);
    for (const [decision, label] of [["approved", "通过"], ["rejected", "拒绝"]]) {
      const button = element("button", "", label);
      button.type = "button";
      button.dataset.decision = decision;
      controls.append(button);
    }
    card.append(controls);
    tagReviewList.append(card);
  }
}

function renderGraph(data) {
  clear(graphResults);
  const page = data.page || { offset: 0, limit: 20, count: 0, has_more: false, truncated: false };
  const total = page.total_count ?? page.count;
  const range = data.selected_content_id
    ? `${page.count > 1 ? `${page.offset + 1}-${page.offset + page.count - 1}` : "0"} / ${Math.max(0, total - 1)} 相关 · 起点`
    : page.count
      ? `${page.offset + 1}-${page.offset + page.count} / ${total}`
      : `0 / ${total}`;
  graphPage.textContent = `${range}${page.truncated ? " · 还有下一页" : ""}`;
  graphBack.disabled = graphHistory.length === 0;
  graphPrevious.disabled = page.offset <= 0;
  graphNext.disabled = !page.has_more;
  const relationNames = {
    favorite: "收藏", favorite_folder: "收藏夹", user_tag: "用户标签", platform: "平台",
    author: "作者", media_type: "媒体类型", topic: "主题", detail_tag: "细标签",
  };
  graphCoverage.textContent = `关系覆盖：${Object.entries(data.relation_coverage || {})
    .map(([kind, counts]) => `${relationNames[kind] || kind} ${counts.content_count}/${counts.content_total}`)
    .join(" · ")}`;
  const nodes = new Map(data.nodes.map((item) => [item.id, item]));
  const contents = data.nodes.filter((item) => item.kind === "content");
  if (!contents.length) {
    graphResults.append(element("div", "empty", "无关系"));
    return;
  }
  const facets = new Map(contents.map((item) => [`content:${item.content_id}`, {}]));
  for (const edge of data.edges) {
    const values = facets.get(edge.source) || {};
    const node = nodes.get(edge.target);
    if (node) values[edge.relation] = [...(values[edge.relation] || []), node];
    facets.set(edge.source, values);
  }
  const table = element("table", "graph-table");
  const headings = ["内容", "平台", "作者", "媒体类型", "收藏", "收藏夹", "用户标签", "主题", "细标签", "关系"];
  const head = element("tr");
  for (const heading of headings) head.append(element("th", "", heading));
  const thead = element("thead");
  thead.append(head);
  table.append(thead);
  const body = element("tbody");
  for (const content of contents) {
    const relation = facets.get(`content:${content.content_id}`) || {};
    const row = element("tr");
    const titleCell = element("td", "");
    const detailLink = element("a", "graph-detail-link", content.label || content.content_id);
    detailLink.href = `/?content_id=${encodeURIComponent(content.content_id)}`;
    detailLink.target = "_blank";
    detailLink.rel = "noreferrer";
    titleCell.append(detailLink, element("div", "graph-content-id", content.content_id));
    row.append(titleCell);
    for (const kind of ["platform", "author", "media_type", "favorite", "favorite_folder",
      "user_tag", "topic", "detail_tag"]) {
      const cell = element("td", "graph-relation-cell");
      const values = kind === "platform" ? relation.platform
        : kind === "author" ? relation.author
          : kind === "media_type" ? relation.media_type
            : kind === "favorite" ? relation.favorite
              : relation[kind];
      for (const node of values || []) {
        const button = element("button", "graph-relation", node.label);
        button.type = "button";
        button.dataset.facetId = node.id;
        button.title = `查找关系：${node.label}`;
        cell.append(button);
      }
      row.append(cell);
    }
    const action = element("td");
    const button = element("button", "", "展开关系");
    button.type = "button";
    button.dataset.expandContentId = content.content_id;
    action.append(button);
    row.append(action);
    body.append(row);
  }
  table.append(body);
  graphResults.append(table);
}

async function loadGraph(nextState = graphState, { push = false } = {}) {
  if (push) graphHistory.push({ ...graphState });
  graphState = { ...nextState };
  const params = new URLSearchParams({ limit: "20", offset: String(graphState.offset || 0) });
  if (graphState.query) params.set("query", graphState.query);
  if (graphState.contentId) params.set("content_id", graphState.contentId);
  if (graphState.facetId) params.set("facet_id", graphState.facetId);
  renderGraph(await request(`/api/v1/dev/rag/graph?${params.toString()}`));
}

function optionLabel(item) {
  const date = item.created_at ? new Date(item.created_at).toLocaleString() : "";
  return [item.title || item.id, date].filter(Boolean).join(" · ");
}

function setOptions(select, items, labelFor, placeholder) {
  clear(select);
  const first = element("option", "", placeholder);
  first.value = "";
  select.append(first);
  for (const item of items) {
    const option = element("option", "", labelFor(item));
    option.value = item.id;
    select.append(option);
  }
}

function queryLabel(query) {
  const status = query.status || "未记录";
  const question = query.question || query.id;
  return `${status} · ${question.slice(0, 100)}`;
}

async function loadSession(sessionId, preferredQueryId = "") {
  if (!sessionId) {
    setOptions(querySelect, [], queryLabel, "未选择");
    renderNoQuery("未选择");
    return;
  }
  const session = await request(`/api/v1/ask/sessions/${encodeURIComponent(sessionId)}`);
  const queries = session.messages || [];
  setOptions(querySelect, queries, queryLabel, queries.length ? "选择问答" : "无问答记录");
  if (preferredQueryId && queries.some((query) => query.id === preferredQueryId)) {
    querySelect.value = preferredQueryId;
  } else if (queries.length) {
    querySelect.value = queries[queries.length - 1].id;
  }
  if (querySelect.value) await loadQuery(querySelect.value);
  else renderNoQuery("无问答记录");
}

function renderNoQuery(label) {
  clear(recordContent);
  recordContent.className = "empty";
  recordContent.textContent = label;
}

function renderCalls(target, calls) {
  if (!Array.isArray(calls) || !calls.length) {
    addItem(target, "", "未记录");
    return;
  }
  for (const call of calls) {
    const meta = [
      `状态 ${display(call.status)}`,
      `耗时 ${call.elapsed_ms === undefined ? "未记录" : `${call.elapsed_ms} ms`}`,
      `输入 ${call.input_bytes === undefined ? "未记录" : `${call.input_bytes}/${display(call.input_limit_bytes)} bytes`}`,
      `输出上限 ${display(call.max_output_tokens)} tokens`,
      `HTTP ${display(call.http_status)}`,
    ].join(" · ");
    addItem(target, `${display(call.stage)}${call.call ? ` · ${call.call}` : ""}`, meta,
      call.status === "failed"
        ? `错误 ${display(call.error_type)} · cause ${display(call.cause_type)} · reason ${display(call.cause_reason_type)}`
        : `Token ${display(call.usage)}`);
  }
}

function renderCandidates(target, candidates, emptyLabel = "未记录") {
  if (!Array.isArray(candidates)) {
    addItem(target, "", emptyLabel);
    return;
  }
  if (!candidates.length) {
    addItem(target, "", "无候选");
    return;
  }
  for (const candidate of candidates) {
    const time = [candidate.start_seconds, candidate.end_seconds]
      .filter((value) => value !== undefined && value !== null)
      .map((value) => `${value}s`).join("–");
    const meta = [
      `#${display(candidate.rank)}`,
      `ID ${display(candidate.hit_id || candidate.id)}`,
      `内容 ${display(candidate.content_id)}`,
      `${display(candidate.source_kind)} ${display(candidate.source_ref)}${time ? ` · ${time}` : ""} · ${display(candidate.retrieval_role)}`,
      `Score ${display(candidate.score)} · ${display(candidate.score_type)}`,
    ].join(" · ");
    addItem(target, candidate.title || candidate.hit_id || candidate.id, meta);
  }
}

function renderRetrievalBudget(target, budget) {
  if (!budget) {
    addItem(target, "状态", "未记录");
    return;
  }
  const limits = budget.limits || {};
  addItem(target, "冻结范围内容", budget.scope_content_count);
  addItem(target, "每层块上限", limits.per_layer_block_limit);
  addItem(target, "每内容块上限", limits.per_content_block_limit);
  addItem(target, "融合块上限", limits.merged_block_limit);
  addItem(target, "最终块上限", limits.final_block_limit);
  addItem(target, "最终每内容块上限", limits.final_per_content_block_limit);
  addItem(target, "补查块上限", limits.supplement_block_limit);

  const initial = budget.initial;
  if (initial) {
    addItem(target, "初召回", `${display(initial.candidate_block_count)} 块 · ${display(initial.candidate_content_count)} 项 · 截断 ${display(initial.truncated)}`);
    for (const layer of initial.layers || []) {
      addItem(target, layer.tool,
        `${display(layer.candidate_block_count)}/${display(layer.block_limit)} 块 · ${display(layer.candidate_content_count)}/${display(layer.scope_content_count)} 项 · 块截断 ${display(layer.truncated_by_block_limit)} · 内容截断 ${display(layer.truncated_by_per_content_limit)}`);
    }
  }
  const evidence = budget.evidence;
  if (evidence) {
    addItem(target, "证据候选", `${display(evidence.candidate_block_count)} 块 · ${display(evidence.candidate_content_count)} 项`);
    addItem(target, "命中与邻接", `${display(evidence.matched_block_count)} 命中块 · ${display(evidence.adjacent_context_block_count)} 邻接块`);
  }
  const final = budget.final;
  if (final) {
    addItem(target, "最终输入", `${display(final.selected_block_count)} 块 · ${display(final.selected_content_count)} 项 · 任务截断 ${display(final.truncated_by_task_quota)} · 字节截断 ${display(final.truncated_by_input_budget)}`);
  }
  const targets = budget.explicit_compare_targets;
  if (targets) {
    if (targets.status === "paused_for_explicit_batching") {
      addItem(target, "指定比较", `暂停 · ${display(targets.requested_content_count)} 项 · 每批 ${display(targets.required_batch_size)} 项`);
    } else {
      addItem(target, "指定比较", `${display(targets.final_prompt_content_ids?.length ?? targets.final_evidence_content_ids?.length ?? targets.initial_hit_content_ids?.length ?? 0)}/${display(targets.requested_content_ids?.length ?? 0)} 项进入证据`);
    }
  }
}

function renderRecord(query) {
  const trace = query.trace || {};
  const result = query.result || {};
  clear(recordContent);
  recordContent.className = "";

  const header = element("div", "record-head");
  header.append(element("div", "question", query.question || "未记录"));
  header.append(element("div", `status${query.status === "failed" ? " failed" : ""}`, display(query.status)));
  recordContent.append(header);
  if (result.answer) recordContent.append(element("div", result.status === "unavailable" ? "answer error" : "answer",
    result.status === "unavailable" ? safeErrorText(result.answer) : result.answer));
  else recordContent.append(element("div", "answer muted", "未记录"));

  const grid = element("div", "details-grid");
  recordContent.append(grid);

  addDetails(grid, "路由", (body) => {
    addItem(body, "阶段", trace.route ? "已记录" : (trace.calls?.some((call) => call.stage === "P-ROUTE") ? "已调用" : "未记录"));
    addPre(body, trace.route);
  });

  addDetails(grid, "模型调用", (body) => renderCalls(body, trace.calls));

  addDetails(grid, "Embedding", (body) => {
    if (!Array.isArray(trace.embedding_calls)) {
      addItem(body, "", "未记录");
      return;
    }
    if (!trace.embedding_calls.length) {
      addItem(body, "", "未执行");
      return;
    }
    for (const call of trace.embedding_calls) {
      const meta = `状态 ${display(call.status)} · 耗时 ${call.elapsed_ms === undefined ? "未记录" : `${call.elapsed_ms} ms`} · 输入 ${display(call.input_bytes)} bytes · 维度 ${display(call.dimension)}`;
      addItem(body, "Embedding", meta, call.status === "failed"
        ? `错误 ${display(call.error_type)} · cause ${display(call.cause_type)} · reason ${display(call.cause_reason_type)}`
        : "");
    }
  });

  addDetails(grid, "检索候选", (body) => renderCandidates(body, trace.retrieval_candidates));

  addDetails(grid, "配额与覆盖", (body) => renderRetrievalBudget(body, trace.retrieval_budget));

  addDetails(grid, "Rerank 排名", (body) => {
    const rerank = trace.rerank;
    if (!rerank) {
      addItem(body, "状态", "未记录");
      addItem(body, "Rerank 前", "未记录");
      addItem(body, "Rerank 后", "未记录");
      return;
    }
    addItem(body, "状态", display(rerank.status));
    addItem(body, "Rerank 前", "检索候选");
    renderCandidates(body, rerank.before ?? trace.retrieval_candidates,
      trace.retrieval_candidates ? "无候选" : (rerank.status === "not_executed" ? "未执行" : "未记录"));
    addItem(body, "Rerank 后", rerank.after ? "已记录" : (rerank.status === "not_executed" ? "未执行" : "未记录"));
    if (rerank.after) renderCandidates(body, rerank.after);
  });

  addDetails(grid, "证据检查", (body) => {
    const validation = trace.evidence_validation;
    if (!validation) {
      addItem(body, "状态", "未记录");
      return;
    }
    addItem(body, "状态", `${display(validation.status)} · ${display(validation.answer_status)}`);
    addItem(body, "答案段", validation.supported_segments);
    addItem(body, "引用", validation.citations);
    addItem(body, "未覆盖", validation.uncovered);
    for (const slot of validation.slots || []) {
      addItem(body, slot.slot_id, `分数 ${display(slot.score)} · 证据 ${display(slot.evidence_count)} · 引文 ${display(slot.quote_count)} · 缺失 ${display(slot.missing)}`);
    }
  });

  addDetails(grid, "补查", (body) => {
    if (trace.supplement_rounds === undefined) addItem(body, "轮数", "未记录");
    else addItem(body, "轮数", trace.supplement_rounds);
    if (!Array.isArray(trace.supplement_calls)) {
      addItem(body, "调用", "未记录");
      return;
    }
    if (!trace.supplement_calls.length) {
      addItem(body, "调用", trace.supplement_rounds ? "未记录" : "未执行");
      return;
    }
    for (const call of trace.supplement_calls) {
      addItem(body, `${display(call.tool)} · ${display(call.slot_id)}`,
        `状态 ${display(call.status)} · 耗时 ${call.elapsed_ms === undefined ? "未记录" : `${call.elapsed_ms} ms`} · 命中 ${display(call.hit_count)} · ${display(call.score_type)}`,
        call.status === "failed"
          ? `错误 ${display(call.error_type)} · cause ${display(call.cause_type)}`
          : call.retrieval_stats
            ? `${display(call.retrieval_stats.candidate_block_count)} 块 · ${display(call.retrieval_stats.candidate_content_count)} 项 · 块截断 ${display(call.retrieval_stats.truncated_by_block_limit)}`
            : "");
    }
  });

  addDetails(grid, "耗时与 Token", (body) => {
    addItem(body, "总耗时", trace.elapsed_ms === undefined
      ? (trace.elapsed_seconds === undefined ? "未记录" : `${trace.elapsed_seconds} s`)
      : `${trace.elapsed_ms} ms`);
    const calls = Array.isArray(trace.calls) ? trace.calls : [];
    if (!calls.length) addItem(body, "Token", "未记录");
    for (const call of calls) addItem(body, `${display(call.stage)} Token`, call.usage);
  });

  addDetails(grid, "错误", (body) => {
    const hasError = trace.error_type || trace.cause_type || trace.http_status;
    if (!hasError) {
      addItem(body, "状态", query.status === "failed" ? "未记录" : "无错误记录");
      return;
    }
    addItem(body, "异常", trace.error_type);
    addItem(body, "Cause", trace.cause_type);
    addItem(body, "Cause reason", trace.cause_reason_type);
    addItem(body, "HTTP", trace.http_status);
  });

  addDetails(grid, "引用", (body) => {
    const citations = result.citations;
    if (!Array.isArray(citations)) {
      addItem(body, "", "未记录");
      return;
    }
    if (!citations.length) {
      addItem(body, "", "无引用");
      return;
    }
    for (const citation of citations) {
      const location = [citation.start_seconds, citation.end_seconds]
        .filter((value) => value !== undefined && value !== null)
        .map((value) => `${value}s`).join("–");
      addItem(body, citation.title || citation.content_id,
        `${display(citation.source_kind)} · ${display(citation.source_ref)}${location ? ` · ${location}` : ""} · ${display(citation.id)}`,
        citation.text);
    }
  });
}

async function loadQuery(queryId) {
  if (!queryId) {
    renderNoQuery("未选择");
    return;
  }
  const query = await request(`/api/v1/ask/queries/${encodeURIComponent(queryId)}`);
  renderRecord(query);
}

async function refresh(preferredSessionId = sessionSelect.value, preferredQueryId = querySelect.value) {
  if (indexRebuildTimer) {
    window.clearTimeout(indexRebuildTimer);
    indexRebuildTimer = null;
  }
  notice.textContent = "";
  try {
    const [overview, sessions, tagReviews, samples] = await Promise.all([
      request("/api/v1/dev/rag/overview"),
      request("/api/v1/ask/sessions"),
      request("/api/v1/dev/rag/tag-reviews"),
      request(`/api/v1/dev/rag/chunking/samples?limit=${chunkingSampleState.limit}&offset=${chunkingSampleState.offset}`),
    ]);
    renderOverview(overview);
    if (overview.index?.rebuild?.status === "running") {
      indexRebuildTimer = window.setTimeout(() => {
        pollIndexRebuild().catch((error) => { notice.textContent = `索引状态读取失败 · ${error.message}`; });
      }, 1500);
    }
    renderTagReviews(tagReviews);
    renderChunkingSamples(samples);
    await loadGraph();
    setOptions(sessionSelect, sessions, optionLabel, sessions.length ? "选择会话" : "无会话记录");
    if (!sessions.length) {
      setOptions(querySelect, [], queryLabel, "无问答记录");
      renderNoQuery("无会话记录");
      return;
    }
    sessionSelect.value = sessions.some((item) => item.id === preferredSessionId)
      ? preferredSessionId : sessions[0].id;
    await loadSession(sessionSelect.value, preferredQueryId);
  } catch (error) {
    notice.textContent = `加载失败 · ${error.message}`;
  }
}

async function pollIndexRebuild() {
  const overview = await request("/api/v1/dev/rag/overview");
  renderOverview(overview);
  if (overview.index?.rebuild?.status === "running") {
    indexRebuildTimer = window.setTimeout(() => {
      pollIndexRebuild().catch((error) => { notice.textContent = `索引状态读取失败 · ${error.message}`; });
    }, 1500);
  }
}

sessionSelect.addEventListener("change", () => {
  loadSession(sessionSelect.value).catch((error) => { notice.textContent = `加载失败 · ${error.message}`; });
});

querySelect.addEventListener("change", () => {
  loadQuery(querySelect.value).catch((error) => { notice.textContent = `加载失败 · ${error.message}`; });
});

document.querySelector("#refresh").addEventListener("click", () => {
  refresh().catch((error) => { notice.textContent = `加载失败 · ${error.message}`; });
});

indexRebuild?.addEventListener("click", async () => {
  indexRebuild.disabled = true;
  notice.textContent = "";
  try {
    await request("/api/v1/dev/rag/index/rebuild", { method: "POST" });
    await pollIndexRebuild();
  } catch (error) {
    notice.textContent = `索引重建失败 · ${error.message}`;
    indexRebuild.disabled = false;
  }
});

chunkingSamples.addEventListener("change", (event) => {
  const checkbox = event.target.closest("input[data-content-id]");
  if (!checkbox) return;
  const selected = selectedChunkingContentIds();
  if (selected.length > 5) checkbox.checked = false;
  updateChunkingSelection();
});

chunkingPrevious.addEventListener("click", () => {
  loadChunkingSamples(Math.max(0, chunkingSampleState.offset - chunkingSampleState.limit))
    .catch((error) => { notice.textContent = `样本读取失败 · ${error.message}`; });
});

chunkingNext.addEventListener("click", () => {
  loadChunkingSamples(chunkingSampleState.offset + chunkingSampleState.limit)
    .catch((error) => { notice.textContent = `样本读取失败 · ${error.message}`; });
});

chunkingRun.addEventListener("click", async () => {
  const contentIds = selectedChunkingContentIds();
  if (!contentIds.length || contentIds.length > 5) return;
  chunkingRun.disabled = true;
  notice.textContent = "";
  try {
    const result = await request("/api/v1/dev/rag/chunking/backfill", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content_ids: contentIds }),
    });
    renderChunkingResults(result.results);
    await loadChunkingSamples();
  } catch (error) {
    notice.textContent = `样本重建失败 · ${error.message}`;
  } finally {
    updateChunkingSelection();
  }
});

tagReviewList.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-decision]");
  const card = button?.closest("[data-tag-id]");
  if (!button || !card) return;
  button.disabled = true;
  try {
    await request(`/api/v1/dev/rag/tag-reviews/${encodeURIComponent(card.dataset.tagId)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        decision: button.dataset.decision,
        note: card.querySelector("[data-review-note]").value,
      }),
    });
    await refresh();
  } catch (error) {
    notice.textContent = `审核失败 · ${error.message}`;
    button.disabled = false;
  }
});

document.querySelector("#graph-search").addEventListener("click", () => {
  graphHistory.length = 0;
  loadGraph({ query: graphQuery.value.trim(), contentId: "", facetId: "", offset: 0 })
    .catch((error) => { notice.textContent = `关系检索失败 · ${error.message}`; });
});

graphResults.addEventListener("click", (event) => {
  const facetButton = event.target.closest("button[data-facet-id]");
  const contentButton = event.target.closest("button[data-expand-content-id]");
  if (facetButton) {
    loadGraph({ query: "", contentId: "", facetId: facetButton.dataset.facetId, offset: 0 }, { push: true })
      .catch((error) => { notice.textContent = `关系读取失败 · ${error.message}`; });
  } else if (contentButton) {
    loadGraph({ query: "", contentId: contentButton.dataset.expandContentId, facetId: "", offset: 0 }, { push: true })
      .catch((error) => {
      notice.textContent = `关系读取失败 · ${error.message}`;
    });
  }
});

graphBack.addEventListener("click", () => {
  const previous = graphHistory.pop();
  if (previous) loadGraph(previous).catch((error) => { notice.textContent = `关系返回失败 · ${error.message}`; });
});

graphPrevious.addEventListener("click", () => {
  loadGraph({ ...graphState, offset: Math.max(0, graphState.offset - 20) })
    .catch((error) => { notice.textContent = `关系翻页失败 · ${error.message}`; });
});

graphNext.addEventListener("click", () => {
  loadGraph({ ...graphState, offset: graphState.offset + 20 })
    .catch((error) => { notice.textContent = `关系翻页失败 · ${error.message}`; });
});

refresh().catch((error) => { notice.textContent = `加载失败 · ${error.message}`; });
