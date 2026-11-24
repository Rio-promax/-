"""Bilibili API helpers and product-owned QR login session."""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import socket
import shutil
import ssl
import tempfile
import time
import urllib.parse
import zlib
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlparse
from urllib.request import Request, urlopen

from app.adapters.sources.link import LinkImportError
from app.adapters.sources.network_errors import is_transient_network_error

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
logger = logging.getLogger(__name__)
_TRANSIENT_RETRIES = 2
MAX_VIDEOS_PER_PAGE = 30
MAX_SEASON_ITEMS_PER_PAGE = 30
BILIBILI_SEASON_LIST_URL = (
    "https://api.bilibili.com/x/polymer/web-space/seasons_archives_list"
)
# 设备指纹与 wbi 签名密钥在一轮扫描内复用，避免每页重复请求与指纹漂移。
_BUVID_COOKIE_TTL_SECONDS = 300
_WBI_KEY_TTL_SECONDS = 600
_buvid_cookie_cache: tuple[float, str] | None = None
_wbi_key_cache: tuple[float, str, tuple[str, str]] | None = None
BILIBILI_QR_GENERATE_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
BILIBILI_QR_POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
BILIBILI_QR_EXPIRES_SECONDS = 180

# Standard wbi mixin-key permutation used by the official web client.
_MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
]


@dataclass(frozen=True, slots=True)
class SpaceVideo:
    bvid: str
    title: str
    url: str
    duration_seconds: float | None = None
    published_at: str | None = None
    thumbnail_url: str | None = None
    page_count: int | None = None


@dataclass(frozen=True, slots=True)
class BilibiliFavoriteFolder:
    id: int
    title: str
    media_count: int


@dataclass(frozen=True, slots=True)
class UpCard:
    mid: int
    name: str
    archive_count: int | None = None


@dataclass(frozen=True, slots=True)
class SubtitleCue:
    start_seconds: float
    end_seconds: float
    text: str


@dataclass(frozen=True, slots=True)
class BilibiliQrCode:
    qrcode_key: str
    login_url: str
    svg: str
    expires_in: int


@dataclass(frozen=True, slots=True)
class BilibiliQrPoll:
    state: str
    message: str
    cookie: str | None = None
    refresh_token: str | None = None


def generate_bilibili_qr_code() -> BilibiliQrCode:
    """Request a Bilibili-issued QR login URL and render it locally as SVG."""

    try:
        payload = _http_json(BILIBILI_QR_GENERATE_URL, referer="https://passport.bilibili.com/")
    except (HTTPError, URLError) as error:
        raise LinkImportError("无法生成 B站登录二维码，请检查网络后重试") from error
    if payload.get("code") != 0:
        raise LinkImportError(
            f"B站登录二维码生成失败（接口返回 {payload.get('code')} {payload.get('message', '')}）".strip()
        )
    data = payload.get("data") or {}
    login_url = str(data.get("url") or "").strip()
    qrcode_key = str(data.get("qrcode_key") or "").strip()
    if not login_url or not qrcode_key:
        raise LinkImportError("B站没有返回有效的登录二维码")
    return BilibiliQrCode(
        qrcode_key=qrcode_key,
        login_url=login_url,
        svg=_render_qr_svg(login_url),
        expires_in=BILIBILI_QR_EXPIRES_SECONDS,
    )


def poll_bilibili_qr_code(qrcode_key: str) -> BilibiliQrPoll:
    """Poll Bilibili Passport and return only a short-lived auth result."""

    key = qrcode_key.strip()
    if not key:
        raise LinkImportError("缺少 B站登录二维码标识")
    url = BILIBILI_QR_POLL_URL + "?" + urllib.parse.urlencode({"qrcode_key": key})
    try:
        payload, headers = _http_json_with_headers(
            url, referer="https://passport.bilibili.com/"
        )
    except (HTTPError, URLError) as error:
        raise LinkImportError("无法检查 B站二维码登录状态，请稍后重试") from error
    if payload.get("code") != 0:
        raise LinkImportError(
            f"B站二维码登录检查失败（接口返回 {payload.get('code')} {payload.get('message', '')}）".strip()
        )

    data = payload.get("data") or {}
    try:
        status_code = int(data.get("code"))
    except (TypeError, ValueError):
        raise LinkImportError("B站二维码登录返回了无法识别的状态") from None
    messages = {
        86101: "等待使用 B站 App 扫码",
        86090: "二维码已扫码，请在 B站 App 中确认登录",
        86038: "B站登录二维码已过期，请重新生成",
    }
    if status_code == 86101:
        return BilibiliQrPoll("WAITING", messages[status_code])
    if status_code == 86090:
        return BilibiliQrPoll("SCANNED", messages[status_code])
    if status_code == 86038:
        return BilibiliQrPoll("EXPIRED", messages[status_code])
    if status_code != 0:
        return BilibiliQrPoll("WAITING", str(data.get("message") or "等待 B站登录确认"))

    cookie = _cookies_from_headers(headers)
    if not cookie:
        cookie = _cookies_from_login_url(data.get("url"))
    refresh_token = str(data.get("refresh_token") or "").strip() or None
    if not cookie:
        raise LinkImportError("B站已返回登录成功，但没有返回可用登录会话，请重新扫码")
    return BilibiliQrPoll(
        "CONNECTED",
        "B站二维码登录成功，正在验证登录会话",
        cookie=cookie,
        refresh_token=refresh_token,
    )


