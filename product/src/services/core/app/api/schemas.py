from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import ContentKind, SourcePlatform, SummaryStrength


SummaryApiMode = Literal["chat_completions", "responses"]


class PreflightCheckResponse(BaseModel):
    code: str
    label: str
    status: Literal["ok", "warning", "error"]
    blocking: bool = False
    message: str
    action: str | None = None


class ResourceEstimateResponse(BaseModel):
    estimated_duration_seconds_min: int
    estimated_duration_seconds_max: int
    estimated_disk_bytes: int
    disk_free_bytes: int
    memory_required_mb: int
    cloud_input_tokens_min: int
    cloud_input_tokens_max: int
    cloud_cost_min: float | None = None
    cloud_cost_max: float | None = None
    cloud_cost_currency: str | None = None
    cloud_cost_note: str
    basis: str


class EnvironmentCheckResponse(BaseModel):
    status: Literal["ok", "warning", "error"]
    checked_at: datetime
    checks: list[PreflightCheckResponse]
    platform: str
    python_version: str
    ffmpeg_path: str | None = None
    disk_free_bytes: int = 0
    model_root: str
    secret_status: dict[str, Literal["saved", "not_configured", "unreadable"]]


class TaskPreflightRequest(BaseModel):
    content_id: str | None = None
    kind: ContentKind | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    text_length: int = Field(default=0, ge=0)
    has_transcript: bool = False
    asr_engine: Literal["cloud", "local"] | None = None
    local_model: str | None = Field(default=None, max_length=81)
    model: str | None = Field(default=None, min_length=1, max_length=200)
    max_chunk_tokens: int = Field(default=800, ge=32, le=32000)
    source_url: str | None = Field(default=None, max_length=2000)


class TaskPreflightResponse(BaseModel):
    ready: bool
    checks: list[PreflightCheckResponse]
    estimate: ResourceEstimateResponse


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "core"
    api_contract_version: str


class ContentCreateRequest(BaseModel):
    kind: ContentKind
    title: str = Field(min_length=1)
    platform: SourcePlatform
    canonical_url: str | None = None
    thumbnail_url: str | None = None
    author: str | None = None
    language: str | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    content_hash: str | None = None
    published_at: datetime | None = None
    category: str = Field(default="未分类", min_length=1, max_length=120)
    tag_ids: list[str] | None = Field(default=None, max_length=100)
    introduction: str = Field(default="", max_length=30)
    favorite: bool = False
    favorite_folder_ids: list[str] = Field(default_factory=list, max_length=50)
    acquisition_method: str = Field(default="api", min_length=1, max_length=80)
    processing_model: str | None = Field(default=None, max_length=200)


class ContentResponse(BaseModel):
    id: str
    kind: ContentKind
    title: str
    platform: SourcePlatform
    canonical_url: str | None
    thumbnail_url: str | None = None
    author: str | None
    language: str | None
    duration_seconds: float | None
    content_hash: str | None
    published_at: datetime | None
    acquired_at: datetime
    acquisition_method: str
    category: str
    tag_ids: list[str] = Field(default_factory=list)
    tag_names: list[str] = Field(default_factory=list)
    introduction: str = ""
    favorite: bool
    favorite_folder_ids: list[str] = Field(default_factory=list)
    deleted_at: datetime | None
    processing_model: str | None
    created_at: datetime
    updated_at: datetime


class AnalysisRunCreateRequest(BaseModel):
    model: str | None = Field(default=None, min_length=1)
    strength: SummaryStrength = SummaryStrength.STANDARD
    summary_template: str = "general"
    summary_style: Literal["general", "course_notes", "academic", "tutorial", "sharing", "task_oriented", "business", "meeting_minutes"] | None = None
    language: str | None = None
    prompt_version: str = "summary-v1"
    asr_engine: str | None = None
    max_chunk_tokens: int = Field(default=800, ge=256, le=32000)
    priority: int = Field(default=0, ge=-10, le=10)


class AnalysisRunResponse(BaseModel):
    id: str
    content_id: str
    status: str
    settings_snapshot: dict[str, Any]
    prompt_version: str
    created_at: datetime
    updated_at: datetime


