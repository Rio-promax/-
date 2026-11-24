"""统一平台对象分类器（P3）：URL 级识别，不做网络请求。

- B站 沿用既有子类型值（single/creator/favorite/watchlater/collection），保护现有
  候选扫描流程与测试；`object_label` 为全部取值提供中文标签。
- 新平台返回方案 §5.1 的 8 值；小红书笔记与抖音分享短链在 URL 级无法区分子类型，
  返回 unknown（由 P7/P8/P9 读取内容后细化）。
- `platform` 为必填：调用方先用 `link.detect_platform` 解析平台，避免循环导入。
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlparse

from app.domain.models import SourcePlatform


SOURCE_TYPE_LABELS: dict[str, str] = {
    "video": "视频",
    "image_post": "图文笔记",
    "article": "文章",
    "question": "问题",
    "answer": "回答",
    "account": "账号主页",
    "collection": "集合",
    "unknown": "未知类型",
    # B站 既有子类型（向后兼容现有候选扫描流程）
    "single": "单条内容",
    "creator": "UP 主主页",
    "favorite": "收藏夹",
    "watchlater": "稍后再看",
}


def object_label(source_type: str) -> str:
    """source_type 的中文标签，供界面直接展示，不得由前端各自硬编码翻译。"""
    return SOURCE_TYPE_LABELS.get(source_type, "未知类型")


def _watchlater_bvid(parsed) -> str | None:
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    candidate = str(query.get("bvid") or query.get("bv_id") or "").strip()
    if candidate and re.fullmatch(r"(?:BV[0-9A-Za-z]{10}|av\d+)", candidate, re.IGNORECASE):
        return candidate
    match = re.search(r"(?:BV[0-9A-Za-z]{10}|av\d+)", parsed.query, re.IGNORECASE)
    return match.group(0) if match else None


def _bilibili_season_id(parsed) -> int | None:
    """合集页（`/lists?sid=`、`/channel/collectiondetail?sid=`）的 season_id。

    只做 URL 级判断，不发请求；`/medialist/detail/` 是列表（series），不走这里。
    """

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


def is_collection_url(url: str, platform: SourcePlatform) -> bool:
    """账号与集合链接仅识别，不得直接创建内容任务。"""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    if platform is SourcePlatform.BILIBILI:
        if "watchlater" in path and _watchlater_bvid(parsed):
            return False
        return (
            host.startswith("space.")
            or "/favlist" in path
            or "/medialist/detail/" in path
            or "watchlater" in path
        )
    if platform is SourcePlatform.ZHIHU:
        if re.fullmatch(r"/collections?(?:/\d+)?/?", path):
            return True
        return path.startswith("/people/")
    if platform is SourcePlatform.XIAOHONGSHU:
        return "/user/profile" in path
    if platform is SourcePlatform.YOUTUBE:
        return path.startswith("/@") or "/channel/" in path or "/user/" in path
    if platform is SourcePlatform.DOUYIN:
        return path.startswith("/user/")
    return False


def classify_source_type(url: str, platform: SourcePlatform) -> str:
    resolved = urlparse(url)
    host = (resolved.hostname or "").lower()
    path = resolved.path.lower()
    if platform is SourcePlatform.BILIBILI:
        if "watchlater" in path and _watchlater_bvid(resolved):
            return "single"
        if "/favlist" in path:
            return "favorite"
        if host.startswith("space.") and _bilibili_season_id(resolved) is not None:
            return "collection"
        if host.startswith("space."):
            return "creator"
        if "/medialist/detail/" in path:
            return "collection"
        if "watchlater" in path:
            return "watchlater"
        return "single"
    if platform is SourcePlatform.ZHIHU:
        if re.fullmatch(r"/collections?(?:/\d+)?/?", path):
            return "favorite"
        if host == "zhuanlan.zhihu.com":
            return "article"
        if re.search(r"^/question/\d+/answer/\d+", path):
            return "answer"
        if re.match(r"^/question/\d+", path):
            return "question"
        if path.startswith("/people/"):
            return "account"
        return "unknown"
    if platform is SourcePlatform.XIAOHONGSHU:
        if "/user/profile" in path:
            return "account"
        return "unknown"
    if platform is SourcePlatform.DOUYIN:
        if path.startswith("/user/"):
            return "account"
        if re.match(r"^/video/\d+", path):
            return "video"
        if re.match(r"^/note/\d+", path):
            return "image_post"
        return "unknown"
    if platform is SourcePlatform.WECHAT:
        return "article" if re.match(r"^/s/", path) else "unknown"
    # youtube / web：方案范围外，维持既有 single/collection 语义
    return "collection" if is_collection_url(url, platform) else "single"