def probe_bilibili_session(cookie: str | None) -> tuple[str, str | None, str]:
    """Validate the product-owned Bilibili session without returning secrets."""

    if not cookie or not cookie.strip():
        return "NOT_CONNECTED", None, "尚未连接 B站，请先生成二维码并使用 B站 App 扫码登录"
    try:
        payload = _http_json(
            "https://api.bilibili.com/x/web-interface/nav",
            extra_headers={"Cookie": cookie.strip()},
        )
    except HTTPError as error:
        if error.code in {401, 403}:
            return "REAUTH_REQUIRED", None, "B站登录会话已失效，请重新扫码登录"
        if error.code in {412, 429}:
            return "RISK_CONTROLLED", None, "B站要求人工验证，请稍后重试"
        if error.code >= 500:
            return "TEMPORARY_ERROR", None, "B站登录状态暂时无法检查，请稍后重试"
        return "REAUTH_REQUIRED", None, f"B站登录状态检查失败（HTTP {error.code}）"
    except (URLError, TimeoutError, socket.timeout):
        return "TEMPORARY_ERROR", None, "无法连接 B站，请检查网络后重试"

    code = payload.get("code")
    data = payload.get("data") or {}
    if code in {-352, -412, -799}:
        return "RISK_CONTROLLED", None, "B站要求人工验证，请稍后重试"
    if code != 0 or not data.get("isLogin"):
        return "REAUTH_REQUIRED", None, "未检测到有效的 B站登录会话，请重新扫码登录"
    account = str(data.get("uname") or data.get("mid") or "").strip() or None
    return "CONNECTED", account, "B站登录会话可用"


def _render_qr_svg(login_url: str) -> str:
    try:
        import qrcode
        from qrcode.image.svg import SvgPathImage
    except ImportError as error:
        raise LinkImportError("缺少二维码生成依赖，请重新安装产品依赖后重试") from error
    qr = qrcode.QRCode(border=2, box_size=8)
    qr.add_data(login_url)
    qr.make(fit=True)
    image = qr.make_image(image_factory=SvgPathImage)
    rendered = image.to_string()
    return rendered.decode("utf-8") if isinstance(rendered, bytes) else str(rendered)


_LOGIN_COOKIE_NAMES = frozenset(
    {"DedeUserID", "DedeUserID__ckMd5", "SESSDATA", "bili_jct", "sid", "bili_ticket"}
)


def _cookies_from_headers(headers) -> str:
    values = headers.get_all("Set-Cookie") or []
    cookies: dict[str, str] = {}
    for raw in values:
        pair = str(raw).split(";", 1)[0].strip()
        name, separator, value = pair.partition("=")
        if separator and name in _LOGIN_COOKIE_NAMES and value:
            cookies[name] = value
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


def _cookies_from_login_url(raw_url) -> str:
    if not raw_url:
        return ""
    cookies: dict[str, str] = {}
    query = urllib.parse.urlparse(str(raw_url)).query
    for name, value in parse_qsl(query, keep_blank_values=True):
        if name in _LOGIN_COOKIE_NAMES and value:
            cookies[name] = value
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


def fetch_video_subtitle(
    bvid: str,
    cid: int,
    cookie: str | None = None,
) -> tuple[str, list[SubtitleCue]] | None:
    """Fetch the public subtitle list for one video.

    Returns (language, cues) when a usable subtitle exists, None when the video
    has no public subtitle, and raises LinkImportError with a QR-login hint when
    the platform requires a signed-in session or blocks the request.
    """

    session_cookie = _merged_cookie(cookie)
    wbi = _wbi_keys(session_cookie)
    params = _signed_wbi_params({"bvid": bvid, "cid": cid}, wbi[0], wbi[1])
    url = "https://api.bilibili.com/x/player/wbi/v2?" + urllib.parse.urlencode(params)
    try:
        payload = _http_json(
            url,
            referer=f"https://www.bilibili.com/video/{bvid}",
            extra_headers={"Cookie": session_cookie},
        )
    except HTTPError as error:
        connection_status = (
            "REAUTH_REQUIRED" if error.code in {401, 403}
            else "RISK_CONTROLLED" if error.code in {412, 429}
            else None
        )
        raise LinkImportError(
            _RESTRICTED_MESSAGE if connection_status == "RISK_CONTROLLED"
            else f"B站字幕读取失败（HTTP {error.code}）",
            connection_status=connection_status,
        ) from error
    except URLError as error:
        raise LinkImportError("无法连接到B站，请检查网络或稍后重试") from error

    code = payload.get("code")
    if code != 0:
        if code in {-101, -400}:
            raise LinkImportError(
                "视频字幕需要登录。请在设置页使用 B站二维码登录后重试",
                connection_status="REAUTH_REQUIRED",
            )
        if code in {-352, -799}:
            raise LinkImportError(_RESTRICTED_MESSAGE, connection_status="RISK_CONTROLLED")
        raise LinkImportError(
            f"B站字幕读取失败（接口返回 {code} {payload.get('message', '')}）".strip()
        )

    subtitles = ((payload.get("data") or {}).get("subtitle") or {}).get("subtitles") or []
    if not isinstance(subtitles, list) or not subtitles:
        return None
    track = _preferred_subtitle(subtitles)
    if track is None:
        return None
    cues = _download_subtitle_cues(track, bvid)
    if not cues:
        return None
    return track.get("lan_doc") or track.get("lan") or "字幕", cues