class JobResponse(BaseModel):
    id: str
    type: str
    analysis_run_id: str
    state: str
    execution_state: str = "waiting"
    queue_state: str = "waiting"
    active_job_id: str | None = None
    attempt: int
    progress: int
    checkpoint: str | None
    last_stable_stage: str | None = None
    resume_stage: str | None = None
    lease_until: datetime | None
    worker_id: str | None
    error_code: str | None
    error_message: str | None
    recovery_action: str | None = None
    recovery_suggestion: str | None = None
    archive_path: str | None = None
    summary_preview: str | None = None
    source_url: str | None = None
    source_note: str | None = None
    thumbnail_url: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    elapsed_seconds: float | None = None
    priority: int = 0
    queue_position: int | None = None
    content_id: str | None = None
    content_title: str | None = None
    content_platform: SourcePlatform | None = None
    content_author: str | None = None
    content_category: str | None = None
    # 内容首次入库时间：重试不会改写，用作任务列表的稳定排序锚点。
    content_created_at: datetime | None = None
    batch_name: str | None = None
    batch_id: str | None = None
    batch_item_number: int | None = None
    batch_total: int | None = None
    collection_id: str | None = None
    collection_title: str | None = None
    collection_total: int | None = None
    asr_subtitle_hit: bool | None = None
    asr_skipped: bool | None = None
    asr_skipped_reason: str | None = None
    asr_fallback_reason: str | None = None
    asr_segment_completed: int | None = None
    asr_segment_total: int | None = None
    asr_completed_audio_seconds: float | None = None
    asr_audio_seconds: float | None = None
    asr_vad_effective_audio_seconds: float | None = None
    asr_total_budget_seconds: float | None = None
    asr_elapsed_seconds: float | None = None
    asr_rtf: float | None = None
    asr_eta_seconds: float | None = None
    asr_budget_warning: bool | None = None
    asr_worker_generation: int | None = None
    asr_worker_cold_start: bool | None = None
    asr_recovery_count: int | None = None
    asr_batch_size: int | None = None
    asr_batch_selection: str | None = None
    asr_phase_seconds: dict[str, float | None] = Field(default_factory=dict)


class OpenUrlRequest(BaseModel):
    """只允许 http/https：来源链接交系统默认浏览器打开。"""

    url: str = Field(min_length=1, max_length=2000)


class QueueReorderRequest(BaseModel):
    """The complete visible order of queued jobs at the time of drop."""

    job_ids: list[str] = Field(min_length=1, max_length=200)


class QueueMoveRequest(BaseModel):
    job_id: str = Field(min_length=1, max_length=80)
    target_index: int = Field(ge=0, le=200)


class QueueSwitchRequest(BaseModel):
    target_job_id: str | None = Field(default=None, max_length=80)


class JobPriorityUpdateRequest(BaseModel):
    priority: int = Field(ge=-10, le=10)


class TaskEventResponse(BaseModel):
    id: str
    job_id: str
    sequence: int
    attempt: int
    event_type: str
    stage: str | None = None
    state: str
    progress: int
    checkpoint: str | None = None
    error_code: str | None = None
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime


class AnalysisRunCreatedResponse(BaseModel):
    run: AnalysisRunResponse
    job: JobResponse


class ZhihuSourceTextRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    title: str = Field(min_length=1, max_length=500)
    author: str | None = Field(default=None, max_length=200)
    text: str = Field(min_length=1, max_length=2_000_000)


class XhsNoteSourceRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    title: str = Field(default="", max_length=500)
    author: str | None = Field(default=None, max_length=200)
    text: str = Field(min_length=1, max_length=2_000_000)
    thumbnail_url: str | None = Field(default=None, max_length=2000)


class LocalImportRequest(BaseModel):
    source_path: str | None = None
    text: str | None = None
    zhihu_source: ZhihuSourceTextRequest | None = None
    xiaohongshu_source: XhsNoteSourceRequest | None = None
    model: str | None = Field(default=None, min_length=1)
    summary_template: str = "general"
    summary_style: Literal["general", "course_notes", "academic", "tutorial", "sharing", "task_oriented", "business", "meeting_minutes"] | None = None
    strength: SummaryStrength = SummaryStrength.STANDARD
    extra_instruction: str | None = Field(default=None, max_length=2000)
    duplicate_action: Literal["reuse", "overwrite", "regenerate"] = "regenerate"
    language: str | None = None
    max_chunk_tokens: int = Field(default=800, ge=32, le=32000)
    priority: int = Field(default=0, ge=-10, le=10)
    classify: bool = False
    category: str | None = Field(default=None, min_length=1, max_length=120)
    favorite_folder_ids: list[str] = Field(default_factory=list, max_length=50)
    tag_ids: list[str] = Field(default_factory=list, max_length=100)


class MobileIntakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: Literal["bilibili", "xiaohongshu"]
    title: str = Field(min_length=1, max_length=500)
    canonical_url: str = Field(min_length=1, max_length=2000)
    text: str = Field(min_length=1, max_length=2_000_000)
    language: str | None = Field(default=None, max_length=40)
    duration_seconds: float | None = Field(default=None, gt=0, le=172800)


