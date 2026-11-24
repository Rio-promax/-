"""R6 防回归辅助契约（不是验收依据）。

唯一权威验收是「设计定稿 ↔ 分支运行页」并排拼图逐项比对（R7 由主 Agent 执行）；
本文件只防止已经按图对齐的元素在后续改动里被意外删掉，**不得替代并排拼图比对**。

本轮口径为 2026-11-12 六张 v3 定稿图：
  图一 知识库 / 图二 任务 / 图三 问答收起 / 图四 问答展开 /
  图五 内容接入 / 图六 内容详情；C1~C10 为方案「冲突裁定表」编号。
每条断言都标注来源图号或 C 编号与具体元素。断言只指向跨文件结构映射、
真实资源字节、CSS 数值常量与 HTML→JS 的接线关系；不把「自己写进源码的
描述字符串」冒充一致性证据，也不写 assert True 之类的自证式空断言。
"""
from pathlib import Path
import re

UI = Path(__file__).resolve().parents[1] / "app" / "ui"
# 目录层级核对：UI 在 core/app/ui；UI.parent 才是 core/app，后端在 core/app/api/main.py。
# 误取上一层（parents[1] = core）再拼 api/main.py 会指向不存在的路径，收集期即失败。
MAIN_PY_PATH = UI.parent / "api" / "main.py"

HTML = (UI / "index.html").read_text(encoding="utf-8")
CSS = (UI / "style.css").read_text(encoding="utf-8")
JS = (UI / "app.js").read_text(encoding="utf-8")
MAIN_PY = MAIN_PY_PATH.read_text(encoding="utf-8")
ICONS = UI / "platform-icons"

HTML_ACTS = set(re.findall(r'data-act="([^"]+)"', HTML))
JS_CASES = set(re.findall(r'case\s+"([^"]+)"\s*:', JS))

PLATFORM_FILES = {
    "bilibili.ico", "zhihu.ico", "xiaohongshu.ico",
    "wechat.png", "douyin.ico", "youtube.ico",
}


# ---------------- 图一：知识库（5 列 / 无框卡片 / 封面内置标志 / 两行标题） ----------------

def test_fig1_five_columns_single_css_constant():
    """图一：5 列 × 3 行网格，列数由单一 CSS 常量 --lib-cols 控制。"""
    assert "--lib-cols: 5;" in CSS, "图一：--lib-cols 应为 5"
    assert "repeat(var(--lib-cols), minmax(0, 1fr))" in CSS, "图一：列数须由单一变量控制"
    assert 'id="lib-grid"' in HTML, "图一：卡片网格容器存在"


def test_fig1_cover_template_and_full_title_attr():
    """图一/C6/C7/1-12：封面 .cover 内置封面图+平台标志，时长仅真实存在才输出。"""
    assert 'class="cover"' in JS, "图一/C6：知识库与任务共用封面容器"
    assert "cover__img" in JS and "platform-badge" in JS and "duration-badge" in JS, \
        "图一/C6：封面三元素齐全"
    assert "withDuration && dur > 0" in JS, \
        "图一/1-12：仅当有真实时长才输出 duration-badge（空/0 不显示 00:00）"
    assert 'referrerpolicy="no-referrer"' in JS, "图一：封面代理需 no-referrer"
    assert 'class="tile__title" title=' in JS, "图一/C7：标题须带 title 存完整原始标题"
    assert "-webkit-line-clamp: 2" in CSS, "图一/C7：标题最多两行截断"
    assert "coverHtml({ id: job.content_id" in JS, "图一/C6：任务页复用同一封面模板"


def test_fig1_platform_six_original_files_and_mapping():
    """图一/C3：六个平台原图标真实落盘，且 JS 映射表与磁盘文件名集合一致。"""
    on_disk = {p.name for p in ICONS.glob("*") if p.is_file()}
    assert PLATFORM_FILES <= on_disk, "图一/C3：六个原图标须真实存在（非字符串自证）"
    for name in PLATFORM_FILES:
        assert (ICONS / name).stat().st_size > 0, f"图一/C3：{name} 字节数应 > 0"
    mapped = set(re.findall(r'"([a-z]+\.(?:ico|png))"', JS))
    assert mapped == PLATFORM_FILES, "图一/C3：JS 映射表与磁盘六个原文件一一对应"


