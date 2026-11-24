"""11-22 重复任务检测与分流 防回归契约（不是验收依据）。

唯一权威验收是 8765 运行页的 R7 两组最小复现。本文件锁住 R1~R5 的源码级契约：
服务端判重两层口径与活跃归档口径、三态删除分流与统一路径、继续导入走 resummarize
且同批同内容一份、折叠键带后缀、双主动作弹窗文案与三条锁释放路径。
"""
from pathlib import Path
from types import SimpleNamespace

from app.db.store import _history_identity_key, _title_suffix_key

APP = Path(__file__).resolve().parents[1] / "app"
JS = (APP / "ui" / "app.js").read_text(encoding="utf-8")
HTML = (APP / "ui" / "index.html").read_text(encoding="utf-8")
MAIN = (APP / "api" / "main.py").read_text(encoding="utf-8")
STORE = (APP / "db" / "store.py").read_text(encoding="utf-8")
SCHEMAS = (APP / "api" / "schemas.py").read_text(encoding="utf-8")


def _between(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def _job_action() -> str:
    return _between(JS, "async function jobAction(action)", "async function loadJobStages")


def _delete_helper() -> str:
    return _between(JS, "async function deleteJobWithState(job)", "async function checkDuplicateJobs")


# ---------------- R1：服务端判重两层口径 + 活跃归档 ----------------

def test_r1_duplicate_check_endpoint_exists():
    assert '@app.post("/api/v1/jobs/duplicate-check"' in MAIN
    assert "def duplicate_check(request: DuplicateCheckRequest)" in MAIN
    assert "class DuplicateCheckRequest" in SCHEMAS
    assert "class DuplicateCheckResponse" in SCHEMAS


def test_r1_uses_active_archived_only_and_two_layers():
    fn = _between(MAIN, "def duplicate_check(request: DuplicateCheckRequest)", "@app.post(\"/api/v1/jobs/{job_id}/switch\"")
    # 活跃归档口径：archived_only + 未删除，回收站不计。
    assert "archived_only=True, include_deleted=False" in fn
    # 第一层：相同 content_id 命中活跃归档集合。
    assert "if content.id in archived_ids:" in fn
    # 第二层：跨 ID 用 find_duplicate_content，且命中内容必须仍在活跃归档集合里。
    assert "store.find_duplicate_content(canonical_url=source_url)" in fn
    assert "candidate.id in archived_ids" in fn


def test_r1_only_marks_failed_paused_not_running():
    fn = _between(MAIN, "def duplicate_check(request: DuplicateCheckRequest)", "@app.post(\"/api/v1/jobs/{job_id}/switch\"")
    assert "if job.state not in {JobState.FAILED, JobState.CANCELLED, JobState.PAUSED}:" in fn


def test_r1_check_failure_does_not_block_batch():
    helper = _between(JS, "async function checkDuplicateJobs(ids)", "async function resummarizeDuplicate")
    assert 'post("/jobs/duplicate-check", { job_ids: ids })' in JS
    assert "return null;" in helper, "判重接口失败返回 null，调用方跳过弹窗走原流程"
    action = _job_action()
    assert "const checked = await checkDuplicateJobs(ids);" in action
    assert "if (checked) {" in action


def test_r1_delete_entry_does_not_pop_duplicate_dialog():
    """删除入口是唯一不查重的口径；弹窗只在 retry/resume 分支触发。"""
    action = _job_action()
    check_call = "const checked = await checkDuplicateJobs(ids);"
    guard = 'if (action === "retry" || action === "resume") {'
    # 查重调用必须位于 retry/resume 守卫之后、且没有 delete 分支调用它。
    assert action.index(guard) < action.index(check_call)
    assert action.count(check_call) == 1


# ---------------- R2：三态删除分流 + 统一路径 + 错误文案 ----------------

def test_r2_delete_helper_three_state_split():
    helper = _delete_helper()
    assert "const key = jobState(job).key;" in helper
    # 终态直接 DELETE
    assert 'await del(`/jobs/${id}`);' in helper
    assert 'return { ok: true, mode: "direct-delete" };' in helper
    # 暂停 → cancel → DELETE
    assert 'await post(`/jobs/${id}/cancel`, {});' in helper
    assert '"cancel-delete"' in helper
    # 进行中 → pause 成功再 cancel→DELETE，pause 失败计入 skip
    assert 'await post(`/jobs/${id}/pause`, {});' in helper
    assert '"pause-cancel-delete"' in helper
    assert "return { ok: false, skipped: true, reason: error.message };" in helper
    assert '"running", "switching", "waiting"' in helper


def test_r2_delete_helper_no_new_backend_endpoint():
    helper = _delete_helper()
    assert "cancel-and-delete" not in helper
    assert "force=true" not in helper
    # 复用现成 cancel 与 DELETE 两端点，无自定义后端路径。
    for bad in ["/jobs/batch-delete", "/jobs/delete-with-state"]:
        assert bad not in helper


def test_r2_cancel_success_delete_fail_is_retry_safe():
    helper = _delete_helper()
    assert "return { ok: false, cancelled: true, reason: error.message };" in helper


def test_r2_error_code_texts_added():
    assert "job_not_deletable:" in JS
    assert "job_not_retryable:" in JS
    assert "job_not_cancellable:" in JS


def test_r2_four_category_delete_feedback():
    action = _job_action()
    for label in ["直接删除", "暂停转取消删除", "跳过保留", "失败 "]:
        assert label in action, label


# ---------------- R3：舍弃共用删除路径 ----------------

def test_r3_discard_reuses_delete_helper_no_content_delete():
    action = _job_action()
    discard_seg = _between(action, 'if (dup && mode === "discard")', '} else if (dup && mode === "import")')
    assert "await deleteJobWithState(item);" in discard_seg
    # 不调用任何删 content / 归档接口。
    for bad in ["/contents/", "/archive", "purge", "delete_content"]:
        assert bad not in discard_seg, bad
    assert "舍弃 " in action and "条重复任务" in action


# ---------------- R4：继续导入 + 副本可见 + 副本数 ----------------

def test_r4_continue_import_uses_resummarize_not_retry():
    helper = _between(JS, "async function resummarizeDuplicate(matchedContentId)", "async function jobAction")
    assert "/resummarize" in helper
    assert "/retry" not in helper
    action = _job_action()
    import_seg = _between(action, 'if (dup && mode === "import")', '} else if (action === "delete")')
    assert "await resummarizeDuplicate(contentKey);" in import_seg


def test_r4_one_copy_per_content_per_batch():
    action = _job_action()
    import_seg = _between(action, 'if (dup && mode === "import")', '} else if (action === "delete")')
    assert "const contentKey = dup.matched_content_id || id;" in import_seg
    assert "if (!plan.handledContents.has(contentKey))" in import_seg
    assert "plan.handledContents.add(contentKey);" in import_seg


def test_r4_old_task_cleaned_only_after_new_job_enqueued():
    action = _job_action()
    import_seg = _between(action, 'if (dup && mode === "import")', '} else if (action === "delete")')
    assert "if (newId) {" in import_seg
    # 清理在新任务 id 拿到之后才发生。
    assert import_seg.index("if (newId) {") < import_seg.index("await deleteJobWithState")
    assert "cleanupFailed += 1;" in import_seg


def test_r4_history_fold_key_includes_title_suffix():
    assert "def _title_suffix_key(title: str | None) -> str:" in STORE
    fn = _between(STORE, "def _history_identity_key(entry: HistoryEntry)", "def _platform_connection_from_row")
    assert "_title_suffix_key(entry.content.title)" in fn
    assert 'return f"bili:{bvid}:p{page_number}:{_title_suffix_key(entry.content.title)}"' in fn
    # 无后缀仍空串 → 历史重复导入显示方式不变。
    suffix_fn = _between(STORE, "def _title_suffix_key(title: str | None)", "def _history_identity_key")
    assert 'return f"s{match.group(1)}" if match else ""' in suffix_fn
    assert r'（(\d+)）\s*$' in suffix_fn


# ---------------- R5：双主动作弹窗 + 三条锁释放路径 ----------------

def test_r5_dialog_buttons_exact_text_no_cancel():
    seg = _between(HTML, 'id="triage-dialog"', "<!--")
    assert ">舍弃</button>" in seg.replace("\n", "")
    assert ">继续导入</button>" in seg.replace("\n", "")
    assert "取消" not in seg


def test_r5_dialog_list_uses_textcontent():
    fn = _between(JS, "function requestTriageConfirmation(", "function closeTriageConfirmation")
    assert "row.textContent = line;" in fn
    assert "innerHTML" not in fn
    assert "replaceChildren()" in fn


def test_r5_callback_style_two_actions():
    fn = _between(JS, "function requestTriageConfirmation(", "function closeTriageConfirmation")
    assert "S.triageImportAction = onImport;" in fn
    assert "S.triageDiscardAction = onDiscard;" in fn
    assert "S.triageDismissAction = onDismiss" in fn
    assert "onImport" in fn and "onDiscard" in fn


def test_r5_esc_and_backdrop_dismiss_without_action():
    assert "case \"triage-dismiss\": dismissTriage(); return;" in JS
    dismiss = _between(JS, "function dismissTriage()", "function fmtDuration")
    assert "if ($(\"#triage-dialog\").hidden) return;" in dismiss
    assert "closeTriageConfirmation();" in dismiss
    assert "if (onDismiss) onDismiss();" in dismiss
    esc = [line for line in JS.splitlines() if 'event.key === "Escape"' in line][0]
    assert "dismissTriage();" in esc


def test_r5_three_lock_release_paths_via_finish():
    action = _job_action()
    assert "let finished = false;" in action
    assert "const finish = () => {" in action
    assert "if (finished) return;" in action
    assert "jobsBatchBusy = false;" in action
    # ① 动作执行完 finally；② dismiss；③ 逐条失败不中断后 finally。
    assert "} finally {\n        finish();\n      }" in action, "runBatch 末尾 finally 释放锁"
    assert "() => finish()," in action, "dismiss 回调释放锁、不执行分流"
    assert "failed += 1;" in action and "console.warn(\"[jobAction]\"" in action, "执行失败计入失败数不中断"


def test_r5_batch_lock_guard_unchanged():
    assert 'if (jobsBatchBusy) return toast("上一批操作还在进行中，请稍候");' in JS
    assert "if (jobsBatchBusy && JOB_MUTATING_ACTS.has(action.dataset.act)) {" in JS


# ---------------- 行为级：折叠键（纯函数，不连库） ----------------

def _bili_entry(title: str, url: str = "https://www.bilibili.com/video/BV1PXxd6vEaM/?p=1"):
    content = SimpleNamespace(id="content-x", title=title, source=SimpleNamespace(canonical_url=url))
    return SimpleNamespace(content=content)


def test_title_suffix_key_extracts_duplicate_suffix():
    assert _title_suffix_key("原视频（1）") == "s1"
    assert _title_suffix_key("原视频（12）") == "s12"
    assert _title_suffix_key("原视频（2）   ") == "s2"
    assert _title_suffix_key("原视频") == ""
    assert _title_suffix_key(None) == ""
    # 非末尾后缀不算副本序号。
    assert _title_suffix_key("原视频（1）后记") == ""


def test_fold_key_separates_original_and_suffixed_copy():
    original = _history_identity_key(_bili_entry("原视频"))
    copy = _history_identity_key(_bili_entry("原视频（1）"))
    assert original != copy, "原件与带序号副本要各占一行"
    assert original == "bili:BV1PXxd6vEaM:p1:", "无后缀键维持原折叠口径（末尾多空串）"


def test_fold_key_no_suffix_still_folds_history_duplicates():
    a = _history_identity_key(_bili_entry("视频 P0"))
    b = _history_identity_key(_bili_entry("视频 P1"))
    assert a == b, "无后缀的历史重复导入仍折叠成一行"