class ResummarizeRequest(BaseModel):
    summary_template: str = "general"
    summary_style: Literal["general", "course_notes", "academic", "tutorial", "sharing", "task_oriented", "business", "meeting_minutes"] | None = None
    # 11-23：内容详情的重新总结复用原内容生成下一版本；继续导入不传，仍新建副本。
    reuse_content: bool = False
    strength: SummaryStrength = SummaryStrength.STANDARD
    extra_instruction: str | None = Field(default=None, max_length=2000)
    language: str | None = None
    max_chunk_tokens: int = Field(default=800, ge=256, le=32000)
    priority: int = Field(default=0, ge=-10, le=10)
    classify: bool = False
    category: str | None = Field(default=None, min_length=1, max_length=120)
    favorite_folder_ids: list[str] = Field(default_factory=list, max_length=50)
    tag_ids: list[str] = Field(default_factory=list, max_length=100)


class DuplicateCheckRequest(BaseModel):
    """11-22 R1：批量操作前服务端判重；只处理 job id，判重口径在服务端统一。"""

    job_ids: list[str] = Field(min_length=1, max_length=500)


class DuplicateCheckItem(BaseModel):
    job_id: str
    is_duplicate: bool = False
    matched_content_id: str | None = None
    matched_title: str | None = None


class DuplicateCheckResponse(BaseModel):
    items: list[DuplicateCheckItem] = Field(default_factory=list)


class LinkImportRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    model: str | None = Field(default=None, min_length=1)
    summary_template: str = "general"
    summary_style: Literal["general", "course_notes", "academic", "tutorial", "sharing", "task_oriented", "business", "meeting_minutes"] | None = None
    strength: SummaryStrength = SummaryStrength.STANDARD
    extra_instruction: str | None = Field(default=None, max_length=2000)
    duplicate_action: Literal["reuse", "overwrite", "regenerate"] = "reuse"
    language: str | None = None
    max_chunk_tokens: int = Field(default=800, ge=32, le=32000)
    priority: int = Field(default=0, ge=-10, le=10)


class LinkQueryRequest(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=50)
    language: str | None = None


class LinkQueryItemResponse(BaseModel):
    item_id: str
    input_url: str
    source_url: str | None = None
    platform: str | None = None
    kind: Literal["single", "collection", "creator", "favorite", "watchlater", "unknown"] = "unknown"
    source_type: Literal["single", "collection", "creator", "favorite", "watchlater", "unknown"] = "unknown"
    status: Literal["pending", "ready", "duplicate", "failed", "timed_out"]
    title: str | None = None
    author: str | None = None
    thumbnail_url: str | None = None
    duration_seconds: float | None = None
    published_at: datetime | None = None
    duplicate: bool = False
    selectable: bool = False
    reason: str | None = None
    material_hint: str | None = None


class LinkQueryResponse(BaseModel):
    query_id: str
    status: Literal["processing", "completed", "cancelled", "timed_out"] = "processing"
    items: list[LinkQueryItemResponse] = Field(default_factory=list)
    deadline_at: datetime | None = None


class LinkQueryConfirmRequest(BaseModel):
    query_id: str = Field(min_length=1, max_length=120)
    item_ids: list[str] = Field(min_length=1)
    model: str | None = Field(default=None, min_length=1)
    summary_template: str = "general"
    summary_style: Literal["general", "course_notes", "academic", "tutorial", "sharing", "task_oriented", "business", "meeting_minutes"] | None = None
    strength: SummaryStrength = SummaryStrength.STANDARD
    extra_instruction: str | None = Field(default=None, max_length=2000)
    duplicate_action: Literal["reuse", "overwrite", "regenerate"] = "reuse"
    language: str | None = None
    max_chunk_tokens: int = Field(default=800, ge=32, le=32000)
    priority: int = Field(default=0, ge=-10, le=10)
    classify: bool = False
    category: str | None = Field(default=None, min_length=1, max_length=120)
    favorite_folder_ids: list[str] = Field(default_factory=list, max_length=50)
    tag_ids: list[str] = Field(default_factory=list, max_length=100)


class SourceProbeRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)


class SourceProbeItemResponse(BaseModel):
    title: str
    source_url: str
    platform: str
    author: str | None = None
    thumbnail_url: str | None = None
    duration_seconds: float | None = None
    page_number: int | None = None
    duplicate: bool = False


class SourceProbeResponse(BaseModel):
    url: str
    platform: str
    kind: Literal["single", "collection"]
    # 值域由 classify.classify_source_type 控制：B站 既有子类型 + 方案 §5.1 的 8 值。
    source_type: str = "single"
    object_label: str = ""
    duplicate: bool = False
    preview_status: Literal["pending", "ready", "failed"] = "pending"
    preview_error: str | None = None
    items: list[SourceProbeItemResponse] = Field(default_factory=list)
    requires_login: bool = False
    material_hint: str
    next_action: str
    can_import: bool

class SourceCapabilityResponse(BaseModel):
    """`PlatformDefinition` 的派生投影：不要在此新增独立维护的能力字段。"""

    platform: str
    display_name: str
    login_url: str
    auth_type: str
    checker_available: bool
    browser_session_available: bool
    supported_source_types: list[str]
    public_import_available: bool
    account_probe_available: bool
    text_available: bool
    image_ocr_available: bool
    video_available: bool
    collection_sync_available: bool
    note: str


