"""11-23：重新总结改为同一内容生成下一版本；继续导入仍新建副本。"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import main
from app.api.main import create_app
from app.domain.models import SourcePlatform

JS = (
    Path(__file__).resolve().parents[1] / "app" / "ui" / "app.js"
).read_text(encoding="utf-8")


def _between(script: str, start: str, end: str) -> str:
    return script.split(start, 1)[1].split(end, 1)[0]


def install_fake_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.workflows import analyze

    class FakeSummarizer:
        def __init__(self, _settings) -> None:
            pass

        def summarize_chunks(self, chunks, *, title, strength, prompt, skill=None, text_material=False):
            text = "\n".join(chunk.text for chunk in chunks)
            return SimpleNamespace(markdown=f"# 内容总结\n\n{text}\n", overview=text)

    monkeypatch.setattr(analyze, "OpenAICompatibleSummarizer", FakeSummarizer)


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(
        f"sqlite:///:memory:", tmp_path / "knowledge-root"
    ))


def test_r1_reuse_content_keeps_id_and_adds_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_summary(monkeypatch)
    client = _client(tmp_path)
    first = client.post(
        "/api/v1/imports/local",
        json={"title": "收藏了就不看", "text": "第一段原始转写。\n\n第二段原始转写。", "max_chunk_tokens": 32},
    )
    assert first.status_code == 201
    first_id = first.json()["content"]["id"]

    response = client.post(
        f"/api/v1/contents/{first_id}/resummarize",
        json={"reuse_content": True, "summary_style": "general"},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["content"]["id"] == first_id, "R1：重新总结复用原内容"
    assert "（1）" not in payload["content"]["title"], "R1：不加副本后缀"

    versions = client.get(f"/api/v1/contents/{first_id}/summary-versions").json()
    assert len(versions) == 2, "R1：原内容生成 V2"
    assert sorted(item["version_number"] for item in versions) == [1, 2]
    history = client.get("/api/v1/history").json()
    assert len(history) == 1, "R1：左栏不出现第二条内容"


def test_r1_reuse_content_keeps_bilibili_collection_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.adapters.sources.prepared import PreparedSource
    from app.domain.models import AnalysisSettings, ContentKind, Transcript, TranscriptSegment

    install_fake_summary(monkeypatch)
    source_url = "https://www.bilibili.com/video/BV1vF4F64EsW/?p=1"

    def fake_prepare(*, url, title, language, bilibili_cookie, asr_configured, page_number=None):
        return [PreparedSource(
            kind=ContentKind.VIDEO,
            title="收藏了就不看",
            transcript=Transcript(
                "zh-CN", "test", "test", (TranscriptSegment(0, 2, "B 站原始转写。"),)
            ),
            content_hash="bili-hash",
            source_path=None,
            source_url=source_url,
            acquisition_method="test",
            platform=SourcePlatform.BILIBILI,
        )]

    monkeypatch.setattr(main, "_prepare_link_sources", fake_prepare)
    monkeypatch.setattr(main, "_preflight_link_connection", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "_bilibili_cookie", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "_asr_is_configured", lambda *args, **kwargs: True)
    monkeypatch.setattr(main, "_summary_settings_snapshot", lambda *args, **kwargs: {
        "summary_config": {"model": "test-model"},
        "summary_provider": "openai-compatible",
        "prompt_version": "test-prompt",
        "summary_prompt": "test prompt",
        "summary_prompt_hash": "test-hash",
        "summary_skill": None,
    })

    client = _client(tmp_path)
    client.app.state.job_queue.submit = lambda *args, **kwargs: None
    store = client.app.state.store
    existing = store.create_content(
        kind=ContentKind.VIDEO,
        title="收藏了就不看",
        platform=SourcePlatform.BILIBILI,
        canonical_url=source_url,
        content_hash="bili-hash",
    )
    _, existing_job = store.create_analysis_run(existing.id, AnalysisSettings("test-model"))
    existing_job.metadata["source_url"] = source_url
    store.save_job(existing_job)

    response = client.post(
        f"/api/v1/contents/{existing.id}/resummarize", json={"reuse_content": True}
    )
    assert response.status_code == 201
    assert response.json()["content"]["id"] == existing.id
    assert response.json()["job"]["collection_id"] == "parts:BV1vF4F64EsW"


def test_r2_restyle_sends_reuse_flag() -> None:
    seg = JS.split("async function submitRestyle()", 1)[1].split("/* R13", 1)[0]
    assert "reuse_content: true" in seg, "R2：详情重新总结声明复用"


def test_r3_duplicate_does_not_send_reuse_flag() -> None:
    helper = _between(JS, "async function resummarizeDuplicate(matchedContentId)", "async function jobAction")
    assert "/resummarize" in helper
    assert "reuse_content" not in helper, "R3：继续导入仍走新建副本"
