"""Add user-created favorite folders and content memberships."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_favorite_folders"
down_revision: str | Sequence[str] | None = "0007_governance_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "favorite_folders",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "content_favorite_folders",
        sa.Column("content_id", sa.String(length=80), nullable=False),
        sa.Column("folder_id", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["content_id"], ["content_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["folder_id"], ["favorite_folders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("content_id", "folder_id"),
    )
    op.create_index(
        "ix_content_favorite_folders_folder_id",
        "content_favorite_folders",
        ["folder_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_content_favorite_folders_folder_id",
        table_name="content_favorite_folders",
    )
    op.drop_table("content_favorite_folders")
    op.drop_table("favorite_folders")