class SourceCapabilitiesResponse(BaseModel):
    capabilities: list[SourceCapabilityResponse]

class ImportResponse(BaseModel):
    content: ContentResponse
    run: AnalysisRunResponse
    job: JobResponse
    duplicate: bool = False
    duplicate_content_id: str | None = None
    reused: bool = False


class LocalImportResponse(ImportResponse):
    pass


class LinkImportResponse(BaseModel):
    content: ContentResponse | None = None
    run: AnalysisRunResponse | None = None
    job: JobResponse | None = None
    accepted: list[ImportResponse] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    failed: list[LinkImportFailure] = Field(default_factory=list)
    association_failures: list["LinkImportAssociationFailure"] = Field(default_factory=list)


class HistoryEntryResponse(BaseModel):
    content: ContentResponse
    run: AnalysisRunResponse
    job: JobResponse


class TagResponse(BaseModel):
    id: str
    name: str
    user_id: str = "local"
    content_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TagCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class TagUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class TagSuggestionResponse(BaseModel):
    name: str
    confidence: float = Field(ge=0, le=1)


class ImportBatchMemberResponse(BaseModel):
    content: ContentResponse | None = None
    job: JobResponse


class ImportBatchResponse(BaseModel):
    id: str
    name: str
    source_type: str | None = None
    total: int
    completed: int = 0
    failed: int = 0
    cancelled: int = 0
    queued: int = 0
    members: list[ImportBatchMemberResponse] = Field(default_factory=list)


class ContentUpdateRequest(BaseModel):
    category: str | None = Field(default=None, min_length=1, max_length=120)
    tag_ids: list[str] | None = Field(default=None, max_length=100)
    introduction: str | None = Field(default=None, max_length=30)
    favorite: bool | None = None
    favorite_folder_ids: list[str] | None = Field(default=None, max_length=50)


class IntroductionBackfillStartRequest(BaseModel):
    content_ids: list[str] = Field(default_factory=list)


class IntroductionBackfillPreviewResponse(BaseModel):
    eligible_count: int = 0
    no_summary_count: int = 0
    content_ids: list[str] = Field(default_factory=list)


class IntroductionBackfillItemResponse(BaseModel):
    content_id: str
    status: Literal["pending", "succeeded", "skipped", "failed"]
    message: str | None = None
    introduction: str | None = None


class IntroductionBackfillResponse(BaseModel):
    run_id: str
    status: Literal["queued", "running", "completed"]
    total: int = 0
    completed: int = 0
    succeeded: int = 0
    skipped: int = 0
    failed: int = 0
    failed_ids: list[str] = Field(default_factory=list)
    items: list[IntroductionBackfillItemResponse] = Field(default_factory=list)


class ContentBatchRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=200)
    action: Literal["move", "delete", "restore"]
    category: str | None = Field(default=None, min_length=1, max_length=120)


class ContentBatchOrganizeRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=200)
    operation: Literal["add_tag", "remove_tag", "add_folder", "remove_folder"]
    tag_id: str | None = Field(default=None, max_length=80)
    folder_ids: list[str] = Field(default_factory=list, max_length=50)


class ContentBatchOrganizeResponse(BaseModel):
    operation: str
    succeeded: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    failed: list[dict[str, str]] = Field(default_factory=list)


class CategoryResponse(BaseModel):
    name: str


class FavoriteFolderCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    parent_id: str | None = Field(default=None, max_length=80)


class FavoriteFolderUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    parent_id: str | None = Field(default=None, max_length=80)


class FavoriteFolderResponse(BaseModel):
    id: str
    name: str
    parent_id: str | None = None
    content_count: int = 0
    is_system: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ContentExportRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=200)
    format: Literal["markdown", "text", "subtitle", "json"] = "markdown"


class EvidenceResponse(BaseModel):
    ordinal: int
    start_seconds: float | None = None
    end_seconds: float | None = None
    text: str
    source_kind: str | None = None
    location_kind: Literal["timestamp", "detail_only"] = "detail_only"


class SummaryVersionResponse(BaseModel):
    id: str
    content_id: str
    version_number: int
    parent_version_id: str | None = None
    origin: Literal["original", "partial", "edited"]
    template: str
    chapter_title: str | None = None
    source_start_seconds: float | None = None
    source_end_seconds: float | None = None
    markdown: str
    summary_strength: SummaryStrength | None = None
    summary_style: str | None = None
    material_level: Literal["M0", "M1", "M2"] | None = None
    source_version: str | None = None
    source_scope: dict[str, Any] | None = None
    processed_source_refs: list[str] | None = None
    expected_source_refs: list[str] | None = None
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    created_at: datetime


