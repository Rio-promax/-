import subprocess
import textwrap
from pathlib import Path


UI_JS = Path(__file__).resolve().parents[1] / "app" / "ui" / "app.js"
JS = UI_JS.read_text(encoding="utf-8")


def _run_node(script: str) -> None:
    result = subprocess.run(
        [
            "node",
            "--input-type=commonjs",
            "-e",
            "(async () => {\n" + textwrap.dedent(script) + "\n})().catch((error) => { console.error(error); process.exitCode = 1; });",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _go_function() -> str:
    start = JS.index("function go(route, options = {}) {")
    end = JS.index("function showTip(target)", start)
    return JS[start:end]


def _job_open_case() -> str:
    start = JS.index('case "job-open": {')
    end = JS.index('case "job-pause":', start)
    return JS[start:end]


def test_entering_library_refreshes_history_before_rendering_fresh_entries():
    _run_node(
        f"""
        const assert = require("node:assert/strict");
        const S = {{ route: "tasks", history: [{{ id: "old" }}] }};
        const rendered = [];
        const refreshed = [];
        const window = {{ scrollTo() {{}} }};
        function $$(selector) {{ return []; }}
        function closeSheet() {{}}
        function closePopmenu() {{}}
        function closeRestyle() {{}}
        function stopJobsWatch() {{}}
        function renderLibrary() {{ rendered.push(S.history.map((entry) => entry.id)); }}
        let librarySyncPromise = null;
        function renderLibraryToolbar() {{}}
        function refresh(key) {{
          refreshed.push(key);
          return Promise.resolve().then(() => {{
            if (key === "history") S.history = [{{ id: "fresh" }}];
            return true;
          }});
        }}
        {JS[JS.index("async function syncLibraryData"):JS.index("function go(route, options = {})")]}
        {_go_function()}
        go("library");
        await new Promise((resolve) => setImmediate(resolve));
        assert.deepEqual(refreshed, ["history", "tags", "folders"]);
        assert.deepEqual(rendered.at(-1), ["fresh"]);
        """
    )


def test_job_open_uses_content_id_without_a_history_match():
    _run_node(
        f"""
        const assert = require("node:assert/strict");
        const calls = [];
        const S = {{ jobs: [{{ id: "job_0c248686044c47f18d5f4dd3b1e793eb", content_id: "content_2eebccaef65f491fb2aa120a8b7fbfe0" }}], history: [] }};
        const target = {{ dataset: {{ jobId: S.jobs[0].id }} }};
        function $(selector) {{ return {{scrollTop: 37}}; }}
        function go(route) {{ calls.push(["route", route]); }}
        async function openContent(contentId) {{ calls.push(["content", contentId]); }}
        function toast(message) {{ calls.push(["toast", message]); }}
        function idOf(entry) {{ return entry?.content?.id || entry?.content_id || entry?.id || ""; }}
        async function onAction() {{
          switch ("job-open") {{
            {_job_open_case()}
          }}
        }}
        await onAction();
        assert.equal(S.contentReturn.route, "tasks");
        assert.equal(S.contentReturn.scrollTop, 37);
        assert.deepEqual(calls, [
          ["route", "content"],
          ["content", "content_2eebccaef65f491fb2aa120a8b7fbfe0"],
        ]);
        """
    )


def test_job_open_keeps_history_lookup_for_legacy_jobs_without_content_id():
    _run_node(
        f"""
        const assert = require("node:assert/strict");
        const calls = [];
        const job = {{ id: "legacy-job" }};
        const S = {{ jobs: [job], history: [{{ job: {{ id: job.id }}, content: {{ id: "legacy-content" }} }}] }};
        const target = {{ dataset: {{ jobId: job.id }} }};
        function $(selector) {{ return {{scrollTop: 37}}; }}
        function go(route) {{ calls.push(["route", route]); }}
        async function openContent(contentId) {{ calls.push(["content", contentId]); }}
        function toast(message) {{ calls.push(["toast", message]); }}
        function idOf(entry) {{ return entry?.content?.id || entry?.content_id || entry?.id || ""; }}
        async function onAction() {{
          switch ("job-open") {{
            {_job_open_case()}
          }}
        }}
        await onAction();
        assert.equal(S.contentReturn.route, "tasks");
        assert.equal(S.contentReturn.scrollTop, 37);
        assert.deepEqual(calls, [["route", "content"], ["content", "legacy-content"]]);
        """
    )
