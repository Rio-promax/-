"""Add independent tags, nested folders and the persistent content introduction."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_knowledge_library_taxonomy"
down_revision: str | Sequence[str] | None = "0009_job_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("content_items") as batch:
        batch.add_column(sa.Column("introduction", sa.Text(), nullable=False, server_default=""))

    with op.batch_alter_table("favorite_folders") as batch:
        batch.add_column(sa.Column("parent_id", sa.String(length=80), nullable=True))
        batch.create_index("ix_favorite_folders_parent_id", ["parent_id"])
        batch.create_foreign_key(
            "fk_favorite_folders_parent_id",
            "favorite_folders",
            ["parent_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_table(
        "tags",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("user_id", sa.String(length=80), nullable=False, server_default="local"),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_tags_user_name"),
    )
    op.create_index("ix_tags_user_id", "tags", ["user_id"])
    op.create_table(
        "content_tags",
        sa.Column("content_id", sa.String(length=80), nullable=False),
        sa.Column("tag_id", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["content_id"], ["content_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("content_id", "tag_id"),
    )
    op.create_index("ix_content_tags_tag_id", "content_tags", ["tag_id"])


def downgrade() -> None:
    op.drop_index("ix_content_tags_tag_id", table_name="content_tags")
    op.drop_table("content_tags")
    op.drop_index("ix_tags_user_id", table_name="tags")
    op.drop_table("tags")
    with op.batch_alter_table("favorite_folders") as batch:
        batch.drop_constraint("fk_favorite_folders_parent_id", type_="foreignkey")
        batch.drop_index("ix_favorite_folders_parent_id")
        batch.drop_column("parent_id")
    with op.batch_alter_table("content_items") as batch:
        batch.drop_column("introduction")
