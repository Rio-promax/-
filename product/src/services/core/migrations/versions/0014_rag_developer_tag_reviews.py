"""Add append-only developer review history for internal RAG tags."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_rag_developer_tag_reviews"
down_revision: str | Sequence[str] | None = "0013_rag_execution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rag_developer_tag_reviews",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("tag_id", sa.String(80), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reviewer", sa.String(32), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("candidate_name", sa.String(16), nullable=False),
        sa.Column("candidate_definition", sa.String(120), nullable=False),
        sa.Column("same_concept", sa.Boolean(), nullable=False),
        sa.Column("canonical_tag_id", sa.String(80), nullable=True),
        sa.Column("material_evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_rag_developer_tag_reviews_tag_id",
        "rag_developer_tag_reviews",
        ["tag_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_rag_developer_tag_reviews_tag_id", table_name="rag_developer_tag_reviews")
    op.drop_table("rag_developer_tag_reviews")
