from types import SimpleNamespace
from pathlib import Path

import pytest
from app.api.main import create_app
from fastapi.testclient import TestClient


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


def test_removed_title_is_ignored_and_import_summary_strength_is_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_summary(monkeypatch)
    client = TestClient(create_app("sqlite:///:memory:", tmp_path / "knowledge-root"))

    page = client.get("/")
    from app.api.schemas import LinkImportRequest, LinksImportRequest, LocalImportRequest

    assert "title" not in LocalImportRequest.model_fields
    assert "title" not in LinkImportRequest.model_fields
    assert "title" not in LinksImportRequest.model_fields
    assert 'id="title"' not in page.text
    assert 'id="summary-strength"' in page.text
    assert "总结强度" in page.text

    response = client.post(
        "/api/v1/imports/local",
        json={
            "text": "旧接口仍然可以提交的正文。",
            "title": "旧标题应被忽略",
            "strength": "deep",
        },
    )

    assert response.status_code == 201
    assert response.json()["content"]["title"] == "未命名文本"
    assert response.json()["run"]["settings_snapshot"]["strength"] == "deep"


def test_content_library_title_remains_real_metadata(tmp_path: Path) -> None:
    client = TestClient(create_app("sqlite:///:memory:", tmp_path / "knowledge-root"))

    response = client.post(
        "/api/v1/contents",
        json={"kind": "article", "title": "内容库真实标题", "platform": "web"},
    )

    assert response.status_code == 201
    assert response.json()["title"] == "内容库真实标题"
