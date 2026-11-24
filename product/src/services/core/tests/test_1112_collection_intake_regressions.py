from types import SimpleNamespace

import pytest

from app.adapters.sources import link
from app.adapters.sources.prepared import PreparedSource
from app.api import main
from app.api.main import _job_collection_id, create_app
from app.db.store import SQLiteStore
from app.domain.jobs import JobState
from app.domain.models import AnalysisSettings, ContentKind, SourcePlatform, Transcript, TranscriptSegment
from fastapi.testclient import TestClient


def test_import_batch_is_not_a_platform_collection():
    assert _job_collection_id(SimpleNamespace(metadata={"import_batch_id": "batch-1"})) is None
    assert _job_collection_id(SimpleNamespace(metadata={"season_id": 42})) == "season:42"
    assert _job_collection_id(SimpleNamespace(metadata={"collection_id": "season:42"})) is None


def test_bilibili_duplicate_identity_is_bvid_and_p_number():
    store = SQLiteStore("sqlite:///:memory:")
    existing = store.create_content(
        kind=ContentKind.VIDEO,
        title="P1",
        platform=SourcePlatform.BILIBILI,
        canonical_url="https://www.bilibili.com/video/BV1vF4F64EsW/?p=1",
        content_hash="old-p1-hash",
    )

    duplicate = store.find_duplicate_content(
        canonical_url="https://www.bilibili.com/video/BV1vF4F64EsW?p=1",
        content_hash="new-p1-hash",
    )
    other_part = store.find_duplicate_content(
        canonical_url="https://www.bilibili.com/video/BV1vF4F64EsW/?p=2",
        content_hash="new-p2-hash",
    )

    assert duplicate is not None and duplicate.id == existing.id
    assert other_part is None


def test_link_query_preserves_requested_bilibili_part(monkeypatch, tmp_path):
    selected_pages = []

    def fake_prepare(*, url, title, language, bilibili_cookie, asr_configured, page_number=None):
        selected_pages.append(page_number)
        pages = [1, 2]
        if page_number is not None:
            pages = [page_number]
        return [
            PreparedSource(
                kind=ContentKind.VIDEO,
                title=f"视频 - P{number}",
                transcript=Transcript(
                    "zh-CN", "test", "test", (TranscriptSegment(0, 2, f"P{number} 内容。"),)
                ),
                content_hash=f"hash-p{number}",
                source_path=None,
                source_url=f"https://www.bilibili.com/video/BV1vF4F64EsW/?p={number}",
                acquisition_method="test",
                platform=SourcePlatform.BILIBILI,
            )
            for number in pages
        ]

    monkeypatch.setattr(main, "_prepare_link_sources", fake_prepare)
    client = TestClient(create_app("sqlite:///:memory:", tmp_path / "knowledge-root"))
    response = client.post(
        "/api/v1/imports/query",
        json={"urls": ["https://www.bilibili.com/video/BV1vF4F64EsW/?p=2"]},
    )
    assert response.status_code == 200
    query_id = response.json()["query_id"]
    for _ in range(100):
        snapshot = client.get(f"/api/v1/imports/query/{query_id}").json()
        if snapshot["status"] != "processing":
            break

    assert selected_pages == [2]
    assert [item["title"] for item in snapshot["items"]] == ["视频 - P2"]
    assert [item["source_url"] for item in snapshot["items"]] == [
        "https://www.bilibili.com/video/BV1vF4F64EsW/?p=2"
    ]


def test_light_link_preview_returns_only_requested_part_metadata(monkeypatch):
    url = "https://www.bilibili.com/video/BV1vF4F64EsW/?p=2"
    pages = (
        SimpleNamespace(number=1, part="第一部分", duration_seconds=60),
        SimpleNamespace(number=2, part="第二部分", duration_seconds=90),
    )
    material = SimpleNamespace(
        title="示例视频",
        author="示例作者",
        thumbnail_url="https://i.example.test/cover.jpg",
        duration_seconds=150,
        published_at=None,
        pages=pages,
    )
    monkeypatch.setattr(
        link,
        "fetch_public_page",
        lambda input_url: link.PublicPage(final_url=input_url, html="<html><title>fallback</title></html>"),
    )
    monkeypatch.setattr(link, "_bilibili_video_material", lambda *args, **kwargs: material)
    monkeypatch.setattr(link, "_bilibili_audio", lambda *args, **kwargs: pytest.fail("preview downloaded audio"))

    preview = link.preview_link_import(url)

    assert [item["title"] for item in preview] == ["示例视频 - 第二部分"]
    assert preview[0]["source_url"] == "https://www.bilibili.com/video/BV1vF4F64EsW/?p=2"
    assert preview[0]["author"] == "示例作者"
    assert preview[0]["thumbnail_url"] == "https://i.example.test/cover.jpg"
    assert preview[0]["duration_seconds"] == 90


