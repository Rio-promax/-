import json
from hashlib import sha256
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.adapters.summary.openai_compatible import OpenAICompatibleSummarizer, SummarySettings
from app.db.store import SQLiteStore
from app.knowledge.ask_index import AskIndex
from app.knowledge.rag import RagService, _search_facets
from app.knowledge.tool_agent import ACT_SCHEMA, FINAL_SCHEMA, Decision, _bounded_agent_prompt, _limit_search_lanes, _overview_target


def setup_agent(tmp_path, monkeypatch, responses):
    store = SQLiteStore("sqlite:///:memory:")
    service = RagService(store, AskIndex(store, tmp_path / "archive"))
    scope = {"kind": "all", "content_ids": [], "content_set_id": "SET_A", "source_versions": {}}
    session = service.rag_store.create_session("test", scope)
    query = service.rag_store.create_query(session["id"], "请解释刚才回答", scope)
    prompts = []
    class Generator:
        def structured_json_request_bytes(self, prompt, schema, **kwargs):
            return len(prompt.encode("utf-8")) + len(json.dumps(schema).encode("utf-8"))
        def complete_json(self, prompt, schema, **kwargs):
            assert schema in (ACT_SCHEMA, FINAL_SCHEMA)
            assert "t" not in schema["properties"] and "g" not in schema["properties"]
            prompts.append(prompt)
            return responses.pop(0), {}
    monkeypatch.setattr(service, "summarizer", lambda: Generator())
    monkeypatch.setattr(service, "refresh_scope_material_versions", lambda value: value)
    monkeypatch.setattr(service, "_changed_scope_source_ids", lambda *args: [])
    return store, service, query, prompts




@pytest.mark.parametrize(("question", "scope_kind", "expected_calls"), [
    ("这篇主要讲什么？", "selected", [FINAL_SCHEMA]),
    ("《版本核验》主要讲什么？", "all", [FINAL_SCHEMA]),
    ("我记得有一篇提到“版本A”，它讲什么？", "all", [ACT_SCHEMA, FINAL_SCHEMA]),
])
def test_document_overview_routes_to_indexed_note(tmp_path, monkeypatch, question, scope_kind, expected_calls):
    from .test_rag import _versioned_original_evidence

    store, content, _, summary, _, service, scope, _ = _versioned_original_evidence(tmp_path)
    scope = {**scope, "kind": scope_kind}
    session = service.rag_store.create_session("overview", scope)
    query = service.rag_store.create_query(session["id"], question, scope)
    calls = []

    class Generator:
        def structured_json_request_bytes(self, prompt, *args, **kwargs):
            return len(prompt.encode("utf-8"))

        def complete_json(self, prompt, schema, **kwargs):
            calls.append(schema)
            if schema is ACT_SCHEMA:
                return {"actions": [{"tool": "search_summaries", "args": {"query": "版本A"}}],
                        "answer": "", "citations": []}, {}
            assert summary in prompt
            return {"answer": "概括版本A的处理流程。", "citations": ["E1"]}, {}

    monkeypatch.setattr(service, "summarizer", Generator)
    service.run_query(query["id"])
    result = service.rag_store.get_query(query["id"])
    assert result["status"] == "completed"
    assert result["result"]["citations"][0]["content_id"] == content.id
    assert calls == expected_calls
    store.engine.dispose()


def test_document_overview_does_not_auto_resolve_duplicate_titles():
    entries = [SimpleNamespace(content=SimpleNamespace(id=id_, title="同名资料"))
               for id_ in ("one", "two")]
    service = SimpleNamespace(store=SimpleNamespace(list_history=lambda **kwargs: entries))
    question = "《同名资料》主要讲什么？"
    assert _overview_target(service, question, {"content_ids": ["one", "two"]}) == (
        None, "ambiguous_title",
    )
    assert _overview_target(service, question, {"content_ids": ["one"]}) == ("one", None)


