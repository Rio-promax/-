from pathlib import Path

from app.adapters.sources.prepared import PreparedSource
from app.api.main import _job_response
from app.db.store import SQLiteStore
from app.domain.models import AnalysisSettings, ContentKind, SourcePlatform, Transcript, TranscriptSegment
from app.workflows.analyze import AnalysisWorkflow
from app.workflows import analyze


def _source(
    tmp_path: Path,
    transcript: Transcript | None,
    audio: bool,
    download_seconds: float | None = None,
) -> PreparedSource:
    audio_path = tmp_path / "source.mp3" if audio else None
    if audio_path is not None:
        audio_path.write_bytes(b"audio")
    return PreparedSource(
        kind=ContentKind.AUDIO,
        title="可观测性测试",
        transcript=transcript,
        content_hash="observability-hash",
        source_path=str(audio_path) if audio_path else None,
        source_url=None,
        acquisition_method="test",
        platform=SourcePlatform.LOCAL,
        duration_seconds=30.0,
        audio_path=str(audio_path) if audio_path else None,
        download_seconds=download_seconds,
    )


def test_submit_records_subtitle_fast_path_and_api_projects_stats(tmp_path: Path) -> None:
    store = SQLiteStore(f"sqlite:///{(tmp_path / 'asr.sqlite').as_posix()}")
    workflow = AnalysisWorkflow(store, tmp_path / "archive")
    try:
        subtitle = Transcript(
            "zh",
            "bilibili_subtitle",
            "bilibili",
            (TranscriptSegment(0.0, 30.0, "字幕内容"),),
        )
        _content, _run, job = workflow.submit(
            _source(tmp_path, subtitle, audio=False),
            AnalysisSettings(model="summary"),
        )

        stats = job.metadata["asr_stats"]
        assert stats["subtitle_hit"] is True
        assert stats["asr_skipped"] is True
        assert stats["asr_skipped_reason"] == "subtitle_hit"
        response = _job_response(job)
        assert response.asr_subtitle_hit is True
        assert response.asr_skipped is True
        assert response.asr_phase_seconds["asr"] == 0.0
    finally:
        workflow.close()


def test_submit_records_audio_fallback_reason_without_subtitle(tmp_path: Path) -> None:
    store = SQLiteStore(f"sqlite:///{(tmp_path / 'asr.sqlite').as_posix()}")
    workflow = AnalysisWorkflow(store, tmp_path / "archive")
    try:
        _content, _run, job = workflow.submit(
            _source(tmp_path, None, audio=True),
            AnalysisSettings(model="summary"),
        )
        stats = job.metadata["asr_stats"]
        assert stats["subtitle_hit"] is False
        assert stats["asr_skipped"] is False
        assert stats["asr_fallback_reason"] == "subtitle_unavailable"
        assert _job_response(job).asr_fallback_reason == "subtitle_unavailable"
    finally:
        workflow.close()


def test_submit_projects_known_audio_download_time(tmp_path: Path) -> None:
    store = SQLiteStore(f"sqlite:///{(tmp_path / 'asr.sqlite').as_posix()}")
    workflow = AnalysisWorkflow(store, tmp_path / "archive")
    try:
        _content, _run, job = workflow.submit(
            _source(tmp_path, None, audio=True, download_seconds=12.5),
            AnalysisSettings(model="summary"),
        )
        assert job.metadata["asr_stats"]["phase_seconds"]["download"] == 12.5
        assert _job_response(job).asr_phase_seconds["download"] == 12.5
    finally:
        workflow.close()


def test_asr_eta_uses_completed_audio_and_live_rtf(tmp_path: Path) -> None:
    store = SQLiteStore(f"sqlite:///{(tmp_path / 'asr.sqlite').as_posix()}")
    workflow = AnalysisWorkflow(store, tmp_path / "archive")
    try:
        _content, _run, job = workflow.submit(
            _source(tmp_path, None, audio=True),
            AnalysisSettings(model="summary"),
        )
        stats = job.metadata["asr_stats"]
        analyze._update_asr_timing(
            job,
            stats,
            completed_audio_seconds=10.0,
            total_audio_seconds=30.0,
            elapsed_seconds=20.0,
        )

        response = _job_response(job)
        assert response.asr_completed_audio_seconds == 10.0
        assert response.asr_elapsed_seconds == 20.0
        assert response.asr_rtf == 2.0
        assert response.asr_eta_seconds == 40.0
    finally:
        workflow.close()
