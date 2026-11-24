"""Local, retrieval-only evaluator for a manually frozen AI-ask gold set.

Gold input contract (`ai-ask-retrieval-gold-v1`; documentation only, no sample
gold set is shipped):

* Top level: `dataset_status="frozen"`, a frozen `snapshot` with `snapshot_id`,
  `archive_manifest_sha256`, `index_db_sha256`, and the complete `content_ids`;
  `profiles` with `fts_profile_id`, `vector_profile_id`, `model_sha256`, and
  `dimension`; `key_recall_categories`; and `cases`.
* Each case: `case_id`, `question`, `categories`, `answerability`, explicit
  non-empty `scope_content_ids`, matching `snapshot_id`, `review` with
  `status="approved"`, `approved_by_human=true`, `reviewer_ref`,
  `evidence_verified=true`, and `required_evidence`.
* Each required evidence item is the exact tuple
  `(content_id, source_kind, location_kind, source_ref, text_hash)` from the
  frozen archive mapping. Negative-answer cases instead require a human-verified
  `negative_evidence_audit` tied to the same snapshot and exact scope.

The schema declares human work; it cannot prove that a declaration is truthful.
The evaluator rejects candidate schemas and incomplete declarations. Synthetic
unit fixtures below exercise only the scoring mechanics and are not gold data or
quality evidence. Per-case output intentionally excludes questions, hit text,
source references, URLs, and filesystem paths.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote

GOLD_SCHEMA = "ai-ask-retrieval-gold-v1"
METHODS = ("keyword", "vector", "hybrid")
ANSWERABLE = "answerable"
NEGATIVE_ANSWERABILITY = {"scope_no_answer", "corpus_no_answer"}
SUPPORTED_ANSWERABILITY = {ANSWERABLE, "partial_coverage", *NEGATIVE_ANSWERABILITY}
REQUIRED_CATEGORIES = (
    "fact",
    "numeric_proper_name",
    "synonym",
    "cross_content_all_evidence",
    "follow_up",
    "summary_only",
    "partial_coverage",
    "conflicting_claims",
    "scope_no_answer",
    "corpus_no_answer",
)
NO_ANSWER_CATEGORIES = {"scope_no_answer", "corpus_no_answer"}
THRESHOLDS = {
    "minimum_human_reviewed_cases": 60,
    "minimum_cases_per_category": 5,
    "overall_case_recall_at_5": 0.90,
    "key_category_case_recall_at_5": 0.80,
    "cross_content_all_evidence_at_10": 0.85,
    "scope_violations": 0,
    "scope_no_answer_correct_refusal": 0.90,
    "corpus_no_answer_correct_refusal": 0.90,
}
SHA256_LENGTH = 64
SAFE_LABEL = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != SHA256_LENGTH:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def evidence_key(item: Any) -> tuple[str, str, str, str, str] | None:
    """Extract the exact source-mapped evidence identity without normalization."""
    if isinstance(item, Mapping):
        values = tuple(
            item.get(field)
            for field in (
                "content_id",
                "source_kind",
                "location_kind",
                "source_ref",
                "text_hash",
            )
        )
    else:
        values = tuple(
            getattr(item, field, None)
            for field in (
                "content_id",
                "source_kind",
                "location_kind",
                "source_ref",
                "text_hash",
            )
        )
    if not all(isinstance(value, str) and value for value in values):
        return None
    return values  # type: ignore[return-value]


def _case_evidence_key(case: Mapping[str, Any], field: str) -> str:
    encoded = json.dumps(case[field], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def validate_gold_dataset(dataset: Any) -> list[str]:
    """Return stable gate codes; never echo untrusted prompt or source text."""
    issues: list[str] = []
    if not isinstance(dataset, Mapping) or dataset.get("schema_version") != GOLD_SCHEMA:
        return ["gold_schema_required"]
    if dataset.get("dataset_status") != "frozen":
        issues.append("dataset_not_frozen")

    snapshot = dataset.get("snapshot")
    if not isinstance(snapshot, Mapping):
        issues.append("snapshot_missing")
        snapshot = {}
    snapshot_id = snapshot.get("snapshot_id")
    if not _safe_label(snapshot_id):
        issues.append("snapshot_id_missing")
    if not _is_sha256(snapshot.get("archive_manifest_sha256")):
        issues.append("archive_manifest_sha256_invalid")
    if not _is_sha256(snapshot.get("index_db_sha256")):
        issues.append("index_db_sha256_invalid")
    content_ids = snapshot.get("content_ids")
    if not _valid_string_list(content_ids, allow_empty=False) or len(content_ids) != len(
        set(content_ids)
    ):
        issues.append("snapshot_content_ids_invalid")
        content_ids = []

    profiles = dataset.get("profiles")
    if not isinstance(profiles, Mapping):
        issues.append("profile_missing")
        profiles = {}
    if not _nonempty_string(profiles.get("fts_profile_id")):
        issues.append("fts_profile_missing")
    if not _nonempty_string(profiles.get("vector_profile_id")):
        issues.append("vector_profile_missing")
    if not _is_sha256(profiles.get("model_sha256")):
        issues.append("model_sha256_invalid")
    if not isinstance(profiles.get("dimension"), int) or profiles.get("dimension", 0) < 1:
        issues.append("vector_dimension_invalid")

    key_categories = dataset.get("key_recall_categories")
    if (
        not _valid_string_list(key_categories, allow_empty=False)
        or any(category not in REQUIRED_CATEGORIES for category in key_categories)
        or any(category in NO_ANSWER_CATEGORIES for category in key_categories)
    ):
        issues.append("key_recall_categories_invalid")
        key_categories = []

    cases = dataset.get("cases")
    if not isinstance(cases, list):
        issues.append("cases_missing")
        cases = []
    if len(cases) < THRESHOLDS["minimum_human_reviewed_cases"]:
        issues.append("minimum_case_count_not_met")

    seen_ids: set[str] = set()
    category_counts: Counter[str] = Counter()
    key_category_answerable_counts: Counter[str] = Counter()
    for case in cases:
        if not isinstance(case, Mapping):
            issues.append("case_shape_invalid")
            continue
        case_id = case.get("case_id")
        if not _safe_label(case_id):
            issues.append("case_id_missing")
        elif case_id in seen_ids:
            issues.append("case_id_duplicate")
        else:
            seen_ids.add(case_id)
        if not _nonempty_string(case.get("question")):
            issues.append("question_missing")

        categories = case.get("categories")
        if not _valid_string_list(categories, allow_empty=False):
            issues.append("case_categories_invalid")
            categories = []
        if any(category not in REQUIRED_CATEGORIES for category in categories):
            issues.append("case_category_unknown")
        category_counts.update(
            category for category in categories if category in REQUIRED_CATEGORIES
        )

        review = case.get("review")
        if (
            not isinstance(review, Mapping)
            or review.get("status") != "approved"
            or review.get("approved_by_human") is not True
            or not _nonempty_string(review.get("reviewer_ref"))
        ):
            issues.append("human_review_missing")
        if not isinstance(review, Mapping) or review.get("evidence_verified") is not True:
            issues.append("evidence_verification_missing")
        if case.get("is_gold") is not True:
            issues.append("gold_approval_missing")
        if case.get("snapshot_id") != snapshot_id:
            issues.append("case_snapshot_mismatch")

        scope = case.get("scope_content_ids")
        if not _valid_string_list(scope, allow_empty=False) or len(scope) != len(set(scope)):
            issues.append("case_scope_invalid")
            scope = []
        if not set(scope).issubset(set(content_ids)):
            issues.append("case_scope_outside_snapshot")

        answerability = case.get("answerability")
        if answerability not in SUPPORTED_ANSWERABILITY:
            issues.append("answerability_invalid")
        required = case.get("required_evidence")
        if not isinstance(required, list):
            issues.append("required_evidence_missing")
            required = []
        if answerability in NEGATIVE_ANSWERABILITY:
            if required:
                issues.append("negative_case_has_positive_evidence")
            _validate_negative_audit(case, snapshot, scope, issues)
            expected_category = answerability
            if expected_category not in categories:
                issues.append("negative_case_category_mismatch")
        else:
            if not required:
                issues.append("answerable_case_evidence_missing")
            case_keys: set[tuple[str, str, str, str, str]] = set()
            for evidence in required:
                key = evidence_key(evidence)
                if key is None or not _is_sha256(key[4]):
                    issues.append("evidence_identity_invalid")
                    continue
                if key in case_keys:
                    issues.append("evidence_identity_duplicate")
                case_keys.add(key)
                if key[0] not in scope:
                    issues.append("evidence_outside_case_scope")
            if (
                "cross_content_all_evidence" in categories
                and len({key[0] for key in case_keys}) < 2
            ):
                issues.append("cross_content_evidence_not_cross_content")
            if answerability == "partial_coverage" and "partial_coverage" not in categories:
                issues.append("partial_coverage_category_mismatch")
            if answerability == ANSWERABLE:
                key_category_answerable_counts.update(
                    category for category in categories if category in key_categories
                )

    for category in REQUIRED_CATEGORIES:
        if category_counts[category] < THRESHOLDS["minimum_cases_per_category"]:
            issues.append(f"category_minimum_not_met:{category}")
    for category in key_categories:
        if key_category_answerable_counts[category] < THRESHOLDS["minimum_cases_per_category"]:
            issues.append(f"key_category_answerable_minimum_not_met:{category}")

    return list(dict.fromkeys(issues))


def _validate_negative_audit(
    case: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    scope: Sequence[str],
    issues: list[str],
) -> None:
    audit = case.get("negative_evidence_audit")
    if not isinstance(audit, Mapping):
        issues.append("negative_evidence_audit_missing")
        return
    if audit.get("human_verified") is not True or not _nonempty_string(audit.get("reviewer_ref")):
        issues.append("negative_evidence_audit_unverified")
    if audit.get("snapshot_id") != snapshot.get("snapshot_id"):
        issues.append("negative_evidence_snapshot_mismatch")
    if audit.get("archive_manifest_sha256") != snapshot.get("archive_manifest_sha256"):
        issues.append("negative_evidence_manifest_mismatch")
    audit_scope = audit.get("scope_content_ids")
    if not _valid_string_list(audit_scope, allow_empty=False) or set(audit_scope) != set(scope):
        issues.append("negative_evidence_scope_mismatch")
    if not _is_sha256(audit.get("audit_artifact_sha256")):
        issues.append("negative_evidence_audit_artifact_missing")
    if case.get("answerability") == "corpus_no_answer":
        if set(scope) != set(snapshot.get("content_ids", [])):
            issues.append("corpus_no_answer_scope_incomplete")


def _valid_string_list(value: Any, *, allow_empty: bool) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _safe_label(value: Any) -> bool:
    return isinstance(value, str) and SAFE_LABEL.fullmatch(value) is not None


def summarize_candidate_files(paths: Sequence[Path]) -> dict[str, Any]:
    """Return metadata-only candidate status; never treat candidates as gold."""
    per_file: list[dict[str, Any]] = []
    total_cases = gold_declared = human_approved = evidence_verified = 0
    distinct_case_ids: set[str] = set()
    duplicate_case_records = 0
    schema_versions: list[str] = []
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        cases = data.get("cases") if isinstance(data, Mapping) else None
        if not isinstance(cases, list):
            cases = []
        file_gold = file_approved = file_verified = 0
        for case in cases:
            if not isinstance(case, Mapping):
                continue
            case_id = case.get("case_id")
            if _safe_label(case_id):
                if case_id in distinct_case_ids:
                    duplicate_case_records += 1
                else:
                    distinct_case_ids.add(case_id)
            file_gold += int(case.get("is_gold") is True)
            review = case.get("human_final_review")
            file_approved += int(
                isinstance(review, Mapping)
                and review.get("status") in {"approved", "已审核", "human_approved"}
            )
            file_verified += int(
                case.get("required_evidence_verified") is True
                or case.get("negative_evidence_verified") is True
            )
        raw_schema = data.get("schema_version") if isinstance(data, Mapping) else None
        schema = raw_schema if _safe_label(raw_schema) else "unknown"
        schema_versions.append(schema)
        per_file.append(
            {
                "schema_version": schema,
                "case_count": len(cases),
                "gold_declared_count": file_gold,
                "human_approved_count": file_approved,
                "evidence_verified_count": file_verified,
                "status": "not_evaluable",
            }
        )
        total_cases += len(cases)
        gold_declared += file_gold
        human_approved += file_approved
        evidence_verified += file_verified
    return {
        "evaluation_status": "not_evaluable",
        "dataset_kind": "untrusted_candidate_cards",
        "schema_versions": schema_versions,
        "case_count": total_cases,
        "distinct_case_count": len(distinct_case_ids),
        "duplicate_case_record_count": duplicate_case_records,
        "gold_declared_count": gold_declared,
        "human_approved_count": human_approved,
        "evidence_verified_count": evidence_verified,
        "gold_count": 0,
        "reasons": [
            "candidate_cards_are_not_gold",
            "human_review_and_evidence_verification_required",
        ],
        "files": per_file,
        "retrieval_metrics": "not_evaluated",
        "answer_layer_metrics": "not_evaluated",
        "overall_quality_gate_status": "not_evaluable",
    }


def evidence_recall_at_k(
    required_evidence: Sequence[Any], hits: Sequence[Any], k: int
) -> float | None:
    required = {key for item in required_evidence if (key := evidence_key(item)) is not None}
    if not required:
        return None
    found = {key for hit in hits[:k] if (key := evidence_key(hit)) in required}
    return len(found) / len(required)


def all_required_evidence_at_k(
    required_evidence: Sequence[Any], hits: Sequence[Any], k: int
) -> bool | None:
    required = {key for item in required_evidence if (key := evidence_key(item)) is not None}
    if not required:
        return None
    found = {key for hit in hits[:k] if (key := evidence_key(hit)) in required}
    return required.issubset(found)


def case_recall_at_k(required_evidence: Sequence[Any], hits: Sequence[Any], k: int) -> bool | None:
    """Count a question once when at least one exact approved evidence item is found."""
    fraction = evidence_recall_at_k(required_evidence, hits, k)
    return None if fraction is None else fraction > 0


def _redacted_hit_list(
    hits: Sequence[Any], allowed_ids: set[str]
) -> tuple[list[dict[str, Any]], int]:
    result: list[dict[str, Any]] = []
    violations = 0
    for rank, hit in enumerate(hits[:10], start=1):
        key = evidence_key(hit)
        if key is None:
            result.append({"rank": rank, "evidence_key": None, "in_scope": False})
            violations += 1
            continue
        in_scope = key[0] in allowed_ids
        violations += int(not in_scope)
        digest = hashlib.sha256(
            json.dumps(key, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:16]
        result.append({"rank": rank, "evidence_key": digest, "in_scope": in_scope})
    return result, violations


def _case_method_result(case: Mapping[str, Any], hits: Sequence[Any]) -> tuple[dict[str, Any], int]:
    allowed = set(case["scope_content_ids"])
    safe_hits, violations = _redacted_hit_list(hits, allowed)
    required = case.get("required_evidence", [])
    answerable = case.get("answerability") not in NEGATIVE_ANSWERABILITY
    result: dict[str, Any] = {
        "status": "completed",
        "hits": safe_hits,
        "scope_violation_count": violations,
    }
    if answerable:
        result["case_recall_at_5"] = case_recall_at_k(required, hits, 5)
        result["case_recall_at_10"] = case_recall_at_k(required, hits, 10)
        result["evidence_recall_at_5"] = evidence_recall_at_k(required, hits, 5)
        result["evidence_recall_at_10"] = evidence_recall_at_k(required, hits, 10)
        if "cross_content_all_evidence" in case.get("categories", []):
            result["all_required_evidence_at_10"] = all_required_evidence_at_k(required, hits, 10)
    else:
        result["case_recall_at_5"] = "not_applicable"
        result["case_recall_at_10"] = "not_applicable"
        result["evidence_recall_at_5"] = "not_applicable"
        result["evidence_recall_at_10"] = "not_applicable"
        result["correct_refusal"] = "not_evaluated"
    return result, violations


def _macro_average(values: Iterable[float]) -> float | None:
    numbers = list(values)
    if not numbers:
        return None
    return sum(numbers) / len(numbers)


def _aggregate_method(
    dataset: Mapping[str, Any], case_results: Sequence[Mapping[str, Any]], status: str
) -> dict[str, Any]:
    if status != "completed":
        return {
            "status": status,
            "case_recall_at_5": "not_evaluated",
            "case_recall_at_10": "not_evaluated",
            "evidence_recall_at_5": "not_evaluated",
            "evidence_recall_at_10": "not_evaluated",
            "category_evidence_recall_at_5": "not_evaluated",
            "cross_content_all_evidence_at_10": "not_evaluated",
            "scope_violation_count": sum(
                int(row.get("scope_violation_count", 0)) for row in case_results
            ),
        }
    cases = dataset["cases"]
    by_id = {row["case_id"]: row for row in case_results}
    positive_cases = [
        case for case in cases if case.get("answerability") not in NEGATIVE_ANSWERABILITY
    ]
    if any(case["case_id"] not in by_id for case in positive_cases):
        return {"status": "incomplete", "case_recall_at_5": "not_evaluated"}
    all_rows = [by_id[case["case_id"]] for case in positive_cases]
    case_recall5 = _macro_average(float(row["case_recall_at_5"]) for row in all_rows)
    case_recall10 = _macro_average(float(row["case_recall_at_10"]) for row in all_rows)
    recall5 = _macro_average(row["evidence_recall_at_5"] for row in all_rows)
    recall10 = _macro_average(row["evidence_recall_at_10"] for row in all_rows)
    category_metrics: dict[str, Any] = {}
    for category in REQUIRED_CATEGORIES:
        selected = [
            by_id[case["case_id"]]
            for case in positive_cases
            if category in case.get("categories", [])
        ]
        if selected:
            category_metrics[category] = {
                "case_count": len(selected),
                "case_recall_at_5": _macro_average(
                    float(row["case_recall_at_5"]) for row in selected
                ),
                "evidence_recall_at_5": _macro_average(
                    row["evidence_recall_at_5"] for row in selected
                ),
            }
    cross_cases = [
        by_id[case["case_id"]]
        for case in positive_cases
        if "cross_content_all_evidence" in case.get("categories", [])
    ]
    cross_complete = (
        sum(bool(row.get("all_required_evidence_at_10")) for row in cross_cases) / len(cross_cases)
        if cross_cases
        else None
    )
    scope_violations = sum(int(row.get("scope_violation_count", 0)) for row in case_results)
    key_categories = dataset["key_recall_categories"]
    retrieval_failures = []
    if case_recall5 is None or case_recall5 < THRESHOLDS["overall_case_recall_at_5"]:
        retrieval_failures.append("overall_case_recall_at_5_below_threshold")
    for category in key_categories:
        metric = category_metrics.get(category, {}).get("case_recall_at_5")
        if metric is None or metric < THRESHOLDS["key_category_case_recall_at_5"]:
            retrieval_failures.append(f"key_category_recall_at_5_below_threshold:{category}")
    if cross_complete is None or cross_complete < THRESHOLDS["cross_content_all_evidence_at_10"]:
        retrieval_failures.append("cross_content_all_evidence_at_10_below_threshold")
    if scope_violations:
        retrieval_failures.append("scope_violation_detected")
    return {
        "status": "completed",
        "case_recall_at_5": case_recall5,
        "case_recall_at_10": case_recall10,
        "evidence_recall_at_5": recall5,
        "evidence_recall_at_10": recall10,
        "category_evidence_recall_at_5": category_metrics,
        "cross_content_all_evidence_at_10": cross_complete,
        "cross_content_case_count": len(cross_cases),
        "scope_violation_count": scope_violations,
        "retrieval_gate_status": "fail" if retrieval_failures else "pass",
        "retrieval_gate_failures": retrieval_failures,
    }


def evaluate_with_index(
    dataset: Mapping[str, Any],
    index: Any,
    *,
    observed_archive_manifest_sha256: str,
    observed_index_db_sha256: str,
) -> dict[str, Any]:
    """Run three independent retrieval paths; errors never trigger fallback."""
    issues = validate_gold_dataset(dataset)
    if issues:
        return _not_evaluable_report(issues, _safe_snapshot(dataset))
    snapshot = dataset["snapshot"]
    if observed_archive_manifest_sha256 != snapshot["archive_manifest_sha256"]:
        return _not_evaluable_report(
            ["archive_manifest_snapshot_mismatch"], _safe_snapshot(dataset)
        )
    if observed_index_db_sha256 != snapshot["index_db_sha256"]:
        return _not_evaluable_report(["index_db_snapshot_mismatch"], _safe_snapshot(dataset))
    profile_issues = _profile_mismatches(dataset["profiles"], index)
    if profile_issues:
        return _not_evaluable_report(profile_issues, _safe_snapshot(dataset))

    method_rows: dict[str, list[dict[str, Any]]] = {method: [] for method in METHODS}
    method_status = {method: "completed" for method in METHODS}
    per_case: list[dict[str, Any]] = []
    searchers = {
        "keyword": index.search_keyword,
        "vector": index.search_vector,
        "hybrid": index.search_hybrid,
    }
    for case in dataset["cases"]:
        case_row: dict[str, Any] = {"case_id": case["case_id"], "categories": case["categories"]}
        for method in METHODS:
            try:
                hits = searchers[method](
                    case["question"],
                    limit=10,
                    content_ids=list(case["scope_content_ids"]),
                )
                result, _ = _case_method_result(case, hits)
            except Exception as error:  # Query text and exception text can contain private input.
                result = {"status": "error", "error_class": type(error).__name__}
                method_status[method] = "error"
            result["case_id"] = case["case_id"]
            method_rows[method].append(result)
            case_row[method] = result
        per_case.append(case_row)

    method_reports = {
        method: {
            "cases": method_rows[method],
            "aggregate": _aggregate_method(dataset, method_rows[method], method_status[method]),
        }
        for method in METHODS
    }
    method_statuses = [report["aggregate"].get("status") for report in method_reports.values()]
    retrieval_status = (
        method_reports["hybrid"]["aggregate"].get("retrieval_gate_status", "not_evaluable")
        if all(status == "completed" for status in method_statuses)
        else "not_evaluable"
    )
    return {
        "evaluation_status": "completed",
        "dataset_kind": "human_frozen_gold_declaration",
        "snapshot": _safe_snapshot(dataset),
        "gold_case_count": len(dataset["cases"]),
        "answerability_case_counts": dict(
            Counter(str(case["answerability"]) for case in dataset["cases"])
        ),
        "gate_thresholds": dict(THRESHOLDS),
        "metric_definitions": {
            "case_recall_at_k": (
                "Fraction of answerable questions with at least one exact approved "
                "evidence tuple in top-k."
            ),
            "evidence_recall_at_k": (
                "Diagnostic macro average of exact required tuples in top-k divided "
                "by required tuple count."
            ),
            "cross_content_all_evidence_at_10": (
                "Fraction of cross-content cases with every exact required tuple in top 10."
            ),
            "scope_violation_count": (
                "Number of hits outside a case's explicit frozen content scope."
            ),
        },
        "retrieval_methods": method_reports,
        "answer_layer_metrics": {
            "status": "not_evaluated",
            "metrics": {
                "scope_no_answer_correct_refusal": "not_evaluated",
                "corpus_no_answer_correct_refusal": "not_evaluated",
                "fabricated_citations": "not_evaluated",
                "fabricated_times": "not_evaluated",
                "answer_fact_correctness": "not_evaluated",
            },
            "reason": "retrieval_only_executor_does_not_run_answer_generation",
        },
        "retrieval_quality_gate_status": retrieval_status,
        "retrieval_quality_gate_method": "hybrid",
        "overall_quality_gate_status": "not_evaluable",
        "overall_quality_gate_reason": "answer_layer_metrics_are_not_evaluated",
    }


def _profile_mismatches(expected: Mapping[str, Any], index: Any) -> list[str]:
    issues: list[str] = []
    if getattr(index, "profile_id", None) != expected.get("fts_profile_id"):
        issues.append("fts_profile_mismatch")
    if getattr(index, "vector_profile_id", None) != expected.get("vector_profile_id"):
        issues.append("vector_profile_mismatch")
    backend = getattr(index, "_embedding_backend", None)
    config = getattr(backend, "config", {}) if backend is not None else {}
    if not isinstance(config, Mapping) or config.get("model_sha256") != expected.get(
        "model_sha256"
    ):
        issues.append("model_sha256_mismatch")
    if getattr(backend, "dimension", None) != expected.get("dimension"):
        issues.append("vector_dimension_mismatch")
    if getattr(index, "vector_error_message", None):
        issues.append("vector_backend_unavailable")
    return issues


def _safe_snapshot(dataset: Any) -> dict[str, Any] | None:
    if not isinstance(dataset, Mapping):
        return None
    snapshot = dataset.get("snapshot")
    if not isinstance(snapshot, Mapping):
        return None
    return {
        "snapshot_id": snapshot.get("snapshot_id")
        if _safe_label(snapshot.get("snapshot_id"))
        else None,
        "archive_manifest_sha256": snapshot.get("archive_manifest_sha256")
        if _is_sha256(snapshot.get("archive_manifest_sha256"))
        else None,
    }


def _not_evaluable_report(issues: Sequence[str], snapshot: Any = None) -> dict[str, Any]:
    return {
        "evaluation_status": "not_evaluable",
        "dataset_kind": "untrusted_or_incomplete_gold_declaration",
        "snapshot": snapshot,
        "reasons": list(dict.fromkeys(issues)),
        "retrieval_metrics": "not_evaluated",
        "answer_layer_metrics": "not_evaluated",
        "overall_quality_gate_status": "not_evaluable",
    }


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=Path(__file__).resolve().parent,
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return Path(result.stdout.strip()).resolve()


def _is_ignored_evaluation_path(path: Path) -> bool:
    try:
        root = _repo_root()
        relative = path.expanduser().resolve().relative_to(root)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
        return False
    if relative.parts[:3] != ("product", "local", "ai-ask-evaluation"):
        return False
    try:
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", "--", relative.as_posix()],
            cwd=root,
            capture_output=True,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


def _paths_overlap(left: Path, right: Path) -> bool:
    left = left.expanduser().resolve()
    right = right.expanduser().resolve()
    return left == right or left in right.parents or right in left.parents


def _validate_scratch_directory(
    scratch_dir: Path,
    *,
    input_paths: Sequence[Path],
    archive_root: Path,
) -> str | None:
    scratch = scratch_dir.expanduser().resolve()
    if os.path.lexists(scratch):
        return "scratch_directory_must_be_new"
    if not _is_ignored_evaluation_path(scratch):
        return "scratch_directory_must_be_ignored_evaluation_path"
    if any(_paths_overlap(scratch, item) for item in input_paths):
        return "scratch_directory_overlaps_input"
    if _paths_overlap(scratch, archive_root):
        return "scratch_directory_overlaps_archive_root"
    return None


def _manifest_content_ids(manifest: Any) -> list[str] | None:
    """Read the frozen manifest's selected content identities without exposing them."""
    if not isinstance(manifest, Mapping):
        return None
    selected = manifest.get("selected")
    if not isinstance(selected, list) or not selected:
        return None
    content_ids: list[str] = []
    for row in selected:
        if not isinstance(row, Mapping) or not _nonempty_string(row.get("content_id")):
            return None
        content_ids.append(row["content_id"])
    if len(content_ids) != len(set(content_ids)):
        return None
    return content_ids


