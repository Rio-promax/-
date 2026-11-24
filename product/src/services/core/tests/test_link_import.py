import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread, enumerate as list_threads
from types import SimpleNamespace
from urllib.error import URLError

import pytest
from fastapi.testclient import TestClient

from app.adapters.sources import bilibili, link
from app.adapters.sources.prepared import PreparedSource
from app.api import main
from app.api.main import LINK_QUERY_DEADLINE_SECONDS, LINK_QUERY_TTL_SECONDS, create_app
from app.domain.models import ContentKind, SourcePlatform, Transcript, TranscriptSegment


def install_fake_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.workflows import analyze

    class FakeSummarizer:
        def __init__(self, *args, **kwargs):
            pass

        def summarize_chunks(self, chunks, *, title, strength, prompt, skill=None, text_material=False):
            text = "\n".join(chunk.text for chunk in chunks)
            return SimpleNamespace(
                markdown=f"# {title}\n\n## 概览\n\n{text}\n",
                overview=text,
                key_points=(text,),
            )

    monkeypatch.setattr(analyze, "OpenAICompatibleSummarizer", FakeSummarizer)


def make_client(tmp_path: Path) -> TestClient:
    return TestClient(create_app("sqlite:///:memory:", tmp_path / "knowledge-root"))


def wait_for_link_query_workers(
    client: TestClient,
    query_id: str,
    timeout: float = 1.0,
) -> None:
    deadline = time.monotonic() + timeout
    while True:
        workers = tuple(client.app.state.link_query_workers.get(query_id, ()))
        if not workers:
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            alive = [worker.name for worker in workers if worker.is_alive()]
            raise AssertionError(f"link query workers did not stop: {alive}")
        for worker in workers:
            worker.join(remaining)


def wait_for_link_query(client: TestClient, response) -> dict:
    """Read the asynchronous query session until its batch reaches a terminal state."""

    payload = response.json()
    query_id = payload["query_id"]
    for _ in range(200):
        current = client.get(f"/api/v1/imports/query/{query_id}")
        assert current.status_code == 200
        snapshot = current.json()
        if snapshot["status"] != "processing":
            wait_for_link_query_workers(client, query_id)
            return snapshot
        time.sleep(0.01)
    raise AssertionError(f"link query {query_id} did not reach a terminal state")


@pytest.mark.parametrize(
    ("input_url", "final_url", "platform"),
    [
        (
            "https://www.zhihu.com/question/123/answer/456",
            "https://www.zhihu.com/question/123/answer/456",
            SourcePlatform.ZHIHU,
        ),
        (
            "https://www.xiaohongshu.com/explore/example",
            "https://www.xiaohongshu.com/explore/example",
            SourcePlatform.XIAOHONGSHU,
        ),
        (
            "https://mp.weixin.qq.com/s/example",
            "https://mp.weixin.qq.com/s/example",
            SourcePlatform.WECHAT,
        ),
        (
            "https://example.com/post",
            "https://example.com/post",
            SourcePlatform.WEB,
        ),
    ],
)
def test_prepare_link_import_recognizes_article_platforms(
    monkeypatch: pytest.MonkeyPatch,
    input_url: str,
    final_url: str,
    platform: SourcePlatform,
) -> None:
    monkeypatch.setattr(
        link,
        "fetch_public_page",
        lambda _: link.PublicPage(final_url, _page_html()),
    )

    source = link.prepare_link_import(url=input_url, title=None, language="zh-CN")

    assert source.platform is platform
    assert source.kind is ContentKind.ARTICLE
    assert source.title == "公开内容标题"
    assert source.author == "测试作者"
    assert source.source_url == final_url
    assert source.thumbnail_url == "https://cdn.example.test/cover.jpg"
    assert source.transcript.source_kind == "public_page_text"


def test_zhihu_favorite_urls_are_collection_sources(tmp_path: Path) -> None:
    urls = (
        "https://www.zhihu.com/collections",
        "https://www.zhihu.com/collection/123456",
        "https://www.zhihu.com/collections/123456",
    )

    for url in urls:
        assert link._is_collection_url(url, SourcePlatform.ZHIHU)
        assert link.classify_source_type(url, SourcePlatform.ZHIHU) == "favorite"

    client = make_client(tmp_path)
    response = client.post("/api/v1/imports/probe", json={"url": urls[1]})

    assert response.status_code == 200
    assert response.json()["kind"] == "collection"
    assert response.json()["source_type"] == "favorite"
    assert response.json()["can_import"] is False
    assert "10" in response.json()["next_action"]


