"""Local ASR catalog, model lifecycle helpers and faster-whisper adapter."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
from queue import Empty, Queue
import re
import shutil
import subprocess
import sys
import ctypes
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic
from uuid import uuid4

from app.domain.models import Transcript, TranscriptSegment

_MODEL_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,80}")
_MANIFEST_NAME = "model.manifest.json"
_REQUIRED_FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")


@dataclass(frozen=True, slots=True)
class LocalAsrModelDefinition:
    id: str
    label: str
    repo_id: str
    size: str
    languages: str
    description: str
    estimated_size_bytes: int = 0
    memory_required_mb: int = 0
    speed: str = "未测量"
    quality: str = "未标定"
    device_requirements: str = "CPU 可运行"
    expected_files: tuple[str, ...] = _REQUIRED_FILES
    revision: str | None = None
    license: str | None = None


LOCAL_ASR_MODELS: tuple[LocalAsrModelDefinition, ...] = (
    LocalAsrModelDefinition(
        id="sensevoice-small",
        label="SenseVoiceSmall",
        repo_id="iic/SenseVoiceSmall",
        size="940,019,376 bytes（ModelScope 元数据）",
        languages="中文、英文及中英混合（另含粤语、日语、韩语）",
        description="默认快速本地模型；产品层切片后逐片转写并保存进度。",
        estimated_size_bytes=940_019_376,
        memory_required_mb=2200,
        speed="快速（待本机基准）",
        quality="待固定样本验收",
        device_requirements="CPU 可运行；建议 4 GB 可用内存",
        expected_files=(
            "model.pt",
            "config.yaml",
            "configuration.json",
            "chn_jpn_yue_eng_ko_spectok.bpe.model",
        ),
        revision="master",
        license="Apache License 2.0",
    ),
    LocalAsrModelDefinition(
        id="small",
        label="Whisper Small",
        repo_id="Systran/faster-whisper-small",
        size="约 486 MB",
        languages="99 种语言",
        description="适合普通电脑先试用，中文和多语言可用。",
        estimated_size_bytes=486 * 1024**2,
        memory_required_mb=1200,
        speed="较快",
        quality="中等",
        device_requirements="CPU 可运行；建议 4 GB 可用内存",
    ),
    LocalAsrModelDefinition(
        id="base",
        label="Whisper Base",
        repo_id="Systran/faster-whisper-base",
        size="约 145 MB",
        languages="99 种语言",
        description="资源占用较低，适合已有缓存和普通电脑快速试用。",
        estimated_size_bytes=145 * 1024**2,
        memory_required_mb=800,
        speed="快",
        quality="基础",
        device_requirements="CPU 可运行；建议 4 GB 可用内存",
    ),
    LocalAsrModelDefinition(
        id="medium",
        label="Whisper Medium",
        repo_id="Systran/faster-whisper-medium",
        size="约 1.53 GB",
        languages="99 种语言",
        description="准确率和资源占用的平衡选项。",
        estimated_size_bytes=1530 * 1024**2,
        memory_required_mb=2600,
        speed="中等",
        quality="较高",
        device_requirements="CPU 可运行；建议 8 GB 可用内存",
    ),
    LocalAsrModelDefinition(
        id="large-v3-turbo",
        label="Whisper Large-v3 Turbo",
        repo_id="mobiuslabsgmbh/faster-whisper-large-v3-turbo",
        size="约 1.62 GB",
        languages="99 种语言",
        description="多语言高质量与较快速度，优先推荐有较大内存的电脑。",
        estimated_size_bytes=1620 * 1024**2,
        memory_required_mb=3200,
        speed="较快",
        quality="高",
        device_requirements="建议 8 GB 可用内存；GPU 可加速",
    ),
    LocalAsrModelDefinition(
        id="large-v3",
        label="Whisper Large-v3",
        repo_id="Systran/faster-whisper-large-v3",
        size="约 3.09 GB",
        languages="100 种语言",
        description="质量优先的多语言模型，CPU 运行较慢且占用内存较高。",
        estimated_size_bytes=3090 * 1024**2,
        memory_required_mb=5200,
        speed="较慢",
        quality="最高",
        device_requirements="建议 16 GB 可用内存；GPU 更合适",
    ),
)


@dataclass(frozen=True, slots=True)
class LocalAsrValidation:
    status: str
    ready: bool
    message: str
    path: Path
    size_bytes: int = 0
    sha256: str | None = None
    manifest_present: bool = False
    missing_files: tuple[str, ...] = ()
    invalid_files: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LocalAsrModelInfo:
    id: str
    label: str
    repo_id: str
    size: str
    languages: str
    description: str
    estimated_size_bytes: int
    memory_required_mb: int
    speed: str
    quality: str
    device_requirements: str


@dataclass(frozen=True, slots=True)
class LocalAsrModelCandidate:
    id: str
    path: Path
    validation: LocalAsrValidation


class LocalAsrError(RuntimeError):
    """Raised when the local ASR runtime or model is unavailable."""


@dataclass(frozen=True, slots=True)
class AsrBatchBenchmark:
    """Measured result for one fixed-sample ASR batch size.

    Batch selection is deliberately data-driven.  A missing measurement or an
    incomplete/incorrectly ordered output is not treated as evidence that a
    larger batch is safe; callers therefore fall back to batch 1.
    """

    batch_size: int
    total_seconds: float
    peak_memory_mb: float | None = None
    missing_segments: int = 0
    duplicate_segments: int = 0
    out_of_order_segments: int = 0
    status: str = "ok"


def select_safe_asr_batch(
    benchmarks: tuple[AsrBatchBenchmark, ...] | list[AsrBatchBenchmark],
    *,
    min_improvement: float = 0.10,
    memory_limit_mb: float = 4096.0,
) -> int:
    """Choose a measured batch size or keep the safe default of one.

    The comparison is against the same-sample batch-1 result.  A candidate
    must be successful, complete, ordered, within the memory limit, and at
    least ten percent faster.  This helper never guesses from CPU count or
    model metadata, so an unbenchmarked installation remains batch 1.
    """

    def healthy(item: AsrBatchBenchmark) -> bool:
        return (
            item.batch_size >= 1
            and item.total_seconds > 0.0
            and item.status.casefold() in {"ok", "passed", "success"}
            and item.missing_segments == 0
            and item.duplicate_segments == 0
            and item.out_of_order_segments == 0
        )

    baseline = next(
        (item for item in benchmarks if item.batch_size == 1 and healthy(item)),
        None,
    )
    if baseline is None:
        return 1
    threshold = baseline.total_seconds * max(0.0, 1.0 - float(min_improvement))
    safe = [
        item
        for item in benchmarks
        if item.batch_size > 1
        and healthy(item)
        and item.peak_memory_mb is not None
        and 0.0 < float(item.peak_memory_mb) <= float(memory_limit_mb)
        and item.total_seconds <= threshold
    ]
    if not safe:
        return 1
    selected = min(safe, key=lambda item: (item.total_seconds, -item.batch_size))
    return int(selected.batch_size)


def get_local_model_definition(model_id: str) -> LocalAsrModelDefinition | None:
    return next((item for item in LOCAL_ASR_MODELS if item.id == model_id), None)


def _require_model_id(model_id: str) -> str:
    if not isinstance(model_id, str) or not _MODEL_ID_PATTERN.fullmatch(model_id):
        raise LocalAsrError("本地 ASR 模型标识无效")
    return model_id


def local_model_path(model_root: Path, model_id: str) -> Path:
    _require_model_id(model_id)
    return model_root / model_id


def _format_bytes(value: int) -> str:
    if value >= 1024**3:
        return f"{value / 1024**3:.2f} GB"
    if value >= 1024**2:
        return f"{value / 1024**2:.0f} MB"
    if value >= 1024:
        return f"{value / 1024:.0f} KB"
    return f"{value} B"


def _has_required_model_files(
    model_path: Path,
    expected_files: tuple[str, ...] = _REQUIRED_FILES,
) -> bool:
    return model_path.is_dir() and all(
        (model_path / name).is_file() for name in expected_files
    )


def _model_files(model_path: Path) -> list[Path]:
    if not model_path.is_dir():
        return []
    return sorted(
        item
        for item in model_path.rglob("*")
        if item.is_file() and item.name != _MANIFEST_NAME
    )


def _directory_size(model_path: Path) -> int:
    return sum(item.stat().st_size for item in _model_files(model_path))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_path(model_path: Path) -> Path:
    return model_path / _MANIFEST_NAME


def model_manifest_path(model_path: Path) -> Path:
    return _manifest_path(model_path)


def _read_manifest(model_path: Path) -> dict[str, object] | None:
    path = _manifest_path(model_path)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise LocalAsrError("本地 ASR 模型清单损坏") from error
    if not isinstance(value, dict) or not isinstance(value.get("files"), dict):
        raise LocalAsrError("本地 ASR 模型清单格式无效")
    return value


def _validation_for_path(model_path: Path, model_id: str) -> LocalAsrValidation:
    definition = get_local_model_definition(model_id)
    required_files = definition.expected_files if definition else _REQUIRED_FILES
    if not model_path.is_dir():
        return LocalAsrValidation(
            status="not_found",
            ready=False,
            message="模型目录不存在",
            path=model_path,
            missing_files=required_files,
        )

    missing = tuple(name for name in required_files if not (model_path / name).is_file())
    if missing:
        return LocalAsrValidation(
            status="incomplete",
            ready=False,
            message=f"缺少模型文件：{', '.join(missing)}",
            path=model_path,
            size_bytes=_directory_size(model_path),
            missing_files=missing,
        )

    invalid: list[str] = []
    config_name = "configuration.json" if model_id == "sensevoice-small" else "config.json"
    try:
        config = json.loads((model_path / config_name).read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            invalid.append(config_name)
    except (OSError, UnicodeDecodeError, ValueError):
        invalid.append(config_name)
    for name in required_files:
        try:
            if (model_path / name).stat().st_size <= 0:
                invalid.append(name)
        except OSError:
            invalid.append(name)

    manifest_present = _manifest_path(model_path).is_file()
    manifest: dict[str, object] | None = None
    if manifest_present:
        try:
            manifest = _read_manifest(model_path)
        except LocalAsrError:
            invalid.append(_MANIFEST_NAME)
        if manifest is not None:
            records = manifest.get("files")
            if not isinstance(records, dict):
                invalid.append(_MANIFEST_NAME)
            else:
                for relative, record in records.items():
                    file_path = model_path / str(relative)
                    if not file_path.is_file() or not isinstance(record, dict):
                        invalid.append(str(relative))
                        continue
                    try:
                        stat = file_path.stat()
                        if int(record.get("size", -1)) != stat.st_size:
                            invalid.append(str(relative))
                            continue
                        recorded_mtime = record.get("mtime_ns")
                        if recorded_mtime is not None and int(recorded_mtime) == stat.st_mtime_ns:
                            continue
                        if str(record.get("sha256")) != _sha256(file_path):
                            invalid.append(str(relative))
                    except (OSError, TypeError, ValueError):
                        invalid.append(str(relative))

    size_bytes = _directory_size(model_path)
    if invalid:
        return LocalAsrValidation(
            status="corrupt",
            ready=False,
            message=f"模型校验失败：{', '.join(sorted(set(invalid)))}",
            path=model_path,
            size_bytes=size_bytes,
            manifest_present=manifest_present,
            invalid_files=tuple(sorted(set(invalid))),
        )

    digest = None
    if manifest:
        digest_value = manifest.get("model_sha256")
        digest = str(digest_value) if digest_value else None
    return LocalAsrValidation(
        status="ready",
        ready=True,
        message=(
            "模型文件和清单校验通过"
            if manifest_present
            else "模型基础文件校验通过，尚未生成清单"
        ),
        path=model_path,
        size_bytes=size_bytes,
        sha256=digest,
        manifest_present=manifest_present,
    )


def validate_local_model(model_root: Path, model_id: str) -> LocalAsrValidation:
    _require_model_id(model_id)
    return _validation_for_path(local_model_path(model_root, model_id), model_id)


def resolved_local_model_identity(model_path: Path, model_id: str) -> str:
    """Return the immutable manifest identity used by product ASR runs."""

    validation = _validation_for_path(model_path, model_id)
    if not validation.ready:
        raise LocalAsrError(f"本地 ASR 模型尚未通过校验：{validation.message}")
    identity = str(validation.sha256 or "").strip()
    if model_id == "sensevoice-small" and (
        not validation.manifest_present or not identity
    ):
        raise LocalAsrError("SenseVoiceSmall 模型清单缺少 model_sha256")
    return identity or f"path:{model_id}"


def is_local_model_ready(model_root: Path, model_id: str) -> bool:
    try:
        return validate_local_model(model_root, model_id).ready
    except LocalAsrError:
        return False


def local_asr_model_info(
    model_root: Path,
    model_id: str,
    *,
    model_path: Path | None = None,
) -> LocalAsrModelInfo:
    definition = get_local_model_definition(model_id)
    if definition is not None:
        return LocalAsrModelInfo(
            id=definition.id,
            label=definition.label,
            repo_id=definition.repo_id,
            size=definition.size,
            languages=definition.languages,
            description=definition.description,
            estimated_size_bytes=definition.estimated_size_bytes,
            memory_required_mb=definition.memory_required_mb,
            speed=definition.speed,
            quality=definition.quality,
            device_requirements=definition.device_requirements,
        )
    path = model_path or local_model_path(model_root, model_id)
    validation = _validation_for_path(path, model_id)
    return LocalAsrModelInfo(
        id=model_id,
        label=path.name,
        repo_id="",
        size=_format_bytes(validation.size_bytes),
        languages="需从模型配置确认",
        description="用户导入的 faster-whisper 模型",
        estimated_size_bytes=validation.size_bytes,
        memory_required_mb=max(0, int(validation.size_bytes / 1024**2 * 1.5)),
        speed="需实测",
        quality="需实测",
        device_requirements="需要 faster-whisper 和可用内存",
    )


def list_local_asr_model_ids(model_root: Path) -> tuple[str, ...]:
    ids = [definition.id for definition in LOCAL_ASR_MODELS]
    if model_root.is_dir():
        for path in sorted(model_root.iterdir()):
            if not path.is_dir() or path.name.startswith("."):
                continue
            if not _MODEL_ID_PATTERN.fullmatch(path.name):
                continue
            if path.name not in ids and (
                _manifest_path(path).is_file() or _has_required_model_files(path)
            ):
                ids.append(path.name)
    return tuple(ids)


def write_model_manifest(
    model_path: Path,
    model_id: str,
    *,
    source_revision: str | None = None,
) -> Path:
    _require_model_id(model_id)
    validation = _validation_for_path(model_path, model_id)
    if not validation.ready:
        raise LocalAsrError(f"模型无法生成清单：{validation.message}")
    records: dict[str, dict[str, int | str]] = {}
    hashes: list[str] = []
    for file_path in _model_files(model_path):
        relative = file_path.relative_to(model_path).as_posix()
        stat = file_path.stat()
        digest = _sha256(file_path)
        records[relative] = {
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "sha256": digest,
        }
        hashes.append(f"{relative}:{digest}")
    manifest = {
        "schema_version": 1,
        "model_id": model_id,
        "created_at": datetime.now(UTC).isoformat(),
        "source_revision": source_revision,
        "model_sha256": hashlib.sha256("\n".join(sorted(hashes)).encode()).hexdigest(),
        "files": records,
    }
    path = _manifest_path(model_path)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _model_id_for_repo_id(repo_id: str) -> str | None:
    definition = next((item for item in LOCAL_ASR_MODELS if item.repo_id == repo_id), None)
    return definition.id if definition else None


def _repo_id_from_cache_path(path: Path) -> str | None:
    if not path.name.startswith("models--"):
        return None
    encoded = path.name.removeprefix("models--")
    if "--" not in encoded:
        return None
    owner, name = encoded.split("--", 1)
    return f"{owner}/{name}"


def _huggingface_cache_roots(source: Path) -> tuple[Path, ...]:
    if source.name == "hub" and source.is_dir():
        return (source,)
    hub = source / "hub"
    if hub.is_dir():
        return (hub,)
    if source.name.startswith("models--") and source.is_dir():
        return (source.parent,)
    return ()


def _snapshot_candidates(repo_cache: Path) -> tuple[Path, ...]:
    snapshots = repo_cache / "snapshots"
    if not snapshots.is_dir():
        return ()
    ordered: list[Path] = []
    refs_main = repo_cache / "refs" / "main"
    if refs_main.is_file():
        revision = refs_main.read_text(encoding="utf-8").strip()
        preferred = snapshots / revision
        if preferred.is_dir():
            ordered.append(preferred)
    ordered.extend(
        sorted(
            (item for item in snapshots.iterdir() if item.is_dir() and item not in ordered),
            key=lambda item: item.stat().st_mtime_ns,
            reverse=True,
        )
    )
    return tuple(ordered)


def _huggingface_snapshot_candidates(
    source: Path,
    *,
    model_id: str | None = None,
) -> tuple[Path, ...]:
    roots = _huggingface_cache_roots(source)
    if not roots:
        return ()
    definition = get_local_model_definition(model_id) if model_id else None
    expected_repo = definition.repo_id if definition else None
    candidates: list[Path] = []
    for root in roots:
        repo_caches = (
            (source,)
            if source.name.startswith("models--")
            else tuple(sorted(root.glob("models--*")))
        )
        for repo_cache in repo_caches:
            repo_id = _repo_id_from_cache_path(repo_cache)
            if expected_repo and repo_id != expected_repo:
                continue
            expected_files = definition.expected_files if definition else _REQUIRED_FILES
            for snapshot in _snapshot_candidates(repo_cache):
                if _has_required_model_files(snapshot, expected_files):
                    candidates.append(snapshot)
                    break
    return tuple(candidates)


def _source_model_path(source_path: Path, *, model_id: str | None = None) -> Path:
    source = source_path.expanduser().resolve()
    definition = get_local_model_definition(model_id) if model_id else None
    expected_files = definition.expected_files if definition else _REQUIRED_FILES
    if source.is_file():
        if source.name not in set(expected_files):
            raise LocalAsrError("请选择包含完整模型文件的目录，或选择 model.bin、config.json、tokenizer.json、vocabulary.txt")
        source = source.parent
    if not source.is_dir():
        raise LocalAsrError("模型文件或目录不存在")
    if _has_required_model_files(source, expected_files):
        return source
    candidates = _huggingface_snapshot_candidates(source, model_id=model_id)
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise LocalAsrError(
            "检测到多个 Hugging Face 本地模型，请在导入名称中填写 small、base、medium 等公开模型 ID，"
            "或直接选择 hub\\models--...\\snapshots\\<版本> 目录"
        )
    required = "、".join(_REQUIRED_FILES)
    raise LocalAsrError(
        "目录中未找到完整模型；需要同时包含 "
        f"{required}。已限定检查当前目录、一级子目录以及 Hugging Face "
        "hub\\models--*\\snapshots\\*，不会扫描整块磁盘。"
    )


def _source_model_id(source_path: Path, requested: str | None) -> str:
    if requested:
        return _require_model_id(requested)
    for part in (source_path, *source_path.parents):
        repo_id = _repo_id_from_cache_path(part)
        if repo_id:
            mapped = _model_id_for_repo_id(repo_id)
            if mapped:
                return mapped
    slug = re.sub(r"[^a-z0-9._-]+", "-", source_path.name.lower()).strip("-._")
    if not slug:
        slug = f"imported-{hashlib.sha256(str(source_path).encode()).hexdigest()[:12]}"
    if not _MODEL_ID_PATTERN.fullmatch(slug):
        slug = f"imported-{hashlib.sha256(str(source_path).encode()).hexdigest()[:12]}"
    return slug[:81]


def _model_scan_paths(source: Path) -> tuple[Path, ...]:
    paths: list[Path] = []
    if _has_required_model_files(source):
        paths.append(source)
    paths.extend(_huggingface_snapshot_candidates(source))
    for child in sorted(source.iterdir()):
        if not child.is_dir() or (child.name.startswith(".") and child.name != ".hf"):
            continue
        if _has_required_model_files(child):
            paths.append(child)
        paths.extend(_huggingface_snapshot_candidates(child))
    unique: list[Path] = []
    for path in paths:
        if path not in unique:
            unique.append(path)
    return tuple(unique)


def discover_local_asr_models(
    source_path: Path,
    *,
    model_id: str | None = None,
) -> tuple[LocalAsrModelCandidate, ...]:
    source = source_path.expanduser().resolve()
    if source.is_file():
        if source.name not in {"model.bin", "config.json", "tokenizer.json", "vocabulary.txt"}:
            raise LocalAsrError(
                "请选择完整模型目录，或选择 model.bin、config.json、tokenizer.json、"
                "vocabulary.txt 文件"
            )
        source = source.parent
    if not source.is_dir():
        raise LocalAsrError("模型扫描目录不存在")
    paths = _model_scan_paths(source)
    candidates: list[LocalAsrModelCandidate] = []
    for path in paths:
        resolved_id = model_id if model_id and len(paths) == 1 else _source_model_id(path, None)
        validation = _validation_for_path(path, resolved_id)
        if validation.ready:
            candidates.append(LocalAsrModelCandidate(resolved_id, path, validation))
    return tuple(candidates)


def inspect_local_asr_model(
    source_path: Path,
    *,
    model_id: str | None = None,
) -> tuple[Path, str, LocalAsrValidation]:
    source = _source_model_path(source_path, model_id=model_id)
    resolved_id = _source_model_id(source, model_id)
    return source, resolved_id, _validation_for_path(source, resolved_id)


def _trash_model(model_root: Path, model_path: Path, model_id: str) -> Path:
    trash_root = model_root / ".trash"
    trash_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    destination = trash_root / f"{model_id}-{timestamp}-{uuid4().hex[:8]}"
    shutil.move(str(model_path), str(destination))
    return destination


def import_local_asr_model(
    model_root: Path,
    source_path: Path,
    *,
    model_id: str | None = None,
    overwrite: bool = False,
    move_source: bool = False,
) -> Path:
    source, resolved_id, validation = inspect_local_asr_model(source_path, model_id=model_id)
    if not validation.ready:
        raise LocalAsrError(f"模型导入前校验失败：{validation.message}")
    model_root.mkdir(parents=True, exist_ok=True)
    target = local_model_path(model_root, resolved_id)
    if target.exists() and not overwrite:
        existing_validation = _validation_for_path(target, resolved_id)
        if existing_validation.ready:
            return target
        raise LocalAsrError("目标模型已存在但未通过校验；如需替换请明确开启覆盖")
    staging = model_root / f".{resolved_id}.importing-{uuid4().hex[:8]}"
    shutil.copytree(source, staging)
    write_model_manifest(staging, resolved_id, source_revision="imported")
    copied_validation = _validation_for_path(staging, resolved_id)
    if not copied_validation.ready:
        raise LocalAsrError(f"导入副本校验失败：{copied_validation.message}")
    if target.exists():
        _trash_model(model_root, target, resolved_id)
    staging.rename(target)
    if move_source and source != target:
        source_trash = model_root / ".trash" / f"source-{uuid4().hex[:8]}"
        source_trash.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(source_trash))
    return target


def remove_local_asr_model(model_root: Path, model_id: str) -> Path:
    target = local_model_path(model_root, model_id)
    if not target.is_dir():
        raise LocalAsrError("本地 ASR 模型不存在")
    return _trash_model(model_root, target, model_id)


def local_asr_runtime_available() -> bool:
    return (
        importlib.util.find_spec("faster_whisper") is not None
        or importlib.util.find_spec("funasr") is not None
        or _external_sensevoice_python() is not None
    )


def _external_sensevoice_python() -> Path | None:
    """Return the isolated FunASR interpreter when the desktop env is separate."""

    project_root = Path(__file__).resolve().parents[6]
    candidate = project_root / "local" / "asr-runtime" / "Scripts" / "python.exe"
    return candidate if candidate.is_file() else None


def _runtime_environment() -> dict[str, str]:
    """Build an isolated-runtime environment without unusable Windows PATH entries."""

    environment = {
        **os.environ,
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    if os.name != "nt":
        return environment
    path = environment.get("PATH")
    if not path:
        return environment
    usable: list[str] = []
    for entry in path.split(os.pathsep):
        if not entry:
            usable.append(entry)
            continue
        try:
            if Path(entry).is_dir():
                usable.append(entry)
        except OSError:
            # A stale or inaccessible PATH entry can make Windows resolve a
            # missing executable as WinError 5 instead of FileNotFoundError.
            continue
    environment["PATH"] = os.pathsep.join(usable)
    return environment


def sensevoice_runtime_available() -> bool:
    # SenseVoice is never allowed to fall back to the desktop interpreter;
    # the model and FunASR dependencies live in this product-local runtime.
    return _external_sensevoice_python() is not None


def _windows_compatible_path(path: Path) -> Path:
    """Return an existing Windows 8.3 path when Unicode paths break a runtime.

    SenseVoice's SentencePiece loader is an external-process dependency.  On
    this Windows installation it can open the same model through the short
    path, but reports ``NOT_FOUND`` for the full Chinese workspace path.  Keep
    the workaround at the process boundary and leave product metadata on the
    original user-visible path.
    """

    resolved = path.expanduser().resolve()
    if os.name != "nt" or not resolved.exists():
        return resolved
    try:
        get_short_path_name = ctypes.windll.kernel32.GetShortPathNameW
    except (AttributeError, OSError):
        return resolved
    try:
        required = int(get_short_path_name(str(resolved), None, 0))
        if required <= 0:
            return resolved
        # The first call returns the required buffer length excluding the
        # terminating NUL.  A second call is still allowed to report the
        # required size if the filesystem path changes between calls.
        while required > 0:
            buffer = ctypes.create_unicode_buffer(required + 1)
            written = int(
                get_short_path_name(str(resolved), buffer, ctypes.c_uint32(len(buffer)).value)
            )
            if written <= 0:
                return resolved
            if written < len(buffer):
                return Path(buffer.value)
            required = written
    except (OSError, TypeError, ValueError):
        return resolved
    return resolved


def local_asr_download_available() -> bool:
    return (
        local_asr_runtime_available()
        and (
            importlib.util.find_spec("huggingface_hub") is not None
            or importlib.util.find_spec("modelscope") is not None
        )
    )


def local_asr_install_hint() -> str:
    return (
        "本地 ASR 组件尚未安装，请在 product 目录执行 "
        "python -m pip install -e .[local-asr] 后重试"
    )


def download_local_asr_model(
    model_root: Path,
    model_id: str,
    *,
    progress: Callable[[dict[str, object]], None] | None = None,
    timeout_seconds: float = 1800.0,
) -> Path:
    definition = get_local_model_definition(model_id)
    if definition is None:
        raise LocalAsrError("不支持的本地 ASR 模型")
    if not local_asr_download_available():
        raise LocalAsrError(local_asr_install_hint())

    model_root.mkdir(parents=True, exist_ok=True)
    target = local_model_path(model_root, definition.id)
    partial = model_root / f".{definition.id}.partial-{uuid4().hex[:8]}"
    partial.mkdir(parents=True, exist_ok=False)
    stop_monitor = Event()

    def emit(update: dict[str, object]) -> None:
        if progress:
            progress(update)

    def monitor() -> None:
        while not stop_monitor.is_set():
            downloaded = _directory_size(partial)
            ratio = (
                downloaded / definition.estimated_size_bytes
                if definition.estimated_size_bytes
                else 0
            )
            emit(
                {
                    "status": "downloading",
                    "progress": min(89, max(10, 10 + int(ratio * 80))),
                    "downloaded_bytes": downloaded,
                    "total_bytes": definition.estimated_size_bytes,
                    "message": "正在下载模型文件",
                }
            )
            stop_monitor.wait(0.25)

    emit(
        {
            "status": "downloading",
            "progress": 5,
            "downloaded_bytes": 0,
            "total_bytes": definition.estimated_size_bytes,
            "message": "准备下载模型文件",
        }
    )
    monitor_thread = Thread(target=monitor, name=f"asr-progress-{model_id}", daemon=True)
    monitor_thread.start()
    try:
        if definition.id == "sensevoice-small":
            emit(
                {
                    "status": "downloading",
                    "progress": 10,
                    "message": "正在从 ModelScope 下载 SenseVoiceSmall 固定版本",
                }
            )
            runtime_python = _external_sensevoice_python()
            if runtime_python is None:
                raise LocalAsrError("SenseVoiceSmall 独立运行时尚未安装")
            cache_root = model_root.parent / "modelscope-cache"
            helper = (
                "from modelscope.hub.snapshot_download import snapshot_download;"
                "import sys;"
                "print(snapshot_download(model_id=sys.argv[1], revision=sys.argv[2], "
                "cache_dir=sys.argv[3]), flush=True)"
            )
            try:
                completed = subprocess.run(
                    [
                        str(runtime_python),
                        "-c",
                        helper,
                        definition.repo_id,
                        definition.revision or "master",
                        str(cache_root),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=_runtime_environment(),
                    timeout=max(1.0, float(timeout_seconds)),
                )
            except subprocess.TimeoutExpired as error:
                raise LocalAsrError(
                    f"模型下载超过 {max(1, int(timeout_seconds))} 秒，已终止下载进程，稍后可重试"
                ) from error
            except subprocess.CalledProcessError as error:
                detail = (error.stderr or error.stdout or str(error)).strip()
                raise LocalAsrError(f"模型下载失败：{detail}") from error
            source = (
                cache_root
                / "models"
                / definition.repo_id.replace("/", "--")
                / "snapshots"
                / (definition.revision or "master")
            )
            if not source.is_dir():
                raise LocalAsrError("ModelScope 未返回有效模型目录")
            shutil.copytree(source, partial, dirs_exist_ok=True)
        else:
            from huggingface_hub import snapshot_download

            emit(
                {
                    "status": "downloading",
                    "progress": 10,
                    "message": "正在从 Hugging Face 下载模型文件",
                }
            )
            try:
                snapshot_download(
                    repo_id=definition.repo_id,
                    local_dir=str(partial),
                    local_dir_use_symlinks=False,
                    revision=definition.revision,
                )
            except TypeError:
                snapshot_download(repo_id=definition.repo_id, local_dir=str(partial))
    except LocalAsrError:
        raise
    except Exception as error:
        raise LocalAsrError(f"模型下载失败：{error}") from error
    finally:
        stop_monitor.set()
        monitor_thread.join(timeout=2)

    emit({"status": "validating", "progress": 90, "message": "正在校验模型文件"})
    try:
        write_model_manifest(partial, definition.id, source_revision=definition.revision)
        validation = _validation_for_path(partial, definition.id)
        if not validation.ready:
            raise LocalAsrError(f"模型下载未完成：{validation.message}")
        if target.exists():
            _trash_model(model_root, target, definition.id)
        partial.rename(target)
    except LocalAsrError:
        raise
    except Exception as error:
        raise LocalAsrError(f"模型安装失败：{error}") from error
    emit(
        {
            "status": "downloaded",
            "progress": 100,
            "downloaded_bytes": validation.size_bytes,
            "total_bytes": definition.estimated_size_bytes,
            "message": "模型下载并校验完成",
        }
    )
    return target


def check_local_model_update(model_root: Path, model_id: str) -> dict[str, object]:
    definition = get_local_model_definition(model_id)
    if definition is None or not definition.repo_id:
        return {"update_status": "not_supported", "update_available": False}
    manifest = _read_manifest(local_model_path(model_root, model_id))
    if importlib.util.find_spec("huggingface_hub") is None:
        return {
            "update_status": "unavailable",
            "update_available": False,
            "update_error": "未安装 huggingface_hub，无法检查公开模型更新",
        }
    try:
        from huggingface_hub import HfApi

        remote = HfApi().model_info(definition.repo_id)
        remote_revision = str(getattr(remote, "sha", "") or "")
        local_revision = str((manifest or {}).get("source_revision") or "")
        available = bool(remote_revision and local_revision and remote_revision != local_revision)
        return {
            "update_status": "checked",
            "update_available": available,
            "remote_revision": remote_revision or None,
            "local_revision": local_revision or None,
        }
    except Exception as error:
        return {"update_status": "error", "update_available": False, "update_error": str(error)}


_MODEL_CACHE: dict[str, object] = {}
_MODEL_CACHE_LOCK = Lock()


class FasterWhisperTranscriber:
    """Run a downloaded CTranslate2 Whisper model without network access."""

    name = "faster-whisper"

    def __init__(
        self,
        model_path: Path,
        *,
        model_id: str,
        device: str = "cpu",
        compute_type: str = "int8",
    ) -> None:
        self.model_path = model_path
        self.model_id = model_id
        self.device = device
        self.compute_type = compute_type

    def _model(self):
        cache_key = f"{self.model_path}|{self.device}|{self.compute_type}"
        with _MODEL_CACHE_LOCK:
            cached = _MODEL_CACHE.get(cache_key)
            if cached is not None:
                return cached
            if not local_asr_runtime_available():
                raise LocalAsrError(local_asr_install_hint())
            from faster_whisper import WhisperModel

            model = WhisperModel(
                str(self.model_path),
                device=self.device,
                compute_type=self.compute_type,
            )
            _MODEL_CACHE[cache_key] = model
            return model

    def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None = None,
    ) -> Transcript:
        if not is_local_model_ready(self.model_path.parent, self.model_id):
            raise LocalAsrError("本地 ASR 模型尚未下载完成")
        if not audio_path.is_file():
            raise LocalAsrError("缺少可转写的音频文件")
        model = self._model()
        segments, info = model.transcribe(
            str(audio_path),
            language=language,
            beam_size=5,
            vad_filter=True,
        )
        cues: list[TranscriptSegment] = []
        for segment in segments:
            text = str(getattr(segment, "text", "") or "").strip()
            if text:
                cues.append(
                    TranscriptSegment(
                        float(getattr(segment, "start", 0.0)),
                        float(getattr(segment, "end", 0.0)),
                        text,
                    )
                )
        detected_language = language or getattr(info, "language", None)
        return Transcript(
            detected_language,
            "asr",
            f"faster-whisper:{self.model_id}",
            tuple(cues),
        )


_SENSEVOICE_TAG = re.compile(r"<\|[^|>]+\|>")


def _sensevoice_text(value: object) -> str:
    return " ".join(_SENSEVOICE_TAG.sub(" ", str(value or "")).split())


def asr_text_quality(label: str, text: str) -> bool:
    """Apply a lightweight language gate when no human reference is bundled."""

    normalized = _sensevoice_text(text)
    if not normalized:
        return False
    lowered = str(label or "").casefold()
    has_cjk = any("\u4e00" <= char <= "\u9fff" for char in normalized)
    has_latin = any(char.isascii() and char.isalpha() for char in normalized)
    if lowered in {"zh", "chinese"}:
        return has_cjk
    if lowered in {"en", "english"}:
        return has_latin
    if lowered in {"mixed", "zh-en", "en-zh"}:
        return has_cjk and has_latin
    return True


class _ProcessEntry32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("cntUsage", ctypes.c_uint32),
        ("th32ProcessID", ctypes.c_uint32),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", ctypes.c_uint32),
        ("cntThreads", ctypes.c_uint32),
        ("th32ParentProcessID", ctypes.c_uint32),
        ("pcPriClassBase", ctypes.c_int32),
        ("dwFlags", ctypes.c_uint32),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("page_fault_count", ctypes.c_ulong),
        ("peak_working_set_size", ctypes.c_size_t),
        ("working_set_size", ctypes.c_size_t),
        ("quota_peak_paged_pool_usage", ctypes.c_size_t),
        ("quota_paged_pool_usage", ctypes.c_size_t),
        ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
        ("quota_non_paged_pool_usage", ctypes.c_size_t),
        ("pagefile_usage", ctypes.c_size_t),
        ("peak_pagefile_usage", ctypes.c_size_t),
    ]


class _FileTime(ctypes.Structure):
    _fields_ = [
        ("low", ctypes.c_uint32),
        ("high", ctypes.c_uint32),
    ]


def _windows_process_tree(root_pid: int) -> tuple[int, ...]:
    """Return a Windows process plus all descendants from Toolhelp32."""

    if os.name != "nt" or not hasattr(ctypes, "windll"):
        return (root_pid,)

    kernel32 = ctypes.windll.kernel32
    try:
        create_snapshot = kernel32.CreateToolhelp32Snapshot
        create_snapshot.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
        create_snapshot.restype = ctypes.c_void_p
        snapshot = create_snapshot(0x00000002, 0)
        invalid_handle = ctypes.c_void_p(-1).value
        if not snapshot or snapshot == invalid_handle:
            return (root_pid,)
        parent_by_pid: dict[int, int] = {}
        try:
            process_first = kernel32.Process32FirstW
            process_next = kernel32.Process32NextW
            process_first.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ProcessEntry32W)]
            process_first.restype = ctypes.c_int
            process_next.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ProcessEntry32W)]
            process_next.restype = ctypes.c_int
            entry = _ProcessEntry32W()
            entry.dwSize = ctypes.sizeof(entry)
            if not process_first(snapshot, ctypes.byref(entry)):
                return (root_pid,)
            while True:
                parent_by_pid[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
                entry.dwSize = ctypes.sizeof(entry)
                if not process_next(snapshot, ctypes.byref(entry)):
                    break
        finally:
            close_handle = kernel32.CloseHandle
            close_handle.argtypes = [ctypes.c_void_p]
            close_handle.restype = ctypes.c_int
            close_handle(snapshot)
    except (AttributeError, OSError, TypeError, ValueError):
        return (root_pid,)

    descendants = {int(root_pid)}
    changed = True
    while changed:
        changed = False
        for pid, parent_pid in parent_by_pid.items():
            if parent_pid in descendants and pid not in descendants:
                descendants.add(pid)
                changed = True
    return tuple(sorted(descendants))


def _windows_working_set_mb(process_id: int) -> float | None:
    """Read one Windows process working set in MiB."""

    if os.name != "nt" or not hasattr(ctypes, "windll"):
        return None

    kernel32 = ctypes.windll.kernel32
    try:
        open_process = kernel32.OpenProcess
        open_process.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        open_process.restype = ctypes.c_void_p
        process = open_process(0x0410, False, int(process_id))
        if not process:
            return None
        try:
            counters = _ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
            get_memory.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(_ProcessMemoryCounters),
                ctypes.c_ulong,
            ]
            get_memory.restype = ctypes.c_int
            if not get_memory(process, ctypes.byref(counters), counters.cb):
                return None
            return float(counters.working_set_size) / (1024.0 * 1024.0)
        finally:
            close_handle = kernel32.CloseHandle
            close_handle.argtypes = [ctypes.c_void_p]
            close_handle.restype = ctypes.c_int
            close_handle(process)
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _windows_cpu_time_seconds(process_id: int) -> float | None:
    """Read one Windows process' user+kernel CPU time in seconds."""

    if os.name != "nt" or not hasattr(ctypes, "windll"):
        return None

    kernel32 = ctypes.windll.kernel32
    try:
        open_process = kernel32.OpenProcess
        open_process.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        open_process.restype = ctypes.c_void_p
        process = open_process(0x1000, False, int(process_id))
        if not process:
            return None
        try:
            creation = _FileTime()
            exit_time = _FileTime()
            kernel = _FileTime()
            user = _FileTime()
            get_times = kernel32.GetProcessTimes
            get_times.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(_FileTime),
                ctypes.POINTER(_FileTime),
                ctypes.POINTER(_FileTime),
                ctypes.POINTER(_FileTime),
            ]
            get_times.restype = ctypes.c_int
            if not get_times(
                process,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ):
                return None
            ticks = (
                (int(kernel.high) << 32)
                + int(kernel.low)
                + (int(user.high) << 32)
                + int(user.low)
            )
            return float(ticks) / 10_000_000.0
        finally:
            close_handle = kernel32.CloseHandle
            close_handle.argtypes = [ctypes.c_void_p]
            close_handle.restype = ctypes.c_int
            close_handle(process)
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _probe_audio_duration(audio_path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is not None:
        try:
            result = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(_windows_compatible_path(audio_path)),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
            )
            duration = max(0.0, float(result.stdout.strip()))
            if duration > 0.0:
                return duration
        except (OSError, ValueError, subprocess.SubprocessError):
            pass

    # The isolated FunASR runtime bundles libsndfile even on desktops where
    # ffprobe is absent.  Use it only as a duration probe; slicing still
    # requires the product-level ffmpeg check below.
    runtime_python = _external_sensevoice_python()
    if runtime_python is None:
        return 0.0
    runner = (
        "import soundfile as sf,sys;"
        "print(float(sf.info(sys.argv[1]).duration),flush=True)"
    )
    try:
        result = subprocess.run(
            [str(runtime_python), "-c", runner, str(_windows_compatible_path(audio_path))],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_runtime_environment(),
            timeout=15,
        )
        return max(0.0, float(result.stdout.strip()))
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def build_audio_segment_ranges(
    duration_seconds: float,
    *,
    target_seconds: float = 30.0,
    max_seconds: float = 60.0,
) -> tuple[tuple[float, float], ...]:
    """Split one audio source into deterministic product-level ranges.

    The count is chosen before any model call, which makes the persisted
    `(job, config, segment_index)` keys stable across worker restarts.  Short
    audio remains one segment; longer audio is balanced around 30 seconds and
    never exceeds the 60-second upper bound from the product contract.
    """

    duration = max(0.0, float(duration_seconds))
    target = max(1.0, min(float(target_seconds), float(max_seconds)))
    maximum = max(target, float(max_seconds))
    if duration <= 0.0:
        return ((0.0, target),)
    count = max(1, math.ceil(duration / target))
    count = max(count, math.ceil(duration / maximum))
    width = duration / count
    return tuple(
        (round(index * width, 6), round(duration if index == count - 1 else (index + 1) * width, 6))
        for index in range(count)
    )


