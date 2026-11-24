from __future__ import annotations

import json
from pathlib import Path
from time import monotonic, sleep

from app.db.store import SQLiteStore
from app.api.main import create_app
from app.domain.models import AnalysisSettings, ContentKind, SourcePlatform
from app.workflows import analyze
from app.workflows.analyze import AnalysisWorkflow
from fastapi.testclient import TestClient


class _FakeSenseVoiceWorker:
    generation = 1
    alive = True

    def __init__(self) -> None:
        self.calls: list[Path] = []
        self.batch_calls: list[tuple[Path, ...]] = []

    def transcribe(
        self,
        audio_path,
        *,
        language=None,
        cancel_check=None,
        on_heartbeat=None,
        on_lease_heartbeat=None,
    ):
        if cancel_check:
            assert not cancel_check()
        if on_heartbeat:
            on_heartbeat()
        if on_lease_heartbeat:
            on_lease_heartbeat()
        self.calls.append(Path(audio_path))
        return f"片段 {len(self.calls)}", language or "zh"

    def close(self) -> None:
        return

    def transcribe_batch(
        self,
        audio_paths,
        *,
        language=None,
        cancel_check=None,
        on_heartbeat=None,
        on_lease_heartbeat=None,
    ):
        if cancel_check:
            assert not cancel_check()
        if on_heartbeat:
            on_heartbeat()
        if on_lease_heartbeat:
            on_lease_heartbeat()
        paths = tuple(Path(path) for path in audio_paths)
        self.batch_calls.append(paths)
        results = []
        for path in paths:
            self.calls.append(path)
            results.append((f"片段 {len(self.calls)}", language or "zh"))
        return tuple(results)

    def ensure_started(self, cancel_check=None) -> int:
        if cancel_check:
            assert not cancel_check()
        return self.generation


class _FlakySenseVoiceWorker(_FakeSenseVoiceWorker):
    def __init__(self) -> None:
        super().__init__()
        self.failed_once = False

    def transcribe(
        self,
        audio_path,
        *,
        language=None,
        cancel_check=None,
        on_heartbeat=None,
        on_lease_heartbeat=None,
    ):
        if not self.failed_once:
            self.failed_once = True
            raise TimeoutError("test timeout")
        return super().transcribe(
            audio_path,
            language=language,
            cancel_check=cancel_check,
            on_heartbeat=on_heartbeat,
            on_lease_heartbeat=on_lease_heartbeat,
        )


def _workflow(tmp_path: Path, duration: float) -> tuple[SQLiteStore, AnalysisWorkflow, object]:
    store = SQLiteStore(f"sqlite:///{(tmp_path / 'asr.sqlite').as_posix()}")
    content = store.create_content(
        kind=ContentKind.AUDIO,
        title="分片恢复测试",
        platform=SourcePlatform.LOCAL,
        duration_seconds=duration,
    )
    run, job = store.create_analysis_run(content.id, AnalysisSettings(model="summary"))
    audio = tmp_path / "source.mp3"
    audio.write_bytes(b"audio")
    job.metadata = {
        "audio_path": str(audio),
        "checkpoint_dir": str(tmp_path / "checkpoints"),
    }
    job.claim("test-worker")
    store.save_job(job)
    return store, AnalysisWorkflow(store, tmp_path / "archive"), job


def test_sensevoice_workflow_persists_and_merges_product_segments(
    tmp_path: Path, monkeypatch
) -> None:
    store, workflow, job = _workflow(tmp_path, 65.0)
    worker = _FakeSenseVoiceWorker()
    workflow._sensevoice_worker = worker
    workflow._sensevoice_worker_key = str((tmp_path / "model").resolve())
    workflow._sensevoice_worker_last_used = monotonic()
    monkeypatch.setattr(analyze, "materialize_audio_segment", lambda audio_path, **_: audio_path)

    transcript = workflow._transcribe_sensevoice_segments(
        job,
        tmp_path / "model",
        language="zh",
    )

    assert len(transcript.segments) == 3
    assert [segment.text for segment in transcript.segments] == ["片段 1", "片段 2", "片段 3"]
    fingerprint = job.metadata["asr_config_fingerprint"]
    progress = store.asr_segment_progress(job.id, fingerprint)
    assert progress["total"] == 3
    assert progress["completed"] == 3
    assert progress["completed_audio_seconds"] == 65.0
    assert job.metadata["asr_completed_segments"] == 3


