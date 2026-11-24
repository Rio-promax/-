"""Rebuildable SQLite FTS5 index for archived Q&A evidence spans."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import sqlite3
import struct
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Any, Callable, Literal

from sqlalchemy import func, select, text

from app.archive.schema import ArchiveSchemaError, validate_record
from app.db.models import (
    AskIndexChunkRow,
    AskIndexContentRow,
    AskIndexProfileRow,
    ContentRow,
)
from app.domain.jobs import JobState
from app.knowledge.siliconflow_retrieval import (
    EMBED_BATCH_SIZE,
    AskEmbeddingUnavailableError,
    SiliconFlowRetrieval,
)
from app.knowledge.source_map import map_transcript_segments

logger = logging.getLogger(__name__)

MAX_CHUNK_UTF8_BYTES = 2400
BOUNDARY_WINDOW_UTF8_BYTES = 6000
MAX_BOUNDARY_CALLS_PER_CONTENT = 6
MAX_BOUNDARY_SECONDS_PER_CONTENT = 20
MAX_BOUNDARY_OUTPUT_TOKENS = 128
MAX_BOUNDARY_INPUT_BYTES_PER_CALL = 10000
EMBEDDING_CONTEXT_LIMIT_TOKENS = 32768

_PROFILE_CONFIG = {
    "engine": "sqlite-fts5-trigram",
    "schema": "ask-index-v3",
    "source_map": "archive-transcript-v1",
    "span_rule": "model-advised-ordered-chunks-v1",
}


@dataclass(frozen=True, slots=True)
class AskIndexResult:
    content_id: str
    status: str
    chunk_count: int
    source_hash: str
    error_code: str | None = None
    vector_status: str | None = None
    vector_error_code: str | None = None
    chunking_status: str | None = None
    chunking_calls: int = 0
    chunking_input_bytes: int = 0
    chunking_output_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class AskIndexHit:
    stable_id: str
    content_id: str
    source_kind: str
    location_kind: str
    source_ref: str
    start_seconds: float | None
    end_seconds: float | None
    text_hash: str
    text: str
    rank: float
    source_refs: tuple[str, ...] = ()
    chunk_ordinal: int = 0


class AskIndex:
    """Build and query versioned keyword and cloud-embedded vector indexes."""

    def __init__(
        self, store, archive_root: str | Path, *, embedding_backend=None,
        chunk_boundary_proposer: Callable | None = None, chunking_model: str | None = None,
        chunking_config: dict[str, Any] | None = None,
    ) -> None:
        self.store = store
        self.archive_root = Path(archive_root).expanduser().resolve()
        self._lock = RLock()
        self._embedding_backend = embedding_backend
        self._chunk_boundary_proposer = chunk_boundary_proposer
        self.chunking_model = chunking_model.strip() if chunking_model else None
        self.max_chunk_utf8_bytes = MAX_CHUNK_UTF8_BYTES
        self.chunking_config = {
            "implementation": "model-advised-ordered-chunks-v1",
            "boundary_model": self.chunking_model,
            "max_chunk_size": {"value": MAX_CHUNK_UTF8_BYTES, "unit": "UTF-8 bytes"},
            "proposal_window_utf8_bytes": BOUNDARY_WINDOW_UTF8_BYTES,
            "max_calls_per_content": MAX_BOUNDARY_CALLS_PER_CONTENT,
            "max_total_seconds_per_content": MAX_BOUNDARY_SECONDS_PER_CONTENT,
            "max_output_tokens_per_call": MAX_BOUNDARY_OUTPUT_TOKENS,
            "max_input_bytes_per_call": MAX_BOUNDARY_INPUT_BYTES_PER_CALL,
            "max_total_input_bytes_per_content": (
                MAX_BOUNDARY_CALLS_PER_CONTENT * MAX_BOUNDARY_INPUT_BYTES_PER_CALL
            ),
            "max_output_tokens_per_content": (
                MAX_BOUNDARY_CALLS_PER_CONTENT * MAX_BOUNDARY_OUTPUT_TOKENS
            ),
            "model_context_limit_tokens": EMBEDDING_CONTEXT_LIMIT_TOKENS,
            "embedding_token_bound_method": "UTF-8 byte count upper bound",
        }
        self.chunking_config.update(chunking_config or {})
        self._embedding_config_error: AskEmbeddingUnavailableError | None = None
        self._vector_setup_error: AskEmbeddingUnavailableError | None = None
        self._vector_requested = embedding_backend is not None
        if embedding_backend is None:
            self._embedding_backend = SiliconFlowRetrieval.from_environment()
            self._vector_requested = self._embedding_backend is not None

        self.vector_profile_id: str | None = None
        self.vector_table_name: str | None = None
        if self._embedding_backend is not None:
            vector_config = {
                **self._embedding_backend.config,
                "span_rule": "model-advised-ordered-chunks-v1",
                "chunking_profile": self.chunking_config,
                "max_input_utf8_bytes": MAX_CHUNK_UTF8_BYTES,
                "context_limit_tokens": EMBEDDING_CONTEXT_LIMIT_TOKENS,
            }
            self._vector_config = vector_config
            encoded_vector_config = json.dumps(vector_config, sort_keys=True, separators=(",", ":"))
            vector_digest = hashlib.sha256(encoded_vector_config.encode("utf-8")).hexdigest()
            self.vector_profile_id = f"vec:{vector_digest[:32]}"
            dimension = self._embedding_backend.dimension
            if not isinstance(dimension, int) or dimension < 1:
                raise AskEmbeddingUnavailableError("embedding 向量维度无效")
            self.vector_table_name = f"ask_index_vectors_d{dimension}"

        self._profile_config = {**_PROFILE_CONFIG, "chunking": self.chunking_config}
        encoded = json.dumps(self._profile_config, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        self.profile_id = f"fts5:{digest[:32]}"
        self._install_fts5()
        with self.store.session_factory() as session:
            self._new_profile = session.get(AskIndexProfileRow, self.profile_id) is None
            if self.vector_profile_id is not None:
                self._new_profile = self._new_profile or (
                    session.get(AskIndexProfileRow, self.vector_profile_id) is None
                )
        self._record_profile(self.profile_id, "sqlite-fts5-trigram", self._profile_config)
        if self.vector_profile_id is not None:
            self._record_profile(
                self.vector_profile_id,
                "sqlite-vec",
                self._vector_config,
            )
            try:
                self._install_vector_store()
            except AskEmbeddingUnavailableError as error:
                self._vector_setup_error = error

    @property
    def vector_configured(self) -> bool:
        return self._vector_requested

    @property
    def vector_error_message(self) -> str | None:
        error = self._embedding_config_error or self._vector_setup_error
        return str(error) if error is not None else None

    def close(self) -> None:
        pass

    def _record_profile(self, profile_id: str, engine: str, config_json: dict[str, Any]) -> None:
        with self.store.session_factory.begin() as session:
            if session.get(AskIndexProfileRow, profile_id) is None:
                session.add(
                    AskIndexProfileRow(
                        id=profile_id,
                        engine=engine,
                        config_json=config_json,
                        created_at=datetime.now(UTC),
                    )
                )

    def _install_vector_store(self) -> None:
        if self.vector_table_name is None or self._embedding_backend is None:
            return
        table_name = self.vector_table_name
        dimension = self._embedding_backend.dimension
        ddl = (
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {table_name} USING vec0("
            f"point_id INTEGER PRIMARY KEY, embedding FLOAT[{dimension}], "
            "profile_id TEXT, content_id TEXT, active BOOLEAN, source_kind TEXT, "
            "+stable_id TEXT)"
        )
        try:
            with self.store.engine.begin() as connection:
                self._load_vector_extension(connection)
                connection.exec_driver_sql(ddl)
        except AskEmbeddingUnavailableError:
            raise
        except Exception as error:
            raise AskEmbeddingUnavailableError(
                f"SQLite 向量扩展不可用：{error}"
            ) from error

    @staticmethod
    def _load_vector_extension(connection) -> None:
        raw_connection = connection.connection.driver_connection
        try:
            raw_connection.execute("SELECT vec_version()").fetchone()
            return
        except sqlite3.OperationalError:
            pass

        try:
            import sqlite_vec

            raw_connection.enable_load_extension(True)
            try:
                sqlite_vec.load(raw_connection)
            finally:
                raw_connection.enable_load_extension(False)
        except Exception as error:
            raise AskEmbeddingUnavailableError(
                "sqlite-vec 未安装或无法载入；请安装项目依赖 sqlite-vec"
            ) from error

    def _require_vector(self):
        if self._embedding_config_error is not None:
            raise self._embedding_config_error
        if self._vector_setup_error is not None:
            raise self._vector_setup_error
        if self._embedding_backend is None or self.vector_profile_id is None:
            raise AskEmbeddingUnavailableError(
                "向量检索未启用；请配置 SILICONFLOW_API_KEY"
            )
        return self._embedding_backend

    def embed_query(self, query: str, *, timeout: float = 60) -> list[float]:
        backend = self._require_vector()
        if not query.strip():
            return []
        vector = backend.embed_query(query, timeout=timeout)
        _validate_vector(vector, backend.dimension)
        return vector

    def _install_fts5(self) -> None:
        """Install the FTS virtual table and keep it in sync with source spans."""

        statements = (
            "CREATE VIRTUAL TABLE IF NOT EXISTS ask_index_fts USING fts5("
            "content_text, content='ask_index_chunks', content_rowid='id', tokenize='trigram')",
            "CREATE TRIGGER IF NOT EXISTS ask_index_chunks_ai AFTER INSERT ON ask_index_chunks "
            "BEGIN "
            "INSERT INTO ask_index_fts(rowid, content_text) VALUES (new.id, new.content_text); END",
            "CREATE TRIGGER IF NOT EXISTS ask_index_chunks_ad AFTER DELETE ON ask_index_chunks "
            "BEGIN "
            "INSERT INTO ask_index_fts(ask_index_fts, rowid, content_text) "
            "VALUES ('delete', old.id, old.content_text); END",
            "CREATE TRIGGER IF NOT EXISTS ask_index_chunks_au AFTER UPDATE ON ask_index_chunks "
            "BEGIN "
            "INSERT INTO ask_index_fts(ask_index_fts, rowid, content_text) "
            "VALUES ('delete', old.id, old.content_text); "
            "INSERT INTO ask_index_fts(rowid, content_text) VALUES (new.id, new.content_text); END",
        )
        with self.store.engine.begin() as connection:
            for statement in statements:
                connection.exec_driver_sql(statement)

    def sync_content(
        self,
        content_id: str,
        archive_path: str | Path,
        *,
        summary_text: str | None = None,
        force_rechunk: bool = False,
    ) -> AskIndexResult:
        """Index one completed archive; never alter its source files."""

        with self._lock:
            with self.store.session_factory() as session:
                content = session.get(ContentRow, content_id)
                if content is None:
                    return AskIndexResult(content_id, "failed", 0, "", "content_missing")
                if content.deleted_at is not None:
                    return self._mark_deleted(content_id)

            try:
                requested_path = archive_path
                while True:
                    had_completed_job, latest_path = self._latest_completed_archive(content_id)
                    if had_completed_job:
                        if latest_path is None:
                            return self._mark_failed(content_id, "completed_archive_missing")
                        requested_path = latest_path
                    path = self._resolve_archive(requested_path)
                    source_units = self._read_spans(path, content_id, summary_text)

                    has_completed_job_after_read, latest_path_after_read = (
                        self._latest_completed_archive(content_id)
                    )
                    if has_completed_job_after_read:
                        if latest_path_after_read is None:
                            return self._mark_failed(content_id, "completed_archive_missing")
                        latest_path_after_read = self._resolve_archive(latest_path_after_read)
                        if latest_path_after_read != path:
                            requested_path = latest_path_after_read
                            continue
                    elif had_completed_job:
                        return self._mark_failed(content_id, "completed_archive_missing")
                    break
            except _ArchiveIndexError as error:
                return self._mark_failed(content_id, error.code)
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
                logger.warning("Q&A index archive could not be read for %s: %s", content_id, error)
                return self._mark_failed(content_id, "archive_invalid")

            input_hash = _stable_hash(source_units)
            cached = None if force_rechunk else self._cached_chunking(content_id, input_hash)
            if cached is None:
                spans, chunking = self._build_chunks(source_units, content_id)
            else:
                spans, chunking = cached
            source_hash = _stable_hash(spans)
            status = (
                "indexed"
                if any(span["source_kind"] != "summary" for span in spans)
                else "partial"
            )
            if not spans:
                return self._mark_failed(content_id, "no_searchable_source")

            with self.store.session_factory() as session:
                current = session.get(AskIndexContentRow, (self.profile_id, content_id))
                unchanged_fts = (
                    current is not None
                    and current.source_hash == source_hash
                    and current.status == status
                )

            with self.store.session_factory.begin() as session:
                if not unchanged_fts:
                    session.query(AskIndexChunkRow).filter_by(
                        profile_id=self.profile_id,
                        content_id=content_id,
                    ).delete(synchronize_session=False)
                    for span in spans:
                        session.add(
                            AskIndexChunkRow(
                                stable_id=span["stable_id"],
                                profile_id=self.profile_id,
                                content_id=content_id,
                                source_kind=span["source_kind"],
                                location_kind=span["location_kind"],
                                source_ref=span["source_ref"],
                                source_refs=list(span["source_refs"]),
                                chunk_ordinal=span["chunk_ordinal"],
                                start_seconds=span["start_seconds"],
                                end_seconds=span["end_seconds"],
                                text_hash=span["text_hash"],
                                content_text=span["text"],
                            )
                        )
                state = session.get(AskIndexContentRow, (self.profile_id, content_id))
                if state is None:
                    state = AskIndexContentRow(
                        profile_id=self.profile_id,
                        content_id=content_id,
                        source_hash=source_hash,
                        status=status,
                        chunk_count=len(spans),
                        error_code=None,
                        updated_at=datetime.now(UTC),
                    )
                    session.add(state)
                state.source_hash = source_hash
                state.status = status
                state.chunk_count = len(spans)
                state.error_code = None
                state.chunking_input_hash = input_hash
                state.chunking_status = chunking["status"]
                state.chunking_model = self.chunking_model
                state.chunking_calls = chunking["calls"]
                state.chunking_input_bytes = chunking["input_bytes"]
                state.chunking_output_tokens = chunking["output_tokens"]
                state.chunking_error_code = chunking["error_code"]
                state.chunking_trace = chunking["trace"]
                state.updated_at = datetime.now(UTC)

            vector_status = None
            vector_error_code = None
            if self._vector_requested:
                try:
                    vector_status, vector_error_code = self._sync_vector_content(
                        content_id, spans, source_hash, status
                    )
                except AskEmbeddingUnavailableError as error:
                    vector_status = "failed"
                    vector_error_code = "embedding_unavailable"
                    logger.warning(
                        "Q&A vector index unavailable for %s: %s", content_id, error
                    )

            return AskIndexResult(
                content_id,
                status,
                len(spans),
                source_hash,
                vector_status=vector_status,
                vector_error_code=vector_error_code,
                chunking_status=chunking["status"],
                chunking_calls=chunking["calls"],
                chunking_input_bytes=chunking["input_bytes"],
                chunking_output_tokens=chunking["output_tokens"],
            )

    def sync_latest(self, content_id: str, *, force_rechunk: bool = False) -> AskIndexResult:
        """Rebuild a restored item from its most recent completed archive."""

        has_completed_job, archive_path = self._latest_completed_archive(content_id)
        if not has_completed_job or archive_path is None:
            return self._mark_failed(content_id, "completed_archive_missing")
        return self.sync_content(
            content_id,
            archive_path,
            summary_text=self.store.get_summary(content_id),
            force_rechunk=force_rechunk,
        )

    def has_content(self, content_id: str) -> bool:
        with self.store.session_factory() as session:
            return session.get(AskIndexContentRow, (self.profile_id, content_id)) is not None

    def chunking_snapshot(self, content_ids: list[str] | None = None) -> dict[str, Any]:
        with self.store.session_factory() as session:
            query = select(
                AskIndexContentRow.chunking_status,
                AskIndexContentRow.chunking_calls,
                AskIndexContentRow.chunking_input_bytes,
                AskIndexContentRow.chunking_output_tokens,
                AskIndexContentRow.chunking_error_code,
                AskIndexContentRow.chunking_trace,
            ).where(AskIndexContentRow.profile_id == self.profile_id)
            if content_ids is not None:
                if not content_ids:
                    rows = []
                else:
                    rows = session.execute(query.where(
                        AskIndexContentRow.content_id.in_(content_ids)
                    )).all()
            else:
                rows = session.execute(query).all()
        statuses: dict[str, int] = {}
        errors: dict[str, int] = {}
        calls = input_bytes = output_tokens = 0
        output_known = True
        for status, row_calls, row_input, row_output, error_code, _trace in rows:
            if status:
                statuses[status] = statuses.get(status, 0) + 1
            calls += row_calls or 0
            input_bytes += row_input or 0
            if row_output is None:
                output_known = False
            else:
                output_tokens += row_output
            if error_code:
                errors[error_code] = errors.get(error_code, 0) + 1
        return {
            "model": self.chunking_model,
            "profile_id": self.profile_id,
            "limits": dict(self.chunking_config),
            "statuses": statuses,
            "errors": errors,
            "calls": calls,
            "input_bytes": input_bytes,
            "output_tokens": output_tokens if output_known else None,
            "output_tokens_known": output_known,
        }

    def chunking_content_states(self, content_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not content_ids:
            return {}
        with self.store.session_factory() as session:
            rows = session.execute(select(
                AskIndexContentRow.content_id,
                AskIndexContentRow.status,
                AskIndexContentRow.chunk_count,
                AskIndexContentRow.chunking_status,
                AskIndexContentRow.chunking_model,
                AskIndexContentRow.chunking_calls,
                AskIndexContentRow.chunking_input_bytes,
                AskIndexContentRow.chunking_output_tokens,
                AskIndexContentRow.chunking_error_code,
                AskIndexContentRow.chunking_trace,
            ).where(
                AskIndexContentRow.profile_id == self.profile_id,
                AskIndexContentRow.content_id.in_(content_ids),
            )).all()
        return {
            content_id: {
                "index_status": index_status,
                "chunk_count": chunk_count,
                "status": chunking_status,
                "model": model,
                "calls": calls,
                "input_bytes": input_bytes,
                "output_tokens": output_tokens,
                "error_code": error_code,
                "trace": trace or [],
            }
            for (
                content_id, index_status, chunk_count, chunking_status, model,
                calls, input_bytes, output_tokens, error_code, trace,
            ) in rows
        }

    def _sync_vector_content(
        self,
        content_id: str,
        spans: list[dict[str, Any]],
        source_hash: str,
        fts_status: str,
    ) -> tuple[str, str | None]:
        backend = self._require_vector()
        profile_id = self.vector_profile_id
        table_name = self.vector_table_name
        assert profile_id is not None and table_name is not None

        vector_spans = [_span_for_profile(span, content_id, profile_id) for span in spans]
        span_byte_lengths = [len(span["text"].encode("utf-8")) for span in vector_spans]
        if any(length > MAX_CHUNK_UTF8_BYTES for length in span_byte_lengths):
            raise AskEmbeddingUnavailableError("chunk 超过 UTF-8 字节上限")
        if any(length > EMBEDDING_CONTEXT_LIMIT_TOKENS for length in span_byte_lengths):
            raise AskEmbeddingUnavailableError("chunk 超过保守估算的 embedding token 上限")
        desired_ids = {span["stable_id"] for span in vector_spans}
        with self.store.session_factory() as session:
            state = session.get(AskIndexContentRow, (profile_id, content_id))
            same_source = state is not None and state.source_hash == source_hash
            connection = session.connection()
            self._load_vector_extension(connection)
            point_rows = connection.exec_driver_sql(
                f"SELECT point_id, stable_id FROM {table_name} "
                "WHERE profile_id = ? AND content_id = ?",
                (profile_id, content_id),
            ).all()
            existing_points = {
                str(stable_id): int(point_id)
                for point_id, stable_id in point_rows
                if str(stable_id) in desired_ids
            }

        if not same_source:
            with self.store.session_factory.begin() as session:
                self._delete_vector_points(session, [int(row[0]) for row in point_rows])
                session.query(AskIndexChunkRow).filter_by(
                    profile_id=profile_id,
                    content_id=content_id,
                ).delete(synchronize_session=False)
                self._save_vector_state(
                    session,
                    profile_id,
                    content_id,
                    source_hash,
                    "pending",
                    0,
                    None,
                )
            existing_points = {}

        completed_ids = set(existing_points)
        missing_spans = [span for span in vector_spans if span["stable_id"] not in completed_ids]

        try:
            for offset in range(0, len(missing_spans), EMBED_BATCH_SIZE):
                batch = missing_spans[offset : offset + EMBED_BATCH_SIZE]
                vectors = backend.embed_documents([span["text"] for span in batch])
                if len(vectors) != len(batch):
                    raise AskEmbeddingUnavailableError("embedding 批次返回数量不匹配")
                for vector in vectors:
                    _validate_vector(vector, backend.dimension)

                with self.store.session_factory.begin() as session:
                    existing_rows = {
                        row.stable_id: row for row in session.scalars(
                            select(AskIndexChunkRow).where(
                                AskIndexChunkRow.profile_id == profile_id,
                                AskIndexChunkRow.content_id == content_id,
                                AskIndexChunkRow.stable_id.in_([span["stable_id"] for span in batch]),
                            )
                        )
                    }
                    chunk_rows: list[AskIndexChunkRow] = []
                    for span in batch:
                        row = existing_rows.get(span["stable_id"])
                        if row is None:
                            row = AskIndexChunkRow(
                                stable_id=span["stable_id"],
                                profile_id=profile_id,
                                content_id=content_id,
                                source_kind=span["source_kind"],
                                location_kind=span["location_kind"],
                                source_ref=span["source_ref"],
                                source_refs=list(span["source_refs"]),
                                chunk_ordinal=span["chunk_ordinal"],
                                start_seconds=span["start_seconds"],
                                end_seconds=span["end_seconds"],
                                text_hash=span["text_hash"],
                                content_text=span["text"],
                            )
                            session.add(row)
                        chunk_rows.append(row)
                    session.flush()
                    connection = session.connection()
                    self._load_vector_extension(connection)
                    for row, vector in zip(chunk_rows, vectors, strict=True):
                        connection.exec_driver_sql(
                            f"INSERT INTO {table_name}("
                            "point_id, embedding, profile_id, content_id, active, source_kind, "
                            "stable_id"
                            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (
                                row.id,
                                struct.pack(f"{backend.dimension}f", *vector),
                                profile_id,
                                content_id,
                                1,
                                row.source_kind,
                                row.stable_id,
                            ),
                        )
                        completed_ids.add(row.stable_id)
                    self._save_vector_state(
                        session,
                        profile_id,
                        content_id,
                        source_hash,
                        "partial",
                        len(completed_ids),
                        None,
                    )
        except AskEmbeddingUnavailableError as error:
            status = "partial" if completed_ids else "failed"
            with self.store.session_factory.begin() as session:
                self._save_vector_state(
                    session,
                    profile_id,
                    content_id,
                    source_hash,
                    status,
                    len(completed_ids),
                    "embedding_unavailable",
                )
            logger.warning("Q&A vector indexing paused for %s: %s", content_id, error)
            return status, "embedding_unavailable"
        except Exception:
            status = "partial" if completed_ids else "failed"
            with self.store.session_factory.begin() as session:
                self._save_vector_state(
                    session,
                    profile_id,
                    content_id,
                    source_hash,
                    status,
                    len(completed_ids),
                    "vector_index_failed",
                )
            logger.exception("Q&A vector index failed for %s", content_id)
            return status, "vector_index_failed"

        status = "indexed" if len(completed_ids) == len(vector_spans) else "partial"
        if fts_status == "partial" and status == "indexed":
            status = "partial"
        with self.store.session_factory.begin() as session:
            point_rows = self._vector_rows(session, content_id)
            point_ids = [point_id for point_id, _ in point_rows]
            self._set_vector_points_active(session, point_ids, True)
            self._save_vector_state(
                session,
                profile_id,
                content_id,
                source_hash,
                status,
                len(completed_ids),
                None,
            )
        return status, None

    def _vector_rows(self, session, content_id: str) -> list[tuple[int, str]]:
        table_name = self.vector_table_name
        profile_id = self.vector_profile_id
        if table_name is None or profile_id is None:
            return []
        connection = session.connection()
        self._load_vector_extension(connection)
        rows = connection.exec_driver_sql(
            f"SELECT point_id, stable_id FROM {table_name} "
            "WHERE profile_id = ? AND content_id = ?",
            (profile_id, content_id),
        ).all()
        return [(int(point_id), str(stable_id)) for point_id, stable_id in rows]

    def _delete_vector_points(self, session, point_ids: list[int]) -> None:
        if not point_ids or self.vector_table_name is None:
            return
        connection = session.connection()
        self._load_vector_extension(connection)
        placeholders = ", ".join("?" for _ in point_ids)
        connection.exec_driver_sql(
            f"DELETE FROM {self.vector_table_name} WHERE point_id IN ({placeholders})",
            tuple(point_ids),
        )

    def _set_vector_points_active(
        self, session, point_ids: list[int], active: bool
    ) -> None:
        if not point_ids or self.vector_table_name is None:
            return
        connection = session.connection()
        self._load_vector_extension(connection)
        placeholders = ", ".join("?" for _ in point_ids)
        connection.exec_driver_sql(
            f"UPDATE {self.vector_table_name} SET active = ? "
            f"WHERE point_id IN ({placeholders})",
            (int(active), *point_ids),
        )

    @staticmethod
    def _save_vector_state(
        session,
        profile_id: str,
        content_id: str,
        source_hash: str,
        status: str,
        chunk_count: int,
        error_code: str | None,
    ) -> None:
        state = session.get(AskIndexContentRow, (profile_id, content_id))
        if state is None:
            state = AskIndexContentRow(
                profile_id=profile_id,
                content_id=content_id,
                source_hash=source_hash,
                status=status,
                chunk_count=chunk_count,
                error_code=error_code,
                updated_at=datetime.now(UTC),
            )
            session.add(state)
        else:
            state.source_hash = source_hash
            state.status = status
            state.chunk_count = chunk_count
            state.error_code = error_code
            state.updated_at = datetime.now(UTC)

    def mark_deleted(self, content_id: str) -> AskIndexResult:
        """Keep rebuildable spans but exclude the soft-deleted item from search."""

        with self._lock:
            return self._mark_deleted(content_id)

    def record_failure(self, content_id: str, error_code: str) -> AskIndexResult:
        return self._mark_failed(content_id, error_code)

    def _mark_deleted(self, content_id: str) -> AskIndexResult:
        with self.store.session_factory.begin() as session:
            state = session.get(AskIndexContentRow, (self.profile_id, content_id))
            if state is None:
                state = AskIndexContentRow(
                    profile_id=self.profile_id,
                    content_id=content_id,
                    source_hash="",
                    status="deleted",
                    chunk_count=0,
                    error_code=None,
                    updated_at=datetime.now(UTC),
                )
                session.add(state)
            else:
                state.status = "deleted"
                state.updated_at = datetime.now(UTC)
                state.error_code = None

            vector_status = None
            if self.vector_profile_id is not None:
                vector_rows = self._vector_rows(session, content_id)
                self._set_vector_points_active(
                    session, [point_id for point_id, _ in vector_rows], False
                )
                vector_state = session.get(
                    AskIndexContentRow, (self.vector_profile_id, content_id)
                )
                if vector_state is None:
                    self._save_vector_state(
                        session,
                        self.vector_profile_id,
                        content_id,
                        "",
                        "deleted",
                        0,
                        None,
                    )
                else:
                    vector_state.status = "deleted"
                    vector_state.updated_at = datetime.now(UTC)
                    vector_state.error_code = None
                vector_status = "deleted"
            return AskIndexResult(
                content_id,
                "deleted",
                state.chunk_count,
                state.source_hash,
                vector_status=vector_status,
            )

    def _mark_failed(self, content_id: str, error_code: str) -> AskIndexResult:
        with self.store.session_factory.begin() as session:
            if session.get(ContentRow, content_id) is None:
                return AskIndexResult(content_id, "failed", 0, "", error_code)
            session.query(AskIndexChunkRow).filter_by(
                profile_id=self.profile_id,
                content_id=content_id,
            ).delete(synchronize_session=False)
            state = session.get(AskIndexContentRow, (self.profile_id, content_id))
            if state is None:
                state = AskIndexContentRow(
                    profile_id=self.profile_id,
                    content_id=content_id,
                    source_hash="",
                    status="failed",
                    chunk_count=0,
                    error_code=error_code,
                    updated_at=datetime.now(UTC),
                )
                session.add(state)
            else:
                state.source_hash = ""
                state.status = "failed"
                state.chunk_count = 0
                state.error_code = error_code
                state.updated_at = datetime.now(UTC)
            vector_status = None
            if self.vector_profile_id is not None:
                vector_rows = self._vector_rows(session, content_id)
                self._set_vector_points_active(
                    session, [point_id for point_id, _ in vector_rows], False
                )
                self._save_vector_state(
                    session,
                    self.vector_profile_id,
                    content_id,
                    "",
                    "failed",
                    0,
                    error_code,
                )
                vector_status = "failed"
        return AskIndexResult(
            content_id,
            "failed",
            0,
            "",
            error_code,
            vector_status=vector_status,
        )

    def backfill(self) -> dict[str, int]:
        """Reconcile all completed archive snapshots; safe to rerun."""

        results = {"indexed": 0, "partial": 0, "failed": 0, "deleted": 0}
        for entry in self.store.list_history(archived_only=True, include_deleted=True):
            if entry.content.deleted_at is not None:
                result = self.mark_deleted(entry.content.id)
            else:
                # The history snapshot may become stale while new work completes.
                # Re-read the newest completed run for each content before syncing.
                result = self.sync_latest(entry.content.id)
            results[result.status] = results.get(result.status, 0) + 1
        return results

    def _latest_completed_archive(self, content_id: str) -> tuple[bool, Path | None]:
        """Return the newest completed job's archive path by run creation order."""

        for job in reversed(self.store.list_content_jobs(content_id)):
            if job.state is not JobState.COMPLETED:
                continue
            archive_path = job.metadata.get("archive_path")
            if not isinstance(archive_path, str) or not archive_path.strip():
                return True, None
            return True, Path(archive_path)
        return False, None

    def coverage_snapshot(self) -> dict[str, int]:
        """Report index state against completed, non-deleted library content."""

        entries = self.store.list_history(archived_only=True, include_deleted=False)
        content_ids = {entry.content.id for entry in entries}
        with self.store.session_factory() as session:
            states = session.execute(
                select(AskIndexContentRow.content_id, AskIndexContentRow.status).where(
                    AskIndexContentRow.profile_id == self.profile_id,
                    AskIndexContentRow.content_id.in_(content_ids) if content_ids else False,
                )
            ).all()
        counts = {"indexed": 0, "partial": 0, "failed": 0, "pending": 0}
        processed: set[str] = set()
        for content_id, status in states:
            processed.add(content_id)
            if status in counts:
                counts[status] += 1
        return {
            "total_completed": len(content_ids),
            "indexed": counts["indexed"],
            "partial": counts["partial"],
            "failed": counts["failed"],
            "pending": counts["pending"] + len(content_ids - processed),
        }

    def coverage_for(self, content_ids: list[str]) -> dict[str, Any]:
        """Report current-profile index state for a frozen content scope."""

        ids = list(dict.fromkeys(content_ids))
        counts = {"indexed": 0, "partial": 0, "failed": 0}
        if ids:
            with self.store.session_factory() as session:
                rows = session.execute(
                    select(AskIndexContentRow.content_id, AskIndexContentRow.status).where(
                        AskIndexContentRow.profile_id == self.profile_id,
                        AskIndexContentRow.content_id.in_(ids),
                    )
                ).all()
            for content_id, status in rows:
                if status in counts:
                    counts[status] += 1
        return {
            "profile_id": self.profile_id,
            "target": len(ids),
            **counts,
            "pending": len(ids) - sum(counts.values()),
        }

    def content_source_versions(self, content_ids: list[str]) -> dict[str, str]:
        """Return the active indexed source digest for each requested item."""

        if not content_ids:
            return {}
        with self.store.session_factory() as session:
            rows = session.execute(
                select(AskIndexContentRow.content_id, AskIndexContentRow.source_hash).where(
                    AskIndexContentRow.profile_id == self.profile_id,
                    AskIndexContentRow.content_id.in_(content_ids),
                    AskIndexContentRow.status.in_(("indexed", "partial")),
                )
            ).all()
        return {content_id: source_hash for content_id, source_hash in rows}

    def original_time_coverage(self, content_id: str) -> dict[str, float | None]:
        with self.store.session_factory() as session:
            duration, last_position = session.execute(
                select(ContentRow.duration_seconds, func.max(AskIndexChunkRow.end_seconds))
                .outerjoin(AskIndexChunkRow, (AskIndexChunkRow.content_id == ContentRow.id)
                           & (AskIndexChunkRow.profile_id == self.profile_id)
                           & (AskIndexChunkRow.source_kind != "summary")
                           & (AskIndexChunkRow.location_kind == "timestamp"))
                .where(ContentRow.id == content_id)
                .group_by(ContentRow.id, ContentRow.duration_seconds)
            ).one_or_none() or (None, None)
        return {"duration_seconds": duration, "last_indexed_timestamp": last_position}

    def vector_coverage_snapshot(self) -> dict[str, Any]:
        """Report verified active vector-point coverage for active archives."""

        return self._vector_coverage_snapshot(verify_points=True)

    def vector_state_coverage_snapshot(self) -> dict[str, Any]:
        """Report persisted vector state counts without checking active vector rows."""

        return self._vector_coverage_snapshot(verify_points=False)

    def _vector_coverage_snapshot(self, *, verify_points: bool) -> dict[str, Any]:
        self._require_vector()
        assert self.vector_profile_id is not None and self.vector_table_name is not None
        entries = self.store.list_history(archived_only=True, include_deleted=False)
        content_ids = {entry.content.id for entry in entries}
        with self.store.session_factory() as session:
            states = session.execute(
                select(
                    AskIndexContentRow.content_id,
                    AskIndexContentRow.status,
                    AskIndexContentRow.error_code,
                    AskIndexContentRow.source_hash,
                    AskIndexContentRow.chunk_count,
                ).where(
                    AskIndexContentRow.profile_id == self.vector_profile_id,
                    AskIndexContentRow.content_id.in_(content_ids) if content_ids else False,
                )
            ).all()
            fts_states = session.execute(
                select(
                    AskIndexContentRow.content_id,
                    AskIndexContentRow.source_hash,
                    AskIndexContentRow.status,
                ).where(
                    AskIndexContentRow.profile_id == self.profile_id,
                    AskIndexContentRow.content_id.in_(content_ids) if content_ids else False,
                )
            ).all()
            total_chunks = (
                session.query(AskIndexChunkRow)
                .filter(
                    AskIndexChunkRow.profile_id == self.profile_id,
                    AskIndexChunkRow.content_id.in_(content_ids) if content_ids else False,
                )
                .count()
            )
            if verify_points and content_ids:
                id_parameters = {
                    f"content_{index}": value
                    for index, value in enumerate(content_ids)
                }
                content_placeholders = ", ".join(f":{key}" for key in id_parameters)
                connection = session.connection()
                self._load_vector_extension(connection)
                covered_chunks = connection.execute(
                    text(
                        f"SELECT COUNT(*) FROM {self.vector_table_name} AS vectors "
                        "JOIN ask_index_chunks AS vector_chunks "
                        "ON vector_chunks.id = vectors.point_id "
                        "JOIN ask_index_contents AS vector_state "
                        "ON vector_state.profile_id = vector_chunks.profile_id "
                        "AND vector_state.content_id = vector_chunks.content_id "
                        "JOIN ask_index_contents AS fts_state "
                        "ON fts_state.content_id = vector_chunks.content_id "
                        "WHERE vector_chunks.profile_id = :vector_profile "
                        "AND vectors.active = 1 "
                        "AND fts_state.profile_id = :fts_profile "
                        "AND vector_state.status IN ('indexed', 'partial') "
                        "AND fts_state.status IN ('indexed', 'partial') "
                        "AND vector_state.source_hash = fts_state.source_hash "
                        f"AND vector_chunks.content_id IN ({content_placeholders})"
                    ),
                    {
                        "vector_profile": self.vector_profile_id,
                        "fts_profile": self.profile_id,
                        **id_parameters,
                    },
                ).scalar_one()
            elif verify_points:
                covered_chunks = 0
            else:
                fts_states = session.execute(
                    select(
                        AskIndexContentRow.content_id,
                        AskIndexContentRow.source_hash,
                        AskIndexContentRow.status,
                    ).where(
                        AskIndexContentRow.profile_id == self.profile_id,
                        AskIndexContentRow.content_id.in_(content_ids) if content_ids else False,
                    )
                ).all()
                fts_source_hashes = {
                    content_id: source_hash
                    for content_id, source_hash, status in fts_states
                    if status in {"indexed", "partial"}
                }
                status_record_covered_chunks = sum(
                    max(0, chunk_count)
                    for content_id, status, _error_code, source_hash, chunk_count in states
                    if status in {"indexed", "partial"}
                    and fts_source_hashes.get(content_id) == source_hash
                )
        counts = {"indexed": 0, "partial": 0, "failed": 0, "pending": 0}
        errors: dict[str, int] = {}
        processed: set[str] = set()
        for content_id, status, error_code, _source_hash, _chunk_count in states:
            processed.add(content_id)
            if status in counts:
                counts[status] += 1
            if error_code:
                errors[error_code] = errors.get(error_code, 0) + 1
        result = {
            "profile_id": self.vector_profile_id,
            "total_completed": len(content_ids),
            "indexed": counts["indexed"],
            "partial": counts["partial"],
            "failed": counts["failed"],
            "pending": counts["pending"] + len(content_ids - processed),
            "total_chunks": int(total_chunks),
            "errors": errors,
        }
        if verify_points:
            result["covered_chunks"] = int(covered_chunks)
        else:
            result["status_record_covered_chunks"] = int(status_record_covered_chunks)
            result["coverage_basis"] = "status_records"
            result["vector_points_verified"] = False
        return result

    def search(self, query: str, *, limit: int = 20) -> tuple[AskIndexHit, ...]:
        """Return FTS5 phrase-match candidates for diagnostic use."""

        phrase = " ".join(query.split())
        if len(phrase) < 3:
            return ()
        match = '"' + phrase.replace('"', '""') + '"'
        statement = text(
            "SELECT chunks.stable_id, chunks.content_id, chunks.source_kind, "
            "chunks.location_kind, chunks.source_ref, chunks.start_seconds, "
            "chunks.end_seconds, chunks.text_hash, chunks.content_text, "
            "bm25(ask_index_fts) AS rank, chunks.source_refs, chunks.chunk_ordinal "
            "FROM ask_index_fts "
            "JOIN ask_index_chunks AS chunks ON chunks.id = ask_index_fts.rowid "
            "JOIN content_items AS content ON content.id = chunks.content_id "
            "JOIN ask_index_contents AS state "
            "ON state.profile_id = chunks.profile_id AND state.content_id = chunks.content_id "
            "WHERE ask_index_fts MATCH :match AND chunks.profile_id = :profile_id "
            "AND content.deleted_at IS NULL AND state.status IN ('indexed', 'partial') "
            "ORDER BY rank ASC, chunks.content_id ASC, chunks.stable_id ASC LIMIT :limit"
        )
        with self.store.session_factory() as session:
            rows = session.execute(
                statement,
                {"match": match, "profile_id": self.profile_id, "limit": max(1, int(limit))},
            ).all()
        return tuple(_hit_from_search_row(row) for row in rows)

    def read_chunks(
        self,
        stable_ids: list[str] | tuple[str, ...],
        *,
        content_ids: list[str] | tuple[str, ...],
        neighbor_window: int = 0,
    ) -> tuple[AskIndexHit, ...]:
        """Read exact current chunks, constrained to the caller's frozen scope."""

        if not stable_ids or not content_ids:
            return ()
        if neighbor_window not in {0, 1}:
            raise ValueError("neighbor_window must be 0 or 1")
        ids = list(dict.fromkeys(stable_ids))[:8]
        contents = list(dict.fromkeys(content_ids))
        with self.store.session_factory() as session:
            rows = session.execute(
                select(AskIndexChunkRow).where(
                    AskIndexChunkRow.profile_id == self.profile_id,
                    AskIndexChunkRow.stable_id.in_(ids),
                    AskIndexChunkRow.content_id.in_(contents),
                )
            ).scalars().all()
            hits = {row.stable_id: _hit_from_chunk(row) for row in rows}
            if neighbor_window and rows:
                scopes = {(row.content_id, row.source_kind, row.location_kind) for row in rows}
                for content_id, source_kind, location_kind in scopes:
                    siblings = session.execute(
                        select(AskIndexChunkRow).where(
                            AskIndexChunkRow.profile_id == self.profile_id,
                            AskIndexChunkRow.content_id == content_id,
                            AskIndexChunkRow.source_kind == source_kind,
                            AskIndexChunkRow.location_kind == location_kind,
                        ).order_by(AskIndexChunkRow.chunk_ordinal)
                    ).scalars().all()
                    positions = {row.stable_id: index for index, row in enumerate(siblings)}
                    for row in rows:
                        if (row.content_id, row.source_kind, row.location_kind) != (content_id, source_kind, location_kind):
                            continue
                        index = positions.get(row.stable_id)
                        if index is None:
                            continue
                        for neighbor in siblings[max(0, index - 1): index + 2]:
                            hits.setdefault(neighbor.stable_id, _hit_from_chunk(neighbor))
        return tuple(sorted(
            hits.values(),
            key=lambda hit: (
                hit.content_id, hit.source_kind, hit.location_kind, hit.chunk_ordinal,
            ),
        ))

    def read_content_spans(
        self,
        content_id: str,
        *,
        evidence_kind: Literal["summary", "original"],
    ) -> tuple[AskIndexHit, ...]:
        """Read the complete currently indexed evidence layer for one content."""

        kind_filter = (
            AskIndexChunkRow.source_kind == "summary"
            if evidence_kind == "summary"
            else AskIndexChunkRow.source_kind != "summary"
        )
        with self.store.session_factory() as session:
            rows = session.execute(select(AskIndexChunkRow).where(
                AskIndexChunkRow.profile_id == self.profile_id,
                AskIndexChunkRow.content_id == content_id,
                kind_filter,
            ).order_by(
                AskIndexChunkRow.source_kind,
                AskIndexChunkRow.location_kind,
                AskIndexChunkRow.chunk_ordinal,
            )).scalars().all()
        return tuple(_hit_from_chunk(row) for row in rows)

    def search_keyword(
        self,
        query: str,
        *,
        limit: int = 20,
        content_ids: list[str] | tuple[str, ...] | None = None,
        vector_covered_only: bool = False,
        evidence_kind: Literal["summary", "original"] | None = None,
    ) -> tuple[AskIndexHit, ...]:
        """Return FTS5 trigram candidates, optionally requiring vector coverage."""

        terms = _keyword_trigrams(query)
        if not terms or (content_ids is not None and not content_ids):
            return ()
        match = " OR ".join(f'"{term}"' for term in terms)
        content_filter = ""
        parameters: dict[str, Any] = {
            "match": match,
            "profile_id": self.profile_id,
            "limit": max(1, int(limit)),
        }
        vector_coverage_filter = ""
        if vector_covered_only:
            self._require_vector()
            assert self.vector_profile_id is not None
            assert self.vector_table_name is not None
            parameters["vector_profile"] = self.vector_profile_id
            vector_coverage_filter = (
                " AND EXISTS ("
                "SELECT 1 FROM ask_index_chunks AS vector_chunks "
                "JOIN ask_index_contents AS vector_state "
                "ON vector_state.profile_id = vector_chunks.profile_id "
                "AND vector_state.content_id = vector_chunks.content_id "
                "JOIN ask_index_contents AS fts_state "
                "ON fts_state.profile_id = :profile_id "
                "AND fts_state.content_id = chunks.content_id "
                f"JOIN {self.vector_table_name} AS vectors "
                "ON vectors.point_id = vector_chunks.id "
                "AND vectors.profile_id = vector_chunks.profile_id "
                "AND vectors.content_id = vector_chunks.content_id "
                "AND vectors.stable_id = vector_chunks.stable_id "
                "AND vectors.active = 1 "
                "WHERE vector_chunks.profile_id = :vector_profile "
                "AND vector_chunks.content_id = chunks.content_id "
                "AND vector_chunks.source_kind = chunks.source_kind "
                "AND vector_chunks.location_kind = chunks.location_kind "
                "AND vector_chunks.source_ref = chunks.source_ref "
                "AND vector_chunks.text_hash = chunks.text_hash "
                "AND vector_state.status IN ('indexed', 'partial') "
                "AND fts_state.status IN ('indexed', 'partial') "
                "AND vector_state.source_hash = fts_state.source_hash)"
            )
        if content_ids is not None:
            placeholders = []
            for index, content_id in enumerate(dict.fromkeys(content_ids)):
                key = f"content_id_{index}"
                placeholders.append(f":{key}")
                parameters[key] = content_id
            content_filter = f" AND chunks.content_id IN ({', '.join(placeholders)})"
        evidence_filter = ""
        if evidence_kind == "summary":
            evidence_filter = " AND chunks.source_kind = 'summary'"
        elif evidence_kind == "original":
            evidence_filter = " AND chunks.source_kind != 'summary'"
        statement = text(
            "SELECT chunks.stable_id, chunks.content_id, chunks.source_kind, "
            "chunks.location_kind, chunks.source_ref, chunks.start_seconds, "
            "chunks.end_seconds, chunks.text_hash, chunks.content_text, "
            "bm25(ask_index_fts) AS rank, chunks.source_refs, chunks.chunk_ordinal "
            "FROM ask_index_fts "
            "JOIN ask_index_chunks AS chunks ON chunks.id = ask_index_fts.rowid "
            "JOIN content_items AS content ON content.id = chunks.content_id "
            "JOIN ask_index_contents AS state "
            "ON state.profile_id = chunks.profile_id AND state.content_id = chunks.content_id "
            "WHERE ask_index_fts MATCH :match AND chunks.profile_id = :profile_id "
            "AND content.deleted_at IS NULL AND state.status IN ('indexed', 'partial') "
            f"{content_filter}{evidence_filter}{vector_coverage_filter} "
            "ORDER BY rank ASC, chunks.content_id ASC, chunks.stable_id ASC LIMIT :limit"
        )
        with self.store.session_factory() as session:
            if vector_covered_only:
                self._load_vector_extension(session.connection())
            rows = session.execute(statement, parameters).all()
        return tuple(_hit_from_search_row(row) for row in rows)

    def search_vector(
        self,
        query: str,
        *,
        limit: int = 20,
        content_ids: list[str] | tuple[str, ...] | None = None,
        evidence_kind: Literal["summary", "original"] | None = None,
        timeout: float = 60,
        query_vector: list[float] | tuple[float, ...] | None = None,
    ) -> tuple[AskIndexHit, ...]:
        """Return vector candidates without falling back to keyword search."""

        backend = self._require_vector()
        if not query.strip() or (content_ids is not None and not content_ids):
            return ()
        vector = query_vector if query_vector is not None else self.embed_query(query, timeout=timeout)
        _validate_vector(vector, backend.dimension)
        assert self.vector_profile_id is not None and self.vector_table_name is not None
        eligible_ids = self._eligible_vector_content_ids(content_ids)
        if not eligible_ids:
            return ()

        vector_bytes = struct.pack(f"{backend.dimension}f", *vector)
        candidate_rows: list[tuple[int, float]] = []
        source_filter = (
            " AND source_kind = 'summary'"
            if evidence_kind == "summary"
            else " AND source_kind != 'summary'"
            if evidence_kind == "original"
            else ""
        )
        with self.store.engine.connect() as connection:
            self._load_vector_extension(connection)
            for content_id in eligible_ids:
                rows = connection.exec_driver_sql(
                    f"SELECT point_id, distance FROM {self.vector_table_name} "
                    "WHERE embedding MATCH ? AND k = ? AND profile_id = ? "
                    "AND content_id = ? AND active = 1"
                    f"{source_filter} ORDER BY distance",
                    (
                        vector_bytes,
                        max(1, int(limit)),
                        self.vector_profile_id,
                        content_id,
                    ),
                ).all()
                candidate_rows.extend(
                    (int(point_id), float(distance)) for point_id, distance in rows
                )
        candidate_rows.sort(key=lambda item: (item[1], item[0]))
        candidate_rows = candidate_rows[: max(1, int(limit))]
        if not candidate_rows:
            return ()

        point_ids = [point_id for point_id, _ in candidate_rows]
        distances = dict(candidate_rows)
        placeholders = ", ".join(f":point_{index}" for index in range(len(point_ids)))
        query_parameters = {
            "vector_profile": self.vector_profile_id,
            "fts_profile": self.profile_id,
            **{f"point_{index}": point_id for index, point_id in enumerate(point_ids)},
        }
        statement = text(
            "SELECT chunks.id, chunks.content_id, chunks.source_kind, "
            "chunks.location_kind, chunks.source_ref, chunks.start_seconds, "
            "chunks.end_seconds, chunks.text_hash, chunks.content_text, "
            "chunks.source_refs, chunks.chunk_ordinal "
            "FROM ask_index_chunks AS chunks "
            "JOIN content_items AS content ON content.id = chunks.content_id "
            "JOIN ask_index_contents AS vector_state "
            "ON vector_state.profile_id = chunks.profile_id "
            "AND vector_state.content_id = chunks.content_id "
            "JOIN ask_index_contents AS fts_state "
            "ON fts_state.profile_id = :fts_profile "
            "AND fts_state.content_id = chunks.content_id "
            "WHERE chunks.profile_id = :vector_profile "
            "AND content.deleted_at IS NULL "
            "AND vector_state.status IN ('indexed', 'partial') "
            "AND fts_state.status IN ('indexed', 'partial') "
            "AND vector_state.source_hash = fts_state.source_hash "
            f"AND chunks.id IN ({placeholders})"
        )
        with self.store.session_factory() as session:
            rows = session.execute(statement, query_parameters).all()
        hits_by_id = {
            int(row[0]): AskIndexHit(
                _stable_id_for_profile(
                    self.profile_id,
                    row[1],
                    row[2],
                    row[3],
                    row[4],
                    row[5],
                    row[6],
                    row[7],
                    row[10],
                    _decode_source_refs(row[9], row[4]),
                ),
                row[1],
                row[2],
                row[3],
                row[4],
                row[5],
                row[6],
                row[7],
                row[8],
                distances[int(row[0])],
                tuple(_decode_source_refs(row[9], row[4])),
                int(row[10]),
            )
            for row in rows
        }
        return tuple(
            hits_by_id[point_id]
            for point_id, _ in candidate_rows
            if point_id in hits_by_id
        )

    def search_hybrid(
        self,
        query: str,
        *,
        limit: int = 20,
        content_ids: list[str] | tuple[str, ...] | None = None,
        evidence_kind: Literal["summary", "original"] | None = None,
        rerank: bool = False,
        rerank_backend: SiliconFlowRetrieval | None = None,
        ranking_trace: dict[str, Any] | None = None,
        timeout: float = 60,
        query_vector: list[float] | tuple[float, ...] | None = None,
    ) -> tuple[AskIndexHit, ...]:
        """Fuse explicit keyword and vector candidates with reciprocal ranks."""

        self._require_vector()
        candidate_limit = max(20, max(1, int(limit)) * 4)
        keyword_hits = self.search_keyword(
            query,
            limit=candidate_limit,
            content_ids=content_ids,
            vector_covered_only=True,
            evidence_kind=evidence_kind,
        )
        vector_hits = self.search_vector(
            query,
            limit=candidate_limit,
            content_ids=content_ids,
            evidence_kind=evidence_kind,
            timeout=timeout,
            query_vector=query_vector,
        )
        scores: dict[str, float] = {}
        hits_by_id: dict[str, AskIndexHit] = {}
        for hits in (keyword_hits, vector_hits):
            for rank, hit in enumerate(hits, start=1):
                scores[hit.stable_id] = scores.get(hit.stable_id, 0.0) + 1.0 / (60 + rank)
                hits_by_id[hit.stable_id] = hit
        ordered_ids = sorted(
            scores,
            key=lambda stable_id: (
                -scores[stable_id],
                hits_by_id[stable_id].content_id,
                stable_id,
            ),
        )[:candidate_limit]
        candidates = tuple(
            replace(hits_by_id[stable_id], rank=scores[stable_id])
            for stable_id in ordered_ids
        )
        if ranking_trace is not None:
            ranking_trace["rrf_ids"] = [hit.stable_id for hit in candidates]
        backend = rerank_backend or self._embedding_backend
        if rerank and isinstance(backend, SiliconFlowRetrieval) and candidates:
            with self.store.session_factory() as session:
                titles = dict(session.execute(
                    select(ContentRow.id, ContentRow.title).where(
                        ContentRow.id.in_({hit.content_id for hit in candidates})
                    )
                ).all())
            try:
                ranking = backend.rerank(query, [
                    f"{titles.get(hit.content_id, '')}\n{hit.text}" for hit in candidates
                ], timeout=timeout)
            except AskEmbeddingUnavailableError:
                if ranking_trace is None:
                    raise
                ranking_trace["status"] = "unavailable"
            else:
                if ranking_trace is not None:
                    ranking_trace.update(status="applied", candidates=len(candidates))
                    ranking_trace["reranked_ids"] = [candidates[index].stable_id for index, _ in ranking]
                return tuple(
                    replace(candidates[index], rank=score)
                    for index, score in ranking[: max(1, int(limit))]
                )
        return candidates[: max(1, int(limit))]

    def _eligible_vector_content_ids(
        self, content_ids: list[str] | tuple[str, ...] | None
    ) -> list[str]:
        assert self.vector_profile_id is not None
        with self.store.session_factory() as session:
            fts_states = session.execute(
                text(
                    "SELECT state.content_id, state.source_hash FROM ask_index_contents AS state "
                    "JOIN content_items AS content ON content.id = state.content_id "
                    "WHERE state.profile_id = :profile_id "
                    "AND state.status IN ('indexed', 'partial') AND content.deleted_at IS NULL"
                ),
                {"profile_id": self.profile_id},
            ).all()
            vector_states = session.execute(
                text(
                    "SELECT content_id, source_hash FROM ask_index_contents "
                    "WHERE profile_id = :profile_id AND status IN ('indexed', 'partial')"
                ),
                {"profile_id": self.vector_profile_id},
            ).all()
        current_fts = dict(fts_states)
        current_vectors = dict(vector_states)
        eligible = [
            content_id
            for content_id, source_hash in current_fts.items()
            if current_vectors.get(content_id) == source_hash
        ]
        if content_ids is not None:
            requested = set(content_ids)
            eligible = [content_id for content_id in eligible if content_id in requested]
        return sorted(eligible)

    def _resolve_archive(self, archive_path: str | Path) -> Path:
        directory = Path(archive_path).expanduser().resolve()
        if directory != self.archive_root and self.archive_root not in directory.parents:
            raise _ArchiveIndexError("archive_path_outside_root")
        if not directory.is_dir():
            raise _ArchiveIndexError("archive_missing")
        return directory

    def _cached_chunking(
        self, content_id: str, input_hash: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
        with self.store.session_factory() as session:
            state = session.get(AskIndexContentRow, (self.profile_id, content_id))
            if (
                state is None
                or state.chunking_input_hash != input_hash
                or state.chunking_status is None
                or state.status not in {"indexed", "partial"}
            ):
                return None
            rows = session.execute(select(AskIndexChunkRow).where(
                AskIndexChunkRow.profile_id == self.profile_id,
                AskIndexChunkRow.content_id == content_id,
            ).order_by(
                AskIndexChunkRow.source_kind,
                AskIndexChunkRow.location_kind,
                AskIndexChunkRow.chunk_ordinal,
            )).scalars().all()
            if not rows or len(rows) != state.chunk_count:
                return None
            spans = [{
                "stable_id": row.stable_id,
                "source_kind": row.source_kind,
                "location_kind": row.location_kind,
                "source_ref": row.source_ref,
                "source_refs": list(row.source_refs or [row.source_ref]),
                "chunk_ordinal": row.chunk_ordinal,
                "start_seconds": row.start_seconds,
                "end_seconds": row.end_seconds,
                "text_hash": row.text_hash,
                "text": row.content_text,
            } for row in rows]
            chunking = {
                "status": state.chunking_status,
                "calls": state.chunking_calls,
                "input_bytes": state.chunking_input_bytes,
                "output_tokens": state.chunking_output_tokens,
                "error_code": state.chunking_error_code,
                "trace": state.chunking_trace or [],
            }
        return spans, chunking

    def _build_chunks(
        self, source_units: list[dict[str, Any]], content_id: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for source_unit in source_units:
            source_kind = source_unit["source_kind"]
            location_kind = source_unit["location_kind"]
            grouped.setdefault((source_kind, location_kind), []).extend(
                _split_source_unit(source_unit)
            )

        deadline = monotonic() + MAX_BOUNDARY_SECONDS_PER_CONTENT
        call_count = input_bytes = output_tokens = successful_windows = fallback_windows = 0
        output_tokens_known = True
        error_code = None
        chunking_trace: list[dict[str, Any]] = []
        spans: list[dict[str, Any]] = []
        for (source_kind, location_kind), units in grouped.items():
            group_spans: list[dict[str, Any]] = []
            for window in _source_windows(units):
                proposed_ends = None
                proposal_trace = None
                if self._chunk_boundary_proposer is not None:
                    remaining = deadline - monotonic()
                    if call_count >= MAX_BOUNDARY_CALLS_PER_CONTENT:
                        error_code = error_code or "boundary_call_budget_exhausted"
                    elif remaining < 1:
                        error_code = error_code or "boundary_time_budget_exhausted"
                    else:
                        call_count += 1
                        try:
                            response, meta = self._chunk_boundary_proposer(
                                source_kind, window, timeout=remaining,
                            )
                            meta = meta if isinstance(meta, dict) else {}
                            reported_bytes = meta.get("input_bytes")
                            input_bytes += (
                                int(reported_bytes) if isinstance(reported_bytes, int)
                                and reported_bytes >= 0 else _source_window_bytes(window)
                            )
                            usage = meta.get("usage")
                            used_tokens = (
                                usage.get("completion_tokens", usage.get("output_tokens"))
                                if isinstance(usage, dict) else None
                            )
                            if isinstance(used_tokens, int) and used_tokens >= 0:
                                output_tokens += used_tokens
                            else:
                                output_tokens_known = False
                            proposed_ends = _valid_boundary_ends(response, len(window))
                            returned_ends = response.get("ends") if isinstance(response, dict) else None
                            recorded_ends = (
                                [value for value in returned_ends if isinstance(value, int)
                                 and not isinstance(value, bool)][:128]
                                if isinstance(returned_ends, list) else None
                            )
                            proposal_trace = {
                                "source_kind": source_kind,
                                "source_refs": list(dict.fromkeys(
                                    unit["source_ref"] for unit in window
                                )),
                                "unit_count": len(window),
                                "boundary_ends": recorded_ends,
                                "accepted": proposed_ends is not None,
                                "input_bytes": (
                                    int(reported_bytes) if isinstance(reported_bytes, int)
                                    and reported_bytes >= 0 else _source_window_bytes(window)
                                ),
                                "output_tokens": used_tokens if isinstance(used_tokens, int) else None,
                                "error_code": None if proposed_ends is not None else "boundary_output_invalid",
                            }
                            if proposed_ends is None:
                                error_code = error_code or "boundary_output_invalid"
                        except Exception as error:
                            logger.info(
                                "RAG chunk boundary proposal failed for %s (%s)",
                                content_id, type(error).__name__,
                            )
                            error_code = error_code or "boundary_model_failed"
                            failed_input_bytes = _source_window_bytes(window)
                            input_bytes += failed_input_bytes
                            proposal_trace = {
                                "source_kind": source_kind,
                                "source_refs": list(dict.fromkeys(
                                    unit["source_ref"] for unit in window
                                )),
                                "unit_count": len(window),
                                "boundary_ends": None,
                                "accepted": False,
                                "input_bytes": failed_input_bytes,
                                "output_tokens": None,
                                "error_code": "boundary_model_failed",
                            }

                window_spans = (
                    _chunks_from_boundaries(
                        window, proposed_ends, source_kind, location_kind,
                        first_ordinal=len(group_spans) + 1,
                    ) if proposed_ends is not None else None
                )
                if window_spans is None:
                    if proposed_ends is not None:
                        error_code = error_code or "boundary_output_oversize"
                        if proposal_trace is not None:
                            proposal_trace["accepted"] = False
                            proposal_trace["error_code"] = "boundary_output_oversize"
                    fallback_windows += 1
                    window_spans = _chunks_by_size(
                        window, source_kind, location_kind,
                        first_ordinal=len(group_spans) + 1,
                    )
                    if self._chunk_boundary_proposer is None:
                        error_code = "summary_model_unconfigured"
                else:
                    successful_windows += 1
                    if proposal_trace is not None:
                        proposal_trace["accepted"] = True
                        proposal_trace["error_code"] = None
                if proposal_trace is not None:
                    chunking_trace.append(proposal_trace)
                group_spans.extend(window_spans)

            for span in group_spans:
                span["text_hash"] = hashlib.sha256(span["text"].encode("utf-8")).hexdigest()
                span["stable_id"] = _stable_id_for_profile(
                    self.profile_id,
                    content_id,
                    span["source_kind"],
                    span["location_kind"],
                    span["source_ref"],
                    span["start_seconds"],
                    span["end_seconds"],
                    span["text_hash"],
                    span["chunk_ordinal"],
                    span["source_refs"],
                )
            spans.extend(group_spans)

        if self._chunk_boundary_proposer is None:
            status = "rules_only"
        elif fallback_windows and successful_windows:
            status = "partial_fallback"
        elif fallback_windows:
            status = "fallback"
        else:
            status = "model"
        chunking = {
            "status": status,
            "calls": call_count,
            "input_bytes": input_bytes,
            "output_tokens": output_tokens if output_tokens_known else None,
            "error_code": error_code,
            "trace": chunking_trace,
        }
        return spans, chunking

    def _read_spans(
        self,
        directory: Path,
        content_id: str,
        summary_text: str | None,
    ) -> list[dict[str, Any]]:
        record_path = directory / "record.json"
        if not record_path.is_file():
            raise _ArchiveIndexError("archive_record_missing")
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or record.get("content_id") != content_id:
            raise _ArchiveIndexError("archive_content_mismatch")
        try:
            validate_record(record)
        except ArchiveSchemaError as error:
            raise _ArchiveIndexError("archive_record_invalid") from error

        specs: list[dict[str, Any]] = []
        transcript_path = directory / "transcript.json"
        if transcript_path.is_file():
            raw_transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
            if not isinstance(raw_transcript, dict) or not isinstance(
                raw_transcript.get("segments"), list
            ):
                raise _ArchiveIndexError("archive_transcript_invalid")
            source_kind = str(
                raw_transcript.get("source_kind")
                or record.get("transcript_source")
                or "unknown"
            )
            record_source = str(record.get("transcript_source") or "")
            if record_source and source_kind != record_source:
                raise _ArchiveIndexError("archive_source_mismatch")
            for ordinal, segment in enumerate(map_transcript_segments(raw_transcript), start=1):
                specs.append(
                    {
                        "source_kind": segment.source_kind,
                        "location_kind": segment.location_kind,
                        "source_ref": segment.source_ref,
                        "ordinal": ordinal,
                        "start_seconds": segment.start_seconds,
                        "end_seconds": segment.end_seconds,
                        "text": segment.text,
                    }
                )

        if isinstance(summary_text, str) and summary_text.strip():
            for ordinal, paragraph in enumerate(_summary_paragraphs(summary_text), start=1):
                specs.append(
                    {
                        "source_kind": "summary",
                        "location_kind": "summary",
                        "source_ref": f"summary:paragraph:{ordinal}",
                        "ordinal": ordinal,
                        "start_seconds": None,
                        "end_seconds": None,
                        "text": paragraph,
                    }
                )

        return specs


def _split_source_unit(unit: dict[str, Any]) -> list[dict[str, Any]]:
    max_text_bytes = MAX_CHUNK_UTF8_BYTES - 512
    text_value = unit["text"]
    if len(text_value.encode("utf-8")) <= max_text_bytes:
        return [dict(unit)]
    pieces: list[str] = []
    remaining = text_value
    while remaining:
        if len(remaining.encode("utf-8")) <= max_text_bytes:
            pieces.append(remaining)
            break
        used = 0
        end = 0
        for end, character in enumerate(remaining, start=1):
            used += len(character.encode("utf-8"))
            if used > max_text_bytes:
                end -= 1
                break
        prefix = remaining[:end]
        sentence_breaks = [match.end() for match in re.finditer(r"[。！？!?；;\n]", prefix)]
        split_at = (
            sentence_breaks[-1]
            if sentence_breaks and sentence_breaks[-1] >= len(prefix) // 2
            else len(prefix)
        )
        pieces.append(remaining[:split_at])
        remaining = remaining[split_at:]
    return [{**unit, "text": piece} for piece in pieces if piece.strip()]


def _source_unit_bytes(unit: dict[str, Any]) -> int:
    value = {
        "ordinal": unit["ordinal"],
        "source_ref": unit["source_ref"],
        "text": unit["text"],
    }
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _source_windows(units: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    windows: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_bytes = 0
    for unit in units:
        unit_bytes = _source_unit_bytes(unit)
        if current and current_bytes + unit_bytes > BOUNDARY_WINDOW_UTF8_BYTES:
            windows.append(current)
            current = []
            current_bytes = 0
        current.append(unit)
        current_bytes += unit_bytes
    if current:
        windows.append(current)
    return windows


def _source_window_bytes(units: list[dict[str, Any]]) -> int:
    return sum(_source_unit_bytes(unit) for unit in units)


def _valid_boundary_ends(response: Any, unit_count: int) -> list[int] | None:
    if not isinstance(response, dict):
        return None
    ends = response.get("ends")
    if not isinstance(ends, list) or not ends or ends[-1] != unit_count:
        return None
    if any(not isinstance(end, int) or isinstance(end, bool) for end in ends):
        return None
    if any(end <= 0 for end in ends) or any(
        left >= right for left, right in zip(ends, ends[1:])
    ):
        return None
    return ends


def _render_chunk(
    units: list[dict[str, Any]], source_kind: str, location_kind: str, ordinal: int,
) -> dict[str, Any] | None:
    refs = list(dict.fromkeys(unit["source_ref"] for unit in units))
    text_value = "\n".join(unit["text"] for unit in units).strip()
    if len(text_value.encode("utf-8")) > MAX_CHUNK_UTF8_BYTES:
        return None
    timed_units = [unit for unit in units if unit["start_seconds"] is not None]
    start_seconds = timed_units[0]["start_seconds"] if timed_units else None
    end_seconds = next(
        (unit["end_seconds"] for unit in reversed(units) if unit["end_seconds"] is not None),
        None,
    )
    return {
        "source_kind": source_kind,
        "location_kind": location_kind,
        "source_ref": refs[0],
        "source_refs": refs,
        "chunk_ordinal": ordinal,
        "start_seconds": start_seconds,
        "end_seconds": end_seconds,
        "text": text_value,
    }


def _chunks_from_boundaries(
    units: list[dict[str, Any]],
    ends: list[int],
    source_kind: str,
    location_kind: str,
    *,
    first_ordinal: int,
) -> list[dict[str, Any]] | None:
    chunks: list[dict[str, Any]] = []
    start = 0
    for end in ends:
        chunk = _render_chunk(
            units[start:end], source_kind, location_kind, first_ordinal + len(chunks),
        )
        if chunk is None:
            return None
        chunks.append(chunk)
        start = end
    return chunks if start == len(units) else None


def _chunks_by_size(
    units: list[dict[str, Any]],
    source_kind: str,
    location_kind: str,
    *,
    first_ordinal: int,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    for unit in units:
        candidate = [*current, unit]
        if current and _render_chunk(
            candidate, source_kind, location_kind, first_ordinal + len(chunks),
        ) is None:
            chunk = _render_chunk(
                current, source_kind, location_kind, first_ordinal + len(chunks),
            )
            if chunk is not None:
                chunks.append(chunk)
            current = [unit]
        else:
            current = candidate
        if _render_chunk(
            current, source_kind, location_kind, first_ordinal + len(chunks),
        ) is None:
            raise ValueError("source unit exceeds chunk byte limit")
    if current:
        chunk = _render_chunk(
            current, source_kind, location_kind, first_ordinal + len(chunks),
        )
        if chunk is not None:
            chunks.append(chunk)
    return chunks


class _ArchiveIndexError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _hit_from_chunk(row: AskIndexChunkRow) -> AskIndexHit:
    return AskIndexHit(
        row.stable_id,
        row.content_id,
        row.source_kind,
        row.location_kind,
        row.source_ref,
        row.start_seconds,
        row.end_seconds,
        row.text_hash,
        row.content_text,
        0.0,
        tuple(row.source_refs or [row.source_ref]),
        row.chunk_ordinal,
    )


def _decode_source_refs(value: Any, fallback: str) -> tuple[str, ...]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = None
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value) or (fallback,)
    if isinstance(value, tuple) and all(isinstance(item, str) for item in value):
        return value or (fallback,)
    return (fallback,)


def _hit_from_search_row(row) -> AskIndexHit:
    return AskIndexHit(
        row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9],
        _decode_source_refs(row[10], row[4]), int(row[11]),
    )


def _summary_paragraphs(markdown: str) -> tuple[str, ...]:
    paragraphs: list[str] = []
    heading: str | None = None
    for block in re.split(r"\n\s*\n", markdown.strip()):
        text_block = block.strip()
        if not text_block:
            continue
        if text_block.startswith("#") and "\n" not in text_block:
            heading = text_block
            continue
        if heading:
            text_block = f"{heading}\n{text_block}"
            heading = None
        paragraphs.append(text_block)
    return tuple(paragraphs)


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _stable_id_for_profile(
    profile_id: str,
    content_id: str,
    source_kind: str,
    location_kind: str,
    source_ref: str,
    start_seconds: float | None,
    end_seconds: float | None,
    text_hash: str,
    chunk_ordinal: int,
    source_refs: list[str] | tuple[str, ...],
) -> str:
    return _stable_hash(
        {
            "profile_id": profile_id,
            "content_id": content_id,
            "source_kind": source_kind,
            "location_kind": location_kind,
            "source_ref": source_ref,
            "start_seconds": start_seconds,
            "end_seconds": end_seconds,
            "text_hash": text_hash,
            "chunk_ordinal": chunk_ordinal,
            "source_refs": list(source_refs),
        }
    )


def _span_for_profile(
    span: dict[str, Any], content_id: str, profile_id: str
) -> dict[str, Any]:
    result = dict(span)
    result["stable_id"] = _stable_id_for_profile(
        profile_id,
        content_id,
        span["source_kind"],
        span["location_kind"],
        span["source_ref"],
        span["start_seconds"],
        span["end_seconds"],
        span["text_hash"],
        span["chunk_ordinal"],
        span["source_refs"],
    )
    return result


def _validate_vector(vector, dimension: int) -> list[float]:
    if not isinstance(vector, (list, tuple)) or len(vector) != dimension:
        raise AskEmbeddingUnavailableError("embedding 返回向量维度不匹配")
    try:
        values = [float(value) for value in vector]
    except (TypeError, ValueError) as error:
        raise AskEmbeddingUnavailableError("embedding 返回了非数值向量") from error
    if not all(math.isfinite(value) for value in values):
        raise AskEmbeddingUnavailableError("embedding 返回了非有限值")
    norm = math.sqrt(sum(value * value for value in values))
    if not math.isclose(norm, 1.0, rel_tol=1e-3, abs_tol=1e-3):
        raise AskEmbeddingUnavailableError("embedding 返回向量未按 L2 归一化")
    return values


def _keyword_trigrams(query: str) -> tuple[str, ...]:
    terms: list[str] = []
    for token in re.findall(r"[\w]+", " ".join(query.split()).casefold(), flags=re.UNICODE):
        terms.extend(token[offset : offset + 3] for offset in range(len(token) - 2))
    return tuple(dict.fromkeys(terms))
