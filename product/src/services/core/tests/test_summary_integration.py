import json
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from app.adapters.sources.prepared import PreparedSource
from app.adapters.summary import openai_compatible
from app.adapters.summary.openai_compatible import (
    OpenAICompatibleSummarizer,
    SummaryProviderError,
    SummarySettings,
    api_key_fingerprint,
    filter_summary_models,
)
from app.api import main as api_main
from app.api.main import create_app
from app.db.store import SQLiteStore
from app.domain.models import (
    AnalysisSettings,
    ContentKind,
    SourcePlatform,
    SummaryStrength,
    Transcript,
    TranscriptSegment,
)
from app.knowledge.prompts import DEFAULT_TEXT_SUMMARY_PROMPT, DEFAULT_INTRODUCTION_PROMPT, DEFAULT_SUMMARY_PROMPT, prompt_hash
from app.knowledge.skills import load_skill_document
from app.workflows import analyze
from app.workflows.analyze import AnalysisWorkflow
from fastapi.testclient import TestClient


def test_default_summary_prompt_does_not_require_fixed_output_sections() -> None:
    assert "## 概览" not in DEFAULT_SUMMARY_PROMPT
    assert "## 关键要点" not in DEFAULT_SUMMARY_PROMPT
    assert "## 分段笔记" not in DEFAULT_SUMMARY_PROMPT
    assert "章节" not in DEFAULT_SUMMARY_PROMPT
    assert "时间戳" not in DEFAULT_SUMMARY_PROMPT
    assert "\n-" not in DEFAULT_SUMMARY_PROMPT
    assert "\n*" not in DEFAULT_SUMMARY_PROMPT


def _patch_summary_connection_test(monkeypatch) -> None:
    class FakeSummarizer:
        def __init__(self, settings) -> None:
            self.settings = settings

        def test_connection(self) -> None:
            return None

    monkeypatch.setattr(api_main, "OpenAICompatibleSummarizer", FakeSummarizer)


def test_summary_settings_expose_prompt_and_skill_without_api_key(
    tmp_path: Path, monkeypatch
) -> None:
    _patch_summary_connection_test(monkeypatch)
    skill_root = tmp_path / "skills"
    skill_path = skill_root / "demo" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("按问题、证据、结论组织总结。", encoding="utf-8")
    client = TestClient(create_app("sqlite:///:memory:", tmp_path / "archive", skill_root))

    response = client.get("/api/v1/settings")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary_prompt"]
    assert payload["summary_prompt_hash"]
    assert payload["summary_skill_options"][0]["path"] == "demo/SKILL.md"
    assert "summary_api_key" not in payload
    assert payload["summary_api_mode"] == "chat_completions"

    validation = client.post(
        "/api/v1/settings/summary/test",
        json={
            "summary_provider": "openai-compatible",
            "summary_api_url": "https://summary.example.test/v1/chat/completions",
            "summary_model": "test-model",
        },
    )
    assert validation.status_code == 200

    saved = client.put(
        "/api/v1/settings",
        json={
            "summary_engine": "openai-compatible",
            "summary_provider": "openai-compatible",
            "summary_api_url": "https://summary.example.test/v1/chat/completions",
            "summary_model": "test-model",
            "summary_prompt": "请覆盖所有分块并输出完整 Markdown。",
            "summary_skill_path": "demo/SKILL.md",
            "summary_validation_token": validation.json()["validation_token"],
        },
    )

    assert saved.status_code == 200
    saved_payload = saved.json()
    assert saved_payload["summary_engine"] == "openai-compatible"
    assert saved_payload["summary_skill_path"] == "demo/SKILL.md"
    assert saved_payload["summary_prompt_version"].startswith("summary-")
    assert saved_payload["summary_api_key_configured"] is False
    assert "summary_api_key" not in saved_payload

    mismatch = client.put(
        "/api/v1/settings",
        json={
            "summary_api_url": "https://summary.example.test/v1/chat/completions",
            "summary_api_mode": "responses",
        },
    )

    assert mismatch.status_code == 422
    assert "不匹配" in mismatch.json()["detail"]


