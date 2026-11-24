"""11-22 问答请求生命周期 UI 契约。"""
from pathlib import Path


APP = Path(__file__).resolve().parents[1] / "app"
JS = (APP / "ui" / "app.js").read_text(encoding="utf-8")
HTML = (APP / "ui" / "index.html").read_text(encoding="utf-8")


def _ask_send() -> str:
    return JS.split("async function askSend()", 1)[1].split("\n  /* ------------------------- 图五", 1)[0]


def test_question_stays_in_composer_until_query_is_accepted():
    action = _ask_send()
    assert action.index('await post("/ask/queries"') < action.index('input.value = ""')
    assert 'status: "submitting"' in action
    assert 'submitting: "正在发送"' in JS


def test_accepted_query_is_polled_by_its_query_id_and_session():
    assert "async function watchAskQuery(queryId, sessionId)" in JS
    assert 'api(`/ask/queries/${encodeURIComponent(queryId)}`)' in JS
    assert 'if (S.sessionId === sessionId)' in JS
    assert 'new Set(["completed", "failed", "cancelled", "paused"])' in JS


def test_stop_and_draft_clear_are_separate_controls():
    assert 'data-act="ask-clear"' in HTML and '清空草稿</button>' in HTML
    assert 'data-act="ask-stop"' in HTML and '停止生成</button>' in HTML
    assert 'case "ask-clear":' in JS
    assert 'case "ask-stop":' in JS
    assert 'post(`/ask/queries/${encodeURIComponent(queryId)}/cancel`' in JS


def test_failed_question_can_resume_and_continue_reports_queued_state():
    assert 'data-act="ask-retry"' in JS
    assert 'case "ask-retry":' in JS
    assert 'post(`/ask/queries/${encodeURIComponent(queryId)}/continue`' in JS
    assert "已重新排队" in JS