def test_b23_redirected_p2_preview_and_query_import_only_p2(monkeypatch, tmp_path):
    short_url = "https://b23.tv/redirected-video"
    final_url = "https://www.bilibili.com/video/BV1vF4F64EsW/?p=2"
    pages = (
        SimpleNamespace(number=1, part="第一部分", duration_seconds=60),
        SimpleNamespace(number=2, part="第二部分", duration_seconds=90),
    )
    material = SimpleNamespace(
        title="系列总标题",
        author="示例作者",
        thumbnail_url="https://i.example.test/cover.jpg",
        duration_seconds=150,
        published_at=None,
        text="多P简介",
        pages=pages,
    )
    monkeypatch.setattr(
        link,
        "fetch_public_page",
        lambda _: link.PublicPage(final_url=final_url, html="<html></html>"),
    )
    monkeypatch.setattr(link, "_bilibili_video_material", lambda *args, **kwargs: material)
    monkeypatch.setattr(
        link,
        "_bilibili_subtitle",
        lambda *args, page, **kwargs: (
            Transcript("zh-CN", "test", "test", (TranscriptSegment(0, 2, f"P{page.number}"),)),
            "subtitle",
        ),
    )

    preview = link.preview_link_import(short_url)
    assert [item["page_number"] for item in preview] == [2]

    monkeypatch.setattr(main, "_preflight_link_connection", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "_require_asr_for_untitled_source", lambda *args, **kwargs: None)
    client = TestClient(create_app("sqlite:///:memory:", tmp_path / "knowledge-root"))
    monkeypatch.setattr(client.app.state.job_queue, "submit", lambda *args, **kwargs: None)
    query = client.post("/api/v1/imports/query", json={"urls": [short_url]})
    assert query.status_code == 200
    query_id = query.json()["query_id"]
    for _ in range(100):
        snapshot = client.get(f"/api/v1/imports/query/{query_id}").json()
        if snapshot["status"] != "processing":
            break
    assert [item["source_url"] for item in snapshot["items"]] == [final_url]
    assert [item["title"] for item in snapshot["items"]] == ["系列总标题 - 第二部分"]

    confirmed = client.post(
        "/api/v1/imports/query/confirm",
        json={"query_id": query_id, "item_ids": [snapshot["items"][0]["item_id"]]},
    )

    assert confirmed.status_code == 201
    assert len(confirmed.json()["accepted"]) == 1
    assert confirmed.json()["accepted"][0]["content"]["canonical_url"] == final_url
    assert len(client.get("/api/v1/jobs").json()) == 1