def _preferred_subtitle(subtitles: list) -> dict | None:
    ranked = sorted(
        (item for item in subtitles if isinstance(item, dict) and item.get("subtitle_url")),
        key=lambda item: _subtitle_rank(item),
    )
    return ranked[0] if ranked else None


def _subtitle_rank(item: dict) -> int:
    lan = str(item.get("lan") or "").lower()
    if lan.startswith("ai-zh") or lan in {"zh-cn", "zh-hans", "zh"}:
        return 0
    if lan.startswith("ai"):
        return 1
    if lan.startswith("zh"):
        return 2
    return 3


def _download_subtitle_cues(track: dict, bvid: str) -> list[SubtitleCue]:
    url = str(track.get("subtitle_url") or "")
    if not url:
        return []
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("/"):
        url = "https://www.bilibili.com" + url
    try:
        payload = _http_json(
            url,
            referer=f"https://www.bilibili.com/video/{bvid}",
        )
    except (HTTPError, URLError):
        return []
    body = payload.get("body") if isinstance(payload, dict) else None
    if not isinstance(body, list):
        return []
    cues: list[SubtitleCue] = []
    for item in body:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item.get("from"))
            end = float(item.get("to"))
            text = str(item.get("content") or "").strip()
        except (TypeError, ValueError):
            continue
        if text and end >= start:
            cues.append(SubtitleCue(start, end, text))
    return cues


def fetch_video_audio_urls(
    bvid: str,
    cid: int,
    cookie: str | None = None,
) -> list[str]:
    """Return playable audio stream URLs (lowest bitrate first).

    Empty list means the video has no public audio stream; raises
    LinkImportError with a QR-login hint when the platform blocks it.
    """

    session_cookie = _merged_cookie(cookie)
    wbi = _wbi_keys(session_cookie)
    params = _signed_wbi_params({"bvid": bvid, "cid": cid}, wbi[0], wbi[1])
    url = "https://api.bilibili.com/x/player/wbi/v2?" + urllib.parse.urlencode(params)
    try:
        payload = _http_json(
            url,
            referer=f"https://www.bilibili.com/video/{bvid}",
            extra_headers={"Cookie": session_cookie},
        )
    except HTTPError as error:
        connection_status = (
            "REAUTH_REQUIRED" if error.code in {401, 403}
            else "RISK_CONTROLLED" if error.code in {412, 429}
            else None
        )
        raise LinkImportError(
            _RESTRICTED_MESSAGE if connection_status == "RISK_CONTROLLED"
            else f"B站音频信息读取失败（HTTP {error.code}）",
            connection_status=connection_status,
        ) from error
    except URLError as error:
        raise LinkImportError("无法连接到B站，请检查网络或稍后重试") from error

    code = payload.get("code")
    if code != 0:
        if code in {-101, -400}:
            raise LinkImportError(
                "音频流需要登录。请在设置页使用 B站二维码登录后重试",
                connection_status="REAUTH_REQUIRED",
            )
        if code in {-352, -799}:
            raise LinkImportError(_RESTRICTED_MESSAGE, connection_status="RISK_CONTROLLED")
        raise LinkImportError(
            f"B站音频信息读取失败（接口返回 {code} {payload.get('message', '')}）".strip()
        )

    audio = ((payload.get("data") or {}).get("dash") or {}).get("audio") or []
    urls: list[str] = []
    for item in audio:
        if not isinstance(item, dict):
            continue
        raw = item.get("baseUrl") or item.get("base_url") or ""
        decoded = urllib.parse.unquote(str(raw)).replace("&amp;", "&")
        if decoded and decoded not in urls:
            urls.append(decoded)
    return urls


def download_audio(url: str, dest: Path, *, cookie: str | None = None) -> Path:
    """Stream one audio URL into dest; the caller owns cleanup."""

    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "gzip, deflate",
        "Referer": "https://www.bilibili.com/",
    }
    merged = _merged_cookie(cookie)
    if merged:
        headers["Cookie"] = merged
    try:
        with urlopen(Request(url, headers=headers), timeout=120) as response, dest.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    except HTTPError as error:
        connection_status = (
            "REAUTH_REQUIRED" if error.code in {401, 403}
            else "RISK_CONTROLLED" if error.code in {412, 429}
            else None
        )
        raise LinkImportError(
            f"B站音频下载失败（HTTP {error.code}）",
            connection_status=connection_status,
        ) from error
    except URLError as error:
        raise LinkImportError("B站音频下载失败（网络错误，请稍后重试）") from error
    if dest.stat().st_size == 0:
        raise LinkImportError("B站音频下载失败（文件为空）")
    return dest


