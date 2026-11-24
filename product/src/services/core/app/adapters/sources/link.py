"""Read legally accessible public text from supported platform links."""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import re
import shutil
import socket
import ssl
import time
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from app.adapters.sources.classify import (
    classify_source_type as classify_source_type_for,
    is_collection_url as classify_is_collection_url,
)
from app.adapters.sources.network_errors import is_transient_network_error
from app.adapters.sources.prepared import PreparedSource
from app.domain.models import ContentKind, SourcePlatform, Transcript, TranscriptSegment
from app.knowledge.transcript import transcript_from_text

MAX_PAGE_BYTES = 2_000_000
MIN_TEXT_CHARS = 40
_IGNORED_TAGS = frozenset({"script", "style", "svg", "noscript", "template"})
logger = logging.getLogger(__name__)
_TRANSIENT_RETRIES = 2


class LinkImportError(ValueError):
    def __init__(self, message: str, *, connection_status: str | None = None) -> None:
        super().__init__(message)
        self.connection_status = connection_status


def _thumbnail_url(raw: object, base_url: str) -> str | None:
    """Return a usable public cover URL from page metadata or platform state."""

    value = str(raw or "").strip()
    if not value:
        return None
    candidate = urljoin(base_url, value)
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if parsed.scheme == "http":
        candidate = urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, parsed.fragment))
    return candidate


@dataclass(frozen=True, slots=True)
class PublicPage:
    final_url: str
    html: str


def prepare_link_import(
    *,
    url: str,
    title: str | None,
    language: str | None,
    bilibili_cookie: str | None = None,
    asr_configured: bool = False,
) -> PreparedSource:
    """Prepare one source and keep the original single-video contract."""

    sources = prepare_link_imports(
        url=url,
        title=title,
        language=language,
        bilibili_cookie=bilibili_cookie,
        asr_configured=asr_configured,
    )
    if len(sources) != 1:
        raise LinkImportError("该链接包含多个 P 视频，请使用支持多 P 的批量导入入口")
    return sources[0]