@pytest.mark.parametrize("soft_deleted", [False, True])
def test_duplicate_link_reuses_existing_content_without_creating_job(
    monkeypatch, tmp_path, soft_deleted
):
    source_url = "https://www.bilibili.com/video/BV1vF4F64EsW?p=1"

    def fake_prepare(*, url, title, language, bilibili_cookie, asr_configured, page_number=None):
        return [
            PreparedSource(
                kind=ContentKind.VIDEO,
                title="视频 - P1",
                transcript=Transcript(
                    "zh-CN", "test", "test", (TranscriptSegment(0, 2, "P1 内容。"),)
                ),
                content_hash="new-p1-hash",
                source_path=None,
                source_url=source_url,
                acquisition_method="test",
                platform=SourcePlatform.BILIBILI,
            )
        ]

    monkeypatch.setattr(main, "_prepare_link_sources", fake_prepare)
    client = TestClient(create_app("sqlite:///:memory:", tmp_path / "knowledge-root"))
    store = client.app.state.store
    existing = store.create_content(
        kind=ContentKind.VIDEO,
        title="已有 P1 笔记",
        platform=SourcePlatform.BILIBILI,
        canonical_url="https://www.bilibili.com/video/BV1vF4F64EsW/?p=1",
        content_hash="old-p1-hash",
    )
    tag = store.create_tag("已有标签")
    folder = store.create_favorite_folder("已有收藏夹")
    store.update_content(
        existing.id,
        tag_ids=[tag.id],
        favorite=True,
        favorite_folder_ids=[folder.id],
    )
    if soft_deleted:
        store.soft_delete_content(existing.id)
    index_syncs = []
    client.app.state.ask_index = SimpleNamespace(sync_latest=lambda content_id: index_syncs.append(content_id))
    monkeypatch.setattr(client.app.state.job_queue, "submit", lambda *args, **kwargs: None)

    query = client.post("/api/v1/imports/query", json={"urls": [source_url]})
    query_id = query.json()["query_id"]
    for _ in range(100):
        snapshot = client.get(f"/api/v1/imports/query/{query_id}").json()
        if snapshot["status"] != "processing":
            break
    item = snapshot["items"][0]
    assert item["status"] == "duplicate"

    confirmed = client.post(
        "/api/v1/imports/query/confirm",
        json={"query_id": query_id, "item_ids": [item["item_id"]]},
    )

    assert confirmed.status_code == 201
    assert confirmed.json()["accepted"] == []
    assert len(confirmed.json()["skipped"]) == 1
    assert client.get("/api/v1/jobs").json() == []
    restored = store.get_content(existing.id)
    assert restored.id == existing.id
    assert restored.deleted_at is None
    assert index_syncs == ([existing.id] if soft_deleted else [])
    assert store.tag_ids(existing.id) == [tag.id]
    assert store.favorite_folder_ids(existing.id) == [folder.id]


def test_trusted_season_survives_duplicate_reuse_resummary_and_retry(monkeypatch, tmp_path):
    source_url = "https://www.bilibili.com/video/BV1vF4F64EsW/?p=1"
    transcript = Transcript("zh-CN", "test", "test", (TranscriptSegment(0, 2, "已有字幕。"),))

    def fake_prepare(*, url, title, language, bilibili_cookie, asr_configured, page_number=None):
        return [PreparedSource(
            kind=ContentKind.VIDEO,
            title=title or "原始标题",
            transcript=transcript,
            content_hash="same-p1-hash",
            source_path=None,
            source_url=source_url,
            acquisition_method="test",
            platform=SourcePlatform.BILIBILI,
        )]

    monkeypatch.setattr(main, "_preflight_link_connection", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "_prepare_link_sources", fake_prepare)
    monkeypatch.setattr(main, "_require_asr_for_untitled_source", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "_analysis_settings_from_store", lambda *args, **kwargs: AnalysisSettings("test-model"))
    monkeypatch.setattr(main, "_summary_settings_snapshot", lambda *args, **kwargs: {
        "summary_config": {"model": "test-model"},
        "summary_provider": "openai-compatible",
        "prompt_version": "test-prompt",
        "summary_prompt": "test prompt",
        "summary_prompt_hash": "test-hash",
        "summary_skill": None,
    })
    client = TestClient(create_app("sqlite:///:memory:", tmp_path / "knowledge-root"))
    monkeypatch.setattr(client.app.state.job_queue, "submit", lambda *args, **kwargs: None)
    store = client.app.state.store
    existing = store.create_content(
        kind=ContentKind.VIDEO,
        title="先前导入的 P1",
        platform=SourcePlatform.BILIBILI,
        canonical_url=source_url,
        content_hash="same-p1-hash",
    )
    _, existing_job = store.create_analysis_run(existing.id, AnalysisSettings("test-model"))
    existing_job.metadata["source_url"] = source_url
    store.save_job(existing_job)
    client.app.state.creator_scans["season-scan"] = {
        "candidates": [{"candidate_id": "candidate-p1", "url": source_url, "title": "原始标题", "selectable": True}],
        "season_id": 321,
        "up_name": "可信合集",
        "total": 2,
    }

    reused = client.post("/api/v1/imports/bilibili/scans/confirm", json={
        "scan_id": "season-scan",
        "candidate_ids": ["candidate-p1"],
        "duplicate_action": "reuse",
    })

    assert reused.status_code == 201
    assert reused.json()["accepted"] == []
    assert len(reused.json()["skipped"]) == 1
    assert len(store.list_content_jobs(existing.id)) == 1
    assert store.get_job(existing_job.id).metadata["season_id"] == 321
    assert client.get("/api/v1/jobs").json()[0]["collection_id"] == "season:321"

    resummarized = client.post(f"/api/v1/contents/{existing.id}/resummarize", json={})
    assert resummarized.status_code == 201
    assert resummarized.json()["job"]["collection_id"] == "season:321"

    resummary_job = store.get_job(resummarized.json()["job"]["id"])
    resummary_job.state = JobState.FAILED
    store.save_job(resummary_job)
    retried = client.post(f"/api/v1/jobs/{resummary_job.id}/retry")

    assert retried.status_code == 200
    assert retried.json()["job"]["collection_id"] == "season:321"