def test_summary_prompt_only_put_isolated_from_external_configuration(
    tmp_path: Path, monkeypatch
) -> None:
    skill_root = tmp_path / "skills"
    skill_path = skill_root / "demo" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("保留现有 Skill。", encoding="utf-8")
    client = TestClient(create_app("sqlite:///:memory:", tmp_path / "archive", skill_root))
    store = client.app.state.store
    store.set_setting("summary_provider", "qwen")
    store.set_setting("summary_api_url", "https://summary.example.test/v1")
    store.set_setting("summary_api_mode", "chat_completions")
    store.set_setting("summary_model", "qwen-plus")
    store.set_setting("summary_api_key", "old-summary-key")
    store.set_setting("summary_prompt", "旧 Prompt")
    store.set_setting("summary_skill_path", "demo/SKILL.md")
    store.set_setting("ai_tag_recommendation_enabled", "true")

    def fail_if_summary_validation_is_requested(*_args, **_kwargs):
        raise AssertionError("Prompt-only update must not consume a summary validation token")

    monkeypatch.setattr(
        api_main,
        "_consume_summary_validation_token",
        fail_if_summary_validation_is_requested,
    )

    response = client.put(
        "/api/v1/settings",
        json={"summary_prompt": "新 Prompt"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary_prompt"] == "新 Prompt"
    assert payload["summary_provider"] == "qwen"
    assert payload["summary_api_url"] == "https://summary.example.test/v1"
    assert payload["summary_api_mode"] == "chat_completions"
    assert payload["summary_model"] == "qwen-plus"
    assert payload["summary_api_key_configured"] is True
    assert payload["summary_skill_path"] == "demo/SKILL.md"
    assert payload["ai_tag_recommendation_enabled"] is True
    assert store.get_setting("summary_api_key") == "old-summary-key"

    reloaded = client.get("/api/v1/settings")
    assert reloaded.status_code == 200
    assert reloaded.json()["summary_prompt"] == "新 Prompt"


def test_summary_connection_uses_explicit_mode_and_model(
    tmp_path: Path, monkeypatch
) -> None:
    captured: dict[str, object] = {}

    class FakeSummarizer:
        def __init__(self, settings) -> None:
            captured["settings"] = settings

        def test_connection(self) -> None:
            return None

    monkeypatch.setattr(api_main, "OpenAICompatibleSummarizer", FakeSummarizer)
    client = TestClient(create_app("sqlite:///:memory:", tmp_path / "archive"))

    response = client.post(
        "/api/v1/settings/summary/test",
        json={
            "summary_api_url": "https://summary.example.test/v1",
            "summary_api_mode": "chat_completions",
            "summary_api_key": "test-secret-key",
            "summary_model": "test-model",
        },
    )

    assert response.status_code == 200
    settings = captured["settings"]
    assert settings.api_url == "https://summary.example.test/v1"
    assert settings.api_mode == "chat_completions"
    assert settings.model == "test-model"
    assert response.json()["validation_token"]


def test_summary_skill_root_can_be_changed(tmp_path: Path) -> None:
    initial_root = tmp_path / "initial-skills"
    selected_root = tmp_path / "selected-skills"
    selected_skill = selected_root / "product" / "SKILL.md"
    selected_skill.parent.mkdir(parents=True)
    selected_skill.write_text("按主题、证据、结论组织。", encoding="utf-8")
    client = TestClient(create_app("sqlite:///:memory:", tmp_path / "archive", initial_root))

    response = client.put(
        "/api/v1/settings",
        json={
            "summary_skills_root": str(selected_root),
            "summary_skill_path": "product/SKILL.md",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary_skills_root"] == str(selected_root.resolve())
    assert payload["summary_skill_path"] == "product/SKILL.md"
    assert payload["summary_skill_options"][0]["path"] == "product/SKILL.md"


def test_external_summary_provider_is_called_and_snapshot_is_archived(
    tmp_path: Path, monkeypatch
) -> None:
    store = SQLiteStore("sqlite:///:memory:")
    store.set_setting("summary_provider", "openai-compatible")
    store.set_setting("summary_api_url", "https://summary.example.test/v1/chat/completions")
    store.set_setting("summary_model", "test-model")
    monkeypatch.setattr(
        store,
        "get_secret_setting",
        lambda _key, *, purpose: "test-secret-key",
    )
    calls: list[tuple[str, object]] = []

    class FakeSummarizer:
        def __init__(self, settings) -> None:
            calls.append(("init", settings.model))
            assert settings.api_key == "test-secret-key"

        def summarize_chunks(self, chunks, *, title, strength, prompt, skill=None, text_material=False):
            calls.append(("summarize", (len(chunks), title, strength, prompt, skill)))
            summary_markdown = (
                "# 内容总结\n\n## 概览\n\n完整覆盖主题。\n\n"
                "## 关键要点\n\n- 核心结论（00:00:00）。\n\n"
                "## 分段笔记\n\n### 片段 1\n\n完整内容。\n"
            )
            return SimpleNamespace(
                markdown=summary_markdown,
                overview="完整覆盖主题。",
                key_points=("核心结论（00:00:00）。",),
            )

        def generate_introduction(self, *, title, summary_markdown, prompt=DEFAULT_INTRODUCTION_PROMPT):
            calls.append(("introduction", (title, summary_markdown, prompt)))
            return "主题与核心结论"

    monkeypatch.setattr(analyze, "OpenAICompatibleSummarizer", FakeSummarizer)
    transcript = Transcript(
        "zh-CN",
        "subtitle",
        "test",
        (TranscriptSegment(0.0, 5.0, "第一段主题和结论。"),),
    )
    source = PreparedSource(
        kind=ContentKind.ARTICLE,
        title="外部总结测试",
        transcript=transcript,
        content_hash="summary-test",
        source_path=None,
        source_url="https://example.test/summary",
        acquisition_method="test",
        platform=SourcePlatform.WEB,
    )
    prompt = DEFAULT_SUMMARY_PROMPT
    skills_root = tmp_path / "skills"
    skill_path = skills_root / "demo" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("按问题、证据、结论组织。", encoding="utf-8")
    skill = load_skill_document(skills_root, "demo/SKILL.md")
    workflow = AnalysisWorkflow(store, tmp_path / "archive", skills_root=skills_root)
    content, run, job = workflow.submit(
        source,
        AnalysisSettings(
            model="test-model",
            strength=SummaryStrength.STANDARD,
            prompt_version="summary-test",
            summary_engine="openai-compatible",
            summary_provider="openai-compatible",
            summary_config={
                "api_url": "https://summary.example.test/v1/chat/completions",
                "model": "test-model",
                "timeout_seconds": 30,
            },
            summary_prompt=prompt,
            summary_prompt_hash=prompt_hash(prompt),
            summary_skill=skill.metadata(),
        ),
    )

    workflow.run(job.id, source.transcript)

    completed = store.get_job(job.id)
    assert completed.state.value == "completed"
    assert calls[0] == ("init", "test-model")
    assert calls[1][0] == "summarize"
    assert calls[1][1][-1] == "按问题、证据、结论组织。"
    assert any(call[0] == "introduction" for call in calls)
    assert store.get_content(content.id).introduction == "主题与核心结论"
    record = Path(completed.metadata["archive_path"]) / "record.json"
    record_text = record.read_text(encoding="utf-8")
    assert "openai-compatible" in record_text
    assert "summary-test" in record_text
    assert "test-secret-key" not in record_text
    assert run.settings_snapshot["summary_prompt_hash"] == prompt_hash(DEFAULT_TEXT_SUMMARY_PROMPT)


def test_summary_strength_and_material_level_matrix_is_persisted_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SQLiteStore("sqlite:///:memory:")
    api_url = "https://summary.example.test/v1/chat/completions"
    store.set_setting("summary_api_url", api_url)
    store.set_setting("summary_model", "test-model")
    store.set_setting("summary_provider", "openai-compatible")
    calls: list[tuple[SummaryStrength, str]] = []

    class FakeSummarizer:
        def __init__(self, _settings) -> None:
            pass

        def summarize_chunks(self, chunks, *, title, strength, prompt, skill=None, text_material=False):
            calls.append((strength, prompt))
            text = "\n".join(chunk.text for chunk in chunks)
            return SimpleNamespace(markdown=f"# {title}\n\n{text}\n", overview=text, key_points=(text,))

        def generate_introduction(self, *, title, summary_markdown, prompt=DEFAULT_INTRODUCTION_PROMPT):
            return "矩阵测试"

    monkeypatch.setattr(analyze, "OpenAICompatibleSummarizer", FakeSummarizer)
    workflow = AnalysisWorkflow(store, tmp_path / "archive")
    expected_calls = []
    try:
        for strength in (SummaryStrength.QUICK, SummaryStrength.STANDARD, SummaryStrength.DEEP):
            for material_level in ("M0", "M1", "M2"):
                segments = () if material_level == "M0" else (
                    TranscriptSegment(0, 5, f"{strength.value} {material_level} 的材料证据。"),
                )
                transcript = Transcript(
                    "zh-CN", "subtitle", "matrix", segments,
                    source_coverage_complete=material_level == "M2",
                )
                source = PreparedSource(
                    kind=ContentKind.ARTICLE,
                    title=f"{strength.value}-{material_level}",
                    transcript=transcript,
                    content_hash=f"matrix-{strength.value}-{material_level}",
                    source_path=None,
                    source_url=f"https://example.test/{strength.value}/{material_level}",
                    acquisition_method="test",
                    platform=SourcePlatform.WEB,
                )
                content, _run, job = workflow.submit(
                    source,
                    AnalysisSettings(
                        model="test-model", strength=strength,
                        summary_config={"api_url": api_url, "model": "test-model", "timeout_seconds": 30},
                        summary_prompt=DEFAULT_SUMMARY_PROMPT,
                        summary_prompt_hash=prompt_hash(DEFAULT_SUMMARY_PROMPT),
                    ),
                )
                workflow.run(job.id, transcript)
                completed = store.get_job(job.id)
                assert completed.state.value == "completed"
                record = json.loads((Path(completed.metadata["archive_path"]) / "record.json").read_text("utf-8"))
                assert record["material_level"] == material_level
                versions = store.list_summary_versions(content.id)
                if material_level == "M0":
                    assert not versions
                    # 11-23：M0 不再丢弃正文，落库的是可解释的空态说明。
                    assert store.get_summary(content.id) == (
                        "# 来源预览\n\n## 材料\n\n尚未取得可用正文材料。"
                    )
                    assert record.get("summary_strength") is None
                    assert len(calls) == len(expected_calls)
                else:
                    assert len(versions) == 1
                    assert versions[0].summary_strength == strength.value
                    assert versions[0].material_level == material_level
                    assert record["summary_strength"] == strength.value
                    assert ("本次材料等级为 M1" in calls[-1][1]) is (material_level == "M1")
                    assert calls[-1][0] is strength
                    if material_level == "M2":
                        assert versions[0].expected_source_refs == versions[0].processed_source_refs
                    else:
                        assert versions[0].expected_source_refs is None
                    expected_calls.append((strength, material_level))
    finally:
        workflow.close()

    assert len(calls) == 6
    assert len(expected_calls) == 6


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def test_openai_compatible_introduction_uses_saved_summary_and_normalizes_output(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request, *, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _FakeResponse(
            {"choices": [{"message": {"content": "简介：研究视频主题与核心结论"}}]}
        )

    monkeypatch.setattr(openai_compatible, "urlopen", fake_urlopen)
    summarizer = OpenAICompatibleSummarizer(
        SummarySettings(
            api_url="https://example.test/v1/chat/completions",
            api_key="secret-key",
            model="summary-model",
            timeout_seconds=45,
        )
    )

    result = summarizer.generate_introduction(
        title="标题仅用于消歧",
        summary_markdown="# 正文总结\n\n视频讨论研究方法与核心结论。",
    )

    assert result == "研究视频主题与核心结论"
    body = captured["body"]
    assert body["messages"][0]["content"] == DEFAULT_INTRODUCTION_PROMPT
    assert "标题（仅用于指代消歧）：标题仅用于消歧" in body["messages"][1]["content"]
    assert "<summary>" in body["messages"][1]["content"]
    assert "正文总结" in body["messages"][1]["content"]
    assert captured["timeout"] == 45


def test_introduction_normalizer_rejects_overlong_or_empty_output() -> None:
    assert openai_compatible._normalize_introduction("  `简介：主题识别`  ") == "主题识别"
    with pytest.raises(SummaryProviderError):
        openai_compatible._normalize_introduction("")
    with pytest.raises(SummaryProviderError):
        openai_compatible._normalize_introduction("一" * 31)


def test_introduction_backfill_api_preserves_nonempty_skips_missing_summary_and_retries_failures(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[str] = []
    fail_titles = {"补齐失败"}

    class FakeBackfillSummarizer:
        def __init__(self, _settings) -> None:
            pass

        def generate_introduction(self, *, title, summary_markdown, prompt=DEFAULT_INTRODUCTION_PROMPT):
            calls.append(title)
            if title in fail_titles:
                raise SummaryProviderError("fake introduction failure")
            assert summary_markdown.strip()
            return f"识别：{title}"[:30]

    monkeypatch.setattr(api_main, "OpenAICompatibleSummarizer", FakeBackfillSummarizer)
    client = TestClient(create_app("sqlite:///:memory:", tmp_path / "archive"))
    store = client.app.state.store

    def archived_content(title: str, *, introduction: str = "", summary: str | None = None) -> str:
        response = client.post(
            "/api/v1/contents",
            json={
                "kind": "article",
                "title": title,
                "platform": "web",
                "canonical_url": f"https://example.test/{title}",
                "introduction": introduction,
            },
        )
        assert response.status_code == 201
        content_id = response.json()["id"]
        run_response = client.post(
            f"/api/v1/contents/{content_id}/analysis-runs",
            json={"model": "test-model"},
        )
        assert run_response.status_code == 201
        job = store.get_job(run_response.json()["job"]["id"])
        from app.domain.jobs import JobState

        for target in (
            JobState.ACQUIRING,
            JobState.EXTRACTING,
            JobState.TRANSCRIBING,
            JobState.CHUNKING,
            JobState.SUMMARIZING,
            JobState.ARCHIVING,
            JobState.INDEXING,
            JobState.COMPLETED,
        ):
            job.transition(target)
        store.save_job(job)
        if summary is not None:
            store.upsert_summary(content_id, summary, transcript_text="原始材料")
        return content_id

    eligible_id = archived_content("待补齐", summary="# 已保存总结\n\n主题内容")
    preserved_id = archived_content(
        "人工简介", introduction="人工填写的简介", summary="# 已保存总结"
    )
    no_summary_id = archived_content("没有总结")
    failed_id = archived_content("补齐失败", summary="# 另一个总结")

    preview = client.get("/api/v1/content-introductions/backfill/preview")
    assert preview.status_code == 200
    assert preview.json()["eligible_count"] == 2
    assert preview.json()["no_summary_count"] == 1
    assert set(preview.json()["content_ids"]) == {eligible_id, failed_id}

    started = client.post(
        "/api/v1/content-introductions/backfill",
        json={"content_ids": [eligible_id, preserved_id, no_summary_id, failed_id]},
    )
    assert started.status_code == 202
    run_id = started.json()["run_id"]
    record = None
    for _ in range(50):
        record = client.get(f"/api/v1/content-introductions/backfill/{run_id}").json()
        if record["status"] == "completed":
            break
        time.sleep(0.01)
    assert record["status"] == "completed"
    assert record["succeeded"] == 1
    assert record["skipped"] == 1
    assert record["failed"] == 1
    assert record["failed_ids"] == [failed_id]
    assert store.get_content(eligible_id).introduction == "识别：待补齐"
    assert store.get_content(preserved_id).introduction == "人工填写的简介"
    assert store.get_content(no_summary_id).introduction == ""

    fail_titles.clear()
    retry = client.post(
        "/api/v1/content-introductions/backfill",
        json={"content_ids": record["failed_ids"]},
    )
    assert retry.status_code == 202
    retry_id = retry.json()["run_id"]
    retry_record = None
    for _ in range(50):
        retry_record = client.get(f"/api/v1/content-introductions/backfill/{retry_id}").json()
        if retry_record["status"] == "completed":
            break
        time.sleep(0.01)
    assert retry_record["succeeded"] == 1
    assert retry_record["failed"] == 0
    assert store.get_content(failed_id).introduction == "识别：补齐失败"
    assert calls.count("人工简介") == 0


def test_openai_compatible_chat_request_carries_timestamps_and_skill(monkeypatch) -> None:
    captured: dict[str, object] = {}
    markdown = (
        "# 内容总结\n\n## 概览\n\n覆盖主题。\n\n"
        "## 关键要点\n\n- 关键结论。\n\n## 分段笔记\n\n### 片段 1\n\n内容。"
    )

    def fake_urlopen(request, *, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["authorization"] = request.headers["Authorization"]
        captured["timeout"] = timeout
        response_markdown = "```markdown\n" + markdown + "\n```"
        return _FakeResponse({"choices": [{"message": {"content": response_markdown}}]})

    monkeypatch.setattr(openai_compatible, "urlopen", fake_urlopen)
    summarizer = OpenAICompatibleSummarizer(
        SummarySettings(
            api_url="https://example.test/v1/chat/completions",
            api_key="secret-key",
            model="summary-model",
            timeout_seconds=45,
        )
    )
    from app.domain.models import Chunk

    chunk = Chunk(1, 0.0, 5.0, "第一段内容。", "hash", 6)
    result = summarizer.summarize_chunks(
        (chunk,),
        title="测试视频",
        strength=SummaryStrength.STANDARD,
        prompt="请输出完整总结。",
        skill="按问题、证据、结论组织。",
    )

    body = captured["body"]
    assert body["model"] == "summary-model"
    message_content = body["messages"][1]["content"]
    assert "[片段 1 | 00:00:00 - 00:00:05]" in message_content
    assert "<skill>" in message_content
    assert captured["authorization"] == "Bearer secret-key"
    assert captured["timeout"] == 45
    assert result.overview == "覆盖主题。"


def test_openai_compatible_base_url_is_normalized_for_chat_request(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request, *, timeout):
        captured["url"] = request.full_url
        return _FakeResponse({"choices": [{"message": {"content": "自由格式总结"}}]})

    monkeypatch.setattr(openai_compatible, "urlopen", fake_urlopen)
    summarizer = OpenAICompatibleSummarizer(
        SummarySettings(
            api_url="https://example.test/v1",
            api_key="secret-key",
            model="summary-model",
        )
    )

    from app.domain.models import Chunk

    summarizer.summarize_chunks(
        (Chunk(1, 0.0, 5.0, "第一段内容。", "hash", 6),),
        title="测试视频",
        strength=SummaryStrength.STANDARD,
        prompt="请输出完整总结。",
    )

    assert captured["url"] == "https://example.test/v1/chat/completions"


def test_openai_compatible_base_url_is_normalized_for_responses_request(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request, *, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse({"output_text": "自由格式总结"})

    monkeypatch.setattr(openai_compatible, "urlopen", fake_urlopen)
    summarizer = OpenAICompatibleSummarizer(
        SummarySettings(
            api_url="https://example.test/v1",
            api_key="secret-key",
            model="responses-model",
            api_mode="responses",
        )
    )

    from app.domain.models import Chunk

    summarizer.summarize_chunks(
        (Chunk(1, 0.0, 5.0, "第一段内容。", "hash", 6),),
        title="测试视频",
        strength=SummaryStrength.STANDARD,
        prompt="请输出完整总结。",
    )

    assert captured["url"] == "https://example.test/v1/responses"
    assert captured["body"]["instructions"] == "请输出完整总结。"


def test_summary_workflow_rejects_stale_provider_snapshot(tmp_path: Path, monkeypatch) -> None:
    store = SQLiteStore("sqlite:///:memory:")
    store.set_setting("summary_provider", "qwen")
    store.set_setting("summary_api_url", "https://summary.example.test/compatible-mode/v1")
    store.set_setting("summary_model", "qwen3.7-flash")
    store.set_setting("summary_api_key", "current-secret-key")
    calls: list[str] = []

    class FakeSummarizer:
        def __init__(self, _settings) -> None:
            calls.append("init")

    monkeypatch.setattr(analyze, "OpenAICompatibleSummarizer", FakeSummarizer)
    transcript = Transcript(
        "zh-CN",
        "subtitle",
        "test",
        (TranscriptSegment(0.0, 5.0, "第一段主题和结论。"),),
    )
    source = PreparedSource(
        kind=ContentKind.ARTICLE,
        title="旧配置测试",
        transcript=transcript,
        content_hash="stale-summary-test",
        source_path=None,
        source_url="https://example.test/stale-summary",
        acquisition_method="test",
        platform=SourcePlatform.WEB,
    )
    workflow = AnalysisWorkflow(store, tmp_path / "archive")
    _, _, job = workflow.submit(
        source,
        AnalysisSettings(
            model="deepseek-v4-flash",
            summary_provider="deepseek",
            summary_config={
                "api_url": "https://api.deepseek.com/chat/completions",
                "model": "deepseek-v4-flash",
                "timeout_seconds": 30,
                "api_key_fingerprint": api_key_fingerprint("old-secret-key"),
            },
        ),
    )

    workflow.run(job.id, source.transcript)

    failed = store.get_job(job.id)
    assert failed.state.value == "failed"
    assert "旧的供应商、地址或模型" in (failed.error_message or "")
    assert calls == []


def test_summary_parser_accepts_freeform_markdown_without_required_sections() -> None:
    result = openai_compatible._parse_summary("模型返回的自由格式总结。")

    assert result.markdown == "# 内容总结\n\n模型返回的自由格式总结。\n"
    assert result.overview == ""
    assert result.key_points == ()


def test_openai_compatible_responses_request_is_supported(monkeypatch) -> None:
    captured: dict[str, object] = {}
    markdown = (
        "# 内容总结\n\n## 概览\n\n覆盖主题。\n\n"
        "## 关键要点\n\n- 关键结论。\n\n## 分段笔记\n\n### 片段 1\n\n内容。"
    )

    def fake_urlopen(request, *, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse({"output_text": markdown})

    monkeypatch.setattr(openai_compatible, "urlopen", fake_urlopen)
    summarizer = OpenAICompatibleSummarizer(
        SummarySettings(
            api_url="https://example.test/v1/responses",
            api_key="secret-key",
            model="responses-model",
        )
    )
    from app.domain.models import Chunk

    chunk = Chunk(1, 0.0, 5.0, "第一段内容。", "hash", 6)
    summarizer.summarize_chunks(
        (chunk,),
        title="测试视频",
        strength=SummaryStrength.QUICK,
        prompt="请输出完整总结。",
    )

    body = captured["body"]
    assert body["model"] == "responses-model"
    assert body["instructions"] == "请输出完整总结。"
    assert "视频标题：测试视频" in body["input"]


@pytest.mark.parametrize(
    ("provider", "model", "expected_reasoning", "expected_temperature"),
    [
        ("qwen", "qwen3.7-flash", {"effort": "none"}, 0),
        ("qwen", "qwen2.5-72b-instruct", None, None),
        ("openai-compatible", "gpt-4o-mini", None, None),
    ],
)
def test_responses_json_request_applies_supported_qwen37_params_only_to_qwen37(
    monkeypatch, provider: str, model: str, expected_reasoning: dict[str, str] | None,
    expected_temperature: int | None,
) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request, *, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse({"output_text": '{"ok":true}', "usage": {}})

    monkeypatch.setattr(openai_compatible, "urlopen", fake_urlopen)
    summarizer = OpenAICompatibleSummarizer(
        SummarySettings(
            api_url="https://example.test/compatible-mode/v1/responses",
            api_key="secret-key",
            model=model,
            provider=provider,
            api_mode="responses",
        )
    )
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["ok"],
        "properties": {"ok": {"type": "boolean"}},
    }

    result, _meta = summarizer.complete_json(
        "连接测试，只返回 ok=true。", schema, timeout=7, max_output_tokens=32
    )

    assert result == {"ok": True}
    if expected_reasoning is None:
        assert "reasoning" not in captured["body"]
    else:
        assert captured["body"]["reasoning"] == expected_reasoning
    if expected_temperature is None:
        assert "temperature" not in captured["body"]
    else:
        assert captured["body"]["temperature"] == expected_temperature


def test_openai_compatible_model_discovery_uses_models_endpoint(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request, *, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["authorization"] = request.headers["Authorization"]
        captured["timeout"] = timeout
        return _FakeResponse(
            {
                "data": [
                    {"id": "gpt-4o-mini"},
                    {"model": "custom-model"},
                    {"id": "gpt-4o-mini"},
                    "string-model",
                ]
            }
        )

    monkeypatch.setattr(openai_compatible, "urlopen", fake_urlopen)
    summarizer = OpenAICompatibleSummarizer(
        SummarySettings(
            api_url="https://example.test/v1/chat/completions",
            api_key="secret-key",
            timeout_seconds=17,
        )
    )

    models = summarizer.list_models()

    assert models == ("gpt-4o-mini", "custom-model", "string-model")
    assert captured == {
        "url": "https://example.test/v1/models",
        "method": "GET",
        "authorization": "Bearer secret-key",
        "timeout": 17,
    }


def test_openai_compatible_model_discovery_reports_invalid_endpoint() -> None:
    summarizer = OpenAICompatibleSummarizer(
        SummarySettings(api_url="not-a-url", api_key="secret-key")
    )

    with pytest.raises(SummaryProviderError, match="完整的 http 或 https"):
        summarizer.list_models()


def test_filter_summary_models_orders_brand_and_excludes_non_text_capabilities() -> None:
    entries = [
        {"id": "other-text", "owned_by": "other"},
        {"id": "qwen-plus", "owned_by": "qwen"},
        {"id": "text-embedding-v4", "owned_by": "qwen"},
        {"id": "whisper-1", "task": "automatic-speech-recognition"},
        {"id": "tts-1", "task": "text-to-speech"},
        {"id": "bge-reranker-v2", "type": "rerank"},
        {"id": "gpt-image-1", "task": "image_generation"},
        {
            "id": "qwen-turbo",
            "owned_by": "qwen",
            "capabilities": {"text_generation": True, "embedding": False},
        },
        {"id": "qwen-max", "owned_by": "qwen"},
        {"id": "other-text", "owned_by": "other"},
    ]

    assert filter_summary_models(entries, "qwen") == (
        "qwen-plus",
        "qwen-turbo",
        "qwen-max",
        "other-text",
    )


def test_unconfigured_settings_do_not_inject_summary_model_or_url(tmp_path: Path) -> None:
    client = TestClient(create_app("sqlite:///:memory:", tmp_path / "archive"))

    payload = client.get("/api/v1/settings").json()

    assert payload["summary_configured"] is False
    assert payload["summary_model"] is None
    assert payload["summary_api_url"] is None


def test_model_discovery_carries_provider_and_orders_brand_before_other_text_models(
    monkeypatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request, *, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.headers["Authorization"]
        captured["timeout"] = timeout
        return _FakeResponse(
            {
                "data": [
                    {"id": "qwen-plus", "owned_by": "qwen"},
                    {"id": "gpt-5", "owned_by": "openai"},
                    {"id": "text-embedding-v4", "owned_by": "qwen"},
                    {"id": "qwen-plus", "owned_by": "qwen"},
                ]
            }
        )

    monkeypatch.setattr(openai_compatible, "urlopen", fake_urlopen)
    client = TestClient(create_app("sqlite:///:memory:", tmp_path / "archive"))

    response = client.post(
        "/api/v1/settings/summary/models",
        json={
            "summary_provider": "qwen",
            "summary_api_url": "https://dashscope.example.test/compatible-mode/v1",
            "summary_api_key": "test-secret-key",
        },
    )

    assert response.status_code == 200
    assert response.json()["models"] == ["qwen-plus", "gpt-5"]
    assert response.json()["models_supported"] is True
    assert captured == {
        "url": "https://dashscope.example.test/compatible-mode/v1/models",
        "authorization": "Bearer test-secret-key",
        "timeout": 120,
    }


def test_model_discovery_allows_manual_model_when_models_endpoint_is_unsupported(
    monkeypatch, tmp_path: Path
) -> None:
    def fake_urlopen(request, *, timeout):
        raise HTTPError(request.full_url, 404, "not found", {}, None)

    monkeypatch.setattr(openai_compatible, "urlopen", fake_urlopen)
    client = TestClient(create_app("sqlite:///:memory:", tmp_path / "archive"))

    response = client.post(
        "/api/v1/settings/summary/models",
        json={
            "summary_provider": "grok",
            "summary_api_url": "https://xai.example.test/v1",
            "summary_api_key": "test-secret-key",
        },
    )

    assert response.status_code == 200
    assert response.json()["models"] == []
    assert response.json()["models_supported"] is False
    assert "手动填写模型 ID" in response.json()["message"]


def test_saved_key_is_not_reused_after_summary_provider_or_url_changes(tmp_path: Path) -> None:
    client = TestClient(create_app("sqlite:///:memory:", tmp_path / "archive"))
    store = client.app.state.store
    store.set_setting("summary_provider", "qwen")
    store.set_setting("summary_api_url", "https://dashscope.example.test/compatible-mode/v1")
    store.set_setting("summary_model", "qwen-plus")
    store.set_setting("summary_api_key", "old-key")

    response = client.post(
        "/api/v1/settings/summary/models",
        json={
            "summary_provider": "grok",
            "summary_api_url": "https://xai.example.test/v1",
        },
    )

    assert response.status_code == 422
    assert "API Key" in response.json()["detail"]


def test_summary_put_requires_validation_token_and_preserves_old_configuration(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app("sqlite:///:memory:", tmp_path / "archive"))
    store = client.app.state.store
    store.set_setting("summary_provider", "qwen")
    store.set_setting("summary_api_url", "https://dashscope.example.test/compatible-mode/v1")
    store.set_setting("summary_model", "qwen-plus")
    store.set_setting("summary_api_key", "old-key")

    response = client.put(
        "/api/v1/settings",
        json={
            "summary_provider": "qwen",
            "summary_api_url": "https://dashscope.example.test/compatible-mode/v1",
            "summary_model": "definitely-not-a-model",
            "summary_api_key": "new-key",
        },
    )

    assert response.status_code == 422
    assert "验证" in response.json()["detail"]
    assert store.get_setting("summary_provider") == "qwen"
    assert store.get_setting("summary_api_url") == "https://dashscope.example.test/compatible-mode/v1"
    assert store.get_setting("summary_model") == "qwen-plus"
    assert store.get_setting("summary_api_key") == "old-key"


def test_summary_key_only_put_requires_validation_token(tmp_path: Path) -> None:
    client = TestClient(create_app("sqlite:///:memory:", tmp_path / "archive"))
    store = client.app.state.store
    store.set_setting("summary_provider", "qwen")
    store.set_setting("summary_api_url", "https://dashscope.example.test/compatible-mode/v1")
    store.set_setting("summary_model", "qwen-plus")
    store.set_setting("summary_api_key", "old-key")

    response = client.put(
        "/api/v1/settings",
        json={"summary_api_key": "new-key-without-test"},
    )

    assert response.status_code == 422
    assert "验证" in response.json()["detail"]
    assert store.get_setting("summary_api_key") == "old-key"


def test_summary_key_only_put_rejects_mismatched_token(
    tmp_path: Path, monkeypatch
) -> None:
    _patch_summary_connection_test(monkeypatch)
    from app.db import store as store_module

    monkeypatch.setattr(
        store_module,
        "protect_secret",
        lambda value, *, purpose: "protected:" + value,
    )
    client = TestClient(create_app("sqlite:///:memory:", tmp_path / "archive"))
    store = client.app.state.store
    store.set_setting("summary_provider", "qwen")
    store.set_setting("summary_api_url", "https://dashscope.example.test/compatible-mode/v1")
    store.set_setting("summary_api_mode", "chat_completions")
    store.set_setting("summary_model", "qwen-plus")
    store.set_setting("summary_api_key", "old-key")

    validation = client.post(
        "/api/v1/settings/summary/test",
        json={
            "summary_provider": "qwen",
            "summary_api_url": "https://dashscope.example.test/compatible-mode/v1",
            "summary_api_mode": "chat_completions",
            "summary_model": "qwen-plus",
            "summary_api_key": "new-key",
        },
    )
    assert validation.status_code == 200

    response = client.put(
        "/api/v1/settings",
        json={
            "summary_api_key": "different-key",
            "summary_validation_token": validation.json()["validation_token"],
        },
    )

    assert response.status_code == 422
    assert "不匹配" in response.json()["detail"]
    assert store.get_setting("summary_api_key") == "old-key"


def test_summary_key_only_put_saves_after_matching_validation(
    tmp_path: Path, monkeypatch
) -> None:
    _patch_summary_connection_test(monkeypatch)
    from app.db import store as store_module

    monkeypatch.setattr(
        store_module,
        "protect_secret",
        lambda value, *, purpose: "protected:" + value,
    )
    client = TestClient(create_app("sqlite:///:memory:", tmp_path / "archive"))
    store = client.app.state.store
    store.set_setting("summary_provider", "qwen")
    store.set_setting("summary_api_url", "https://dashscope.example.test/compatible-mode/v1")
    store.set_setting("summary_api_mode", "chat_completions")
    store.set_setting("summary_model", "qwen-plus")
    store.set_setting("summary_api_key", "old-key")

    validation = client.post(
        "/api/v1/settings/summary/test",
        json={
            "summary_provider": "qwen",
            "summary_api_url": "https://dashscope.example.test/compatible-mode/v1",
            "summary_api_mode": "chat_completions",
            "summary_model": "qwen-plus",
            "summary_api_key": "new-key",
        },
    )
    assert validation.status_code == 200

    response = client.put(
        "/api/v1/settings",
        json={
            "summary_api_key": "new-key",
            "summary_validation_token": validation.json()["validation_token"],
        },
    )

    assert response.status_code == 200
    assert store.get_setting("summary_api_key") == "protected:new-key"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("summary_provider", "grok"),
        ("summary_api_url", "https://other.example.test/v1"),
        ("summary_api_mode", "responses"),
        ("summary_model", "qwen-max"),
        ("summary_api_key", "different-key"),
    ],
)
def test_summary_validation_token_is_bound_to_every_summary_target_field(
    field: str,
    value: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    _patch_summary_connection_test(monkeypatch)
    client = TestClient(create_app("sqlite:///:memory:", tmp_path / "archive"))
    test_payload = {
        "summary_provider": "qwen",
        "summary_api_url": "https://dashscope.example.test/compatible-mode/v1",
        "summary_api_mode": "chat_completions",
        "summary_model": "qwen-plus",
        "summary_api_key": "test-secret-key",
    }
    validation = client.post("/api/v1/settings/summary/test", json=test_payload)
    assert validation.status_code == 200

    save_payload = dict(test_payload)
    save_payload["summary_validation_token"] = validation.json()["validation_token"]
    save_payload[field] = value
    response = client.put("/api/v1/settings", json=save_payload)

    assert response.status_code == 422
    assert "不匹配" in response.json()["detail"]


def test_settings_update_requires_new_key_for_changed_summary_target(tmp_path: Path) -> None:
    client = TestClient(create_app("sqlite:///:memory:", tmp_path / "archive"))
    store = client.app.state.store
    store.set_setting("summary_provider", "qwen")
    store.set_setting("summary_api_url", "https://dashscope.example.test/compatible-mode/v1")
    store.set_setting("summary_model", "qwen-plus")
    store.set_setting("summary_api_key", "old-key")

    response = client.put(
        "/api/v1/settings",
        json={
            "summary_provider": "grok",
            "summary_api_url": "https://xai.example.test/v1",
            "summary_model": "grok-4",
        },
    )

    assert response.status_code == 422
    assert "重新填写 API Key" in response.json()["detail"]
    assert store.get_setting("summary_provider") == "qwen"


def test_summary_key_protection_failure_does_not_partially_update_settings(
    monkeypatch, tmp_path: Path
) -> None:
    from app.db import store as store_module
    from app.platforms.secrets import SecretStorageError

    client = TestClient(create_app("sqlite:///:memory:", tmp_path / "archive"))
    store = client.app.state.store
    store.set_setting("summary_provider", "qwen")
    store.set_setting("summary_api_url", "https://old.example.test/v1")
    store.set_setting("summary_api_mode", "chat_completions")
    store.set_setting("summary_model", "old-model")
    store.set_setting("summary_api_key", "old-key")

    def fail_protection(value: str, *, purpose: str) -> str:
        raise SecretStorageError("protection failed")

    monkeypatch.setattr(store_module, "protect_secret", fail_protection)
    response = client.put(
        "/api/v1/settings",
        json={
            "summary_provider": "grok",
            "summary_api_url": "https://new.example.test/v1",
            "summary_api_mode": "chat_completions",
            "summary_model": "grok-4",
            "summary_api_key": "new-key",
        },
    )

    assert response.status_code == 422
    assert store.get_setting("summary_provider") == "qwen"
    assert store.get_setting("summary_api_url") == "https://old.example.test/v1"
    assert store.get_setting("summary_api_mode") == "chat_completions"
    assert store.get_setting("summary_model") == "old-model"
    assert store.get_setting("summary_api_key") == "old-key"


def test_summary_settings_are_written_together(tmp_path: Path, monkeypatch) -> None:
    from app.db import store as store_module

    _patch_summary_connection_test(monkeypatch)
    monkeypatch.setattr(
        store_module,
        "protect_secret",
        lambda value, *, purpose: "protected:" + value,
    )
    client = TestClient(create_app("sqlite:///:memory:", tmp_path / "archive"))

    validation = client.post(
        "/api/v1/settings/summary/test",
        json={
            "summary_provider": "glm",
            "summary_api_url": "https://open.bigmodel.example.test/api/paas/v4",
            "summary_api_mode": "chat_completions",
            "summary_model": "glm-5",
            "summary_api_key": "new-key",
        },
    )
    assert validation.status_code == 200

    response = client.put(
        "/api/v1/settings",
        json={
            "summary_provider": "glm",
            "summary_api_url": "https://open.bigmodel.example.test/api/paas/v4",
            "summary_api_mode": "chat_completions",
            "summary_model": "glm-5",
            "summary_api_key": "new-key",
            "summary_validation_token": validation.json()["validation_token"],
        },
    )

    assert response.status_code == 200
    store = client.app.state.store
    assert store.get_setting("summary_provider") == "glm"
    assert store.get_setting("summary_api_url") == "https://open.bigmodel.example.test/api/paas/v4"
    assert store.get_setting("summary_model") == "glm-5"
    assert store.get_setting("summary_api_key") == "protected:new-key"

    replay = client.put(
        "/api/v1/settings",
        json={
            "summary_provider": "glm",
            "summary_api_url": "https://open.bigmodel.example.test/api/paas/v4",
            "summary_api_mode": "chat_completions",
            "summary_model": "glm-5",
            "summary_api_key": "new-key",
            "summary_validation_token": validation.json()["validation_token"],
        },
    )
    assert replay.status_code == 422
    assert "凭证" in replay.json()["detail"]


def test_legacy_summary_provider_values_are_accepted_without_migration(tmp_path: Path) -> None:
    client = TestClient(create_app("sqlite:///:memory:", tmp_path / "archive"))
    store = client.app.state.store
    store.set_setting("summary_provider", "tongyi")
    store.set_setting("summary_api_url", "https://dashscope.example.test/compatible-mode/v1")
    store.set_setting("summary_model", "qwen-plus")

    assert client.get("/api/v1/settings").json()["summary_provider"] == "tongyi"
    assert store.get_setting("summary_provider") == "tongyi"


def test_summary_ui_auto_discovers_models_and_validates_before_saving(tmp_path: Path) -> None:
    client = TestClient(create_app("sqlite:///:memory:", tmp_path / "archive"))
    page = client.get("/").text
    script = client.get("/ui/app.js").text

    assert "获取模型" in page
    assert "保存" in page
    assert "连接并获取模型" not in page
    assert "验证并保存" not in page
    assert "id=\"summary-model-options\"" in page
    assert "list=\"summary-model-options\"" not in page
    assert 'role="combobox"' in page
    assert 'role="listbox"' in page
    assert 'id="summary-model-toggle"' in page
    assert "summary-target-grid" in page
    assert "summary-api-mode-field" in page
    assert "<option value=\"qwen\">Qwen</option>" in page
    assert "<option value=\"doubao\">豆包</option>" in page
    assert "<option value=\"hunyuan\">混元</option>" in page
    assert "<option value=\"glm\">GLM</option>" in page
    assert "<option value=\"grok\">Grok</option>" in page

    discovery_start = script.index("async function discoverSummaryModels")
    discovery_body = script[discovery_start:script.index("// New library controls", discovery_start)]
    save_start = script.index("async function saveSummarySettings")
    save_body = script[save_start:script.index("async function clearSummarySettings", save_start)]
    assert 'api("/api/v1/settings/summary/models"' in discovery_body
    assert 'api("/api/v1/settings/summary/test"' in save_body
    assert save_body.index('api("/api/v1/settings/summary/test"') < save_body.index('api("/api/v1/settings"')
    assert 'document.querySelector("#summary-api-url").addEventListener("change", scheduleSummaryModelDiscovery);' in script
    assert 'document.querySelector("#summary-api-key").addEventListener("change", scheduleSummaryModelDiscovery);' in script
    assert 'document.querySelector("#summary-api-mode").addEventListener("change", scheduleSummaryModelDiscovery);' in script
    assert "setTimeout(verifySummaryConnection" not in script
    assert "setSummaryFormBusy(true)" in save_body
    assert "setSummaryFormBusy(false)" in save_body
    assert "payload.summary_validation_token = validation.validation_token" in save_body
    assert 'let saveStage = "validation"' in save_body
    assert 'saveStage = "save"' in save_body
    assert '"save_failed" : "validation_failed"' in save_body
    assert '"总结模型列表获取失败"' in script
    assert '"总结模型连接验证失败"' in script
    assert '"总结 API 配置保存失败"' in script
    assert '"模型列表获取失败"' in script
    assert '"模型连接验证失败"' in script
    assert '"API 配置保存失败"' in script
    assert 'button.textContent = "获取模型中"' in script
    assert 'saveButton.textContent = "保存中"' in script
    assert 'setAttribute("aria-busy", "true")' in script
    assert '"需重试"' not in script
    assert 'const urlWasPreset = state.summaryApiUrlSource === "preset";' not in script
    assert "summaryEndpointMatchesPreset" not in script
    assert "summaryProviderExplicit" not in script
    assert "summaryApiUrlSource" not in script
    provider_sync_start = script.index("function syncSummaryProviderFromEndpoint")
    provider_sync_body = script[provider_sync_start:script.index("function asrProviderForEndpoint", provider_sync_start)]
    assert "providerSelect.value =" not in provider_sync_body
    provider_change_start = script.index("function applySummaryProviderPreset")
    provider_change_body = script[provider_change_start:script.index("function syncSummaryProviderFromEndpoint", provider_change_start)]
    assert "!currentUrl" in provider_change_body
    assert "scheduleSummaryModelDiscovery();" in provider_change_body
    assert "modelField.value" not in provider_change_body
    picker_start = script.index("function setSummaryModelPickerOpen")
    picker_body = script[picker_start:script.index("function summaryDiscoveryFingerprint", picker_start)]
    assert "ArrowDown" in picker_body
    assert "ArrowUp" in picker_body
    assert "Enter" in picker_body
    assert "selectSummaryModel" in picker_body
    invalidation_start = script.index("function invalidateSummaryConnection")
    invalidation_body = script[invalidation_start:script.index("function handleSummaryModelChange", invalidation_start)]
    assert 'models: []' in invalidation_body
    assert 'validationToken: null' in invalidation_body
    assert 'model.value = ""' not in invalidation_body