def test_fig1_thumbnail_proxy_path_and_no_referrer():
    """图一/未接线问题9：封面走 /api/v1/contents/{id}/thumbnail 代理且 no-referrer。"""
    assert "/api/v1/contents/${" in JS and "/thumbnail" in JS, "图一：封面代理路径"
    assert 'referrerpolicy="no-referrer"' in JS, "图一：封面代理需 no-referrer"
    assert MAIN_PY_PATH.exists(), "R6：UI.parent/api/main.py 路径须真实存在"
    assert "def content_thumbnail" in MAIN_PY, "图一：后端封面代理存在"
    assert "thumbnail_host_not_allowed" in MAIN_PY, "图一：代理带 host 白名单"


def test_fig1_no_thumb_uses_neutral_placeholder():
    """图一/1-10、图二/2-05：无 thumbnail_url 的内容用程序化占位封面，不写死其它条目封面。"""
    assert "placeholderThumb(" in JS, "图一：无封面内容生成程序化占位封面"
    assert "thumbnail_url" in JS, "图一：按真实 thumbnail_url 字段判断是否有封面"
    assert "data:image/svg+xml" in JS, "图一：占位封面为内联 SVG data URI（非产品数据）"
    assert "data-fallback=" in JS, "图一：真实封面加载失败时回退到占位图"


# ---------------- 图二：任务（7 状态圈 / 96px / 编辑态复选框） ----------------

def test_fig2_seven_state_labels_and_color_rules():
    """图二/C4：7 状态文字逐字按裁定表，7 色值由 CSS 变量与 data-state 规则提供。

    11-18c 口径变更：「等待中」改名「排队中」（系统会自己接手），
    「部分失败」整词删除（父集合行不再挂状态词）。
    """
    labels = ["已完成", "进行中", "保存进度", "排队中", "已暂停", "失败", "已取消"]
    keys = ["completed", "running", "switching", "waiting", "paused", "failed", "cancelled"]
    for key in keys:
        assert f'.job-state[data-state="{key}"]' in CSS, f"图二/C4：缺 {key} 色值规则"
        assert f"--job-{key}:" in CSS, f"图二/C4：缺 {key} 颜色变量"
    for label in labels:
        assert f'"{label}"' in JS, f"图二/C4：缺状态文字 {label}"


def test_fig2_state_computed_from_real_job_data():
    """图二/C4：状态由 job.state 等真实字段计算，不另建体系、不得全部已完成。"""
    assert "job.state || job.execution_state || job.status" in JS, "图二/C4：读真实状态字段"
    assert 'data-state="${state.key}"' in JS, "图二/C4：状态随数据变化输出"
    assert 'note: "已完成"' not in JS, "图二/C4：不再有旧版固定文案"
    assert "已完成 · 100%" not in JS, "图二/C4：完成态不拼进度"


def test_fig2_checkbox_hidden_by_default_shown_when_editing():
    """图二/C5：复选框默认隐藏且零占位，编辑态由 #jobs-list.is-editing 显示。"""
    assert ".job-card__pick { display: none;" in CSS, "图二/C5：默认隐藏零占位"
    assert ".jobs-list.is-editing .job-card__pick" in CSS, "图二/C5：编辑态显示"
    assert 'data-act="jobs-edit"' in HTML and 'case "jobs-edit":' in JS, "图二/C5：编辑按钮接线"
    assert "is-editing" in JS, "图二/C5：JS 切换 is-editing 类"


def test_fig2_row_height_and_continuous_scroll():
    """图二：任务行约 96px，任务列表连续滚动、不截断成固定条数。"""
    assert "min-height: 96px" in CSS, "图二：常规行高 96px"
    assert "overflow-y: auto" in CSS, "图二：任务列表可滚动"
    assert "filtered.slice(0, 40)" not in JS, "图二：不得只画 40 条后留白"
    assert "groups.map((group)" in JS, "图二：渲染全部真实任务（R2 后按合集分组渲染）"


# ---------------- 图三/四：问答两态（收起两栏 / 展开三栏 / C10 拖动折叠） ----------------

def test_fig3_collapsed_two_columns_default():
    """图三/C10：默认 collapsed 收起=两栏，隐藏设置栏与其分隔线。"""
    assert 'id="ask-columns" data-ask-state="collapsed"' in HTML, "图三：默认收起态"
    assert "grid-template-columns: var(--sess-w) 12px minmax(0, 1fr);" in CSS, "图三：两栏"
    assert '[data-ask-state="collapsed"] .ask-scope' in CSS, "图三：收起隐藏设置栏"
    assert 'data-act="ask-expand"' in HTML, "图三：收起态右上 › 展开入口"


