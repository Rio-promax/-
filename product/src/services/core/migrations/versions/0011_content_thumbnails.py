"""Persist a source thumbnail for compact content and task cards."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_content_thumbnails"
down_revision: str | Sequence[str] | None = "0010_knowledge_library_taxonomy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("content_items") as batch:
        batch.add_column(sa.Column("thumbnail_url", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("content_items") as batch:
        batch.drop_column("thumbnail_url")
