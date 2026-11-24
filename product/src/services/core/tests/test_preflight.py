import json
from pathlib import Path

from app.adapters.asr.local import write_model_manifest
from app.api.main import create_app
from app.workflows import preflight
from fastapi.testclient import TestClient


def _client(tmp_path: Path) -> TestClient:
    client = TestClient(create_app("sqlite:///:memory:", tmp_path / "archive"))
    client.app.state.asr_model_root = tmp_path / "models"
    client.app.state.workflow.asr_model_root = client.app.state.asr_model_root
    return client


def _write_model(root: Path) -> None:
    model = root / "small"
    model.mkdir(parents=True)
    (model / "config.json").write_text(json.dumps({"model_type": "whisper"}), encoding="utf-8")
    (model / "model.bin").write_bytes(b"model")
    (model / "tokenizer.json").write_text("{}", encoding="utf-8")
    (model / "vocabulary.txt").write_text("hello" + chr(10), encoding="utf-8")
    write_model_manifest(model, "small")


def test_environment_report_redacts_secrets_and_exposes_blocking_checks(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.app.state.store.set_setting("summary_api_key", "test-summary-secret")

    response = client.get("/api/v1/environment/check")

    assert response.status_code == 200
    payload = response.json()
    assert "test-summary-secret" not in response.text
    assert "summary_api_key" not in payload
    assert payload["secret_status"]["summary_api_key"] == "saved"
    assert "disk" in {item["code"] for item in payload["checks"]}


def test_settings_response_reports_secret_status_without_exposing_secret(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.app.state.store.set_setting("summary_api_key", "dpapi:not-a-usable-secret")

    response = client.get("/api/v1/settings")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary_api_key_configured"] is False
    assert "not-a-usable-secret" not in response.text


def test_task_preflight_blocks_missing_asr_and_returns_resource_estimate(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/v1/tasks/preflight",
        json={
            "kind": "video",
            "duration_seconds": 600,
            "has_transcript": False,
            "asr_engine": "cloud",
            "model": "gpt-test",
            "max_chunk_tokens": 800,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ready"] is False
    assert any(item["code"] == "asr_cloud_not_configured" for item in payload["checks"])
    assert payload["estimate"]["estimated_duration_seconds_max"] > 0
    assert payload["estimate"]["estimated_disk_bytes"] > 0
    assert "api_key" not in response.text.lower()


def test_task_preflight_blocks_incomplete_cloud_asr_configuration(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.app.state.store.set_setting("summary_api_key", "test-summary-secret")
    client.app.state.store.set_setting(
        "summary_api_url", "https://summary.example.test/v1/chat/completions"
    )
    client.app.state.store.set_setting("summary_model", "summary-test")
    client.app.state.store.set_setting("asr_engine", "cloud")
    client.app.state.store.set_setting("asr_cloud_api_key", "test-asr-secret")

    response = client.post(
        "/api/v1/tasks/preflight",
        json={
            "kind": "video",
            "duration_seconds": 120,
            "has_transcript": False,
            "asr_engine": "cloud",
            "model": "summary-test",
            "max_chunk_tokens": 800,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ready"] is False
    assert any(item["code"] == "asr_cloud_not_configured" for item in payload["checks"])


def test_task_preflight_accepts_ready_local_model_without_network_requirement(
    tmp_path: Path, monkeypatch
) -> None:
    client = _client(tmp_path)
    _write_model(tmp_path / "models")
    client.app.state.store.set_setting("summary_api_key", "test-summary-secret")
    client.app.state.store.set_setting(
        "summary_api_url", "https://summary.example.test/v1/chat/completions"
    )
    client.app.state.store.set_setting("summary_model", "summary-test")
    client.app.state.store.set_setting("asr_engine", "local")
    client.app.state.store.set_setting("asr_local_model", "small")
    monkeypatch.setattr(preflight, "local_asr_runtime_available", lambda: True)

    response = client.post(
        "/api/v1/tasks/preflight",
        json={
            "kind": "video",
            "duration_seconds": 120,
            "has_transcript": False,
            "asr_engine": "local",
            "local_model": "small",
            "model": "summary-test",
            "max_chunk_tokens": 800,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ready"] is True
    assert all(item["status"] in {"ok", "warning"} for item in payload["checks"])
    assert payload["estimate"]["memory_required_mb"] > 0


def test_task_preflight_rejects_invalid_parameters(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/v1/tasks/preflight",
        json={
            "kind": "article",
            "text_length": -1,
            "model": "",
            "max_chunk_tokens": 1,
        },
    )

    assert response.status_code == 422