def test_fig4_expanded_three_columns_two_resizers():
    """图四/C10：展开=三栏（会话/对话/设置），两条 12px 分隔线，隐藏展开入口。"""
    assert "grid-template-columns: var(--sess-w) 12px minmax(0, 1fr) 12px var(--set-w);" in CSS, \
        "图四：三栏双分隔线"
    assert '[data-ask-state="expanded"] .ask-expand' in CSS, "图四：展开后隐藏 › 入口"
    assert HTML.count('class="ask-resizer"') == 2, "图四：恰好两条分隔线"
    assert 'data-resizer="sessions"' in HTML and 'data-resizer="settings"' in HTML, \
        "图四：两分隔线标识"


def test_fig34_expand_collapse_actions_wired():
    """图三/四：ask-expand / ask-collapse 两个按钮都有真实 case，不是只 console.warn 的死按钮。"""
    assert 'data-act="ask-expand"' in HTML and 'data-act="ask-collapse"' in HTML, "图三/四：两个入口"
    assert {"ask-expand", "ask-collapse"} <= JS_CASES, "图三/四：两个 act 都有分支"
    assert "setAskState(" in JS, "图三/四：真实切换两态"


def test_c10_real_pointer_drag_clamp_and_min_center():
    """C10：两条分隔线真实 pointer 拖动，clamp 220–360 / 260–420，中央 >=420px。"""
    for evt in ("pointerdown", "pointermove", "pointerup"):
        assert evt in JS, f"C10：缺 {evt} 真实拖动事件"
    assert "--sess-w" in JS and "--set-w" in JS and "setProperty(" in JS, \
        "C10：用 el.style.setProperty 改宽度变量"
    assert "min: 220, max: 360" in JS, "C10：会话栏 220–360"
    assert "min: 260, max: 420" in JS, "C10：设置栏 260–420"
    assert "ASK_MIN_CENTER = 420" in JS, "C10：中央对话最小可读宽度 420px"


def test_c10_fold_restore_keeps_scope_and_session_no_persistence():
    """C10：折叠再展开恢复折叠前宽度、不清空范围选择、不重置会话、不做持久化。"""
    assert "localStorage" not in JS and "sessionStorage" not in JS, "C10：不新增持久化设置"
    assert "S.askWidths" in JS, "C10：记录折叠前宽度"
    body = JS.split("function setAskState(")[1].split("function initAskResizers(")[0]
    for token in ("scopeContents", "applied", "sessionId", "sessionDetail"):
        assert token not in body, f"C10：折叠/展开不得触碰 {token}"


# ---------------- 图三/四：会话条目、范围选择、真实回答时间 ----------------

def test_fig3_session_title_only_and_hover_delete():
    """U-6/裁定F：会话只显示标题、删除键 hover/focus-within 显示、点击删除不触发会话切换。"""
    assert "fmtDate(session.created_at)" not in JS, "图三：去掉 11-10 · 日期前缀"
    assert ".session__del" in CSS and ".session-row:hover .session__del" in CSS, \
        "U-6：删除键 hover 显示"
    assert ":focus-within" in CSS and ":has(.session.is-current)" not in CSS, \
        "U-6：键盘可访问，且不再仅选中显示"
    seg = JS.split("function renderAsk()")[1].split("renderScopeList();")[0]
    assert 'data-session="' in seg and 'data-session-id="' in seg, \
        "图三：删除键与会话切换用不同属性，点击不误触发"
    assert "ask-session-delete" in JS_CASES, "图三：删除 act 有分支"
    assert "/ask/sessions/${id}" in JS, "图三：沿用 DELETE /api/v1/ask/sessions/{id}"


def test_fig4_scope_kind_all_and_content_ids():
    """图四/C10：S.scopeKind 初始 all、全库逐条列出可勾选、勾选进 content_ids。"""
    assert 'scopeKind: "all"' in JS, "图四：默认全库（segmented 选中「全库」）"
    assert 'data-scope-content=' in JS, "图四：逐条勾选框"
    assert "S.scopeKind === \"all\" ? S.history" in JS, "图四：全库逐条列出全部内容"
    assert "content_ids:" in JS, "图四：范围走 scopePayload() 的 content_ids"
    assert ".scope-item" in CSS and "-webkit-line-clamp: 2" in CSS, \
        "图四/C9：浅灰小字两行截断、无独立卡片"
    assert 'id="ask-scope-summary"' in HTML, "图四：底部「已选 N 条 · 共 M 条」"