class AskScopeRequest(BaseModel):
    kind: Literal["all", "favorites", "selected"] = "all"
    material_scope: Literal["full", "summaries"] = "full"
    content_ids: list[str] = Field(default_factory=list, max_length=5000)
    tag_ids: list[str] = Field(default_factory=list, max_length=100)
    favorite_folder_ids: list[str] = Field(default_factory=list, max_length=100)


class AskSessionCreateRequest(BaseModel):
    scope: AskScopeRequest = Field(default_factory=AskScopeRequest)
    title: str | None = Field(default=None, max_length=200)


class AskQueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=5000)
    session_id: str | None = Field(default=None, max_length=80)
    confirmed_scope: AskScopeRequest | None = None


class AskFeedbackRequest(BaseModel):
    query_id: str = Field(min_length=1, max_length=80)
    content_id: str = Field(min_length=1, max_length=80)
    helpful: bool
    detail_tag_ids: list[str] = Field(default_factory=list, max_length=10)


class DeveloperTagReviewRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str | None = Field(default=None, max_length=300)


class AskChunkingBackfillRequest(BaseModel):
    content_ids: list[str] = Field(min_length=1, max_length=5)


class AskSettingsUpdateRequest(BaseModel):
    provider: str = Field(default="openai-compatible", min_length=1, max_length=80)
    api_url: str = Field(default="", max_length=1000)
    api_mode: SummaryApiMode = "chat_completions"
    model: str = Field(default="", max_length=200)
    api_key: str | None = Field(default=None, max_length=500)
    reuse_summary_config: bool = False


class AskSettingsResponse(BaseModel):
    provider: str
    api_url: str | None = None
    api_mode: SummaryApiMode = "chat_completions"
    model: str | None = None
    configured: bool = False
    api_key_configured: bool = False
    reuse_summary_config: bool = False


class AskQueryAcceptedResponse(BaseModel):
    session_id: str
    query_id: str
    status: str


class AskFeedbackResponse(BaseModel):
    saved: bool
    created_at: datetime


class SummaryFeedbackResponse(BaseModel):
    id: str
    content_id: str
    version_id: str | None = None
    category: Literal["accurate", "omission", "poor_wording"]
    note: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class PartialSummaryRequest(BaseModel):
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    chapter_title: str | None = Field(default=None, max_length=200)
    template: str = "general"


class SummaryVersionUpdateRequest(BaseModel):
    markdown: str = Field(min_length=1, max_length=500000)


class SummaryFeedbackRequest(BaseModel):
    version_id: str | None = None
    category: Literal["accurate", "omission", "poor_wording"]
    note: str | None = Field(default=None, max_length=2000)


class AppMetaResponse(BaseModel):
    version: str
    api_contract_version: str
    changelog: list[dict[str, str]]
    known_issues: list[str]
    browser_validation: str = "blocked"


class DataGovernanceResponse(BaseModel):
    archive_root: str
    source_retention_days: int
    cache_retention_days: int
    candidate_count: int
    candidate_bytes: int
    by_kind: dict[str, int]
    trash_root: str


class DataGovernanceUpdateRequest(BaseModel):
    source_retention_days: int = Field(default=30, ge=1, le=3650)
    cache_retention_days: int = Field(default=7, ge=1, le=3650)


class CleanupRequest(BaseModel):
    execute: bool = False


class CleanupResponse(BaseModel):
    execute: bool
    candidate_count: int
    candidate_bytes: int
    moved: list[str] = Field(default_factory=list)
    trash_root: str


class BackupCreateResponse(BaseModel):
    path: str
    file_count: int
    redacted_settings: list[str] = Field(default_factory=list)


class BackupRestoreRequest(BaseModel):
    path: str = Field(min_length=1, max_length=2000)


class BackupRestoreResponse(BaseModel):
    restored_content_count: int
    restored_archive_files: int
    skipped_secrets: list[str] = Field(default_factory=list)
    ask_index_backfill: dict[str, int] = Field(default_factory=dict)
    ask_index_coverage: dict[str, int] = Field(default_factory=dict)
    ask_index_vector_coverage: dict[str, Any] = Field(default_factory=dict)


class DiagnosticResponse(BaseModel):
    job_id: str
    content_id: str
    app_version: str
    state: str
    checkpoint: str | None = None
    progress: int
    attempt: int
    error_code: str | None = None
    error_stage: str
    error_category: str
    recovery_action: str
    recovery_suggestion: str
    context: dict[str, Any] = Field(default_factory=dict)
    events: list[TaskEventResponse] = Field(default_factory=list)


class TaskFeedbackRequest(BaseModel):
    category: Literal["accuracy", "missing", "bug", "other"]
    note: str | None = Field(default=None, max_length=2000)


class TaskFeedbackResponse(BaseModel):
    id: str
    job_id: str
    content_id: str
    category: Literal["accuracy", "missing", "bug", "other"]
    note: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class SummaryVersionCompareResponse(BaseModel):
    left: SummaryVersionResponse
    right: SummaryVersionResponse
    diff: str

