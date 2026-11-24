"""Regression tests for cloud ASR settings and model discovery."""

import json
from pathlib import Path
from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient

from app.adapters.asr import openai_compatible
from app.adapters.asr.openai_compatible import filter_asr_models
from app.api import main as api_main
from app.api.main import create_app


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def test_copy_summary_key_writes_both_asr_secrets_without_changing_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db import store as store_module

    monkeypatch.setattr(
        store_module,
        "unprotect_secret",
        lambda value, *, purpose: "summary-secret",
    )
    monkeypatch.setattr(
        store_module,
        "protect_secret",
        lambda value, *, purpose: "dpapi:asr-sealed",
    )
    client = TestClient(create_app("sqlite:///:memory:"))
    store = client.app.state.store
    store.set_setting("summary_provider", "qwen")
    store.set_setting("summary_api_url", "https://summary.example.test/v1")
    store.set_setting("summary_model", "qwen-plus")
    store.set_setting("summary_prompt", "原总结 Prompt")
    store.set_setting("summary_api_key", "summary-secret")

    response = client.put(
        "/api/v1/settings",
        json={
            "asr_engine": "cloud",
            "asr_api_url": "https://asr.example.test/v1/audio/transcriptions",
            "asr_model": "whisper-large-v3",
            "copy_summary_key": True,
        },
    )

    assert response.status_code == 200
    assert "summary-secret" not in response.text
    assert store.get_setting("summary_api_key") == "summary-secret"
    assert store._get_setting_raw("asr_cloud_api_key") == "dpapi:asr-sealed"
    assert store._get_setting_raw("asr_api_key") == "dpapi:asr-sealed"
    assert "summary-secret" not in (store._get_setting_raw("asr_cloud_api_key") or "")
    assert store.get_secret_setting("asr_cloud_api_key", purpose="云端 ASR API Key") == (
        "summary-secret"
    )
    assert store.get_secret_setting("asr_api_key", purpose="云端 ASR API Key") == (
        "summary-secret"
    )
    assert store.get_setting("summary_provider") == "qwen"
    assert store.get_setting("summary_api_url") == "https://summary.example.test/v1"
    assert store.get_setting("summary_model") == "qwen-plus"
    assert store.get_setting("summary_prompt") == "原总结 Prompt"


def test_copy_summary_key_requires_a_saved_summary_key() -> None:
    client = TestClient(create_app("sqlite:///:memory:"))

    response = client.put(
        "/api/v1/settings",
        json={
            "asr_engine": "cloud",
            "asr_api_url": "https://asr.example.test/v1",
            "asr_model": "whisper-large-v3",
            "copy_summary_key": True,
        },
    )

    assert response.status_code == 422
    assert "总结 API Key" in response.json()["detail"]
    assert client.app.state.store.get_setting("asr_cloud_api_key") is None
    assert client.app.state.store.get_setting("asr_api_key") is None


def test_asr_partial_update_does_not_touch_summary_settings(
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
        lambda value, *, purpose: "asr-secret",
    )
    client = TestClient(create_app("sqlite:///:memory:"))
    store = client.app.state.store
    for key, value in {
        "summary_provider": "qwen",
        "summary_api_url": "https://summary.example.test/v1",
        "summary_model": "qwen-plus",
        "summary_prompt": "原总结 Prompt",
        "summary_api_key": "summary-secret",
    }.items():
        store.set_setting(key, value)

    response = client.put(
        "/api/v1/settings",
        json={
            "asr_api_url": "https://asr.example.test/v1",
            "asr_api_key": "asr-secret",
            "asr_model": "whisper-large-v3",
        },
    )

    assert response.status_code == 200
    assert store._get_setting_raw("asr_cloud_api_key") == "dpapi:asr-sealed"
    assert store._get_setting_raw("asr_api_key") == "dpapi:asr-sealed"
    assert "asr-secret" not in (store._get_setting_raw("asr_cloud_api_key") or "")
    assert store.get_secret_setting("asr_cloud_api_key", purpose="云端 ASR API Key") == (
        "asr-secret"
    )
    assert store.get_setting("summary_provider") == "qwen"
    assert store.get_setting("summary_api_url") == "https://summary.example.test/v1"
    assert store.get_setting("summary_model") == "qwen-plus"
    assert store.get_setting("summary_prompt") == "原总结 Prompt"
    assert store.get_setting("summary_api_key") == "summary-secret"


