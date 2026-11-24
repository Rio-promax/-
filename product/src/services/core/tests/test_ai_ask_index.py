import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from zipfile import ZipFile

import pytest
from app.archive.schema import build_record
from app.archive.writer import ArchiveBundle, write_archive
from app.db.models import AskIndexContentRow
from app.db.store import SQLiteStore
from app.domain.jobs import JobState
from app.domain.models import (
    AnalysisSettings,
    ContentKind,
    SourcePlatform,
    Transcript,
    TranscriptSegment,
)
from app.knowledge.ask_index import AskIndex
from app.knowledge import ask_index as ask_index_module
from app.knowledge.siliconflow_retrieval import (
    EMBED_BATCH_SIZE,
    AskEmbeddingUnavailableError,
    SiliconFlowRetrieval,
)
from app.knowledge.source_map import map_transcript_segments
from app.knowledge.transcript import (
    transcript_from_text,
    transcript_position_kind,
    transcript_to_dict,
)


def _content(store: SQLiteStore, title: str):
    return store.create_content(
        kind=ContentKind.VIDEO,
        title=title,
        platform=SourcePlatform.BILIBILI,
        canonical_url=f"https://example.test/{title}",
        duration_seconds=120,
    )


def _archive(root, content, transcript: Transcript, summary: str = ""):
    record = build_record(
        content,
        model="test-model",
        prompt_version="summary-v1",
        transcript_source=transcript.source_kind,
        analyzed_at=datetime(2026, 10, 10, tzinfo=UTC),
    )
    return write_archive(
        root,
        ArchiveBundle(
            record=record,
            summary_markdown=summary,
            transcript=transcript_to_dict(transcript),
        ),
    ).directory


def _completed_archive_job(store: SQLiteStore, content_id: str, archive_path):
    _run, job = store.create_analysis_run(
        content_id, AnalysisSettings(model="test-model")
    )
    job.state = JobState.COMPLETED
    job.completed_at = datetime.now(UTC)
    job.metadata["archive_path"] = str(archive_path)
    store.save_job(job)
    return job


class _FakeEmbedding:
    dimension = 3

    def __init__(self, *, fail_on_call: int | None = None):
        self.fail_on_call = fail_on_call
        self.document_calls = 0
        self.document_batch_sizes = []
        self.config = {
            "engine": "fake-test-embedding",
            "model_id": "fake-v1",
            "dimension": self.dimension,
            "batch_size": EMBED_BATCH_SIZE,
            "source_map": "archive-transcript-v1",
            "span_rule": "one-transcript-segment-v1",
        }

    @staticmethod
    def _vector(text: str) -> list[float]:
        lowered = text.casefold()
        if any(token in lowered for token in ("许可", "授权", "字幕")):
            return [1.0, 0.0, 0.0]
        if any(token in lowered for token in ("文章", "采购", "章节")):
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]

    def embed_documents(self, texts: list[str], *, timeout: float = 60) -> list[list[float]]:
        self.document_calls += 1
        self.document_batch_sizes.append(len(texts))
        if self.document_calls == self.fail_on_call:
            raise AskEmbeddingUnavailableError("test embedding interruption")
        return [self._vector(text) for text in texts]

    def embed_query(self, query: str, *, timeout: float = 60) -> list[float]:
        return self._vector(query)


