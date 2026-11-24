"""FastAPI application factory for the desktop sidecar."""

from __future__ import annotations

import difflib
import hashlib
import io
import json
import logging
import re
import secrets
import shutil
import subprocess
import sys
import webbrowser
from concurrent.futures import Future, ThreadPoolExecutor
from time import monotonic
import zipfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Lock, RLock, Thread, current_thread
from urllib.parse import parse_qs, urlparse, urlsplit, urlunsplit

from fastapi import BackgroundTasks, Body, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.archive.schema import render_markdown
from app.adapters.asr.local import (
    LocalAsrError,
    LocalAsrModelCandidate,
    check_local_model_update,
    discover_local_asr_models,
    download_local_asr_model,
    get_local_model_definition,
    import_local_asr_model,
    inspect_local_asr_model,
    is_local_model_ready,
    list_local_asr_model_ids,
    local_asr_download_available,
    local_asr_install_hint,
    local_asr_model_info,
    local_asr_runtime_available,
    local_model_path,
    remove_local_asr_model,
    validate_local_model,
)
from app.adapters.asr.openai_compatible import (
    AsrModelsUnavailable,
    AsrProviderError,
    DEFAULT_API_URL as DEFAULT_ASR_API_URL,
    DEFAULT_MODEL as DEFAULT_ASR_MODEL,
    DEFAULT_TIMEOUT_SECONDS as DEFAULT_ASR_TIMEOUT_SECONDS,
    OpenAICompatibleTranscriber,
    TranscriptionSettings,
)
from app.adapters.sources.bilibili import (
    enumerate_favorite_folders,
    enumerate_favorite_videos,
    enumerate_season_videos,
    enumerate_space_videos,
    enumerate_watchlater_videos,
    fetch_up_card,
    generate_bilibili_qr_code,
    parse_favorite_id,
    parse_season_id,
    parse_space_mid,
    poll_bilibili_qr_code,
    is_watchlater_url,
)
from app.adapters.sources.classify import object_label
from app.adapters.sources.link import (
    LinkImportError,
    _is_collection_url,
    classify_source_type,
    detect_platform,
    prepare_link_import,
    prepare_link_imports,
    preview_link_import,
)
from app.adapters.sources.local import LocalImportError, prepare_local_import
from app.adapters.sources.xiaohongshu import XiaohongshuSourceError, prepare_xhs_note
from app.adapters.sources.zhihu import ZhihuSourceError, prepare_zhihu_text
from app.adapters.summary.openai_compatible import (
    DEFAULT_SUMMARY_API_URL,
    DEFAULT_SUMMARY_MODEL,
    DEFAULT_SUMMARY_TIMEOUT_SECONDS,
    OpenAICompatibleSummarizer,
    SummaryModelsUnavailable,
    SummaryProviderError,
    SummarySettings,
    api_key_fingerprint,
    normalize_summary_provider,
    resolve_summary_api_mode,
    summary_endpoint,
)
from app.api.schemas import (
    AnalysisResultResponse,
    AskFeedbackRequest,
    AskFeedbackResponse,
    DeveloperTagReviewRequest,
    AskChunkingBackfillRequest,
    AskQueryAcceptedResponse,
    AskQueryRequest,
    AskScopeRequest,
    AskSessionCreateRequest,
    AskSettingsResponse,
    AskSettingsUpdateRequest,
    AnalysisRunCreatedResponse,
    AnalysisRunCreateRequest,
    AnalysisRunResponse,
    AppMetaResponse,
    AsrConnectionTestRequest,
    AsrConnectionTestResponse,
    AsrModelsRequest,
    AsrModelsResponse,
    BackupCreateResponse,
    BackupRestoreRequest,
    BackupRestoreResponse,
    BilibiliQrCodePollRequest,
    BilibiliQrCodeResponse,
    BilibiliFavoriteFolderResponse,
    BilibiliSpacePreviewRequest,
    BilibiliSpacePreviewResponse,
    CategoryResponse,
    CleanupRequest,
    CleanupResponse,
    ContentBatchRequest,
    ContentBatchOrganizeRequest,
    ContentBatchOrganizeResponse,
    ContentCreateRequest,
    ContentExportRequest,
    ContentResponse,
    ContentUpdateRequest,
    CreatorScanAcceptedResponse,
    CreatorScanError,
    CreatorScanRequest,
    CreatorScanResponse,
    DataGovernanceResponse,
    DataGovernanceUpdateRequest,
    DiagnosticResponse,
    DuplicateCheckItem,
    DuplicateCheckRequest,
    DuplicateCheckResponse,
    EnvironmentCheckResponse,
    EvidenceResponse,
    FavoriteFolderCreateRequest,
    FavoriteFolderResponse,
    ImportBatchMemberResponse,
    ImportBatchResponse,
    FavoriteFolderUpdateRequest,
    HealthResponse,
    HistoryEntryResponse,
    ImportResponse,
    LinkImportAssociationFailure,
    IntroductionBackfillItemResponse,
    IntroductionBackfillPreviewResponse,
    IntroductionBackfillResponse,
    IntroductionBackfillStartRequest,
    JobResponse,
    JobPriorityUpdateRequest,
    LinkImportFailure,
    LinkImportRequest,
    LinkImportResponse,
    LinkQueryConfirmRequest,
    LinkQueryItemResponse,
    LinkQueryRequest,
    LinkQueryResponse,
    LinksImportRequest,
    LinksImportResponse,
    LocalAsrModelCandidateResponse,
    LocalAsrModelImportRequest,
    LocalAsrModelPathRequest,
    LocalAsrModelResponse,
    LocalAsrModelsResponse,
    LocalAsrRuntimeInstallResponse,
    LocalImportRequest,
    LocalImportResponse,
    OpenUrlRequest,
    PartialSummaryRequest,
    PlatformConnectionConnectRequest,
    PlatformBrowserLoginRequest,
    PlatformConnectionResponse,
    PlatformConnectionsResponse,
    SettingsResponse,
    SettingsUpdateRequest,
    SourceCapabilitiesResponse,
    SourceCapabilityResponse,
    SourceProbeRequest,
    SourceProbeResponse,
    ScanImportRequest,
    SpaceVideoCandidate,
    ResummarizeRequest,
    SummaryConnectionTestRequest,
    SummaryConnectionTestResponse,
    SummaryModelsRequest,
    SummaryModelsResponse,
    SummaryFeedbackRequest,
    SummaryFeedbackResponse,
    SummarySkillContentResponse,
    SummarySkillResponse,
    SummaryVersionCompareResponse,
    SummaryVersionResponse,
    SummaryVersionUpdateRequest,
    TagCreateRequest,
    TagResponse,
    TagSuggestionResponse,
    TagUpdateRequest,
    QueueReorderRequest,
    QueueMoveRequest,
    QueueSwitchRequest,
    TaskEventResponse,
    TaskFeedbackRequest,
    TaskFeedbackResponse,
    TaskPreflightRequest,
    TaskPreflightResponse,
)
from app.db.store import (
    ContentNotFoundError,
    FavoriteFolder,
    FavoriteFolderNotFoundError,
    HistoryEntry,
    PlatformConnection,
    SQLiteStore,
    TagNotFoundError,
    _bilibili_source_identity,
)
from app.db.rag_store import RagStore
from app.domain.jobs import InvalidTransitionError, JobState, stable_checkpoint_for
from app.domain.models import AnalysisSettings, ContentKind, SourcePlatform, SummaryStrength, new_id
from app.adapters.sources.prepared import PreparedSource
from app.knowledge.transcript import transcript_to_dict
from app.knowledge.ask_index import (
    AskIndex,
    BOUNDARY_WINDOW_UTF8_BYTES,
    MAX_BOUNDARY_INPUT_BYTES_PER_CALL,
    MAX_BOUNDARY_OUTPUT_TOKENS,
)
from app.knowledge.rag import RagService, classification_source_version
from app.knowledge.siliconflow_retrieval import (
    AskEmbeddingUnavailableError,
    EMBEDDING_MODEL,
    RERANK_MODEL,
    SiliconFlowRetrieval,
)
from app.knowledge.prompts import DEFAULT_SUMMARY_PROMPT, prompt_hash, prompt_version
from app.knowledge.source_map import map_transcript_segments
from app.knowledge.skills import SkillFileError, list_skill_documents, load_skill_document
from app.knowledge.templates import (
    DEFAULT_SUMMARY_TEMPLATE,
    SUMMARY_STYLES,
    get_summary_style,
    get_summary_template,
)
from app.logging_config import configure_logging, resolve_log_dir
from app.meta import API_CONTRACT_VERSION, APP_VERSION, CHANGELOG, KNOWN_ISSUES
from app.platforms.connections import (
    CHECKING,
    CONNECTED,
    EXPIRED,
    NOT_CONNECTED,
    PLATFORM_DEFINITIONS,
    REAUTH_REQUIRED,
    RISK_CONTROLLED,
    TEMPORARY_ERROR,
    UNSUPPORTED,
    get_platform_definition,
    probe_platform,
)
from app.platforms.secrets import SecretStorageError
from app.workflows.analyze import AnalysisWorkflow, cleanup_temporary_audio
from app.workflows.diagnostics import (
    build_diagnostic_report,
    recovery_guidance,
    sanitize_context,
)
from app.workflows.governance import (
    cleanup_retention,
    create_backup,
    restore_backup,
    retention_report,
)
from app.workflows.preflight import environment_report, task_preflight
from app.workflows.queue import LocalJobQueue

UI_DIRECTORY = Path(__file__).resolve().parents[1] / "ui"
LOCAL_ASR_MODEL_CLEARED = "__cleared__"
SUMMARY_ENGINE_OPENAI = "openai-compatible"
_DEFAULT_SINGLE_LINK_PREPARER = prepare_link_import
logger = logging.getLogger(__name__)


class SummaryConfigurationError(ValueError):
    """Raised when the selected summary configuration cannot be executed."""


SUMMARY_VALIDATION_TOKEN_TTL_SECONDS = 5 * 60
LINK_QUERY_TTL_SECONDS = 60 * 60
LINK_QUERY_DEADLINE_SECONDS = 180
CREATOR_SCAN_MAX_PAGES = 100
CREATOR_SCAN_DEADLINE_SECONDS = 900
CREATOR_SCAN_PAGE_INTERVAL_SECONDS = 1.2
_RUNNING_JOB_STATES = frozenset({
    JobState.ACQUIRING,
    JobState.EXTRACTING,
    JobState.TRANSCRIBING,
    JobState.CHUNKING,
    JobState.SUMMARIZING,
    JobState.ARCHIVING,
    JobState.INDEXING,
})
_STABLE_STAGE_BY_CHECKPOINT = {
    "source_ready": "acquiring",
    "text_loaded": "extracting",
    "transcript_ready": "transcribing",
    "chunks_ready": "chunking",
    "summary_ready": "summarizing",
    "indexed": "indexing",
}
_RESUME_STAGE_BY_CHECKPOINT = {
    None: "acquiring",
    "source_ready": "extracting",
    "text_loaded": "transcribing",
    "transcript_ready": "chunking",
    "chunks_ready": "summarizing",
    "summary_ready": "archiving",
    "indexed": None,
}