def materialize_audio_segment(
    audio_path: Path,
    *,
    start_seconds: float,
    end_seconds: float,
    directory: Path,
) -> Path:
    """Create one short-lived 16 kHz mono WAV for an ASR segment.

    Only the original compressed audio and the persisted time ranges are
    retained.  The caller owns ``directory`` and removes the generated WAVs
    after the current segment is committed.
    """

    if end_seconds <= start_seconds:
        raise LocalAsrError("ASR 片段时间范围无效")
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise LocalAsrError("本地 ASR 切片需要可用的 ffmpeg")
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / f"segment-{start_seconds:.3f}-{end_seconds:.3f}.wav"
    duration = max(0.01, float(end_seconds) - float(start_seconds))
    try:
        subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{max(0.0, float(start_seconds)):.6f}",
                "-i",
                str(_windows_compatible_path(audio_path)),
                "-t",
                f"{duration:.6f}",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                str(output),
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(30.0, duration * 4.0),
        )
    except subprocess.TimeoutExpired as error:
        raise TimeoutError("ASR 片段音频切片超时") from error
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", None) or str(error)
        raise LocalAsrError(f"ASR 片段音频切片失败：{str(detail).strip()}") from error
    if not output.is_file() or output.stat().st_size == 0:
        raise LocalAsrError("ASR 片段音频切片为空")
    return output


