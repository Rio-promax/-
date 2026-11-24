from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.db.store import SQLiteStore
from app.domain.jobs import Job
from app.domain.models import AnalysisSettings, ContentKind, SourcePlatform


def _store_with_job() -> tuple[SQLiteStore, Job]:
    store = SQLiteStore("sqlite:///:memory:")
    content = store.create_content(
        kind=ContentKind.AUDIO,
        title="ASR checkpoint test",
        platform=SourcePlatform.LOCAL,
    )
    _run, job = store.create_analysis_run(content.id, AnalysisSettings(model="test"))
    return store, job


def _segments() -> list[dict[str, object]]:
    return [
        {"segment_index": 0, "start_seconds": 0.0, "end_seconds": 20.0},
        {"segment_index": 1, "start_seconds": 20.0, "end_seconds": 40.0},
    ]


def test_asr_checkpoint_creation_is_idempotent_and_config_scoped() -> None:
    store, job = _store_with_job()

    first = store.create_asr_segments(job.id, "config-a", _segments())
    repeated = store.create_asr_segments(job.id, "config-a", _segments())
    second_config = store.create_asr_segments(job.id, "config-b", _segments())

    assert [row.id for row in repeated] == [row.id for row in first]
    assert len(first) == len(second_config) == 2
    assert {row.config_fingerprint for row in first + second_config} == {
        "config-a",
        "config-b",
    }


def test_asr_checkpoint_lease_commit_and_expiry_recovery() -> None:
    store, job = _store_with_job()
    store.create_asr_segments(job.id, "config-a", _segments())
    started = datetime(2026, 9, 19, tzinfo=UTC)

    first = store.claim_asr_segment(
        job.id,
        "config-a",
        "worker-1",
        lease_seconds=10,
        worker_generation=3,
        now=started,
    )
    assert first is not None
    assert first.segment_index == 0
    assert first.attempts == 1
    assert first.worker_generation == 3
    assert not store.heartbeat_asr_segment(
        first.id,
        "worker-1",
        worker_generation=2,
        lease_seconds=10,
        now=started + timedelta(seconds=1),
    )
    assert store.heartbeat_asr_segment(
        first.id,
        "worker-1",
        worker_generation=3,
        lease_seconds=10,
        now=started + timedelta(seconds=5),
    )

    committed = store.commit_asr_segment(
        first.id,
        "worker-1",
        worker_generation=3,
        text="第一片",
        language="zh",
        now=started + timedelta(seconds=6),
    )
    assert committed.status == "completed"
    assert committed.text == "第一片"
    assert store.commit_asr_segment(
        first.id,
        "stale-worker",
        worker_generation=99,
        text="不得覆盖",
    ).text == "第一片"

    second = store.claim_asr_segment(
        job.id,
        "config-a",
        "worker-1",
        lease_seconds=10,
        worker_generation=4,
        now=started,
    )
    assert second is not None and second.segment_index == 1
    assert store.recover_expired_asr_segments(now=started + timedelta(seconds=11)) == 1
    reclaimed = store.claim_asr_segment(
        job.id,
        "config-a",
        "worker-2",
        worker_generation=5,
        now=started + timedelta(seconds=12),
    )
    assert reclaimed is not None
    assert reclaimed.id == second.id
    assert reclaimed.attempts == 2
    with pytest.raises(RuntimeError, match="lease"):
        store.commit_asr_segment(
            reclaimed.id,
            "worker-1",
            worker_generation=4,
            text="旧代际",
        )
    with pytest.raises(RuntimeError, match="lease"):
        store.commit_asr_segment(
            reclaimed.id,
            "worker-2",
            worker_generation=4,
            text="旧代际",
        )


def test_asr_progress_cleanup_and_dynamic_budget() -> None:
    store, job = _store_with_job()
    store.create_asr_segments(job.id, "config-a", _segments())
    claimed = store.claim_asr_segment(
        job.id,
        "config-a",
        "worker",
        worker_generation=1,
    )
    assert claimed is not None
    store.commit_asr_segment(
        claimed.id,
        "worker",
        worker_generation=1,
        text="完成",
    )

    progress = store.asr_segment_progress(job.id, "config-a")
    assert progress["total"] == 2
    assert progress["completed"] == 1
    assert progress["completed_audio_seconds"] == 20.0

    assert store.asr_total_budget_seconds(
        engine="sensevoice-small", device="cpu", audio_seconds=10.0
    ) == 300.0
    for rtf in (0.5, 1.0, 2.0, 3.0, 10.0):
        store.record_asr_performance(
            engine="sensevoice-small",
            device="cpu",
            audio_seconds=100.0,
            elapsed_seconds=100.0 * rtf,
        )
    assert store.asr_total_budget_seconds(
        engine="sensevoice-small", device="cpu", audio_seconds=1000.0
    ) == 4180.0

    assert store.clear_asr_checkpoints(job.id, "config-a") == 2
    assert store.list_asr_segments(job.id, "config-a") == []


def test_stale_run_checkpoints_are_removed_only_after_new_job_is_kept() -> None:
    store, old_job = _store_with_job()
    content = store.get_content(store.get_analysis_run(old_job.analysis_run_id).content_id)
    _old_rows = store.create_asr_segments(old_job.id, "old-config", _segments())
    _new_run, new_job = store.create_analysis_run(content.id, AnalysisSettings(model="new"))
    store.create_asr_segments(new_job.id, "new-config", _segments())

    stale_jobs = store.clear_stale_asr_checkpoints(
        content.id,
        keep_job_id=new_job.id,
    )

    assert [job.id for job in stale_jobs] == [old_job.id]
    assert store.list_asr_segments(old_job.id, "old-config") == []
    assert len(store.list_asr_segments(new_job.id, "new-config")) == 2
