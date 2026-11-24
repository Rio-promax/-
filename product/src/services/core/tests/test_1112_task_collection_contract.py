"""R1～R13 防回归辅助契约（不是验收依据）。

唯一权威验收是「运行页实际交互」。本文件只锁住本轮已经落地的结构与接线，
防止后续改动把排序口径、合集字段、阶段展示、全选联动、配置枚举再改回非法值。
断言只指向：跨文件字段映射、CSS 数值、HTML→JS 接线、后端真实端点。
"""
from pathlib import Path
import re

UI = Path(__file__).resolve().parents[1] / "app" / "ui"
MAIN_PY_PATH = UI.parent / "api" / "main.py"
SCHEMAS_PATH = UI.parent / "api" / "schemas.py"

HTML = (UI / "index.html").read_text(encoding="utf-8")
CSS = (UI / "style.css").read_text(encoding="utf-8")
JS = (UI / "app.js").read_text(encoding="utf-8")
MAIN_PY = MAIN_PY_PATH.read_text(encoding="utf-8")
SCHEMAS = SCHEMAS_PATH.read_text(encoding="utf-8")

STYLE_VALUES = [
    "general", "course_notes", "academic", "tutorial",
    "sharing", "task_oriented", "business", "meeting_minutes",
]
STRENGTH_VALUES = ["quick", "standard", "deep"]


# ---------------- R1：任务排序 ----------------

def test_r1_order_follows_import_sequence():
    """分区：有活任务（进行中 / 排队中）在最上 → 已结束（首次导入最近在上）。

    11-18c 口径变更：原三区「进行中 → 等待中（已暂停最前）→ 已结束」改为两区；
    已暂停归「未完成」，不再单独占一道等待区。
    11-21 修订：结束态原按最近完成时间倒序，重试会产生新完成时间让旧项浮顶；
    改用内容首次入库时间作锚点，重试后仍停在原位置。
    11-22 v2：锚点改为后端持久字段 content_created_at，合集锚点独立于当前筛选，
    同锚点用合集键兜底，顺序不再依赖后端返回顺序。
    """
    assert "JOB_STATE_ORDER" not in JS, "R1：不再用状态优先级常量"
    assert "jobs.sort((a, b) => orderOf(a) - orderOf(b));" in JS, "R1：组内按导入序号升序"
    assert "const zone = hasRunning || hasQueued ? 0 : 1;" in JS, "11-18c R1：两区分层"
    assert "if (a.zone !== b.zone) return a.zone - b.zone;" in JS, "R1：有活任务的组优先"
    assert "if (a.hasRunning !== b.hasRunning) return a.hasRunning ? -1 : 1;" in JS, \
        "11-18c R1：跑着的组先于排队的组"
    assert "if (liveA && liveB && posA !== posB) return posA - posB;" in JS, \
        "R1：排队区按队列位置，重试的排最后"
    assert 'const anchorOf = (group) => group.sortAnchor || group.anchor || "";' in JS, \
        "11-22 R3：锚点统一取值，不再退回最近完成时间"
    assert "anchorOf(b).localeCompare(anchorOf(a))" in JS, \
        "11-21 R4：已结束按首次入库时间倒序，重试不改变位置"
    assert 'stateA === "completed"' not in JS, "R1：完成项不再沉底"


def test_r1_keeps_scroll_expand_and_selection():
    """R1：排序变化后保留滚动位置、展开状态与已选任务。"""
    assert "const scrollTop = list.scrollTop;" in JS, "R1：重绘前记录滚动位置"
    assert "list.scrollTop = scrollTop;" in JS, "R1：重绘后恢复滚动位置"
    assert "const expandedCollections = new Set();" in JS, "R1：展开状态跨重绘保留"
    assert "jobExpandedCount" not in JS, "R3：展开数量用 jobViewLimit 保存，不用会回缩的临时变量"
    assert "const jobViewLimit = new Map();" in JS, "R3：展开数量跨重绘保留"


# ---------------- R2：父子任务与进度 ----------------

