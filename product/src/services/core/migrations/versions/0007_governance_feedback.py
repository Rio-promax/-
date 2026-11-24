"""Add task feedback context for diagnostics and quality follow-up."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_governance_feedback"
down_revision: str | Sequence[str] | None = "0006_content_library"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("summary_feedback") as batch:
        batch.add_column(sa.Column("context_json", sa.JSON(), nullable=True))
    op.create_table(
        "job_feedback",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("job_id", sa.String(length=80), nullable=False),
        sa.Column("content_id", sa.String(length=80), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("context_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["content_id"], ["content_items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_feedback_job_id", "job_feedback", ["job_id"])
    op.create_index("ix_job_feedback_content_id", "job_feedback", ["content_id"])


def downgrade() -> None:
    op.drop_index("ix_job_feedback_content_id", table_name="job_feedback")
    op.drop_index("ix_job_feedback_job_id", table_name="job_feedback")
    op.drop_table("job_feedback")
    with op.batch_alter_table("summary_feedback") as batch:
        batch.drop_column("context_json")