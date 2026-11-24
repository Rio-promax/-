"""Atomic portable archive writer."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.archive.schema import render_markdown, safe_slug, validate_record


@dataclass(frozen=True, slots=True)
class ArchiveBundle:
    record: Mapping[str, Any]
    summary_markdown: str
    transcript: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ArchivePaths:
    directory: Path
    index: Path
    record: Path
    transcript: Path | None


# Windows 未开长路径时全路径上限 259 字符（260 含结尾 NUL），本机实测：
# 目录 229 + 分隔符 + 临时名可写，目录 230 即失败（Errno 2 / WinError 206）。
# _write_atomic 的临时名最长 ".transcript.json.<8位随机>.tmp"（29），故目录留 225：
# 225 + 1 + 29 = 255，另留 4 个字符余量给以后可能变长的文件名。
_MAX_DIRECTORY_PATH_LENGTH = 225


def _fitted_name(
    parent: Path, prefix: str, title_slug: str, suffix: str, *, reserve: int = 0
) -> str:
    """按剩余路径预算收缩标题；prefix 与 suffix（唯一标识）不参与截断。

    reserve 供父目录使用：父目录要为「子目录名 + 分隔符」留出空间，否则父目录会把预算用满。
    """

    room = _MAX_DIRECTORY_PATH_LENGTH - reserve - len(str(parent)) - 1 - len(prefix) - len(suffix)
    return f"{prefix}{title_slug[: max(room, 0)]}{suffix}"


def write_archive(
    root: Path,
    bundle: ArchiveBundle,
    *,
    now: datetime | None = None,
    batch_name: str | None = None,
    item_number: int | None = None,
) -> ArchivePaths:
    """Write one archive, optionally as one item in a shared batch directory."""

    del now
    validate_record(bundle.record)
    analyzed_at = str(bundle.record["analyzed_at"])
    year = (
        analyzed_at[:4] if len(analyzed_at) >= 4 and analyzed_at[:4].isdigit() else "unknown-year"
    )
    platform = safe_slug(str(bundle.record["source_platform"]), fallback="unknown-source")
    year_directory = root / year / platform
    title_slug = safe_slug(str(bundle.record["title"]))
    identity_suffix = f"--{bundle.record['content_id']}"
    if batch_name:
        ordinal = item_number if item_number is not None else 1
        if ordinal < 1:
            raise ValueError("batch item_number must be positive")
        item_prefix = f"{ordinal:02d}_"
        batch_directory = year_directory / _fitted_name(
            year_directory,
            "",
            safe_slug(batch_name, fallback="video-batch"),
            "",
            reserve=1 + len(item_prefix) + len(identity_suffix),
        )
        directory = batch_directory / _fitted_name(
            batch_directory, item_prefix, title_slug, identity_suffix
        )
    else:
        directory = year_directory / _fitted_name(
            year_directory, "", title_slug, identity_suffix
        )
    directory.mkdir(parents=True, exist_ok=True)
    _assert_within(root, directory)

    index_path = directory / "index.md"
    record_path = directory / "record.json"
    _write_text_atomic(index_path, render_markdown(bundle.record, bundle.summary_markdown))
    _write_json_atomic(record_path, bundle.record)

    transcript_path: Path | None = None
    if bundle.transcript is not None:
        transcript_path = directory / "transcript.json"
        _write_json_atomic(transcript_path, bundle.transcript)

    return ArchivePaths(directory, index_path, record_path, transcript_path)


def _assert_within(root: Path, path: Path) -> None:
    root_resolved = root.resolve()
    path_resolved = path.resolve()
    if path_resolved != root_resolved and root_resolved not in path_resolved.parents:
        raise ValueError("archive path escaped knowledge root")


def _write_text_atomic(path: Path, content: str) -> None:
    _write_atomic(path, content.encode("utf-8"))


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    content = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _write_text_atomic(path, content)


def _write_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(file_descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
