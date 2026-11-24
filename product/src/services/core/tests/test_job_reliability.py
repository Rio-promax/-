from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.adapters.sources.local import prepare_local_import
from app.api.main import create_app
from app.domain.models import AnalysisSettings
from app.knowledge.transcript import transcript_to_dict
from app.workflows.queue import LocalJobQueue


def test_job_response_exposes_execution_timing_and_priority() -> None:
    client = TestClient(create_app("sqlite:///:memory:"))
    content = client.post(
        "/api/v1/contents",
        json={"kind": "article", "title": "排队内容", "platform": "local"},
    ).json()

    response = client.post(
        f"/api/v1/contents/{content['id']}/analysis-runs",
        json={"model": "test-model", "priority": 7},
    )

    assert response.status_code == 201
    job = response.json()["job"]
    assert job["created_at"]
    assert job["started_at"] is None
    assert job["completed_at"] is None
    assert job["elapsed_seconds"] is None
    assert job["priority"] == 7
    assert job["queue_position"] is None

    stored = client.app.state.store.get_job(job["id"])
    stored.claim("test-worker")
    client.app.state.store.save_job(stored)
    assert client.app.state.store.get_job(job["id"]).elapsed_seconds is not None


def test_expired_job_reuses_transcript_checkpoint(
    tmp_path, monkeypatch
) -> None:
    from app.workflows import analyze

    class FakeSummarizer:
        def __init__(self, _settings) -> None:
            pass

        def summarize_chunks(self, chunks, *, title, strength, prompt, skill=None):
            text = "\n".join(chunk.text for chunk in chunks)
            return SimpleNamespace(
                markdown=(
                    "# 内容总结\n\n## 概览\n\n"
                    + text
                    + "\n\n## 关键要点\n\n- 已恢复\n\n## 分段笔记\n\n- 已恢复\n"
                ),
                overview="已恢复",
            )

    monkeypatch.setattr(analyze, "OpenAICompatibleSummarizer", FakeSummarizer)
    client = TestClient(create_app("sqlite:///:memory:", tmp_path / "archive"))
    source = prepare_local_import(
        source_path=None,
        text="需要保留的中间转写。",
        title="可恢复任务",
        language=None,
    )
    workflow = client.app.state.workflow
    _, _, job = workflow.submit(source, AnalysisSettings(model="test-model"))
    old = datetime.now(UTC) - timedelta(minutes=10)
    job.claim("crashed-worker", lease_seconds=1, now=old)
    job.update_progress(45, checkpoint="transcript_ready")
    workflow._write_checkpoint(job, "transcript", transcript_to_dict(source.transcript))
    client.app.state.store.save_job(job)

    recovered = client.app.state.store.recover_expired_jobs(now=datetime.now(UTC))
    assert [item.id for item in recovered] == [job.id]
    assert client.app.state.store.get_job(job.id).state.value == "queued"

    workflow.run(job.id, None)

    final_job = client.app.state.store.get_job(job.id)
    assert final_job.state.value == "completed"
    assert final_job.attempt == 2
    assert final_job.metadata["transcript_path"]


def test_local_queue_honors_priority_after_active_job_finishes() -> None:
    jobs = {
        "first": SimpleNamespace(queue_position=None, priority=0),
        "second": SimpleNamespace(queue_position=None, priority=0),
    }

    class Store:
        def get_job(self, job_id):
            return jobs[job_id]

        def save_job(self, job):
            return job

    queue = LocalJobQueue(Store(), lambda: 1)
    started = Event()
    release = Event()
    execution = []

    def runner(job_id, _transcript):
        execution.append(job_id)
        if job_id == "first":
            started.set()
            release.wait(timeout=3)

    thread = Thread(target=lambda: queue.submit("first", None, runner), daemon=True)
    thread.start()
    assert started.wait(timeout=3)
    queue.submit("second", None, runner, priority=5)
    assert jobs["second"].queue_position == 1
    release.set()
    thread.join(timeout=3)

    assert execution == ["first", "second"]