def test_sensevoice_workflow_uses_persisted_safe_batch_selection(
    tmp_path: Path, monkeypatch
) -> None:
    store, workflow, job = _workflow(tmp_path, 65.0)
    store.set_setting(
        "asr_batch_selection",
        json.dumps(
            {
                "model_id": "sensevoice-small",
                "selected_batch_size": 2,
                "status": "passed",
            }
        ),
    )
    worker = _FakeSenseVoiceWorker()
    workflow._sensevoice_worker = worker
    workflow._sensevoice_worker_key = str((tmp_path / "model").resolve())
    workflow._sensevoice_worker_last_used = monotonic()
    monkeypatch.setattr(analyze, "materialize_audio_segment", lambda audio_path, **_: audio_path)

    transcript = workflow._transcribe_sensevoice_segments(
        job,
        tmp_path / "model",
        language="zh",
    )

    assert [len(paths) for paths in worker.batch_calls] == [2]
    assert len(worker.calls) == 3
    assert [segment.text for segment in transcript.segments] == [
        "片段 1",
        "片段 2",
        "片段 3",
    ]
    assert job.metadata["asr_batch_size"] == 2
    assert job.metadata["asr_config_fingerprint"] == analyze.asr_config_fingerprint(
        model_id="sensevoice-small",
        language="zh",
        batch_size=2,
    )
    assert job.metadata["asr_stats"]["batch_selection"] == "benchmark_passed"


def test_sensevoice_workflow_reuses_completed_segment_after_resume(
    tmp_path: Path, monkeypatch
) -> None:
    store, workflow, job = _workflow(tmp_path, 65.0)
    worker = _FakeSenseVoiceWorker()
    workflow._sensevoice_worker = worker
    workflow._sensevoice_worker_key = str((tmp_path / "model").resolve())
    workflow._sensevoice_worker_last_used = monotonic()
    monkeypatch.setattr(analyze, "materialize_audio_segment", lambda audio_path, **_: audio_path)

    fingerprint = analyze.asr_config_fingerprint(model_id="sensevoice-small", language="zh")
    store.create_asr_segments(
        job.id,
        fingerprint,
        [
            {"segment_index": index, "start_seconds": start, "end_seconds": end}
            for index, (start, end) in enumerate(analyze.build_audio_segment_ranges(65.0))
        ],
    )
    claimed = store.claim_asr_segment(
        job.id,
        fingerprint,
        "test-worker:asr",
        worker_generation=1,
    )
    assert claimed is not None
    store.commit_asr_segment(
        claimed.id,
        "test-worker:asr",
        worker_generation=1,
        text="已保存",
        language="zh",
    )

    transcript = workflow._transcribe_sensevoice_segments(
        job,
        tmp_path / "model",
        language="zh",
    )

    assert transcript.segments[0].text == "已保存"
    assert [segment.text for segment in transcript.segments[1:]] == ["片段 1", "片段 2"]
    assert len(worker.calls) == 2


