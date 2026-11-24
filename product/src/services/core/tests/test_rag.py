import json
from datetime import UTC, datetime
from time import monotonic
from types import SimpleNamespace

import pytest

from app.archive.schema import build_record
from app.archive.writer import ArchiveBundle, write_archive
from app.db.store import SQLiteStore
from app.domain.models import (
    AnalysisSettings,
    Chunk,
    ContentKind,
    SourcePlatform,
    SummaryStrength,
    Transcript,
    TranscriptSegment,
)
from app.knowledge.ask_index import AskIndex, AskIndexHit
from app.knowledge.transcript import transcript_to_dict
from app.adapters.summary import openai_compatible
from app.adapters.summary.openai_compatible import OpenAICompatibleSummarizer, SummarySettings, _summary_input
from app.knowledge.rag import (
    RagService, RESPOND_SCHEMA, ROUTE_SCHEMA, SCAN_SCHEMA,
    _exception_trace, _explicit_compare_content_ids, _limit_evidence, _retrieval_budget,
    _retrieval_query_aliases, _strict_keys,
    _supplement_exhausted, _validate_route, _validate_scan, classification_source_version,
)


def _archive(root, content, *, transcript: Transcript, summary: str):
    record = build_record(
        content,
        model="test-model",
        prompt_version="summary-v1",
        transcript_source=transcript.source_kind,
        analyzed_at=datetime(2026, 10, 31, tzinfo=UTC),
    )
    return write_archive(
        root,
        ArchiveBundle(
            record=record,
            summary_markdown=summary,
            transcript=transcript_to_dict(transcript),
        ),
    ).directory


