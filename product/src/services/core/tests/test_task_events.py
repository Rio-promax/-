import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.domain.jobs import JobErrorCode, JobState


def _client() -> TestClient:
    return TestClient(create_app("sqlite:///:memory:"))


def _create_job(client: TestClient) -> str:
    content = client.post(
        "/api/v1/contents",
        json={"kind": "article", "title": "事件测试", "platform": "local"},
    )
    assert content.status_code == 201
    run = client.post(
        f"/api/v1/contents/{content.json()['id']}/analysis-runs",
        json={"model": "test-model"},
    )
    assert run.status_code == 201
    return run.json()["job"]["id"]


def test_job_events_capture_order_attempt_and_utc_time() -> None:
    client = _client()
    job_id = _create_job(client)
    store = client.app.state.store
    job = store.get_job(job_id)

    job.claim("test-worker", now=datetime(2026, 1, 1, tzinfo=UTC))
    store.save_job(job)
    job.update_progress(35, checkpoint="transcript_ready")
    store.save_job(job)
    job.fail(JobErrorCode.SUMMARY_GENERATION_FAILED, "模拟失败")
    store.save_job(job)

    response = client.get(f"/api/v1/jobs/{job_id}/events")
    assert response.status_code == 200
    events = response.json()
    assert [event["sequence"] for event in events] == [1, 2, 3, 4]
    assert [event["event_type"] for event in events] == [
        "created",
        "started",
        "progress",
        "failed",
    ]
    assert [event["attempt"] for event in events] == [0, 1, 1, 1]
    assert events[0]["stage"] == "queue"
    assert events[2]["stage"] == "transcription"
    assert events[3]["error_code"] == "summary_generation_failed"
    assert all(
        datetime.fromisoformat(
            event["occurred_at"].replace("Z", "+00:00")
        ).tzinfo is not None
        for event in events
    )

    after_progress = client.get(
        f"/api/v1/jobs/{job_id}/events",
        params={"after_sequence": 2, "limit": 1},
    )
    assert after_progress.status_code == 200
    assert [event["sequence"] for event in after_progress.json()] == [3]


def test_diagnostics_include_task_events_without_raw_error_content() -> None:
    client = _client()
    job_id = _create_job(client)
    store = client.app.state.store
    job = store.get_job(job_id)
    job.state = JobState.FAILED
    job.error_code = JobErrorCode.UNKNOWN
    job.error_message = "private.mp4?api_key=secret"
    store.save_job(job)

    diagnostics = client.get(f"/api/v1/jobs/{job_id}/diagnostics")
    assert diagnostics.status_code == 200
    payload = diagnostics.json()
    assert payload["events"][-1]["event_type"] == "failed"
    assert "private.mp4" not in json.dumps(payload, ensure_ascii=False)
    assert "api_key" not in json.dumps(payload, ensure_ascii=False).lower()

    exported = client.get(f"/api/v1/jobs/{job_id}/diagnostics/export")
    assert exported.status_code == 200
    assert exported.json()["events"][-1]["sequence"] == payload["events"][-1]["sequence"]


def test_job_events_return_not_found_for_unknown_job() -> None:
    response = _client().get("/api/v1/jobs/missing/events")
    assert response.status_code == 404
