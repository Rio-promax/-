from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters.summary.openai_compatible import (
    OpenAICompatibleSummarizer,
    SummaryProviderError,
    SummarySettings,
)
from app.api.main import create_app
from app.domain.models import Chunk, SummaryStrength


FINAL = "# 团队协作\n\n## Context\n\n安排复盘时间。"
DRAFT = (
    "我们需要写中文 Markdown 总结。需要覆盖全部分块。\n\n"
    "# 团队协作\n\n这是第一版。\n\n现在写最终版。\n\n" + FINAL
)


def summarize(adapter):
    return adapter.summarize_chunks(
        (Chunk(1, 0, 5, "团队安排了一次复盘。", "hash", 9),),
        title="协作", strength=SummaryStrength.STANDARD, prompt="输出最终正文。",
    )


@pytest.mark.parametrize(("url", "mode", "model", "expected"), [
    ("https://api.deepseek.com", "responses", "deepseek-flash", {"reasoning": {"effort": "none"}}),
    ("https://api.deepseek.com/v1/chat/completions", None, "deepseek-v4-pro", {"thinking": {"type": "disabled"}}),
    ("https://gateway.example/v1/responses", None, "deepseek-flash", {}),
    ("https://api.deepseek.com.gateway.example/responses", None, "deepseek-flash", {}),
    ("https://api.deepseek.com/responses", None, "deepseek-unknown", {}),
])
def test_summary_uses_thinking_control_for_verified_endpoint_and_model(monkeypatch, url, mode, model, expected):
    adapter = OpenAICompatibleSummarizer(SummarySettings(
        api_url=url, model=model, api_mode=mode, provider="qwen",
    ))
    requests = []

    def respond(payload):
        requests.append(payload)
        if "messages" in payload:
            return {"choices": [{"message": {"content": FINAL}}]}
        return {"output_text": FINAL}

    monkeypatch.setattr(adapter, "_request", respond)
    assert FINAL in summarize(adapter).markdown
    assert len(requests) == 1
    assert {key: val for key, val in requests[0].items() if key in ("reasoning", "thinking")} == expected


def responses_message(text):
    return {"type": "message", "role": "assistant", "content": [
        {"type": "reasoning_text", "text": "独立消息内推理"},
        {"type": "output_text", "text": text},
    ]}


@pytest.mark.parametrize(("mode", "response"), [
    ("responses", {
        "output_text": DRAFT,
        "output": [
            {"type": "reasoning", "content": [{"type": "reasoning_text", "text": DRAFT}]},
            {"type": "function_call", "text": "工具信息"},
            {**responses_message(FINAL), "phase": "final_answer"},
            {**responses_message("仍在组织内容"), "phase": "commentary"},
        ],
    }),
    ("chat_completions", {"choices": [{"message": {
        "reasoning_content": DRAFT,
        "content": [{"type": "reasoning_text", "text": "独立推理"}, {"type": "text", "text": FINAL}],
    }}]}),
])
def test_extracts_final_message_and_ignores_reasoning_fields(monkeypatch, mode, response):
    adapter = OpenAICompatibleSummarizer(SummarySettings(api_url="https://gateway.example", api_mode=mode))
    monkeypatch.setattr(adapter, "_request", lambda payload: response)
    assert summarize(adapter).markdown == "# 内容总结\n\n" + FINAL + "\n"


