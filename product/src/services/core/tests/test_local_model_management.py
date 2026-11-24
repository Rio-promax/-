import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.adapters.asr import local as local_asr
from app.api import main as api_main
from app.api.main import create_app
from fastapi.testclient import TestClient


def _write_model(path: Path, payload: bytes = b"model") -> Path:
    path.mkdir(parents=True)
    (path / "config.json").write_text(json.dumps({"model_type": "whisper"}), encoding="utf-8")
    (path / "model.bin").write_bytes(payload)
    (path / "tokenizer.json").write_text("{}", encoding="utf-8")
    (path / "vocabulary.txt").write_text("hello" + chr(10), encoding="utf-8")
    return path


def _write_sensevoice_model(path: Path) -> Path:
    path.mkdir(parents=True)
    for name in (
        "model.pt",
        "config.yaml",
        "configuration.json",
        "chn_jpn_yue_eng_ko_spectok.bpe.model",
    ):
        (path / name).write_bytes(b"{}" if name == "configuration.json" else b"model")
    return path


def _client(tmp_path: Path) -> TestClient:
    client = TestClient(create_app("sqlite:///:memory:", tmp_path / "archive"))
    client.app.state.asr_model_root = tmp_path / "models"
    return client


def _model(payload: dict) -> dict:
    return next(item for item in payload["models"] if item["id"] == "small")


def test_sensevoice_runtime_environment_drops_unusable_path_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing-runtime-bin"
    usable = tmp_path / "usable-runtime-bin"
    usable.mkdir()
    monkeypatch.setenv("PATH", os.pathsep.join((str(missing), str(usable))))

    environment = local_asr._runtime_environment()

    assert str(usable) in environment["PATH"].split(os.pathsep)
    assert str(missing) not in environment["PATH"].split(os.pathsep)


def test_sensevoice_worker_memory_includes_recursive_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not hasattr(local_asr.ctypes, "windll"):
        pytest.skip("Windows Toolhelp32 memory probe")
    worker = local_asr.SenseVoiceWorker(Path("model"))
    worker._process = SimpleNamespace(pid=101)
    monkeypatch.setattr(local_asr, "_windows_process_tree", lambda _pid: (101, 202, 303))
    values = {101: 10.5, 202: 20.25, 303: 1.25}
    monkeypatch.setattr(local_asr, "_windows_working_set_mb", values.__getitem__)

    assert worker.memory_rss_mb() == 32.0


def test_local_model_manifest_detects_same_size_corruption(tmp_path: Path) -> None:
    model_path = tmp_path / "models" / "small"
    _write_model(model_path, b"good-model")
    local_asr.write_model_manifest(model_path, "small")
    model_file = model_path / "model.bin"
    previous_mtime_ns = model_file.stat().st_mtime_ns
    model_file.write_bytes(b"bad-model!")
    os.utime(
        model_file,
        ns=(model_file.stat().st_atime_ns, previous_mtime_ns + 1_000_000_000),
    )

    validation = local_asr.validate_local_model(tmp_path / "models", "small")

    assert validation.ready is False
    assert validation.status == "corrupt"
    assert "model.bin" in validation.invalid_files


