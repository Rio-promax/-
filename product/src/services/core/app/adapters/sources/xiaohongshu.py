"""Normalize one Xiaohongshu note read from the embedded browser."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse

from app.adapters.sources.prepared import PreparedSource
from app.domain.models import ContentKind, SourcePlatform
from app.knowledge.transcript import transcript_from_text


class XiaohongshuSourceError(ValueError):
    pass


def prepare_xhs_note(
    *,
    url: str,
    title: str,
    author: str | None,
    text: str,
    thumbnail_url: str | None = None,
    language: str | None = None,
) -> PreparedSource:
    source_url = (url or "").strip()
    parsed = urlparse(source_url)
    if parsed.scheme != "https" or parsed.hostname not in {
        "www.xiaohongshu.com",
        "xiaohongshu.com",
    }:
        raise XiaohongshuSourceError("小红书笔记链接无效")
    note_id = re.sub(r"^/explore/", "", parsed.path).strip("/")
    if not re.fullmatch(r"[0-9a-zA-Z]{10,40}", note_id or ""):
        raise XiaohongshuSourceError("小红书笔记链接无效")
    normalized_text = (text or "").strip()
    if not normalized_text:
        raise XiaohongshuSourceError("小红书笔记正文为空")
    normalized_title = (title or "").strip() or normalized_text.splitlines()[0][:200]
    canonical_url = f"https://www.xiaohongshu.com/explore/{note_id}"
    return PreparedSource(
        kind=ContentKind.ARTICLE,
        title=normalized_title,
        transcript=transcript_from_text(normalized_text, language=language),
        content_hash=hashlib.sha256(normalized_text.encode("utf-8")).hexdigest(),
        source_path=None,
        source_url=canonical_url,
        acquisition_method="xiaohongshu_embedded_browser",
        platform=SourcePlatform.XIAOHONGSHU,
        author=(author or "").strip() or None,
        thumbnail_url=(thumbnail_url or "").strip() or None,
    )