def test_composite_search_adds_other_layer_and_reranks_answer_globally(tmp_path, monkeypatch):
    from .test_rag import _versioned_original_evidence

    store, content, _, _, index, service, scope, _ = _versioned_original_evidence(tmp_path)
    session = service.rag_store.create_session("multi", scope)
    question = "一句话问了多个问题，又有指代，怎么处理？"
    query = service.rag_store.create_query(session["id"], question, scope)
    ranking_calls = []

    def rerank(ranked_question, documents, **kwargs):
        ranking_calls.append((ranked_question, documents))
        return [(i, float(i)) for i in reversed(range(len(documents)))]

    def execute_tool(tool, args, frozen_scope):
        from app.knowledge.rag import _hit_dict

        kind = "summary" if tool == "search_summaries" else "original"
        spans = index.read_content_spans(content.id, evidence_kind=kind)
        return {"hits": [_hit_dict(span) for span in spans]}

    class Generator:
        def structured_json_request_bytes(self, prompt, *args, **kwargs):
            return len(prompt.encode("utf-8"))

        def complete_json(self, prompt, schema, **kwargs):
            payload = json.loads(prompt.split("\n", 1)[1])
            if not payload["results"]:
                return {"actions": [{"tool": "search_original", "args": {"query": "版本A"}}],
                        "answer": "", "citations": []}, {}
            if schema is ACT_SCHEMA:
                return {"actions": [], "answer": "准备作答", "citations": []}, {}
            assert payload["results"][0]["tool"] == "answer_rerank"
            assert [span["source_kind"] for span in payload["results"][0]["result"]["evidence"]] == [
                "summary", "original",
            ]
            return {"answer": "整理两层材料后回答。", "citations": ["E1"]}, {}

    monkeypatch.setattr(service, "reranker", SimpleNamespace(rerank=rerank))
    monkeypatch.setattr(service, "execute_tool", execute_tool)
    monkeypatch.setattr(service, "summarizer", Generator)
    service.run_query(query["id"])
    response = service.rag_store.get_query(query["id"])
    assert response["status"] == "completed"
    trace = response["trace"]
    assert [call["tool"] for call in trace["tool_results"]] == ["search_original", "search_summaries"]
    assert trace["answer_rerank"]["status"] == "applied"
    assert len(ranking_calls) == 1 and ranking_calls[0][0] == question
    store.engine.dispose()


def test_model_selects_tool_and_receives_real_result(tmp_path, monkeypatch):
    store, service, query, prompts = setup_agent(tmp_path, monkeypatch, [
        {"actions": [{"tool": "compute_result", "args": {}}], "answer": "", "citations": []},
        {"actions": [], "answer": "范围内有0条内容。", "citations": []}])
    service.run_query(query["id"])
    result = service.rag_store.get_query(query["id"])
    assert result["status"] == "completed"
    assert result["trace"]["tool_results"][0]["tool"] == "compute_result"
    assert '"count":0' in prompts[1]
    store.engine.dispose()


def test_last_model_turn_reserves_answer_without_advertising_tools(tmp_path, monkeypatch):
    action = {"actions": [{"tool": "inspect_scope", "args": {}}], "answer": "", "citations": []}
    store, service, query, prompts = setup_agent(tmp_path, monkeypatch, [
        action, action, action, {"actions": [], "answer": "范围已确认。", "citations": []},
    ])
    service.run_query(query["id"])
    result = service.rag_store.get_query(query["id"])
    assert result["status"] == "completed"
    assert len(result["trace"]["tool_results"]) == 3
    assert json.loads(prompts[-1].split("\n", 1)[1])["tools"] == []
    store.engine.dispose()


def test_deepseek_agent_sends_json_object_and_keeps_tool_contract(monkeypatch):
    requests = []

    def read_response(client, payload):
        requests.append((client.settings, payload))
        answer = {"actions": [{"tool": "inspect_scope", "args": {}}], "answer": "", "citations": []}
        return {"choices": [{"message": {"content": json.dumps(answer)}, "finish_reason": "stop"}]}

    monkeypatch.setattr(OpenAICompatibleSummarizer, "_request", read_response)
    agent = OpenAICompatibleSummarizer.for_tool_agent(SummarySettings(
        api_url="https://api.deepseek.com/v1/responses", api_mode="responses", model="deepseek-flash",
    ))
    output, _ = agent.complete_json("检查范围", ACT_SCHEMA, timeout=10, max_output_tokens=200)
    settings, payload = requests[0]
    assert settings.api_url == "https://api.deepseek.com/v1/chat/completions"
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["thinking"] == {"type": "disabled"}
    assert '"inspect_scope"' in payload["messages"][0]["content"]
    assert Decision.model_validate(output).actions[0].tool == "inspect_scope"


