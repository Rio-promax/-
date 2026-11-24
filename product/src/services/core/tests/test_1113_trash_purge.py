"""R3 / M7：回收站彻底删除的后端契约。"""
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.db.models import JobRow


def _create_content(client: TestClient, title: str) -> str:
    response = client.post(
        "/api/v1/contents",
        json={"kind": "video", "title": title, "platform": "local"},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_job(client: TestClient, content_id: str) -> str:
    response = client.post(
        f"/api/v1/contents/{content_id}/analysis-runs",
        json={"model": "test-model", "strength": "quick"},
    )
    assert response.status_code == 201
    return response.json()["job"]["id"]


def _set_archive_path(app, job_id: str, directory: Path) -> None:
    with app.state.store.session_factory.begin() as session:
        job = session.get(JobRow, job_id)
        metadata = dict(job.metadata_json or {})
        metadata["archive_path"] = str(directory)
        job.metadata_json = metadata


def test_purge_removes_only_its_own_archive_directory(tmp_path: Path) -> None:
    app = create_app("sqlite:///:memory:")
    app.state.archive_root = tmp_path
    client = TestClient(app)
    first = _create_content(client, "第一条")
    second = _create_content(client, "第二条")
    batch = tmp_path / "2026" / "local" / "batch_x"
    own = batch / f"01_first--{first}"
    sibling = batch / f"02_second--{second}"
    own.mkdir(parents=True)
    sibling.mkdir(parents=True)
    (own / "index.md").write_text("first", encoding="utf-8")
    (sibling / "index.md").write_text("second", encoding="utf-8")
    job_id = _create_job(client, first)
    _set_archive_path(app, job_id, own)
    assert client.delete(f"/api/v1/contents/{first}").status_code == 200

    response = client.delete(f"/api/v1/contents/{first}/purge")

    assert response.status_code == 200
    assert not own.exists()
    assert sibling.exists() and (sibling / "index.md").read_text(encoding="utf-8") == "second"
    assert batch.exists()
    assert client.get(f"/api/v1/contents/{first}").status_code == 404
    assert client.get(f"/api/v1/contents/{second}").status_code == 200
    trash_ids = [
        item.get("content", {}).get("id")
        for item in client.get("/api/v1/trash").json()
    ]
    assert first not in trash_ids


def test_purge_rejects_content_not_in_trash() -> None:
    client = TestClient(create_app("sqlite:///:memory:"))
    content_id = _create_content(client, "未删除")

    response = client.delete(f"/api/v1/contents/{content_id}/purge")

    assert response.status_code == 409
    assert client.get(f"/api/v1/contents/{content_id}").status_code == 200


def test_purge_rejects_archive_path_outside_root(tmp_path: Path) -> None:
    app = create_app("sqlite:///:memory:")
    app.state.archive_root = tmp_path / "root"
    (tmp_path / "root").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    client = TestClient(app)
    content_id = _create_content(client, "越界")
    job_id = _create_job(client, content_id)
    _set_archive_path(app, job_id, outside)
    assert client.delete(f"/api/v1/contents/{content_id}").status_code == 200

    response = client.delete(f"/api/v1/contents/{content_id}/purge")

    assert response.status_code == 409
    assert outside.exists()
    assert client.get(f"/api/v1/contents/{content_id}").status_code == 200


def test_purge_keeps_record_when_archive_delete_fails(tmp_path: Path, monkeypatch) -> None:
    from app.api import main as api_main

    app = create_app("sqlite:///:memory:")
    app.state.archive_root = tmp_path
    client = TestClient(app)
    content_id = _create_content(client, "删不掉")
    own = tmp_path / "2026" / "local" / f"01_locked--{content_id}"
    own.mkdir(parents=True)
    (own / "index.md").write_text("locked", encoding="utf-8")
    job_id = _create_job(client, content_id)
    _set_archive_path(app, job_id, own)
    assert client.delete(f"/api/v1/contents/{content_id}").status_code == 200

    def fail(_directory):
        raise OSError("archive directory is locked")

    monkeypatch.setattr(api_main.shutil, "rmtree", fail)

    response = client.delete(f"/api/v1/contents/{content_id}/purge")

    assert response.status_code == 409
    assert own.exists()
    assert client.get(f"/api/v1/contents/{content_id}").status_code == 200
    assert content_id in [
        item.get("content", {}).get("id")
        for item in client.get("/api/v1/trash").json()
    ]