class AnalysisResultResponse(BaseModel):
    content: ContentResponse
    run: AnalysisRunResponse
    job: JobResponse
    archive_path: str
    markdown: str
    record: dict[str, Any]
    evidence: list[EvidenceResponse] = Field(default_factory=list)
    versions: list[SummaryVersionResponse] = Field(default_factory=list)
    feedback: list[SummaryFeedbackResponse] = Field(default_factory=list)
    tag_suggestions: list[TagSuggestionResponse] = Field(default_factory=list)

class SummarySkillResponse(BaseModel):
    path: str
    name: str
    sha256: str
    size: int


class SummarySkillContentResponse(SummarySkillResponse):
    content: str


class SummaryConnectionTestRequest(BaseModel):
    summary_engine: Literal["openai-compatible"] = "openai-compatible"
    summary_provider: str | None = Field(default=None, max_length=80)
    summary_api_url: str | None = Field(default=None, max_length=1000)
    summary_api_key: str | None = Field(default=None, max_length=500)
    summary_model: str | None = Field(default=None, max_length=200)
    summary_api_mode: SummaryApiMode | None = None


class SummaryConnectionTestResponse(BaseModel):
    ok: bool
    message: str
    validation_token: str | None = None


class SummaryModelsRequest(BaseModel):
    summary_engine: Literal["openai-compatible"] = "openai-compatible"
    summary_provider: str | None = Field(default=None, max_length=80)
    summary_api_url: str | None = Field(default=None, max_length=1000)
    summary_api_key: str | None = Field(default=None, max_length=500)
    summary_api_mode: SummaryApiMode | None = None


class SummaryModelsResponse(BaseModel):
    ok: bool
    message: str
    models: list[str] = Field(default_factory=list)
    models_supported: bool = True


class AsrConnectionTestRequest(BaseModel):
    # ``provider`` is the public ASR endpoint contract.  Keep accepting the
    # prefixed spelling used by the settings form while clients migrate.
    provider: str | None = Field(default=None, max_length=80)
    asr_provider: str | None = Field(default=None, max_length=80)
    asr_api_url: str | None = Field(default=None, max_length=500)
    asr_api_key: str | None = Field(default=None, max_length=500)
    asr_model: str | None = Field(default=None, max_length=200)


class AsrConnectionTestResponse(BaseModel):
    ok: bool
    message: str


class AsrModelsRequest(BaseModel):
    # See ``AsrConnectionTestRequest.provider`` for the compatibility note.
    provider: str | None = Field(default=None, max_length=80)
    asr_provider: str | None = Field(default=None, max_length=80)
    asr_api_url: str | None = Field(default=None, max_length=500)
    asr_api_key: str | None = Field(default=None, max_length=500)


class AsrModelsResponse(BaseModel):
    ok: bool
    message: str
    models: list[str] = Field(default_factory=list)
    models_supported: bool = True


class SettingsResponse(BaseModel):
    archive_root: str
    default_model: str = "gpt-4o-mini"
    external_ai_configured: bool = False
    summary_engine: Literal["openai-compatible"] = "openai-compatible"
    summary_provider: str = "openai-compatible"
    summary_api_url: str | None = None
    summary_api_mode: SummaryApiMode = "chat_completions"
    summary_model: str | None = None
    summary_configured: bool = False
    summary_api_key_configured: bool = False
    summary_prompt: str = ""
    summary_prompt_configured: bool = False
    summary_prompt_version: str = ""
    summary_prompt_hash: str = ""
    summary_skill_path: str | None = None
    summary_skill_name: str | None = None
    summary_skill_hash: str | None = None
    summary_skill_error: str | None = None
    summary_skills_root: str = ""
    summary_skill_options: list[SummarySkillResponse] = Field(default_factory=list)
    bilibili_browser: str | None = None
    bilibili_browser_profile: str | None = None
    asr_configured: bool = False
    asr_engine: Literal["cloud", "local"] = "cloud"
    asr_provider: str | None = None
    bilibili_connected: bool = False
    asr_api_url: str | None = None
    asr_model: str | None = None
    asr_cloud_configured: bool = False
    asr_cloud_api_url: str | None = None
    asr_cloud_model: str | None = None
    asr_local_configured: bool = False
    asr_local_model: str | None = None
    task_concurrency: int = Field(default=1, ge=1, le=4)
    ai_tag_recommendation_enabled: bool = False
    enable_ai_ask: bool = True
    ai_ask_cloud_configured: bool = False