def test_r2_collection_fields_exist_backend():
    """合集含受信任 B 站 season 与同一 BVID 的多 P／多批；导入批次本身不作合集键。"""
    for field in ("collection_id: str | None = None",
                  "collection_title: str | None = None",
                  "collection_total: int | None = None"):
        assert field in SCHEMAS, f"R2：JobResponse 缺字段 {field}"
    assert "def _job_collection_id(job)" in MAIN_PY, "R2：合集键统一由 _job_collection_id 计算"
    collection_helper = MAIN_PY.split("def _job_collection_id(job)", 1)[1].split("def _job_execution_state", 1)[0]
    assert 'f"season:{season_id}"' in collection_helper, "R2：受信任 season 作为合集键"
    assert "import_batch_id" not in collection_helper, "R2：导入批次不回退为合集"
    assert "job.metadata.get(\"season_id\")" in collection_helper
    assert 'collection_metadata = {\n                "season_id": season_id' in MAIN_PY, \
        "R2：只有受信任扫描结果向任务写 season_id"
    confirm_schema = SCHEMAS.split("class LinkQueryConfirmRequest", 1)[1].split("class SourceProbeRequest", 1)[0]
    assert "collection_id:" not in confirm_schema, "R2：链接确认不接受任意合集字段"


def test_r2_parent_state_never_ends_early():
    """R2：还有等待项不能提前结束；取消不算成功。

    11-18c 口径变更：父集合行不再挂状态词，「部分失败」整词删除，
    只保留已有的「已完成 Y / Z」计数；stateKey 降级为排序内部字段。
    """
    assert 'if (states.includes("running") || states.includes("switching")) stateKey = "running";' in JS
    assert 'else if (states.includes("waiting")) stateKey = "running";' in JS, \
        "R2：仍有等待项时父任务保持进行中"
    assert 'countOf("completed") === states.length' in JS, "R2：全部成功才是已完成"
    assert 'stateKey = "partial"' not in JS, "11-18c R2：部分失败已删除"
    assert 'partial: "部分失败"' not in JS, "11-18c R2：状态词表只留六项"
    assert 'aria-label="任务状态：${label}"' not in JS.split("function collectionRowHtml", 1)[1], \
        "11-18c R2：父集合行不再渲染 .job-state"
    assert 'const key = bucket.key,' in JS and 'data-group-state' in JS or 'data-job-group' in JS, \
        "R2：父行复选框携带分组标识"
    assert "已完成 ${group.completed} / ${group.total}" in JS, "R2：父任务显示整集完成数量"


def test_r2_retry_items_deduplicated_in_collection():
    """R2/R4：同一 BVID+P 的重试与重复导入只保留最新一条任务，避免父集虚高。"""
    assert "const identity = jobIdentity(job);" in JS
    assert "latest.set(identity, job);" in JS


# ---------------- R3：子项排序与展开 ----------------

def test_r3_page_size_and_increment():
    assert "const JOB_PAGE_SIZE = 4;" in JS, "R3：默认最多 4 项"
    assert "(jobViewLimit.get(key) || JOB_PAGE_SIZE) + JOB_PAGE_SIZE" in JS, "R3：每次继续展开 +4"
    assert "group.jobs.length > shown.length" in JS, "R3：全部展开后不再出现继续展开"
    assert "data-act=\"job-expand-more\"" in JS, "R3：继续展开按钮接线"


def test_r3_keeps_original_number_after_status_change():
    assert "job.batch_item_number" in JS, "R3：保留原始序号"
    assert "fallbackOrder" in JS, "R3：缺序号时按创建先后补位"
    assert "function startJobsWatch()" in JS and "refresh(\"jobs\", { quiet: true })" in JS, \
        "R3：任务页自动刷新状态，列表不会停在进入时的快照"


# ---------------- R4：开始/暂停与拖拽换位 ----------------

def test_r4_start_resume_and_drag_wired():
    # 11-18c R2 口径变更：排队中是「系统会自己接手」，点它等于插队抢占；
    # 已暂停必须人点，所以按钮叫「继续」。
    assert 'action = "插队"; act = "job-start";' in JS, "R4：排队中给插队按钮（行为仍是抢占）"
    assert 'action = "继续"; act = "job-resume";' in JS, "R4：已暂停给继续按钮"
    assert "`/jobs/${target.dataset.jobId}/switch`" in JS, "R4：开始走抢占接口"
    assert "`/jobs/${target.dataset.jobId}/resume`" in JS, "R4：暂停恢复走 resume"
    assert 'draggable="true" data-drag-job=' in JS, "R4：等待中可拖拽"
    assert 'post("/queue/move", { job_id: moving, target_index: target })' in JS, \
        "R4：拖拽落到队列移动接口"
    assert "if (dragJobId) { jobsWatchTimer = setTimeout(jobsWatchTick, 4000); return; }" in JS, \
        "R4：拖拽期间不重绘"


