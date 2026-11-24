from datetime import UTC, datetime

import pytest
from app.domain.jobs import InvalidTransitionError, Job, JobState
from app.domain.models import (
    AnalysisRun,
    AnalysisSettings,
    ContentItem,
    ContentKind,
    SourcePlatform,
    SourceRecord,
    SummaryStrength,
    TopicSynthesis,
)


def make_content(title: str = "课程") -> ContentItem:
    return ContentItem.create(
        kind=ContentKind.VIDEO,
        title=title,
        source=SourceRecord(SourcePlatform.LOCAL),
    )


def test_analysis_run_copies_settings_for_context_isolation() -> None:
    settings = AnalysisSettings(model="test-model", strength=SummaryStrength.DEEP)
    run = AnalysisRun.create("content-1", settings)
    settings_map = run.settings_snapshot
    settings_map["model"] = "other-model"

    assert run.settings_snapshot["model"] == "other-model"
    assert settings.model == "test-model"
    assert run.content_id == "content-1"


def test_topic_synthesis_requires_explicit_unique_content_ids() -> None:
    synthesis = TopicSynthesis(("content-1", "content-2"), "比较两篇内容")
    assert synthesis.content_ids == ("content-1", "content-2")

    with pytest.raises(ValueError, match="unique"):
        TopicSynthesis(("content-1", "content-1"), "比较")


def test_content_validates_title_and_duration() -> None:
    with pytest.raises(ValueError, match="title"):
        make_content(" ")
    with pytest.raises(ValueError, match="duration"):
        ContentItem.create(
            kind=ContentKind.VIDEO,
            title="视频",
            source=SourceRecord(SourcePlatform.LOCAL),
            duration_seconds=-1,
        )


def test_job_claim_progress_and_recovery() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    job = Job(type="analyze", analysis_run_id="run-1")
    job.claim("worker-1", lease_seconds=10, now=now)
    assert job.state is JobState.ACQUIRING
    assert job.attempt == 1
    job.update_progress(20, checkpoint="acquired")
    assert job.checkpoint == "acquired"
    assert job.recover_if_expired(now=now) is False
    assert job.recover_if_expired(now=now.replace(second=11)) is True
    assert job.state is JobState.QUEUED
    assert job.worker_id is None


def test_job_rejects_invalid_transition() -> None:
    job = Job(type="analyze", analysis_run_id="run-1")
    with pytest.raises(InvalidTransitionError):
        job.transition(JobState.COMPLETED)
