import pytest

from app.adapters.sources.prepared import PreparedSource
from app.adapters.summary.openai_compatible import OpenAICompatibleSummarizer
from app.db.store import SQLiteStore
from app.domain.models import AnalysisSettings, Chunk, ContentKind, SummaryStrength
from app.knowledge.prompts import DEFAULT_SUMMARY_PROMPT, prompt_hash
from app.knowledge.transcript import transcript_from_text
from app.workflows.analyze import AnalysisWorkflow


@pytest.mark.parametrize("api_mode", ["chat_completions", "responses"])
@pytest.mark.parametrize("kind", [ContentKind.ARTICLE, ContentKind.IMAGE, ContentKind.PDF, ContentKind.VIDEO])
def test_summary_request_uses_material_kind_and_frozen_prompt(tmp_path, monkeypatch, kind, api_mode):
    requests = []
    monkeypatch.setattr(OpenAICompatibleSummarizer, "_request", lambda self, payload: (
        requests.append(payload) or {"choices": [{"message": {"content": "今天天气很好。"}}]}
    ))
    monkeypatch.setattr(OpenAICompatibleSummarizer, "generate_introduction", lambda self, **kwargs: "天气记录")
    store = SQLiteStore("sqlite:///:memory:")
    store.set_setting("summary_api_url", "https://example.test/v1")
    store.set_setting("summary_api_mode", api_mode)
    store.set_setting("summary_model", "test")
    workflow = AnalysisWorkflow(store, tmp_path / "archive")
    source = PreparedSource(kind=kind, title="天气", transcript=transcript_from_text("今天天气很好。"),
        content_hash="weather", source_path=None, source_url=None, acquisition_method="test")
    content, run, job = workflow.submit(source, AnalysisSettings(model="test", summary_prompt=DEFAULT_SUMMARY_PROMPT,
        summary_prompt_hash=prompt_hash(DEFAULT_SUMMARY_PROMPT),
        summary_config={"api_url": "https://example.test/v1", "api_mode": api_mode}))
    frozen = run.settings_snapshot["summary_prompt"]
    if kind is ContentKind.VIDEO:
        assert frozen == DEFAULT_SUMMARY_PROMPT
    else:
        assert "总结内容的篇幅不得超过原始文字材料的篇幅" in frozen
        assert "不生成材料中不存在的时间戳或来源位置" not in frozen
        assert run.settings_snapshot["summary_prompt_hash"] == prompt_hash(frozen)
        assert run.prompt_version == "summary-" + prompt_hash(frozen)[:12]
    # Execute the real request builder; the injected provider captures the final payload.
    workflow._summarize_with_ai(content, run, (Chunk(
        1, 0, 12, "今天天气很好。", "hash", 8),), SummaryStrength.STANDARD)
    if api_mode == "responses":
        system, material = requests[0]["instructions"], requests[0]["input"]
    else:
        system, material = [m["content"] for m in requests[0]["messages"]]
    assert system == frozen
    if kind is ContentKind.VIDEO:
        assert "视频标题：天气" in material
        assert "[片段 1 | 00:00:00 - 00:00:12]" in material
    else:
        assert "内容标题：天气" in material
        assert "[段落 1]" in material
        assert "转写" not in material
        assert "00:00" not in material
        assert "视频" not in material
    assert "今天天气很好。" in material
    assert store.get_analysis_run(run.id).settings_snapshot["summary_prompt"] == frozen
    store.engine.dispose()


def test_text_task_preserves_explicit_custom_prompt(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    workflow = AnalysisWorkflow(store, tmp_path / "archive")
    source = PreparedSource(kind=ContentKind.ARTICLE, title="分享", transcript=transcript_from_text("分享一个网站。"),
        content_hash="sharing", source_path=None, source_url=None, acquisition_method="test")
    custom = "用户自定义整理要求"
    _, run, _ = workflow.submit(source, AnalysisSettings(model="test", summary_prompt=custom,
        summary_prompt_hash=prompt_hash(custom), prompt_version="custom-version"))
    assert run.settings_snapshot["summary_prompt"] == custom
    assert run.settings_snapshot["summary_prompt_hash"] == prompt_hash(custom)
    assert run.prompt_version == "custom-version"
    store.engine.dispose()