class SettingsUpdateRequest(BaseModel):
    archive_root: str | None = Field(default=None, max_length=1000)
    summary_engine: Literal["openai-compatible"] | None = None
    summary_provider: str | None = Field(default=None, max_length=80)
    summary_api_url: str | None = Field(default=None, max_length=1000)
    summary_api_mode: SummaryApiMode | None = None
    summary_api_key: str | None = Field(default=None, max_length=500)
    summary_validation_token: str | None = Field(default=None, max_length=256)
    summary_model: str | None = Field(default=None, max_length=200)
    summary_prompt: str | None = Field(default=None, max_length=50000)
    summary_skill_path: str | None = Field(default=None, max_length=500)
    summary_skills_root: str | None = Field(default=None, max_length=1000)
    bilibili_browser: Literal["chrome", "edge", "firefox"] | None = None
    bilibili_browser_profile: str | None = Field(default=None, max_length=200)
    asr_engine: Literal["cloud", "local"] | None = None
    asr_provider: str | None = Field(default=None, max_length=80)
    asr_api_url: str | None = Field(default=None, max_length=500)
    asr_api_key: str | None = Field(default=None, max_length=500)
    asr_model: str | None = Field(default=None, max_length=200)
    asr_local_model: str | None = Field(default=None, max_length=200)
    copy_summary_key: bool = False
    # R4：显式清除密钥时同步清除该 provider 已选模型；留空保存不触发。
    clear_secret_provider: Literal["summary", "asr"] | None = None
    task_concurrency: int | None = Field(default=None, ge=1, le=4)
    ai_tag_recommendation_enabled: bool | None = None
    enable_ai_ask: bool | None = None
    ai_ask_siliconflow_api_key: str | None = Field(default=None, max_length=500)

class LocalAsrModelCandidateResponse(BaseModel):
    id: str
    label: str
    repo_id: str = ""
    size: str = ""
    path: str
    size_bytes: int = 0
    validation_status: str = "ready"
    message: str = ""
    missing_files: list[str] = Field(default_factory=list)


class LocalAsrModelResponse(BaseModel):
    id: str
    label: str
    repo_id: str
    size: str
    languages: str
    description: str
    installed: bool = False
    model_ready: bool = False
    usable: bool = False
    status: str = "available"
    validation_status: str = "not_found"
    compatibility_status: str = "unknown"
    path: str | None = None
    error: str | None = None
    size_bytes: int = 0
    memory_required_mb: int = 0
    speed: str = "未测量"
    quality: str = "未标定"
    device_requirements: str = "CPU 可运行"
    progress: int = Field(default=0, ge=0, le=100)
    downloaded_bytes: int = 0
    total_bytes: int = 0
    progress_message: str | None = None
    checksum: str | None = None
    imported: bool = False
    retryable: bool = False
    trash_path: str | None = None
    update_status: str | None = None
    update_available: bool = False
    update_error: str | None = None
    remote_revision: str | None = None
    local_revision: str | None = None
    selection_required: bool = False
    candidates: list[LocalAsrModelCandidateResponse] = Field(default_factory=list)
    scan_scope: str | None = None


class LocalAsrModelsResponse(BaseModel):
    model_root: str
    runtime_available: bool
    runtime_status: str = "unknown"
    runtime_installing: bool = False
    runtime_install_progress: int = 0
    runtime_install_message: str = ""
    runtime_install_error: str | None = None
    runtime_install_command: str | None = None
    models: list[LocalAsrModelResponse]


class LocalAsrRuntimeInstallResponse(BaseModel):
    runtime_available: bool
    status: str
    progress: int = 0
    message: str = ""
    error: str | None = None
    command: str


class LocalAsrModelPathRequest(BaseModel):
    path: str = Field(min_length=1, max_length=2000)
    model_id: str | None = Field(default=None, max_length=81)


class LocalAsrModelImportRequest(LocalAsrModelPathRequest):
    overwrite: bool = False
    move_source: bool = False

class PlatformConnectionResponse(BaseModel):
    platform: str
    display_name: str
    status: str
    auth_type: str
    account_label: str | None = None
    browser: str | None = None
    browser_profile: str | None = None
    login_url: str | None = None
    last_checked_at: datetime | None = None
    last_connected_at: datetime | None = None
    message: str | None = None
    supported: bool = True


class PlatformConnectionsResponse(BaseModel):
    connections: list[PlatformConnectionResponse]

class BilibiliQrCodeResponse(BaseModel):
    qrcode_key: str
    login_url: str
    qrcode_svg: str
    expires_in: int


class BilibiliQrCodePollRequest(BaseModel):
    qrcode_key: str = Field(min_length=1, max_length=200)


class PlatformConnectionConnectRequest(BaseModel):
    browser: Literal["chrome", "edge", "firefox"] | None = None
    browser_profile: str | None = Field(default=None, max_length=200)


class PlatformBrowserLoginRequest(BaseModel):
    status: Literal[
        "NOT_CONNECTED",
        "CONNECTED",
        "EXPIRED",
        "REAUTH_REQUIRED",
        "RISK_CONTROLLED",
    ]
    message: str = Field(min_length=1, max_length=500)
    browser_profile: str | None = Field(default=None, max_length=200)