def create_app(
    database_url: str | None = None,
    archive_root: str | Path | None = None,
    skills_root: str | Path | None = None,
) -> FastAPI:
    database_url = database_url or f"sqlite:///{(Path(__file__).resolve().parents[5] / 'local' / 'knowledge.db').as_posix()}"
    store = SQLiteStore(database_url)
    configured_archive_root = (
        archive_root
        if archive_root is not None
        else store.get_setting("archive_root")
        or Path(__file__).resolve().parents[5] / "local" / "knowledge-root"
    )
    resolved_archive_root = Path(configured_archive_root).expanduser().resolve()
    # Keep ASR model files under the product's explicit local data directory;
    # the process working directory must not decide where 1.5 GB models live.
    asr_model_root = (Path(__file__).resolve().parents[5] / "local" / "asr-models").resolve()
    default_skills_root = Path(__file__).resolve().parents[6] / "skills"
    resolved_skills_root = (
        Path(skills_root).expanduser().resolve()
        if skills_root is not None
        else Path(
            store.get_setting("summary_skills_root") or default_skills_root
        ).expanduser().resolve()
    )
    workflow = AnalysisWorkflow(
        store,
        resolved_archive_root,
        asr_model_root,
        resolved_skills_root,
    )
    app = FastAPI(title="Multi-source Knowledge Core", version=APP_VERSION)
    # The UI is also intentionally openable from its local file:// path. A
    # file-origin request is reported as Origin: null by browsers; allow only
    # that local origin so the direct-file fallback can reach this sidecar.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["null"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.asr_model_root = asr_model_root
    app.state.default_skills_root = (
        Path(skills_root).expanduser().resolve() if skills_root is not None else default_skills_root
    )
    app.state.skills_root = resolved_skills_root
    app.state.asr_downloads = {}
    app.state.asr_download_lock = Lock()
    app.state.asr_runtime_install = {
        "status": "idle",
        "progress": 0,
        "message": "等待安装本地 ASR 组件",
        "error": None,
    }
    app.state.asr_runtime_install_lock = Lock()
    app.state.store = store
    app.state.workflow = workflow
    # Creator scans are short-lived operational state. Candidates are not added to
    # the content library until the user explicitly selects them.
    app.state.creator_scans = {}
    app.state.creator_scan_lock = Lock()
    app.state.favorite_scans = {}
    app.state.favorite_scan_lock = Lock()
    app.state.watchlater_scans = {}
    app.state.watchlater_scan_lock = Lock()
    # Query sessions keep per-link validation results and prepared source
    # material between the explicit “查询” and “确认提交” actions.
    app.state.link_queries = {}
    app.state.link_query_lock = Lock()
    app.state.link_query_store_lock = Lock()
    app.state.link_query_workers = {}
    # QR login progress is deliberately process-local.  It must not replace
    # the durable platform connection record used by settings and imports.
    app.state.bilibili_qr_attempts = {}
    app.state.bilibili_qr_lock = RLock()
    # Summary connection tests issue short-lived, one-time credentials for the
    # subsequent settings write.  This state is scoped to the summary settings
    # flow and never contains the API key itself, only its fingerprint.
    app.state.summary_validation_tokens = {}
    app.state.summary_validation_lock = Lock()
    app.state.introduction_backfills = {}
    app.state.introduction_backfill_lock = Lock()

    def queue_limit() -> int:
        # The local worker is intentionally single-concurrency.  Keep the
        # setting readable for old databases, but do not let it change the
        # scheduling contract.
        return 1

    def revive_requeued_job(job_id: str) -> None:
        """Turn a job that yielded the worker back into a runnable job.

        Preemption parks the job as ``paused`` so the running workflow can stop
        at its checkpoint.  When its turn in the waiting line comes the queue
        revives it here, so the user never has to press start again.
        """

        try:
            job = store.get_job(job_id)
        except LookupError:
            return
        if job.state is not JobState.PAUSED:
            return
        job.metadata.pop("switch_requeue", None)
        job.transition(JobState.QUEUED)
        store.save_job(job)
        try:
            run = store.get_analysis_run(job.analysis_run_id)
        except LookupError:
            return
        run.status = "queued"
        run.updated_at = datetime.now(UTC)
        store.save_analysis_run(run)

    app.state.job_queue = LocalJobQueue(store, queue_limit, revive_requeued_job)
    app.state.ask_index = None
    app.state.ask_index_error = None
    app.state.ask_index_backfill_future = None
    app.state.ask_index_backfill_status = None
    app.state.ask_index_backfill_lock = Lock()
    ask_index_lock = Lock()
    app.state.rag_service = None
    app.state.ask_workers = set()
    app.state.ask_workers_lock = Lock()
    app.state.rag_tag_workers = {}
    app.state.rag_tag_workers_lock = Lock()
    app.state.rag_tag_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rag-tag")
    app.state.rag_tag_review_running = False
    app.state.rag_tag_review_lock = Lock()
    app.state.rag_tag_review_future = None
    rag_service_lock = Lock()

    def get_ask_index() -> AskIndex:
        index = app.state.ask_index
        if index is not None:
            return index
        with ask_index_lock:
            index = app.state.ask_index
            if index is None:
                cloud_key = store.get_secret_setting(
                    "ai_ask_siliconflow_api_key", purpose="AI 问答硅基流动 API Key"
                )
                backend = SiliconFlowRetrieval(cloud_key) if cloud_key else None
                boundary_proposer = None
                boundary_model = None
                boundary_config: dict[str, object] = {}
                try:
                    summary_snapshot = _summary_settings_snapshot(
                        store, app.state.skills_root, strict_skill=False,
                    )
                    summary_config = summary_snapshot["summary_config"]
                    summary_api_key = store.get_secret_setting(
                        "summary_api_key", purpose="总结模型 API Key",
                    ) or ""
                    if summary_api_key:
                        summary_api_url = str(summary_config["api_url"])
                        boundary_model = str(summary_config["model"])
                        boundary_provider = str(summary_snapshot["summary_provider"])
                        boundary_api_mode = str(summary_config["api_mode"])
                        boundary_config = {
                            "boundary_provider": boundary_provider,
                            "boundary_api_mode": boundary_api_mode,
                            "boundary_endpoint_hash": hashlib.sha256(
                                summary_api_url.encode("utf-8")
                            ).hexdigest()[:16],
                        }
                        boundary_client = OpenAICompatibleSummarizer(SummarySettings(
                            api_url=summary_api_url,
                            api_key=summary_api_key,
                            model=boundary_model,
                            timeout_seconds=20,
                            api_mode=boundary_api_mode,
                            provider=boundary_provider,
                        ))
                        schema = {
                            "type": "object",
                            "properties": {
                                "ends": {
                                    "type": "array",
                                    "items": {"type": "integer", "minimum": 1},
                                    "minItems": 1,
                                },
                            },
                            "required": ["ends"],
                            "additionalProperties": False,
                        }

                        def boundary_proposer(source_kind, units, *, timeout):
                            prompt = json.dumps({
                                "task": (
                                    "根据语义把有序单元合并成紧凑、连贯的检索块。"
                                    "只返回每块最后一个单元的1起始序号；最后一个序号必须覆盖全部单元。"
                                    "不要改写或省略原文。"
                                ),
                                "source_kind": source_kind,
                                "units": [{
                                    "index": index,
                                    "ordinal": unit["ordinal"],
                                    "source_ref": unit["source_ref"],
                                    "text": unit["text"],
                                } for index, unit in enumerate(units, start=1)],
                            }, ensure_ascii=False, separators=(",", ":"))
                            return boundary_client.complete_json(
                                prompt, schema, timeout=timeout,
                                max_output_tokens=MAX_BOUNDARY_OUTPUT_TOKENS,
                                max_input_bytes=MAX_BOUNDARY_INPUT_BYTES_PER_CALL,
                            )
                    else:
                        boundary_config = {"fallback_reason": "summary_model_unconfigured"}
                except (SummaryConfigurationError, SecretStorageError, SummaryProviderError, ValueError):
                    logger.info("RAG chunk boundary model is unavailable; using size-based chunks")
                    boundary_config = {"fallback_reason": "summary_model_unconfigured"}
                if backend is None:
                    index = AskIndex(
                        store, resolved_archive_root,
                        chunk_boundary_proposer=boundary_proposer,
                        chunking_model=boundary_model,
                        chunking_config=boundary_config,
                    )
                else:
                    index = AskIndex(
                        store, resolved_archive_root, embedding_backend=backend,
                        chunk_boundary_proposer=boundary_proposer,
                        chunking_model=boundary_model,
                        chunking_config=boundary_config,
                    )
                app.state.ask_index = index
                app.state.ask_index_error = index.vector_error_message
                if index._new_profile:
                    state = {
                        "profile_id": index.profile_id,
                        "status": "not_started",
                        "manual_required": True,
                    }
                    store.set_setting(ask_index_backfill_setting, json.dumps(state))
                    app.state.ask_index_backfill_status = state
                if app.state.ask_index_error:
                    logger.error(
                        "Q&A vector capability unavailable: %s",
                        app.state.ask_index_error,
                    )
        return index

    def get_rag_service() -> RagService:
        service = app.state.rag_service
        if service is not None:
            return service
        with rag_service_lock:
            service = app.state.rag_service
            if service is None:
                service = RagService(store, get_ask_index(), rag_store=RagStore(store))
                app.state.rag_service = service
        return service

    def start_ask_worker(query_id: str) -> None:
        with app.state.ask_workers_lock:
            if query_id in app.state.ask_workers:
                raise HTTPException(status_code=409, detail="问答任务正在运行")
            app.state.ask_workers.add(query_id)

        def run() -> None:
            try:
                get_rag_service().run_query(query_id)
            finally:
                with app.state.ask_workers_lock:
                    app.state.ask_workers.discard(query_id)

        Thread(target=run, name=f"ask-{query_id}", daemon=True).start()

    def start_rag_tagging(content_id: str) -> None:
        if not store.get_secret_setting("summary_api_key", purpose="总结模型 API Key"):
            return
        with app.state.rag_tag_workers_lock:
            existing = app.state.rag_tag_workers.get(content_id)
            if existing is not None and not existing.done():
                return

        def run() -> None:
            try:
                result = get_rag_service().run_tagging(content_id)
                logger.info("RAG classification completed for %s: %s", content_id, result["status"])
            except Exception:
                logger.exception("RAG classification failed for %s", content_id)

        with app.state.rag_tag_workers_lock:
            existing = app.state.rag_tag_workers.get(content_id)
            if existing is not None and not existing.done():
                return
            future = app.state.rag_tag_executor.submit(run)
            app.state.rag_tag_workers[content_id] = future

        def clear(completed: Future) -> None:
            with app.state.rag_tag_workers_lock:
                if app.state.rag_tag_workers.get(content_id) is completed:
                    app.state.rag_tag_workers.pop(content_id, None)

        future.add_done_callback(clear)

    def start_rag_tag_review() -> None:
        with app.state.rag_tag_review_lock:
            if app.state.rag_tag_review_running:
                return
            app.state.rag_tag_review_running = True

        def run() -> None:
            try:
                result = get_rag_service().review_tag_candidates()
                logger.info("RAG tag review completed: %s", result)
            except Exception:
                logger.exception("RAG tag review failed")
            finally:
                with app.state.rag_tag_review_lock:
                    app.state.rag_tag_review_running = False

        with app.state.rag_tag_review_lock:
            app.state.rag_tag_review_future = app.state.rag_tag_executor.submit(run)

    ask_index_backfill_setting = "ask_index_backfill_state"

    def read_ask_index_backfill_state(index: AskIndex) -> dict[str, object]:
        raw = store.get_setting(ask_index_backfill_setting)
        try:
            saved = json.loads(raw) if raw else None
        except (TypeError, json.JSONDecodeError):
            saved = None
        if isinstance(saved, dict) and saved.get("profile_id") == index.profile_id:
            return saved
        return {
            "profile_id": index.profile_id,
            "status": "not_started",
            "manual_required": False,
        }

    def backfill_ask_index(profile_id: str, *, classify_after: bool) -> None:
        index = get_ask_index()
        if index.profile_id != profile_id:
            return
        state: dict[str, object] = {
            "profile_id": profile_id,
            "status": "running",
            "manual_required": False,
            "requested_at": datetime.now(UTC).isoformat(),
        }
        store.set_setting(ask_index_backfill_setting, json.dumps(state))
        app.state.ask_index_backfill_status = state
        try:
            result = index.backfill()
            text_coverage = index.coverage_snapshot()
            vector_coverage = (
                index.vector_state_coverage_snapshot() if index.vector_configured else None
            )
            failed = (
                text_coverage["failed"] > 0
                or text_coverage["pending"] > 0
                or index.vector_error_message is not None
                or (
                    vector_coverage is not None
                    and (
                        vector_coverage["failed"] > 0
                        or vector_coverage["pending"] > 0
                        or bool(vector_coverage["errors"])
                    )
                )
            )
            state = {
                **state,
                "status": "failed" if failed else "complete",
                "finished_at": datetime.now(UTC).isoformat(),
                "result": result,
            }
            store.set_setting(ask_index_backfill_setting, json.dumps(state))
            app.state.ask_index_backfill_status = state
            logger.info("Q&A source index backfill completed: %s", result)
        except Exception:
            state = {
                **state,
                "status": "failed",
                "finished_at": datetime.now(UTC).isoformat(),
                "error_code": "index_backfill_failed",
            }
            store.set_setting(ask_index_backfill_setting, json.dumps(state))
            app.state.ask_index_backfill_status = state
            logger.exception("Q&A source index backfill failed")
            return
        if classify_after:
            try:
                backfill_rag_classification()
            except Exception:
                logger.exception("RAG classification backfill failed")

    def schedule_ask_index_backfill(index: AskIndex, *, classify_after: bool) -> bool:
        with app.state.ask_index_backfill_lock:
            future = app.state.ask_index_backfill_future
            if future is not None and not future.done():
                return False
            state = {
                "profile_id": index.profile_id,
                "status": "running",
                "manual_required": False,
                "requested_at": datetime.now(UTC).isoformat(),
            }
            store.set_setting(ask_index_backfill_setting, json.dumps(state))
            app.state.ask_index_backfill_status = state
            app.state.ask_index_backfill_future = app.state.rag_tag_executor.submit(
                backfill_ask_index, index.profile_id, classify_after=classify_after,
            )
        return True

    def backfill_rag_classification() -> None:
        service = get_rag_service()
        if not service.ask_settings().get("configured") and not store.get_secret_setting(
            "summary_api_key", purpose="总结模型 API Key"
        ):
            logger.info("RAG classification backfill waiting for summary model configuration")
            return
        entries = store.list_history(archived_only=True, include_deleted=False)
        for entry in entries:
            versions = store.list_summary_versions(entry.content.id)
            version = versions[0] if versions else None
            summary = store.get_summary(entry.content.id) or ""
            material_level = version.material_level if version and version.material_level else "unknown"
            source_version = classification_source_version(
                version, summary, material_level, service.index.profile_id
            )
            coverage = service.rag_store.get_coverage(entry.content.id)
            if coverage and coverage["source_version"] == source_version and coverage["status"] in {
                "complete", "partial", "no_topics", "metadata_only"
            }:
                continue
            service.run_tagging(entry.content.id)

    def start_rag_classification_backfill() -> None:
        if store.get_secret_setting("summary_api_key", purpose="总结模型 API Key"):
            app.state.rag_tag_executor.submit(backfill_rag_classification)

    def start_ask_index_backfill() -> None:
        index = get_ask_index()
        get_rag_service()
        state = read_ask_index_backfill_state(index)
        if state.get("status") == "running":
            schedule_ask_index_backfill(index, classify_after=False)
            return
        if state.get("status") == "failed":
            logger.info("Q&A source index backfill has failed items; waiting for an explicit retry")
            return
        if state.get("manual_required") or index._new_profile:
            logger.info("Q&A index profile needs an explicit full rebuild; automatic backfill is unstarted")
            return
        coverage = index.coverage_snapshot()
        text_complete = (
            coverage["pending"] == 0
            and coverage["failed"] == 0
            and coverage["indexed"] + coverage["partial"] == coverage["total_completed"]
        )
        if state.get("status") == "complete" and text_complete:
            vector_complete = True
            if index.vector_configured:
                try:
                    vector_coverage = index.vector_state_coverage_snapshot()
                    vector_complete = (
                        vector_coverage["pending"] == 0
                        and vector_coverage["failed"] == 0
                        and not vector_coverage["errors"]
                    )
                except AskEmbeddingUnavailableError:
                    vector_complete = False
            if vector_complete:
                logger.info("Q&A source index is complete; startup backfill skipped")
                return
        if coverage["indexed"] + coverage["partial"] == 0:
            state = {
                "profile_id": index.profile_id,
                "status": "not_started",
                "manual_required": True,
            }
            store.set_setting(ask_index_backfill_setting, json.dumps(state))
            app.state.ask_index_backfill_status = state
            logger.info("Q&A index profile has no current indexed content; waiting for explicit rebuild")
            return
        schedule_ask_index_backfill(index, classify_after=True)

    app.router.add_event_handler("startup", start_ask_index_backfill)

    def close_ask_index() -> None:
        app.state.rag_tag_executor.shutdown(wait=True, cancel_futures=True)
        with app.state.rag_tag_workers_lock:
            app.state.rag_tag_workers.clear()
        index = app.state.ask_index
        if index is not None:
            index.close()

    app.router.add_event_handler("shutdown", close_ask_index)

    def acquire_scan_source(job):
        url = job.metadata["source_url"]
        run = store.get_analysis_run(job.analysis_run_id)
        _preflight_link_connection(store, url)
        page_query = parse_qs(urlsplit(url).query).get("p")
        sources = _prepare_link_sources(
            url=url, title=None, language=run.settings_snapshot.get("language"),
            bilibili_cookie=_bilibili_cookie(store),
            asr_configured=_asr_is_configured(store, app.state.asr_model_root),
            page_number=int(page_query[0]) if page_query else None,
        )
        try:
            workflow._assert_current_attempt(job)
            source = sources[0]
            store.refresh_source_metadata(
                run.content_id, title=source.title, canonical_url=source.source_url,
                author=source.author, duration_seconds=source.duration_seconds,
                thumbnail_url=source.thumbnail_url, content_hash=source.content_hash,
                acquisition_method=source.acquisition_method,
                published_at=source.published_at,
                language=source.transcript.language if source.transcript else None,
            )
            settings_data = dict(run.settings_snapshot)
            settings_data["strength"] = SummaryStrength(settings_data["strength"])
            settings = AnalysisSettings(**settings_data)
            if len(sources) > 1:
                job.metadata.update({
                    "archive_batch_name": _archive_batch_name(sources),
                    "import_batch_id": job.metadata.get("import_batch_id") or new_id("import-batch"),
                    "archive_item_number": 1, "archive_total": len(sources),
                })
            # Multi-P expansion stays inside the active acquisition task.
            # Additional parts join the same serial queue, with durable transcripts.
            for index, part in enumerate(sources[1:], start=2):
                content, _run, child = workflow.submit(
                    part, settings,
                    import_batch_id=job.metadata.get("import_batch_id"),
                    archive_group=job.metadata.get("archive_batch_name"),
                    archive_index=index if job.metadata.get("archive_batch_name") else None,
                    archive_total=len(sources),
                )
                original = store.get_content(run.content_id)
                store.update_content(
                    content.id, category=original.category,
                    tag_ids=store.tag_ids(original.id),
                    favorite_folder_ids=store.favorite_folder_ids(original.id),
                )
                if part.transcript is not None:
                    workflow._write_checkpoint(child, "transcript", transcript_to_dict(part.transcript))
                    child.metadata["resume_checkpoint"] = "transcript_ready"
                child.metadata["scan_import"] = True
                store.save_job(child)
                schedule_job(child.id, part.transcript)
            return source
        except Exception:
            for source in sources:
                _discard_temporary_audio(source)
            raise

    def run_analysis_job(job_id: str, transcript) -> None:
        try:
            workflow.run(job_id, transcript, acquire_source=acquire_scan_source)
        finally:
            try:
                job = store.get_job(job_id)
                if job.state is JobState.COMPLETED:
                    run = store.get_analysis_run(job.analysis_run_id)
                    archive_path = job.metadata.get("archive_path")
                    if isinstance(archive_path, str):
                        get_ask_index().sync_content(
                            run.content_id,
                            archive_path,
                            summary_text=store.get_summary(run.content_id),
                        )
                        start_rag_tagging(run.content_id)
                    else:
                        get_ask_index().record_failure(run.content_id, "completed_archive_missing")
            except Exception:
                logger.exception("Q&A source index sync failed after job %s", job_id)

    def schedule_job(job_id: str, transcript, *, front: bool = False) -> None:
        job = store.get_job(job_id)
        if job.state is not JobState.QUEUED:
            return
        app.state.job_queue.submit(
            job_id,
            transcript,
            run_analysis_job,
        )
        if front:
            # 用户点「开始」恢复的任务排到等待区首位，当前任务让出后立刻轮到它。
            app.state.job_queue.move_to_front(job_id)

    def cleanup_job_artifacts(job) -> None:
        """Remove task-owned checkpoints and only explicitly temporary audio."""

        workflow.discard_checkpoints(job)
        if job.metadata.get("audio_is_temp"):
            cleanup_temporary_audio(job.metadata.get("audio_path"))

    def cleanup_content_artifacts(content_id: str) -> None:
        for content_job in store.list_content_jobs(content_id):
            app.state.job_queue.remove(content_job.id)
            cleanup_job_artifacts(content_job)

    def run_introduction_backfill(run_id: str) -> None:
        with app.state.introduction_backfill_lock:
            record = app.state.introduction_backfills.get(run_id)
            if record is None:
                return
            record["status"] = "running"
            content_ids = list(record.get("content_ids") or [])
        try:
            summarizer = _introduction_summarizer(store, resolved_skills_root)
        except Exception as error:
            with app.state.introduction_backfill_lock:
                record = app.state.introduction_backfills.get(run_id)
                if record is not None:
                    for content_id in content_ids:
                        record["items"][content_id] = {
                            "status": "failed",
                            "message": str(error) or "简介生成配置不可用",
                        }
                    record["status"] = "completed"
            return

        for content_id in content_ids:
            try:
                content = store.get_content(content_id)
                if (content.introduction or "").strip():
                    item = {"status": "skipped", "message": "已有简介，未覆盖"}
                else:
                    summary = store.get_summary(content_id)
                    if not summary or not summary.strip():
                        item = {"status": "skipped", "message": "没有有效正文总结，已跳过"}
                    else:
                        introduction = summarizer.generate_introduction(
                            title=content.title,
                            summary_markdown=summary,
                        )
                        latest = store.get_content(content_id)
                        if (latest.introduction or "").strip():
                            item = {"status": "skipped", "message": "生成期间已有人工简介，未覆盖"}
                        else:
                            updated = store.update_content(
                                content_id,
                                introduction=introduction,
                            )
                            _sync_content_introduction(store, content_id, updated.introduction)
                            item = {
                                "status": "succeeded",
                                "message": "已生成并保存",
                                "introduction": updated.introduction,
                            }
            except Exception as error:
                item = {"status": "failed", "message": str(error) or "简介生成失败"}
            with app.state.introduction_backfill_lock:
                record = app.state.introduction_backfills.get(run_id)
                if record is None:
                    return
                record["items"][content_id] = item
        with app.state.introduction_backfill_lock:
            record = app.state.introduction_backfills.get(run_id)
            if record is not None:
                record["status"] = "completed"

    _LINK_QUERY_TERMINAL_ITEM_STATES = frozenset(
        {"ready", "duplicate", "failed", "timed_out"}
    )

    def _register_link_query_worker(query_id: str, worker: Thread) -> None:
        with app.state.link_query_lock:
            app.state.link_query_workers.setdefault(query_id, set()).add(worker)

    def _unregister_link_query_worker(query_id: str, worker: Thread) -> None:
        with app.state.link_query_lock:
            workers = app.state.link_query_workers.get(query_id)
            if not isinstance(workers, set):
                return
            workers.discard(worker)
            if not workers:
                app.state.link_query_workers.pop(query_id, None)

    def _start_link_query_worker(
        query_id: str,
        target,
        args: tuple[object, ...],
        name: str,
    ) -> Thread:
        worker = Thread(target=target, args=args, name=name, daemon=True)
        _register_link_query_worker(query_id, worker)
        try:
            worker.start()
        except Exception:
            _unregister_link_query_worker(query_id, worker)
            raise
        return worker

    def _cleanup_link_queries() -> None:
        now = datetime.now(UTC)
        expired: list[dict[str, object]] = []
        with app.state.link_query_lock:
            for query_id, record in list(app.state.link_queries.items()):
                created_at = record.get("created_at")
                if not isinstance(created_at, datetime):
                    continue
                if (now - created_at).total_seconds() <= LINK_QUERY_TTL_SECONDS:
                    continue
                expired.append(record)
                del app.state.link_queries[query_id]
                cancel_event = record.get("cancel_event")
                if isinstance(cancel_event, Event):
                    cancel_event.set()
                done_event = record.get("done_event")
                if isinstance(done_event, Event):
                    done_event.set()
        for record in expired:
            for item in record.get("items", {}).values():
                if isinstance(item, dict):
                    source = item.get("source")
                    if source is not None:
                        _discard_temporary_audio(source)

    def _link_query_item_response(item: dict[str, object]) -> LinkQueryItemResponse:
        source = item.get("source")
        duplicate = bool(item.get("duplicate"))
        status_value = str(item.get("status") or "failed")
        if source is not None:
            return LinkQueryItemResponse(
                item_id=str(item["item_id"]),
                input_url=str(item["input_url"]),
                source_url=source.source_url,
                platform=source.platform.value,
                kind=str(item.get("kind") or "single"),
                source_type=str(item.get("source_type") or "single"),
                status=status_value,
                title=source.title,
                author=source.author,
                thumbnail_url=source.thumbnail_url,
                duration_seconds=source.duration_seconds,
                published_at=source.published_at,
                duplicate=duplicate,
                selectable=status_value in {"ready", "duplicate"},
                reason=(
                    "内容库中已有相同来源，将以新内容导入"
                    if duplicate
                    else None
                ),
                material_hint=source.source_note,
            )
        return LinkQueryItemResponse(
            item_id=str(item["item_id"]),
            input_url=str(item["input_url"]),
            platform=item.get("platform"),
            kind=str(item.get("kind") or "unknown"),
            source_type=str(item.get("source_type") or item.get("kind") or "unknown"),
            status=status_value,
            selectable=False,
            reason=str(item.get("reason") or "链接校验失败"),
        )

    def _link_query_snapshot(record: dict[str, object]) -> LinkQueryResponse:
        items = record.get("items")
        item_records = items.values() if isinstance(items, dict) else ()
        return LinkQueryResponse(
            query_id=str(record["query_id"]),
            status=str(record.get("status") or "processing"),
            items=[
                _link_query_item_response(item)
                for item in item_records
                if isinstance(item, dict)
            ],
            deadline_at=(
                record.get("deadline_at")
                if isinstance(record.get("deadline_at"), datetime)
                else None
            ),
        )

    def _finish_link_query_if_idle(record: dict[str, object], now: datetime) -> None:
        if record.get("status") != "processing":
            return
        items = record.get("items")
        if not isinstance(items, dict) or not items:
            return
        if any(
            item.get("status") not in _LINK_QUERY_TERMINAL_ITEM_STATES
            for item in items.values()
            if isinstance(item, dict)
        ):
            return
        record["status"] = "completed"
        record["completed_at"] = now
        done_event = record.get("done_event")
        if isinstance(done_event, Event):
            done_event.set()

    def _update_link_query_item(
        query_id: str,
        item_id: str,
        changes: dict[str, object],
    ) -> bool:
        with app.state.link_query_lock:
            record = app.state.link_queries.get(query_id)
            items = record.get("items") if isinstance(record, dict) else None
            item = items.get(item_id) if isinstance(items, dict) else None
            if (
                not isinstance(record, dict)
                or record.get("status") != "processing"
                or not isinstance(item, dict)
                or item.get("status") != "pending"
            ):
                return False
            item.update(changes)
            _finish_link_query_if_idle(record, datetime.now(UTC))
            return True

    def _run_link_query_item(
        query_id: str,
        item_id: str,
        url: str,
        language: str | None,
    ) -> None:
        try:
            _run_link_query_item_body(query_id, item_id, url, language)
        finally:
            _unregister_link_query_worker(query_id, current_thread())

    def _run_link_query_item_body(
        query_id: str,
        item_id: str,
        url: str,
        language: str | None,
    ) -> None:
        with app.state.link_query_lock:
            record = app.state.link_queries.get(query_id)
            items = record.get("items") if isinstance(record, dict) else None
            item = items.get(item_id) if isinstance(items, dict) else None
            cancel_event = record.get("cancel_event") if isinstance(record, dict) else None
            if (
                not isinstance(record, dict)
                or record.get("status") != "processing"
                or not isinstance(item, dict)
                or item.get("status") != "pending"
                or (isinstance(cancel_event, Event) and cancel_event.is_set())
            ):
                return

        platform = detect_platform(url)
        sources: list[object] = []
        failure: str | None = None
        try:
            with app.state.link_query_store_lock:
                _preflight_link_connection(store, url)
                bilibili_cookie = _bilibili_cookie(store)
                asr_configured = _asr_is_configured(
                    store,
                    app.state.asr_model_root,
                )
            page_query = parse_qs(urlsplit(url).query).get("p")
            try:
                page_number = int(page_query[0]) if page_query else None
            except (TypeError, ValueError):
                page_number = None
            if page_number is not None and page_number < 1:
                page_number = None
            sources = _prepare_link_sources(
                url=url,
                title=None,
                language=language,
                bilibili_cookie=bilibili_cookie,
                asr_configured=asr_configured,
                page_number=page_number,
            )
            for source in sources:
                _require_asr_for_untitled_source(
                    store,
                    source,
                    app.state.asr_model_root,
                    configured=asr_configured,
                )
        except HTTPException as error:
            failure = str(error.detail)
        except LinkImportError as error:
            failure = str(error)
            with app.state.link_query_store_lock:
                _sync_bilibili_error_status(store, url, error)
        except Exception as error:
            logger.exception("link query failed url=%s", url)
            failure = "链接校验失败，请稍后重试"

        if failure or not sources:
            for source in sources:
                _discard_temporary_audio(source)
            _update_link_query_item(
                query_id,
                item_id,
                {
                    "status": "failed",
                    "reason": failure or "未找到可导入的内容",
                    "source": None,
                    "duplicate": False,
                },
            )
            return

        duplicate_sources: list[object] = []
        accepted_items: list[dict[str, object]] = []
        with app.state.link_query_lock:
            record = app.state.link_queries.get(query_id)
            items = record.get("items") if isinstance(record, dict) else None
            item = items.get(item_id) if isinstance(items, dict) else None
            if (
                not isinstance(record, dict)
                or record.get("status") != "processing"
                or not isinstance(item, dict)
                or item.get("status") != "pending"
            ):
                duplicate_sources = sources
            else:
                seen_source_keys = record.setdefault("seen_source_keys", set())
                for source in sources:
                    source_key = _source_identity(source)
                    if source_key is not None and source_key in seen_source_keys:
                        duplicate_sources.append(source)
                        continue
                    if source_key is not None:
                        seen_source_keys.add(source_key)
                    with app.state.link_query_store_lock:
                        duplicate = store.find_duplicate_content(
                            canonical_url=source.source_url,
                            content_hash=source.content_hash,
                        )
                    accepted_items.append(
                        {
                            "item_id": (
                                item_id
                                if not accepted_items
                                else new_id("link-query-item")
                            ),
                            "input_url": url,
                            "platform": source.platform.value,
                            "kind": "single",
                            "source_type": "single",
                            "status": "duplicate" if duplicate else "ready",
                            "source": source,
                            "duplicate": duplicate,
                        }
                    )
                if accepted_items:
                    first = accepted_items[0]
                    item.update(first)
                    for extra in accepted_items[1:]:
                        items[str(extra["item_id"])] = extra
                    _finish_link_query_if_idle(record, datetime.now(UTC))
                else:
                    # Preserve the existing batch de-duplication contract:
                    # the second URL is removed once its canonical source is
                    # known to be represented by an earlier item.
                    items.pop(item_id, None)
                    _finish_link_query_if_idle(record, datetime.now(UTC))
        for source in duplicate_sources:
            _discard_temporary_audio(source)

    def _expire_link_query(query_id: str) -> bool:
        timed_out_sources: list[object] = []
        with app.state.link_query_lock:
            record = app.state.link_queries.get(query_id)
            if not isinstance(record, dict) or record.get("status") != "processing":
                return False
            deadline_at = record.get("deadline_at")
            if not isinstance(deadline_at, datetime) or datetime.now(UTC) < deadline_at:
                return False
            items = record.get("items")
            if isinstance(items, dict):
                for item in items.values():
                    if isinstance(item, dict) and item.get("status") == "pending":
                        source = item.get("source")
                        if source is not None:
                            timed_out_sources.append(source)
                        item.update(
                            {
                                "status": "timed_out",
                                "source": None,
                                "reason": "查询超过 180 秒，请重试该链接",
                            }
                        )
            record["status"] = "timed_out"
            record["completed_at"] = datetime.now(UTC)
            cancel_event = record.get("cancel_event")
            if isinstance(cancel_event, Event):
                cancel_event.set()
            done_event = record.get("done_event")
            if isinstance(done_event, Event):
                done_event.set()
        for source in timed_out_sources:
            _discard_temporary_audio(source)
        return True

    def _watch_link_query(query_id: str) -> None:
        try:
            _watch_link_query_body(query_id)
        finally:
            _unregister_link_query_worker(query_id, current_thread())

    def _watch_link_query_body(query_id: str) -> None:
        while True:
            with app.state.link_query_lock:
                record = app.state.link_queries.get(query_id)
                if not isinstance(record, dict):
                    return
                if record.get("status") != "processing":
                    return
                deadline_at = record.get("deadline_at")
                done_event = record.get("done_event")
            if not isinstance(deadline_at, datetime):
                return
            remaining = (deadline_at - datetime.now(UTC)).total_seconds()
            if remaining <= 0:
                _expire_link_query(query_id)
                return
            if isinstance(done_event, Event) and done_event.wait(min(remaining, 1.0)):
                return

    def _cancel_link_query(query_id: str) -> LinkQueryResponse:
        with app.state.link_query_lock:
            record = app.state.link_queries.get(query_id)
            if not isinstance(record, dict):
                raise HTTPException(status_code=404, detail="link_query_expired")
            if record.get("status") == "processing":
                items = record.get("items")
                if isinstance(items, dict):
                    for item in items.values():
                        if isinstance(item, dict) and item.get("status") == "pending":
                            item.update(
                                {
                                    "status": "timed_out",
                                    "reason": "查询已取消，请重试该链接",
                                }
                            )
                record["status"] = "cancelled"
                record["completed_at"] = datetime.now(UTC)
                cancel_event = record.get("cancel_event")
                if isinstance(cancel_event, Event):
                    cancel_event.set()
                done_event = record.get("done_event")
                if isinstance(done_event, Event):
                    done_event.set()
            return _link_query_snapshot(record)

    def _shutdown_link_query_workers() -> None:
        with app.state.link_query_lock:
            workers = [
                worker
                for query_workers in app.state.link_query_workers.values()
                for worker in query_workers
            ]
            for record in app.state.link_queries.values():
                if record.get("status") == "processing":
                    record["status"] = "cancelled"
                    record["completed_at"] = datetime.now(UTC)
                    items = record.get("items")
                    if isinstance(items, dict):
                        for item in items.values():
                            if isinstance(item, dict) and item.get("status") == "pending":
                                item.update(
                                    {
                                        "status": "timed_out",
                                        "reason": "应用正在关闭，请重试该链接",
                                    }
                                )
                cancel_event = record.get("cancel_event")
                if isinstance(cancel_event, Event):
                    cancel_event.set()
                done_event = record.get("done_event")
                if isinstance(done_event, Event):
                    done_event.set()
        deadline = monotonic() + 5.0
        for worker in workers:
            if worker is current_thread():
                continue
            worker.join(max(0.0, deadline - monotonic()))

    app.router.add_event_handler("shutdown", _shutdown_link_query_workers)

    def _creator_scan_error(error: Exception, source_type: str = "creator") -> dict[str, object]:
        message = str(error).strip()
        lowered = message.lower()
        source_label = {
            "favorite": "收藏夹",
            "watchlater": "稍后再看",
            "collection": "合集",
        }.get(source_type, "UP 主主页")
        if "风控" in message or "412" in message or "-352" in message or "-799" in message:
            return CreatorScanError(
                code="PLATFORM_RISK_CONTROL",
                user_message=f"B站暂时限制了{source_label}读取，请完成登录或稍后重试。",
                retryable=True,
                suggested_action="login",
            ).model_dump()
        if "不存在" in message or "-404" in message or "啥都木有" in message:
            return CreatorScanError(
                code="CREATOR_NOT_FOUND",
                user_message=(
                    "未找到该收藏夹，链接可能已失效。"
                    if source_type == "favorite"
                    else "未找到稍后再看列表，链接可能已失效。"
                    if source_type == "watchlater"
                    else "未找到该合集，链接可能已失效。"
                    if source_type == "collection"
                    else "未找到该 UP 主，账号可能不存在或已注销。"
                ),
                suggested_action="edit_url",
            ).model_dump()
        if "封禁" in message or "blocked" in lowered or "禁言" in message:
            return CreatorScanError(
                code="CREATOR_BLOCKED",
                user_message=(
                    "该收藏夹当前不可访问，可能已失效或受平台限制。"
                    if source_type == "favorite"
                    else "该稍后再看列表当前不可访问，可能已失效或受平台限制。"
                    if source_type == "watchlater"
                    else "该合集当前不可访问，可能已失效或受平台限制。"
                    if source_type == "collection"
                    else "该账号当前不可访问，可能已被封禁或受平台限制。"
                ),
                suggested_action="open_source",
            ).model_dump()
        if "超时" in message or "timed out" in lowered or "timeout" in lowered:
            return CreatorScanError(
                code="UPSTREAM_TIMEOUT",
                user_message=f"读取 B站{source_label}超时，已保留当前扫描状态，请稍后重试。",
                retryable=True,
                suggested_action="retry",
            ).model_dump()
        if "登录" in message or "权限" in message or "访问" in message:
            return CreatorScanError(
                code="ACCESS_RESTRICTED",
                user_message=(
                    "当前登录状态无权读取该收藏夹。"
                    if source_type == "favorite"
                    else "当前登录状态无权读取稍后再看列表。"
                    if source_type == "watchlater"
                    else "当前登录状态无权读取该 UP 主的投稿列表。"
                ),
                retryable=True,
                suggested_action="login",
            ).model_dump()
        return CreatorScanError(
            code="UPSTREAM_INVALID_RESPONSE",
            user_message=f"B站返回的{source_label}数据暂时无法解析，请稍后重试。",
            retryable=True,
            suggested_action="retry",
        ).model_dump()

    def _creator_candidate(video, *, source_type: str = "creator") -> dict[str, object]:
        if source_type == "favorite":
            import_state = store.get_bilibili_video_import_state(video.bvid, video.page_count)
            duplicate_status = str(import_state["duplicate_status"])
            existing_id = import_state["existing_content_id"]
            page_count = import_state["page_count"]
            imported_page_count = import_state["imported_page_count"]
            part_statuses = import_state["part_statuses"]
        else:
            existing = store.get_content_by_url(video.url)
            if existing is None:
                duplicate_status = "new"
                existing_id = None
            elif store.get_summary(existing.id):
                duplicate_status = "summarized"
                existing_id = existing.id
            else:
                duplicate_status = "processing"
                existing_id = existing.id
            page_count = video.page_count
            imported_page_count = 0
            part_statuses = []
        return {
            "candidate_id": f"video:{video.bvid}",
            "bvid": video.bvid,
            "title": video.title or "未命名视频",
            "url": f"https://www.bilibili.com/video/{video.bvid}",
            "duration_seconds": video.duration_seconds,
            "published_at": video.published_at,
            "thumbnail_url": video.thumbnail_url,
            "duplicate_status": duplicate_status,
            "existing_content_id": existing_id,
            "selectable": duplicate_status != "processing",
            "page_count": page_count,
            "imported_page_count": imported_page_count,
            "part_statuses": part_statuses,
        }

    def _creator_scan_response(record: dict[str, object]) -> CreatorScanResponse:
        error = record.get("error")
        return CreatorScanResponse(
            scan_id=str(record["scan_id"]),
            url=str(record["url"]),
            status=str(record["status"]),
            mid=record.get("mid"),
            source_type=str(record.get("source_type") or "creator"),
            up_name=record.get("up_name"),
            total=record.get("total"),
            fetched_count=int(record.get("fetched_count") or 0),
            skipped_count=int(record.get("skipped_count") or 0),
            candidates=[SpaceVideoCandidate(**item) for item in record.get("candidates", [])],
            error=CreatorScanError(**error) if isinstance(error, dict) else None,
            started_at=record.get("started_at"),
            completed_at=record.get("completed_at"),
        )

    def _update_creator_scan(scan_id: str, **changes: object) -> bool:
        with app.state.creator_scan_lock:
            record = app.state.creator_scans.get(scan_id)
            if record is None:
                return False
            if record["cancel_event"].is_set() and changes.get("status") != "cancelled":
                return False
            record.update(changes)
            return True

    def _run_creator_scan(scan_id: str) -> None:
        with app.state.creator_scan_lock:
            record = app.state.creator_scans.get(scan_id)
            if record is None:
                return
            cancel_event = record["cancel_event"]
            if cancel_event.is_set():
                record["status"] = "cancelled"
                record["error"] = CreatorScanError(
                    code="SCAN_CANCELLED", user_message="已取消扫描，尚未创建总结任务。", suggested_action="none"
                ).model_dump()
                record["completed_at"] = datetime.now(UTC).isoformat()
                return
            record["status"] = "running"
            record["started_at"] = datetime.now(UTC).isoformat()
            mid = int(record["mid"])
            season_id = record.get("season_id")
        try:
            if season_id:
                # 合集链接只读该合集；标题与总数由合集接口自身给出，无需再取 UP 主名片。
                def _read_page(page_number: int):
                    season_videos, season_total, season_title = enumerate_season_videos(
                        mid, int(season_id), page=page_number, cookie=_bilibili_cookie(store)
                    )
                    return season_videos, season_total, season_title
            else:
                up = fetch_up_card(mid, cookie=_bilibili_cookie(store))
                _update_creator_scan(scan_id, up_name=up.name, total=up.archive_count)

                def _read_page(page_number: int):
                    space_videos, space_total = enumerate_space_videos(
                        mid, page=page_number, cookie=_bilibili_cookie(store)
                    )
                    return space_videos, space_total, None

            page = 1
            seen: set[str] = set()
            deadline = monotonic() + CREATOR_SCAN_DEADLINE_SECONDS
            while True:
                if cancel_event.is_set():
                    _update_creator_scan(
                        scan_id,
                        status="cancelled",
                        error=CreatorScanError(
                            code="SCAN_CANCELLED",
                            user_message="已取消扫描，尚未创建总结任务。",
                            suggested_action="none",
                        ).model_dump(),
                        completed_at=datetime.now(UTC).isoformat(),
                    )
                    return
                videos, total, page_title = _read_page(page)
                if page_title:
                    _update_creator_scan(scan_id, up_name=page_title)
                current_candidates = list(record.get("candidates", []))
                added = 0
                for video in videos:
                    if video.bvid in seen:
                        continue
                    seen.add(video.bvid)
                    current_candidates.append(_creator_candidate(video))
                    added += 1
                fetched_count = len(current_candidates)
                _update_creator_scan(
                    scan_id,
                    total=total,
                    candidates=current_candidates,
                    fetched_count=fetched_count,
                    skipped_count=max(int(total or 0) - fetched_count, 0),
                )
                if cancel_event.is_set():
                    _update_creator_scan(
                        scan_id,
                        status="cancelled",
                        error=CreatorScanError(
                            code="SCAN_CANCELLED",
                            user_message="已取消扫描，尚未创建总结任务。",
                            suggested_action="none",
                        ).model_dump(),
                        completed_at=datetime.now(UTC).isoformat(),
                    )
                    return
                if not videos or added == 0 or fetched_count >= total:
                    break
                if page >= CREATOR_SCAN_MAX_PAGES:
                    logger.warning(
                        "creator scan reached page cap scan_id=%s page=%s fetched=%s total=%s",
                        scan_id,
                        page,
                        fetched_count,
                        total,
                    )
                    break
                if monotonic() >= deadline:
                    logger.warning(
                        "creator scan exceeded time budget scan_id=%s page=%s fetched=%s total=%s",
                        scan_id,
                        page,
                        fetched_count,
                        total,
                    )
                    break
                page += 1
                cancel_event.wait(CREATOR_SCAN_PAGE_INTERVAL_SECONDS)
            final_error = None
            if not record.get("candidates"):
                final_error = CreatorScanError(
                    code="NO_PUBLIC_VIDEOS",
                    user_message=(
                        "该合集没有可访问的视频。"
                        if season_id
                        else "该 UP 主没有可访问的公开视频。"
                    ),
                    suggested_action="open_source",
                ).model_dump()
            _update_creator_scan(
                scan_id,
                status="completed",
                error=final_error,
                completed_at=datetime.now(UTC).isoformat(),
            )
        except LinkImportError as error:
            _update_creator_scan(
                scan_id,
                status="failed",
                error=_creator_scan_error(error, str(record.get("source_type") or "creator")),
                completed_at=datetime.now(UTC).isoformat(),
            )
        except Exception as error:
            _update_creator_scan(
                scan_id,
                status="failed",
                error=_creator_scan_error(error, str(record.get("source_type") or "creator")),
                completed_at=datetime.now(UTC).isoformat(),
            )

    def _run_favorite_scan(scan_id: str) -> None:
        with app.state.favorite_scan_lock:
            record = app.state.favorite_scans.get(scan_id)
            if record is None:
                return
            cancel_event = record["cancel_event"]
            if cancel_event.is_set():
                record.update({
                    "status": "cancelled",
                    "error": CreatorScanError(
                        code="SCAN_CANCELLED",
                        user_message="已取消扫描，尚未创建总结任务。",
                        suggested_action="none",
                    ).model_dump(),
                    "completed_at": datetime.now(UTC).isoformat(),
                })
                return
            record["status"] = "running"
            record["started_at"] = datetime.now(UTC).isoformat()
            favorite_id = int(record["favorite_id"])
        try:
            page = 1
            seen: set[str] = set()
            while True:
                videos, total, title = enumerate_favorite_videos(
                    favorite_id, page=page, cookie=_bilibili_cookie(store)
                )
                with app.state.favorite_scan_lock:
                    record = app.state.favorite_scans.get(scan_id)
                    if record is None or record["cancel_event"].is_set():
                        return
                    candidates = list(record.get("candidates", []))
                    for video in videos:
                        if video.bvid not in seen:
                            seen.add(video.bvid)
                            candidates.append(_creator_candidate(video, source_type="favorite"))
                    record.update({
                        "up_name": title,
                        "total": total,
                        "candidates": candidates,
                        "fetched_count": len(candidates),
                        "skipped_count": max(int(total or 0) - len(candidates), 0),
                    })
                if not videos or len(seen) >= total:
                    break
                page += 1
            with app.state.favorite_scan_lock:
                record = app.state.favorite_scans.get(scan_id)
                if record is None or record["cancel_event"].is_set():
                    return
                record.update({
                    "status": "completed",
                    "completed_at": datetime.now(UTC).isoformat(),
                    "error": (
                        CreatorScanError(
                            code="NO_PUBLIC_VIDEOS",
                            user_message="该收藏夹没有可访问的视频。",
                            suggested_action="open_source",
                        ).model_dump()
                        if not record.get("candidates") else None
                    ),
                })
        except Exception as error:
            with app.state.favorite_scan_lock:
                record = app.state.favorite_scans.get(scan_id)
                if record is None or record["cancel_event"].is_set():
                    return
                record.update({"status": "failed", "error": _creator_scan_error(error, "favorite"), "completed_at": datetime.now(UTC).isoformat()})

    def _run_watchlater_scan(scan_id: str) -> None:
        with app.state.watchlater_scan_lock:
            record = app.state.watchlater_scans.get(scan_id)
            if record is None:
                return
            cancel_event = record["cancel_event"]
            if cancel_event.is_set():
                record.update({
                    "status": "cancelled",
                    "error": CreatorScanError(
                        code="SCAN_CANCELLED",
                        user_message="已取消扫描，尚未创建总结任务。",
                        suggested_action="none",
                    ).model_dump(),
                    "completed_at": datetime.now(UTC).isoformat(),
                })
                return
            record["status"] = "running"
            record["started_at"] = datetime.now(UTC).isoformat()
        try:
            page = 1
            seen: set[str] = set()
            while True:
                videos, total = enumerate_watchlater_videos(
                    page=page, cookie=_bilibili_cookie(store)
                )
                with app.state.watchlater_scan_lock:
                    record = app.state.watchlater_scans.get(scan_id)
                    if record is None or record["cancel_event"].is_set():
                        return
                    candidates = list(record.get("candidates", []))
                    for video in videos:
                        if video.bvid in seen:
                            continue
                        seen.add(video.bvid)
                        candidates.append(_creator_candidate(video))
                    record.update({
                        "up_name": "稍后再看",
                        "total": total,
                        "candidates": candidates,
                        "fetched_count": len(candidates),
                        "skipped_count": max(int(total or 0) - len(candidates), 0),
                    })
                if not videos or len(seen) >= total:
                    break
                page += 1
            with app.state.watchlater_scan_lock:
                record = app.state.watchlater_scans.get(scan_id)
                if record is None or record["cancel_event"].is_set():
                    return
                record.update({
                    "status": "completed",
                    "completed_at": datetime.now(UTC).isoformat(),
                    "error": (
                        CreatorScanError(
                            code="NO_PUBLIC_VIDEOS",
                            user_message="稍后再看列表中没有可访问的视频。",
                            suggested_action="open_source",
                        ).model_dump()
                        if not record.get("candidates") else None
                    ),
                })
        except Exception as error:
            with app.state.watchlater_scan_lock:
                record = app.state.watchlater_scans.get(scan_id)
                if record is None or record["cancel_event"].is_set():
                    return
                record.update({
                    "status": "failed",
                    "error": _creator_scan_error(error, "watchlater"),
                    "completed_at": datetime.now(UTC).isoformat(),
                })
    app.state.archive_root = resolved_archive_root
    held_jobs = _hold_interrupted_jobs(store)
    if held_jobs:
        logger.info("startup_hold count=%s", held_jobs)

    @app.get("/ui/app.js", include_in_schema=False)
    def desktop_ui_script() -> Response:
        """Serve the UI script with the current source contract injected.

        Keeping the placeholder in the checked-in asset means the frontend
        cannot become a second manually maintained version source.  An old
        backend process falls back to StaticFiles and serves the unresolved
        placeholder, which the frontend rejects before making business calls.
        """
        script = (UI_DIRECTORY / "app.js").read_text(encoding="utf-8")
        return Response(
            content=script.replace("__API_CONTRACT_VERSION__", API_CONTRACT_VERSION),
            media_type="application/javascript",
            headers={"Cache-Control": "no-store"},
        )

    app.mount("/ui", StaticFiles(directory=UI_DIRECTORY), name="ui")

    @app.get("/", include_in_schema=False)
    def desktop_ui() -> FileResponse:
        return FileResponse(
            UI_DIRECTORY / "index.html",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/dev/rag", include_in_schema=False)
    def rag_developer_ui() -> FileResponse:
        return FileResponse(
            UI_DIRECTORY / "_legacy" / "dev-rag.html",
            headers={"Cache-Control": "no-store"},
        )


    @app.get("/api/v1/contents/{content_id}/thumbnail")
    def content_thumbnail(content_id: str):
        """11-10 回扫 R1：代理封面，规避 B 站 CDN 对本地 Referer 的 403。"""
        import tempfile
        import urllib.parse
        import urllib.request
        from pathlib import Path
        from starlette.responses import Response

        try:
            content = store.get_content(content_id)
        except ContentNotFoundError as error:
            raise HTTPException(status_code=404, detail="content_not_found") from error
        source = getattr(content, "source", None)
        url = getattr(source, "thumbnail_url", None) or getattr(content, "thumbnail_url", None)
        if not isinstance(url, str) or not url:
            raise HTTPException(status_code=404, detail="thumbnail_not_found")
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower()
        allowed = ("hdslb.com", "bilibili.com", "xhscdn.com", "byteimg.com",
                   "douyincdn.com", "zhimg.com")
        if parsed.scheme not in ("http", "https") or not any(
            host == domain or host.endswith("." + domain) for domain in allowed
        ):
            raise HTTPException(status_code=422, detail="thumbnail_host_not_allowed")
        cache = Path(tempfile.gettempdir()) / "wb-thumb-cache"
        cache.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
        target = cache / (key + ".img")
        meta = cache / (key + ".type")
        if target.is_file():
            cached_type = meta.read_text(encoding="utf-8").strip() if meta.is_file() else "image/jpeg"
            return Response(content=target.read_bytes(), media_type=cached_type)
        request = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0", "Accept": "image/*"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=8) as response:
                media_type = (response.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip()
                data = response.read(5 * 1024 * 1024 + 1)
        except Exception as error:
            raise HTTPException(status_code=502, detail="thumbnail_fetch_failed") from error
        if not media_type.startswith("image/") or len(data) > 5 * 1024 * 1024:
            raise HTTPException(status_code=502, detail="thumbnail_invalid_payload")
        target.write_bytes(data)
        meta.write_text(media_type, encoding="utf-8")
        return Response(content=data, media_type=media_type)

    @app.post("/api/v1/contents/{content_id}/export/write")
    def write_content_export(content_id: str, request: dict = Body(...)) -> Response:
        """按设计稿图八：把导出内容写入归档目录或归档根下的自定义子目录。

        只接受内容自身的归档目录，或归档根下的相对子目录名；不接收任意绝对路径，
        文件名只允许安全字符，写入前校验目标仍在允许的目录内。
        """
        filename = request.get("filename")
        content = request.get("content")
        subdir = request.get("subdir") or ""
        if not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", filename):
            raise HTTPException(status_code=422, detail="invalid_filename")
        if not isinstance(content, str) or not isinstance(subdir, str):
            raise HTTPException(status_code=422, detail="invalid_payload")
        if len(content) > 5_000_000:
            raise HTTPException(status_code=413, detail="payload_too_large")
        if ".." in subdir or "\\" in subdir or "/" in subdir or ":" in subdir:
            raise HTTPException(status_code=422, detail="invalid_subdir")
        root_value = getattr(app.state, "archive_root", None)
        root = Path(root_value).resolve() if root_value else None
        if subdir:
            if root is None:
                raise HTTPException(status_code=409, detail="archive_root_unavailable")
            directory = (root / subdir).resolve()
            if directory != root and root not in directory.parents:
                raise HTTPException(status_code=422, detail="subdir_out_of_root")
            directory.mkdir(parents=True, exist_ok=True)
        else:
            try:
                entry = store.get_history_entry(content_id)
            except ContentNotFoundError as error:
                raise HTTPException(status_code=404, detail="content_not_found") from error
            archive_value = entry.job.metadata.get("archive_path")
            candidate = Path(archive_value) if isinstance(archive_value, str) else None
            directory = candidate.resolve() if candidate and candidate.is_dir() else None
            if directory is None:
                raise HTTPException(status_code=409, detail="archive_not_available")
        target = (directory / filename).resolve()
        if target.parent != directory or len(str(target)) > 220:
            raise HTTPException(status_code=422, detail="invalid_target")
        try:
            target.write_text(content, encoding="utf-8")
        except OSError as error:
            raise HTTPException(status_code=500, detail="archive_write_failed") from error
        return Response(
            content=json.dumps({"path": str(target), "filename": filename}, ensure_ascii=False),
            media_type="application/json",
        )

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(api_contract_version=API_CONTRACT_VERSION)

    @app.get("/api/v1/meta", response_model=AppMetaResponse)
    def get_meta() -> AppMetaResponse:
        return AppMetaResponse(
            version=APP_VERSION,
            api_contract_version=API_CONTRACT_VERSION,
            changelog=CHANGELOG,
            known_issues=KNOWN_ISSUES,
            browser_validation="blocked",
        )

    @app.get("/api/v1/environment/check", response_model=EnvironmentCheckResponse)
    def check_environment(
        check_network: bool = Query(default=True),
    ) -> EnvironmentCheckResponse:
        return EnvironmentCheckResponse(
            **environment_report(
                store,
                app.state.archive_root,
                app.state.asr_model_root,
                check_network=check_network,
            )
        )

    @app.post("/api/v1/system/open-url")
    def open_url_externally(request: OpenUrlRequest) -> dict[str, object]:
        """来源链接交系统默认浏览器，失败如实返回，不退回壳内浏览。"""

        parsed = urlsplit(request.url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise HTTPException(status_code=422, detail="unsupported_url_scheme")
        try:
            opened = webbrowser.open(parsed.geturl())
        except Exception as error:  # noqa: BLE001 - 打开失败按真实原因反馈
            raise HTTPException(status_code=500, detail="open_browser_failed") from error
        if not opened:
            raise HTTPException(status_code=500, detail="open_browser_failed")
        return {"opened": True}

    @app.post("/api/v1/tasks/preflight", response_model=TaskPreflightResponse)
    def preflight_task(request: TaskPreflightRequest) -> TaskPreflightResponse:
        content = None
        if request.content_id:
            try:
                content = store.get_content(request.content_id)
            except ContentNotFoundError as error:
                raise HTTPException(status_code=404, detail="content_not_found") from error
        kind = request.kind.value if request.kind else content.kind.value if content else None
        duration = request.duration_seconds
        if duration is None and content is not None:
            duration = content.duration_seconds
        source_url = request.source_url
        if source_url is None and content is not None:
            source_url = content.source.canonical_url
        result = task_preflight(
            store,
            kind=kind,
            duration_seconds=duration,
            text_length=request.text_length,
            has_transcript=request.has_transcript,
            asr_engine=request.asr_engine,
            local_model=request.local_model or _local_asr_model(store),
            model=request.model or store.get_setting("summary_model"),
            max_chunk_tokens=request.max_chunk_tokens,
            source_url=source_url,
            archive_root=app.state.archive_root,
            model_root=app.state.asr_model_root,
        )
        return TaskPreflightResponse(**result)
    @app.post(
        "/api/v1/contents", response_model=ContentResponse, status_code=status.HTTP_201_CREATED
    )
    def create_content(request: ContentCreateRequest) -> ContentResponse:
        try:
            content = store.create_content(
                kind=request.kind,
                title=request.title,
                platform=request.platform,
                canonical_url=request.canonical_url,
                thumbnail_url=request.thumbnail_url,
                author=request.author,
                language=request.language,
                duration_seconds=request.duration_seconds,
                content_hash=request.content_hash,
                published_at=request.published_at,
                acquisition_method=request.acquisition_method,
                category=request.category,
                tag_ids=request.tag_ids,
                introduction=request.introduction,
                favorite=request.favorite,
                favorite_folder_ids=request.favorite_folder_ids,
                processing_model=request.processing_model,
            )
        except FavoriteFolderNotFoundError as error:
            raise HTTPException(status_code=404, detail="favorite_folder_not_found") from error
        except TagNotFoundError as error:
            raise HTTPException(status_code=404, detail="tag_not_found") from error
        return _content_response(
            content,
            favorite_folder_ids=store.favorite_folder_ids(content.id),
            tag_ids=store.tag_ids(content.id),
            tag_names=store.tag_names(content.id),
        )

    @app.get("/api/v1/contents/{content_id}", response_model=ContentResponse)
    def get_content(content_id: str) -> ContentResponse:
        try:
            content = store.get_content(content_id)
            return _content_response(
                content,
                favorite_folder_ids=store.favorite_folder_ids(content_id),
                tag_ids=store.tag_ids(content_id),
                tag_names=store.tag_names(content_id),
            )
        except ContentNotFoundError as error:
            raise HTTPException(status_code=404, detail="content_not_found") from error

    @app.patch("/api/v1/contents/{content_id}", response_model=ContentResponse)
    def update_content(content_id: str, request: ContentUpdateRequest) -> ContentResponse:
        try:
            content = store.update_content(
                content_id,
                category=request.category,
                tag_ids=request.tag_ids,
                introduction=request.introduction,
                favorite=request.favorite,
                favorite_folder_ids=request.favorite_folder_ids,
            )
            if request.introduction is not None:
                _sync_content_introduction(store, content_id, content.introduction)
            if request.tag_ids is not None:
                _sync_content_tags(store, content_id, store.tag_names(content_id))
            return _content_response(
                content,
                favorite_folder_ids=store.favorite_folder_ids(content_id),
                tag_ids=store.tag_ids(content_id),
                tag_names=store.tag_names(content_id),
            )
        except FavoriteFolderNotFoundError as error:
            raise HTTPException(status_code=404, detail="favorite_folder_not_found") from error
        except TagNotFoundError as error:
            raise HTTPException(status_code=404, detail="tag_not_found") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except ContentNotFoundError as error:
            raise HTTPException(status_code=404, detail="content_not_found") from error

    @app.delete("/api/v1/contents/{content_id}", response_model=ContentResponse)
    def delete_content(content_id: str) -> ContentResponse:
        try:
            content = store.soft_delete_content(content_id)
            get_ask_index().mark_deleted(content_id)
            get_rag_service().rag_store.invalidate_content(content_id)
            cleanup_content_artifacts(content_id)
            return _content_response(
                content,
                favorite_folder_ids=store.favorite_folder_ids(content_id),
                tag_ids=store.tag_ids(content_id),
                tag_names=store.tag_names(content_id),
            )
        except ContentNotFoundError as error:
            raise HTTPException(status_code=404, detail="content_not_found") from error

    @app.post("/api/v1/contents/{content_id}/restore", response_model=ContentResponse)
    def restore_content(content_id: str) -> ContentResponse:
        try:
            content = store.restore_content(content_id)
            get_ask_index().sync_latest(content_id)
            start_rag_tagging(content_id)
            return _content_response(
                content,
                favorite_folder_ids=store.favorite_folder_ids(content_id),
                tag_ids=store.tag_ids(content_id),
                tag_names=store.tag_names(content_id),
            )
        except ContentNotFoundError as error:
            raise HTTPException(status_code=404, detail="content_not_found") from error

    @app.delete("/api/v1/contents/{content_id}/purge")
    def purge_content(content_id: str) -> dict[str, bool]:
        try:
            content = store.get_content(content_id)
        except ContentNotFoundError as error:
            raise HTTPException(status_code=404, detail="content_not_found") from error
        if content.deleted_at is None:
            raise HTTPException(status_code=409, detail="content_not_deleted")
        archived = []
        for job in store.list_content_jobs(content_id):
            value = (job.metadata or {}).get("archive_path")
            if isinstance(value, str) and value:
                archived.append(value)
        directories: list[Path] = []
        if archived:
            root_value = getattr(app.state, "archive_root", None)
            if root_value is None:
                raise HTTPException(status_code=409, detail="archive_root_unavailable")
            root = Path(root_value).resolve()
            for value in dict.fromkeys(archived):
                directory = Path(value).resolve()
                if directory == root or root not in directory.parents:
                    raise HTTPException(status_code=409, detail="archive_path_out_of_root")
                directories.append(directory)
        for directory in directories:
            if directory.is_dir():
                try:
                    shutil.rmtree(directory)
                except OSError as error:
                    raise HTTPException(status_code=409, detail="archive_delete_failed") from error
        cleanup_content_artifacts(content_id)
        get_ask_index().mark_deleted(content_id)
        get_rag_service().rag_store.invalidate_content(content_id)
        try:
            store.purge_content(content_id)
        except ContentNotFoundError as error:
            raise HTTPException(status_code=404, detail="content_not_found") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {"purged": True}

    @app.get("/api/v1/trash", response_model=list[HistoryEntryResponse])
    def list_trash(
        q: str | None = Query(default=None, max_length=200),
        category: str | None = Query(default=None, max_length=120),
    ) -> list[HistoryEntryResponse]:
        return [
            _history_response(
                entry,
                favorite_folder_ids=store.favorite_folder_ids(entry.content.id),
                tag_ids=store.tag_ids(entry.content.id),
                tag_names=store.tag_names(entry.content.id),
            )
            for entry in store.list_history(
                q,
                category=category,
                include_deleted=True,
                deleted_only=True,
            )
        ]

    @app.get("/api/v1/tags", response_model=list[TagResponse])
    def list_tags() -> list[TagResponse]:
        return [
            TagResponse(
                id=tag.id,
                name=tag.name,
                user_id=tag.user_id,
                content_count=tag.content_count,
                created_at=tag.created_at,
                updated_at=tag.updated_at,
            )
            for tag in store.list_tags()
        ]

    @app.post("/api/v1/tags", response_model=TagResponse, status_code=status.HTTP_201_CREATED)
    def create_tag(request: TagCreateRequest) -> TagResponse:
        try:
            tag = store.create_tag(request.name)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return TagResponse(
            id=tag.id,
            name=tag.name,
            user_id=tag.user_id,
            content_count=tag.content_count,
            created_at=tag.created_at,
            updated_at=tag.updated_at,
        )

    @app.patch("/api/v1/tags/{tag_id}", response_model=TagResponse)
    def rename_tag(tag_id: str, request: TagUpdateRequest) -> TagResponse:
        try:
            tag = store.rename_tag(tag_id, request.name)
        except TagNotFoundError as error:
            raise HTTPException(status_code=404, detail="tag_not_found") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return TagResponse(
            id=tag.id,
            name=tag.name,
            user_id=tag.user_id,
            content_count=tag.content_count,
            created_at=tag.created_at,
            updated_at=tag.updated_at,
        )

    @app.delete("/api/v1/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_tag(tag_id: str) -> Response:
        try:
            store.delete_tag(tag_id)
        except TagNotFoundError as error:
            raise HTTPException(status_code=404, detail="tag_not_found") from error
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/api/v1/content-categories", response_model=list[CategoryResponse])
    def list_content_categories() -> list[CategoryResponse]:
        return [CategoryResponse(name=name) for name in store.list_categories()]

    @app.get("/api/v1/favorite-folders", response_model=list[FavoriteFolderResponse])
    def list_favorite_folders() -> list[FavoriteFolderResponse]:
        folders = [
            FavoriteFolderResponse(
                id="all",
                name="全部收藏",
                parent_id=None,
                content_count=store.count_favorites(),
                is_system=True,
            )
        ]
        folders.extend(
            _favorite_folder_response(folder) for folder in store.list_favorite_folders()
        )
        return folders

    @app.post(
        "/api/v1/favorite-folders",
        response_model=FavoriteFolderResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_favorite_folder(request: FavoriteFolderCreateRequest) -> FavoriteFolderResponse:
        try:
            return _favorite_folder_response(
                store.create_favorite_folder(request.name, parent_id=request.parent_id)
            )
        except FavoriteFolderNotFoundError as error:
            raise HTTPException(status_code=404, detail="favorite_folder_not_found") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.patch("/api/v1/favorite-folders/{folder_id}", response_model=FavoriteFolderResponse)
    def rename_favorite_folder(
        folder_id: str,
        request: FavoriteFolderUpdateRequest,
    ) -> FavoriteFolderResponse:
        if folder_id == "all":
            raise HTTPException(status_code=400, detail="system_favorite_folder_immutable")
        try:
            folder = store.rename_favorite_folder(folder_id, request.name)
            if "parent_id" in request.model_fields_set:
                folder = store.update_favorite_folder_parent(folder_id, request.parent_id)
            return _favorite_folder_response(folder)
        except FavoriteFolderNotFoundError as error:
            raise HTTPException(status_code=404, detail="favorite_folder_not_found") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.delete("/api/v1/favorite-folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_favorite_folder(folder_id: str) -> Response:
        if folder_id == "all":
            raise HTTPException(status_code=400, detail="system_favorite_folder_immutable")
        try:
            store.delete_favorite_folder(folder_id)
        except FavoriteFolderNotFoundError as error:
            raise HTTPException(status_code=404, detail="favorite_folder_not_found") from error
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    @app.post("/api/v1/contents/batch-organize", response_model=ContentBatchOrganizeResponse)
    def batch_organize(request: ContentBatchOrganizeRequest) -> ContentBatchOrganizeResponse:
        try:
            report = store.batch_organize(
                request.ids,
                operation=request.operation,
                tag_id=request.tag_id,
                folder_ids=request.folder_ids,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return ContentBatchOrganizeResponse(**report)

    @app.post("/api/v1/contents/batch", response_model=list[ContentResponse])
    def batch_content_action(request: ContentBatchRequest) -> list[ContentResponse]:
        if request.action == "move" and request.category is None:
            raise HTTPException(status_code=422, detail="移动内容时必须提供分类")
        contents = []
        try:
            for content_id in request.ids:
                if request.action == "move":
                    content = store.update_content(content_id, category=request.category)
                elif request.action == "delete":
                    content = store.soft_delete_content(content_id)
                    get_ask_index().mark_deleted(content_id)
                    get_rag_service().rag_store.invalidate_content(content_id)
                    cleanup_content_artifacts(content_id)
                else:
                    content = store.restore_content(content_id)
                    get_ask_index().sync_latest(content_id)
                    start_rag_tagging(content_id)
                contents.append(_content_response(content))
        except ContentNotFoundError as error:
            raise HTTPException(status_code=404, detail="content_not_found") from error
        return contents
    @app.post(
        "/api/v1/contents/{content_id}/analysis-runs",
        response_model=AnalysisRunCreatedResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_analysis_run(
        content_id: str,
        request: AnalysisRunCreateRequest,
    ) -> AnalysisRunCreatedResponse:
        try:
            settings = _analysis_settings_from_store(
                store,
                app.state.skills_root,
                model=request.model,
                language=request.language,
                asr_engine=request.asr_engine,
                max_chunk_tokens=request.max_chunk_tokens,
                summary_template=request.summary_template,
                summary_style=request.summary_style,
                requested_prompt_version=request.prompt_version,
                strength=request.strength,
            )
            run, job = store.create_analysis_run(content_id, settings, priority=request.priority)
        except SummaryConfigurationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except ContentNotFoundError as error:
            raise HTTPException(status_code=404, detail="content_not_found") from error
        content = store.get_content(content_id)
        return AnalysisRunCreatedResponse(run=_run_response(run), job=_job_response(job, content=content))

    @app.get("/api/v1/source-capabilities", response_model=SourceCapabilitiesResponse)
    def source_capabilities() -> SourceCapabilitiesResponse:
        # 能力唯一真相源：连接型平台全部由 PLATFORM_DEFINITIONS 投影生成。
        projected = [
            SourceCapabilityResponse(
                platform=definition.key,
                display_name=definition.display_name,
                login_url=definition.login_url,
                auth_type=definition.auth_type,
                checker_available=definition.checker_available,
                browser_session_available=definition.browser_session_available,
                supported_source_types=list(definition.supported_source_types),
                public_import_available=definition.public_import_available,
                account_probe_available=definition.account_probe_available,
                text_available=definition.text_available,
                image_ocr_available=definition.image_ocr_available,
                video_available=definition.video_available,
                collection_sync_available=definition.collection_sync_available,
                note=definition.capability_note,
            )
            for definition in PLATFORM_DEFINITIONS
        ]
        # 非连接型平台（媒体边界方案范围外，无 PlatformDefinition）：维持既有
        # 静态事实，避免为连接目录引入无登录语义的伪定义。
        legacy = [
            SourceCapabilityResponse(
                platform="youtube",
                display_name="YouTube",
                login_url="",
                auth_type="public",
                checker_available=False,
                browser_session_available=False,
                supported_source_types=["video"],
                public_import_available=True,
                account_probe_available=False,
                text_available=True,
                image_ocr_available=False,
                video_available=True,
                collection_sync_available=False,
                note="支持公开单条链接；频道和播放列表预览暂未接入。",
            ),
            SourceCapabilityResponse(
                platform="web",
                display_name="普通网页",
                login_url="",
                auth_type="public",
                checker_available=False,
                browser_session_available=False,
                supported_source_types=["article"],
                public_import_available=True,
                account_probe_available=False,
                text_available=True,
                image_ocr_available=False,
                video_available=False,
                collection_sync_available=False,
                note="支持公开单页正文读取。",
            ),
        ]
        return SourceCapabilitiesResponse(capabilities=projected + legacy)
    @app.post("/api/v1/imports/probe", response_model=SourceProbeResponse)
    def probe_source(request: SourceProbeRequest) -> SourceProbeResponse:
        url = request.url.strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise HTTPException(status_code=422, detail="请输入完整的 http 或 https 链接")
        platform = detect_platform(url)
        if platform is None:
            raise HTTPException(status_code=422, detail="暂不支持此链接")
        is_collection = _is_collection_url(url, platform)
        if is_collection:
            source_type = classify_source_type(url, platform)
            is_bilibili_creator = source_type == "creator"
            return SourceProbeResponse(
                url=url,
                platform=platform.value,
                kind="collection",
                source_type=source_type,
                object_label=object_label(source_type),
                preview_status="failed",
                preview_error="请粘贴单条视频链接",
                material_hint=(
                    "可读取该 UP 主的公开投稿候选，需先确认导入范围。"
                    if is_bilibili_creator
                    else "可读取该 B站集合中的候选视频，需先确认导入范围。"
                    if platform is SourcePlatform.BILIBILI and source_type in {"favorite", "watchlater"}
                    else "仅读取此知乎收藏夹前 10 条候选，需由用户选择单条导入。"
                    if platform is SourcePlatform.ZHIHU and source_type == "favorite"
                    else "该集合链接当前不能作为单条内容处理。"
                ),
                next_action=(
                    "预览候选视频后批量入队"
                    if platform is SourcePlatform.BILIBILI and source_type in {"creator", "favorite", "watchlater"}
                    else "预览前 10 条候选后选择一条导入"
                    if platform is SourcePlatform.ZHIHU and source_type == "favorite"
                    else "请粘贴集合中的具体内容链接；当前版本暂不支持直接扫描该集合"
                ),
                can_import=False,
            )
        preview_items: list[dict[str, object]] = []
        preview_error = None
        try:
            preview_items = preview_link_import(url)
        except LinkImportError as error:
            preview_error = str(error)
        for item in preview_items:
            item["duplicate"] = store.find_duplicate_content(
                canonical_url=str(item.get("source_url") or "")
            ) is not None
        duplicate = any(bool(item.get("duplicate")) for item in preview_items)
        definition = get_platform_definition(platform.value)
        source_type = classify_source_type(url, platform)
        content_bearing = source_type not in {"account", "collection", "unknown"}
        import_available = definition is None or definition.public_import_available
        can_import = import_available and content_bearing
        if import_available:
            is_video = platform in {SourcePlatform.BILIBILI, SourcePlatform.YOUTUBE, SourcePlatform.DOUYIN}
            material_hint = (
                "处理时检查公开字幕；无字幕时需要可用的 ASR。"
                if is_video
                else "处理时读取公开页面正文。"
            )
            next_action = (
                "确认后创建新内容，标题自动增加后缀"
                if duplicate
                else "确认后创建任务"
            )
        else:
            material_hint = (
                definition.capability_note
                if definition
                else "该平台暂不支持内容导入。"
            )
            next_action = "使用本地文件或粘贴文本导入该内容"
        return SourceProbeResponse(
            url=url,
            platform=platform.value,
            kind="single",
            source_type=source_type,
            object_label=object_label(source_type),
            duplicate=duplicate,
            preview_status="ready" if preview_items else "failed",
            preview_error=preview_error,
            items=preview_items,
            material_hint=material_hint,
            next_action=next_action,
            can_import=can_import,
        )

    @app.post("/api/v1/imports/query", response_model=LinkQueryResponse)
    def query_link_imports(request: LinkQueryRequest) -> LinkQueryResponse:
        """Start per-link validation without creating an analysis task."""

        _cleanup_link_queries()
        urls: list[str] = []
        seen_urls: set[str] = set()
        for raw_url in request.urls:
            url = raw_url.strip()
            if url and url not in seen_urls:
                urls.append(url)
                seen_urls.add(url)
        if not urls:
            raise HTTPException(status_code=422, detail="请至少输入一条链接")

        query_id = new_id("link-query")
        created_at = datetime.now(UTC)
        deadline_at = created_at + timedelta(seconds=LINK_QUERY_DEADLINE_SECONDS)
        records: dict[str, dict[str, object]] = {}
        for url in urls:
            platform = detect_platform(url)
            collection = bool(platform and _is_collection_url(url, platform))
            item_id = new_id("link-query-item")
            records[item_id] = {
                "item_id": item_id,
                "input_url": url,
                "platform": platform.value if platform else None,
                "kind": classify_source_type(url, platform) if collection else "single",
                "source_type": classify_source_type(url, platform) if collection else "single",
                "status": "pending",
                "reason": "正在查询链接…",
                "source": None,
                "duplicate": False,
            }
        record: dict[str, object] = {
            "query_id": query_id,
            "created_at": created_at,
            "deadline_at": deadline_at,
            "status": "processing",
            "items": records,
            "seen_source_keys": set(),
            "cancel_event": Event(),
            "done_event": Event(),
        }
        with app.state.link_query_lock:
            app.state.link_queries[query_id] = record
        for item in list(records.values()):
            _start_link_query_worker(
                query_id,
                _run_link_query_item,
                args=(query_id, str(item["item_id"]), str(item["input_url"]), request.language),
                name=f"{query_id}-{item['item_id']}",
            )
        _start_link_query_worker(
            query_id,
            _watch_link_query,
            args=(query_id,),
            name=f"{query_id}-deadline",
        )
        with app.state.link_query_lock:
            return _link_query_snapshot(record)

    def _confirm_link_query(
        request: LinkQueryConfirmRequest,
        background_tasks: BackgroundTasks,
        *,
        collection_metadata: dict[str, object] | None = None,
    ) -> LinkImportResponse:
        _cleanup_link_queries()
        _expire_link_query(request.query_id)
        if request.favorite_folder_ids:
            available_folders = {
                folder.id for folder in store.list_favorite_folders()
            }
            missing = set(request.favorite_folder_ids) - available_folders
            if missing:
                raise HTTPException(status_code=404, detail="favorite_folder_not_found")
        if request.tag_ids:
            missing_tags = set(request.tag_ids) - {tag.id for tag in store.list_tags()}
            if missing_tags:
                raise HTTPException(status_code=404, detail="tag_not_found")

        with app.state.link_query_lock:
            record = app.state.link_queries.get(request.query_id)
            if record is None:
                raise HTTPException(status_code=404, detail="link_query_expired")
            records = record.get("items")
            if not isinstance(records, dict):
                raise HTTPException(status_code=409, detail="link_query_invalid")
            selected: list[dict[str, object]] = []
            seen_item_ids: set[str] = set()
            for item_id in request.item_ids:
                if item_id in seen_item_ids:
                    continue
                seen_item_ids.add(item_id)
                item = records.get(item_id)
                if not isinstance(item, dict) or item.get("source") is None:
                    raise HTTPException(status_code=422, detail="只能提交查询通过的链接")
                if item.get("status") not in {"ready", "duplicate"}:
                    raise HTTPException(status_code=422, detail="查询结果中存在不可提交的链接")
                selected.append(item)

        if not selected:
            raise HTTPException(status_code=422, detail="请至少选择一条可提交链接")
        try:
            settings = _analysis_settings_from_store(
                store,
                app.state.skills_root,
                model=request.model,
                language=request.language,
                asr_engine=store.get_setting("asr_engine") or "cloud",
                max_chunk_tokens=request.max_chunk_tokens,
                summary_template=request.summary_template,
                summary_style=request.summary_style,
                strength=request.strength,
                extra_instruction=request.extra_instruction,
            )
        except SummaryConfigurationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

        sources = [item["source"] for item in selected]
        organization_requested = bool(
            (request.category or "").strip()
            or request.tag_ids
            or request.favorite_folder_ids
        )
        batch_name = _archive_batch_name(sources) if organization_requested and len(sources) > 1 else None
        import_batch_id = new_id("import-batch") if len(sources) > 1 else None
        accepted: list[ImportResponse] = []
        skipped: list[str] = []
        failed: list[LinkImportFailure] = []
        association_failures: list[LinkImportAssociationFailure] = []
        submitted_ids: set[str] = set()
        for index, item in enumerate(selected, start=1):
            source = item["source"]
            input_url = str(item["input_url"])
            duplicate = store.find_duplicate_content(
                canonical_url=source.source_url,
                content_hash=source.content_hash,
            )
            season_metadata = collection_metadata
            if duplicate and collection_metadata:
                season_metadata = _attach_season_metadata(
                    store, duplicate.id, collection_metadata
                )
            if duplicate and request.duplicate_action == "reuse":
                try:
                    if duplicate.deleted_at is not None:
                        store.restore_content(duplicate.id)
                        get_ask_index().sync_latest(duplicate.id)
                except ContentNotFoundError:
                    pass
                else:
                    _discard_temporary_audio(source)
                    skipped.append(source.source_url or input_url)
                    submitted_ids.add(str(item["item_id"]))
                    continue
            source = _source_with_duplicate_title(
                store, source, duplicate, request.duplicate_action
            )
            job_created = False
            job_scheduled = False
            try:
                if source.acquisition_method != "queued_link":
                    _require_asr_for_untitled_source(store, source, app.state.asr_model_root)
                content, run, job = workflow.submit(
                    source,
                    settings,
                    content_id=(
                        duplicate.id
                        if duplicate and request.duplicate_action == "overwrite"
                        else None
                    ),
                    archive_group=batch_name,
                    import_batch_id=import_batch_id,
                    archive_index=index if batch_name else None,
                    archive_total=len(sources) if batch_name else None,
                    priority=request.priority,
                )
                job_created = True
                if season_metadata:
                    _set_season_metadata(job, season_metadata)
                if source.acquisition_method == "queued_link":
                    job.metadata["deferred_link"] = True
                    job.metadata["scan_import"] = True
                    store.save_job(job)
                elif season_metadata:
                    store.save_job(job)
                folder_ids: list[str] = []
                if (request.category or "").strip() or request.tag_ids:
                    content = store.update_content(
                        content.id,
                        category=request.category or None,
                        tag_ids=request.tag_ids or None,
                    )
                folder_association_error: Exception | None = None
                if request.favorite_folder_ids:
                    try:
                        content = store.update_content(
                            content.id,
                            favorite_folder_ids=request.favorite_folder_ids,
                        )
                    except Exception as error:
                        folder_association_error = error
                if organization_requested:
                    folder_ids = store.favorite_folder_ids(content.id)
                background_tasks.add_task(schedule_job, job.id, source.transcript)
                job_scheduled = True
                accepted_item = ImportResponse(
                    content=_content_response(
                        content,
                        favorite_folder_ids=folder_ids,
                        tag_ids=store.tag_ids(content.id),
                        tag_names=store.tag_names(content.id),
                    ),
                    run=_run_response(run),
                    job=_job_response(job, content=content),
                    duplicate=duplicate is not None,
                    duplicate_content_id=duplicate.id if duplicate else None,
                )
                accepted.append(accepted_item)
                if folder_association_error is not None:
                    association_failures.append(
                        LinkImportAssociationFailure(
                            content=accepted_item.content,
                            run=accepted_item.run,
                            job=accepted_item.job,
                            folder_ids=list(request.favorite_folder_ids),
                            reason=f"收藏夹关联失败：{folder_association_error}",
                        )
                    )
                submitted_ids.add(str(item["item_id"]))
            except Exception as error:
                if not job_created:
                    _discard_temporary_audio(source)
                elif not job_scheduled:
                    # A task already exists even when its optional organization
                    # write failed. It must still enter the queue exactly once.
                    background_tasks.add_task(schedule_job, job.id, source.transcript)
                    job_scheduled = True
                _sync_bilibili_error_status(store, input_url, error)
                logger.exception("link import failed url=%s", input_url)
                failed.append(LinkImportFailure(url=input_url, reason="链接导入失败，请稍后重试"))

        with app.state.link_query_lock:
            record = app.state.link_queries.get(request.query_id)
            if record is not None:
                records = record.get("items")
                if isinstance(records, dict):
                    for item_id in submitted_ids:
                        records.pop(item_id, None)
                    if not records:
                        app.state.link_queries.pop(request.query_id, None)
        first = accepted[0] if accepted else None
        return LinkImportResponse(
            content=first.content if first else None,
            run=first.run if first else None,
            job=first.job if first else None,
            accepted=accepted,
            skipped=skipped,
            failed=failed,
            association_failures=association_failures,
        )

    @app.post(
        "/api/v1/imports/query/confirm",
        response_model=LinkImportResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def confirm_link_query(
        request: LinkQueryConfirmRequest,
        background_tasks: BackgroundTasks,
    ) -> LinkImportResponse:
        return _confirm_link_query(request, background_tasks)

    @app.post(
        "/api/v1/imports/bilibili/scans/confirm",
        response_model=LinkImportResponse, status_code=status.HTTP_201_CREATED,
    )
    def confirm_scan_import(
        request: ScanImportRequest, background_tasks: BackgroundTasks,
    ) -> LinkImportResponse:
        candidates = None
        season_id: object = None
        collection_title: str | None = None
        collection_total: int | None = None
        for scans, lock in (
            (app.state.favorite_scans, app.state.favorite_scan_lock),
            (app.state.creator_scans, app.state.creator_scan_lock),
            (app.state.watchlater_scans, app.state.watchlater_scan_lock),
        ):
            with lock:
                scan = scans.get(request.scan_id)
                if scan is not None:
                    candidates = {item["candidate_id"]: dict(item) for item in scan["candidates"]}
                    # 只有可信合集扫描记录携带 season_id；收藏夹和稍后再看保持平铺。
                    season_id = scan.get("season_id")
                    collection_title = str(scan.get("up_name") or "").strip() or None
                    raw_total = scan.get("total")
                    collection_total = raw_total if isinstance(raw_total, int) and raw_total > 0 else None
                    break
        if candidates is None:
            raise HTTPException(status_code=404, detail="scan_not_found")
        selected = []
        for candidate_id in dict.fromkeys(request.candidate_ids):
            item = candidates.get(candidate_id)
            if item is None or not item.get("selectable", False):
                raise HTTPException(status_code=422, detail="所选候选不存在或正在处理")
            selected.append(item)
        records = {}
        for item in selected:
            source = PreparedSource(
                kind=ContentKind.VIDEO, title=item["title"], transcript=None,
                content_hash=hashlib.sha256(item["url"].encode()).hexdigest(), source_path=None,
                source_url=item["url"], acquisition_method="queued_link",
                platform=SourcePlatform.BILIBILI,
                thumbnail_url=item.get("thumbnail_url"),
                duration_seconds=item.get("duration_seconds"),
            )
            item_id = item["candidate_id"]
            records[item_id] = {
                "item_id": item_id, "input_url": item["url"],
                "source": source, "status": "ready",
            }
        query_id = new_id("scan-import")
        with app.state.link_query_lock:
            app.state.link_queries[query_id] = {
                "query_id": query_id, "created_at": datetime.now(UTC),
                "status": "completed", "items": records,
            }
        collection_metadata = None
        if season_id not in (None, ""):
            collection_metadata = {
                "season_id": season_id,
                "collection_title": collection_title,
                "collection_total": collection_total,
            }
        try:
            return _confirm_link_query(
                LinkQueryConfirmRequest(
                    query_id=query_id, item_ids=list(records),
                    summary_style=request.summary_style, strength=request.strength,
                    duplicate_action=request.duplicate_action,
                    tag_ids=request.tag_ids, favorite_folder_ids=request.favorite_folder_ids,
                ),
                background_tasks,
                collection_metadata=collection_metadata,
            )
        finally:
            with app.state.link_query_lock:
                app.state.link_queries.pop(query_id, None)

    @app.get("/api/v1/imports/query/{query_id}", response_model=LinkQueryResponse)
    def get_link_query(query_id: str) -> LinkQueryResponse:
        _cleanup_link_queries()
        _expire_link_query(query_id)
        with app.state.link_query_lock:
            record = app.state.link_queries.get(query_id)
            if not isinstance(record, dict):
                raise HTTPException(status_code=404, detail="link_query_expired")
            return _link_query_snapshot(record)

    @app.post("/api/v1/imports/query/{query_id}/cancel", response_model=LinkQueryResponse)
    def cancel_link_query(query_id: str) -> LinkQueryResponse:
        _cleanup_link_queries()
        _expire_link_query(query_id)
        return _cancel_link_query(query_id)

    @app.delete("/api/v1/imports/query/{query_id}", response_model=LinkQueryResponse)
    def delete_link_query(query_id: str) -> LinkQueryResponse:
        """Keep the cancel operation compatible with existing DELETE scan controls."""

        _cleanup_link_queries()
        _expire_link_query(query_id)
        return _cancel_link_query(query_id)

    @app.post(
        "/api/v1/imports/local",
        response_model=LocalImportResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def import_local_content(
        request: LocalImportRequest,
        background_tasks: BackgroundTasks,
        operation_id: str | None = Header(default=None, alias="X-Xhs-Operation-Id"),
    ) -> LocalImportResponse:
        note = request.xiaohongshu_source
        if note is None or not re.fullmatch(r"[0-9a-f]{32}", operation_id or ""):
            return _import_local_content(request, background_tasks)

        note_match = re.match(
            r"https://(?:www\.)?xiaohongshu\.com/(?:explore|discovery/item)/([A-Za-z0-9_-]{1,80})(?:[/?#]|$)",
            note.url,
        )
        note_id = note_match[1] if note_match else "-"
        started = monotonic()
        outcome, job_id = "failed", "-"
        try:
            result = _import_local_content(request, background_tasks)
            outcome = "reused" if result.reused else "created"
            job_id = result.job.id
            return result
        except HTTPException as error:
            outcome = f"http_{error.status_code}"
            raise
        finally:
            logger.warning(
                "xhs-import op=%s note=%s result=%s job=%s ms=%d",
                operation_id, note_id, outcome, job_id, (monotonic() - started) * 1000,
            )

    def _import_local_content(
        request: LocalImportRequest,
        background_tasks: BackgroundTasks,
    ) -> LocalImportResponse:
        if request.favorite_folder_ids:
            available_folders = {folder.id for folder in store.list_favorite_folders()}
            missing = set(request.favorite_folder_ids) - available_folders
            if missing:
                raise HTTPException(status_code=404, detail="favorite_folder_not_found")
        if request.tag_ids:
            missing_tags = set(request.tag_ids) - {tag.id for tag in store.list_tags()}
            if missing_tags:
                raise HTTPException(status_code=404, detail="tag_not_found")
        try:
            if request.zhihu_source is not None:
                if request.source_path is not None or request.text is not None:
                    raise HTTPException(status_code=422, detail="知乎正文不能与本地来源同时提交")
                source = prepare_zhihu_text(
                    **request.zhihu_source.model_dump(),
                    language=request.language,
                )
            elif request.xiaohongshu_source is not None:
                if request.source_path is not None or request.text is not None:
                    raise HTTPException(status_code=422, detail="小红书正文不能与本地来源同时提交")
                source = prepare_xhs_note(
                    **request.xiaohongshu_source.model_dump(),
                    language=request.language,
                )
            else:
                source = prepare_local_import(
                    source_path=request.source_path,
                    text=request.text,
                    title=None,
                    language=request.language,
                )
        except ZhihuSourceError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except XiaohongshuSourceError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except LocalImportError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        duplicate = store.find_duplicate_content(
            canonical_url=source.source_url,
            content_hash=source.content_hash,
        )
        if duplicate and request.duplicate_action == "reuse":
            try:
                if duplicate.deleted_at is not None:
                    store.restore_content(duplicate.id)
                    get_ask_index().sync_latest(duplicate.id)
                if request.tag_ids or request.favorite_folder_ids or request.category:
                    store.update_content(
                        duplicate.id,
                        category=request.category.strip() if request.category else None,
                        tag_ids=request.tag_ids or None,
                        favorite_folder_ids=request.favorite_folder_ids,
                    )
                reused = _duplicate_import_response(store, duplicate.id)
                _discard_temporary_audio(source)
                return LocalImportResponse(**reused.model_dump())
            except ContentNotFoundError:
                pass
        existing_id = (
            duplicate.id
            if duplicate and request.duplicate_action == "overwrite"
            else None
        )
        source = _source_with_duplicate_title(
            store, source, duplicate, request.duplicate_action
        )
        try:
            _require_asr_for_untitled_source(store, source, app.state.asr_model_root)
            settings = _analysis_settings_from_store(
                store,
                app.state.skills_root,
                model=request.model,
                language=request.language,
                asr_engine=store.get_setting("asr_engine") or "cloud",
                max_chunk_tokens=request.max_chunk_tokens,
                summary_template=request.summary_template,
                summary_style=request.summary_style,
                strength=request.strength,
                extra_instruction=request.extra_instruction,
            )
            content, run, job = workflow.submit(source, settings, content_id=existing_id)
            if request.tag_ids or request.favorite_folder_ids or request.category:
                content = store.update_content(
                    content.id,
                    category=request.category.strip() if request.category else None,
                    tag_ids=request.tag_ids or None,
                    favorite_folder_ids=request.favorite_folder_ids,
                )
        except SummaryConfigurationError as error:
            _discard_temporary_audio(source)
            raise HTTPException(status_code=422, detail=str(error)) from error
        except Exception:
            _discard_temporary_audio(source)
            raise
        background_tasks.add_task(schedule_job, job.id, source.transcript)
        return LocalImportResponse(
            content=_content_response(
                content,
                favorite_folder_ids=store.favorite_folder_ids(content.id),
                tag_ids=store.tag_ids(content.id),
                tag_names=store.tag_names(content.id),
            ),
            run=_run_response(run),
            job=_job_response(job, content=content),
            duplicate=duplicate is not None,
            duplicate_content_id=duplicate.id if duplicate else None,
            reused=False,
        )

    @app.post(
        "/api/v1/imports/link",
        response_model=LinkImportResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def import_link_content(
        request: LinkImportRequest,
        background_tasks: BackgroundTasks,
    ) -> LinkImportResponse:
        try:
            _preflight_link_connection(store, request.url)
            sources = _prepare_link_sources(
                url=request.url,
                title=None,
                language=request.language,
                bilibili_cookie=_bilibili_cookie(store),
                asr_configured=_asr_is_configured(store, app.state.asr_model_root),
            )
        except LinkImportError as error:
            _sync_bilibili_error_status(store, request.url, error)
            raise HTTPException(status_code=422, detail=str(error)) from error
        try:
            for source in sources:
                _require_asr_for_untitled_source(store, source, app.state.asr_model_root)
        except HTTPException:
            for source in sources:
                _discard_temporary_audio(source)
            raise
        try:
            settings = _analysis_settings_from_store(
                store,
                app.state.skills_root,
                model=request.model,
                language=request.language,
                asr_engine=store.get_setting("asr_engine") or "cloud",
                max_chunk_tokens=request.max_chunk_tokens,
                summary_template=request.summary_template,
                summary_style=request.summary_style,
                strength=request.strength,
                extra_instruction=request.extra_instruction,
            )
        except SummaryConfigurationError as error:
            for source in sources:
                _discard_temporary_audio(source)
            raise HTTPException(status_code=422, detail=str(error)) from error

        duplicates = [
            store.find_duplicate_content(
                canonical_url=source.source_url,
                content_hash=source.content_hash,
            )
            for source in sources
        ]
        duplicate = duplicates[0] if len(sources) == 1 else None
        if duplicate and request.duplicate_action == "reuse":
            try:
                if duplicate.deleted_at is not None:
                    store.restore_content(duplicate.id)
                    get_ask_index().sync_latest(duplicate.id)
                reused = _duplicate_import_response(store, duplicate.id)
                for source in sources:
                    _discard_temporary_audio(source)
                return LinkImportResponse(
                    content=reused.content,
                    run=reused.run,
                    job=reused.job,
                    accepted=[reused],
                )
            except ContentNotFoundError:
                pass
        prepared_sources: list[tuple[object, object | None]] = []
        skipped: list[str] = []
        for source, duplicate_item in zip(sources, duplicates, strict=True):
            if duplicate_item and request.duplicate_action == "reuse":
                _discard_temporary_audio(source)
                skipped.append(source.source_url or duplicate_item.id)
                continue
            prepared_sources.append(
                (
                    _source_with_duplicate_title(
                        store, source, duplicate_item, request.duplicate_action
                    ),
                    duplicate_item,
                )
            )
        if not prepared_sources:
            return LinkImportResponse(skipped=skipped)
        prepared_only = [source for source, _duplicate in prepared_sources]
        batch_name = _archive_batch_name(prepared_only) if len(prepared_only) > 1 else None
        import_batch_id = new_id("import-batch") if len(prepared_only) > 1 else None
        items: list[ImportResponse] = []
        try:
            for index, (source, duplicate_item) in enumerate(prepared_sources, start=1):
                content, run, job = workflow.submit(
                    source,
                    settings,
                    content_id=(
                        duplicate_item.id
                        if duplicate_item and request.duplicate_action == "overwrite"
                        else None
                    ),
                    archive_group=batch_name,
                    import_batch_id=import_batch_id,
                    archive_index=index if batch_name else None,
                    archive_total=len(prepared_only) if batch_name else None,
                )
                background_tasks.add_task(schedule_job, job.id, source.transcript)
                items.append(
                    ImportResponse(
                        content=_content_response(content),
                        run=_run_response(run),
                        job=_job_response(job, content=content),
                        duplicate=duplicate_item is not None,
                        duplicate_content_id=duplicate_item.id if duplicate_item else None,
                    )
                )
        except Exception:
            for source, _duplicate_item in prepared_sources[len(items):]:
                _discard_temporary_audio(source)
            raise
        first = items[0]
        return LinkImportResponse(
            content=first.content,
            run=first.run,
            job=first.job,
            accepted=items,
        )

    def _parse_creator_scan_input(raw_url: str) -> tuple[str, int]:
        url = raw_url.strip()
        if not url:
            raise HTTPException(status_code=422, detail=CreatorScanError(
                code="EMPTY_INPUT", user_message="请输入 B站 UP 主主页链接。", suggested_action="edit_url"
            ).model_dump())
        try:
            parsed = urlparse(url)
            parsed.hostname
        except ValueError:
            raise HTTPException(status_code=422, detail=CreatorScanError(
                code="INVALID_URL", user_message="请输入完整的 http 或 https 链接。", suggested_action="edit_url"
            ).model_dump())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise HTTPException(status_code=422, detail=CreatorScanError(
                code="INVALID_URL", user_message="请输入完整的 http 或 https 链接。", suggested_action="edit_url"
            ).model_dump())
        host = (parsed.hostname or "").lower()
        bilibili_hosts = {"bilibili.com", "www.bilibili.com", "b23.tv", "www.b23.tv"}
        if host not in bilibili_hosts and not host.endswith(".bilibili.com"):
            raise HTTPException(status_code=422, detail=CreatorScanError(
                code="NOT_BILIBILI_URL", user_message="当前入口仅支持 B站 UP 主主页链接。", suggested_action="open_single_import"
            ).model_dump())
        mid = parse_space_mid(url)
        if mid is None:
            raise HTTPException(status_code=422, detail=CreatorScanError(
                code="NOT_CREATOR_URL", user_message="检测到 B站链接，但它不是 UP 主主页，请改用 space.bilibili.com 链接。", suggested_action="open_single_import"
            ).model_dump())
        return url, mid

    def _parse_favorite_scan_input(raw_url: str) -> tuple[str, int]:
        url = raw_url.strip()
        favorite_id = parse_favorite_id(url)
        if favorite_id is None:
            raise HTTPException(status_code=422, detail=CreatorScanError(
                code="NOT_CREATOR_URL", user_message="请输入 B站收藏夹链接。", suggested_action="edit_url"
            ).model_dump())
        return url, favorite_id

    def _parse_watchlater_scan_input(raw_url: str) -> str:
        url = raw_url.strip()
        if not is_watchlater_url(url) or classify_source_type(url, SourcePlatform.BILIBILI) != "watchlater":
            raise HTTPException(status_code=422, detail=CreatorScanError(
                code="NOT_CREATOR_URL",
                user_message="请输入 B站“稍后再看”列表链接，不要带具体视频参数。",
                suggested_action="edit_url",
            ).model_dump())
        return url

    @app.post(
        "/api/v1/imports/bilibili/creator-scans",
        response_model=CreatorScanAcceptedResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def start_creator_scan(request: CreatorScanRequest) -> CreatorScanAcceptedResponse:
        url, mid = _parse_creator_scan_input(request.url)
        season_id = parse_season_id(url)
        source_type = "collection" if season_id else "creator"
        with app.state.creator_scan_lock:
            if not request.refresh:
                for existing in app.state.creator_scans.values():
                    if (
                        existing.get("mid") == mid
                        and existing.get("season_id") == season_id
                        and existing.get("status") in {"queued", "running", "completed"}
                    ):
                        return CreatorScanAcceptedResponse(
                            scan_id=str(existing["scan_id"]), status=str(existing["status"])
                        )
            scan_id = new_id("creator-scan")
            app.state.creator_scans[scan_id] = {
                "scan_id": scan_id, "url": url, "mid": mid, "season_id": season_id,
                "source_type": source_type,
                "up_name": None,
                "total": None, "fetched_count": 0, "candidates": [], "status": "queued",
                "error": None, "started_at": None, "completed_at": None, "cancel_event": Event(),
            }
        Thread(target=_run_creator_scan, args=(scan_id,), name=scan_id, daemon=True).start()
        return CreatorScanAcceptedResponse(scan_id=scan_id, status="queued")

    @app.get(
        "/api/v1/imports/bilibili/creator-scans/{scan_id}",
        response_model=CreatorScanResponse,
    )
    def get_creator_scan(scan_id: str) -> CreatorScanResponse:
        with app.state.creator_scan_lock:
            record = app.state.creator_scans.get(scan_id)
            if record is None:
                raise HTTPException(status_code=404, detail="creator_scan_not_found")
            snapshot = dict(record)
            snapshot["candidates"] = list(record.get("candidates", []))
        return _creator_scan_response(snapshot)

    @app.delete(
        "/api/v1/imports/bilibili/creator-scans/{scan_id}",
        response_model=CreatorScanResponse,
    )
    def cancel_creator_scan(scan_id: str) -> CreatorScanResponse:
        with app.state.creator_scan_lock:
            record = app.state.creator_scans.get(scan_id)
            if record is None:
                raise HTTPException(status_code=404, detail="creator_scan_not_found")
            record["cancel_event"].set()
            if record.get("status") in {"queued", "running"}:
                record["status"] = "cancelled"
                record["error"] = CreatorScanError(
                    code="SCAN_CANCELLED", user_message="已取消扫描，尚未创建总结任务。", suggested_action="none"
                ).model_dump()
                record["completed_at"] = datetime.now(UTC).isoformat()
            snapshot = dict(record)
            snapshot["candidates"] = list(record.get("candidates", []))
        return _creator_scan_response(snapshot)

    @app.get(
        "/api/v1/imports/bilibili/favorite-folders",
        response_model=list[BilibiliFavoriteFolderResponse],
    )
    def list_bilibili_favorite_folders() -> list[BilibiliFavoriteFolderResponse]:
        try:
            cookie = _bilibili_cookie(store)
            if not cookie:
                raise HTTPException(
                    status_code=401,
                    detail="B站登录未确认，请在设置中使用二维码重新登录",
                )
            folders = enumerate_favorite_folders(cookie)
        except HTTPException:
            raise
        except LinkImportError as error:
            error_status = (
                401
                if error.connection_status == REAUTH_REQUIRED
                else 429
                if error.connection_status == RISK_CONTROLLED
                else 502
            )
            raise HTTPException(status_code=error_status, detail=str(error)) from error
        return [
            BilibiliFavoriteFolderResponse(
                id=folder.id,
                title=folder.title,
                media_count=folder.media_count,
            )
            for folder in folders
        ]

    @app.post(
        "/api/v1/imports/bilibili/favorite-scans",
        response_model=CreatorScanAcceptedResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def start_favorite_scan(request: CreatorScanRequest) -> CreatorScanAcceptedResponse:
        url, favorite_id = _parse_favorite_scan_input(request.url)
        with app.state.favorite_scan_lock:
            if not request.refresh:
                for existing in app.state.favorite_scans.values():
                    if existing.get("favorite_id") == favorite_id and existing.get("status") in {"queued", "running", "completed"}:
                        return CreatorScanAcceptedResponse(scan_id=str(existing["scan_id"]), status=str(existing["status"]))
            scan_id = new_id("favorite-scan")
            app.state.favorite_scans[scan_id] = {
                "scan_id": scan_id, "url": url, "favorite_id": favorite_id, "source_type": "favorite",
                "up_name": None, "total": None, "fetched_count": 0, "candidates": [], "status": "queued",
                "error": None, "started_at": None, "completed_at": None, "cancel_event": Event(),
            }
        Thread(target=_run_favorite_scan, args=(scan_id,), name=scan_id, daemon=True).start()
        return CreatorScanAcceptedResponse(scan_id=scan_id, status="queued")

    @app.get("/api/v1/imports/bilibili/favorite-scans/{scan_id}", response_model=CreatorScanResponse)
    def get_favorite_scan(scan_id: str) -> CreatorScanResponse:
        with app.state.favorite_scan_lock:
            record = app.state.favorite_scans.get(scan_id)
            if record is None:
                raise HTTPException(status_code=404, detail="favorite_scan_not_found")
            snapshot = dict(record)
            snapshot["candidates"] = list(record.get("candidates", []))
        return _creator_scan_response(snapshot)

    @app.delete("/api/v1/imports/bilibili/favorite-scans/{scan_id}", response_model=CreatorScanResponse)
    def cancel_favorite_scan(scan_id: str) -> CreatorScanResponse:
        with app.state.favorite_scan_lock:
            record = app.state.favorite_scans.get(scan_id)
            if record is None:
                raise HTTPException(status_code=404, detail="favorite_scan_not_found")
            record["cancel_event"].set()
            if record.get("status") in {"queued", "running"}:
                record.update({"status": "cancelled", "error": CreatorScanError(
                    code="SCAN_CANCELLED", user_message="已取消扫描，尚未创建总结任务。", suggested_action="none"
                ).model_dump(), "completed_at": datetime.now(UTC).isoformat()})
            snapshot = dict(record)
            snapshot["candidates"] = list(record.get("candidates", []))
        return _creator_scan_response(snapshot)

    @app.post(
        "/api/v1/imports/bilibili/watchlater-scans",
        response_model=CreatorScanAcceptedResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def start_watchlater_scan(request: CreatorScanRequest) -> CreatorScanAcceptedResponse:
        url = _parse_watchlater_scan_input(request.url)
        with app.state.watchlater_scan_lock:
            if not request.refresh:
                for existing in app.state.watchlater_scans.values():
                    if existing.get("status") in {"queued", "running", "completed"}:
                        return CreatorScanAcceptedResponse(
                            scan_id=str(existing["scan_id"]), status=str(existing["status"])
                        )
            scan_id = new_id("watchlater-scan")
            app.state.watchlater_scans[scan_id] = {
                "scan_id": scan_id,
                "url": url,
                "source_type": "watchlater",
                "up_name": "稍后再看",
                "total": None,
                "fetched_count": 0,
                "skipped_count": 0,
                "candidates": [],
                "status": "queued",
                "error": None,
                "started_at": None,
                "completed_at": None,
                "cancel_event": Event(),
            }
        Thread(target=_run_watchlater_scan, args=(scan_id,), name=scan_id, daemon=True).start()
        return CreatorScanAcceptedResponse(scan_id=scan_id, status="queued")

    @app.get(
        "/api/v1/imports/bilibili/watchlater-scans/{scan_id}",
        response_model=CreatorScanResponse,
    )
    def get_watchlater_scan(scan_id: str) -> CreatorScanResponse:
        with app.state.watchlater_scan_lock:
            record = app.state.watchlater_scans.get(scan_id)
            if record is None:
                raise HTTPException(status_code=404, detail="watchlater_scan_not_found")
            snapshot = dict(record)
            snapshot["candidates"] = list(record.get("candidates", []))
        return _creator_scan_response(snapshot)

    @app.delete(
        "/api/v1/imports/bilibili/watchlater-scans/{scan_id}",
        response_model=CreatorScanResponse,
    )
    def cancel_watchlater_scan(scan_id: str) -> CreatorScanResponse:
        with app.state.watchlater_scan_lock:
            record = app.state.watchlater_scans.get(scan_id)
            if record is None:
                raise HTTPException(status_code=404, detail="watchlater_scan_not_found")
            record["cancel_event"].set()
            if record.get("status") in {"queued", "running"}:
                record.update({
                    "status": "cancelled",
                    "error": CreatorScanError(
                        code="SCAN_CANCELLED",
                        user_message="已取消扫描，尚未创建总结任务。",
                        suggested_action="none",
                    ).model_dump(),
                    "completed_at": datetime.now(UTC).isoformat(),
                })
            snapshot = dict(record)
            snapshot["candidates"] = list(record.get("candidates", []))
        return _creator_scan_response(snapshot)
    @app.post(
        "/api/v1/imports/bilibili/space/preview",
        response_model=BilibiliSpacePreviewResponse,
    )
    def preview_bilibili_space(request: BilibiliSpacePreviewRequest) -> BilibiliSpacePreviewResponse:
        mid = parse_space_mid(request.url)
        if mid is None:
            raise HTTPException(status_code=422, detail="这不是B站UP主主页链接")
        try:
            up = fetch_up_card(mid, cookie=_bilibili_cookie(store))
            videos, total = enumerate_space_videos(mid, cookie=_bilibili_cookie(store))
        except LinkImportError as error:
            _sync_bilibili_error_status(store, request.url, error)
            raise HTTPException(status_code=422, detail=str(error)) from error
        return BilibiliSpacePreviewResponse(
            mid=up.mid,
            up_name=up.name,
            total=total,
            candidates=[
                SpaceVideoCandidate(
                    bvid=video.bvid,
                    title=video.title,
                    url=video.url,
                    duration_seconds=video.duration_seconds,
                    published_at=video.published_at,
                    thumbnail_url=video.thumbnail_url,
                )
                for video in videos
            ],
        )

    @app.post(
        "/api/v1/imports/links",
        response_model=LinksImportResponse,
        status_code=status.HTTP_200_OK,
    )
    def import_links(
        request: LinksImportRequest,
        background_tasks: BackgroundTasks,
    ) -> LinksImportResponse:
        try:
            settings = _analysis_settings_from_store(
                store,
                app.state.skills_root,
                model=request.model,
                language=request.language,
                asr_engine=store.get_setting("asr_engine") or "cloud",
                max_chunk_tokens=request.max_chunk_tokens,
                summary_template=request.summary_template,
                summary_style=request.summary_style,
                strength=request.strength,
            )
        except SummaryConfigurationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        accepted: list[ImportResponse] = []
        skipped: list[str] = []
        failed: list[LinkImportFailure] = []
        seen_urls: set[str] = set()
        seen_source_keys: set[tuple[str, str]] = set()
        for raw_url in request.urls:
            url = raw_url.strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            try:
                _preflight_link_connection(store, url)
                sources = _prepare_link_sources(
                    url=url,
                    title=None,
                    language=request.language,
                    bilibili_cookie=_bilibili_cookie(store),
                    asr_configured=_asr_is_configured(store, app.state.asr_model_root),
                )
            except LinkImportError as error:
                _sync_bilibili_error_status(store, url, error)
                failed.append(LinkImportFailure(url=url, reason=str(error)))
                continue
            try:
                for source in sources:
                    _require_asr_for_untitled_source(store, source, app.state.asr_model_root)
            except HTTPException as error:
                for source in sources:
                    _discard_temporary_audio(source)
                failed.append(LinkImportFailure(url=url, reason=error.detail))
                continue

            new_sources: list[tuple[object, object | None]] = []
            for source in sources:
                source_key = _source_identity(source)
                if source_key is not None and source_key in seen_source_keys:
                    _discard_temporary_audio(source)
                    continue
                if source_key is not None:
                    seen_source_keys.add(source_key)
                duplicate = store.find_duplicate_content(
                    canonical_url=source.source_url,
                    content_hash=source.content_hash,
                )
                if duplicate and request.duplicate_action == "reuse":
                    _discard_temporary_audio(source)
                    skipped.append(source.source_url or duplicate.id)
                    continue
                new_sources.append(
                    (
                        _source_with_duplicate_title(
                            store, source, duplicate, request.duplicate_action
                        ),
                        duplicate,
                    )
                )
            if not new_sources:
                continue

            prepared_sources = [source for source, _duplicate in new_sources]
            batch_name = _archive_batch_name(prepared_sources) if len(prepared_sources) > 1 else None
            import_batch_id = new_id("import-batch") if len(prepared_sources) > 1 else None
            submitted = 0
            try:
                for index, (source, duplicate) in enumerate(new_sources, start=1):
                    content, run, job = workflow.submit(
                        source,
                        settings,
                        content_id=(
                            duplicate.id
                            if duplicate and request.duplicate_action == "overwrite"
                            else None
                        ),
                        archive_group=batch_name,
                        import_batch_id=import_batch_id,
                        archive_index=index if batch_name else None,
                        archive_total=len(prepared_sources) if batch_name else None,
                    )
                    background_tasks.add_task(schedule_job, job.id, source.transcript)
                    accepted.append(
                        ImportResponse(
                            content=_content_response(content),
                            run=_run_response(run),
                            job=_job_response(job, content=content),
                            duplicate=duplicate is not None,
                            duplicate_content_id=duplicate.id if duplicate else None,
                        )
                    )
                    submitted += 1
            except Exception:
                for source, _duplicate in new_sources[submitted:]:
                    _discard_temporary_audio(source)
                raise
        return LinksImportResponse(accepted=accepted, skipped=skipped, failed=failed)

    @app.get("/api/v1/jobs", response_model=list[JobResponse])
    def list_jobs(
        state: str | None = Query(default=None, max_length=32),
        limit: int = Query(default=200, ge=1, le=5000),
    ) -> list[JobResponse]:
        try:
            states = {JobState(state)} if state else None
        except ValueError as error:
            raise HTTPException(status_code=422, detail="invalid_job_state") from error
        result: list[JobResponse] = []
        for job in store.list_jobs(states=states)[:limit]:
            try:
                run = store.get_analysis_run(job.analysis_run_id)
                content = store.get_content(run.content_id)
            except LookupError:
                content = None
            result.append(_job_response(job, content=content))
        return result

    @app.get("/api/v1/import-batches", response_model=list[ImportBatchResponse])
    def list_import_batches(limit: int = Query(default=50, ge=1, le=200)) -> list[ImportBatchResponse]:
        grouped: dict[str, list] = {}
        for job in store.list_jobs()[:2000]:
            batch_id = job.metadata.get("import_batch_id")
            if isinstance(batch_id, str) and batch_id:
                grouped.setdefault(batch_id, []).append(job)
        batches = [_import_batch_response(store, batch_id, jobs) for batch_id, jobs in grouped.items()]
        batches.sort(key=lambda item: item.members[0].job.created_at if item.members else datetime.min.replace(tzinfo=UTC), reverse=True)
        return batches[:limit]

    @app.get("/api/v1/import-batches/{batch_id}", response_model=ImportBatchResponse)
    def get_import_batch(batch_id: str) -> ImportBatchResponse:
        jobs = [
            job for job in store.list_jobs()
            if job.metadata.get("import_batch_id") == batch_id
        ]
        if not jobs:
            raise HTTPException(status_code=404, detail="import_batch_not_found")
        return _import_batch_response(store, batch_id, jobs)

    def _queue_snapshot() -> dict[str, object]:
        snapshot = app.state.job_queue.snapshot()
        persisted_queued = store.list_jobs(states={JobState.QUEUED})
        persisted_paused = store.list_jobs(states={JobState.PAUSED})
        pending_ids = list(snapshot.get("job_ids", []))
        pending_set = set(pending_ids)
        ordered_ids = pending_ids + [job.id for job in persisted_queued if job.id not in pending_set]
        snapshot["job_ids"] = ordered_ids
        snapshot["queued"] = len(ordered_ids)
        snapshot["items"] = [
            {
                "job_id": job_id,
                "priority": next((job.priority for job in persisted_queued if job.id == job_id), 0),
                "queue_position": index,
            }
            for index, job_id in enumerate(ordered_ids, start=1)
        ]
        snapshot["persisted_queued"] = len(persisted_queued)
        snapshot["persisted_paused"] = len(persisted_paused)
        active_id = snapshot.get("active_job_id")
        if not active_id:
            active_id = next(
                (
                    job.id
                    for job in store.list_jobs()
                    if job.state in _RUNNING_JOB_STATES
                ),
                None,
            )
        snapshot["active_job_id"] = active_id
        snapshot["active"] = 1 if active_id else 0
        snapshot["concurrency_limit"] = 1
        totals = {"total": 0, "waiting": 0, "paused": 0, "running": 0, "completed": 0, "failed": 0, "cancelled": 0}
        for job in store.list_jobs():
            totals["total"] += 1
            execution = _job_execution_state(job)
            if execution in {"running", "switching"}:
                totals["running"] += 1
            elif execution in totals:
                totals[execution] += 1
        snapshot["stats"] = totals
        return snapshot

    @app.get("/api/v1/queue")
    def get_queue() -> dict[str, object]:
        return _queue_snapshot()

    @app.post("/api/v1/queue/reorder")
    def reorder_queue(request: QueueReorderRequest) -> dict[str, object]:
        """Apply a drag-and-drop order to the jobs currently waiting in memory."""

        queued_ids: list[str] = []
        for job_id in request.job_ids:
            try:
                job = store.get_job(job_id)
            except LookupError:
                continue
            if job.state is JobState.QUEUED:
                queued_ids.append(job_id)
        snapshot = app.state.job_queue.reorder(queued_ids)
        # The worker may not have consumed a newly submitted job yet. Keep the
        # persisted position for that short window so a refresh sees the same
        # order and the queue can append it without losing the user's drop.
        pending_ids = set(snapshot.get("job_ids", []))
        persisted = store.list_jobs(states={JobState.QUEUED})
        ordered_ids = [job_id for job_id in queued_ids if job_id not in pending_ids]
        ordered_ids.extend(
            job.id for job in persisted
            if job.id not in queued_ids and job.id not in pending_ids
        )
        for position, job_id in enumerate(ordered_ids, start=1):
            job = store.get_job(job_id)
            job.queue_position = position
            store.save_job(job)
        return _queue_snapshot()

    @app.post("/api/v1/queue/move")
    def move_queue_item(request: QueueMoveRequest) -> dict[str, object]:
        """Move one waiting job without replacing the whole client snapshot."""

        try:
            job = store.get_job(request.job_id)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="job_not_found") from error
        if job.state is not JobState.QUEUED and not _is_switch_requeue(job):
            raise HTTPException(status_code=409, detail="job_not_waiting")
        snapshot = app.state.job_queue.move(request.job_id, request.target_index)
        pending_ids = list(snapshot.get("job_ids", []))
        if request.job_id not in pending_ids:
            waiting_ids = [
                item.id for item in store.list_jobs(states={JobState.QUEUED})
            ]
            waiting_ids.remove(request.job_id) if request.job_id in waiting_ids else None
            target_index = max(0, min(request.target_index, len(waiting_ids)))
            waiting_ids.insert(target_index, request.job_id)
            for position, waiting_id in enumerate(waiting_ids, start=1):
                waiting_job = store.get_job(waiting_id)
                waiting_job.queue_position = position
                store.save_job(waiting_job)
        return _queue_snapshot()

    @app.post("/api/v1/queue/promote/{job_id}")
    def promote_queue_item(job_id: str) -> dict[str, object]:
        try:
            job = store.get_job(job_id)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="job_not_found") from error
        if job.state is not JobState.QUEUED:
            raise HTTPException(status_code=409, detail="job_not_waiting")
        app.state.job_queue.move_to_front(job_id)
        waiting_ids = [
            item.id for item in store.list_jobs(states={JobState.QUEUED})
        ]
        if job_id in waiting_ids:
            waiting_ids.remove(job_id)
            waiting_ids.insert(0, job_id)
            for position, waiting_id in enumerate(waiting_ids, start=1):
                waiting_job = store.get_job(waiting_id)
                waiting_job.queue_position = position
                store.save_job(waiting_job)
        return _queue_snapshot()

    def _job_content(job):
        try:
            run = store.get_analysis_run(job.analysis_run_id)
            return store.get_content(run.content_id)
        except LookupError:
            return None

    @app.post("/api/v1/jobs/duplicate-check", response_model=DuplicateCheckResponse)
    def duplicate_check(request: DuplicateCheckRequest) -> DuplicateCheckResponse:
        """11-22 R1：批量重试/继续前服务端判重。

        口径：以「当前有效、已归档内容」为准——/history 活跃列表（archived_only +
        未删除）里的 content。两层匹配：① 未完成项的 content_id 命中活跃归档内容；
        ② 跨 ID 时用 store.find_duplicate_content（canonical_url + BVID+P 兜底）判重，
        且命中的内容必须仍在活跃归档集合里（回收站不算）。进行中任务不误判。
        """
        archived_entries = store.list_history(archived_only=True, include_deleted=False)
        archived_ids = {entry.content.id for entry in archived_entries}
        items: list[DuplicateCheckItem] = []
        for job_id in request.job_ids:
            base = DuplicateCheckItem(job_id=job_id)
            try:
                job = store.get_job(job_id)
            except LookupError:
                items.append(base)
                continue
            # 只标记用户可见的失败/暂停项；进行中/排队/完成不判为重复。
            if job.state not in {JobState.FAILED, JobState.CANCELLED, JobState.PAUSED}:
                items.append(base)
                continue
            content = _job_content(job)
            if content is None:
                items.append(base)
                continue
            matched = None
            # 第一层：相同 content_id 直接命中活跃归档内容。
            if content.id in archived_ids:
                matched = content
            # 第二层：跨 ID 用来源身份判重，且命中内容必须仍在活跃归档集合里。
            if matched is None:
                source_url = job.metadata.get("source_url")
                if isinstance(source_url, str) and source_url.strip():
                    candidate = store.find_duplicate_content(canonical_url=source_url)
                    if candidate is not None and candidate.id in archived_ids:
                        matched = candidate
            if matched is not None:
                base.is_duplicate = True
                base.matched_content_id = matched.id
                base.matched_title = matched.title
            items.append(base)
        return DuplicateCheckResponse(items=items)

    @app.post("/api/v1/jobs/{job_id}/switch", response_model=JobResponse)
    def switch_job(
        job_id: str,
        request: QueueSwitchRequest,
        background_tasks: BackgroundTasks,
    ) -> JobResponse:
        """Atomically yield the current worker to one waiting job."""

        try:
            requested = store.get_job(job_id)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="job_not_found") from error

        snapshot = _queue_snapshot()
        active_id = snapshot.get("active_job_id")
        active = store.get_job(active_id) if isinstance(active_id, str) else None
        requested_is_running = requested.state in _RUNNING_JOB_STATES
        target_id = request.target_job_id or (job_id if not requested_is_running else None)
        if target_id is not None:
            try:
                target = store.get_job(target_id)
            except LookupError as error:
                raise HTTPException(status_code=404, detail="target_job_not_found") from error
            if _is_switch_requeue(target):
                revive_requeued_job(target.id)
                target = store.get_job(target.id)
            if target.state is not JobState.QUEUED:
                raise HTTPException(status_code=409, detail="target_job_not_waiting")
            app.state.job_queue.move_to_front(target.id)

        if active is not None:
            if active.id == target_id and active.id != job_id:
                raise HTTPException(status_code=409, detail="target_job_already_running")
            if active.state not in _RUNNING_JOB_STATES | {JobState.PAUSED}:
                raise HTTPException(status_code=409, detail="active_job_not_switchable")
            _remember_stable_checkpoint(active)
            if active.state is not JobState.PAUSED:
                active.transition(JobState.PAUSED)
            run = store.get_analysis_run(active.analysis_run_id)
            run.status = "paused"
            run.updated_at = datetime.now(UTC)
            store.save_analysis_run(run)
            app.state.job_queue.remove(active.id)
            if target_id is None:
                target_id = active.id
                active.metadata.pop("switch_requeue", None)
                store.save_job(active)
            else:
                # 被抢占的任务排到插队者后面，插队者跑完它自动接力，不用手动点开始。
                active.metadata["switch_requeue"] = True
                store.save_job(active)
                waiting_ids = list(app.state.job_queue.snapshot().get("job_ids", []))
                anchor = waiting_ids.index(target_id) + 1 if target_id in waiting_ids else 0
                app.state.job_queue.requeue(active.id, index=anchor)
            return _job_response(active, content=_job_content(active))

        if target_id is None:
            raise HTTPException(status_code=409, detail="job_not_switchable")
        if not app.state.job_queue.start_waiting(target_id, run_analysis_job):
            background_tasks.add_task(schedule_job, target_id, None)
        refreshed = store.get_job(target_id)
        return _job_response(refreshed, content=_job_content(refreshed))

    @app.patch("/api/v1/jobs/{job_id}/priority", response_model=JobResponse)
    def update_job_priority(job_id: str, request: JobPriorityUpdateRequest) -> JobResponse:
        try:
            job = store.get_job(job_id)
            if job.state is not JobState.QUEUED:
                raise HTTPException(status_code=409, detail="job_not_waiting")
            job.priority = request.priority
            store.save_job(job)
            app.state.job_queue.set_priority(job_id, request.priority)
            # Legacy clients may still send this request.  Keep its historical
            # response behavior without letting priority participate in the
            # worker scheduler or the new UI contract.
            if request.priority > 0:
                waiting = [
                    item.id for item in store.list_jobs(states={JobState.QUEUED})
                ]
                if job_id in waiting:
                    waiting.remove(job_id)
                    waiting.insert(0, job_id)
                    for position, waiting_id in enumerate(waiting, start=1):
                        waiting_job = store.get_job(waiting_id)
                        waiting_job.queue_position = position
                        store.save_job(waiting_job)
            refreshed = store.get_job(job_id)
            run = store.get_analysis_run(refreshed.analysis_run_id)
            try:
                content = store.get_content(run.content_id)
            except LookupError:
                content = None
            return _job_response(refreshed, content=content)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="job_not_found") from error

    @app.post("/api/v1/jobs/{job_id}/pause", response_model=JobResponse)
    def pause_job(job_id: str) -> JobResponse:
        try:
            job = store.get_job(job_id)
            if job.state in {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}:
                raise HTTPException(status_code=409, detail="job_not_pauseable")
            app.state.job_queue.remove(job.id)
            if job.state is JobState.PAUSED:
                run = store.get_analysis_run(job.analysis_run_id)
                content = store.get_content(run.content_id)
                return _job_response(job, content=content)
            _remember_stable_checkpoint(job)
            job.transition(JobState.PAUSED)
            store.save_job(job)
            run = store.get_analysis_run(job.analysis_run_id)
            run.status = "paused"
            run.updated_at = datetime.now(UTC)
            store.save_analysis_run(run)
            content = store.get_content(run.content_id)
            return _job_response(job, content=content)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="job_not_found") from error
        except InvalidTransitionError as error:
            raise HTTPException(status_code=409, detail="job_not_pauseable") from error

    def _collection_members(collection_id: str) -> list:
        return [job for job in store.list_jobs() if _job_collection_id(job) == collection_id]

    @app.post("/api/v1/job-collections/{collection_id}/pause")
    def pause_job_collection(collection_id: str) -> dict[str, int]:
        """按 collection_id 暂停整组；取材中补建的成员由二次扫描覆盖。"""

        terminal = {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}
        paused = skipped = 0
        seen: set[str] = set()
        # acquire_scan_source 会在运行中补建分 P：扫到没有新成员为止，最多 3 轮。
        for _ in range(3):
            fresh = [job for job in _collection_members(collection_id) if job.id not in seen]
            if not fresh:
                break
            for job in fresh:
                seen.add(job.id)
                if job.state in terminal or job.state is JobState.PAUSED:
                    skipped += 1
                    continue
                app.state.job_queue.remove(job.id)
                _remember_stable_checkpoint(job)
                job.transition(JobState.PAUSED)
                store.save_job(job)
                run = store.get_analysis_run(job.analysis_run_id)
                run.status = "paused"
                run.updated_at = datetime.now(UTC)
                store.save_analysis_run(run)
                paused += 1
        return {"paused": paused, "skipped": skipped}

    @app.post("/api/v1/job-collections/{collection_id}/delete")
    def delete_job_collection(collection_id: str) -> dict[str, int]:
        """取消未结束成员后删除整组任务记录；内容与归档按既有口径保留。"""

        jobs = _collection_members(collection_id)
        if not jobs:
            raise HTTPException(status_code=404, detail="collection_not_found")
        terminal = {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}
        cancelled = 0
        for job in jobs:
            if job.state in terminal:
                continue
            try:
                app.state.job_queue.remove(job.id)
                job.metadata.pop("last_stable_checkpoint", None)
                job.metadata.pop("resume_checkpoint", None)
                job.transition(JobState.CANCELLED)
                store.clear_asr_checkpoints(job.id)
                store.save_job(job)
                cleanup_job_artifacts(job)
                run = store.get_analysis_run(job.analysis_run_id)
                run.status = "cancelled"
                run.updated_at = datetime.now(UTC)
                store.save_analysis_run(run)
                cancelled += 1
            except (InvalidTransitionError, LookupError):
                continue
        deleted = 0
        for job in _collection_members(collection_id):
            try:
                store.delete_job(job.id)
                deleted += 1
            except (LookupError, ValueError):
                continue
        return {"cancelled": cancelled, "deleted": deleted}

    @app.post("/api/v1/jobs/{job_id}/resume", response_model=JobResponse)
    def resume_job(
        job_id: str,
        background_tasks: BackgroundTasks,
        front: bool = True,
    ) -> JobResponse:
        try:
            job = store.get_job(job_id)
            if job.state is JobState.QUEUED:
                # 11-18c R3：排队中的任务再点「继续」是幂等操作，不再 409。
                background_tasks.add_task(schedule_job, job.id, None, front=False)
                run = store.get_analysis_run(job.analysis_run_id)
                content = store.get_content(run.content_id)
                return _job_response(job, content=content)
            if job.state is not JobState.PAUSED:
                raise HTTPException(status_code=409, detail="job_not_paused")
            if "resume_checkpoint" not in job.metadata:
                _remember_stable_checkpoint(job)
            job.transition(JobState.QUEUED)
            store.save_job(job)
            run = store.get_analysis_run(job.analysis_run_id)
            run.status = "queued"
            run.updated_at = datetime.now(UTC)
            store.save_analysis_run(run)
            background_tasks.add_task(schedule_job, job.id, None, front=front)
            refreshed = store.get_job(job.id)
            content = store.get_content(run.content_id)
            return _job_response(refreshed, content=content)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="job_not_found") from error
        except InvalidTransitionError as error:
            raise HTTPException(status_code=409, detail="job_not_resumable") from error

    @app.get("/api/v1/jobs/{job_id}", response_model=JobResponse)
    def get_job(job_id: str) -> JobResponse:
        try:
            job = store.get_job(job_id)
            try:
                run = store.get_analysis_run(job.analysis_run_id)
                content = store.get_content(run.content_id)
            except LookupError:
                content = None
            return _job_response(job, content=content)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="job_not_found") from error

    @app.delete("/api/v1/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_job(job_id: str) -> Response:
        try:
            job = store.get_job(job_id)
            app.state.job_queue.remove(job_id)
            store.delete_job(job_id)
            cleanup_job_artifacts(job)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="job_not_found") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get(
        "/api/v1/jobs/{job_id}/events",
        response_model=list[TaskEventResponse],
    )
    def list_job_events(
        job_id: str,
        after_sequence: int = Query(default=0, ge=0),
        limit: int = Query(default=200, ge=1, le=500),
    ) -> list[TaskEventResponse]:
        try:
            store.get_job(job_id)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="job_not_found") from error
        return [
            _task_event_response(event)
            for event in store.list_job_events(
                job_id,
                after_sequence=after_sequence,
                limit=limit,
            )
        ]

    @app.get(
        "/api/v1/jobs/{job_id}/diagnostics",
        response_model=DiagnosticResponse,
    )
    def get_job_diagnostics(job_id: str) -> DiagnosticResponse:
        try:
            job = store.get_job(job_id)
            run = store.get_analysis_run(job.analysis_run_id)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="job_not_found") from error
        events = store.list_job_events(job_id, limit=200)
        return DiagnosticResponse(
            **build_diagnostic_report(job, run, APP_VERSION, events=events)
        )

    @app.get("/api/v1/jobs/{job_id}/diagnostics/export")
    def export_job_diagnostics(job_id: str) -> Response:
        try:
            job = store.get_job(job_id)
            run = store.get_analysis_run(job.analysis_run_id)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="job_not_found") from error
        events = store.list_job_events(job_id, limit=200)
        payload = build_diagnostic_report(job, run, APP_VERSION, events=events)
        return Response(
            content=json.dumps(payload, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="diagnostic-{job_id}.json"'
            },
        )

    @app.post(
        "/api/v1/jobs/{job_id}/feedback",
        response_model=TaskFeedbackResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_job_feedback(
        job_id: str, request: TaskFeedbackRequest
    ) -> TaskFeedbackResponse:
        try:
            job = store.get_job(job_id)
            run = store.get_analysis_run(job.analysis_run_id)
            feedback = store.create_job_feedback(
                job_id,
                content_id=run.content_id,
                category=request.category,
                note=request.note,
                context=sanitize_context(job, run, APP_VERSION),
            )
        except ContentNotFoundError as error:
            raise HTTPException(status_code=404, detail="content_not_found") from error
        except LookupError as error:
            raise HTTPException(status_code=404, detail="job_not_found") from error
        return _task_feedback_response(feedback)

    @app.get(
        "/api/v1/jobs/{job_id}/feedback",
        response_model=list[TaskFeedbackResponse],
    )
    def list_job_feedback(job_id: str) -> list[TaskFeedbackResponse]:
        try:
            store.get_job(job_id)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="job_not_found") from error
        return [_task_feedback_response(item) for item in store.list_job_feedback(job_id)]

    @app.post("/api/v1/jobs/{job_id}/cancel", response_model=JobResponse)
    def cancel_job(job_id: str) -> JobResponse:
        try:
            job = store.get_job(job_id)
            app.state.job_queue.remove(job_id)
            job.metadata.pop("last_stable_checkpoint", None)
            job.metadata.pop("resume_checkpoint", None)
            job.transition(JobState.CANCELLED)
            store.clear_asr_checkpoints(job.id)
            store.save_job(job)
            cleanup_job_artifacts(job)
            run = store.get_analysis_run(job.analysis_run_id)
            run.status = "cancelled"
            run.updated_at = datetime.now(UTC)
            store.save_analysis_run(run)
            content = store.get_content(run.content_id)
            return _job_response(job, content=content)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="job_not_found") from error
        except InvalidTransitionError as error:
            raise HTTPException(status_code=409, detail="job_not_cancellable") from error

    @app.post("/api/v1/jobs/{job_id}/retry", response_model=ImportResponse)
    def retry_job(job_id: str, background_tasks: BackgroundTasks) -> ImportResponse:
        try:
            previous_job = store.get_job(job_id)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="job_not_found") from error
        if previous_job.state not in {JobState.FAILED, JobState.CANCELLED}:
            raise HTTPException(status_code=409, detail="job_not_retryable")
        previous_run = store.get_analysis_run(previous_job.analysis_run_id)
        previous_content = store.get_content(previous_run.content_id)
        source_path = previous_job.metadata.get("source_path")
        source_url = previous_job.metadata.get("source_url")
        try:
            if previous_job.metadata.get("scan_import"):
                source = PreparedSource(
                    kind=previous_content.kind, title=previous_content.title,
                    transcript=None, content_hash=previous_content.content_hash,
                    source_path=None, source_url=source_url, acquisition_method="queued_link",
                    platform=previous_content.source.platform,
                    thumbnail_url=previous_content.source.thumbnail_url,
                    author=previous_content.source.author,
                    duration_seconds=previous_content.duration_seconds,
                )
            elif isinstance(source_path, str):
                source = prepare_local_import(
                    source_path=source_path,
                    text=None,
                    title=previous_content.title,
                    language=previous_run.settings_snapshot.get("language"),
                )
            elif isinstance(source_url, str):
                _preflight_link_connection(store, source_url)
                prepared_sources = _prepare_link_sources(
                    url=source_url,
                    title=None,
                    language=previous_run.settings_snapshot.get("language"),
                    bilibili_cookie=_bilibili_cookie(store),
                    asr_configured=_asr_is_configured(store, app.state.asr_model_root),
                )
                source = next(
                    (candidate for candidate in prepared_sources if candidate.source_url == source_url),
                    None,
                )
                if source is None:
                    raise LinkImportError("无法定位需要重试的 P 视频")
                source = replace(source, title=previous_content.title)
            else:
                raise HTTPException(status_code=409, detail="retry_source_unavailable")
        except (LocalImportError, LinkImportError) as error:
            _sync_bilibili_error_status(store, source_url, error)
            raise HTTPException(status_code=422, detail=str(error)) from error
        if source.acquisition_method != "queued_link":
            _require_asr_for_untitled_source(store, source, app.state.asr_model_root)
        retry_summary = _summary_settings_snapshot(
            store,
            app.state.skills_root,
            strict_skill=False,
        )
        retry_config = dict(retry_summary["summary_config"])
        retry_model = str(retry_config["model"])
        retry_provider = str(retry_summary["summary_provider"])
        settings = AnalysisSettings(
            model=retry_model,
            language=previous_run.settings_snapshot.get("language"),
            strength=SummaryStrength(
                previous_run.settings_snapshot.get("strength", SummaryStrength.STANDARD.value)
            ),
            prompt_version=str(retry_summary["prompt_version"]),
            asr_engine=previous_run.settings_snapshot.get("asr_engine"),
            asr_config=previous_run.settings_snapshot.get("asr_config"),
            max_chunk_tokens=int(previous_run.settings_snapshot["max_chunk_tokens"]),
            summary_engine=SUMMARY_ENGINE_OPENAI,
            summary_provider=retry_provider,
            summary_style=previous_run.settings_snapshot.get("summary_style", "general"),
            summary_template=str(
                previous_run.settings_snapshot.get("summary_template")
                or DEFAULT_SUMMARY_TEMPLATE
            ),
            summary_config=retry_config,
            summary_prompt=retry_summary["summary_prompt"],
            summary_prompt_hash=retry_summary["summary_prompt_hash"],
            summary_skill=retry_summary["summary_skill"],
        )
        # R8：断点可用性 = 白名单 + 24 小时有效期 + 产物可读 + 配置兼容。
        # 元数据说可续跑但文件缺失时逐级降级（summary→chunks→transcript），
        # 都不满足才从头取源，避免「转写被删却判 fresh」的假续跑。
        resumable_checkpoints = ("transcript_ready", "chunks_ready", "summary_ready")
        stored_resume_checkpoint = previous_job.metadata.get("resume_checkpoint")
        resume_checkpoint = (
            stored_resume_checkpoint
            if isinstance(stored_resume_checkpoint, str)
            else previous_job.checkpoint
        )
        resume_checkpoint_saved_at = previous_job.metadata.get("checkpoint_saved_at")
        resume_checkpoint_dir = previous_job.metadata.get("checkpoint_dir")
        resume_is_fresh = False
        if resume_checkpoint in resumable_checkpoints and isinstance(
            resume_checkpoint_saved_at, str
        ):
            try:
                saved_at = datetime.fromisoformat(resume_checkpoint_saved_at.replace("Z", "+00:00"))
                if saved_at.tzinfo is None:
                    saved_at = saved_at.replace(tzinfo=UTC)
                within_24h = (datetime.now(UTC) - saved_at).total_seconds() <= 24 * 60 * 60
            except ValueError:
                within_24h = False
            fingerprint = previous_job.metadata.get("checkpoint_config_fingerprint")
            fingerprint_ok = (
                fingerprint is None  # 老任务无指纹，沿用其历史行为
                or fingerprint == _resume_checkpoint_fingerprint(settings)
            )
            if within_24h and fingerprint_ok:
                start = resumable_checkpoints.index(resume_checkpoint)
                for candidate in resumable_checkpoints[start:]:
                    if _checkpoint_files_readable(resume_checkpoint_dir, candidate):
                        resume_checkpoint = candidate
                        resume_is_fresh = True
                        break
        if not resume_is_fresh:
            workflow.discard_checkpoints(previous_job)
            resume_checkpoint = None
            resume_checkpoint_dir = None
            resume_checkpoint_saved_at = None
        content, run, job = workflow.submit(
            source,
            settings,
            content_id=previous_content.id,
            archive_group=previous_job.metadata.get("archive_batch_name"),
            import_batch_id=previous_job.metadata.get("import_batch_id"),
            archive_index=previous_job.metadata.get("archive_item_number"),
            archive_total=previous_job.metadata.get("archive_total"),
            resume_checkpoint=resume_checkpoint,
            resume_progress=previous_job.progress if resume_checkpoint else 0,
            resume_checkpoint_dir=resume_checkpoint_dir if resume_checkpoint else None,
            resume_checkpoint_saved_at=resume_checkpoint_saved_at if resume_checkpoint else None,
        )
        if previous_job.metadata.get("scan_import"):
            job.metadata["scan_import"] = True
            job.metadata["deferred_link"] = not resume_is_fresh
        season_metadata = _season_metadata_for_content(store, previous_content.id)
        if season_metadata:
            _set_season_metadata(job, season_metadata)
        if previous_job.metadata.get("scan_import") or season_metadata:
            store.save_job(job)
        background_tasks.add_task(schedule_job, job.id, source.transcript)
        return ImportResponse(
            content=_content_response(content),
            run=_run_response(run),
            job=_job_response(job, content=content),
        )

    @app.post(
        "/api/v1/contents/{content_id}/resummarize",
        response_model=ImportResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def resummarize_content(
        content_id: str,
        request: ResummarizeRequest,
        background_tasks: BackgroundTasks,
    ) -> ImportResponse:
        """Create a brand-new content/job pair from the original source."""

        if request.favorite_folder_ids and not request.classify:
            raise HTTPException(status_code=422, detail="未选择归类时不能指定收藏夹")
        if request.classify:
            if not (request.category or "").strip() and not request.tag_ids:
                raise HTTPException(status_code=422, detail="选择归类后必须填写分类或选择标签")
            if not request.favorite_folder_ids:
                raise HTTPException(status_code=422, detail="选择归类后必须选择或创建收藏夹")
            if request.tag_ids:
                known_tags = {tag.id for tag in store.list_tags()}
                if set(request.tag_ids) - known_tags:
                    raise HTTPException(status_code=404, detail="tag_not_found")
            known_folders = {folder.id for folder in store.list_favorite_folders()}
            if set(request.favorite_folder_ids) - known_folders:
                raise HTTPException(status_code=404, detail="favorite_folder_not_found")

        try:
            previous = store.get_history_entry(content_id)
        except ContentNotFoundError as error:
            raise HTTPException(status_code=404, detail="content_not_found") from error
        source_path = previous.job.metadata.get("source_path")
        source_url = previous.job.metadata.get("source_url")
        try:
            if isinstance(source_path, str) and source_path.strip():
                source = prepare_local_import(
                    source_path=source_path,
                    text=None,
                    title=previous.content.title,
                    language=request.language or previous.content.language,
                )
            elif isinstance(source_url, str) and source_url.strip():
                _preflight_link_connection(store, source_url)
                prepared = _prepare_link_sources(
                    url=source_url,
                    title=None,
                    language=request.language or previous.content.language,
                    bilibili_cookie=_bilibili_cookie(store),
                    asr_configured=_asr_is_configured(store, app.state.asr_model_root),
                )
                source = next(
                    (candidate for candidate in prepared if candidate.source_url == source_url),
                    prepared[0] if prepared else None,
                )
                if source is None:
                    raise LinkImportError("无法定位原始来源，不能重新总结")
                source = replace(source, title=previous.content.title)
            else:
                # Pasted text has no filesystem path or external URL. Its
                # original transcript is already persisted with the archived
                # content, so rebuild only from that source text—not from the
                # previous summary.
                transcript_text = store.get_transcript_text(content_id)
                if not transcript_text or not transcript_text.strip():
                    raise HTTPException(status_code=409, detail="resummarize_source_unavailable")
                source = prepare_local_import(
                    source_path=None,
                    text=transcript_text,
                    title=previous.content.title,
                    language=request.language or previous.content.language,
                )
            _require_asr_for_untitled_source(store, source, app.state.asr_model_root)
            settings = _analysis_settings_from_store(
                store,
                app.state.skills_root,
                model=None,
                language=request.language or previous.content.language,
                asr_engine=store.get_setting("asr_engine") or "cloud",
                max_chunk_tokens=request.max_chunk_tokens,
                summary_template=request.summary_template,
                summary_style=request.summary_style,
                strength=request.strength,
                extra_instruction=request.extra_instruction,
            )
            if request.reuse_content:
                # 11-23：内容详情的重新总结复用原内容，跑完在原内容下生成 V2；
                # 仍从原始来源重建，不读上一版总结正文，也不加「（N）」副本后缀。
                content, run, job = workflow.submit(
                    source, settings, content_id=content_id, priority=request.priority
                )
            else:
                duplicate = store.find_duplicate_content(
                    canonical_url=source.source_url,
                    content_hash=source.content_hash,
                )
                if duplicate is not None:
                    source = _source_with_duplicate_title(store, source, duplicate, "regenerate")
                content, run, job = workflow.submit(source, settings, priority=request.priority)
            season_metadata = _season_metadata_for_content(store, previous.content.id)
            if season_metadata:
                _set_season_metadata(job, season_metadata)
                store.save_job(job)
            if request.classify:
                content = store.update_content(
                    content.id,
                    category=request.category.strip() if request.category else None,
                    tag_ids=request.tag_ids or None,
                    favorite_folder_ids=request.favorite_folder_ids,
                )
        except (LocalImportError, LinkImportError) as error:
            _sync_bilibili_error_status(store, source_url, error)
            raise HTTPException(status_code=422, detail=str(error)) from error
        except SummaryConfigurationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        background_tasks.add_task(schedule_job, job.id, source.transcript)
        return ImportResponse(
            content=_content_response(
                content,
                favorite_folder_ids=store.favorite_folder_ids(content.id),
                tag_ids=store.tag_ids(content.id),
                tag_names=store.tag_names(content.id),
            ),
            run=_run_response(run),
            job=_job_response(job, content=content),
        )

    @app.get("/api/v1/history/count")
    def count_history() -> dict[str, int]:
        return {"total": store.count_archived_contents()}

    @app.get("/api/v1/history", response_model=list[HistoryEntryResponse])
    def list_history(
        q: str | None = Query(default=None, max_length=200),
        category: str | None = Query(default=None, max_length=120),
        platform: str | None = Query(default=None, max_length=32),
        author: str | None = Query(default=None, max_length=200),
        favorite_folder_id: str | None = Query(default=None, max_length=80),
        tag_id: str | None = Query(default=None, max_length=80),
        archived_only: bool = Query(default=False),
        sort_by: str = Query(default="created_at", pattern="^(created_at|updated_at)$"),
        order: str = Query(default="desc", pattern="^(asc|desc)$"),
        # R9：归档取数一次取全，避免知识库在 50 条处截断；默认值仍是 50。
        limit: int = Query(default=50, ge=1, le=2000),
        offset: int = Query(default=0, ge=0),
    ) -> list[HistoryEntryResponse]:
        return [
            _history_response(
                entry,
                favorite_folder_ids=store.favorite_folder_ids(entry.content.id),
                tag_ids=store.tag_ids(entry.content.id),
                tag_names=store.tag_names(entry.content.id),
            )
            for entry in store.list_history(
                q,
                category=category,
                platform=platform,
                author=author,
                favorite_folder_id=favorite_folder_id,
                tag_id=tag_id,
                archived_only=archived_only,
                sort_by=sort_by,
                descending=order == "desc",
                limit=limit if archived_only else None,
                offset=offset if archived_only else 0,
            )
        ]

    @app.get(
        "/api/v1/content-introductions/backfill/preview",
        response_model=IntroductionBackfillPreviewResponse,
    )
    def preview_introduction_backfill() -> IntroductionBackfillPreviewResponse:
        candidates, no_summary_ids = _introduction_backfill_candidates(store)
        return IntroductionBackfillPreviewResponse(
            eligible_count=len(candidates),
            no_summary_count=len(no_summary_ids),
            content_ids=[entry.content.id for entry in candidates],
        )

    @app.post(
        "/api/v1/content-introductions/backfill",
        response_model=IntroductionBackfillResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def start_introduction_backfill(
        request: IntroductionBackfillStartRequest,
    ) -> IntroductionBackfillResponse:
        candidates, no_summary_ids = _introduction_backfill_candidates(
            store,
            request.content_ids or None,
        )
        content_ids = [entry.content.id for entry in candidates]
        run_id = new_id("introduction-backfill")
        items = {
            content_id: {"status": "pending"}
            for content_id in content_ids
        }
        items.update(
            {
                content_id: {
                    "status": "skipped",
                    "message": "没有有效正文总结，已跳过",
                }
                for content_id in no_summary_ids
            }
        )
        record: dict[str, object] = {
            "run_id": run_id,
            "status": "queued" if content_ids else "completed",
            "content_ids": content_ids,
            "items": items,
        }
        with app.state.introduction_backfill_lock:
            app.state.introduction_backfills[run_id] = record
        if content_ids:
            Thread(
                target=run_introduction_backfill,
                args=(run_id,),
                name=run_id,
                daemon=True,
            ).start()
        return _introduction_backfill_response(record)

    @app.get(
        "/api/v1/content-introductions/backfill/{run_id}",
        response_model=IntroductionBackfillResponse,
    )
    def get_introduction_backfill(run_id: str) -> IntroductionBackfillResponse:
        with app.state.introduction_backfill_lock:
            record = app.state.introduction_backfills.get(run_id)
            if record is None:
                raise HTTPException(status_code=404, detail="introduction_backfill_not_found")
            return _introduction_backfill_response(record)

    @app.get("/api/v1/contents/{content_id}/export")
    def export_content(
        content_id: str,
        format: str = Query(default="markdown", pattern="^(markdown|text|subtitle|json)$"),
    ) -> Response:
        try:
            payload, extension, media_type = _content_export(store, content_id, format)
        except ContentNotFoundError as error:
            raise HTTPException(status_code=404, detail="content_not_found") from error
        except LookupError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        filename = f"content-{content_id}.{extension}"
        return Response(
            content=payload,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.post("/api/v1/contents/export")
    def export_contents(request: ContentExportRequest) -> Response:
        archive = io.BytesIO()
        try:
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
                for content_id in request.ids:
                    payload, extension, _media_type = _content_export(
                        store, content_id, request.format
                    )
                    bundle.writestr(f"content-{content_id}.{extension}", payload)
        except ContentNotFoundError as error:
            raise HTTPException(status_code=404, detail="content_not_found") from error
        except LookupError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return Response(
            content=archive.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": "attachment; filename=content-export.zip"},
        )
    @app.get("/api/v1/contents/{content_id}/result", response_model=AnalysisResultResponse)
    def get_analysis_result(content_id: str) -> AnalysisResultResponse:
        try:
            entry = store.get_history_entry(content_id)
        except ContentNotFoundError as error:
            raise HTTPException(status_code=404, detail="content_not_found") from error
        archive_path = entry.job.metadata.get("archive_path")
        if entry.job.state is not JobState.COMPLETED or not isinstance(archive_path, str):
            raise HTTPException(status_code=409, detail="result_not_ready")
        directory = Path(archive_path)
        index_path = directory / "index.md"
        record_path = directory / "record.json"
        if not index_path.is_file() or not record_path.is_file():
            raise HTTPException(status_code=409, detail="archive_not_available")
        return AnalysisResultResponse(
            content=_content_response(
                entry.content,
                favorite_folder_ids=store.favorite_folder_ids(content_id),
                tag_ids=store.tag_ids(content_id),
                tag_names=store.tag_names(content_id),
            ),
            run=_run_response(entry.run),
            job=_job_response(entry.job, content=entry.content),
            archive_path=str(directory),
            markdown=index_path.read_text(encoding="utf-8"),
            record=json.loads(record_path.read_text(encoding="utf-8")),
            evidence=_result_evidence(directory),
            versions=[
                _summary_version_response(version)
                for version in store.list_summary_versions(content_id)
            ],
            feedback=[
                _summary_feedback_response(item)
                for item in store.list_summary_feedback(content_id)
            ],
            tag_suggestions=[
                TagSuggestionResponse(**item)
                for item in (entry.job.metadata.get("tag_suggestions") or [])
                if isinstance(item, dict) and item.get("name")
            ],
        )

    @app.get(
        "/api/v1/contents/{content_id}/summary-versions",
        response_model=list[SummaryVersionResponse],
    )
    def list_summary_versions(content_id: str) -> list[SummaryVersionResponse]:
        try:
            store.get_content(content_id)
            return [
                _summary_version_response(version)
                for version in store.list_summary_versions(content_id)
            ]
        except ContentNotFoundError as error:
            raise HTTPException(status_code=404, detail="content_not_found") from error

    @app.post(
        "/api/v1/contents/{content_id}/summary-versions/partial",
        response_model=SummaryVersionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_partial_summary(
        content_id: str, request: PartialSummaryRequest
    ) -> SummaryVersionResponse:
        if request.end_seconds <= request.start_seconds:
            raise HTTPException(status_code=422, detail="局部总结结束时间必须大于开始时间")
        try:
            version = workflow.generate_partial_summary(
                content_id,
                start_seconds=request.start_seconds,
                end_seconds=request.end_seconds,
                template=request.template,
                chapter_title=request.chapter_title,
            )
        except ContentNotFoundError as error:
            raise HTTPException(status_code=404, detail="content_not_found") from error
        except LookupError as error:
            raise HTTPException(status_code=404, detail="summary_version_not_found") from error
        except (ValueError, RuntimeError, SummaryProviderError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return _summary_version_response(version)

    @app.get(
        "/api/v1/contents/{content_id}/summary-versions/compare",
        response_model=SummaryVersionCompareResponse,
    )
    def compare_summary_versions(
        content_id: str, left_id: str, right_id: str
    ) -> SummaryVersionCompareResponse:
        try:
            left = store.get_summary_version(left_id)
            right = store.get_summary_version(right_id)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="summary_version_not_found") from error
        if left.content_id != content_id or right.content_id != content_id:
            raise HTTPException(status_code=404, detail="summary_version_not_found")
        diff = "\n".join(
            difflib.unified_diff(
                left.markdown.splitlines(),
                right.markdown.splitlines(),
                fromfile=f"v{left.version_number}",
                tofile=f"v{right.version_number}",
                lineterm="",
            )
        )
        return SummaryVersionCompareResponse(
            left=_summary_version_response(left),
            right=_summary_version_response(right),
            diff=diff,
        )

    @app.put(
        "/api/v1/contents/{content_id}/summary-versions/{version_id}",
        response_model=SummaryVersionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def edit_summary_version(
        content_id: str, version_id: str, request: SummaryVersionUpdateRequest
    ) -> SummaryVersionResponse:
        try:
            parent = store.get_summary_version(version_id)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="summary_version_not_found") from error
        if parent.content_id != content_id:
            raise HTTPException(status_code=404, detail="summary_version_not_found")
        version = store.create_summary_version(
            content_id,
            request.markdown,
            template=parent.template,
            origin="edited",
            parent_version_id=parent.id,
            chapter_title=parent.chapter_title,
            source_start_seconds=parent.source_start_seconds,
            source_end_seconds=parent.source_end_seconds,
            summary_strength=parent.summary_strength,
            summary_style=parent.summary_style,
            material_level=parent.material_level,
            source_version=parent.source_version,
            source_scope=parent.source_scope,
            processed_source_refs=parent.processed_source_refs,
            expected_source_refs=parent.expected_source_refs,
            provider=parent.provider,
            model=parent.model,
            prompt_version=parent.prompt_version,
        )
        return _summary_version_response(version)

    @app.post(
        "/api/v1/contents/{content_id}/feedback",
        response_model=SummaryFeedbackResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_summary_feedback(
        content_id: str, request: SummaryFeedbackRequest
    ) -> SummaryFeedbackResponse:
        try:
            try:
                entry = store.get_history_entry(content_id)
                context = sanitize_context(entry.job, entry.run, APP_VERSION)
            except ContentNotFoundError:
                context = {}
            feedback = store.create_summary_feedback(
                content_id,
                version_id=request.version_id,
                category=request.category,
                note=request.note,
                context=context,
            )
        except ContentNotFoundError as error:
            raise HTTPException(status_code=404, detail="content_not_found") from error
        except LookupError as error:
            raise HTTPException(status_code=404, detail="summary_version_not_found") from error
        return _summary_feedback_response(feedback)

    @app.get("/api/v1/platform-connections", response_model=PlatformConnectionsResponse)
    def list_platform_connections() -> PlatformConnectionsResponse:
        return PlatformConnectionsResponse(
            connections=[
                _platform_connection_response(
                    _connection_or_default(store, definition), definition
                )
                for definition in PLATFORM_DEFINITIONS
            ]
        )

    def _qr_attempt_state(qrcode_key: str) -> str:
        key = qrcode_key.strip()
        with app.state.bilibili_qr_lock:
            attempt = app.state.bilibili_qr_attempts.get(key)
            if attempt is None:
                return "inactive"
            if monotonic() >= float(attempt["expires_at"]):
                app.state.bilibili_qr_attempts.pop(key, None)
                return "expired"
            return "active"

    def _finish_qr_attempt(qrcode_key: str) -> None:
        with app.state.bilibili_qr_lock:
            app.state.bilibili_qr_attempts.pop(qrcode_key.strip(), None)

    def _qr_connection_response(status_value: str, message: str) -> PlatformConnectionResponse:
        definition = get_platform_definition("bilibili")
        assert definition is not None
        connection = _connection_or_default(store, definition)
        return _platform_connection_response(
            replace(connection, status=status_value, message=message), definition
        )

    @app.post(
        "/api/v1/platform-connections/bilibili/qrcode",
        response_model=BilibiliQrCodeResponse,
    )
    def generate_bilibili_qrcode() -> BilibiliQrCodeResponse:
        try:
            qrcode = generate_bilibili_qr_code()
        except LinkImportError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        with app.state.bilibili_qr_lock:
            # Replacing the in-memory token invalidates any late response from
            # an older QR without touching the stable connection record.
            app.state.bilibili_qr_attempts.clear()
            app.state.bilibili_qr_attempts[qrcode.qrcode_key] = {
                "expires_at": monotonic() + max(1, qrcode.expires_in),
            }
        return BilibiliQrCodeResponse(
            qrcode_key=qrcode.qrcode_key,
            login_url=qrcode.login_url,
            qrcode_svg=qrcode.svg,
            expires_in=qrcode.expires_in,
        )


    @app.post(
        "/api/v1/platform-connections/bilibili/qrcode/poll",
        response_model=PlatformConnectionResponse,
    )
    def poll_bilibili_qrcode(
        request: BilibiliQrCodePollRequest,
    ) -> PlatformConnectionResponse:
        attempt_state = _qr_attempt_state(request.qrcode_key)
        if attempt_state == "expired":
            return _qr_connection_response(EXPIRED, "B站登录二维码已过期，请重新生成")
        if attempt_state != "active":
            raise HTTPException(status_code=409, detail="bilibili_qr_attempt_inactive")
        try:
            result = poll_bilibili_qr_code(request.qrcode_key)
        except LinkImportError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        definition = get_platform_definition("bilibili")
        assert definition is not None
        attempt_state = _qr_attempt_state(request.qrcode_key)
        if attempt_state == "expired":
            return _qr_connection_response(EXPIRED, "B站登录二维码已过期，请重新生成")
        if attempt_state != "active":
            raise HTTPException(status_code=409, detail="bilibili_qr_attempt_inactive")
        if result.state in {"WAITING", "SCANNED"}:
            return _qr_connection_response(CHECKING, result.message)
        if result.state == "EXPIRED":
            _finish_qr_attempt(request.qrcode_key)
            return _qr_connection_response(EXPIRED, result.message)
        if result.state == "CONNECTED":
            checked_status, account, message = probe_platform("bilibili", result.cookie)
            verified = checked_status == CONNECTED
            if checked_status == TEMPORARY_ERROR:
                checked_status = CONNECTED
                verified = False
                message = "B站登录已保存，账号信息暂未验证；请稍后手动检查"
            expired = False
            try:
                with app.state.bilibili_qr_lock:
                    attempt_state = _qr_attempt_state(request.qrcode_key)
                    if attempt_state == "expired":
                        expired = True
                    elif attempt_state != "active":
                        raise HTTPException(
                            status_code=409, detail="bilibili_qr_attempt_inactive"
                        )
                    else:
                        # Keep the session write and stable status update in
                        # one critical section after the network probe.  A
                        # cancellation that wins during probe therefore
                        # prevents both durable writes.
                        try:
                            store.save_bilibili_session(result.cookie or "", result.refresh_token)
                        except SecretStorageError:
                            app.state.bilibili_qr_attempts.pop(request.qrcode_key.strip(), None)
                            raise
                        previous = store.get_platform_connection("bilibili")
                        now = datetime.now(UTC)
                        record = store.save_platform_connection(
                            platform="bilibili",
                            status=checked_status,
                            auth_type=definition.auth_type,
                            account_label=account,
                            browser=None,
                            browser_profile=None,
                            login_url=definition.login_url,
                            last_checked_at=(now if verified or checked_status != CONNECTED else None),
                            last_connected_at=(
                                now
                                if checked_status == CONNECTED
                                else previous.last_connected_at if previous else None
                            ),
                            message=(
                                "B站登录已确认，后续链接将复用该会话"
                                if verified
                                else message
                            ),
                        )
                        app.state.bilibili_qr_attempts.pop(request.qrcode_key.strip(), None)
            except SecretStorageError as error:
                raise HTTPException(status_code=503, detail=str(error)) from error
            if expired:
                return _qr_connection_response(EXPIRED, "B站登录二维码已过期，请重新生成")
            return _platform_connection_response(record, definition)
        _finish_qr_attempt(request.qrcode_key)
        return _qr_connection_response(CHECKING, result.message)

    @app.delete(
        "/api/v1/platform-connections/bilibili/qrcode/{qrcode_key}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def cancel_bilibili_qrcode(qrcode_key: str) -> None:
        _finish_qr_attempt(qrcode_key)


    @app.post(
        "/api/v1/platform-connections/{platform}/connect",
        response_model=PlatformConnectionResponse,
    )
    def connect_platform(
        platform: str,
        request: PlatformConnectionConnectRequest,
    ) -> PlatformConnectionResponse:
        definition = get_platform_definition(platform)
        if definition is None:
            raise HTTPException(status_code=404, detail="platform_not_supported")
        if platform == "bilibili":
            raise HTTPException(status_code=409, detail="B站请使用二维码登录")
        if not _is_connectable(definition):
            # P4 硬约束：尚未接入连接通道的平台仍只读、不写库。
            checked_status, _account, message = probe_platform(platform, None)
            stable = store.get_platform_connection(platform) or _connection_or_default(store, definition)
            return _platform_connection_response(
                replace(stable, status=checked_status, message=message), definition
            )
        previous = store.get_platform_connection(platform)
        record = store.save_platform_connection(
            platform=platform,
            status=NOT_CONNECTED,
            auth_type=definition.auth_type,
            account_label=None,
            browser=None,
            browser_profile=request.browser_profile,
            login_url=definition.login_url,
            last_checked_at=None,
            last_connected_at=previous.last_connected_at if previous else None,
            message=f"请在桌面壳内打开{definition.display_name}并完成登录",
        )
        return _platform_connection_response(record, definition)

    @app.post(
        "/api/v1/platform-connections/{platform}/check",
        response_model=PlatformConnectionResponse,
    )
    def check_platform(platform: str) -> PlatformConnectionResponse:
        definition = get_platform_definition(platform)
        if definition is None:
            raise HTTPException(status_code=404, detail="platform_not_supported")
        previous = store.get_platform_connection(platform)
        browser = previous.browser if previous and platform != "bilibili" else None
        profile = previous.browser_profile if previous and platform != "bilibili" else None
        if platform == "bilibili":
            try:
                checked_status, account, message = probe_platform(
                    platform, store.get_bilibili_session_cookie()
                )
            except SecretStorageError as error:
                record = _save_bilibili_status(
                    store,
                    REAUTH_REQUIRED,
                    str(error),
                    account_label=None,
                    last_checked_at=datetime.now(UTC),
                    last_connected_at=None,
                )
                return _platform_connection_response(record, definition)
            if checked_status == TEMPORARY_ERROR:
                stable = previous or _connection_or_default(store, definition)
                return _platform_connection_response(
                    replace(stable, message=message), definition
                )
        elif definition.browser_session_available:
            stable = previous or _connection_or_default(store, definition)
            return _platform_connection_response(
                replace(stable, message=f"请在桌面壳中检查{definition.display_name}登录状态"), definition
            )
        else:
            # 未接入连接通道的平台不写库，仅返回只读 UNSUPPORTED 状态。
            checked_status, account, message = probe_platform(platform, None)
            stable = previous or _connection_or_default(store, definition)
            return _platform_connection_response(
                replace(stable, status=checked_status, message=message), definition
            )
        record = store.save_platform_connection(
            platform=platform,
            status=checked_status,
            auth_type=definition.auth_type,
            account_label=account,
            browser=browser,
            browser_profile=profile,
            login_url=definition.login_url,
            last_checked_at=datetime.now(UTC),
            last_connected_at=(
                datetime.now(UTC) if checked_status == CONNECTED
                else previous.last_connected_at if previous else None
            ),
            message=message,
        )
        return _platform_connection_response(record, definition)

    @app.post(
        "/api/v1/platform-connections/{platform}/browser-login",
        response_model=PlatformConnectionResponse,
    )
    def save_browser_login(
        platform: str,
        request: PlatformBrowserLoginRequest,
    ) -> PlatformConnectionResponse:
        definition = get_platform_definition(platform)
        if definition is None:
            raise HTTPException(status_code=404, detail="platform_not_supported")
        if platform == "bilibili":
            raise HTTPException(status_code=409, detail="bilibili_uses_qrcode_login")
        if not definition.browser_session_available:
            raise HTTPException(status_code=404, detail="platform_not_supported")
        previous = store.get_platform_connection(platform)
        record = store.save_platform_connection(
            platform=platform,
            status=request.status,
            auth_type=definition.auth_type,
            account_label=None,
            browser=None,
            browser_profile=request.browser_profile,
            login_url=definition.login_url,
            last_checked_at=datetime.now(UTC),
            last_connected_at=(
                datetime.now(UTC)
                if request.status == CONNECTED
                else previous.last_connected_at if previous else None
            ),
            message=request.message,
        )
        return _platform_connection_response(record, definition)

    @app.delete("/api/v1/platform-connections/{platform}", status_code=status.HTTP_204_NO_CONTENT)
    def disconnect_platform(platform: str) -> None:
        definition = get_platform_definition(platform)
        if definition is None:
            raise HTTPException(status_code=404, detail="platform_not_supported")
        store.delete_platform_connection(platform)
        if platform == "bilibili":
            store.clear_bilibili_session()
            store.set_setting("bilibili_browser", None)
            store.set_setting("bilibili_browser_profile", None)

    @app.get("/api/v1/settings", response_model=SettingsResponse)
    def get_settings() -> SettingsResponse:
        return _settings_response(
            store,
            app.state.archive_root,
            app.state.asr_model_root,
            app.state.skills_root,
        )

    @app.get("/api/v1/ask/settings", response_model=AskSettingsResponse)
    def get_ask_settings() -> AskSettingsResponse:
        configured = get_rag_service().ask_settings()
        return AskSettingsResponse(
            provider=configured["provider"], api_url=configured["api_url"],
            api_mode=configured["api_mode"], model=configured["model"],
            configured=configured["configured"], api_key_configured=configured["api_key_configured"],
            reuse_summary_config=configured["reuse_summary_config"],
        )

    @app.get("/api/v1/dev/rag/overview", include_in_schema=False)
    def get_rag_developer_overview() -> dict[str, object]:
        service = app.state.rag_service
        settings = (
            service.ask_settings()
            if service is not None
            else RagService.ask_settings_for_store(store)
        )
        index = app.state.ask_index
        embedding_configured = (
            index.vector_configured
            if index is not None
            else bool(store.get_secret_setting(
                "ai_ask_siliconflow_api_key", purpose="AI 问答硅基流动 API Key"
            ))
        )
        text_coverage = index.coverage_snapshot() if index is not None else None
        vector_coverage: dict[str, object] | None = None
        vector_status = "not_configured" if not embedding_configured else "not_initialized"
        if index is not None and index.vector_configured:
            try:
                vector_coverage = index.vector_state_coverage_snapshot()
                vector_status = "state_records_available"
            except AskEmbeddingUnavailableError:
                vector_status = "unavailable"
        chunking_config = getattr(index, "chunking_config", {}) if index is not None else {}
        chunking_snapshot = (
            getattr(index, "chunking_snapshot", lambda: {})() if index is not None else {}
        )
        rebuild_state = app.state.ask_index_backfill_status
        if index is None:
            rebuild_state = {"profile_id": None, "status": "not_initialized"}
        elif (
            not isinstance(rebuild_state, dict)
            or rebuild_state.get("profile_id") != index.profile_id
        ):
            rebuild_state = read_ask_index_backfill_state(index)
        if not isinstance(rebuild_state, dict):
            rebuild_state = {"profile_id": None, "status": "not_initialized"}
        vector_retryable = bool(
            vector_coverage
            and (
                vector_coverage["pending"] > 0
                or vector_coverage["failed"] > 0
                or vector_coverage["errors"]
            )
        )
        total_completed = (
            text_coverage["total_completed"]
            if text_coverage is not None
            else len(store.list_history(archived_only=True, include_deleted=False))
        )
        profile_id = index.profile_id if index is not None else None
        rebuild = {
            "status": rebuild_state.get(
                "status", "not_started" if index is not None else "not_initialized",
            ),
            "profile_id": profile_id,
            "processed": (
                text_coverage["total_completed"] - text_coverage["pending"]
                if text_coverage is not None else 0
            ),
            "total": total_completed,
            "pending": text_coverage["pending"] if text_coverage is not None else total_completed,
            "failed": text_coverage["failed"] if text_coverage is not None else 0,
            "vector_processed": (
                vector_coverage["total_completed"] - vector_coverage["pending"]
                if vector_coverage else None
            ),
            "vector_pending": vector_coverage["pending"] if vector_coverage else None,
            "vector_failed": vector_coverage["failed"] if vector_coverage else None,
            "requested_at": rebuild_state.get("requested_at"),
            "finished_at": rebuild_state.get("finished_at"),
            "result": rebuild_state.get("result"),
            "retryable": total_completed > 0
            and rebuild_state.get("status") != "running"
            and (
                text_coverage is None
                or text_coverage["pending"] > 0
                or text_coverage["failed"] > 0
                or vector_retryable
                or rebuild_state.get("status") in {"not_started", "failed"}
            ),
        }
        return {
            "answer_model": {
                "provider": settings["provider"],
                "model": settings["model"],
                "api_mode": settings["api_mode"],
                "configured": settings["configured"],
                "reuse_summary_config": settings["reuse_summary_config"],
            },
            "retrieval": {
                "configured": embedding_configured,
                "embedding_model": EMBEDDING_MODEL,
                "rerank_model": RERANK_MODEL,
                "rerank_default_enabled": bool(index and index.vector_configured and (
                    service.reranker if service is not None else SiliconFlowRetrieval.from_environment()
                )),
            },
            "chunking": {
                **chunking_snapshot,
                "implementation": chunking_config.get("implementation"),
                "chunk_limit": chunking_config.get("max_chunk_size"),
                "proposal_window_utf8_bytes": (
                    chunking_config.get("proposal_window_utf8_bytes")
                ),
                "embedding_context_limit_tokens": (
                    chunking_config.get("model_context_limit_tokens")
                ),
                "embedding_token_bound_method": chunking_config.get(
                    "embedding_token_bound_method"
                ),
                "fallback_reason": chunking_config.get("fallback_reason"),
            },
            "index": {
                "status": "ready" if index is not None else "not_initialized",
                "profile_id": profile_id,
                "text": text_coverage,
                "vector_status": vector_status,
                "vector": vector_coverage,
                "rebuild": rebuild,
            },
        }

    @app.post(
        "/api/v1/dev/rag/index/rebuild",
        status_code=status.HTTP_202_ACCEPTED,
        include_in_schema=False,
    )
    def start_developer_ask_index_backfill() -> dict[str, str]:
        index = get_ask_index()
        schedule_ask_index_backfill(index, classify_after=False)
        return {"status": "running", "profile_id": index.profile_id}

    def _developer_tag_review_queue() -> list[dict[str, object]]:
        service = get_rag_service()
        result = []
        for candidate in service.rag_store.eligible_tag_reviews(developer_only=True):
            contexts = []
            for context in candidate["contexts"]:
                coverage = service.rag_store.get_coverage(context["content_id"])
                if coverage is None or coverage["source_version"] != context["source_version"]:
                    continue
                hits = service.index.read_chunks(
                    context["source_refs"], content_ids=[context["content_id"]], neighbor_window=0,
                )
                if hits:
                    contexts.append({
                        "content_id": context["content_id"],
                        "source_version": context["source_version"],
                        "topic_ids": context["topic_ids"],
                        "evidence": [{
                            "id": hit.stable_id, "source_ref": hit.source_ref,
                            "source_kind": hit.source_kind, "text": hit.text[:1200],
                        } for hit in hits[:4]],
                    })
            if len({item["content_id"] for item in contexts}) >= 2:
                result.append({**candidate, "contexts": contexts[:5]})
        return result

    @app.get("/api/v1/dev/rag/chunking/samples", include_in_schema=False)
    def list_rag_chunking_samples(
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0, le=100000),
    ) -> dict[str, object]:
        entries = store.list_history(
            archived_only=True, include_deleted=False, limit=limit + 1, offset=offset,
        )
        has_more = len(entries) > limit
        entries = entries[:limit]
        index = get_ask_index()
        states = index.chunking_content_states([entry.content.id for entry in entries])
        return {
            "page": {
                "limit": limit,
                "offset": offset,
                "count": len(entries),
                "has_more": has_more,
            },
            "model": index.chunking_model,
            "items": [{
                "content_id": entry.content.id,
                "title": entry.content.title,
                "created_at": entry.run.created_at.isoformat(),
                "index_status": states.get(entry.content.id, {}).get("index_status"),
                "chunk_count": states.get(entry.content.id, {}).get("chunk_count", 0),
                "chunking": {
                    key: states.get(entry.content.id, {}).get(key)
                    for key in (
                        "status", "model", "calls", "input_bytes", "output_tokens", "error_code",
                        "trace",
                    )
                },
            } for entry in entries],
        }

    @app.post("/api/v1/dev/rag/chunking/backfill", include_in_schema=False)
    def backfill_rag_chunking_samples(
        request: AskChunkingBackfillRequest,
    ) -> dict[str, object]:
        if len(set(request.content_ids)) != len(request.content_ids):
            raise HTTPException(status_code=422, detail="内容 ID 不能重复")
        index = get_ask_index()
        results = []
        for content_id in request.content_ids:
            try:
                entry = store.get_history_entry(content_id)
            except Exception as error:
                raise HTTPException(status_code=404, detail="内容不存在") from error
            if entry.content.deleted_at is not None:
                raise HTTPException(status_code=404, detail="内容不存在")
            has_completed_job, _archive_path = index._latest_completed_archive(content_id)
            if not has_completed_job:
                raise HTTPException(status_code=409, detail="内容没有已完成的归档")
            result = index.sync_latest(content_id, force_rechunk=True)
            state = index.chunking_content_states([content_id]).get(content_id, {})
            results.append({
                "content_id": content_id,
                "status": result.status,
                "chunk_count": result.chunk_count,
                "error_code": result.error_code,
                "vector_status": result.vector_status,
                "vector_error_code": result.vector_error_code,
                "chunking": {
                    key: state.get(key)
                    for key in (
                        "status", "model", "calls", "input_bytes", "output_tokens", "error_code",
                        "trace",
                    )
                },
            })
        return {"results": results}

    @app.get("/api/v1/dev/rag/tag-reviews", include_in_schema=False)
    def list_developer_tag_reviews() -> list[dict[str, object]]:
        return _developer_tag_review_queue()

    @app.post("/api/v1/dev/rag/tag-reviews/{tag_id}", include_in_schema=False)
    def review_developer_tag(tag_id: str, request: DeveloperTagReviewRequest) -> dict[str, object]:
        service = get_rag_service()
        candidate = next((item for item in _developer_tag_review_queue() if item["id"] == tag_id), None)
        if candidate is None:
            raise HTTPException(status_code=409, detail="候选依据已变化或不足，刷新后重试")
        evidence = [
            {
                "content_id": context["content_id"],
                "source_version": context["source_version"],
                "source_refs": [item["id"] for item in context["evidence"]],
                "text": "\n".join(item["text"] for item in context["evidence"]),
            }
            for context in candidate["contexts"]
        ]
        reviewed = service.rag_store.review_developer_candidate(
            tag_id, decision=request.decision, material_evidence=evidence, note=request.note,
        )
        if reviewed is None:
            raise HTTPException(status_code=409, detail="候选状态或审核依据已变化，刷新后重试")
        if request.decision == "approved":
            service.rag_store.promote_eligible_tags()
        tag = next((item for item in service.rag_store.list_detail_tags() if item["id"] == tag_id), None)
        return {"id": tag_id, "decision": request.decision,
                "status": tag["status"] if tag else reviewed["status"]}

    @app.get("/api/v1/dev/rag/graph", include_in_schema=False)
    def get_rag_graph(
        query: str = Query(default="", max_length=100),
        content_id: str | None = Query(default=None, max_length=80),
        facet_id: str | None = Query(default=None, max_length=180),
        limit: int = Query(default=20, ge=1, le=50),
        offset: int = Query(default=0, ge=0, le=100000),
    ) -> dict[str, object]:
        return get_rag_service().rag_store.graph_view(
            query=query, content_id=content_id, facet_id=facet_id, limit=limit, offset=offset,
        )

    @app.put("/api/v1/ask/settings", response_model=AskSettingsResponse)
    def update_ask_settings(request: AskSettingsUpdateRequest) -> AskSettingsResponse:
        if request.reuse_summary_config:
            service = get_rag_service()
            saved = service.ask_settings()
            if not saved["reuse_summary_config"]:
                store.set_setting("ask_reuse_summary_config", "true")
            configured = get_rag_service().ask_settings()
            app.state.rag_service = None
            return AskSettingsResponse(
                provider=configured["provider"], api_url=configured["api_url"],
                api_mode=configured["api_mode"], model=configured["model"],
                configured=configured["configured"], api_key_configured=configured["api_key_configured"],
                reuse_summary_config=True,
            )
        if not request.api_url.strip() or not request.model.strip():
            raise HTTPException(status_code=400, detail="API 地址和模型 ID 不能为空")
        try:
            _validate_summary_api_url(request.api_url, request.api_mode)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        current_key = store.get_secret_setting("ask_api_key", purpose="AI 问答生成模型 API Key")
        api_key = request.api_key.strip() if request.api_key else current_key
        if not api_key:
            raise HTTPException(status_code=400, detail="请填写 AI 问答 API Key")
        store.set_setting("ask_reuse_summary_config", "false")
        store.set_setting("ask_provider", request.provider.strip())
        store.set_setting("ask_api_url", request.api_url.strip())
        store.set_setting("ask_api_mode", request.api_mode)
        store.set_setting("ask_model", request.model.strip())
        if request.api_key and request.api_key.strip():
            store.set_secret_setting("ask_api_key", request.api_key.strip(), purpose="AI 问答生成模型 API Key")
        app.state.rag_service = None
        return get_ask_settings()

    @app.post("/api/v1/ask/settings/check")
    def check_ask_settings(request: AskSettingsUpdateRequest) -> dict[str, object]:
        if request.reuse_summary_config:
            values = get_rag_service().ask_settings()
        else:
            values = {
                "api_url": request.api_url.strip() or store.get_setting("ask_api_url"),
                "api_mode": request.api_mode,
                "model": request.model.strip() or store.get_setting("ask_model"),
                "provider": request.provider,
                "api_key": request.api_key.strip() if request.api_key and request.api_key.strip() else
                    store.get_secret_setting("ask_api_key", purpose="AI 问答生成模型 API Key"),
            }
        if not all(values.get(key) for key in ("api_url", "api_mode", "model", "api_key")):
            raise HTTPException(status_code=400, detail="问答模型配置不完整")
        try:
            from app.knowledge.tool_agent import ACT_SCHEMA, Decision

            _validate_summary_api_url(values["api_url"], values["api_mode"])
            model = OpenAICompatibleSummarizer.for_tool_agent(SummarySettings(
                api_url=values["api_url"], api_mode=values["api_mode"],
                model=values["model"], provider=values["provider"],
                api_key=values["api_key"], timeout_seconds=20,
            ))
            result, _ = model.complete_json(
                "连接测试。仅调用 inspect_scope 一次，参数是空对象，answer 和 citations 留空。",
                ACT_SCHEMA, timeout=20, max_output_tokens=200,
            )
            decision = Decision.model_validate(result)
            if [action.tool for action in decision.actions] != ["inspect_scope"]:
                raise ValueError("模型未返回有效的问答工具决策")
        except (ValueError, SummaryProviderError) as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        return {"ok": True, "message": "问答模型与结构化输出可用"}

    @app.get("/api/v1/ask/catalog")
    def get_ask_catalog() -> dict[str, object]:
        rag_store = get_rag_service().rag_store
        return {"topics": rag_store.list_topics(), "detail_tags": rag_store.list_detail_tags(),
                "catalog_version": rag_store.list_topics()[0]["catalog_version"]}

    @app.get("/api/v1/ask/sessions")
    def list_ask_sessions() -> list[dict[str, object]]:
        return get_rag_service().rag_store.list_sessions()

    @app.post("/api/v1/ask/sessions", status_code=status.HTTP_201_CREATED)
    def create_ask_session(request: AskSessionCreateRequest) -> dict[str, object]:
        service = get_rag_service()
        try:
            scope = service.freeze_scope(request.scope.dict())
        except (ValueError, LookupError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return service.rag_store.create_session(request.title or "新会话", scope)

    @app.get("/api/v1/ask/sessions/{session_id}")
    def get_ask_session(session_id: str) -> dict[str, object]:
        try:
            return get_rag_service().rag_store.get_session(session_id)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="问答会话不存在") from error

    @app.delete("/api/v1/ask/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_ask_session(session_id: str) -> None:
        try:
            get_rag_service().rag_store.delete_session(session_id)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="问答会话不存在") from error

    @app.post("/api/v1/ask/queries", response_model=AskQueryAcceptedResponse,
              status_code=status.HTTP_202_ACCEPTED)
    def submit_ask_query(request: AskQueryRequest) -> AskQueryAcceptedResponse:
        service = get_rag_service()
        rag_store = service.rag_store
        if not service.ask_settings().get("configured"):
            raise HTTPException(status_code=409, detail="请先配置回答模型")
        if request.session_id:
            try:
                session_data = rag_store.get_session(request.session_id)
            except LookupError as error:
                raise HTTPException(status_code=404, detail="问答会话不存在") from error
            try:
                scope = (
                    service.freeze_scope(request.confirmed_scope.dict())
                    if request.confirmed_scope else
                    service.refresh_scope_material_versions(session_data["scope"])
                )
            except (ValueError, LookupError) as error:
                raise HTTPException(status_code=400, detail=str(error)) from error
            session_id = request.session_id
        else:
            try:
                scope = service.freeze_scope(
                    request.confirmed_scope.dict() if request.confirmed_scope else {"kind": "all"}
                )
            except (ValueError, LookupError) as error:
                raise HTTPException(status_code=400, detail=str(error)) from error
            session_id = rag_store.create_session("新会话", scope)["id"]
        query = rag_store.create_query(session_id, request.question.strip(), scope)
        start_ask_worker(query["id"])
        return AskQueryAcceptedResponse(session_id=session_id, query_id=query["id"], status="queued")

    @app.get("/api/v1/ask/queries/{query_id}")
    def get_ask_query(query_id: str) -> dict[str, object]:
        try:
            return get_rag_service().rag_store.get_query(query_id)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="问答任务不存在") from error

    @app.post("/api/v1/ask/queries/{query_id}/cancel")
    def cancel_ask_query(query_id: str) -> dict[str, str]:
        try:
            get_rag_service().rag_store.request_cancel(query_id)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="问答任务不存在") from error
        return {"status": "cancelling"}

    @app.post("/api/v1/ask/queries/{query_id}/continue")
    def continue_ask_query(query_id: str) -> AskQueryAcceptedResponse:
        service = get_rag_service()
        try:
            service.rag_store.resume_query(query_id)
            query = service.rag_store.get_query(query_id)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="问答任务不存在") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        start_ask_worker(query_id)
        return AskQueryAcceptedResponse(session_id=query["session_id"], query_id=query_id, status="queued")

    @app.post("/api/v1/ask/feedback", response_model=AskFeedbackResponse)
    def submit_ask_feedback(request: AskFeedbackRequest) -> AskFeedbackResponse:
        service = get_rag_service()
        try:
            query = service.rag_store.get_query(request.query_id)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="问答任务不存在") from error
        citations = (query.get("result") or {}).get("citations", [])
        cited_content_ids = {item.get("content_id") for item in citations}
        if request.content_id not in cited_content_ids:
            raise HTTPException(status_code=403, detail="反馈内容不在本轮引用范围内")
        valid_tag_ids = service.rag_store.feedback_tag_ids(request.content_id)
        if set(request.detail_tag_ids) - valid_tag_ids:
            raise HTTPException(status_code=400, detail="细标签不属于引用内容")
        saved = service.rag_store.record_answer_feedback(request.query_id, request.helpful)
        for tag_id in request.detail_tag_ids:
            service.rag_store.record_tag_feedback(query_id=request.query_id,
                content_id=request.content_id, tag_id=tag_id, helpful=request.helpful)
        if request.helpful and request.detail_tag_ids:
            start_rag_tag_review()
        return AskFeedbackResponse(saved=saved)

    def _retention_days() -> tuple[int, int]:
        try:
            source_days = max(1, int(store.get_setting("retention_source_days") or "30"))
        except ValueError:
            source_days = 30
        try:
            cache_days = max(1, int(store.get_setting("retention_cache_days") or "7"))
        except ValueError:
            cache_days = 7
        return source_days, cache_days

    @app.get("/api/v1/data-governance", response_model=DataGovernanceResponse)
    def get_data_governance() -> DataGovernanceResponse:
        source_days, cache_days = _retention_days()
        return DataGovernanceResponse(
            **retention_report(
                app.state.archive_root,
                source_days=source_days,
                cache_days=cache_days,
            )
        )

    @app.put("/api/v1/data-governance", response_model=DataGovernanceResponse)
    def update_data_governance(request: DataGovernanceUpdateRequest) -> DataGovernanceResponse:
        store.set_setting("retention_source_days", str(request.source_retention_days))
        store.set_setting("retention_cache_days", str(request.cache_retention_days))
        return DataGovernanceResponse(
            **retention_report(
                app.state.archive_root,
                source_days=request.source_retention_days,
                cache_days=request.cache_retention_days,
            )
        )

    @app.post(
        "/api/v1/data-governance/cleanup",
        response_model=CleanupResponse,
    )
    def cleanup_data(request: CleanupRequest) -> CleanupResponse:
        source_days, cache_days = _retention_days()
        report = cleanup_retention(
            app.state.archive_root,
            source_days=source_days,
            cache_days=cache_days,
            execute=request.execute,
        )
        return CleanupResponse(
            execute=request.execute,
            candidate_count=report["candidate_count"],
            candidate_bytes=report["candidate_bytes"],
            moved=report["moved"],
            trash_root=report["trash_root"],
        )

    @app.post(
        "/api/v1/data-governance/backup",
        response_model=BackupCreateResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def backup_data() -> BackupCreateResponse:
        return BackupCreateResponse(**create_backup(store, app.state.archive_root))

    @app.post(
        "/api/v1/data-governance/restore",
        response_model=BackupRestoreResponse,
    )
    def restore_data(request: BackupRestoreRequest) -> BackupRestoreResponse:
        backup_path = Path(request.path).expanduser().resolve()
        backup_root = (app.state.archive_root / "backups").resolve()
        if backup_root not in backup_path.parents:
            raise HTTPException(status_code=422, detail="backup_path_must_be_in_backup_directory")
        try:
            restored = restore_backup(store, app.state.archive_root, backup_path)
            ask_index = get_ask_index()
            ask_index_backfill = ask_index.backfill()
            ask_index_coverage = ask_index.coverage_snapshot()
            ask_index_vector_coverage = {}
            if ask_index.vector_configured:
                try:
                    ask_index_vector_coverage = ask_index.vector_coverage_snapshot()
                except AskEmbeddingUnavailableError as error:
                    ask_index_vector_coverage = {
                        "status": "unavailable",
                        "error_code": "embedding_unavailable",
                        "message": str(error),
                    }
            logger.info(
                "Q&A indexes reconciled after backup restore: "
                "backfill=%s coverage=%s vector_coverage=%s",
                ask_index_backfill,
                ask_index_coverage,
                ask_index_vector_coverage,
            )
            return BackupRestoreResponse(
                **restored,
                ask_index_backfill=ask_index_backfill,
                ask_index_coverage=ask_index_coverage,
                ask_index_vector_coverage=ask_index_vector_coverage,
            )
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="backup_not_found") from error
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get(
        "/api/v1/settings/summary/skills",
        response_model=list[SummarySkillResponse],
    )
    def get_summary_skills() -> list[SummarySkillResponse]:
        return [_summary_skill_response(document) for document in list_skill_documents(app.state.skills_root)]

    @app.post("/api/v1/settings/summary/skills-root/pick")
    def pick_summary_skills_root() -> dict[str, str | None]:
        try:
            selected = _pick_directory("选择总结 Skill 存储目录")
        except OSError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return {"path": selected}

    @app.get(
        "/api/v1/settings/summary/skills/{skill_path:path}",
        response_model=SummarySkillContentResponse,
    )
    def get_summary_skill(skill_path: str) -> SummarySkillContentResponse:
        try:
            document = load_skill_document(app.state.skills_root, skill_path)
        except SkillFileError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return SummarySkillContentResponse(**document.metadata(), content=document.content)

    @app.post(
        "/api/v1/settings/summary/test",
        response_model=SummaryConnectionTestResponse,
    )
    def test_summary_connection(
        request: SummaryConnectionTestRequest,
    ) -> SummaryConnectionTestResponse:
        try:
            stored_provider = store.get_setting("summary_provider") or SUMMARY_ENGINE_OPENAI
            provider = request.summary_provider or stored_provider
            stored_url = store.get_setting("summary_api_url")
            api_url = request.summary_api_url or stored_url or DEFAULT_SUMMARY_API_URL
            api_mode = request.summary_api_mode or store.get_setting("summary_api_mode")
            api_key = _summary_api_key_for_request(
                store,
                provider=provider,
                api_url=api_url,
                requested_key=request.summary_api_key,
            )
        except SecretStorageError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        try:
            _validate_summary_api_url(api_url, api_mode)
        except SummaryConfigurationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        model = request.summary_model or store.get_setting("summary_model") or DEFAULT_SUMMARY_MODEL
        settings = SummarySettings(
            api_url=api_url,
            api_key=api_key,
            model=model,
            timeout_seconds=DEFAULT_SUMMARY_TIMEOUT_SECONDS,
            api_mode=api_mode,
            provider=provider,
        )
        try:
            OpenAICompatibleSummarizer(settings).test_connection()
        except SummaryProviderError as error:
            raise HTTPException(status_code=422, detail=f"总结服务连接失败：{error}") from error
        try:
            validation_token = _issue_summary_validation_token(
                app,
                provider=provider,
                api_url=api_url,
                api_mode=api_mode,
                model=model,
                api_key=api_key,
            )
        except SummaryConfigurationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return SummaryConnectionTestResponse(
            ok=True,
            message="总结模型连接成功",
            validation_token=validation_token,
        )

    @app.post(
        "/api/v1/settings/summary/models",
        response_model=SummaryModelsResponse,
    )
    def list_summary_models(request: SummaryModelsRequest) -> SummaryModelsResponse:
        try:
            stored_provider = store.get_setting("summary_provider") or SUMMARY_ENGINE_OPENAI
            provider = request.summary_provider or stored_provider
            stored_url = store.get_setting("summary_api_url")
            api_url = request.summary_api_url or stored_url or DEFAULT_SUMMARY_API_URL
            api_mode = request.summary_api_mode or store.get_setting("summary_api_mode")
            api_key = _summary_api_key_for_request(
                store,
                provider=provider,
                api_url=api_url,
                requested_key=request.summary_api_key,
            )
        except SecretStorageError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        try:
            _validate_summary_api_url(api_url, api_mode)
        except SummaryConfigurationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        settings = SummarySettings(
            api_url=api_url,
            api_key=api_key,
            model=DEFAULT_SUMMARY_MODEL,
            timeout_seconds=DEFAULT_SUMMARY_TIMEOUT_SECONDS,
            api_mode=api_mode,
            provider=provider,
        )
        try:
            models = OpenAICompatibleSummarizer(settings).list_models()
        except SummaryModelsUnavailable as error:
            return SummaryModelsResponse(
                ok=True,
                message=str(error),
                models=[],
                models_supported=False,
            )
        except SummaryProviderError as error:
            raise HTTPException(status_code=422, detail=f"总结服务识别失败：{error}") from error
        return SummaryModelsResponse(
            ok=True,
            message="识别成功，请选择总结模型",
            models=list(models),
            models_supported=True,
        )

    @app.post(
        "/api/v1/settings/asr/models",
        response_model=AsrModelsResponse,
    )
    def list_asr_models(request: AsrModelsRequest) -> AsrModelsResponse:
        """Discover ASR models using only the ASR target and credential."""

        try:
            api_url = (
                request.asr_api_url
                or store.get_setting("asr_cloud_api_url")
                or store.get_setting("asr_api_url")
                or DEFAULT_ASR_API_URL
            )
            api_key = _asr_api_key_for_request(store, request.asr_api_key)
        except SecretStorageError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        settings = TranscriptionSettings(
            api_url=api_url,
            api_key=api_key,
            model=DEFAULT_ASR_MODEL,
            provider=(
                request.provider
                or request.asr_provider
                or store.get_setting("asr_provider")
            ),
            timeout_seconds=DEFAULT_ASR_TIMEOUT_SECONDS,
        )
        try:
            models = OpenAICompatibleTranscriber(settings).list_models()
        except AsrModelsUnavailable as error:
            return AsrModelsResponse(
                ok=True,
                message=str(error),
                models=[],
                models_supported=False,
            )
        except AsrProviderError as error:
            raise HTTPException(status_code=422, detail=f"ASR 服务识别失败：{error}") from error
        return AsrModelsResponse(
            ok=True,
            message="识别成功，请选择 ASR 模型",
            models=list(models),
            models_supported=True,
        )

    @app.post(
        "/api/v1/settings/asr/test",
        response_model=AsrConnectionTestResponse,
    )
    def test_asr_connection(
        request: AsrConnectionTestRequest,
    ) -> AsrConnectionTestResponse:
        """Validate a manually selected ASR model without touching summary."""

        try:
            api_url = (
                request.asr_api_url
                or store.get_setting("asr_cloud_api_url")
                or store.get_setting("asr_api_url")
                or DEFAULT_ASR_API_URL
            )
            api_key = _asr_api_key_for_request(store, request.asr_api_key)
        except SecretStorageError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        settings = TranscriptionSettings(
            api_url=api_url,
            api_key=api_key,
            model=(
                request.asr_model
                or store.get_setting("asr_cloud_model")
                or store.get_setting("asr_model")
                or DEFAULT_ASR_MODEL
            ),
            provider=(
                request.provider
                or request.asr_provider
                or store.get_setting("asr_provider")
            ),
            timeout_seconds=DEFAULT_ASR_TIMEOUT_SECONDS,
        )
        try:
            models = OpenAICompatibleTranscriber(settings).list_models()
        except AsrModelsUnavailable as error:
            return AsrConnectionTestResponse(
                ok=True,
                message=f"ASR 接口连接成功，但无法获取模型列表；{error}，可手动保存当前模型",
            )
        except AsrProviderError as error:
            raise HTTPException(status_code=422, detail=f"ASR 服务连接失败：{error}") from error
        if settings.model.strip() not in models:
            raise HTTPException(
                status_code=422,
                detail="当前 ASR 模型不在服务商返回的模型列表中，请重新识别或手动填写有效模型 ID",
            )
        return AsrConnectionTestResponse(ok=True, message="ASR 模型连接成功")

    @app.post("/api/v1/settings/archive-root/pick")
    def pick_archive_root() -> dict[str, str | None]:
        try:
            selected = _pick_archive_directory()
        except OSError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return {"path": selected}

    @app.get("/api/v1/asr/local-models", response_model=LocalAsrModelsResponse)
    def get_local_asr_models() -> LocalAsrModelsResponse:
        with app.state.asr_download_lock:
            downloads = {key: dict(value) for key, value in app.state.asr_downloads.items()}
        with app.state.asr_runtime_install_lock:
            runtime_install = dict(app.state.asr_runtime_install)
        return _local_asr_models_response(
            app.state.asr_model_root,
            downloads,
            runtime_available=local_asr_runtime_available(),
            runtime_install=runtime_install,
        )

    @app.post(
        "/api/v1/asr/local-runtime/install",
        response_model=LocalAsrRuntimeInstallResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def install_local_asr_runtime() -> LocalAsrRuntimeInstallResponse:
        command = _local_asr_runtime_install_command()
        command_text = _local_asr_runtime_command_text(command)
        if local_asr_runtime_available():
            with app.state.asr_runtime_install_lock:
                app.state.asr_runtime_install = {
                    "status": "ready",
                    "progress": 100,
                    "message": "本地 ASR 组件已安装",
                    "error": None,
                }
                runtime_install = dict(app.state.asr_runtime_install)
            return _local_asr_runtime_install_response(runtime_install, command_text)

        with app.state.asr_runtime_install_lock:
            current = dict(app.state.asr_runtime_install)
            if current.get("status") == "installing":
                return _local_asr_runtime_install_response(current, command_text)
            app.state.asr_runtime_install = {
                "status": "installing",
                "progress": 5,
                "message": "正在下载并安装本地 ASR 组件",
                "error": None,
            }

        def update_runtime_install(update: dict[str, object]) -> None:
            with app.state.asr_runtime_install_lock:
                state = dict(app.state.asr_runtime_install)
                state.update(update)
                app.state.asr_runtime_install = state

        def run_runtime_install() -> None:
            try:
                completed = subprocess.run(
                    command,
                    cwd=str(_local_asr_runtime_project_root()),
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=1800,
                    check=False,
                )
                output = "\n".join(
                    part.strip()
                    for part in (completed.stdout, completed.stderr)
                    if part and part.strip()
                )
                if completed.returncode != 0:
                    raise LocalAsrError(
                        "本地 ASR 组件安装失败"
                        + (f"：{output[-1200:]}" if output else "")
                    )
                if not local_asr_runtime_available():
                    raise LocalAsrError("安装命令已完成，但仍未检测到 faster-whisper")
                update_runtime_install(
                    {
                        "status": "ready",
                        "progress": 100,
                        "message": "本地 ASR 组件安装完成",
                        "error": None,
                    }
                )
            except Exception as error:
                update_runtime_install(
                    {
                        "status": "error",
                        "progress": 0,
                        "message": "本地 ASR 组件安装失败",
                        "error": str(error),
                    }
                )

        Thread(
            target=run_runtime_install,
            name="asr-runtime-install",
            daemon=True,
        ).start()
        return _local_asr_runtime_install_response(
            {"status": "installing", "progress": 5, "message": "正在下载并安装本地 ASR 组件"},
            command_text,
        )

    @app.post(
        "/api/v1/asr/local-models/{model_id}/download",
        response_model=LocalAsrModelResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def download_local_asr_model_endpoint(model_id: str) -> LocalAsrModelResponse:
        if get_local_model_definition(model_id) is None:
            raise HTTPException(status_code=404, detail="local_asr_model_not_supported")
        if is_local_model_ready(app.state.asr_model_root, model_id):
            return _local_asr_model_response(
                app.state.asr_model_root,
                model_id,
                {"status": "downloaded", "progress": 100},
                runtime_available=local_asr_runtime_available(),
            )
        if not local_asr_download_available():
            raise HTTPException(status_code=503, detail=local_asr_install_hint())
        with app.state.asr_download_lock:
            current = dict(app.state.asr_downloads.get(model_id, {}))
            if current.get("status") == "downloading":
                return _local_asr_model_response(
                    app.state.asr_model_root,
                    model_id,
                    current,
                    runtime_available=local_asr_runtime_available(),
                )
            initial = {
                "status": "downloading",
                "progress": 0,
                "downloaded_bytes": 0,
                "total_bytes": get_local_model_definition(model_id).estimated_size_bytes,
                "message": "准备下载模型文件",
                "error": None,
            }
            app.state.asr_downloads[model_id] = initial

        def update_download_state(update: dict[str, object]) -> None:
            with app.state.asr_download_lock:
                state = dict(app.state.asr_downloads.get(model_id, {}))
                state.update(update)
                app.state.asr_downloads[model_id] = state

        def run_download() -> None:
            try:
                target = download_local_asr_model(
                    app.state.asr_model_root,
                    model_id,
                    progress=update_download_state,
                )
                validation = validate_local_model(app.state.asr_model_root, model_id)
                if (
                    not validation.ready
                    or target != local_model_path(app.state.asr_model_root, model_id)
                ):
                    raise LocalAsrError(f"模型下载后校验失败：{validation.message}")
                update_download_state(
                    {
                        "status": "downloaded",
                        "progress": 100,
                        "downloaded_bytes": validation.size_bytes,
                        "error": None,
                        "message": "模型下载并校验完成",
                    }
                )
            except Exception as error:
                update_download_state(
                    {
                        "status": "error",
                        "progress": 0,
                        "error": str(error),
                        "message": "模型下载或校验失败",
                    }
                )

        Thread(target=run_download, name=f"asr-download-{model_id}", daemon=True).start()
        return _local_asr_model_response(
            app.state.asr_model_root,
            model_id,
            initial,
            runtime_available=local_asr_runtime_available(),
        )

    @app.post(
        "/api/v1/asr/local-models/discover",
        response_model=LocalAsrModelResponse,
    )
    def discover_local_asr_model(request: LocalAsrModelPathRequest) -> LocalAsrModelResponse:
        scan_path = Path(request.path).expanduser().resolve()
        try:
            candidates = discover_local_asr_models(scan_path)
        except LocalAsrError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if not candidates:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"未找到完整本地模型。扫描范围：{scan_path}；仅检查当前目录、一级子目录以及 "
                    "Hugging Face hub\\models--*\\snapshots\\*，不会扫描整块磁盘；需要同时包含 "
                    "config.json、model.bin、tokenizer.json、vocabulary.txt。"
                ),
            )
        if len(candidates) > 1:
            message = f"扫描到 {len(candidates)} 个完整本地模型，请选择后再导入。"
            return _local_asr_selection_response(
                scan_path,
                candidates,
                message,
                runtime_available=local_asr_runtime_available(),
            )
        candidate = candidates[0]
        return _local_asr_model_response(
            candidate.path.parent,
            candidate.id,
            {"status": "discovered"},
            runtime_available=local_asr_runtime_available(),
            model_path=candidate.path,
            validation=candidate.validation,
            scan_scope=scan_path,
        )

    @app.post(
        "/api/v1/asr/local-models/import",
        response_model=LocalAsrModelResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def import_local_asr_model_endpoint(
        request: LocalAsrModelImportRequest,
    ) -> LocalAsrModelResponse:
        try:
            source, resolved_id, _ = inspect_local_asr_model(
                Path(request.path),
                model_id=request.model_id,
            )
            reused = (
                not request.overwrite
                and is_local_model_ready(app.state.asr_model_root, resolved_id)
            )
            target = import_local_asr_model(
                app.state.asr_model_root,
                source,
                model_id=resolved_id,
                overwrite=request.overwrite,
                move_source=request.move_source,
            )
            model_id = target.name
            validation = validate_local_model(app.state.asr_model_root, model_id)
        except LocalAsrError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return _local_asr_model_response(
            app.state.asr_model_root,
            model_id,
            {"status": "reused" if reused else "imported"},
            runtime_available=local_asr_runtime_available(),
            model_path=target,
            validation=validation,
            imported=True,
            reused=reused,
        )

    @app.post(
        "/api/v1/asr/local-models/{model_id}/validate",
        response_model=LocalAsrModelResponse,
    )
    def validate_local_asr_model_endpoint(model_id: str) -> LocalAsrModelResponse:
        try:
            validation = validate_local_model(app.state.asr_model_root, model_id)
        except LocalAsrError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return _local_asr_model_response(
            app.state.asr_model_root,
            model_id,
            {},
            runtime_available=local_asr_runtime_available(),
            validation=validation,
        )

    @app.post(
        "/api/v1/asr/local-models/{model_id}/update-check",
        response_model=LocalAsrModelResponse,
    )
    def check_local_asr_model_update(model_id: str) -> LocalAsrModelResponse:
        try:
            update = check_local_model_update(app.state.asr_model_root, model_id)
            validation = validate_local_model(app.state.asr_model_root, model_id)
        except LocalAsrError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return _local_asr_model_response(
            app.state.asr_model_root,
            model_id,
            update,
            runtime_available=local_asr_runtime_available(),
            validation=validation,
        )

    @app.delete(
        "/api/v1/asr/local-models/{model_id}",
        response_model=LocalAsrModelResponse,
    )
    def remove_local_asr_model_endpoint(model_id: str) -> LocalAsrModelResponse:
        try:
            trash_path = remove_local_asr_model(app.state.asr_model_root, model_id)
            validation = validate_local_model(app.state.asr_model_root, model_id)
        except LocalAsrError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        if _local_asr_model(store) == model_id:
            store.set_setting("asr_local_model", LOCAL_ASR_MODEL_CLEARED)
        return _local_asr_model_response(
            app.state.asr_model_root,
            model_id,
            {"status": "moved_to_trash", "trash_path": str(trash_path)},
            runtime_available=local_asr_runtime_available(),
            validation=validation,
        )
    @app.put("/api/v1/settings", response_model=SettingsResponse)
    def update_settings(request: SettingsUpdateRequest) -> SettingsResponse:
        provided = request.model_fields_set
        asr_cloud_fields = {
            "asr_engine",
            "asr_provider",
            "asr_api_url",
            "asr_api_key",
            "asr_model",
        }
        asr_cloud_update_requested = bool(provided.intersection(asr_cloud_fields))
        copied_asr_api_key: str | None = None
        if request.copy_summary_key:
            if not asr_cloud_update_requested or request.asr_engine == "local":
                raise HTTPException(
                    status_code=422,
                    detail="copy_summary_key 仅可用于云端 ASR 配置更新",
                )
            try:
                copied_asr_api_key = store.get_secret_setting(
                    "summary_api_key",
                    purpose="总结模型 API Key",
                )
            except SecretStorageError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
            if not copied_asr_api_key:
                raise HTTPException(
                    status_code=422,
                    detail="未保存总结 API Key，无法复制到云端 ASR",
                )
        selected_skills_root = app.state.skills_root
        if "summary_skills_root" in provided:
            if request.summary_skills_root:
                try:
                    selected_skills_root = _prepare_summary_skills_root(request.summary_skills_root)
                except OSError as error:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Skill 存储目录不可用：{error}",
                    ) from error
            else:
                selected_skills_root = app.state.default_skills_root
        summary_validation_fields = {
            "summary_provider",
            "summary_api_url",
            "summary_api_mode",
            "summary_api_key",
            "summary_model",
        }
        summary_configuration_provided = provided.intersection(summary_validation_fields)
        candidate_summary_api_url = (
            request.summary_api_url
            if "summary_api_url" in provided
            else store.get_setting("summary_api_url") or DEFAULT_SUMMARY_API_URL
        )
        candidate_summary_api_mode = (
            request.summary_api_mode
            if "summary_api_mode" in provided
            else store.get_setting("summary_api_mode")
        )
        candidate_summary_provider = (
            request.summary_provider
            if "summary_provider" in provided
            else store.get_setting("summary_provider") or SUMMARY_ENGINE_OPENAI
        )
        # A Prompt-only patch is deliberately independent from the external API
        # configuration.  It must not validate the target or consume a model
        # validation token just to persist summary_prompt.
        summary_clear_requested = _summary_clear_requested(request, provided)
        if summary_configuration_provided and candidate_summary_api_url:
            try:
                _validate_summary_api_url(candidate_summary_api_url, candidate_summary_api_mode)
            except SummaryConfigurationError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
            stored_key_present = bool(store.get_setting("summary_api_key"))
            target_changed = not _summary_config_identity_matches(
                store,
                provider=str(candidate_summary_provider or SUMMARY_ENGINE_OPENAI),
                api_url=candidate_summary_api_url,
            )
            if (
                stored_key_present
                and target_changed
                and not summary_clear_requested
                and not (request.summary_api_key or "").strip()
            ):
                raise HTTPException(
                    status_code=422,
                    detail="切换总结服务商或地址后必须重新填写 API Key",
                )
        if summary_configuration_provided and not summary_clear_requested:
            effective_provider = str(
                request.summary_provider
                or store.get_setting("summary_provider")
                or SUMMARY_ENGINE_OPENAI
            )
            effective_model = (
                request.summary_model
                if "summary_model" in provided
                else store.get_setting("summary_model")
            )
            try:
                effective_api_key = _summary_api_key_for_request(
                    store,
                    provider=effective_provider,
                    api_url=candidate_summary_api_url or "",
                    requested_key=request.summary_api_key,
                )
                expected_fingerprint = _summary_validation_fingerprint(
                    provider=effective_provider,
                    api_url=candidate_summary_api_url or "",
                    api_mode=candidate_summary_api_mode,
                    model=effective_model or "",
                    api_key=effective_api_key,
                )
            except (SecretStorageError, SummaryConfigurationError) as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
            _consume_summary_validation_token(
                app,
                request.summary_validation_token,
                expected_fingerprint,
            )
        selected_skill_path: str | None = None
        if "summary_skill_path" in provided and request.summary_skill_path:
            try:
                selected_skill_path = load_skill_document(
                    selected_skills_root,
                    request.summary_skill_path,
                ).path
            except SkillFileError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error

        summary_values: dict[str, str | None] = {}
        if "summary_engine" in provided:
            summary_values["summary_engine"] = SUMMARY_ENGINE_OPENAI
        if "summary_provider" in provided:
            summary_values["summary_provider"] = request.summary_provider
        if "summary_api_url" in provided:
            summary_values["summary_api_url"] = request.summary_api_url
        if "summary_api_mode" in provided:
            summary_values["summary_api_mode"] = request.summary_api_mode
        if "summary_model" in provided:
            summary_values["summary_model"] = request.summary_model
        if "summary_prompt" in provided:
            summary_values["summary_prompt"] = request.summary_prompt
        if "summary_skills_root" in provided:
            summary_values["summary_skills_root"] = (
                str(selected_skills_root) if request.summary_skills_root else None
            )
        if "summary_skill_path" in provided:
            summary_values["summary_skill_path"] = selected_skill_path
        # R4：清除总结密钥时同步清除已选总结模型，避免密钥没了模型还留着。
        if request.clear_secret_provider == "summary":
            summary_values["summary_model"] = None
        if "archive_root" in provided:
            try:
                selected_archive_root = _prepare_archive_root(request.archive_root)
            except OSError as error:
                raise HTTPException(status_code=422, detail=f"归档位置不可用：{error}") from error
            store.set_setting("archive_root", str(selected_archive_root))
            app.state.archive_root = selected_archive_root
            workflow.archive_root = selected_archive_root
        if "bilibili_browser" in provided or "bilibili_browser_profile" in provided:
            # Legacy clients may still send these fields; the QR flow owns auth now.
            store.set_setting("bilibili_browser", None)
            store.set_setting("bilibili_browser_profile", None)
        asr_engine = request.asr_engine if "asr_engine" in provided else None
        if "asr_local_model" in provided:
            # Keep an explicit marker so legacy cloud models are not reused.
            store.set_setting("asr_local_model", request.asr_local_model or LOCAL_ASR_MODEL_CLEARED)
        if asr_engine == "local":
            model_id = request.asr_model if "asr_model" in provided else _local_asr_model(store)
            if not local_asr_runtime_available():
                raise HTTPException(status_code=422, detail="本地 ASR 组件尚未安装，请先安装本地组件后重试")
            if not model_id or not is_local_model_ready(app.state.asr_model_root, model_id):
                raise HTTPException(status_code=422, detail="请先下载并选择一个可用的本地 ASR 模型")
            store.set_setting("asr_engine", "local")
            store.set_setting("asr_local_model", model_id)
        else:
            if asr_engine == "cloud":
                store.set_setting("asr_engine", "cloud")
            if "asr_provider" in provided:
                store.set_setting("asr_provider", request.asr_provider)
            if "asr_api_url" in provided:
                store.set_setting("asr_cloud_api_url", request.asr_api_url)
                store.set_setting("asr_api_url", request.asr_api_url)
            if copied_asr_api_key is not None:
                try:
                    store.set_secret_setting(
                        "asr_cloud_api_key",
                        copied_asr_api_key,
                        purpose="云端 ASR API Key",
                    )
                    store.set_secret_setting(
                        "asr_api_key",
                        copied_asr_api_key,
                        purpose="云端 ASR API Key",
                    )
                except SecretStorageError as error:
                    raise HTTPException(status_code=422, detail=str(error)) from error
            elif "asr_api_key" in provided:
                try:
                    for key in ("asr_cloud_api_key", "asr_api_key"):
                        store.set_secret_setting(
                            key,
                            request.asr_api_key,
                            purpose="云端 ASR API Key",
                        )
                except SecretStorageError as error:
                    raise HTTPException(status_code=422, detail=str(error)) from error
            if "asr_model" in provided:
                store.set_setting("asr_cloud_model", request.asr_model)
                store.set_setting("asr_model", request.asr_model)
            # R4：清除云端 ASR 密钥时同步清除已选模型。
            if request.clear_secret_provider == "asr":
                store.set_setting("asr_cloud_model", None)
                store.set_setting("asr_model", None)
        if "task_concurrency" in provided:
            # Retain the setting key for old clients, but the local worker is
            # deliberately fixed at one active task.
            store.set_setting("task_concurrency", "1")
        if "ai_tag_recommendation_enabled" in provided:
            store.set_setting(
                "ai_tag_recommendation_enabled",
                "true" if request.ai_tag_recommendation_enabled else "false",
            )
        if "enable_ai_ask" in provided:
            store.set_setting(
                "enable_ai_ask",
                "true" if request.enable_ai_ask else "false",
            )
        if "ai_ask_siliconflow_api_key" in provided:
            try:
                store.set_secret_setting(
                    "ai_ask_siliconflow_api_key",
                    request.ai_ask_siliconflow_api_key,
                    purpose="AI 问答硅基流动 API Key",
                )
            except SecretStorageError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
            with ask_index_lock:
                app.state.ask_index = None
            start_ask_index_backfill()
        # Protect the summary key and commit the whole summary group only after
        # all preceding request validation has succeeded.  A protection or
        # transaction failure therefore leaves the previous summary target
        # untouched.
        if summary_values or "summary_api_key" in provided:
            try:
                store.set_summary_settings_atomically(
                    summary_values,
                    api_key_provided="summary_api_key" in provided,
                    api_key=request.summary_api_key,
                )
            except SecretStorageError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
            if (
                {"summary_api_url", "summary_api_mode", "summary_provider", "summary_model"}
                & summary_values.keys()
                or "summary_api_key" in provided
            ):
                with ask_index_lock:
                    app.state.ask_index = None
                with rag_service_lock:
                    app.state.rag_service = None
            if "summary_skills_root" in provided:
                app.state.skills_root = selected_skills_root
                workflow.skills_root = selected_skills_root
            start_rag_classification_backfill()
        return _settings_response(
            store,
            app.state.archive_root,
            app.state.asr_model_root,
            app.state.skills_root,
        )

    return app


def _duplicate_import_response(store: SQLiteStore, content_id: str) -> ImportResponse:
    entry = store.get_history_entry(content_id)
    return ImportResponse(
        content=_content_response(
            entry.content,
            favorite_folder_ids=store.favorite_folder_ids(content_id),
            tag_ids=store.tag_ids(content_id),
            tag_names=store.tag_names(content_id),
        ),
        run=_run_response(entry.run),
        job=_job_response(entry.job, content=entry.content),
        duplicate=True,
        duplicate_content_id=content_id,
        reused=True,
    )

def _favorite_folder_response(folder: FavoriteFolder) -> FavoriteFolderResponse:
    return FavoriteFolderResponse(
        id=folder.id,
        name=folder.name,
        parent_id=folder.parent_id,
        content_count=folder.content_count,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
    )


def _import_batch_response(store: SQLiteStore, batch_id: str, jobs: list) -> ImportBatchResponse:
    members: list[ImportBatchMemberResponse] = []
    states: list[str] = []
    first_name = batch_id
    source_type: str | None = None
    for job in sorted(jobs, key=lambda item: item.metadata.get("archive_item_number") or 0):
        first_name = str(job.metadata.get("archive_batch_name") or first_name)
        source_type = source_type or job.metadata.get("source_platform")
        content = None
        try:
            run = store.get_analysis_run(job.analysis_run_id)
            content = store.get_content(run.content_id)
        except LookupError:
            content = None
        members.append(
            ImportBatchMemberResponse(
                content=(
                    _content_response(
                        content,
                        favorite_folder_ids=store.favorite_folder_ids(content.id),
                        tag_ids=store.tag_ids(content.id),
                        tag_names=store.tag_names(content.id),
                    )
                    if content is not None
                    else None
                ),
                job=_job_response(job, content=content),
            )
        )
        states.append(job.state.value)
    return ImportBatchResponse(
        id=batch_id,
        name=first_name,
        source_type=source_type,
        total=len(members),
        completed=states.count(JobState.COMPLETED.value),
        failed=states.count(JobState.FAILED.value),
        cancelled=states.count(JobState.CANCELLED.value),
        queued=sum(state in {JobState.QUEUED.value, JobState.PAUSED.value} for state in states),
        members=members,
    )


def _content_response(
    content,
    *,
    favorite_folder_ids: list[str] | None = None,
    tag_ids: list[str] | None = None,
    tag_names: list[str] | None = None,
) -> ContentResponse:
    return ContentResponse(
        id=content.id,
        kind=content.kind,
        title=content.title,
        platform=content.source.platform,
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
        tag_ids=list(tag_ids if tag_ids is not None else getattr(content, "tags", ()) or ()),
        tag_names=list(tag_names or ()),
        introduction=getattr(content, "introduction", "") or "",
        favorite=content.favorite,
        favorite_folder_ids=list(favorite_folder_ids or []),
        deleted_at=content.deleted_at,
        processing_model=content.processing_model,
        created_at=content.created_at,
        updated_at=content.updated_at,
    )


def _introduction_backfill_candidates(
    store: SQLiteStore,
    content_ids: list[str] | None = None,
) -> tuple[list[HistoryEntry], list[str]]:
    requested = set(content_ids or []) or None
    candidates: list[HistoryEntry] = []
    no_summary_ids: list[str] = []
    for entry in store.list_history(archived_only=True):
        content_id = entry.content.id
        if requested is not None and content_id not in requested:
            continue
        if (entry.content.introduction or "").strip():
            continue
        summary = store.get_summary(content_id)
        if not summary or not summary.strip():
            no_summary_ids.append(content_id)
            continue
        candidates.append(entry)
    return candidates, no_summary_ids


def _introduction_summarizer(
    store: SQLiteStore,
    skills_root: Path,
) -> OpenAICompatibleSummarizer:
    summary = _summary_settings_snapshot(store, skills_root, strict_skill=False)
    config = dict(summary["summary_config"])
    try:
        api_key = store.get_secret_setting(
            "summary_api_key",
            purpose="总结模型 API Key",
        ) or ""
    except SecretStorageError:
        api_key = ""
    return OpenAICompatibleSummarizer(
        SummarySettings(
            api_url=str(config.get("api_url") or DEFAULT_SUMMARY_API_URL),
            api_key=api_key,
            model=str(config.get("model") or DEFAULT_SUMMARY_MODEL),
            timeout_seconds=int(config.get("timeout_seconds") or DEFAULT_SUMMARY_TIMEOUT_SECONDS),
            api_mode=str(config.get("api_mode") or "chat_completions"),
        )
    )


def _introduction_backfill_response(record: dict[str, object]) -> IntroductionBackfillResponse:
    raw_items = record.get("items") if isinstance(record.get("items"), dict) else {}
    items = [
        IntroductionBackfillItemResponse(
            content_id=content_id,
            status=str(item.get("status") or "pending"),
            message=item.get("message"),
            introduction=item.get("introduction"),
        )
        for content_id, item in raw_items.items()
        if isinstance(item, dict)
    ]
    succeeded = sum(item.status == "succeeded" for item in items)
    skipped = sum(item.status == "skipped" for item in items)
    failed_ids = [item.content_id for item in items if item.status == "failed"]
    return IntroductionBackfillResponse(
        run_id=str(record["run_id"]),
        status=str(record.get("status") or "queued"),
        total=len(items),
        completed=sum(item.status != "pending" for item in items),
        succeeded=succeeded,
        skipped=skipped,
        failed=len(failed_ids),
        failed_ids=failed_ids,
        items=items,
    )


def _run_response(run) -> AnalysisRunResponse:
    return AnalysisRunResponse(
        id=run.id,
        content_id=run.content_id,
        status=run.status,
        settings_snapshot=run.settings_snapshot,
        prompt_version=run.prompt_version,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _hold_interrupted_jobs(store) -> int:
    """11-18c R1：重启后一律不自动续跑。

    跨会话遗留的非终态任务（含上次正在跑、被关掉打断的那条）全部转「已暂停」，
    保留断点，由用户在任务页手动「继续」。同一次会话内新导入的任务不受影响。
    """

    holdable_states = {
        JobState.QUEUED,
        JobState.ACQUIRING,
        JobState.EXTRACTING,
        JobState.TRANSCRIBING,
        JobState.CHUNKING,
        JobState.SUMMARIZING,
        JobState.ARCHIVING,
        JobState.INDEXING,
    }
    held = 0
    for job in store.list_jobs(states=holdable_states):
        _remember_stable_checkpoint(job)
        job.transition(JobState.PAUSED)
        store.save_job(job)
        run = store.get_analysis_run(job.analysis_run_id)
        run.status = "paused"
        run.updated_at = datetime.now(UTC)
        store.save_analysis_run(run)
        held += 1
    return held


def _remember_stable_checkpoint(job) -> str | None:
    """Record the last committed stage before pause or terminal failure."""

    stable = stable_checkpoint_for(job.checkpoint)
    if stable is None:
        stored = job.metadata.get("last_stable_checkpoint")
        if isinstance(stored, str):
            stable = stored
    job.metadata["last_stable_checkpoint"] = stable
    job.metadata["resume_checkpoint"] = stable
    return stable


def _stable_stage_view(job) -> tuple[str | None, str | None]:
    if job.state is JobState.CANCELLED:
        return None, None
    stable = job.metadata.get("last_stable_checkpoint")
    if not isinstance(stable, str):
        stable = stable_checkpoint_for(job.checkpoint)
    last_stage = _STABLE_STAGE_BY_CHECKPOINT.get(stable)
    if job.state in {JobState.PAUSED, JobState.FAILED}:
        return last_stage, _RESUME_STAGE_BY_CHECKPOINT.get(stable)
    if "resume_checkpoint" in job.metadata:
        return last_stage, _RESUME_STAGE_BY_CHECKPOINT.get(stable)
    return last_stage, None


def _job_response(job, *, content=None) -> JobResponse:
    execution_state = _job_execution_state(job)
    last_stable_stage, resume_stage = _stable_stage_view(job)
    asr_stats = job.metadata.get("asr_stats")
    if not isinstance(asr_stats, dict):
        asr_stats = {}
    phase_seconds = asr_stats.get("phase_seconds")
    if not isinstance(phase_seconds, dict):
        phase_seconds = {}
    phase_seconds = {
        str(key): (float(value) if isinstance(value, (int, float)) else None)
        for key, value in phase_seconds.items()
        if isinstance(key, str)
    }
    guidance = (
        recovery_guidance(job.error_code.value)
        if job.error_code is not None and job.state is not JobState.CANCELLED
        else None
    )
    collection_id, collection_title, collection_total = _job_collection_fields(job)
    return JobResponse(
        id=job.id,
        type=job.type,
        analysis_run_id=job.analysis_run_id,
        state=job.state.value,
        execution_state=execution_state,
        queue_state=execution_state,
        active_job_id=job.id if execution_state in {"running", "switching"} else None,
        attempt=job.attempt,
        progress=job.progress,
        checkpoint=job.checkpoint,
        last_stable_stage=last_stable_stage,
        resume_stage=resume_stage,
        lease_until=job.lease_until,
        worker_id=job.worker_id,
        error_code=job.error_code.value if job.error_code else None,
        error_message=job.error_message,
        recovery_action=guidance["action"] if guidance else None,
        recovery_suggestion=guidance["suggestion"] if guidance else None,
        archive_path=job.metadata.get("archive_path"),
        summary_preview=job.metadata.get("summary_preview"),
        source_url=job.metadata.get("source_url"),
        source_note=job.metadata.get("source_note"),
        thumbnail_url=job.metadata.get("thumbnail_url")
        or (content.source.thumbnail_url if content is not None else None),
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        elapsed_seconds=job.elapsed_seconds,
        priority=job.priority,
        queue_position=job.queue_position if execution_state == "waiting" else None,
        content_id=content.id if content is not None else None,
        content_title=content.title if content is not None else None,
        content_platform=content.source.platform if content is not None else None,
        content_author=content.source.author if content is not None else None,
        content_category=content.category if content is not None else None,
        content_created_at=content.created_at if content is not None else None,
        batch_name=job.metadata.get("archive_batch_name"),
        batch_id=job.metadata.get("import_batch_id"),
        batch_item_number=job.metadata.get("archive_item_number"),
        batch_total=job.metadata.get("archive_total"),
        collection_id=collection_id,
        collection_title=collection_title,
        collection_total=collection_total,
        asr_subtitle_hit=asr_stats.get("subtitle_hit"),
        asr_skipped=asr_stats.get("asr_skipped"),
        asr_skipped_reason=asr_stats.get("asr_skipped_reason"),
        asr_fallback_reason=asr_stats.get("asr_fallback_reason"),
        asr_segment_completed=job.metadata.get("asr_completed_segments")
        or asr_stats.get("completed_segments"),
        asr_segment_total=job.metadata.get("asr_total_segments")
        or asr_stats.get("total_segments"),
        asr_completed_audio_seconds=job.metadata.get("asr_completed_audio_seconds")
        if job.metadata.get("asr_completed_audio_seconds") is not None
        else asr_stats.get("completed_audio_seconds"),
        asr_audio_seconds=job.metadata.get("asr_audio_seconds")
        if job.metadata.get("asr_audio_seconds") is not None
        else asr_stats.get("audio_seconds"),
        asr_vad_effective_audio_seconds=asr_stats.get("vad_effective_audio_seconds"),
        asr_total_budget_seconds=job.metadata.get("asr_total_budget_seconds")
        if job.metadata.get("asr_total_budget_seconds") is not None
        else asr_stats.get("total_budget_seconds"),
        asr_elapsed_seconds=job.metadata.get("asr_elapsed_seconds")
        if job.metadata.get("asr_elapsed_seconds") is not None
        else asr_stats.get("asr_elapsed_seconds"),
        asr_rtf=job.metadata.get("asr_rtf")
        if job.metadata.get("asr_rtf") is not None
        else asr_stats.get("asr_rtf"),
        asr_eta_seconds=job.metadata.get("asr_eta_seconds")
        if job.metadata.get("asr_eta_seconds") is not None
        else asr_stats.get("asr_eta_seconds"),
        asr_budget_warning=job.metadata.get("asr_budget_warning")
        if job.metadata.get("asr_budget_warning") is not None
        else asr_stats.get("budget_warning"),
        asr_worker_generation=job.metadata.get("asr_worker_generation")
        if job.metadata.get("asr_worker_generation") is not None
        else asr_stats.get("worker_generation"),
        asr_worker_cold_start=asr_stats.get("worker_cold_start"),
        asr_recovery_count=asr_stats.get("recovery_count"),
        asr_batch_size=job.metadata.get("asr_batch_size") or asr_stats.get("batch_size"),
        asr_batch_selection=asr_stats.get("batch_selection"),
        asr_phase_seconds=phase_seconds,
    )


def _job_collection_id(job) -> str | None:
    """B 站真实 season 与同一 BVID 的多 P／多批导入都形成父集。"""

    season_id = job.metadata.get("season_id")
    if isinstance(season_id, int) or (isinstance(season_id, str) and season_id.strip()):
        return f"season:{season_id}"
    identity = _bilibili_source_identity(job.metadata.get("source_url"))
    if identity is None:
        return None
    return f"parts:{identity[0]}"


def _job_collection_fields(job) -> tuple[str | None, str | None, int | None]:
    collection_id = _job_collection_id(job)
    if collection_id is None:
        return None, None, None
    if collection_id.startswith("parts:"):
        # 多 P／多批父集用归档批次名作标题；整批 archive_total 混入其他视频，不作分母。
        return (
            collection_id,
            job.metadata.get("collection_title") or job.metadata.get("archive_batch_name"),
            None,
        )
    return (
        collection_id,
        job.metadata.get("collection_title"),
        job.metadata.get("collection_total"),
    )


def _season_metadata_for_content(store, content_id: str) -> dict[str, object] | None:
    jobs = store.list_content_jobs(content_id)
    assigned = [job for job in jobs if job.metadata.get("season_id") not in (None, "")]
    if not assigned:
        return None
    job = assigned[-1]
    return {
        "season_id": job.metadata["season_id"],
        "collection_title": job.metadata.get("collection_title"),
        "collection_total": job.metadata.get("collection_total"),
    }


def _set_season_metadata(job, metadata: dict[str, object]) -> None:
    job.metadata["season_id"] = metadata["season_id"]
    job.metadata["collection_title"] = metadata.get("collection_title")
    job.metadata["collection_total"] = metadata.get("collection_total")


def _attach_season_metadata(
    store, content_id: str, incoming: dict[str, object]
) -> dict[str, object]:
    metadata = _season_metadata_for_content(store, content_id) or incoming
    for job in store.list_content_jobs(content_id):
        current = job.metadata.get("season_id")
        if current not in (None, "") and str(current) != str(metadata["season_id"]):
            continue
        _set_season_metadata(job, metadata)
        store.save_job(job)
    return metadata


def _is_switch_requeue(job) -> bool:
    """True for a preempted job that is still waiting for its turn.

    It keeps ``paused`` in storage so the running workflow can stop at its
    checkpoint, but to the user it is a waiting job that will continue by
    itself once the job that jumped ahead finishes.
    """

    return job.state is JobState.PAUSED and bool(job.metadata.get("switch_requeue"))


def _job_execution_state(job) -> str:
    if _is_switch_requeue(job):
        return "waiting"
    if job.state is JobState.PAUSED:
        return "paused"
    if job.state in {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}:
        return job.state.value
    if job.state is JobState.QUEUED:
        return "waiting"
    if job.state in _RUNNING_JOB_STATES:
        return "running"
    return "running"


def _task_event_response(event) -> TaskEventResponse:
    return TaskEventResponse(
        id=event.id,
        job_id=event.job_id,
        sequence=event.sequence,
        attempt=event.attempt,
        event_type=event.event_type,
        stage=event.stage,
        state=event.state,
        progress=event.progress,
        checkpoint=event.checkpoint,
        error_code=event.error_code,
        message=event.message,
        details=event.details,
        occurred_at=event.occurred_at,
    )


def _history_response(
    entry: HistoryEntry,
    *,
    favorite_folder_ids: list[str] | None = None,
    tag_ids: list[str] | None = None,
    tag_names: list[str] | None = None,
) -> HistoryEntryResponse:
    return HistoryEntryResponse(
        content=_content_response(
            entry.content,
            favorite_folder_ids=favorite_folder_ids,
            tag_ids=tag_ids,
            tag_names=tag_names,
        ),
        run=_run_response(entry.run),
        job=_job_response(entry.job, content=entry.content),
    )


def _content_export(
    store: SQLiteStore,
    content_id: str,
    export_format: str,
) -> tuple[str, str, str]:
    entry = store.get_history_entry(content_id)
    archive_path = entry.job.metadata.get("archive_path")
    directory = Path(archive_path) if isinstance(archive_path, str) else None
    if directory is None or not directory.is_dir():
        raise LookupError("archive_not_available")
    record_path = directory / "record.json"
    transcript_path = directory / "transcript.json"
    index_path = directory / "index.md"
    if not record_path.is_file() or not index_path.is_file():
        raise LookupError("archive_not_available")
    markdown = index_path.read_text(encoding="utf-8")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if export_format == "markdown":
        return markdown, "md", "text/markdown; charset=utf-8"
    if export_format == "text":
        return _markdown_to_text(markdown), "txt", "text/plain; charset=utf-8"
    transcript = None
    if transcript_path.is_file():
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    if export_format == "subtitle":
        if not isinstance(transcript, dict) or not isinstance(transcript.get("segments"), list):
            raise LookupError("transcript_not_available")
        return _transcript_to_srt(transcript["segments"]), "srt", "application/x-subrip; charset=utf-8"
    if export_format == "json":
        structured = dict(record)
        structured["transcript"] = transcript
        return json.dumps(structured, ensure_ascii=False, indent=2) + "\n", "json", "application/json"
    raise LookupError("unsupported_export_format")


def _sync_content_introduction(store: SQLiteStore, content_id: str, introduction: str) -> None:
    """Keep the structured archive record and its Markdown header in sync."""

    try:
        entry = store.get_history_entry(content_id)
    except ContentNotFoundError:
        return
    archive_path = entry.job.metadata.get("archive_path")
    if not isinstance(archive_path, str):
        return
    directory = Path(archive_path)
    record_path = directory / "record.json"
    index_path = directory / "index.md"
    if not record_path.is_file():
        return
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            return
        record["introduction"] = introduction
        record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        if index_path.is_file():
            lines = index_path.read_text(encoding="utf-8").splitlines()
            lines = [line for line in lines if not line.startswith("- 简介：")]
            if introduction:
                insert_at = 1 if lines else 0
                lines[insert_at:insert_at] = [f"- 简介：{introduction}"]
            index_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    except (OSError, ValueError):
        # The database remains authoritative for the editable field; a missing
        # archive is handled by the existing result/archive error state.
        return


def _sync_content_tags(store: SQLiteStore, content_id: str, tag_names: list[str]) -> None:
    """Update tag metadata in an existing portable archive when relations change."""

    try:
        entry = store.get_history_entry(content_id)
    except ContentNotFoundError:
        return
    archive_path = entry.job.metadata.get("archive_path")
    if not isinstance(archive_path, str):
        return
    directory = Path(archive_path)
    record_path = directory / "record.json"
    index_path = directory / "index.md"
    if not record_path.is_file():
        return
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            return
        record["tags"] = list(dict.fromkeys(name.strip() for name in tag_names if name.strip()))
        record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        if index_path.is_file():
            index_text = index_path.read_text(encoding="utf-8")
            body = index_text.split("\n---\n", 1)[1] if "\n---\n" in index_text else ""
            index_path.write_text(render_markdown(record, body), encoding="utf-8")
    except (OSError, ValueError):
        return


def _markdown_to_text(markdown: str) -> str:
    plain = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", markdown)
    plain = re.sub(r"^\s{0,3}#{1,6}\s?", "", plain, flags=re.MULTILINE)
    plain = re.sub(r"[*_`>]+", "", plain)
    return plain.strip() + "\n"


def _transcript_to_srt(segments: list[dict]) -> str:
    rows: list[str] = []
    ordinal = 1
    for segment in segments:
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        start = _srt_timestamp(float(segment.get("start_seconds") or 0))
        end = _srt_timestamp(float(segment.get("end_seconds") or 0))
        rows.extend([str(ordinal), f"{start} --> {end}", text, ""])
        ordinal += 1
    return "\n".join(rows)


def _srt_timestamp(seconds: float) -> str:
    total_ms = max(0, round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{whole_seconds:02},{milliseconds:03}"

def _summary_version_response(version) -> SummaryVersionResponse:
    return SummaryVersionResponse(
        id=version.id,
        content_id=version.content_id,
        version_number=version.version_number,
        parent_version_id=version.parent_version_id,
        origin=version.origin,
        template=version.template,
        chapter_title=version.chapter_title,
        source_start_seconds=version.source_start_seconds,
        source_end_seconds=version.source_end_seconds,
        markdown=version.markdown,
        summary_strength=version.summary_strength,
        summary_style=version.summary_style,
        material_level=version.material_level,
        source_version=version.source_version,
        source_scope=version.source_scope,
        processed_source_refs=version.processed_source_refs,
        expected_source_refs=version.expected_source_refs,
        provider=version.provider,
        model=version.model,
        prompt_version=version.prompt_version,
        created_at=version.created_at,
    )


def _summary_feedback_response(feedback) -> SummaryFeedbackResponse:
    return SummaryFeedbackResponse(
        id=feedback.id,
        content_id=feedback.content_id,
        version_id=feedback.version_id,
        category=feedback.category,
        note=feedback.note,
        context=feedback.context,
        created_at=feedback.created_at,
    )


def _task_feedback_response(feedback) -> TaskFeedbackResponse:
    return TaskFeedbackResponse(
        id=feedback.id,
        job_id=feedback.job_id,
        content_id=feedback.content_id,
        category=feedback.category,
        note=feedback.note,
        context=feedback.context,
        created_at=feedback.created_at,
    )


def _result_evidence(directory: Path) -> list[EvidenceResponse]:
    transcript_path = directory / "transcript.json"
    if not transcript_path.is_file():
        return []
    try:
        payload = json.loads(transcript_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    evidence: list[EvidenceResponse] = []
    for span in map_transcript_segments(payload):
        evidence.append(
            EvidenceResponse(
                ordinal=span.ordinal,
                start_seconds=span.start_seconds,
                end_seconds=span.end_seconds,
                text=span.text,
                source_kind=span.source_kind,
                location_kind=span.location_kind,
            )
        )
    return evidence

_STATUS_UNSET = object()


def _save_bilibili_status(
    store: SQLiteStore,
    status_value: str,
    message: str,
    *,
    account_label: str | None | object = _STATUS_UNSET,
    last_checked_at: datetime | None | object = _STATUS_UNSET,
    last_connected_at: datetime | None | object = _STATUS_UNSET,
) -> PlatformConnection:
    definition = get_platform_definition("bilibili")
    assert definition is not None
    previous = store.get_platform_connection("bilibili")
    return store.save_platform_connection(
        platform="bilibili",
        status=status_value,
        auth_type=definition.auth_type,
        account_label=(
            previous.account_label
            if account_label is _STATUS_UNSET and previous
            else account_label if account_label is not _STATUS_UNSET else None
        ),
        browser=None,
        browser_profile=None,
        login_url=definition.login_url,
        last_checked_at=(
            previous.last_checked_at
            if last_checked_at is _STATUS_UNSET and previous
            else last_checked_at if last_checked_at is not _STATUS_UNSET else None
        ),
        last_connected_at=(
            previous.last_connected_at
            if last_connected_at is _STATUS_UNSET and previous
            else last_connected_at if last_connected_at is not _STATUS_UNSET else None
        ),
        message=message,
    )


def _normalize_legacy_bilibili_connection(
    store: SQLiteStore,
    connection: PlatformConnection,
) -> PlatformConnection:
    if connection.platform != "bilibili" or connection.status != CHECKING:
        return connection
    raw_cookie = store._get_setting_raw("bilibili_session_cookie")
    try:
        cookie = store.get_bilibili_session_cookie()
    except SecretStorageError:
        return _save_bilibili_status(
            store,
            REAUTH_REQUIRED,
            "B站本地登录会话无法读取，请重新扫码登录",
            account_label=None,
            last_checked_at=None,
            last_connected_at=None,
        )
    if cookie:
        return _save_bilibili_status(
            store,
            CONNECTED,
            "检测到已保存的 B站登录会话，等待后续检查",
            last_checked_at=None,
        )
    return _save_bilibili_status(
        store,
        NOT_CONNECTED if not raw_cookie else REAUTH_REQUIRED,
        (
            "尚未连接 B站，请生成二维码并使用 B站 App 扫码确认登录"
            if not raw_cookie
            else "B站本地登录会话无法读取，请重新扫码登录"
        ),
        account_label=None,
        last_checked_at=None,
        last_connected_at=None,
    )


def _sync_bilibili_error_status(
    store: SQLiteStore,
    url: str | None,
    error: Exception | str,
) -> None:
    """Persist only explicit auth/risk failures; leave transient errors alone."""

    if not url or detect_platform(url) is not SourcePlatform.BILIBILI:
        return
    status_value = getattr(error, "connection_status", None)
    if status_value == RISK_CONTROLLED:
        _save_bilibili_status(
            store,
            RISK_CONTROLLED,
            "B站要求人工验证，请稍后重试",
            account_label=None,
            last_checked_at=datetime.now(UTC),
        )
        return
    if status_value == REAUTH_REQUIRED:
        _save_bilibili_status(
            store,
            REAUTH_REQUIRED,
            "B站登录会话已失效，请重新扫码登录",
            account_label=None,
            last_checked_at=datetime.now(UTC),
        )


def _connection_or_default(
    store: SQLiteStore,
    definition,
) -> PlatformConnection:
    if not _is_connectable(definition):
        # P4 硬约束：未接入连接通道的平台不写库——忽略任何存量行。
        return PlatformConnection(
            platform=definition.key,
            status=UNSUPPORTED,
            auth_type=definition.auth_type,
            account_label=None,
            browser=None,
            browser_profile=None,
            login_url=definition.login_url,
            last_checked_at=None,
            last_connected_at=None,
            message=definition.capability_note,
            updated_at=datetime.now(UTC),
        )
    existing = store.get_platform_connection(definition.key)
    if existing is not None:
        return _normalize_legacy_bilibili_connection(store, existing)
    return PlatformConnection(
        platform=definition.key,
        status=NOT_CONNECTED if _is_connectable(definition) else UNSUPPORTED,
        auth_type=definition.auth_type,
        account_label=None,
        browser=None,
        browser_profile=None,
        login_url=definition.login_url,
        last_checked_at=None,
        last_connected_at=None,
        message=(
            "尚未连接：请在下方生成 B站二维码，并使用 B站 App 扫码确认登录"
            if definition.key == "bilibili"
            else f"请在桌面壳内打开{definition.display_name}并完成登录"
            if definition.browser_session_available
            else "当前版本暂未接入该平台的自动登录验证"
        )
        if _is_connectable(definition)
        else "当前版本暂未接入该平台的自动登录验证",
        updated_at=datetime.now(UTC),
    )


def _platform_connection_response(
    connection: PlatformConnection,
    definition,
) -> PlatformConnectionResponse:
    legacy_bilibili = definition.key == "bilibili" and connection.auth_type != definition.auth_type
    return PlatformConnectionResponse(
        platform=connection.platform,
        display_name=definition.display_name,
        status=REAUTH_REQUIRED if legacy_bilibili else connection.status,
        auth_type=definition.auth_type if legacy_bilibili else connection.auth_type,
        account_label=None if legacy_bilibili else connection.account_label,
        browser=None if legacy_bilibili else connection.browser,
        browser_profile=None if legacy_bilibili else connection.browser_profile,
        login_url=connection.login_url or definition.login_url,
        last_checked_at=connection.last_checked_at,
        last_connected_at=None if legacy_bilibili else connection.last_connected_at,
        message=(
            "旧版浏览器登录态未迁移，请重新生成 B站二维码"
            if legacy_bilibili
            else connection.message
        ),
        supported=_is_connectable(definition),
    )


def _is_connectable(definition) -> bool:
    return definition.checker_available or definition.browser_session_available


def _local_asr_runtime_project_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _local_asr_runtime_install_command() -> list[str]:
    project = _local_asr_runtime_project_root()
    return [
        sys.executable,
        "-m",
        "pip",
        "install",
        "-e",
        f"{project}[local-asr]",
    ]


def _local_asr_runtime_command_text(command: list[str]) -> str:
    return " ".join(f'"{part}"' if " " in part else part for part in command)


def _local_asr_runtime_install_response(
    state: dict[str, object],
    command_text: str,
) -> LocalAsrRuntimeInstallResponse:
    return LocalAsrRuntimeInstallResponse(
        runtime_available=local_asr_runtime_available(),
        status=str(state.get("status") or "idle"),
        progress=int(state.get("progress", 0) or 0),
        message=str(state.get("message") or ""),
        error=str(state["error"]) if state.get("error") else None,
        command=command_text,
    )


def _local_asr_candidate_response(candidate: LocalAsrModelCandidate) -> LocalAsrModelCandidateResponse:
    info = local_asr_model_info(
        candidate.path.parent,
        candidate.id,
        model_path=candidate.path,
    )
    return LocalAsrModelCandidateResponse(
        id=info.id,
        label=info.label,
        repo_id=info.repo_id,
        size=info.size,
        path=str(candidate.path),
        size_bytes=candidate.validation.size_bytes,
        validation_status=candidate.validation.status,
        message=candidate.validation.message,
        missing_files=list(candidate.validation.missing_files),
    )


def _local_asr_selection_response(
    scan_path: Path,
    candidates: tuple[LocalAsrModelCandidate, ...],
    message: str,
    *,
    runtime_available: bool,
) -> LocalAsrModelResponse:
    return LocalAsrModelResponse(
        id="",
        label="发现多个完整本地模型",
        repo_id="",
        size=f"{len(candidates)} 个候选",
        languages="",
        description=message,
        status="selection_required",
        validation_status="selection_required",
        compatibility_status="ready" if runtime_available else "runtime_unavailable",
        path=str(scan_path),
        error=message,
        progress_message=message,
        selection_required=True,
        candidates=[_local_asr_candidate_response(candidate) for candidate in candidates],
        scan_scope=str(scan_path),
    )


def _local_asr_model_response(
    model_root: Path,
    model_id: str,
    download_state: dict[str, object],
    *,
    runtime_available: bool,
    model_path: Path | None = None,
    validation=None,
    imported: bool = False,
    reused: bool = False,
    scan_scope: Path | None = None,
) -> LocalAsrModelResponse:
    path = model_path or local_model_path(model_root, model_id)
    info = local_asr_model_info(model_root, model_id, model_path=model_path)
    validation = validation or validate_local_model(model_root, model_id)
    state_status = str(download_state.get("status") or "")
    installed = validation.ready
    if installed and reused:
        response_status = "reused"
    elif installed and imported:
        response_status = "imported"
    elif installed:
        response_status = "downloaded"
    elif state_status:
        response_status = state_status
    else:
        response_status = validation.status
    error = download_state.get("error")
    if error is None and not installed and validation.status in {"incomplete", "corrupt"}:
        error = validation.message
    try:
        progress = int(download_state.get("progress", 100 if installed else 0) or 0)
    except (TypeError, ValueError):
        progress = 100 if installed else 0
    try:
        downloaded_bytes = int(download_state.get("downloaded_bytes", validation.size_bytes) or 0)
    except (TypeError, ValueError):
        downloaded_bytes = validation.size_bytes
    try:
        total_bytes = int(download_state.get("total_bytes", info.estimated_size_bytes) or 0)
    except (TypeError, ValueError):
        total_bytes = info.estimated_size_bytes
    compatibility = (
        "ready" if installed and runtime_available else
        "runtime_unavailable" if installed else
        "invalid"
    )
    return LocalAsrModelResponse(
        id=info.id,
        label=info.label,
        repo_id=info.repo_id,
        size=info.size,
        languages=info.languages,
        description=info.description,
        installed=installed,
        model_ready=installed,
        usable=installed and runtime_available,
        status=response_status,
        validation_status=validation.status,
        compatibility_status=compatibility,
        path=str(path) if installed or model_path is not None else None,
        error=str(error) if error else None,
        size_bytes=validation.size_bytes,
        memory_required_mb=info.memory_required_mb,
        speed=info.speed,
        quality=info.quality,
        device_requirements=info.device_requirements,
        progress=max(0, min(100, progress)),
        downloaded_bytes=downloaded_bytes,
        total_bytes=total_bytes,
        progress_message=str(
            download_state.get("message")
            or download_state.get("progress_message")
            or validation.message
        ),
        checksum=validation.sha256,
        imported=imported,
        retryable=response_status in {"error", "incomplete", "corrupt"},
        trash_path=str(download_state["trash_path"]) if download_state.get("trash_path") else None,
        update_status=(
            str(download_state["update_status"])
            if download_state.get("update_status")
            else None
        ),
        update_available=bool(download_state.get("update_available", False)),
        update_error=(
            str(download_state["update_error"]) if download_state.get("update_error") else None
        ),
        remote_revision=(
            str(download_state["remote_revision"])
            if download_state.get("remote_revision")
            else None
        ),
        local_revision=(
            str(download_state["local_revision"]) if download_state.get("local_revision") else None
        ),
        scan_scope=str(scan_scope) if scan_scope else None,
    )


def _local_asr_models_response(
    model_root: Path,
    downloads: dict[str, dict[str, object]],
    *,
    runtime_available: bool,
    runtime_install: dict[str, object] | None = None,
) -> LocalAsrModelsResponse:
    model_ids = list(list_local_asr_model_ids(model_root))
    for model_id in downloads:
        if model_id not in model_ids:
            model_ids.append(model_id)
    runtime_install = runtime_install or {}
    install_status = str(
        runtime_install.get("status") or ("ready" if runtime_available else "idle")
    )
    return LocalAsrModelsResponse(
        model_root=str(model_root),
        runtime_available=runtime_available,
        runtime_status="ready" if runtime_available else install_status,
        runtime_installing=install_status == "installing",
        runtime_install_progress=int(
            runtime_install.get("progress", 100 if runtime_available else 0) or 0
        ),
        runtime_install_message=str(
            runtime_install.get("message")
            or ("本地 ASR 组件已安装" if runtime_available else "本地 ASR 组件尚未安装")
        ),
        runtime_install_error=(
            str(runtime_install["error"]) if runtime_install.get("error") else None
        ),
        runtime_install_command=_local_asr_runtime_command_text(_local_asr_runtime_install_command()),
        models=[
            _local_asr_model_response(
                model_root,
                model_id,
                downloads.get(model_id, {}),
                runtime_available=runtime_available,
            )
            for model_id in model_ids
        ],
    )

def _cloud_asr_api_url(store: SQLiteStore) -> str:
    return (
        store.get_setting("asr_cloud_api_url")
        or store.get_setting("asr_api_url")
        or DEFAULT_ASR_API_URL
    )


def _cloud_asr_model(store: SQLiteStore) -> str:
    return (
        store.get_setting("asr_cloud_model")
        or store.get_setting("asr_model")
        or DEFAULT_ASR_MODEL
    )


def _configured_cloud_asr_values(store: SQLiteStore) -> tuple[str | None, str | None]:
    api_url = (
        store.get_setting("asr_cloud_api_url") or store.get_setting("asr_api_url") or ""
    ).strip()
    model = (
        store.get_setting("asr_cloud_model") or store.get_setting("asr_model") or ""
    ).strip()
    return api_url or None, model or None


def _cloud_asr_configured(store: SQLiteStore) -> bool:
    api_url, model = _configured_cloud_asr_values(store)
    try:
        api_key = store.get_secret_setting(
            "asr_cloud_api_key", purpose="云端 ASR API Key"
        ) or store.get_secret_setting(
            "asr_api_key", purpose="云端 ASR API Key"
        )
    except SecretStorageError:
        return False
    return bool(api_url and model and api_key)


def _asr_api_key_for_request(store: SQLiteStore, requested_key: str | None) -> str:
    """Resolve only the ASR credential for an ASR request.

    A missing request key means "reuse the saved ASR key".  The summary key is
    intentionally never a fallback; copying it is an explicit PUT flag handled
    in the settings update path below.
    """

    key = (requested_key or "").strip()
    if key:
        return key
    return (
        store.get_secret_setting("asr_cloud_api_key", purpose="云端 ASR API Key")
        or store.get_secret_setting("asr_api_key", purpose="云端 ASR API Key")
        or ""
    )


def _local_asr_model(store: SQLiteStore) -> str | None:
    configured_model = store.get_setting("asr_local_model")
    if configured_model is not None:
        return None if configured_model == LOCAL_ASR_MODEL_CLEARED else configured_model
    return (
        store.get_setting("asr_model")
        if (store.get_setting("asr_engine") or "cloud") == "local"
        else None
    )


def _asr_settings_snapshot(store: SQLiteStore) -> dict[str, str]:
    return {
        "engine": store.get_setting("asr_engine") or "cloud",
        "cloud_api_url": _cloud_asr_api_url(store),
        "cloud_model": _cloud_asr_model(store),
        "local_model": _local_asr_model(store) or "",
    }


def _asr_is_configured(store: SQLiteStore, model_root: Path) -> bool:
    engine = store.get_setting("asr_engine") or "cloud"
    if engine == "local":
        model_id = _local_asr_model(store)
        return bool(
            local_asr_runtime_available()
            and model_id
            and is_local_model_ready(model_root, model_id)
        )
    return _cloud_asr_configured(store)


def _summary_skill_response(document) -> SummarySkillResponse:
    return SummarySkillResponse(**document.metadata())


def _validate_summary_api_url(value: str, api_mode: str | None = None) -> None:
    try:
        summary_endpoint(value, api_mode)
    except SummaryProviderError as error:
        raise SummaryConfigurationError(str(error)) from error


def _summary_config_identity_matches(
    store: SQLiteStore,
    *,
    provider: str,
    api_url: str,
) -> bool:
    """Allow a saved key to be reused only for the same target."""

    saved_url = store.get_setting("summary_api_url")
    if not saved_url:
        return False
    saved_provider = store.get_setting("summary_provider") or SUMMARY_ENGINE_OPENAI
    try:
        return (
            normalize_summary_provider(saved_provider)
            == normalize_summary_provider(provider)
            and _summary_base_url_for_identity(saved_url)
            == _summary_base_url_for_identity(api_url)
        )
    except SummaryProviderError:
        return False


def _summary_base_url_for_identity(value: str) -> str:
    parsed = urlsplit(value.strip())
    path = parsed.path.rstrip("/")
    lower_path = path.lower()
    for suffix in ("/chat/completions", "/responses"):
        if lower_path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.query, ""))


def _summary_validation_fingerprint(
    *,
    provider: str,
    api_url: str,
    api_mode: str | None,
    model: str,
    api_key: str,
) -> str:
    if not api_url or not api_url.strip():
        raise SummaryConfigurationError("总结接口地址不能为空")
    normalized_model = model.strip()
    if not normalized_model:
        raise SummaryConfigurationError("总结模型 ID 不能为空")
    effective_mode = resolve_summary_api_mode(api_url, api_mode)
    return "\u0000".join(
        (
            normalize_summary_provider(provider),
            _summary_base_url_for_identity(api_url),
            effective_mode,
            normalized_model,
            api_key_fingerprint(api_key) or "",
        )
    )


def _checkpoint_files_readable(checkpoint_dir: str | None, checkpoint: str) -> bool:
    """R8：稳定断点对应的产物文件必须存在且 JSON 可读，避免元数据假续跑。"""
    names = {
        "transcript_ready": ("transcript.json",),
        "chunks_ready": ("transcript.json", "chunks.json"),
        "summary_ready": ("transcript.json", "chunks.json", "summary.json"),
    }.get(checkpoint)
    if not names or not checkpoint_dir:
        return False
    directory = Path(checkpoint_dir)
    for name in names:
        path = directory / name
        if not path.is_file():
            return False
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
    return True


def _resume_checkpoint_fingerprint(settings: "AnalysisSettings") -> str:
    """R8：与断点写入共用的配置指纹算法。"""
    from app.domain.jobs import checkpoint_config_fingerprint

    return checkpoint_config_fingerprint(
        model=settings.model,
        prompt_hash=settings.summary_prompt_hash,
        max_chunk_tokens=settings.max_chunk_tokens,
        language=settings.language,
    )


def _summary_clear_requested(
    request: SettingsUpdateRequest,
    provided: set[str],
) -> bool:
    """Allow the explicit clear action without requiring a model test."""

    # R4：显式清密钥时一并清模型，与「留空保存保留原值」区分。
    if request.clear_secret_provider == "summary":
        return True
    if "summary_api_url" not in provided or request.summary_api_url is not None:
        return False
    if "summary_api_mode" in provided and request.summary_api_mode is not None:
        return False
    if "summary_model" in provided and request.summary_model is not None:
        return False
    if "summary_api_key" in provided and (request.summary_api_key or "").strip():
        return False
    if "summary_provider" in provided and request.summary_provider:
        return normalize_summary_provider(request.summary_provider) == "custom"
    return True


def _issue_summary_validation_token(
    app: FastAPI,
    *,
    provider: str,
    api_url: str,
    api_mode: str | None,
    model: str,
    api_key: str,
) -> str:
    fingerprint = _summary_validation_fingerprint(
        provider=provider,
        api_url=api_url,
        api_mode=api_mode,
        model=model,
        api_key=api_key,
    )
    token = secrets.token_urlsafe(32)
    now = monotonic()
    with app.state.summary_validation_lock:
        tokens = app.state.summary_validation_tokens
        for existing_token, record in list(tokens.items()):
            if record["expires_at"] <= now:
                del tokens[existing_token]
        tokens[token] = {
            "expires_at": now + SUMMARY_VALIDATION_TOKEN_TTL_SECONDS,
            "fingerprint": fingerprint,
        }
    return token


def _consume_summary_validation_token(
    app: FastAPI,
    token: str | None,
    expected_fingerprint: str,
) -> None:
    if not token or not token.strip():
        raise HTTPException(
            status_code=422,
            detail="总结配置必须先通过‘验证并保存’所需的连接验证",
        )
    with app.state.summary_validation_lock:
        record = app.state.summary_validation_tokens.pop(token.strip(), None)
    if not record or record["expires_at"] <= monotonic():
        raise HTTPException(
            status_code=422,
            detail="总结配置验证凭证已过期，请重新验证当前模型",
        )
    if record["fingerprint"] != expected_fingerprint:
        raise HTTPException(
            status_code=422,
            detail="总结配置验证凭证与当前服务商、地址、协议、模型或 API Key 不匹配",
        )


def _summary_api_key_for_request(
    store: SQLiteStore,
    *,
    provider: str,
    api_url: str,
    requested_key: str | None,
) -> str:
    key = (requested_key or "").strip()
    if key:
        return key
    if not _summary_config_identity_matches(
        store,
        provider=provider,
        api_url=api_url,
    ):
        return ""
    return store.get_secret_setting(
        "summary_api_key",
        purpose="总结模型 API Key",
    ) or ""


def _summary_prompt(store: SQLiteStore) -> str:
    return (store.get_setting("summary_prompt") or DEFAULT_SUMMARY_PROMPT).strip()


def _summary_settings_snapshot(
    store: SQLiteStore,
    skills_root: Path,
    *,
    strict_skill: bool = True,
) -> dict[str, object]:
    engine = SUMMARY_ENGINE_OPENAI
    provider = store.get_setting("summary_provider") or SUMMARY_ENGINE_OPENAI
    if provider == "builtin":
        provider = SUMMARY_ENGINE_OPENAI
    api_url = store.get_setting("summary_api_url") or DEFAULT_SUMMARY_API_URL
    try:
        api_mode = resolve_summary_api_mode(api_url, store.get_setting("summary_api_mode"))
    except SummaryProviderError as error:
        raise SummaryConfigurationError(str(error)) from error
    model = store.get_setting("summary_model") or DEFAULT_SUMMARY_MODEL
    if str(model).startswith("local"):
        model = DEFAULT_SUMMARY_MODEL
    prompt = _summary_prompt(store)
    timeout_seconds = DEFAULT_SUMMARY_TIMEOUT_SECONDS
    try:
        api_key = store.get_secret_setting(
            "summary_api_key",
            purpose="总结模型 API Key",
        ) or ""
    except SecretStorageError:
        api_key = ""

    skill_path = store.get_setting("summary_skill_path")
    skill_metadata: dict[str, object] | None = None
    skill_error: str | None = None
    if skill_path:
        try:
            skill_metadata = load_skill_document(skills_root, skill_path).metadata()
        except SkillFileError as error:
            skill_error = str(error)
            if strict_skill:
                raise SummaryConfigurationError(skill_error) from error
    return {
        "summary_engine": engine,
        "summary_provider": provider,
        "summary_config": {
            "api_url": api_url,
            "api_mode": api_mode,
            "model": model,
            "timeout_seconds": timeout_seconds,
            "api_key_fingerprint": api_key_fingerprint(api_key),
        },
        "summary_prompt": prompt,
        "summary_prompt_hash": prompt_hash(prompt),
        "prompt_version": prompt_version(prompt),
        "summary_skill": skill_metadata,
        "summary_skill_path": skill_path,
        "summary_skill_error": skill_error,
    }


def _analysis_settings_from_store(
    store: SQLiteStore,
    skills_root: Path,
    *,
    model: str | None,
    language: str | None,
    asr_engine: str | None,
    max_chunk_tokens: int,
    strength: SummaryStrength = SummaryStrength.STANDARD,
    summary_template: str = DEFAULT_SUMMARY_TEMPLATE,
    summary_style: str | None = None,
    extra_instruction: str | None = None,
    requested_prompt_version: str | None = None,
) -> AnalysisSettings:
    del requested_prompt_version
    summary = _summary_settings_snapshot(store, skills_root)
    summary_config = dict(summary["summary_config"])
    requested_model = model.strip() if model and model.strip() else None
    effective_model = requested_model or str(summary_config["model"])
    if effective_model.startswith("local"):
        effective_model = str(summary_config["model"])
    summary_config["model"] = effective_model
    try:
        template_id = get_summary_template(summary_template).id
        style_id = summary_style or "general"
        if style_id == "general" and template_id in SUMMARY_STYLES:
            style_id = template_id
        get_summary_style(style_id)
    except ValueError as error:
        raise SummaryConfigurationError(str(error)) from error
    return AnalysisSettings(
        model=effective_model,
        strength=strength,
        language=language,
        prompt_version=str(summary["prompt_version"]),
        asr_engine=asr_engine,
        asr_config=_asr_settings_snapshot(store),
        max_chunk_tokens=max_chunk_tokens,
        summary_engine=SUMMARY_ENGINE_OPENAI,
        summary_provider=str(summary["summary_provider"]),
        summary_template=template_id,
        summary_style=style_id,
        summary_config=summary_config,
        summary_prompt=str(summary["summary_prompt"]),
        summary_prompt_hash=str(summary["summary_prompt_hash"]),
        summary_skill=summary["summary_skill"],
        extra_instruction=extra_instruction.strip() if extra_instruction and extra_instruction.strip() else None,
    )


def _settings_response(
    store: SQLiteStore,
    archive_root,
    asr_model_root: Path,
    skills_root: Path,
) -> SettingsResponse:
    asr_engine = store.get_setting("asr_engine") or "cloud"
    cloud_api_url, cloud_model = _configured_cloud_asr_values(store)

    local_model = _local_asr_model(store)
    asr_model = local_model if asr_engine == "local" else cloud_model
    summary = _summary_settings_snapshot(store, skills_root, strict_skill=False)
    summary_config = dict(summary["summary_config"])
    summary_engine = str(summary["summary_engine"])
    stored_summary_url = store.get_setting("summary_api_url")
    stored_summary_model = store.get_setting("summary_model")
    configured_summary_model = stored_summary_model.strip() if stored_summary_model else None
    effective_summary_model = configured_summary_model or ""
    try:
        summary_key_configured = bool(
            store.get_secret_setting("summary_api_key", purpose="总结模型 API Key")
        )
    except SecretStorageError:
        summary_key_configured = False
    summary_configured = bool(
        summary_key_configured
        and configured_summary_model
        and stored_summary_url
        and stored_summary_url.strip()
    )
    selected_skill = summary.get("summary_skill") or {}
    bilibili_connection = store.get_platform_connection("bilibili")
    try:
        bilibili_session_available = bool(store.get_bilibili_session_cookie())
    except SecretStorageError:
        bilibili_session_available = False

    return SettingsResponse(
        archive_root=str(archive_root),
        default_model=effective_summary_model,
        external_ai_configured=summary_configured,
        summary_engine=summary_engine,
        summary_provider=str(summary["summary_provider"]),
        summary_api_url=stored_summary_url.strip() if stored_summary_url else None,
        summary_api_mode=str(summary_config["api_mode"]),
        summary_model=configured_summary_model,
        summary_configured=summary_configured,
        summary_api_key_configured=summary_key_configured,
        summary_prompt=str(summary["summary_prompt"]),
        summary_prompt_configured=bool(store.get_setting("summary_prompt")),
        summary_prompt_version=str(summary["prompt_version"]),
        summary_prompt_hash=str(summary["summary_prompt_hash"]),
        summary_skill_path=summary.get("summary_skill_path"),
        summary_skill_name=selected_skill.get("name"),
        summary_skill_hash=selected_skill.get("sha256"),
        summary_skill_error=summary.get("summary_skill_error"),
        summary_skills_root=str(skills_root),
        summary_skill_options=[
            _summary_skill_response(document)
            for document in list_skill_documents(skills_root)
        ],
        bilibili_browser=None,
        bilibili_browser_profile=None,
        bilibili_connected=bool(
            bilibili_connection
            and bilibili_connection.status == CONNECTED
            and bilibili_session_available
        ),
        asr_configured=_asr_is_configured(store, asr_model_root),
        asr_engine=asr_engine,
        asr_provider=store.get_setting("asr_provider"),
        asr_api_url=cloud_api_url,
        asr_model=asr_model,
        asr_cloud_configured=_cloud_asr_configured(store),
        asr_cloud_api_url=cloud_api_url,
        asr_cloud_model=cloud_model,
        asr_local_configured=bool(
            local_asr_runtime_available()
            and local_model
            and is_local_model_ready(asr_model_root, local_model)
        ),
        asr_local_model=local_model,
        task_concurrency=1,
        ai_tag_recommendation_enabled=(store.get_setting("ai_tag_recommendation_enabled") or "false").lower() == "true",
        enable_ai_ask=(store.get_setting("enable_ai_ask") or "true").lower() == "true",
        ai_ask_cloud_configured=bool(
            store.get_secret_setting(
                "ai_ask_siliconflow_api_key", purpose="AI 问答硅基流动 API Key"
            )
        ),
    )


def _prepare_archive_root(value: str | None) -> Path:
    if value is None or not value.strip():
        raise OSError("归档位置不能为空")
    selected = Path(value.strip()).expanduser().resolve()
    selected.mkdir(parents=True, exist_ok=True)
    if not selected.is_dir():
        raise OSError("选择的路径不是目录")
    return selected


def _prepare_summary_skills_root(value: str | None) -> Path:
    if value is None or not value.strip():
        raise OSError("Skill 存储目录不能为空")
    selected = Path(value.strip()).expanduser().resolve()
    selected.mkdir(parents=True, exist_ok=True)
    if not selected.is_dir():
        raise OSError("选择的 Skill 路径不是目录")
    return selected


def _pick_directory(title: str) -> str | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as error:
        raise OSError("当前 Python 环境没有可用的系统目录选择器") from error

    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(title=title)
    except tk.TclError as error:
        raise OSError("无法打开系统目录选择器") from error
    finally:
        if root is not None:
            root.destroy()
    return str(Path(selected).expanduser().resolve()) if selected else None


def _pick_archive_directory() -> str | None:
    return _pick_directory("选择知识归档位置")


def _bilibili_cookie(store: SQLiteStore) -> str | None:
    try:
        return store.get_bilibili_session_cookie()
    except SecretStorageError as error:
        _save_bilibili_status(
            store,
            REAUTH_REQUIRED,
            "B站本地登录会话无法读取，请重新扫码登录",
            account_label=None,
            last_checked_at=datetime.now(UTC),
            last_connected_at=None,
        )
        raise LinkImportError(str(error)) from error


def _preflight_link_connection(store: SQLiteStore, url: str) -> None:
    """Stop known-invalid Bilibili sessions before creating an empty job."""

    if detect_platform(url) is not SourcePlatform.BILIBILI:
        return
    definition = get_platform_definition("bilibili")
    assert definition is not None
    connection = _connection_or_default(store, definition)
    if connection is None:
        return
    if connection.status == CHECKING:
        # CHECKING is only an in-memory QR phase.  Legacy persisted rows are
        # normalized by _connection_or_default before this guard is reached.
        return
    if connection.status in {EXPIRED, REAUTH_REQUIRED, RISK_CONTROLLED}:
        raise LinkImportError(
            "B站登录前置检查失败："
            + (connection.message or "请重新登录后再导入链接")
        )


def _prepare_link_sources(
    *,
    url: str,
    title: str | None,
    language: str | None,
    bilibili_cookie: str | None,
    asr_configured: bool,
    page_number: int | None = None,
):
    # Keep the old API-level seam usable for tests and integrations that inject
    # one prepared source; production uses the multi-P expansion by default.
    if prepare_link_import is not _DEFAULT_SINGLE_LINK_PREPARER:
        return [
            prepare_link_import(
                url=url,
                title=title,
                language=language,
                bilibili_cookie=bilibili_cookie,
                asr_configured=asr_configured,
            )
        ]
    return prepare_link_imports(
        url=url,
        title=title,
        language=language,
        bilibili_cookie=bilibili_cookie,
        asr_configured=asr_configured,
        **({"page_number": page_number} if page_number is not None else {}),
    )

def _archive_batch_name(sources) -> str:
    # 批次名整段进入归档目录名，id 只取 8 位十六进制以控制 Windows 路径长度（上限 260）。
    base_title = str(sources[0].title).split(" - ", 1)[0].strip() or "视频批次"
    batch_id = new_id("batch").split("_", 1)[-1][:8]
    return f"batch_{batch_id}-{base_title}"


def _source_with_duplicate_title(store: SQLiteStore, source, duplicate, action: str):
    if duplicate is not None and action == "regenerate":
        return replace(source, title=store.next_duplicate_title(source.title))
    return source


def _source_identity(source) -> tuple[str, str] | None:
    if source.source_url:
        return ("url", str(source.source_url))
    if source.content_hash:
        return ("hash", str(source.content_hash))
    return None


def _require_asr_for_untitled_source(
    store: SQLiteStore,
    source,
    model_root: Path,
    *,
    configured: bool | None = None,
) -> None:
    """Videos without subtitles need the configured public ASR before queuing."""

    if source.transcript is not None:
        return
    if source.audio_path is None:
        return
    if configured is None:
        configured = _asr_is_configured(store, model_root)
    if not configured:
        raise HTTPException(
            status_code=422,
            detail=(
                "无法识别视频内容：该视频没有公开字幕，且未配置 ASR 服务。"
                "请在设置页配置云端 ASR，或下载并选择一个本地 ASR 模型后重试"
            ),
        )


def _discard_temporary_audio(source) -> None:
    if source.audio_is_temp:
        cleanup_temporary_audio(source.audio_path)


configure_logging(resolve_log_dir())
app = create_app()
