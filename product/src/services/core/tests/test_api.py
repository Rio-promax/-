from app.api import main
from app.api import main as api_main
from app.api.main import create_app
from fastapi.testclient import TestClient


def test_source_capabilities_describe_current_adapter_scope() -> None:
    client = TestClient(create_app("sqlite:///:memory:"))

    response = client.get("/api/v1/source-capabilities")

    assert response.status_code == 200
    capabilities = {item["platform"]: item for item in response.json()["capabilities"]}
    assert capabilities["bilibili"]["public_import_available"] is True
    assert capabilities["zhihu"]["public_import_available"] is False

def test_sqlite_store_enables_foreign_keys() -> None:
    client = TestClient(create_app("sqlite:///:memory:"))
    with client.app.state.store.engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_create_content_and_isolated_analysis_run() -> None:
    client = TestClient(create_app("sqlite:///:memory:"))
    health = client.get("/health")
    assert health.status_code == 200

    content_response = client.post(
        "/api/v1/contents",
        json={
            "kind": "video",
            "title": "第一条内容",
            "platform": "local",
        },
    )
    assert content_response.status_code == 201
    content_id = content_response.json()["id"]

    run_response = client.post(
        f"/api/v1/contents/{content_id}/analysis-runs",
        json={"model": "test-model", "strength": "deep"},
    )
    assert run_response.status_code == 201
    payload = run_response.json()
    assert payload["run"]["content_id"] == content_id
    assert payload["run"]["settings_snapshot"]["strength"] == "deep"
    assert payload["job"]["state"] == "queued"

    job_response = client.get(f"/api/v1/jobs/{payload['job']['id']}")
    assert job_response.status_code == 200
    assert job_response.json()["analysis_run_id"] == payload["run"]["id"]


def test_delete_content_invalidates_internal_rag_edges_without_changing_user_tags() -> None:
    from sqlalchemy import select

    from app.db.models import ContentRagDetailTagRow

    client = TestClient(create_app("sqlite:///:memory:"))
    created = client.post("/api/v1/contents", json={
        "kind": "video", "title": "删除边验证", "platform": "local",
    })
    assert created.status_code == 201
    content_id = created.json()["id"]
    store = client.app.state.store
    user_tag = store.create_tag("用户主题")
    store.update_content(content_id, tag_ids=[user_tag.id])
    assert client.get("/api/v1/ask/catalog").status_code == 200
    rag_store = client.app.state.rag_service.rag_store
    internal_tag = rag_store.upsert_detail_tag(
        name="本地细词", definition="内部 RAG 候选", content_id=content_id,
        topic_ids=[], source_refs=["summary:paragraph:1"], source_version="v1",
    )

    deleted = client.delete(f"/api/v1/contents/{content_id}")

    assert deleted.status_code == 200
    with store.session_factory() as session:
        edge = session.execute(select(ContentRagDetailTagRow).where(
            ContentRagDetailTagRow.content_id == content_id,
            ContentRagDetailTagRow.tag_id == internal_tag["id"],
        )).scalar_one()
    assert edge.status == "invalid"
    assert store.tag_ids(content_id) == [user_tag.id]