def test_dashscope_agent_uses_fast_structured_decisions():
    settings = SummarySettings(
        api_url="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        api_mode="chat_completions", model="qwen3.8-max", provider="qwen",
    )
    agent = OpenAICompatibleSummarizer.for_tool_agent(settings)
    payload = agent._structured_json_payload("检查范围", ACT_SCHEMA, 700, "chat_completions")
    assert payload["enable_thinking"] is False
    assert payload["response_format"]["type"] == "json_schema"
    plain = OpenAICompatibleSummarizer(settings)
    assert "enable_thinking" not in plain._structured_json_payload("试题", ACT_SCHEMA, 700, "chat_completions")


def test_final_prompt_keeps_full_top_evidence_and_removes_duplicate_blocks():
    top = {"id": "E1", "content_id": "first", "text": "甲" * 450 + "512 token 是例子"}
    extra = [{"id": f"E{n}", "content_id": "first", "text": "乙" * 700} for n in range(2, 17)]
    other = {"id": "E17", "content_id": "second", "text": "另一来源的适用条件"}
    state = {"results": [
        {"tool": "read_chunks", "result": {"evidence": [top, *extra, other]}},
        {"result": {"evidence": [top, *extra]}},
    ], "history": []}
    generator = SimpleNamespace(structured_json_request_bytes=lambda prompt, *a, **kw:
                                len(prompt.encode("utf-8")))
    sent = []
    prompt = _bounded_agent_prompt(state, generator, 1300, final=True, sent_evidence=sent)
    assert prompt.count('"id":"E1"') == 1
    assert top["text"] in prompt
    assert "E1" in {span["id"] for span in sent}
    assert "E17" not in {span["id"] for span in sent}
    payload = json.loads(prompt.split("\n", 1)[1])
    assert sent == [
        {"id": span["id"], "chars": len(span["text"]),
         "sha256": sha256(span["text"].encode("utf-8")).hexdigest()}
        for packet in payload["results"] for span in packet["result"]["evidence"]
    ]


@pytest.mark.parametrize("final", [False, True])
def test_context_block_limit_is_shared_across_search_lanes(final):
    state = {"history": [], "results": [
        {"tool": tool, "result": {"evidence": [
            {"id": f"{tool}-{n}", "content_id": str(n), "text": "evidence"}
            for n in range(20)
        ]}}
        for tool in ("search_summaries", "search_original")
    ]}
    generator = SimpleNamespace(structured_json_request_bytes=lambda prompt, *a, **kw: len(prompt))
    sent = []
    assert _bounded_agent_prompt(state, generator, 1300, final=final, sent_evidence=sent)
    assert len(sent) == (16 if final else 6)
    assert sum(span["id"].startswith("search_summaries") for span in sent) == (8 if final else 3)


@pytest.mark.parametrize("final", [False, True])
def test_context_budget_keeps_ranked_adjacent_blocks_whole(final):
    pair = [
        {"id": f"pair-{n}", "content_id": "document", "source_kind": "summary",
         "location_kind": "summary", "chunk_ordinal": n, "text": "甲" * 600}
        for n in (1, 2)
    ]
    state = {"history": [], "results": [
        {"tool": "search_summaries", "result": {"evidence": pair}},
        {"tool": "search_original", "result": {"evidence": [
            {"id": f"other-{n}", "content_id": str(n), "text": "乙" * 1500}
            for n in range(16)
        ]}},
    ]}
    generator = SimpleNamespace(
        structured_json_request_bytes=lambda prompt, *a, **kw: len(prompt.encode("utf-8"))
    )
    sent = []
    packing = {}
    prompt = _bounded_agent_prompt(state, generator, 1300, final=final, sent_evidence=sent, packing_trace=packing)
    assert prompt and len(prompt.encode("utf-8")) <= (50000 if final else 24000)
    assert packing["dropped_by_block_limit"] and packing["dropped_by_byte_limit"]
    assert len(sent) < 16
    assert {span["id"]: span["chars"] for span in sent if span["id"].startswith("pair-")} == {
        "pair-1": 600, "pair-2": 600,
    }
    assert all(span["chars"] == 1500 for span in sent if span["id"].startswith("other-"))
    byte_ranks = [int(id_.split("-")[1]) for id_ in packing["dropped_by_byte_limit"]]
    assert byte_ranks == sorted(byte_ranks, reverse=True)


