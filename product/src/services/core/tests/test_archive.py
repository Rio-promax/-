from datetime import UTC, datetime

from app.archive.schema import build_record, render_markdown, safe_slug, validate_record
from app.archive.writer import ArchiveBundle, file_sha256, write_archive
from app.domain.models import ContentItem, ContentKind, SourcePlatform, SourceRecord


def make_record() -> dict[str, object]:
    content = ContentItem.create(
        kind=ContentKind.VIDEO,
        title="长视频：可靠的知识整理",
        source=SourceRecord(SourcePlatform.BILIBILI, canonical_url="https://example.test/video"),
        content_hash="abc123",
    )
    return build_record(
        content,
        model="test-model",
        prompt_version="summary-v1",
        transcript_source="subtitle",
        analyzed_at=datetime(2026, 1, 2, tzinfo=UTC),
        tags=("知识", "知识", "教程"),
    )


def test_archive_schema_and_markdown() -> None:
    record = make_record()
    validate_record(record)
    markdown = render_markdown(record, "# 结论\n\n内容正文")
    # 用户可读头部,不再输出技术性 frontmatter
    assert not markdown.startswith("---")
    assert markdown.startswith("# 长视频：可靠的知识整理")
    assert "平台：bilibili" in markdown
    assert "来源：https://example.test/video" in markdown
    assert "分析时间：" in markdown
    assert "# 结论" in markdown
    assert "content_id" not in markdown
    assert record["tags"] == ["知识", "教程"]


def test_write_archive_is_portable_and_has_no_temp_files(tmp_path) -> None:
    record = make_record()
    paths = write_archive(
        tmp_path,
        ArchiveBundle(
            record=record,
            summary_markdown="# 结论\n\n- 可恢复\n",
            transcript={"segments": []},
        ),
    )

    assert paths.index.exists()
    assert paths.record.exists()
    assert paths.transcript is not None and paths.transcript.exists()
    assert paths.index.read_text(encoding="utf-8").endswith("\n")
    assert not list(paths.directory.glob("*.tmp"))
    assert len(file_sha256(paths.index)) == 64


def test_batch_archive_directory_respects_windows_path_budget(tmp_path) -> None:
    """批次名与标题再长，目录全路径也不得逼近 Windows 260 上限。"""

    content = ContentItem.create(
        kind=ContentKind.VIDEO,
        title="长视频：可靠的知识整理" * 12,
        source=SourceRecord(SourcePlatform.BILIBILI, canonical_url="https://example.test/long"),
        content_hash="long",
    )
    record = build_record(
        content,
        model="test-model",
        prompt_version="summary-v1",
        transcript_source="subtitle",
        analyzed_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    batch_name = f"batch_{'f' * 8}-{'批次标题' * 20}"
    padded_root = tmp_path / ("p" * max(120 - len(str(tmp_path)) - 1, 1))

    naive_directory = (
        padded_root
        / "2026"
        / "bilibili"
        / safe_slug(batch_name)
        / f"03_{safe_slug(str(record['title']))}--{record['content_id']}"
    )
    assert len(str(naive_directory)) > 260, "该用例必须覆盖超长路径场景"

    paths = write_archive(
        padded_root,
        ArchiveBundle(
            record=record,
            summary_markdown="# 结论\n",
            transcript={"segments": [{"start": 0.0, "text": "开场"}]},
        ),
        batch_name=batch_name,
        item_number=3,
    )

    # 259 是本机实测的全路径上限；再减去分隔符与最长临时名
    # ".transcript.json.<8位随机>.tmp"（29），目录不得超过 229。
    assert len(str(paths.directory)) <= 229
    assert paths.directory.name.startswith("03_")
    assert paths.directory.name.endswith(f"--{record['content_id']}")
    assert paths.index.exists() and paths.record.exists()
    assert paths.transcript is not None and paths.transcript.exists()