def prepare_link_imports(
    *,
    url: str,
    title: str | None,
    language: str | None,
    bilibili_cookie: str | None = None,
    asr_configured: bool = False,
    page_number: int | None = None,
) -> list[PreparedSource]:
    """Prepare every independently summarizable video represented by one link."""

    input_url = _normalize_input_url(url)
    platform = detect_platform(input_url)
    if platform is None:
        raise LinkImportError("目前仅支持 Bilibili、YouTube、知乎、小红书、微信公众号、抖音和普通网页链接")
    if _is_collection_url(input_url, platform):
        raise LinkImportError(_collection_url_hint(input_url, platform))

    page = fetch_public_page(input_url)
    final_platform = detect_platform(page.final_url)
    if final_platform is not platform:
        raise LinkImportError("链接跳转后不属于原平台，无法安全读取")
    if (
        platform is SourcePlatform.WEB
        and urlparse(input_url).hostname != urlparse(page.final_url).hostname
    ):
        raise LinkImportError("普通网页链接跳转后不属于原站点，无法安全读取")
    if _is_collection_url(page.final_url, platform):
        raise LinkImportError(_collection_url_hint(page.final_url, platform))
    if platform is SourcePlatform.BILIBILI:
        redirected_page_number = None
        for source_url in (page.final_url, input_url):
            page_query = parse_qsl(urlsplit(source_url).query, keep_blank_values=True)
            requested_page = next(
                (value for key, value in page_query if key.lower() == "p"), None
            )
            try:
                candidate_page_number = int(requested_page) if requested_page is not None else None
            except ValueError:
                candidate_page_number = None
            if candidate_page_number is not None and candidate_page_number >= 1:
                redirected_page_number = candidate_page_number
                break
        if redirected_page_number is not None:
            page_number = redirected_page_number

    parser = _PublicPageParser()
    parser.feed(page.html)
    parser.close()
    canonical_url = _canonical_url(parser.canonical_url, page.final_url, platform)
    text = _readable_text(parser)
    material = (
        _bilibili_video_material(parser, page.html, base_url=page.final_url)
        if platform is SourcePlatform.BILIBILI
        else None
    )
    if material is not None:
        # 平台结构化材料优先：真实标题、作者和简介，而不是整页导航文字。
        text = material.text or text

    if platform is SourcePlatform.BILIBILI and material is not None and len(material.pages) > 1:
        return _prepare_bilibili_page_sources(
            canonical_url=canonical_url,
            parser=parser,
            html=page.html,
            text=text,
            material=material,
            title=title,
            bilibili_cookie=bilibili_cookie,
            asr_configured=asr_configured,
            page_number=page_number,
        )

    transcript: Transcript | None = None
    source_note: str | None = None
    audio_path: str | None = None
    audio_is_temp = False
    download_seconds: float | None = None
    is_bilibili_text = platform is SourcePlatform.BILIBILI and _is_bilibili_text_url(input_url)
    if platform is SourcePlatform.BILIBILI and not is_bilibili_text:
        subtitle = _bilibili_subtitle(
            parser,
            page.html,
            bilibili_cookie=bilibili_cookie,
            asr_configured=asr_configured,
        )
        if subtitle is not None:
            transcript, source_note = subtitle
        elif asr_configured:
            audio = _bilibili_audio(
                canonical_url,
                cookie=bilibili_cookie,
            )
            if audio is not None:
                audio_path, source_note, download_seconds = audio
                audio_is_temp = True
    if transcript is None and audio_path is None:
        if platform in _VIDEO_PLATFORMS and not is_bilibili_text:
            raise LinkImportError(_video_recognition_failure(platform))
        if len(text) < MIN_TEXT_CHARS:
            raise LinkImportError(
                "链接已识别，但网页没有返回足够的公开正文，未生成不完整总结"
            )
        transcript = transcript_from_text(
            text, language=language, source_kind="public_page_text"
        )

    resolved_title = (
        title or (material.title if material else None)
        or _first_metadata(parser, "og:title", "twitter:title") or parser.title
    ).strip()
    if not resolved_title:
        resolved_title = _platform_label(platform) + "内容"
    author = (material.author if material else None) or _first_metadata(
        parser, "article:author", "author"
    )
    kind = (
        ContentKind.VIDEO
        if platform in _VIDEO_PLATFORMS and not is_bilibili_text
        else ContentKind.ARTICLE
    )
    if source_note is None:
        source_note = (
            "已读取公开视频页的标题、简介与标签；未获得字幕时，摘要只覆盖页面文字。"
            if material is not None
            else (
                "已读取公开视频页可见文字；未获得字幕时，摘要只覆盖页面文字。"
                if kind is ContentKind.VIDEO
                else "已读取公开页面可见文字。"
            )
        )
    return [PreparedSource(
        kind=kind,
        title=resolved_title,
        transcript=transcript,
        content_hash=_content_hash(canonical_url, text),
        source_path=None,
        source_url=canonical_url,
        acquisition_method="public_page",
        platform=platform,
        author=author,
        published_at=(
            material.published_at
            if material is not None
            else _parse_published_at(
                _first_metadata(parser, "article:published_time", "datePublished", "pubdate")
            )
        ),
        duration_seconds=material.duration_seconds if material else None,
        thumbnail_url=_thumbnail_url(
            material.thumbnail_url
            if material is not None and material.thumbnail_url
            else _first_metadata(parser, "og:image", "twitter:image"),
            page.final_url,
        ),
        source_note=source_note,
        audio_path=audio_path,
        audio_is_temp=audio_is_temp,
        download_seconds=download_seconds,
    )]


