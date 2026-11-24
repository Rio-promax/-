"""Offline tests for the Bilibili space (UP 主主页) helpers."""

import gzip
import shutil
import sys
import types
from pathlib import Path

import pytest

from app.adapters.sources import bilibili
from app.adapters.sources.link import LinkImportError


def test_parse_space_mid_accepts_common_url_shapes() -> None:
    assert bilibili.parse_space_mid("https://space.bilibili.com/17849059") == 17849059
    assert bilibili.parse_space_mid("https://space.bilibili.com/17849059/video") == 17849059
    assert (
        bilibili.parse_space_mid("https://space.bilibili.com/17849059?spm_id_from=333.999.0.0")
        == 17849059
    )
    assert bilibili.parse_space_mid("https://www.bilibili.com/video/BV1GKgM6qEar/") is None
    assert bilibili.parse_space_mid("https://example.com/123") is None


def test_watchlater_url_distinguishes_list_from_other_pages() -> None:
    assert bilibili.is_watchlater_url("https://www.bilibili.com/watchlater") is True
    assert bilibili.is_watchlater_url("https://www.bilibili.com/list/watchlater") is True
    assert bilibili.is_watchlater_url("https://www.bilibili.com/video/BV1GKgM6qEar") is False


def test_enumerate_favorite_folders_uses_authenticated_mid_and_keeps_remote_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    monkeypatch.setattr(bilibili, "_buvid_cookies", lambda: None)

    def fake_http_json(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/x/web-interface/nav"):
            return {"code": 0, "data": {"isLogin": True, "mid": 2468}}
        return {
            "code": 0,
            "data": {
                "count": 2,
                "list": [
                    {"id": 101, "title": "A 类", "media_count": 12},
                    {"id": 102, "title": "二类", "media_count": 3},
                ],
            },
        }

    monkeypatch.setattr(bilibili, "_http_json", fake_http_json)

    folders = bilibili.enumerate_favorite_folders("SESSDATA=valid-session")

    assert [(folder.id, folder.title, folder.media_count) for folder in folders] == [
        (101, "A 类", 12),
        (102, "二类", 3),
    ]
    assert "up_mid=2468" in calls[1][0]
    assert calls[0][1]["extra_headers"]["Cookie"] == "SESSDATA=valid-session"
    assert calls[1][1]["extra_headers"]["Cookie"] == "SESSDATA=valid-session"


def test_enumerate_favorite_folders_rejects_unverified_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    monkeypatch.setattr(bilibili, "_buvid_cookies", lambda: None)
    monkeypatch.setattr(
        bilibili,
        "_http_json",
        lambda url, **kwargs: calls.append(url) or {
            "code": -101,
            "data": {"isLogin": False},
        },
    )

    with pytest.raises(LinkImportError, match="登录") as error:
        bilibili.enumerate_favorite_folders("SESSDATA=stale-session")

    assert error.value.connection_status == "REAUTH_REQUIRED"
    assert len(calls) == 1


def test_enumerate_favorite_folders_reports_nav_risk_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    monkeypatch.setattr(bilibili, "_buvid_cookies", lambda: None)
    monkeypatch.setattr(
        bilibili,
        "_http_json",
        lambda url, **kwargs: calls.append(url) or {"code": -799, "data": {"isLogin": False}},
    )

    with pytest.raises(LinkImportError, match="人工验证") as error:
        bilibili.enumerate_favorite_folders("SESSDATA=valid-session")

    assert error.value.connection_status == "RISK_CONTROLLED"
    assert len(calls) == 1


def test_probe_bilibili_session_reports_nav_risk_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        bilibili,
        "_http_json",
        lambda *args, **kwargs: {"code": -799, "data": {"isLogin": False}},
    )

    status, account, message = bilibili.probe_bilibili_session("SESSDATA=valid-session")

    assert status == "RISK_CONTROLLED"
    assert account is None
    assert "稍后重试" in message


def test_signed_wbi_params_has_expected_shape() -> None:
    params = bilibili._signed_wbi_params(
        {"mid": 17849059, "ps": 30, "pn": 1},
        img_key="7cd084941338484aae1ad9425b84077c",
        sub_key="4932caff0ff746eab6f01bf08b70ac45",
    )
    assert set(params) >= {"mid", "ps", "pn", "wts", "w_rid"}
    assert len(params["w_rid"]) == 32
    assert all(character not in params["w_rid"] for character in "!'()*")


