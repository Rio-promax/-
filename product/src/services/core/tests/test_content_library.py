from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from app.api.main import create_app
from app.db.store import SQLiteStore
from app.domain.jobs import JobState
from fastapi.testclient import TestClient
from sqlalchemy import inspect


def make_client(tmp_path: Path) -> TestClient:
    return TestClient(create_app("sqlite:///:memory:", tmp_path / "knowledge-root"))


def install_fake_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.workflows import analyze

    class FakeSummarizer:
        def __init__(self, _settings) -> None:
            pass

        def summarize_chunks(self, chunks, *, title, strength, prompt, skill=None):
            text = "\n".join(chunk.text for chunk in chunks)
            return SimpleNamespace(
                markdown=f"# 内容总结\n\n## 概览\n\n{text}\n",
                overview=text,
            )

    monkeypatch.setattr(analyze, "OpenAICompatibleSummarizer", FakeSummarizer)


def create_content(client: TestClient, title: str, *, category: str = "未分类") -> dict:
    response = client.post(
        "/api/v1/contents",
        json={
            "kind": "video",
            "title": title,
            "platform": "bilibili",
            "canonical_url": f"https://www.bilibili.com/video/{title}",
            "author": "测试作者",
            "language": "zh-CN",
            "duration_seconds": 120,
            "published_at": "2026-08-20T12:00:00Z",
            "category": category,
            "processing_model": "test-model",
        },
    )
    assert response.status_code == 201
    content = response.json()
    run = client.post(
        f"/api/v1/contents/{content['id']}/analysis-runs",
        json={"model": "test-model"},
    )
    assert run.status_code == 201
    return content


def complete_content_job(client: TestClient, content_id: str) -> None:
    job = client.app.state.store.get_history_entry(content_id).job
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
        job.transition(target)
    client.app.state.store.save_job(job)


