"""11-18 界面局部改造 防回归辅助契约（不是验收依据）。

唯一权威验收是 8765 运行页的实际交互与人工确认。本文件只锁住本轮五处
局部改动的结构接线，防止后续把定稿版图的口径改回去。
"""
from pathlib import Path

UI = Path(__file__).resolve().parents[1] / "app" / "ui"
HTML = (UI / "index.html").read_text(encoding="utf-8")
CSS = (UI / "style.css").read_text(encoding="utf-8")
JS = (UI / "app.js").read_text(encoding="utf-8")


def test_r1_collection_head_aligns_with_rows():
    """R1：父集合下拉入口在「已完成」之后，封面前端不再被占位顶右；封面带合集角标。"""
    head = JS.split("function collectionRowHtml(group)", 1)[1].split("if (!expanded) return head;", 1)[0]
    body = head.split("const head = `", 1)[1]
    assert body.index("${jobCover(") < body.index("${expandBtn}"), "R1：封面不再被下拉按钮顶右"
    assert '<span class="job-state"' not in body, \
        "11-18c R2 口径变更：父集合行不再挂状态词，下拉直接跟在名称与计数之后"
    assert 'jobCover(group.jobs[0], "合集")' in JS, "R1：封面右上角合集角标"
    assert 'data-act="job-expand"' in head and 'data-group-key="${esc(group.key)}"' in head, \
        "R1：展开接线不变"
    assert 'cornerText ? `<span class="cover__corner">' in JS, "R1：角标只在传入 cornerText 时渲染"
    assert ".cover__corner {" in CSS and ".job-card--group .job-expand {" in CSS


def test_r2_stage_toggle_icon_and_queue_badge():
    """R2：阶段按钮是固定宽图标，排队「第X/共Y」只在展开态状态行。"""
    assert 'aria-label="${stageLabel}" title="${stageLabel}"' in JS
    assert '<path d="M4 7h16M4 12h16M4 17h16"/>' in JS, "R2：三条横线图标"
    assert "width: 28px; height: 28px" in CSS, "R2：阶段按钮各行同宽"
    assert "function jobQueueBadge(job)" in JS
    assert "排队 第${position}/共${total}" in JS
    assert ".job-card__queue" in CSS
    assert "排队第 ${queued} 位" not in JS, "R2：旧文案已移除"


def test_r3_stage_track_centered():
    """R3：阶段轴居中；11-18b R3 已按用户口径把轨道内容收窄到 720px。"""
    assert ".job-stages { flex-basis: 100%; padding: 10px 0 4px; }" in CSS
    assert ".job-stages > * { max-width: 720px; margin-left: auto; margin-right: auto; }" in CSS
    assert "max-width: 560px" not in CSS
    assert "grid-template-columns: repeat(5, minmax(0, 1fr))" in CSS, "R3：五段等分保留"


def test_r4_quick_list_collection_dropdown():
    """R4：父集合聚合、先展开子集面板、面板不溢出侧栏。"""
    assert "function quickGroups()" in JS
    assert "const jobMap = archivedJobByContent();" in JS
    assert "collectionInfoOf(entry, jobMap)" in JS, "归属改由统一函数取数（含 paused/failed）"
    assert 'data-quick-group="${esc(group.key)}"' in JS
    assert "S.quickOpen = S.quickOpen === key ? null : key;" in JS
    assert "quickOpen: null" in JS
    assert "quick-group__panel" in CSS and "max-width: 100%" in CSS
    assert "overflow-x: hidden" in CSS, "R4：侧栏仍禁止横向溢出"
    block = JS.split('const quickGroup = target.closest?.("[data-quick-group]");', 1)[1] \
        .split("const quick = target.closest", 1)[0]
    assert "openContent" not in block, "R4：点父项不得直接进内容"


def test_r5_source_card_neutral_blue():
    """R5：来源卡去棕黄；目录与链接文字契约不变。"""
    assert "background: #eef4ff;" in CSS
    assert "#fdf1da" not in CSS
    assert "color: var(--blue); display: -webkit-box;" in CSS
    assert "padding: 28px 14px 20px;" in CSS


def test_scope_ai_ask_untouched():
    """范围外：AI 问答结构保持 11-12 的两态栅格，本轮不改。"""
    assert "220px minmax(0, 1fr) 220px" in CSS
    assert 'id="ask-columns" data-ask-state="collapsed"' in HTML
