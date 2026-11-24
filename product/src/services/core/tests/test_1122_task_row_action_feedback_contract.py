"""11-22 任务行操作的等待与读回 UI 契约。"""
from pathlib import Path


JS = (Path(__file__).resolve().parents[1] / "app" / "ui" / "app.js").read_text(encoding="utf-8")


def _row_actions() -> str:
    return JS.split('case "job-pause":', 1)[1].split("/* 图三 */", 1)[0]


def test_row_action_shows_progress_and_blocks_duplicate_clicks():
    assert "const jobActionsInFlight = new Map();" in JS
    assert "const pendingAction = jobActionsInFlight.get(job.id);" in JS
    assert "async function runJobRowAction(jobId, pendingLabel, request, feedback)" in JS
    assert "if (jobActionsInFlight.has(jobId)) return;" in JS
    assert 'jobActionsInFlight.delete(jobId);' in JS
    block = _row_actions()
    for label in ("正在暂停…", "正在切换…", "正在恢复…", "正在重试…"):
        assert label in block
    assert '${actionDisabled ? " disabled" : ""}' in JS


def test_row_action_result_comes_from_refreshed_job_and_queue():
    assert "([jobsRefreshed, queueRefreshed]) => jobsRefreshed && queueRefreshed" in JS
    helper = JS.split("async function runJobRowAction(jobId, pendingLabel, request, feedback)", 1)[1]
    helper = helper.split("async function jobAction(action)", 1)[0]
    assert "await syncJobsAfterMutation({ quiet: true })" in helper
    block = _row_actions()
    assert 'state === "waiting" ? "已移到队首"' in block
    assert 'state === "running" ? "已开始处理"' in block


def test_priority_feedback_only_names_requeued_active_job_after_confirmation():
    block = _row_actions()
    assert "const activeBefore = S.queue?.active_job_id || null;" in JS
    assert "queue?.items?.some((item) => item.job_id === activeBefore)" in block
    assert "原任务已回队列" in block
    assert "已开始，原任务已让出" not in block


def test_batch_pause_and_resume_report_confirmed_outcomes():
    action = JS.split("async function jobAction(action)", 1)[1].split("async function loadJobStages", 1)[0]
    assert "let pauseConfirmed = 0;" in action
    assert "let resumeQueued = 0;" in action and "let resumeStarted = 0;" in action
    assert "pauseConfirmed += 1;" in action
    assert "resumeQueued += 1;" in action and "resumeStarted += 1;" in action
    assert '已暂停 ${pauseConfirmed} 项' in action
    assert '已重新排队 ${resumeQueued} 项' in action
    assert '已开始处理 ${resumeStarted} 项' in action
