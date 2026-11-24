"""Normalize one user-selected Zhihu answer or article for the existing workflow."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse

from app.adapters.sources.classify import classify_source_type
from app.adapters.sources.prepared import PreparedSource
from app.domain.models import ContentKind, SourcePlatform
from app.knowledge.transcript import transcript_from_text


class ZhihuSourceError(ValueError):
    pass


def prepare_zhihu_text(
    *,
    url: str,
    title: str,
    author: str | None,
    text: str,
    language: str | None = None,
) -> PreparedSource:
    source_url = url.strip()
    parsed = urlparse(source_url)
    if parsed.scheme != "https" or parsed.hostname not in {"www.zhihu.com", "zhuanlan.zhihu.com"}:
        raise ZhihuSourceError("知乎原文链接无效")
    source_type = classify_source_type(source_url, SourcePlatform.ZHIHU)
    if source_type not in {"answer", "article"}:
        raise ZhihuSourceError("仅支持知乎回答或文章")
    if source_type == "answer" and not re.fullmatch(r"/question/\d+/answer/\d+/?", parsed.path):
        raise ZhihuSourceError("知乎回答链接无效")
    if source_type == "article" and (
        parsed.hostname != "zhuanlan.zhihu.com"
        or not re.fullmatch(r"/p/\d+/?", parsed.path)
    ):
        raise ZhihuSourceError("知乎文章链接无效")
    normalized_text = text.strip()
    normalized_title = title.strip()
    if not normalized_title or not normalized_text:
        raise ZhihuSourceError("知乎原文标题或正文为空")
    return PreparedSource(
        kind=ContentKind.ARTICLE,
        title=normalized_title,
        transcript=transcript_from_text(normalized_text, language=language),
        content_hash=hashlib.sha256(normalized_text.encode("utf-8")).hexdigest(),
        source_path=None,
        source_url=source_url,
        acquisition_method="zhihu_embedded_browser",
        platform=SourcePlatform.ZHIHU,
        author=author.strip() if author and author.strip() else None,
    )