@pytest.mark.parametrize(("lane_count", "expected"), [(1, 12), (2, 20), (3, 30), (4, 28), (5, 30), (7, 28), (30, 30)])
def test_multilane_search_divides_total_budget_across_lanes(lane_count, expected):
    state = {"history": [], "results": [
        {"tool": "search_summaries", "query": f"query-{lane}", "result": {"evidence": [
            {"id": f"{lane}-{rank}", "content_id": f"{lane}-{rank}", "text": "证据"}
            for rank in range(12)
        ]}}
        for lane in range(lane_count)
    ]}
    trace = {}
    _limit_search_lanes(state, trace)
    generator = SimpleNamespace(structured_json_request_bytes=lambda prompt, *a, **kw: len(prompt))
    sent = []
    assert _bounded_agent_prompt(state, generator, 1300, final=True, sent_evidence=sent)
    assert len(sent) == expected
    if lane_count > 1:
        assert all(int(span["id"].split("-")[1]) < min(10, 30 // lane_count) for span in sent)
        assert len(trace["multi_search_limits"]["drops"]) == lane_count


def test_unknown_tools_and_scope_overrides_rejected():
    for action in [{"tool": "delete", "args": {}},
                   {"tool": "search_summaries", "args": {"query": "test", "content_set_id": "OUTSIDE"}}]:
        with pytest.raises(ValidationError):
            Decision.model_validate({"actions": [action], "answer": "", "citations": []})


def test_composite_queries_search_each_intent_separately():
    tasks = _search_facets("一句话有多个问题并存在指代")
    assert len(tasks) == 2
    assert "子问题" in tasks[0]
    assert "指代" in tasks[1]
    assert _search_facets("指代消解") == ("指代消解",)


def test_budget_stops_endless_tool_calls(tmp_path, monkeypatch):
    action = {"actions": [{"tool": "inspect_scope", "args": {}}], "answer": "", "citations": []}
    store, service, query, prompts = setup_agent(tmp_path, monkeypatch, [action] * 4)
    service.run_query(query["id"])
    assert len(prompts) == 4
    assert service.rag_store.get_query(query["id"])["status"] == "paused"
    store.engine.dispose()






def test_feedback_can_answer_without_search_with_prior_answer(tmp_path, monkeypatch):
    store, service, query, prompts = setup_agent(tmp_path, monkeypatch, [
        {"actions": [], "answer": "请告诉我关注点。", "citations": []},
        {"actions": [], "answer": "关注费用即可。", "citations": []}])
    service.run_query(query["id"])
    followup = service.rag_store.create_query(query["session_id"], "我的意思是费用，不是操作步骤", query["scope"])
    monkeypatch.setattr(service, "execute_tool", lambda *args, **kwargs: pytest.fail("must allow no tool"))
    service.run_query(followup["id"])
    assert "请告诉我关注点" in prompts[-1]
    assert "我的意思是费用" in prompts[-1]
    assert service.rag_store.get_query(followup["id"])["status"] == "completed"
    store.engine.dispose()


def test_same_tool_can_receive_new_query_without_fixed_feedback_routes(tmp_path, monkeypatch):
    responses = [{"actions": [{"tool": "search_summaries", "args": {"query": q}}], "answer": "", "citations": []}
                 for q in ["步骤", "费用"]]
    responses.append({"actions": [], "answer": "已检查费用资料，暂无匹配。", "citations": []})
    store, service, query, _ = setup_agent(tmp_path, monkeypatch, responses)
    seen = []
    def search(tool, args, scope):
        seen.append((tool, args["query"]))
        return {"hits": []}
    monkeypatch.setattr(service, "execute_tool", search)
    service.run_query(query["id"])
    assert seen == [("search_summaries", "步骤"), ("search_summaries", "费用")]
    assert service.rag_store.get_query(query["id"])["status"] == "completed"
    store.engine.dispose()


def test_action_schema_has_no_open_objects():
    def walk(item):
        if isinstance(item, dict):
            if item.get("type") == "object":
                assert item.get("additionalProperties") is False
                assert set(item.get("required", [])) == set(item.get("properties", {}))
            for value in item.values(): walk(value)
        elif isinstance(item, list):
            for value in item: walk(value)
    walk(ACT_SCHEMA)


def test_malformed_tool_call_is_not_executed(tmp_path, monkeypatch):
    store, service, query, _ = setup_agent(tmp_path, monkeypatch, [
        {"actions": [{"tool": "search_summaries", "args": {"query": 123}}], "answer": "", "citations": []}])
    monkeypatch.setattr(service, "execute_tool", lambda *args, **kwargs: pytest.fail("invalid call executed"))
    service.run_query(query["id"])
    assert service.rag_store.get_query(query["id"])["status"] == "failed"
    store.engine.dispose()












def test_loaded_evidence_does_not_block_clarification(tmp_path, monkeypatch):
    from .test_rag import _versioned_original_evidence
    store, content, archive, summary, index, service, scope, _ = _versioned_original_evidence(tmp_path)
    session = service.rag_store.create_session("clarify", scope)
    query = service.rag_store.create_query(session["id"], "请修改", scope)
    calls = []
    class Generator:
        def structured_json_request_bytes(self, *args, **kwargs): return 1000
        def complete_json(self, prompt, schema, **kwargs):
            calls.append(prompt)
            if len(calls) == 1:
                return {"actions": [{"tool": "search_original", "args": {"query": "版本A"}}], "answer": "", "citations": []}, {}
            assert json.loads(prompt.split("\n", 1)[1])["results"][0]["result"]["evidence"]
            return {"actions": [], "answer": "你想了解原文措辞还是操作流程？", "citations": []}, {}
    monkeypatch.setattr(service, "summarizer", lambda: Generator())
    service.run_query(query["id"])
    assert service.rag_store.get_query(query["id"])["status"] == "completed"
    store.engine.dispose()


def test_change_while_queued_preserves_snapshot_and_pauses(tmp_path, monkeypatch):
    from .test_rag import _versioned_original_evidence
    store, content, archive, summary, index, service, scope, _ = _versioned_original_evidence(tmp_path)
    session = service.rag_store.create_session("queued", scope)
    query = service.rag_store.create_query(session["id"], "版本A", scope)
    frozen = dict(query["scope"]["source_versions"])
    index.sync_content(content.id, archive, summary_text=summary + "更新")
    monkeypatch.setattr(service, "summarizer", lambda: pytest.fail("stale snapshot must pause before planning"))
    service.run_query(query["id"])
    result = service.rag_store.get_query(query["id"])
    assert result["status"] == "paused"
    assert result["scope"]["source_versions"] == frozen
    store.engine.dispose()


@pytest.mark.parametrize("block_count", [1, 16])
def test_large_chinese_results_fit_without_repeated_pause(tmp_path, monkeypatch, block_count):
    from app.knowledge.rag import _hit_dict
    from .test_rag import _versioned_original_evidence
    store, content, archive, summary, index, service, scope, _ = _versioned_original_evidence(tmp_path)
    session = service.rag_store.create_session("large", scope)
    query = service.rag_store.create_query(session["id"], "请概括", scope)
    real = index.search_keyword("版本A", content_ids=[content.id], evidence_kind="original")[0]
    monkeypatch.setattr(service, "execute_tool", lambda *args, **kwargs: {"hits": [_hit_dict(real)]})
    original = service._evidence([real], scope["content_ids"], scope["source_versions"])[0]
    many = [{**original, "id": "E" + str(i), "text": "原文很长。" * 200} for i in range(block_count)]
    monkeypatch.setattr(service, "_evidence", lambda *args: many)
    calls = []
    class Generator:
        def structured_json_request_bytes(self, prompt, schema, **kwargs):
            return len(prompt.encode("utf-8")) + len(json.dumps(schema).encode("utf-8"))
        def complete_json(self, prompt, schema, **kwargs):
            assert self.structured_json_request_bytes(prompt, schema) <= kwargs["max_input_bytes"]
            calls.append(prompt)
            if len(calls) == 1:
                return {"actions": [{"tool": "search_original", "args": {"query": "版本A"}}], "answer": "", "citations": []}, {}
            item = json.loads(prompt.split("\n", 1)[1])["results"][0]["result"]["evidence"][0]
            if block_count == 1:
                assert item["text"] == many[0]["text"]
            if schema is FINAL_SCHEMA:
                return {"answer": "已概括提供的片段。", "citations": [item["id"]]}, {}
            return {"actions": [], "answer": "已概括提供的片段。", "citations": [{"id": item["id"], "quote": item["text"][:20]}]}, {}
    monkeypatch.setattr(service, "summarizer", lambda: Generator())
    service.run_query(query["id"])
    assert len(calls) == (2 if block_count == 1 else 3)
    if block_count > 1:
        trace = service.rag_store.get_query(query["id"])["trace"]
        assert len(trace["calls"][1]["sent_evidence"]) <= 6
        assert trace["calls"][-1]["stage"] == "P-FINAL"
    assert service.rag_store.get_query(query["id"])["status"] == "completed"
    store.engine.dispose()