def test_light_probe_returns_preview_metadata_and_source_duplicate(monkeypatch, tmp_path):
    source_url = "https://www.bilibili.com/video/BV1vF4F64EsW?p=1"
    monkeypatch.setattr(
        main,
        "preview_link_import",
        lambda url: [{
            "title": "示例 P1",
            "source_url": "https://www.bilibili.com/video/BV1vF4F64EsW/?p=1",
            "platform": "bilibili",
            "author": "作者",
            "thumbnail_url": "https://i.example.test/cover.jpg",
            "duration_seconds": 60,
            "page_number": 1,
        }],
    )
    client = TestClient(create_app("sqlite:///:memory:", tmp_path / "knowledge-root"))
    client.app.state.store.create_content(
        kind=ContentKind.VIDEO,
        title="已存在 P1",
        platform=SourcePlatform.BILIBILI,
        canonical_url="https://www.bilibili.com/video/BV1vF4F64EsW/?p=1",
        content_hash="old-p1-hash",
    )

    response = client.post("/api/v1/imports/probe", json={"url": source_url})

    assert response.status_code == 200
    body = response.json()
    assert body["preview_status"] == "ready"
    assert body["items"][0]["title"] == "示例 P1"
    assert body["items"][0]["author"] == "作者"
    assert body["items"][0]["thumbnail_url"] == "https://i.example.test/cover.jpg"
    assert body["items"][0]["duplicate"] is True


def test_intake_ui_uses_light_preview_and_latest_input_only():
    from pathlib import Path

    root = Path(link.__file__).parents[2] / "ui"
    html = (root / "index.html").read_text(encoding="utf-8")
    script = (root / "app.js").read_text(encoding="utf-8")
    assert 'id="intake-preview"' in html
    assert 'post("/imports/probe", { url })' in script
    assert "setTimeout(() => intakeQuery(), 350)" in script
    assert "intakeIsCurrent(submitSeq, snapshot)" in script
    assert 'duplicate_action: "reuse"' in script
    assert "const accepted = confirmation.accepted || [];" in script
    assert "const skipped = confirmation.skipped || [];" in script
    assert "const failed = confirmation.failed || [];" in script
    assert '部分链接提交失败，输入已保留' in script
    assert 'go("tasks")' in script
    assert "function archivedJobByContent()" in script
    assert 'String(job.state || "").toLowerCase() !== "completed"' in script
    assert "const jobMap = archivedJobByContent();" in script
    assert 'rows="2"' in html


def test_delete_confirmations_use_product_dialog():
    from pathlib import Path

    script = Path(link.__file__).parents[2] / "ui" / "app.js"
    source = script.read_text(encoding="utf-8")
    assert 'id="confirm-dialog"' in (script.parent / "index.html").read_text(encoding="utf-8")
    assert "requestConfirmation(`确认将 ${ids.length} 条内容移入回收站？`" in source
    assert 'requestConfirmation("确认删除这个会话？"' in source
    assert 'requestConfirmation("确认删除这条内容？"' in source
    assert source.count("window.confirm(") == 0
    assert 'requestConfirmation(`确认彻底删除「${title}」？' in source
