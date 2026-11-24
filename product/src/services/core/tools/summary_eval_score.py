"""Calculate summary-review-v2 scores from preserved reviewer JSON; no model calls."""

import argparse
import json
from decimal import Decimal
from pathlib import Path

VERSIONS = ("详细", "通用", "简要")


def number(value):
    score = Decimal(str(value))
    if not score.is_finite() or not 0 <= score <= 10:
        raise ValueError("分数必须在0至10之间")
    return score


def calculate(data):
    if data["protocol"] != "summary-review-v2":
        raise ValueError("评审协议不匹配")
    stage = data["stage"]
    if stage not in ("screen", "full"):
        raise ValueError("阶段必须为screen或full")
    reviews = data["reviews"]
    scores = {}
    blocked = False
    for label, review in reviews.items():
        if label not in VERSIONS:
            raise ValueError("未知版型")
        for key in ("fidelity", "coverage", "reading", "format"):
            if not review["reasons"][key].strip():
                raise ValueError("必须保留逐维评分原因")
        reading = sum(number(review["reading"][key]) for key in (
            "clarity", "coherence", "burden"
        )) / 3
        score = (number(review["fidelity"]) + number(review["coverage"]) +
                 reading * 2 + number(review["format"])) / 5
        for issue in review["issues"]:
            if issue["severity"] not in ("severe", "general", "minor", "uncertain"):
                raise ValueError("未知问题等级")
            blocked |= (issue["severity"] == "severe" or
                        (issue["severity"] == "uncertain" and issue["core"]))
        scores[label] = {"reading": str(reading), "score": str(score)}
    complete = all(label in scores for label in VERSIONS)
    overall = sum(Decimal(value["score"]) for value in scores.values()) / 3 if complete else None
    status = "screen_only" if stage == "screen" else (
        "incomplete" if not complete else "blocked" if blocked else
        "score_threshold_met" if overall > 9 else "below_threshold"
    )
    return {"protocol": data["protocol"], "scores": scores,
            "overall": str(overall) if overall is not None else None,
            "status": status, "promotion": "not_authorized_by_score_alone"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reviews", type=Path)
    args = parser.parse_args()
    print(json.dumps(calculate(json.loads(args.reviews.read_text(encoding="utf-8-sig"))),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
