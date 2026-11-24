"""Add durable summary versions and quality feedback."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_summary_assets"
down_revision: str | Sequence[str] | None = "0004_job_execution_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "summary_versions",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("content_id", sa.String(length=80), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("parent_version_id", sa.String(length=80), nullable=True),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("template", sa.String(length=64), nullable=False),
        sa.Column("chapter_title", sa.Text(), nullable=True),
        sa.Column("source_start_seconds", sa.Float(), nullable=True),
        sa.Column("source_end_seconds", sa.Float(), nullable=True),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["content_id"], ["content_items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_summary_versions_content_id", "summary_versions", ["content_id"])
    op.create_table(
        "summary_feedback",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("content_id", sa.String(length=80), nullable=False),
        sa.Column("version_id", sa.String(length=80), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["content_id"], ["content_items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_summary_feedback_content_id", "summary_feedback", ["content_id"])


def downgrade() -> None:
    op.drop_index("ix_summary_feedback_content_id", table_name="summary_feedback")
    op.drop_table("summary_feedback")
    op.drop_index("ix_summary_versions_content_id", table_name="summary_versions")
    op.drop_table("summary_versions")