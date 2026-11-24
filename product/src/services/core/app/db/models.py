"""SQLAlchemy persistence models.

The Markdown/JSON archive remains the portable source of truth. These tables
store operational state and rebuildable indexes only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ContentRow(Base):
    __tablename__ = "content_items"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acquired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acquisition_method: Mapped[str] = mapped_column(Text, nullable=False, default="adapter")
    # ``category`` remains a legacy compatibility column. New UI writes tags.
    category: Mapped[str] = mapped_column(String(120), nullable=False, default="未分类")
    favorite: Mapped[bool] = mapped_column(nullable=False, default=False)
    introduction: Mapped[str] = mapped_column(Text, nullable=False, default="")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FavoriteFolderRow(Base):
    """User-created folders used to further organize favorited content."""

    __tablename__ = "favorite_folders"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("favorite_folders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ContentFavoriteFolderRow(Base):
    """Many-to-many membership between content items and user folders."""

    __tablename__ = "content_favorite_folders"

    content_id: Mapped[str] = mapped_column(
        ForeignKey("content_items.id", ondelete="CASCADE"), primary_key=True
    )
    folder_id: Mapped[str] = mapped_column(
        ForeignKey("favorite_folders.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TagRow(Base):
    """User-owned content tags. The desktop app currently has one local user."""

    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_tags_user_name"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(80), nullable=False, default="local", index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ContentTagRow(Base):
    """Many-to-many membership between content items and tags."""

    __tablename__ = "content_tags"

    content_id: Mapped[str] = mapped_column(
        ForeignKey("content_items.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[str] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AnalysisRunRow(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    content_id: Mapped[str] = mapped_column(
        ForeignKey("content_items.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    settings_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class JobRow(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    analysis_run_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.id"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checkpoint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    queue_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class JobEventRow(Base):
    """Append-only lifecycle events used by the task timeline and diagnostics."""

    __tablename__ = "job_events"
    __table_args__ = (
        UniqueConstraint("job_id", "sequence", name="uq_job_events_job_sequence"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    progress: Mapped[int] = mapped_column(Integer, nullable=False)
    checkpoint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AsrSegmentRow(Base):
    """Durable, idempotent product-level ASR segment checkpoints."""

    __tablename__ = "asr_segments"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "config_fingerprint",
            "segment_index",
            name="uq_asr_segments_job_config_index",
        ),
    )

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    config_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    segment_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    end_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", index=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AsrPerformanceSampleRow(Base):
    """Successful local ASR timing samples used for a soft total budget."""

    __tablename__ = "asr_performance_samples"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    engine: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    device: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    audio_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    elapsed_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    rtf: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class ContentSummaryRow(Base):
    """Rebuildable searchable text for each content item (summary body)."""

    __tablename__ = "content_summaries"

    content_id: Mapped[str] = mapped_column(
        ForeignKey("content_items.id"), primary_key=True
    )
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    transcript_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AskIndexProfileRow(Base):
    """Identity for one rebuildable Q&A index configuration."""

    __tablename__ = "ask_index_profiles"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    engine: Mapped[str] = mapped_column(String(32), nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AskIndexContentRow(Base):
    """Per-content build state and source digest for one Q&A index profile."""

    __tablename__ = "ask_index_contents"

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("ask_index_profiles.id", ondelete="CASCADE"), primary_key=True
    )
    content_id: Mapped[str] = mapped_column(
        ForeignKey("content_items.id", ondelete="CASCADE"), primary_key=True
    )
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chunking_input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chunking_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    chunking_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    chunking_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunking_input_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunking_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunking_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chunking_trace: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AskIndexChunkRow(Base):
    """One searchable span with its original source and location mapping."""

    __tablename__ = "ask_index_chunks"
    __table_args__ = (
        UniqueConstraint("stable_id", name="uq_ask_index_chunks_stable_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stable_id: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("ask_index_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content_id: Mapped[str] = mapped_column(
        ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    location_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    source_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    chunk_ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    start_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)


class SummaryVersionRow(Base):
    __tablename__ = "summary_versions"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    content_id: Mapped[str] = mapped_column(
        ForeignKey("content_items.id"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_version_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    template: Mapped[str] = mapped_column(String(64), nullable=False)
    chapter_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_start_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_end_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    summary_strength: Mapped[str | None] = mapped_column(String(16), nullable=True)
    summary_style: Mapped[str | None] = mapped_column(String(32), nullable=True)
    material_level: Mapped[str | None] = mapped_column(String(8), nullable=True)
    source_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_scope: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    processed_source_refs: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    expected_source_refs: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RagTopicRow(Base):
    __tablename__ = "rag_topics"

    id: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    catalog_version: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ContentTopicRow(Base):
    __tablename__ = "content_rag_topics"

    content_id: Mapped[str] = mapped_column(
        ForeignKey("content_items.id", ondelete="CASCADE"), primary_key=True
    )
    topic_id: Mapped[str] = mapped_column(
        ForeignKey("rag_topics.id"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(String(12), nullable=False)
    discussion: Mapped[str] = mapped_column(String(16), nullable=False)
    source_version: Mapped[str] = mapped_column(String(80), nullable=False)
    source_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="confirmed")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RagCoverageRow(Base):
    __tablename__ = "rag_coverage"

    content_id: Mapped[str] = mapped_column(
        ForeignKey("content_items.id", ondelete="CASCADE"), primary_key=True
    )
    source_version: Mapped[str] = mapped_column(String(80), nullable=False)
    material_level: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    trace: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RagDetailTagRow(Base):
    __tablename__ = "rag_detail_tags"
    __table_args__ = (
        UniqueConstraint("normalized_name", "short_definition", name="uq_rag_detail_name_definition"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(16), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    short_definition: Mapped[str] = mapped_column(String(120), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    extractor_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_reviewed: Mapped[bool] = mapped_column(nullable=False, default=False)
    redirected_to: Mapped[str | None] = mapped_column(String(80), nullable=True)
    review_trace: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    last_qualified_query_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RagDeveloperTagReviewRow(Base):
    __tablename__ = "rag_developer_tag_reviews"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    tag_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reviewer: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    candidate_name: Mapped[str] = mapped_column(String(16), nullable=False)
    candidate_definition: Mapped[str] = mapped_column(String(120), nullable=False)
    same_concept: Mapped[bool] = mapped_column(nullable=False)
    canonical_tag_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    material_evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ContentRagDetailTagRow(Base):
    __tablename__ = "content_rag_detail_tags"
    __table_args__ = (UniqueConstraint("content_id", "tag_id", name="uq_content_rag_detail_tag"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    content_id: Mapped[str] = mapped_column(
        ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tag_id: Mapped[str] = mapped_column(
        ForeignKey("rag_detail_tags.id", ondelete="CASCADE"), nullable=False, index=True
    )
    topic_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    source_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    source_version: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="candidate")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RagSessionRow(Base):
    __tablename__ = "rag_sessions"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    scope: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RagQueryRow(Base):
    __tablename__ = "rag_queries"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("rag_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    scope_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    trace: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    cancel_requested: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RagScanItemRow(Base):
    __tablename__ = "rag_scan_items"
    __table_args__ = (UniqueConstraint("query_id", "content_id", name="uq_rag_scan_query_content"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    query_id: Mapped[str] = mapped_column(
        ForeignKey("rag_queries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_version: Mapped[str] = mapped_column(String(80), nullable=False)
    cursor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    completed: Mapped[bool] = mapped_column(nullable=False, default=False)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RagFeedbackEventRow(Base):
    __tablename__ = "rag_feedback_events"
    __table_args__ = (UniqueConstraint("query_id", "tag_id", "content_id", name="uq_rag_tag_feedback_event"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    query_id: Mapped[str] = mapped_column(
        ForeignKey("rag_queries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tag_id: Mapped[str] = mapped_column(
        ForeignKey("rag_detail_tags.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content_id: Mapped[str] = mapped_column(
        ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    helpful: Mapped[bool] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RagAnswerFeedbackRow(Base):
    __tablename__ = "rag_answer_feedback"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    query_id: Mapped[str] = mapped_column(
        ForeignKey("rag_queries.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    helpful: Mapped[bool] = mapped_column(nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SummaryFeedbackRow(Base):
    __tablename__ = "summary_feedback"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    content_id: Mapped[str] = mapped_column(
        ForeignKey("content_items.id"), nullable=False, index=True
    )
    version_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class JobFeedbackRow(Base):
    __tablename__ = "job_feedback"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), nullable=False, index=True)
    content_id: Mapped[str] = mapped_column(
        ForeignKey("content_items.id"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AppSettingRow(Base):
    """Local user settings such as product-owned platform session credentials."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PlatformConnectionRow(Base):
    """Metadata for an explicitly connected platform session.

    The first desktop implementation stores the selected browser session,
    never the cookie values themselves. Platform adapters validate that
    session before a link job is created.
    """

    __tablename__ = "platform_connections"

    platform: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    auth_type: Mapped[str] = mapped_column(String(32), nullable=False)
    account_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    browser: Mapped[str | None] = mapped_column(String(32), nullable=True)
    browser_profile: Mapped[str | None] = mapped_column(String(200), nullable=True)
    login_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
