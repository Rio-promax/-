"""Add ordered source-aware chunks and model boundary build metadata."""

from collections.abc import Sequence
import re

import sqlalchemy as sa
from alembic import op

revision: str = "0015_dynamic_ask_chunks"
down_revision: str | Sequence[str] | None = "0014_rag_developer_tag_reviews"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _source_order(row: dict) -> tuple[int, float, str]:
    match = re.search(r"(?:segment|paragraph):(\d+)$", row["source_ref"] or "")
    if match:
        return 0, float(match.group(1)), row["source_ref"]
    if row["start_seconds"] is not None:
        return 1, float(row["start_seconds"]), row["source_ref"]
    return 2, 0.0, row["source_ref"]


def _set_ordinals() -> None:
    connection = op.get_bind()
    result = connection.execution_options(stream_results=True).execute(sa.text(
        "SELECT id, profile_id, content_id, source_kind, location_kind, source_ref, start_seconds "
        "FROM ask_index_chunks "
        "ORDER BY profile_id, content_id, source_kind, location_kind, id"
    ))
    group_key = None
    group: list[dict] = []

    def flush() -> None:
        for ordinal, row in enumerate(sorted(group, key=_source_order), start=1):
            connection.execute(sa.text(
                "UPDATE ask_index_chunks SET chunk_ordinal = :ordinal WHERE id = :id"
            ), {"ordinal": ordinal, "id": row["id"]})

    for result_row in result.mappings():
        row = dict(result_row)
        current_key = (
            row["profile_id"], row["content_id"], row["source_kind"], row["location_kind"],
        )
        if group_key is not None and current_key != group_key:
            flush()
            group = []
        group_key = current_key
        group.append(row)
    if group:
        flush()


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "ask_index_chunks" in tables:
        columns = {column["name"] for column in inspector.get_columns("ask_index_chunks")}
        if "source_refs" not in columns:
            op.add_column("ask_index_chunks", sa.Column(
                "source_refs", sa.JSON(), nullable=False, server_default=sa.text("'[]'"),
            ))
        if "chunk_ordinal" not in columns:
            op.add_column("ask_index_chunks", sa.Column(
                "chunk_ordinal", sa.Integer(), nullable=False, server_default="0",
            ))
        _set_ordinals()
        indexes = {item["name"] for item in inspector.get_indexes("ask_index_chunks")}
        if "ix_ask_index_chunk_source_order" not in indexes:
            op.create_index(
                "ix_ask_index_chunk_source_order",
                "ask_index_chunks",
                ["profile_id", "content_id", "source_kind", "location_kind", "chunk_ordinal"],
            )
    if "ask_index_contents" in tables:
        columns = {column["name"] for column in inspector.get_columns("ask_index_contents")}
        additions = (
            ("chunking_input_hash", sa.String(64), True),
            ("chunking_status", sa.String(24), True),
            ("chunking_model", sa.String(200), True),
            ("chunking_calls", sa.Integer(), False),
            ("chunking_input_bytes", sa.Integer(), False),
            ("chunking_output_tokens", sa.Integer(), True),
            ("chunking_error_code", sa.String(64), True),
            ("chunking_trace", sa.JSON(), False),
        )
        for name, column_type, nullable in additions:
            if name in columns:
                continue
            kwargs = {"nullable": nullable}
            if not nullable:
                kwargs["server_default"] = "[]" if name == "chunking_trace" else "0"
            op.add_column("ask_index_contents", sa.Column(name, column_type, **kwargs))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "ask_index_chunks" in tables:
        indexes = {item["name"] for item in inspector.get_indexes("ask_index_chunks")}
        if "ix_ask_index_chunk_source_order" in indexes:
            op.drop_index("ix_ask_index_chunk_source_order", table_name="ask_index_chunks")
        columns = {column["name"] for column in inspector.get_columns("ask_index_chunks")}
        for column in ("chunk_ordinal", "source_refs"):
            if column in columns:
                op.drop_column("ask_index_chunks", column)
    if "ask_index_contents" in tables:
        columns = {column["name"] for column in inspector.get_columns("ask_index_contents")}
        for column in (
            "chunking_error_code", "chunking_output_tokens", "chunking_input_bytes",
            "chunking_calls", "chunking_model", "chunking_status", "chunking_input_hash",
            "chunking_trace",
        ):
            if column in columns:
                op.drop_column("ask_index_contents", column)