def preview_link_import(url: str) -> list[dict[str, object]]:
    """Read title and cover metadata only; never fetch subtitles or audio."""

    input_url = _normalize_input_url(url)
    platform = detect_platform(input_url)
    if platform is None:
        raise LinkImportError("暂不支持此链接")
    if _is_collection_url(input_url, platform):
        raise LinkImportError(_collection_url_hint(input_url, platform))
    page = fetch_public_page(input_url)
    if detect_platform(page.final_url) is not platform:
        raise LinkImportError("链接跳转后不属于原平台，无法安全读取")
    parser = _PublicPageParser()
    parser.feed(page.html)
    parser.close()
    canonical_url = _canonical_url(parser.canonical_url, page.final_url, platform)
    material = (
        _bilibili_video_material(parser, page.html, base_url=page.final_url)
        if platform is SourcePlatform.BILIBILI
        else None
    )
    title = (material.title if material else None) or _first_metadata(
        parser, "og:title", "twitter:title"
    ) or parser.title or "未命名内容"
    author = (material.author if material else None) or _first_metadata(
        parser, "article:author", "author"
    )
    thumbnail_url = _thumbnail_url(
        material.thumbnail_url
        if material and material.thumbnail_url
        else _first_metadata(parser, "og:image", "twitter:image"),
        page.final_url,
    )
    duration = material.duration_seconds if material else None
    if platform is SourcePlatform.BILIBILI:
        page_number = None
        for source_url in (page.final_url, input_url):
            page_query = parse_qsl(urlsplit(source_url).query, keep_blank_values=True)
            requested_page = next(
                (value for key, value in page_query if key.lower() == "p"), None
            )
            try:
                page_number = int(requested_page) if requested_page is not None else None
            except ValueError:
                page_number = None
            if page_number is not None and page_number >= 1:
                break
        if material and len(material.pages) > 1:
            pages = [item for item in material.pages if page_number is None or item.number == page_number]
            if not pages:
                raise LinkImportError("无法定位需要预览的 P 视频")
            return [
                {
                    "title": f"{title} - {item.part or f'P{item.number}'}",
                    "source_url": _bilibili_page_url(canonical_url, item.number),
                    "platform": platform.value,
                    "author": author,
                    "thumbnail_url": thumbnail_url,
                    "duration_seconds": item.duration_seconds or duration,
                    "page_number": item.number,
                }
                for item in pages
            ]
        if material and material.pages:
            page = material.pages[0]
            if page_number is not None and page.number != page_number:
                raise LinkImportError("无法定位需要预览的 P 视频")
            return [{
                "title": title,
                "source_url": _bilibili_page_url(canonical_url, page.number),
                "platform": platform.value,
                "author": author,
                "thumbnail_url": thumbnail_url,
                "duration_seconds": page.duration_seconds or duration,
                "page_number": page.number,
            }]
        selected_page = page_number or 1
        return [{
            "title": title,
            "source_url": _bilibili_page_url(canonical_url, selected_page),
            "platform": platform.value,
            "author": author,
            "thumbnail_url": thumbnail_url,
            "duration_seconds": duration,
            "page_number": selected_page,
        }]
    return [{
        "title": title,
        "source_url": canonical_url,
        "platform": platform.value,
        "author": author,
        "thumbnail_url": thumbnail_url,
        "duration_seconds": duration,
        "page_number": None,
    }]


