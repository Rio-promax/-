"""Add durable product-level ASR segment checkpoints and timing samples."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_asr_checkpoints"
down_revision: str | Sequence[str] | None = "0011_content_thumbnails"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "asr_segments",
        sa.Column("id", sa.String(length=120), nullable=False),
        sa.Column("job_id", sa.String(length=80), nullable=False),
        sa.Column("config_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("segment_index", sa.Integer(), nullable=False),
        sa.Column("start_seconds", sa.Float(), nullable=False),
        sa.Column("end_seconds", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id",
            "config_fingerprint",
            "segment_index",
            name="uq_asr_segments_job_config_index",
        ),
    )
    op.create_index("ix_asr_segments_job_id", "asr_segments", ["job_id"])
    op.create_index(
        "ix_asr_segments_config_fingerprint",
        "asr_segments",
        ["config_fingerprint"],
    )
    op.create_index("ix_asr_segments_status", "asr_segments", ["status"])
    op.create_table(
        "asr_performance_samples",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("engine", sa.String(length=64), nullable=False),
        sa.Column("device", sa.String(length=32), nullable=False),
        sa.Column("audio_seconds", sa.Float(), nullable=False),
        sa.Column("elapsed_seconds", sa.Float(), nullable=False),
        sa.Column("rtf", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_asr_performance_samples_engine", "asr_performance_samples", ["engine"])
    op.create_index("ix_asr_performance_samples_device", "asr_performance_samples", ["device"])
    op.create_index(
        "ix_asr_performance_samples_created_at",
        "asr_performance_samples",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_asr_performance_samples_created_at", table_name="asr_performance_samples")
    op.drop_index("ix_asr_performance_samples_device", table_name="asr_performance_samples")
    op.drop_index("ix_asr_performance_samples_engine", table_name="asr_performance_samples")
    op.drop_table("asr_performance_samples")
    op.drop_index("ix_asr_segments_status", table_name="asr_segments")
    op.drop_index("ix_asr_segments_config_fingerprint", table_name="asr_segments")
    op.drop_index("ix_asr_segments_job_id", table_name="asr_segments")
    op.drop_table("asr_segments")
