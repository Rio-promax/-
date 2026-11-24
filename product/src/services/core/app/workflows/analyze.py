"""Run one local analysis from normalized text through archive writing."""

from __future__ import annotations

import json
import hashlib
import logging
import multiprocessing as mp
import shutil
from dataclasses import replace
from tempfile import TemporaryDirectory
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock, Thread, current_thread
from time import monotonic

from app.adapters.asr.local import (
    LocalAsrError,
    SenseVoiceWorker,
    build_audio_segment_ranges,
    is_local_model_ready,
    local_asr_runtime_available,
    materialize_audio_segment,
    _probe_audio_duration,
    resolved_local_model_identity,
)
from app.adapters.asr.openai_compatible import (
    DEFAULT_API_URL,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS as DEFAULT_ASR_TIMEOUT_SECONDS,
)
from app.adapters.sources.prepared import PreparedSource
from app.adapters.summary.openai_compatible import (
    DEFAULT_SUMMARY_API_URL,
    DEFAULT_SUMMARY_MODEL,
    DEFAULT_SUMMARY_TIMEOUT_SECONDS,
    OpenAICompatibleSummarizer,
    SummaryProviderError,
    SummaryResult,
    SummarySettings,
    api_key_fingerprint,
    contains_summary_draft,
    normalize_summary_provider,
    resolve_summary_api_mode,
    summary_endpoint,
)
from app.archive.schema import build_record
from app.archive.writer import ArchiveBundle, write_archive
from app.db.store import SQLiteStore
from app.domain.jobs import (
    Job,
    JobErrorCode,
    JobState,
    checkpoint_config_fingerprint,
    stable_checkpoint_for,
)
from app.domain.models import (
    AnalysisRun,
    AnalysisSettings,
    ContentItem,
    ContentKind,
    SummaryStrength,
    Transcript,
    TranscriptSegment,
)
from app.knowledge.chunking import chunk_transcript
from app.knowledge.prompts import (
    DEFAULT_SUMMARY_PROMPT, DEFAULT_TEXT_SUMMARY_PROMPT, prompt_hash, prompt_version,
)
from app.knowledge.skills import SkillFileError, load_skill_document
from app.knowledge.templates import DEFAULT_SUMMARY_TEMPLATE, get_summary_template
from app.knowledge.transcript import transcript_from_dict, transcript_to_dict
from app.workflows.preflight import cloud_asr_ready, local_asr_ready


class SummaryGenerationError(RuntimeError):
    """Raised when a summary cannot be generated and must not be replaced by a transcript."""


class TranscriptCoverageError(RuntimeError):
    """Raised when a video transcript cannot be proven to cover the source."""


# TODO: 产品确认是否需要把片尾无声容差暴露为可配置规则。
_MAX_UNTRANSCRIBED_TAIL_SECONDS = 5.0
# Kept as a test/compatibility override for callers that explicitly patch the
# old setting.  The default path derives a soft budget from the recent RTF
# samples instead of applying a fixed deadline to the complete task.
ASR_CALL_DEADLINE_SECONDS = float(DEFAULT_ASR_TIMEOUT_SECONDS)
ASR_MODEL_STARTUP_TIMEOUT_SECONDS = 180.0
ASR_SEGMENT_NO_PROGRESS_TIMEOUT_SECONDS = 120.0
ASR_CANCEL_TIMEOUT_SECONDS = 10.0
ASR_SEGMENT_TARGET_SECONDS = 30.0
ASR_SEGMENT_MAX_SECONDS = 60.0
ASR_WORKER_IDLE_SECONDS = 600.0
ASR_DEFAULT_BATCH_SIZE = 1
ASR_BATCH_MEMORY_LIMIT_MB = 4096.0
_ASR_POLL_INTERVAL_SECONDS = 0.1
logger = logging.getLogger(__name__)