def test_r4_preempted_job_continues_by_itself():
    """被插队的那条排到插队者之后，并自动接力，不用用户再点一次开始。"""
    assert 'active.metadata["switch_requeue"] = True' in MAIN_PY, \
        "R4：被抢占的任务要打上自动接力标记"
    assert "app.state.job_queue.requeue(active.id, index=anchor)" in MAIN_PY, \
        "R4：被抢占的任务排到插队者之后"
    assert "LocalJobQueue(store, queue_limit, revive_requeued_job)" in MAIN_PY, \
        "R4：队列轮到该任务时把它从暂停态唤醒"
    assert 'job.metadata.pop("switch_requeue", None)' in MAIN_PY, \
        "R4：唤醒后清掉标记，之后的手动暂停仍是暂停"
    assert "if _is_switch_requeue(job):\n        return \"waiting\"" in MAIN_PY, \
        "R4：对用户显示为等待中而不是已暂停"


# ---------------- R4：内容库集合 ----------------

def test_r4_library_shows_collections_with_single_cover():
    assert "function libraryGroups()" in JS, "R4：知识库按合集分组"
    assert "function collectionTileHtml(group)" in JS
    assert 'String(job.state || "").toLowerCase() !== "completed"' in JS, \
        "R4：按历史成功任务判断归档资格，不被最新失败重试覆盖"
    assert "const jobMap = archivedJobByContent();" in JS
    assert "S.libCollection" in JS, "R4：可进入单个集查看"
    assert "tile--collection" in CSS and "tile__collection-count" in CSS, "R4：集卡片有独立样式"


# ---------------- R5：重新总结弹窗 ----------------

def test_r5_restyle_dialog_wired():
    assert 'id="restyle-sheet"' in HTML and 'id="restyle-submit"' in HTML
    assert 'data-act="restyle-close"' in HTML and 'data-act="restyle-submit"' in HTML
    assert "function submitRestyle()" in JS
    assert "if (S.restyleSubmitting || !S.contentId) return;" in JS, "R5：提交中阻止重复提交"
    assert 'errorLine.textContent = `提交失败：${error.message}`;' in JS, "R5：失败显示原因"
    assert '$("#restyle-sheet").hidden = true;' in JS, "R5：取消只关弹窗，不建任务"
    assert "post(`/contents/${S.contentId}/resummarize`" in JS, "R5：复用原重新总结接口"


# ---------------- R6：运行过程展示 ----------------

def test_r6_stages_come_from_real_events():
    assert "/jobs/${encodeURIComponent(jobId)}/events" in JS, "R6：阶段取真实事件接口"
    assert "function jobStagesHtml(job)" in JS
    assert "job-stage-list" in CSS and "job-stage__bar" in CSS, "R6：阶段进度条"
    assert 'JOB_STAGE_ORDER = ["source", "transcription", "chunking", "summary", "archive"]' in JS, \
        "R6：阶段轴与 /jobs/{id}/events 返回的真实 stage 名一致"
    assert 'queue: "排队", source: "取材", transcription: "转写",' in JS, "R6：阶段文字"


def test_r6_no_fake_percentage_and_real_pause_feedback():
    assert "const progress = event && Number.isFinite(Number(event.progress))" in JS, \
        "R6：没有数据不写百分比"
    assert "progress == null ? 0 : progress" in JS, "R6：无数据不画假进度"
    # 11-18 R2：排队改为「第X/共Y」并移到展开态的状态行；分母取运行时队列总数。
    assert "function jobQueueBadge(job)" in JS, "11-18 R2：排队位次由运行时队列计算"
    assert "排队 第${position}/共${total}" in JS, "11-18 R2：等待显示「第X/共Y」"
    assert 'expanded && state.key === "waiting" ? jobQueueBadge(job)' in JS, \
        "11-18 R2：排队只在阶段展开态出现"
    assert "排队第 ${queued} 位" not in JS, "11-18 R2：旧排队文案已移除"
    # 11-17 R1：失败原因改由 humanizeFailure 统一给「阶段 + 中文原因 + 下一步」，
    # 不再把后端英文异常原文直接展示给用户；R6「失败显示真实原因」的语义继续保留。
    assert "note = humanizeFailure(job).text;" in JS, "R6／11-17 R1：失败显示真实原因"
    assert "job.error_message || \"该阶段执行失败\"" not in JS, "11-17 R1：旧英文原文直显已移除"
    assert 'toast("已暂停")' not in JS, "R6：暂停提示按接口返回状态，不写死"
    assert 'toast(key === "paused" ? "已暂停" : ' in JS


