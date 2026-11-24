"""Small transactional store used by the API and future worker."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
import re
from statistics import median
from typing import Any
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import DateTime, case, create_engine, delete, event, exists, func, or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import (
    AnalysisRunRow,
    AsrPerformanceSampleRow,
    AsrSegmentRow,
    AppSettingRow,
    Base,
    ContentTagRow,
    ContentFavoriteFolderRow,
    ContentRow,
    ContentSummaryRow,
    FavoriteFolderRow,
    JobFeedbackRow,
    JobEventRow,
    JobRow,
    PlatformConnectionRow,
    SummaryFeedbackRow,
    SummaryVersionRow,
    TagRow,
)
from app.domain.jobs import Job, JobState, StaleJobAttemptError
from app.domain.models import (
    AnalysisRun,
    AnalysisSettings,
    ContentItem,
    ContentKind,
    SourcePlatform,
    SourceRecord,
    new_id,
)
from app.platforms.secrets import protect_secret, unprotect_secret

PROTECTED_SETTING_KEYS = frozenset(
    {
        "summary_api_key",
        "ask_api_key",
        "asr_api_key",
        "asr_cloud_api_key",
        "bilibili_session_cookie",
        "bilibili_refresh_token",
    }
)

_EVENT_STAGE_BY_CHECKPOINT = {
    "source_ready": "source",
    "acquiring": "source",
    "extracting": "source",
    "text_loaded": "source",
    "transcript_ready": "transcription",
    "transcribing": "transcription",
    "chunks_ready": "chunking",
    "chunking": "chunking",
    "summary_ready": "summary",
    "summarizing": "summary",
    "archiving": "archive",
    "indexing": "archive",
    "indexed": "archive",
}

_EVENT_STATE_LABEL = {
    "queued": "任务已排队",
    "acquiring": "开始获取来源",
    "extracting": "正在提取内容",
    "transcribing": "正在转写内容",
    "chunking": "正在切分转写内容",
    "summarizing": "正在生成总结",
    "archiving": "正在保存归档",
    "indexing": "正在建立索引",
    "paused": "任务已暂停",
    "completed": "任务已完成",
    "failed": "任务失败",
    "cancelled": "任务已取消",
}


class ContentNotFoundError(LookupError):
    pass


class AnalysisRunNotFoundError(LookupError):
    pass


class FavoriteFolderNotFoundError(LookupError):
    pass


class TagNotFoundError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    content: ContentItem
    run: AnalysisRun
    job: Job


@dataclass(frozen=True, slots=True)
class JobEvent:
    id: str
    job_id: str
    sequence: int
    attempt: int
    event_type: str
    stage: str | None
    state: str
    progress: int
    checkpoint: str | None
    error_code: str | None
    message: str
    details: dict[str, Any]
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class AsrSegmentCheckpoint:
    id: str
    job_id: str
    config_fingerprint: str
    segment_index: int
    start_seconds: float
    end_seconds: float
    status: str
    text: str | None
    language: str | None
    attempts: int
    lease_owner: str | None
    lease_expires_at: datetime | None
    worker_generation: int
    heartbeat_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AsrPerformanceSample:
    id: str
    engine: str
    device: str
    audio_seconds: float
    elapsed_seconds: float
    rtf: float
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SummaryVersion:
    id: str
    content_id: str
    version_number: int
    parent_version_id: str | None
    origin: str
    template: str
    chapter_title: str | None
    source_start_seconds: float | None
    source_end_seconds: float | None
    markdown: str
    created_at: datetime
    summary_strength: str | None = None
    summary_style: str | None = None
    material_level: str | None = None
    source_version: str | None = None
    source_scope: dict[str, Any] | None = None
    processed_source_refs: list[str] | None = None
    expected_source_refs: list[str] | None = None
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None


@dataclass(frozen=True, slots=True)
class SummaryFeedback:
    id: str
    content_id: str
    version_id: str | None
    category: str
    note: str | None
    context: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TaskFeedback:
    id: str
    job_id: str
    content_id: str
    category: str
    note: str | None
    context: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PlatformConnection:
    platform: str
    status: str
    auth_type: str
    account_label: str | None
    browser: str | None
    browser_profile: str | None
    login_url: str | None
    last_checked_at: datetime | None
    last_connected_at: datetime | None
    message: str | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class FavoriteFolder:
    id: str
    name: str
    parent_id: str | None
    content_count: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Tag:
    id: str
    name: str
    user_id: str
    content_count: int
    created_at: datetime
    updated_at: datetime


def _bilibili_source_identity(canonical_url: str | None) -> tuple[str, int] | None:
    if not canonical_url:
        return None
    parsed = urlsplit(canonical_url)
    host = (parsed.hostname or "").lower()
    if host != "bilibili.com" and not host.endswith(".bilibili.com"):
        return None
    match = re.search(r"(?:^|/)(BV[0-9A-Za-z]{10})(?:/|$)", parsed.path)
    if not match:
        return None
    try:
        page_number = int(parse_qs(parsed.query).get("p", ["1"])[0])
    except (TypeError, ValueError):
        page_number = 1
    return match.group(1), max(1, page_number)


class SQLiteStore:
    """Persistence facade; callers do not depend on SQLAlchemy row objects."""

    def __init__(self, database_url: str | None = None) -> None:
        database_url = database_url or (
            f"sqlite:///{(Path(__file__).resolve().parents[5] / 'local' / 'knowledge.db').as_posix()}"
        )
        engine_kwargs: dict[str, Any] = {"future": True}
        serialize_memory_connection = database_url in {"sqlite://", "sqlite:///:memory:"}
        if database_url.startswith("sqlite"):
            engine_kwargs["connect_args"] = {"check_same_thread": False}
        if serialize_memory_connection:
            engine_kwargs["poolclass"] = StaticPool
        self.engine: Engine = create_engine(database_url, **engine_kwargs)
        if database_url.startswith("sqlite"):
            @event.listens_for(self.engine, "connect")
            def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
                cursor = dbapi_connection.cursor()
                try:
                    cursor.execute("PRAGMA foreign_keys=ON")
                    # 向量检索要在 113MB 库里逐内容读块；不开 mmap 时每次约 150ms，
                    # 34 个内容累计 10 秒以上。mmap 之外还要放大页缓存，
                    # 默认 2MB 会被反复淘汰，耗时在 0.6~3 秒间抖动。
                    cursor.execute("PRAGMA mmap_size=536870912")
                    cursor.execute("PRAGMA cache_size=-65536")
                finally:
                    cursor.close()

        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)
        Base.metadata.create_all(self.engine)
        self._ensure_runtime_schema()

    def _ensure_runtime_schema(self) -> None:
        """Add local-only columns when an older desktop DB is opened."""

        with self.engine.begin() as connection:
            table_additions = {
                "jobs": {
                    "started_at": "DATETIME",
                    "completed_at": "DATETIME",
                    "priority": "INTEGER NOT NULL DEFAULT 0",
                    "queue_position": "INTEGER",
                },
                "content_items": {
                    "thumbnail_url": "TEXT",
                    "published_at": "DATETIME",
                    "acquired_at": "DATETIME",
                    "acquisition_method": "TEXT NOT NULL DEFAULT 'adapter'",
                    "category": "VARCHAR(120) NOT NULL DEFAULT '未分类'",
                    "favorite": "BOOLEAN NOT NULL DEFAULT 0",
                    "deleted_at": "DATETIME",
                    "processing_model": "VARCHAR(200)",
                    "introduction": "TEXT NOT NULL DEFAULT ''",
                },
                "favorite_folders": {
                    "parent_id": "VARCHAR(80)",
                },
                "content_summaries": {
                    "transcript_text": "TEXT",
                    "source_note": "TEXT",
                },
                "summary_feedback": {
                    "context_json": "JSON",
                },
                "summary_versions": {
                    "summary_strength": "VARCHAR(16)",
                    "summary_style": "VARCHAR(32)",
                    "material_level": "VARCHAR(8)",
                    "source_version": "VARCHAR(80)",
                    "source_scope": "JSON",
                    "processed_source_refs": "JSON",
                    "expected_source_refs": "JSON",
                    "provider": "VARCHAR(80)",
                    "model": "VARCHAR(200)",
                    "prompt_version": "VARCHAR(80)",
                },
                "rag_detail_tags": {
                    "display_name": "VARCHAR(16) NOT NULL DEFAULT ''",
                    "source_reviewed": "BOOLEAN NOT NULL DEFAULT 0",
                    "redirected_to": "VARCHAR(80)",
                    "review_trace": "JSON",
                },
                "rag_coverage": {
                    "trace": "JSON NOT NULL DEFAULT '{}'",
                },
                "ask_index_chunks": {
                    "source_refs": "JSON NOT NULL DEFAULT '[]'",
                    "chunk_ordinal": "INTEGER NOT NULL DEFAULT 0",
                },
                "ask_index_contents": {
                    "chunking_input_hash": "VARCHAR(64)",
                    "chunking_status": "VARCHAR(24)",
                    "chunking_model": "VARCHAR(200)",
                    "chunking_calls": "INTEGER NOT NULL DEFAULT 0",
                    "chunking_input_bytes": "INTEGER NOT NULL DEFAULT 0",
                    "chunking_output_tokens": "INTEGER",
                    "chunking_error_code": "VARCHAR(64)",
                    "chunking_trace": "JSON NOT NULL DEFAULT '[]'",
                },
            }
            for table, additions in table_additions.items():
                columns = {
                    row[1]
                    for row in connection.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
                }
                for name, definition in additions.items():
                    if name not in columns:
                        connection.exec_driver_sql(
                            f"ALTER TABLE {table} ADD COLUMN {name} {definition}"
                        )
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_content_favorite_folders_folder_id "
                "ON content_favorite_folders (folder_id)"
            )
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_content_tags_tag_id ON content_tags (tag_id)"
            )
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_ask_index_chunk_source_order "
                "ON ask_index_chunks (profile_id, content_id, source_kind, location_kind, chunk_ordinal)"
            )

        # New installations are created by ``Base.metadata.create_all`` above.
        # Existing desktop databases need a one-time compatibility conversion:
        # the old single ``category`` value becomes a local Tag and relation.
        with self.session_factory.begin() as session:
            legacy_rows = session.execute(
                select(ContentRow.id, ContentRow.category).where(
                    ContentRow.category.is_not(None),
                    ContentRow.category != "",
                    ContentRow.category != "未分类",
                )
            ).all()
            now = datetime.now(UTC)
            for content_id, category in legacy_rows:
                name = str(category).strip()
                if not name:
                    continue
                tag = session.execute(
                    select(TagRow).where(TagRow.user_id == "local", TagRow.name == name)
                ).scalar_one_or_none()
                if tag is None:
                    tag = TagRow(
                        id=new_id("tag"),
                        user_id="local",
                        name=name,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(tag)
                    session.flush()
                linked = session.execute(
                    select(ContentTagRow).where(
                        ContentTagRow.content_id == content_id,
                        ContentTagRow.tag_id == tag.id,
                    )
                ).scalar_one_or_none()
                if linked is None:
                    session.add(
                        ContentTagRow(
                            content_id=content_id,
                            tag_id=tag.id,
                            created_at=now,
                        )
                    )

    def create_content(
        self,
        *,
        kind: ContentKind,
        title: str,
        platform: SourcePlatform,
        canonical_url: str | None = None,
        thumbnail_url: str | None = None,
        author: str | None = None,
        language: str | None = None,
        duration_seconds: float | None = None,
        content_hash: str | None = None,
        published_at: datetime | None = None,
        acquisition_method: str = "adapter",
        category: str = "未分类",
        tag_ids: list[str] | tuple[str, ...] | None = None,
        introduction: str = "",
        favorite: bool = False,
        favorite_folder_ids: list[str] | tuple[str, ...] | None = None,
        processing_model: str | None = None,
    ) -> ContentItem:
        folder_ids = _normalize_folder_ids(favorite_folder_ids)
        normalized_tag_ids = _normalize_ids(tag_ids)
        # Keep the legacy category API usable while the UI migrates to tags.
        if tag_ids is None and category.strip() and category.strip() != "未分类":
            with self.session_factory.begin() as session:
                tag = _get_or_create_tag(session, category.strip())
                normalized_tag_ids = (tag.id,)
        if folder_ids:
            favorite = True
        content = ContentItem.create(
            kind=kind,
            title=title,
            source=SourceRecord(
                platform,
                canonical_url=canonical_url,
                thumbnail_url=thumbnail_url,
                author=author,
                published_at=published_at,
                acquisition_method=acquisition_method,
            ),
            language=language,
            duration_seconds=duration_seconds,
            content_hash=content_hash,
            category=category,
            introduction=introduction,
            favorite=favorite,
            processing_model=processing_model,
        )
        with self.session_factory.begin() as session:
            session.add(
                ContentRow(
                    id=content.id,
                    kind=content.kind.value,
                    title=content.title,
                    platform=content.source.platform.value,
                    canonical_url=content.source.canonical_url,
                    thumbnail_url=content.source.thumbnail_url,
                    author=content.source.author,
                    language=content.language,
                    duration_seconds=content.duration_seconds,
                    content_hash=content.content_hash,
                    published_at=content.source.published_at,
                    acquired_at=content.source.acquired_at,
                    acquisition_method=content.source.acquisition_method,
                    category=content.category,
                    favorite=content.favorite,
                    introduction=content.introduction,
                    deleted_at=content.deleted_at,
                    processing_model=content.processing_model,
                    created_at=content.created_at,
                    updated_at=content.updated_at,
                )
            )
            if folder_ids:
                existing_folder_ids = set(
                    session.execute(
                        select(FavoriteFolderRow.id).where(FavoriteFolderRow.id.in_(folder_ids))
                    ).scalars().all()
                )
                if existing_folder_ids != set(folder_ids):
                    raise FavoriteFolderNotFoundError(
                        next(iter(set(folder_ids) - existing_folder_ids))
                    )
                session.add_all(
                    ContentFavoriteFolderRow(
                        content_id=content.id,
                        folder_id=folder_id,
                        created_at=content.created_at,
                    )
                    for folder_id in folder_ids
                )
            if normalized_tag_ids:
                existing_tag_ids = set(
                    session.execute(
                        select(TagRow.id).where(
                            TagRow.id.in_(normalized_tag_ids), TagRow.user_id == "local"
                        )
                    ).scalars().all()
                )
                if existing_tag_ids != set(normalized_tag_ids):
                    raise TagNotFoundError(next(iter(set(normalized_tag_ids) - existing_tag_ids)))
                session.add_all(
                    ContentTagRow(
                        content_id=content.id,
                        tag_id=tag_id,
                        created_at=content.created_at,
                    )
                    for tag_id in normalized_tag_ids
                )
        return content

    def get_content(self, content_id: str) -> ContentItem:
        with self.session_factory() as session:
            row = session.get(ContentRow, content_id)
            if row is None:
                raise ContentNotFoundError(content_id)
            return _content_from_row(row)

    def refresh_source_metadata(
        self, content_id: str, *, title: str, canonical_url: str | None,
        author: str | None, duration_seconds: float | None,
        thumbnail_url: str | None, content_hash: str, acquisition_method: str,
        published_at: datetime | None, language: str | None,
    ) -> ContentItem:
        """Replace scan metadata with the material acquired by a queued task."""
        with self.session_factory.begin() as session:
            row = session.get(ContentRow, content_id)
            if row is None:
                raise ContentNotFoundError(content_id)
            row.title = title
            row.canonical_url = canonical_url
            row.author = author
            row.duration_seconds = duration_seconds
            row.thumbnail_url = thumbnail_url
            row.content_hash = content_hash
            row.acquisition_method = acquisition_method
            row.published_at = published_at
            row.language = language
        return self.get_content(content_id)

    def find_duplicate_content(
        self,
        *,
        canonical_url: str | None = None,
        content_hash: str | None = None,
    ) -> ContentItem | None:
        conditions = []
        if canonical_url:
            conditions.append(ContentRow.canonical_url == canonical_url)
        if content_hash:
            conditions.append(ContentRow.content_hash == content_hash)
        if not conditions:
            return None
        with self.session_factory() as session:
            row = session.execute(
                select(ContentRow)
                .where(or_(*conditions))
                .order_by(ContentRow.deleted_at.is_(None).desc(), ContentRow.updated_at.desc())
            ).scalars().first()
            if row is None and (identity := _bilibili_source_identity(canonical_url)):
                bvid, page_number = identity
                candidates = session.execute(
                    select(ContentRow)
                    .where(
                        ContentRow.platform == SourcePlatform.BILIBILI.value,
                        ContentRow.canonical_url.ilike(f"%{bvid}%"),
                    )
                    .order_by(ContentRow.deleted_at.is_(None).desc(), ContentRow.updated_at.desc())
                ).scalars().all()
                row = next(
                    (
                        candidate for candidate in candidates
                        if _bilibili_source_identity(candidate.canonical_url) == identity
                    ),
                    None,
                )
        return _content_from_row(row) if row is not None else None

    def next_duplicate_title(self, base_title: str) -> str:
        """Return the next title suffix for a regenerated duplicate."""

        base = base_title.strip() or "未命名内容"
        pattern = re.compile(rf"^{re.escape(base)}（(\d+)）$")
        with self.session_factory() as session:
            titles = session.execute(select(ContentRow.title)).scalars().all()
        used = {
            int(match.group(1))
            for title in titles
            if (match := pattern.match(str(title))) is not None
        }
        suffix = 1
        while suffix in used:
            suffix += 1
        return f"{base}（{suffix}）"

    def update_content(
        self,
        content_id: str,
        *,
        category: str | None = None,
        tag_ids: list[str] | tuple[str, ...] | None = None,
        introduction: str | None = None,
        favorite: bool | None = None,
        favorite_folder_ids: list[str] | tuple[str, ...] | None = None,
        processing_model: str | None = None,
    ) -> ContentItem:
        with self.session_factory.begin() as session:
            row = session.get(ContentRow, content_id)
            if row is None:
                raise ContentNotFoundError(content_id)
            if category is not None:
                row.category = category.strip() or "未分类"
                if tag_ids is None and row.category != "未分类":
                    tag = _get_or_create_tag(session, row.category)
                    linked = session.execute(
                        select(ContentTagRow).where(
                            ContentTagRow.content_id == content_id,
                            ContentTagRow.tag_id == tag.id,
                        )
                    ).scalar_one_or_none()
                    if linked is None:
                        session.add(
                            ContentTagRow(
                                content_id=content_id,
                                tag_id=tag.id,
                                created_at=datetime.now(UTC),
                            )
                        )
            if introduction is not None:
                clean_introduction = introduction.strip()
                if len(clean_introduction) > 30:
                    raise ValueError("introduction must be at most 30 characters")
                row.introduction = clean_introduction
            if favorite is not None:
                row.favorite = favorite
            folder_ids = _normalize_folder_ids(favorite_folder_ids)
            if favorite is False:
                session.execute(
                    delete(ContentFavoriteFolderRow).where(
                        ContentFavoriteFolderRow.content_id == content_id
                    )
                )
            if favorite_folder_ids is not None:
                if favorite is False and folder_ids:
                    raise ValueError("favorite_folder_conflicts")
                existing_folder_ids = set(
                    session.execute(
                        select(FavoriteFolderRow.id).where(FavoriteFolderRow.id.in_(folder_ids))
                    ).scalars().all()
                ) if folder_ids else set()
                if existing_folder_ids != set(folder_ids):
                    raise FavoriteFolderNotFoundError(
                        next(iter(set(folder_ids) - existing_folder_ids))
                    )
                session.execute(
                    delete(ContentFavoriteFolderRow).where(
                        ContentFavoriteFolderRow.content_id == content_id
                    )
                )
                session.add_all(
                    ContentFavoriteFolderRow(
                        content_id=content_id,
                        folder_id=folder_id,
                        created_at=datetime.now(UTC),
                    )
                    for folder_id in folder_ids
                )
                if folder_ids:
                    row.favorite = True
            if tag_ids is not None:
                normalized_tag_ids = _normalize_ids(tag_ids)
                existing_tag_ids = set(
                    session.execute(
                        select(TagRow.id).where(
                            TagRow.id.in_(normalized_tag_ids), TagRow.user_id == "local"
                        )
                    ).scalars().all()
                ) if normalized_tag_ids else set()
                if existing_tag_ids != set(normalized_tag_ids):
                    raise TagNotFoundError(next(iter(set(normalized_tag_ids) - existing_tag_ids)))
                session.execute(
                    delete(ContentTagRow).where(ContentTagRow.content_id == content_id)
                )
                session.add_all(
                    ContentTagRow(
                        content_id=content_id,
                        tag_id=tag_id,
                        created_at=datetime.now(UTC),
                    )
                    for tag_id in normalized_tag_ids
                )
            if processing_model is not None:
                row.processing_model = processing_model
            row.updated_at = datetime.now(UTC)
        return _content_from_row(row)

    def soft_delete_content(self, content_id: str) -> ContentItem:
        now = datetime.now(UTC)
        with self.session_factory.begin() as session:
            row = session.get(ContentRow, content_id)
            if row is None:
                raise ContentNotFoundError(content_id)
            job_rows = session.execute(
                select(JobRow)
                .join(AnalysisRunRow, AnalysisRunRow.id == JobRow.analysis_run_id)
                .where(AnalysisRunRow.content_id == content_id)
            ).scalars().all()
            job_ids = [job.id for job in job_rows]
            if job_ids:
                session.execute(delete(AsrSegmentRow).where(AsrSegmentRow.job_id.in_(job_ids)))
            for job in job_rows:
                if job.state not in {
                    JobState.COMPLETED.value,
                    JobState.FAILED.value,
                    JobState.CANCELLED.value,
                }:
                    job.state = JobState.CANCELLED.value
                    job.completed_at = now
                    job.lease_until = None
                    job.error_message = "内容已删除，任务不会继续执行"
                metadata = dict(job.metadata_json or {})
                metadata.pop("last_stable_checkpoint", None)
                metadata.pop("resume_checkpoint", None)
                metadata.pop("checkpoint_saved_at", None)
                job.metadata_json = metadata
                job.updated_at = now
            run_rows = session.execute(
                select(AnalysisRunRow).where(AnalysisRunRow.content_id == content_id)
            ).scalars().all()
            for run in run_rows:
                if run.status not in {"completed", "failed", "cancelled"}:
                    run.status = "cancelled"
                run.updated_at = now
            row.deleted_at = now
            row.updated_at = now
        return _content_from_row(row)

    def restore_content(self, content_id: str) -> ContentItem:
        with self.session_factory.begin() as session:
            row = session.get(ContentRow, content_id)
            if row is None:
                raise ContentNotFoundError(content_id)
            row.deleted_at = None
            row.updated_at = datetime.now(UTC)
        return _content_from_row(row)

    def purge_content(self, content_id: str) -> None:
        """Permanently remove a soft-deleted content row and every dependent row."""
        with self.session_factory.begin() as session:
            row = session.get(ContentRow, content_id)
            if row is None:
                raise ContentNotFoundError(content_id)
            if row.deleted_at is None:
                raise ValueError("content_not_deleted")
            job_ids = list(session.execute(
                select(JobRow.id)
                .join(AnalysisRunRow, AnalysisRunRow.id == JobRow.analysis_run_id)
                .where(AnalysisRunRow.content_id == content_id)
            ).scalars())
            if job_ids:
                session.execute(delete(AsrSegmentRow).where(AsrSegmentRow.job_id.in_(job_ids)))
                session.execute(delete(JobEventRow).where(JobEventRow.job_id.in_(job_ids)))
            session.execute(delete(JobRow).where(JobRow.analysis_run_id.in_(
                select(AnalysisRunRow.id).where(AnalysisRunRow.content_id == content_id)
            )))
            for table in reversed(Base.metadata.sorted_tables):
                if "content_id" in table.c and table.name != ContentRow.__tablename__:
                    session.execute(table.delete().where(table.c.content_id == content_id))
            session.delete(row)

    def list_categories(self, *, include_deleted: bool = False) -> list[str]:
        statement = select(ContentRow.category).distinct().order_by(ContentRow.category.asc())
        if not include_deleted:
            statement = statement.where(ContentRow.deleted_at.is_(None))
        with self.session_factory() as session:
            values = session.execute(statement).scalars().all()
        return [value for value in values if value]

    def create_tag(self, name: str, *, user_id: str = "local") -> Tag:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("tag_name_required")
        now = datetime.now(UTC)
        with self.session_factory.begin() as session:
            duplicate = session.execute(
                select(TagRow).where(
                    TagRow.user_id == user_id,
                    TagRow.name.ilike(clean_name),
                )
            ).scalar_one_or_none()
            if duplicate is not None:
                raise ValueError("tag_exists")
            row = TagRow(
                id=new_id("tag"),
                user_id=user_id,
                name=clean_name,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        return _tag_from_row(row, 0)

    def list_tags(self, *, user_id: str = "local", include_deleted: bool = False) -> list[Tag]:
        statement = select(TagRow).where(TagRow.user_id == user_id).order_by(
            TagRow.created_at.asc(), TagRow.name.asc()
        )
        with self.session_factory() as session:
            completed_content = _completed_job_exists(ContentTagRow.content_id)
            rows = session.execute(statement).scalars().all()
            counts = dict(
                session.execute(
                    select(
                        ContentTagRow.tag_id,
                        func.count(func.distinct(ContentTagRow.content_id)),
                    )
                    .join(ContentRow, ContentRow.id == ContentTagRow.content_id)
                    .where(ContentRow.deleted_at.is_(None), completed_content)
                    .group_by(ContentTagRow.tag_id)
                ).all()
            )
        return [_tag_from_row(row, int(counts.get(row.id, 0))) for row in rows]

    def rename_tag(self, tag_id: str, name: str, *, user_id: str = "local") -> Tag:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("tag_name_required")
        with self.session_factory.begin() as session:
            row = session.get(TagRow, tag_id)
            if row is None or row.user_id != user_id:
                raise TagNotFoundError(tag_id)
            duplicate = session.execute(
                select(TagRow).where(
                    TagRow.id != tag_id,
                    TagRow.user_id == user_id,
                    TagRow.name.ilike(clean_name),
                )
            ).scalar_one_or_none()
            if duplicate is not None:
                raise ValueError("tag_exists")
            row.name = clean_name
            row.updated_at = datetime.now(UTC)
            completed_content = _completed_job_exists(ContentTagRow.content_id)
            count = int(
                session.execute(
                    select(func.count(func.distinct(ContentTagRow.content_id)))
                    .join(ContentRow, ContentRow.id == ContentTagRow.content_id)
                    .where(ContentTagRow.tag_id == tag_id, ContentRow.deleted_at.is_(None))
                    .where(completed_content)
                ).scalar_one()
            )
        return _tag_from_row(row, count)

    def delete_tag(self, tag_id: str, *, user_id: str = "local") -> None:
        with self.session_factory.begin() as session:
            row = session.get(TagRow, tag_id)
            if row is None or row.user_id != user_id:
                raise TagNotFoundError(tag_id)
            session.execute(delete(ContentTagRow).where(ContentTagRow.tag_id == tag_id))
            session.delete(row)

    def tag_ids(self, content_id: str, *, user_id: str = "local") -> list[str]:
        with self.session_factory() as session:
            return list(
                session.execute(
                    select(ContentTagRow.tag_id)
                    .join(TagRow, TagRow.id == ContentTagRow.tag_id)
                    .where(
                        ContentTagRow.content_id == content_id,
                        TagRow.user_id == user_id,
                    )
                    .order_by(TagRow.created_at.asc(), TagRow.name.asc())
                ).scalars().all()
            )

    def tag_names(self, content_id: str, *, user_id: str = "local") -> list[str]:
        with self.session_factory() as session:
            return list(
                session.execute(
                    select(TagRow.name)
                    .join(ContentTagRow, ContentTagRow.tag_id == TagRow.id)
                    .where(
                        ContentTagRow.content_id == content_id,
                        TagRow.user_id == user_id,
                    )
                    .order_by(TagRow.created_at.asc(), TagRow.name.asc())
                ).scalars().all()
            )

    def batch_organize(
        self,
        content_ids: list[str],
        *,
        operation: str,
        tag_id: str | None = None,
        folder_ids: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        """Apply one classification operation and report partial outcomes."""

        if operation not in {"add_tag", "remove_tag", "add_folder", "remove_folder"}:
            raise ValueError("unsupported_classification_operation")
        normalized_ids = list(dict.fromkeys(item.strip() for item in content_ids if item.strip()))
        normalized_folders = _normalize_folder_ids(folder_ids)
        succeeded: list[str] = []
        skipped: list[str] = []
        failed: list[dict[str, str]] = []
        for content_id in normalized_ids:
            try:
                content = self.get_content(content_id)
                # A content item can disappear from the confirmed result set
                # between the preview and execution. Treat soft-deleted
                # entries as skipped rather than mutating the recycle bin.
                if content.deleted_at is not None:
                    skipped.append(content_id)
                    continue
                if operation in {"add_tag", "remove_tag"}:
                    if not tag_id:
                        raise ValueError("tag_required")
                    if operation == "add_tag":
                        current = self.tag_ids(content_id)
                        if tag_id in current:
                            skipped.append(content_id)
                            continue
                        self.update_content(content_id, tag_ids=[*current, tag_id])
                    else:
                        current = [item for item in self.tag_ids(content_id) if item != tag_id]
                        if len(current) == len(self.tag_ids(content_id)):
                            skipped.append(content_id)
                            continue
                        self.update_content(content_id, tag_ids=current)
                else:
                    if not normalized_folders:
                        raise ValueError("folder_required")
                    current = self.favorite_folder_ids(content_id)
                    if operation == "add_folder":
                        next_ids = list(dict.fromkeys([*current, *normalized_folders]))
                        if next_ids == current:
                            skipped.append(content_id)
                            continue
                    else:
                        next_ids = [item for item in current if item not in normalized_folders]
                        if next_ids == current:
                            skipped.append(content_id)
                            continue
                    self.update_content(content_id, favorite_folder_ids=next_ids)
                succeeded.append(content_id)
            except (ContentNotFoundError, TagNotFoundError, FavoriteFolderNotFoundError, ValueError) as error:
                failed.append({"id": content_id, "reason": str(error)})
        return {
            "operation": operation,
            "succeeded": succeeded,
            "skipped": skipped,
            "failed": failed,
        }


    def create_favorite_folder(self, name: str, *, parent_id: str | None = None) -> FavoriteFolder:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("favorite_folder_name_required")
        now = datetime.now(UTC)
        with self.session_factory.begin() as session:
            if parent_id is not None and session.get(FavoriteFolderRow, parent_id) is None:
                raise FavoriteFolderNotFoundError(parent_id)
            existing = session.execute(
                select(FavoriteFolderRow).where(FavoriteFolderRow.name.ilike(clean_name))
            ).scalar_one_or_none()
            if existing is not None:
                raise ValueError("favorite_folder_exists")
            row = FavoriteFolderRow(
                id=new_id("favorite-folder"),
                name=clean_name,
                parent_id=parent_id,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        return _favorite_folder_from_row(row, 0)

    def list_favorite_folders(self) -> list[FavoriteFolder]:
        with self.session_factory() as session:
            completed_content = _completed_job_exists(ContentFavoriteFolderRow.content_id)
            rows = session.execute(
                select(FavoriteFolderRow).order_by(FavoriteFolderRow.created_at.asc())
            ).scalars().all()
            counts = dict(
                session.execute(
                    select(
                        ContentFavoriteFolderRow.folder_id,
                        func.count(func.distinct(ContentFavoriteFolderRow.content_id)),
                    )
                    .join(ContentRow, ContentRow.id == ContentFavoriteFolderRow.content_id)
                    .where(
                        ContentRow.deleted_at.is_(None),
                        ContentRow.favorite.is_(True),
                        completed_content,
                    )
                    .group_by(ContentFavoriteFolderRow.folder_id)
                ).all()
            )
        return [_favorite_folder_from_row(row, int(counts.get(row.id, 0))) for row in rows]

    def count_favorites(self) -> int:
        with self.session_factory() as session:
            return int(
                session.execute(
                    select(func.count(ContentRow.id)).where(
                        ContentRow.favorite.is_(True),
                        ContentRow.deleted_at.is_(None),
                        _completed_job_exists(ContentRow.id),
                    )
                ).scalar_one()
            )

    def rename_favorite_folder(self, folder_id: str, name: str) -> FavoriteFolder:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("favorite_folder_name_required")
        now = datetime.now(UTC)
        with self.session_factory.begin() as session:
            row = session.get(FavoriteFolderRow, folder_id)
            if row is None:
                raise FavoriteFolderNotFoundError(folder_id)
            duplicate = session.execute(
                select(FavoriteFolderRow).where(
                    FavoriteFolderRow.id != folder_id,
                    FavoriteFolderRow.name.ilike(clean_name),
                )
            ).scalar_one_or_none()
            if duplicate is not None:
                raise ValueError("favorite_folder_exists")
            row.name = clean_name
            row.updated_at = now
            completed_content = _completed_job_exists(ContentFavoriteFolderRow.content_id)
            count = int(
                session.execute(
                    select(func.count(func.distinct(ContentFavoriteFolderRow.content_id)))
                    .join(ContentRow, ContentRow.id == ContentFavoriteFolderRow.content_id)
                    .where(
                        ContentFavoriteFolderRow.folder_id == folder_id,
                        ContentRow.deleted_at.is_(None),
                        ContentRow.favorite.is_(True),
                        completed_content,
                    )
                ).scalar_one()
            )
        return _favorite_folder_from_row(row, count)

    def update_favorite_folder_parent(self, folder_id: str, parent_id: str | None) -> FavoriteFolder:
        with self.session_factory.begin() as session:
            row = session.get(FavoriteFolderRow, folder_id)
            if row is None:
                raise FavoriteFolderNotFoundError(folder_id)
            if parent_id == folder_id:
                raise ValueError("favorite_folder_parent_conflicts")
            if parent_id is not None:
                parent = session.get(FavoriteFolderRow, parent_id)
                if parent is None:
                    raise FavoriteFolderNotFoundError(parent_id)
                seen = {folder_id}
                while parent is not None:
                    if parent.id in seen:
                        raise ValueError("favorite_folder_parent_conflicts")
                    seen.add(parent.id)
                    parent = (
                        session.get(FavoriteFolderRow, parent.parent_id)
                        if parent.parent_id is not None
                        else None
                    )
            row.parent_id = parent_id
            row.updated_at = datetime.now(UTC)
            completed_content = _completed_job_exists(ContentFavoriteFolderRow.content_id)
            count = int(
                session.execute(
                    select(func.count(func.distinct(ContentFavoriteFolderRow.content_id)))
                    .join(ContentRow, ContentRow.id == ContentFavoriteFolderRow.content_id)
                    .where(
                        ContentFavoriteFolderRow.folder_id == folder_id,
                        ContentRow.deleted_at.is_(None),
                        ContentRow.favorite.is_(True),
                        completed_content,
                    )
                ).scalar_one()
            )
        return _favorite_folder_from_row(row, count)

    def delete_favorite_folder(self, folder_id: str) -> None:
        with self.session_factory.begin() as session:
            row = session.get(FavoriteFolderRow, folder_id)
            if row is None:
                raise FavoriteFolderNotFoundError(folder_id)
            session.execute(
                delete(ContentFavoriteFolderRow).where(
                    ContentFavoriteFolderRow.folder_id == folder_id
                )
            )
            session.delete(row)

    def favorite_folder_ids(self, content_id: str) -> list[str]:
        with self.session_factory() as session:
            return list(
                session.execute(
                    select(ContentFavoriteFolderRow.folder_id)
                    .join(
                        FavoriteFolderRow,
                        FavoriteFolderRow.id == ContentFavoriteFolderRow.folder_id,
                    )
                    .where(ContentFavoriteFolderRow.content_id == content_id)
                    .order_by(FavoriteFolderRow.created_at.asc(), FavoriteFolderRow.name.asc())
                ).scalars().all()
            )


    def get_content_by_url(self, canonical_url: str) -> ContentItem | None:
        with self.session_factory() as session:
            row = session.execute(
                select(ContentRow).where(ContentRow.canonical_url == canonical_url)
            ).scalars().first()
        return _content_from_row(row) if row is not None else None

    def get_bilibili_video_import_state(
        self, bvid: str, page_count: int | None
    ) -> dict[str, Any]:
        """Aggregate existing B站 content and task state by stable BVID and P number."""

        page_count = page_count if isinstance(page_count, int) and page_count > 0 else None
        with self.session_factory() as session:
            rows = session.execute(
                select(ContentRow).where(
                    ContentRow.platform == "bilibili",
                    ContentRow.canonical_url.ilike(f"%{bvid}%"),
                    ContentRow.deleted_at.is_(None),
                )
            ).scalars().all()
            content_ids = [row.id for row in rows]
            if not content_ids:
                return {
                    "duplicate_status": "new",
                    "existing_content_id": None,
                    "page_count": page_count,
                    "imported_page_count": 0,
                    "part_statuses": [],
                }

            job_rows = session.execute(
                select(JobRow, AnalysisRunRow.content_id)
                .join(AnalysisRunRow, AnalysisRunRow.id == JobRow.analysis_run_id)
                .where(AnalysisRunRow.content_id.in_(content_ids))
                .order_by(JobRow.created_at.desc())
            ).all()
            summarized_ids = set(
                session.execute(
                    select(ContentSummaryRow.content_id).where(
                        ContentSummaryRow.content_id.in_(content_ids)
                    )
                ).scalars().all()
            )

        content_ids_by_page: dict[int, list[str]] = {}
        for row in rows:
            query = parse_qs(urlsplit(row.canonical_url or "").query)
            try:
                page_number = int(query.get("p", ["1"])[0])
            except (TypeError, ValueError):
                page_number = 1
            content_ids_by_page.setdefault(max(1, page_number), []).append(row.id)

        active_states = {
            JobState.QUEUED.value,
            JobState.ACQUIRING.value,
            JobState.EXTRACTING.value,
            JobState.TRANSCRIBING.value,
            JobState.CHUNKING.value,
            JobState.SUMMARIZING.value,
            JobState.ARCHIVING.value,
            JobState.INDEXING.value,
            JobState.PAUSED.value,
        }
        active_job_ids: set[str] = set()
        latest_job_state: dict[str, str] = {}
        for job, content_id in job_rows:
            if job.state in active_states:
                active_job_ids.add(content_id)
            latest_job_state.setdefault(content_id, job.state)

        def page_status(content_ids_for_page: list[str]) -> str:
            if any(content_id in active_job_ids for content_id in content_ids_for_page):
                return "processing"
            if any(content_id in summarized_ids for content_id in content_ids_for_page):
                return "summarized"
            if any(
                latest_job_state.get(content_id) == JobState.FAILED.value
                for content_id in content_ids_for_page
            ):
                return "failed"
            return "new"

        part_numbers = (
            range(1, page_count + 1)
            if page_count is not None
            else sorted(content_ids_by_page)
        )
        part_statuses = [
            page_status(content_ids_by_page.get(page_number, []))
            for page_number in part_numbers
        ]
        imported_page_count = sum(value == "summarized" for value in part_statuses)
        if (
            page_count is not None
            and part_statuses
            and all(value == "summarized" for value in part_statuses)
        ):
            duplicate_status = "summarized"
        elif "processing" in part_statuses:
            duplicate_status = "processing"
        elif "failed" in part_statuses:
            duplicate_status = "failed"
        else:
            duplicate_status = "new"
        return {
            "duplicate_status": duplicate_status,
            "existing_content_id": next(iter(content_ids)),
            "page_count": page_count,
            "imported_page_count": imported_page_count,
            "part_statuses": part_statuses,
        }

    def list_content_jobs(self, content_id: str) -> list[Job]:
        """Return every run job for content-level artifact cleanup."""

        statement = (
            select(JobRow)
            .join(AnalysisRunRow, AnalysisRunRow.id == JobRow.analysis_run_id)
            .where(AnalysisRunRow.content_id == content_id)
            .order_by(JobRow.created_at.asc())
        )
        with self.session_factory() as session:
            rows = session.execute(statement).scalars().all()
        return [_job_from_row(row) for row in rows]

    def create_analysis_run(
        self, content_id: str, settings: AnalysisSettings, *, priority: int = 0
    ) -> tuple[AnalysisRun, Job]:
        content = self.get_content(content_id)
        run = AnalysisRun.create(content.id, settings)
        now = datetime.now(UTC)
        job = Job(type="analyze", analysis_run_id=run.id, created_at=now, priority=priority)
        with self.session_factory.begin() as session:
            session.add(
                AnalysisRunRow(
                    id=run.id,
                    content_id=run.content_id,
                    status=run.status,
                    settings_snapshot=run.settings_snapshot,
                    prompt_version=run.prompt_version,
                    created_at=run.created_at,
                    updated_at=run.updated_at,
                )
            )
            session.add(
                JobRow(
                    id=job.id,
                    analysis_run_id=job.analysis_run_id,
                    type=job.type,
                    state=job.state.value,
                    attempt=job.attempt,
                    progress=job.progress,
                    metadata_json=job.metadata,
                    created_at=job.created_at,
                    started_at=job.started_at,
                    completed_at=job.completed_at,
                    priority=job.priority,
                    queue_position=job.queue_position,
                    updated_at=now,
                )
            )
            session.flush()
            session.add(
                JobEventRow(
                    id=new_id("event"),
                    job_id=job.id,
                    sequence=1,
                    attempt=job.attempt,
                    event_type="created",
                    stage="queue",
                    state=job.state.value,
                    progress=job.progress,
                    checkpoint=job.checkpoint,
                    error_code=None,
                    message="任务已创建并排队",
                    details_json={},
                    occurred_at=now,
                )
            )
        return run, job

    def get_job(self, job_id: str) -> Job:
        with self.session_factory() as session:
            row = session.get(JobRow, job_id)
            if row is None:
                raise LookupError(job_id)
            return _job_from_row(row)

    def get_analysis_run(self, run_id: str) -> AnalysisRun:
        with self.session_factory() as session:
            row = session.get(AnalysisRunRow, run_id)
            if row is None:
                raise AnalysisRunNotFoundError(run_id)
            return _analysis_run_from_row(row)

    def save_analysis_run(self, run: AnalysisRun) -> AnalysisRun:
        with self.session_factory.begin() as session:
            row = session.get(AnalysisRunRow, run.id)
            if row is None:
                raise AnalysisRunNotFoundError(run.id)
            row.status = run.status
            row.updated_at = run.updated_at
            row.error_code = run.error_code
            row.error_message = run.error_message
        return run

    def save_job(self, job: Job) -> Job:
        now = datetime.now(UTC)
        with self.session_factory.begin() as session:
            row = session.get(JobRow, job.id)
            if row is None:
                raise LookupError(job.id)
            previous_state = row.state
            previous_attempt = row.attempt
            previous_worker_id = row.worker_id
            previous_progress = row.progress
            previous_checkpoint = row.checkpoint
            previous_error_code = row.error_code
            previous_error_message = row.error_message
            current_state = job.state.value
            if (
                job.attempt < previous_attempt
                or (
                    job.attempt == previous_attempt
                    and previous_state != JobState.QUEUED.value
                    and job.worker_id is not None
                    and job.worker_id != previous_worker_id
                )
                or (
                    previous_state in {
                        JobState.PAUSED.value,
                        JobState.FAILED.value,
                        JobState.CANCELLED.value,
                    }
                    and current_state
                    not in {
                        JobState.PAUSED.value,
                        JobState.QUEUED.value,
                        JobState.CANCELLED.value,
                    }
                )
                or (
                    previous_state == JobState.QUEUED.value
                    and job.attempt == previous_attempt
                    and job.worker_id is not None
                    and job.worker_id != previous_worker_id
                )
            ):
                raise StaleJobAttemptError(job.id)
            row.state = job.state.value
            row.attempt = job.attempt
            row.progress = job.progress
            row.checkpoint = job.checkpoint
            row.lease_until = job.lease_until
            row.worker_id = job.worker_id
            row.error_code = job.error_code.value if job.error_code else None
            row.error_message = job.error_message
            row.metadata_json = job.metadata
            row.started_at = job.started_at
            row.completed_at = job.completed_at
            row.priority = job.priority
            row.queue_position = job.queue_position
            row.updated_at = now
            change = _job_event_change(
                previous_state=previous_state,
                previous_attempt=previous_attempt,
                previous_progress=previous_progress,
                previous_checkpoint=previous_checkpoint,
                previous_error_code=previous_error_code,
                previous_error_message=previous_error_message,
                job=job,
            )
            if change is not None:
                event_type, message, details = change
                _append_job_event(
                    session,
                    job,
                    event_type=event_type,
                    message=message,
                    details=details,
                    occurred_at=now,
                )
        return job

    def list_jobs(self, *, states: set[JobState] | None = None) -> list[Job]:
        running_states = {
            JobState.ACQUIRING.value,
            JobState.EXTRACTING.value,
            JobState.TRANSCRIBING.value,
            JobState.CHUNKING.value,
            JobState.SUMMARIZING.value,
            JobState.ARCHIVING.value,
            JobState.INDEXING.value,
        }
        terminal_states = {
            JobState.COMPLETED.value,
            JobState.FAILED.value,
            JobState.CANCELLED.value,
        }
        state_bucket = case(
            (JobRow.state.in_(terminal_states), 0),
            (JobRow.state.in_(running_states), 1),
            (JobRow.state == JobState.QUEUED.value, 2),
            (JobRow.state == JobState.PAUSED.value, 3),
            else_=4,
        )
        queued_without_position = case(
            (JobRow.state == JobState.QUEUED.value, case((JobRow.queue_position.is_(None), 1), else_=0)),
            else_=0,
        )
        queued_position = case(
            (JobRow.state == JobState.QUEUED.value, JobRow.queue_position),
            else_=None,
        )
        running_order = case(
            (JobRow.state.in_(running_states), func.coalesce(JobRow.started_at, JobRow.created_at)),
            else_=None,
        )
        terminal_order = case(
            (JobRow.state.in_(terminal_states), func.coalesce(JobRow.completed_at, JobRow.updated_at, JobRow.created_at)),
            else_=None,
        )
        statement = select(JobRow).order_by(
            state_bucket.asc(),
            queued_without_position.asc(),
            queued_position.asc(),
            running_order.asc(),
            case((JobRow.state == JobState.PAUSED.value, JobRow.updated_at), else_=None).desc(),
            terminal_order.desc(),
            JobRow.id.asc(),
        )
        if states:
            statement = statement.where(JobRow.state.in_([state.value for state in states]))
        with self.session_factory() as session:
            rows = session.execute(statement).scalars().all()
        return [_job_from_row(row) for row in rows]

    def delete_job(self, job_id: str) -> None:
        """Delete only the task record; its content and archive remain intact."""

        with self.session_factory.begin() as session:
            row = session.get(JobRow, job_id)
            if row is None:
                raise LookupError(job_id)
            if row.state not in {
                JobState.COMPLETED.value,
                JobState.FAILED.value,
                JobState.CANCELLED.value,
            }:
                raise ValueError("job_not_deletable")
            session.execute(delete(AsrSegmentRow).where(AsrSegmentRow.job_id == job_id))
            session.execute(delete(JobFeedbackRow).where(JobFeedbackRow.job_id == job_id))
            session.delete(row)

    def list_job_events(
        self,
        job_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
    ) -> list[JobEvent]:
        statement = (
            select(JobEventRow)
            .where(
                JobEventRow.job_id == job_id,
                JobEventRow.sequence > after_sequence,
            )
            .order_by(JobEventRow.sequence.asc())
            .limit(limit)
        )
        with self.session_factory() as session:
            rows = session.execute(statement).scalars().all()
        return [_job_event_from_row(row) for row in rows]

    def record_job_event(
        self,
        job_id: str,
        event_type: str,
        *,
        message: str,
        stage: str | None = None,
        state: str | None = None,
        progress: int | None = None,
        attempt: int | None = None,
        checkpoint: str | None = None,
        error_code: str | None = None,
        details: dict[str, Any] | None = None,
        occurred_at: datetime | None = None,
    ) -> JobEvent:
        """Append a non-state lifecycle event while preserving the job snapshot."""

        with self.session_factory.begin() as session:
            row = session.get(JobRow, job_id)
            if row is None:
                raise LookupError(job_id)
            event = _append_job_event(
                session,
                Job(
                    id=row.id,
                    type=row.type,
                    analysis_run_id=row.analysis_run_id,
                    state=JobState(row.state),
                    attempt=row.attempt if attempt is None else attempt,
                    progress=row.progress if progress is None else progress,
                    checkpoint=row.checkpoint if checkpoint is None else checkpoint,
                ),
                event_type=event_type,
                message=message,
                stage=stage,
                state=state or row.state,
                details=details,
                error_code=error_code if error_code is not None else row.error_code,
                occurred_at=occurred_at,
            )
        return event

    # ------------------------------------------------------------------
    # Product-level ASR checkpoints
    # ------------------------------------------------------------------

    def create_asr_segments(
        self,
        job_id: str,
        config_fingerprint: str,
        segments: list[dict[str, object]] | tuple[dict[str, object], ...],
    ) -> list[AsrSegmentCheckpoint]:
        """Create a stable segment set without replacing an existing checkpoint.

        The unique key is intentionally the product contract rather than a
        generated row id.  Reopening a job therefore reuses already completed
        text and never appends a second copy of a segment.
        """

        fingerprint = str(config_fingerprint).strip()
        if not fingerprint:
            raise ValueError("config_fingerprint must not be empty")
        now = datetime.now(UTC)
        with self.session_factory.begin() as session:
            if session.get(JobRow, job_id) is None:
                raise LookupError(job_id)
            for item in segments:
                index = int(item["segment_index"])
                existing = session.execute(
                    select(AsrSegmentRow).where(
                        AsrSegmentRow.job_id == job_id,
                        AsrSegmentRow.config_fingerprint == fingerprint,
                        AsrSegmentRow.segment_index == index,
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    continue
                start = float(item["start_seconds"])
                end = float(item["end_seconds"])
                if start < 0 or end <= start:
                    raise ValueError("ASR segment time range is invalid")
                session.add(
                    AsrSegmentRow(
                        id=f"asrseg-{job_id}-{fingerprint[:20]}-{index}",
                        job_id=job_id,
                        config_fingerprint=fingerprint,
                        segment_index=index,
                        start_seconds=start,
                        end_seconds=end,
                        status="pending",
                        attempts=0,
                        worker_generation=0,
                        created_at=now,
                        updated_at=now,
                    )
                )
        return self.list_asr_segments(job_id, fingerprint)

    def list_asr_segments(
        self,
        job_id: str,
        config_fingerprint: str,
    ) -> list[AsrSegmentCheckpoint]:
        with self.session_factory() as session:
            rows = session.execute(
                select(AsrSegmentRow)
                .where(
                    AsrSegmentRow.job_id == job_id,
                    AsrSegmentRow.config_fingerprint == config_fingerprint,
                )
                .order_by(AsrSegmentRow.segment_index.asc())
            ).scalars().all()
        return [_asr_segment_from_row(row) for row in rows]

    def claim_asr_segment(
        self,
        job_id: str,
        config_fingerprint: str,
        lease_owner: str,
        *,
        lease_seconds: int = 150,
        worker_generation: int = 0,
        now: datetime | None = None,
    ) -> AsrSegmentCheckpoint | None:
        """Claim the next pending or expired segment in one transaction."""

        if not lease_owner.strip():
            raise ValueError("lease_owner must not be empty")
        now = now or datetime.now(UTC)
        with self.session_factory.begin() as session:
            rows = session.execute(
                select(AsrSegmentRow)
                .where(
                    AsrSegmentRow.job_id == job_id,
                    AsrSegmentRow.config_fingerprint == config_fingerprint,
                    AsrSegmentRow.status.in_(("pending", "processing")),
                )
                .order_by(AsrSegmentRow.segment_index.asc())
            ).scalars().all()
            selected = None
            for row in rows:
                expired = (
                    row.status == "processing"
                    and row.lease_expires_at is not None
                    and _utc_datetime(row.lease_expires_at) <= _utc_datetime(now)
                )
                if row.status == "pending" or expired:
                    selected = row
                    break
            if selected is None:
                return None
            selected.status = "processing"
            selected.attempts += 1
            selected.lease_owner = lease_owner
            selected.lease_expires_at = now + timedelta(seconds=max(1, lease_seconds))
            selected.worker_generation = int(worker_generation)
            selected.heartbeat_at = now
            selected.error_message = None
            selected.updated_at = now
            session.flush()
            return _asr_segment_from_row(selected)

    def heartbeat_asr_segment(
        self,
        segment_id: str,
        lease_owner: str,
        *,
        worker_generation: int,
        lease_seconds: int = 150,
        now: datetime | None = None,
    ) -> bool:
        now = now or datetime.now(UTC)
        with self.session_factory.begin() as session:
            row = session.get(AsrSegmentRow, segment_id)
            if (
                row is None
                or row.status != "processing"
                or row.lease_owner != lease_owner
                or row.worker_generation != int(worker_generation)
            ):
                return False
            if row.lease_expires_at is not None and _utc_datetime(row.lease_expires_at) <= _utc_datetime(now):
                return False
            row.heartbeat_at = now
            row.lease_expires_at = now + timedelta(seconds=max(1, lease_seconds))
            row.updated_at = now
            return True

    def commit_asr_segment(
        self,
        segment_id: str,
        lease_owner: str,
        *,
        worker_generation: int,
        text: str,
        language: str | None = None,
        now: datetime | None = None,
    ) -> AsrSegmentCheckpoint:
        """Commit text and completed state atomically for one valid lease."""

        normalized = text.strip()
        now = now or datetime.now(UTC)
        with self.session_factory.begin() as session:
            row = session.get(AsrSegmentRow, segment_id)
            if row is None:
                raise LookupError(segment_id)
            if row.status == "completed":
                return _asr_segment_from_row(row)
            if (
                row.status != "processing"
                or row.lease_owner != lease_owner
                or row.worker_generation != int(worker_generation)
            ):
                raise RuntimeError("ASR segment lease is no longer valid")
            if row.lease_expires_at is not None and _utc_datetime(row.lease_expires_at) <= _utc_datetime(now):
                raise RuntimeError("ASR segment lease has expired")
            row.text = normalized
            row.language = language.strip() if isinstance(language, str) and language.strip() else None
            row.status = "completed"
            row.lease_owner = None
            row.lease_expires_at = None
            row.heartbeat_at = now
            row.completed_at = now
            row.error_message = None
            row.updated_at = now
            session.flush()
            return _asr_segment_from_row(row)

    def fail_asr_segment(
        self,
        segment_id: str,
        lease_owner: str,
        message: str,
        *,
        worker_generation: int,
        retryable: bool = True,
        now: datetime | None = None,
    ) -> bool:
        now = now or datetime.now(UTC)
        with self.session_factory.begin() as session:
            row = session.get(AsrSegmentRow, segment_id)
            if (
                row is None
                or row.status != "processing"
                or row.lease_owner != lease_owner
                or row.worker_generation != int(worker_generation)
            ):
                return False
            row.status = "pending" if retryable else "failed"
            row.lease_owner = None
            row.lease_expires_at = None
            row.error_message = str(message).strip() or "ASR segment failed"
            row.updated_at = now
            return True

    def recover_expired_asr_segments(self, *, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        recovered = 0
        with self.session_factory.begin() as session:
            rows = session.execute(
                select(AsrSegmentRow).where(AsrSegmentRow.status == "processing")
            ).scalars().all()
            for row in rows:
                if row.lease_expires_at is None or _utc_datetime(row.lease_expires_at) > _utc_datetime(now):
                    continue
                row.status = "pending"
                row.lease_owner = None
                row.lease_expires_at = None
                row.error_message = "租约过期，等待恢复"
                row.updated_at = now
                recovered += 1
        return recovered

    def asr_segment_progress(self, job_id: str, config_fingerprint: str) -> dict[str, object]:
        rows = self.list_asr_segments(job_id, config_fingerprint)
        completed = [row for row in rows if row.status == "completed"]
        return {
            "total": len(rows),
            "completed": len(completed),
            "processing": sum(row.status == "processing" for row in rows),
            "failed": sum(row.status == "failed" for row in rows),
            "audio_seconds": sum(max(0.0, row.end_seconds - row.start_seconds) for row in rows),
            "completed_audio_seconds": sum(
                max(0.0, row.end_seconds - row.start_seconds) for row in completed
            ),
            "segments": rows,
        }

    def clear_asr_checkpoints(
        self,
        job_id: str,
        config_fingerprint: str | None = None,
    ) -> int:
        with self.session_factory.begin() as session:
            statement = delete(AsrSegmentRow).where(AsrSegmentRow.job_id == job_id)
            if config_fingerprint is not None:
                statement = statement.where(
                    AsrSegmentRow.config_fingerprint == config_fingerprint
                )
            result = session.execute(statement)
            return int(result.rowcount or 0)

    def clear_stale_asr_checkpoints(
        self,
        content_id: str,
        *,
        keep_job_id: str,
    ) -> list[Job]:
        """Drop ASR rows belonging to older runs after a new result commits."""

        with self.session_factory.begin() as session:
            rows = session.execute(
                select(JobRow)
                .join(AnalysisRunRow, AnalysisRunRow.id == JobRow.analysis_run_id)
                .where(
                    AnalysisRunRow.content_id == content_id,
                    JobRow.id != keep_job_id,
                )
            ).scalars().all()
            stale_ids = [row.id for row in rows]
            if stale_ids:
                session.execute(delete(AsrSegmentRow).where(AsrSegmentRow.job_id.in_(stale_ids)))
            return [_job_from_row(row) for row in rows]

    def record_asr_performance(
        self,
        *,
        engine: str,
        device: str,
        audio_seconds: float,
        elapsed_seconds: float,
        now: datetime | None = None,
    ) -> AsrPerformanceSample:
        audio = max(0.001, float(audio_seconds))
        elapsed = max(0.0, float(elapsed_seconds))
        now = now or datetime.now(UTC)
        sample = AsrPerformanceSample(
            id=new_id("asr-sample"),
            engine=engine,
            device=device,
            audio_seconds=audio,
            elapsed_seconds=elapsed,
            rtf=elapsed / audio,
            created_at=now,
        )
        with self.session_factory.begin() as session:
            session.add(
                AsrPerformanceSampleRow(
                    id=sample.id,
                    engine=sample.engine,
                    device=sample.device,
                    audio_seconds=sample.audio_seconds,
                    elapsed_seconds=sample.elapsed_seconds,
                    rtf=sample.rtf,
                    created_at=sample.created_at,
                )
            )
        return sample

    def recent_asr_rtf(
        self,
        *,
        engine: str,
        device: str,
        limit: int = 5,
    ) -> list[float]:
        with self.session_factory() as session:
            rows = session.execute(
                select(AsrPerformanceSampleRow.rtf)
                .where(
                    AsrPerformanceSampleRow.engine == engine,
                    AsrPerformanceSampleRow.device == device,
                )
                .order_by(AsrPerformanceSampleRow.created_at.desc())
                .limit(max(1, int(limit)))
            ).scalars().all()
        return [float(value) for value in rows]

    def asr_total_budget_seconds(
        self,
        *,
        engine: str,
        device: str,
        audio_seconds: float,
    ) -> float:
        samples = self.recent_asr_rtf(engine=engine, device=device, limit=5)
        history_rtf = float(median(samples)) if samples else 1.5
        return min(
            21600.0,
            max(300.0, max(0.0, float(audio_seconds)) * max(history_rtf * 2.0, 1.5) + 180.0),
        )

    def recover_expired_jobs(self, *, now: datetime | None = None) -> list[Job]:
        recovered: list[Job] = []
        for job in self.list_jobs():
            if job.recover_if_expired(now=now):
                self.save_job(job)
                recovered.append(job)
        return recovered

    def create_summary_version(
        self,
        content_id: str,
        markdown: str,
        *,
        template: str,
        origin: str,
        parent_version_id: str | None = None,
        chapter_title: str | None = None,
        source_start_seconds: float | None = None,
        source_end_seconds: float | None = None,
        summary_strength: str | None = None,
        summary_style: str | None = None,
        material_level: str | None = None,
        source_version: str | None = None,
        source_scope: dict[str, Any] | None = None,
        processed_source_refs: list[str] | None = None,
        expected_source_refs: list[str] | None = None,
        provider: str | None = None,
        model: str | None = None,
        prompt_version: str | None = None,
    ) -> SummaryVersion:
        if not markdown.strip():
            raise ValueError("summary version markdown must not be empty")
        now = datetime.now(UTC)
        with self.session_factory.begin() as session:
            if session.get(ContentRow, content_id) is None:
                raise ContentNotFoundError(content_id)
            latest = session.execute(
                select(SummaryVersionRow)
                .where(SummaryVersionRow.content_id == content_id)
                .order_by(SummaryVersionRow.version_number.desc())
            ).scalars().first()
            version_number = latest.version_number + 1 if latest else 1
            row = SummaryVersionRow(
                id=new_id("summary"),
                content_id=content_id,
                version_number=version_number,
                parent_version_id=parent_version_id,
                origin=origin,
                template=template,
                chapter_title=chapter_title,
                source_start_seconds=source_start_seconds,
                source_end_seconds=source_end_seconds,
                markdown=markdown,
                summary_strength=summary_strength,
                summary_style=summary_style,
                material_level=material_level,
                source_version=source_version,
                source_scope=source_scope,
                processed_source_refs=processed_source_refs,
                expected_source_refs=expected_source_refs,
                provider=provider,
                model=model,
                prompt_version=prompt_version,
                created_at=now,
            )
            session.add(row)
        return _summary_version_from_row(row)

    def get_summary_version(self, version_id: str) -> SummaryVersion:
        with self.session_factory() as session:
            row = session.get(SummaryVersionRow, version_id)
            if row is None:
                raise LookupError(version_id)
        return _summary_version_from_row(row)

    def list_summary_versions(self, content_id: str) -> list[SummaryVersion]:
        with self.session_factory() as session:
            rows = session.execute(
                select(SummaryVersionRow)
                .where(SummaryVersionRow.content_id == content_id)
                .order_by(SummaryVersionRow.version_number.desc())
            ).scalars().all()
        return [_summary_version_from_row(row) for row in rows]

    def create_summary_feedback(
        self,
        content_id: str,
        *,
        category: str,
        version_id: str | None = None,
        note: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> SummaryFeedback:
        now = datetime.now(UTC)
        with self.session_factory.begin() as session:
            if session.get(ContentRow, content_id) is None:
                raise ContentNotFoundError(content_id)
            if version_id:
                version = session.get(SummaryVersionRow, version_id)
                if version is None or version.content_id != content_id:
                    raise LookupError(version_id)
            row = SummaryFeedbackRow(
                id=new_id("feedback"),
                content_id=content_id,
                version_id=version_id,
                category=category,
                note=note.strip() if note and note.strip() else None,
                context_json=dict(context or {}),
                created_at=now,
            )
            session.add(row)
        return _summary_feedback_from_row(row)

    def list_summary_feedback(self, content_id: str) -> list[SummaryFeedback]:
        with self.session_factory() as session:
            rows = session.execute(
                select(SummaryFeedbackRow)
                .where(SummaryFeedbackRow.content_id == content_id)
                .order_by(SummaryFeedbackRow.created_at.desc())
            ).scalars().all()
        return [_summary_feedback_from_row(row) for row in rows]

    def create_job_feedback(
        self,
        job_id: str,
        *,
        content_id: str,
        category: str,
        note: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> TaskFeedback:
        now = datetime.now(UTC)
        with self.session_factory.begin() as session:
            if session.get(JobRow, job_id) is None:
                raise LookupError(job_id)
            if session.get(ContentRow, content_id) is None:
                raise ContentNotFoundError(content_id)
            row = JobFeedbackRow(
                id=new_id("job-feedback"),
                job_id=job_id,
                content_id=content_id,
                category=category,
                note=note.strip() if note and note.strip() else None,
                context_json=dict(context or {}),
                created_at=now,
            )
            session.add(row)
        return _task_feedback_from_row(row)

    def list_job_feedback(self, job_id: str) -> list[TaskFeedback]:
        with self.session_factory() as session:
            rows = session.execute(
                select(JobFeedbackRow)
                .where(JobFeedbackRow.job_id == job_id)
                .order_by(JobFeedbackRow.created_at.desc())
            ).scalars().all()
        return [_task_feedback_from_row(row) for row in rows]

    def export_snapshot(self) -> dict[str, Any]:
        """Export rebuildable library state without protected setting values."""

        models = (
            ContentRow,
            TagRow,
            FavoriteFolderRow,
            ContentTagRow,
            ContentFavoriteFolderRow,
            AnalysisRunRow,
            JobRow,
            JobEventRow,
            ContentSummaryRow,
            SummaryVersionRow,
            SummaryFeedbackRow,
            JobFeedbackRow,
            PlatformConnectionRow,
        )
        tables: dict[str, list[dict[str, Any]]] = {}
        with self.session_factory() as session:
            for model in models:
                rows = session.execute(select(model)).scalars().all()
                tables[model.__tablename__] = [
                    {
                        column.name: _snapshot_value(getattr(row, column.name))
                        for column in model.__table__.columns
                    }
                    for row in rows
                ]
            settings = session.execute(select(AppSettingRow)).scalars().all()
            setting_values = {
                row.key: row.value
                for row in settings
                if row.key not in PROTECTED_SETTING_KEYS
            }
            redacted_settings = sorted(
                row.key for row in settings if row.key in PROTECTED_SETTING_KEYS
            )
        return {
            "schema_version": "governance-v1",
            "created_at": datetime.now(UTC).isoformat(),
            "tables": tables,
            "settings": setting_values,
            "redacted_settings": redacted_settings,
        }

    def restore_snapshot(self, snapshot: dict[str, Any]) -> dict[str, int | list[str]]:
        """Merge a portable snapshot, leaving protected settings untouched."""

        model_order = (
            ContentRow,
            TagRow,
            FavoriteFolderRow,
            ContentTagRow,
            ContentFavoriteFolderRow,
            AnalysisRunRow,
            JobRow,
            JobEventRow,
            ContentSummaryRow,
            SummaryVersionRow,
            SummaryFeedbackRow,
            JobFeedbackRow,
            PlatformConnectionRow,
        )
        restored: dict[str, int] = {}
        tables = snapshot.get("tables")
        if not isinstance(tables, dict):
            raise ValueError("backup_snapshot_tables_missing")
        with self.session_factory.begin() as session:
            for model in model_order:
                count = 0
                primary_keys = list(model.__mapper__.primary_key)
                for raw in tables.get(model.__tablename__, []):
                    if not isinstance(raw, dict):
                        continue
                    key_values = [raw.get(column.name) for column in primary_keys]
                    if any(value is None for value in key_values):
                        continue
                    identity = key_values[0] if len(key_values) == 1 else tuple(key_values)
                    if session.get(model, identity) is not None:
                        continue
                    values = {
                        column.name: _restore_value(raw.get(column.name), column.type)
                        for column in model.__table__.columns
                        if column.name in raw
                    }
                    session.add(model(**values))
                    count += 1
                session.flush()
                restored[model.__tablename__] = count
        settings = snapshot.get("settings")
        restored_settings = 0
        if isinstance(settings, dict):
            for key, value in settings.items():
                if key in PROTECTED_SETTING_KEYS or key in {"archive_root", "summary_skills_root"} or not isinstance(value, str):
                    continue
                self.set_setting(key, value)
                restored_settings += 1
        restored["settings"] = restored_settings
        return restored

    def upsert_summary(
        self,
        content_id: str,
        summary_text: str,
        *,
        transcript_text: str | None = None,
        source_note: str | None = None,
        processing_model: str | None = None,
    ) -> None:
        with self.session_factory.begin() as session:
            row = session.get(ContentSummaryRow, content_id)
            now = datetime.now(UTC)
            if row is None:
                session.add(
                    ContentSummaryRow(
                        content_id=content_id,
                        summary_text=summary_text,
                        transcript_text=transcript_text,
                        source_note=source_note,
                        updated_at=now,
                    )
                )
            else:
                row.summary_text = summary_text
                row.transcript_text = transcript_text
                row.source_note = source_note
                row.updated_at = now
            content = session.get(ContentRow, content_id)
            if content is not None and processing_model:
                content.processing_model = processing_model
                content.updated_at = now

    def get_summary(self, content_id: str) -> str | None:
        with self.session_factory() as session:
            row = session.get(ContentSummaryRow, content_id)
        return row.summary_text if row is not None else None

    def get_transcript_text(self, content_id: str) -> str | None:
        """Return the saved source transcript without exposing summary text."""

        with self.session_factory() as session:
            row = session.get(ContentSummaryRow, content_id)
        return row.transcript_text if row is not None else None

    def _get_setting_raw(self, key: str) -> str | None:
        with self.session_factory() as session:
            row = session.get(AppSettingRow, key)
            return row.value if row is not None else None

    def get_setting(self, key: str) -> str | None:
        value = self._get_setting_raw(key)
        if value and key in {"asr_api_key", "asr_cloud_api_key"} and value.startswith(
            ("dpapi:", "fernet:")
        ):
            return unprotect_secret(value, purpose="云端 ASR API Key")
        return value

    def set_setting(self, key: str, value: str | None) -> None:
        with self.session_factory.begin() as session:
            row = session.get(AppSettingRow, key)
            now = datetime.now(UTC)
            if value is None or not value.strip():
                if row is not None:
                    session.delete(row)
                return
            if row is None:
                session.add(AppSettingRow(key=key, value=value.strip(), updated_at=now))
            else:
                row.value = value.strip()
                row.updated_at = now

    def set_secret_setting(self, key: str, value: str | None, *, purpose: str) -> None:
        if value is None or not value.strip():
            self.set_setting(key, None)
            return
        self.set_setting(key, protect_secret(value.strip(), purpose=purpose))

    def set_summary_settings_atomically(
        self,
        values: dict[str, str | None],
        *,
        api_key_provided: bool = False,
        api_key: str | None = None,
    ) -> None:
        """Persist the summary configuration as one validated SQLite change.

        Secret protection deliberately happens before opening the transaction so
        a platform security failure cannot leave URL/provider/model settings
        half-updated.  An omitted key keeps the already protected key intact.
        """

        protected_key: str | None = None
        if api_key_provided and api_key and api_key.strip():
            protected_key = protect_secret(
                api_key.strip(),
                purpose="总结模型 API Key",
            )

        pending = dict(values)
        if api_key_provided:
            pending["summary_api_key"] = protected_key
        with self.session_factory.begin() as session:
            now = datetime.now(UTC)
            for key, value in pending.items():
                row = session.get(AppSettingRow, key)
                if value is None or not str(value).strip():
                    if row is not None:
                        session.delete(row)
                    continue
                normalized = str(value).strip()
                if row is None:
                    session.add(AppSettingRow(key=key, value=normalized, updated_at=now))
                else:
                    row.value = normalized
                    row.updated_at = now

    def get_secret_setting(self, key: str, *, purpose: str) -> str | None:
        protected = self._get_setting_raw(key)
        if not protected:
            return None
        if not protected.startswith(("dpapi:", "fernet:")):
            return protected
        return unprotect_secret(protected, purpose=purpose)

    def save_bilibili_session(self, cookie: str, refresh_token: str | None) -> None:
        # Protect both values before opening the transaction.  If DPAPI fails,
        # neither half of the session is written and a previous session stays
        # intact.
        protected_cookie = protect_secret(cookie)
        protected_refresh = protect_secret(refresh_token) if refresh_token else None
        with self.session_factory.begin() as session:
            now = datetime.now(UTC)
            for key, value in (
                ("bilibili_session_cookie", protected_cookie),
                ("bilibili_refresh_token", protected_refresh),
            ):
                row = session.get(AppSettingRow, key)
                if value is None:
                    if row is not None:
                        session.delete(row)
                elif row is None:
                    session.add(AppSettingRow(key=key, value=value, updated_at=now))
                else:
                    row.value = value
                    row.updated_at = now

    def get_bilibili_session_cookie(self) -> str | None:
        protected = self.get_setting("bilibili_session_cookie")
        return unprotect_secret(protected) if protected else None

    def get_bilibili_refresh_token(self) -> str | None:
        protected = self.get_setting("bilibili_refresh_token")
        return unprotect_secret(protected) if protected else None

    def clear_bilibili_session(self) -> None:
        self.set_setting("bilibili_session_cookie", None)
        self.set_setting("bilibili_refresh_token", None)

    def get_platform_connection(self, platform: str) -> PlatformConnection | None:
        with self.session_factory() as session:
            row = session.get(PlatformConnectionRow, platform)
        return _platform_connection_from_row(row) if row is not None else None

    def list_platform_connections(self) -> list[PlatformConnection]:
        with self.session_factory() as session:
            rows = session.execute(
                select(PlatformConnectionRow).order_by(PlatformConnectionRow.platform)
            ).scalars().all()
        return [_platform_connection_from_row(row) for row in rows]

    def save_platform_connection(
        self,
        *,
        platform: str,
        status: str,
        auth_type: str,
        account_label: str | None = None,
        browser: str | None = None,
        browser_profile: str | None = None,
        login_url: str | None = None,
        last_checked_at: datetime | None = None,
        last_connected_at: datetime | None = None,
        message: str | None = None,
    ) -> PlatformConnection:
        now = datetime.now(UTC)
        with self.session_factory.begin() as session:
            row = session.get(PlatformConnectionRow, platform)
            if row is None:
                row = PlatformConnectionRow(
                    platform=platform,
                    status=status,
                    auth_type=auth_type,
                    account_label=account_label,
                    browser=browser,
                    browser_profile=browser_profile,
                    login_url=login_url,
                    last_checked_at=last_checked_at,
                    last_connected_at=last_connected_at,
                    message=message,
                    updated_at=now,
                )
                session.add(row)
            else:
                row.status = status
                row.auth_type = auth_type
                row.account_label = account_label
                row.browser = browser
                row.browser_profile = browser_profile
                row.login_url = login_url
                row.last_checked_at = last_checked_at
                row.last_connected_at = last_connected_at
                row.message = message
                row.updated_at = now
        return _platform_connection_from_row(row)

    def delete_platform_connection(self, platform: str) -> None:
        with self.session_factory.begin() as session:
            row = session.get(PlatformConnectionRow, platform)
            if row is not None:
                session.delete(row)

    def count_archived_contents(self) -> int:
        statement = (
            select(func.count(func.distinct(ContentRow.id)))
            .join(AnalysisRunRow, AnalysisRunRow.content_id == ContentRow.id)
            .join(JobRow, JobRow.analysis_run_id == AnalysisRunRow.id)
            .where(ContentRow.deleted_at.is_(None), JobRow.state == JobState.COMPLETED.value)
        )
        with self.session_factory() as session:
            return int(session.scalar(statement) or 0)

    def list_history(
        self,
        query: str | None = None,
        *,
        category: str | None = None,
        platform: str | None = None,
        author: str | None = None,
        sort_by: str = "created_at",
        descending: bool = True,
        include_deleted: bool = False,
        deleted_only: bool = False,
        favorite_folder_id: str | None = None,
        tag_id: str | None = None,
        archived_only: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[HistoryEntry]:
        sort_column = {
            "created_at": ContentRow.created_at,
            "updated_at": ContentRow.updated_at,
        }.get(sort_by, ContentRow.created_at)
        statement = (
            select(ContentRow, AnalysisRunRow, JobRow)
            .join(AnalysisRunRow, AnalysisRunRow.content_id == ContentRow.id)
            .join(JobRow, JobRow.analysis_run_id == AnalysisRunRow.id)
        )
        if deleted_only:
            statement = statement.where(ContentRow.deleted_at.is_not(None))
        elif not include_deleted:
            statement = statement.where(ContentRow.deleted_at.is_(None))
        if archived_only:
            statement = statement.where(JobRow.state == JobState.COMPLETED.value)
        if category:
            statement = statement.where(ContentRow.category == category.strip())
        if platform:
            statement = statement.where(ContentRow.platform == platform.strip())
        if author:
            statement = statement.where(ContentRow.author.ilike(f"%{author.strip()}%"))
        if favorite_folder_id:
            if favorite_folder_id == "all":
                statement = statement.where(ContentRow.favorite.is_(True))
            else:
                statement = statement.where(
                    exists(
                        select(ContentFavoriteFolderRow.content_id).where(
                            ContentFavoriteFolderRow.content_id == ContentRow.id,
                            ContentFavoriteFolderRow.folder_id == favorite_folder_id,
                        )
                    )
                )
        if tag_id:
            if tag_id == "untagged":
                statement = statement.where(
                    ~exists(
                        select(ContentTagRow.content_id).where(
                            ContentTagRow.content_id == ContentRow.id
                        )
                    )
                )
            else:
                statement = statement.where(
                    exists(
                        select(ContentTagRow.content_id).where(
                            ContentTagRow.content_id == ContentRow.id,
                            ContentTagRow.tag_id == tag_id,
                        )
                    )
                )
        if query and query.strip():
            term = f"%{query.strip()}%"
            summary_hit = exists(
                select(ContentSummaryRow.content_id).where(
                    ContentSummaryRow.content_id == ContentRow.id,
                    or_(
                        ContentSummaryRow.summary_text.ilike(term),
                        ContentSummaryRow.transcript_text.ilike(term),
                        ContentSummaryRow.source_note.ilike(term),
                    ),
                )
            )
            statement = statement.where(
                or_(
                    ContentRow.title.ilike(term),
                    ContentRow.platform.ilike(term),
                    ContentRow.author.ilike(term),
                    ContentRow.canonical_url.ilike(term),
                    ContentRow.language.ilike(term),
                    ContentRow.category.ilike(term),
                    summary_hit,
                )
            )
        order = sort_column.desc() if descending else sort_column.asc()
        statement = statement.order_by(order, AnalysisRunRow.created_at.desc())
        with self.session_factory() as session:
            rows = session.execute(statement).all()
        entries = [_history_entry_from_rows(*row) for row in rows]
        # A retry may create several runs for one Content; repeated imports of the
        # same BVID+P create several Content rows. Both render one row here.
        unique: dict[str, HistoryEntry] = {}
        for entry in entries:
            key = _history_identity_key(entry)
            previous = unique.get(key)
            if previous is None or entry.run.created_at > previous.run.created_at:
                unique[key] = entry
        entries = [entry for entry in entries if unique.get(_history_identity_key(entry)) is entry]
        start = max(0, offset)
        return entries[start:] if limit is None else entries[start : start + max(0, limit)]

    def get_history_entry(self, content_id: str) -> HistoryEntry:
        statement = (
            select(ContentRow, AnalysisRunRow, JobRow)
            .join(AnalysisRunRow, AnalysisRunRow.content_id == ContentRow.id)
            .join(JobRow, JobRow.analysis_run_id == AnalysisRunRow.id)
            .where(ContentRow.id == content_id)
            .order_by(AnalysisRunRow.created_at.desc())
        )
        with self.session_factory() as session:
            row = session.execute(statement).first()
        if row is None:
            raise ContentNotFoundError(content_id)
        return _history_entry_from_rows(*row)


def _snapshot_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _snapshot_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_snapshot_value(item) for item in value]
    return value


def _restore_value(value: Any, column_type: Any) -> Any:
    if value is None:
        return None
    if isinstance(column_type, DateTime) and isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


def _summary_version_from_row(row: SummaryVersionRow) -> SummaryVersion:
    return SummaryVersion(
        id=row.id,
        content_id=row.content_id,
        version_number=row.version_number,
        parent_version_id=row.parent_version_id,
        origin=row.origin,
        template=row.template,
        chapter_title=row.chapter_title,
        source_start_seconds=row.source_start_seconds,
        source_end_seconds=row.source_end_seconds,
        markdown=row.markdown,
        created_at=row.created_at,
        summary_strength=row.summary_strength,
        summary_style=row.summary_style,
        material_level=row.material_level,
        source_version=row.source_version,
        source_scope=row.source_scope,
        processed_source_refs=row.processed_source_refs,
        expected_source_refs=row.expected_source_refs,
        provider=row.provider,
        model=row.model,
        prompt_version=row.prompt_version,
    )


def _summary_feedback_from_row(row: SummaryFeedbackRow) -> SummaryFeedback:
    return SummaryFeedback(
        id=row.id,
        content_id=row.content_id,
        version_id=row.version_id,
        category=row.category,
        note=row.note,
        context=row.context_json or {},
        created_at=row.created_at,
    )


def _task_feedback_from_row(row: JobFeedbackRow) -> TaskFeedback:
    return TaskFeedback(
        id=row.id,
        job_id=row.job_id,
        content_id=row.content_id,
        category=row.category,
        note=row.note,
        context=row.context_json or {},
        created_at=row.created_at,
    )


def _normalize_folder_ids(folder_ids: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if not folder_ids:
        return ()
    return tuple(dict.fromkeys(folder_id.strip() for folder_id in folder_ids if folder_id.strip()))


def _normalize_ids(values: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if not values:
        return ()
    return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))


def _get_or_create_tag(session, name: str, *, user_id: str = "local") -> TagRow:
    tag = session.execute(
        select(TagRow).where(TagRow.user_id == user_id, TagRow.name.ilike(name))
    ).scalar_one_or_none()
    if tag is not None:
        return tag
    now = datetime.now(UTC)
    tag = TagRow(
        id=new_id("tag"),
        user_id=user_id,
        name=name,
        created_at=now,
        updated_at=now,
    )
    session.add(tag)
    session.flush()
    return tag


def _tag_from_row(row: TagRow, content_count: int) -> Tag:
    return Tag(
        id=row.id,
        name=row.name,
        user_id=row.user_id,
        content_count=content_count,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _completed_job_exists(content_id_expression: Any):
    return exists(
        select(JobRow.id)
        .join(AnalysisRunRow, AnalysisRunRow.id == JobRow.analysis_run_id)
        .where(
            AnalysisRunRow.content_id == content_id_expression,
            JobRow.state == JobState.COMPLETED.value,
        )
    )


def _favorite_folder_from_row(row: FavoriteFolderRow, content_count: int) -> FavoriteFolder:
    return FavoriteFolder(
        id=row.id,
        name=row.name,
        parent_id=row.parent_id,
        content_count=content_count,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )

def _content_from_row(row: ContentRow) -> ContentItem:
    return ContentItem(
        id=row.id,
        kind=ContentKind(row.kind),
        title=row.title,
        source=SourceRecord(
            platform=SourcePlatform(row.platform),
            canonical_url=row.canonical_url,
            thumbnail_url=row.thumbnail_url,
            author=row.author,
            published_at=row.published_at,
            acquired_at=row.acquired_at or row.created_at,
            acquisition_method=row.acquisition_method or "adapter",
        ),
        language=row.language,
        duration_seconds=row.duration_seconds,
        content_hash=row.content_hash,
        category=row.category or "未分类",
        introduction=row.introduction or "",
        favorite=bool(row.favorite),
        deleted_at=row.deleted_at,
        processing_model=row.processing_model,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _utc_datetime(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _event_stage(checkpoint: str | None, state: str) -> str:
    if state == JobState.QUEUED.value:
        return "queue"
    if checkpoint:
        return _EVENT_STAGE_BY_CHECKPOINT.get(checkpoint, "task")
    return "queue" if state == JobState.QUEUED.value else "task"


def _job_event_change(
    *,
    previous_state: str,
    previous_attempt: int,
    previous_progress: int,
    previous_checkpoint: str | None,
    previous_error_code: str | None,
    previous_error_message: str | None,
    job: Job,
) -> tuple[str, str, dict[str, Any]] | None:
    current_state = job.state.value
    details: dict[str, Any] = {}
    if previous_state != current_state:
        details["previous_state"] = previous_state
        if current_state == JobState.ACQUIRING.value:
            return "started", "任务开始执行", details
        if current_state == JobState.PAUSED.value:
            stable_checkpoint = job.metadata.get("last_stable_checkpoint")
            if isinstance(stable_checkpoint, str):
                details["last_stable_checkpoint"] = stable_checkpoint
            return "paused", "任务已暂停", details
        if current_state == JobState.QUEUED.value and previous_state == JobState.PAUSED.value:
            resume_checkpoint = job.metadata.get("resume_checkpoint")
            if isinstance(resume_checkpoint, str):
                details["resume_checkpoint"] = resume_checkpoint
            return "resumed", "任务已继续，等待执行", details
        if current_state == JobState.QUEUED.value:
            return "requeued", "任务已重新排队", details
        if current_state == JobState.COMPLETED.value:
            return "completed", "任务已完成", details
        if current_state == JobState.FAILED.value:
            if job.error_code is not None:
                details["error_code"] = job.error_code.value
            return "failed", "任务失败", details
        if current_state == JobState.CANCELLED.value:
            return "cancelled", "任务已取消", details
        return "stage_changed", _EVENT_STATE_LABEL.get(current_state, "任务阶段已更新"), details

    current_error_code = (
        job.error_code.value if job.error_code is not None else None
    )
    if (
        previous_error_code != current_error_code
        or previous_error_message != job.error_message
    ):
        if current_error_code:
            details["error_code"] = current_error_code
        return "error", "任务错误信息已更新", details

    if previous_progress != job.progress or previous_checkpoint != job.checkpoint:
        details["previous_progress"] = previous_progress
        if previous_checkpoint:
            details["previous_checkpoint"] = previous_checkpoint
        return "progress", f"任务进度更新至 {job.progress}%", details

    if previous_attempt != job.attempt:
        return "attempt", f"任务开始第 {job.attempt} 次尝试", details

    return None


def _append_job_event(
    session,
    job: Job,
    *,
    event_type: str,
    message: str,
    stage: str | None = None,
    state: str | None = None,
    progress: int | None = None,
    attempt: int | None = None,
    checkpoint: str | None = None,
    error_code: str | None = None,
    details: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
) -> JobEvent:
    normalized_type = event_type.strip()
    normalized_message = message.strip()
    if not normalized_type:
        raise ValueError("event_type must not be empty")
    if not normalized_message:
        raise ValueError("event message must not be empty")
    current_state = state or job.state.value
    current_checkpoint = job.checkpoint if checkpoint is None else checkpoint
    current_error_code = error_code
    if current_error_code is None and job.error_code is not None:
        current_error_code = job.error_code.value
    last_sequence = session.execute(
        select(func.max(JobEventRow.sequence)).where(JobEventRow.job_id == job.id)
    ).scalar_one()
    row = JobEventRow(
        id=new_id("event"),
        job_id=job.id,
        sequence=int(last_sequence or 0) + 1,
        attempt=job.attempt if attempt is None else attempt,
        event_type=normalized_type,
        stage=stage or _event_stage(current_checkpoint, current_state),
        state=current_state,
        progress=job.progress if progress is None else progress,
        checkpoint=current_checkpoint,
        error_code=current_error_code,
        message=normalized_message,
        details_json=dict(details or {}),
        occurred_at=_utc_datetime(occurred_at or datetime.now(UTC)),
    )
    session.add(row)
    return _job_event_from_row(row)


def _job_from_row(row: JobRow) -> Job:
    from app.domain.jobs import JobErrorCode

    return Job(
        id=row.id,
        type=row.type,
        analysis_run_id=row.analysis_run_id,
        state=JobState(row.state),
        attempt=row.attempt,
        progress=row.progress,
        checkpoint=row.checkpoint,
        lease_until=row.lease_until,
        worker_id=row.worker_id,
        error_code=JobErrorCode(row.error_code) if row.error_code else None,
        error_message=row.error_message,
        metadata=row.metadata_json or {},
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
        priority=row.priority or 0,
        queue_position=row.queue_position,
    )


def _job_event_from_row(row: JobEventRow) -> JobEvent:
    return JobEvent(
        id=row.id,
        job_id=row.job_id,
        sequence=row.sequence,
        attempt=row.attempt,
        event_type=row.event_type,
        stage=row.stage,
        state=row.state,
        progress=row.progress,
        checkpoint=row.checkpoint,
        error_code=row.error_code,
        message=row.message,
        details=dict(row.details_json or {}),
        occurred_at=_utc_datetime(row.occurred_at),
    )


def _asr_segment_from_row(row: AsrSegmentRow) -> AsrSegmentCheckpoint:
    return AsrSegmentCheckpoint(
        id=row.id,
        job_id=row.job_id,
        config_fingerprint=row.config_fingerprint,
        segment_index=row.segment_index,
        start_seconds=float(row.start_seconds),
        end_seconds=float(row.end_seconds),
        status=row.status,
        text=row.text,
        language=row.language,
        attempts=int(row.attempts),
        lease_owner=row.lease_owner,
        lease_expires_at=_utc_datetime(row.lease_expires_at)
        if row.lease_expires_at is not None
        else None,
        worker_generation=int(row.worker_generation),
        heartbeat_at=_utc_datetime(row.heartbeat_at) if row.heartbeat_at is not None else None,
        completed_at=_utc_datetime(row.completed_at) if row.completed_at is not None else None,
        error_message=row.error_message,
        created_at=_utc_datetime(row.created_at),
        updated_at=_utc_datetime(row.updated_at),
    )


def _analysis_run_from_row(row: AnalysisRunRow) -> AnalysisRun:
    return AnalysisRun(
        id=row.id,
        content_id=row.content_id,
        status=row.status,
        settings_snapshot=row.settings_snapshot,
        prompt_version=row.prompt_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
        error_code=row.error_code,
        error_message=row.error_message,
    )


def _history_entry_from_rows(
    content_row: ContentRow,
    run_row: AnalysisRunRow,
    job_row: JobRow,
) -> HistoryEntry:
    return HistoryEntry(
        content=_content_from_row(content_row),
        run=_analysis_run_from_row(run_row),
        job=_job_from_row(job_row),
    )


def _title_suffix_key(title: str | None) -> str:
    """取标题末尾的「（N）」重复后缀作折叠键的一部分；无后缀返回空串。

    11-22 R4：继续导入生成的副本标题是「原名（1）」「原名（2）」，其 canonical_url
    仍与原件同源。折叠键带上这个后缀后，原件与副本各占一行、同时可见；无后缀的历史
    重复导入继续按原键折叠，显示方式不变。
    """

    match = re.search(r"（(\d+)）\s*$", title or "")
    return f"s{match.group(1)}" if match else ""


def _history_identity_key(entry: HistoryEntry) -> str:
    """同一 BVID+P 的历史重复导入折叠成一行；带「（N）」后缀的副本独立成行。

    数据本身不删除、不合并。11-22 R4 增加标题后缀维度使带序号副本可见。
    """

    identity = _bilibili_source_identity(entry.content.source.canonical_url)
    if identity is not None:
        bvid, page_number = identity
        return f"bili:{bvid}:p{page_number}:{_title_suffix_key(entry.content.title)}"
    return f"content:{entry.content.id}"


def _platform_connection_from_row(row: PlatformConnectionRow) -> PlatformConnection:
    return PlatformConnection(
        platform=row.platform,
        status=row.status,
        auth_type=row.auth_type,
        account_label=row.account_label,
        browser=row.browser,
        browser_profile=row.browser_profile,
        login_url=row.login_url,
        last_checked_at=row.last_checked_at,
        last_connected_at=row.last_connected_at,
        message=row.message,
        updated_at=row.updated_at,
    )
