"""11-22 任务批量重试反馈、去重收敛与排序锚点 防回归契约（不是验收依据）。

唯一权威验收是 8765 运行页的实际交互与人工确认。本文件只锁住外部审核指出的
几处补正：进度持续可见、成功/失败分开统计、批次锁覆盖刷新窗口、最终数字按
刷新后状态核对；合集层不再二次归并；排序锚点改用后端持久字段。
"""
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
JS = (APP / "ui" / "app.js").read_text(encoding="utf-8")
SCHEMAS = (APP / "api" / "schemas.py").read_text(encoding="utf-8")
MAIN = (APP / "api" / "main.py").read_text(encoding="utf-8")
HTML = (APP / "ui" / "index.html").read_text(encoding="utf-8")
CSS = (APP / "ui" / "style.css").read_text(encoding="utf-8")


def _job_action() -> str:
    return JS.split("async function jobAction(action)", 1)[1].split("async function loadJobStages", 1)[0]


def test_r1_progress_stays_visible_during_slow_requests():
    assert 'id="jobs-batch-progress" role="status" hidden' in HTML
    action = _job_action()
    assert 'retryProgress.hidden = false;' in action
    assert 'if (action === "retry") retryProgress.hidden = true;' in action
    assert 'showRetryProgress(`正在重试第 ${index + 1}/${ids.length} 项（成功 ${ok}，失败 ${failed}）`)' in action
    assert 'showRetryProgress(`已处理 ${index + 1}/${ids.length} 项（成功 ${ok}，失败 ${failed}）`)' in action


def test_ordinary_toast_uses_product_theme_tokens():
    rule = CSS.split(".toast {", 1)[1].split("}", 1)[0]
    assert "background: var(--card)" in rule
    assert "color: var(--ink)" in rule
    assert "border: 1px solid var(--line-2)" in rule


def test_r1_counts_success_and_failure_separately():
    """慢请求与失败请求要能被区分，进度分子不能只计成功项。"""
    action = _job_action()
    assert "let ok = 0;" in action and "let failed = 0;" in action
    assert "ok += 1;" in action and "failed += 1;" in action
    assert "（成功 ${ok}，失败 ${failed}）" in action


def test_r1_final_count_verified_after_refresh():
    """「已进入进行区」只能来自刷新后的真实状态，不能直接拿 HTTP 成功数。"""
    action = _job_action()
    assert "retriedIds.push(result.job.id);" in action and "retriedIds.push(result.id);" in action, \
        "retry 与 resume 的新任务 id 都纳入刷新后核对"
    assert "const stateOf = (jobId) =>" in action
    assert "retriedIds.filter((jobId) => liveKeys.includes(stateOf(jobId))).length" in action
    assert "已进入进行区" in action
    assert "const finalRefreshed = await syncJobsAfterMutation({ quiet: true });" in action, \
        "核对前统一刷新 jobs+queue，并在刷新失败时停止报告推测结果"


def test_r1_batch_lock_covers_request_and_refresh():
    """锁要覆盖请求 → 刷新 → 重绘整段，三条重复触发路径都必须被挡住。"""
    assert "let jobsBatchBusy = false;" in JS
    assert 'if (jobsBatchBusy) return toast("上一批操作还在进行中，请稍候");' in JS
    action = _job_action()
    assert "jobsBatchBusy = true;" in action and "} finally {" in action
    assert "jobsBatchBusy = false;" in action, "锁必须在 finally 释放，刷新异常也不能卡死"
    assert "if (jobsBatchBusy && JOB_MUTATING_ACTS.has(action.dataset.act)) {" in JS, \
        "行内与合集入口在锁期间不接新操作"
    assert '$$("#jobs-list [data-act]", list).forEach((button) => {' in JS, \
        "重绘出来的行内按钮要同步禁用"
    assert '"job-group-pause", "job-group-delete",' in JS


