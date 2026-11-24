from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock, Thread
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.adapters.sources.local import prepare_local_import
from app.api.main import create_app
from app.domain.jobs import JobState
from app.domain.models import AnalysisSettings
from app.knowledge.chunking import chunk_transcript
from app.knowledge.transcript import transcript_from_text


def make_client(tmp_path: Path) -> TestClient:
    database_url = f"sqlite:///{(tmp_path / 'knowledge.db').as_posix()}"
    return TestClient(create_app(database_url, tmp_path / "knowledge-root"))


def test_empty_local_audio_is_rejected_before_asr(tmp_path: Path) -> None:
    audio = tmp_path / "empty.mp3"
    audio.touch()

    with pytest.raises(ValueError, match="音频文件为空"):
        prepare_local_import(source_path=str(audio), text=None, title=None, language="zh-CN")


def install_fake_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.workflows import analyze

    class FakeSummarizer:
        def __init__(self, _settings) -> None:
            pass

        def summarize_chunks(self, chunks, *, title, strength, prompt, skill=None, text_material=False):
            text = "\n".join(chunk.text for chunk in chunks)
            return SimpleNamespace(
                markdown=f"# 内容总结\n\n## 概览\n\n{text}\n",
                overview=text,
            )

    monkeypatch.setattr(analyze, "OpenAICompatibleSummarizer", FakeSummarizer)


