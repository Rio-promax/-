"""Recoverable data retention and portable backup helpers."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile


RETENTION_DIRS: dict[str, tuple[str, ...]] = {
    "source": ("source", "sources", "video", "videos", "audio", "audios"),
    "subtitle": ("subtitle", "subtitles"),
    "cache": ("cache",),
}


def retention_report(
    archive_root: Path,
    *,
    source_days: int = 30,
    cache_days: int = 7,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(UTC)
    candidates: list[dict[str, Any]] = []
    by_kind: dict[str, int] = {kind: 0 for kind in RETENTION_DIRS}
    total_bytes = 0
    root = archive_root.resolve()
    for kind, directory_names in RETENTION_DIRS.items():
        cutoff = current - timedelta(days=cache_days if kind == "cache" else source_days)
        for directory_name in directory_names:
            directory = root / directory_name
            if not directory.is_dir():
                continue
            for path in directory.rglob("*"):
                if not path.is_file() or path.is_symlink():
                    continue
                modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
                if modified >= cutoff:
                    continue
                relative = path.relative_to(root)
                size = path.stat().st_size
                candidates.append(
                    {
                        "kind": kind,
                        "relative_path": relative.as_posix(),
                        "bytes": size,
                        "modified_at": modified.isoformat(),
                    }
                )
                by_kind[kind] += 1
                total_bytes += size
    return {
        "archive_root": str(root),
        "source_retention_days": source_days,
        "cache_retention_days": cache_days,
        "candidate_count": len(candidates),
        "candidate_bytes": total_bytes,
        "by_kind": by_kind,
        "candidates": candidates,
        "trash_root": str(root / ".trash" / "data-cleanup"),
    }


def cleanup_retention(
    archive_root: Path,
    *,
    source_days: int = 30,
    cache_days: int = 7,
    execute: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    report = retention_report(
        archive_root,
        source_days=source_days,
        cache_days=cache_days,
        now=now,
    )
    moved: list[str] = []
    if execute:
        stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
        trash_root = Path(report["trash_root"]) / stamp
        root = Path(report["archive_root"])
        for candidate in report["candidates"]:
            source = root / Path(candidate["relative_path"])
            if not source.is_file():
                continue
            target = trash_root / Path(candidate["relative_path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            moved.append(candidate["relative_path"])
        report["trash_root"] = str(trash_root)
    report["moved"] = moved
    return report


def create_backup(store, archive_root: Path, destination: Path | None = None) -> dict[str, Any]:
    root = archive_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    backup_path = destination or (
        root / "backups" / f"knowledge-backup-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.zip"
    )
    backup_path = backup_path.expanduser().resolve()
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = store.export_snapshot()
    snapshot["archive_root"] = str(root)
    file_count = 0
    with ZipFile(backup_path, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "snapshot.json",
            json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True),
        )
        for path in root.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(root)
            if relative.parts[0] in {".trash", ".checkpoints", "backups"}:
                continue
            archive.write(path, f"archive/{relative.as_posix()}")
            file_count += 1
    return {
        "path": str(backup_path),
        "file_count": file_count,
        "redacted_settings": snapshot["redacted_settings"],
    }


def _rewrite_portable_job_paths(snapshot: dict[str, Any], archive_root: Path) -> None:
    previous_root_value = snapshot.get("archive_root")
    if not isinstance(previous_root_value, str):
        return
    previous_root = Path(previous_root_value).expanduser().resolve()
    jobs = snapshot.get("tables", {}).get("jobs", [])
    if not isinstance(jobs, list):
        return
    for row in jobs:
        if not isinstance(row, dict):
            continue
        metadata = row.get("metadata_json")
        if not isinstance(metadata, dict):
            continue
        for key in ("archive_path", "checkpoint_dir"):
            value = metadata.get(key)
            if not isinstance(value, str):
                continue
            candidate = Path(value).expanduser().resolve()
            if previous_root not in candidate.parents:
                continue
            metadata[key] = str(archive_root / candidate.relative_to(previous_root))


def restore_backup(store, archive_root: Path, backup_path: Path) -> dict[str, Any]:
    root = archive_root.resolve()
    backup = backup_path.expanduser().resolve()
    if not backup.is_file():
        raise FileNotFoundError(str(backup))
    with ZipFile(backup) as archive:
        names = archive.namelist()
        for name in names:
            path = Path(name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("backup_path_invalid")
        try:
            snapshot = json.loads(archive.read("snapshot.json"))
        except (KeyError, json.JSONDecodeError) as error:
            raise ValueError("backup_snapshot_invalid") from error
        _rewrite_portable_job_paths(snapshot, root)
        restored = store.restore_snapshot(snapshot)
        archive_count = 0
        for name in names:
            if not name.startswith("archive/") or name.endswith("/"):
                continue
            relative = Path(name.removeprefix("archive/"))
            target = (root / relative).resolve()
            if root not in target.parents:
                raise ValueError("backup_path_invalid")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination)
            archive_count += 1
    return {
        "restored_content_count": int(restored.get("content_items", 0)),
        "restored_archive_files": archive_count,
        "skipped_secrets": list(snapshot.get("redacted_settings", [])),
    }
