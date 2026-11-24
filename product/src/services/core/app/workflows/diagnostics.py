"""Redacted task diagnostics shared by the API and feedback capture."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


_CHECKPOINT_STAGE = {
    "source_ready": "source",
    "acquiring": "source",
    "extracting": "source",
    "transcript_ready": "transcription",
    "transcribing": "transcription",
    "chunks_ready": "chunking",
    "chunking": "chunking",
    "summary_ready": "summary",
    "summarizing": "summary",
    "archiving": "archive",
    "indexing": "archive",
}

_ERROR_CATEGORY = {
    "summary_generation_failed": "summary",
    "invalid_output": "summary",
    "transcript_incomplete": "transcription",
    "asr_runtime_unavailable": "transcription",
    "asr_local_model_not_installed": "transcription",
    "asr_cloud_not_configured": "configuration",
    "asr_timeout": "transcription",
    "model_unavailable": "configuration",
    "auth_required": "source",
    "access_restricted": "source",
    "source_not_found": "source",
    "unsupported_source": "source",
    "transient_network": "network",
    "disk_space": "storage",
}

_RECOVERY_GUIDANCE_BY_CODE = {
    "auth_required": {
        "action": "login_recheck",
        "suggestion": "请登录来源平台后重新检测来源。",
    },
    "access_restricted": {
        "action": "login_recheck",
        "suggestion": "请登录来源平台后重新检测来源。",
    },
    "source_not_found": {
        "action": "change_source",
        "suggestion": "该来源无法由当前应用修复，请更换内容。",
    },
    "unsupported_source": {
        "action": "change_source",
        "suggestion": "该来源无法由当前应用处理，请更换内容。",
    },
    "transcript_incomplete": {
        "action": "change_source",
        "suggestion": "转写内容不足，请更换内容；无需再次提交当前来源。",
    },
    "asr_runtime_unavailable": {
        "action": "settings",
        "suggestion": "请在设置页安装本地 ASR 组件后重试。",
    },
    "asr_local_model_not_installed": {
        "action": "settings",
        "suggestion": "请在设置页下载并选择本地 ASR 模型后重试。",
    },
    "asr_cloud_not_configured": {
        "action": "settings",
        "suggestion": "请在设置页配置云端 ASR 后重试。",
    },
    "asr_timeout": {
        "action": "retry",
        "suggestion": "已保留已完成阶段，请重试当前任务。",
    },
    "summary_generation_failed": {
        "action": "retry",
        "suggestion": "已保留已完成阶段，请重试当前任务。",
    },
    "invalid_output": {
        "action": "retry",
        "suggestion": "已保留已完成阶段，请重试当前任务。",
    },
    "transient_network": {
        "action": "retry",
        "suggestion": "请检查网络连接后重试当前任务。",
    },
    "model_unavailable": {
        "action": "settings",
        "suggestion": "请检查模型配置或更换可用模型后重试。",
    },
    "disk_space": {
        "action": "settings",
        "suggestion": "请清理可用磁盘空间或更换归档目录后重试。",
    },
    "unknown": {
        "action": "diagnostics",
        "suggestion": "当前错误无法由用户直接修复，请保留诊断信息反馈。",
    },
}

_RECOVERY_GUIDANCE_BY_CATEGORY = {
    "summary": _RECOVERY_GUIDANCE_BY_CODE["summary_generation_failed"],
    "transcription": {
        "action": "diagnostics",
        "suggestion": "当前转写问题无法由用户直接确认，请保留诊断信息并进入诊断。",
    },
    "configuration": _RECOVERY_GUIDANCE_BY_CODE["asr_runtime_unavailable"],
    "source": _RECOVERY_GUIDANCE_BY_CODE["auth_required"],
    "network": _RECOVERY_GUIDANCE_BY_CODE["transient_network"],
    "storage": _RECOVERY_GUIDANCE_BY_CODE["disk_space"],
    "unknown": _RECOVERY_GUIDANCE_BY_CODE["unknown"],
}


def _error_code(job) -> str | None:
    return job.error_code.value if job.error_code is not None else None


def recovery_guidance(
    error_code: str | None,
    *,
    error_category: str | None = None,
) -> dict[str, str]:
    """Return one stable recovery action for an existing error code."""

    code = str(error_code or "").strip()
    guidance = _RECOVERY_GUIDANCE_BY_CODE.get(code)
    if guidance is None:
        guidance = _RECOVERY_GUIDANCE_BY_CATEGORY.get(
            str(error_category or "unknown"),
            _RECOVERY_GUIDANCE_BY_CODE["unknown"],
        )
    return dict(guidance)


def _stage(job) -> str:
    return _CHECKPOINT_STAGE.get(str(job.checkpoint or ""), "task")


def sanitize_context(job, run, app_version: str) -> dict[str, Any]:
    code = _error_code(job)
    category = _ERROR_CATEGORY.get(code or "", "unknown")
    settings = run.settings_snapshot or {}
    return {
        "job_id": job.id,
        "content_id": run.content_id,
        "state": job.state.value,
        "checkpoint": job.checkpoint,
        "progress": job.progress,
        "attempt": job.attempt,
        "error_code": code,
        "error_stage": _stage(job),
        "error_category": category,
        "summary_model": settings.get("model"),
        "summary_provider": settings.get("summary_provider"),
        "summary_template": settings.get("summary_template"),
        "summary_style": settings.get("summary_style"),
        "prompt_version": run.prompt_version,
        "asr_engine": settings.get("asr_engine"),
        "app_version": app_version,
    }


def _diagnostic_event(event) -> dict[str, Any]:
    """Keep the timeline useful without copying arbitrary task metadata."""

    occurred_at = getattr(event, "occurred_at", None)
    if isinstance(occurred_at, datetime):
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)
        occurred_at_value = occurred_at.isoformat()
    else:
        occurred_at_value = str(occurred_at or "")
    event_type = str(getattr(event, "event_type", ""))
    raw_message = str(getattr(event, "message", ""))
    message = (
        "任务发生错误"
        if event_type in {"failed", "error"}
        else raw_message[:500]
    )
    details = getattr(event, "details", {})
    safe_details = {
        key: details[key]
        for key in (
            "previous_state",
            "previous_progress",
            "previous_checkpoint",
            "error_code",
        )
        if isinstance(details, dict) and key in details
    }
    return {
        "id": str(getattr(event, "id", "")),
        "job_id": str(getattr(event, "job_id", "")),
        "sequence": int(getattr(event, "sequence", 0)),
        "attempt": int(getattr(event, "attempt", 0)),
        "event_type": event_type,
        "stage": getattr(event, "stage", None),
        "state": str(getattr(event, "state", "")),
        "progress": int(getattr(event, "progress", 0)),
        "checkpoint": getattr(event, "checkpoint", None),
        "error_code": getattr(event, "error_code", None),
        "message": message,
        "details": safe_details,
        "occurred_at": occurred_at_value,
    }


def build_diagnostic_report(
    job,
    run,
    app_version: str,
    *,
    events: list[Any] | None = None,
) -> dict[str, Any]:
    context = sanitize_context(job, run, app_version)
    guidance = recovery_guidance(
        context["error_code"],
        error_category=context["error_category"],
    )
    return {
        "job_id": job.id,
        "content_id": run.content_id,
        "app_version": app_version,
        "state": job.state.value,
        "checkpoint": job.checkpoint,
        "progress": job.progress,
        "attempt": job.attempt,
        "error_code": context["error_code"],
        "error_stage": context["error_stage"],
        "error_category": context["error_category"],
        "recovery_action": guidance["action"],
        "recovery_suggestion": guidance["suggestion"],
        "context": context,
        "events": [_diagnostic_event(event) for event in (events or [])],
    }