def test_developer_tag_review_shows_material_and_persists_decision(tmp_path) -> None:
    from datetime import UTC, datetime

    from app.archive.schema import build_record
    from app.archive.writer import ArchiveBundle, write_archive
    from app.domain.models import AnalysisSettings, ContentKind, SourcePlatform, Transcript, TranscriptSegment
    from app.knowledge.transcript import transcript_to_dict

    client = TestClient(create_app("sqlite:///:memory:", archive_root=tmp_path / "archives"))
    client.get("/api/v1/ask/catalog")
    service = client.app.state.rag_service
    store = client.app.state.store
    contents = []
    tag = None
    for number in range(2):
        content = store.create_content(
            kind=ContentKind.ARTICLE,
            title=f"审核材料{number}",
            platform=SourcePlatform.LOCAL,
        )
        phrase = f"材料{number}证明候选方法适用于该流程。"
        transcript = Transcript(
            "zh", "text", "local", (TranscriptSegment(0, 1, phrase),),
            position_kind="detail_only",
        )
        record = build_record(
            content, model="test-model", prompt_version="test-v1",
            transcript_source="text", analyzed_at=datetime(2026, 10, 31, tzinfo=UTC),
        )
        archive = write_archive(tmp_path / "archives", ArchiveBundle(
            record=record,
            summary_markdown=f"总结材料{number}。",
            transcript=transcript_to_dict(transcript),
        )).directory
        summary = f"总结材料{number}。"
        store.upsert_summary(content.id, summary)
        service.index.sync_content(content.id, archive, summary_text=summary)
        service.rag_store.set_coverage(
            content.id, source_version="v1", material_level="M1", status="complete",
        )
        hit = service.index.search_keyword(summary, evidence_kind="summary")[0]
        if tag is None:
            tag = service.rag_store.upsert_detail_tag(
                name="候选方法", definition="按步骤检查材料", content_id=content.id,
                topic_ids=["T11"], source_refs=[hit.stable_id], source_version="v1",
            )
        else:
            service.rag_store.upsert_detail_tag(
                name="候选方法", definition="按步骤检查材料", content_id=content.id,
                topic_ids=["T11"], source_refs=[hit.stable_id], source_version="v1",
            )
        contents.append(content)

    scope = {"kind": "selected", "content_ids": [item.id for item in contents],
             "content_set_id": "SET_REVIEW", "count": len(contents), "material_scope": "full"}
    session = service.rag_store.create_session("审核", scope)
    queries = [service.rag_store.create_query(session["id"], f"问题{i}", scope) for i in range(2)]
    for query, content in zip(queries, contents, strict=True):
        service.rag_store.record_tag_feedback(
            query_id=query["id"], content_id=content.id, tag_id=tag["id"], helpful=True,
        )
    service.rag_store.review_tag_candidate(
        tag["id"], source_supported=True,
        verified_content_ids=[item.id for item in contents], same_concept=False,
    )

    queued = client.get("/api/v1/dev/rag/tag-reviews")

    assert queued.status_code == 200
    candidate = queued.json()[0]
    assert candidate["name"] == "候选方法"
    assert candidate["contexts"][0]["evidence"][0]["text"].startswith("总结材料")
    reviewed = client.post(f"/api/v1/dev/rag/tag-reviews/{tag['id']}", json={
        "decision": "approved", "note": "材料与定义一致",
    })
    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "active"
    audit = service.rag_store.list_developer_tag_reviews(tag["id"])
    assert audit[-1]["decision"] == "approved"
    assert audit[-1]["material_evidence"][0]["text"].startswith("总结材料")


def test_rag_chunking_samples_rechunk_explicitly_selected_archives(tmp_path) -> None:
    from datetime import UTC, datetime

    from app.archive.schema import build_record
    from app.archive.writer import ArchiveBundle, write_archive
    from app.domain.jobs import JobState
    from app.domain.models import AnalysisSettings, ContentKind, SourcePlatform, Transcript, TranscriptSegment
    from app.knowledge.transcript import transcript_to_dict

    client = TestClient(create_app("sqlite:///:memory:", archive_root=tmp_path / "archives"))
    with client:
        store = client.app.state.store
        content = store.create_content(
            kind=ContentKind.ARTICLE, title="动态切块样本", platform=SourcePlatform.LOCAL,
        )
        transcript = Transcript(
            "zh", "text", "local", (TranscriptSegment(0, 2, "原文样本可检索。"),),
            position_kind="detail_only",
        )
        record = build_record(
            content, model="test-model", prompt_version="test-v1", transcript_source="text",
            analyzed_at=datetime(2026, 10, 31, tzinfo=UTC),
        )
        archive = write_archive(tmp_path / "archives", ArchiveBundle(
            record=record, summary_markdown="摘要样本可检索。",
            transcript=transcript_to_dict(transcript),
        )).directory
        store.upsert_summary(content.id, "摘要样本可检索。")
        _run, job = store.create_analysis_run(content.id, AnalysisSettings(model="test-model"))
        job.state = JobState.COMPLETED
        job.completed_at = datetime.now(UTC)
        job.metadata["archive_path"] = str(archive)
        store.save_job(job)

        listed = client.get("/api/v1/dev/rag/chunking/samples")
        assert listed.status_code == 200
        assert listed.json()["items"][0]["content_id"] == content.id

        rebuilt = client.post(
            "/api/v1/dev/rag/chunking/backfill", json={"content_ids": [content.id]},
        )
        assert rebuilt.status_code == 200
        result = rebuilt.json()["results"][0]
        assert result["content_id"] == content.id
        assert result["status"] == "indexed"
        assert result["chunking"]["status"] == "rules_only"
        assert result["chunking"]["error_code"] == "summary_model_unconfigured"
        assert result["chunk_count"] == 2

        too_many = client.post(
            "/api/v1/dev/rag/chunking/backfill",
            json={"content_ids": [content.id] * 6},
        )
        assert too_many.status_code == 422