def test_c8_answer_time_from_api_field():
    """图三/C8：.answer__time 取真实回答时间字段，不硬编码、不取当前时间。"""
    assert "answer__time" in JS, "图三：回答底部时间节点"
    assert "updated_at" in JS and "created_at" in JS, "C8：取接口持久化时间字段"
    assert "fmtDateTime(answerTime(" in JS, "C8：时间由会话/回答接口字段格式化"
    assert "detail?.messages" in JS, "C8：读会话详情真实 messages 字段"
    assert "2026-11-11 10:30" not in JS, "C8：不得硬编码效果图时间"
    assert "Date.now()" not in JS, "C8：不得用当前时间冒充历史回答时间"


# ---------------- 图五 / 图六：内容接入、内容详情 ----------------

def test_fig5_intake_full_bleed_single_card():
    """U-1/裁定A：画面铺平（推翻上一轮 960px 限宽）、查询次级/提交主操作、识别 N 条实时计算。"""
    assert '.screen[data-screen="intake"] { max-width: none; }' in CSS, "U-1：接入页去限宽"
    assert "max-width: none; min-height: calc(100vh - 220px);" in CSS, "U-1：白卡铺满并撑高"
    assert "margin-top: auto;" in CSS, "U-1：底部操作行贴底"
    assert "max-width: 960px" not in CSS, "U-1：不得残留 960px 限宽"
    assert 'data-act="intake-query"' in HTML and 'data-act="intake-submit"' in HTML, \
        "图五：查询次级 / 提交主操作"
    assert "renderIntakeCount" in JS and "intakeRows()" in JS, "图五：识别 N 条实时计算"
    assert "/imports/query" in JS and '"/settings"' in JS, "图五：沿用真实接口"


def test_fig6_four_columns_equal_sidebars_and_md_render():
    """图六：两侧栏等宽、正文走 mdToHtml 转义渲染、前后篇导航不覆盖正文。"""
    assert "220px minmax(0, 1fr) 220px" in CSS, "图六：两侧栏等宽"
    assert "function mdToHtml" in JS and "esc(" in JS, "图六：<concept> 等标记走 mdToHtml，不开任意 HTML"
    assert ".doc-pager" in CSS, "图六：前后篇导航不覆盖正文"
    assert 'data-act="doc-regenerate"' in HTML, "图六：重新生成"


def test_fig6_export_four_formats_three_destinations():
    """图六：导出 4 格式 × 3 位置全部保留真功能。"""
    for fmt in ("markdown", "pdf", "word", "text"):
        assert f'name="export-format" value="{fmt}"' in HTML, f"图六：格式 {fmt}"
    for where in ("archive", "download", "custom"):
        assert f'name="export-where" value="{where}"' in HTML, f"图六：位置 {where}"
    assert "function submitExport" in JS and "writeArchive(" in JS, "图六：导出真功能"


# ---------------- 全页：死按钮、零复用、文案规则 ----------------

def test_all_html_actions_have_js_case():
    """图一/图二/图三/图四/图五/图六（全页）：不得出现死按钮，HTML 全部 data-act 都有 case。"""
    assert len(HTML_ACTS) >= 40, f"全页：data-act 应 >= 40，实际 {len(HTML_ACTS)}"
    missing = HTML_ACTS - JS_CASES
    assert not missing, f"全页：以下 data-act 缺 case（死按钮）{sorted(missing)}"
    assert 'console.warn("[unhandled action]"' in JS and "未接线的操作" in JS, \
        "全页：未知 action 有可见反馈，不只静默 console.warn"


def test_zero_reuse_and_five_rail_items():
    """产品问题1/C2：三文件无旧框架标识；rail 恰好 5 个方框图标且第 5 个为太阳。"""
    forbidden = ["app-shell", "--theme-", "data-view", "ui-style", "_legacy",
                 "renderHistoryEntries", "renderLibraryPlatformBadge"]
    for token in forbidden:
        for name, text in [("index.html", HTML), ("style.css", CSS), ("app.js", JS)]:
            assert token not in text, f"{name} 仍含旧框架标识 {token}"
    assert HTML.count('class="rail__item') == 5, "C2：rail 恰好 5 个入口"
    assert 'id="i-sun"' in HTML, "C2：第 5 个图标为太阳"


def test_no_explanatory_subtitles():
    """图一/图四/图五（全页文案规则）：只保留名称、内容与必要状态，不新增说明副标题。"""
    assert "逐条勾选后点" not in JS and "逐条勾选后点" not in HTML, "全页：去掉说明小字"
    assert "已选 ${S.scopeContents.size} 条 · 共 ${S.history.length} 条" in JS, \
        "图四：底部只留「已选 N 条 · 共 M 条」"
    assert "识别${count}条" in JS, "图五/5-09：识别N条（无空格）为状态文字"