def _prepare_bilibili_page_sources(
    *,
    canonical_url: str,
    parser: "_PublicPageParser",
    html: str,
    text: str,
    material: "_BilibiliMaterial",
    title: str | None,
    bilibili_cookie: str | None,
    asr_configured: bool,
    page_number: int | None = None,
) -> list[PreparedSource]:
    base_title = (
        title or material.title or _first_metadata(parser, "og:title", "twitter:title") or parser.title
    ).strip()
    if not base_title:
        base_title = "B站视频"
    author = material.author or _first_metadata(parser, "article:author", "author")
    sources: list[PreparedSource] = []
    pages = [page for page in material.pages if page_number is None or page.number == page_number]
    if not pages:
        raise LinkImportError("无法定位需要处理的 P 视频")
    try:
        for page in pages:
            page_url = _bilibili_page_url(canonical_url, page.number)
            part_title = page.part or f"P{page.number}"
            resolved_title = f"{base_title} - {part_title}"
            subtitle = _bilibili_subtitle(
                parser,
                html,
                bilibili_cookie=bilibili_cookie,
                asr_configured=asr_configured,
                page=page,
            )
            transcript: Transcript | None = None
            source_note: str | None = None
            audio_path: str | None = None
            audio_is_temp = False
            download_seconds: float | None = None
            if subtitle is not None:
                transcript, source_note = subtitle
            elif asr_configured:
                audio = _bilibili_audio(page_url, cookie=bilibili_cookie)
                if audio is not None:
                    audio_path, source_note, download_seconds = audio
                    audio_is_temp = True
                    source_note = f"第 {page.number} P：{source_note}"
            if transcript is None and audio_path is None:
                raise LinkImportError(
                    f"无法识别视频内容：第 {page.number} P（{part_title}）没有可读取的字幕，"
                    "且没有可用的语音识别（ASR）"
                )
            sources.append(
                PreparedSource(
                    kind=ContentKind.VIDEO,
                    title=resolved_title,
                    transcript=transcript,
                    content_hash=_content_hash(page_url, text),
                    source_path=None,
                    source_url=page_url,
                    acquisition_method="public_page",
                    platform=SourcePlatform.BILIBILI,
                    author=author,
                    published_at=material.published_at,
                    duration_seconds=(
                        page.duration_seconds
                        if page.duration_seconds is not None
                        else material.duration_seconds
                    ),
                    thumbnail_url=_thumbnail_url(material.thumbnail_url, page_url),
                    source_note=source_note,
                    audio_path=audio_path,
                    audio_is_temp=audio_is_temp,
                    download_seconds=download_seconds,
                )
            )
    except Exception:
        for source in sources:
            if source.audio_is_temp and source.audio_path:
                _cleanup_temporary_audio(source.audio_path)
        raise
    return sources
def detect_platform(url: str) -> SourcePlatform | None:
    host = urlparse(url).hostname
    if not host:
        return None
    normalized = host.lower()
    if (
        normalized == "b23.tv"
        or normalized.endswith(".bilibili.com")
        or normalized == "bilibili.com"
    ):
        return SourcePlatform.BILIBILI
    if normalized == "youtu.be" or normalized.endswith(".youtube.com") or normalized == "youtube.com":
        return SourcePlatform.YOUTUBE
    if normalized == "zhihu.com" or normalized.endswith(".zhihu.com"):
        return SourcePlatform.ZHIHU
    if normalized == "xhslink.com" or normalized.endswith(".xiaohongshu.com"):
        return SourcePlatform.XIAOHONGSHU
    if (
        normalized == "douyin.com"
        or normalized.endswith(".douyin.com")
        or normalized.endswith(".iesdouyin.com")
    ):
        return SourcePlatform.DOUYIN
    if normalized == "mp.weixin.qq.com" or normalized.endswith(".weixin.qq.com"):
        return SourcePlatform.WECHAT

    # 普通网页：任何可访问的 http(s) 页面都进入统一公开页文本流程
    return SourcePlatform.WEB


def fetch_public_page(url: str) -> PublicPage:
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "gzip, deflate",
            "User-Agent": "ContentKnowledgeLibrary/0.1",
        },
    )
    for attempt in range(_TRANSIENT_RETRIES + 1):
        try:
            with urlopen(request, timeout=12) as response:
                content_type = response.headers.get("Content-Type", "")
                if content_type and "html" not in content_type.lower():
                    raise LinkImportError("链接没有返回网页内容，无法读取")
                payload = response.read(MAX_PAGE_BYTES + 1)
                if len(payload) > MAX_PAGE_BYTES:
                    raise LinkImportError("网页内容过大，暂时无法读取")
                decoded = _decode_html(_decompress(payload, response.headers), content_type)
                return PublicPage(response.geturl(), decoded)
        except HTTPError as error:
            if error.code in {401, 403}:
                raise LinkImportError(
                    "平台要求登录或拒绝公开读取，请先完成该平台授权登录后重试"
                ) from error
            if error.code == 404:
                raise LinkImportError("找不到该链接对应的内容") from error
            raise LinkImportError(f"平台读取失败（HTTP {error.code}）") from error
        except LinkImportError:
            raise
        except (gzip.BadGzipFile, EOFError, OSError, zlib.error) as error:
            if attempt >= _TRANSIENT_RETRIES:
                raise LinkImportError("网页响应不完整，请稍后重试") from error
            logger.warning(
                "retrying transient public page response url=%s attempt=%s reason=%s",
                url,
                attempt + 1,
                type(error).__name__,
            )
            time.sleep(0.15 * (attempt + 1))
        except (URLError, TimeoutError, socket.timeout, ConnectionResetError, ssl.SSLError) as error:
            if not is_transient_network_error(error) or attempt >= _TRANSIENT_RETRIES:
                raise LinkImportError("无法连接到该平台，请检查网络或稍后重试") from error
            logger.warning(
                "retrying transient public page request url=%s attempt=%s reason=%s",
                url,
                attempt + 1,
                type(error).__name__,
            )
            time.sleep(0.15 * (attempt + 1))