def test_rag_chunking_samples_reuse_summary_model_and_record_real_boundary_response(
    tmp_path, monkeypatch,
) -> None:
    from datetime import UTC, datetime

    from app.adapters.summary.openai_compatible import OpenAICompatibleSummarizer
    from app.archive.schema import build_record
    from app.archive.writer import ArchiveBundle, write_archive
    from app.domain.jobs import JobState
    from app.domain.models import AnalysisSettings, ContentKind, SourcePlatform, Transcript, TranscriptSegment
    from app.knowledge.transcript import transcript_to_dict

    seen = []

    def complete_json(self, _prompt, _schema, *, timeout, max_output_tokens, max_input_bytes):
        seen.append({
            "model": self.settings.model,
            "timeout": timeout,
            "max_output_tokens": max_output_tokens,
            "max_input_bytes": max_input_bytes,
        })
        return {"ends": [1]}, {"input_bytes": 860, "usage": {"completion_tokens": 4}}

    monkeypatch.setattr(OpenAICompatibleSummarizer, "complete_json", complete_json)
    client = TestClient(create_app("sqlite:///:memory:", archive_root=tmp_path / "archives"))
    with client:
        store = client.app.state.store
        store.set_setting("summary_api_url", "https://summary.example/v1/chat/completions")
        store.set_setting("summary_api_mode", "chat_completions")
        store.set_setting("summary_provider", "openai-compatible")
        store.set_setting("summary_model", "summary-boundary-test")
        monkeypatch.setattr(store, "get_secret_setting", lambda key, purpose: (
            "test-key" if key == "summary_api_key" else None
        ))
        client.app.state.ask_index = None
        client.app.state.rag_service = None

        content = store.create_content(
            kind=ContentKind.ARTICLE, title="总结模型切块", platform=SourcePlatform.LOCAL,
        )
        transcript = Transcript(
            "zh", "text", "local", (TranscriptSegment(0, 2, "原文模型边界材料。"),),
            position_kind="detail_only",
        )
        record = build_record(
            content, model="test-model", prompt_version="test-v1", transcript_source="text",
            analyzed_at=datetime(2026, 10, 31, tzinfo=UTC),
        )
        archive = write_archive(tmp_path / "archives", ArchiveBundle(
            record=record, summary_markdown="摘要模型边界材料。",
            transcript=transcript_to_dict(transcript),
        )).directory
        store.upsert_summary(content.id, "摘要模型边界材料。")
        _run, job = store.create_analysis_run(content.id, AnalysisSettings(model="test-model"))
        job.state = JobState.COMPLETED
        job.completed_at = datetime.now(UTC)
        job.metadata["archive_path"] = str(archive)
        store.save_job(job)

        rebuilt = client.post(
            "/api/v1/dev/rag/chunking/backfill", json={"content_ids": [content.id]},
        )

    assert rebuilt.status_code == 200
    result = rebuilt.json()["results"][0]["chunking"]
    assert {key: value for key, value in result.items() if key != "trace"} == {
        "status": "model", "model": "summary-boundary-test", "calls": 2,
        "input_bytes": 1720, "output_tokens": 8, "error_code": None,
    }
    assert len(seen) == 2
    assert all(item["model"] == "summary-boundary-test" for item in seen)
    assert all(item["max_output_tokens"] == 128 for item in seen)
    assert all(item["max_input_bytes"] == 10000 for item in seen)
    assert [item["boundary_ends"] for item in result["trace"]] == [[1], [1]]
    assert all(item["accepted"] is True for item in result["trace"])


def test_new_chunking_profile_skips_automatic_full_backfill(tmp_path, monkeypatch) -> None:
    from app.knowledge.ask_index import AskIndex

    calls = []
    monkeypatch.setattr(AskIndex, "backfill", lambda self: calls.append(self.profile_id))
    client = TestClient(create_app("sqlite:///:memory:", archive_root=tmp_path / "archives"))

    with client:
        assert client.app.state.ask_index is not None
        assert client.app.state.ask_index._new_profile is True

    assert calls == []


