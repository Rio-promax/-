"""P3 统一对象分类器契约测试：短链、追踪参数、账号/集合不产生内容任务、object_label。"""

from __future__ import annotations

import pytest

from app.adapters.sources.classify import classify_source_type, object_label
from app.adapters.sources.link import detect_platform
from app.domain.models import SourcePlatform


@pytest.mark.parametrize(
    ("url", "platform", "expected"),
    [
        # B站 既有子类型保持不变（保护候选扫描流程）
        ("https://www.bilibili.com/video/BV1GJ411x7h7?p=1", SourcePlatform.BILIBILI, "single"),
        ("https://space.bilibili.com/17849059", SourcePlatform.BILIBILI, "creator"),
        ("https://space.bilibili.com/17849059?utm_source=x", SourcePlatform.BILIBILI, "creator"),
        ("https://www.bilibili.com/medialist/detail/ml123", SourcePlatform.BILIBILI, "collection"),
        (
            "https://www.bilibili.com/list/watchlater?bvid=BV1GJ411x7h7",
            SourcePlatform.BILIBILI,
            "single",
        ),
        # 知乎：§5.1 对象类型
        ("https://www.zhihu.com/question/19550228", SourcePlatform.ZHIHU, "question"),
        ("https://www.zhihu.com/question/19550228/answer/20127668", SourcePlatform.ZHIHU, "answer"),
        ("https://zhuanlan.zhihu.com/p/572618841", SourcePlatform.ZHIHU, "article"),
        ("https://www.zhihu.com/people/zhang-san", SourcePlatform.ZHIHU, "account"),
        ("https://www.zhihu.com/topic/xxx", SourcePlatform.ZHIHU, "unknown"),
        # 小红书：URL 级无法区分子类型 → unknown（P7/P9 读取后细化）
        ("https://www.xiaohongshu.com/explore/651d9c8b000000001a016b95", SourcePlatform.XIAOHONGSHU, "unknown"),
        ("https://www.xiaohongshu.com/user/profile/5ff0e6410000000001008400", SourcePlatform.XIAOHONGSHU, "account"),
        ("https://xhslink.com/abc123", SourcePlatform.XIAOHONGSHU, "unknown"),
        # 抖音
        ("https://www.douyin.com/video/7301234567890123456", SourcePlatform.DOUYIN, "video"),
        ("https://www.douyin.com/note/7301234567890123456", SourcePlatform.DOUYIN, "image_post"),
        ("https://www.douyin.com/user/MS4wLjABAAAA", SourcePlatform.DOUYIN, "account"),
        ("https://v.douyin.com/iRNBho6/", SourcePlatform.DOUYIN, "unknown"),
        # 微信公众号
        ("https://mp.weixin.qq.com/s/abcDEF123", SourcePlatform.WECHAT, "article"),
        # youtube / web 维持既有语义
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", SourcePlatform.YOUTUBE, "single"),
        ("https://www.youtube.com/@somechannel", SourcePlatform.YOUTUBE, "collection"),
        ("https://example.com/post/1", SourcePlatform.WEB, "single"),
    ],
)
def test_classify_source_type_by_platform(url: str, platform: SourcePlatform, expected: str) -> None:
    assert classify_source_type(url, platform) == expected


def test_detect_platform_routes_short_links_and_tracking_params() -> None:
    assert detect_platform("https://b23.tv/abc123") is SourcePlatform.BILIBILI
    assert detect_platform("https://xhslink.com/abc123") is SourcePlatform.XIAOHONGSHU
    assert (
        detect_platform("https://www.zhihu.com/question/19550228?utm_source=share&utm_medium=pc")
        is SourcePlatform.ZHIHU
    )


@pytest.mark.parametrize(
    ("source_type", "label"),
    [
        ("video", "视频"),
        ("image_post", "图文笔记"),
        ("article", "文章"),
        ("question", "问题"),
        ("answer", "回答"),
        ("account", "账号主页"),
        ("collection", "集合"),
        ("unknown", "未知类型"),
        ("creator", "UP 主主页"),
        ("favorite", "收藏夹"),
        ("watchlater", "稍后再看"),
        ("single", "单条内容"),
    ],
)
def test_object_label_covers_all_values(source_type: str, label: str) -> None:
    assert object_label(source_type) == label


def test_object_label_falls_back_to_unknown_for_unregistered_value() -> None:
    assert object_label("not-a-type") == "未知类型"