def test_filter_asr_models_uses_ids_and_nested_capability_markers() -> None:
    entries = [
        {"id": "whisper-large-v3"},
        {"id": "custom-speech", "tasks": ["speech_to_text"]},
        {"id": "custom-asr", "capabilities": {"audio": {"transcription": True}}},
        {"id": "custom-asr", "capabilities": {"asr": True}},
        {"id": "text-embedding-v4", "owned_by": "qwen"},
        {"id": "tts-1", "task": "text-to-speech"},
        {"id": "whisper-tts", "task": "text-to-speech"},
    ]

    assert filter_asr_models(entries) == (
        "whisper-large-v3",
        "custom-speech",
        "custom-asr",
    )


def test_asr_model_discovery_filters_and_derives_models_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request, *, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.headers["Authorization"]
        captured["timeout"] = timeout
        return _FakeResponse(
            {
                "data": [
                    {"id": "whisper-large-v3"},
                    {"id": "gpt-4o-mini"},
                    {"id": "custom-asr", "task": "automatic-speech-recognition"},
                    {"id": "custom-asr", "task": "automatic-speech-recognition"},
                ]
            }
        )

    monkeypatch.setattr(openai_compatible, "urlopen", fake_urlopen)
    client = TestClient(create_app("sqlite:///:memory:"))
    response = client.post(
        "/api/v1/settings/asr/models",
        json={
            "provider": "custom",
            "asr_api_url": "https://asr.example.test/v1/audio/transcriptions",
            "asr_api_key": "asr-secret",
        },
    )

    assert response.status_code == 200
    assert response.json()["models"] == ["whisper-large-v3", "custom-asr"]
    assert response.json()["models_supported"] is True
    assert captured == {
        "url": "https://asr.example.test/v1/models",
        "authorization": "Bearer asr-secret",
        "timeout": 120,
    }


def test_asr_model_discovery_reports_manual_fallback_when_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request, *, timeout):
        raise HTTPError(request.full_url, 404, "not found", {}, None)

    monkeypatch.setattr(openai_compatible, "urlopen", fake_urlopen)
    client = TestClient(create_app("sqlite:///:memory:"))

    response = client.post(
        "/api/v1/settings/asr/models",
        json={
            "asr_api_url": "https://asr.example.test/v1",
            "asr_api_key": "asr-secret",
        },
    )

    assert response.status_code == 200
    assert response.json()["models"] == []
    assert response.json()["models_supported"] is False
    assert "手动填写 ASR 模型 ID" in response.json()["message"]


def test_asr_connection_test_requires_model_from_discovery_and_never_saves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request, *, timeout):
        return _FakeResponse({"data": [{"id": "whisper-large-v3"}]})

    monkeypatch.setattr(openai_compatible, "urlopen", fake_urlopen)
    client = TestClient(create_app("sqlite:///:memory:"))

    valid = client.post(
        "/api/v1/settings/asr/test",
        json={
            "provider": "custom",
            "asr_api_url": "https://asr.example.test/v1",
            "asr_api_key": "asr-secret",
            "asr_model": "whisper-large-v3",
        },
    )
    invalid = client.post(
        "/api/v1/settings/asr/test",
        json={
            "asr_api_url": "https://asr.example.test/v1",
            "asr_api_key": "asr-secret",
            "asr_model": "gpt-4o-mini",
        },
    )

    assert valid.status_code == 200
    assert invalid.status_code == 422
    assert "不在服务商返回的模型列表" in invalid.json()["detail"]
    assert client.app.state.store.get_setting("asr_api_key") is None


def test_asr_model_root_is_product_local_path_independent_of_cwd(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    client = TestClient(create_app("sqlite:///:memory:"))

    expected = (Path(api_main.__file__).resolve().parents[5] / "local" / "asr-models").resolve()
    assert client.app.state.asr_model_root == expected
