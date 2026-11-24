"""11-23：设置页总结 Prompt 编辑框 + 本次「补充要求」extra_instruction 全链路。"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.main import create_app
from app.api.schemas import (
    LinkImportRequest,
    LinkQueryConfirmRequest,
    LocalImportRequest,
    ResummarizeRequest,
)

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "app" / "ui" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "app" / "ui" / "index.html").read_text(encoding="utf-8")


def _between(script: str, start: str, end: str) -> str:
    return script.split(start, 1)[1].split(end, 1)[0]


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app("sqlite:///:memory:", tmp_path / "knowledge-root"))


def _install_capturing_summary(monkeypatch: pytest.MonkeyPatch, captured: list[str]) -> None:
    from app.workflows import analyze

    class CapturingSummarizer:
        def __init__(self, _settings) -> None:
            pass

        def summarize_chunks(self, chunks, *, title, strength, prompt, **kwargs) -> SimpleNamespace:
            captured.append(prompt)
            text = "\n".join(chunk.text for chunk in chunks)
            return SimpleNamespace(markdown=f"# 内容总结\n\n{text}\n", overview=text)

    monkeypatch.setattr(analyze, "OpenAICompatibleSummarizer", CapturingSummarizer)


def test_r1_settings_prompt_editor_in_model_pane() -> None:
    pane = _between(JS, "function modelPane()", "function storagePane()")
    assert 'data-setting-key="summary_prompt"' in pane, "R1：模型分区有总结 Prompt 编辑框"
    assert "<textarea" in pane, "R1：用多行文本框承载 prompt"

    save = _between(JS, 'case "settings-save":', 'case "settings-test"') if 'case "settings-test"' in JS else JS.split('case "settings-save":', 1)[1]
    assert "body.summary_prompt = summaryPrompt" in save, "R1：保存时带上 prompt"
    summary_changed = save.split("const summaryChanged =", 1)[1].split("if (summaryChanged)", 1)[0]
    assert "summaryPrompt" not in summary_changed, "R1：prompt 改动不触发 token 校验"


def test_r2_intake_extra_instruction_input() -> None:
    assert 'id="intake-extra-instruction"' in HTML, "R2：导入页有补充要求输入框"
    cfg = _between(JS, "function summaryConfig()", "async function intakeSubmit()")
    assert 'extra_instruction: $("#intake-extra-instruction").value' in cfg, "R2：导入提交带字段"


def test_r3_restyle_extra_instruction_input() -> None:
    assert 'id="restyle-extra-instruction"' in HTML, "R3：重新总结弹窗有补充要求输入框"
    open_seg = _between(JS, "function openRestyle()", "function closeRestyle()")
    assert '$("#restyle-extra-instruction").value = ""' in open_seg, "R3：打开弹窗时清空，避免串值"
    submit_seg = _between(JS, "async function submitRestyle()", "function ")
    assert 'extra_instruction: $("#restyle-extra-instruction").value' in submit_seg, "R3：重新总结提交带字段"


def test_r4_four_request_models_have_extra_instruction() -> None:
    for model in (LocalImportRequest, LinkImportRequest, LinkQueryConfirmRequest, ResummarizeRequest):
        field = model.model_fields.get("extra_instruction")
        assert field is not None, f"R4：{model.__name__} 有 extra_instruction"
        assert field.default is None, f"R4：{model.__name__} 默认不传"
        limits = [getattr(m, "max_length", None) for m in field.metadata]
        assert 2000 in limits, f"R4：{model.__name__} 限长 2000"


def test_r4_extra_instruction_max_length() -> None:
    with pytest.raises(ValidationError):
        LocalImportRequest(text="x", extra_instruction="a" * 2001)


def test_r5_snapshot_carries_extra_instruction(tmp_path: Path) -> None:
    from app.api.main import _analysis_settings_from_store
    from app.db.store import SQLiteStore

    store = SQLiteStore("sqlite:///:memory:")
    settings = _analysis_settings_from_store(
        store,
        tmp_path / "skills",
        model=None,
        language=None,
        asr_engine="cloud",
        max_chunk_tokens=800,
        extra_instruction="  只讲方法论  ",
    )
    snapshot = settings.as_dict()
    assert snapshot["extra_instruction"] == "只讲方法论", "R5：快照携带本次补充要求（已 strip）"
    assert snapshot["summary_prompt_hash"], "R5：全局 prompt hash 口径不变"
    assert "只讲方法论" not in snapshot["summary_prompt"], "R5：不并入全局 prompt"


def test_r6_extra_instruction_appended_to_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []
    _install_capturing_summary(monkeypatch, captured)
    client = _client(tmp_path)
    response = client.post(
        "/api/v1/imports/local",
        json={
            "title": "补充要求生效",
            "text": "原始转写内容一段。",
            "max_chunk_tokens": 32,
            "extra_instruction": "只讲方法论，不要复述原文",
        },
    )
    assert response.status_code == 201
    assert captured, "R6：总结模型被调用"
    assert any("本次补充要求：" in p and "只讲方法论，不要复述原文" in p for p in captured), \
        "R6：补充要求出现在发给模型的 prompt"


def test_r6_blank_extra_instruction_does_not_change_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []
    _install_capturing_summary(monkeypatch, captured)
    client = _client(tmp_path)
    response = client.post(
        "/api/v1/imports/local",
        json={"title": "留空", "text": "原始转写内容一段。", "max_chunk_tokens": 32},
    )
    assert response.status_code == 201
    assert captured and all("本次补充要求" not in p for p in captured), \
        "R6：留空时不追加"


def test_r7_backend_wires_four_call_sites() -> None:
    main_src = (ROOT / "app" / "api" / "main.py").read_text(encoding="utf-8")
    assert main_src.count("extra_instruction=request.extra_instruction,") == 4, \
        "R7：四类导入/重总结调用点都传字段"
    analyze_src = (ROOT / "app" / "workflows" / "analyze.py").read_text(encoding="utf-8")
    assert 'snapshot.get("extra_instruction")' in analyze_src, "R7：生成时读取快照字段"