def download_bilibili_audio(
    url: str,
    *,
    cookie: str | None = None,
) -> Path:
    """Download one Bilibili audio stream using the product-owned session."""

    try:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError
    except ImportError as error:
        raise LinkImportError("缺少 yt-dlp 依赖，无法下载B站音频") from error

    temp_dir = Path(tempfile.mkdtemp(prefix="knowledge-asr-"))
    options = {
        "format": "bestaudio/best",
        "outtmpl": str(temp_dir / "source.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "nopart": True,
        "overwrites": True,
    }
    if cookie and cookie.strip():
        options["http_headers"] = {"Cookie": cookie.strip()}
    try:
        with YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=True)
            prepared_name = Path(downloader.prepare_filename(info)) if info else None
        if prepared_name is not None and prepared_name.is_file():
            if prepared_name.stat().st_size > 0:
                return prepared_name
            raise LinkImportError("B站音频下载失败（文件为空）")
        candidates = [
            path
            for path in temp_dir.glob("source.*")
            if path.is_file() and not path.name.endswith(".part")
        ]
        if candidates:
            if candidates[0].stat().st_size > 0:
                return candidates[0]
            raise LinkImportError("B站音频下载失败（文件为空）")
        raise LinkImportError("B站没有返回可转写的音频文件")
    except DownloadError as error:
        shutil.rmtree(temp_dir, ignore_errors=True)
        detail = str(error).splitlines()[-1].strip() or "下载器未返回具体原因"
        raise LinkImportError(
            f"B站音频下载失败：{detail}。请先在设置页完成 B站二维码登录"
        ) from error
    except LinkImportError:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    except Exception as error:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise LinkImportError(f"B站音频下载失败：{error}") from error


def _merged_cookie(user_cookie: str | None) -> str:
    parts: list[str] = []
    buvid = _buvid_cookies()
    if buvid:
        parts.append(buvid)
    if user_cookie and user_cookie.strip():
        parts.append(user_cookie.strip())
    return "; ".join(part for part in parts if part)


def parse_space_mid(url: str) -> int | None:
    """Return the numeric UP mid from a space.bilibili.com URL, or None."""

    parsed = urlparse(url.strip())
    if (parsed.hostname or "").lower() not in {"space.bilibili.com", "space.b23.tv"}:
        return None
    first = next((part for part in parsed.path.split("/") if part), "")
    try:
        return int(first)
    except ValueError:
        return None


def parse_season_id(url: str) -> int | None:
    """Return the 合集（season）id from a B站 合集链接, or None."""

    parsed = urlparse(url.strip())
    if (parsed.hostname or "").lower() not in {"space.bilibili.com", "space.b23.tv"}:
        return None
    path = parsed.path.lower()
    if "/lists" not in path and "/channel/collectiondetail" not in path:
        return None
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if str(query.get("type") or "").strip().lower() == "series":
        return None
    try:
        return int(str(query.get("sid") or "").strip()) or None
    except ValueError:
        return None


def parse_favorite_id(url: str) -> int | None:
    """Return the numeric Bilibili favorite-folder id from a favlist URL."""

    parsed = urlparse(url.strip())
    if (parsed.hostname or "").lower() not in {"space.bilibili.com", "space.b23.tv"}:
        return None
    if "/favlist" not in parsed.path.lower():
        return None
    try:
        return int(dict(parse_qsl(parsed.query)).get("fid") or 0) or None
    except ValueError:
        return None