def test_fetch_up_card_parses_card_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "code": 0,
        "data": {
            "card": {"name": "木马_MUMAI", "mid": 17849059},
            "archive_count": 22,
        },
    }
    monkeypatch.setattr(
        bilibili,
        "_http_json",
        lambda *args, **kwargs: payload,
    )

    card = bilibili.fetch_up_card(17849059)

    assert card.name == "木马_MUMAI"
    assert card.archive_count == 22


def test_fetch_up_card_reports_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        bilibili,
        "_http_json",
        lambda *args, **kwargs: {"code": -404, "message": "啥都木有"},
    )

    with pytest.raises(LinkImportError, match="无法获取UP主信息"):
        bilibili.fetch_up_card(17849059)


def test_enumerate_space_videos_parses_vlist(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "code": 0,
        "data": {
            "page": {"count": 22},
            "list": {
                "vlist": [
                    {
                        "bvid": "BV1GKgM6qEar",
                        "title": "装好 DeepSeek Harness 还不够",
                        "length": "12:34",
                        "created": 1786982678,
                    }
                ]
            },
        },
    }
    monkeypatch.setattr(bilibili, "_buvid_cookies", lambda: "buvid3=x")
    monkeypatch.setattr(
        bilibili,
        "_wbi_keys",
        lambda _: ("7cd084941338484aae1ad9425b84077c", "4932caff0ff746eab6f01bf08b70ac45"),
    )
    monkeypatch.setattr(bilibili, "_http_json", lambda *args, **kwargs: payload)

    videos, total = bilibili.enumerate_space_videos(17849059)

    assert total == 22
    assert len(videos) == 1
    assert videos[0].bvid == "BV1GKgM6qEar"
    assert videos[0].url == "https://www.bilibili.com/video/BV1GKgM6qEar"
    assert videos[0].duration_seconds == pytest.approx(754.0)


def test_enumerate_watchlater_videos_normalizes_url_and_cover(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bilibili, "_buvid_cookies", lambda: "buvid3=x")
    monkeypatch.setattr(
        bilibili,
        "_http_json",
        lambda *args, **kwargs: {
            "code": 0,
            "data": {
                "count": 2,
                "list": [
                    {
                        "bvid": "BV1GKgM6qEar",
                        "title": "稍后的视频",
                        "duration": 95,
                        "pubdate": 1786982678,
                        "pic": "//i0.hdslb.com/test.jpg",
                    },
                    {"title": "缺少 bvid"},
                ],
            },
        },
    )

    videos, total = bilibili.enumerate_watchlater_videos()

    assert total == 2
    assert len(videos) == 1
    assert videos[0].url == "https://www.bilibili.com/video/BV1GKgM6qEar"
    assert videos[0].thumbnail_url == "https://i0.hdslb.com/test.jpg"


def test_enumerate_favorite_videos_preserves_multi_part_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bilibili, "_buvid_cookies", lambda: None)
    monkeypatch.setattr(
        bilibili,
        "_http_json",
        lambda *args, **kwargs: {
            "code": 0,
            "data": {
                "info": {"title": "分集收藏夹", "media_count": 1},
                "medias": [
                    {
                        "bvid": "BVmulti123",
                        "title": "多 P 视频",
                        "page": 3,
                        "duration": 90,
                    }
                ],
            },
        },
    )

    videos, total, title = bilibili.enumerate_favorite_videos(7, cookie="SESSDATA=ok")

    assert total == 1
    assert title == "分集收藏夹"
    assert videos[0].page_count == 3


