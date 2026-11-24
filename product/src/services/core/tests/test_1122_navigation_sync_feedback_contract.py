"""11-22 导航恢复与读操作反馈契约。"""
from pathlib import Path


APP = Path(__file__).resolve().parents[1] / "app"
JS = (APP / "ui" / "app.js").read_text(encoding="utf-8")
HTML = (APP / "ui" / "index.html").read_text(encoding="utf-8")
CSS = (APP / "ui" / "style.css").read_text(encoding="utf-8")


def test_settings_and_task_content_returns_restore_their_origin():
    assert "settingsReturnRoute" in JS
    assert "S.settingsReturnRoute = S.route" in JS
    assert 'case "settings-back": return go(S.settingsReturnRoute || "intake")' in JS
    assert 'route: "tasks", jobFilter: S.jobFilter, scrollTop: $("#jobs-list").scrollTop' in JS
    assert "function returnFromContent()" in JS
    assert 'case "doc-back": case "doc-back-bottom": return returnFromContent()' in JS
    assert "context.jobFilter" in JS and "context.scrollTop" in JS


def test_note_navigation_has_a_reachable_restore_control_and_stops_at_ends():
    assert 'data-act="doc-restore"' in HTML
    assert 'data-act="doc-refresh"' in HTML
    assert 'data-act="doc-prev"' in HTML and "上一条笔记" in HTML
    assert 'data-act="doc-next"' in HTML and "下一条笔记" in HTML
    assert 'data-act="doc-back-bottom"' in HTML
    assert "function renderDocPager()" in JS
    assert "prev.disabled" in JS and "next.disabled" in JS
    assert "(index + step + list.length) % list.length" not in JS
    assert ".doc-columns.is-quick-collapsed" in CSS
    assert 'data-act="outline-collapse"' in HTML
    assert 'data-act="outline-restore"' in HTML
    assert 'id="outline-restore-btn"' in HTML
    assert "function setDocOutlineCollapsed(collapsed)" in JS
    assert ".doc-columns.is-outline-collapsed" in CSS


def test_task_and_library_entry_and_manual_refresh_cover_their_data_sets():
    route = JS.split("function go(route, options = {})", 1)[1].split("/* ------------------------- 图六", 1)[0]
    assert 'if (route === "tasks") { renderJobs(); void syncJobsAfterMutation(); }' in route
    assert 'if (route === "library") {' in route and "void syncLibraryData();" in route
    library_sync = JS.split("async function syncLibraryData", 1)[1].split("/* ------------------------- 路由", 1)[0]
    for key in ('refresh("history"', 'refresh("tags"', 'refresh("folders"'):
        assert key in library_sync
    assert 'case "jobs-refresh":' in JS and 'toast("任务列表已刷新")' in JS
    assert 'case "lib-refresh":' in JS and 'toast("知识库已刷新")' in JS
    assert 'id="jobs-refresh-btn"' in HTML and 'id="lib-refresh-btn"' in HTML
    assert 'S.jobsRefreshing' in JS and 'S.libraryRefreshing' in JS


def test_asr_and_environment_checks_render_real_load_and_check_results():
    assert "S.asrLocalModelsError" in JS
    assert 'data-act="asr-retry"' in JS and 'case "asr-retry":' in JS
    assert 'S.environmentCheck.status' in JS
    assert "report?.checks" in JS
    assert 'check.action' in JS
    assert "result.healthy" not in JS
    assert 'data-act="conn-check"' in JS and "环境自检失败" in JS
    assert 'case "doc-refresh":' in JS
    assert "async function refreshCurrentContent()" in JS