def _decompress(payload: bytes, headers) -> bytes:
    """Bilibili and other CDNs compress responses even for small requests."""

    encoding = (headers.get("Content-Encoding") or "").lower()
    if "gzip" in encoding:
        return gzip.decompress(payload)
    if "deflate" in encoding:
        try:
            return zlib.decompress(payload)
        except zlib.error:
            return zlib.decompress(payload, -zlib.MAX_WBITS)
    return payload


def _normalize_input_url(value: str) -> str:
    normalized = value.strip()
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise LinkImportError("请输入完整的 http 或 https 链接")
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    if host.endswith("bilibili.com") and "watchlater" in path:
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        candidate = str(query.get("bvid") or query.get("bv_id") or "").strip()
        if not candidate:
            match = re.search(r"(?:BV[0-9A-Za-z]{10}|av\d+)", parsed.query, re.IGNORECASE)
            candidate = match.group(0) if match else ""
        if candidate:
            return f"https://www.bilibili.com/video/{candidate}"
    return normalized


def _is_bilibili_text_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    return host == "t.bilibili.com" or path.startswith("/opus/") or path.startswith("/read/cv")

def _is_collection_url(url: str, platform: SourcePlatform) -> bool:
    """转发统一分类器（P3）：签名保持不变，调用方无需修改。"""
    return classify_is_collection_url(url, platform)


def classify_source_type(url: str, platform: SourcePlatform | None = None) -> str:
    """转发统一分类器（P3）：B站 既有子类型与新平台 §5.1 值见 classify.py。"""
    return classify_source_type_for(url, platform or detect_platform(url))


def _collection_url_hint(url: str, platform: SourcePlatform) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    if platform is SourcePlatform.BILIBILI:
        if "watchlater" in path:
            return (
                "这是B站“稍后再看”列表。查询后可扫描其中的视频并选择要导入的内容。"
            )
        if "/favlist" in path:
            return "这是B站收藏夹。查询后可扫描其中的视频并选择要导入的内容。"
        if "/medialist/detail/" in path:
            return "这是B站视频合集，不是单条内容；当前版本暂不支持直接扫描整个合集，请粘贴具体视频链接"
        if classify_source_type_for(url, SourcePlatform.BILIBILI) == "collection":
            return (
                "这是B站的合集，不是单条内容。确认后只扫描该合集内的视频并批量导入，"
                "不会读取该 UP 主的其它投稿。"
            )
        if host.startswith("space."):
            return (
                "这是B站UP主主页，不是单条内容。确认后可预览该 UP 主的公开投稿并批量导入，"
                "也可以直接粘贴具体视频链接。"
            )
    return "这是博主页或收藏列表，不是单条内容。请粘贴主页链接预览候选内容，或先粘贴单条内容链接"


_VIDEO_PLATFORMS = frozenset(
    {SourcePlatform.BILIBILI, SourcePlatform.YOUTUBE, SourcePlatform.DOUYIN}
)