# ---------------- R7：内容接入布局 ----------------

def test_r7_account_strip_moved_below_options():
    strip = HTML.find('class="account-import-strip account-import-strip--compact"')
    options = HTML.find('class="intake-card__options"')
    foot = HTML.find('class="intake-card__foot"')
    assert strip > -1 and options > -1 and foot > -1
    assert options < strip < foot, "R7：快捷导入须在表达风格/强度之后、底部操作之前"
    assert "account-import-strip--compact .account-import-strip__actions { display: flex; flex-wrap: wrap;" in CSS, \
        "R7：窄窗换行不遮挡"


# ---------------- R8：恢复总结配置 ----------------

def test_r8_restores_valid_enums_and_really_sends_them():
    for style in STYLE_VALUES:
        assert f'value="{style}"' in HTML, f"R8：缺合法风格 {style}"
    for strength in STRENGTH_VALUES:
        assert f'value="{strength}"' in HTML, f"R8：缺合法强度 {strength}"
    assert 'value="concise"' not in HTML and 'value="brief"' not in HTML, "R8：不得保留非法枚举"
    assert 'summary_style: $("#intake-style").value' in JS, "R8：导入真实发送风格"
    assert 'strength: $("#intake-strength").value' in JS, "R8：导入真实发送强度"
    assert 'summary_style: $("#restyle-style").value' in JS, "R8：重新总结用同一组风格"
    assert 'strength: $("#restyle-strength").value' in JS, "R8：重新总结用同一组强度"


# ---------------- R9：任务页高度 ----------------

def test_r9_jobs_list_uses_remaining_height():
    assert ".screen[data-screen=\"tasks\"] {" in CSS, "R9：任务页有独立高度规则"
    assert "display: flex; flex-direction: column;" in CSS
    assert "flex: 1; min-height: 0;" in CSS, "R9：列表吃剩余高度并正常滚动"
    assert "max-height: calc(100vh - 320px)" not in CSS, "R9：不再用 320px 硬算留白"


# ---------------- R10：编辑全选 ----------------

def test_r10_select_all_with_parent_child_linkage():
    assert 'id="jobs-select-all"' in HTML and 'data-act="jobs-select-all"' in HTML
    assert "function filteredJobs()" in JS, "R10：全选范围与筛选共用同一份结果"
    assert 'case "jobs-select-all"' in JS
    assert "box.indeterminate = picked > 0 && picked < group.jobs.length;" in JS, \
        "R10：子项部分选中时父集半选"
    assert "const groupPick = target.dataset?.jobGroup;" in JS, "R10：勾父集带动全部子项"
    assert 'selectAll.textContent = allPicked ? "取消全选" : "全选";' in JS, "R10：全选与取消全选两态"


# ---------------- R11 / R12 / R13：目录、来源卡、外部链接 ----------------

def test_r11_outline_offset_and_link_color():
    assert "padding: 28px 14px 20px;" in CSS, "R11：目录整体下移"
    assert "color: var(--blue); display: -webkit-box;" in CSS, "R11：来源链接用界面链接色"


def test_r12_source_card_without_thumbnail():
    assert "doc-source-thumb" not in HTML, "R12：来源卡不再有重复缩略图"
    assert "source-card__thumb" not in CSS, "R12：缩略图样式一并移除，不留空白占位"
    assert 'id="doc-source-title"' in HTML, "R12：来源标题仍可点击"


def test_r13_external_link_via_system_browser():
    assert 'data-act="doc-open-source"' in HTML, "R13：来源卡改为外链操作"
    assert 'target="_blank"' not in HTML, "R13：不再走壳内新窗口"
    assert '"/api/v1/system/open-url"' in MAIN_PY, "R13：系统浏览器端点存在"
    assert "webbrowser.open(parsed.geturl())" in MAIN_PY
    assert 'if parsed.scheme not in {"http", "https"} or not parsed.netloc:' in MAIN_PY, \
        "R13：只允许 http/https"
    assert "链接已复制" in JS, "R13：打开失败时提供复制"
