"""Add content library metadata and reversible organization state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_content_library"
down_revision: str | Sequence[str] | None = "0005_summary_assets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("content_items") as batch:
        batch.add_column(sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(
            sa.Column("acquisition_method", sa.Text(), nullable=False, server_default="adapter")
        )
        batch.add_column(
            sa.Column("category", sa.String(length=120), nullable=False, server_default="未分类")
        )
        batch.add_column(sa.Column("favorite", sa.Boolean(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("processing_model", sa.String(length=200), nullable=True))

    with op.batch_alter_table("content_summaries") as batch:
        batch.add_column(sa.Column("transcript_text", sa.Text(), nullable=True))
        batch.add_column(sa.Column("source_note", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("content_summaries") as batch:
        batch.drop_column("source_note")
        batch.drop_column("transcript_text")
    with op.batch_alter_table("content_items") as batch:
        batch.drop_column("processing_model")
        batch.drop_column("deleted_at")
        batch.drop_column("favorite")
        batch.drop_column("category")
        batch.drop_column("acquisition_method")
        batch.drop_column("acquired_at")
        batch.drop_column("published_at")