def _video_recognition_failure(platform: SourcePlatform) -> str:
    """Explain why the video content could not be recognized, never fake it."""

    if platform is SourcePlatform.BILIBILI:
        return (
            "无法识别视频内容：该视频没有可读取的公开字幕，且没有配置语音识别（ASR）。"
            "请在设置页配置 ASR 后重试。"
        )
    if platform is SourcePlatform.YOUTUBE:
        return (
            "无法识别视频内容：当前适配器无法获取该视频的字幕或音频转写。"
            "请使用可公开获取字幕的视频，或接入 ASR 后重试。"
        )
    return (
        "无法识别视频内容：当前适配器无法获取该视频的字幕或音频转写。"
        "请使用可公开获取字幕的视频，或接入 ASR 后重试。"
    )


def _bilibili_subtitle(
    parser: "_PublicPageParser",
    html: str,
    *,
    bilibili_cookie: str | None,
    asr_configured: bool,
    page: "_BilibiliPage | None" = None,
) -> tuple[Transcript, str] | None:
    """Fetch a subtitle for the requested Bilibili page."""

    del parser
    state = _extract_initial_state(html)
    if state is None:
        return None
    video_data = state.get("videoData")
    if not isinstance(video_data, dict):
        return None
    if page is None:
        bvid = str(video_data.get("bvid") or state.get("bvid") or "").strip()
        cid = video_data.get("cid")
        if not cid:
            cid_map = state.get("cidMap")
            if isinstance(cid_map, dict) and cid_map:
                first = next(iter(cid_map.values()), None)
                cid = first.get("cid") if isinstance(first, dict) else None
        try:
            cid_value = int(cid)
        except (TypeError, ValueError):
            return None
    else:
        bvid = page.bvid
        cid_value = page.cid
    if not bvid or not cid_value:
        return None

    from app.adapters.sources.bilibili import fetch_video_subtitle

    try:
        result = fetch_video_subtitle(bvid, cid_value, cookie=bilibili_cookie)
    except LinkImportError as error:
        # 有产品登录会话且已配置 ASR 时，继续走 yt-dlp 音频路径。
        if bilibili_cookie and asr_configured:
            return None
        raise LinkImportError(
            f"无法识别视频内容：{error}",
            connection_status=error.connection_status,
        ) from error
    if result is None:
        return None
    language, cues = result
    segments = tuple(
        TranscriptSegment(cue.start_seconds, cue.end_seconds, cue.text) for cue in cues
    )
    transcript = Transcript(language, "bilibili_subtitle", "bilibili", segments)
    prefix = f"第 {page.number} P " if page is not None else ""
    return transcript, f"已获取{prefix}视频字幕（{language}），按时间轴总结。"


def _bilibili_audio(
    url: str,
    *,
    cookie: str | None,
) -> tuple[str, str, float] | None:
    """Download the audio stream for ASR transcription when no subtitle exists.

    Returns (temp audio path, source note) or raises LinkImportError with the
    recognition failure reason. Callers never fall back to page text.
    """

    from app.adapters.sources.bilibili import download_bilibili_audio

    started = time.perf_counter()
    try:
        audio_path = download_bilibili_audio(url, cookie=cookie)
    except LinkImportError as error:
        raise LinkImportError(
            f"无法识别视频内容：{error}",
            connection_status=error.connection_status,
        ) from error
    return (
        str(audio_path),
        "已通过 yt-dlp 获取临时音频，将通过语音识别（ASR）转写后总结。",
        max(0.0, time.perf_counter() - started),
    )


@dataclass(frozen=True, slots=True)
class _BilibiliPage:
    bvid: str
    number: int
    cid: int
    part: str
    duration_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class _BilibiliMaterial:
    title: str | None
    author: str | None
    duration_seconds: float | None
    published_at: datetime | None
    text: str
    bvid: str | None = None
    thumbnail_url: str | None = None
    pages: tuple[_BilibiliPage, ...] = ()