def test_startup_keeps_a_complete_index_profile_without_scheduling_another_backfill(tmp_path) -> None:
    import json
    from datetime import UTC, datetime

    from app.archive.schema import build_record
    from app.archive.writer import ArchiveBundle, write_archive
    from app.domain.jobs import JobState
    from app.domain.models import AnalysisSettings, ContentKind, SourcePlatform, Transcript, TranscriptSegment
    from app.knowledge.ask_index import AskIndex
    from app.knowledge.transcript import transcript_to_dict

    database_url = f"sqlite:///{(tmp_path / 'knowledge.db').as_posix()}"
    archive_root = tmp_path / "archives"
    app = create_app(database_url, archive_root=archive_root)
    with TestClient(app):
        store = app.state.store
        content = store.create_content(
            kind=ContentKind.ARTICLE, title="重启索引", platform=SourcePlatform.LOCAL,
        )
        transcript = Transcript(
            "zh", "text", "local", (TranscriptSegment(0, 1, "重启后的资料仍可检索。"),),
            position_kind="detail_only",
        )
        record = build_record(
            content, model="test-model", prompt_version="test-v1", transcript_source="text",
            analyzed_at=datetime(2026, 10, 31, tzinfo=UTC),
        )
        archive = write_archive(archive_root, ArchiveBundle(
            record=record, summary_markdown="重启后的资料仍可检索。",
            transcript=transcript_to_dict(transcript),
        )).directory
        _run, job = store.create_analysis_run(content.id, AnalysisSettings(model="test-model"))
        job.state = JobState.COMPLETED
        job.completed_at = datetime.now(UTC)
        job.metadata["archive_path"] = str(archive)
        store.save_job(job)
        index = app.state.ask_index
        index.sync_content(content.id, archive, summary_text="重启后的资料仍可检索。")
        profile_id = index.profile_id
        store.set_setting("ask_index_backfill_state", json.dumps({
            "profile_id": profile_id, "status": "complete", "manual_required": False,
        }))

    app = create_app(database_url, archive_root=archive_root)
    with TestClient(app):
        assert app.state.ask_index.profile_id == profile_id
        assert app.state.ask_index_backfill_future is None
        assert app.state.ask_index.coverage_snapshot() == {
            "total_completed": 1, "indexed": 1, "partial": 0, "failed": 0, "pending": 0,
        }


def test_rag_overview_does_not_initialize_index_on_read(monkeypatch) -> None:
    client = TestClient(create_app("sqlite:///:memory:"))

    with client:
        client.app.state.ask_index = None

        def fail_if_initialized(*_args, **_kwargs):
            raise AssertionError("只读概览不应创建索引")

        monkeypatch.setattr(api_main, "AskIndex", fail_if_initialized)
        response = client.get("/api/v1/dev/rag/overview")

    assert response.status_code == 200
    assert response.json()["index"]["status"] == "not_initialized"