def _versioned_original_evidence(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    content = store.create_content(kind=ContentKind.ARTICLE, title="版本核验", platform=SourcePlatform.LOCAL)
    text = "原文记录版本A的处理顺序：先检查材料，再生成回答。"
    summary = "总结说明版本A处理材料的流程。"
    transcript = Transcript("zh", "plain_text", "local", (TranscriptSegment(0, 2, text),))
    archive = _archive(tmp_path / "archives", content, transcript=transcript, summary=summary)
    store.upsert_summary(content.id, summary)
    store.create_summary_version(
        content.id, summary, template="general", origin="original",
        summary_strength="standard", material_level="M2", source_version="transcript-v1",
    )
    index = AskIndex(store, tmp_path / "archives")
    index.sync_content(content.id, archive, summary_text=summary)
    service = RagService(store, index)
    store.list_history = lambda **_kwargs: [SimpleNamespace(content=content)]
    scope = service.freeze_scope({"kind": "selected", "content_ids": [content.id], "material_scope": "full"})
    hit = index.search_keyword("版本A", evidence_kind="original")[0]
    evidence = service._evidence([hit], scope["content_ids"], scope["source_versions"])
    return store, content, archive, summary, index, service, scope, evidence


def test_rag_evidence_includes_exactly_one_adjacent_transcript_chunk_each_side(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    content = store.create_content(
        kind=ContentKind.ARTICLE, title="邻接证据", platform=SourcePlatform.LOCAL,
    )
    transcript = Transcript("zh", "asr", "faster-whisper:test", tuple(
        TranscriptSegment((index - 1) * 2, index * 2, f"转写片段{index}，保留原始时间。")
        for index in range(1, 6)
    ))
    archive = _archive(
        tmp_path / "archives", content, transcript=transcript, summary="",
    )
    index = AskIndex(
        store, tmp_path / "archives",
        chunk_boundary_proposer=lambda _kind, units, timeout: (
            {"ends": list(range(1, len(units) + 1))},
            {"usage": {"completion_tokens": 0}},
        ),
    )
    indexed = index.sync_content(content.id, archive, summary_text="")
    original_spans = index.read_content_spans(content.id, evidence_kind="original")
    assert indexed.status == "indexed"
    assert len(original_spans) == 5
    service = RagService(store, index)
    store.list_history = lambda **_kwargs: [SimpleNamespace(content=content)]
    scope = service.freeze_scope({
        "kind": "selected", "content_ids": [content.id], "material_scope": "full",
    })
    center = next(
        hit for hit in original_spans if hit.chunk_ordinal == 3
    )

    evidence = service._evidence([center], scope["content_ids"], scope["source_versions"])

    assert [item["chunk_ordinal"] for item in evidence] == [2, 3, 4]
    assert [item["source_refs"] for item in evidence] == [
        ["transcript:segment:2"], ["transcript:segment:3"], ["transcript:segment:4"],
    ]
    assert [item["retrieval_role"] for item in evidence] == [
        "adjacent_previous", "matched", "adjacent_next",
    ]
    assert [(item["start_seconds"], item["end_seconds"]) for item in evidence] == [
        (2, 4), (4, 6), (6, 8),
    ]
    prompt = json.loads(service._respond_prompt(
        "原文检索问题", {"answer_slots": []}, evidence, scope,
    ))
    assert [item["retrieval_role"] for item in prompt["evidence"]] == [
        "adjacent_previous", "matched", "adjacent_next",
    ]
    assert all(item["text"] for item in prompt["evidence"])


def test_retrieval_budget_scales_block_limits_by_task():
    lookup = _retrieval_budget({
        "task": "lookup", "granularity": "broad", "answer_slots": [{}],
    })
    comparison = _retrieval_budget({
        "task": "compare", "granularity": "mixed", "answer_slots": [{}, {}],
    })

    assert lookup["per_layer_block_limit"] < comparison["per_layer_block_limit"]
    assert lookup["merged_block_limit"] < comparison["merged_block_limit"]
    assert lookup["final_block_limit"] < comparison["final_block_limit"]
    assert lookup["per_content_block_limit"] <= comparison["per_content_block_limit"]


def test_routing_examples_select_or_skip_text_layers_and_preserve_unknown(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    service = RagService(store, AskIndex(store, tmp_path / "archives"))
    scope = {"content_set_id": "SET_ROUTE_CASES", "content_ids": ["content_a", "content_b"]}

    def actions(granularity, *, task="explain", slots=None):
        return service._deterministic_actions("question", {
            "task": task,
            "granularity": granularity,
            "answer_slots": slots or [],
            "protected_content_ids": [],
        }, scope)

    assert [item["tool"] for item in actions("broad")] == ["search_summaries"]
    assert [item["tool"] for item in actions("detail")] == ["search_original"]
    assert [item["tool"] for item in actions("mixed")] == [
        "search_summaries", "search_original",
    ]
    assert actions("metadata", task="count") == []
    assert _validate_scan({"items": [{
        "content_id": "content_a", "decision": "unknown", "evidence_ids": [],
    }]}, "content_a", set()) == ("unknown", [])


def test_final_evidence_quota_keeps_each_explicit_compare_target():
    contents = [f"content_{index}" for index in range(1, 9)]
    evidence = [{
        "id": f"hit_{content_index}_{chunk_index}",
        "content_id": f"content_{content_index}",
        "text": "证据",
    } for content_index in range(1, 9) for chunk_index in range(1, 5)]
    route = {
        "task": "compare", "granularity": "mixed", "answer_slots": [{}, {}],
        "protected_content_ids": [contents[-2], contents[-1]],
    }

    selected = _limit_evidence(evidence, route)
    content_counts = {}
    for item in selected:
        content_counts[item["content_id"]] = content_counts.get(item["content_id"], 0) + 1

    assert len(selected) == 24
    assert set(route["protected_content_ids"]) <= set(content_counts)
    assert max(content_counts.values()) <= 6


def test_final_prompt_budget_fairly_includes_all_six_compare_targets(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    service = RagService(store, AskIndex(store, tmp_path / "archives"))
    generator = OpenAICompatibleSummarizer(SummarySettings(
        api_url="https://example.test/compatible-mode/v1/responses", api_key="test-key",
        model="test-model", provider="openai-compatible", api_mode="responses",
    ))
    target_ids = [f"content_{index}" for index in range(6)]
    route = {"task": "compare", "answer_slots": [
        {"slot_id": "S1", "question": "比较甲乙", "required": True, "requires_original": False},
        {"slot_id": "S2", "question": "比较丙丁", "required": True, "requires_original": False},
    ]}
    evidence = [{
        "id": f"hit_{index}", "content_id": content_id, "title": f"材料{index}",
        "source_kind": "summary",
        "original_source_type": None, "source_ref": "summary:paragraph:1",
        "source_refs": ["summary:paragraph:1"], "chunk_ordinal": index,
        "retrieval_role": "matched", "start_seconds": None, "end_seconds": None,
        "source_version": "v1", "summary_strength": "standard", "material_level": "M2",
        "text": "甲方案处理内容。" * 500,
    } for index, content_id in enumerate(target_ids)]

    context = service._bounded_response_context(
        generator, "比较这六项材料", route, evidence, {"count": 6},
        max_input_bytes=10000, max_output_tokens=1800, required_content_ids=target_ids,
    )

    assert context is not None
    prompt, bounded, schema = context
    prompt_evidence = json.loads(prompt)["evidence"]
    assert {item["content_id"] for item in prompt_evidence} == set(target_ids)
    assert all(item["text"] for item in prompt_evidence)
    assert all(
        len(item["text"]) < len(evidence[index]["text"])
        and evidence[index]["text"].startswith(item["text"])
        for index, item in enumerate(prompt_evidence)
    )
    assert schema["$defs"]["evidence_id"]["enum"] == [item["id"] for item in bounded]
    assert generator.structured_json_request_bytes(
        prompt, schema, max_output_tokens=1800,
    ) <= 10000


def test_enumeration_prompt_fairly_splits_budget_across_materials(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    service = RagService(store, AskIndex(store, tmp_path / "archives"))
    generator = OpenAICompatibleSummarizer(SummarySettings(
        api_url="https://example.test/compatible-mode/v1/responses", api_key="test-key",
        model="test-model", provider="openai-compatible", api_mode="responses",
    ))
    content_ids = [f"content_{index}" for index in range(6)]
    route = {"task": "enumerate", "granularity": "broad", "answer_slots": [
        {"slot_id": "S1", "question": "列出相关资料", "required": True, "requires_original": False},
    ], "protected_content_ids": []}
    evidence = [{
        "id": f"hit_{index}", "content_id": content_id, "title": f"资料标题{index}",
        "source_kind": "summary", "original_source_type": None,
        "source_ref": "summary:paragraph:1", "source_refs": ["summary:paragraph:1"],
        "start_seconds": None, "end_seconds": None, "source_version": "v1",
        "summary_strength": "standard", "material_level": "M2",
        "chunk_ordinal": 0, "retrieval_role": "matched",
        "text": "前" * 595 + "检索增强生成" + "后" * 100,
    } for index, content_id in enumerate(content_ids)]

    context = service._bounded_response_context(
        generator, "哪些资料讲 RAG？", route, evidence, {"count": 6},
        max_input_bytes=10000, max_output_tokens=650,
    )

    assert context is not None
    prompt, bounded, schema = context
    prompt_data = json.loads(prompt)
    selected_ids = {item["content_id"] for item in prompt_data["evidence"]}
    assert len(selected_ids) >= 2
    assert selected_ids <= set(content_ids)
    assert all(item["title"] for item in prompt_data["evidence"])
    assert "chunk_text_offset_chars" in prompt_data["evidence_excerpt_note"]
    original_by_id = {item["content_id"]: item["text"] for item in evidence}
    for item in prompt_data["evidence"]:
        offset = item["chunk_text_offset_chars"]
        assert offset > 0
        assert "检索增强生成" in item["text"]
        assert original_by_id[item["content_id"]][offset:offset + len(item["text"])] == item["text"]
    byte_lengths = [len(item["text"].encode("utf-8")) for item in prompt_data["evidence"]]
    assert min(byte_lengths) > 0
    assert max(byte_lengths) - min(byte_lengths) <= 3
    assert generator.structured_json_request_bytes(
        prompt, schema, max_output_tokens=650,
    ) <= 15000
    assert len(bounded) == len(selected_ids)




def test_deterministic_search_actions_use_task_limits_and_preserve_targets():
    store = SQLiteStore("sqlite:///:memory:")
    service = RagService(store, AskIndex(store, "archives"))
    route = {
        "task": "compare", "granularity": "mixed", "answer_slots": [{}, {}],
        "protected_content_ids": ["content_a", "content_b"],
    }
    scope = {"content_set_id": "SET_COMPARE"}

    actions = service._deterministic_actions("比较内容", route, scope)

    assert actions[0]["args"]["top_k"] == 36
    assert actions[0]["args"]["max_per_content"] == 3
    assert actions[0]["args"]["preserve_content_ids"] == ["content_a", "content_b"]


def test_explicit_comparison_targets_are_selected_by_exact_scoped_title():
    question = "比较《甲方案》与乙方案的处理差异"

    assert _explicit_compare_content_ids(question, {
        "content_a": "甲方案", "content_b": "乙方案", "content_c": "未提及方案",
    }, ["content_a", "content_b", "content_c"]) == ["content_a", "content_b"]


def test_search_tool_preserves_explicit_compare_targets_and_reports_block_truncation():
    store = SQLiteStore("sqlite:///:memory:")
    first = store.create_content(kind=ContentKind.ARTICLE, title="比较甲", platform=SourcePlatform.LOCAL)
    second = store.create_content(kind=ContentKind.ARTICLE, title="比较乙", platform=SourcePlatform.LOCAL)
    index = AskIndex(store, "archives")
    service = RagService(store, index)
    scope = {"content_ids": [first.id, second.id], "content_set_id": "SET_COMPARE"}
    hits = [
        AskIndexHit(f"hit-{i}", first.id if i < 4 else second.id, "summary", "summary",
                    f"summary:paragraph:{i}", None, None, f"hash-{i}", f"证据{i}", float(i))
        for i in range(1, 5)
    ]

    def search_keyword(query, *, limit, content_ids, vector_covered_only=False, evidence_kind=None):
        return tuple(hit for hit in hits if hit.content_id in content_ids)[:limit]

    index.search_keyword = search_keyword
    result = service.execute_tool("search_summaries", {
        "query": "比较甲和比较乙", "content_set_id": "SET_COMPARE", "top_k": 2,
        "max_per_content": 1, "preserve_content_ids": [first.id, second.id],
    }, scope)

    assert {hit["content_id"] for hit in result["hits"]} == {first.id, second.id}
    assert result["retrieval_stats"] == {
        "scope_content_count": 2,
        "block_limit": 2,
        "per_content_block_limit": 1,
        "candidate_block_count": 2,
        "candidate_content_count": 2,
        "raw_candidate_block_count": 3,
        "truncated_by_block_limit": True,
        "truncated_by_per_content_limit": True,
        "explicit_target_count": 2,
        "explicit_target_hit_count": 2,
        "explicit_target_missing_count": 0,
    }


@pytest.mark.parametrize("tool,kind", [("search_summaries", "summary"), ("search_original", "asr")])
def test_single_document_search_does_not_default_to_two_blocks(tmp_path, monkeypatch, tool, kind):
    store = SQLiteStore("sqlite:///:memory:")
    index = AskIndex(store, tmp_path / "archives")
    service = RagService(store, index)
    scope = {"content_ids": ["content_a"], "content_set_id": "SET_ONE"}
    hits = tuple(
        AskIndexHit(f"hit-{i}", "content_a", kind, "summary",
                    f"section:{i}", None, None, f"hash-{i}", f"证据{i}", float(i))
        for i in range(1, 5)
    )
    monkeypatch.setattr(index, "search_keyword", lambda *args, **kwargs: hits[:kwargs["limit"]])
    result = service.execute_tool(tool, {"query": "文章讲什么", "content_set_id": "SET_ONE"}, scope)
    assert [item["hit_id"] for item in result["hits"]] == [hit.stable_id for hit in hits]
    assert result["retrieval_stats"]["per_content_block_limit"] == 20
    assert not result["retrieval_stats"]["truncated_by_per_content_limit"]
    explicit = service.execute_tool(tool, {
        "query": "文章讲什么", "content_set_id": "SET_ONE", "max_per_content": 2,
    }, scope)
    assert len(explicit["hits"]) == 2
    store.engine.dispose()


def test_rag_acronym_adds_scoped_chinese_lexical_search_without_replacing_query(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    index = AskIndex(store, tmp_path / "archives")
    service = RagService(store, index)

    def add_material(title, summary):
        content = store.create_content(
            kind=ContentKind.ARTICLE, title=title, platform=SourcePlatform.LOCAL,
        )
        transcript = Transcript("zh", "plain_text", "local", (
            TranscriptSegment(0, 2, "文章原文用于隔离原文检索。"),
        ))
        archive = _archive(tmp_path / "archives", content, transcript=transcript, summary=summary)
        index.sync_content(content.id, archive, summary_text=summary)
        return content

    irrelevant = add_material("人工智能概述", "材料介绍人工智能的发展。")
    relevant = add_material("检索方法", "本文介绍检索增强生成的流程。")
    outside_scope = add_material("范围外资料", "本文也介绍检索增强生成。")
    scope = {
        "content_ids": [irrelevant.id, relevant.id], "content_set_id": "SET_ALIAS",
        "count": 2, "material_scope": "full",
    }

    result = service.execute_tool("search_summaries", {
        "query": "哪些资料讲 RAG？", "content_set_id": scope["content_set_id"],
        "top_k": 28, "max_per_content": 3, "preserve_content_ids": [],
    }, scope)

    assert _retrieval_query_aliases("哪些资料讲 RAG？") == ("RAG", "检索增强生成")
    assert _retrieval_query_aliases("人工智能") == ()
    assert [item["content_id"] for item in result["hits"]] == [relevant.id]
    assert outside_scope.id not in {item["content_id"] for item in result["hits"]}
    assert result["retrieval_stats"]["lexical_aliases"] == [
        {"alias": "RAG", "hit_count": 0},
        {"alias": "检索增强生成", "hit_count": 1},
    ]




def _pin_test_evidence_versions(service, evidence, scope):
    versions = dict(scope.get("source_versions") or {})
    for item in evidence:
        versions.setdefault(item["content_id"], f"test-index-hash:{item['content_id']}")
        item["indexed_source_hash"] = versions[item["content_id"]]
    service.index.content_source_versions = lambda content_ids: {
        content_id: versions.get(content_id) for content_id in content_ids
    }
    return {**scope, "source_versions": versions}


def test_summary_strength_is_frozen_and_changes_prompt_detail():
    quick = AnalysisSettings(model="test", strength=SummaryStrength.QUICK)
    deep = AnalysisSettings(model="test", strength=SummaryStrength.DEEP)

    assert quick.as_dict()["strength"] == "quick"
    assert deep.as_dict()["strength"] == "deep"
    chunks = (Chunk(1, 0, 1, "材料正文", "hash", 2),)
    quick_input = _summary_input("标题", SummaryStrength.QUICK, chunks, None)
    deep_input = _summary_input("标题", SummaryStrength.DEEP, chunks, None)
    assert "覆盖材料主线" in quick_input
    assert "充分展开材料中的论证" in deep_input


def test_summary_versions_keep_strength_and_old_versions_remain_unknown():
    store = SQLiteStore("sqlite:///:memory:")
    content = store.create_content(
        kind=ContentKind.ARTICLE,
        title="强度版本",
        platform=SourcePlatform.LOCAL,
    )

    old = store.create_summary_version(
        content.id, "旧总结", template="general", origin="original"
    )
    new = store.create_summary_version(
        content.id,
        "详细总结",
        template="general",
        origin="original",
        summary_strength="deep",
        material_level="M2",
    )

    assert old.summary_strength is None
    assert new.summary_strength == "deep"
    assert new.material_level == "M2"


def test_ask_index_exposes_separate_summary_and_original_candidates(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    content = store.create_content(
        kind=ContentKind.VIDEO,
        title="分层索引",
        platform=SourcePlatform.BILIBILI,
        duration_seconds=60,
    )
    transcript = Transcript(
        "zh",
        "bilibili_subtitle",
        "bilibili",
        (TranscriptSegment(21, 23, "原文解释 RAG 切片参数为 512 Token。"),),
    )
    summary = "## 概览\n\nRAG 的检索与生成流程分为两个阶段。\n\n## 结论\n\n检索增强生成先找依据。"
    archive = _archive(
        tmp_path / "archives",
        content,
        transcript=transcript,
        summary=summary,
    )
    index = AskIndex(store, tmp_path / "archives")
    store.upsert_summary(content.id, summary)
    result = index.sync_content(content.id, archive, summary_text=summary)

    assert result.status == "indexed"
    summary_hits = index.search_keyword("RAG 检索生成", evidence_kind="summary")
    original_hits = index.search_keyword("RAG 切片参数", evidence_kind="original")
    assert summary_hits
    assert all(hit.source_kind == "summary" for hit in summary_hits)
    assert summary_hits[0].source_ref == "summary:paragraph:1"
    assert summary_hits[0].start_seconds is None
    assert original_hits
    assert all(hit.source_kind != "summary" for hit in original_hits)
    assert original_hits[0].source_ref == "transcript:segment:1"
    assert (original_hits[0].start_seconds, original_hits[0].end_seconds) == (21, 23)


def test_short_route_request_including_schema_fits_2400_bytes(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    service = RagService(store, AskIndex(store, tmp_path / "archives"))
    generator = OpenAICompatibleSummarizer(SummarySettings(
        api_url="https://example.test/v1/chat/completions",
        api_key="unused-test-key",
        model="test-route-model",
    ))
    scope = {
        "kind": "all", "content_set_id": "SET_123456789abc", "count": 25,
        "material_scope": "full",
    }

    prompt, clarification = service.build_route_prompt("RAG 的主要流程是什么？", scope, generator)

    actual_bytes = generator.structured_json_request_bytes(
        prompt, ROUTE_SCHEMA, max_output_tokens=700
    )
    assert clarification is None
    assert actual_bytes <= 2400


def test_full_scan_m1_negative_stays_unknown_but_summary_scan_is_exact(tmp_path):
    def run_scan(material_scope: str):
        store = SQLiteStore("sqlite:///:memory:")
        content = store.create_content(
            kind=ContentKind.ARTICLE,
            title="扫描范围材料",
            platform=SourcePlatform.LOCAL,
        )
        transcript = Transcript(
            "zh", "plain_text", "local", (TranscriptSegment(0, 2, "一段与问题无关的材料。"),)
        )
        summary = "## 概览\n\n总结没有讨论该语义条件。"
        archive = _archive(tmp_path / material_scope, content, transcript=transcript, summary=summary)
        store.upsert_summary(content.id, summary)
        store.create_summary_version(
            content.id, summary, template="general", origin="original",
            summary_strength="standard", material_level="M1", source_version="source-v1",
        )
        index = AskIndex(store, tmp_path / material_scope)
        index.sync_content(content.id, archive, summary_text=summary)
        service = RagService(store, index)
        scope = {
            "kind": "all", "content_set_id": "SET_SCAN", "count": 1,
            "content_ids": [content.id], "material_scope": material_scope,
        }
        session = service.rag_store.create_session("扫描", scope)
        query = service.rag_store.create_query(session["id"], "哪份材料讨论该语义条件？", scope)
        store.list_history = lambda **_kwargs: [SimpleNamespace(content=content)]
        captured_batches = []

        class NoMatchGenerator:
            settings = SimpleNamespace(model="test-scan-model")

            def structured_json_request_bytes(self, *_args, **_kwargs):
                return 900

            def complete_json(self, prompt, schema, **_kwargs):
                captured_batches.append((schema, json.loads(prompt)["items"][0]))
                return {"items": [{
                    "content_id": content.id, "decision": "no_match",
                    "evidence_ids": [],
                }]}, {"input_bytes": 900}

        result = service._semantic_scan(
            query["id"], query["question"], {"semantic_conditions": ["讨论该语义条件"]},
            scope, NoMatchGenerator(), {"calls": []}, monotonic(),
        )
        return result, captured_batches

    full_result, full_batches = run_scan("full")
    summary_result, summary_batches = run_scan("summaries")

    assert full_result["coverage"]["unknown"] == 1
    assert full_result["coverage"]["exact"] is False
    assert full_result["status"] == "partial"
    assert summary_result["coverage"]["unknown"] == 0
    assert summary_result["coverage"]["exact"] is True
    assert summary_result["status"] == "answer"
    for schema, batch in full_batches + summary_batches:
        item_list_schema = schema["properties"]["items"]
        item_schema = item_list_schema["items"]
        assert item_list_schema["minItems"] == item_list_schema["maxItems"] == 1
        assert item_schema["properties"]["content_id"]["enum"] == [batch["content_id"]]
        assert item_schema["properties"]["evidence_ids"]["items"]["enum"] == [
            evidence["id"] for evidence in batch["evidence"]
        ]


def test_scan_output_schema_omits_unused_reason_field():
    item_schema = SCAN_SCHEMA["properties"]["items"]["items"]

    assert "reason" not in item_schema["required"]
    assert "reason" not in item_schema["properties"]
    assert _validate_scan(
        {"items": [{"content_id": "content_1", "decision": "no_match", "evidence_ids": []}]},
        "content_1",
        set(),
    ) == ("no_match", [])


def test_route_prompt_has_no_completeness_key(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    service = RagService(store, AskIndex(store, tmp_path / "archives"))

    class PromptGenerator:
        def structured_json_request_bytes(self, *_args, **_kwargs):
            return 100

    prompt, clarification = service.build_route_prompt(
        "只要一条最相关证据，不要求穷尽全文。",
        {"kind": "selected", "content_set_id": "SET_SINGLE", "count": 1,
         "material_scope": "full"},
        PromptGenerator(),
    )

    assert clarification is None
    assert "a 只表示是否要穷尽当前范围" not in prompt
    assert "键 t/g/a/s/f" not in prompt
    assert "键 t/g/s/f" in prompt
    assert "a" not in ROUTE_SCHEMA["required"]
    assert "a" not in ROUTE_SCHEMA["properties"]
    with pytest.raises(ValueError):
        _validate_route(
            {"t": "explain", "g": "broad", "a": True,
             "s": [{"q": "资料", "r": True, "o": False}], "f": []},
            "资料",
        )


def test_route_prompt_distinguishes_document_discovery_from_source_detail(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    service = RagService(store, AskIndex(store, tmp_path / "archives"))
    generator = OpenAICompatibleSummarizer(SummarySettings(
        api_url="https://example.test/v1/chat/completions",
        api_key="unused-test-key",
        model="test-route-model",
    ))
    scope = {
        "kind": "all", "content_set_id": "SET_123456789abc", "count": 34,
        "material_scope": "full",
    }

    prompt, clarification = service.build_route_prompt("哪些资料讲 RAG？", scope, generator)

    assert clarification is None
    assert "哪些资料讲 X、列出相关资料”用 enumerate+broad" in prompt
    assert "概括资料用 synthesize+broad" in prompt
    assert "解释主题用 explain+broad" in prompt
    assert "只有明确询问对象间关系时用 relation" in prompt
    assert "原话、具体数值、单位、条件或参数用 detail 且答复点 o=true" in prompt
    assert "有哪些数字参数”用 enumerate+mixed" in prompt
    assert "只有问多少份或数量才用 count+metadata" in prompt
    assert generator.structured_json_request_bytes(
        prompt, ROUTE_SCHEMA, max_output_tokens=700,
    ) <= 2400


def test_route_shape_selects_summary_original_or_mixed_layers(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    service = RagService(store, AskIndex(store, tmp_path / "archives"))
    scope = {"content_set_id": "SET_ROUTE_SHAPES"}
    cases = [
        ({"t": "enumerate", "g": "broad",
          "s": [{"q": "相关资料", "r": True, "o": False}], "f": []},
         ["search_summaries"]),
        ({"t": "enumerate", "g": "mixed",
          "s": [{"q": "数字参数", "r": True, "o": False}], "f": []},
         ["search_summaries", "search_original"]),
        ({"t": "lookup", "g": "detail",
          "s": [{"q": "原文参数", "r": True, "o": True}], "f": []},
         ["search_original"]),
    ]

    for raw_route, expected_layers in cases:
        route = _validate_route(raw_route, "路由形状测试")
        actions = service._deterministic_actions("路由形状测试", route, scope)
        assert [action["tool"] for action in actions] == expected_layers










def test_qwen_responses_request_preserves_dynamic_rag_schema(monkeypatch, tmp_path):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b'{"output_text":"{}","usage":{}}'

    def fake_urlopen(request, *, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(openai_compatible, "urlopen", fake_urlopen)
    store = SQLiteStore("sqlite:///:memory:")
    service = RagService(store, AskIndex(store, tmp_path / "archives"))
    generator = OpenAICompatibleSummarizer(SummarySettings(
        api_url="https://example.test/compatible-mode/v1/responses", api_key="secret",
        model="qwen3.7-flash", provider="qwen", api_mode="responses",
    ))
    route = {"answer_slots": [
        {"slot_id": "S1", "question": "问题一", "required": True, "requires_original": False},
        {"slot_id": "S2", "question": "问题二", "required": True, "requires_original": False},
    ]}
    evidence = [
        {"id": "hit_1", "content_id": "content_1", "title": "材料一", "source_kind": "original",
         "original_source_type": "transcript", "source_ref": "segment:1", "start_seconds": 0,
         "end_seconds": 1, "source_version": "v1", "summary_strength": "standard",
         "material_level": "M2", "text": "依据一。"},
        {"id": "hit_2", "content_id": "content_1", "title": "材料一", "source_kind": "original",
         "original_source_type": "transcript", "source_ref": "segment:2", "start_seconds": 1,
         "end_seconds": 2, "source_version": "v1", "summary_strength": "standard",
         "material_level": "M2", "text": "依据二。"},
    ]
    context = service._bounded_response_context(
        generator, "问题一和问题二", route, evidence, {"count": 1},
        max_input_bytes=10000, max_output_tokens=900,
    )
    assert context is not None
    prompt, _bounded, schema = context

    generator.complete_json(prompt, schema, timeout=7, max_output_tokens=900)

    body = captured["body"]
    sent_format = body["text"]["format"]
    assert sent_format["strict"] is True
    assert sent_format["schema"] == schema
    assert "slots" in sent_format["schema"]["required"]
    assert sent_format["schema"]["properties"]["slots"]["minItems"] == 2
    assert sent_format["schema"]["properties"]["slots"]["items"]["properties"]["evidence"]["items"]["properties"]["id"] == {
        "$ref": "#/$defs/evidence_id",
    }
    assert body["reasoning"] == {"effort": "none"}
    assert body["temperature"] == 0


def test_response_context_keeps_later_hits_and_verifies_quotes_after_twelfth_sentence(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    service = RagService(store, AskIndex(store, tmp_path / "archives"))
    generator = OpenAICompatibleSummarizer(SummarySettings(
        api_url="https://example.test/compatible-mode/v1/responses", api_key="secret",
        model="qwen3.7-flash", provider="qwen", api_mode="responses",
    ))
    route = {"answer_slots": [
        {"slot_id": "S1", "question": "比较依据", "required": True, "requires_original": False},
    ]}
    sentences = [f"第{i}句比较证据。" for i in range(1, 15)]
    later_sentence = "后续命中仍可引用的明确比较对象。"
    evidence = [
        {"id": "hit_1", "content_id": "content_1", "title": "材料", "source_kind": "original",
         "original_source_type": "transcript", "source_ref": "segment:1", "start_seconds": 0,
         "end_seconds": 1, "source_version": "v1", "summary_strength": "standard",
         "material_level": "M2", "text": "".join(sentences)},
        {"id": "hit_2", "content_id": "content_1", "title": "材料", "source_kind": "original",
         "original_source_type": "transcript", "source_ref": "segment:2", "start_seconds": 1,
         "end_seconds": 2, "source_version": "v1", "summary_strength": "standard",
         "material_level": "M2", "text": later_sentence},
    ]

    context = service._bounded_response_context(
        generator, "比较依据", route, evidence, {"count": 1},
        max_input_bytes=10000, max_output_tokens=900,
    )
    assert context is not None
    prompt, bounded, schema = context

    assert [item["id"] for item in bounded] == ["hit_1", "hit_2"]
    prompt_evidence = json.loads(prompt)["evidence"]
    assert sentences[12] in prompt_evidence[0]["text"]
    assert later_sentence in prompt_evidence[1]["text"]
    assert "quote" not in schema.get("$defs", {})
    assert schema["properties"]["slots"]["items"]["properties"]["evidence"]["items"]["properties"]["id"] == {
        "$ref": "#/$defs/evidence_id",
    }

    response = {
        "slots": [{"slot_id": "S1", "score": 2, "answer": "第13句与后续对象可以共同支撑比较。",
                   "evidence": [{"id": "hit_1", "quote": sentences[12]},
                                {"id": "hit_2", "quote": later_sentence}], "missing": []}],
        "actions": [],
    }
    scope = _pin_test_evidence_versions(service, bounded, {"count": 1})
    result = service._validate_response(response, route, bounded, scope, {})

    assert result["status"] == "answer"
    assert result["answer"] == "第13句与后续对象可以共同支撑比较。"
    assert len(result["citations"]) == 2


def test_strict_output_key_error_trace_uses_safe_code_and_fields():
    try:
        _strict_keys({"decision": "answer"}, {"slots", "decision"})
    except ValueError as error:
        assert _exception_trace(error) == {
            "error_type": "ValueError",
            "error_code": "RAG_STRUCTURED_OUTPUT_FIELDS_INVALID",
            "missing_fields": ["slots"],
            "extra_fields": [],
        }
    else:
        raise AssertionError("missing structured output field must be rejected")


def test_response_program_builds_partial_answer_and_uncovered_slots(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    service = RagService(store, AskIndex(store, tmp_path / "archives"))
    route = {"answer_slots": [
        {"slot_id": "S1", "question": "问题一", "required": True, "requires_original": False},
        {"slot_id": "S2", "question": "问题二", "required": True, "requires_original": False},
    ]}
    evidence = [
        {"id": "hit_1", "content_id": "content_1", "title": "材料", "source_kind": "original",
         "original_source_type": "transcript", "source_ref": "segment:1", "start_seconds": 0,
         "end_seconds": 1, "summary_strength": "standard", "material_level": "M2", "text": "依据一"},
        {"id": "hit_2", "content_id": "content_1", "title": "材料", "source_kind": "original",
         "original_source_type": "transcript", "source_ref": "segment:2", "start_seconds": 1,
         "end_seconds": 2, "summary_strength": "standard", "material_level": "M2", "text": "依据二"},
    ]
    response = {
        "slots": [
            {"slot_id": "S1", "score": 2, "answer": "问题一的回答。",
             "evidence": [{"id": "hit_1", "quote": "依据一"}], "missing": []},
            {"slot_id": "S2", "score": 1, "answer": "", "evidence": [], "missing": ["具体条件"]},
        ],
        "actions": [],
    }

    scope = _pin_test_evidence_versions(service, evidence, {})
    result = service._validate_response(response, route, evidence, scope, {})

    assert result["status"] == "partial"
    assert result["uncovered"] == ["问题二：具体条件"]
    assert result["answer"] == "问题一的回答。"
    assert result["answer_segments"] == [{"slot_id": "S1", "text": "问题一的回答。", "evidence_ids": ["hit_1"]}]
    assert len(result["citations"]) == 1


def test_response_includes_verified_original_quote_with_model_explanation(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    service = RagService(store, AskIndex(store, tmp_path / "archives"))
    route = {"answer_slots": [
        {"slot_id": "S1", "question": "原文句子", "required": True, "requires_original": True},
    ]}
    evidence = [{"id": "hit_1", "content_id": "content_1", "title": "材料",
                 "source_kind": "original", "original_source_type": "transcript",
                 "source_ref": "segment:1", "start_seconds": 0, "end_seconds": 1,
                 "summary_strength": "standard", "material_level": "M2", "text": "原文中的连续句子。"}]
    response = {"slots": [
        {"slot_id": "S1", "score": 2, "answer": "这句话说明了材料采用的处理方式。",
         "evidence": [{"id": "hit_1", "quote": "原文中的连续句子。"}], "missing": []},
    ], "actions": []}

    scope = _pin_test_evidence_versions(service, evidence, {"count": 1})
    result = service._validate_response(response, route, evidence, scope, {})

    assert result["status"] == "answer"
    assert result["answer_segments"] == [{
        "slot_id": "S1", "text": "原文：“原文中的连续句子。”\n说明：这句话说明了材料采用的处理方式。",
        "evidence_ids": ["hit_1"],
    }]
    assert result["answer"] == result["answer_segments"][0]["text"]
    assert len(result["citations"]) == 1


def test_response_validates_index_hash_separately_from_summary_source_version(tmp_path):
    _, content, _, _, index, service, scope, evidence = _versioned_original_evidence(tmp_path)
    route = {"answer_slots": [
        {"slot_id": "S1", "question": "版本A原文", "required": True, "requires_original": True},
    ]}
    response = {"slots": [
        {"slot_id": "S1", "score": 2, "answer": "原文说明了先检查材料、再生成回答。",
         "evidence": [{"id": evidence[0]["id"], "quote": evidence[0]["text"]}], "missing": []},
    ], "actions": []}
    index_hash = scope["source_versions"][content.id]
    assert evidence[0]["source_version"] == "transcript-v1"
    assert evidence[0]["source_version"] != index_hash
    assert evidence[0]["indexed_source_hash"] == index_hash

    trace = {}
    result = service._validate_response(response, route, evidence, scope, trace)

    assert result["status"] == "answer"
    assert result["citations"][0]["id"] == evidence[0]["id"]
    assert trace["evidence_version_validation"] == {
        "status": "ok", "phase": "respond_validation", "checked_content_count": 1,
    }


def test_response_rejects_evidence_from_a_changed_frozen_index_version(tmp_path):
    _, content, archive, summary, index, service, scope, evidence = _versioned_original_evidence(tmp_path)
    route = {"answer_slots": [
        {"slot_id": "S1", "question": "版本A原文", "required": True, "requires_original": True},
    ]}
    response = {"slots": [
        {"slot_id": "S1", "score": 2, "answer": "原文说明了处理顺序。",
         "evidence": [{"id": evidence[0]["id"], "quote": evidence[0]["text"]}], "missing": []},
    ], "actions": []}
    index.sync_content(content.id, archive, summary_text=f"{summary} 新版本补充。")

    with pytest.raises(ValueError, match="证据版本与冻结范围不一致"):
        service._validate_response(response, route, evidence, scope, {})








def test_response_without_supported_slots_returns_insufficient(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    service = RagService(store, AskIndex(store, tmp_path / "archives"))
    route = {"answer_slots": [
        {"slot_id": "S1", "question": "准确参数是多少？", "required": True, "requires_original": True},
    ]}
    response = {"slots": [
        {"slot_id": "S1", "score": 0, "answer": "", "evidence": [], "missing": ["原文未提供"]},
    ], "actions": []}

    result = service._validate_response(response, route, [], {"count": 1}, {})

    assert result["status"] == "insufficient"
    assert result["answer"] == ""
    assert result["citations"] == []
    assert result["uncovered"] == ["准确参数是多少？：原文未提供"]


def test_response_conflict_is_not_presented_as_supported(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    service = RagService(store, AskIndex(store, tmp_path / "archives"))
    route = {"answer_slots": [
        {"slot_id": "S1", "question": "哪个参数适用？", "required": True, "requires_original": True},
    ]}
    evidence = [
        {"id": "hit_1", "content_id": "content_1", "source_kind": "original",
         "source_ref": "segment:1", "start_seconds": 0, "end_seconds": 1,
         "summary_strength": "standard", "material_level": "M2", "text": "参数为 20。"},
        {"id": "hit_2", "content_id": "content_1", "source_kind": "original",
         "source_ref": "segment:2", "start_seconds": 1, "end_seconds": 2,
         "summary_strength": "standard", "material_level": "M2", "text": "参数为 30。"},
    ]
    response = {"slots": [
        {"slot_id": "S1", "score": 1, "answer": "", "evidence": [
            {"id": "hit_1", "quote": "参数为 20。"}, {"id": "hit_2", "quote": "参数为 30。"},
        ], "missing": ["材料对参数存在冲突"]},
    ], "actions": []}

    result = service._validate_response(response, route, evidence, {"count": 1}, {})

    assert result["status"] == "insufficient"
    assert result["answer"] == ""
    assert result["citations"] == []
    assert result["answer_slots"][0]["score"] == 1
    assert result["answer_slots"][0]["missing"] == ["材料对参数存在冲突"]


def test_response_requests_bounded_supplement_for_an_unsupported_point(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    service = RagService(store, AskIndex(store, tmp_path / "archives"))
    route = {"answer_slots": [
        {"slot_id": "S1", "question": "流程是什么？", "required": True, "requires_original": False},
        {"slot_id": "S2", "question": "精确参数是多少？", "required": True, "requires_original": True},
    ]}
    evidence = [{"id": "hit_1", "content_id": "content_1", "title": "材料",
                 "source_kind": "original", "original_source_type": "transcript",
                 "source_ref": "segment:1", "start_seconds": 0, "end_seconds": 1,
                 "summary_strength": "standard", "material_level": "M2", "text": "流程包含检索和生成。"}]
    response = {
        "slots": [
            {"slot_id": "S1", "score": 2, "answer": "流程包含检索和生成。",
             "evidence": [{"id": "hit_1", "quote": "流程包含检索和生成。"}], "missing": []},
            {"slot_id": "S2", "score": 1, "answer": "", "evidence": [], "missing": ["参数值"]},
        ],
        "actions": [{"tool": "search_original", "slot_id": "S2", "query": "精确参数及单位"}],
    }

    scope = _pin_test_evidence_versions(
        service, evidence, {"content_set_id": "SET_RAG", "count": 1},
    )
    result = service._validate_response(response, route, evidence, scope, {})

    assert result["status"] == "supplement"
    assert result["answer"] == ""
    assert result["citations"] == []
    assert result["support_candidate"]["answer_segments"] == [
        {"slot_id": "S1", "text": "流程包含检索和生成。", "evidence_ids": ["hit_1"]},
    ]
    assert result["supplement_actions"] == [{
        "tool": "search_original", "slot_id": "S2", "args": {
            "query": "精确参数及单位", "content_set_id": "SET_RAG", "top_k": 24,
            "max_per_content": 3, "preserve_content_ids": [],
        },
    }]
    support_segments = result["support_candidate"]["answer_segments"]
    partial = _supplement_exhausted(result, result["support_candidate"], "预算已用尽")
    assert partial["status"] == "partial"
    assert partial["answer_segments"] == support_segments


def test_response_rejects_evidence_id_outside_current_results(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    service = RagService(store, AskIndex(store, tmp_path / "archives"))
    route = {"answer_slots": [
        {"slot_id": "S1", "question": "问题一", "required": True, "requires_original": False},
    ]}
    evidence = [{"id": "hit_1", "content_id": "content_1", "source_kind": "original",
                 "source_ref": "segment:1", "start_seconds": 0, "end_seconds": 1,
                 "summary_strength": "standard", "material_level": "M2", "text": "依据一"}]
    response = {"slots": [
        {"slot_id": "S1", "score": 2, "answer": "答案一。",
         "evidence": [{"id": "forged", "quote": "依据一"}], "missing": []},
    ], "actions": []}

    with pytest.raises(ValueError) as error:
        service._validate_response(response, route, evidence, {}, {})
    assert str(error.value) == "P-RESPOND 引用了范围外或伪造的依据 ID"


def test_response_rejects_quote_not_bound_to_its_evidence_id(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    service = RagService(store, AskIndex(store, tmp_path / "archives"))
    route = {"answer_slots": [
        {"slot_id": "S1", "question": "问题一", "required": True, "requires_original": False},
    ]}
    evidence = [
        {"id": "hit_1", "content_id": "content_1", "source_kind": "original",
         "source_ref": "segment:1", "start_seconds": 0, "end_seconds": 1,
         "summary_strength": "standard", "material_level": "M2", "text": "依据一"},
        {"id": "hit_2", "content_id": "content_1", "source_kind": "original",
         "source_ref": "segment:2", "start_seconds": 1, "end_seconds": 2,
         "summary_strength": "standard", "material_level": "M2", "text": "依据二"},
    ]
    response = {"slots": [
        {"slot_id": "S1", "score": 2, "answer": "答案一。",
         "evidence": [{"id": "hit_1", "quote": "依据二"}], "missing": []},
    ], "actions": []}

    with pytest.raises(ValueError) as error:
        service._validate_response(response, route, evidence, {}, {})
    assert str(error.value) == "P-RESPOND 短引文未匹配绑定的保存文本"


@pytest.mark.parametrize(("field", "value", "path", "observed_length", "limit"), [
    ("answer", "x" * 1601, "slots[0].answer", 1601, 1600),
    ("evidence", [{}] * 13, "slots[0].evidence", 13, 12),
])
def test_response_capacity_failure_records_only_safe_field_dimensions(
    tmp_path, field, value, path, observed_length, limit,
):
    store = SQLiteStore("sqlite:///:memory:")
    service = RagService(store, AskIndex(store, tmp_path / "archives"))
    route = {"answer_slots": [
        {"slot_id": "S1", "question": "问题一", "required": True, "requires_original": False},
    ]}
    slot = {"slot_id": "S1", "score": 0, "answer": "", "evidence": [], "missing": []}
    slot[field] = value

    with pytest.raises(ValueError) as error:
        service._validate_response({"slots": [slot], "actions": []}, route, [], {}, {})

    diagnostic = _exception_trace(error.value)
    assert diagnostic == {
        "error_type": "ValueError",
        "error_code": "RAG_RESPOND_FIELD_CAPACITY",
        "structure_path": path,
        "observed_type": "str" if field != "evidence" else "list",
        "observed_length": observed_length,
        "capacity_limit": limit,
    }
    assert "x" not in json.dumps(diagnostic)


def test_long_missing_detail_is_normalized_without_promoting_answer(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    service = RagService(store, AskIndex(store, tmp_path / "archives"))
    route = {"task": "enumerate", "answer_slots": [
        {"slot_id": "S1", "question": "列出相关资料", "required": True, "requires_original": False},
    ]}
    long_reason = "private diagnostic text " * 8
    response = {"slots": [
        {"slot_id": "S1", "score": 1, "answer": "", "evidence": [], "missing": [long_reason]},
    ], "actions": []}
    trace = {}

    result = service._validate_response(response, route, [], {"count": 34}, trace)

    assert result["status"] == "insufficient"
    assert result["answer"] == ""
    assert result["citations"] == []
    assert result["answer_slots"][0]["score"] == 1
    assert result["answer_slots"][0]["missing"] == ["证据不足"]
    assert trace["respond_field_normalizations"] == [{
        "path": "slots[0].missing[0]", "observed_length": len(long_reason),
        "capacity_limit": 120, "replacement": "evidence_insufficient",
    }]
    assert long_reason not in json.dumps(trace, ensure_ascii=False)


def test_enumerate_maps_titles_only_from_validated_evidence_and_dedupes(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    service = RagService(store, AskIndex(store, tmp_path / "archives"))
    route = {"task": "enumerate", "answer_slots": [
        {"slot_id": "S1", "question": "列出相關資料", "required": True, "requires_original": False},
    ]}
    evidence = [
        {"id": "hit_1", "content_id": "content_1", "title": "资料甲", "source_kind": "summary",
         "original_source_type": None, "source_ref": "summary:paragraph:1", "source_refs": ["summary:paragraph:1"],
         "start_seconds": None, "end_seconds": None, "source_version": "v1", "indexed_source_hash": "v1",
         "summary_strength": "standard", "material_level": "M2", "chunk_ordinal": 0,
         "chunk_text_offset_chars": 12,
         "text": "x" * 12 + "RAG 通过检索材料生成回答。"},
        {"id": "hit_2", "content_id": "content_1", "title": "资料甲", "source_kind": "summary",
         "original_source_type": None, "source_ref": "summary:paragraph:2", "source_refs": ["summary:paragraph:2"],
         "start_seconds": None, "end_seconds": None, "source_version": "v1", "indexed_source_hash": "v1",
         "summary_strength": "standard", "material_level": "M2", "chunk_ordinal": 1,
         "text": "RAG 的检索结果用于生成。"},
        {"id": "hit_3", "content_id": "content_2", "title": "资料乙", "source_kind": "summary",
         "original_source_type": None, "source_ref": "summary:paragraph:1", "source_refs": ["summary:paragraph:1"],
         "start_seconds": None, "end_seconds": None, "source_version": "v2", "indexed_source_hash": "v2",
         "summary_strength": "standard", "material_level": "M2", "chunk_ordinal": 0,
         "text": "RAG 使用向量检索定位相关内容。"},
    ]
    service.index.content_source_versions = lambda _content_ids: {"content_1": "v1", "content_2": "v2"}
    response = {"slots": [
        {"slot_id": "S1", "score": 2, "answer": "模型生成的资料清单。", "evidence": [
            {"id": "hit_1", "quote": "RAG 通过检索材料生成回答。"},
            {"id": "hit_2", "quote": "RAG 的检索结果用于生成。"},
            {"id": "hit_3", "quote": "RAG 使用向量检索定位相关内容。"},
        ], "missing": []},
    ], "actions": []}

    result = service._validate_response(response, route, evidence, {
        "count": 34, "content_ids": ["content_1", "content_2"],
        "source_versions": {"content_1": "v1", "content_2": "v2"},
    }, {})

    assert result["status"] == "answer"
    assert result["answer"] == "已核验的相关资料：\n- 资料甲\n- 资料乙"
    assert result["answer_segments"][0]["evidence_ids"] == ["hit_1", "hit_3"]
    assert [item["title"] for item in result["citations"]] == ["资料甲", "资料乙"]
    assert result["citations"][0]["chunk_text_offset_chars"] == 12
    assert result["citations"][0]["text"][12:].startswith("RAG")
    assert result["trace"]["enumeration_validation"] == {
        "status": "evidence_mapped", "accepted_title_count": 2, "accepted_evidence_count": 2,
    }


def test_response_does_not_score_summary_as_original_evidence(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    service = RagService(store, AskIndex(store, tmp_path / "archives"))
    route = {"answer_slots": [
        {"slot_id": "S1", "question": "准确原话是什么？", "required": True, "requires_original": True},
    ]}
    evidence = [{"id": "hit_1", "content_id": "content_1", "source_kind": "summary",
                 "source_ref": "summary:paragraph:1", "start_seconds": None, "end_seconds": None,
                 "summary_strength": "deep", "material_level": "M2", "text": "总结里的改写。"}]
    response = {"slots": [
        {"slot_id": "S1", "score": 2, "answer": "总结里的改写。",
         "evidence": [{"id": "hit_1", "quote": "总结里的改写。"}], "missing": []},
    ], "actions": []}

    result = service._validate_response(response, route, evidence, {"count": 1}, {})

    assert result["status"] == "insufficient"
    assert result["answer"] == ""
    assert result["citations"] == []
    assert result["answer_slots"][0]["score"] == 1




def test_internal_tag_lifecycle_deduplicates_reviews_merges_safely_and_withdraws_deleted_edges(tmp_path):
    from datetime import timedelta

    from sqlalchemy import select

    from app.db.models import ContentRagDetailTagRow, RagDetailTagRow

    store = SQLiteStore("sqlite:///:memory:")
    service = RagService(store, AskIndex(store, tmp_path / "archives"))
    contents = [
        store.create_content(kind=ContentKind.ARTICLE, title=f"材料{i}", platform=SourcePlatform.LOCAL)
        for i in range(2)
    ]
    material_evidence = [{
        "content_id": item.id,
        "source_refs": ["summary:paragraph:1"],
        "source_version": "v1",
        "text": f"支持细标签的材料 {item.id}",
    } for item in contents]
    user_tag = store.create_tag("用户标签")
    store.update_content(contents[0].id, tag_ids=[user_tag.id])
    scope = {"kind": "selected", "content_ids": [item.id for item in contents],
             "content_set_id": "SET_TAG", "count": 2, "material_scope": "full"}
    session = service.rag_store.create_session("细词生命周期", scope)
    queries = [
        service.rag_store.create_query(session["id"], f"问题{i}", scope)
        for i in range(2)
    ]
    tag = service.rag_store.upsert_detail_tag(
        name="证据链", definition="按来源追踪论据", content_id=contents[0].id,
        topic_ids=["T11"], source_refs=["summary:paragraph:1"], source_version="v1",
    )
    for content in contents[1:]:
        service.rag_store.upsert_detail_tag(
            name="证据链", definition="按来源追踪论据", content_id=content.id,
            topic_ids=["T11"], source_refs=["summary:paragraph:1"], source_version="v1",
        )

    assert service.rag_store.record_tag_feedback(
        query_id=queries[0]["id"], content_id=contents[0].id, tag_id=tag["id"], helpful=True,
    ) is True
    assert service.rag_store.record_tag_feedback(
        query_id=queries[0]["id"], content_id=contents[0].id, tag_id=tag["id"], helpful=True,
    ) is False
    assert service.rag_store.record_tag_feedback(
        query_id=queries[1]["id"], content_id=contents[1].id, tag_id=tag["id"], helpful=True,
    ) is True
    assert service.rag_store.promote_eligible_tags() == []
    assert service.rag_store.review_tag_candidate(
        tag["id"], source_supported=True,
        verified_content_ids=[item.id for item in contents], same_concept=False,
    ) is True
    assert service.rag_store.promote_eligible_tags() == []
    approval = service.rag_store.review_developer_candidate(
        tag["id"], decision="approved", note="来源与定义已核对",
        material_evidence=material_evidence,
    )
    assert approval["decision"] == "approved"
    assert service.rag_store.promote_eligible_tags() == [tag["id"]]
    audit = service.rag_store.list_developer_tag_reviews(tag["id"])
    assert audit[-1]["candidate_name"] == "证据链"
    assert audit[-1]["material_evidence"][0]["text"].startswith("支持细标签的材料")
    assert service.rag_store.record_tag_feedback(
        query_id=queries[1]["id"], content_id=contents[0].id, tag_id=tag["id"], helpful=True,
    ) is True

    canonical = service.rag_store.upsert_detail_tag(
        name="RAG", definition="检索后生成", content_id=contents[0].id,
        topic_ids=["T11"], source_refs=["summary:paragraph:1"], source_version="v1",
    )
    with store.session_factory.begin() as db:
        db.get(RagDetailTagRow, canonical["id"]).status = "active"
        link = db.execute(select(ContentRagDetailTagRow).where(
            ContentRagDetailTagRow.content_id == contents[0].id,
            ContentRagDetailTagRow.tag_id == canonical["id"],
        )).scalar_one()
        link.status = "active"
    synonym = service.rag_store.upsert_detail_tag(
        name="检索增强生成", definition="RAG 的中文名称", content_id=contents[0].id,
        topic_ids=["T11"], source_refs=["summary:paragraph:1"], source_version="v1",
    )
    service.rag_store.upsert_detail_tag(
        name="检索增强生成", definition="RAG 的中文名称", content_id=contents[1].id,
        topic_ids=["T11"], source_refs=["summary:paragraph:1"], source_version="v1",
    )
    for query, content in zip(queries, contents, strict=True):
        service.rag_store.record_tag_feedback(
            query_id=query["id"], content_id=content.id, tag_id=synonym["id"], helpful=True,
        )
    assert service.rag_store.review_tag_candidate(
        synonym["id"], source_supported=True,
        verified_content_ids=[item.id for item in contents], same_concept=True,
        canonical_tag_id=canonical["id"],
    ) is True
    canonical_before_approval = next(
        item for item in service.rag_store.list_detail_tags()
        if item["id"] == canonical["id"]
    )
    assert synonym["name"] not in canonical_before_approval["aliases"]
    service.rag_store.review_developer_candidate(
        synonym["id"], decision="approved", note="建议合并已核实",
        material_evidence=material_evidence,
    )

    related = service.rag_store.upsert_detail_tag(
        name="GraphRAG", definition="图增强检索方法", content_id=contents[0].id,
        topic_ids=["T11"], source_refs=["summary:paragraph:1"], source_version="v1",
    )
    service.rag_store.upsert_detail_tag(
        name="GraphRAG", definition="图增强检索方法", content_id=contents[1].id,
        topic_ids=["T11"], source_refs=["summary:paragraph:1"], source_version="v1",
    )
    for query, content in zip(queries, contents, strict=True):
        service.rag_store.record_tag_feedback(
            query_id=query["id"], content_id=content.id, tag_id=related["id"], helpful=True,
        )
    assert service.rag_store.review_tag_candidate(
        related["id"], source_supported=True,
        verified_content_ids=[item.id for item in contents], same_concept=False,
    ) is True
    service.rag_store.review_developer_candidate(
        related["id"], decision="rejected", note="概念范围仍有差异",
        material_evidence=material_evidence,
    )
    tags = {item["id"]: item for item in service.rag_store.list_detail_tags()}
    assert tags[synonym["id"]]["status"] == "merged"
    assert tags[related["id"]]["status"] == "candidate"
    assert "GraphRAG" not in tags[canonical["id"]]["aliases"]
    assert service.rag_store.list_developer_tag_reviews(related["id"])[-1]["decision"] == "rejected"

    unsupported = service.rag_store.upsert_detail_tag(
        name="无依据", definition="没有可用来源", content_id=contents[0].id,
        topic_ids=[], source_refs=["summary:paragraph:1"], source_version="v1",
    )
    service.rag_store.upsert_detail_tag(
        name="无依据", definition="没有可用来源", content_id=contents[1].id,
        topic_ids=[], source_refs=["summary:paragraph:1"], source_version="v1",
    )
    with store.session_factory.begin() as db:
        for link in db.execute(select(ContentRagDetailTagRow).where(
            ContentRagDetailTagRow.tag_id == unsupported["id"],
        )).scalars():
            link.source_refs = []
    assert service.rag_store.review_tag_candidate(
        unsupported["id"], source_supported=True,
        verified_content_ids=[item.id for item in contents], same_concept=False,
    ) is False

    with store.session_factory.begin() as db:
        active = db.get(RagDetailTagRow, canonical["id"])
        active.last_qualified_query_at = datetime.now(UTC) - timedelta(days=91)
    assert canonical["id"] not in {item["id"] for item in service.rag_store.list_detail_tags(active_only=True)}
    assert service.rag_store.record_tag_feedback(
        query_id=queries[0]["id"], content_id=contents[0].id,
        tag_id=canonical["id"], helpful=True,
    ) is True
    assert canonical["id"] in {item["id"] for item in service.rag_store.list_detail_tags(active_only=True)}

    capacity_tag = service.rag_store.upsert_detail_tag(
        name="容量暂停", definition="容量测试候选", content_id=contents[0].id,
        topic_ids=[], source_refs=["summary:paragraph:1"], source_version="v1",
    )
    service.rag_store.upsert_detail_tag(
        name="容量暂停", definition="容量测试候选", content_id=contents[1].id,
        topic_ids=[], source_refs=["summary:paragraph:1"], source_version="v1",
    )
    service.rag_store.record_tag_feedback(
        query_id=queries[0]["id"], content_id=contents[0].id,
        tag_id=capacity_tag["id"], helpful=True,
    )
    service.rag_store.record_tag_feedback(
        query_id=queries[1]["id"], content_id=contents[1].id,
        tag_id=capacity_tag["id"], helpful=True,
    )
    service.rag_store.review_tag_candidate(
        capacity_tag["id"], source_supported=True,
        verified_content_ids=[item.id for item in contents], same_concept=False,
    )
    service.rag_store.review_developer_candidate(
        capacity_tag["id"], decision="approved", material_evidence=material_evidence,
    )
    now = datetime.now(UTC)
    with store.session_factory.begin() as db:
        db.add_all(RagDetailTagRow(
            id=f"capacity-{number}", display_name=f"C{number:04d}",
            normalized_name=f"capacity{number}", short_definition="容量占位", aliases=[],
            status="active", extractor_model=None, prompt_version=None, source_reviewed=True,
            redirected_to=None, review_trace=None, last_qualified_query_at=now, created_at=now,
        ) for number in range(1000))
    assert capacity_tag["id"] not in service.rag_store.promote_eligible_tags()

    service.rag_store.replace_topics(
        contents[0].id, source_version="v1", material_level="M2",
        topics=[{"topic_id": "T11", "source_refs": ["summary:paragraph:1"]}],
        source_refs=["summary:paragraph:1"],
    )
    service.rag_store.invalidate_content(contents[0].id)
    with store.session_factory() as db:
        rows = db.execute(select(ContentRagDetailTagRow).where(
            ContentRagDetailTagRow.content_id == contents[0].id,
        )).scalars().all()
    assert rows and all(item.status == "invalid" for item in rows)
    assert store.tag_ids(contents[0].id) == [user_tag.id]
    assert service.rag_store.get_coverage(contents[0].id)["status"] == "source_missing"






def test_semantic_scan_with_unavailable_index_cannot_use_retained_old_chunks(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    index = AskIndex(store, tmp_path / "archives")
    content = store.create_content(kind=ContentKind.ARTICLE, title="索引失败", platform=SourcePlatform.LOCAL)
    sentence = "旧索引中仍可能留有正文块。"
    transcript = Transcript("zh", "plain_text", "local", (TranscriptSegment(0, 2, sentence),))
    archive = _archive(tmp_path / "archives", content, transcript=transcript, summary=sentence)
    store.upsert_summary(content.id, sentence)
    store.create_summary_version(
        content.id, sentence, template="general", origin="original",
        summary_strength="standard", material_level="M2", source_version="v1",
    )
    index.sync_content(content.id, archive, summary_text=sentence)
    service = RagService(store, index)
    store.list_history = lambda **_kwargs: [SimpleNamespace(content=content)]
    scope = service.freeze_scope({"kind": "selected", "content_ids": [content.id]})
    index.record_failure(content.id, "test_index_failure")
    refreshed = service.refresh_scope_material_versions(scope)
    session = service.rag_store.create_session("索引失败", refreshed)
    query = service.rag_store.create_query(session["id"], "旧索引是否还在？", refreshed)

    class NoCallGenerator:
        settings = SimpleNamespace(model="must-not-run")

        def complete_json(self, *_args, **_kwargs):
            raise AssertionError("不可用索引的旧块不能进入 P-SCAN")

    result = service._semantic_scan(
        query["id"], query["question"], {"semantic_conditions": ["旧索引"]},
        refreshed, NoCallGenerator(), {"calls": []}, monotonic(),
    )

    assert result["status"] == "partial"
    assert result["coverage"]["exact"] is False
    assert result["coverage"]["unknown"] == 1
    assert result["scan_items"][0]["error_code"] == "index_unavailable"


def test_ptag_accepts_one_grounded_detail_tag_and_requests_one_to_five_without_padding() -> None:
    store = SQLiteStore("sqlite:///:memory:")
    content = store.create_content(
        kind=ContentKind.ARTICLE, title="单个有效细词", platform=SourcePlatform.LOCAL,
    )
    summary = "材料只支持一个有效的流程标签。"
    store.upsert_summary(content.id, summary)
    store.create_summary_version(
        content.id, summary, template="general", origin="original",
        summary_strength="standard", material_level="M2", source_version="summary-v1",
    )
    hit = AskIndexHit(
        "evidence-1", content.id, "summary", "summary", "summary:paragraph:1",
        None, None, "text-hash", summary, 0.0,
    )

    class FakeIndex:
        profile_id = "test-profile"

        def sync_latest(self, _content_id):
            return None

        def read_content_spans(self, _content_id, *, evidence_kind):
            assert evidence_kind == "summary"
            return (hit,)

    class FakeGenerator:
        settings = SimpleNamespace(model="ptag-test")

        def structured_json_request_bytes(self, *_args, **_kwargs):
            return 200

        def complete_json(self, prompt, _schema, **_kwargs):
            self.prompt = json.loads(prompt)
            return ({"topics": [], "detail_tags": [{
                "name": "流程核验", "definition": "按步骤检查输入",
                "topic_ids": ["T11"], "evidence_ids": [hit.stable_id],
            }]}, {"usage": {"total_tokens": 10}})

    service = RagService(store, FakeIndex())
    generator = FakeGenerator()
    service.summary_summarizer = lambda: generator

    result = service.run_tagging(content.id)

    assert result["detail_tags"] == 1
    assert "1～5 个细标签" in generator.prompt["rules"]
    assert len(service.rag_store.list_detail_tags()) == 1


def test_feedback_prompt_includes_previous_answer_and_tool_summary(tmp_path):
    store = SQLiteStore("sqlite:///:memory:")
    service = RagService(store, AskIndex(store, tmp_path / "archive"))
    generator = OpenAICompatibleSummarizer(SummarySettings(model="test"))
    scope = {"kind": "all", "content_set_id": "SET_A", "count": 1, "material_scope": "full"}
    history = [{"question": "如何部署", "result": {"answer": "先安装软件"},
                "scope": scope, "trace": {"tool_results": [{"tool": "search_summaries",
                "args": {"query": "部署步骤"}, "result_ids": ["H1"]}]}}]
    prompt, error = service.build_route_prompt("我想了解费用", scope, generator, history)
    assert error is None
    assert "先安装软件" in prompt
    assert "search_summaries" in prompt
    assert "H1" in prompt
    assert "我想了解费用" in prompt
    assert generator.structured_json_request_bytes(prompt, ROUTE_SCHEMA, max_output_tokens=700) <= 6000
    store.engine.dispose()


# Integration contracts below exercise the production tool-first entrypoint.
from .test_tool_agent import setup_agent
from app.knowledge.tool_agent import ACT_SCHEMA

def test_direct_answer_does_not_call_tools(tmp_path, monkeypatch):
    store, service, query, _ = setup_agent(tmp_path, monkeypatch, [
        {"actions": [], "answer": "请说明你希望修改哪一部分。", "citations": []}])
    monkeypatch.setattr(service, "execute_tool", lambda *args, **kwargs: pytest.fail("unexpected tool"))
    service.run_query(query["id"])
    result = service.rag_store.get_query(query["id"])
    assert result["status"] == "completed"
    assert result["trace"]["execution"] == "tool-first-v1"
    assert result["result"]["answer"] == "请说明你希望修改哪一部分。"
    store.engine.dispose()


@pytest.mark.parametrize("mutation", [None, "forged_id", "forged_quote", "source_before_capture", "source_before_delivery"])
def test_real_search_citation_and_source_validation(tmp_path, monkeypatch, mutation):
    from .test_rag import _versioned_original_evidence
    store, content, archive, summary, index, service, scope, _ = _versioned_original_evidence(tmp_path)
    session = service.rag_store.create_session("原文", scope)
    query = service.rag_store.create_query(session["id"], "版本A讲了什么", scope)
    calls = []
    class Generator:
        def structured_json_request_bytes(self, prompt, schema, **kwargs):
            return len(prompt.encode("utf-8")) + len(json.dumps(schema).encode("utf-8"))
        def complete_json(self, prompt, schema, **kwargs):
            calls.append(prompt)
            if len(calls) == 1:
                return {"actions": [{"tool": "search_original", "args": {"query": "版本A"}}], "answer": "", "citations": []}, {}
            data = json.loads(prompt.split("\n", 1)[1])
            item = data["results"][0]["result"]["evidence"][0]
            if mutation == "source_before_delivery":
                index.sync_content(content.id, archive, summary_text=summary + "修改")
            return {"actions": [], "answer": "先检查材料，再生成回答。", "citations": [{
                "id": "fake" if mutation == "forged_id" else item["id"],
                "quote": "材料不存在的句子" if mutation == "forged_quote" else item["text"][:20]}]}, {}
    monkeypatch.setattr(service, "summarizer", lambda: Generator())
    if mutation == "source_before_capture":
        original = service.execute_tool
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            index.sync_content(content.id, archive, summary_text=summary + "修改")
            return result
        monkeypatch.setattr(service, "execute_tool", changed)
    service.run_query(query["id"])
    result = service.rag_store.get_query(query["id"])
    if mutation is None:
        assert result["status"] == "completed"
        citation = result["result"]["citations"][0]
        assert citation["content_id"] == content.id
        assert citation["text"] and citation["source_kind"] == "original"
    elif mutation.startswith("source_"):
        assert result["status"] == "paused"
        assert not result["result"]["citations"]
    else:
        assert result["status"] == "failed"
        assert not result["result"]["citations"]
    store.engine.dispose()


def test_cancel_during_model_call_does_not_publish_late_answer(tmp_path, monkeypatch):
    store, service, query, _ = setup_agent(tmp_path, monkeypatch, [])
    class Generator:
        def structured_json_request_bytes(self, *args, **kwargs): return 1000
        def complete_json(self, *args, **kwargs):
            service.rag_store.request_cancel(query["id"])
            return {"actions": [], "answer": "迟到答案", "citations": []}, {}
    monkeypatch.setattr(service, "summarizer", lambda: Generator())
    service.run_query(query["id"])
    assert service.rag_store.get_query(query["id"])["status"] == "cancelled"
    store.engine.dispose()


def test_unshrinkable_input_clarifies_before_provider_call(tmp_path, monkeypatch):
    from app.knowledge.tool_agent import AGENT_INPUT_LIMIT

    store, service, query, _ = setup_agent(tmp_path, monkeypatch, [])
    class Generator:
        def structured_json_request_bytes(self, *args, **kwargs): return AGENT_INPUT_LIMIT + 1
        def complete_json(self, *args, **kwargs): pytest.fail("oversized request")
    monkeypatch.setattr(service, "summarizer", lambda: Generator())
    service.run_query(query["id"])
    assert service.rag_store.get_query(query["id"])["status"] == "completed"
    assert service.rag_store.get_query(query["id"])["result"]["status"] == "clarify"
    store.engine.dispose()


def test_model_output_caps_and_resume(tmp_path, monkeypatch):
    store, service, query, _ = setup_agent(tmp_path, monkeypatch, [])
    caps = []
    class Generator:
        def structured_json_request_bytes(self, *args, **kwargs): return 1000
        def complete_json(self, *args, **kwargs):
            caps.append(kwargs["max_output_tokens"])
            return {"actions": [{"tool": "inspect_scope", "args": {}}], "answer": "", "citations": []}, {}
    monkeypatch.setattr(service, "summarizer", lambda: Generator())
    service.run_query(query["id"])
    assert caps == [700, 700, 700, 1300]
    assert service.rag_store.get_query(query["id"])["status"] == "paused"
    service.rag_store.resume_query(query["id"])
    class Final(Generator):
        def complete_json(self, *args, **kwargs):
            assert args[1] == ACT_SCHEMA
            return {"actions": [], "answer": "请说明关注点。", "citations": []}, {}
    monkeypatch.setattr(service, "summarizer", lambda: Final())
    service.run_query(query["id"])
    assert service.rag_store.get_query(query["id"])["status"] == "completed"
    store.engine.dispose()


def test_selected_scope_is_not_truncated_by_old_compare_classification(tmp_path, monkeypatch):
    store, service, query, _ = setup_agent(tmp_path, monkeypatch, [
        {"actions": [{"tool": "inspect_scope", "args": {}}], "answer": "", "citations": []},
        {"actions": [], "answer": "请说明比较重点。", "citations": []}])
    scope = {**query["scope"], "kind": "selected", "content_ids": [str(i) for i in range(7)]}
    service.rag_store.update_query(query["id"], scope=scope)
    service.run_query(query["id"])
    result = service.rag_store.get_query(query["id"])
    assert result["status"] == "completed"
    assert result["trace"]["tool_results"][0]["result"]["count"] == 7
    store.engine.dispose()


@pytest.mark.parametrize("name", ["inspect_scope", "resolve_catalog", "query_contents", "expand_content_links", "search_summaries", "search_original", "read_chunks", "compute_result"])
def test_each_registered_tool_runs_with_real_archive(tmp_path, monkeypatch, name):
    from .test_rag import _versioned_original_evidence
    store, content, archive, summary, index, service, scope, _ = _versioned_original_evidence(tmp_path)
    session = service.rag_store.create_session("tool", scope)
    query = service.rag_store.create_query(session["id"], "材料查询", scope)
    hit_id = index.search_keyword("版本A", content_ids=[content.id], evidence_kind="original")[0].stable_id
    filters = {"media_type": None, "author_ids": [], "platform_ids": [], "published_at": None, "collected_at": None}
    args = {"inspect_scope": {}, "resolve_catalog": {"terms": ["RAG"]},
            "query_contents": {"filters": filters, "cursor": None, "topic_ids": [], "tag_ids": [], "logic": "any"},
            "expand_content_links": {"seed_content_ids": [content.id], "active_tag_ids": []},
            "search_summaries": {"query": "版本A"}, "search_original": {"query": "版本A"},
            "read_chunks": {"chunk_ids": [hit_id], "neighbor_window": 1}, "compute_result": {}}[name]
    prompts = []
    class Generator:
        def structured_json_request_bytes(self, *args, **kwargs): return 1000
        def complete_json(self, prompt, schema, **kwargs):
            prompts.append(prompt)
            if len(prompts) == 1:
                return {"actions": [{"tool": name, "args": args}], "answer": "", "citations": []}, {}
            result = json.loads(prompt.split("\n", 1)[1])["results"][-1]["result"]
            cites = [{"id": result["evidence"][0]["id"], "quote": result["evidence"][0]["text"][:15]}] if result.get("evidence") else []
            return {"actions": [], "answer": "材料查询完成。", "citations": cites}, {}
    monkeypatch.setattr(service, "summarizer", lambda: Generator())
    service.run_query(query["id"])
    result = service.rag_store.get_query(query["id"])
    assert result["status"] == "completed", result["trace"]
    assert result["trace"]["tool_results"][0]["tool"] == name
    assert "error" not in result["trace"]["tool_results"][0]
    store.engine.dispose()


def test_topic_count_reports_incomplete_classification(tmp_path, monkeypatch):
    from .test_rag import _versioned_original_evidence
    from app.knowledge.rag_catalog import TOPICS
    store, content, archive, summary, index, service, scope, _ = _versioned_original_evidence(tmp_path)
    session = service.rag_store.create_session("count", scope)
    query = service.rag_store.create_query(session["id"], "主题有几篇", scope)
    calls = []
    class Generator:
        def structured_json_request_bytes(self, *args, **kwargs): return 1000
        def complete_json(self, prompt, schema, **kwargs):
            calls.append(prompt)
            if len(calls) == 1:
                return {"actions": [{"tool": "query_contents", "args": {
                    "filters": {"media_type": None, "author_ids": [], "platform_ids": [], "published_at": None, "collected_at": None},
                    "cursor": None, "topic_ids": [TOPICS[0].id], "tag_ids": [], "logic": "any"}}], "answer": "", "citations": []}, {}
            result = json.loads(prompt.split("\n", 1)[1])["results"][-1]["result"]
            assert result["exact"] is False
            assert result["classification_coverage"]["unknown"] == 1
            return {"actions": [], "answer": "已确认0项，另有1项尚未完成分类，不能给出精确总数。", "citations": []}, {}
    monkeypatch.setattr(service, "summarizer", lambda: Generator())
    service.run_query(query["id"])
    result = service.rag_store.get_query(query["id"])
    assert result["status"] == "completed"
    assert result["result"]["coverage"]["exact"] is False
    assert "index_coverage" in result["trace"]
    store.engine.dispose()
