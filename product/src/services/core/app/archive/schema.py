"""Versioned archive schema and deterministic Markdown rendering."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from app.domain.models import ContentItem

ARCHIVE_SCHEMA_VERSION = "archive-v1"
RECORD_REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "content_id",
        "title",
        "source_url",
        "source_platform",
        "analyzed_at",
        "model",
        "prompt_version",
        "transcript_source",
        "content_hash",
        "tags",
    }
)


class ArchiveSchemaError(ValueError):
    """Raised when an archive record cannot be safely written."""


def build_record(
    content: ContentItem,
    *,
    model: str,
    prompt_version: str,
    transcript_source: str,
    analyzed_at: datetime,
    tags: tuple[str, ...] = (),
    summary_strength: str | None = None,
    asr_model: str | None = None,
    analysis_mode: str | None = None,
    summary_engine: str | None = None,
    summary_provider: str | None = None,
    summary_api_url: str | None = None,
    prompt_hash: str | None = None,
    skill_path: str | None = None,
    skill_hash: str | None = None,
    confidence: float | None = None,
    summary_template: str | None = None,
    summary_style: str | None = None,
    material_level: str | None = None,
) -> dict[str, Any]:
    if not model.strip():
        raise ArchiveSchemaError("model must not be empty")
    record = {
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "content_id": content.id,
        "title": content.title,
        "source_url": content.source.canonical_url,
        "source_platform": content.source.platform.value,
        "platform": content.source.platform.value,
        "source_author": content.source.author,
        "published_at": _datetime_value(content.source.published_at),
        "acquired_at": _datetime_value(content.source.acquired_at),
        "created_at": _datetime_value(content.created_at),
        "analyzed_at": _datetime_value(analyzed_at),
        "content_type": content.kind.value,
        "source_type": transcript_source,
        "analysis_mode": analysis_mode,
        "summary_engine": summary_engine,
        "summary_provider": summary_provider,
        "summary_api_url": summary_api_url,
        "prompt_hash": prompt_hash,
        "skill_path": skill_path,
        "skill_hash": skill_hash,
        "summary_template": summary_template,
        "summary_style": summary_style,
        "asr_model": asr_model,
        "confidence": confidence,
        "model": model,
        "prompt_version": prompt_version,
        "transcript_source": transcript_source,
        "content_hash": content.content_hash,
        "tags": list(dict.fromkeys(tag.strip() for tag in tags if tag.strip())),
        "language": content.language,
        "duration_seconds": content.duration_seconds,
        "introduction": getattr(content, "introduction", "") or "",
    }
    if summary_strength is not None:
        record["summary_strength"] = summary_strength
    if material_level is not None:
        record["material_level"] = material_level
    return record


def validate_record(record: Mapping[str, Any]) -> None:
    missing = sorted(RECORD_REQUIRED_FIELDS - record.keys())
    if missing:
        raise ArchiveSchemaError(f"record missing required fields: {', '.join(missing)}")
    if record["schema_version"] != ARCHIVE_SCHEMA_VERSION:
        raise ArchiveSchemaError(f"unsupported archive schema: {record['schema_version']!r}")
    if not isinstance(record["tags"], list) or not all(
        isinstance(tag, str) for tag in record["tags"]
    ):
        raise ArchiveSchemaError("record tags must be a list of strings")
    if not isinstance(record["content_id"], str) or not record["content_id"].strip():
        raise ArchiveSchemaError("record content_id must not be empty")


def render_markdown(record: Mapping[str, Any], body: str) -> str:
    """Render user-readable Markdown; structured fields stay in record.json."""

    validate_record(record)
    lines = [f"# {record['title']}", ""]
    platform = record.get("platform") or record.get("source_platform")
    if platform:
        lines.append(f"- 平台：{platform}")
    author = record.get("source_author")
    if author:
        lines.append(f"- 作者：{author}")
    source_url = record.get("source_url")
    if source_url:
        lines.append(f"- 来源：{source_url}")
    published_at = record.get("published_at")
    if published_at:
        lines.append(f"- 发布时间：{published_at}")
    tags = [str(tag).strip() for tag in record.get("tags", []) if str(tag).strip()]
    if tags:
        lines.append(f"- 标签：{'、'.join(tags)}")
    introduction = record.get("introduction")
    if introduction:
        lines.append(f"- 简介：{introduction}")
    analyzed_at = record.get("analyzed_at")
    if analyzed_at:
        lines.append(f"- 分析时间：{analyzed_at}")
    lines.extend(["", "---", "", body.strip(), ""])
    return "\n".join(lines)


def safe_slug(value: str, *, fallback: str = "untitled") -> str:
    normalized = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", value.strip()).strip("-")
    return normalized[:96] or fallback


def _datetime_value(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _frontmatter_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'