@pytest.mark.parametrize("code", [-352, -799])
def test_enumerate_space_videos_reports_risk_control(
    monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    monkeypatch.setattr(bilibili, "_buvid_cookies", lambda: "buvid3=x")
    monkeypatch.setattr(
        bilibili,
        "_wbi_keys",
        lambda _: ("7cd084941338484aae1ad9425b84077c", "4932caff0ff746eab6f01bf08b70ac45"),
    )
    monkeypatch.setattr(
        bilibili,
        "_http_json",
        lambda *args, **kwargs: {"code": code, "message": "风控"},
    )

    with pytest.raises(LinkImportError, match="风控"):
        bilibili.enumerate_space_videos(17849059)


def test_length_seconds_handles_short_and_long_formats() -> None:
    assert bilibili._length_seconds("12:34") == pytest.approx(754.0)
    assert bilibili._length_seconds("1:02:03") == pytest.approx(3723.0)
    assert bilibili._length_seconds(None) is None


def test_gzip_payload_is_decoded_by_http_json(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        headers = {"Content-Encoding": "gzip"}

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def read(self) -> bytes:
            return gzip.compress(b'{"code": 0}')

    monkeypatch.setattr(
        bilibili,
        "urlopen",
        lambda request, timeout: FakeResponse(),
    )

    assert bilibili._http_json("https://api.bilibili.com/x/example") == {"code": 0}

def test_fetch_video_subtitle_parses_cues(monkeypatch: pytest.MonkeyPatch) -> None:
    player_payload = {
        "code": 0,
        "data": {
            "subtitle": {
                "subtitles": [
                    {"lan": "ai-zh", "lan_doc": "中文（自动生成）", "subtitle_url": "//aisubtitle.hdslb.com/x.json"},
                    {"lan": "en", "lan_doc": "英文", "subtitle_url": "//aisubtitle.hdslb.com/en.json"},
                ]
            }
        },
    }
    cue_payload = {
        "body": [
            {"from": 0.0, "to": 3.0, "content": "欢迎来到第一课。"},
            {"from": 3.5, "to": 6.0, "content": "今天介绍知识库的基本概念。"},
        ]
    }
    calls = []

    def fake_http_json(url, *, referer=None, extra_headers=None):
        calls.append(url)
        if "player/wbi" in url:
            return player_payload
        return cue_payload

    monkeypatch.setattr(bilibili, "_buvid_cookies", lambda: "buvid3=x")
    monkeypatch.setattr(bilibili, "_wbi_keys", lambda _: ("7cd084941338484aae1ad9425b84077c", "4932caff0ff746eab6f01bf08b70ac45"))
    monkeypatch.setattr(bilibili, "_http_json", fake_http_json)

    result = bilibili.fetch_video_subtitle("BV1GKgM6qEar", 12345, cookie="SESSDATA=abc")

    assert result is not None
    language, cues = result
    assert language == "中文（自动生成）"
    assert len(cues) == 2
    assert cues[0].text == "欢迎来到第一课。"
    assert cues[0].start_seconds == 0.0
    # 用户cookie应被合并进请求
    assert any("SESSDATA=abc" in str(call) for call in calls) is False  # cookie在header不在url


def test_fetch_video_subtitle_returns_none_without_subtitles(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bilibili, "_buvid_cookies", lambda: "buvid3=x")
    monkeypatch.setattr(bilibili, "_wbi_keys", lambda _: ("7cd084941338484aae1ad9425b84077c", "4932caff0ff746eab6f01bf08b70ac45"))
    monkeypatch.setattr(
        bilibili,
        "_http_json",
        lambda *args, **kwargs: {"code": 0, "data": {"subtitle": {"subtitles": []}}},
    )

    assert bilibili.fetch_video_subtitle("BV1GKgM6qEar", 12345) is None


def test_fetch_video_subtitle_requires_login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bilibili, "_buvid_cookies", lambda: "buvid3=x")
    monkeypatch.setattr(bilibili, "_wbi_keys", lambda _: ("7cd084941338484aae1ad9425b84077c", "4932caff0ff746eab6f01bf08b70ac45"))
    monkeypatch.setattr(
        bilibili,
        "_http_json",
        lambda *args, **kwargs: {"code": -101, "message": "账号未登录"},
    )

    with pytest.raises(LinkImportError, match="二维码登录"):
        bilibili.fetch_video_subtitle("BV1GKgM6qEar", 12345)


def test_fetch_video_subtitle_risk_control(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bilibili, "_buvid_cookies", lambda: "buvid3=x")
    monkeypatch.setattr(bilibili, "_wbi_keys", lambda _: ("7cd084941338484aae1ad9425b84077c", "4932caff0ff746eab6f01bf08b70ac45"))
    monkeypatch.setattr(
        bilibili,
        "_http_json",
        lambda *args, **kwargs: {"code": -352, "message": "风控校验失败"},
    )

    with pytest.raises(LinkImportError, match="风控"):
        bilibili.fetch_video_subtitle("BV1GKgM6qEar", 12345)




def test_fetch_video_audio_urls_parses_dash_and_unescapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "code": 0,
        "data": {
            "dash": {
                "audio": [
                    {"baseUrl": "https://xy.example/a.m4s?b=1&amp;c=2", "bandwidth": 100},
                    {"base_url": "https://xy2.example/a.m4s?b=3", "bandwidth": 300},
                ]
            }
        },
    }
    monkeypatch.setattr(bilibili, "_buvid_cookies", lambda: "buvid3=x")
    monkeypatch.setattr(
        bilibili,
        "_wbi_keys",
        lambda _: ("7cd084941338484aae1ad9425b84077c", "4932caff0ff746eab6f01bf08b70ac45"),
    )
    monkeypatch.setattr(bilibili, "_http_json", lambda *args, **kwargs: payload)

    urls = bilibili.fetch_video_audio_urls("BV1GKgM6qEar", 123)

    assert urls[0] == "https://xy.example/a.m4s?b=1&c=2"
    assert len(urls) == 2


