"""Persistent-job state machine independent from a queue implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from .models import new_id


class JobState(StrEnum):
    QUEUED = "queued"
    ACQUIRING = "acquiring"
    EXTRACTING = "extracting"
    TRANSCRIBING = "transcribing"
    CHUNKING = "chunking"
    SUMMARIZING = "summarizing"
    ARCHIVING = "archiving"
    INDEXING = "indexing"
    COMPLETED = "completed"
    PAUSED = "paused"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobErrorCode(StrEnum):
    AUTH_REQUIRED = "auth_required"
    ACCESS_RESTRICTED = "access_restricted"
    SOURCE_NOT_FOUND = "source_not_found"
    UNSUPPORTED_SOURCE = "unsupported_source"
    TRANSIENT_NETWORK = "transient_network"
    MODEL_UNAVAILABLE = "model_unavailable"
    INVALID_OUTPUT = "invalid_output"
    SUMMARY_GENERATION_FAILED = "summary_generation_failed"
    TRANSCRIPT_INCOMPLETE = "transcript_incomplete"
    DISK_SPACE = "disk_space"
    ASR_RUNTIME_UNAVAILABLE = "asr_runtime_unavailable"
    ASR_LOCAL_MODEL_NOT_INSTALLED = "asr_local_model_not_installed"
    ASR_CLOUD_NOT_CONFIGURED = "asr_cloud_not_configured"
    ASR_TIMEOUT = "asr_timeout"
    UNKNOWN = "unknown"


class InvalidTransitionError(ValueError):
    """Raised when a workflow attempts an illegal state transition."""


class StaleJobAttemptError(RuntimeError):
    """Raised when an old worker tries to persist after losing execution ownership."""


_STABLE_CHECKPOINT_BY_CHECKPOINT = {
    "source_ready": "source_ready",
    "acquiring": "source_ready",
    "extracting": "source_ready",
    "text_loaded": "text_loaded",
    "transcribing": "text_loaded",
    "transcript_ready": "transcript_ready",
    "chunking": "transcript_ready",
    "chunks_ready": "chunks_ready",
    "summarizing": "chunks_ready",
    "summary_ready": "summary_ready",
    "archiving": "summary_ready",
    "indexing": "summary_ready",
    "indexed": "indexed",
}


def checkpoint_config_fingerprint(
    *,
    model: str,
    prompt_hash: str,
    max_chunk_tokens: int,
    language: str | None,
) -> str:
    """R8：续跑产物所依赖的配置身份；模型或提示词变化时旧摘要失效。"""
    import hashlib
    import json

    payload = {
        "model": model,
        "prompt_hash": prompt_hash,
        "max_chunk_tokens": max_chunk_tokens,
        "language": language,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def stable_checkpoint_for(checkpoint: str | None) -> str | None:
    """Return the last committed checkpoint for a current workflow marker."""

    if not checkpoint:
        return None
    return _STABLE_CHECKPOINT_BY_CHECKPOINT.get(checkpoint)


_TERMINAL_STATES = {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.QUEUED: frozenset({JobState.ACQUIRING, JobState.PAUSED, JobState.CANCELLED}),
    JobState.ACQUIRING: frozenset(
        {JobState.EXTRACTING, JobState.PAUSED, JobState.FAILED, JobState.CANCELLED}
    ),
    JobState.EXTRACTING: frozenset(
        {JobState.TRANSCRIBING, JobState.PAUSED, JobState.FAILED, JobState.CANCELLED}
    ),
    JobState.TRANSCRIBING: frozenset(
        {JobState.CHUNKING, JobState.PAUSED, JobState.FAILED, JobState.CANCELLED}
    ),
    JobState.CHUNKING: frozenset(
        {JobState.SUMMARIZING, JobState.PAUSED, JobState.FAILED, JobState.CANCELLED}
    ),
    JobState.SUMMARIZING: frozenset(
        {JobState.ARCHIVING, JobState.PAUSED, JobState.FAILED, JobState.CANCELLED}
    ),
    JobState.ARCHIVING: frozenset(
        {JobState.INDEXING, JobState.PAUSED, JobState.FAILED, JobState.CANCELLED}
    ),
    JobState.INDEXING: frozenset(
        {JobState.COMPLETED, JobState.PAUSED, JobState.FAILED, JobState.CANCELLED}
    ),
    JobState.PAUSED: frozenset({JobState.QUEUED, JobState.CANCELLED}),
    JobState.FAILED: frozenset({JobState.QUEUED, JobState.CANCELLED}),
    JobState.COMPLETED: frozenset(),
    JobState.CANCELLED: frozenset(),
}


@dataclass(slots=True)
class Job:
    type: str
    analysis_run_id: str
    id: str = field(default_factory=lambda: new_id("job"))
    state: JobState = JobState.QUEUED
    attempt: int = 0
    progress: int = 0
    checkpoint: str | None = None
    lease_until: datetime | None = None
    worker_id: str | None = None
    error_code: JobErrorCode | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    priority: int = 0
    queue_position: int | None = None

    def transition(self, target: JobState) -> None:
        if target not in _TRANSITIONS[self.state]:
            raise InvalidTransitionError(f"cannot transition {self.state} -> {target}")
        self.state = target
        if target is JobState.ACQUIRING and self.started_at is None:
            self.started_at = datetime.now(UTC)
        if target is JobState.PAUSED:
            self.lease_until = None
            self.worker_id = None
            self.queue_position = None
        if target in _TERMINAL_STATES:
            self.lease_until = None
            self.worker_id = None
            self.queue_position = None
            self.completed_at = self.completed_at or datetime.now(UTC)
        elif target is JobState.QUEUED:
            self.completed_at = None

    def transition_if_possible_to_queued(self) -> None:
        """Resume a paused job into the waiting queue when explicitly requested."""

        if self.state is JobState.PAUSED:
            self.transition(JobState.QUEUED)

    def claim(
        self, worker_id: str, *, lease_seconds: int = 60, now: datetime | None = None
    ) -> None:
        if self.state is not JobState.QUEUED:
            raise InvalidTransitionError(f"only queued jobs can be claimed, got {self.state}")
        if not worker_id.strip():
            raise ValueError("worker_id must not be empty")
        now = now or datetime.now(UTC)
        self.attempt += 1
        self.worker_id = worker_id
        self.lease_until = now + timedelta(seconds=lease_seconds)
        self.queue_position = None
        self.started_at = self.started_at or now
        self.transition(JobState.ACQUIRING)

    def heartbeat(self, *, lease_seconds: int = 60, now: datetime | None = None) -> None:
        if self.worker_id is None or self.lease_until is None:
            raise ValueError("job has no active lease")
        now = now or datetime.now(UTC)
        self.lease_until = now + timedelta(seconds=lease_seconds)

    def update_progress(self, progress: int, checkpoint: str | None = None) -> None:
        if not 0 <= progress <= 100:
            raise ValueError("progress must be between 0 and 100")
        if progress < self.progress:
            raise ValueError("progress cannot move backwards")
        self.progress = progress
        if checkpoint is not None:
            self.checkpoint = checkpoint

    def fail(self, code: JobErrorCode, message: str) -> None:
        if self.state in _TERMINAL_STATES:
            raise InvalidTransitionError(f"terminal job cannot fail: {self.state}")
        self.error_code = code
        self.error_message = message
        self.transition(JobState.FAILED)

    def recover_if_expired(self, *, now: datetime | None = None) -> bool:
        if self.lease_until is None or self.state in _TERMINAL_STATES:
            return False
        now = _as_utc(now or datetime.now(UTC))
        lease_until = _as_utc(self.lease_until)
        if lease_until > now:
            return False
        self.worker_id = None
        self.lease_until = None
        if self.state not in {JobState.PAUSED, JobState.FAILED}:
            self.state = JobState.QUEUED
            self.completed_at = None
        return True

    @property
    def elapsed_seconds(self) -> float | None:
        if self.started_at is None:
            return None
        started = _as_utc(self.started_at)
        end = _as_utc(self.completed_at) if self.completed_at else datetime.now(UTC)
        return max(0.0, (end - started).total_seconds())

    @property
    def is_terminal(self) -> bool:
        return self.state in _TERMINAL_STATES