def test_every_item_success_refreshes_immediately():
    """四类批量动作每项成功后都立即刷新，已入队/已暂停/已删除项当场离开原区。"""
    action = _job_action()
    assert "changed = true;" in action, "成功即标记，不区分 pause/resume/retry/delete"
    assert "if (changed) {" in action
    assert 'await syncJobsAfterMutation({ quiet: true });' in action, \
        "逐项刷新统一走收口函数，逐项 quiet 避免刷屏"
    assert "retriedNow" not in action, "不得再按 retry 单独分支决定是否刷新"


def test_all_task_routes_share_one_sync_helper():
    """任务变更后刷新口径只有一份：jobs + queue + 重绘，编辑态也不漏。"""
    helper = JS.split("async function syncJobsAfterMutation(options = {}) {", 1)[1]
    helper = helper.split("\n  }", 1)[0]
    assert 'refresh("jobs", { quiet: true })' in helper
    assert 'refresh("queue", { quiet: true })' in helper
    assert "renderJobs();" in helper
    routes = ["job-group-pause", "job-group-delete", "job-pause", "job-start",
              "job-resume", "job-retry", "jobs-refresh", "queue/move"]
    for route in routes:
        assert route in JS, route
    helper = JS.split("async function runJobRowAction(jobId, pendingLabel, request, feedback)", 1)[1]
    helper = helper.split("async function jobAction(action)", 1)[0]
    assert "await syncJobsAfterMutation({ quiet: true })" in helper, "行内变更统一读回 jobs+queue"
    rows = JS.split('case "job-pause":', 1)[1].split("/* 图三 */", 1)[0]
    assert rows.count("return runJobRowAction(") == 4, "行内暂停/插队/继续/重试共用忙碌与读回"


def test_collection_attribution_shared_by_both_pages():
    """知识库页与内容侧栏共用归属取数，history job 优先覆盖暂停/失败任务。"""
    fn = JS.split("function collectionInfoOf(entry, jobMap) {", 1)[1].split("\n  }", 1)[0]
    assert "entryJob?.collection_id ? entryJob : archived" in fn, "history job 优先，completed 映射兜底"
    assert "collectionId: String(source?.collection_id" in fn
    assert JS.count("collectionInfoOf(entry, jobMap)") >= 2, "两页都用它，不允许各取各的"


def test_batch_retry_routes_paused_to_resume_and_skips_live():
    """后端 /retry 只接受 failed/cancelled：暂停转继续，进行中跳过，避免整批 409。"""
    action = _job_action()
    assert 'current === "paused"' in action
    assert 'await post(`/jobs/${id}/resume?front=false`, {})' in action
    assert "resumed += 1;" in action
    assert "result?.job?.id" in action, "retry 仍从 ImportResponse.job.id 取新任务"
    assert "result?.id" in action, "resume 返回 JobResponse.id"
    assert '["running", "switching", "waiting", "completed"].includes(current)' in action
    assert "skipped += 1;" in action
    assert "已暂停转继续" in action and "已跳过" in action, "结果提示要说清分流"


def test_paused_is_terminal_and_stage_failure_does_not_cache_empty():
    """只剩暂停任务时停止轮询空转；阶段读取失败保留重试能力。"""
    assert 'new Set(["completed", "failed", "cancelled", "paused"])' in JS
    stages = JS.split("async function loadJobStages(jobId) {", 1)[1].split("\n  }", 1)[0]
    assert "jobEvents.delete(jobId);" in stages
    assert "jobEvents.set(jobId, []);" not in stages, "空数组会渲染空白轨道且缓存命中后不再重试"


def test_r2_merge_happens_only_once():
    """归并只在 filteredJobs() 做一次，合集层不再对同一份数据二次归并。"""
    collections = JS.split("function jobCollections()", 1)[1]
    assert "const latestByContent = new Map();" not in collections
    assert "filteredJobs().forEach((job) => {" in collections


def test_r3_anchor_comes_from_backend_persistent_field():
    """锚点用内容首次入库时间，重试、删旧尝试、列表截断都不改写它。"""
    assert "content_created_at: datetime | None = None" in SCHEMAS
    assert "content_created_at=content.created_at if content is not None else None" in MAIN
    assert 'String(job.content_created_at || job.created_at || "")' in JS
    assert "const groupAnchor = new Map();" in JS, "组锚点独立于当前筛选"