def test_developer_rag_graph_searches_attributes_and_traverses_relations() -> None:
    from sqlalchemy import select

    from app.db.models import ContentRagDetailTagRow, RagDetailTagRow
    from app.domain.models import ContentKind, SourcePlatform

    client = TestClient(create_app("sqlite:///:memory:"))
    client.get("/api/v1/ask/catalog")
    store = client.app.state.store
    rag_store = client.app.state.rag_service.rag_store
    folder = store.create_favorite_folder("Graph 集合")
    user_tag = store.create_tag("Graph 用户标签")
    shared = {
        "kind": ContentKind.VIDEO,
        "platform": SourcePlatform.BILIBILI,
        "author": "关系作者甲",
        "favorite_folder_ids": [folder.id],
        "tag_ids": [user_tag.id],
    }
    first = store.create_content(title="Graph 种子内容", **shared)
    second = store.create_content(title="Graph 关联内容", **shared)
    unrelated = store.create_content(
        kind=ContentKind.ARTICLE, title="无关内容", platform=SourcePlatform.LOCAL,
    )
    for content in (first, second):
        rag_store.replace_topics(
            content.id, source_version="v1", material_level="M1",
            topics=[{"topic_id": "T11", "source_refs": ["summary:paragraph:1"]}],
            source_refs=["summary:paragraph:1"],
        )
    active = rag_store.upsert_detail_tag(
        name="正式关系标签", definition="关系检索示例", content_id=first.id,
        topic_ids=["T11"], source_refs=["summary:paragraph:1"], source_version="v1",
    )
    rag_store.upsert_detail_tag(
        name="正式关系标签", definition="关系检索示例", content_id=second.id,
        topic_ids=["T11"], source_refs=["summary:paragraph:1"], source_version="v1",
    )
    candidate = rag_store.upsert_detail_tag(
        name="待审核关系标签", definition="不得进正式关系图", content_id=first.id,
        topic_ids=["T11"], source_refs=["summary:paragraph:1"], source_version="v1",
    )
    with store.session_factory.begin() as db:
        db.get(RagDetailTagRow, active["id"]).status = "active"
        for link in db.execute(select(ContentRagDetailTagRow).where(
            ContentRagDetailTagRow.tag_id == active["id"],
        )).scalars():
            link.status = "active"
    assert unrelated.id not in {first.id, second.id}

    searched = client.get("/api/v1/dev/rag/graph", params={"query": "关系作者甲"})
    assert searched.status_code == 200
    graph = searched.json()
    content_ids = {node.get("content_id") for node in graph["nodes"] if node["kind"] == "content"}
    facet_kinds = {node["kind"] for node in graph["nodes"] if node["kind"] != "content"}
    facet_names = {node["label"] for node in graph["nodes"] if node["kind"] == "detail_tag"}
    assert {first.id, second.id} <= content_ids
    assert {"favorite_folder", "user_tag", "topic", "detail_tag", "platform", "author", "media_type"} <= facet_kinds
    assert "正式关系标签" in facet_names
    assert "待审核关系标签" not in facet_names
    assert not {"created_at", "start_seconds", "text"} & set(graph)
    assert graph["page"] == {
        "offset": 0, "limit": 20, "count": 2, "total_count": 2,
        "has_more": False, "truncated": False,
    }
    query_second_page = client.get(
        "/api/v1/dev/rag/graph", params={"query": "关系作者甲", "limit": 1, "offset": 1},
    ).json()["page"]
    assert query_second_page["count"] == 1
    assert query_second_page["total_count"] == 2
    all_page = client.get("/api/v1/dev/rag/graph", params={"limit": 1}).json()["page"]
    assert all_page["count"] == 1
    assert all_page["total_count"] == 3
    assert all_page["has_more"] is True
    assert graph["relation_coverage"]["topic"] == {"content_count": 2, "content_total": 2}

    traversed = client.get("/api/v1/dev/rag/graph", params={"content_id": first.id, "limit": 1})
    assert traversed.status_code == 200
    assert traversed.json()["related_content_ids"] == [second.id]
    assert traversed.json()["page"]["total_count"] == 2
    assert traversed.json()["relation_coverage"]["favorite_folder"] == {
        "content_count": 2, "content_total": 2,
    }
    traversed_next = client.get("/api/v1/dev/rag/graph", params={
        "content_id": first.id, "limit": 1, "offset": 1,
    }).json()["page"]
    assert traversed_next["count"] == 1
    assert traversed_next["total_count"] == 2
    assert traversed_next["has_more"] is False

    relation_page = client.get("/api/v1/dev/rag/graph", params={
        "facet_id": f"favorite_folder:{folder.id}", "limit": 1,
    }).json()
    assert relation_page["page"] == {
        "offset": 0, "limit": 1, "count": 1, "total_count": 2,
        "has_more": True, "truncated": True,
    }
    next_relation_page = client.get("/api/v1/dev/rag/graph", params={
        "facet_id": f"favorite_folder:{folder.id}", "limit": 1, "offset": 1,
    }).json()
    assert next_relation_page["page"]["count"] == 1
    assert next_relation_page["page"]["total_count"] == 2
    assert next_relation_page["page"]["has_more"] is False
    first_page_ids = {
        node["content_id"] for node in relation_page["nodes"] if node["kind"] == "content"
    }
    second_page_ids = {
        node["content_id"] for node in next_relation_page["nodes"] if node["kind"] == "content"
    }
    assert first_page_ids.isdisjoint(second_page_ids)
    assert first_page_ids | second_page_ids == {first.id, second.id}


