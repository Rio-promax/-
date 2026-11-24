import json
import os
from pathlib import Path
import shutil
from datetime import UTC, datetime
from zipfile import ZipFile

from app.archive.schema import build_record
from app.archive.writer import ArchiveBundle, write_archive
from app.api.main import create_app
from app.domain.jobs import JobState
from app.meta import API_CONTRACT_VERSION
from fastapi.testclient import TestClient


def make_client(tmp_path: Path) -> tuple[TestClient, Path]:
    archive_root = tmp_path / "knowledge-root"
    return TestClient(create_app("sqlite:///:memory:", archive_root)), archive_root


def create_job(client: TestClient, title: str = "含有用户内容的标题") -> tuple[str, str]:
    content = client.post(
        "/api/v1/contents",
        json={
            "kind": "video",
            "title": title,
            "platform": "local",
            "canonical_url": "file:///C:/Users/demo/private-video.mp4",
        },
    )
    assert content.status_code == 201
    content_id = content.json()["id"]
    run = client.post(
        f"/api/v1/contents/{content_id}/analysis-runs",
        json={"model": "test-model"},
    )
    assert run.status_code == 201
    return content_id, run.json()["job"]["id"]


def test_retention_cleanup_is_dry_run_and_recoverable(tmp_path: Path) -> None:
    client, archive_root = make_client(tmp_path)
    old_file = archive_root / "cache" / "old-audio.wav"
    old_file.parent.mkdir(parents=True)
    old_file.write_bytes(b"temporary audio")
    old_timestamp = old_file.stat().st_mtime - 10 * 24 * 60 * 60
    os.utime(old_file, (old_timestamp, old_timestamp))

    preview = client.post(
        "/api/v1/data-governance/cleanup",
        json={"execute": False},
    )
    assert preview.status_code == 200
    assert preview.json()["candidate_count"] == 1
    assert old_file.exists()

    cleanup = client.post(
        "/api/v1/data-governance/cleanup",
        json={"execute": True},
    )
    assert cleanup.status_code == 200
    assert cleanup.json()["moved"]
    assert not old_file.exists()
    assert (archive_root / ".trash" / "data-cleanup").is_dir()


def test_backup_redacts_secrets_and_restores_library(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.db import store as store_module

    monkeypatch.setattr(
        store_module,
        "protect_secret",
        lambda value, *, purpose: "dpapi:governance-sealed",
    )
    monkeypatch.setattr(
        store_module,
        "unprotect_secret",
        lambda value, *, purpose: "do-not-export-this",
    )
    client, archive_root = make_client(tmp_path)
    content_id, _job_id = create_job(client, "可备份内容")
    client.app.state.store.set_setting("archive_root", str(archive_root))
    client.app.state.store.set_setting("summary_template", "general")
    client.app.state.store.set_secret_setting(
        "summary_api_key", "do-not-export-this", purpose="summary API Key"
    )

    store = client.app.state.store
    content = store.get_content(content_id)
    transcript = {
        "language": "zh",
        "source_kind": "bilibili_subtitle",
        "engine": "bilibili",
        "position_kind": "timestamp",
        "segments": [
            {
                "start_seconds": 5.0,
                "end_seconds": 6.0,
                "text": "备份恢复后索引覆盖核对短语",
            }
        ],
    }
    archive_paths = write_archive(
        archive_root,
        ArchiveBundle(
            record=build_record(
                content,
                model="test-model",
                prompt_version="summary-v1",
                transcript_source="bilibili_subtitle",
                analyzed_at=datetime.now(UTC),
            ),
            summary_markdown="恢复测试摘要",
            transcript=transcript,
        ),
    )
    job = store.get_job(_job_id)
    job.state = JobState.COMPLETED
    job.completed_at = datetime.now(UTC)
    job.metadata["archive_path"] = str(archive_paths.directory)
    store.save_job(job)
    store.upsert_summary(content_id, "恢复测试摘要")

    backup = client.post("/api/v1/data-governance/backup")
    assert backup.status_code == 201
    backup_path = Path(backup.json()["path"])
    assert backup_path.is_file()
    with ZipFile(backup_path) as archive:
        snapshot = json.loads(archive.read("snapshot.json"))
    assert content_id in {row["id"] for row in snapshot["tables"]["content_items"]}
    assert "do-not-export-this" not in json.dumps(snapshot, ensure_ascii=False)
    assert "summary_api_key" in snapshot["redacted_settings"]
    assert "ask_index_contents" not in snapshot["tables"]

    restored_archive_root = tmp_path / "restored-knowledge-root"
    restored_backup = restored_archive_root / "backups" / backup_path.name
    restored_backup.parent.mkdir(parents=True)
    shutil.copy2(backup_path, restored_backup)
    restore_client = TestClient(create_app("sqlite:///:memory:", restored_archive_root))
    restored = restore_client.post(
        "/api/v1/data-governance/restore",
        json={"path": str(restored_backup)},
    )
    assert restored.status_code == 200
    restored_payload = restored.json()
    assert restored_payload["restored_content_count"] >= 1
    assert restored_payload["ask_index_backfill"]["indexed"] == 1
    assert restored_payload["ask_index_coverage"] == {
        "total_completed": 1,
        "indexed": 1,
        "partial": 0,
        "failed": 0,
        "pending": 0,
    }
    assert len(restore_client.app.state.ask_index.search("备份恢复后索引覆盖核对短语")) == 1


def test_diagnostics_and_task_feedback_are_sanitized(tmp_path: Path) -> None:
    client, _archive_root = make_client(tmp_path)
    content_id, job_id = create_job(client)
    job = client.app.state.store.get_job(job_id)
    from app.domain.jobs import JobErrorCode, JobState

    job.state = JobState.FAILED
    job.error_code = JobErrorCode.SUMMARY_GENERATION_FAILED
    job.error_message = "secret title / C:/Users/demo/private.mp4?api_key=leak"
    job.checkpoint = "summarizing"
    client.app.state.store.save_job(job)

    diagnostics = client.get(f"/api/v1/jobs/{job_id}/diagnostics")
    assert diagnostics.status_code == 200
    diagnostic = diagnostics.json()
    assert diagnostic["error_category"] == "summary"
    assert diagnostic["error_stage"] == "summary"
    assert diagnostic["recovery_suggestion"]
    assert "含有用户内容的标题" not in json.dumps(diagnostic, ensure_ascii=False)
    assert "private.mp4" not in json.dumps(diagnostic, ensure_ascii=False)
    assert "api_key" not in json.dumps(diagnostic, ensure_ascii=False).lower()

    feedback = client.post(
        f"/api/v1/jobs/{job_id}/feedback",
        json={"category": "bug", "note": "失败了"},
    )
    assert feedback.status_code == 201
    assert feedback.json()["content_id"] == content_id
    assert "含有用户内容的标题" not in json.dumps(feedback.json(), ensure_ascii=False)
    assert "private.mp4" not in json.dumps(feedback.json(), ensure_ascii=False)


def test_meta_contract_exposes_version_and_known_issues(tmp_path: Path) -> None:
    client, _archive_root = make_client(tmp_path)

    health = client.get("/health")
    response = client.get("/api/v1/meta")

    assert health.status_code == 200
    assert response.status_code == 200
    health_payload = health.json()
    meta_payload = response.json()
    assert meta_payload["version"] == "0.2.0"
    assert meta_payload["changelog"]
    assert meta_payload["known_issues"]
    assert health_payload["api_contract_version"] == meta_payload["api_contract_version"]
    assert health_payload["api_contract_version"] == API_CONTRACT_VERSION
