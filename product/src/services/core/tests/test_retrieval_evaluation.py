"""Synthetic mechanics tests only; these fixtures are not quality evidence."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from tools import ai_ask_retrieval_eval as evaluation


def _sha(char: str) -> str:
    return char * 64


def _evidence(content_id: str, source_ref: str, char: str) -> dict[str, str]:
    return {
        "content_id": content_id,
        "source_kind": "bilibili_subtitle",
        "location_kind": "time_range",
        "source_ref": source_ref,
        "text_hash": _sha(char),
    }


def _case(index: int, category: str) -> dict:
    answerability = "answerable"
    scope = ["content-a", "content-b"]
    required = [_evidence("content-a", f"segment-{index}", "a")]
    audit = None
    if category == "cross_content_all_evidence":
        required.append(_evidence("content-b", f"segment-b-{index}", "b"))
    if category == "scope_no_answer":
        answerability = "scope_no_answer"
        required = []
    elif category == "corpus_no_answer":
        answerability = "corpus_no_answer"
        required = []
    elif category == "partial_coverage":
        answerability = "partial_coverage"
    if answerability in evaluation.NEGATIVE_ANSWERABILITY:
        audit = {
            "human_verified": True,
            "reviewer_ref": "reviewer-1",
            "snapshot_id": "snap-test",
            "archive_manifest_sha256": _sha("c"),
            "scope_content_ids": scope,
            "audit_artifact_sha256": _sha("d"),
        }
    return {
        "case_id": f"T-{index:03d}",
        "question": f"synthetic question {index}",
        "categories": [category],
        "answerability": answerability,
        "scope_content_ids": scope,
        "snapshot_id": "snap-test",
        "is_gold": True,
        "review": {
            "status": "approved",
            "approved_by_human": True,
            "reviewer_ref": "reviewer-1",
            "evidence_verified": True,
        },
        "required_evidence": required,
        "negative_evidence_audit": audit,
    }


def _valid_contract_fixture() -> dict:
    """Synthetic mechanics fixture; never shipped or counted as reviewed gold."""
    categories = evaluation.REQUIRED_CATEGORIES
    cases = [_case(index, categories[index % len(categories)]) for index in range(60)]
    return {
        "schema_version": evaluation.GOLD_SCHEMA,
        "dataset_status": "frozen",
        "snapshot": {
            "snapshot_id": "snap-test",
            "archive_manifest_sha256": _sha("c"),
            "index_db_sha256": _sha("e"),
            "content_ids": ["content-a", "content-b"],
        },
        "profiles": {
            "fts_profile_id": "fts5:test",
            "vector_profile_id": "vec:test",
            "model_sha256": _sha("f"),
            "dimension": 1024,
        },
        "key_recall_categories": ["fact", "numeric_proper_name", "synonym"],
        "cases": cases,
    }


def _hit(item: dict[str, str], text: str = "synthetic hit") -> SimpleNamespace:
    return SimpleNamespace(**item, text=text)


def test_pending_candidates_are_never_gold_or_evaluable(tmp_path):
    cards = [
        {"case_id": f"M1D-{i:03d}", "is_gold": False, "human_final_review": {"status": "pending"}}
        for i in range(55)
    ]
    candidate_file = tmp_path / "pending-candidates.json"
    candidate_file.write_text(
        json.dumps({"schema_version": "m1-question-card-candidates-v5", "cases": cards}),
        encoding="utf-8",
    )

    report = evaluation.summarize_candidate_files([candidate_file])

    assert report["case_count"] == 55
    assert report["distinct_case_count"] == 55
    assert report["duplicate_case_record_count"] == 0
    assert report["gold_count"] == 0
    assert report["gold_declared_count"] == 0
    assert report["evaluation_status"] == "not_evaluable"
    assert report["retrieval_metrics"] == "not_evaluated"
    assert report["overall_quality_gate_status"] == "not_evaluable"


def test_candidate_revision_does_not_inflate_distinct_question_count(tmp_path):
    paths = []
    for name in ("original", "revision"):
        path = tmp_path / f"{name}.json"
        path.write_text(
            json.dumps({"cases": [{"case_id": "M1D-001", "is_gold": False}]}),
            encoding="utf-8",
        )
        paths.append(path)

    report = evaluation.summarize_candidate_files(paths)

    assert report["case_count"] == 2
    assert report["distinct_case_count"] == 1
    assert report["duplicate_case_record_count"] == 1
    assert report["gold_count"] == 0


def test_candidate_schema_fails_gold_schema_gate():
    candidate = {"schema_version": "m1-question-card-candidates-v5", "cases": []}

    assert evaluation.validate_gold_dataset(candidate) == ["gold_schema_required"]


def test_human_evidence_snapshot_and_profile_gates_are_required():
    dataset = _valid_contract_fixture()
    assert evaluation.validate_gold_dataset(dataset) == []

    dataset["cases"][0]["review"]["approved_by_human"] = False
    assert "human_review_missing" in evaluation.validate_gold_dataset(dataset)

    dataset = _valid_contract_fixture()
    dataset["cases"][0]["review"]["evidence_verified"] = False
    assert "evidence_verification_missing" in evaluation.validate_gold_dataset(dataset)

    dataset = _valid_contract_fixture()
    dataset["cases"][0]["snapshot_id"] = "other-snapshot"
    assert "case_snapshot_mismatch" in evaluation.validate_gold_dataset(dataset)

    dataset = _valid_contract_fixture()
    dataset["snapshot"]["index_db_sha256"] = "bad-hash"
    assert "index_db_sha256_invalid" in evaluation.validate_gold_dataset(dataset)


def test_evidence_match_requires_exact_source_tuple_and_hash():
    expected = _evidence("content-a", "segment-1", "a")
    near_match = _hit({**expected, "text_hash": _sha("b")})

    assert evaluation.evidence_recall_at_k([expected], [near_match], 5) == 0.0
    assert evaluation.evidence_recall_at_k([expected], [_hit(expected)], 5) == 1.0


def test_scope_leak_and_cross_content_requires_every_evidence_at_ten():
    case = _case(1, "cross_content_all_evidence")
    first, second = case["required_evidence"]
    leaked = _hit(_evidence("outside-scope", "leak", "9"))
    one_required = _hit(first)

    result, violations = evaluation._case_method_result(case, [one_required, leaked])
    assert violations == 1
    assert result["scope_violation_count"] == 1
    assert result["all_required_evidence_at_10"] is False
    assert result["case_recall_at_5"] is True
    assert result["evidence_recall_at_5"] == 0.5
    assert result["hits"][1]["in_scope"] is False
    assert "content-a" not in json.dumps(result)
    assert "synthetic hit" not in json.dumps(result)

    assert (
        evaluation.all_required_evidence_at_k([first, second], [_hit(first), _hit(second)], 10)
        is True
    )


def test_gate_counts_questions_and_uses_hybrid_not_diagnostic_baselines():
    dataset = _valid_contract_fixture()
    by_question = {case["question"]: case for case in dataset["cases"]}

    class HybridOnlyIndex:
        profile_id = "fts5:test"
        vector_profile_id = "vec:test"
        vector_error_message = None
        _embedding_backend = SimpleNamespace(config={"model_sha256": _sha("f")}, dimension=1024)

        def search_keyword(self, query, *, limit, content_ids):
            return ()

        def search_vector(self, query, *, limit, content_ids):
            return ()

        def search_hybrid(self, query, *, limit, content_ids):
            return tuple(_hit(item) for item in by_question[query]["required_evidence"])

    report = evaluation.evaluate_with_index(
        dataset,
        HybridOnlyIndex(),
        observed_archive_manifest_sha256=_sha("c"),
        observed_index_db_sha256=_sha("e"),
    )
    assert report["retrieval_methods"]["keyword"]["aggregate"]["retrieval_gate_status"] == "fail"
    assert report["retrieval_methods"]["vector"]["aggregate"]["retrieval_gate_status"] == "fail"
    assert report["retrieval_methods"]["hybrid"]["aggregate"]["case_recall_at_5"] == 1.0
    assert report["retrieval_quality_gate_status"] == "pass"
    assert report["overall_quality_gate_status"] == "not_evaluable"


def test_three_retrieval_paths_are_called_independently_and_no_answer_is_unscored():
    dataset = _valid_contract_fixture()

    class EmptyIndex:
        profile_id = "fts5:test"
        vector_profile_id = "vec:test"
        vector_error_message = None
        _embedding_backend = SimpleNamespace(config={"model_sha256": _sha("f")}, dimension=1024)

        def __init__(self):
            self.calls = {method: 0 for method in evaluation.METHODS}

        def _search(self, method, query, *, limit, content_ids):
            self.calls[method] += 1
            assert limit == 10
            assert content_ids
            return ()

        def search_keyword(self, query, *, limit, content_ids):
            return self._search("keyword", query, limit=limit, content_ids=content_ids)

        def search_vector(self, query, *, limit, content_ids):
            return self._search("vector", query, limit=limit, content_ids=content_ids)

        def search_hybrid(self, query, *, limit, content_ids):
            return self._search("hybrid", query, limit=limit, content_ids=content_ids)

    index = EmptyIndex()
    report = evaluation.evaluate_with_index(
        dataset,
        index,
        observed_archive_manifest_sha256=_sha("c"),
        observed_index_db_sha256=_sha("e"),
    )

    assert index.calls == {"keyword": 60, "vector": 60, "hybrid": 60}
    assert report["retrieval_methods"]["keyword"]["aggregate"]["evidence_recall_at_5"] == 0.0
    assert report["retrieval_methods"]["vector"]["aggregate"]["evidence_recall_at_5"] == 0.0
    assert report["retrieval_methods"]["hybrid"]["aggregate"]["evidence_recall_at_5"] == 0.0
    assert (
        report["answer_layer_metrics"]["metrics"]["scope_no_answer_correct_refusal"]
        == "not_evaluated"
    )
    assert report["answer_layer_metrics"]["metrics"]["fabricated_citations"] == "not_evaluated"
    assert report["overall_quality_gate_status"] == "not_evaluable"
    encoded = json.dumps(report)
    assert "synthetic question" not in encoded
    assert "synthetic hit" not in encoded


def test_snapshot_or_profile_mismatch_stops_before_any_search():
    dataset = _valid_contract_fixture()

    class UncalledIndex:
        profile_id = "wrong"
        vector_profile_id = "wrong"
        vector_error_message = None
        _embedding_backend = SimpleNamespace(config={"model_sha256": _sha("f")}, dimension=1024)

        def __getattr__(self, name):
            raise AssertionError(f"search must not run: {name}")

    report = evaluation.evaluate_with_index(
        dataset,
        UncalledIndex(),
        observed_archive_manifest_sha256=_sha("0"),
        observed_index_db_sha256=_sha("e"),
    )
    assert report["evaluation_status"] == "not_evaluable"
    assert "archive_manifest_snapshot_mismatch" in report["reasons"]
    assert "retrieval_metrics" in report

    report = evaluation.evaluate_with_index(
        dataset,
        UncalledIndex(),
        observed_archive_manifest_sha256=_sha("c"),
        observed_index_db_sha256=_sha("e"),
    )
    assert report["evaluation_status"] == "not_evaluable"
    assert "fts_profile_mismatch" in report["reasons"]
    assert "vector_profile_mismatch" in report["reasons"]


def test_vector_failure_is_reported_without_fts_fallback():
    dataset = _valid_contract_fixture()

    class VectorFailureIndex:
        profile_id = "fts5:test"
        vector_profile_id = "vec:test"
        vector_error_message = None
        _embedding_backend = SimpleNamespace(config={"model_sha256": _sha("f")}, dimension=1024)

        def __init__(self):
            self.keyword_calls = 0
            self.vector_calls = 0
            self.hybrid_calls = 0

        def search_keyword(self, query, *, limit, content_ids):
            self.keyword_calls += 1
            return ()

        def search_vector(self, query, *, limit, content_ids):
            self.vector_calls += 1
            raise RuntimeError("synthetic unavailable backend")

        def search_hybrid(self, query, *, limit, content_ids):
            self.hybrid_calls += 1
            return ()

    index = VectorFailureIndex()
    report = evaluation.evaluate_with_index(
        dataset,
        index,
        observed_archive_manifest_sha256=_sha("c"),
        observed_index_db_sha256=_sha("e"),
    )

    assert index.keyword_calls == index.vector_calls == index.hybrid_calls == 60
    assert report["retrieval_methods"]["vector"]["aggregate"]["status"] == "error"
    assert report["retrieval_methods"]["keyword"]["aggregate"]["status"] == "completed"
    assert report["retrieval_quality_gate_status"] == "not_evaluable"
    assert report["retrieval_methods"]["vector"]["cases"][0]["error_class"] == "RuntimeError"


def test_manifest_content_ids_must_match_frozen_snapshot():
    dataset = _valid_contract_fixture()
    matching = {
        "selected": [{"content_id": "content-a"}, {"content_id": "content-b"}],
    }
    assert evaluation._manifest_snapshot_issues(dataset, matching) == []

    missing_content = {"selected": [{"content_id": "content-a"}]}
    assert evaluation._manifest_snapshot_issues(dataset, missing_content) == [
        "snapshot_manifest_content_ids_mismatch"
    ]

    duplicate_content = {
        "selected": [{"content_id": "content-a"}, {"content_id": "content-a"}],
    }
    assert evaluation._manifest_snapshot_issues(dataset, duplicate_content) == [
        "snapshot_manifest_content_ids_invalid"
    ]


def test_read_only_backup_preserves_source_and_copies_sqlite_contents(tmp_path):
    source = tmp_path / "source.sqlite"
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample VALUES ('frozen')")
    source_sha = evaluation._hash_file(source)

    copy_path = evaluation._backup_index_database(source, scratch)

    assert copy_path != source
    assert copy_path.is_file()
    assert evaluation._hash_file(source) == source_sha
    with sqlite3.connect(copy_path) as connection:
        assert connection.execute("SELECT value FROM sample").fetchone() == ("frozen",)
    with pytest.raises(FileExistsError):
        evaluation._backup_index_database(source, scratch)


def test_product_ask_index_initializes_only_the_isolated_copy(tmp_path, monkeypatch):
    source = tmp_path / "existing-index.sqlite"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO marker VALUES ('keep-source')")
    source_sha = evaluation._hash_file(source)
    scratch = tmp_path / "run"
    scratch.mkdir()
    archive_root = tmp_path / "archives"
    archive_root.mkdir()
    copy_path = evaluation._backup_index_database(source, scratch)
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)

    index = evaluation._load_product_index(copy_path, archive_root, scratch)
    try:
        assert Path(index.store.engine.url.database).resolve() == copy_path.resolve()
    finally:
        index.close()
        index.store.engine.dispose()

    assert evaluation._hash_file(source) == source_sha
    with sqlite3.connect(copy_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "ask_index_fts" in tables


def test_scratch_directory_must_be_new_and_git_ignored(tmp_path):
    repository = evaluation._repo_root()
    ignored_path = repository / "product" / "local" / "ai-ask-evaluation" / "new-run-only"
    assert evaluation._is_ignored_evaluation_path(ignored_path)
    assert not evaluation._is_ignored_evaluation_path(
        repository / "product" / "src" / "services" / "core" / "not-ignored"
    )

    existing = tmp_path / "existing"
    existing.mkdir()
    assert (
        evaluation._validate_scratch_directory(
            existing,
            input_paths=(),
            archive_root=tmp_path / "archives",
        )
        == "scratch_directory_must_be_new"
    )


def test_report_writer_never_overwrites_or_targets_input(tmp_path):
    existing_report = tmp_path / "old-report.json"
    existing_report.write_text("preserve", encoding="utf-8")
    with pytest.raises(FileExistsError):
        evaluation._write_report({"evaluation_status": "not_evaluable"}, existing_report)
    assert existing_report.read_text(encoding="utf-8") == "preserve"

    source = tmp_path / "source.sqlite"
    source.write_bytes(b"read-only")
    with pytest.raises(ValueError):
        evaluation._write_report(
            {"evaluation_status": "not_evaluable"},
            source,
            forbidden_paths=(source,),
        )
    assert source.read_bytes() == b"read-only"


def test_retrieval_exit_codes_do_not_claim_answer_layer_passed():
    completed = {
        "evaluation_status": "completed",
        "retrieval_quality_gate_status": "pass",
        "overall_quality_gate_status": "not_evaluable",
    }
    assert evaluation._exit_code(completed) == 0
    assert evaluation._exit_code({**completed, "retrieval_quality_gate_status": "fail"}) == 1
    assert (
        evaluation._exit_code({**completed, "retrieval_quality_gate_status": "not_evaluable"}) == 2
    )
    assert evaluation._exit_code({"evaluation_status": "not_evaluable"}) == 2


def test_cli_candidate_input_is_metadata_only_and_never_evaluated(tmp_path, monkeypatch, capsys):
    candidate_file = tmp_path / "pending-candidates.json"
    candidate_file.write_text(
        json.dumps(
            {
                "schema_version": "m1-question-card-candidates-v5",
                "cases": [
                    {
                        "case_id": "M1D-001",
                        "question": "synthetic pending question",
                        "is_gold": False,
                        "human_final_review": {"status": "pending"},
                        "required_evidence_verified": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["ai_ask_retrieval_eval", "--candidate-file", str(candidate_file)],
    )

    assert evaluation._cli() == 2

    report = json.loads(capsys.readouterr().out)
    assert report["evaluation_status"] == "not_evaluable"
    assert report["gold_count"] == 0
    assert report["retrieval_metrics"] == "not_evaluated"
    assert "synthetic pending question" not in json.dumps(report)