def test_sensevoice_timeout_retries_the_same_pending_segment(
    tmp_path: Path, monkeypatch
) -> None:
    store, workflow, job = _workflow(tmp_path, 65.0)
    worker = _FlakySenseVoiceWorker()
    workflow._sensevoice_worker = worker
    workflow._sensevoice_worker_key = str((tmp_path / "model").resolve())
    workflow._sensevoice_worker_last_used = monotonic()
    monkeypatch.setattr(analyze, "materialize_audio_segment", lambda audio_path, **_: audio_path)

    transcript = workflow._transcribe_sensevoice_segments(
        job,
        tmp_path / "model",
        language="zh",
    )

    assert [segment.text for segment in transcript.segments] == [
        "片段 1",
        "片段 2",
        "片段 3",
    ]
    assert len(worker.calls) == 3
    fingerprint = job.metadata["asr_config_fingerprint"]
    rows = store.list_asr_segments(job.id, fingerprint)
    assert [row.attempts for row in rows] == [2, 1, 1]
    assert all(row.worker_generation == 1 for row in rows)


def test_resident_worker_is_released_after_idle_timeout(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(analyze, "ASR_WORKER_IDLE_SECONDS", 0.1)
    store, workflow, _job = _workflow(tmp_path, 10.0)
    worker = _FakeSenseVoiceWorker()
    workflow._sensevoice_worker = worker
    workflow._sensevoice_worker_key = str((tmp_path / "model").resolve())
    workflow._sensevoice_worker_last_used = monotonic() - 1.0

    try:
        deadline = monotonic() + 1.0
        while workflow._sensevoice_worker is not None and monotonic() < deadline:
            sleep(0.05)
        assert workflow._sensevoice_worker is None
        assert workflow._sensevoice_worker_key is None
    finally:
        workflow.close()


def test_cancel_job_clears_asr_segment_checkpoints(tmp_path: Path) -> None:
    client = TestClient(create_app("sqlite:///:memory:", tmp_path / "archive"))
    store = client.app.state.store
    content = store.create_content(
        kind=ContentKind.AUDIO,
        title="取消清理测试",
        platform=SourcePlatform.LOCAL,
    )
    _run, job = store.create_analysis_run(content.id, AnalysisSettings(model="summary"))
    store.create_asr_segments(
        job.id,
        "cancel-config",
        [{"segment_index": 0, "start_seconds": 0.0, "end_seconds": 30.0}],
    )

    response = client.post(f"/api/v1/jobs/{job.id}/cancel")

    assert response.status_code == 200
    assert store.list_asr_segments(job.id, "cancel-config") == []


def test_delete_content_cancels_runs_and_cleans_task_asr_artifacts(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    client = TestClient(create_app("sqlite:///:memory:", archive))
    store = client.app.state.store
    content = store.create_content(
        kind=ContentKind.AUDIO,
        title="内容级 ASR 清理",
        platform=SourcePlatform.LOCAL,
    )
    _run, job = store.create_analysis_run(content.id, AnalysisSettings(model="summary"))
    audio_dir = tmp_path / "knowledge-asr-delete"
    audio_dir.mkdir()
    audio = audio_dir / "source.mp3"
    audio.write_bytes(b"temporary audio")
    checkpoint_dir = archive / ".checkpoints" / job.id
    checkpoint_dir.mkdir(parents=True)
    (checkpoint_dir / "transcript.json").write_text("{}", encoding="utf-8")
    job.metadata.update(
        {
            "audio_path": str(audio),
            "audio_is_temp": True,
            "checkpoint_dir": str(checkpoint_dir),
        }
    )
    store.save_job(job)
    store.create_asr_segments(
        job.id,
        "delete-config",
        [{"segment_index": 0, "start_seconds": 0.0, "end_seconds": 30.0}],
    )

    try:
        response = client.delete(f"/api/v1/contents/{content.id}")

        assert response.status_code == 200
        deleted_job = store.get_job(job.id)
        assert deleted_job.state.value == "cancelled"
        assert store.list_asr_segments(job.id, "delete-config") == []
        assert not checkpoint_dir.exists()
        assert not audio_dir.exists()
        assert client.post(f"/api/v1/jobs/{job.id}/resume").status_code == 409
    finally:
        client.app.state.workflow.close()
