"""M0 domain models.

These objects intentionally have no database or framework dependency. They are the
contract shared by persistence, adapters, workflows and the desktop API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class ContentKind(StrEnum):
    VIDEO = "video"
    AUDIO = "audio"
    ARTICLE = "article"
    IMAGE = "image"
    PDF = "pdf"


class SourcePlatform(StrEnum):
    LOCAL = "local"
    BILIBILI = "bilibili"
    YOUTUBE = "youtube"
    ZHIHU = "zhihu"
    XIAOHONGSHU = "xiaohongshu"
    WECHAT = "wechat"
    DOUYIN = "douyin"
    WEB = "web"


class SummaryStrength(StrEnum):
    QUICK = "quick"
    STANDARD = "standard"
    DEEP = "deep"


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """Evidence for where a content item came from."""

    platform: SourcePlatform
    canonical_url: str | None = None
    thumbnail_url: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    acquired_at: datetime = field(default_factory=utc_now)
    acquisition_method: str = "adapter"


@dataclass(slots=True)
class ContentItem:
    id: str
    kind: ContentKind
    title: str
    source: SourceRecord
    language: str | None = None
    duration_seconds: float | None = None
    content_hash: str | None = None
    category: str = "未分类"
    tags: tuple[str, ...] = ()
    introduction: str = ""
    favorite: bool = False
    deleted_at: datetime | None = None
    processing_model: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    @classmethod
    def create(
        cls,
        *,
        kind: ContentKind,
        title: str,
        source: SourceRecord,
        language: str | None = None,
        duration_seconds: float | None = None,
        content_hash: str | None = None,
        category: str = "未分类",
        tags: tuple[str, ...] = (),
        introduction: str = "",
        favorite: bool = False,
        deleted_at: datetime | None = None,
        processing_model: str | None = None,
    ) -> ContentItem:
        if not title.strip():
            raise ValueError("content title must not be empty")
        if duration_seconds is not None and duration_seconds < 0:
            raise ValueError("duration_seconds must not be negative")
        clean_introduction = introduction.strip()
        if len(clean_introduction) > 30:
            raise ValueError("introduction must be at most 30 characters")
        return cls(
            id=new_id("content"),
            kind=kind,
            title=title.strip(),
            source=source,
            language=language,
            duration_seconds=duration_seconds,
            content_hash=content_hash,
            category=category.strip() or "未分类",
            tags=tuple(dict.fromkeys(tag.strip() for tag in tags if tag.strip())),
            introduction=clean_introduction,
            favorite=favorite,
            deleted_at=deleted_at,
            processing_model=processing_model,
        )


@dataclass(frozen=True, slots=True)
class AnalysisSettings:
    """Immutable settings snapshot for one AnalysisRun."""

    model: str
    strength: SummaryStrength = SummaryStrength.STANDARD
    language: str | None = None
    prompt_version: str = "summary-v1"
    asr_engine: str | None = None
    asr_config: dict[str, str] | None = None
    max_chunk_tokens: int = 800
    summary_engine: str = "openai-compatible"
    summary_provider: str = "openai-compatible"
    summary_template: str = "general"
    summary_style: str = "general"
    summary_config: dict[str, Any] | None = None
    summary_prompt: str | None = None
    summary_prompt_hash: str | None = None
    summary_skill: dict[str, Any] | None = None
    extra_instruction: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "strength": self.strength.value,
            "language": self.language,
            "prompt_version": self.prompt_version,
            "asr_engine": self.asr_engine,
            "asr_config": dict(self.asr_config or {}),
            "max_chunk_tokens": self.max_chunk_tokens,
            "summary_engine": self.summary_engine,
            "summary_provider": self.summary_provider,
            "summary_template": self.summary_template,
            "summary_style": self.summary_style,
            "summary_config": dict(self.summary_config or {}),
            "summary_prompt": self.summary_prompt,
            "summary_prompt_hash": self.summary_prompt_hash,
            "summary_skill": dict(self.summary_skill or {}) or None,
            "extra_instruction": self.extra_instruction,
        }


@dataclass(slots=True)
class AnalysisRun:
    """One isolated analysis context for one content item."""

    content_id: str
    settings_snapshot: dict[str, Any]
    id: str = field(default_factory=lambda: new_id("run"))
    status: str = "queued"
    prompt_version: str = "summary-v1"
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    error_code: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if not self.content_id:
            raise ValueError("AnalysisRun requires a content_id")
        # Copy at the boundary so global settings changes cannot mutate a run.
        self.settings_snapshot = dict(self.settings_snapshot)

    @classmethod
    def create(cls, content_id: str, settings: AnalysisSettings) -> AnalysisRun:
        return cls(
            content_id=content_id,
            settings_snapshot=settings.as_dict(),
            prompt_version=settings.prompt_version,
        )


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    start_seconds: float
    end_seconds: float
    text: str
    speaker: str | None = None

    def __post_init__(self) -> None:
        if self.start_seconds < 0 or self.end_seconds < self.start_seconds:
            raise ValueError("invalid transcript segment time range")
        if not self.text.strip():
            raise ValueError("transcript segment text must not be empty")


@dataclass(frozen=True, slots=True)
class Transcript:
    language: str | None
    source_kind: str
    engine: str | None
    segments: tuple[TranscriptSegment, ...]
    version: str = "transcript-v1"
    position_kind: str = "timestamp"
    source_coverage_complete: bool | None = None


@dataclass(frozen=True, slots=True)
class Chunk:
    ordinal: int
    start_seconds: float
    end_seconds: float
    text: str
    text_hash: str
    token_count: int
    chapter_title: str | None = None


@dataclass(frozen=True, slots=True)
class Artifact:
    type: str
    path: str
    content_hash: str
    schema_version: str = "archive-v1"
    derived_from: str | None = None


@dataclass(frozen=True, slots=True)
class TopicSynthesis:
    """Explicit multi-content context; never inferred from the previous task."""

    content_ids: tuple[str, ...]
    instructions: str
    id: str = field(default_factory=lambda: new_id("topic"))
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.content_ids:
            raise ValueError("TopicSynthesis requires at least one content_id")
        if len(set(self.content_ids)) != len(self.content_ids):
            raise ValueError("TopicSynthesis content_ids must be unique")
        if not self.instructions.strip():
            raise ValueError("TopicSynthesis instructions must not be empty")
