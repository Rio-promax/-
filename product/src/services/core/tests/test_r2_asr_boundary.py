from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread

import pytest

from app.adapters.sources.prepared import PreparedSource
from app.db.store import SQLiteStore
from app.domain.jobs import JobErrorCode, JobState
from app.domain.models import AnalysisSettings, ContentKind, SourcePlatform
from app.workflows import analyze
from app.workflows.analyze import AnalysisWorkflow
from app.workflows.queue import LocalJobQueue


@pytest.fixture
def blocking_asr_endpoint():
    entered = Event()
    release = Event()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            entered.set()
            release.wait(5)
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"segments":[{"start":0,"end":1,"text":"ok"}]}')
            except OSError:
                pass

        def log_message(self, _format: str, *_args) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield (
            f"http://127.0.0.1:{server.server_port}/v1/audio/transcriptions",
            entered,
            release,
        )
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def _source(audio_path: Path, suffix: str) -> PreparedSource:
    return PreparedSource(
        kind=ContentKind.VIDEO,
        title=f"R2 {suffix}",
        transcript=None,
        content_hash=f"r2-{suffix}",
        source_path=None,
        source_url=f"https://example.test/r2/{suffix}",
        acquisition_method="test",
        platform=SourcePlatform.WEB,
        duration_seconds=1.0,
        audio_path=str(audio_path),
    )


def _workflow_with_two_jobs(
    tmp_path: Path,
    endpoint: str,
) -> tuple[SQLiteStore, AnalysisWorkflow, object, object]:
    audio_path = tmp_path / "source.m4a"
    audio_path.write_bytes(b"controlled-audio")
    # The test intentionally overlaps a queue thread and the controlling
    # thread; a file-backed database avoids StaticPool's single-connection
    # in-memory race while keeping the fixture isolated per test.
    store = SQLiteStore(f"sqlite:///{(tmp_path / 'r2.sqlite').as_posix()}")
    store.set_setting("asr_engine", "cloud")
    store.set_setting("asr_cloud_api_url", endpoint)
    store.set_setting("asr_cloud_model", "test-model")
    store.set_setting("asr_cloud_api_key", "test-key")
    workflow = AnalysisWorkflow(store, tmp_path / "archive")
    _, _, first = workflow.submit(
        _source(audio_path, "first"),
        AnalysisSettings(model="summary-model"),
    )
    _, _, second = workflow.submit(
        _source(audio_path, "second"),
        AnalysisSettings(model="summary-model"),
    )
    return store, workflow, first, second


def _run_queue_with_blocked_asr(
    tmp_path: Path,
    endpoint: str,
    entered: Event,
    release: Event,
    monkeypatch: pytest.MonkeyPatch,
    *,
    action: str | None,
):
    store, workflow, first, second = _workflow_with_two_jobs(tmp_path, endpoint)
    monkeypatch.setattr(analyze, "ASR_CALL_DEADLINE_SECONDS", 1.0)
    stopped = Event()
    next_started = Event()
    original_stop = analyze._stop_asr_process

    def track_stop(process) -> None:
        original_stop(process)
        stopped.set()

    monkeypatch.setattr(analyze, "_stop_asr_process", track_stop)

    def runner(job_id: str, _transcript) -> None:
        if job_id == first.id:
            workflow.run(job_id, None)
            return
        next_started.set()
        job = store.get_job(job_id)
        job.claim("next-worker")
        store.save_job(job)

    queue = LocalJobQueue(store)
    worker = Thread(target=lambda: queue.submit(first.id, None, runner), daemon=True)
    worker.start()
    assert entered.wait(5)
    queue.submit(second.id, None, runner)
    assert queue.active_job_id() == first.id
    assert not next_started.wait(0.15)

    if action == "pause":
        first_job = store.get_job(first.id)
        first_job.transition(JobState.PAUSED)
        store.save_job(first_job)
        queue.remove(first.id)
    elif action == "cancel":
        first_job = store.get_job(first.id)
        first_job.transition(JobState.CANCELLED)
        store.save_job(first_job)
        queue.remove(first.id)

    assert worker.join(6) is None
    assert not worker.is_alive()
    assert stopped.is_set()
    assert next_started.is_set()
    assert queue.active_job_id() is None
    assert store.get_job(second.id).state is JobState.ACQUIRING
    release.set()
    return store, first, second


def test_r2_asr_timeout_stops_child_before_first_waiting_job(
    tmp_path: Path,
    blocking_asr_endpoint,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint, entered, release = blocking_asr_endpoint
    store, first, second = _run_queue_with_blocked_asr(
        tmp_path,
        endpoint,
        entered,
        release,
        monkeypatch,
        action=None,
    )

    failed = store.get_job(first.id)
    assert failed.state is JobState.FAILED
    assert failed.error_code is JobErrorCode.ASR_TIMEOUT
    assert failed.checkpoint == "transcribing"
    assert store.get_job(second.id).attempt == 1


def test_r2_isolated_asr_returns_transcript_after_child_completion(
    tmp_path: Path,
    blocking_asr_endpoint,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint, entered, release = blocking_asr_endpoint
    release.set()
    _store, workflow, first, _second = _workflow_with_two_jobs(tmp_path, endpoint)
    monkeypatch.setattr(analyze, "ASR_CALL_DEADLINE_SECONDS", 1.0)

    job = _store.get_job(first.id)
    job.claim("test-worker")
    _store.save_job(job)
    transcript = workflow._transcribe(job)

    assert entered.wait(5)
    assert transcript.segments[0].text == "ok"


@pytest.mark.parametrize(
    ("action", "expected_state"),
    [("pause", JobState.PAUSED), ("cancel", JobState.CANCELLED)],
)
def test_r2_stop_action_rejects_old_asr_writeback_and_releases_queue(
    tmp_path: Path,
    blocking_asr_endpoint,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    expected_state: JobState,
) -> None:
    endpoint, entered, release = blocking_asr_endpoint
    store, first, _second = _run_queue_with_blocked_asr(
        tmp_path,
        endpoint,
        entered,
        release,
        monkeypatch,
        action=action,
    )

    stopped = store.get_job(first.id)
    assert stopped.state is expected_state
    assert stopped.checkpoint == "transcribing"
    assert stopped.progress == 40
