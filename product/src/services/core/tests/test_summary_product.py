from pathlib import Path
from types import SimpleNamespace

import pytest
from app.api.main import create_app
from fastapi.testclient import TestClient


def make_client(tmp_path: Path) -> TestClient:
    return TestClient(create_app("sqlite:///:memory:", tmp_path / "knowledge-root"))


def test_edit_summary_version_creates_latest_version_without_overwriting(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    created = client.post(
        "/api/v1/contents",
        json={
            "kind": "video",
            "title": "版本编辑",
            "platform": "bilibili",
            "canonical_url": "https://www.bilibili.com/video/BV-version-edit",
            "author": "测试作者",
            "language": "zh-CN",
            "duration_seconds": 120,
            "published_at": "2026-08-20T12:00:00Z",
            "category": "未分类",
            "processing_model": "test-model",
        },
    )
    assert created.status_code == 201
    content_id = created.json()["id"]
    original = client.app.state.store.create_summary_version(
        content_id, "# 原正文", template="general", origin="original"
    )
    saved = client.put(
        f"/api/v1/contents/{content_id}/summary-versions/{original.id}",
        json={"markdown": "# 修改后正文"},
    )
    assert saved.status_code == 201
    versions = client.get(f"/api/v1/contents/{content_id}/summary-versions").json()
    assert [version["markdown"] for version in versions] == ["# 修改后正文", "# 原正文"]
    assert versions[0]["parent_version_id"] == original.id


def install_fake_summary(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str | None, str]]:
    from app.workflows import analyze

    calls = []

    class FakeSummarizer:
        def __init__(self, _settings) -> None:
            pass

        def summarize_chunks(
            self, chunks, *, title, strength, prompt, skill=None, template=None, style="general", text_material=False
        ):
            calls.append((template, style))
            text = "\n".join(chunk.text for chunk in chunks)
            return SimpleNamespace(
                markdown=(
                    f"# 内容总结\n\n## 概览\n\n{text}\n\n"
                    "## 关键要点\n\n- 结论。\n\n## 分段笔记\n\n### 片段\n"
                ),
                overview=text,
                key_points=(f"结论（模板：{template}）。",),
            )

    monkeypatch.setattr(analyze, "OpenAICompatibleSummarizer", FakeSummarizer)
    return calls


def test_result_exposes_evidence_versions_and_feedback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = install_fake_summary(monkeypatch)
    client = make_client(tmp_path)

    created = client.post(
        "/api/v1/imports/local",
        json={
            "title": "证据版本测试",
            "text": "第一段事实。\n\n第二段结论。",
            "summary_template": "meeting_minutes",
            "summary_style": "general",
        },
    )
    assert created.status_code == 201
    assert calls == [(None, "meeting_minutes")]
    content_id = created.json()["content"]["id"]

    result = client.get(f"/api/v1/contents/{content_id}/result")
    assert result.status_code == 200
    payload = result.json()
    assert payload["evidence"][0]["text"] == "第一段事实。"
    assert payload["versions"][0]["origin"] == "original"
    assert payload["versions"][0]["template"] == "meeting_minutes"
    assert payload["versions"][0]["summary_style"] == "meeting_minutes"
    assert payload["feedback"] == []


def test_partial_summary_edit_compare_and_feedback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_summary(monkeypatch)
    client = make_client(tmp_path)
    created = client.post(
        "/api/v1/imports/local",
        json={"title": "局部生成测试", "text": "第一段。\n\n第二段。"},
    )
    content_id = created.json()["content"]["id"]
    original = client.get(f"/api/v1/contents/{content_id}/result").json()["versions"][0]

    partial = client.post(
        f"/api/v1/contents/{content_id}/summary-versions/partial",
        json={"start_seconds": 0, "end_seconds": 30, "chapter_title": "第一章"},
    )
    assert partial.status_code == 201
    partial_version = partial.json()
    assert partial_version["origin"] == "partial"
    assert partial_version["parent_version_id"] == original["id"]

    edited = client.put(
        f"/api/v1/contents/{content_id}/summary-versions/{partial_version['id']}",
        json={"markdown": "# 手工修订\n\n保留证据。"},
    )
    assert edited.status_code == 201
    edited_version = edited.json()
    assert edited_version["origin"] == "edited"
    assert edited_version["parent_version_id"] == partial_version["id"]

    comparison = client.get(
        f"/api/v1/contents/{content_id}/summary-versions/compare",
        params={"left_id": partial_version["id"], "right_id": edited_version["id"]},
    )
    assert comparison.status_code == 200
    assert "手工修订" in comparison.json()["diff"]

    feedback = client.post(
        f"/api/v1/contents/{content_id}/feedback",
        json={
            "version_id": edited_version["id"],
            "category": "omission",
            "note": "补充第二段证据",
        },
    )
    assert feedback.status_code == 201
    assert feedback.json()["category"] == "omission"

    result = client.get(f"/api/v1/contents/{content_id}/result").json()
    assert len(result["versions"]) == 3
    assert result["feedback"][0]["note"] == "补充第二段证据"