def test_index_maps_real_subtitles_but_not_estimated_text_times(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    root = tmp_path / "archives"
    index = AskIndex(store, root)

    subtitle_content = _content(store, "subtitle-source")
    subtitle_path = _archive(
        root,
        subtitle_content,
        Transcript(
            "zh",
            "bilibili_subtitle",
            "bilibili",
            (TranscriptSegment(12.5, 14.0, "授权许可条件只在字幕原文中出现"),),
        ),
    )
    subtitle_result = index.sync_content(
        subtitle_content.id,
        subtitle_path,
        summary_text="摘要辅助内容不提供时间位置",
    )

    subtitle_hit = index.search("授权许可条件只在字幕原文中出现")
    summary_hit = index.search("摘要辅助内容不提供时间位置")
    assert subtitle_result.status == "indexed"
    assert len(subtitle_hit) == 1
    assert subtitle_hit[0].location_kind == "timestamp"
    assert (subtitle_hit[0].start_seconds, subtitle_hit[0].end_seconds) == (12.5, 14.0)
    assert len(summary_hit) == 1
    assert summary_hit[0].source_kind == "summary"
    assert summary_hit[0].location_kind == "summary"
    assert summary_hit[0].start_seconds is None

    text_content = _content(store, "text-source")
    text_transcript = transcript_from_text("本地文章中的真实文本没有视频时间位置")
    text_path = _archive(root, text_content, text_transcript)
    text_result = index.sync_content(text_content.id, text_path)

    text_hit = index.search("本地文章中的真实文本没有视频时间位置")
    assert text_result.status == "indexed"
    assert len(text_hit) == 1
    assert text_hit[0].source_kind == "text"
    assert text_hit[0].location_kind == "detail_only"
    assert text_hit[0].start_seconds is None
    assert text_hit[0].end_seconds is None


def test_index_is_idempotent_updates_changed_sources_and_hides_soft_deleted_items(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    root = tmp_path / "archives"
    index = AskIndex(store, root)
    content = _content(store, "mutable-source")

    first_path = _archive(
        root,
        content,
        Transcript(
            "zh",
            "asr",
            "faster-whisper:test",
            (TranscriptSegment(2, 4, "旧版本专属证据短语"),),
        ),
    )
    first = index.sync_content(content.id, first_path)
    repeated = index.sync_content(content.id, first_path)
    assert repeated.source_hash == first.source_hash
    assert repeated.chunk_count == first.chunk_count == 1
    assert len(index.search("旧版本专属证据短语")) == 1

    updated_path = _archive(
        root,
        content,
        Transcript(
            "zh",
            "asr",
            "faster-whisper:test",
            (TranscriptSegment(7, 9, "更新版本专属证据短语"),),
        ),
    )
    updated = index.sync_content(content.id, updated_path)
    assert updated.source_hash != first.source_hash
    assert index.search("旧版本专属证据短语") == ()
    assert len(index.search("更新版本专属证据短语")) == 1

    store.soft_delete_content(content.id)
    index.mark_deleted(content.id)
    assert index.search("更新版本专属证据短语") == ()

    store.restore_content(content.id)
    restored = index.sync_content(content.id, updated_path)
    assert restored.status == "indexed"
    assert len(index.search("更新版本专属证据短语")) == 1


def test_legacy_plain_text_asr_placeholder_is_not_a_timestamp(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    root = tmp_path / "archives"
    index = AskIndex(store, root)
    content = _content(store, "legacy-asr-text")
    transcript = Transcript(
        "zh",
        "asr",
        "openai-compatible",
        (TranscriptSegment(0.0, 1.0, "旧式纯文本识别结果不应标记为时间"),),
    )
    path = _archive(root, content, transcript)
    legacy_transcript_path = path / "transcript.json"
    legacy_transcript = json.loads(legacy_transcript_path.read_text(encoding="utf-8"))
    legacy_transcript.pop("position_kind")
    legacy_transcript_path.write_text(
        json.dumps(legacy_transcript, ensure_ascii=False), encoding="utf-8"
    )

    result = index.sync_content(content.id, path)
    hit = index.search("旧式纯文本识别结果不应标记为时间")
    assert result.status == "indexed"
    assert len(hit) == 1
    assert hit[0].location_kind == "detail_only"
    assert hit[0].start_seconds is None
    assert hit[0].end_seconds is None


def test_position_mapping_rejects_article_and_legacy_asr_times_but_accepts_real_asr():
    segments = [{"start_seconds": 0.0, "end_seconds": 1.0, "text": "sample"}]
    assert transcript_position_kind("text", None, segments, explicit="timestamp") == "detail_only"
    assert transcript_position_kind(
        "asr", "openai-compatible", segments
    ) == "detail_only"
    assert transcript_position_kind(
        "asr",
        "faster-whisper:model",
        [{"start_seconds": 2.0, "end_seconds": 3.0, "text": "sample"}],
    ) == "timestamp"


def test_shared_source_map_is_used_for_existing_evidence_and_ask_index():
    article_spans = map_transcript_segments(
        {
            "source_kind": "text",
            "position_kind": "timestamp",
            "segments": [
                {"start_seconds": 40, "end_seconds": 42, "text": "文章段落原文"},
            ],
        }
    )
    subtitle_spans = map_transcript_segments(
        {
            "source_kind": "bilibili_subtitle",
            "position_kind": "timestamp",
            "segments": [
                {"start_seconds": 40, "end_seconds": 42, "text": "字幕时间来自原始轨道"},
            ],
        }
    )
    assert len(article_spans) == len(subtitle_spans) == 1
    assert article_spans[0].location_kind == "detail_only"
    assert article_spans[0].start_seconds is None
    assert subtitle_spans[0].location_kind == "timestamp"
    assert subtitle_spans[0].start_seconds == 40


def test_dynamic_chunks_group_source_units_cache_model_boundaries_and_expand_neighbors(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    root = tmp_path / "archives"
    calls = []

    def propose(_kind, units, *, timeout):
        calls.append((tuple(unit["source_ref"] for unit in units), timeout))
        return {"ends": [2, 4]}, {
            "input_bytes": 900,
            "usage": {"completion_tokens": 14},
        }

    index = AskIndex(
        store, root, embedding_backend=_FakeEmbedding(),
        chunk_boundary_proposer=propose, chunking_model="test-boundary-v1",
    )
    content = _content(store, "dynamic-chunk-source")
    path = _archive(
        root,
        content,
        Transcript(
            "zh", "asr", "faster-whisper:test",
            tuple(TranscriptSegment(i * 2, i * 2 + 1, f"第{i}段授权材料") for i in range(1, 5)),
        ),
    )

    first = index.sync_content(content.id, path)
    second = index.sync_content(content.id, path)

    spans = index.read_content_spans(content.id, evidence_kind="original")
    assert first.chunk_count == second.chunk_count == 2
    assert [span.chunk_ordinal for span in spans] == [1, 2]
    assert spans[0].source_refs == (
        "transcript:segment:1", "transcript:segment:2",
    )
    assert (spans[0].start_seconds, spans[0].end_seconds) == (2, 5)
    assert len(calls) == 1
    assert first.vector_status == "indexed"
    vector_hits = index.search_vector(
        "授权", content_ids=[content.id], query_vector=_FakeEmbedding._vector("授权"), limit=4,
    )
    assert len(vector_hits) == 2
    assert [hit.chunk_ordinal for hit in vector_hits] == [1, 2]
    expanded = index.read_chunks(
        [spans[0].stable_id], content_ids=[content.id], neighbor_window=1,
    )
    assert [hit.chunk_ordinal for hit in expanded] == [1, 2]
    assert all(len(hit.text.encode("utf-8")) <= index.max_chunk_utf8_bytes for hit in spans)


def test_invalid_dynamic_chunk_boundaries_fall_back_and_record_reason(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    root = tmp_path / "archives"

    def invalid(_kind, units, *, timeout):
        return {"ends": [len(units), 1]}, {"input_bytes": 300, "usage": {}}

    index = AskIndex(store, root, chunk_boundary_proposer=invalid, chunking_model="bad-boundary")
    content = _content(store, "invalid-dynamic-chunk-source")
    path = _archive(
        root, content,
        Transcript("zh", "asr", "faster-whisper:test", tuple(
            TranscriptSegment(i * 2, i * 2 + 1, f"第{i}段规则回退材料") for i in range(1, 4)
        )),
    )

    result = index.sync_content(content.id, path)

    with store.session_factory() as session:
        state = session.get(AskIndexContentRow, (index.profile_id, content.id))
    assert result.status == "indexed"
    assert state.chunking_status == "fallback"
    assert state.chunking_error_code == "boundary_output_invalid"
    assert state.chunking_calls == 1
    assert state.status == "indexed"


def test_summary_chunk_ordinals_keep_paragraph_ten_adjacent_in_source_order(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    root = tmp_path / "archives"
    calls = []

    def propose(_kind, units, *, timeout):
        calls.append(len(units))
        return {"ends": list(range(1, len(units) + 1))}, {
            "input_bytes": 1200,
            "usage": {"completion_tokens": 20},
        }

    index = AskIndex(store, root, chunk_boundary_proposer=propose, chunking_model="test-boundary-v1")
    content = _content(store, "summary-ordinal-ten")
    path = _archive(root, content, Transcript("zh", "asr", "faster-whisper:test", ()))
    summary = "\n\n".join(f"第{i}段总结内容与唯一线索" for i in range(1, 11))

    index.sync_content(content.id, path, summary_text=summary)
    spans = index.read_content_spans(content.id, evidence_kind="summary")
    center = next(span for span in spans if span.source_ref == "summary:paragraph:9")
    expanded = index.read_chunks([center.stable_id], content_ids=[content.id], neighbor_window=1)

    assert calls == [10]
    assert [span.source_ref for span in spans] == [f"summary:paragraph:{i}" for i in range(1, 11)]
    assert [span.source_ref for span in expanded] == [
        "summary:paragraph:8", "summary:paragraph:9", "summary:paragraph:10",
    ]


def test_chunk_boundary_requests_share_twenty_second_content_budget(tmp_path, monkeypatch):
    store = SQLiteStore("sqlite:///:memory:")
    elapsed = {"seconds": 0.0}
    requests = []

    def clock():
        return elapsed["seconds"]

    def propose(_kind, units, *, timeout):
        requests.append(timeout)
        elapsed["seconds"] += 4.9
        return {"ends": list(range(1, len(units) + 1))}, {
            "input_bytes": 100, "usage": {"completion_tokens": 1},
        }

    monkeypatch.setattr(ask_index_module, "monotonic", clock)
    index = AskIndex(store, tmp_path, chunk_boundary_proposer=propose, chunking_model="test-boundary")
    units = [{
        "source_kind": "transcript", "location_kind": "text",
        "source_ref": f"transcript:segment:{ordinal}", "ordinal": ordinal,
        "start_seconds": ordinal, "end_seconds": ordinal + 1, "text": "x" * 1500,
    } for ordinal in range(1, 31)]

    _chunks, state = index._build_chunks(units, "bounded-content")

    assert state["calls"] == len(requests) == 4
    assert requests == pytest.approx([20, 15.1, 10.2, 5.3])
    assert elapsed["seconds"] == pytest.approx(19.6)
    assert state["status"] == "partial_fallback"
    assert state["error_code"] == "boundary_time_budget_exhausted"


def test_chunk_boundary_requests_stop_at_six_per_content(tmp_path, monkeypatch):
    store = SQLiteStore("sqlite:///:memory:")
    calls = []
    monkeypatch.setattr(ask_index_module, "monotonic", lambda: 0.0)

    def propose(_kind, units, *, timeout):
        calls.append(timeout)
        return {"ends": list(range(1, len(units) + 1))}, {
            "input_bytes": 100, "usage": {"completion_tokens": 1},
        }

    index = AskIndex(store, tmp_path, chunk_boundary_proposer=propose, chunking_model="test-boundary")
    units = [{
        "source_kind": "transcript", "location_kind": "text",
        "source_ref": f"transcript:segment:{ordinal}", "ordinal": ordinal,
        "start_seconds": ordinal, "end_seconds": ordinal + 1, "text": "x" * 1500,
    } for ordinal in range(1, 60)]

    _chunks, state = index._build_chunks(units, "call-bounded-content")

    assert state["calls"] == len(calls) == 6
    assert state["status"] == "partial_fallback"
    assert state["error_code"] == "boundary_call_budget_exhausted"


def test_concurrent_sync_does_not_overwrite_newer_completed_archive(tmp_path, monkeypatch):
    store = SQLiteStore("sqlite:///:memory:")
    root = tmp_path / "archives"
    index = AskIndex(store, root)
    content = _content(store, "concurrent-source")

    old_archive = _archive(
        root,
        content,
        Transcript(
            "zh",
            "asr",
            "faster-whisper:test",
            (TranscriptSegment(1, 2, "旧完成版本独有证据"),),
        ),
    )
    old_snapshot = root / "old-completed-run"
    shutil.copytree(old_archive, old_snapshot)
    _completed_archive_job(store, content.id, old_snapshot)

    new_archive = _archive(
        root,
        content,
        Transcript(
            "zh",
            "asr",
            "faster-whisper:test",
            (TranscriptSegment(3, 4, "最新完成版本独有证据"),),
        ),
    )
    new_snapshot = root / "new-completed-run"
    shutil.copytree(new_archive, new_snapshot)

    original_read = index._read_spans
    old_read_started = Event()
    continue_old_read = Event()

    def pause_after_old_read(directory, content_id, summary_text):
        spans = original_read(directory, content_id, summary_text)
        if directory == old_snapshot.resolve():
            old_read_started.set()
            assert continue_old_read.wait(timeout=10)
        return spans

    monkeypatch.setattr(index, "_read_spans", pause_after_old_read)

    with ThreadPoolExecutor(max_workers=1) as executor:
        stale_sync = executor.submit(index.sync_content, content.id, old_snapshot)
        assert old_read_started.wait(timeout=10)
        _completed_archive_job(store, content.id, new_snapshot)
        latest_index = AskIndex(store, root)
        latest_result = latest_index.sync_latest(content.id)
        assert latest_result.status == "indexed"
        assert len(index.search("最新完成版本独有证据")) == 1
        continue_old_read.set()
        stale_result = stale_sync.result(timeout=10)

    assert stale_result.status == "indexed"
    assert index.search("旧完成版本独有证据") == ()
    latest_hit = index.search("最新完成版本独有证据")
    assert len(latest_hit) == 1
    assert latest_hit[0].source_ref == "transcript:segment:1"


def test_backfill_rechecks_latest_after_history_snapshot(tmp_path, monkeypatch):
    store = SQLiteStore("sqlite:///:memory:")
    root = tmp_path / "archives"
    index = AskIndex(store, root)
    content = _content(store, "stale-history-source")

    old_archive = _archive(
        root,
        content,
        Transcript(
            "zh",
            "asr",
            "faster-whisper:test",
            (TranscriptSegment(1, 2, "历史快照中的旧归档"),),
        ),
    )
    old_snapshot = root / "old-history-run"
    shutil.copytree(old_archive, old_snapshot)
    _completed_archive_job(store, content.id, old_snapshot)

    new_archive = _archive(
        root,
        content,
        Transcript(
            "zh",
            "asr",
            "faster-whisper:test",
            (TranscriptSegment(3, 4, "历史快照之后的新归档"),),
        ),
    )
    new_snapshot = root / "new-history-run"
    shutil.copytree(new_archive, new_snapshot)

    original_list_history = store.list_history
    history_ready = Event()
    continue_backfill = Event()

    def pause_after_history_snapshot(*args, **kwargs):
        entries = original_list_history(*args, **kwargs)
        history_ready.set()
        assert continue_backfill.wait(timeout=10)
        return entries

    monkeypatch.setattr(store, "list_history", pause_after_history_snapshot)

    with ThreadPoolExecutor(max_workers=1) as executor:
        backfill = executor.submit(index.backfill)
        assert history_ready.wait(timeout=10)
        _completed_archive_job(store, content.id, new_snapshot)
        latest_index = AskIndex(store, root)
        assert latest_index.sync_latest(content.id).status == "indexed"
        continue_backfill.set()
        backfill_result = backfill.result(timeout=10)

    assert backfill_result["indexed"] == 1
    assert index.search("历史快照中的旧归档") == ()
    assert len(index.search("历史快照之后的新归档")) == 1


def test_backup_restore_rebuilds_index_and_reports_coverage(tmp_path, monkeypatch):
    import app.api.main as main_module
    import app.db.store as store_module
    from fastapi.testclient import TestClient

    if "app.api.main" not in sys.modules:
        original_store = store_module.SQLiteStore

        class IsolatedDefaultStore(original_store):
            def __init__(self, database_url=None):
                if str(database_url or "").casefold().endswith("/local/knowledge.db"):
                    database_url = "sqlite:///:memory:"
                super().__init__(database_url)

        monkeypatch.setattr(store_module, "SQLiteStore", IsolatedDefaultStore)

    original_ask_index = main_module.AskIndex

    def ask_index_with_test_embedding(store, archive_root, **kwargs):
        return original_ask_index(
            store, archive_root, embedding_backend=_FakeEmbedding(), **kwargs,
        )

    monkeypatch.setattr(main_module, "AskIndex", ask_index_with_test_embedding)
    create_app = main_module.create_app

    source_root = tmp_path / "source-archives"
    source_app = create_app("sqlite:///:memory:", source_root)
    source_store = source_app.state.store
    content = _content(source_store, "backup-restore-source")
    archive_path = _archive(
        source_root,
        content,
        Transcript(
            "zh",
            "bilibili_subtitle",
            "bilibili",
            (TranscriptSegment(5, 6, "恢复归档后必须重建索引并核对覆盖"),),
        ),
    )
    _completed_archive_job(source_store, content.id, archive_path)
    source_store.upsert_summary(content.id, "备份中的摘要")

    with TestClient(source_app) as source_client:
        backup_response = source_client.post("/api/v1/data-governance/backup")
    assert backup_response.status_code == 201
    backup_path = Path(backup_response.json()["path"])
    with ZipFile(backup_path) as backup:
        snapshot = json.loads(backup.read("snapshot.json"))
    assert "ask_index_contents" not in snapshot["tables"]

    restored_root = tmp_path / "restored-archives"
    restored_backup = restored_root / "backups" / backup_path.name
    restored_backup.parent.mkdir(parents=True)
    shutil.copy2(backup_path, restored_backup)
    restored_app = create_app("sqlite:///:memory:", restored_root)
    with TestClient(restored_app) as restored_client:
        restored_response = restored_client.post(
            "/api/v1/data-governance/restore",
            json={"path": str(restored_backup)},
        )

    assert restored_response.status_code == 200
    payload = restored_response.json()
    assert payload["restored_content_count"] == 1
    assert payload["restored_archive_files"] >= 1
    assert payload["ask_index_backfill"]["indexed"] == 1
    assert payload["ask_index_coverage"] == {
        "total_completed": 1,
        "indexed": 1,
        "partial": 0,
        "failed": 0,
        "pending": 0,
    }
    assert payload["ask_index_vector_coverage"]["indexed"] == 1
    assert payload["ask_index_vector_coverage"]["covered_chunks"] == 2
    assert payload["ask_index_vector_coverage"]["total_chunks"] == 2
    hits = restored_app.state.ask_index.search("恢复归档后必须重建索引并核对覆盖")
    assert len(hits) == 1
    assert hits[0].location_kind == "timestamp"
    vector_hits = restored_app.state.ask_index.search_vector(
        "恢复归档后必须重建索引并核对覆盖"
    )
    assert any(vector_hit.source_ref == hits[0].source_ref for vector_hit in vector_hits)


def test_vector_search_filters_content_and_keeps_source_positions(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    root = tmp_path / "archives"
    backend = _FakeEmbedding()
    index = AskIndex(store, root, embedding_backend=backend)

    subtitle_content = _content(store, "vector-subtitle")
    subtitle_path = _archive(
        root,
        subtitle_content,
        Transcript(
            "zh",
            "bilibili_subtitle",
            "bilibili",
            (TranscriptSegment(31, 33, "授权许可条件在字幕原文中说明"),),
        ),
    )
    article_content = _content(store, "vector-article")
    article_path = _archive(
        root,
        article_content,
        transcript_from_text("文章章节介绍采购流程"),
    )
    excluded_content = _content(store, "vector-excluded")
    excluded_path = _archive(
        root,
        excluded_content,
        Transcript("zh", "asr", "faster-whisper:test", (TranscriptSegment(1, 2, "独立向量候选"),)),
    )
    for content, path in (
        (subtitle_content, subtitle_path),
        (article_content, article_path),
        (excluded_content, excluded_path),
    ):
        result = index.sync_content(content.id, path)
        assert result.vector_status == "indexed"

    subtitle_hits = index.search_vector(
        "文章采购条款", content_ids=[subtitle_content.id]
    )
    assert len(subtitle_hits) == 1
    assert subtitle_hits[0].content_id == subtitle_content.id
    assert subtitle_hits[0].source_kind == "bilibili_subtitle"
    assert subtitle_hits[0].location_kind == "timestamp"
    assert (subtitle_hits[0].start_seconds, subtitle_hits[0].end_seconds) == (31, 33)

    multi_content_hits = index.search_vector(
        "文章采购条款", content_ids=[subtitle_content.id, article_content.id]
    )
    assert {hit.content_id for hit in multi_content_hits} <= {
        subtitle_content.id,
        article_content.id,
    }
    article_hits = index.search_vector(
        "文章采购流程", content_ids=[article_content.id]
    )
    assert len(article_hits) == 1
    assert article_hits[0].location_kind == "detail_only"
    assert article_hits[0].start_seconds is None
    assert article_hits[0].end_seconds is None
    hybrid_hits = index.search_hybrid(
        "文章章节介绍采购流程", content_ids=[article_content.id]
    )
    assert len(hybrid_hits) == 1
    assert hybrid_hits[0].content_id == article_content.id


def test_vector_profile_isolated_by_embedding_version(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    root = tmp_path / "archives"
    first_backend = _FakeEmbedding()
    first_index = AskIndex(store, root, embedding_backend=first_backend)
    content = _content(store, "vector-profile-version")
    path = _archive(
        root,
        content,
        Transcript("zh", "asr", "faster-whisper:test", (TranscriptSegment(1, 2, "授权许可依据"),)),
    )
    assert first_index.sync_content(content.id, path).vector_status == "indexed"

    second_backend = _FakeEmbedding()
    second_backend.config = {**second_backend.config, "model_id": "fake-v2"}
    second_index = AskIndex(store, root, embedding_backend=second_backend)
    assert second_index.vector_profile_id != first_index.vector_profile_id
    assert second_index.search_vector("授权许可依据") == ()
    assert len(first_index.search_vector("授权许可依据")) == 1


def test_embedding_batch_size_is_part_of_the_vector_profile(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    root = tmp_path / "archives"
    current_config = SiliconFlowRetrieval.config
    assert current_config["batch_size"] == 32

    current_backend = _FakeEmbedding()
    current_backend.config = current_config
    current_index = AskIndex(store, root, embedding_backend=current_backend)

    previous_backend = _FakeEmbedding()
    previous_backend.config = {**current_config, "batch_size": 2}
    previous_index = AskIndex(store, root, embedding_backend=previous_backend)

    assert previous_index.vector_profile_id != current_index.vector_profile_id


def test_vector_index_persists_updates_deletes_and_restores(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    root = tmp_path / "archives"
    backend = _FakeEmbedding()
    index = AskIndex(store, root, embedding_backend=backend)
    content = _content(store, "vector-lifecycle")
    first_path = _archive(
        root,
        content,
        Transcript(
            "zh",
            "asr",
            "faster-whisper:test",
            (TranscriptSegment(2, 4, "旧版授权许可说明"),),
        ),
    )
    assert index.sync_content(content.id, first_path).vector_status == "indexed"

    restarted_backend = _FakeEmbedding()
    restarted_index = AskIndex(store, root, embedding_backend=restarted_backend)
    assert len(restarted_index.search_vector("授权许可说明")) == 1

    store.soft_delete_content(content.id)
    assert restarted_index.mark_deleted(content.id).vector_status == "deleted"
    assert restarted_index.search_vector("授权许可说明") == ()

    store.restore_content(content.id)
    restored = restarted_index.sync_content(content.id, first_path)
    assert restored.vector_status == "indexed"
    assert len(restarted_index.search_vector("授权许可说明")) == 1
    assert restarted_backend.document_calls == 0

    updated_path = _archive(
        root,
        content,
        Transcript(
            "zh",
            "asr",
            "faster-whisper:test",
            (TranscriptSegment(8, 10, "新版授权许可说明"),),
        ),
    )
    updated = restarted_index.sync_content(content.id, updated_path)
    assert updated.vector_status == "indexed"
    assert len(restarted_index.search_vector("新版授权许可说明")) == 1
    assert restarted_backend.document_calls == 1


def test_vector_partial_coverage_resumes_without_reembedding_completed_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr("app.knowledge.ask_index.EMBED_BATCH_SIZE", 4)
    store = SQLiteStore("sqlite:///:memory:")
    root = tmp_path / "archives"
    backend = _FakeEmbedding(fail_on_call=2)
    index = AskIndex(store, root, embedding_backend=backend)
    content = _content(store, "vector-partial")
    path = _archive(
        root,
        content,
        Transcript(
            "zh",
            "asr",
            "faster-whisper:test",
            tuple(
                TranscriptSegment(
                    index * 2 + 1, index * 2 + 2,
                    f"授权条件第{index + 1}段" + "x" * 1800,
                )
                for index in range(9)
            ),
        ),
    )
    _completed_archive_job(store, content.id, path)

    partial = index.sync_content(content.id, path)
    assert partial.vector_status == "partial"
    assert partial.vector_error_code == "embedding_unavailable"
    first_coverage = index.vector_coverage_snapshot()
    assert first_coverage["partial"] == 1
    assert first_coverage["covered_chunks"] == 4
    assert first_coverage["total_chunks"] == 9
    assert first_coverage["errors"] == {"embedding_unavailable": 1}
    assert backend.document_batch_sizes == [4, 4]

    current_profile_id = index.vector_profile_id
    index.close()
    restarted_backend = _FakeEmbedding()
    restarted_index = AskIndex(store, root, embedding_backend=restarted_backend)
    assert restarted_index.vector_profile_id == current_profile_id
    resumed = restarted_index.sync_content(content.id, path)
    assert resumed.vector_status == "indexed"
    assert restarted_backend.document_batch_sizes == [4, 1]
    final_coverage = restarted_index.vector_coverage_snapshot()
    assert final_coverage["indexed"] == 1
    assert final_coverage["covered_chunks"] == 9
    assert final_coverage["total_chunks"] == 9
    assert len(restarted_index.search_vector("授权条件")) == 9


def test_hybrid_does_not_return_keyword_only_partial_vector_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr("app.knowledge.ask_index.EMBED_BATCH_SIZE", 4)
    store = SQLiteStore("sqlite:///:memory:")
    root = tmp_path / "archives"
    backend = _FakeEmbedding(fail_on_call=2)
    index = AskIndex(store, root, embedding_backend=backend)
    content = _content(store, "hybrid-partial-vector-coverage")
    unembedded_query = "未处理证据唯一标识只存在于第五片段"
    unembedded_text = unembedded_query + "x" * 1800
    path = _archive(
        root,
        content,
        Transcript(
            "zh",
            "asr",
            "faster-whisper:test",
            (
                TranscriptSegment(1, 2, "授权依据第一段已写入向量索引" + "x" * 1800),
                TranscriptSegment(3, 4, "授权依据第二段已写入向量索引" + "x" * 1800),
                TranscriptSegment(5, 6, "授权依据第三段已写入向量索引" + "x" * 1800),
                TranscriptSegment(7, 8, "授权依据第四段已写入向量索引" + "x" * 1800),
                TranscriptSegment(9, 10, unembedded_text),
                TranscriptSegment(11, 12, "授权依据第六段等待向量处理" + "x" * 1800),
                TranscriptSegment(13, 14, "授权依据第七段等待向量处理" + "x" * 1800),
                TranscriptSegment(15, 16, "授权依据第八段等待向量处理" + "x" * 1800),
                TranscriptSegment(17, 18, "授权依据第九段等待向量处理" + "x" * 1800),
                TranscriptSegment(19, 20, "授权依据第十段等待向量处理" + "x" * 1800),
            ),
        ),
    )

    result = index.sync_content(content.id, path)

    assert result.vector_status == "partial"
    assert any(unembedded_query in hit.text for hit in index.search_keyword(unembedded_query))
    hybrid_hits = index.search_hybrid(unembedded_query)
    assert hybrid_hits
    assert all(unembedded_query not in hit.text for hit in hybrid_hits)


def test_cloud_rerank_reorders_hybrid_candidates(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    root = tmp_path / "archives"
    fake = _FakeEmbedding()
    backend = SiliconFlowRetrieval("synthetic-test-key")
    backend.dimension = fake.dimension
    backend.config = fake.config
    backend.embed_documents = fake.embed_documents
    backend.embed_query = fake.embed_query
    backend.rerank = lambda query, documents, *, timeout=60: [
        (index, float(index)) for index in reversed(range(len(documents)))
    ]
    index = AskIndex(store, root, embedding_backend=backend)
    content = _content(store, "cloud-rerank")
    path = _archive(
        root,
        content,
        Transcript(
            "zh",
            "asr",
            "faster-whisper:test",
            (
                    TranscriptSegment(1, 2, "授权依据第一段" + "x" * 1500),
                    TranscriptSegment(3, 4, "授权依据第二段" + "x" * 1500),
            ),
        ),
    )
    assert index.sync_content(content.id, path).vector_status == "indexed"
    candidates = index.search_hybrid("授权依据", limit=2, rerank=True)
    assert len(candidates) == 2
    assert [hit.rank for hit in candidates] == [1.0, 0.0]
    trace = {}
    shortlist = index.search_hybrid("授权依据", limit=1, rerank=True, ranking_trace=trace)
    assert [hit.stable_id for hit in shortlist] == trace["reranked_ids"][:1]
    assert trace["reranked_ids"] == trace["rrf_ids"][::-1]
    assert len(trace["reranked_ids"]) == 2


def test_vector_sync_recreates_missing_point_on_existing_chunk(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    root = tmp_path / "archives"
    index = AskIndex(store, root, embedding_backend=_FakeEmbedding())
    content = _content(store, "recover-existing-vector-chunk")
    path = _archive(root, content, Transcript(
        "zh", "asr", "faster-whisper:test", (TranscriptSegment(1, 2, "已有分块缺少向量"),),
    ))
    assert index.sync_content(content.id, path).vector_status == "indexed"
    with store.session_factory.begin() as session:
        point_ids = [point_id for point_id, _ in index._vector_rows(session, content.id)]
        assert point_ids
        index._delete_vector_points(session, point_ids)
    assert index.sync_content(content.id, path).vector_status == "indexed"
    with store.session_factory() as session:
        assert [point_id for point_id, _ in index._vector_rows(session, content.id)] == point_ids


def test_hybrid_loads_sqlite_vec_on_reconnected_disk_session(tmp_path):
    database_path = tmp_path / "ask-index.sqlite3"
    store = SQLiteStore(f"sqlite:///{database_path.as_posix()}")
    root = tmp_path / "archives"
    index = AskIndex(store, root, embedding_backend=_FakeEmbedding())
    content = _content(store, "hybrid-reconnected-disk-store")
    path = _archive(
        root,
        content,
        Transcript(
            "zh",
            "asr",
            "faster-whisper:test",
            (TranscriptSegment(11, 13, "SQLite 新连接加载扩展后仍可完成混合检索"),),
        ),
    )
    assert index.sync_content(content.id, path).vector_status == "indexed"

    store.engine.dispose()

    hits = index.search_hybrid("SQLite 新连接加载扩展后仍可完成混合检索")

    assert len(hits) == 1
    assert hits[0].content_id == content.id
    assert hits[0].location_kind == "timestamp"


def test_coverage_counts_explicit_pending_state(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    root = tmp_path / "archives"
    index = AskIndex(store, root, embedding_backend=_FakeEmbedding())
    content = _content(store, "pending-coverage")
    path = _archive(
        root,
        content,
        Transcript(
            "zh",
            "asr",
            "faster-whisper:test",
            (TranscriptSegment(1, 2, "尚未处理的索引证据"),),
        ),
    )
    _completed_archive_job(store, content.id, path)
    assert index.sync_content(content.id, path).vector_status == "indexed"

    with store.session_factory.begin() as session:
        for profile_id in (index.profile_id, index.vector_profile_id):
            state = session.get(AskIndexContentRow, (profile_id, content.id))
            state.status = "pending"

    keyword_coverage = index.coverage_snapshot()
    vector_coverage = index.vector_coverage_snapshot()
    assert keyword_coverage["total_completed"] == 1
    assert keyword_coverage["pending"] == 1
    assert keyword_coverage["indexed"] == 0
    assert vector_coverage["pending"] == 1
    assert vector_coverage["indexed"] == 0
    assert vector_coverage["covered_chunks"] == 0
    assert vector_coverage["total_chunks"] == 1


def test_scope_coverage_counts_indexed_failed_and_pending_content(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    root = tmp_path / "archives"
    index = AskIndex(store, root)
    indexed = _content(store, "scope-indexed")
    failed = _content(store, "scope-failed")
    pending = _content(store, "scope-pending")
    path = _archive(
        root,
        indexed,
        Transcript("zh", "asr", "faster-whisper:test", (
            TranscriptSegment(1, 2, "当前索引覆盖需按冻结范围统计"),
        )),
    )
    index.sync_content(indexed.id, path)
    index.record_failure(failed.id, "archive_missing")

    coverage = index.coverage_for([indexed.id, failed.id, pending.id])

    assert coverage == {
        "profile_id": index.profile_id,
        "target": 3,
        "indexed": 1,
        "partial": 0,
        "failed": 1,
        "pending": 1,
    }


def test_vector_coverage_loads_sqlite_vec_on_reconnected_disk_session(tmp_path):
    database_path = tmp_path / "ask-index.sqlite3"
    store = SQLiteStore(f"sqlite:///{database_path.as_posix()}")
    root = tmp_path / "archives"
    index = AskIndex(store, root, embedding_backend=_FakeEmbedding())
    content = _content(store, "coverage-reconnected-disk-store")
    path = _archive(
        root,
        content,
        Transcript(
            "zh",
            "asr",
            "faster-whisper:test",
            (TranscriptSegment(15, 17, "覆盖查询应在新连接加载 SQLite 向量扩展"),),
        ),
    )
    _completed_archive_job(store, content.id, path)
    assert index.sync_content(content.id, path).vector_status == "indexed"

    store.engine.dispose()

    snapshot = index.vector_coverage_snapshot()

    assert snapshot["indexed"] == 1
    assert snapshot["covered_chunks"] == 1
    assert snapshot["total_chunks"] == 1


def test_vector_state_coverage_is_distinct_from_verified_vector_points(tmp_path):
    from app.db.models import AskIndexChunkRow

    store = SQLiteStore("sqlite:///:memory:")
    root = tmp_path / "archives"
    index = AskIndex(store, root, embedding_backend=_FakeEmbedding())
    content = _content(store, "unverified-vector-state")
    path = _archive(
        root,
        content,
        Transcript(
            "zh",
            "asr",
            "faster-whisper:test",
            (TranscriptSegment(3, 5, "向量点状态校验"),),
        ),
    )
    _completed_archive_job(store, content.id, path)
    assert index.sync_content(content.id, path).vector_status == "indexed"

    with store.session_factory() as session:
        point_id = session.query(AskIndexChunkRow.id).filter_by(
            profile_id=index.vector_profile_id, content_id=content.id,
        ).scalar()
    with store.engine.begin() as connection:
        index._load_vector_extension(connection)
        connection.exec_driver_sql(
            f"DELETE FROM {index.vector_table_name} WHERE point_id = ?", (point_id,)
        )

    status_snapshot = index.vector_state_coverage_snapshot()
    verified_snapshot = index.vector_coverage_snapshot()

    assert status_snapshot["status_record_covered_chunks"] == 1
    assert status_snapshot["coverage_basis"] == "status_records"
    assert status_snapshot["vector_points_verified"] is False
    assert verified_snapshot["covered_chunks"] == 0
    assert verified_snapshot["total_chunks"] == 1


def test_app_starts_and_keeps_content_indexing_when_sqlite_vec_cannot_load(
    tmp_path, monkeypatch
):
    import app.db.store as store_module
    from fastapi.testclient import TestClient

    if "app.api.main" not in sys.modules:
        original_store = store_module.SQLiteStore

        class IsolatedDefaultStore(original_store):
            def __init__(self, database_url=None):
                if str(database_url or "").casefold().endswith("/local/knowledge.db"):
                    database_url = "sqlite:///:memory:"
                super().__init__(database_url)

        monkeypatch.setattr(store_module, "SQLiteStore", IsolatedDefaultStore)

    import app.api.main as main_module

    def fail_vector_extension(_connection):
        raise AskEmbeddingUnavailableError(
            "sqlite-vec 未安装或无法载入；请安装项目依赖 sqlite-vec"
        )

    monkeypatch.setattr(
        AskIndex, "_load_vector_extension", staticmethod(fail_vector_extension)
    )

    def ask_index_with_test_embedding(store, archive_root, **kwargs):
        return AskIndex(store, archive_root, embedding_backend=_FakeEmbedding(), **kwargs)

    monkeypatch.setattr(main_module, "AskIndex", ask_index_with_test_embedding)
    archive_root = tmp_path / "archives"
    app = main_module.create_app("sqlite:///:memory:", archive_root)

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/settings").status_code == 200

        index = app.state.ask_index
        assert index is not None
        assert app.state.ask_index_error == (
            "sqlite-vec 未安装或无法载入；请安装项目依赖 sqlite-vec"
        )
        content = _content(app.state.store, "sqlite-vec-unavailable-content-flow")
        path = _archive(
            archive_root,
            content,
            Transcript(
                "zh",
                "asr",
                "faster-whisper:test",
                (TranscriptSegment(1, 2, "内容归档关键词仍能建立诊断索引"),),
            ),
        )
        result = index.sync_content(content.id, path)

        assert result.status == "indexed"
        assert result.vector_status == "failed"
        assert len(index.search_keyword("内容归档关键词仍能建立诊断索引")) == 1
        with pytest.raises(AskEmbeddingUnavailableError, match="sqlite-vec 未安装或无法载入"):
            index.search_vector("内容归档关键词仍能建立诊断索引")
        with pytest.raises(AskEmbeddingUnavailableError, match="sqlite-vec 未安装或无法载入"):
            index.search_hybrid("内容归档关键词仍能建立诊断索引")


def test_explicit_full_index_rebuild_tracks_failures_and_resumes_on_restart(
    tmp_path, monkeypatch,
):
    import app.api.main as main_module
    from fastapi.testclient import TestClient

    original_ask_index = main_module.AskIndex
    backends = [_FakeEmbedding(fail_on_call=1)]

    def ask_index_with_test_embedding(store, archive_root, **kwargs):
        return original_ask_index(
            store, archive_root, embedding_backend=backends[0], **kwargs,
        )

    monkeypatch.setattr(main_module, "AskIndex", ask_index_with_test_embedding)
    database_path = tmp_path / "knowledge.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    archive_root = tmp_path / "archives"
    app = main_module.create_app(database_url, archive_root)
    store = app.state.store
    for number in range(6):
        content = _content(store, f"full-rebuild-{number}")
        archive_path = _archive(
            archive_root,
            content,
            Transcript("zh", "asr", "faster-whisper:test", (
                TranscriptSegment(1, 2, f"全库重建第{number}篇资料"),
            )),
        )
        _completed_archive_job(store, content.id, archive_path)

    def wait_for_index_status(client, expected):
        for _ in range(200):
            overview = client.get("/api/v1/dev/rag/overview").json()
            if overview["index"]["rebuild"]["status"] == expected:
                return overview
            Event().wait(0.025)
        pytest.fail(f"索引状态未变为 {expected}")

    with TestClient(app) as client:
        before = client.get("/api/v1/dev/rag/overview").json()
        first_profile_id = before["index"]["profile_id"]
        assert before["index"]["text"]["pending"] == 6
        assert before["index"]["rebuild"]["status"] == "not_started"
        assert backends[0].document_calls == 0

        started = client.post("/api/v1/dev/rag/index/rebuild")
        assert started.status_code == 202
        failed = wait_for_index_status(client, "failed")
        assert (
            failed["index"]["text"]["indexed"]
            + failed["index"]["text"]["partial"]
        ) == 6
        assert failed["index"]["vector"]["failed"] == 1
        assert failed["index"]["rebuild"]["retryable"] is True

        retried = client.post("/api/v1/dev/rag/index/rebuild")
        assert retried.status_code == 202
        complete = wait_for_index_status(client, "complete")
        assert complete["index"]["profile_id"] == first_profile_id
        assert complete["index"]["text"]["indexed"] + complete["index"]["text"]["partial"] == 6
        assert complete["index"]["vector"]["indexed"] + complete["index"]["vector"]["partial"] == 6
        assert backends[0].document_calls == 7

    store.engine.dispose()
    backends[0] = _FakeEmbedding()
    restarted_app = main_module.create_app(database_url, archive_root)
    with TestClient(restarted_app) as restarted_client:
        after_restart = restarted_client.get("/api/v1/dev/rag/overview").json()
        assert after_restart["index"]["profile_id"] == first_profile_id
        assert after_restart["index"]["text"]["indexed"] + after_restart["index"]["text"]["partial"] == 6
        assert after_restart["index"]["vector"]["indexed"] + after_restart["index"]["vector"]["partial"] == 6
        assert backends[0].document_calls == 0


def test_failed_index_rebuild_exception_is_persisted_for_restart(tmp_path, monkeypatch):
    import app.api.main as main_module
    from fastapi.testclient import TestClient

    def fail_backfill(_self):
        raise RuntimeError("injected index failure")

    monkeypatch.setattr(main_module.AskIndex, "backfill", fail_backfill)
    database_path = tmp_path / "knowledge.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    archive_root = tmp_path / "archives"
    app = main_module.create_app(database_url, archive_root)
    store = app.state.store
    content = _content(store, "persist-failed-backfill")
    archive_path = _archive(
        archive_root,
        content,
        Transcript("zh", "asr", "faster-whisper:test", (
            TranscriptSegment(1, 2, "失败状态需要在重启后保留"),
        )),
    )
    _completed_archive_job(store, content.id, archive_path)

    with TestClient(app) as client:
        started = client.post("/api/v1/dev/rag/index/rebuild")
        assert started.status_code == 202
        app.state.ask_index_backfill_future.result(timeout=5)
        persisted = json.loads(store.get_setting("ask_index_backfill_state"))
        assert persisted["status"] == "failed"
        assert persisted["error_code"] == "index_backfill_failed"

    store.engine.dispose()
    restarted_app = main_module.create_app(database_url, archive_root)
    with TestClient(restarted_app) as restarted_client:
        overview = restarted_client.get("/api/v1/dev/rag/overview").json()
        assert overview["index"]["rebuild"]["status"] == "failed"
        assert overview["index"]["rebuild"]["retryable"] is True
        assert restarted_app.state.ask_index_backfill_future is None


def test_vector_configuration_errors_are_explicit_without_keyword_fallback(
    tmp_path, monkeypatch
):
    from app.knowledge.siliconflow_retrieval import API_KEY_ENV

    monkeypatch.delenv(API_KEY_ENV, raising=False)
    store = SQLiteStore("sqlite:///:memory:")
    root = tmp_path / "archives"
    index = AskIndex(store, root)
    content = _content(store, "vector-missing-model")
    path = _archive(
        root,
        content,
        Transcript(
            "zh",
            "asr",
            "faster-whisper:test",
            (TranscriptSegment(1, 2, "模型缺失时关键词仍可诊断"),),
        ),
    )

    result = index.sync_content(content.id, path)
    assert result.vector_status is None
    assert result.vector_error_code is None
    assert len(index.search_keyword("模型缺失时关键词仍可诊断")) == 1
    with pytest.raises(AskEmbeddingUnavailableError, match="SILICONFLOW_API_KEY"):
        index.search_vector("模型缺失时关键词仍可诊断")
    with pytest.raises(AskEmbeddingUnavailableError, match="SILICONFLOW_API_KEY"):
        index.search_hybrid("模型缺失时关键词仍可诊断")