def test_fetch_video_audio_urls_empty_dash_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bilibili, "_buvid_cookies", lambda: "buvid3=x")
    monkeypatch.setattr(
        bilibili,
        "_wbi_keys",
        lambda _: ("7cd084941338484aae1ad9425b84077c", "4932caff0ff746eab6f01bf08b70ac45"),
    )
    monkeypatch.setattr(
        bilibili,
        "_http_json",
        lambda *args, **kwargs: {"code": 0, "data": {"dash": {"audio": []}}},
    )

    assert bilibili.fetch_video_audio_urls("BV1GKgM6qEar", 123) == []


def test_fetch_video_audio_urls_requires_login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bilibili, "_buvid_cookies", lambda: "buvid3=x")
    monkeypatch.setattr(
        bilibili,
        "_wbi_keys",
        lambda _: ("7cd084941338484aae1ad9425b84077c", "4932caff0ff746eab6f01bf08b70ac45"),
    )
    monkeypatch.setattr(
        bilibili,
        "_http_json",
        lambda *args, **kwargs: {"code": -101, "message": "账号未登录"},
    )

    with pytest.raises(LinkImportError, match="二维码登录"):
        bilibili.fetch_video_audio_urls("BV1GKgM6qEar", 123)


def test_enumerate_space_videos_passes_product_session_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"code": 0, "data": {"page": {"count": 1}, "list": {"vlist": []}}}
    seen_headers = {}

    def fake_http_json(url, *, referer=None, extra_headers=None):
        seen_headers.update(extra_headers or {})
        return payload

    monkeypatch.setattr(bilibili, "_buvid_cookies", lambda: "buvid3=x")
    monkeypatch.setattr(bilibili, "_wbi_keys", lambda _: ("7cd084941338484aae1ad9425b84077c", "4932caff0ff746eab6f01bf08b70ac45"))
    monkeypatch.setattr(bilibili, "_http_json", fake_http_json)

    bilibili.enumerate_space_videos(17849059, cookie="SESSDATA=abc")

    assert "SESSDATA=abc" in seen_headers.get("Cookie", "")


def test_download_bilibili_audio_uses_product_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    class FakeYoutubeDL:
        def __init__(self, options):
            captured["options"] = options

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def extract_info(self, _url, download):
            assert download is True
            output = str(captured["options"]["outtmpl"]).replace("%(ext)s", "m4a")
            Path(output).write_bytes(b"fake-audio")
            return {"id": "BV1GKgM6qEar"}

        def prepare_filename(self, _info):
            return str(captured["options"]["outtmpl"]).replace("%(ext)s", "m4a")

    fake_yt_dlp = types.ModuleType("yt_dlp")
    fake_yt_dlp.YoutubeDL = FakeYoutubeDL
    fake_utils = types.ModuleType("yt_dlp.utils")
    fake_utils.DownloadError = RuntimeError
    monkeypatch.setitem(sys.modules, "yt_dlp", fake_yt_dlp)
    monkeypatch.setitem(sys.modules, "yt_dlp.utils", fake_utils)

    audio = bilibili.download_bilibili_audio(
        "https://www.bilibili.com/video/BV1GKgM6qEar",
        cookie="SESSDATA=abc",
    )

    assert audio.read_bytes() == b"fake-audio"
    assert captured["options"]["format"] == "bestaudio/best"
    assert captured["options"]["noplaylist"] is True
    assert captured["options"]["http_headers"]["Cookie"] == "SESSDATA=abc"
    shutil.rmtree(audio.parent)


def test_download_bilibili_audio_rejects_empty_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    class FakeYoutubeDL:
        def __init__(self, options):
            captured["options"] = options

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def extract_info(self, _url, download):
            output = str(captured["options"]["outtmpl"]).replace("%(ext)s", "m4a")
            Path(output).touch()
            return {"id": "BV-empty"}

        def prepare_filename(self, _info):
            return str(captured["options"]["outtmpl"]).replace("%(ext)s", "m4a")

    fake_yt_dlp = types.ModuleType("yt_dlp")
    fake_yt_dlp.YoutubeDL = FakeYoutubeDL
    fake_utils = types.ModuleType("yt_dlp.utils")
    fake_utils.DownloadError = RuntimeError
    monkeypatch.setitem(sys.modules, "yt_dlp", fake_yt_dlp)
    monkeypatch.setitem(sys.modules, "yt_dlp.utils", fake_utils)

    with pytest.raises(bilibili.LinkImportError, match="文件为空"):
        bilibili.download_bilibili_audio("https://www.bilibili.com/video/BV-empty")
