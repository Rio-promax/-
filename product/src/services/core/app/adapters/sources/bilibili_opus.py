"""B站 图文（动态 opus / 专栏 read）适配器（P10）。

硬约束：不修改 `app/adapters/sources/bilibili.py`（保护 B站 视频回归）；
本包自测通过后由 I1–I4 整合包接入 link.py/main.py，在此之前不接线、不影响现有路径。

P5（OCR）冻结期间：图片文字识别标"未支持"——本适配器只产出图片 URL 的原序清单，
不调用 OCR、不产出 ocr_attribution（P12 落库时一并决定）。

真实 opus / read 页面 `__INITIAL_STATE__` 的专有键名待 D3 真实样本校准；当前按
opusData / readInfo 两种已知形态尽力解析，并保留 `<title>` + 正文文档序兜底路径。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlparse

from app.adapters.sources.link import (
    _PublicPageParser,
    _extract_initial_state,
    _is_bilibili_text_url,
)
from app.adapters.sources.prepared import PreparedSource
from app.domain.models import ContentKind, SourcePlatform
from app.knowledge.transcript import transcript_from_text

_IMAGE_HOST_SUFFIX = "hdslb.com"
# 头像、表情、装饰图不计入图文图片序列（按路径特征过滤，待真实样本校准）。
_IMAGE_EXCLUDE_MARKERS = ("/avatar", "/emote", "emoticon")


@dataclass(frozen=True, slots=True)
class BilibiliOpusMaterial:
    """一次图文解析产物；image_urls 保持页面文档序。"""

    title: str | None
    author: str | None
    text: str
    image_urls: tuple[str, ...]
    canonical_url: str
    ocr_supported: bool = False  # P5 冻结期间恒 False，验收标"未支持"


class _OpusImageParser(HTMLParser):
    """按文档序收集内容图 <img src>，跳过头像/表情类小图。"""

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self._base_url = base_url
        self.image_urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "img":
            return
        attributes = dict(attrs)
        src = (attributes.get("src") or attributes.get("data-src") or "").strip()
        if not src or src.startswith("data:"):
            return
        host = urlparse(src).hostname or ""
        if not host.endswith(_IMAGE_HOST_SUFFIX):
            return
        lowered = src.lower()
        if any(marker in lowered for marker in _IMAGE_EXCLUDE_MARKERS):
            return
        self.image_urls.append(src)


def is_opus_url(url: str) -> bool:
    """B站 图文链接识别：与视频链接互斥，不互相误判。"""
    return _is_bilibili_text_url(url)


def extract_opus_material(html: str, base_url: str) -> BilibiliOpusMaterial | None:
    parser = _PublicPageParser()
    parser.feed(html)
    parser.close()

    images = _OpusImageParser(base_url)
    images.feed(html)
    images.close()

    state = _extract_initial_state(html)
    title = parser.title
    author = None
    text = " ".join(part.strip() for part in parser.text_parts if part.strip())
    if isinstance(state, dict):
        for key in ("opusData", "readInfo"):
            entry = state.get(key)
            if not isinstance(entry, dict):
                continue
            entry_title = str(entry.get("title") or "").strip()
            if entry_title:
                title = entry_title
            author_entry = entry.get("author")
            if isinstance(author_entry, dict):
                author_name = str(author_entry.get("name") or "").strip()
                if author_name:
                    author = author_name
            break
    if not text and not images and not title:
        return None
    return BilibiliOpusMaterial(
        title=title or None,
        author=author,
        text=text,
        image_urls=tuple(images.image_urls),
        canonical_url=base_url,
    )


def build_prepared_source(
    material: BilibiliOpusMaterial,
    *,
    language: str | None = None,
) -> PreparedSource:
    """转换为统一内容对象（§5.2：image_post → kind=image；OCR 未支持期间无归属信息）。"""
    content_hash = hashlib.sha256(
        f"{material.canonical_url}\n{material.text}".encode("utf-8")
    ).hexdigest()
    return PreparedSource(
        kind=ContentKind.IMAGE,
        title=material.title or "B站图文",
        transcript=transcript_from_text(material.text, language=language) if material.text else None,
        content_hash=content_hash,
        source_path=None,
        source_url=material.canonical_url,
        acquisition_method="adapter",
        platform=SourcePlatform.BILIBILI,
        author=material.author,
        thumbnail_url=material.image_urls[0] if material.image_urls else None,
    )