def enumerate_favorite_folders(cookie: str | None) -> list[BilibiliFavoriteFolder]:
    """Return the signed-in account's own video favorite folders."""

    if not cookie or not cookie.strip():
        raise LinkImportError(
            "B站登录未确认，请在设置中使用二维码重新登录",
            connection_status="REAUTH_REQUIRED",
        )
    headers = {"Cookie": cookie.strip()}
    try:
        nav = _http_json(
            "https://api.bilibili.com/x/web-interface/nav",
            extra_headers=headers,
        )
    except HTTPError as error:
        status = (
            "REAUTH_REQUIRED" if error.code in {401, 403}
            else "RISK_CONTROLLED" if error.code in {412, 429}
            else None
        )
        raise LinkImportError(
            f"B站登录状态验证失败（HTTP {error.code}）", connection_status=status
        ) from error
    except (URLError, TimeoutError) as error:
        raise LinkImportError("无法连接到B站，请检查网络后重试") from error

    nav_data = nav.get("data") or {}
    if nav.get("code") in {-352, -412, -799}:
        raise LinkImportError("B站要求人工验证，请稍后重试", connection_status="RISK_CONTROLLED")
    if nav.get("code") != 0 or not nav_data.get("isLogin"):
        raise LinkImportError(
            "B站登录会话未通过验证，请在设置中使用二维码重新登录",
            connection_status="REAUTH_REQUIRED",
        )
    try:
        mid = int(nav_data.get("mid") or 0)
    except (TypeError, ValueError):
        mid = 0
    if mid <= 0:
        raise LinkImportError(
            "B站登录响应未提供账号 ID，请重新检查登录状态",
            connection_status="REAUTH_REQUIRED",
        )

    cookies = _merged_cookie(cookie)
    headers = {"Cookie": cookies}
    url = "https://api.bilibili.com/x/v3/fav/folder/created/list-all?" + urllib.parse.urlencode(
        {"up_mid": mid}
    )
    try:
        payload = _http_json(
            url,
            referer="https://space.bilibili.com/",
            extra_headers=headers,
        )
    except HTTPError as error:
        status = (
            "REAUTH_REQUIRED" if error.code in {401, 403}
            else "RISK_CONTROLLED" if error.code in {412, 429}
            else None
        )
        raise LinkImportError(
            f"B站收藏夹目录读取失败（HTTP {error.code}）", connection_status=status
        ) from error
    except (URLError, TimeoutError) as error:
        raise LinkImportError("无法连接到B站，请检查网络后重试") from error

    code = payload.get("code")
    if code in {-101, -400, -403}:
        raise LinkImportError(
            "当前 B站登录状态无权读取本人收藏夹目录，请重新扫码登录",
            connection_status="REAUTH_REQUIRED",
        )
    if code in {-352, -799, -412}:
        raise LinkImportError(
            "B站暂时限制了收藏夹目录读取，请稍后重试",
            connection_status="RISK_CONTROLLED",
        )
    if code != 0:
        message = f"B站收藏夹目录读取失败（接口返回 {code} {payload.get('message', '')}）"
        raise LinkImportError(message.strip())

    data = payload.get("data") or {}
    raw_folders = data.get("list") or []
    if not isinstance(raw_folders, list):
        raise LinkImportError("B站返回的收藏夹目录格式无法解析")
    folders: list[BilibiliFavoriteFolder] = []
    for raw in raw_folders:
        if not isinstance(raw, dict):
            continue
        try:
            folder_id = int(raw.get("id") or raw.get("media_id") or 0)
            media_count = max(0, int(raw.get("media_count") or 0))
        except (TypeError, ValueError):
            continue
        if folder_id <= 0:
            continue
        folders.append(BilibiliFavoriteFolder(
            id=folder_id,
            title=str(raw.get("title") or "").strip() or "未命名收藏夹",
            media_count=media_count,
        ))
    return folders


def is_watchlater_url(url: str) -> bool:
    """Return whether a URL points to the whole Bilibili watch-later list."""

    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    return (
        host in {"bilibili.com", "www.bilibili.com", "b23.tv", "www.b23.tv"}
        and "watchlater" in parsed.path.lower()
    )


def fetch_up_card(mid: int, cookie: str | None = None) -> UpCard:
    """Resolve the UP 主's public name and archive count via the card API."""

    try:
        payload = _http_json(
            f"https://api.bilibili.com/x/web-interface/card?mid={mid}",
            referer=f"https://space.bilibili.com/{mid}",
            extra_headers={"Cookie": _merged_cookie(cookie)} if cookie else {},
        )
    except HTTPError as error:
        connection_status = (
            "REAUTH_REQUIRED" if error.code in {401, 403}
            else "RISK_CONTROLLED" if error.code in {412, 429}
            else None
        )
        raise LinkImportError(
            f"B站UP主信息读取失败（HTTP {error.code}）",
            connection_status=connection_status,
        ) from error
    except (URLError, TimeoutError, socket.timeout) as error:
        raise LinkImportError("无法连接到B站，请检查网络或稍后重试") from error
    if payload.get("code") != 0:
        code = payload.get("code")
        connection_status = (
            "REAUTH_REQUIRED" if code in {-101, -400}
            else "RISK_CONTROLLED" if code in {-352, -412, -799}
            else None
        )
        raise LinkImportError(
            f"无法获取UP主信息（接口返回 {code} {payload.get('message', '')}）".strip(),
            connection_status=connection_status,
        )
    data = payload.get("data") or {}
    card = data.get("card") or {}
    name = str(card.get("name") or "").strip()
    if not name:
        raise LinkImportError("无法确认该UP主的主页信息")
    archive_count = data.get("archive_count")
    return UpCard(
        mid=mid,
        name=name,
        archive_count=int(archive_count) if isinstance(archive_count, int) else None,
    )


