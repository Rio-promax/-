"""Persist RAG taxonomy, sessions, traces, feedback and resumable scan state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_rag_execution"
down_revision: str | Sequence[str] | None = "0012_asr_checkpoints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rag_topics",
        sa.Column("id", sa.String(8), primary_key=True),
        sa.Column("name", sa.String(40), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("catalog_version", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "content_rag_topics",
        sa.Column("content_id", sa.String(80), sa.ForeignKey("content_items.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("topic_id", sa.String(8), sa.ForeignKey("rag_topics.id"), primary_key=True),
        sa.Column("role", sa.String(12), nullable=False),
        sa.Column("discussion", sa.String(16), nullable=False),
        sa.Column("source_version", sa.String(80), nullable=False),
        sa.Column("source_refs", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="confirmed"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_content_rag_topics_topic_id", "content_rag_topics", ["topic_id"])
    op.create_table(
        "rag_coverage",
        sa.Column("content_id", sa.String(80), sa.ForeignKey("content_items.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("source_version", sa.String(80), nullable=False),
        sa.Column("material_level", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("trace", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "rag_detail_tags",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("display_name", sa.String(16), nullable=False),
        sa.Column("normalized_name", sa.String(64), nullable=False),
        sa.Column("short_definition", sa.String(120), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("extractor_model", sa.String(200), nullable=True),
        sa.Column("prompt_version", sa.String(80), nullable=True),
        sa.Column("last_qualified_query_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_reviewed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("redirected_to", sa.String(80), nullable=True),
        sa.Column("review_trace", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("normalized_name", "short_definition", name="uq_rag_detail_name_definition"),
    )
    op.create_index("ix_rag_detail_tags_normalized_name", "rag_detail_tags", ["normalized_name"])
    op.create_index("ix_rag_detail_tags_status", "rag_detail_tags", ["status"])
    op.create_table(
        "content_rag_detail_tags",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("content_id", sa.String(80), sa.ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tag_id", sa.String(80), sa.ForeignKey("rag_detail_tags.id", ondelete="CASCADE"), nullable=False),
        sa.Column("topic_ids", sa.JSON(), nullable=False),
        sa.Column("source_refs", sa.JSON(), nullable=False),
        sa.Column("source_version", sa.String(80), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("content_id", "tag_id", name="uq_content_rag_detail_tag"),
    )
    op.create_index("ix_content_rag_detail_tags_content_id", "content_rag_detail_tags", ["content_id"])
    op.create_index("ix_content_rag_detail_tags_tag_id", "content_rag_detail_tags", ["tag_id"])
    op.create_table(
        "rag_sessions",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("scope", sa.JSON(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "rag_queries",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("session_id", sa.String(80), sa.ForeignKey("rag_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("scope_snapshot", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("trace", sa.JSON(), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_rag_queries_session_id", "rag_queries", ["session_id"])
    op.create_index("ix_rag_queries_status", "rag_queries", ["status"])
    op.create_table(
        "rag_scan_items",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("query_id", sa.String(80), sa.ForeignKey("rag_queries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content_id", sa.String(80), nullable=False),
        sa.Column("source_version", sa.String(80), nullable=False),
        sa.Column("cursor", sa.String(120), nullable=True),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("query_id", "content_id", name="uq_rag_scan_query_content"),
    )
    op.create_index("ix_rag_scan_items_query_id", "rag_scan_items", ["query_id"])
    op.create_index("ix_rag_scan_items_content_id", "rag_scan_items", ["content_id"])
    op.create_table(
        "rag_feedback_events",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("query_id", sa.String(80), sa.ForeignKey("rag_queries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tag_id", sa.String(80), sa.ForeignKey("rag_detail_tags.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content_id", sa.String(80), sa.ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("helpful", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("query_id", "tag_id", "content_id", name="uq_rag_tag_feedback_event"),
    )
    op.create_index("ix_rag_feedback_events_query_id", "rag_feedback_events", ["query_id"])
    op.create_index("ix_rag_feedback_events_tag_id", "rag_feedback_events", ["tag_id"])
    op.create_index("ix_rag_feedback_events_content_id", "rag_feedback_events", ["content_id"])
    op.create_table(
        "rag_answer_feedback",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("query_id", sa.String(80), sa.ForeignKey("rag_queries.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("helpful", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    for index, table in (
        ("ix_rag_feedback_events_content_id", "rag_feedback_events"),
        ("ix_rag_feedback_events_tag_id", "rag_feedback_events"),
        ("ix_rag_feedback_events_query_id", "rag_feedback_events"),
        ("ix_rag_scan_items_content_id", "rag_scan_items"),
        ("ix_rag_scan_items_query_id", "rag_scan_items"),
        ("ix_rag_queries_status", "rag_queries"),
        ("ix_rag_queries_session_id", "rag_queries"),
        ("ix_content_rag_detail_tags_tag_id", "content_rag_detail_tags"),
        ("ix_content_rag_detail_tags_content_id", "content_rag_detail_tags"),
        ("ix_rag_detail_tags_status", "rag_detail_tags"),
        ("ix_rag_detail_tags_normalized_name", "rag_detail_tags"),
        ("ix_content_rag_topics_topic_id", "content_rag_topics"),
    ):
        op.drop_index(index, table_name=table)
    for table in (
        "rag_answer_feedback", "rag_feedback_events", "rag_scan_items", "rag_queries", "rag_sessions",
        "content_rag_detail_tags", "rag_detail_tags", "rag_coverage",
        "content_rag_topics", "rag_topics",
    ):
        op.drop_table(table)