def _bilibili_video_material(
    parser: "_PublicPageParser",
    html: str,
    *,
    base_url: str | None = None,
) -> _BilibiliMaterial | None:
    """Prefer structured Bilibili state and retain every page/cid."""

    state = _extract_initial_state(html)
    if state is None:
        return None
    video_data = state.get("videoData") or {}
    if not isinstance(video_data, dict) or not video_data.get("title"):
        return None
    up_data = state.get("upData") or {}
    parts: list[str] = []
    description = str(video_data.get("desc") or "").strip()
    if description:
        parts.append(description)
    sign = str(up_data.get("sign") or "").strip()
    if sign:
        parts.append(f"作者简介：{sign}")
    tags = state.get("tags")
    if isinstance(tags, list):
        names = [
            str(tag.get("tag_name", "")).strip()
            for tag in tags
            if isinstance(tag, dict) and tag.get("tag_name")
        ]
        if names:
            parts.append("标签：" + "、".join(names))
    stat = video_data.get("stat")
    if isinstance(stat, dict):
        counts = [
            (key, label)
            for key, label in (
                ("view", "播放"),
                ("like", "点赞"),
                ("favorite", "收藏"),
                ("coin", "投币"),
                ("danmaku", "弹幕"),
            )
            if stat.get(key) not in (None, "", 0)
        ]
        if counts:
            parts.append("，".join(f"{label} {stat[key]}" for key, label in counts))
    text = "\n\n".join(_deduplicate(parts)).strip()
    meta_description = _first_metadata(parser, "og:description", "description")
    if len(text) < MIN_TEXT_CHARS and meta_description:
        text = meta_description
    title = str(video_data.get("title")).strip()
    duration_seconds = _duration_seconds(video_data.get("duration"))
    bvid = str(video_data.get("bvid") or state.get("bvid") or "").strip() or None
    pages = _extract_bilibili_pages(
        state,
        video_data,
        bvid=bvid,
        title=title,
        duration_seconds=duration_seconds,
    )
    return _BilibiliMaterial(
        title=title,
        author=_owner_name(video_data),
        duration_seconds=duration_seconds,
        published_at=_parse_published_at(video_data.get("pubdate") or video_data.get("ctime")),
        text=text,
        bvid=bvid,
        thumbnail_url=_thumbnail_url(
            video_data.get("pic"), base_url or "https://www.bilibili.com"
        ),
        pages=pages,
    )


def _extract_bilibili_pages(
    state: dict,
    video_data: dict,
    *,
    bvid: str | None,
    title: str,
    duration_seconds: float | None,
) -> tuple[_BilibiliPage, ...]:
    if not bvid:
        return ()
    raw_pages = video_data.get("pages")
    if not isinstance(raw_pages, list):
        raw_pages = state.get("pages")
    if not isinstance(raw_pages, list):
        raw_pages = []
        cid_map = state.get("cidMap")
        if isinstance(cid_map, dict):
            for key, value in cid_map.items():
                if not isinstance(value, dict):
                    continue
                item = dict(value)
                item.setdefault("cid", key)
                raw_pages.append(item)
    if not raw_pages:
        raw_pages = [
            {
                "page": 1,
                "cid": video_data.get("cid"),
                "part": title,
                "duration": duration_seconds,
            }
        ]

    pages: list[_BilibiliPage] = []
    seen_cids: set[int] = set()
    for index, raw_page in enumerate(raw_pages, start=1):
        if not isinstance(raw_page, dict):
            continue
        try:
            cid = int(raw_page.get("cid"))
        except (TypeError, ValueError):
            continue
        if cid <= 0 or cid in seen_cids:
            continue
        try:
            number = int(raw_page.get("page") or index)
        except (TypeError, ValueError):
            number = index
        if number <= 0:
            number = index
        part = str(raw_page.get("part") or raw_page.get("title") or "").strip()
        pages.append(
            _BilibiliPage(
                bvid=bvid,
                number=number,
                cid=cid,
                part=part,
                duration_seconds=_duration_seconds(raw_page.get("duration")),
            )
        )
        seen_cids.add(cid)
    return tuple(sorted(pages, key=lambda item: item.number))