def test_cancel_queued_job_and_reject_unknown_content() -> None:
    client = TestClient(create_app("sqlite:///:memory:"))
    missing = client.post(
        "/api/v1/contents/missing/analysis-runs",
        json={"model": "test-model"},
    )
    assert missing.status_code == 404

    content = client.post(
        "/api/v1/contents",
        json={"kind": "article", "title": "文章", "platform": "web"},
    ).json()
    run = client.post(
        f"/api/v1/contents/{content['id']}/analysis-runs",
        json={"model": "test-model"},
    ).json()
    cancelled = client.post(f"/api/v1/jobs/{run['job']['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "cancelled"


def test_pause_and_resume_queued_job() -> None:

    client = TestClient(create_app("sqlite:///:memory:"))
    content = client.post(
        "/api/v1/contents",
        json={"kind": "article", "title": "可暂停文章", "platform": "web"},
    ).json()
    run = client.post(
        f"/api/v1/contents/{content['id']}/analysis-runs",
        json={"model": "test-model"},
    ).json()
    job_id = run["job"]["id"]

    paused = client.post(f"/api/v1/jobs/{job_id}/pause")
    assert paused.status_code == 200
    assert paused.json()["state"] == "paused"

    resumed = client.post(f"/api/v1/jobs/{job_id}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["state"] == "queued"

def test_file_ui_fallback_can_reach_local_api() -> None:
    client = TestClient(create_app("sqlite:///:memory:"))

    page = client.get("/", headers={"Origin": "null"})
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    assert 'window.location.protocol === "file:"' in page.text
    assert "app.js" in page.text
    for marker in (
        "id=\"input-panel\"",
        "id=\"task-preflight\"",
        "id=\"job-panel\"",
        "id=\"refresh-job\"",
        "id=\"summary-style\"",
        "id=\"result-evidence\"",
        "id=\"result-versions\"",
        "id=\"result-feedback\"",
        "id=\"history-category\"",
        "id=\"favorite-folders\"",
        "id=\"favorite-folder-list\"",
        "id=\"add-favorite-content\"",
        "id=\"backfill-introductions\"",
        "id=\"create-favorite-folder\"",
        "id=\"introduction-backfill-status\"",
        "id=\"history-platform\"",
        "id=\"history-author\"",
        "id=\"history-sort\"",
        "id=\"show-trash\"",
        "id=\"library-menu-portal\"",
        "id=\"data-governance-section\"",
        "id=\"cleanup-data\"",
        "id=\"backup-data\"",
        "id=\"restore-data\"",
        "id=\"query-links\"",
        "id=\"query-local\"",
        "id=\"intake-mode-tabs\"",
        "id=\"intake-tab-link\"",
        "id=\"intake-tab-local\"",
        "data-intake-mode=\"link\"",
        "data-intake-mode=\"local\"",
        "id=\"text-file\"",
        "id=\"local-dropzone\"",
        "id=\"link-query-dialog\"",
        "id=\"intake-task-status\"",
        "id=\"job-focus-panel\"",
        "id=\"settings-subnav\"",
        "id=\"settings-content\"",
        "id=\"settings-return\"",
        "data-settings-target=\"operations\"",
        "data-settings-section=\"storage\"",
        "data-task-filter=\"failed\"",
        "data-view=\"intake\"",
        "data-view=\"tasks\"",
        "id=\"ui-theme\"",

    ):
        assert marker in page.text
    intake_view_start = page.text.index('<section class="view" data-view="intake">')
    intake_tabs_position = page.text.index('id="intake-mode-tabs"')
    tasks_view_position = page.text.index('data-view="tasks"')
    assert intake_view_start < intake_tabs_position < tasks_view_position
    result_meta_position = page.text.index('id="result-meta"')
    result_tags_position = page.text.index('id="result-tags-panel"')
    reading_position = page.text.index('class="result-reading-layout"')
    result_navigation_position = page.text.index('class="result-footer-navigation"')
    result_evidence_position = page.text.index('id="result-evidence"')
    result_versions_position = page.text.index('id="result-versions"')
    result_feedback_position = page.text.index('id="result-feedback"')
    assert result_meta_position < result_tags_position < reading_position < result_navigation_position
    assert result_navigation_position < result_evidence_position < result_versions_position < result_feedback_position
    script = client.get("/ui/app.js")
    assert script.status_code == 200
    assert "job-feedback" in script.text
    assert "/api/v1/data-governance" in script.text
    assert "/api/v1/favorite-folders" in script.text
    assert "/api/v1/imports/query" in script.text
    assert "queryLocalSource" in script.text
    assert "confirmLocalQuery" in script.text
    assert "retryLinkUrls" in script.text
    assert "loadTaskList" in script.text
    assert "showIntakeMode" in script.text
    assert script.text.count("function showView(") == 1
    assert script.text.count("function loadResult(") == 1
    assert script.text.count("function renderResultDocument(") == 1
    assert 'document.querySelector(".main-content")' in script.text
    assert "intakeModeTabs?.querySelectorAll" in script.text
    assert "intakeModeTabs?.addEventListener(\"keydown\"" in script.text
    assert "ArrowRight" in script.text
    assert "queryLinksButton.hidden = true" in script.text
    assert "syncImportAction" in script.text
    assert "await queryLinks();" in script.text
    assert "settingsScrollTops" in script.text
    assert "createSourceCover" in script.text
    assert "activeContentSnapshot" in script.text
    assert "pixel-cat" in script.text
    stylesheet = client.get("/ui/style.css")
    assert stylesheet.status_code == 200
    assert "pixel-cat-walk-frame-1" in stylesheet.text
    assert "pixel-cat-walk-frame-2" in stylesheet.text
    assert "pixel-cat-walk-frame-3" in stylesheet.text
    assert "prefers-reduced-motion" in stylesheet.text
    assert "[hidden]" in stylesheet.text
    assert "overscroll-behavior: contain" in stylesheet.text
    assert "pixel-cat-sprite-day.svg" in stylesheet.text
    assert "pixel-cat-sprite-night.svg" in stylesheet.text
    for asset in ("pixel-cat-sprite-day.svg", "pixel-cat-sprite-night.svg"):
        sprite = client.get(f"/ui/{asset}")
        assert sprite.status_code == 200
        assert "shape-rendering=\"crispEdges\"" in sprite.text
    assert "scheduleSourceProbe(value)" not in script.text
    assert page.headers["access-control-allow-origin"] == "null"

    preflight = client.options(
        "/api/v1/settings",
        headers={
            "Origin": "null",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "null"


def test_summary_prompt_ui_uses_debounced_partial_save_without_prompt_identity_details() -> None:
    client = TestClient(create_app("sqlite:///:memory:"))

    page = client.get("/")
    script = client.get("/ui/app.js").text

    assert page.status_code == 200
    assert 'id="summary-prompt-save-status"' in page.text
    assert 'id="retry-summary-prompt"' in page.text
    assert "summaryPromptSaveTimer" in script
    assert "}, 700);" in script
    assert "正在保存" in script
    assert "已保存" in script
    assert "保存失败" in script
    assert 'body: JSON.stringify({ summary_prompt: prompt })' in script
    assert "summary_prompt_version" not in script
    assert "summary_prompt_hash" not in script
    form_builder = script.split("function summaryConfigFromForm", 1)[1].split(
        "function scheduleSummaryPromptSave", 1
    )[0]
    assert "summary_prompt" not in form_builder


def test_local_asr_catalog_and_separate_engine_config(monkeypatch) -> None:
    from app.db import store as store_module

    monkeypatch.setattr(
        store_module,
        "protect_secret",
        lambda value, *, purpose: "dpapi:asr-test-key",
    )
    monkeypatch.setattr(
        store_module,
        "unprotect_secret",
        lambda value, *, purpose: "test-key",
    )
    client = TestClient(create_app("sqlite:///:memory:"))

    catalog = client.get("/api/v1/asr/local-models")
    assert catalog.status_code == 200
    payload = catalog.json()
    assert payload["model_root"].endswith("local\\asr-models")
    assert {item["id"] for item in payload["models"]} == {
        "sensevoice-small",
        "small",
        "base",
        "medium",
        "large-v3-turbo",
        "large-v3",
    }

    unavailable = client.put(
        "/api/v1/settings",
        json={"asr_engine": "local", "asr_model": "large-v3"},
    )
    assert unavailable.status_code == 422

    cloud = client.put(
        "/api/v1/settings",
        json={
            "asr_engine": "cloud",
            "asr_api_url": "https://asr.example.test/v1/transcriptions",
            "asr_api_key": "test-key",
            "asr_model": "cloud-model",
        },
    )
    assert cloud.status_code == 200

    monkeypatch.setattr(main, "local_asr_runtime_available", lambda: True)
    monkeypatch.setattr(main, "is_local_model_ready", lambda _root, model: model == "large-v3")
    local = client.put(
        "/api/v1/settings",
        json={"asr_engine": "local", "asr_model": "large-v3"},
    )
    assert local.status_code == 200
    body = local.json()
    assert body["asr_engine"] == "local"
    assert body["asr_local_model"] == "large-v3"
    assert body["asr_cloud_api_url"] == "https://asr.example.test/v1/transcriptions"
    assert body["asr_cloud_model"] == "cloud-model"
    assert body["asr_cloud_configured"] is True
    assert body["asr_local_configured"] is True

    cleared = client.put("/api/v1/settings", json={"asr_local_model": None})
    assert cleared.status_code == 200
    assert cleared.json()["asr_local_model"] is None
    assert cleared.json()["asr_cloud_model"] == "cloud-model"


def test_cloud_asr_requires_explicit_endpoint_model_and_key(monkeypatch) -> None:
    from app.db import store as store_module

    monkeypatch.setattr(
        store_module,
        "protect_secret",
        lambda value, *, purpose: "dpapi:asr-test-key",
    )
    monkeypatch.setattr(
        store_module,
        "unprotect_secret",
        lambda value, *, purpose: "test-key",
    )
    client = TestClient(create_app("sqlite:///:memory:"))

    response = client.put(
        "/api/v1/settings",
        json={"asr_engine": "cloud", "asr_api_key": "test-key"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["asr_cloud_configured"] is False
    assert body["asr_configured"] is False
    assert body["asr_cloud_api_url"] is None
    assert body["asr_cloud_model"] is None


def test_settings_secret_storage_failure_returns_actionable_422(monkeypatch) -> None:
    client = TestClient(create_app("sqlite:///:memory:"))

    class FakeSummarizer:
        def __init__(self, settings) -> None:
            self.settings = settings

        def test_connection(self) -> None:
            return None

    monkeypatch.setattr(api_main, "OpenAICompatibleSummarizer", FakeSummarizer)
    validation = client.post(
        "/api/v1/settings/summary/test",
        json={
            "summary_provider": "openai",
            "summary_api_url": "https://summary.example.test/v1",
            "summary_api_mode": "chat_completions",
            "summary_model": "test-model",
            "summary_api_key": "test-key",
        },
    )
    assert validation.status_code == 200

    from app.db import store as store_module
    from app.platforms.secrets import SecretStorageError

    def fail(value: str, *, purpose: str) -> str:
        raise SecretStorageError(f"无法保护{purpose}失败（Windows 错误 2）")

    monkeypatch.setattr(store_module, "protect_secret", fail)
    response = client.put(
        "/api/v1/settings",
        json={
            "summary_provider": "openai",
            "summary_api_url": "https://summary.example.test/v1",
            "summary_api_mode": "chat_completions",
            "summary_model": "test-model",
            "summary_api_key": "test-key",
            "summary_validation_token": validation.json()["validation_token"],
        },
    )

    assert response.status_code == 422
    assert "请求未完成" not in response.text
    assert "Windows 错误 2" in response.json()["detail"]

def test_local_asr_download_rejects_unknown_model() -> None:
    client = TestClient(create_app("sqlite:///:memory:"))

    response = client.post("/api/v1/asr/local-models/not-a-model/download")

    assert response.status_code == 404
    assert response.json()["detail"] == "local_asr_model_not_supported"


def test_dev_rag_overview_labels_vector_state_coverage_as_unverified() -> None:
    client = TestClient(create_app("sqlite:///:memory:"))

    class SnapshotIndex:
        profile_id = "fts-profile"
        vector_configured = True

        def coverage_snapshot(self):
            return {"total_completed": 1, "indexed": 1, "partial": 0, "failed": 0, "pending": 0}

        def vector_state_coverage_snapshot(self):
            return {
                "profile_id": "vector-profile",
                "total_completed": 1,
                "indexed": 1,
                "partial": 0,
                "failed": 0,
                "pending": 0,
                "status_record_covered_chunks": 1,
                "total_chunks": 2,
                "coverage_basis": "status_records",
                "vector_points_verified": False,
                "errors": {},
            }

    client.app.state.ask_index = SnapshotIndex()

    response = client.get("/api/v1/dev/rag/overview")

    assert response.status_code == 200
    overview = response.json()
    vector = overview["index"]["vector"]
    assert overview["index"]["vector_status"] == "state_records_available"
    assert vector["status_record_covered_chunks"] == 1
    assert vector["coverage_basis"] == "status_records"
    assert vector["vector_points_verified"] is False
    assert "covered_chunks" not in vector
    assert "api_key" not in overview
    assert "api_url" not in overview
