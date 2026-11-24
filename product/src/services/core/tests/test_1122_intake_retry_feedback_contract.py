"""11-22 链接提交等待、失败重查与任务可见反馈契约。"""
from pathlib import Path


JS = (Path(__file__).resolve().parents[1] / "app" / "ui" / "app.js").read_text(encoding="utf-8")


def _intake_query() -> str:
    return JS.split("async function intakeQuery(", 1)[1].split("function lockIntake", 1)[0]


def _intake_submit() -> str:
    return JS.split("async function intakeSubmit()", 1)[1].split("const accountImportTitles", 1)[0]


def test_submit_is_locked_before_requery_and_shows_current_phase():
    submit = _intake_submit()
    assert submit.index("S.intakeSubmitting = true;") < submit.index("intakeQuery({ fromSubmit: true })")
    assert "if (S.intakeSubmitting) return;" in submit
    assert "function renderIntakeControls()" in JS
    assert 'S.intakePhase === "query" ? "正在查询…" : "提交中…"' in JS


def test_failed_submission_forces_fresh_query_before_retry():
    submit = _intake_submit()
    assert "S.intakePreviewSnapshot = null;" in submit
    assert 'S.intakePreviewItems.every((item) => ["ready", "duplicate"].includes(item.status))' in submit
    query = _intake_query()
    assert "S.intakeQuerying" in query and "finally" in query


def test_created_count_requires_job_list_readback_and_reuse_is_separate():
    submit = _intake_submit()
    assert submit.index('const jobsRefreshed = await refresh("jobs");') < submit.index("const created = jobsRefreshed")
    assert 'S.jobs.some((job) => job.id === item.job?.id)' in submit
    assert '已创建 ${created.length} 项' in submit
    assert '复用 ${reusedCount} 项' in submit
    assert '失败 ${failed.length} 项' in submit
    preview = JS.split("function renderIntakePreview(", 1)[1].split("function invalidateIntakePreview", 1)[0]
    assert 'options.submitting && ["ready", "duplicate"].includes(status)' in preview
    assert 'status === "failed" || status === "timed_out" ? (item.reason || "识别失败")' in preview


def test_failure_keeps_input_but_success_clears_it():
    submit = _intake_submit()
    failure = submit.split("if (failed.length) {", 1)[1].split("if (!createdItems.length)", 1)[0]
    assert '$("#intake-links").value = "";' not in failure
    success = submit.rsplit('const jobsRefreshed = await refresh("jobs");', 1)[1]
    assert '$("#intake-links").value = "";' in success