class BilibiliSpacePreviewRequest(BaseModel):
    url: str = Field(max_length=2000)


class SpaceVideoCandidate(BaseModel):
    candidate_id: str | None = None
    bvid: str
    title: str
    url: str
    duration_seconds: float | None = None
    published_at: str | None = None
    thumbnail_url: str | None = None
    duplicate_status: Literal["new", "summarized", "processing", "failed"] = "new"
    existing_content_id: str | None = None
    selectable: bool = True
    page_count: int | None = None
    imported_page_count: int = 0
    part_statuses: list[Literal["new", "summarized", "processing", "failed"]] = Field(
        default_factory=list
    )


class BilibiliFavoriteFolderResponse(BaseModel):
    id: int
    title: str
    media_count: int


class BilibiliSpacePreviewResponse(BaseModel):
    mid: int
    up_name: str
    total: int
    candidates: list[SpaceVideoCandidate]


class CreatorScanRequest(BaseModel):
    url: str = Field(max_length=2000)
    refresh: bool = False


class CreatorScanError(BaseModel):
    code: Literal[
        "EMPTY_INPUT",
        "INVALID_URL",
        "NOT_BILIBILI_URL",
        "NOT_CREATOR_URL",
        "CREATOR_NOT_FOUND",
        "CREATOR_BLOCKED",
        "ACCESS_RESTRICTED",
        "NO_PUBLIC_VIDEOS",
        "PLATFORM_RISK_CONTROL",
        "UPSTREAM_TIMEOUT",
        "UPSTREAM_INVALID_RESPONSE",
        "SCAN_CANCELLED",
    ]
    user_message: str
    retryable: bool = False
    suggested_action: Literal[
        "edit_url",
        "open_single_import",
        "login",
        "retry",
        "open_source",
        "none",
    ] = "none"
    upstream_code: int | str | None = None


class CreatorScanAcceptedResponse(BaseModel):
    scan_id: str
    status: Literal["queued", "running", "completed"]
    poll_after_ms: int = 500


class CreatorScanResponse(BaseModel):
    scan_id: str
    url: str
    status: Literal[
        "queued",
        "running",
        "completed",
        "partial",
        "failed",
        "cancelled",
    ]
    mid: int | None = None
    source_type: Literal["creator", "favorite", "watchlater", "collection"] = "creator"
    up_name: str | None = None
    total: int | None = None
    fetched_count: int = 0
    skipped_count: int = 0
    candidates: list[SpaceVideoCandidate] = Field(default_factory=list)
    error: CreatorScanError | None = None
    started_at: str | None = None
    completed_at: str | None = None


class CreatorBatchRequest(BaseModel):
    scan_id: str = Field(min_length=1, max_length=80)
    candidate_ids: list[str] = Field(min_length=1, max_length=2000)
    summary_mode: Literal["individual", "aggregate", "individual_and_aggregate"] = "individual"
    summary_template: str = "general"
    summary_style: Literal["general", "course_notes", "academic", "tutorial", "sharing", "task_oriented", "business", "meeting_minutes"] | None = None
    duplicate_action: Literal["reuse", "regenerate"] = "regenerate"


class ScanImportRequest(BaseModel):
    scan_id: str = Field(min_length=1, max_length=80)
    candidate_ids: list[str] = Field(min_length=1)
    summary_style: Literal["general", "course_notes", "academic", "tutorial", "sharing", "task_oriented", "business", "meeting_minutes"] | None = None
    strength: SummaryStrength = SummaryStrength.STANDARD
    duplicate_action: Literal["reuse", "regenerate"] = "reuse"
    favorite_folder_ids: list[str] = Field(default_factory=list, max_length=50)
    tag_ids: list[str] = Field(default_factory=list, max_length=100)


class LinksImportRequest(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=50)
    model: str | None = Field(default=None, min_length=1)
    strength: SummaryStrength = SummaryStrength.STANDARD
    summary_template: str = "general"
    summary_style: Literal["general", "course_notes", "academic", "tutorial", "sharing", "task_oriented", "business", "meeting_minutes"] | None = None
    duplicate_action: Literal["reuse", "overwrite", "regenerate"] = "reuse"
    language: str | None = None
    max_chunk_tokens: int = Field(default=800, ge=32, le=32000)
    priority: int = Field(default=0, ge=-10, le=10)


class LinkImportFailure(BaseModel):
    url: str
    reason: str


class LinkImportAssociationFailure(BaseModel):
    """A created task whose requested folder association can be retried alone."""

    content: ContentResponse
    run: AnalysisRunResponse
    job: JobResponse
    folder_ids: list[str] = Field(default_factory=list, max_length=50)
    reason: str


class LinksImportResponse(BaseModel):
    accepted: list[ImportResponse]
    skipped: list[str]
    failed: list[LinkImportFailure]