def _manifest_snapshot_issues(dataset: Mapping[str, Any], manifest: Any) -> list[str]:
    manifest_ids = _manifest_content_ids(manifest)
    if manifest_ids is None:
        return ["snapshot_manifest_content_ids_invalid"]
    snapshot_ids = dataset["snapshot"]["content_ids"]
    if set(manifest_ids) != set(snapshot_ids) or len(manifest_ids) != len(snapshot_ids):
        return ["snapshot_manifest_content_ids_mismatch"]
    return []


def _source_file_state(index_db: Path) -> dict[str, Any]:
    """Fingerprint the SQLite file and sidecars without returning their paths."""
    result: dict[str, Any] = {}
    for label, path in (
        ("database", index_db),
        ("wal", index_db.with_name(index_db.name + "-wal")),
        ("shared_memory", index_db.with_name(index_db.name + "-shm")),
    ):
        if path.is_file():
            result[label] = {
                "exists": True,
                "size_bytes": path.stat().st_size,
                "sha256": _hash_file(path),
            }
        else:
            result[label] = {"exists": False}
    return result


def _backup_index_database(index_db: Path, scratch_dir: Path) -> Path:
    """Copy a frozen SQLite source through a read-only connection to a new file."""
    source_path = index_db.expanduser().resolve()
    backup_path = scratch_dir.resolve() / "index-snapshot.sqlite"
    if os.path.lexists(backup_path):
        raise FileExistsError("scratch_index_copy_already_exists")
    source_uri = f"file:{quote(source_path.as_posix(), safe='/:')}?mode=ro"
    source = None
    target = None
    try:
        source = sqlite3.connect(source_uri, uri=True)
        source.execute("PRAGMA query_only=ON")
        descriptor = os.open(backup_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.close(descriptor)
        target = sqlite3.connect(backup_path)
        source.backup(target)
        target.commit()
    finally:
        if target is not None:
            target.close()
        if source is not None:
            source.close()
    return backup_path


def _write_report(
    report: Mapping[str, Any],
    output: Path | None,
    *,
    forbidden_paths: Sequence[Path] = (),
    archive_root: Path | None = None,
    must_be_within: Path | None = None,
) -> None:
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output is None:
        print(encoded, end="")
        return
    target = output.expanduser().resolve()
    if any(target == item.expanduser().resolve() for item in forbidden_paths):
        raise ValueError("report_output_conflicts_with_input")
    if archive_root is not None:
        archive = archive_root.expanduser().resolve()
        if target == archive or archive in target.parents:
            raise ValueError("report_output_conflicts_with_archive")
    if must_be_within is not None:
        try:
            target.relative_to(must_be_within.expanduser().resolve())
        except ValueError as error:
            raise ValueError("report_output_must_be_within_scratch") from error
    if os.path.lexists(output):
        raise FileExistsError("report_output_must_be_new")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(encoded)
    print(
        json.dumps(
            {"report_written": True, "evaluation_status": report.get("evaluation_status")},
            ensure_ascii=False,
        )
    )


def _emit_report(
    report: Mapping[str, Any],
    output: Path | None,
    *,
    forbidden_paths: Sequence[Path] = (),
    archive_root: Path | None = None,
    must_be_within: Path | None = None,
) -> bool:
    try:
        _write_report(
            report,
            output,
            forbidden_paths=forbidden_paths,
            archive_root=archive_root,
            must_be_within=must_be_within,
        )
    except (OSError, ValueError):
        print(json.dumps(_not_evaluable_report(["report_output_refused"]), ensure_ascii=False))
        return False
    return True


def _load_product_index(index_db: Path, archive_root: Path, scratch_dir: Path) -> Any:
    # Product imports and runtime side effects stay within this new ignored run directory.
    isolated = scratch_dir.resolve()
    for directory in (isolated / "logs", isolated / "pycache", isolated / "temp"):
        directory.mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = str(isolated / "temp")
    os.environ["TMP"] = str(isolated / "temp")
    os.environ["PRODUCT_LOG_DIR"] = str(isolated / "logs")
    os.environ["PYTHONPYCACHEPREFIX"] = str(isolated / "pycache")
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

    from app.db.store import SQLiteStore
    from app.knowledge.ask_index import AskIndex

    # SQLiteStore and AskIndex initialize schema/profile state, so they only see the copy.
    database_url = f"sqlite:///{index_db.resolve().as_posix()}"
    store = SQLiteStore(database_url)
    index = AskIndex(store, archive_root)
    index._evaluation_owned_store = store
    return index


def _exit_code(report: Mapping[str, Any]) -> int:
    if report.get("evaluation_status") != "completed":
        return 2
    status = report.get("retrieval_quality_gate_status")
    if status == "pass":
        return 0
    if status == "fail":
        return 1
    return 2


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Run local AI-ask retrieval evaluation.")
    parser.add_argument("--dataset", type=Path, help="Human-frozen gold declaration")
    parser.add_argument("--candidate-file", type=Path, action="append", default=[])
    parser.add_argument("--index-db", type=Path, help="Existing isolated evaluation SQLite DB")
    parser.add_argument("--archive-root", type=Path, help="Read-only archive root for the snapshot")
    parser.add_argument("--snapshot-manifest", type=Path, help="Frozen archive manifest")
    parser.add_argument(
        "--scratch-dir",
        type=Path,
        help="New ignored run directory under product/local/ai-ask-evaluation",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional new report file; existing files are never overwritten",
    )
    args = parser.parse_args()

    if args.candidate_file:
        if any(
            value is not None
            for value in (
                args.dataset,
                args.index_db,
                args.archive_root,
                args.snapshot_manifest,
                args.scratch_dir,
            )
        ):
            parser.error("candidate_file_mode_cannot_run_retrieval")
        if args.output is not None:
            parser.error("candidate_file_mode_writes_stdout_only")
        candidate_paths = [path.expanduser().resolve() for path in args.candidate_file]
        try:
            report = summarize_candidate_files(candidate_paths)
        except (OSError, UnicodeError, json.JSONDecodeError):
            report = _not_evaluable_report(["candidate_file_unreadable"])
        _emit_report(report, args.output, forbidden_paths=candidate_paths)
        return 2
    if args.dataset is None:
        parser.error("dataset_required")
    try:
        dataset_path = args.dataset.expanduser().resolve()
        dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        _emit_report(_not_evaluable_report(["dataset_file_unreadable"]), None)
        return 2
    issues = validate_gold_dataset(dataset)
    if issues:
        _emit_report(
            _not_evaluable_report(issues, _safe_snapshot(dataset)),
            None,
            forbidden_paths=(dataset_path,),
        )
        return 2
    if not all((args.index_db, args.archive_root, args.snapshot_manifest, args.scratch_dir)):
        parser.error("valid_gold_requires_index_db_archive_root_manifest_and_scratch_dir")

    index_db = args.index_db.expanduser().resolve()
    archive_root = args.archive_root.expanduser().resolve()
    manifest_path = args.snapshot_manifest.expanduser().resolve()
    scratch_dir = args.scratch_dir.expanduser().resolve()
    input_paths = (dataset_path, index_db, manifest_path)
    invalid_scratch = _validate_scratch_directory(
        scratch_dir,
        input_paths=input_paths,
        archive_root=archive_root,
    )
    if invalid_scratch is not None:
        _emit_report(
            _not_evaluable_report([invalid_scratch], _safe_snapshot(dataset)),
            None,
            forbidden_paths=input_paths,
            archive_root=archive_root,
        )
        return 2
    if not _is_ignored_evaluation_path(index_db):
        _emit_report(
            _not_evaluable_report(
                ["index_db_must_be_existing_ignored_evaluation_index"],
                _safe_snapshot(dataset),
            ),
            None,
            forbidden_paths=input_paths,
            archive_root=archive_root,
        )
        return 2
    if not index_db.is_file():
        _emit_report(
            _not_evaluable_report(["evaluation_db_not_found"], _safe_snapshot(dataset)),
            None,
            forbidden_paths=input_paths,
            archive_root=archive_root,
        )
        return 2
    if not archive_root.is_dir():
        _emit_report(
            _not_evaluable_report(["archive_root_not_found"], _safe_snapshot(dataset)),
            None,
            forbidden_paths=input_paths,
        )
        return 2
    if not manifest_path.is_file():
        _emit_report(
            _not_evaluable_report(["snapshot_manifest_not_found"], _safe_snapshot(dataset)),
            None,
            forbidden_paths=input_paths,
            archive_root=archive_root,
        )
        return 2
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        _emit_report(
            _not_evaluable_report(["snapshot_manifest_unreadable"], _safe_snapshot(dataset)),
            None,
            forbidden_paths=input_paths,
            archive_root=archive_root,
        )
        return 2

    observed_manifest_sha = _hash_file(manifest_path)
    observed_db_sha = _hash_file(index_db)
    manifest_issues = _manifest_snapshot_issues(dataset, manifest)
    if observed_manifest_sha != dataset["snapshot"]["archive_manifest_sha256"]:
        manifest_issues.append("archive_manifest_snapshot_mismatch")
    if manifest_issues:
        _emit_report(
            _not_evaluable_report(manifest_issues, _safe_snapshot(dataset)),
            None,
            forbidden_paths=input_paths,
            archive_root=archive_root,
        )
        return 2
    if observed_db_sha != dataset["snapshot"]["index_db_sha256"]:
        _emit_report(
            _not_evaluable_report(["index_db_snapshot_mismatch"], _safe_snapshot(dataset)),
            None,
            forbidden_paths=input_paths,
            archive_root=archive_root,
        )
        return 2

    if any(index_db.with_name(index_db.name + suffix).exists() for suffix in ("-wal", "-shm")):
        _emit_report(
            _not_evaluable_report(["index_db_has_live_sidecar"], _safe_snapshot(dataset)),
            None,
            forbidden_paths=input_paths,
            archive_root=archive_root,
        )
        return 2

    source_state_before = _source_file_state(index_db)
    try:
        scratch_dir.parent.mkdir(parents=True, exist_ok=True)
        scratch_dir.mkdir()
        index_copy = _backup_index_database(index_db, scratch_dir)
    except (OSError, sqlite3.Error, ValueError):
        _emit_report(
            _not_evaluable_report(["isolated_index_backup_failed"], _safe_snapshot(dataset)),
            args.output,
            forbidden_paths=(*input_paths, scratch_dir / "index-snapshot.sqlite"),
            archive_root=archive_root,
            must_be_within=scratch_dir,
        )
        return 2

    index = None
    close_failed = False
    try:
        index = _load_product_index(index_copy, archive_root, scratch_dir)
        report = evaluate_with_index(
            dataset,
            index,
            observed_archive_manifest_sha256=observed_manifest_sha,
            observed_index_db_sha256=observed_db_sha,
        )
    except Exception as error:
        report = _not_evaluable_report(
            [f"index_open_error:{type(error).__name__}"], _safe_snapshot(dataset)
        )
    finally:
        if index is not None:
            try:
                index.close()
                index._evaluation_owned_store.engine.dispose()
            except Exception:
                close_failed = True

    source_unchanged = source_state_before == _source_file_state(index_db)
    if not source_unchanged:
        report = _not_evaluable_report(
            ["source_index_changed_during_evaluation"], _safe_snapshot(dataset)
        )
    elif close_failed:
        report = _not_evaluable_report(
            ["evaluation_resources_failed_to_close"], _safe_snapshot(dataset)
        )
    report["input_integrity"] = {"source_index_unchanged": source_unchanged}
    report_output_ok = _emit_report(
        report,
        args.output,
        forbidden_paths=(*input_paths, index_copy),
        archive_root=archive_root,
        must_be_within=scratch_dir,
    )
    return _exit_code(report) if report_output_ok else 2


if __name__ == "__main__":
    raise SystemExit(_cli())