def test_zhihu_embedded_text_import_keeps_platform_and_original_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    install_fake_summary(monkeypatch)
    client = make_client(tmp_path)
    source_url = "https://www.zhihu.com/question/123/answer/456"
    response = client.post(
        "/api/v1/imports/local",
        json={
            "zhihu_source": {
                "url": source_url,
                "title": "测试回答",
                "author": "测试作者",
                "text": "这是从回答原文页读取的完整正文。",
            }
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["content"]["platform"] == "zhihu"
    assert payload["content"]["canonical_url"] == source_url
    assert payload["content"]["title"] == "测试回答"
    assert payload["content"]["author"] == "测试作者"


@pytest.mark.parametrize(
    ("input_url", "final_url", "platform"),
    [
        (
            "https://b23.tv/example",
            "https://www.bilibili.com/video/BV1example",
            SourcePlatform.BILIBILI,
        ),
        (
            "https://www.douyin.com/video/example",
            "https://www.douyin.com/video/example",
            SourcePlatform.DOUYIN,
        ),
        (
            "https://www.youtube.com/watch?v=example",
            "https://www.youtube.com/watch?v=example",
            SourcePlatform.YOUTUBE,
        ),
    ],
)
def test_video_platforms_fail_when_content_cannot_be_recognized(
    monkeypatch: pytest.MonkeyPatch,
    input_url: str,
    final_url: str,
    platform: SourcePlatform,
) -> None:
    """视频严禁以页面可见文字冒充总结；无字幕/转写时必须输出失败原因。"""

    monkeypatch.setattr(
        link,
        "fetch_public_page",
        lambda _: link.PublicPage(final_url, _page_html()),
    )

    with pytest.raises(link.LinkImportError, match="无法识别视频内容"):
        link.prepare_link_import(url=input_url, title=None, language="zh-CN")


def test_bilibili_material_keeps_video_duration() -> None:
    html = '''<script>window.__INITIAL_STATE__={"videoData":{"title":"视频标题","duration":120,"desc":"简介"}}</script>'''
    parser = link._PublicPageParser()
    parser.feed(html)
    parser.close()

    material = link._bilibili_video_material(parser, html)

    assert material is not None
    assert material.duration_seconds == 120.0


@pytest.mark.parametrize(
    ("code", "expected_status"),
    [(-101, "REAUTH_REQUIRED"), (-352, "RISK_CONTROLLED")],
)
def test_bilibili_subtitle_errors_keep_structured_connection_status(
    monkeypatch: pytest.MonkeyPatch,
    code: int,
    expected_status: str,
) -> None:
    monkeypatch.setattr(bilibili, "_merged_cookie", lambda _cookie: "")
    monkeypatch.setattr(bilibili, "_wbi_keys", lambda _cookies: ("i" * 32, "s" * 32))
    monkeypatch.setattr(
        bilibili,
        "_http_json",
        lambda *args, **kwargs: {"code": code, "message": "upstream"},
    )

    with pytest.raises(link.LinkImportError) as raised:
        bilibili.fetch_video_subtitle("BV1example", 123)

    assert raised.value.connection_status == expected_status


def test_bilibili_subtitle_network_error_has_no_durable_connection_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bilibili, "_merged_cookie", lambda _cookie: "")
    monkeypatch.setattr(bilibili, "_wbi_keys", lambda _cookies: ("i" * 32, "s" * 32))
    monkeypatch.setattr(
        bilibili,
        "_http_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(URLError("offline")),
    )

    with pytest.raises(link.LinkImportError) as raised:
        bilibili.fetch_video_subtitle("BV1example", 123)

    assert raised.value.connection_status is None


def test_link_import_runs_to_archive(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    install_fake_summary(monkeypatch)
    monkeypatch.setattr(
        link,
        "fetch_public_page",
        lambda _: link.PublicPage(
            "https://www.zhihu.com/question/123/answer/456",
            _page_html(),
        ),
    )
    client = make_client(tmp_path)

    response = client.post(
        "/api/v1/imports/link",
        json={"url": "https://www.zhihu.com/question/123/answer/456", "strength": "quick"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["content"]["platform"] == "zhihu"
    assert payload["content"]["author"] == "测试作者"
    assert payload["job"]["source_url"] == "https://www.zhihu.com/question/123/answer/456"
    assert payload["job"]["source_note"] == "已读取公开页面可见文字。"
    assert client.get(f"/api/v1/jobs/{payload['job']['id']}").json()["state"] == "completed"

    result = client.get(f"/api/v1/contents/{payload['content']['id']}/result")
    assert result.status_code == 200
    assert result.json()["record"]["source_platform"] == "zhihu"
    assert result.json()["record"]["source_url"] == "https://www.zhihu.com/question/123/answer/456"


def test_collection_link_is_not_treated_as_single_content() -> None:
    with pytest.raises(link.LinkImportError, match="博主页"):
        link.prepare_link_import(
            url="https://www.zhihu.com/people/test-author",
            title=None,
            language=None,
        )


def test_source_probe_describes_single_and_collection_links(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    single = client.post(
        "/api/v1/imports/probe",
        json={"url": "https://www.zhihu.com/question/123/answer/456"},
    )
    assert single.status_code == 200
    assert single.json()["kind"] == "single"
    # 2026-09-20 决策 D1：知乎未登录公开读取基本不可读，收缩为仅识别 + 降级导入。
    assert single.json()["can_import"] is False
    assert single.json()["source_type"] == "answer"
    assert single.json()["object_label"] == "回答"
    assert "本地文件" in single.json()["next_action"]
    assert single.json()["platform"] == "zhihu"

    collection = client.post(
        "/api/v1/imports/probe",
        json={"url": "https://space.bilibili.com/17849059"},
    )
    assert collection.status_code == 200
    assert collection.json()["kind"] == "collection"
    assert collection.json()["can_import"] is False
    assert collection.json()["source_type"] == "creator"
    assert collection.json()["object_label"] == "UP 主主页"
    assert "预览候选" in collection.json()["next_action"]


def test_link_query_validates_each_item_before_confirm_and_keeps_thumbnail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install_fake_summary(monkeypatch)

    def fake_prepare(*, url, title, language, bilibili_cookie, asr_configured, page_number=None):
        if "failed" in url:
            raise link.LinkImportError("该链接没有可读取的字幕")
        return [
            PreparedSource(
                kind=ContentKind.ARTICLE,
                title=f"标题 {url.rsplit('/', 1)[-1]}",
                transcript=Transcript(
                    "zh-CN",
                    "test",
                    "test",
                    (TranscriptSegment(0, 2, "这是一段足够长的测试内容。"),),
                ),
                content_hash=url,
                source_path=None,
                source_url=url,
                acquisition_method="test",
                platform=SourcePlatform.WEB,
                thumbnail_url=f"https://img.example.test/{url.rsplit('/', 1)[-1]}.jpg",
            )
        ]

    monkeypatch.setattr(main, "_prepare_link_sources", fake_prepare)
    client = make_client(tmp_path)
    urls = [
        "https://example.test/one",
        "https://example.test/two",
        "https://example.test/failed",
    ]

    query = client.post("/api/v1/imports/query", json={"urls": urls})

    assert query.status_code == 200
    query_payload = wait_for_link_query(client, query)
    assert [item["status"] for item in query_payload["items"]] == ["ready", "ready", "failed"]
    assert query_payload["items"][0]["thumbnail_url"] == "https://img.example.test/one.jpg"
    assert client.get("/api/v1/history").json() == []

    folder = client.post("/api/v1/favorite-folders", json={"name": "课程"}).json()
    ready_ids = [item["item_id"] for item in query_payload["items"] if item["selectable"]]
    confirmed = client.post(
        "/api/v1/imports/query/confirm",
        json={
            "query_id": query_payload["query_id"],
            "item_ids": ready_ids,
            "classify": True,
            "category": "课程",
            "favorite_folder_ids": [folder["id"]],
        },
    )

    assert confirmed.status_code == 201
    confirmed_payload = confirmed.json()
    assert len(confirmed_payload["accepted"]) == 2
    assert confirmed_payload["content"]["category"] == "课程"
    assert confirmed_payload["content"]["favorite_folder_ids"] == [folder["id"]]
    assert confirmed_payload["accepted"][0]["job"]["thumbnail_url"].endswith(".jpg")
    assert confirmed_payload["failed"] == []
    for accepted_item in confirmed_payload["accepted"]:
        stored_job = client.app.state.store.get_job(accepted_item["job"]["id"])
        assert stored_job.metadata["archive_batch_name"]


def test_link_query_uses_one_hour_expiry_boundary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install_fake_summary(monkeypatch)

    def fake_prepare(*, url, title, language, bilibili_cookie, asr_configured, page_number=None):
        return [
            PreparedSource(
                kind=ContentKind.ARTICLE,
                title="边界测试内容",
                transcript=Transcript(
                    "zh-CN",
                    "test",
                    "test",
                    (TranscriptSegment(0, 2, "这是一段足够长的边界测试内容。"),),
                ),
                content_hash=url,
                source_path=None,
                source_url=url,
                acquisition_method="test",
                platform=SourcePlatform.WEB,
            )
        ]

    monkeypatch.setattr(main, "_prepare_link_sources", fake_prepare)
    client = make_client(tmp_path)

    within_boundary = client.post(
        "/api/v1/imports/query",
        json={"urls": ["https://example.test/within-boundary"]},
    )
    assert within_boundary.status_code == 200
    within_payload = wait_for_link_query(client, within_boundary)
    client.app.state.link_queries[within_payload["query_id"]]["created_at"] = (
        datetime.now(UTC) - timedelta(seconds=LINK_QUERY_TTL_SECONDS - 1)
    )
    still_valid = client.post(
        "/api/v1/imports/query/confirm",
        json={
            "query_id": within_payload["query_id"],
            "item_ids": [within_payload["items"][0]["item_id"]],
        },
    )
    assert still_valid.status_code == 201

    past_boundary = client.post(
        "/api/v1/imports/query",
        json={"urls": ["https://example.test/past-boundary"]},
    )
    assert past_boundary.status_code == 200
    past_payload = wait_for_link_query(client, past_boundary)
    client.app.state.link_queries[past_payload["query_id"]]["created_at"] = (
        datetime.now(UTC) - timedelta(seconds=LINK_QUERY_TTL_SECONDS + 1)
    )
    expired = client.post(
        "/api/v1/imports/query/confirm",
        json={
            "query_id": past_payload["query_id"],
            "item_ids": [past_payload["items"][0]["item_id"]],
        },
    )
    assert expired.status_code == 404
    assert expired.json()["detail"] == "link_query_expired"


def test_link_query_keeps_failed_submission_for_retry_and_does_not_wrap_unclassified_batch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install_fake_summary(monkeypatch)

    def fake_prepare(*, url, title, language, bilibili_cookie, asr_configured, page_number=None):
        return [
            PreparedSource(
                kind=ContentKind.ARTICLE,
                title=f"标题 {url.rsplit('/', 1)[-1]}",
                transcript=Transcript(
                    "zh-CN",
                    "test",
                    "test",
                    (TranscriptSegment(0, 2, "这是一段足够长的测试内容。"),),
                ),
                content_hash=url,
                source_path=None,
                source_url=url,
                acquisition_method="test",
                platform=SourcePlatform.WEB,
            )
        ]

    monkeypatch.setattr(main, "_prepare_link_sources", fake_prepare)
    client = make_client(tmp_path)
    query = client.post(
        "/api/v1/imports/query",
        json={"urls": ["https://example.test/one", "https://example.test/two"]},
    )
    assert query.status_code == 200
    query_payload = wait_for_link_query(client, query)
    item_ids = [item["item_id"] for item in query_payload["items"]]

    original_submit = client.app.state.workflow.submit

    def flaky_submit(source, settings, **kwargs):
        if source.source_url.endswith("/two"):
            raise RuntimeError("模拟提交失败")
        return original_submit(source, settings, **kwargs)

    monkeypatch.setattr(client.app.state.workflow, "submit", flaky_submit)
    first_submit = client.post(
        "/api/v1/imports/query/confirm",
        json={"query_id": query_payload["query_id"], "item_ids": item_ids},
    )

    assert first_submit.status_code == 201
    first_payload = first_submit.json()
    assert len(first_payload["accepted"]) == 1
    assert [item["url"] for item in first_payload["failed"]] == [
        "https://example.test/two"
    ]
    stored_job = client.app.state.store.get_job(first_payload["accepted"][0]["job"]["id"])
    assert stored_job.metadata["archive_batch_name"] is None

    monkeypatch.setattr(client.app.state.workflow, "submit", original_submit)
    retry_id = next(
        item["item_id"]
        for item in query_payload["items"]
        if item["input_url"].endswith("/two")
    )
    retry = client.post(
        "/api/v1/imports/query/confirm",
        json={"query_id": query_payload["query_id"], "item_ids": [retry_id]},
    )

    assert retry.status_code == 201
    assert len(retry.json()["accepted"]) == 1
    assert retry.json()["failed"] == []


def test_r7_restricted_source_reaches_failed_query_terminal_with_login_guidance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def restricted_prepare(**_kwargs):
        raise link.LinkImportError("B站读取受限，请在设置页使用 B站二维码登录后重试")

    monkeypatch.setattr(main, "_prepare_link_sources", restricted_prepare)
    client = make_client(tmp_path)

    started = client.post(
        "/api/v1/imports/query",
        json={"urls": ["https://www.bilibili.com/video/BV-restricted"]},
    )
    payload = wait_for_link_query(client, started)

    assert LINK_QUERY_DEADLINE_SECONDS == 180
    assert payload["status"] == "completed"
    assert payload["items"][0]["status"] == "failed"
    assert payload["items"][0]["selectable"] is False
    assert "登录" in payload["items"][0]["reason"]


def test_r8_mixed_query_isolates_success_from_failed_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def mixed_prepare(*, url, **_kwargs):
        if url.endswith("/restricted"):
            raise link.LinkImportError("来源读取受限")
        return [
            PreparedSource(
                kind=ContentKind.ARTICLE,
                title="可用来源",
                transcript=Transcript(
                    "zh-CN",
                    "test",
                    "test",
                    (TranscriptSegment(0, 2, "成功来源保持独立。"),),
                ),
                content_hash="r8-success",
                source_path=None,
                source_url=url,
                acquisition_method="test",
                platform=SourcePlatform.WEB,
            )
        ]

    monkeypatch.setattr(main, "_prepare_link_sources", mixed_prepare)
    client = make_client(tmp_path)
    client.app.state.job_queue.submit = lambda *_args, **_kwargs: None
    query = client.post(
        "/api/v1/imports/query",
        json={"urls": ["https://example.test/success", "https://example.test/restricted"]},
    )
    payload = wait_for_link_query(client, query)

    assert [item["status"] for item in payload["items"]] == ["ready", "failed"]
    ready = next(item for item in payload["items"] if item["status"] == "ready")
    confirmed = client.post(
        "/api/v1/imports/query/confirm",
        json={"query_id": payload["query_id"], "item_ids": [ready["item_id"]]},
    )

    assert confirmed.status_code == 201
    assert len(confirmed.json()["accepted"]) == 1
    assert len(client.app.state.store.list_jobs()) == 1


def test_r10_source_collection_name_never_auto_maps_product_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def source_prepare(*, url, **_kwargs):
        return [
            PreparedSource(
                kind=ContentKind.ARTICLE,
                title="同名来源收藏夹内容",
                transcript=Transcript(
                    "zh-CN",
                    "test",
                    "test",
                    (TranscriptSegment(0, 2, "来源集合不等于产品收藏夹。"),),
                ),
                content_hash="r10-source-folder",
                source_path=None,
                source_url=url,
                acquisition_method="bilibili_favorite",
                platform=SourcePlatform.BILIBILI,
            )
        ]

    monkeypatch.setattr(main, "_prepare_link_sources", source_prepare)
    client = make_client(tmp_path)
    product_folder = client.post(
        "/api/v1/favorite-folders", json={"name": "同名来源收藏夹"}
    ).json()
    client.app.state.job_queue.submit = lambda *_args, **_kwargs: None
    query = client.post(
        "/api/v1/imports/query",
        json={"urls": ["https://www.bilibili.com/list/favorite"]},
    )
    payload = wait_for_link_query(client, query)
    item = payload["items"][0]
    confirmed = client.post(
        "/api/v1/imports/query/confirm",
        json={"query_id": payload["query_id"], "item_ids": [item["item_id"]]},
    )

    assert confirmed.status_code == 201
    content = confirmed.json()["accepted"][0]["content"]
    assert content["favorite_folder_ids"] == []
    folders = {folder["id"]: folder for folder in client.get("/api/v1/favorite-folders").json()}
    assert folders[product_folder["id"]]["content_count"] == 0


def test_link_query_exposes_folder_association_retry_without_creating_duplicate_task(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install_fake_summary(monkeypatch)

    def fake_prepare(*, url, title, language, bilibili_cookie, asr_configured, page_number=None):
        return [
            PreparedSource(
                kind=ContentKind.ARTICLE,
                title="需要归类的内容",
                transcript=Transcript(
                    "zh-CN",
                    "test",
                    "test",
                    (TranscriptSegment(0, 2, "这是一段足够长的测试内容。"),),
                ),
                content_hash=url,
                source_path=None,
                source_url=url,
                acquisition_method="test",
                platform=SourcePlatform.WEB,
            )
        ]

    monkeypatch.setattr(main, "_prepare_link_sources", fake_prepare)
    client = make_client(tmp_path)
    folder = client.post("/api/v1/favorite-folders", json={"name": "重试归类"}).json()
    query = client.post(
        "/api/v1/imports/query",
        json={"urls": ["https://example.test/association-retry"]},
    )
    item_id = query.json()["items"][0]["item_id"]

    store = client.app.state.store
    original_update = store.update_content
    fail_once = True

    def fail_folder_write(content_id, **kwargs):
        nonlocal fail_once
        if fail_once and kwargs.get("favorite_folder_ids") == [folder["id"]]:
            fail_once = False
            raise RuntimeError("模拟收藏夹关联失败")
        return original_update(content_id, **kwargs)

    monkeypatch.setattr(store, "update_content", fail_folder_write)
    monkeypatch.setattr(client.app.state.job_queue, "submit", lambda *args, **kwargs: None)
    first = client.post(
        "/api/v1/imports/query/confirm",
        json={
            "query_id": query.json()["query_id"],
            "item_ids": [item_id],
            "classify": True,
            "favorite_folder_ids": [folder["id"]],
        },
    )

    assert first.status_code == 201
    payload = first.json()
    assert len(payload["accepted"]) == 1
    assert payload["failed"] == []
    assert len(payload["association_failures"]) == 1
    failure = payload["association_failures"][0]
    assert failure["content"]["id"] == payload["accepted"][0]["content"]["id"]
    assert failure["job"]["id"] == payload["accepted"][0]["job"]["id"]
    assert failure["folder_ids"] == [folder["id"]]
    job_count = len(store.list_jobs())

    restored = client.patch(
        f"/api/v1/contents/{failure['content']['id']}",
        json={"favorite_folder_ids": failure["folder_ids"]},
    )

    assert restored.status_code == 200
    assert restored.json()["favorite_folder_ids"] == [folder["id"]]
    assert len(store.list_jobs()) == job_count

def test_invalid_link_returns_a_clear_api_error(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.post("/api/v1/imports/link", json={"url": "not-a-url"})

    assert response.status_code == 422
    assert "完整" in response.json()["detail"]


def _page_html() -> str:
    return """
    <html lang="zh-CN">
      <head>
        <title>页面标题</title>
        <meta property="og:title" content="公开内容标题" />
        <meta property="og:image" content="https://cdn.example.test/cover.jpg" />
        <meta property="article:author" content="测试作者" />
        <meta name="description" content="这是一段公开内容的简短说明。" />
      </head>
      <body>
        <article>
          这是一段足够长的公开正文，用于验证链接导入会读取页面中的可见文字，并将它交给现有的总结和归档流程。
          正文保留来源链接和作者，方便以后回到原页面核对内容。
        </article>
      </body>
    </html>
    """
def test_fetch_public_page_decompresses_gzip(monkeypatch: pytest.MonkeyPatch) -> None:
    import gzip

    class FakeResponse:
        headers = {"Content-Type": "text/html", "Content-Encoding": "gzip"}

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def geturl(self) -> str:
            return "https://www.bilibili.com/video/BV1GKgM6qEar/"

        def read(self, _limit: int = -1) -> bytes:
            return gzip.compress("<html><title>测试标题</title></html>".encode("utf-8"))

    monkeypatch.setattr(link, "urlopen", lambda _request, timeout: FakeResponse())

    page = link.fetch_public_page("https://www.bilibili.com/video/BV1GKgM6qEar/")

    assert "测试标题" in page.html


_BILIBILI_VIDEO_HTML = """
<html lang="zh-CN">
  <head>
    <title>页面标题</title>
    <meta property="og:title" content="og标题" />
    <meta name="description" content="meta描述内容" />
    <link rel="canonical" href="https://www.bilibili.com/video/BV1GKgM6qEar" />
    <script>window.__INITIAL_STATE__={"bvid":"BV1GKgM6qEar","videoData":{"title":"真实视频标题","bvid":"BV1GKgM6qEar","cid":12345,"owner":{"name":"测试UP主","mid":1},"desc":"这是视频的详细简介，描述了视频的主要内容与知识点。","stat":{"view":1000,"like":10}},"upData":{"sign":"作者个人简介"},"tags":[{"tag_name":"AI"},{"tag_name":"教程"}]};(function(){})();</script>
  </head>
  <body>
    <nav>首页 番剧 直播</nav>
    <article>页面正文噪音文字</article>
  </body>
</html>
"""


def test_bilibili_video_without_subtitle_fails_with_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.adapters.sources import bilibili

    monkeypatch.setattr(
        link,
        "fetch_public_page",
        lambda _: link.PublicPage(
            "https://www.bilibili.com/video/BV1GKgM6qEar/",
            _BILIBILI_VIDEO_HTML,
        ),
    )
    monkeypatch.setattr(
        bilibili,
        "fetch_video_subtitle",
        lambda bvid, cid, cookie=None: None,
    )

    with pytest.raises(link.LinkImportError, match="无法识别视频内容"):
        link.prepare_link_import(
            url="https://www.bilibili.com/video/BV1GKgM6qEar/",
            title=None,
            language="zh-CN",
        )


def test_bilibili_favlist_and_medialist_are_collection_urls() -> None:
    with pytest.raises(link.LinkImportError, match="收藏夹"):
        link.prepare_link_import(
            url="https://space.bilibili.com/17849059/favlist?fid=123",
            title=None,
            language=None,
        )
    with pytest.raises(link.LinkImportError, match="不是单条内容"):
        link.prepare_link_import(
            url="https://www.bilibili.com/medialist/detail/ml123",
            title=None,
            language=None,
        )



def test_bilibili_text_link_is_imported_as_article(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = """<html><head><title>图文标题</title></head><body>
    这是 B站 图文正文，包含足够长的公开内容，用于验证文字链接不会被误判成视频。
    </body></html>"""
    monkeypatch.setattr(
        link,
        "fetch_public_page",
        lambda url: link.PublicPage(url, html),
    )
    source = link.prepare_link_import(
        url="https://www.bilibili.com/opus/123456",
        title=None,
        language="zh-CN",
    )
    assert source.kind is ContentKind.ARTICLE
    assert source.transcript is not None
    assert "图文正文" in " ".join(segment.text for segment in source.transcript.segments)

def test_bilibili_space_link_reports_actionable_hint() -> None:
    with pytest.raises(link.LinkImportError, match="UP主主页"):
        link.prepare_link_import(
            url="https://space.bilibili.com/17849059",
            title=None,
            language=None,
        )


def test_space_preview_endpoint_returns_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.adapters.sources import bilibili
    from app.api import main as api_main

    monkeypatch.setattr(
        api_main,
        "fetch_up_card",
        lambda mid, cookie=None: bilibili.UpCard(mid=mid, name="测试UP主", archive_count=22),
    )
    monkeypatch.setattr(
        api_main,
        "enumerate_space_videos",
        lambda mid, page=1, cookie=None: (
            [
                bilibili.SpaceVideo(
                    bvid="BV1GKgM6qEar",
                    title="视频一",
                    url="https://www.bilibili.com/video/BV1GKgM6qEar",
                    duration_seconds=120.0,
                    published_at="2026-08-15",
                )
            ],
            22,
        ),
    )
    client = make_client(tmp_path)

    response = client.post(
        "/api/v1/imports/bilibili/space/preview",
        json={"url": "https://space.bilibili.com/17849059"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["up_name"] == "测试UP主"
    assert payload["total"] == 22
    assert payload["candidates"][0]["bvid"] == "BV1GKgM6qEar"



def test_bilibili_season_link_classifies_as_collection_and_scans_only_the_season(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import main as api_main

    season_url = "https://space.bilibili.com/17849059/lists?sid=8291412"
    assert link.classify_source_type(season_url, SourcePlatform.BILIBILI) == "collection"
    assert bilibili.parse_season_id(season_url) == 8291412
    assert "合集" in link._collection_url_hint(season_url, SourcePlatform.BILIBILI)

    monkeypatch.setattr(api_main, "CREATOR_SCAN_PAGE_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(
        api_main,
        "fetch_up_card",
        lambda *args, **kwargs: pytest.fail("合集扫描不应读取 UP 主名片"),
    )
    monkeypatch.setattr(
        api_main,
        "enumerate_space_videos",
        lambda *args, **kwargs: pytest.fail("合集扫描不应读取 UP 主全量投稿"),
    )
    calls = []

    def fake_season(mid, season_id, page=1, cookie=None):
        calls.append((mid, season_id, page))
        return (
            [
                bilibili.SpaceVideo(
                    "BV1", "合集视频一", "https://www.bilibili.com/video/BV1", 60, "2026-08-15"
                )
            ],
            1,
            "Agent理论研究",
        )

    monkeypatch.setattr(api_main, "enumerate_season_videos", fake_season)
    client = make_client(tmp_path)
    start = client.post("/api/v1/imports/bilibili/creator-scans", json={"url": season_url})
    assert start.status_code == 202
    scan_id = start.json()["scan_id"]

    payload = None
    for _ in range(30):
        payload = client.get(f"/api/v1/imports/bilibili/creator-scans/{scan_id}").json()
        if payload["status"] == "completed":
            break
        time.sleep(0.01)
    assert payload["status"] == "completed"
    assert payload["source_type"] == "collection"
    assert payload["up_name"] == "Agent理论研究"
    assert payload["total"] == 1
    assert [item["bvid"] for item in payload["candidates"]] == ["BV1"]
    assert calls == [(17849059, 8291412, 1)]


def test_enumerate_season_videos_reads_the_season_api(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_http_json(url, *, referer=None, extra_headers=None):
        captured["url"] = url
        captured["referer"] = referer
        return {
            "code": 0,
            "data": {
                "meta": {"name": "合集·Agent理论研究", "total": 2},
                "archives": [
                    {
                        "bvid": "BV1",
                        "title": "视频一",
                        "duration": 601,
                        "pic": "http://i1.hdslb.com/a.jpg",
                        "pubdate": 1778258552,
                    },
                    {"bvid": "BV2", "title": "视频二", "duration": 60, "pic": "//i2.hdslb.com/b.jpg"},
                ],
            },
        }

    monkeypatch.setattr(bilibili, "_http_json", fake_http_json)
    monkeypatch.setattr(bilibili, "_merged_cookie", lambda cookie: "SESSDATA=x")

    videos, total, title = bilibili.enumerate_season_videos(17849059, 8291412)

    assert total == 2
    assert title == "Agent理论研究"
    assert "seasons_archives_list" in captured["url"]
    assert "season_id=8291412" in captured["url"]
    assert [video.bvid for video in videos] == ["BV1", "BV2"]
    assert videos[0].duration_seconds == 601.0
    assert videos[0].published_at == "2026-05-09"
    assert videos[0].thumbnail_url == "https://i1.hdslb.com/a.jpg"
    assert videos[1].thumbnail_url == "https://i2.hdslb.com/b.jpg"
    assert videos[1].published_at is None


def test_creator_scan_is_paginated_and_returns_duplicate_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.adapters.sources import bilibili
    from app.api import main as api_main

    monkeypatch.setattr(api_main, "CREATOR_SCAN_PAGE_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(
        api_main,
        "fetch_up_card",
        lambda mid, cookie=None: bilibili.UpCard(mid=mid, name="测试UP主", archive_count=3),
    )
    calls = []

    def fake_enumerate(mid, page=1, cookie=None):
        calls.append(page)
        items = [
            bilibili.SpaceVideo("BV1", "视频一", "https://www.bilibili.com/video/BV1", 60, "2026-08-15"),
            bilibili.SpaceVideo("BV2", "视频二", "https://www.bilibili.com/video/BV2", 120, "2026-08-14"),
        ] if page == 1 else [
            bilibili.SpaceVideo("BV3", "视频三", "https://www.bilibili.com/video/BV3", 180, "2026-08-13"),
        ]
        return items, 3

    monkeypatch.setattr(api_main, "enumerate_space_videos", fake_enumerate)
    client = make_client(tmp_path)
    start = client.post(
        "/api/v1/imports/bilibili/creator-scans",
        json={"url": "https://space.bilibili.com/17849059"},
    )
    assert start.status_code == 202
    scan_id = start.json()["scan_id"]

    payload = None
    for _ in range(30):
        payload = client.get(f"/api/v1/imports/bilibili/creator-scans/{scan_id}").json()
        if payload["status"] == "completed":
            break
        time.sleep(0.01)
    assert payload["status"] == "completed"
    assert payload["up_name"] == "测试UP主"
    assert payload["fetched_count"] == 3
    assert [item["bvid"] for item in payload["candidates"]] == ["BV1", "BV2", "BV3"]
    assert calls == [1, 2]


def test_creator_scan_stops_at_page_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.adapters.sources import bilibili
    from app.api import main as api_main

    monkeypatch.setattr(api_main, "CREATOR_SCAN_PAGE_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(api_main, "CREATOR_SCAN_MAX_PAGES", 2)
    monkeypatch.setattr(
        api_main,
        "fetch_up_card",
        lambda mid, cookie=None: bilibili.UpCard(mid=mid, name="测试UP主", archive_count=100),
    )
    calls = []

    def fake_enumerate(mid, page=1, cookie=None):
        calls.append(page)
        return (
            [
                bilibili.SpaceVideo(
                    f"BV{page}",
                    f"视频{page}",
                    f"https://www.bilibili.com/video/BV{page}",
                    60,
                    "2026-08-15",
                )
            ],
            100,
        )

    monkeypatch.setattr(api_main, "enumerate_space_videos", fake_enumerate)
    client = make_client(tmp_path)
    start = client.post(
        "/api/v1/imports/bilibili/creator-scans",
        json={"url": "https://space.bilibili.com/17849059"},
    )
    assert start.status_code == 202
    scan_id = start.json()["scan_id"]

    payload = None
    for _ in range(50):
        payload = client.get(f"/api/v1/imports/bilibili/creator-scans/{scan_id}").json()
        if payload["status"] == "completed":
            break
        time.sleep(0.01)

    assert payload["status"] == "completed"
    assert calls == [1, 2]
    assert payload["fetched_count"] == 2
    assert payload["skipped_count"] == 98
    assert payload["error"] is None


def test_favorite_scan_returns_selectable_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.adapters.sources import bilibili
    from app.api import main as api_main

    monkeypatch.setattr(
        api_main,
        "enumerate_favorite_videos",
        lambda favorite_id, page=1, cookie=None: (
            [bilibili.SpaceVideo("BV1", "收藏的视频", "https://www.bilibili.com/video/BV1", 60, "2026-08-15")],
            1,
            "测试收藏夹",
        ),
    )
    client = make_client(tmp_path)
    start = client.post(
        "/api/v1/imports/bilibili/favorite-scans",
        json={"url": "https://space.bilibili.com/17849059/favlist?fid=123"},
    )
    assert start.status_code == 202
    scan_id = start.json()["scan_id"]

    payload = None
    for _ in range(30):
        payload = client.get(f"/api/v1/imports/bilibili/favorite-scans/{scan_id}").json()
        if payload["status"] == "completed":
            break
        time.sleep(0.01)
    assert payload["status"] == "completed"
    assert payload["source_type"] == "favorite"
    assert payload["up_name"] == "测试收藏夹"
    assert payload["candidates"][0]["bvid"] == "BV1"
    assert client.app.state.store.list_jobs() == []


def test_bilibili_favorite_folder_directory_requires_session_and_preserves_folder_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import main as api_main

    client = make_client(tmp_path)
    monkeypatch.setattr(api_main, "_bilibili_cookie", lambda store: "SESSDATA=verified")
    monkeypatch.setattr(
        api_main,
        "enumerate_favorite_folders",
        lambda cookie: [
            SimpleNamespace(id=101, title="A 类", media_count=12),
            SimpleNamespace(id=102, title="二类", media_count=3),
        ],
        raising=False,
    )

    response = client.get("/api/v1/imports/bilibili/favorite-folders")

    assert response.status_code == 200
    assert response.json() == [
        {"id": 101, "title": "A 类", "media_count": 12},
        {"id": 102, "title": "二类", "media_count": 3},
    ]


def test_bilibili_favorite_folder_directory_requires_saved_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import main as api_main

    monkeypatch.setattr(api_main, "_bilibili_cookie", lambda store: None)
    client = make_client(tmp_path)

    response = client.get("/api/v1/imports/bilibili/favorite-folders")

    assert response.status_code == 401
    assert "登录" in response.json()["detail"]


def test_favorite_scan_reports_bvid_multi_part_import_and_job_states(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import main as api_main
    from app.domain.jobs import JobState
    from app.domain.models import AnalysisSettings

    monkeypatch.setattr(
        api_main,
        "enumerate_favorite_videos",
        lambda favorite_id, page=1, cookie=None: (
            [
                bilibili.SpaceVideo(
                    "BVmulti123",
                    "多 P 收藏视频",
                    "https://www.bilibili.com/video/BVmulti123",
                    180,
                    "2026-08-15",
                    page_count=3,
                )
            ],
            1,
            "多 P 收藏夹",
        ),
    )
    client = make_client(tmp_path)
    store = client.app.state.store

    imported = store.create_content(
        kind=ContentKind.VIDEO,
        title="多 P 收藏视频 - P1",
        platform=SourcePlatform.BILIBILI,
        canonical_url="https://www.bilibili.com/video/BVmulti123/?p=1",
        content_hash="bvid-part-1",
    )
    _run, imported_job = store.create_analysis_run(imported.id, AnalysisSettings(model="test"))
    for target in (
        JobState.ACQUIRING,
        JobState.EXTRACTING,
        JobState.TRANSCRIBING,
        JobState.CHUNKING,
        JobState.SUMMARIZING,
        JobState.ARCHIVING,
        JobState.INDEXING,
        JobState.COMPLETED,
    ):
        imported_job.transition(target)
    store.save_job(imported_job)
    store.upsert_summary(imported.id, "已完成的 P1 摘要")

    failed = store.create_content(
        kind=ContentKind.VIDEO,
        title="多 P 收藏视频 - P2",
        platform=SourcePlatform.BILIBILI,
        canonical_url="https://www.bilibili.com/video/BVmulti123?p=2",
        content_hash="bvid-part-2",
    )
    _run, failed_job = store.create_analysis_run(failed.id, AnalysisSettings(model="test"))
    failed_job.transition(JobState.ACQUIRING)
    failed_job.transition(JobState.FAILED)
    store.save_job(failed_job)

    start = client.post(
        "/api/v1/imports/bilibili/favorite-scans",
        json={"url": "https://space.bilibili.com/17849059/favlist?fid=123"},
    )
    scan_id = start.json()["scan_id"]
    payload = None
    for _ in range(30):
        payload = client.get(f"/api/v1/imports/bilibili/favorite-scans/{scan_id}").json()
        if payload["status"] == "completed":
            break
        time.sleep(0.01)

    candidate = payload["candidates"][0]
    assert candidate["duplicate_status"] == "failed"
    assert candidate["selectable"] is True
    assert candidate["page_count"] == 3
    assert candidate["imported_page_count"] == 1
    assert candidate["part_statuses"] == ["summarized", "failed", "new"]


def test_bilibili_import_state_keeps_unknown_page_count_partial_and_reads_active_job(
    tmp_path: Path,
) -> None:
    from app.domain.jobs import JobState
    from app.domain.models import AnalysisSettings

    client = make_client(tmp_path)
    store = client.app.state.store
    content = store.create_content(
        kind=ContentKind.VIDEO,
        title="未知 P 数的视频 - P1",
        platform=SourcePlatform.BILIBILI,
        canonical_url="https://www.bilibili.com/video/BVunknown123?p=1",
        content_hash="unknown-page-count-part",
    )
    _run, completed_job = store.create_analysis_run(content.id, AnalysisSettings(model="test"))
    for target in (
        JobState.ACQUIRING,
        JobState.EXTRACTING,
        JobState.TRANSCRIBING,
        JobState.CHUNKING,
        JobState.SUMMARIZING,
        JobState.ARCHIVING,
        JobState.INDEXING,
        JobState.COMPLETED,
    ):
        completed_job.transition(target)
    store.save_job(completed_job)
    store.upsert_summary(content.id, "P1 已完成")

    unknown_state = store.get_bilibili_video_import_state("BVunknown123", None)
    assert unknown_state["duplicate_status"] == "new"
    assert unknown_state["page_count"] is None
    assert unknown_state["imported_page_count"] == 1

    active = store.create_content(
        kind=ContentKind.VIDEO,
        title="排队中的视频",
        platform=SourcePlatform.BILIBILI,
        canonical_url="https://www.bilibili.com/video/BVactive123?p=1",
        content_hash="active-part",
    )
    _run, active_job = store.create_analysis_run(active.id, AnalysisSettings(model="test"))
    active_job.transition(JobState.ACQUIRING)
    store.save_job(active_job)

    active_state = store.get_bilibili_video_import_state("BVactive123", 1)
    assert active_state["duplicate_status"] == "processing"
    assert active_state["part_statuses"] == ["processing"]


def test_watchlater_scan_returns_https_candidates_and_thumbnails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.adapters.sources import bilibili
    from app.api import main as api_main

    monkeypatch.setattr(
        api_main,
        "enumerate_watchlater_videos",
        lambda page=1, cookie=None: (
            [
                bilibili.SpaceVideo(
                    "BV1",
                    "稍后的视频",
                    "bilibili://video/BV1",
                    60,
                    "2026-08-15",
                    "https://img.example.test/watchlater.jpg",
                )
            ],
            1,
        ),
    )
    client = make_client(tmp_path)
    start = client.post(
        "/api/v1/imports/bilibili/watchlater-scans",
        json={"url": "https://www.bilibili.com/watchlater"},
    )
    assert start.status_code == 202
    scan_id = start.json()["scan_id"]

    payload = None
    for _ in range(30):
        payload = client.get(f"/api/v1/imports/bilibili/watchlater-scans/{scan_id}").json()
        if payload["status"] == "completed":
            break
        time.sleep(0.01)

    assert payload["status"] == "completed"
    assert payload["source_type"] == "watchlater"
    assert payload["candidates"][0]["url"] == "https://www.bilibili.com/video/BV1"
    assert payload["candidates"][0]["thumbnail_url"] == "https://img.example.test/watchlater.jpg"


def test_watchlater_candidate_uses_https_bvid_and_creates_one_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_summary(monkeypatch)
    from app.adapters.sources import bilibili
    from app.api import main as api_main

    monkeypatch.setattr(
        api_main,
        "enumerate_watchlater_videos",
        lambda page=1, cookie=None: (
            [
                bilibili.SpaceVideo(
                    "BV-watchlater",
                    "稍后解析的视频",
                    "bilibili://video/BV-watchlater",
                    60,
                    "2026-08-15",
                )
            ],
            1,
        ),
    )
    monkeypatch.setattr(
        main,
        "_prepare_link_sources",
        lambda **kwargs: [
            PreparedSource(
                kind=ContentKind.ARTICLE,
                title="稍后解析的视频",
                transcript=Transcript(
                    "zh-CN",
                    "test",
                    "test",
                    (TranscriptSegment(0, 2, "这是一段足够长的测试内容。"),),
                ),
                content_hash=kwargs["url"],
                source_path=None,
                source_url=kwargs["url"],
                acquisition_method="test",
                platform=SourcePlatform.BILIBILI,
            )
        ],
    )
    client = make_client(tmp_path)
    monkeypatch.setattr(client.app.state.job_queue, "submit", lambda *args, **kwargs: None)

    started = client.post(
        "/api/v1/imports/bilibili/watchlater-scans",
        json={"url": "https://www.bilibili.com/watchlater"},
    )
    scan_id = started.json()["scan_id"]
    scan = None
    for _ in range(30):
        scan = client.get(f"/api/v1/imports/bilibili/watchlater-scans/{scan_id}").json()
        if scan["status"] == "completed":
            break
        time.sleep(0.01)
    assert scan["status"] == "completed"
    assert scan["candidates"][0]["url"] == "https://www.bilibili.com/video/BV-watchlater"

    query = client.post(
        "/api/v1/imports/query",
        json={"urls": [scan["candidates"][0]["url"]]},
    )
    payload = wait_for_link_query(client, query)
    item = payload["items"][0]
    confirmed = client.post(
        "/api/v1/imports/query/confirm",
        json={"query_id": query.json()["query_id"], "item_ids": [item["item_id"]]},
    )

    assert confirmed.status_code == 201
    payload = confirmed.json()
    assert len(payload["accepted"]) == 1
    assert payload["accepted"][0]["content"]["canonical_url"] == scan["candidates"][0]["url"]


def test_favorite_scan_candidate_can_be_confirmed_into_a_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_summary(monkeypatch)
    from app.adapters.sources import bilibili
    from app.api import main as api_main

    monkeypatch.setattr(
        api_main,
        "enumerate_favorite_videos",
        lambda favorite_id, page=1, cookie=None: (
            [bilibili.SpaceVideo("BV1", "收藏的视频", "https://www.bilibili.com/video/BV1", 60, "2026-08-15")],
            1,
            "测试收藏夹",
        ),
    )

    monkeypatch.setattr(
        main,
        "_prepare_link_sources",
        lambda **kwargs: [
            PreparedSource(
                kind=ContentKind.ARTICLE,
                title="收藏的视频",
                transcript=Transcript(
                    "zh-CN",
                    "test",
                    "test",
                    (TranscriptSegment(0, 2, "这是一段足够长的测试内容。"),),
                ),
                content_hash="favorite-candidate",
                source_path=None,
                source_url=kwargs["url"],
                acquisition_method="test",
                platform=SourcePlatform.BILIBILI,
            )
        ],
    )
    client = make_client(tmp_path)
    start = client.post(
        "/api/v1/imports/bilibili/favorite-scans",
        json={"url": "https://space.bilibili.com/17849059/favlist?fid=123"},
    )
    scan_id = start.json()["scan_id"]
    scan = None
    for _ in range(30):
        scan = client.get(f"/api/v1/imports/bilibili/favorite-scans/{scan_id}").json()
        if scan["status"] == "completed":
            break
        time.sleep(0.01)
    assert scan["status"] == "completed"

    query = client.post(
        "/api/v1/imports/query",
        json={"urls": [scan["candidates"][0]["url"]]},
    )
    assert query.status_code == 200
    query_payload = wait_for_link_query(client, query)
    item = query_payload["items"][0]
    assert item["selectable"] is True

    confirmed = client.post(
        "/api/v1/imports/query/confirm",
        json={"query_id": query_payload["query_id"], "item_ids": [item["item_id"]]},
    )
    assert confirmed.status_code == 201
    payload = confirmed.json()
    assert len(payload["accepted"]) == 1
    assert payload["accepted"][0]["content"]["canonical_url"] == scan["candidates"][0]["url"]


def test_favorite_scan_error_keeps_favorite_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import main as api_main

    def fail_favorite_scan(favorite_id, page=1, cookie=None):
        raise link.LinkImportError("B站收藏夹需要登录")

    monkeypatch.setattr(api_main, "enumerate_favorite_videos", fail_favorite_scan)
    client = make_client(tmp_path)
    start = client.post(
        "/api/v1/imports/bilibili/favorite-scans",
        json={"url": "https://space.bilibili.com/17849059/favlist?fid=123"},
    )
    scan_id = start.json()["scan_id"]
    payload = None
    for _ in range(30):
        payload = client.get(f"/api/v1/imports/bilibili/favorite-scans/{scan_id}").json()
        if payload["status"] == "failed":
            break
        time.sleep(0.01)
    assert payload["status"] == "failed"
    assert "收藏夹" in payload["error"]["user_message"]
    assert "UP 主" not in payload["error"]["user_message"]


def test_favorite_scan_cancel_wins_before_completion_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.adapters.sources import bilibili
    from app.api import main as api_main

    page_check_reached = Event()
    allow_finalization = Event()
    worker_passed_finalization_gate = Event()

    client = make_client(tmp_path)

    class CancelledTotal(int):
        def __new__(cls) -> "CancelledTotal":
            return int.__new__(cls, 1)

        def __le__(self, other: object) -> bool:
            # This comparison runs after the page lock is released and before
            # the worker's final completed-state write.
            page_check_reached.set()
            if not allow_finalization.wait(1):
                raise RuntimeError("test did not release favorite scan finalization")
            worker_passed_finalization_gate.set()
            return int.__le__(self, other)

    monkeypatch.setattr(
        api_main,
        "enumerate_favorite_videos",
        lambda favorite_id, page=1, cookie=None: (
            [bilibili.SpaceVideo("BV1", "收藏的视频", "https://www.bilibili.com/video/BV1", 60, "2026-08-15")],
            CancelledTotal(),
            "测试收藏夹",
        ),
    )
    start = client.post(
        "/api/v1/imports/bilibili/favorite-scans",
        json={"url": "https://space.bilibili.com/17849059/favlist?fid=123"},
    )
    scan_id = start.json()["scan_id"]
    assert page_check_reached.wait(1)
    cancelled = client.delete(f"/api/v1/imports/bilibili/favorite-scans/{scan_id}")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    allow_finalization.set()
    assert worker_passed_finalization_gate.wait(1)
    worker = next((thread for thread in list_threads() if thread.name == scan_id), None)
    if worker is not None:
        worker.join(1)
        assert not worker.is_alive()
    payload = client.get(f"/api/v1/imports/bilibili/favorite-scans/{scan_id}").json()
    assert payload["status"] == "cancelled"
    assert payload["error"]["code"] == "SCAN_CANCELLED"


def test_favorite_scan_cancel_wins_before_error_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import main as api_main

    started = Event()
    release = Event()
    worker_reached_error = Event()

    def fail_after_cancel(favorite_id, page=1, cookie=None):
        started.set()
        release.wait(1)
        worker_reached_error.set()
        raise link.LinkImportError("B站收藏夹读取失败")

    monkeypatch.setattr(api_main, "enumerate_favorite_videos", fail_after_cancel)
    client = make_client(tmp_path)
    start = client.post(
        "/api/v1/imports/bilibili/favorite-scans",
        json={"url": "https://space.bilibili.com/17849059/favlist?fid=123"},
    )
    scan_id = start.json()["scan_id"]
    assert started.wait(1)

    cancelled = client.delete(f"/api/v1/imports/bilibili/favorite-scans/{scan_id}")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    release.set()

    assert worker_reached_error.wait(1)
    worker = next((thread for thread in list_threads() if thread.name == scan_id), None)
    if worker is not None:
        worker.join(1)
        assert not worker.is_alive()
    payload = client.get(f"/api/v1/imports/bilibili/favorite-scans/{scan_id}").json()
    assert payload["status"] == "cancelled"
    assert payload["error"]["code"] == "SCAN_CANCELLED"


def test_creator_scan_reuses_active_request_and_can_cancel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.adapters.sources import bilibili
    from app.api import main as api_main

    started = Event()
    release = Event()

    def slow_card(mid, cookie=None):
        started.set()
        release.wait(1)
        return bilibili.UpCard(mid=mid, name="测试UP主", archive_count=0)

    monkeypatch.setattr(api_main, "fetch_up_card", slow_card)
    client = make_client(tmp_path)
    body = {"url": "https://space.bilibili.com/17849059"}
    first = client.post("/api/v1/imports/bilibili/creator-scans", json=body)
    assert first.status_code == 202
    scan_id = first.json()["scan_id"]
    assert started.wait(1)

    duplicate = client.post("/api/v1/imports/bilibili/creator-scans", json=body)
    assert duplicate.status_code == 202
    assert duplicate.json()["scan_id"] == scan_id

    cancelled = client.delete(f"/api/v1/imports/bilibili/creator-scans/{scan_id}")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    release.set()
    for _ in range(30):
        payload = client.get(f"/api/v1/imports/bilibili/creator-scans/{scan_id}").json()
        if payload["status"] == "cancelled":
            break
        time.sleep(0.01)
    assert payload["status"] == "cancelled"
    assert payload["error"]["code"] == "SCAN_CANCELLED"


def test_creator_scan_cancel_wins_before_completion_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.adapters.sources import bilibili
    from app.api import main as api_main

    page_check_reached = Event()
    allow_finalization = Event()

    class CancelledTotal(int):
        def __new__(cls) -> "CancelledTotal":
            return int.__new__(cls, 1)

        def __le__(self, other: object) -> bool:
            page_check_reached.set()
            if not allow_finalization.wait(1):
                raise RuntimeError("test did not release creator scan finalization")
            return int.__le__(self, other)

    monkeypatch.setattr(
        api_main,
        "fetch_up_card",
        lambda mid, cookie=None: bilibili.UpCard(
            mid=mid, name="测试UP主", archive_count=1
        ),
    )
    monkeypatch.setattr(
        api_main,
        "enumerate_space_videos",
        lambda mid, page=1, cookie=None: (
            [
                bilibili.SpaceVideo(
                    "BV1",
                    "投稿视频",
                    "https://www.bilibili.com/video/BV1",
                    60,
                    "2026-08-15",
                )
            ],
            CancelledTotal(),
        ),
    )
    client = make_client(tmp_path)
    start = client.post(
        "/api/v1/imports/bilibili/creator-scans",
        json={"url": "https://space.bilibili.com/17849059"},
    )
    scan_id = start.json()["scan_id"]
    assert page_check_reached.wait(1)

    cancelled = client.delete(f"/api/v1/imports/bilibili/creator-scans/{scan_id}")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    allow_finalization.set()
    worker = next((thread for thread in list_threads() if thread.name == scan_id), None)
    if worker is not None:
        worker.join(1)
        assert not worker.is_alive()
    payload = client.get(f"/api/v1/imports/bilibili/creator-scans/{scan_id}").json()
    assert payload["status"] == "cancelled"
    assert payload["error"]["code"] == "SCAN_CANCELLED"


def test_creator_scan_cancel_wins_before_error_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.adapters.sources import link
    from app.api import main as api_main

    started = Event()
    release = Event()

    def fail_after_cancel(mid, cookie=None):
        started.set()
        release.wait(1)
        raise link.LinkImportError("UP 主读取失败")

    monkeypatch.setattr(api_main, "fetch_up_card", fail_after_cancel)
    client = make_client(tmp_path)
    start = client.post(
        "/api/v1/imports/bilibili/creator-scans",
        json={"url": "https://space.bilibili.com/17849059"},
    )
    scan_id = start.json()["scan_id"]
    assert started.wait(1)

    cancelled = client.delete(f"/api/v1/imports/bilibili/creator-scans/{scan_id}")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    release.set()
    worker = next((thread for thread in list_threads() if thread.name == scan_id), None)
    if worker is not None:
        worker.join(1)
        assert not worker.is_alive()
    payload = client.get(f"/api/v1/imports/bilibili/creator-scans/{scan_id}").json()
    assert payload["status"] == "cancelled"
    assert payload["error"]["code"] == "SCAN_CANCELLED"


def test_creator_scan_cancel_wins_before_error_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import main as api_main

    started = Event()
    release = Event()

    def fail_after_cancel(mid, cookie=None):
        started.set()
        release.wait(1)
        raise link.LinkImportError("B站 UP 主读取失败")

    monkeypatch.setattr(api_main, "fetch_up_card", fail_after_cancel)
    client = make_client(tmp_path)
    start = client.post(
        "/api/v1/imports/bilibili/creator-scans",
        json={"url": "https://space.bilibili.com/17849059"},
    )
    scan_id = start.json()["scan_id"]
    assert started.wait(1)

    cancelled = client.delete(f"/api/v1/imports/bilibili/creator-scans/{scan_id}")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    release.set()
    worker = next((thread for thread in list_threads() if thread.name == scan_id), None)
    if worker is not None:
        worker.join(1)
        assert not worker.is_alive()
    payload = client.get(f"/api/v1/imports/bilibili/creator-scans/{scan_id}").json()
    assert payload["status"] == "cancelled"
    assert payload["error"]["code"] == "SCAN_CANCELLED"


def test_creator_scan_returns_structured_input_errors(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    empty = client.post("/api/v1/imports/bilibili/creator-scans", json={"url": ""})
    assert empty.status_code == 422
    assert empty.json()["detail"]["code"] == "EMPTY_INPUT"

    malformed = client.post(
        "/api/v1/imports/bilibili/creator-scans",
        json={"url": "http://[::1"},
    )
    assert malformed.status_code == 422
    assert malformed.json()["detail"]["code"] == "INVALID_URL"

    other = client.post(
        "/api/v1/imports/bilibili/creator-scans",
        json={"url": "https://example.com/post/1"},
    )
    assert other.status_code == 422
    assert other.json()["detail"]["code"] == "NOT_BILIBILI_URL"

    video = client.post(
        "/api/v1/imports/bilibili/creator-scans",
        json={"url": "https://www.bilibili.com/video/BV1GKgM6qEar"},
    )
    assert video.status_code == 422
    assert video.json()["detail"]["code"] == "NOT_CREATOR_URL"

def test_space_preview_reports_restricted_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.adapters.sources import bilibili
    from app.api import main as api_main

    monkeypatch.setattr(
        api_main,
        "fetch_up_card",
        lambda mid, cookie=None: bilibili.UpCard(mid=mid, name="测试UP主", archive_count=22),
    )
    monkeypatch.setattr(
        api_main,
        "enumerate_space_videos",
        lambda mid, page=1, cookie=None: (_ for _ in ()).throw(
            link.LinkImportError("B站公开视频列表接口被平台风控拦截")
        ),
    )
    client = make_client(tmp_path)

    response = client.post(
        "/api/v1/imports/bilibili/space/preview",
        json={"url": "https://space.bilibili.com/17849059"},
    )

    assert response.status_code == 422
    assert "风控" in response.json()["detail"]


def test_batch_links_import_reports_accepted_and_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_fetch(_url: str) -> link.PublicPage:
        return link.PublicPage(_url, _page_html())

    monkeypatch.setattr(link, "fetch_public_page", fake_fetch)
    client = make_client(tmp_path)

    response = client.post(
        "/api/v1/imports/links",
        json={
            "urls": [
                "https://www.zhihu.com/question/1/answer/1",
                "https://www.zhihu.com/question/2/answer/2",
                "not-a-url",
            ],
            "strength": "quick",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["accepted"]) == 2
    assert len(payload["failed"]) == 1
    assert payload["failed"][0]["url"] == "not-a-url"
    assert payload["failed"][0]["reason"]
    assert payload["skipped"] == []


def test_batch_links_skips_already_imported_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        link,
        "fetch_public_page",
        lambda _url: link.PublicPage(_url, _page_html()),
    )
    client = make_client(tmp_path)
    first = client.post(
        "/api/v1/imports/links",
        json={"urls": ["https://www.zhihu.com/question/1/answer/1"], "strength": "quick"},
    ).json()
    assert len(first["accepted"]) == 1

    second = client.post(
        "/api/v1/imports/links",
        json={"urls": ["https://www.zhihu.com/question/1/answer/1"], "strength": "quick"},
    ).json()

    assert second["accepted"] == []
    assert len(second["skipped"]) == 1
    assert len(client.app.state.store.list_jobs()) == 1


def test_link_query_marks_duplicate_as_selectable_and_imports_with_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_summary(monkeypatch)
    monkeypatch.setattr(
        link,
        "fetch_public_page",
        lambda _url: link.PublicPage(_url, _page_html()),
    )
    client = make_client(tmp_path)
    first = client.post(
        "/api/v1/imports/link",
        json={"url": "https://www.zhihu.com/question/1/answer/1", "strength": "quick"},
    ).json()
    query = client.post(
        "/api/v1/imports/query",
        json={"urls": ["https://www.zhihu.com/question/1/answer/1"]},
    )
    assert query.status_code == 200
    query_payload = wait_for_link_query(client, query)
    item = query_payload["items"][0]
    assert item["status"] == "duplicate"
    assert item["selectable"] is True
    confirmed = client.post(
        "/api/v1/imports/query/confirm",
        json={"query_id": query_payload["query_id"], "item_ids": [item["item_id"]], "duplicate_action": "regenerate"},
    )
    assert confirmed.status_code == 201
    accepted = confirmed.json()["accepted"][0]
    assert accepted["duplicate"] is True
    assert accepted["content"]["id"] != first["content"]["id"]
    assert accepted["content"]["title"].endswith("（1）")
    assert accepted["job"]["content_title"] == accepted["content"]["title"]
    history = client.get("/api/v1/history").json()
    assert len(history) == 2
    assert [entry["content"]["title"] for entry in history].count(
        accepted["content"]["title"]
    ) == 1


def test_link_query_deduplicates_same_source_within_one_submission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_summary(monkeypatch)

    def fake_prepare(*, url, title, language, bilibili_cookie, asr_configured, page_number=None):
        return [
            PreparedSource(
                kind=ContentKind.ARTICLE,
                title="同一来源",
                transcript=Transcript(
                    "zh-CN",
                    "test",
                    "test",
                    (TranscriptSegment(0, 2, "同一来源内容。"),),
                ),
                content_hash="same-source-hash",
                source_path=None,
                source_url="https://example.test/canonical",
                acquisition_method="test",
                platform=SourcePlatform.WEB,
            )
        ]

    monkeypatch.setattr(main, "_prepare_link_sources", fake_prepare)
    client = make_client(tmp_path)
    query = client.post(
        "/api/v1/imports/query",
        json={"urls": ["https://example.test/one", "https://example.test/two"]},
    )
    assert query.status_code == 200
    payload = wait_for_link_query(client, query)
    assert len(payload["items"]) == 1
    item = payload["items"][0]
    confirmed = client.post(
        "/api/v1/imports/query/confirm",
        json={"query_id": payload["query_id"], "item_ids": [item["item_id"]]},
    )
    assert confirmed.status_code == 201
    assert len(confirmed.json()["accepted"]) == 1


def test_link_query_returns_per_item_progress_and_cancel_rejects_late_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release_slow = Event()
    slow_started = Event()

    def fake_prepare(*, url, title, language, bilibili_cookie, asr_configured, page_number=None):
        if url.endswith("/slow"):
            slow_started.set()
            release_slow.wait(2)
        return [
            PreparedSource(
                kind=ContentKind.ARTICLE,
                title=url.rsplit("/", 1)[-1],
                transcript=Transcript(
                    "zh-CN",
                    "test",
                    "test",
                    (TranscriptSegment(0, 2, "这是一段逐项查询测试内容。"),),
                ),
                content_hash=url,
                source_path=None,
                source_url=url,
                acquisition_method="test",
                platform=SourcePlatform.WEB,
            )
        ]

    monkeypatch.setattr(main, "_prepare_link_sources", fake_prepare)
    client = make_client(tmp_path)
    started = client.post(
        "/api/v1/imports/query",
        json={"urls": ["https://example.test/slow", "https://example.test/fast"]},
    )

    assert started.status_code == 200
    initial = started.json()
    assert initial["status"] == "processing"
    assert initial["deadline_at"]
    assert LINK_QUERY_DEADLINE_SECONDS == 180
    assert any(item["status"] == "pending" for item in initial["items"])
    assert slow_started.wait(1)

    fast = None
    for _ in range(100):
        fast = client.get(f"/api/v1/imports/query/{initial['query_id']}").json()
        if any(
            item["input_url"].endswith("/fast") and item["status"] == "ready"
            for item in fast["items"]
        ):
            break
        time.sleep(0.01)
    assert fast is not None
    assert any(item["status"] == "pending" for item in fast["items"])
    assert any(
        item["input_url"].endswith("/fast") and item["selectable"]
        for item in fast["items"]
    )

    cancelled = client.post(
        f"/api/v1/imports/query/{initial['query_id']}/cancel",
    )
    assert cancelled.status_code == 200
    cancelled_payload = cancelled.json()
    assert cancelled_payload["status"] == "cancelled"
    assert all(item["status"] != "pending" for item in cancelled_payload["items"])
    assert any(item["status"] == "timed_out" for item in cancelled_payload["items"])
    assert any(
        item["input_url"].endswith("/fast") and item["selectable"]
        for item in cancelled_payload["items"]
    )

    release_slow.set()
    wait_for_link_query_workers(client, initial["query_id"])
    late = client.get(f"/api/v1/imports/query/{initial['query_id']}").json()
    assert late["status"] == "cancelled"
    assert all(
        item["status"] != "ready"
        for item in late["items"]
        if item["input_url"].endswith("/slow")
    )
    assert initial["query_id"] not in client.app.state.link_query_workers


def test_link_query_shutdown_joins_registered_workers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = Event()
    release = Event()

    def slow_prepare(*, url, title, language, bilibili_cookie, asr_configured, page_number=None):
        started.set()
        release.wait(1)
        return []

    monkeypatch.setattr(main, "_prepare_link_sources", slow_prepare)
    app = create_app("sqlite:///:memory:", tmp_path / "knowledge-root")
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/imports/query",
            json={"urls": ["https://example.test/shutdown"]},
        )
        assert response.status_code == 200
        assert started.wait(1)
        query_id = response.json()["query_id"]
        assert query_id in client.app.state.link_query_workers

        def release_worker() -> None:
            time.sleep(0.05)
            release.set()

        Thread(target=release_worker, daemon=True).start()

    assert release.is_set()
    assert not app.state.link_query_workers


def test_link_query_deadline_marks_only_pending_items_timed_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release_slow = Event()
    slow_started = Event()

    def fake_prepare(*, url, title, language, bilibili_cookie, asr_configured, page_number=None):
        slow_started.set()
        release_slow.wait(2)
        return [
            PreparedSource(
                kind=ContentKind.ARTICLE,
                title="截止测试内容",
                transcript=Transcript(
                    "zh-CN",
                    "test",
                    "test",
                    (TranscriptSegment(0, 2, "这是一段截止测试内容。"),),
                ),
                content_hash=url,
                source_path=None,
                source_url=url,
                acquisition_method="test",
                platform=SourcePlatform.WEB,
            )
        ]

    monkeypatch.setattr(main, "_prepare_link_sources", fake_prepare)
    client = make_client(tmp_path)
    started = client.post(
        "/api/v1/imports/query",
        json={"urls": ["https://example.test/slow-deadline"]},
    )
    query_id = started.json()["query_id"]
    assert slow_started.wait(1)
    client.app.state.link_queries[query_id]["deadline_at"] = datetime.now(UTC) - timedelta(seconds=1)

    timed_out = client.get(f"/api/v1/imports/query/{query_id}")
    assert timed_out.status_code == 200
    payload = timed_out.json()
    assert payload["status"] == "timed_out"
    assert payload["items"][0]["status"] == "timed_out"
    assert payload["items"][0]["selectable"] is False

    release_slow.set()
    time.sleep(0.02)
    late = client.get(f"/api/v1/imports/query/{query_id}").json()
    assert late["status"] == "timed_out"
    assert late["items"][0]["status"] == "timed_out"




def test_bilibili_video_prefers_subtitle_over_page_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.adapters.sources import bilibili
    from app.domain.models import TranscriptSegment

    monkeypatch.setattr(
        link,
        "fetch_public_page",
        lambda _: link.PublicPage(
            "https://www.bilibili.com/video/BV1GKgM6qEar/",
            _BILIBILI_VIDEO_HTML,
        ),
    )
    monkeypatch.setattr(
        bilibili,
        "fetch_video_subtitle",
        lambda bvid, cid, cookie=None: (
            "中文（自动生成）",
            [
                bilibili.SubtitleCue(0.0, 3.0, "第一句字幕内容。"),
                bilibili.SubtitleCue(3.5, 8.0, "第二句字幕内容，覆盖视频主体信息。"),
            ],
        ),
    )

    source = link.prepare_link_import(
        url="https://www.bilibili.com/video/BV1GKgM6qEar/",
        title=None,
        language="zh-CN",
        asr_configured=True,
    )

    assert source.transcript.source_kind == "bilibili_subtitle"
    assert source.transcript.engine == "bilibili"
    assert source.transcript.segments[0].start_seconds == 0.0
    assert "字幕" in (source.source_note or "")
    assert all(isinstance(segment, TranscriptSegment) for segment in source.transcript.segments)


def test_bilibili_video_restricted_subtitle_fails_with_assisted_login_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.adapters.sources import bilibili

    monkeypatch.setattr(
        link,
        "fetch_public_page",
        lambda _: link.PublicPage(
            "https://www.bilibili.com/video/BV1GKgM6qEar/",
            _BILIBILI_VIDEO_HTML,
        ),
    )
    monkeypatch.setattr(
        bilibili,
        "fetch_video_subtitle",
        lambda bvid, cid, cookie=None: (_ for _ in ()).throw(
            link.LinkImportError("视频字幕需要登录。请在设置页使用 B站二维码登录后重试")
        ),
    )

    with pytest.raises(link.LinkImportError, match="无法识别视频内容"):
        link.prepare_link_import(
            url="https://www.bilibili.com/video/BV1GKgM6qEar/",
            title=None,
            language="zh-CN",
        )




def test_bilibili_video_without_subtitle_prepares_audio_for_asr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.adapters.sources import bilibili

    monkeypatch.setattr(
        link,
        "fetch_public_page",
        lambda _: link.PublicPage(
            "https://www.bilibili.com/video/BV1GKgM6qEar/",
            _BILIBILI_VIDEO_HTML,
        ),
    )
    monkeypatch.setattr(
        bilibili,
        "fetch_video_subtitle",
        lambda bvid, cid, cookie=None: None,
    )
    audio_dest = {"path": None}

    def fake_download(url, *, cookie=None):
        dest = tmp_path / "knowledge-asr-fake" / "source.m4a"
        dest.parent.mkdir()
        dest.write_bytes(b"fake-audio")
        audio_dest["path"] = str(dest)
        return dest

    monkeypatch.setattr(bilibili, "download_bilibili_audio", fake_download)

    source = link.prepare_link_import(
        url="https://www.bilibili.com/video/BV1GKgM6qEar/",
        title=None,
        language="zh-CN",
        asr_configured=True,
    )

    assert source.transcript is None
    assert source.audio_path == audio_dest["path"]
    assert source.audio_is_temp is True
    assert source.download_seconds is not None
    assert source.download_seconds >= 0.0
    assert "ASR" in (source.source_note or "")


def test_api_rejects_video_without_asr_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.adapters.sources import bilibili

    monkeypatch.setattr(
        link,
        "fetch_public_page",
        lambda _: link.PublicPage(
            "https://www.bilibili.com/video/BV1GKgM6qEar/",
            _BILIBILI_VIDEO_HTML,
        ),
    )
    monkeypatch.setattr(
        bilibili,
        "fetch_video_subtitle",
        lambda bvid, cid, cookie=None: None,
    )
    monkeypatch.setattr(
        bilibili,
        "download_bilibili_audio",
        lambda *args, **kwargs: pytest.fail("未配置 ASR 时不应下载音频"),
    )
    client = make_client(tmp_path)

    response = client.post(
        "/api/v1/imports/link",
        json={"url": "https://www.bilibili.com/video/BV1GKgM6qEar/", "strength": "quick"},
    )

    assert response.status_code == 422
    assert "配置 ASR" in response.json()["detail"]


def test_archive_root_can_be_saved_from_settings(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    target = tmp_path / "selected-knowledge-root"

    response = client.put("/api/v1/settings", json={"archive_root": str(target)})

    assert response.status_code == 200
    assert response.json()["archive_root"] == str(target.resolve())
    assert target.is_dir()
    assert client.app.state.workflow.archive_root == target.resolve()
    assert client.app.state.store.get_setting("archive_root") == str(target.resolve())
def test_settings_update_keeps_existing_asr_key_when_key_is_omitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db import store as store_module

    monkeypatch.setattr(
        store_module,
        "protect_secret",
        lambda value, *, purpose: "dpapi:asr-sealed",
    )
    monkeypatch.setattr(
        store_module,
        "unprotect_secret",
        lambda value, *, purpose: "test-key",
    )
    client = make_client(tmp_path)
    initial = client.put(
        "/api/v1/settings",
        json={"asr_api_key": "test-key", "asr_api_url": "https://example.test/transcribe", "asr_model": "model-a"},
    )
    assert initial.status_code == 200

    response = client.put(
        "/api/v1/settings",
        json={"asr_api_url": "https://example.test/transcribe-v2", "asr_model": "model-b"},
    )

    assert response.status_code == 200
    store = client.app.state.store
    assert store._get_setting_raw("asr_api_key") == "dpapi:asr-sealed"
    assert store._get_setting_raw("asr_cloud_api_key") == "dpapi:asr-sealed"
    assert "test-key" not in (store._get_setting_raw("asr_api_key") or "")
    assert store.get_secret_setting("asr_api_key", purpose="云端 ASR API Key") == "test-key"
def test_settings_qr_session_does_not_accept_browser_fields(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    initial = client.get("/api/v1/settings").json()
    assert initial["bilibili_browser"] is None
    assert initial["bilibili_connected"] is False

    response = client.put(
        "/api/v1/settings",
        json={"bilibili_browser": "edge", "bilibili_browser_profile": "Default"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["bilibili_browser"] is None
    assert payload["bilibili_browser_profile"] is None
    assert payload["bilibili_connected"] is False


def test_history_search_covers_summary_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import urllib.parse

    install_fake_summary(monkeypatch)
    client = make_client(tmp_path)
    client.post(
        "/api/v1/imports/local",
        json={
            "title": "本地学习笔记",
            "text": "第一段说明项目目标。\n\n第二段说明如何保存和检索知识，以及如何建立索引结构。",
            "strength": "standard",
            "max_chunk_tokens": 32,
        },
    )

    by_summary = client.get(
        "/api/v1/history?q=" + urllib.parse.quote("检索知识")
    ).json()

    assert len(by_summary) == 1
    assert by_summary[0]["content"]["title"] == "未命名文本"


_BILIBILI_MULTI_VIDEO_HTML = """
<html lang="zh-CN">
  <head>
    <link rel="canonical" href="https://www.bilibili.com/video/BVmulti123" />
    <script>window.__INITIAL_STATE__={"bvid":"BVmulti123","videoData":{"title":"系列总标题","bvid":"BVmulti123","cid":111,"duration":3,"owner":{"name":"测试UP主"},"desc":"这是一个多 P 视频系列的简介。","pages":[{"cid":111,"page":1,"part":"第一集","duration":3},{"cid":222,"page":2,"part":"第二集","duration":4}]}};</script>
  </head>
  <body><article>页面噪音不应作为视频正文。</article></body>
</html>
"""


def test_bilibili_multi_page_link_prepares_each_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.adapters.sources import bilibili

    monkeypatch.setattr(
        link,
        "fetch_public_page",
        lambda _: link.PublicPage(
            "https://www.bilibili.com/video/BVmulti123",
            _BILIBILI_MULTI_VIDEO_HTML,
        ),
    )
    calls = []

    def fake_subtitle(bvid, cid, cookie=None):
        calls.append((bvid, cid))
        return ("中文", [bilibili.SubtitleCue(0.0, 4.0, f"第 {cid} P 的字幕")])

    monkeypatch.setattr(bilibili, "fetch_video_subtitle", fake_subtitle)

    sources = link.prepare_link_imports(
        url="https://www.bilibili.com/video/BVmulti123",
        title=None,
        language="zh-CN",
    )

    assert calls == [("BVmulti123", 111), ("BVmulti123", 222)]
    assert [source.title for source in sources] == [
        "系列总标题 - 第一集",
        "系列总标题 - 第二集",
    ]
    assert [source.source_url for source in sources] == [
        "https://www.bilibili.com/video/BVmulti123?p=1",
        "https://www.bilibili.com/video/BVmulti123?p=2",
    ]
    assert all(source.transcript is not None for source in sources)


def test_multi_page_link_creates_independent_summaries_in_one_folder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.adapters.sources import bilibili

    install_fake_summary(monkeypatch)
    monkeypatch.setattr(
        link,
        "fetch_public_page",
        lambda _: link.PublicPage(
            "https://www.bilibili.com/video/BVmulti123",
            _BILIBILI_MULTI_VIDEO_HTML,
        ),
    )
    monkeypatch.setattr(
        bilibili,
        "fetch_video_subtitle",
        lambda bvid, cid, cookie=None: (
            "中文",
            [bilibili.SubtitleCue(0.0, 4.0, f"第 {cid} P 的独立内容")],
        ),
    )
    client = make_client(tmp_path)

    response = client.post(
        "/api/v1/imports/link",
        json={"url": "https://www.bilibili.com/video/BVmulti123", "strength": "quick"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert len(payload["accepted"]) == 2
    assert payload["content"]["title"] == "系列总标题 - 第一集"
    jobs = [client.get(f"/api/v1/jobs/{item['job']['id']}").json() for item in payload["accepted"]]
    assert [job["state"] for job in jobs] == ["completed", "completed"]
    paths = [Path(job["archive_path"]) for job in jobs]
    assert paths[0].parent == paths[1].parent
    assert paths[0] != paths[1]
    assert all((path / "index.md").is_file() for path in paths)
    assert all("BVmulti123?p=" in job["source_url"] for job in jobs)


@pytest.mark.parametrize("scan_kind", ["favorite", "creator", "watchlater"])
def test_scan_import_creates_200_jobs_before_acquisition(tmp_path, monkeypatch, scan_kind):
    client = make_client(tmp_path)
    candidates = [dict(candidate_id=f"video:BV{i}", url=f"https://www.bilibili.com/video/BV{i}",
                       title=f"视频{i}", selectable=True, duration_seconds=60) for i in range(200)]
    getattr(client.app.state, f"{scan_kind}_scans")["scan-test"] = {
        "scan_id": "scan-test", "status": "completed", "candidates": candidates,
    }
    scheduled = []
    monkeypatch.setattr(client.app.state.job_queue, "submit", lambda job_id, *args, **kwargs: scheduled.append(job_id))
    monkeypatch.setattr(main, "_prepare_link_sources", lambda **kwargs: pytest.fail("建单不应读取内容"))
    response = client.post("/api/v1/imports/bilibili/scans/confirm", json={
        "scan_id": "scan-test", "candidate_ids": [c["candidate_id"] for c in candidates],
    })
    assert response.status_code == 201, response.text
    accepted = response.json()["accepted"]
    assert len(accepted) == len(scheduled) == 200
    assert all(item["job"]["state"] == "queued" for item in accepted)
    assert all(client.app.state.store.get_job(item["job"]["id"]).metadata["deferred_link"] for item in accepted)


def test_scan_import_rejects_unknown_candidates_without_jobs(tmp_path):
    client = make_client(tmp_path)
    client.app.state.favorite_scans["scan-test"] = {"candidates": [], "status": "completed"}
    response = client.post("/api/v1/imports/bilibili/scans/confirm", json={
        "scan_id": "scan-test", "candidate_ids": ["unknown"],
    })
    assert response.status_code == 422
    assert not client.app.state.store.list_jobs()


def test_scan_jobs_acquire_only_when_running_and_continue_after_failure(tmp_path, monkeypatch):
    install_fake_summary(monkeypatch)
    client = make_client(tmp_path)
    store = client.app.state.store
    client.app.state.favorite_scans["scan-test"] = {
        "status": "completed", "candidates": [
            dict(candidate_id=f"video:{i}", url=f"https://www.bilibili.com/video/BV{i}",
                 title=f"Video {i}", selectable=True) for i in range(2)
        ],
    }
    queued = []
    real_submit = client.app.state.job_queue.submit
    monkeypatch.setattr(client.app.state.job_queue, "submit", lambda *args, **kwargs: queued.append(args))
    calls = []

    def acquire(**kwargs):
        url = kwargs["url"]
        calls.append(url)
        jobs = store.list_jobs()
        assert len(jobs) == 2
        assert sum(job.state.value == "acquiring" for job in jobs) == 1
        if url.endswith("BV0"):
            raise link.LinkImportError("Source unavailable")
        return [PreparedSource(
            kind=ContentKind.VIDEO, title="Resolved title", platform=SourcePlatform.BILIBILI,
            transcript=Transcript("zh-CN", "bilibili_subtitle", "bilibili", (
                TranscriptSegment(0, 4, "Complete subtitle content."),
            )), duration_seconds=4, content_hash="resolved-hash",
            source_path=None, source_url=url, acquisition_method="public_page",
        )]

    monkeypatch.setattr(main, "_prepare_link_sources", acquire)
    report = client.post("/api/v1/imports/bilibili/scans/confirm", json={
        "scan_id": "scan-test", "candidate_ids": ["video:0", "video:1"],
    }).json()
    assert not calls
    monkeypatch.setattr(client.app.state.job_queue, "submit", real_submit)
    for args in queued:
        real_submit(*args)
    jobs = [store.get_job(item["job"]["id"]) for item in report["accepted"]]
    assert [job.state.value for job in jobs] == ["failed", "completed"], [(job.state, job.error_message) for job in jobs]
    assert calls == [f"https://www.bilibili.com/video/BV{i}" for i in range(2)]
    assert store.get_content(report["accepted"][1]["content"]["id"]).title == "Resolved title"


def test_scan_multi_page_video_keeps_independent_jobs_and_folders(tmp_path, monkeypatch):
    install_fake_summary(monkeypatch)
    monkeypatch.setattr(link, "fetch_public_page", lambda _: link.PublicPage(
        "https://www.bilibili.com/video/BVmulti123", _BILIBILI_MULTI_VIDEO_HTML,
    ))
    monkeypatch.setattr(bilibili, "fetch_video_subtitle", lambda bvid, cid, cookie=None: (
        "zh-CN", [bilibili.SubtitleCue(0, 4, f"Subtitle for part {cid}")],
    ))
    client = make_client(tmp_path)
    store = client.app.state.store
    folder = store.create_favorite_folder("Test folder")
    client.app.state.favorite_scans["scan-test"] = {
        "candidates": [dict(candidate_id="video:multi", url="https://www.bilibili.com/video/BVmulti123",
                            title="Series", selectable=True)],
    }
    response = client.post("/api/v1/imports/bilibili/scans/confirm", json={
        "scan_id": "scan-test", "candidate_ids": ["video:multi"], "favorite_folder_ids": [folder.id],
    })
    assert response.status_code == 201, response.text
    jobs = store.list_jobs()
    assert len(jobs) == 2
    assert all(job.state.value == "completed" for job in jobs), [(job.state, job.error_message) for job in jobs]
    contents = [store.get_content(store.get_analysis_run(job.analysis_run_id).content_id) for job in jobs]
    assert {content.source.canonical_url for content in contents} == {
        "https://www.bilibili.com/video/BVmulti123?p=1", "https://www.bilibili.com/video/BVmulti123?p=2",
    }
    assert all(store.favorite_folder_ids(content.id) == [folder.id] for content in contents)
    assert len({Path(job.metadata["archive_path"]).parent for job in jobs}) == 1


def test_scan_cancelled_job_retry_defers_acquisition(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    client.app.state.favorite_scans["scan-test"] = {
        "candidates": [dict(candidate_id="video:one", url="https://www.bilibili.com/video/BVone",
                            title="Video", selectable=True)],
    }
    monkeypatch.setattr(client.app.state.job_queue, "submit", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "_prepare_link_sources", lambda **kwargs: pytest.fail("Retry must queue first"))
    first = client.post("/api/v1/imports/bilibili/scans/confirm", json={
        "scan_id": "scan-test", "candidate_ids": ["video:one"],
    }).json()["accepted"][0]
    assert client.post(f"/api/v1/jobs/{first['job']['id']}/cancel").status_code == 200
    retry = client.post(f"/api/v1/jobs/{first['job']['id']}/retry")
    assert retry.status_code == 200, retry.text
    assert retry.json()["job"]["state"] == "queued"
    assert client.app.state.store.get_job(retry.json()["job"]["id"]).metadata["deferred_link"] is True


def test_queued_multi_page_retry_reads_only_selected_part(monkeypatch):
    monkeypatch.setattr(link, "fetch_public_page", lambda _: link.PublicPage(
        "https://www.bilibili.com/video/BVmulti123", _BILIBILI_MULTI_VIDEO_HTML,
    ))
    calls = []

    def subtitle(bvid, cid, cookie=None):
        calls.append(cid)
        if cid == 111:
            raise link.LinkImportError("Other part unavailable")
        return "zh-CN", [bilibili.SubtitleCue(0, 4, "Selected part content")]

    monkeypatch.setattr(bilibili, "fetch_video_subtitle", subtitle)
    sources = link.prepare_link_imports(
        url="https://www.bilibili.com/video/BVmulti123?p=2",
        title=None, language=None, page_number=2,
    )
    assert calls == [222]
    assert len(sources) == 1
    assert sources[0].source_url.endswith("?p=2")