def test_import_discovers_model_and_keeps_manifest(tmp_path: Path) -> None:
    source = tmp_path / "external" / "my-whisper"
    _write_model(source)
    client = _client(tmp_path)

    response = client.post(
        "/api/v1/asr/local-models/import",
        json={"path": str(source), "model_id": "imported-whisper"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == "imported-whisper"
    assert body["installed"] is True
    assert body["validation_status"] == "ready"
    imported = tmp_path / "models" / "imported-whisper"
    assert (imported / "model.manifest.json").is_file()
    listed = client.get("/api/v1/asr/local-models").json()
    assert any(item["id"] == "imported-whisper" for item in listed["models"])

    discovered = client.post(
        "/api/v1/asr/local-models/discover",
        json={"path": str(source), "model_id": "external-whisper"},
    )
    assert discovered.status_code == 200
    assert discovered.json()["installed"] is True
    assert discovered.json()["size_bytes"] > 0


def _write_huggingface_cache_model(
    cache_root: Path, repo_name: str, payload: bytes = b"model"
) -> Path:
    snapshot = (
        cache_root / "hub" / f"models--Systran--faster-whisper-{repo_name}" / "snapshots" / "revision"
    )
    _write_model(snapshot, payload)
    return snapshot


def test_discover_accepts_huggingface_cache_root(tmp_path: Path) -> None:
    cache_root = tmp_path / ".hf"
    snapshot = _write_huggingface_cache_model(cache_root, "small")
    client = _client(tmp_path)

    discovered = client.post(
        "/api/v1/asr/local-models/discover",
        json={"path": str(cache_root), "model_id": "small"},
    )

    assert discovered.status_code == 200
    body = discovered.json()
    assert body["id"] == "small"
    assert body["installed"] is True
    assert body["validation_status"] == "ready"
    assert Path(body["path"]) == snapshot

    imported = client.post(
        "/api/v1/asr/local-models/import",
        json={"path": str(cache_root), "model_id": "small"},
    )
    assert imported.status_code == 201
    assert imported.json()["id"] == "small"
    assert (tmp_path / "models" / "small" / "model.manifest.json").is_file()


def test_discover_maps_single_huggingface_cache_model_without_name(tmp_path: Path) -> None:
    cache_root = tmp_path / ".hf"
    _write_huggingface_cache_model(cache_root, "base")

    source, model_id, validation = local_asr.inspect_local_asr_model(cache_root)

    assert source.name == "revision"
    assert model_id == "base"
    assert validation.ready is True


def test_discover_returns_selection_for_multiple_complete_models(tmp_path: Path) -> None:
    cache_root = tmp_path / ".hf"
    _write_huggingface_cache_model(cache_root, "small")
    _write_huggingface_cache_model(cache_root, "base")
    client = _client(tmp_path)

    discovered = client.post(
        "/api/v1/asr/local-models/discover",
        json={"path": str(cache_root)},
    )

    assert discovered.status_code == 200
    body = discovered.json()
    assert body["selection_required"] is True
    assert body["validation_status"] == "selection_required"
    assert {item["id"] for item in body["candidates"]} == {"small", "base"}
    assert all(item["validation_status"] == "ready" for item in body["candidates"])


def test_incomplete_huggingface_main_snapshot_falls_back_to_complete_snapshot(
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / ".hf"
    repo_cache = cache_root / "hub" / "models--Systran--faster-whisper-medium"
    incomplete = repo_cache / "snapshots" / "incomplete"
    incomplete.mkdir(parents=True)
    (incomplete / "config.json").write_text("{}", encoding="utf-8")
    (incomplete / "model.bin").write_bytes(b"incomplete")
    complete = _write_model(repo_cache / "snapshots" / "complete")
    refs = repo_cache / "refs"
    refs.mkdir(parents=True)
    (refs / "main").write_text("incomplete", encoding="utf-8")

    source, model_id, validation = local_asr.inspect_local_asr_model(
        cache_root,
        model_id="medium",
    )

    assert source == complete
    assert model_id == "medium"
    assert validation.ready is True


def test_discover_reports_complete_model_requirements(tmp_path: Path) -> None:
    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()
    (incomplete / "config.json").write_text("{}", encoding="utf-8")
    (incomplete / "model.bin").write_bytes(b"incomplete")
    client = _client(tmp_path)

    response = client.post(
        "/api/v1/asr/local-models/discover",
        json={"path": str(incomplete)},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "tokenizer.json" in detail
    assert "vocabulary.txt" in detail
    assert "不会扫描整块磁盘" in detail


def test_download_failure_is_not_reported_as_downloaded(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path)
    monkeypatch.setattr(api_main, "local_asr_download_available", lambda: True)

    def fail_download(*_args, **_kwargs):
        raise local_asr.LocalAsrError("network unavailable")

    monkeypatch.setattr(api_main, "download_local_asr_model", fail_download)
    response = client.post("/api/v1/asr/local-models/small/download")
    assert response.status_code == 202

    item = _model(client.get("/api/v1/asr/local-models").json())
    for _ in range(20):
        if item["status"] == "error":
            break
        time.sleep(0.02)
        item = _model(client.get("/api/v1/asr/local-models").json())

    assert item["status"] == "error"
    assert item["installed"] is False
    assert item["validation_status"] != "ready"
    assert "network unavailable" in item["error"]


def test_download_completion_requires_post_download_validation(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path)
    monkeypatch.setattr(api_main, "local_asr_download_available", lambda: True)
    monkeypatch.setattr(
        api_main,
        "download_local_asr_model",
        lambda model_root, _model_id, **_kwargs: model_root / "small",
    )

    response = client.post("/api/v1/asr/local-models/small/download")
    assert response.status_code == 202
    item = _model(client.get("/api/v1/asr/local-models").json())
    for _ in range(20):
        if item["status"] == "error":
            break
        time.sleep(0.02)
        item = _model(client.get("/api/v1/asr/local-models").json())

    assert item["status"] == "error"
    assert item["installed"] is False
    assert "校验" in item["error"]


def test_model_file_ready_is_separate_from_runtime_availability(
    tmp_path: Path, monkeypatch
) -> None:
    model_path = tmp_path / "models" / "small"
    _write_model(model_path)
    local_asr.write_model_manifest(model_path, "small")
    client = _client(tmp_path)
    monkeypatch.setattr(api_main, "local_asr_runtime_available", lambda: False)

    item = _model(client.get("/api/v1/asr/local-models").json())

    assert item["installed"] is True
    assert item["model_ready"] is True
    assert item["usable"] is False
    assert item["compatibility_status"] == "runtime_unavailable"


def test_import_reuses_existing_complete_model(tmp_path: Path) -> None:
    source = tmp_path / "external" / "small"
    _write_model(source)
    client = _client(tmp_path)

    first = client.post(
        "/api/v1/asr/local-models/import",
        json={"path": str(source), "model_id": "small"},
    )
    second = client.post(
        "/api/v1/asr/local-models/import",
        json={"path": str(source), "model_id": "small"},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["status"] == "reused"
    assert second.json()["model_ready"] is True


def test_runtime_install_endpoint_tracks_completion(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path)
    available = {"value": False}
    monkeypatch.setattr(api_main, "local_asr_runtime_available", lambda: available["value"])

    def fake_run(*_args, **_kwargs):
        available["value"] = True
        return api_main.subprocess.CompletedProcess([], 0, stdout="installed", stderr="")

    monkeypatch.setattr(api_main.subprocess, "run", fake_run)
    response = client.post("/api/v1/asr/local-runtime/install")

    assert response.status_code == 202
    for _ in range(20):
        payload = client.get("/api/v1/asr/local-models").json()
        if payload["runtime_status"] == "ready":
            break
        time.sleep(0.02)
    assert payload["runtime_available"] is True
    assert payload["runtime_installing"] is False
    assert "pip" in payload["runtime_install_command"]

def test_model_removal_moves_to_recoverable_trash(tmp_path: Path) -> None:
    source = tmp_path / "external" / "small"
    _write_model(source)
    client = _client(tmp_path)
    imported = client.post(
        "/api/v1/asr/local-models/import",
        json={"path": str(source), "model_id": "small"},
    )
    assert imported.status_code == 201

    response = client.delete("/api/v1/asr/local-models/small")

    assert response.status_code == 200
    assert response.json()["status"] == "moved_to_trash"
    assert not (tmp_path / "models" / "small").exists()
    assert Path(response.json()["trash_path"]).is_dir()


def test_sensevoice_catalog_is_pinned_and_validates_its_files(tmp_path: Path) -> None:
    definition = local_asr.get_local_model_definition("sensevoice-small")
    assert definition is not None
    assert definition.repo_id == "iic/SenseVoiceSmall"
    assert definition.revision == "master"
    assert definition.license == "Apache License 2.0"
    model_path = _write_sensevoice_model(tmp_path / "models" / "sensevoice-small")
    local_asr.write_model_manifest(
        model_path,
        "sensevoice-small",
        source_revision=definition.revision,
    )
    validation = local_asr.validate_local_model(tmp_path / "models", "sensevoice-small")
    assert validation.ready
    assert validation.sha256
    assert local_asr.resolved_local_model_identity(model_path, "sensevoice-small") == validation.sha256


def test_sensevoice_fingerprint_uses_manifest_digest_not_master(tmp_path: Path) -> None:
    from app.workflows.analyze import asr_config_fingerprint

    model_path = _write_sensevoice_model(tmp_path / "models" / "sensevoice-small")
    local_asr.write_model_manifest(model_path, "sensevoice-small", source_revision="master")
    digest = local_asr.resolved_local_model_identity(model_path, "sensevoice-small")

    assert asr_config_fingerprint(
        model_id="sensevoice-small",
        language="zh",
        model_sha256=digest,
    ) != asr_config_fingerprint(
        model_id="sensevoice-small",
        language="zh",
        model_sha256="master",
    )


def test_sensevoice_transcriber_uses_isolated_runtime_and_strips_tags(
    tmp_path: Path, monkeypatch
) -> None:
    model_path = _write_sensevoice_model(tmp_path / "models" / "sensevoice-small")
    local_asr.write_model_manifest(model_path, "sensevoice-small")
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"audio")
    runtime = tmp_path / "python.exe"
    runtime.write_bytes(b"runtime")
    monkeypatch.setattr(local_asr, "_external_sensevoice_python", lambda: runtime)
    monkeypatch.setattr(local_asr, "_probe_audio_duration", lambda _path: 12.5)

    def fake_run(command, **kwargs):
        assert command[0] == str(runtime)
        assert command[-1] == "zh"
        assert kwargs["timeout"] == 180.0
        return SimpleNamespace(
            stdout='[{"text":"<|zh|><|NEUTRAL|><|Speech|> 你好 world"}]\n',
            stderr="",
        )

    monkeypatch.setattr(local_asr.subprocess, "run", fake_run)
    transcript = local_asr.SenseVoiceTranscriber(model_path).transcribe(audio, language="zh")

    assert transcript.engine == "funasr:sensevoice-small"
    assert transcript.segments[0].text == "你好 world"
    assert transcript.segments[0].end_seconds == 12.5
