"""P10 B站图文适配器契约测试：图文/视频互斥、图片原序、OCR 未支持、bilibili.py 零改动。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.adapters.sources.bilibili_opus import (
    BilibiliOpusMaterial,
    build_prepared_source,
    extract_opus_material,
    is_opus_url,
)
from app.domain.models import ContentKind, SourcePlatform


OPUS_HTML = """
<html><head><title>动态详情_哔哩哔哩</title></head><body>
<script>window.__INITIAL_STATE__={"opusData":{"title":"第一篇图文标题","author":{"name":"测试UP主"},"content":{}}};</script>
<img src="https://i0.hdslb.com/bfs/avatar/xx.jpg">
<article>
  <p>这是正文第一段。</p>
  <img src="https://i0.hdslb.com/bfs/article/second.png">
  <p>这是正文第二段。</p>
  <img src="https://i1.hdslb.com/bfs/article/first.jpg">
  <img src="https://i2.hdslb.com/bfs/emote/xx.png">
  <img src="data:image/gif;base64,xxx">
</article>
</body></html>
"""

READ_HTML = """
<html><head><title>专栏</title></head><body>
<script>window.__INITIAL_STATE__={"readInfo":{"title":"专栏标题","author":{"name":"专栏作者"}}};</script>
<img src="https://i0.hdslb.com/bfs/article/cv-one.png">
</body></html>
"""

FALLBACK_HTML = """
<html><head><title>无状态兜底页</title></head><body>
<p>兜底正文。</p>
<img src="https://i0.hdslb.com/bfs/article/fallback.png">
</body></html>
"""


def test_opus_and_video_urls_are_mutually_exclusive() -> None:
    assert is_opus_url("https://www.bilibili.com/opus/864375702372655884")
    assert is_opus_url("https://www.bilibili.com/read/cv12345678")
    assert is_opus_url("https://t.bilibili.com/678901234567890123")
    # 视频链接不是图文
    assert not is_opus_url("https://www.bilibili.com/video/BV1GJ411x7h7")
    assert not is_opus_url("https://b23.tv/abc123")


def test_extract_prefers_state_and_keeps_image_document_order() -> None:
    material = extract_opus_material(OPUS_HTML, "https://www.bilibili.com/opus/864375702372655884")
    assert material is not None
    assert material.title == "第一篇图文标题"
    assert material.author == "测试UP主"
    assert "正文第一段" in material.text
    # 文档序：avatar/emote/data-URI 已过滤，其余保持原序
    assert material.image_urls == (
        "https://i0.hdslb.com/bfs/article/second.png",
        "https://i1.hdslb.com/bfs/article/first.jpg",
    )
    assert material.ocr_supported is False  # P5 冻结：图片文字"未支持"


def test_extract_supports_read_info_shape() -> None:
    material = extract_opus_material(READ_HTML, "https://www.bilibili.com/read/cv12345678")
    assert material is not None
    assert material.title == "专栏标题"
    assert material.author == "专栏作者"
    assert material.image_urls == ("https://i0.hdslb.com/bfs/article/cv-one.png",)


def test_extract_falls_back_to_title_and_body_without_state() -> None:
    material = extract_opus_material(FALLBACK_HTML, "https://www.bilibili.com/opus/1")
    assert material is not None
    assert material.title == "无状态兜底页"
    assert material.image_urls == ("https://i0.hdslb.com/bfs/article/fallback.png",)


def test_empty_page_returns_none() -> None:
    assert extract_opus_material("<html><head></head><body></body></html>", "https://www.bilibili.com/opus/1") is None


def test_build_prepared_source_maps_to_image_kind() -> None:
    material = BilibiliOpusMaterial(
        title="第一篇图文标题",
        author="测试UP主",
        text="正文",
        image_urls=("https://i0.hdslb.com/bfs/article/second.png",),
        canonical_url="https://www.bilibili.com/opus/864375702372655884",
    )
    prepared = build_prepared_source(material)
    assert prepared.kind is ContentKind.IMAGE
    assert prepared.platform is SourcePlatform.BILIBILI
    assert prepared.author == "测试UP主"
    assert prepared.thumbnail_url == "https://i0.hdslb.com/bfs/article/second.png"
    assert prepared.transcript is not None
    # 同一输入哈希稳定（P12 去重锚点）
    again = build_prepared_source(material)
    assert prepared.content_hash == again.content_hash


def test_bilibili_video_module_untouched() -> None:
    # P10 硬约束：bilibili.py 必须保持原样——此处校验其源文件未引入图文逻辑。
    source = Path(__file__).parents[1].joinpath("app", "adapters", "sources", "bilibili.py").read_text(
        encoding="utf-8"
    )
    assert "bilibili_opus" not in source
    assert "opus" not in source.lower()
