"""Desktop platform connection catalog and product-owned authentication."""

from __future__ import annotations

from dataclasses import dataclass

from app.adapters.sources.bilibili import probe_bilibili_session


NOT_CONNECTED = "NOT_CONNECTED"
CHECKING = "CHECKING"
CONNECTED = "CONNECTED"
EXPIRED = "EXPIRED"
REAUTH_REQUIRED = "REAUTH_REQUIRED"
RISK_CONTROLLED = "RISK_CONTROLLED"
UNSUPPORTED = "UNSUPPORTED"
# A transient upstream failure is returned by a checker but is never written
# as the durable platform connection status.
TEMPORARY_ERROR = "TEMPORARY_ERROR"


@dataclass(frozen=True, slots=True)
class PlatformDefinition:
    """单一静态能力真相源：连接信息与来源能力都定义在此，接口只做投影。"""

    key: str
    display_name: str
    login_url: str
    auth_type: str
    checker_available: bool
    browser_session_available: bool = False
    # 来源能力（静态事实；未经验证的能力一律 False，由对应执行包验收后置 True）
    supported_source_types: tuple[str, ...] = ()
    public_import_available: bool = False
    account_probe_available: bool = False
    text_available: bool = False
    image_ocr_available: bool = False
    video_available: bool = False
    collection_sync_available: bool = False
    capability_note: str = ""


PLATFORM_DEFINITIONS: tuple[PlatformDefinition, ...] = (
    PlatformDefinition(
        "bilibili",
        "B站",
        "https://passport.bilibili.com/login",
        "qrcode_session",
        True,
        supported_source_types=("video", "account", "collection"),
        public_import_available=True,
        account_probe_available=True,
        text_available=True,
        video_available=True,
        collection_sync_available=True,
        capability_note="支持单条视频与 UP 主候选批量入队；图文能力按 P10 排期。",
    ),
    PlatformDefinition(
        "xiaohongshu",
        "小红书",
        "https://www.xiaohongshu.com/",
        "browser_session",
        False,
        browser_session_available=True,
        supported_source_types=("account", "image_post", "video"),
        capability_note="可识别链接平台与类型；未登录无法读取内容（2026-09-20 实测登录墙），导入请使用本地文件或粘贴文本。",
    ),
    PlatformDefinition(
        "zhihu",
        "知乎",
        "https://www.zhihu.com/signin",
        "browser_session",
        False,
        browser_session_available=True,
        supported_source_types=("account", "article", "question", "answer", "collection"),
        capability_note="支持内嵌登录、单个收藏夹前 10 条候选预览及用户确认后的单条导入。",
    ),
    PlatformDefinition(
        "wechat",
        "微信公众号",
        "https://mp.weixin.qq.com/",
        "official_api",
        False,
        supported_source_types=("account", "article"),
        capability_note="可识别公众号文章链接；内容读取未接入。",
    ),
    PlatformDefinition(
        "douyin",
        "抖音",
        "https://www.douyin.com/",
        "browser_session",
        False,
        supported_source_types=("account", "video"),
        capability_note="可识别链接平台与类型；页面为动态渲染，未登录静态读取不可用（2026-09-20 实测），导入请使用本地文件或粘贴文本。",
    ),
)


def get_platform_definition(platform: str) -> PlatformDefinition | None:
    return next((item for item in PLATFORM_DEFINITIONS if item.key == platform), None)


def probe_platform(
    platform: str,
    session_cookie: str | None,
) -> tuple[str, str | None, str]:
    """Return (status, account label, user-facing message) for one platform."""

    definition = get_platform_definition(platform)
    if definition is None:
        return UNSUPPORTED, None, "暂未适配该平台的登录检查"
    if definition.checker_available:
        return probe_bilibili_session(session_cookie)
    # 非连接型平台：文案统一取能力说明（单一来源），不再出现"已提供登录入口"类话术。
    return UNSUPPORTED, None, definition.capability_note