def enumerate_space_videos(
    mid: int, *, page: int = 1, cookie: str | None = None
) -> tuple[list[SpaceVideo], int]:
    """List the UP 主's public videos (newest first) and the total archive count.

    Raises LinkImportError with a clear restricted reason when the platform's
    risk control blocks the public list API; retry after completing the
    product-owned QR login to read signed-in accessible content.
    """

    cookies = _merged_cookie(cookie)
    wbi = _wbi_keys(cookies)
    params = _signed_wbi_params(
        {
            "mid": mid,
            "ps": MAX_VIDEOS_PER_PAGE,
            "pn": page,
            "order": "pubdate",
            "platform": "web",
            "web_location": 1550101,
        },
        wbi[0],
        wbi[1],
    )
    url = "https://api.bilibili.com/x/space/wbi/arc/search?" + urllib.parse.urlencode(params)
    try:
        payload = _http_json(
            url,
            referer=f"https://space.bilibili.com/{mid}/video",
            extra_headers={"Cookie": cookies},
        )
    except HTTPError as error:
        connection_status = (
            "REAUTH_REQUIRED" if error.code in {401, 403}
            else "RISK_CONTROLLED" if error.code in {412, 429}
            else None
        )
        raise LinkImportError(
            _RESTRICTED_MESSAGE if connection_status == "RISK_CONTROLLED"
            else f"B站视频列表读取失败（HTTP {error.code}）",
            connection_status=connection_status,
        ) from error
    except URLError as error:
        raise LinkImportError("无法连接到B站，请检查网络或稍后重试") from error

    code = payload.get("code")
    if code != 0:
        if code in {-352, -799}:
            raise LinkImportError(_RESTRICTED_MESSAGE, connection_status="RISK_CONTROLLED")
        if code in {-101, -400}:
            raise LinkImportError(
                "B站视频列表需要登录，请在设置页使用 B站二维码登录后重试",
                connection_status="REAUTH_REQUIRED",
            )
        raise LinkImportError(
            f"B站视频列表读取失败（接口返回 {code} {payload.get('message', '')}）".strip()
        )
    data = payload.get("data") or {}
    page_info = data.get("page") or {}
    total = int(page_info.get("count") or 0)
    videos: list[SpaceVideo] = []
    for item in (data.get("list") or {}).get("vlist") or []:
        bvid = str(item.get("bvid") or "").strip()
        if not bvid:
            continue
        created = item.get("created")
        videos.append(
            SpaceVideo(
                bvid=bvid,
                title=str(item.get("title") or "").strip(),
                url=f"https://www.bilibili.com/video/{bvid}",
                duration_seconds=_length_seconds(item.get("length")),
                published_at=(
                    time.strftime("%Y-%m-%d", time.localtime(int(created))) if created else None
                ),
                thumbnail_url=_normalize_thumbnail(item.get("pic") or item.get("cover")),
            )
        )
    return videos, total


def enumerate_season_videos(
    mid: int, season_id: int, *, page: int = 1, cookie: str | None = None
) -> tuple[list[SpaceVideo], int, str]:
    """List one page of a Bilibili 合集（season）and its total item count.

    Returns the videos, the 合集 total and the 合集 title.  This endpoint is
    public, does not require wbi signing and is not the UP 主 archive list, so a
    合集 link never falls back to reading the whole space.
    """

    cookies = _merged_cookie(cookie)
    params = urllib.parse.urlencode({
        "mid": mid,
        "season_id": season_id,
        "sort_reverse": "false",
        "page_num": page,
        "page_size": MAX_SEASON_ITEMS_PER_PAGE,
    })
    try:
        payload = _http_json(
            f"{BILIBILI_SEASON_LIST_URL}?{params}",
            referer=f"https://space.bilibili.com/{mid}/lists?sid={season_id}",
            extra_headers={"Cookie": cookies},
        )
    except HTTPError as error:
        connection_status = (
            "REAUTH_REQUIRED" if error.code in {401, 403}
            else "RISK_CONTROLLED" if error.code in {412, 429}
            else None
        )
        raise LinkImportError(
            "B站暂时限制了合集读取，请完成登录或稍后重试"
            if connection_status == "RISK_CONTROLLED"
            else f"B站合集读取失败（HTTP {error.code}）",
            connection_status=connection_status,
        ) from error
    except URLError as error:
        raise LinkImportError("无法连接到B站，请检查网络或稍后重试") from error
    code = payload.get("code")
    if code != 0:
        if code in {-101, -400}:
            raise LinkImportError(
                "B站合集需要登录，请在设置页使用 B站二维码登录后重试",
                connection_status="REAUTH_REQUIRED",
            )
        if code in {-352, -799, -412}:
            raise LinkImportError(
                "B站暂时限制了合集读取，请完成登录或稍后重试",
                connection_status="RISK_CONTROLLED",
            )
        if code in {-404}:
            raise LinkImportError("未找到该合集（接口返回 -404）")
        raise LinkImportError(
            f"B站合集读取失败（接口返回 {code} {payload.get('message', '')}）".strip()
        )
    data = payload.get("data") or {}
    meta = data.get("meta") or {}
    title = str(meta.get("name") or "").strip() or "未命名合集"
    if title.startswith("合集·"):
        title = title[3:].strip() or title
    try:
        total = int(meta.get("total") or 0)
    except (TypeError, ValueError):
        total = 0
    videos: list[SpaceVideo] = []
    for item in data.get("archives") or []:
        bvid = str(item.get("bvid") or "").strip()
        if not bvid:
            continue
        published = item.get("pubdate") or item.get("ctime")
        videos.append(SpaceVideo(
            bvid=bvid,
            title=str(item.get("title") or "").strip(),
            url=f"https://www.bilibili.com/video/{bvid}",
            duration_seconds=_length_seconds(item.get("duration")),
            published_at=(
                time.strftime("%Y-%m-%d", time.localtime(int(published)))
                if isinstance(published, (int, float)) and published
                else None
            ),
            thumbnail_url=_normalize_thumbnail(item.get("pic") or item.get("cover")),
        ))
    return videos, total, title