def _duration_seconds(value) -> float | None:
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return None
    return duration if duration > 0 else None


def _owner_name(video_data: dict) -> str | None:
    owner = video_data.get("owner")
    if isinstance(owner, dict):
        name = str(owner.get("name") or "").strip()
        if name:
            return name
    return None


def _extract_initial_state(html: str) -> dict | None:
    marker = "window.__INITIAL_STATE__="
    position = html.find(marker)
    if position < 0:
        return None
    start = position + len(marker)
    if html[start : start + 1] != "{":
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(html[start:])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _canonical_url(value: str | None, fallback: str, platform: SourcePlatform) -> str:
    if not value:
        return fallback
    resolved = urljoin(fallback, value)
    return resolved if detect_platform(resolved) is platform else fallback


def _bilibili_page_url(base_url: str, page_number: int) -> str:
    parsed = urlsplit(base_url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() != "p"
    ]
    query.append(("p", str(page_number)))
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )

def _readable_text(parser: "_PublicPageParser") -> str:
    parts = _deduplicate(parser.text_parts)
    description = _first_metadata(parser, "og:description", "description", "twitter:description")
    if description and description not in parts:
        parts.append(description)
    return "\n\n".join(parts).strip()


def _first_metadata(parser: "_PublicPageParser", *keys: str) -> str | None:
    for key in keys:
        value = parser.metadata.get(key)
        if value:
            return value
    return None


def _deduplicate(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = re.sub(r"\s+", " ", value).strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _decode_html(payload: bytes, content_type: str) -> str:
    match = re.search(r"charset=([\w-]+)", content_type, flags=re.IGNORECASE)
    encodings = [match.group(1)] if match else []
    encodings.extend(["utf-8", "gb18030"])
    for encoding in dict.fromkeys(encodings):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="replace")



def _parse_published_at(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            return datetime.fromtimestamp(float(value), UTC)
        normalized = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (TypeError, ValueError, OverflowError):
        return None

def _content_hash(url: str, text: str) -> str:
    return hashlib.sha256(f"{url}\n{text}".encode("utf-8")).hexdigest()


def _cleanup_temporary_audio(audio_path: str) -> None:
    try:
        path = Path(audio_path)
        parent = path.parent
        if parent.is_dir() and parent.name.startswith("knowledge-asr-"):
            shutil.rmtree(parent, ignore_errors=True)
        elif path.is_file():
            path.unlink()
    except OSError:
        pass

def _platform_label(platform: SourcePlatform) -> str:
    return {
        SourcePlatform.BILIBILI: "Bilibili",
        SourcePlatform.YOUTUBE: "YouTube",
        SourcePlatform.ZHIHU: "知乎",
        SourcePlatform.XIAOHONGSHU: "小红书",
        SourcePlatform.WECHAT: "微信公众号",
        SourcePlatform.DOUYIN: "抖音",
        SourcePlatform.WEB: "网页",
    }[platform]


class _PublicPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.metadata: dict[str, str] = {}
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.canonical_url: str | None = None
        self._ignored_depth = 0
        self._in_title = False

    @property
    def title(self) -> str:
        return " ".join(self.title_parts).strip()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        attributes = {key.lower(): value for key, value in attrs if value is not None}
        if normalized_tag in _IGNORED_TAGS:
            self._ignored_depth += 1
        if normalized_tag == "title":
            self._in_title = True
        if normalized_tag == "meta":
            key = attributes.get("property") or attributes.get("name")
            content = attributes.get("content")
            if key and content:
                self.metadata.setdefault(key.lower(), content.strip())
        if normalized_tag == "link" and attributes.get("rel", "").lower() == "canonical":
            self.canonical_url = attributes.get("href")

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if normalized_tag == "title":
            self._in_title = False
        if normalized_tag in _IGNORED_TAGS and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        value = re.sub(r"\s+", " ", data).strip()
        if not value:
            return
        if self._in_title:
            self.title_parts.append(value)
        if not self._ignored_depth:
            self.text_parts.append(value)