@pytest.mark.parametrize("response", [
    {"output_text": DRAFT},
    {"output": [{"type": "reasoning", "content": [{"type": "reasoning_text", "text": FINAL}]}], "output_text": FINAL},
    {"output_text": "<think>先分析任务。</think>\n\n" + FINAL},
    {"output_text": "团队进行了复盘。\n\n# 团队协作\n\n草稿。\n\n现在写最终版。\n\n" + FINAL},
    {"status": "incomplete", "output": [responses_message(FINAL)]},
    {"output_text": "用户希望我总结一段关于团队协作的视频。\n\n让我分析一下内容：\n\n" + FINAL},
    {"output_text": "The transcript starts with brief context.\n\nI need to write a summary based on the transcript.\n\n" + FINAL},
    {"output_text": "用户希望我总结一段关于团队协作的视频。\n\n材料只覆盖了部分。我需要明确写出覆盖范围和缺口。\n\n" + FINAL},
])
def test_invalid_body_retries_once_and_only_accepts_clean_retry(monkeypatch, response):
    adapter = OpenAICompatibleSummarizer(SummarySettings(api_url="https://gateway.example/responses"))
    requests = []
    responses = iter([response, {"output": [responses_message(FINAL)]}])

    def respond(payload):
        requests.append(payload)
        return next(responses)

    monkeypatch.setattr(adapter, "_request", respond)
    assert summarize(adapter).markdown == "# 内容总结\n\n" + FINAL + "\n"
    assert len(requests) == 2
    assert DRAFT not in requests[1]["input"]


@pytest.mark.parametrize("body", [
    FINAL + "\n\n## Context\n\n这是另一个场景。\n\n> 现在写最终版。",
    '## Context\n\n作者演示以下提示词。\n\n```text\n<think>这是例子</think>\n我们需要写中文 Markdown 总结。\n```',
    "我们需要写清复盘目标。视频建议先和利益相关者对齐。\n\n## 草稿\n\n草稿用于收集不同意见。",
    "我们需要明确复盘目标。视频中的说明先用中文 Markdown 记录，再开会。",
])
def test_normal_markdown_and_quoted_examples_are_preserved(monkeypatch, body):
    adapter = OpenAICompatibleSummarizer(SummarySettings(api_url="https://gateway.example/responses"))
    monkeypatch.setattr(adapter, "_request", lambda payload: {"output_text": body})
    assert summarize(adapter).markdown == "# 内容总结\n\n" + body + "\n"


def test_transport_failure_uses_existing_error_without_retry(monkeypatch):
    adapter = OpenAICompatibleSummarizer(SummarySettings())
    calls = []

    def fail(payload):
        calls.append(payload)
        raise SummaryProviderError("总结服务请求超时")

    monkeypatch.setattr(adapter, "_request", fail)
    with pytest.raises(SummaryProviderError, match="请求超时"):
        summarize(adapter)
    assert len(calls) == 1


def test_two_draft_responses_fail_before_saving_or_indexing(tmp_path: Path, monkeypatch):
    calls = []

    def respond(_adapter, payload):
        calls.append(payload)
        return {"choices": [{"message": {"content": DRAFT}}]}

    monkeypatch.setattr(OpenAICompatibleSummarizer, "_request", respond)
    app = create_app("sqlite:///:memory:", tmp_path / "knowledge-root")
    client = TestClient(app)
    response = client.post("/api/v1/imports/local", json={"title": "复盘", "text": "团队进行复盘。"})
    assert response.status_code == 201
    created = response.json()
    job = client.get(f"/api/v1/jobs/{created['job']['id']}").json()
    content_id = created["content"]["id"]
    assert len(calls) == 2
    assert job["error_code"] == "summary_generation_failed"
    assert "草稿" in job["error_message"]
    assert app.state.store.get_summary(content_id) is None
    assert app.state.store.list_summary_versions(content_id) == []
    assert client.get(f"/api/v1/contents/{content_id}/result").status_code == 409
    assert not list((tmp_path / "knowledge-root").rglob("index.md"))
    with app.state.store.engine.connect() as connection:
        assert connection.exec_driver_sql(
            "select count(*) from ask_index_chunks where content_id=?", (content_id,)
        ).scalar_one() == 0


def test_resume_does_not_reuse_a_draft_summary_checkpoint(tmp_path: Path):
    workflow = create_app("sqlite:///:memory:", tmp_path / "knowledge-root").state.workflow
    assert workflow._summary_from_dict({"markdown": "# 内容总结\n\n" + DRAFT}) is None
    assert workflow._summary_from_dict({"markdown": FINAL}).markdown == FINAL
