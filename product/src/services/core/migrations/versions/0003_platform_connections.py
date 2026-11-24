"""Add explicit desktop platform connection records."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0003_platform_connections"
down_revision: str | Sequence[str] | None = "0002_rebuildable_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_connections",
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("auth_type", sa.String(length=32), nullable=False),
        sa.Column("account_label", sa.String(length=120), nullable=True),
        sa.Column("browser", sa.String(length=32), nullable=True),
        sa.Column("browser_profile", sa.String(length=200), nullable=True),
        sa.Column("login_url", sa.Text(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("platform"),
    )


def downgrade() -> None:
    op.drop_table("platform_connections")
