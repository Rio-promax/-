from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.domain.jobs import JobErrorCode, JobState, StaleJobAttemptError
from app.workflows.diagnostics import recovery_guidance


@pytest.mark.parametrize(
    ("error_code", "action"),
    [
        ("auth_required", "login_recheck"),
        ("transcript_incomplete", "change_source"),
        ("asr_timeout", "retry"),
        ("transient_network", "retry"),
        ("unknown", "diagnostics"),
    ],
)
def test_r4_error_codes_have_one_executable_recovery_action(
    error_code: str,
    action: str,
) -> None:
    guidance = recovery_guidance(error_code)

    assert guidance["action"] == action
    assert guidance["suggestion"]


def _client() -> TestClient:
    return TestClient(create_app("sqlite:///:memory:"))


def _create_job(client: TestClient) -> str:
    content = client.post(
        "/api/v1/contents",
        json={"kind": "article", "title": "M4 状态语义", "platform": "web"},
    )
    assert content.status_code == 201
    run = client.post(
        f"/api/v1/contents/{content.json()['id']}/analysis-runs",
        json={"model": "test-model"},
    )
    assert run.status_code == 201
    return run.json()["job"]["id"]


_PAUSE_CASES = [
    (JobState.ACQUIRING, "source_ready", 10, "acquiring", "extracting"),
    (JobState.EXTRACTING, "text_loaded", 25, "extracting", "transcribing"),
    (JobState.TRANSCRIBING, "transcribing", 40, "extracting", "transcribing"),
    (JobState.SUMMARIZING, "summarizing", 70, "chunking", "summarizing"),
    (JobState.ARCHIVING, "archiving", 85, "summarizing", "archiving"),
]


def _prepare_running_job(
    client: TestClient,
    job_id: str,
    state: JobState,
    checkpoint: str,
    progress: int,
):
    store = client.app.state.store
    job = store.get_job(job_id)
    job.claim("m4-worker")
    if state is not JobState.ACQUIRING:
        for next_state in (
            JobState.EXTRACTING,
            JobState.TRANSCRIBING,
            JobState.CHUNKING,
            JobState.SUMMARIZING,
            JobState.ARCHIVING,
        ):
            job.transition(next_state)
            if next_state is state:
                break
    assert job.state is state
    job.update_progress(progress, checkpoint=checkpoint)
    store.save_job(job)
    return job


@pytest.mark.parametrize(
    ("state", "checkpoint", "progress", "stable_stage", "resume_stage"),
    _PAUSE_CASES,
)
def test_r5_pause_resume_exposes_stable_and_resume_stages_and_rejects_stale_attempt(
    state: JobState,
    checkpoint: str,
    progress: int,
    stable_stage: str,
    resume_stage: str,
) -> None:
    client = _client()
    job_id = _create_job(client)
    current = _prepare_running_job(client, job_id, state, checkpoint, progress)
    stale_attempt = deepcopy(current)

    paused = client.post(f"/api/v1/jobs/{job_id}/pause")

    assert paused.status_code == 200
    paused_payload = paused.json()
    assert paused_payload["state"] == "paused"
    assert paused_payload["execution_state"] == "paused"
    assert paused_payload["queue_position"] is None
    assert paused_payload["last_stable_stage"] == stable_stage
    assert paused_payload["resume_stage"] == resume_stage
    with pytest.raises(StaleJobAttemptError):
        client.app.state.store.save_job(stale_attempt)

    # Keep this test focused on the API state transition; the queue runner is
    # covered separately and must not start a source-less workflow here.
    client.app.state.job_queue.submit = lambda *_args, **_kwargs: None
    resumed = client.post(f"/api/v1/jobs/{job_id}/resume")

    assert resumed.status_code == 200
    resumed_payload = resumed.json()
    assert resumed_payload["state"] == "queued"
    assert resumed_payload["queue_position"] is None
    assert resumed_payload["last_stable_stage"] == stable_stage
    assert resumed_payload["resume_stage"] == resume_stage
    assert client.app.state.store.get_job(job_id).state is JobState.QUEUED
    with pytest.raises(StaleJobAttemptError):
        client.app.state.store.save_job(stale_attempt)


def test_r5_cancel_clears_recovery_view_and_does_not_requeue() -> None:
    client = _client()
    job_id = _create_job(client)
    current = _prepare_running_job(
        client,
        job_id,
        JobState.SUMMARIZING,
        "summarizing",
        70,
    )
    stale_attempt = deepcopy(current)

    cancelled = client.post(f"/api/v1/jobs/{job_id}/cancel")

    assert cancelled.status_code == 200
    payload = cancelled.json()
    assert payload["state"] == "cancelled"
    assert payload["queue_position"] is None
    assert payload["last_stable_stage"] is None
    assert payload["resume_stage"] is None
    assert payload["recovery_action"] is None
    with pytest.raises(StaleJobAttemptError):
        client.app.state.store.save_job(stale_attempt)

    events = client.get(f"/api/v1/jobs/{job_id}/events").json()
    assert events[-1]["event_type"] == "cancelled"
    assert events[-1]["message"] == "任务已取消"
    assert "恢复" not in events[-1]["message"]
    assert "重新排队" not in events[-1]["message"]


def test_r4_diagnostic_response_exposes_recovery_action() -> None:
    client = _client()
    job_id = _create_job(client)
    store = client.app.state.store
    job = store.get_job(job_id)
    job.error_code = JobErrorCode.TRANSCRIPT_INCOMPLETE
    job.error_message = "转写不足"
    job.state = JobState.FAILED
    store.save_job(job)

    response = client.get(f"/api/v1/jobs/{job_id}/diagnostics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["recovery_action"] == "change_source"
    assert "请重试" not in payload["recovery_suggestion"]