# ---------------- 11-12 本轮：任务两态 / 知识库 / 问答来源 ----------------

def test_u2_jobs_two_state_toolbar():
    """U-2/裁定B：任务页启用编辑前/后两种 UI，批量按钮移到编辑旁且勾选后才出现。"""
    assert 'id="jobs-batch-inline"' in HTML and 'class="jobs-batch"' not in HTML, "U-2：移除底部批量栏"
    assert 'id="jobs-edit-btn"' in HTML and 'id="jobs-refresh-btn"' in HTML, "U-2：两态按钮有钩子"
    assert "退出编辑" in JS and "renderJobsToolbar" in JS, "U-2：编辑按钮切文案"
    assert 'jobs-edit' in HTML_ACTS and "jobs-edit" in JS_CASES, "U-2：编辑接线"


def test_u3_u4_library_edit_delete_and_all_folder():
    """U-3/U-4：知识库多选分组筛选、分组管理和内容归属操作。"""
    assert "activeTagIds: [], activeFolderIds: []" in JS, "知识库分组筛选默认无选中"
    assert 'data-tag="all"' not in HTML and "全部收藏" not in JS, "R5：两个全部入口已移除"
    assert "libFilterDimension" in JS and "candidateEntries" in JS, "R2/R6：两级筛选与添加候选列表"
    assert 'data-act="lib-total"' in HTML and 'data-act="lib-filter-clear-all"' in HTML, "知识库：总库与全局清除入口"
    assert 'data-act="lib-group-menu-toggle"' in HTML and "lib-group-select" in JS_CASES, "知识库：收藏夹和标签多选筛选"
    assert "tagIds.some((id)" in JS and "folderIds.some((id)" in JS, "知识库：同类筛选按并集匹配"
    assert "lib-group-content-add" in JS_CASES and "lib-group-content-remove" in JS_CASES, "知识库：内容整理指定目标分组"
    assert 'class="lib-actions"' not in HTML, "U-5：去除第二行工具栏"
    assert 'data-act="lib-groups-open"' in HTML and 'lib-group-create' in HTML_ACTS, \
        "知识库：统一分组管理入口和双栏新建"
    assert "lib-group-more" in JS and "lib-group-rename" in JS_CASES and "lib-group-delete" in JS_CASES, \
        "知识库：每项通过更多菜单重命名或删除"
    assert "if (event.key === \"Escape\" && S.libGroupMenu)" in JS, "知识库：Escape 收起筛选菜单"
    assert "!target.closest?.(\".lib-group-filter\")" in JS, "知识库：点击筛选菜单外收起菜单"
    assert 'lib-edit' in HTML_ACTS and "lib-edit" in JS_CASES, "U-3：知识库编辑接线"
    assert 'lib-delete' in HTML_ACTS and "lib-delete" in JS_CASES, "U-3：知识库删除接线"
    assert "data-content-pick" in JS and ".lib-grid.is-editing .tile__pick" in CSS, \
        "U-3：编辑态复选框"


def test_u6_u7_hover_delete_and_clickable_sources():
    """U-6/U-7/裁定F：删除键 hover 显示、来源标签可点击查看并跳内容详情。"""
    assert ".session-row:hover .session__del" in CSS and ":focus-within" in CSS, "U-6：hover/聚焦显示"
    assert ":has(.session.is-current)" not in CSS, "U-6：不再仅选中显示"
    assert 'data-act="answer-sources"' in JS and "answer-sources" in JS_CASES, "U-7：来源标签接线"
    assert "source-open" in JS_CASES and "sourceRefs" in JS, "U-7：来源列表跳内容详情"
    assert "#popmenu.is-sources" in CSS, "U-7：来源列表可滚动"

# ---------------- 11-13 追加轮次：回收站条目封面（R9） ----------------

def test_u8_trash_rows_have_cover():
    """R9：回收站条目与知识库卡片共用封面模板，行内封面有固定宽度。"""
    assert "function renderTrash()" in JS, "R9：回收站渲染函数存在"
    block = JS.split("function renderTrash()", 1)[1].split("function renderAsk()", 1)[0]
    assert "coverHtml(content, true)" in block, "R9：回收站条目渲染封面"
    assert ".trash-row .cover" in CSS, "R9：行内封面定宽"
