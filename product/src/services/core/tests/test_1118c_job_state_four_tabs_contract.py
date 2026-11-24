"""11-18c R2/R3 前端契约（防回归辅助，不是验收依据）。

口径来源：用户 2026-11-18 裁定「四个状态 全部／进行中／已完成／未完成 是 OK 的，
但后端也要改」，以及后续「重启之后并不默认全量跑」「父行不挂状态词」「未完成含已取消」。

断言的判据只有一条：**系统还会不会自己接手**。
会 → 进行中（running / waiting）；不会 → 未完成（failed / cancelled / paused）。
"""

from pathlib import Path

UI = Path(__file__).resolve().parents[1] / "app" / "ui"
BACKEND = Path(__file__).resolve().parents[1] / "app"

HTML = (UI / "index.html").read_text(encoding="utf-8")
CSS = (UI / "style.css").read_text(encoding="utf-8")
JS = (UI / "app.js").read_text(encoding="utf-8")
MAIN_PY = (BACKEND / "api" / "main.py").read_text(encoding="utf-8")
QUEUE_PY = (BACKEND / "workflows" / "queue.py").read_text(encoding="utf-8")


def _collection_row_html() -> str:
    """只取父集合行渲染函数，避免把子行的 .job-state 也算进来。"""

    return JS.split("function collectionRowHtml", 1)[1].split("function renderJobs", 1)[0]


# ---------------- R2：四个标签与行内文案 ----------------

def test_r2_four_tabs_renamed():
    assert 'data-job-filter="all" aria-selected="true">全部</button>' in HTML
    assert 'data-job-filter="running" aria-selected="false">进行中</button>' in HTML
    assert 'data-job-filter="completed" aria-selected="false">已完成</button>' in HTML
    assert 'data-job-filter="incomplete" aria-selected="false">未完成</button>' in HTML
    assert 'data-job-filter="waiting"' not in HTML, "11-18c R2：旧「等待」标签已撤"
    assert 'data-job-filter="failed"' not in HTML, "11-18c R2：旧「失败」标签已撤"


def test_r2_filter_mapping_matches_ownership():
    assert 'if (S.jobFilter === "incomplete") return key === "failed" || key === "cancelled" || key === "paused";' in JS, \
        "11-18c R2：未完成 = 失败 + 已取消 + 已暂停"
    assert 'return key !== "completed" && key !== "failed" && key !== "cancelled" && key !== "paused";' in JS, \
        "11-18c R2：进行中 = 其余（运行中 / 排队中），已暂停不得混进来"


def test_r2_state_words_and_buttons():
    assert 'waiting: "排队中"' in JS, "11-18c R2：等待中改名排队中（系统会自己接手）"
    assert 'partial: "部分失败"' not in JS, "11-18c R2：部分失败整词删除"
    assert 'else if (key === "waiting") { action = "插队"; act = "job-start"; }' in JS, \
        "11-18c R2：排队中的按钮是插队（行为仍是抢占）"
    assert 'else if (key === "paused") { action = "继续"; act = "job-resume"; }' in JS, \
        "11-18c R2：已暂停必须人点，按钮叫继续"


def test_r2_parent_row_has_no_state_word():
    body = _collection_row_html()
    assert 'class="job-state"' not in body, "11-18c R2：父集合行不再挂状态词"
    assert 'aria-label="任务状态：${label}"' not in body
    assert "已完成 ${group.completed} / ${group.total}" in body, "父集合行只留计数"
    assert 'stateKey = "partial"' not in JS, "11-18c R2：partial 合成状态已撤"
    assert '.job-state[data-state="partial"]' not in CSS, "11-18c R2：partial 配色规则一并撤掉"


def test_r2_group_zone_no_longer_treats_paused_as_live():
    assert "const zone = hasRunning || hasQueued ? 0 : 1;" in JS, \
        "11-18c R2：只有进行中 / 排队中才算「还有活」，已暂停归未完成"
    assert "const hasLive = states.includes(\"waiting\") || states.includes(\"paused\");" not in JS


# ---------------- R3：批量继续保序 ----------------

def test_r3_batch_resume_keeps_list_order():
    assert 'const query = action === "resume" ? "?front=false" : "";' in JS, \
        "11-18c R3：批量继续走队尾，不逐条插队"
    assert "const listOrder = new Map((S.jobs || []).map((job, index) => [job.id, index]));" in JS, \
        "11-18c R3：批量顺序按列表，不按勾选先后"
    assert '`/jobs/${job.id}/resume?front=false`' in MAIN_PY or "front: bool = True" in MAIN_PY, \
        "11-18c R3：后端 resume 接受 front 参数"
    assert "if job.state is JobState.QUEUED:" in MAIN_PY, "11-18c R3：排队中再点继续是幂等，不再 409"


# ---------------- R1：启动挂起 + 队列不叠栈 ----------------

def test_r1_startup_holds_instead_of_resuming():
    assert "def _hold_interrupted_jobs(store) -> int:" in MAIN_PY
    assert "held_jobs = _hold_interrupted_jobs(store)" in MAIN_PY, "启动时统一挂起"
    assert 'logger.info("startup_hold count=%s", held_jobs)' in MAIN_PY
    assert "for recovered_job in store.recover_expired_jobs():" not in MAIN_PY, \
        "11-18c R1：不再自动续跑过期租约的任务"
    assert "_remember_stable_checkpoint(job)" in MAIN_PY, "挂起前要记断点"


def test_r1_queue_drains_with_loop_not_recursion():
    run_body = QUEUE_PY.split("def _run(", 1)[1]
    assert "while True:" in run_body, "11-18c R1：队列排空改循环"
    assert "self._run(next_item, runner)" not in run_body, "11-18c R1：不得再尾递归叠栈"


# ---------------- R4：重试后结束态排序稳定（11-21，11-22 v2 补正） ----------------

def test_retry_keeps_ended_group_position():
    assert "function contentKey(job) {" in JS, "去重与排序共用同一内容身份键"
    assert "function jobAnchorTime(job) {" in JS, "排序锚点统一走内容首次入库时间"
    assert 'String(job.content_created_at || job.created_at || "")' in JS, \
        "锚点优先用后端 content_created_at，缺失才退回任务创建时间"
    assert "const groupAnchor = new Map();" in JS, "合集锚点扫全量任务，独立于当前筛选"
    assert 'sortAnchor: groupAnchor.get(bucket.key) || jobs.map(jobAnchorTime).sort()[0] || ""' in JS
    assert 'const anchorOf = (group) => group.sortAnchor || group.anchor || "";' in JS
    assert "anchorOf(b).localeCompare(anchorOf(a))" in JS
    assert "lineageAnchor" not in JS, \
        "不再靠前端扫 S.jobs 取最早 created_at（会受列表截断与删除影响）"
    assert "(b.completedAt || b.anchor).localeCompare(a.completedAt || a.anchor)" not in JS, \
        "结束态不得按最近完成时间倒序，否则重试后旧项会浮到顶部"