def test_pasted_text_runs_to_archive_and_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_summary(monkeypatch)
    client = make_client(tmp_path)

    response = client.post(
        "/api/v1/imports/local",
        json={
            "title": "本地学习笔记",
            "text": "第一段说明项目目标。\n\n第二段说明如何保存和检索知识。",
            "strength": "standard",
            "max_chunk_tokens": 32,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    job = client.get(f"/api/v1/jobs/{payload['job']['id']}").json()
    assert job["state"] == "completed"
    assert job["progress"] == 100
    assert job["archive_path"]

    history = client.get("/api/v1/history").json()
    assert history[0]["content"]["title"] == "未命名文本"
    assert history[0]["job"]["summary_preview"]

    result = client.get(f"/api/v1/contents/{payload['content']['id']}/result")
    assert result.status_code == 200
    assert "# 内容总结" in result.json()["markdown"]
    assert (tmp_path / "knowledge-root").exists()


def test_resummarize_pasted_text_creates_new_content_from_saved_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_summary(monkeypatch)
    client = make_client(tmp_path)
    first = client.post(
        "/api/v1/imports/local",
        json={"title": "原始笔记", "text": "重新总结应读取的原始转写。"},
    )
    assert first.status_code == 201
    first_id = first.json()["content"]["id"]
    client.app.state.store.upsert_summary(
        first_id,
        "旧总结不应被重新总结读取。",
        transcript_text="重新总结应读取的原始转写。",
    )

    response = client.post(
        f"/api/v1/contents/{first_id}/resummarize",
        json={"summary_template": "general"},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["content"]["id"] != first_id
    assert payload["content"]["title"] == "未命名文本（1）"
    job_payload = client.get(f"/api/v1/jobs/{payload['job']['id']}").json()
    assert job_payload["state"] == "completed", {
        key: job_payload.get(key) for key in ("state", "checkpoint", "error_code", "error_message")
    }
    assert "重新总结应读取的原始转写" in client.get(
        f"/api/v1/contents/{payload['content']['id']}/result"
    ).json()["markdown"]


def test_local_import_applies_optional_tags_and_favorite_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_summary(monkeypatch)
    client = make_client(tmp_path)
    tag = client.post("/api/v1/tags", json={"name": "课程"})
    assert tag.status_code == 201
    tag_id = tag.json()["id"]
    folder = client.post("/api/v1/favorite-folders", json={"name": "课程资料"})
    assert folder.status_code == 201
    folder_id = folder.json()["id"]

    response = client.post(
        "/api/v1/imports/local",
        json={
            "text": "这是一份需要归类的本地学习材料。",
            "tag_ids": [tag_id],
            "favorite_folder_ids": [folder_id],
        },
    )

    assert response.status_code == 201
    assert response.json()["content"]["tag_ids"] == [tag_id]
    assert response.json()["content"]["favorite_folder_ids"] == [folder_id]

    regenerated = client.post(
        "/api/v1/imports/local",
        json={
            "text": "这是一份需要归类的本地学习材料。",
            "category": "复习",
            "favorite_folder_ids": [folder_id],
        },
    )
    assert regenerated.status_code == 201
    assert regenerated.json()["reused"] is False
    assert regenerated.json()["duplicate"] is True
    assert regenerated.json()["content"]["id"] != response.json()["content"]["id"]
    assert regenerated.json()["content"]["title"].endswith("（1）")
    assert regenerated.json()["content"]["category"] == "复习"
    assert regenerated.json()["content"]["favorite_folder_ids"] == [folder_id]

    no_folder = client.post(
        "/api/v1/imports/local",
        json={
            "text": "这是一份缺少收藏夹的归类材料。",
            "tag_ids": [tag_id],
        },
    )
    assert no_folder.status_code == 201
    assert no_folder.json()["content"]["tag_ids"] == [tag_id]

    no_classification = client.post(
        "/api/v1/imports/local",
        json={
            "text": "这是一份不选择标签和收藏夹也能归档的材料。",
        },
    )
    assert no_classification.status_code == 201
    assert no_classification.json()["content"]["tag_ids"] == []
    assert no_classification.json()["content"]["favorite_folder_ids"] == []


def test_local_media_without_known_duration_fails_even_with_subtitle(tmp_path: Path) -> None:
    media = tmp_path / "课程.mp4"
    media.write_bytes(b"not-a-real-video")
    media.with_suffix(".srt").write_text(
        "1\n00:00:00,000 --> 00:00:03,000\n欢迎学习本地知识库。\n",
        encoding="utf-8",
    )
    client = make_client(tmp_path)

    response = client.post(
        "/api/v1/imports/local",
        json={"source_path": str(media), "strength": "quick"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["content"]["kind"] == "video"
    job = client.get(f"/api/v1/jobs/{payload['job']['id']}").json()
    assert job["state"] == "failed"
    assert job["error_code"] == "transcript_incomplete"
    assert "无法确认视频时长" in job["error_message"]


def test_ai_tag_suggestion_failure_does_not_block_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_summary(monkeypatch)
    client = make_client(tmp_path)
    client.app.state.store.set_setting("ai_tag_recommendation_enabled", "true")

    def fail_suggestions(*_args, **_kwargs):
        raise RuntimeError("标签模型暂时不可用")

    monkeypatch.setattr(client.app.state.workflow, "_generate_tag_suggestions", fail_suggestions)
    response = client.post(
        "/api/v1/imports/local",
        json={"text": "标签推荐失败也必须保存的内容。"},
    )

    assert response.status_code == 201
    job = client.get(f"/api/v1/jobs/{response.json()['job']['id']}").json()
    assert job["state"] == "completed"
    result = client.get(f"/api/v1/contents/{response.json()['content']['id']}/result")
    assert result.status_code == 200
    assert result.json()["tag_suggestions"] == []


def test_configured_rag_tag_worker_handles_consecutive_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.knowledge import rag
    from app.db.models import ContentRow
    from sqlalchemy import select

    install_fake_summary(monkeypatch)
    started = Event()
    release = Event()
    first_call = True
    call_lock = Lock()

    class FakeTagGenerator:
        settings = SimpleNamespace(model="test-rag-classifier")

        def __init__(self, _settings) -> None:
            pass

        def structured_json_request_bytes(self, *_args, **_kwargs) -> int:
            return 200

        def complete_json(self, *_args, **_kwargs):
            nonlocal first_call
            with call_lock:
                should_wait = first_call
                first_call = False
            if should_wait:
                started.set()
                assert release.wait(timeout=8)
            return {"topics": [], "detail_tags": []}, {"usage": {"total_tokens": 10}}

    monkeypatch.setattr(rag, "OpenAICompatibleSummarizer", FakeTagGenerator)
    database_url = f"sqlite:///{(tmp_path / 'knowledge.db').as_posix()}"
    app = create_app(database_url, tmp_path / "knowledge-root")
    with TestClient(app) as client:
        store = client.app.state.store
        store.set_secret_setting("summary_api_key", "test-only-key", purpose="test")
        barrier = Barrier(2)
        connections: list[int] = []

        def hold_connection() -> None:
            with store.engine.connect() as connection:
                connections.append(id(connection.connection.driver_connection))
                barrier.wait(timeout=5)

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(hold_connection)
            second = executor.submit(hold_connection)
            first.result(timeout=8)
            second.result(timeout=8)
        assert len(set(connections)) == 2

        first_import = client.post(
            "/api/v1/imports/local", json={"text": "第一份并发回归材料，包含完整的学习正文。"}
        )
        assert first_import.status_code == 201
        assert started.wait(timeout=8)
        imported_ids = [first_import.json()["content"]["id"]]
        for number in range(2, 5):
            response = client.post(
                "/api/v1/imports/local",
                json={"text": f"第{number}份并发回归材料，包含不同的学习正文。"},
            )
            assert response.status_code == 201
            imported_ids.append(response.json()["content"]["id"])

        with client.app.state.rag_tag_workers_lock:
            workers = list(client.app.state.rag_tag_workers.values())
        release.set()
        for future in workers:
            future.result(timeout=15)

        with store.session_factory() as session:
            persisted_ids = set(session.scalars(select(ContentRow.id)).all())
        assert set(imported_ids) <= persisted_ids
        assert len(imported_ids) == len(set(imported_ids))
def test_local_media_without_subtitle_fails_with_reason(tmp_path: Path) -> None:
    # 假视频无法提取音轨 → 明确失败原因
    media = tmp_path / "无字幕视频.mp4"
    media.write_bytes(b"not-a-real-video")
    client = make_client(tmp_path)

    response = client.post(
        "/api/v1/imports/local",
        json={"source_path": str(media), "strength": "quick"},
    )

    assert response.status_code == 422
    assert "无法识别视频内容" in response.json()["detail"]


def test_local_audio_runs_asr_when_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import struct

    from app.domain.models import Transcript, TranscriptSegment
    from app.adapters.asr import openai_compatible

    # 最小合法 wav（1 秒 8kHz 单声道）
    audio = tmp_path / "语音.wav"
    samples = b"\x00\x00" * 8000
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(samples), b"WAVE", b"fmt ", 16,
        1, 1, 8000, 16000, 2, 16, b"data", len(samples),
    )
    audio.write_bytes(header + samples)

    class FakeTranscriber:
        def __init__(self, settings) -> None:
            self.settings = settings

        def transcribe(self, audio_path, *, language=None) -> Transcript:
            return Transcript(
                language,
                "asr",
                "openai-compatible",
                (TranscriptSegment(0.0, 1.0, "转写文本第一句。"),),
            )

    monkeypatch.setattr(openai_compatible, "OpenAICompatibleTranscriber", FakeTranscriber)
    install_fake_summary(monkeypatch)
    client = make_client(tmp_path)
    client.app.state.store.set_setting("asr_api_key", "test-key")
    client.app.state.store.set_setting("asr_api_url", "https://asr.example.test/v1/transcriptions")
    client.app.state.store.set_setting("asr_model", "test-model")

    response = client.post(
        "/api/v1/imports/local",
        json={"source_path": str(audio), "title": "语音测试", "strength": "quick"},
    )

    assert response.status_code == 201
    payload = response.json()
    job = client.get(f"/api/v1/jobs/{payload['job']['id']}").json()
    assert job["state"] == "completed"
    result = client.get(f"/api/v1/contents/{payload['content']['id']}/result")
    assert "转写文本第一句" in result.json()["markdown"]


def test_local_media_without_subtitle_requires_asr_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.adapters.sources import local_media

    media = tmp_path / "视频.mp4"
    media.write_bytes(b"fake")
    wav = tmp_path / "video.wav"
    wav.write_bytes(b"fake-wav")

    monkeypatch.setattr(local_media, "_audio_for_asr", lambda path: wav)
    client = make_client(tmp_path)

    response = client.post(
        "/api/v1/imports/local",
        json={"source_path": str(media), "strength": "quick"},
    )

    assert response.status_code == 422
    assert "未配置 ASR" in response.json()["detail"]


def test_summary_failure_does_not_create_a_transcript_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.workflows import analyze

    client = make_client(tmp_path)

    class FailingSummarizer:
        def __init__(self, _settings) -> None:
            pass

        def summarize_chunks(self, *_args, **_kwargs):
            raise RuntimeError("总结服务不可用")

    monkeypatch.setattr(analyze, "OpenAICompatibleSummarizer", FailingSummarizer)
    response = client.post(
        "/api/v1/imports/local",
        json={"title": "总结失败", "text": "这是一段不能被当成总结保存的转写文本。"},
    )

    assert response.status_code == 201
    payload = response.json()
    job = client.get(f"/api/v1/jobs/{payload['job']['id']}").json()
    assert job["state"] == "failed"
    assert job["error_code"] == "summary_generation_failed"
    assert "总结生成失败" in job["error_message"]
    result = client.get(f"/api/v1/contents/{payload['content']['id']}/result")
    assert result.status_code == 409


def test_freeform_summary_without_overview_is_archived(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.workflows import analyze

    class FreeformSummarizer:
        def __init__(self, _settings) -> None:
            pass

        def summarize_chunks(self, *_args, **_kwargs):
            return SimpleNamespace(markdown="模型返回的自由格式总结。", overview="")

    monkeypatch.setattr(analyze, "OpenAICompatibleSummarizer", FreeformSummarizer)
    client = make_client(tmp_path)

    response = client.post(
        "/api/v1/imports/local",
        json={"title": "自由格式总结", "text": "这是一段转写文本。"},
    )

    assert response.status_code == 201
    payload = response.json()
    job = client.get(f"/api/v1/jobs/{payload['job']['id']}").json()
    assert job["state"] == "completed"
    result = client.get(f"/api/v1/contents/{payload['content']['id']}/result")
    assert result.status_code == 200
    assert "模型返回的自由格式总结。" in result.json()["markdown"]


def test_cancelled_local_file_job_can_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_summary(monkeypatch)
    source_path = tmp_path / "可重试笔记.txt"
    source_path.write_text("这份笔记可以重新分析。", encoding="utf-8")
    client = make_client(tmp_path)
    source = prepare_local_import(
        source_path=str(source_path),
        text=None,
        title=None,
        language=None,
    )
    content, _, job = client.app.state.workflow.submit(
        source,
        AnalysisSettings(model="test-model"),
    )
    job.transition(JobState.CANCELLED)
    client.app.state.store.save_job(job)

    response = client.post(f"/api/v1/jobs/{job.id}/retry")

    assert response.status_code == 200
    retried = response.json()
    assert retried["content"]["id"] == content.id
    completed = client.get(f"/api/v1/jobs/{retried['job']['id']}").json()
    assert completed["state"] == "completed"


def test_retry_uses_current_summary_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.workflows import analyze

    captured: dict[str, object] = {}

    class CurrentConfigSummarizer:
        def __init__(self, settings) -> None:
            captured["settings"] = settings

        def summarize_chunks(self, chunks, *, title, strength, prompt, skill=None, text_material=False):
            return SimpleNamespace(
                markdown="# 内容总结\n\n## 概览\n\n当前配置已生效。\n",
                overview="当前配置已生效。",
            )

    monkeypatch.setattr(analyze, "OpenAICompatibleSummarizer", CurrentConfigSummarizer)
    source_path = tmp_path / "配置重试笔记.txt"
    source_path.write_text("这份笔记使用当前总结配置重试。", encoding="utf-8")
    client = make_client(tmp_path)
    store = client.app.state.store
    store.set_setting("summary_provider", "qwen")
    store.set_setting("summary_api_url", "https://summary.example.test/compatible-mode/v1")
    store.set_setting("summary_api_mode", "chat_completions")
    store.set_setting("summary_model", "qwen3.7-flash")
    store.set_setting("summary_api_key", "current-secret-key")
    source = prepare_local_import(
        source_path=str(source_path),
        text=None,
        title=None,
        language=None,
    )
    content, _, job = client.app.state.workflow.submit(
        source,
        AnalysisSettings(
            model="deepseek-v4-flash",
            summary_provider="deepseek",
            summary_config={
                "api_url": "https://api.deepseek.com/chat/completions",
                "model": "deepseek-v4-flash",
                "timeout_seconds": 30,
            },
            summary_prompt="旧配置 Prompt",
        ),
    )
    job.transition(JobState.CANCELLED)
    store.save_job(job)

    response = client.post(f"/api/v1/jobs/{job.id}/retry")

    assert response.status_code == 200
    settings = captured["settings"]
    assert settings.api_url == "https://summary.example.test/compatible-mode/v1"
    assert settings.api_mode == "chat_completions"
    assert settings.model == "qwen3.7-flash"
    retried_snapshot = response.json()["run"]["settings_snapshot"]
    assert retried_snapshot["summary_provider"] == "qwen"
    assert retried_snapshot["summary_config"]["api_url"] == "https://summary.example.test/compatible-mode/v1"
    assert retried_snapshot["summary_config"]["model"] == "qwen3.7-flash"
    completed = client.get(f"/api/v1/jobs/{response.json()['job']['id']}").json()
    assert completed["state"] == "completed"
    assert content.id == response.json()["content"]["id"]


def test_video_transcript_shorter_than_known_duration_is_partial_material() -> None:
    from app.domain.models import Transcript, TranscriptSegment
    from app.workflows.analyze import _validate_video_transcript

    transcript = Transcript(
        "zh-CN",
        "subtitle",
        "test",
        (TranscriptSegment(0.0, 10.0, "只识别到视频开头。"),),
    )

    assert _validate_video_transcript(transcript, 120.0) == "M1"


def test_long_segment_is_split_within_budget() -> None:
    transcript = transcript_from_text("知识" * 60)

    chunks = chunk_transcript(transcript, max_tokens=12)

    assert len(chunks) == 10
    assert all(chunk.token_count <= 12 for chunk in chunks)
    assert "".join(chunk.text for chunk in chunks) == "知识" * 60


def test_ui_is_served_from_root(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/")

    assert response.status_code == 200
    assert "内容知识库" in response.text
    assert 'data-view-target="intake"' in response.text
    assert 'data-view-target="jobs"' not in response.text
    assert 'id="source-probe"' in response.text
