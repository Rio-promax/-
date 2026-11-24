from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.adapters.sources.prepared import PreparedSource
from app.api import main as api_main
from app.api.main import create_app
from app.db.store import SQLiteStore
from app.domain.models import (
    AnalysisSettings,
    ContentKind,
    SourcePlatform,
    Transcript,
    TranscriptSegment,
)
from app.workflows.analyze import AnalysisWorkflow


def _temporary_source(audio_path: Path) -> PreparedSource:
    return PreparedSource(
        kind=ContentKind.VIDEO,
        title="临时音频测试",
        transcript=None,
        content_hash="temporary-audio",
        source_path=None,
        source_url="https://www.bilibili.com/video/BV1GKgM6qEar",
        acquisition_method="link",
        platform=SourcePlatform.BILIBILI,
        duration_seconds=1.0,
        audio_path=str(audio_path),
        audio_is_temp=True,
    )


def _install_fake_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.workflows import analyze

    class FakeSummarizer:
        def __init__(self, _settings) -> None:
            pass

        def summarize_chunks(self, *_args, **_kwargs):
            return SimpleNamespace(
                markdown="# 内容总结\n\n## 概览\n\n测试总结。\n",
                overview="测试总结。",
            )

    monkeypatch.setattr(analyze, "OpenAICompatibleSummarizer", FakeSummarizer)


def test_workflow_removes_downloaded_audio_after_asr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp_dir = tmp_path / "knowledge-asr-test"
    temp_dir.mkdir()
    audio_path = temp_dir / "source.m4a"
    audio_path.write_bytes(b"audio")
    store = SQLiteStore("sqlite:///:memory:")
    store.set_setting("asr_api_key", "test-key")
    workflow = AnalysisWorkflow(store, tmp_path / "knowledge-root")

    class FakeTranscriber:
        def __init__(self, _settings) -> None:
            pass

        def transcribe(self, path: Path, *, language: str | None) -> Transcript:
            assert path == audio_path
            assert language == "zh-CN"
            return Transcript(
                "zh-CN",
                "asr",
                "test-asr",
                (TranscriptSegment(0.0, 1.0, "转写出的完整视频内容。"),),
            )

    from app.adapters.asr import openai_compatible

    monkeypatch.setattr(openai_compatible, "OpenAICompatibleTranscriber", FakeTranscriber)
    _install_fake_summary(monkeypatch)
    content, _, job = workflow.submit(
        _temporary_source(audio_path),
        AnalysisSettings(model="test-model", language="zh-CN", max_chunk_tokens=32),
    )
    checkpoint_dir = Path(job.metadata["checkpoint_dir"])

    workflow.run(job.id, None)

    assert not temp_dir.exists()
    assert not checkpoint_dir.exists()
    archived_transcripts = list((tmp_path / "knowledge-root").rglob("transcript.json"))
    assert len(archived_transcripts) == 1
    assert content.id in str(archived_transcripts[0])
    assert store.get_job(job.id).state.value == "completed"


def test_workflow_reports_missing_local_asr_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp_dir = tmp_path / "knowledge-asr-local-runtime"
    temp_dir.mkdir()
    audio_path = temp_dir / "source.m4a"
    audio_path.write_bytes(b"audio")
    store = SQLiteStore("sqlite:///:memory:")
    workflow = AnalysisWorkflow(store, tmp_path / "knowledge-root")

    from app.workflows import analyze

    monkeypatch.setattr(analyze, "local_asr_runtime_available", lambda: False)
    _, _, job = workflow.submit(
        _temporary_source(audio_path),
        AnalysisSettings(
            model="test-model",
            asr_engine="local",
            asr_config={"engine": "local", "local_model": "small"},
        ),
    )

    workflow.run(job.id, None)

    failed = store.get_job(job.id)
    assert failed.state.value == "failed"
    assert failed.error_code.value == "asr_runtime_unavailable"
    assert "本地 ASR 组件尚未安装" in (failed.error_message or "")
    assert not temp_dir.exists()


def test_workflow_clears_checkpoints_after_nonresumable_summary_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp_dir = tmp_path / "knowledge-asr-summary-failure"
    temp_dir.mkdir()
    audio_path = temp_dir / "source.m4a"
    audio_path.write_bytes(b"audio")
    store = SQLiteStore("sqlite:///:memory:")
    store.set_setting("asr_api_key", "test-key")
    workflow = AnalysisWorkflow(store, tmp_path / "knowledge-root")

    class FakeTranscriber:
        def __init__(self, _settings) -> None:
            pass

        def transcribe(self, _path: Path, *, language: str | None) -> Transcript:
            return Transcript(
                "zh-CN",
                "asr",
                "test-asr",
                (TranscriptSegment(0.0, 1.0, "转写内容。"),),
            )

    class FailingSummarizer:
        def __init__(self, _settings) -> None:
            pass

        def summarize_chunks(self, *_args, **_kwargs):
            raise RuntimeError("summary failed")

    from app.adapters.asr import openai_compatible

    monkeypatch.setattr(openai_compatible, "OpenAICompatibleTranscriber", FakeTranscriber)
    from app.workflows import analyze

    monkeypatch.setattr(analyze, "OpenAICompatibleSummarizer", FailingSummarizer)
    _, _, job = workflow.submit(
        _temporary_source(audio_path),
        AnalysisSettings(model="test-model", language="zh-CN", max_chunk_tokens=32),
    )
    checkpoint_dir = Path(job.metadata["checkpoint_dir"])

    workflow.run(job.id, None)

    failed = store.get_job(job.id)
    assert failed.state.value == "failed"
    assert not temp_dir.exists()
    assert not checkpoint_dir.exists()


def test_duplicate_batch_link_discards_downloaded_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp_dir = tmp_path / "knowledge-asr-duplicate"
    temp_dir.mkdir()
    source = _temporary_source(temp_dir / "source.m4a")
    Path(source.audio_path).write_bytes(b"audio")
    client = TestClient(create_app("sqlite:///:memory:", tmp_path / "knowledge-root"))
    client.app.state.store.create_content(
        kind=source.kind,
        title=source.title,
        platform=source.platform,
        canonical_url=source.source_url,
        content_hash=source.content_hash,
    )
    client.app.state.store.set_setting("asr_api_key", "test-key")
    client.app.state.store.set_setting("asr_api_url", "https://asr.example.test/v1/transcriptions")
    client.app.state.store.set_setting("asr_model", "test-model")
    monkeypatch.setattr(api_main, "prepare_link_import", lambda **_kwargs: source)

    response = client.post(
        "/api/v1/imports/links",
        json={
            "urls": [source.source_url],
            "strength": "quick",
            "duplicate_action": "reuse",
        },
    )

    assert response.status_code == 200
    assert response.json()["skipped"] == [source.source_url]
    assert not temp_dir.exists()