def asr_config_fingerprint(
    *,
    model_id: str,
    language: str | None,
    batch_size: int = 1,
    target_seconds: float = ASR_SEGMENT_TARGET_SECONDS,
    max_seconds: float = ASR_SEGMENT_MAX_SECONDS,
    model_sha256: str | None = None,
) -> str:
    """Return the stable identity of one product-level ASR segment set."""

    payload = {
        "engine": "funasr",
        "model": model_id,
        # A downloaded SenseVoice model is identified by its manifest digest,
        # never by the mutable ModelScope ``master`` ref.  ``unresolved`` is
        # retained only for unit callers that exercise the fingerprint helper
        # without a model directory; the real workflow supplies the digest.
        "model_sha256": (
            str(model_sha256).strip()
            if model_sha256
            else ("unresolved" if model_id == "sensevoice-small" else None)
        ),
        "language": language or "auto",
        "vad": "product-ranges-v1",
        "batch_size": int(batch_size),
        "target_seconds": float(target_seconds),
        "max_seconds": float(max_seconds),
        "device": "cpu",
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _is_subtitle_source(source_kind: object) -> bool:
    """Return whether a prepared transcript came from a subtitle track."""

    return isinstance(source_kind, str) and "subtitle" in source_kind.casefold()


def _asr_stats(job) -> dict[str, object]:
    stats = job.metadata.get("asr_stats")
    if not isinstance(stats, dict):
        stats = {}
        job.metadata["asr_stats"] = stats
    phase_seconds = stats.get("phase_seconds")
    if not isinstance(phase_seconds, dict):
        stats["phase_seconds"] = {}
    return stats


def _update_asr_timing(
    job,
    stats: dict[str, object],
    *,
    completed_audio_seconds: float,
    total_audio_seconds: float,
    elapsed_seconds: float,
    completed: bool = False,
) -> None:
    """Persist live ASR elapsed/RTF/ETA from durable audio progress."""

    completed_audio = max(0.0, float(completed_audio_seconds))
    total_audio = max(0.0, float(total_audio_seconds))
    elapsed = max(0.0, float(elapsed_seconds))
    rtf = elapsed / completed_audio if completed_audio > 0.0 else None
    eta = 0.0 if completed else (
        max(0.0, total_audio - completed_audio) * rtf
        if rtf is not None
        else None
    )
    stats["completed_audio_seconds"] = completed_audio
    stats["asr_elapsed_seconds"] = elapsed
    stats["asr_rtf"] = rtf
    stats["asr_eta_seconds"] = eta
    job.metadata["asr_completed_audio_seconds"] = completed_audio
    job.metadata["asr_elapsed_seconds"] = elapsed
    if rtf is None:
        job.metadata.pop("asr_rtf", None)
    else:
        job.metadata["asr_rtf"] = rtf
    if eta is None:
        job.metadata.pop("asr_eta_seconds", None)
    else:
        job.metadata["asr_eta_seconds"] = eta


def _validate_video_transcript(
    transcript: Transcript, duration_seconds: float | None
) -> str:
    if not transcript.segments:
        return "M0"
    if duration_seconds is None:
        raise TranscriptCoverageError("无法确认视频时长，不能验证是否已完整识别视频内容")
    transcript_end = max((segment.end_seconds for segment in transcript.segments), default=0.0)
    if transcript_end + _MAX_UNTRANSCRIBED_TAIL_SECONDS < duration_seconds:
        return "M1"
    return "M2"


def _asr_process_entry(
    result_connection,
    engine: str,
    audio_path: str,
    language: str | None,
    cloud_settings: dict[str, object] | None,
    local_model_path: str | None,
    local_model_id: str | None,
) -> None:
    """Run one ASR call in the narrowly scoped killable boundary."""

    try:
        if engine == "local":
            if not local_model_path or not local_model_id:
                raise RuntimeError("本地 ASR 配置不完整")
            from app.adapters.asr.local import FasterWhisperTranscriber, SenseVoiceTranscriber

            transcriber = (
                SenseVoiceTranscriber(Path(local_model_path), model_id=local_model_id)
                if local_model_id == "sensevoice-small"
                else FasterWhisperTranscriber(Path(local_model_path), model_id=local_model_id)
            )
            # This marks process startup, not completion of the model's full
            # decode.  The parent uses the event to separate model-startup
            # timeout from the per-segment no-progress timeout.
            result_connection.send({"event": "model_ready"})
            transcript = transcriber.transcribe(Path(audio_path), language=language)
        else:
            if not isinstance(cloud_settings, dict):
                raise RuntimeError("云端 ASR 配置不完整")
            from app.adapters.asr.openai_compatible import (
                OpenAICompatibleTranscriber,
                TranscriptionSettings,
            )

            transcriber = OpenAICompatibleTranscriber(TranscriptionSettings(**cloud_settings))
            result_connection.send({"event": "model_ready"})
            transcript = transcriber.transcribe(Path(audio_path), language=language)
        result_connection.send({"ok": True, "transcript": transcript})
    except TimeoutError as error:
        try:
            result_connection.send(
                {
                    "ok": False,
                    "timed_out": True,
                    "error": str(error).strip() or type(error).__name__,
                }
            )
        except (BrokenPipeError, OSError):
            pass
    except BaseException as error:
        try:
            result_connection.send(
                {
                    "ok": False,
                    "error": str(error).strip() or type(error).__name__,
                }
            )
        except (BrokenPipeError, OSError):
            pass
    finally:
        result_connection.close()


def _stop_asr_process(process) -> None:
    """Stop and reap one ASR child before the queue can run another job."""

    if process.is_alive():
        process.terminate()
    process.join(timeout=2)
    if process.is_alive():
        killer = getattr(process, "kill", None)
        if killer is not None:
            killer()
            # Do not let the queue release its sole execution slot until the
            # forced child has actually been reaped.
            process.join()


class AnalysisWorkflow:
    """The small MVP pipeline, deliberately kept in process while jobs are local."""

    def __init__(
        self,
        store: SQLiteStore,
        archive_root: Path,
        asr_model_root: Path | None = None,
        skills_root: Path | None = None,
        temp_root: Path | None = None,
    ) -> None:
        self.store = store
        self.archive_root = archive_root
        self.asr_model_root = asr_model_root or Path("local/asr-models").resolve()
        self.skills_root = skills_root or Path("skills").resolve()
        self.temp_root = temp_root or archive_root / ".tmp"
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self._sensevoice_worker: SenseVoiceWorker | None = None
        self._sensevoice_worker_key: str | None = None
        self._sensevoice_worker_last_used = 0.0
        self._sensevoice_worker_lock = Lock()
        self._sensevoice_idle_stop = Event()
        self._sensevoice_idle_thread = Thread(
            target=self._release_idle_sensevoice_worker,
            name="sensevoice-idle-reaper",
            daemon=True,
        )
        self._sensevoice_idle_thread.start()

    def _release_idle_sensevoice_worker(self) -> None:
        """Release an unused resident Worker without waiting for another job."""

        while not self._sensevoice_idle_stop.wait(
            min(30.0, max(0.1, ASR_WORKER_IDLE_SECONDS / 4.0))
        ):
            with self._sensevoice_worker_lock:
                if (
                    self._sensevoice_worker is not None
                    and self._sensevoice_worker_last_used > 0.0
                    and monotonic() - self._sensevoice_worker_last_used
                    > ASR_WORKER_IDLE_SECONDS
                ):
                    self._sensevoice_worker.close()
                    self._sensevoice_worker = None
                    self._sensevoice_worker_key = None
                    self._sensevoice_worker_last_used = 0.0

    def close(self) -> None:
        """Stop the one resident local ASR worker during application shutdown."""

        self._sensevoice_idle_stop.set()
        with self._sensevoice_worker_lock:
            if self._sensevoice_worker is not None:
                self._sensevoice_worker.close()
            self._sensevoice_worker = None
            self._sensevoice_worker_key = None
            self._sensevoice_worker_last_used = 0.0
        if self._sensevoice_idle_thread is not current_thread():
            self._sensevoice_idle_thread.join(timeout=1)

    def _get_sensevoice_worker(self, model_path: Path) -> SenseVoiceWorker:
        key = str(model_path.resolve())
        with self._sensevoice_worker_lock:
            if (
                self._sensevoice_worker is None
                or self._sensevoice_worker_key != key
                or not self._sensevoice_worker.alive
                or monotonic() - self._sensevoice_worker_last_used > ASR_WORKER_IDLE_SECONDS
            ):
                if self._sensevoice_worker is not None:
                    self._sensevoice_worker.close()
                self._sensevoice_worker = SenseVoiceWorker(
                    model_path,
                    startup_timeout_seconds=ASR_MODEL_STARTUP_TIMEOUT_SECONDS,
                    segment_timeout_seconds=ASR_SEGMENT_NO_PROGRESS_TIMEOUT_SECONDS,
                )
                self._sensevoice_worker_key = key
            self._sensevoice_worker_last_used = monotonic()
            return self._sensevoice_worker

    def _touch_sensevoice_worker(self, worker: SenseVoiceWorker) -> None:
        """Keep the idle reaper from closing a Worker during active decoding."""

        with self._sensevoice_worker_lock:
            if self._sensevoice_worker is worker:
                self._sensevoice_worker_last_used = monotonic()

    def _selected_sensevoice_batch_size(self) -> tuple[int, str]:
        """Read only a validated benchmark selection; otherwise stay at one."""

        raw = self.store.get_setting("asr_batch_selection")
        if not raw:
            return ASR_DEFAULT_BATCH_SIZE, "default_batch_1_until_fixed_sample_benchmark"
        try:
            selection = json.loads(raw)
        except (TypeError, ValueError):
            return ASR_DEFAULT_BATCH_SIZE, "invalid_benchmark_selection_fallback_batch_1"
        if not isinstance(selection, dict) or selection.get("model_id") != "sensevoice-small":
            return ASR_DEFAULT_BATCH_SIZE, "benchmark_model_mismatch_fallback_batch_1"
        try:
            batch_size = int(selection.get("selected_batch_size", 1))
        except (TypeError, ValueError):
            return ASR_DEFAULT_BATCH_SIZE, "invalid_benchmark_selection_fallback_batch_1"
        if batch_size not in {1, 2, 4}:
            return ASR_DEFAULT_BATCH_SIZE, "invalid_benchmark_selection_fallback_batch_1"
        status = str(selection.get("status") or "")
        if batch_size > 1 and status != "passed":
            return ASR_DEFAULT_BATCH_SIZE, f"{status or 'unverified'}_fallback_batch_1"
        return batch_size, "benchmark_passed" if batch_size > 1 else "benchmark_fallback_batch_1"

    def submit(
        self,
        source: PreparedSource,
        settings: AnalysisSettings,
        *,
        content_id: str | None = None,
        archive_group: str | None = None,
        import_batch_id: str | None = None,
        archive_index: int | None = None,
        archive_total: int | None = None,
        priority: int = 0,
        resume_checkpoint: str | None = None,
        resume_progress: int = 0,
        resume_checkpoint_dir: str | None = None,
        resume_checkpoint_saved_at: str | None = None,
    ) -> tuple[ContentItem, AnalysisRun, Job]:
        if content_id is None:
            content = self.store.create_content(
                kind=source.kind,
                title=source.title,
                platform=source.platform,
                canonical_url=source.source_url,
                thumbnail_url=source.thumbnail_url,
                author=source.author,
                language=source.transcript.language if source.transcript else None,
                duration_seconds=source.duration_seconds,
                content_hash=source.content_hash,
                published_at=source.published_at,
                acquisition_method=source.acquisition_method,
                processing_model=settings.model,
            )
        else:
            content = self.store.get_content(content_id)
        if content.kind in {ContentKind.ARTICLE, ContentKind.IMAGE, ContentKind.PDF} and (
            not settings.summary_prompt or settings.summary_prompt.strip() == DEFAULT_SUMMARY_PROMPT
        ):
            settings = replace(
                settings, summary_prompt=DEFAULT_TEXT_SUMMARY_PROMPT,
                summary_prompt_hash=prompt_hash(DEFAULT_TEXT_SUMMARY_PROMPT),
                prompt_version=prompt_version(DEFAULT_TEXT_SUMMARY_PROMPT),
            )
        run, job = self.store.create_analysis_run(content.id, settings, priority=priority)
        source_kind = source.transcript.source_kind if source.transcript else None
        subtitle_hit = _is_subtitle_source(source_kind)
        if source.transcript is not None:
            asr_skipped_reason = "subtitle_hit" if subtitle_hit else "existing_transcript"
            asr_fallback_reason = None
        elif source.audio_path:
            asr_skipped_reason = None
            asr_fallback_reason = "subtitle_unavailable"
        else:
            asr_skipped_reason = None
            asr_fallback_reason = "not_applicable"
        job.metadata = {
            "source_path": source.source_path,
            "source_url": source.source_url,
            "source_platform": source.platform.value,
            "source_kind": source_kind,
            "acquisition_method": source.acquisition_method,
            "source_note": source.source_note,
            "thumbnail_url": source.thumbnail_url,
            "archive_path": None,
            "archive_batch_name": archive_group,
            "import_batch_id": import_batch_id,
            "archive_item_number": archive_index,
            "archive_total": archive_total,
            "summary_preview": None,
            "audio_path": source.audio_path,
            "audio_is_temp": source.audio_is_temp,
            "checkpoint_dir": resume_checkpoint_dir
            or str(self.archive_root / ".checkpoints" / job.id),
            "asr_stats": {
                "subtitle_hit": subtitle_hit,
                "asr_skipped": source.transcript is not None,
                "asr_skipped_reason": asr_skipped_reason,
                "asr_fallback_reason": asr_fallback_reason,
                "batch_size": ASR_DEFAULT_BATCH_SIZE,
                "batch_selection": "default_batch_1_until_fixed_sample_benchmark",
                "phase_seconds": {
                    "download": source.download_seconds,
                    "vad": None,
                    "model_load": None,
                    "asr": 0.0 if source.transcript is not None else None,
                    "merge": 0.0 if source.transcript is not None else None,
                    "summary": None,
                },
            },
        }
        # R8：写入断点配置身份，重试时据此判断旧摘要是否因换模型/提示词失效。
        job.metadata["checkpoint_config_fingerprint"] = checkpoint_config_fingerprint(
            model=str(run.settings_snapshot.get("model") or ""),
            prompt_hash=str(run.settings_snapshot.get("summary_prompt_hash") or ""),
            max_chunk_tokens=int(run.settings_snapshot.get("max_chunk_tokens") or 800),
            language=run.settings_snapshot.get("language"),
        )
        if resume_checkpoint_saved_at:
            job.metadata["checkpoint_saved_at"] = resume_checkpoint_saved_at
        if resume_checkpoint:
            job.metadata["last_stable_checkpoint"] = resume_checkpoint
            job.metadata["resume_checkpoint"] = resume_checkpoint
            job.checkpoint = resume_checkpoint
            job.progress = max(0, min(99, int(resume_progress)))
        self.store.save_job(job)
        return content, run, job

    def _checkpoint_files_exist(self, checkpoint_dir: str | None, checkpoint: str) -> bool:
        """R8：失败收尾只确认稳定断点产物还在，内容可读性由 retry 判据负责。"""
        names = {
            "transcript_ready": ("transcript.json",),
            "chunks_ready": ("transcript.json", "chunks.json"),
            "summary_ready": ("transcript.json", "chunks.json", "summary.json"),
        }.get(checkpoint)
        if not names or not checkpoint_dir:
            return False
        directory = Path(checkpoint_dir)
        return all((directory / name).is_file() for name in names)

    def discard_checkpoints(self, job: Job) -> None:
        """Remove the task's intermediate materials when they are no longer resumable."""

        directory = Path(
            job.metadata.get("checkpoint_dir")
            or (self.archive_root / ".checkpoints" / job.id)
        ).resolve()
        root = (self.archive_root / ".checkpoints").resolve()
        # The path is persisted by ``submit`` as one task-owned directory.
        # Keep the root guard, but also allow a test/import-created explicit
        # task directory outside the default archive root to be reclaimed.
        if directory == root or directory == directory.parent or directory == Path(directory.anchor):
            return
        shutil.rmtree(directory, ignore_errors=True)

    def _transcribe(self, job) -> Transcript:
        """Transcribe the prepared audio through the selected local or cloud ASR."""

        audio_path = job.metadata.get("audio_path")
        if not audio_path or not Path(audio_path).is_file():
            raise RuntimeError("缺少可转写的音频文件，无法识别视频内容")
        if Path(audio_path).stat().st_size == 0:
            raise RuntimeError("可转写的音频文件为空，无法识别视频内容，请更换来源")
        run = self.store.get_analysis_run(job.analysis_run_id)
        asr_config = run.settings_snapshot.get("asr_config") or {}
        engine = asr_config.get("engine") or self.store.get_setting("asr_engine") or "cloud"
        # 云端未配置时不再直接失败：本地就绪就按本地转写，两边都不可用才报错。
        if (
            engine != "local"
            and not cloud_asr_ready(self.store)
            and local_asr_ready(self.store, self.asr_model_root)
        ):
            engine = "local"
            job.metadata["asr_engine_fallback"] = "cloud_not_configured"

        if engine == "local":
            model_id = (
                asr_config.get("local_model")
                or self.store.get_setting("asr_local_model")
                or self.store.get_setting("asr_model")
            )
            if not local_asr_runtime_available():
                raise WorkflowAsrError(
                    JobErrorCode.ASR_RUNTIME_UNAVAILABLE,
                    "本地 ASR 组件尚未安装，请在设置页安装本地组件后重试",
                )
            from app.adapters.asr.local import (
                FasterWhisperTranscriber,
                SenseVoiceTranscriber,
                local_model_path,
            )

            if not is_local_model_ready(self.asr_model_root, model_id):
                raise WorkflowAsrError(
                    JobErrorCode.ASR_LOCAL_MODEL_NOT_INSTALLED,
                    "本地 ASR 模型尚未下载完成，请在设置页下载并选择一个本地模型后重试",
                )
            resolved_model_path = local_model_path(self.asr_model_root, model_id)
            if model_id == "sensevoice-small":
                return self._transcribe_sensevoice_segments(
                    job,
                    resolved_model_path,
                    language=run.settings_snapshot.get("language"),
                )
            transcriber = (
                SenseVoiceTranscriber(resolved_model_path, model_id=model_id)
                if model_id == "sensevoice-small"
                else FasterWhisperTranscriber(resolved_model_path, model_id=model_id)
            )
            language = run.settings_snapshot.get("language")
            if transcriber.__class__.__module__ == "app.adapters.asr.local":
                transcript = self._run_isolated_asr(
                    job,
                    engine="local",
                    audio_path=str(audio_path),
                    language=language,
                    local_model_path=str(resolved_model_path),
                    local_model_id=model_id,
                )
            else:
                transcript = transcriber.transcribe(Path(audio_path), language=language)
        else:
            model_id = (
                asr_config.get("cloud_model")
                or self.store.get_setting("asr_cloud_model")
                or self.store.get_setting("asr_model")
                or DEFAULT_MODEL
            )
            api_key = self.store.get_secret_setting("asr_cloud_api_key", purpose="云端 ASR API Key") or self.store.get_secret_setting("asr_api_key", purpose="云端 ASR API Key")
            if not api_key:
                raise WorkflowAsrError(
                    JobErrorCode.ASR_CLOUD_NOT_CONFIGURED,
                    "无法识别视频内容：该视频没有公开字幕，且未配置 ASR 服务。"
                    "请在设置页配置云端 ASR，或下载并选择一个本地 ASR 模型后重试",
                )
            from app.adapters.asr.openai_compatible import (
                OpenAICompatibleTranscriber,
                TranscriptionSettings,
            )

            settings = TranscriptionSettings(
                api_url=(
                    asr_config.get("cloud_api_url")
                    or self.store.get_setting("asr_cloud_api_url")
                    or self.store.get_setting("asr_api_url")
                    or DEFAULT_API_URL
                ),
                api_key=api_key,
                model=model_id,
            )
            transcriber = OpenAICompatibleTranscriber(settings)
            language = run.settings_snapshot.get("language")
            if transcriber.__class__.__module__ == "app.adapters.asr.openai_compatible":
                transcript = self._run_isolated_asr(
                    job,
                    engine="cloud",
                    audio_path=str(audio_path),
                    language=language,
                    cloud_settings={
                        "api_url": settings.api_url,
                        "api_key": settings.api_key,
                        "model": settings.model,
                        "provider": settings.provider,
                        "timeout_seconds": settings.timeout_seconds,
                    },
                )
            else:
                transcript = transcriber.transcribe(Path(audio_path), language=language)

        job.metadata["source_kind"] = transcript.source_kind
        job.metadata["asr_model"] = model_id
        return transcript

    def _transcribe_sensevoice_segments(
        self,
        job: Job,
        model_path: Path,
        *,
        language: str | None,
    ) -> Transcript:
        """Recognize SenseVoice audio in durable, independently retryable slices."""

        audio_path_raw = job.metadata.get("audio_path")
        if not isinstance(audio_path_raw, str) or not Path(audio_path_raw).is_file():
            raise WorkflowAsrError(
                JobErrorCode.ASR_LOCAL_MODEL_NOT_INSTALLED,
                "缺少可转写的音频文件，无法运行 SenseVoiceSmall",
            )
        audio_path = Path(audio_path_raw)
        run = self.store.get_analysis_run(job.analysis_run_id)
        content = self.store.get_content(run.content_id)
        duration = float(content.duration_seconds or 0.0)
        if duration <= 0.0:
            duration = _probe_audio_duration(audio_path)
        if duration <= 0.0:
            # Keep a single range when the source does not expose a duration;
            # the worker result still supplies real text and the final video
            # coverage check reports whether the source can be proven complete.
            duration = ASR_SEGMENT_TARGET_SECONDS
        batch_size, batch_selection = self._selected_sensevoice_batch_size()
        job.metadata.pop("asr_no_speech", None)
        stats = _asr_stats(job)
        stats.update(
            {
                "subtitle_hit": False,
                "asr_skipped": False,
                "asr_skipped_reason": None,
                "asr_fallback_reason": "subtitle_unavailable",
                "batch_size": batch_size,
                "batch_selection": batch_selection,
                "audio_seconds": duration,
                "asr_started_at": datetime.now(UTC).isoformat(),
            }
        )
        vad_started = monotonic()
        ranges = build_audio_segment_ranges(
            duration,
            target_seconds=ASR_SEGMENT_TARGET_SECONDS,
            max_seconds=ASR_SEGMENT_MAX_SECONDS,
        )
        phase_seconds = stats["phase_seconds"]
        assert isinstance(phase_seconds, dict)
        phase_seconds["vad"] = max(0.0, monotonic() - vad_started)
        stats["segment_count"] = len(ranges)
        stats["vad_input_audio_seconds"] = duration
        stats["vad_effective_audio_seconds"] = sum(end - start for start, end in ranges)
        model_sha256 = None
        if model_path.exists():
            model_sha256 = resolved_local_model_identity(
                model_path,
                "sensevoice-small",
            )
        fingerprint = asr_config_fingerprint(
            model_id="sensevoice-small",
            language=language,
            batch_size=batch_size,
            model_sha256=model_sha256,
        )
        job.metadata["asr_config_fingerprint"] = fingerprint
        job.metadata["asr_segment_target_seconds"] = ASR_SEGMENT_TARGET_SECONDS
        job.metadata["asr_segment_max_seconds"] = ASR_SEGMENT_MAX_SECONDS
        job.metadata["asr_batch_size"] = batch_size
        job.metadata["asr_audio_seconds"] = duration
        total_budget = self.store.asr_total_budget_seconds(
            engine="sensevoice-small",
            device="cpu",
            audio_seconds=duration,
        )
        job.metadata["asr_total_budget_seconds"] = total_budget
        stats["total_budget_seconds"] = total_budget
        stats["memory_limit_mb"] = ASR_BATCH_MEMORY_LIMIT_MB
        self.store.create_asr_segments(
            job.id,
            fingerprint,
            [
                {
                    "segment_index": index,
                    "start_seconds": start,
                    "end_seconds": end,
                }
                for index, (start, end) in enumerate(ranges)
            ],
        )
        self.store.recover_expired_asr_segments()
        rows = self.store.list_asr_segments(job.id, fingerprint)
        worker = self._get_sensevoice_worker(model_path)
        worker_id = f"{job.worker_id or 'local-worker'}:asr"
        asr_started = monotonic()
        checkpoint_dir = Path(
            job.metadata.get("checkpoint_dir")
            or (self.archive_root / ".checkpoints" / job.id)
        )
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        completed_count = sum(row.status == "completed" for row in rows)
        recovery_count = 0
        materialization_seconds = 0.0
        recognition_seconds = 0.0
        model_load_seconds = 0.0
        cold_start_seen = False
        retry_counts: dict[str, int] = {}

        def cancelled() -> bool:
            try:
                latest = self.store.get_job(job.id)
            except LookupError:
                return True
            return (
                latest.state in {JobState.CANCELLED, JobState.PAUSED}
                or latest.attempt != job.attempt
                or latest.worker_id != job.worker_id
            )

        total_segments = len(rows)
        while True:
            rows = self.store.list_asr_segments(job.id, fingerprint)
            pending_rows = [row for row in rows if row.status == "pending"]
            if not pending_rows:
                self.store.recover_expired_asr_segments()
                rows = self.store.list_asr_segments(job.id, fingerprint)
                pending_rows = [row for row in rows if row.status == "pending"]
            if not pending_rows:
                if all(row.status == "completed" for row in rows):
                    break
                raise WorkflowAsrError(
                    JobErrorCode.UNKNOWN,
                    "ASR 片段当前由其他 Worker 处理，无法安全恢复",
                )
            next_pending = pending_rows[0]
            batch_rows = pending_rows[:batch_size]
            self._assert_current_attempt(job)
            segment_retries = retry_counts.get(next_pending.id, 0)

            startup_retries = 0
            while True:
                try:
                    ensure_started = getattr(worker, "ensure_started", None)
                    if callable(ensure_started):
                        worker_generation = int(ensure_started(cancel_check=cancelled))
                    else:
                        worker_generation = int(getattr(worker, "generation", 0) or 0)
                    break
                except (TimeoutError, LocalAsrError) as error:
                    worker.close()
                    if cancelled():
                        raise WorkflowCancelled("任务已取消") from error
                    recovery_count += 1
                    if startup_retries >= 1:
                        raise WorkflowAsrError(
                            JobErrorCode.ASR_TIMEOUT,
                            "SenseVoiceSmall Worker 启动失败或超时，已重建一次，请重试",
                        ) from error
                    startup_retries += 1
                    worker = self._get_sensevoice_worker(model_path)

            claimed_batch = []
            for _target in batch_rows:
                claimed = self.store.claim_asr_segment(
                    job.id,
                    fingerprint,
                    worker_id,
                    lease_seconds=150,
                    worker_generation=worker_generation,
                )
                if claimed is None:
                    self.store.recover_expired_asr_segments()
                    claimed = self.store.claim_asr_segment(
                        job.id,
                        fingerprint,
                        worker_id,
                        lease_seconds=150,
                        worker_generation=worker_generation,
                    )
                if claimed is None:
                    for prior in claimed_batch:
                        self.store.fail_asr_segment(
                            prior.id,
                            worker_id,
                            "批量领取未完成，等待恢复",
                            worker_generation=prior.worker_generation,
                            retryable=True,
                        )
                    raise WorkflowAsrError(
                        JobErrorCode.UNKNOWN,
                        "ASR 片段当前由其他 Worker 处理，无法安全恢复",
                    )
                claimed_batch.append(claimed)
            claimed = claimed_batch[0]
            worker_was_cold = bool(getattr(worker, "last_call_cold", False))
            startup_seconds = getattr(worker, "last_startup_seconds", None)
            heartbeat_state = {"last": 0.0}

            def lease_heartbeat() -> None:
                now = monotonic()
                if now - heartbeat_state["last"] < 2.0:
                    return
                heartbeat_state["last"] = now
                for active in claimed_batch:
                    if not self.store.heartbeat_asr_segment(
                        active.id,
                        worker_id,
                        worker_generation=active.worker_generation,
                        lease_seconds=150,
                    ):
                        return
                self._touch_sensevoice_worker(worker)
                try:
                    latest = self.store.get_job(job.id)
                    if latest.attempt != job.attempt or latest.worker_id != job.worker_id:
                        return
                    latest.heartbeat(lease_seconds=300)
                    latest.metadata["asr_heartbeat_at"] = datetime.now(UTC).isoformat()
                    self.store.save_job(latest)
                except (LookupError, ValueError):
                    return

            try:
                with TemporaryDirectory(
                    prefix="asr-segment-",
                    dir=str(self.temp_root),
                ) as segment_directory:
                    slice_paths = []
                    for active in claimed_batch:
                        materialize_started = monotonic()
                        slice_paths.append(
                            materialize_audio_segment(
                                audio_path,
                                start_seconds=active.start_seconds,
                                end_seconds=active.end_seconds,
                                directory=Path(segment_directory),
                            )
                        )
                        materialization_seconds += max(0.0, monotonic() - materialize_started)
                    recognition_started = monotonic()
                    if len(slice_paths) == 1:
                        text, detected_language = worker.transcribe(
                            slice_paths[0],
                            language=language,
                            cancel_check=cancelled,
                            on_lease_heartbeat=lease_heartbeat,
                        )
                        results = [(text, detected_language)]
                    else:
                        transcribe_batch = getattr(worker, "transcribe_batch", None)
                        if not callable(transcribe_batch):
                            raise LocalAsrError("当前 SenseVoice Worker 不支持批量识别")
                        results = list(
                            transcribe_batch(
                                slice_paths,
                                language=language,
                                cancel_check=cancelled,
                                on_lease_heartbeat=lease_heartbeat,
                            )
                        )
                        if len(results) != len(claimed_batch):
                            raise LocalAsrError("SenseVoiceSmall batch 返回片段数量不一致")
                    self._touch_sensevoice_worker(worker)
                    recognition_seconds += max(0.0, monotonic() - recognition_started)
                    if worker_was_cold:
                        cold_start_seen = True
                        if isinstance(startup_seconds, (int, float)):
                            model_load_seconds += max(0.0, float(startup_seconds))
                if cancelled():
                    raise WorkflowCancelled("任务已取消")
                for active, result in zip(claimed_batch, results):
                    text, detected_language = result
                    self.store.commit_asr_segment(
                        active.id,
                        worker_id,
                        worker_generation=active.worker_generation,
                        text=text,
                        language=detected_language or language,
                    )
                completed_count += len(claimed_batch)
                retry_counts.pop(next_pending.id, None)
            except (WorkflowCancelled, WorkflowPaused):
                for active in claimed_batch:
                    self.store.fail_asr_segment(
                        active.id,
                        worker_id,
                        "任务已停止",
                        worker_generation=active.worker_generation,
                        retryable=True,
                    )
                raise
            except TimeoutError as error:
                for active in claimed_batch:
                    self.store.fail_asr_segment(
                        active.id,
                        worker_id,
                        str(error),
                        worker_generation=active.worker_generation,
                        retryable=True,
                    )
                worker.close()
                recovery_count += 1
                if segment_retries >= 1:
                    raise WorkflowAsrError(
                        JobErrorCode.ASR_TIMEOUT,
                        "SenseVoiceSmall 单片识别超过 120 秒无进展，Worker 已重建一次，请重试",
                    ) from error
                segment_retries += 1
                retry_counts[next_pending.id] = segment_retries
                worker = self._get_sensevoice_worker(model_path)
                # Re-enter the same while-loop.  The failed row is still the
                # first pending key, so no older row can be skipped.
                continue
            except LocalAsrError as error:
                for active in claimed_batch:
                    self.store.fail_asr_segment(
                        active.id,
                        worker_id,
                        str(error),
                        worker_generation=active.worker_generation,
                        retryable=True,
                    )
                if cancelled():
                    raise WorkflowCancelled("任务已取消") from error
                worker.close()
                recovery_count += 1
                if segment_retries >= 1:
                    raise WorkflowAsrError(JobErrorCode.UNKNOWN, str(error)) from error
                segment_retries += 1
                retry_counts[next_pending.id] = segment_retries
                worker = self._get_sensevoice_worker(model_path)
                continue

            progress = 40 + int(round(completed_count / max(1, total_segments) * 5))
            job.update_progress(max(job.progress, min(45, progress)), checkpoint="transcribing")
            job.metadata["asr_completed_segments"] = completed_count
            job.metadata["asr_total_segments"] = total_segments
            job.metadata["asr_completed_audio_seconds"] = sum(
                row.end_seconds - row.start_seconds
                for row in self.store.list_asr_segments(job.id, fingerprint)
                if row.status == "completed"
            )
            stats["completed_segments"] = completed_count
            stats["total_segments"] = total_segments
            _update_asr_timing(
                job,
                stats,
                completed_audio_seconds=float(job.metadata["asr_completed_audio_seconds"]),
                total_audio_seconds=duration,
                elapsed_seconds=max(0.0, monotonic() - asr_started),
            )
            stats["recovery_count"] = recovery_count
            stats["worker_generation"] = worker.generation
            stats["worker_cold_start"] = cold_start_seen
            phase_seconds["asr"] = recognition_seconds
            phase_seconds["model_load"] = model_load_seconds or None
            phase_seconds["slice_materialization"] = materialization_seconds
            self._assert_current_attempt(job)
            self.store.save_job(job)

        final_rows = self.store.list_asr_segments(job.id, fingerprint)
        if any(row.status != "completed" for row in final_rows):
            raise WorkflowAsrError(JobErrorCode.TRANSCRIPT_INCOMPLETE, "ASR 片段未全部完成")
        merge_started = monotonic()
        segments = tuple(
            TranscriptSegment(
                row.start_seconds,
                row.end_seconds,
                str(row.text or "").strip(),
            )
            for row in final_rows
            if str(row.text or "").strip()
        )
        phase_seconds["merge"] = max(0.0, monotonic() - merge_started)
        # 无语音（纯音乐、纯画面）是正常结果：交给 M0 材料分级，不再按失败处理。
        job.metadata["asr_no_speech"] = not segments
        elapsed = max(0.0, monotonic() - asr_started)
        self.store.record_asr_performance(
            engine="sensevoice-small",
            device="cpu",
            audio_seconds=duration,
            elapsed_seconds=elapsed,
        )
        job.metadata["asr_elapsed_seconds"] = elapsed
        job.metadata["asr_rtf"] = elapsed / max(0.001, duration)
        job.metadata["asr_eta_seconds"] = 0.0
        job.metadata["asr_budget_warning"] = elapsed > float(job.metadata["asr_total_budget_seconds"])
        job.metadata["asr_worker_generation"] = worker.generation
        _update_asr_timing(
            job,
            stats,
            completed_audio_seconds=sum(
                max(0.0, row.end_seconds - row.start_seconds) for row in final_rows
            ),
            total_audio_seconds=duration,
            elapsed_seconds=elapsed,
            completed=True,
        )
        stats["budget_warning"] = job.metadata["asr_budget_warning"]
        stats["completed_segments"] = len(final_rows)
        stats["total_segments"] = total_segments
        stats["recovery_count"] = recovery_count
        stats["worker_generation"] = worker.generation
        stats["worker_cold_start"] = cold_start_seen
        phase_seconds["asr"] = recognition_seconds
        phase_seconds["model_load"] = model_load_seconds or None
        phase_seconds["slice_materialization"] = materialization_seconds
        job.metadata["source_kind"] = "asr"
        job.metadata["asr_model"] = "sensevoice-small"
        return Transcript(
            language,
            "asr",
            "funasr:sensevoice-small",
            segments,
        )

    def _run_isolated_asr(
        self,
        job: Job,
        *,
        engine: str,
        audio_path: str,
        language: str | None,
        cloud_settings: dict[str, object] | None = None,
        local_model_path: str | None = None,
        local_model_id: str | None = None,
    ) -> Transcript:
        """Run one killable ASR call with startup and soft total budgets."""

        context = mp.get_context("spawn")
        parent_connection, child_connection = context.Pipe(duplex=False)
        process = context.Process(
            target=_asr_process_entry,
            args=(
                child_connection,
                engine,
                audio_path,
                language,
                cloud_settings,
                local_model_path,
                local_model_id,
            ),
            name=f"asr-{job.id}",
            daemon=True,
        )
        try:
            process.start()
        except Exception:
            child_connection.close()
            parent_connection.close()
            raise
        child_connection.close()

        duration = float(job.metadata.get("asr_audio_seconds") or 0.0)
        if duration <= 0.0:
            duration = _probe_audio_duration(Path(audio_path))
        legacy_override = float(ASR_CALL_DEADLINE_SECONDS) != float(DEFAULT_ASR_TIMEOUT_SECONDS)
        total_budget = (
            max(0.01, float(ASR_CALL_DEADLINE_SECONDS))
            if legacy_override
            else self.store.asr_total_budget_seconds(
                engine=local_model_id or engine,
                device="cpu",
                audio_seconds=duration,
            )
        )
        job.metadata["asr_total_budget_seconds"] = total_budget
        job.metadata["asr_startup_timeout_seconds"] = ASR_MODEL_STARTUP_TIMEOUT_SECONDS
        deadline = monotonic() + total_budget
        startup_deadline = monotonic() + min(total_budget, ASR_MODEL_STARTUP_TIMEOUT_SECONDS)
        model_ready = False
        heartbeat_at = 0.0
        payload: dict[str, object] | None = None
        logger.info(
            "ASR call started job_id=%s engine=%s budget_seconds=%s",
            job.id,
            engine,
            total_budget,
        )
        try:
            while True:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    _stop_asr_process(process)
                    logger.warning("ASR call timed out job_id=%s engine=%s", job.id, engine)
                    raise WorkflowAsrError(
                        JobErrorCode.ASR_TIMEOUT,
                        f"ASR 转写超过动态预算 {max(1, int(total_budget))} 秒，已终止本次调用，请重试",
                    )
                try:
                    if parent_connection.poll(min(_ASR_POLL_INTERVAL_SECONDS, remaining)):
                        event = parent_connection.recv()
                        if isinstance(event, dict) and event.get("event") == "model_ready":
                            model_ready = True
                            continue
                        payload = event if isinstance(event, dict) else None
                        break
                except (EOFError, OSError):
                    break
                if not model_ready and monotonic() >= startup_deadline:
                    _stop_asr_process(process)
                    raise WorkflowAsrError(
                        JobErrorCode.ASR_TIMEOUT,
                        f"ASR Worker 启动超过 {max(1, int(ASR_MODEL_STARTUP_TIMEOUT_SECONDS))} 秒，请重试",
                    )
                if not process.is_alive():
                    # A child can exit between ``poll`` and ``is_alive`` while
                    # its final pipe payload is still buffered.
                    try:
                        if parent_connection.poll(0):
                            payload = parent_connection.recv()
                    except (EOFError, OSError):
                        pass
                    break
                now = monotonic()
                if now - heartbeat_at >= 5.0:
                    heartbeat_at = now
                    try:
                        latest = self.store.get_job(job.id)
                        if latest.attempt == job.attempt and latest.worker_id == job.worker_id:
                            latest.heartbeat(lease_seconds=300)
                            latest.metadata["asr_heartbeat_at"] = datetime.now(UTC).isoformat()
                            self.store.save_job(latest)
                    except (LookupError, ValueError):
                        pass
                latest = self.store.get_job(job.id)
                if latest.state is JobState.CANCELLED:
                    _stop_asr_process(process)
                    logger.info("ASR call cancelled job_id=%s engine=%s", job.id, engine)
                    raise WorkflowCancelled("任务已取消")
                if (
                    latest.state is JobState.PAUSED
                    or latest.attempt != job.attempt
                    or latest.worker_id != job.worker_id
                ):
                    _stop_asr_process(process)
                    logger.info(
                        "ASR call stopped for stale attempt job_id=%s engine=%s",
                        job.id,
                        engine,
                    )
                    raise WorkflowPaused("任务执行权已让出")

            if not isinstance(payload, dict):
                raise WorkflowAsrError(
                    JobErrorCode.UNKNOWN,
                    "ASR 调用进程异常退出，请重试",
                )
            if payload.get("timed_out") is True:
                raise WorkflowAsrError(
                    JobErrorCode.ASR_TIMEOUT,
                    "ASR 转写进程报告无进展超时，已终止本次调用，请重试",
                )
            if payload.get("ok") is not True:
                message = str(payload.get("error") or "ASR 调用失败，请重试")
                raise WorkflowAsrError(JobErrorCode.UNKNOWN, message)
            transcript = payload.get("transcript")
            if not isinstance(transcript, Transcript):
                raise WorkflowAsrError(
                    JobErrorCode.UNKNOWN,
                    "ASR 调用返回了无效转写结果，请重试",
                )
            self._assert_current_attempt(job)
            return transcript
        finally:
            _stop_asr_process(process)
            parent_connection.close()

    def _summary_settings_for_run(self, run: AnalysisRun) -> SummarySettings:
        snapshot = run.settings_snapshot
        summary_config = dict(snapshot.get("summary_config") or {})
        api_url = str(summary_config.get("api_url") or DEFAULT_SUMMARY_API_URL).strip()
        api_mode = summary_config.get("api_mode")
        try:
            api_mode = resolve_summary_api_mode(api_url, api_mode)
            current_api_url = str(
                self.store.get_setting("summary_api_url") or DEFAULT_SUMMARY_API_URL
            ).strip()
            current_api_mode = resolve_summary_api_mode(
                current_api_url,
                self.store.get_setting("summary_api_mode"),
            )
            expected_endpoint = summary_endpoint(api_url, api_mode)
            current_endpoint = summary_endpoint(current_api_url, current_api_mode)
        except SummaryProviderError as error:
            raise SummaryGenerationError(f"总结接口配置无效：{error}") from error
        expected_provider = normalize_summary_provider(
            str(snapshot.get("summary_provider") or "openai-compatible")
        )
        current_provider = normalize_summary_provider(
            str(self.store.get_setting("summary_provider") or "openai-compatible")
        )
        try:
            timeout_seconds = int(
                summary_config.get("timeout_seconds", DEFAULT_SUMMARY_TIMEOUT_SECONDS)
            )
        except (TypeError, ValueError) as error:
            raise SummaryGenerationError("总结服务请求超时时间配置无效") from error
        model = str(
            snapshot.get("model") or summary_config.get("model") or DEFAULT_SUMMARY_MODEL
        ).strip()
        if not model or model.startswith("local"):
            model = DEFAULT_SUMMARY_MODEL
        current_model = str(
            self.store.get_setting("summary_model") or DEFAULT_SUMMARY_MODEL
        ).strip()
        if current_model.startswith("local"):
            current_model = DEFAULT_SUMMARY_MODEL
        if summary_config and (
            (expected_provider, expected_endpoint, model)
            != (current_provider, current_endpoint, current_model)
        ):
            raise SummaryGenerationError(
                "总结配置已更新：任务使用的是旧的供应商、地址或模型，请按当前配置重试"
            )
        api_key = self.store.get_secret_setting(
            "summary_api_key",
            purpose="总结模型 API Key",
        ) or ""
        expected_key_fingerprint = str(summary_config.get("api_key_fingerprint") or "")
        if expected_key_fingerprint and api_key_fingerprint(api_key) != expected_key_fingerprint:
            raise SummaryGenerationError(
                "总结 API Key 已更新：任务使用的是旧密钥，请按当前配置重试"
            )
        return SummarySettings(
            api_url=api_url,
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
            api_mode=api_mode,
        )

    def _generate_introduction_with_ai(
        self,
        content: ContentItem,
        run: AnalysisRun,
        summary_markdown: str,
    ) -> str:
        summarizer = OpenAICompatibleSummarizer(self._summary_settings_for_run(run))
        return summarizer.generate_introduction(
            title=content.title,
            summary_markdown=summary_markdown,
        )

    def _summarize_with_ai(
        self,
        content: ContentItem,
        run: AnalysisRun,
        chunks: tuple,
        strength: SummaryStrength,
        template: str | None = None,
        material_level: str = "M2",
    ):
        if material_level == "M0":
            raise SummaryGenerationError("M0 材料不足，不能生成正文总结")
        snapshot = run.settings_snapshot
        prompt = str(snapshot.get("summary_prompt") or DEFAULT_SUMMARY_PROMPT).strip()
        expected_prompt_hash = snapshot.get("summary_prompt_hash")
        if expected_prompt_hash and prompt_hash(prompt) != expected_prompt_hash:
            raise SummaryGenerationError("任务使用的总结 Prompt 快照已损坏，不能继续生成总结")
        if material_level == "M1":
            prompt += (
                "\n\n本次材料等级为 M1：只覆盖当前已处理的部分材料。明确写出已覆盖范围和缺口，"
                "不得把部分内容写成全片或全文结论。"
            )
        extra_instruction = str(snapshot.get("extra_instruction") or "").strip()
        if extra_instruction:
            prompt += f"\n\n本次补充要求：\n{extra_instruction}"

        skill_content: str | None = None
        skill_snapshot = snapshot.get("summary_skill") or {}
        if skill_snapshot:
            skill_path = str(skill_snapshot.get("path") or "")
            try:
                skill = load_skill_document(self.skills_root, skill_path)
            except SkillFileError as error:
                raise SummaryGenerationError(f"总结使用的 Skill 文件不可用：{error}") from error
            expected_skill_hash = str(skill_snapshot.get("sha256") or "")
            if expected_skill_hash and skill.sha256 != expected_skill_hash:
                raise SummaryGenerationError(f"总结使用的 Skill 文件已发生变化：{skill.path}")
            skill_content = skill.content

        summarizer = OpenAICompatibleSummarizer(self._summary_settings_for_run(run))
        try:
            kwargs = {
                "chunks": chunks,
                "title": content.title,
                "strength": strength,
                "prompt": prompt,
                "skill": skill_content,
            }
            if content.kind in {ContentKind.ARTICLE, ContentKind.IMAGE, ContentKind.PDF}:
                kwargs["text_material"] = True
            if template is not None:
                get_summary_template(template)
                kwargs["template"] = template
            style_id = snapshot.get("summary_style") or "general"
            if style_id != "general":
                kwargs["style"] = style_id
            return summarizer.summarize_chunks(**kwargs)
        except SummaryProviderError:
            raise

    def generate_partial_summary(
        self,
        content_id: str,
        *,
        start_seconds: float,
        end_seconds: float,
        template: str,
        chapter_title: str | None = None,
    ):
        if end_seconds <= start_seconds:
            raise ValueError("局部总结结束时间必须大于开始时间")
        entry = self.store.get_history_entry(content_id)
        transcript_path = entry.job.metadata.get("transcript_path")
        if not isinstance(transcript_path, str) or not Path(transcript_path).is_file():
            archive_path = entry.job.metadata.get("archive_path")
            if isinstance(archive_path, str):
                candidate = Path(archive_path) / "transcript.json"
                transcript_path = str(candidate) if candidate.is_file() else None
        if not isinstance(transcript_path, str) or not Path(transcript_path).is_file():
            raise RuntimeError("当前任务没有可用于局部生成的转写材料")
        try:
            transcript = transcript_from_dict(
                json.loads(Path(transcript_path).read_text(encoding="utf-8"))
            )
        except (OSError, ValueError, TypeError) as error:
            raise RuntimeError("转写材料损坏，无法进行局部生成") from error
        selected = tuple(
            segment
            for segment in transcript.segments
            if segment.end_seconds > start_seconds and segment.start_seconds < end_seconds
        )
        if not selected:
            raise ValueError("指定范围没有可用的转写材料")
        partial_transcript = Transcript(
            transcript.language,
            transcript.source_kind,
            transcript.engine,
            tuple(
                TranscriptSegment(
                    max(0.0, segment.start_seconds),
                    segment.end_seconds,
                    segment.text,
                    segment.speaker,
                )
                for segment in selected
            ),
            version=transcript.version,
        )
        chunks = chunk_transcript(
            partial_transcript,
            max_tokens=int(entry.run.settings_snapshot.get("max_chunk_tokens", 800)),
        )
        template_info = get_summary_template(template)
        summary = self._summarize_with_ai(
            entry.content,
            entry.run,
            chunks,
            SummaryStrength(
                entry.run.settings_snapshot.get(
                    "strength", SummaryStrength.STANDARD.value
                )
            ),
            template=template_info.id,
            material_level="M1",
        )
        versions = self.store.list_summary_versions(content_id)
        parent_version_id = versions[0].id if versions else None
        return self.store.create_summary_version(
            content_id,
            summary.markdown,
            template=template_info.id,
            origin="partial",
            parent_version_id=parent_version_id,
            chapter_title=chapter_title,
            source_start_seconds=start_seconds,
            source_end_seconds=end_seconds,
            summary_strength=entry.run.settings_snapshot.get("strength"),
            summary_style=entry.run.settings_snapshot.get("summary_style"),
            material_level="M1",
            source_version=transcript.version,
            source_scope={"start_seconds": start_seconds, "end_seconds": end_seconds},
            processed_source_refs=[
                f"transcript:segment:{ordinal}"
                for ordinal, segment in enumerate(transcript.segments, start=1)
                if segment.end_seconds > start_seconds and segment.start_seconds < end_seconds
            ],
            provider=str(entry.run.settings_snapshot.get("summary_provider") or "unknown"),
            model=str(entry.run.settings_snapshot.get("model") or "unknown"),
            prompt_version=entry.run.prompt_version,
        )
    def _checkpoint_path(self, job: Job, name: str) -> Path:
        directory = Path(
            job.metadata.get("checkpoint_dir")
            or (self.archive_root / ".checkpoints" / job.id)
        )
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{name}.json"

    def _write_checkpoint(self, job: Job, name: str, value: object) -> None:
        path = self._checkpoint_path(job, name)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        job.metadata[f"{name}_path"] = str(path)
        job.metadata["checkpoint_saved_at"] = datetime.now(UTC).isoformat()

    def _read_checkpoint(self, job: Job, name: str) -> object | None:
        raw_path = job.metadata.get(f"{name}_path")
        path = Path(raw_path) if isinstance(raw_path, str) else self._checkpoint_path(job, name)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise RuntimeError(f"阶段性产物 {name} 已损坏，无法恢复") from error

    def _chunks_to_dict(self, chunks: tuple) -> list[dict[str, object]]:
        return [
            {
                "ordinal": chunk.ordinal,
                "start_seconds": chunk.start_seconds,
                "end_seconds": chunk.end_seconds,
                "text": chunk.text,
                "text_hash": chunk.text_hash,
                "token_count": chunk.token_count,
                "chapter_title": chunk.chapter_title,
            }
            for chunk in chunks
        ]

    def _chunks_from_dict(self, value: object) -> tuple:
        if not isinstance(value, list):
            raise RuntimeError("分段阶段性产物格式无效，无法恢复")
        from app.domain.models import Chunk

        chunks = tuple(Chunk(**item) for item in value if isinstance(item, dict))
        if not chunks:
            raise RuntimeError("分段阶段性产物没有内容，无法恢复")
        return chunks

    def _summary_to_dict(self, summary: SummaryResult) -> dict[str, object]:
        return {
            "markdown": summary.markdown,
            "overview": summary.overview,
            "key_points": list(getattr(summary, "key_points", ())),
        }

    def _summary_from_dict(self, value: object) -> SummaryResult | None:
        if not isinstance(value, dict):
            raise RuntimeError("总结阶段性产物格式无效，无法恢复")
        markdown = str(value.get("markdown") or "")
        if contains_summary_draft(markdown):
            return None
        return SummaryResult(
            markdown=markdown,
            overview=str(value.get("overview") or ""),
            key_points=tuple(str(item) for item in value.get("key_points", []) if item),
        )

    def run(self, job_id: str, transcript: Transcript | None, *, acquire_source=None) -> None:
        """Advance a job and reuse persisted checkpoints after a restart."""

        try:
            job = self.store.get_job(job_id)
            if job.state in {
                JobState.CANCELLED,
                JobState.COMPLETED,
                JobState.PAUSED,
                JobState.FAILED,
            }:
                return
            if "resume_checkpoint" in job.metadata:
                candidate = job.metadata.get("resume_checkpoint")
                resume_checkpoint = candidate if isinstance(candidate, str) else None
            else:
                resume_checkpoint = job.checkpoint
            job.claim("local-worker", lease_seconds=300)
            if resume_checkpoint is None:
                job.update_progress(max(job.progress, 10), checkpoint="source_ready")
            else:
                # Keep the committed checkpoint visible while the resumed
                # attempt re-enters the pipeline.  Each subsequent stage
                # writes its own in-progress marker through ``_advance``.
                job.update_progress(max(job.progress, 10), checkpoint=resume_checkpoint)
            self.store.save_job(job)
            self._assert_current_attempt(job)
            self._set_run_status(job.analysis_run_id, "processing")
            # 认领即进入取材：取源是网络操作，可能持续几十秒；这期间不能一直显示排队中。
            if job.state is JobState.QUEUED:
                job.transition(JobState.ACQUIRING)
                self.store.save_job(job)
            if job.metadata.get("deferred_link"):
                source = acquire_source(job)
                temp_audio = source.audio_path if source.audio_is_temp else None
                self._assert_current_attempt(job)
                transcript = source.transcript
                job.metadata.update({
                    "deferred_link": False,
                    "source_url": source.source_url,
                    "source_kind": transcript.source_kind if transcript else None,
                    "source_note": source.source_note,
                    "acquisition_method": source.acquisition_method,
                    "audio_path": source.audio_path,
                    "audio_is_temp": source.audio_is_temp,
                })
                if transcript is not None:
                    self._write_checkpoint(job, "transcript", transcript_to_dict(transcript))
                    job.metadata["resume_checkpoint"] = "transcript_ready"
                self.store.save_job(job)
            stats = _asr_stats(job)
            if transcript is not None:
                subtitle_hit = _is_subtitle_source(transcript.source_kind)
                stats["subtitle_hit"] = subtitle_hit
                stats["asr_skipped"] = True
                stats["asr_skipped_reason"] = (
                    "subtitle_hit" if subtitle_hit else "existing_transcript"
                )
                stats["asr_fallback_reason"] = None
                stats["asr_elapsed_seconds"] = 0.0
                stats["asr_rtf"] = 0.0
                stats["phase_seconds"]["asr"] = 0.0
                stats["phase_seconds"]["merge"] = 0.0
            elif job.metadata.get("audio_path"):
                stats["asr_skipped"] = False
                stats["asr_skipped_reason"] = None
                stats["asr_fallback_reason"] = "subtitle_unavailable"

            job = self._advance(job, JobState.EXTRACTING, 25, "text_loaded")
            job = self._advance(job, JobState.TRANSCRIBING, 40, "transcribing")
            if transcript is None and resume_checkpoint in {
                "transcript_ready",
                "chunks_ready",
                "summary_ready",
            }:
                saved_transcript = self._read_checkpoint(job, "transcript")
                if saved_transcript is not None:
                    transcript = transcript_from_dict(saved_transcript)
            if transcript is None:
                transcript = self._transcribe(job)
            self._assert_current_attempt(job)
            # 三条 ASR 路径（SenseVoice 切片、faster-whisper 单次、云端）都要记录
            # 「跑通了但没有文本」，否则 M0 只能落到通用空态，分不清是否无人声。
            # 字幕源空段落不算无语音，仍走通用空态。
            job.metadata["asr_no_speech"] = (
                transcript.source_kind == "asr" and not transcript.segments
            )
            self._write_checkpoint(job, "transcript", transcript_to_dict(transcript))
            job.update_progress(max(job.progress, 45), checkpoint="transcript_ready")
            self._assert_current_attempt(job)
            self.store.save_job(job)
            run = self.store.get_analysis_run(job.analysis_run_id)
            content = self.store.get_content(run.content_id)
            if content.kind is ContentKind.VIDEO:
                material_level = _validate_video_transcript(
                    transcript, content.duration_seconds
                )
            else:
                material_level = (
                    "M2" if transcript.segments and transcript.source_coverage_complete is True
                    else "M1" if transcript.segments else "M0"
                )
            summary_strength = SummaryStrength(
                run.settings_snapshot.get("strength", SummaryStrength.STANDARD.value)
            )
            job.metadata["material_level"] = material_level
            job.metadata["summary_strength"] = (
                None if material_level == "M0" else summary_strength.value
            )
            self.store.save_job(job)

            job = self._advance(job, JobState.CHUNKING, 55, "chunking")
            chunk_limit = int(run.settings_snapshot["max_chunk_tokens"])
            chunks = None
            if resume_checkpoint in {"chunks_ready", "summary_ready"}:
                saved_chunks = self._read_checkpoint(job, "chunks")
                if saved_chunks is not None:
                    chunks = self._chunks_from_dict(saved_chunks)
            if chunks is None:
                chunks = chunk_transcript(transcript, max_tokens=chunk_limit)
            self._assert_current_attempt(job)
            self._write_checkpoint(job, "chunks", self._chunks_to_dict(chunks))
            job.update_progress(max(job.progress, 60), checkpoint="chunks_ready")
            self._assert_current_attempt(job)
            self.store.save_job(job)

            job = self._advance(job, JobState.SUMMARIZING, 70, "summarizing")
            summary = None
            summary_started = monotonic()
            if resume_checkpoint == "summary_ready":
                saved_summary = self._read_checkpoint(job, "summary")
                if saved_summary is not None:
                    summary = self._summary_from_dict(saved_summary)
            if summary is None:
                if material_level == "M0":
                    empty_text = (
                        "未检测到可转写的语音内容。本文无相关字幕。"
                        "该视频可能是纯音乐、纯画面或无人声演示；"
                        "可改用带字幕的来源，或手动补充正文。"
                        if job.metadata.get("asr_no_speech")
                        else "尚未取得可用正文材料。"
                    )
                    summary = SummaryResult(
                        markdown=f"# 来源预览\n\n## 材料\n\n{empty_text}",
                        overview=empty_text,
                        key_points=(),
                    )
                    job.metadata["summary_kind"] = "source_preview"
                else:
                    try:
                        summary = self._summarize_with_ai(
                            content,
                            run,
                            chunks,
                            summary_strength,
                            material_level=material_level,
                        )
                    except SummaryGenerationError:
                        raise
                    except Exception as error:
                        raise SummaryGenerationError(f"总结生成失败：{error}") from error
            stats = _asr_stats(job)
            stats["phase_seconds"]["summary"] = max(0.0, monotonic() - summary_started)
            if not summary.markdown.strip():
                raise SummaryGenerationError("总结生成失败，未产生可用总结内容，请重试")
            self._assert_current_attempt(job)
            self._write_checkpoint(job, "summary", self._summary_to_dict(summary))
            job.update_progress(max(job.progress, 75), checkpoint="summary_ready")
            self._assert_current_attempt(job)
            self.store.save_job(job)

            summary_config = run.settings_snapshot.get("summary_config") or {}
            skill_snapshot = run.settings_snapshot.get("summary_skill") or {}
            if material_level != "M0" and not content.introduction and summary.markdown.strip():
                try:
                    self._assert_current_attempt(job)
                    introduction = self._generate_introduction_with_ai(
                        content,
                        run,
                        summary.markdown,
                    )
                    content = self.store.update_content(
                        content.id,
                        introduction=introduction,
                    )
                except Exception as error:
                    # A short recognition phrase is optional metadata. Keep the
                    # saved summary and archive successful when this second AI
                    # request is unavailable; the library backfill can retry it.
                    logger.warning("AI introduction generation failed for %s: %s", content.id, error)
            job = self._advance(job, JobState.ARCHIVING, 85, "archiving")
            record = build_record(
                content,
                tags=self.store.tag_names(content.id),
                model=str(run.settings_snapshot["model"]),
                prompt_version=run.prompt_version,
                transcript_source=transcript.source_kind,
                analyzed_at=datetime.now(UTC),
                asr_model=job.metadata.get("asr_model")
                or run.settings_snapshot.get("asr_engine"),
                analysis_mode="ai",
                summary_engine="openai-compatible",
                summary_provider=run.settings_snapshot.get("summary_provider"),
                summary_api_url=(
                    str(summary_config.get("api_url"))
                    if summary_config.get("api_url")
                    else None
                ),
                prompt_hash=run.settings_snapshot.get("summary_prompt_hash"),
                skill_path=skill_snapshot.get("path"),
                skill_hash=skill_snapshot.get("sha256"),
                confidence=None,
                summary_template=run.settings_snapshot.get("summary_template"),
                summary_style=run.settings_snapshot.get("summary_style"),
                summary_strength=(
                    None if material_level == "M0" else summary_strength.value
                ),
                material_level=material_level,
            )
            self._assert_current_attempt(job)
            paths = write_archive(
                self.archive_root,
                ArchiveBundle(
                    record=record,
                    summary_markdown=summary.markdown,
                    transcript=transcript_to_dict(transcript),
                ),
                batch_name=job.metadata.get("archive_batch_name"),
                item_number=job.metadata.get("archive_item_number"),
            )

            job.metadata["archive_path"] = str(paths.directory)
            job.metadata["summary_preview"] = summary.overview
            self._assert_current_attempt(job)
            self.store.upsert_summary(
                content.id,
                summary.markdown,
                transcript_text="\n".join(segment.text for segment in transcript.segments),
                source_note=job.metadata.get("source_note"),
                processing_model=str(run.settings_snapshot.get("model") or ""),
            )
            if material_level != "M0" and (
                (self.store.get_setting("ai_tag_recommendation_enabled") or "false").lower()
                == "true"
            ):
                try:
                    self._assert_current_attempt(job)
                    job.metadata["tag_suggestions"] = self._generate_tag_suggestions(content, summary)
                except Exception:
                    # Suggestions are optional metadata; archive success must
                    # not be turned into a failed task when the tag provider
                    # is unavailable.
                    logger.warning("AI tag suggestion failed for %s", content.id, exc_info=True)
                    job.metadata["tag_suggestions"] = []
            else:
                job.metadata["tag_suggestions"] = []
            if material_level != "M0" and not job.metadata.get("summary_version_id"):
                self._assert_current_attempt(job)
                processed_source_refs = [
                    f"transcript:segment:{ordinal}"
                    for ordinal, _segment in enumerate(transcript.segments, start=1)
                ]
                version = self.store.create_summary_version(
                    content.id,
                    summary.markdown,
                    template=str(
                        run.settings_snapshot.get("summary_template")
                        or DEFAULT_SUMMARY_TEMPLATE
                    ),
                    origin="original",
                    summary_strength=summary_strength.value,
                    summary_style=run.settings_snapshot.get("summary_style"),
                    material_level=material_level,
                    source_version=transcript.version,
                    source_scope={
                        "start_seconds": min(
                            (segment.start_seconds for segment in transcript.segments),
                            default=None,
                        ),
                        "end_seconds": max(
                            (segment.end_seconds for segment in transcript.segments),
                            default=None,
                        ),
                        "source_kind": transcript.source_kind,
                    },
                    processed_source_refs=processed_source_refs,
                    expected_source_refs=(
                        processed_source_refs if material_level == "M2" else None
                    ),
                    provider=str(run.settings_snapshot.get("summary_provider") or "unknown"),
                    model=str(run.settings_snapshot.get("model") or "unknown"),
                    prompt_version=run.prompt_version,
                )
                job.metadata["summary_version_id"] = version.id
            job = self._advance(job, JobState.INDEXING, 95, "indexing")
            self._assert_current_attempt(job)
            job.transition(JobState.COMPLETED)
            job.update_progress(100, checkpoint="indexed")
            self.store.save_job(job)
            stale_jobs = self.store.clear_stale_asr_checkpoints(
                content.id,
                keep_job_id=job.id,
            )
            for stale_job in stale_jobs:
                self.discard_checkpoints(stale_job)
                if stale_job.metadata.get("audio_is_temp"):
                    cleanup_temporary_audio(stale_job.metadata.get("audio_path"))
            self._set_run_status(job.analysis_run_id, "completed")
        except (WorkflowPaused, WorkflowCancelled):
            return
        except Exception as error:
            try:
                self._assert_current_attempt(job)
            except (WorkflowPaused, WorkflowCancelled):
                return
            self._mark_failed(job_id, error)
        finally:
            try:
                latest = self.store.get_job(job_id)
            except LookupError:
                latest = None
            resumable_checkpoints = {"transcript_ready", "chunks_ready", "summary_ready"}
            if latest and latest.state is JobState.CANCELLED:
                # Cancellation is terminal for this attempt.  Do not leave
                # pending/processing ASR rows that an application restart
                # could accidentally reclaim.
                self.store.clear_asr_checkpoints(job_id)
            # R8：失败产物保留供 24 小时内续跑。判据用元数据的稳定断点，
            # 而非失败瞬间的 summarizing；超期由 retry 侧判据触发清理。
            failed_stable = (
                latest.metadata.get("resume_checkpoint")
                if latest and latest.state is JobState.FAILED
                else None
            )
            failed_keep = failed_stable in resumable_checkpoints and self._checkpoint_files_exist(
                latest.metadata.get("checkpoint_dir"), failed_stable
            )
            if latest and (
                latest.state in {JobState.COMPLETED, JobState.CANCELLED}
                or (latest.state is JobState.FAILED and not failed_keep)
            ):
                self.discard_checkpoints(latest)
            if latest and latest.state in {
                JobState.COMPLETED,
                JobState.CANCELLED,
                JobState.FAILED,
            } and latest.metadata.get("audio_is_temp"):
                cleanup_temporary_audio(latest.metadata.get("audio_path"))
    def _assert_current_attempt(self, job):
        latest = self.store.get_job(job.id)
        if latest.state is JobState.CANCELLED:
            raise WorkflowCancelled("任务已取消")
        if latest.state is JobState.PAUSED:
            raise WorkflowPaused("任务已暂停")
        if latest.attempt != job.attempt or latest.worker_id != job.worker_id:
            raise WorkflowPaused("任务执行权已让出")
        return latest

    def _advance(self, job, state: JobState, progress: int, checkpoint: str):
        self._assert_current_attempt(job)
        job.transition(state)
        job.update_progress(max(job.progress, progress), checkpoint=checkpoint)
        self._assert_current_attempt(job)
        return self.store.save_job(job)

    def _generate_tag_suggestions(self, content: ContentItem, summary: SummaryResult) -> list[dict[str, object]]:
        """Return unconfirmed candidates from the user's existing tag vocabulary.

        The candidate list is deliberately kept in job metadata; only an
        explicit content update creates Content–Tag relations. A later model
        provider can replace this vocabulary matcher without changing that
        persistence boundary.
        """

        haystack = " ".join(
            [content.title, summary.overview, *getattr(summary, "key_points", ())]
        ).casefold()
        suggestions: list[dict[str, object]] = []
        for tag in self.store.list_tags():
            if tag.name.casefold() in haystack:
                suggestions.append({"name": tag.name, "confidence": 0.8})
        return suggestions

    def _mark_failed(self, job_id: str, error: Exception) -> None:
        job = self.store.get_job(job_id)
        if job.state in {JobState.CANCELLED, JobState.COMPLETED, JobState.FAILED, JobState.PAUSED}:
            return
        # TODO: provider-side HTTP errors need a documented, provider-neutral taxonomy.
        error_code = (
            error.code if isinstance(error, WorkflowAsrError)
            else JobErrorCode.SUMMARY_GENERATION_FAILED if isinstance(error, SummaryGenerationError)
            else JobErrorCode.TRANSCRIPT_INCOMPLETE if isinstance(error, TranscriptCoverageError)
            else JobErrorCode.UNKNOWN
        )
        stable_checkpoint = stable_checkpoint_for(job.checkpoint)
        if stable_checkpoint is None:
            stored_checkpoint = job.metadata.get("last_stable_checkpoint")
            stable_checkpoint = (
                stored_checkpoint if isinstance(stored_checkpoint, str) else None
            )
        job.metadata["last_stable_checkpoint"] = stable_checkpoint
        job.metadata["resume_checkpoint"] = stable_checkpoint
        job.fail(error_code, str(error))
        self.store.save_job(job)
        self._set_run_status(job.analysis_run_id, "failed", error_message=str(error))

    def _set_run_status(
        self,
        run_id: str,
        status: str,
        *,
        error_message: str | None = None,
    ) -> None:
        run = self.store.get_analysis_run(run_id)
        run.status = status
        run.updated_at = datetime.now(UTC)
        run.error_code = JobErrorCode.UNKNOWN.value if error_message else None
        run.error_message = error_message
        self.store.save_analysis_run(run)


class WorkflowPaused(RuntimeError):
    """Raised when a worker notices that the user paused the job."""


class WorkflowCancelled(RuntimeError):
    """Raised when a worker notices that the user cancelled the job."""


class WorkflowAsrError(RuntimeError):
    def __init__(self, code: JobErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


def cleanup_temporary_audio(audio_path: str | None) -> None:
    """Remove only audio the current import marked as a temporary download."""

    if not audio_path:
        return
    try:
        path = Path(audio_path)
        parent = path.parent
        if parent.is_dir() and parent.name.startswith("knowledge-asr-"):
            shutil.rmtree(parent, ignore_errors=True)
        elif path.is_file():
            path.unlink()
    except OSError:
        pass
