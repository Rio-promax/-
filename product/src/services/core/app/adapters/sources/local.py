"""Choose the appropriate local-file reader for one import request."""

from __future__ import annotations

from pathlib import Path

from app.adapters.sources.local_media import MEDIA_SUFFIXES, LocalMediaError, import_media_file
from app.adapters.sources.local_text import (
    TEXT_SUFFIXES,
    LocalTextError,
    import_pasted_text,
    import_text_file,
)
from app.adapters.sources.prepared import PreparedSource


class LocalImportError(ValueError):
    pass


def prepare_local_import(
    *,
    source_path: str | None,
    text: str | None,
    title: str | None,
    language: str | None,
) -> PreparedSource:
    if text and text.strip():
        return import_pasted_text(text, title=title, language=language)
    if not source_path or not source_path.strip():
        raise LocalImportError("请粘贴内容或填写本地文件路径")

    path = Path(source_path.strip()).expanduser()
    try:
        if path.suffix.lower() in TEXT_SUFFIXES:
            return import_text_file(path, title=title, language=language)
        if path.suffix.lower() in MEDIA_SUFFIXES:
            return import_media_file(path, title=title, language=language)
    except (LocalTextError, LocalMediaError) as error:
        raise LocalImportError(str(error)) from error
    raise LocalImportError("当前仅支持 TXT、Markdown、SRT、VTT 和常见音视频文件")