def test_content_library_supports_sort_filter_and_source_metadata(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    first = create_content(client, "BV-first", category="课程")
    second = create_content(client, "BV-second", category="课程")

    assert first["published_at"] == "2026-08-20T12:00:00Z"
    assert first["acquisition_method"] == "api"
    assert first["processing_model"] == "test-model"

    ascending = client.get(
        "/api/v1/history",
        params={"category": "课程", "sort_by": "created_at", "order": "asc"},
    )
    descending = client.get(
        "/api/v1/history",
        params={"category": "课程", "sort_by": "created_at", "order": "desc"},
    )
    assert ascending.status_code == 200
    assert [item["content"]["id"] for item in descending.json()] == [
        item["content"]["id"] for item in ascending.json()
    ][::-1]
    assert {item["content"]["id"] for item in ascending.json()} == {
        first["id"],
        second["id"],
    }


def test_archived_library_count_is_global_and_excludes_deleted(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    first = create_content(client, "BV-count-one")
    second = create_content(client, "BV-count-two")
    assert client.get("/api/v1/history/count").json() == {"total": 0}
    complete_content_job(client, first["id"])
    complete_content_job(client, second["id"])
    assert client.get("/api/v1/history/count").json() == {"total": 2}
    assert client.app.state.store.count_archived_contents() == 2
    client.app.state.store.soft_delete_content(first["id"])
    assert client.get("/api/v1/history/count").json() == {"total": 1}


def test_content_delete_restore_categories_and_batch_actions(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    first = create_content(client, "BV-delete-one")
    second = create_content(client, "BV-delete-two")

    updated = client.patch(
        f"/api/v1/contents/{first['id']}",
        json={"category": "稍后阅读", "favorite": True},
    )
    assert updated.status_code == 200
    assert updated.json()["favorite"] is True
    assert client.get("/api/v1/history", params={"category": "稍后阅读"}).json()[0]["content"]["id"] == first["id"]

    moved = client.post(
        "/api/v1/contents/batch",
        json={"ids": [second["id"]], "action": "move", "category": "稍后阅读"},
    )
    assert moved.status_code == 200
    assert moved.json()[0]["category"] == "稍后阅读"

    deleted = client.delete(f"/api/v1/contents/{first['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted_at"] is not None
    assert not any(item["content"]["id"] == first["id"] for item in client.get("/api/v1/history").json())
    trash = client.get("/api/v1/trash")
    assert trash.status_code == 200
    assert trash.json()[0]["content"]["id"] == first["id"]

    restored = client.post(f"/api/v1/contents/{first['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["deleted_at"] is None
    assert any(item["content"]["id"] == first["id"] for item in client.get("/api/v1/history").json())

    batch_deleted = client.post(
        "/api/v1/contents/batch",
        json={"ids": [first["id"], second["id"]], "action": "delete"},
    )
    assert batch_deleted.status_code == 200
    assert len(client.get("/api/v1/trash").json()) == 2


def test_duplicate_actions_and_content_exports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_summary(monkeypatch)
    client = make_client(tmp_path)
    payload = {"title": "重复文本", "text": "字幕唯一词：保留原始内容。", "max_chunk_tokens": 32}

    first = client.post("/api/v1/imports/local", json=payload)
    assert first.status_code == 201
    first_payload = first.json()
    client.app.state.store.upsert_summary(
        first_payload["content"]["id"],
        "摘要不包含检索词",
        transcript_text="字幕索引独有词",
    )
    searched = client.get("/api/v1/history", params={"q": "字幕索引独有词"})
    assert searched.status_code == 200
    assert searched.json()[0]["content"]["id"] == first_payload["content"]["id"]
    reused = client.post("/api/v1/imports/local", json={**payload, "duplicate_action": "reuse"})
    assert reused.status_code == 201
    assert reused.json()["duplicate"] is True
    assert reused.json()["content"]["id"] == first_payload["content"]["id"]

    regenerated = client.post(
        "/api/v1/imports/local", json={**payload, "duplicate_action": "regenerate"}
    )
    assert regenerated.status_code == 201
    assert regenerated.json()["content"]["id"] != first_payload["content"]["id"]
    assert regenerated.json()["content"]["title"] == first_payload["content"]["title"] + "（1）"
    regenerated_job = client.get(
        f"/api/v1/jobs/{regenerated.json()['job']['id']}"
    ).json()
    assert regenerated.json()["content"]["title"].endswith("（1）")
    assert regenerated.json()["content"]["id"] in regenerated_job["archive_path"]
    assert regenerated_job["archive_path"].endswith("-1--" + regenerated.json()["content"]["id"])

    overwritten = client.post(
        "/api/v1/imports/local", json={**payload, "duplicate_action": "overwrite"}
    )
    assert overwritten.status_code == 201
    assert overwritten.json()["content"]["id"] == regenerated.json()["content"]["id"]
    assert overwritten.json()["run"]["id"] != first_payload["run"]["id"]

    content_id = first_payload["content"]["id"]
    markdown = client.get(f"/api/v1/contents/{content_id}/export", params={"format": "markdown"})
    plain = client.get(f"/api/v1/contents/{content_id}/export", params={"format": "text"})
    subtitle = client.get(f"/api/v1/contents/{content_id}/export", params={"format": "subtitle"})
    structured = client.get(f"/api/v1/contents/{content_id}/export", params={"format": "json"})
    assert markdown.status_code == plain.status_code == subtitle.status_code == structured.status_code == 200
    assert "字幕唯一词" in markdown.text
    assert "字幕唯一词" in plain.text
    assert "-->" in subtitle.text
    assert structured.json()["content_id"] == content_id

    batch_export = client.post(
        "/api/v1/contents/export",
        json={"ids": [content_id], "format": "markdown"},
    )
    assert batch_export.status_code == 200
    with ZipFile(BytesIO(batch_export.content)) as archive:
        assert archive.namelist()
        assert "字幕唯一词" in archive.read(archive.namelist()[0]).decode("utf-8")



def test_favorite_folders_support_create_assign_filter_and_delete(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    first = create_content(client, "收藏夹内容一")
    second = create_content(client, "收藏夹内容二")
    complete_content_job(client, first["id"])
    complete_content_job(client, second["id"])

    created = client.post("/api/v1/favorite-folders", json={"name": "课程重点"})
    assert created.status_code == 201
    folder = created.json()
    assert folder["name"] == "课程重点"
    assert folder["content_count"] == 0

    assigned = client.patch(
        f"/api/v1/contents/{first['id']}",
        json={"favorite_folder_ids": [folder["id"]]},
    )
    assert assigned.status_code == 200
    assert assigned.json()["favorite"] is True
    assert assigned.json()["favorite_folder_ids"] == [folder["id"]]

    all_favorites = client.get(
        "/api/v1/history",
        params={"favorite_folder_id": "all", "archived_only": "true"},
    )
    assert [item["content"]["id"] for item in all_favorites.json()] == [first["id"]]
    scoped = client.get(
        "/api/v1/history",
        params={"favorite_folder_id": folder["id"], "archived_only": "true"},
    )
    assert [item["content"]["id"] for item in scoped.json()] == [first["id"]]

    second_assigned = client.patch(
        f"/api/v1/contents/{second['id']}",
        json={"favorite": True, "favorite_folder_ids": [folder["id"]]},
    )
    assert second_assigned.status_code == 200
    folders = client.get("/api/v1/favorite-folders").json()
    assert folders[0]["id"] == "all"
    assert folders[0]["content_count"] == 2
    assert folders[1]["content_count"] == 2

    renamed = client.patch(
        f"/api/v1/favorite-folders/{folder['id']}",
        json={"name": "重点课程"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "重点课程"

    deleted = client.delete(f"/api/v1/favorite-folders/{folder['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/contents/{first['id']}").json()["favorite_folder_ids"] == []
    assert client.get("/api/v1/history", params={"favorite_folder_id": "all"}).status_code == 200


def test_library_tags_and_folders_share_completed_content_set(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    tagged_and_favorited = create_content(client, "完成且多关系")
    tagged_only = create_content(client, "完成仅标签")
    favorited_only = create_content(client, "完成仅收藏夹")
    unfinished = create_content(client, "未完成关系")
    deleted = create_content(client, "已删除关系")
    for content in (tagged_and_favorited, tagged_only, favorited_only, deleted):
        complete_content_job(client, content["id"])

    primary_tag = client.post("/api/v1/tags", json={"name": "主标签"}).json()
    secondary_tag = client.post("/api/v1/tags", json={"name": "副标签"}).json()
    primary_folder = client.post("/api/v1/favorite-folders", json={"name": "主收藏夹"}).json()
    secondary_folder = client.post("/api/v1/favorite-folders", json={"name": "副收藏夹"}).json()

    client.patch(
        f"/api/v1/contents/{tagged_and_favorited['id']}",
        json={
            "tag_ids": [primary_tag["id"], secondary_tag["id"]],
            "favorite_folder_ids": [primary_folder["id"], secondary_folder["id"]],
        },
    )
    client.patch(
        f"/api/v1/contents/{tagged_only['id']}",
        json={"tag_ids": [primary_tag["id"]]},
    )
    client.patch(
        f"/api/v1/contents/{favorited_only['id']}",
        json={"favorite_folder_ids": [primary_folder["id"]]},
    )
    client.patch(
        f"/api/v1/contents/{unfinished['id']}",
        json={
            "tag_ids": [primary_tag["id"]],
            "favorite_folder_ids": [primary_folder["id"]],
        },
    )
    client.patch(
        f"/api/v1/contents/{deleted['id']}",
        json={
            "tag_ids": [primary_tag["id"]],
            "favorite_folder_ids": [primary_folder["id"]],
        },
    )
    assert client.delete(f"/api/v1/contents/{deleted['id']}").status_code == 200

    library = client.get("/api/v1/history", params={"archived_only": "true"}).json()
    library_ids = {item["content"]["id"] for item in library}
    assert library_ids == {
        tagged_and_favorited["id"],
        tagged_only["id"],
        favorited_only["id"],
    }

    tags = {item["id"]: item for item in client.get("/api/v1/tags").json()}
    assert tags[primary_tag["id"]]["content_count"] == 2
    assert tags[secondary_tag["id"]]["content_count"] == 1
    tagged_ids = {
        item["content"]["id"]
        for item in client.get(
            "/api/v1/history",
            params={"tag_id": primary_tag["id"], "archived_only": "true"},
        ).json()
    }
    assert tagged_ids == {tagged_and_favorited["id"], tagged_only["id"]}
    assert len(tagged_ids) == tags[primary_tag["id"]]["content_count"]
    secondary_tag_ids = {
        item["content"]["id"]
        for item in client.get(
            "/api/v1/history",
            params={"tag_id": secondary_tag["id"], "archived_only": "true"},
        ).json()
    }
    assert secondary_tag_ids == {tagged_and_favorited["id"]}
    assert len(secondary_tag_ids) == tags[secondary_tag["id"]]["content_count"]

    folders = {item["id"]: item for item in client.get("/api/v1/favorite-folders").json()}
    assert folders["all"]["content_count"] == 2
    assert folders[primary_folder["id"]]["content_count"] == 2
    assert folders[secondary_folder["id"]]["content_count"] == 1
    favorited_ids = {
        item["content"]["id"]
        for item in client.get(
            "/api/v1/history",
            params={"favorite_folder_id": primary_folder["id"], "archived_only": "true"},
        ).json()
    }
    assert favorited_ids == {tagged_and_favorited["id"], favorited_only["id"]}
    assert len(favorited_ids) == folders[primary_folder["id"]]["content_count"]
    secondary_folder_ids = {
        item["content"]["id"]
        for item in client.get(
            "/api/v1/history",
            params={"favorite_folder_id": secondary_folder["id"], "archived_only": "true"},
        ).json()
    }
    assert secondary_folder_ids == {tagged_and_favorited["id"]}
    assert len(secondary_folder_ids) == folders[secondary_folder["id"]]["content_count"]
    all_favorite_ids = {
        item["content"]["id"]
        for item in client.get(
            "/api/v1/history",
            params={"favorite_folder_id": "all", "archived_only": "true"},
        ).json()
    }
    assert all_favorite_ids == {tagged_and_favorited["id"], favorited_only["id"]}
    assert len(all_favorite_ids) == folders["all"]["content_count"]

    cleared_tag = client.get("/api/v1/history", params={"archived_only": "true"}).json()
    assert {item["content"]["id"] for item in cleared_tag} == library_ids


def test_tags_nested_folders_introduction_batch_and_job_retention(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    first = create_content(client, "标签内容一")
    second = create_content(client, "标签内容二")

    tag = client.post("/api/v1/tags", json={"name": "教程"})
    assert tag.status_code == 201
    tag_id = tag.json()["id"]
    updated = client.patch(
        f"/api/v1/contents/{first['id']}",
        json={"tag_ids": [tag_id], "introduction": "三十字以内的内容简介"},
    )
    assert updated.status_code == 200
    assert updated.json()["tag_ids"] == [tag_id]
    assert updated.json()["tag_names"] == ["教程"]
    assert updated.json()["introduction"] == "三十字以内的内容简介"
    assert client.get("/api/v1/history", params={"tag_id": tag_id, "archived_only": "false"}).json()[0]["content"]["id"] == first["id"]

    root = client.post("/api/v1/favorite-folders", json={"name": "课程", "parent_id": None})
    child = client.post("/api/v1/favorite-folders", json={"name": "重点", "parent_id": root.json()["id"]})
    assert root.status_code == child.status_code == 201
    assert child.json()["parent_id"] == root.json()["id"]
    assigned = client.patch(
        f"/api/v1/contents/{first['id']}",
        json={"favorite_folder_ids": [child.json()["id"]]},
    )
    assert assigned.status_code == 200

    batch = client.post(
        "/api/v1/contents/batch-organize",
        json={"ids": [first["id"], second["id"], "missing"], "operation": "add_tag", "tag_id": tag_id},
    )
    assert batch.status_code == 200
    assert first["id"] in batch.json()["skipped"]
    assert second["id"] in batch.json()["succeeded"]
    assert any(item["id"] == "missing" for item in batch.json()["failed"])

    too_long = client.patch(
        f"/api/v1/contents/{first['id']}",
        json={"introduction": "一" * 31},
    )
    assert too_long.status_code == 422

    run_response = client.post(
        f"/api/v1/contents/{second['id']}/analysis-runs", json={"model": "test-model"}
    )
    assert run_response.status_code == 201
    job = client.app.state.store.get_job(run_response.json()["job"]["id"])
    from app.domain.jobs import JobState
    for target in (JobState.ACQUIRING, JobState.EXTRACTING, JobState.TRANSCRIBING, JobState.CHUNKING, JobState.SUMMARIZING, JobState.ARCHIVING, JobState.INDEXING, JobState.COMPLETED):
        job.transition(target)
    archive_file = tmp_path / "knowledge-root" / "retained" / "record.json"
    archive_file.parent.mkdir(parents=True, exist_ok=True)
    archive_file.write_text('{"content_id": "retained"}', encoding="utf-8")
    job.metadata["archive_path"] = str(archive_file.parent)
    client.app.state.store.save_job(job)
    deleted = client.delete(f"/api/v1/jobs/{job.id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/contents/{second['id']}").status_code == 200
    assert archive_file.is_file()
    assert client.get("/api/v1/history", params={"archived_only": "false"}).json()

    assert client.delete(f"/api/v1/contents/{first['id']}").status_code == 200
    deleted_batch = client.post(
        "/api/v1/contents/batch-organize",
        json={"ids": [first["id"]], "operation": "add_tag", "tag_id": tag_id},
    )
    assert deleted_batch.status_code == 200
    assert deleted_batch.json()["skipped"] == [first["id"]]


def test_tag_and_folder_save_failures_leave_existing_content_unchanged(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    content = create_content(client, "归类失败回归")

    missing_folder = client.patch(
        f"/api/v1/contents/{content['id']}",
        json={"favorite_folder_ids": ["missing-folder"]},
    )
    missing_tag = client.patch(
        f"/api/v1/contents/{content['id']}",
        json={"tag_ids": ["missing-tag"]},
    )

    assert missing_folder.status_code == 404
    assert missing_tag.status_code == 404
    unchanged = client.get(f"/api/v1/contents/{content['id']}")
    assert unchanged.status_code == 200
    assert unchanged.json()["favorite_folder_ids"] == []
    assert unchanged.json()["tag_ids"] == []


def test_runtime_indexes_and_nested_folder_cycle_guard() -> None:
    store = SQLiteStore("sqlite:///:memory:")
    index_names = {
        index["name"]
        for table in ("content_tags", "content_favorite_folders")
        for index in inspect(store.engine).get_indexes(table)
    }
    assert "ix_content_tags_tag_id" in index_names
    assert "ix_content_favorite_folders_folder_id" in index_names

    root = store.create_favorite_folder("根目录")
    child = store.create_favorite_folder("子目录", parent_id=root.id)
    with pytest.raises(ValueError, match="favorite_folder_parent_conflicts"):
        store.update_favorite_folder_parent(root.id, child.id)


def test_non_archived_history_is_deduplicated_by_content(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    content = create_content(client, "多次处理但一张卡")
    rerun = client.post(
        f"/api/v1/contents/{content['id']}/analysis-runs", json={"model": "test-model"}
    )
    assert rerun.status_code == 201

    response = client.get("/api/v1/history", params={"archived_only": "false"})
    assert response.status_code == 200
    assert [item["content"]["id"] for item in response.json()] == [content["id"]]


def test_queue_reorder_and_priority_contract(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    first = create_content(client, "队列一")
    second = create_content(client, "队列二")
    jobs = client.get("/api/v1/jobs", params={"state": "queued"}).json()
    assert len(jobs) == 2
    ids = [jobs[1]["id"], jobs[0]["id"]]
    reordered = client.post("/api/v1/queue/reorder", json={"job_ids": ids})
    assert reordered.status_code == 200
    promoted = client.patch(
        f"/api/v1/jobs/{ids[1]}/priority",
        json={"priority": 1},
    )
    assert promoted.status_code == 200
    assert promoted.json()["priority"] == 1
    listed = client.get("/api/v1/jobs", params={"state": "queued"}).json()
    assert listed[0]["id"] == ids[1]
    assert {item["content_id"] for item in listed} == {first["id"], second["id"]}


def test_archived_history_deduplicates_retried_content(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    content = create_content(client, "重复归档")
    first_job = client.app.state.store.list_jobs()[0]
    from app.domain.jobs import JobState

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
        first_job.transition(target)
    client.app.state.store.save_job(first_job)
    second_run = client.post(
        f"/api/v1/contents/{content['id']}/analysis-runs", json={"model": "test-model"}
    )
    assert second_run.status_code == 201
    second_job = client.app.state.store.get_job(second_run.json()["job"]["id"])
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
        second_job.transition(target)
    client.app.state.store.save_job(second_job)

    archived = client.get("/api/v1/history", params={"archived_only": "true"})
    assert archived.status_code == 200
    assert [item["content"]["id"] for item in archived.json()] == [content["id"]]


def test_archived_history_paginates_after_content_deduplication(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    from app.domain.jobs import JobState

    content_ids = []
    for index in range(3):
        content = create_content(client, f"分页内容 {index}")
        content_ids.append(content["id"])
        job = client.app.state.store.list_jobs()[-1]
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
            job.transition(target)
        client.app.state.store.save_job(job)

    first = client.get(
        "/api/v1/history",
        params={"archived_only": "true", "limit": 2, "offset": 0},
    )
    second = client.get(
        "/api/v1/history",
        params={"archived_only": "true", "limit": 2, "offset": 2},
    )
    assert first.status_code == second.status_code == 200
    assert len(first.json()) == 2
    assert len(second.json()) == 1
    assert set(item["content"]["id"] for item in first.json() + second.json()) == set(content_ids)
