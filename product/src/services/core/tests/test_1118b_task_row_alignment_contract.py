"""11-18b 任务行对齐与重试归并 防回归辅助契约（不是验收依据）。

唯一权威验收是 8765 运行页的实际交互与人工确认。本文件只锁住本轮的四处
结构口径：操作按钮固定宽度、父集合下拉与阶段符号同列、阶段轴收窄、同内容归并。
"""
from pathlib import Path

UI = Path(__file__).resolve().parents[1] / "app" / "ui"
CSS = (UI / "style.css").read_text(encoding="utf-8")
JS = (UI / "app.js").read_text(encoding="utf-8")


def test_r1_action_button_fixed_width():
    """R1：查看结果/重试/开始等按钮同一宽度，符号列与按钮中心都不再跳动。"""
    assert ".job-card > .btn--quiet { color: var(--blue); padding: 0 6px; min-width: 80px; }" in CSS
    assert ".job-card__count { flex: none; min-width: 80px;" in CSS, "R1：父集合右侧占位列同宽"


def test_r2_collection_chevron_in_action_column():
    """R2：父集合下拉箭头移到卡片最右，与子行阶段符号同为 28px 方框。"""
    head = JS.split("function collectionRowHtml(group)", 1)[1].split("if (!expanded) return head;", 1)[0]
    body = head.split("const head = `", 1)[1]
    assert body.index("</div></div>") < body.index("${expandBtn}"), "R2：箭头已移出正文容器"
    assert body.index("${expandBtn}") < body.index('<span class="job-card__count">'), \
        "R2：箭头落在计数之前，与子行符号同列"
    assert ".job-card--group .job-expand { display: grid; place-items: center; width: 28px; height: 28px; margin: 0; }" in CSS
    assert 'data-act="job-expand"' in JS and 'data-group-key="${esc(group.key)}"' in JS, "R2：展开接线不变"


def test_r3_stage_track_shortened():
    """R3：阶段轴内容收窄到 720px 居中，外框仍占整行以保证换行。"""
    assert ".job-stages { flex-basis: 100%; padding: 10px 0 4px; }" in CSS
    assert ".job-stages > * { max-width: 720px; margin-left: auto; margin-right: auto; }" in CSS
    assert "grid-template-columns: repeat(5, minmax(0, 1fr))" in CSS, "R3：五段等分保留"


def test_r4_same_content_merged_to_latest_attempt():
    """R4：同一 content_id 的多次尝试只留最新一条，且去重发生在筛选之前。

    11-21 v2：二次归并从 jobCollections() 移除。filteredJobs() 已按同一把
    contentKey 对全量任务归并一次，合集层再归并是同一数据上的幂等空转。
    """
    block = JS.split("function filteredJobs()", 1)[1].split("function cleanCollectionTitle", 1)[0]
    assert "const latest = new Map();" in block
    assert "const mergeKey = contentKey(job);" in block, "R4/11-21：去重键抽为 contentKey"
    assert block.index("latest.set(mergeKey, job)") < block.index("Array.from(latest.values()).filter(jobInFilter)"), \
        "R4：先按内容归并，再套筛选"
    collections = JS.split("function jobCollections()", 1)[1]
    assert "const latestByContent = new Map();" not in collections, \
        "11-21 v2：合集层不再二次归并"