def enumerate_favorite_videos(
    favorite_id: int, *, page: int = 1, cookie: str | None = None
) -> tuple[list[SpaceVideo], int, str]:
    """List one page of a Bilibili favorite folder's videos."""

    cookies = _merged_cookie(cookie)
    params = urllib.parse.urlencode({
        "media_id": favorite_id, "pn": page, "ps": 20, "keyword": "",
        "order": "mtime", "type": 0, "tid": 0, "platform": "web",
    })
    try:
        payload = _http_json(
            f"https://api.bilibili.com/x/v3/fav/resource/list?{params}",
            referer=f"https://space.bilibili.com/favlist?fid={favorite_id}",
            extra_headers={"Cookie": cookies},
        )
    except HTTPError as error:
        connection_status = "REAUTH_REQUIRED" if error.code in {401, 403} else "RISK_CONTROLLED" if error.code in {412, 429} else None
        raise LinkImportError(
            f"B站收藏夹读取失败（HTTP {error.code}）", connection_status=connection_status
        ) from error
    except URLError as error:
        raise LinkImportError("无法连接到B站，请检查网络或稍后重试") from error
    code = payload.get("code")
    if code != 0:
        if code in {-101, -400}:
            raise LinkImportError("B站收藏夹需要登录，请在设置页使用 B站二维码登录后重试", connection_status="REAUTH_REQUIRED")
        if code in {-352, -799, -412}:
            raise LinkImportError("B站暂时限制了收藏夹读取，请完成登录或稍后重试", connection_status="RISK_CONTROLLED")
        raise LinkImportError(f"B站收藏夹读取失败（接口返回 {code} {payload.get('message', '')}）".strip())
    data = payload.get("data") or {}
    info = data.get("info") or {}
    title = str(info.get("title") or "未命名收藏夹").strip()
    total = int(info.get("media_count") or 0)
    videos: list[SpaceVideo] = []
    for item in data.get("medias") or []:
        bvid = str(item.get("bvid") or "").strip()
        if not bvid:
            continue
        duration = item.get("duration")
        try:
            page_count = int(item.get("page")) if item.get("page") is not None else None
        except (TypeError, ValueError):
            page_count = None
        if page_count is not None and page_count <= 0:
            page_count = None
        videos.append(SpaceVideo(
            bvid=bvid,
            title=str(item.get("title") or "").strip(),
            url=f"https://www.bilibili.com/video/{bvid}",
            duration_seconds=float(duration) if isinstance(duration, (int, float)) else _length_seconds(duration),
            published_at=time.strftime("%Y-%m-%d", time.localtime(int(item["pubtime"]))) if item.get("pubtime") else None,
            thumbnail_url=_normalize_thumbnail(item.get("cover") or item.get("pic")),
            page_count=page_count,
        ))
    return videos, total, title


def enumerate_watchlater_videos(
    *, page: int = 1, cookie: str | None = None
) -> tuple[list[SpaceVideo], int]:
    """List one page of the signed-in user's Bilibili watch-later list."""

    cookies = _merged_cookie(cookie)
    params = urllib.parse.urlencode({"pn": page, "ps": 20})
    try:
        payload = _http_json(
            f"https://api.bilibili.com/x/v2/history/toview?{params}",
            referer="https://www.bilibili.com/watchlater",
            extra_headers={"Cookie": cookies},
        )
    except HTTPError as error:
        connection_status = "REAUTH_REQUIRED" if error.code in {401, 403} else "RISK_CONTROLLED" if error.code in {412, 429} else None
        raise LinkImportError(
            f"B站稍后再看读取失败（HTTP {error.code}）",
            connection_status=connection_status,
        ) from error
    except URLError as error:
        raise LinkImportError("无法连接到B站，请检查网络后重试") from error
    data = payload.get("data") or {}
    code = payload.get("code")
    if code != 0:
        if code in {-101, -400}:
            raise LinkImportError("B站稍后再看需要登录，请在设置页使用 B站二维码登录后重试", connection_status="REAUTH_REQUIRED")
        if code in {-352, -799, -412}:
            raise LinkImportError("B站暂时限制了稍后再看读取，请完成登录或稍后重试", connection_status="RISK_CONTROLLED")
        raise LinkImportError(f"B站稍后再看读取失败（接口返回 {code} {payload.get('message', '')}）".strip())

    raw_items = data.get("list") if isinstance(data, dict) else data
    if not isinstance(raw_items, list):
        raw_items = []
    total = int((data.get("count") if isinstance(data, dict) else None) or len(raw_items))
    videos: list[SpaceVideo] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        bvid = str(item.get("bvid") or "").strip()
        if not bvid:
            continue
        published = item.get("pubdate") or item.get("created") or item.get("ctime")
        videos.append(SpaceVideo(
            bvid=bvid,
            title=str(item.get("title") or "").strip(),
            url=f"https://www.bilibili.com/video/{bvid}",
            duration_seconds=(
                float(item["duration"]) if isinstance(item.get("duration"), (int, float))
                else _length_seconds(item.get("duration") or item.get("length"))
            ),
            published_at=(
                time.strftime("%Y-%m-%d", time.localtime(int(published)))
                if published else None
            ),
            thumbnail_url=_normalize_thumbnail(item.get("pic") or item.get("cover")),
        ))
    return videos, total


_RESTRICTED_MESSAGE = (
    "B站公开视频列表接口被平台风控拦截（HTTP 412/风控校验失败），"
    "当前环境无法批量读取该UP主主页。请粘贴单条视频链接导入，或稍后重试。"
)


