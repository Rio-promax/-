"""Deterministic environment and task submission checks."""

from __future__ import annotations

import platform
import shutil
import socket
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from app.adapters.asr.local import (
    is_local_model_ready,
    local_asr_model_info,
    local_asr_runtime_available,
)

__all__ = [
    "cloud_asr_ready",
    "environment_report",
    "estimate_task_resources",
    "local_asr_ready",
    "task_preflight",
]


@dataclass(frozen=True, slots=True)
class PreflightCheck:
    code: str
    label: str
    status: str
    blocking: bool
    message: str
    action: str | None = None


@dataclass(frozen=True, slots=True)
class ResourceEstimate:
    estimated_duration_seconds_min: int
    estimated_duration_seconds_max: int
    estimated_disk_bytes: int
    disk_free_bytes: int
    memory_required_mb: int
    cloud_input_tokens_min: int
    cloud_input_tokens_max: int
    cloud_cost_min: float | None
    cloud_cost_max: float | None
    cloud_cost_currency: str | None
    cloud_cost_note: str
    basis: str


def _secret_status(store, key: str, *, purpose: str) -> str:
    try:
        return "saved" if store.get_secret_setting(key, purpose=purpose) else "not_configured"
    except Exception:
        return "unreadable"


def cloud_asr_ready(store) -> bool:
    api_url = (
        store.get_setting("asr_cloud_api_url") or store.get_setting("asr_api_url") or ""
    ).strip()
    model = (
        store.get_setting("asr_cloud_model") or store.get_setting("asr_model") or ""
    ).strip()
    key_ready = any(
        _secret_status(store, key, purpose="云端 ASR API Key") == "saved"
        for key in ("asr_cloud_api_key", "asr_api_key")
    )
    return bool(api_url and model and key_ready)


def local_asr_ready(store, model_root: Path) -> bool:
    selected = store.get_setting("asr_local_model") or store.get_setting("asr_model")
    return bool(
        local_asr_runtime_available()
        and selected
        and is_local_model_ready(model_root, selected)
    )