class SenseVoiceTranscriber:
    """Run the pinned SenseVoiceSmall model in its isolated FunASR runtime."""

    name = "sensevoice-small"

    def __init__(self, model_path: Path, *, model_id: str = "sensevoice-small") -> None:
        self.model_path = model_path
        self.model_id = model_id

    def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None = None,
        timeout_seconds: float = 180.0,
    ) -> Transcript:
        if not is_local_model_ready(self.model_path.parent, self.model_id):
            raise LocalAsrError("SenseVoiceSmall 模型尚未下载完成")
        if self.model_id == "sensevoice-small":
            resolved_local_model_identity(self.model_path, self.model_id)
        if not audio_path.is_file() or audio_path.stat().st_size == 0:
            raise LocalAsrError("缺少可转写的音频文件")
        runtime_python = _external_sensevoice_python()
        if runtime_python is None:
            raise LocalAsrError("SenseVoiceSmall 独立运行时尚未安装")
        runner = (
            "import json,sys;"
            "from funasr import AutoModel;"
            "m=AutoModel(model=sys.argv[1],disable_update=True);"
            "r=m.generate(input=sys.argv[2],language=sys.argv[3],use_itn=True,batch_size_s=60);"
            "print(json.dumps(r,ensure_ascii=False),flush=True)"
        )
        try:
            completed = subprocess.run(
                [
                    str(runtime_python),
                    "-c",
                    runner,
                    str(_windows_compatible_path(self.model_path)),
                    str(_windows_compatible_path(audio_path)),
                    language or "auto",
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=_runtime_environment(),
                timeout=max(1.0, float(timeout_seconds)),
            )
        except subprocess.TimeoutExpired as error:
            raise TimeoutError("SenseVoiceSmall 单片转写无进展超时") from error
        except subprocess.CalledProcessError as error:
            detail = (error.stderr or error.stdout or str(error)).strip()
            raise LocalAsrError(f"SenseVoiceSmall 转写失败：{detail}") from error
        lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        if not lines:
            raise LocalAsrError("SenseVoiceSmall 没有返回结果")
        try:
            payload = json.loads(lines[-1])
        except json.JSONDecodeError as error:
            raise LocalAsrError("SenseVoiceSmall 返回了无效结果") from error
        entries = payload if isinstance(payload, list) else [payload]
        text = " ".join(
            part
            for part in (_sensevoice_text(item.get("text")) for item in entries if isinstance(item, dict))
            if part
        )
        if not text:
            return Transcript(language, "asr", f"funasr:{self.model_id}", ())
        duration = _probe_audio_duration(audio_path)
        return Transcript(
            language,
            "asr",
            f"funasr:{self.model_id}",
            (TranscriptSegment(0.0, duration, text),),
        )


_SENSEVOICE_WORKER_SCRIPT = r'''
import json
import sys
from funasr import AutoModel

def clean(value):
    import re
    return " ".join(re.sub(r"<\|[^|>]+\|>", " ", str(value or "")).split())

try:
    model = AutoModel(model=sys.argv[1], disable_update=True)
    print(json.dumps({"event": "model_ready"}, ensure_ascii=False), flush=True)
    for line in sys.stdin:
        request = json.loads(line)
        if request.get("event") == "shutdown":
            break
        if request.get("event") not in {"transcribe", "transcribe_batch"}:
            continue
        try:
            print(json.dumps({"event": "inference_started"}), flush=True)
            is_batch = request.get("event") == "transcribe_batch"
            audio_paths = request.get("audio_paths") if is_batch else [request["audio_path"]]
            if not isinstance(audio_paths, list) or not audio_paths:
                raise RuntimeError("SenseVoiceSmall batch 音频列表为空")
            result = model.generate(
                input=audio_paths if is_batch else audio_paths[0],
                language=request.get("language") or "auto",
                use_itn=True,
                batch_size_s=60,
            )
            entries = result if isinstance(result, list) else [result]
            if is_batch:
                if len(entries) != len(audio_paths):
                    raise RuntimeError(
                        f"SenseVoiceSmall batch 返回 {len(entries)} 条，期望 {len(audio_paths)} 条"
                    )
                items = []
                for index, item in enumerate(entries):
                    text = clean(item.get("text")) if isinstance(item, dict) else ""
                    items.append({
                        "request_id": request.get("request_id"),
                        "ordinal": index,
                        "index": index,
                        "text": text,
                        "language": request.get("language"),
                    })
                print(json.dumps({
                    "event": "batch_result",
                    "request_id": request.get("request_id"),
                    "items": items,
                }, ensure_ascii=False), flush=True)
            else:
                text = " ".join(
                    value for value in (
                        clean(item.get("text")) for item in entries if isinstance(item, dict)
                    ) if value
                )
                print(json.dumps({
                    "event": "result", "text": text,
                    "language": request.get("language"),
                }, ensure_ascii=False), flush=True)
        except BaseException as error:
            print(json.dumps({
                "event": "error", "error": str(error) or type(error).__name__,
            }, ensure_ascii=False), flush=True)
except BaseException as error:
    print(json.dumps({
        "event": "startup_error", "error": str(error) or type(error).__name__,
    }, ensure_ascii=False), flush=True)
'''


class SenseVoiceWorker:
    """Single resident, killable SenseVoice process used by the workflow."""

    def __init__(
        self,
        model_path: Path,
        *,
        model_id: str = "sensevoice-small",
        startup_timeout_seconds: float = 180.0,
        segment_timeout_seconds: float = 120.0,
    ) -> None:
        self.model_path = model_path
        self.model_id = model_id
        self.startup_timeout_seconds = max(1.0, float(startup_timeout_seconds))
        self.segment_timeout_seconds = max(0.01, float(segment_timeout_seconds))
        self._stdin = None
        self._events: Queue[dict[str, object]] | None = None
        self._reader: Thread | None = None
        self._process = None
        self._ready = False
        self._generation = 0
        self._last_startup_seconds: float | None = None
        self._last_call_cold = False
        self.last_batch_integrity: dict[str, int | str] = {
            "missing_segments": 0,
            "duplicate_segments": 0,
            "out_of_order_segments": 0,
            "status": "not_run",
        }

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def last_startup_seconds(self) -> float | None:
        """Duration of the most recent model load, if one completed."""

        return self._last_startup_seconds

    @property
    def last_call_cold(self) -> bool:
        """Whether the most recent transcribe call had to load the model."""

        return self._last_call_cold

    @property
    def alive(self) -> bool:
        return bool(self._process is not None and self._process.poll() is None)

    @property
    def pid(self) -> int | None:
        return int(self._process.pid) if self._process is not None else None

    def memory_rss_mb(self) -> float | None:
        """Return the Worker tree's aggregate working-set size when available."""

        process_id = self.pid
        if process_id is None or not hasattr(ctypes, "windll"):
            return None
        measurements = [
            _windows_working_set_mb(pid) for pid in _windows_process_tree(process_id)
        ]
        valid = [value for value in measurements if isinstance(value, (int, float))]
        return sum(valid) if valid else None

    def cpu_time_seconds(self) -> float | None:
        """Return aggregate CPU time for the Worker and its descendants.

        FunASR does not expose a reliable decode-progress callback.  CPU time
        is therefore used as a conservative proof that a long inference is
        still doing work; queue polling and lease heartbeats never count as
        model progress.
        """

        process_id = self.pid
        if process_id is None:
            return None
        measurements = [
            _windows_cpu_time_seconds(pid) for pid in _windows_process_tree(process_id)
        ]
        valid = [value for value in measurements if isinstance(value, (int, float))]
        return sum(valid) if valid else None

    def _refresh_compute_deadline(
        self,
        deadline: float,
        previous_cpu_time: float | None,
    ) -> tuple[float, float | None]:
        current_cpu_time = self.cpu_time_seconds()
        if current_cpu_time is None:
            return deadline, previous_cpu_time
        if (
            previous_cpu_time is not None
            and current_cpu_time > previous_cpu_time + 1e-6
        ):
            deadline = monotonic() + self.segment_timeout_seconds
        return deadline, current_cpu_time

    def _start(self, cancel_check: Callable[[], bool] | None = None) -> None:
        started_at = monotonic()
        self.close()
        runtime_python = _external_sensevoice_python()
        if runtime_python is None:
            raise LocalAsrError("SenseVoiceSmall 独立运行时尚未安装")
        try:
            process = subprocess.Popen(
                [
                    str(runtime_python),
                    "-u",
                    "-c",
                    _SENSEVOICE_WORKER_SCRIPT,
                    str(_windows_compatible_path(self.model_path)),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=_runtime_environment(),
            )
        except OSError as error:
            raise LocalAsrError(f"SenseVoiceSmall Worker 启动失败：{error}") from error
        events: Queue[dict[str, object]] = Queue()
        self._events = events
        self._stdin = process.stdin
        self._process = process
        self._ready = False
        self._generation += 1

        def read_events() -> None:
            stream = process.stdout
            if stream is None:
                return
            for line in stream:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict):
                    events.put(event)

        self._reader = Thread(
            target=read_events,
            name=f"sensevoice-events-{self.model_id}",
            daemon=True,
        )
        self._reader.start()
        deadline = monotonic() + self.startup_timeout_seconds
        while True:
            if cancel_check and cancel_check():
                self.close()
                raise LocalAsrError("任务已取消")
            try:
                event = events.get(timeout=min(0.1, max(0.01, deadline - monotonic())))
            except Empty:
                event = None
            if event is not None:
                if event.get("event") == "model_ready":
                    self._ready = True
                    self._last_startup_seconds = max(0.0, monotonic() - started_at)
                    return
                if event.get("event") == "startup_error":
                    self.close()
                    raise LocalAsrError(f"SenseVoiceSmall Worker 启动失败：{event.get('error')}")
            if process.poll() is not None:
                return_code = process.returncode
                self.close()
                raise LocalAsrError(
                    f"SenseVoiceSmall Worker 异常退出（退出码 {return_code}）"
                )
            if monotonic() >= deadline:
                self.close()
                raise TimeoutError("SenseVoiceSmall Worker 启动超过 180 秒")

    def ensure_started(self, cancel_check: Callable[[], bool] | None = None) -> int:
        """Load the model before a segment lease is claimed.

        The returned generation is carried through the lease and every
        heartbeat/commit/failure mutation so a rebuilt Worker cannot reuse an
        older generation's lease owner.
        """

        if not self._ready or not self.alive:
            self._last_call_cold = True
            self._start(cancel_check=cancel_check)
        else:
            self._last_call_cold = False
        return self._generation

    def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None = None,
        cancel_check: Callable[[], bool] | None = None,
        on_heartbeat: Callable[[], None] | None = None,
        on_lease_heartbeat: Callable[[], None] | None = None,
    ) -> tuple[str, str | None]:
        self.last_batch_integrity = {
            "missing_segments": 0,
            "duplicate_segments": 0,
            "out_of_order_segments": 0,
            "status": "ok",
        }
        self._last_call_cold = not self._ready or not self.alive
        if self._last_call_cold:
            self._start(cancel_check=cancel_check)
        if self._stdin is None or self._events is None or self._process is None:
            raise LocalAsrError("SenseVoiceSmall Worker 未启动")
        try:
            self._stdin.write(
                json.dumps(
                    {
                    "event": "transcribe",
                    "audio_path": str(_windows_compatible_path(audio_path)),
                    "language": language,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            self._stdin.flush()
        except (BrokenPipeError, OSError) as error:
            self.close()
            raise LocalAsrError("SenseVoiceSmall Worker 已退出") from error
        deadline = monotonic() + self.segment_timeout_seconds
        previous_cpu_time = self.cpu_time_seconds()
        while True:
            if cancel_check and cancel_check():
                self.close()
                raise LocalAsrError("任务已取消")
            deadline, previous_cpu_time = self._refresh_compute_deadline(
                deadline,
                previous_cpu_time,
            )
            remaining = deadline - monotonic()
            if remaining <= 0:
                self.close()
                raise TimeoutError("SenseVoiceSmall 单片转写无进展超过 120 秒")
            try:
                event = self._events.get(timeout=min(0.1, remaining))
            except Empty:
                event = None
            if event is not None:
                event_type = event.get("event")
                if event_type in {"vad_completed", "decode_progress", "segment_progress"}:
                    deadline = monotonic() + self.segment_timeout_seconds
                    if on_heartbeat:
                        on_heartbeat()
                    continue
                if event_type in {"model_ready", "inference_started"}:
                    continue
                if event_type == "result":
                    return str(event.get("text") or ""), event.get("language")
                if event_type == "error":
                    self.close()
                    raise LocalAsrError(str(event.get("error") or "SenseVoiceSmall Worker 识别失败"))
                self.close()
                raise LocalAsrError("SenseVoiceSmall Worker 返回了无效事件")
            elif on_lease_heartbeat:
                # No model progress event arrived.  A lease may be renewed
                # separately, but polling is not ASR progress and must not
                # reset the per-segment no-progress deadline.
                on_lease_heartbeat()
            if self._process.poll() is not None:
                self.close()
                raise LocalAsrError("SenseVoiceSmall Worker 异常退出")

    def transcribe_batch(
        self,
        audio_paths: list[Path],
        *,
        language: str | None = None,
        cancel_check: Callable[[], bool] | None = None,
        on_heartbeat: Callable[[], None] | None = None,
        on_lease_heartbeat: Callable[[], None] | None = None,
    ) -> tuple[tuple[str, str | None], ...]:
        """Recognize a bounded list of files in one resident model call."""

        if not audio_paths:
            raise LocalAsrError("SenseVoiceSmall batch 音频列表为空")
        if not self._ready or not self.alive:
            self._last_call_cold = not self._ready or not self.alive
            self._start(cancel_check=cancel_check)
        else:
            self._last_call_cold = False
        if self._stdin is None or self._events is None or self._process is None:
            raise LocalAsrError("SenseVoiceSmall Worker 未启动")
        paths = [str(_windows_compatible_path(path)) for path in audio_paths]
        request_id = uuid4().hex
        self.last_batch_integrity = {
            "missing_segments": len(paths),
            "duplicate_segments": 0,
            "out_of_order_segments": 0,
            "status": "pending",
        }
        try:
            self._stdin.write(
                json.dumps(
                    {
                        "event": "transcribe_batch",
                        "request_id": request_id,
                        "audio_paths": paths,
                        "language": language,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            self._stdin.flush()
        except (BrokenPipeError, OSError) as error:
            self.close()
            raise LocalAsrError("SenseVoiceSmall Worker 已退出") from error
        deadline = monotonic() + self.segment_timeout_seconds
        previous_cpu_time = self.cpu_time_seconds()
        while True:
            if cancel_check and cancel_check():
                self.close()
                raise LocalAsrError("任务已取消")
            deadline, previous_cpu_time = self._refresh_compute_deadline(
                deadline,
                previous_cpu_time,
            )
            remaining = deadline - monotonic()
            if remaining <= 0:
                self.close()
                raise TimeoutError("SenseVoiceSmall batch 转写无进展超过 120 秒")
            try:
                event = self._events.get(timeout=min(0.1, remaining))
            except Empty:
                event = None
            if event is not None:
                event_type = event.get("event")
                if event_type in {"vad_completed", "decode_progress", "segment_progress"}:
                    deadline = monotonic() + self.segment_timeout_seconds
                    if on_heartbeat:
                        on_heartbeat()
                    continue
                if event_type in {"model_ready", "inference_started"}:
                    continue
                if event_type == "batch_result":
                    response_request_id = event.get("request_id")
                    items = event.get("items")
                    if response_request_id != request_id:
                        self.last_batch_integrity = {
                            "missing_segments": len(paths),
                            "duplicate_segments": 0,
                            "out_of_order_segments": 0,
                            "status": "invalid_request_id",
                        }
                        self.close()
                        raise LocalAsrError("SenseVoiceSmall batch 请求标识不一致")
                    if not isinstance(items, list):
                        self.last_batch_integrity = {
                            "missing_segments": len(paths),
                            "duplicate_segments": 0,
                            "out_of_order_segments": 0,
                            "status": "invalid_items",
                        }
                        self.close()
                        raise LocalAsrError("SenseVoiceSmall batch 返回片段列表无效")
                    ordinals: list[int | None] = []
                    for item in items:
                        if not isinstance(item, dict) or item.get("request_id") != request_id:
                            ordinals.append(None)
                            continue
                        try:
                            ordinal = int(item.get("ordinal"))
                        except (TypeError, ValueError):
                            ordinals.append(None)
                            continue
                        ordinals.append(ordinal)
                    valid_ordinals = [value for value in ordinals if value is not None]
                    expected_ordinals = set(range(len(paths)))
                    seen_ordinals = set(valid_ordinals)
                    duplicate_count = len(valid_ordinals) - len(seen_ordinals)
                    missing_count = len(expected_ordinals - seen_ordinals)
                    out_of_order_count = sum(
                        ordinal != expected_index
                        for expected_index, ordinal in enumerate(ordinals)
                    )
                    self.last_batch_integrity = {
                        "missing_segments": missing_count,
                        "duplicate_segments": duplicate_count,
                        "out_of_order_segments": out_of_order_count,
                        "status": "ok"
                        if not (
                            len(items) != len(paths)
                            or missing_count
                            or duplicate_count
                            or out_of_order_count
                        )
                        else "invalid",
                    }
                    if self.last_batch_integrity["status"] != "ok":
                        self.close()
                        raise LocalAsrError("SenseVoiceSmall batch 返回缺失、重复或乱序片段")
                    normalized: list[tuple[str, str | None]] = []
                    for expected_index, item in enumerate(items):
                        if not isinstance(item, dict):
                            self.close()
                            raise LocalAsrError("SenseVoiceSmall batch 返回项无效")
                        text = str(item.get("text") or "").strip()
                        if not text:
                            self.close()
                            raise LocalAsrError("SenseVoiceSmall batch 返回空文本")
                        normalized.append((text, item.get("language")))
                    return tuple(normalized)
                if event_type == "error":
                    self.close()
                    raise LocalAsrError(str(event.get("error") or "SenseVoiceSmall Worker 识别失败"))
                self.close()
                raise LocalAsrError("SenseVoiceSmall Worker 返回了无效事件")
            elif on_lease_heartbeat:
                on_lease_heartbeat()
            if self._process.poll() is not None:
                self.close()
                raise LocalAsrError("SenseVoiceSmall Worker 异常退出")

    def close(self) -> None:
        stdin = self._stdin
        process = self._process
        self._stdin = None
        self._events = None
        self._reader = None
        self._process = None
        self._ready = False
        if stdin is not None:
            try:
                if process is not None and process.poll() is None:
                    stdin.write(json.dumps({"event": "shutdown"}) + "\n")
                    stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            stdin.close()
        if process is not None:
            if process.poll() is None:
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
