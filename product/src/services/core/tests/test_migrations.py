from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_initial_migration_up_and_down(tmp_path) -> None:
    database_path = Path(tmp_path) / "migration.db"
    core_root = Path(__file__).parents[1]
    config = Config(str(core_root / "alembic.ini"))
    config.set_main_option("script_location", str(core_root / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    tables = set(inspect(engine).get_table_names())
    content_columns = {column["name"] for column in inspect(engine).get_columns("content_items")}
    assert {
        "published_at",
        "acquired_at",
        "category",
        "favorite",
        "deleted_at",
        "processing_model",
        "introduction",
    } <= content_columns
    folder_columns = {column["name"] for column in inspect(engine).get_columns("favorite_folders")}
    assert "parent_id" in folder_columns
    feedback_columns = {column["name"] for column in inspect(engine).get_columns("summary_feedback")}
    assert "context_json" in feedback_columns
    event_columns = {column["name"] for column in inspect(engine).get_columns("job_events")}
    assert {
        "job_id",
        "sequence",
        "attempt",
        "event_type",
        "occurred_at",
    } <= event_columns

    assert {
        "alembic_version",
        "content_items",
        "analysis_runs",
        "jobs",
        "job_events",
        "content_summaries",
        "summary_versions",
        "summary_feedback",
        "job_feedback",
        "app_settings",
        "platform_connections",
        "rag_developer_tag_reviews",
        "tags",
        "content_tags",
        "asr_segments",
        "asr_performance_samples",
    } <= tables

    segment_columns = {
        column["name"] for column in inspect(engine).get_columns("asr_segments")
    }
    assert {
        "job_id",
        "config_fingerprint",
        "segment_index",
        "lease_owner",
        "lease_expires_at",
        "worker_generation",
        "text",
        "status",
    } <= segment_columns
    review_columns = {
        column["name"] for column in inspect(engine).get_columns("rag_developer_tag_reviews")
    }
    assert {
        "tag_id", "decision", "reviewer", "candidate_name", "candidate_definition",
        "same_concept", "canonical_tag_id", "material_evidence", "created_at",
    } <= review_columns
    command.downgrade(config, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}


def test_runtime_schema_upgrades_legacy_ask_chunk_columns(tmp_path) -> None:
    from app.db.store import SQLiteStore

    database_path = Path(tmp_path) / "legacy-ask-index.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    store = SQLiteStore(database_url)
    with store.engine.begin() as connection:
        connection.exec_driver_sql("DROP INDEX IF EXISTS ix_ask_index_chunk_source_order")
        connection.exec_driver_sql("DROP INDEX IF EXISTS ix_ask_index_chunks_chunk_ordinal")
        for column in ("chunk_ordinal", "source_refs"):
            connection.exec_driver_sql(f"ALTER TABLE ask_index_chunks DROP COLUMN {column}")
        for column in (
            "chunking_error_code", "chunking_output_tokens", "chunking_input_bytes",
            "chunking_calls", "chunking_model", "chunking_status", "chunking_input_hash",
            "chunking_trace",
        ):
            connection.exec_driver_sql(f"ALTER TABLE ask_index_contents DROP COLUMN {column}")
    store.engine.dispose()

    SQLiteStore(database_url)

    engine = create_engine(database_url)
    chunk_columns = {column["name"] for column in inspect(engine).get_columns("ask_index_chunks")}
    assert {"source_refs", "chunk_ordinal"} <= chunk_columns
    chunk_state_columns = {
        column["name"] for column in inspect(engine).get_columns("ask_index_contents")
    }
    assert {
        "chunking_input_hash", "chunking_status", "chunking_model", "chunking_calls",
        "chunking_input_bytes", "chunking_output_tokens", "chunking_error_code", "chunking_trace",
    } <= chunk_state_columns