def _disk_usage(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(path)


def environment_report(
    store,
    archive_root: Path,
    model_root: Path,
    *,
    check_network: bool = True,
) -> dict[str, object]:
    checks: list[PreflightCheck] = []
    archive_usage = None
    try:
        archive_usage = _disk_usage(archive_root)
        disk_status = "ok" if archive_usage.free >= 512 * 1024**2 else "error"
        checks.append(
            PreflightCheck(
                "disk",
                "归档磁盘空间",
                disk_status,
                disk_status == "error",
                f"可用空间 {_format_bytes(archive_usage.free)}",
                "清理归档或更换归档目录" if disk_status == "error" else None,
            )
        )
    except OSError as error:
        checks.append(
            PreflightCheck(
                "disk", "归档磁盘空间", "error", True, f"无法读取磁盘空间：{error}", "检查归档目录"
            )
        )

    ffmpeg_path = shutil.which("ffmpeg")
    checks.append(
        PreflightCheck(
            "ffmpeg",
            "FFmpeg",
            "ok" if ffmpeg_path else "warning",
            False,
            f"已找到：{ffmpeg_path}" if ffmpeg_path else "未找到；涉及音视频转换时需要安装",
            None if ffmpeg_path else "安装 FFmpeg 并加入 PATH",
        )
    )
    checks.append(
        PreflightCheck(
            "python",
            "Python 运行时",
            "ok",
            False,
            f"Python {platform.python_version()} / {platform.system()}",
        )
    )
    checks.append(
        PreflightCheck(
            "local_asr_runtime",
            "本地 ASR 运行时",
            "ok" if local_asr_runtime_available() else "warning",
            False,
            "faster-whisper 已安装" if local_asr_runtime_available() else "未安装 faster-whisper",
            None if local_asr_runtime_available() else "安装 product.[local-asr]",
        )
    )
    checks.append(
        PreflightCheck(
            "local_model_root",
            "本地模型目录",
            "ok" if model_root.is_dir() else "warning",
            False,
            str(model_root),
        )
    )

    if check_network:
        try:
            with socket.create_connection(("huggingface.co", 443), timeout=2):
                network_status = "ok"
                network_message = "可以连接公开模型服务"
        except OSError as error:
            network_status = "warning"
            network_message = f"公开模型网络检查失败：{error}"
        checks.append(
            PreflightCheck(
                "network",
                "网络",
                network_status,
                False,
                network_message,
                "检查网络代理或稍后重试" if network_status != "ok" else None,
            )
        )

    secret_status = {
        "summary_api_key": _secret_status(store, "summary_api_key", purpose="总结模型 API Key"),
        "asr_cloud_api_key": _secret_status(store, "asr_cloud_api_key", purpose="云端 ASR API Key"),
        "bilibili_session": _secret_status(store, "bilibili_session_cookie", purpose="B站登录态"),
    }
    for key, label in (
        ("summary_api_key", "总结模型密钥"),
        ("asr_cloud_api_key", "云端 ASR 密钥"),
        ("bilibili_session", "B站登录态"),
    ):
        checks.append(
            PreflightCheck(
                key,
                label,
                "ok" if secret_status[key] == "saved" else "warning",
                False,
                "已保存（值不会在诊断中返回）" if secret_status[key] == "saved" else "未配置",
            )
        )

    blocking_errors = [item for item in checks if item.blocking and item.status == "error"]
    warnings = [item for item in checks if item.status == "warning"]
    return {
        "status": "error" if blocking_errors else "warning" if warnings else "ok",
        "checked_at": datetime.now(UTC),
        "checks": [asdict(item) for item in checks],
        "platform": platform.system(),
        "python_version": sys.version.split()[0],
        "ffmpeg_path": ffmpeg_path,
        "disk_free_bytes": archive_usage.free if archive_usage else 0,
        "model_root": str(model_root),
        "secret_status": secret_status,
    }


def estimate_task_resources(
    *,
    duration_seconds: float | None,
    text_length: int,
    model_root: Path,
    local_model: str | None,
    archive_root: Path,
) -> ResourceEstimate:
    duration = max(1.0, float(duration_seconds or max(60, text_length / 4)))
    estimated_min = max(10, int(duration * 0.15))
    estimated_max = max(estimated_min + 10, int(duration * 1.8 + 60))
    token_base = max(1, int(text_length / 4) if text_length else int(duration * 25))
    disk_bytes = max(5 * 1024**2, int(token_base * 3 + duration * 2048))
    try:
        disk_free = _disk_usage(archive_root).free
    except OSError:
        disk_free = 0
    memory_mb = 1024
    basis = "按输入时长/文本长度估算；实际耗时受网络、设备和模型影响"
    if local_model:
        try:
            memory_mb = max(
                memory_mb, local_asr_model_info(model_root, local_model).memory_required_mb
            )
            disk_bytes += max(
                0, int(local_asr_model_info(model_root, local_model).estimated_size_bytes * 0.02)
            )
            basis += "；已计入所选本地模型资源档位"
        except Exception:
            basis += "；本地模型信息不可用"
    return ResourceEstimate(
        estimated_duration_seconds_min=estimated_min,
        estimated_duration_seconds_max=estimated_max,
        estimated_disk_bytes=disk_bytes,
        disk_free_bytes=disk_free,
        memory_required_mb=memory_mb,
        cloud_input_tokens_min=max(1, int(token_base * 0.8)),
        cloud_input_tokens_max=max(1, int(token_base * 1.3)),
        cloud_cost_min=None,
        cloud_cost_max=None,
        cloud_cost_currency=None,
        cloud_cost_note="未配置服务商单价，不伪造金额；请以服务商账单为准",
        basis=basis,
    )


def task_preflight(
    store,
    *,
    kind: str | None,
    duration_seconds: float | None,
    text_length: int,
    has_transcript: bool,
    asr_engine: str | None,
    local_model: str | None,
    model: str | None,
    max_chunk_tokens: int,
    source_url: str | None,
    archive_root: Path,
    model_root: Path,
) -> dict[str, object]:
    checks: list[PreflightCheck] = []
    effective_model = (model or store.get_setting("summary_model") or "").strip()
    summary_url = (store.get_setting("summary_api_url") or "").strip()
    summary_key = _secret_status(store, "summary_api_key", purpose="总结模型 API Key")
    if not effective_model or not summary_url or summary_key != "saved":
        checks.append(
            PreflightCheck(
                "summary_not_configured",
                "总结模型配置",
                "error",
                True,
                "总结模型地址、模型名或密钥未完整配置",
                "在设置页保存总结模型配置",
            )
        )
    else:
        checks.append(PreflightCheck("summary_configured", "总结模型配置", "ok", False, "已配置"))

    if not effective_model:
        checks.append(
            PreflightCheck(
                "summary_model_missing", "总结模型参数", "error", True, "任务未选择总结模型"
            )
        )
    if not 32 <= max_chunk_tokens <= 32000:
        checks.append(
            PreflightCheck("invalid_parameters", "任务参数", "error", True, "分块参数超出支持范围")
        )
    else:
        checks.append(PreflightCheck("parameters", "任务参数", "ok", False, "参数范围有效"))

    needs_asr = kind in {"video", "audio"} and not has_transcript
    if not needs_asr:
        checks.append(
            PreflightCheck(
                "asr_not_required", "语音识别材料", "ok", False, "已有字幕或当前内容不需要 ASR"
            )
        )
    else:
        engine = asr_engine or store.get_setting("asr_engine") or "cloud"
        if engine == "local":
            selected = (
                local_model
                or store.get_setting("asr_local_model")
                or store.get_setting("asr_model")
            )
            runtime_ready = local_asr_runtime_available()
            model_ready = bool(selected and is_local_model_ready(model_root, selected))
            if not runtime_ready or not model_ready:
                checks.append(
                    PreflightCheck(
                        "asr_local_not_ready",
                        "本地 ASR",
                        "error",
                        True,
                        "本地运行时或模型未通过校验",
                        "安装运行时并选择已校验模型",
                    )
                )
            else:
                checks.append(
                    PreflightCheck("asr_local_ready", "本地 ASR", "ok", False, "运行时和模型已就绪")
                )
        else:
            if not cloud_asr_ready(store):
                if local_asr_ready(store, model_root):
                    checks.append(
                        PreflightCheck(
                            "asr_cloud_not_configured",
                            "云端 ASR",
                            "warning",
                            False,
                            "云端 ASR 未配置，将使用本地模型",
                            "在设置页重新配置云端 ASR",
                        )
                    )
                else:
                    checks.append(
                        PreflightCheck(
                            "asr_cloud_not_configured",
                            "云端 ASR",
                            "error",
                            True,
                            "云端 ASR 服务商、接口地址、模型或密钥未完整配置",
                            "在设置页保存云端 ASR 密钥，或切换已校验的本地模型",
                        )
                    )
            else:
                checks.append(
                    PreflightCheck(
                        "asr_cloud_ready", "云端 ASR", "ok", False, "接口、模型和密钥已配置"
                    )
                )

    if source_url:
        parsed = urlparse(source_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            checks.append(
                PreflightCheck(
                    "source_invalid", "来源地址", "error", True, "来源地址不是有效的 HTTP(S) URL"
                )
            )
        else:
            checks.append(
                PreflightCheck("source_valid", "来源地址", "ok", False, "来源地址格式有效")
            )

    estimate = estimate_task_resources(
        duration_seconds=duration_seconds,
        text_length=text_length,
        model_root=model_root,
        local_model=local_model,
        archive_root=archive_root,
    )
    if estimate.disk_free_bytes and estimate.disk_free_bytes < estimate.estimated_disk_bytes * 2:
        checks.append(
            PreflightCheck(
                "disk_space_low",
                "预计存储空间",
                "error",
                True,
                "可用磁盘空间不足以安全保留原始材料和阶段性产物",
                "清理空间或更换归档目录",
            )
        )
    else:
        checks.append(PreflightCheck("disk_space", "预计存储空间", "ok", False, "空间区间可接受"))

    blocking = [item for item in checks if item.blocking and item.status == "error"]
    return {
        "ready": not blocking,
        "checks": [asdict(item) for item in checks],
        "estimate": asdict(estimate),
    }


def _format_bytes(value: int) -> str:
    if value >= 1024**3:
        return f"{value / 1024**3:.2f} GB"
    if value >= 1024**2:
        return f"{value / 1024**2:.0f} MB"
    return f"{value / 1024:.0f} KB"
