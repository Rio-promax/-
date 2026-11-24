"""Read pasted text and text-based local files."""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.adapters.sources.prepared import PreparedSource
from app.domain.models import ContentKind
from app.knowledge.transcript import transcript_from_subtitle, transcript_from_text

TEXT_SUFFIXES = frozenset({".txt", ".md", ".markdown", ".srt", ".vtt"})
SUBTITLE_SUFFIXES = frozenset({".srt", ".vtt"})


class LocalTextError(ValueError):
    pass


def import_pasted_text(text: str, *, title: str | None, language: str | None) -> PreparedSource:
    normalized = text.strip()
    if not normalized:
        raise LocalTextError("粘贴的内容不能为空")
    return PreparedSource(
        kind=ContentKind.ARTICLE,
        title=(title or "未命名文本").strip() or "未命名文本",
        transcript=transcript_from_text(normalized, language=language),
        content_hash=_text_hash(normalized),
        source_path=None,
        source_url=None,
        acquisition_method="pasted_text",
    )


def import_text_file(path: Path, *, title: str | None, language: str | None) -> PreparedSource:
    if not path.is_file():
        raise LocalTextError("找不到本地文件")
    if path.suffix.lower() not in TEXT_SUFFIXES:
        raise LocalTextError("当前仅支持 TXT、Markdown、SRT 和 VTT 文件")

    content = _read_text(path)
    subtitle = path.suffix.lower() in SUBTITLE_SUFFIXES
    transcript = (
        transcript_from_subtitle(content, language=language)
        if subtitle
        else transcript_from_text(content, language=language)
    )
    return PreparedSource(
        kind=ContentKind.VIDEO if subtitle else ContentKind.ARTICLE,
        title=(title or path.stem).strip() or path.stem,
        transcript=transcript,
        content_hash=_text_hash(content),
        source_path=str(path.resolve()),
        source_url=path.resolve().as_uri(),
        acquisition_method="local_file",
        duration_seconds=transcript.segments[-1].end_seconds if subtitle else None,
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return path.read_text(encoding="gb18030")


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