def _length_seconds(value) -> float | None:
    if not value:
        return None
    try:
        parts = [float(part) for part in str(value).split(":")]
        total = 0.0
        for part in parts:
            total = total * 60 + part
        return total
    except ValueError:
        return None


def _normalize_thumbnail(value) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.startswith("//"):
        return "https:" + raw
    if raw.startswith("http://"):
        return "https://" + raw[7:]
    if raw.startswith("/"):
        return "https://www.bilibili.com" + raw
    return raw


def _buvid_cookies() -> str:
    global _buvid_cookie_cache
    now = time.monotonic()
    cached = _buvid_cookie_cache
    if cached is not None and now - cached[0] < _BUVID_COOKIE_TTL_SECONDS:
        return cached[1]
    payload = _http_json("https://api.bilibili.com/x/frontend/finger/spi")
    data = payload.get("data") or {}
    b3 = str(data.get("b_3") or "")
    b4 = str(data.get("b_4") or "")
    parts = [f"buvid3={b3}"] if b3 else []
    if b4:
        parts.append(f"buvid4={b4}")
    value = "; ".join(parts)
    if value:
        _buvid_cookie_cache = (now, value)
    return value


def _wbi_keys(cookies: str) -> tuple[str, str]:
    global _wbi_key_cache
    now = time.monotonic()
    cached = _wbi_key_cache
    if cached is not None and cached[1] == cookies and now - cached[0] < _WBI_KEY_TTL_SECONDS:
        return cached[2]
    try:
        payload = _http_json(
            "https://api.bilibili.com/x/web-interface/nav",
            extra_headers={"Cookie": cookies},
        )
    except HTTPError as error:
        connection_status = (
            "REAUTH_REQUIRED" if error.code in {401, 403}
            else "RISK_CONTROLLED" if error.code in {412, 429}
            else None
        )
        raise LinkImportError(
            f"B站访问受限（HTTP {error.code}）",
            connection_status=connection_status,
        ) from error
    except URLError as error:
        raise LinkImportError("无法连接到B站，请检查网络或稍后重试") from error
    data = payload.get("data") or {}
    wbi = data.get("wbi_img") or {}
    img_key = str(wbi.get("img_url") or "").rsplit("/", 1)[-1].split(".", 1)[0]
    sub_key = str(wbi.get("sub_url") or "").rsplit("/", 1)[-1].split(".", 1)[0]
    if not img_key or not sub_key:
        raise LinkImportError("B站访问受限，无法获取页面签名参数")
    _wbi_key_cache = (now, cookies, (img_key, sub_key))
    return img_key, sub_key


def _signed_wbi_params(params: dict, img_key: str, sub_key: str) -> dict[str, str]:
    mixin_key = "".join((img_key + sub_key)[index] for index in _MIXIN_KEY_ENC_TAB)[:32]
    signed = {key: str(value) for key, value in params.items()}
    signed["wts"] = str(int(time.time()))
    signed = dict(sorted(signed.items()))
    cleaned = {
        key: "".join(character for character in value if character not in "!'()*")
        for key, value in signed.items()
    }
    query = urllib.parse.urlencode(cleaned)
    signed["w_rid"] = hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()
    return signed


def _http_json(url: str, *, referer: str | None = None, extra_headers: dict[str, str] | None = None) -> dict:
    payload, _ = _http_json_with_headers(url, referer=referer, extra_headers=extra_headers)
    return payload


def _http_json_with_headers(
    url: str, *, referer: str | None = None, extra_headers: dict[str, str] | None = None
) -> tuple[dict, object]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate",
        "Referer": referer or "https://www.bilibili.com/",
    }
    if extra_headers:
        headers.update(extra_headers)
    request = Request(url, headers=headers)
    for attempt in range(_TRANSIENT_RETRIES + 1):
        try:
            with urlopen(request, timeout=12) as response:
                payload = response.read()
                encoding = (response.headers.get("Content-Encoding") or "").lower()
                if "gzip" in encoding:
                    payload = gzip.decompress(payload)
                elif "deflate" in encoding:
                    try:
                        payload = zlib.decompress(payload)
                    except zlib.error:
                        payload = zlib.decompress(payload, -zlib.MAX_WBITS)
                try:
                    parsed = json.loads(payload.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise URLError("bilibili_response_format") from error
                if not isinstance(parsed, dict):
                    raise URLError("bilibili_response_format")
                return parsed, response.headers
        except HTTPError:
            raise
        except (gzip.BadGzipFile, EOFError, OSError, zlib.error) as error:
            if attempt >= _TRANSIENT_RETRIES:
                raise URLError("bilibili_transient_response") from error
            logger.warning(
                "retrying transient Bilibili response failure url=%s attempt=%s reason=%s",
                url,
                attempt + 1,
                type(error).__name__,
            )
            time.sleep(0.15 * (attempt + 1))
        except (URLError, TimeoutError, socket.timeout, ConnectionResetError, ssl.SSLError) as error:
            if not is_transient_network_error(error) or attempt >= _TRANSIENT_RETRIES:
                raise
            logger.warning(
                "retrying transient Bilibili request url=%s attempt=%s reason=%s",
                url,
                attempt + 1,
                type(error).__name__,
            )
            time.sleep(0.15 * (attempt + 1))
