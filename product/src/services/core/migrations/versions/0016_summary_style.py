"""Persist expression style independently from summary strength and template."""

import sqlalchemy as sa
from alembic import op

revision = "0016_summary_style"
down_revision = "0015_dynamic_ask_chunks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("summary_versions")}
    if "summary_style" not in columns:
        op.add_column("summary_versions", sa.Column("summary_style", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("summary_versions", "summary_style")
