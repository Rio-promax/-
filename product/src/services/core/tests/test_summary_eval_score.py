import importlib.util
from copy import deepcopy
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "summary_eval_score", Path(__file__).parents[1] / "tools/summary_eval_score.py"
)
scoring = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scoring)


def reviews(score=9):
    review = {"fidelity": score, "coverage": score, "format": score,
              "reading": {key: score for key in ("clarity", "coherence", "burden")},
              "reasons": {key: "原始评分原因" for key in ("fidelity", "coverage", "reading", "format")},
              "issues": []}
    return {"protocol": "summary-review-v2", "stage": "full",
            "reviews": {label: deepcopy(review) for label in scoring.VERSIONS}}


def test_exactly_nine_continues_and_reading_has_forty_percent():
    data = reviews()
    assert scoring.calculate(data)["status"] == "below_threshold"
    for review in data["reviews"].values():
        review.update(fidelity=5, coverage=5, format=10)
        review["reading"] = dict(clarity=10, coherence=10, burden=10)
    assert scoring.calculate(data)["overall"] == "8"
    for review in data["reviews"].values():
        review["reading"] = dict(clarity=10, coherence=7, burden=4)
    assert scoring.calculate(data)["overall"] == "6.8"


def test_missing_version_and_screen_cannot_pass():
    data = reviews(10)
    del data["reviews"]["详细"]
    result = scoring.calculate(data)
    assert result["status"] == "incomplete" and result["overall"] is None
    data["stage"] = "screen"
    assert scoring.calculate(data)["status"] == "screen_only"


def test_severe_or_unresolved_issue_blocks_high_score():
    for severity in ("severe", "uncertain"):
        data = reviews(10)
        data["reviews"]["通用"]["issues"] = [{"severity": severity, "core": True}]
        assert scoring.calculate(data)["status"] == "blocked"
    result = scoring.calculate(reviews(10))
    assert result["status"] == "score_threshold_met"
    assert result["promotion"] == "not_authorized_by_score_alone"
