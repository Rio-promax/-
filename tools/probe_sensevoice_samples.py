"""Probe the fixed-language SenseVoiceSmall sample contract.

The repository intentionally does not ship audio fixtures.  Pass the locally
approved samples explicitly and this probe records which required labels are
available.  A missing ``mixed`` sample is reported as a sample gap rather than
being treated as a passing quality result.

Example (PowerShell):

    python tools/probe_sensevoice_samples.py `
      --model product/local/asr-models/sensevoice-small `
      --sample zh=product/local/asr-models/sensevoice-small/example/zh.mp3 `
      --sample en=product/local/asr-models/sensevoice-small/example/en.mp3 `
      --output product/local/asr-benchmarks/sensevoice-language-contract.json

Exit codes are 0 for a complete passing contract, 2 when a required sample is
missing, and 1 for an execution or quality failure.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

CORE_ROOT = Path(__file__).resolve().parents[1] / "product" / "src" / "services" / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from app.adapters.asr.local import (  # noqa: E402
    SenseVoiceWorker,
    asr_text_quality,
)


def parse_sample_specs(values: list[str]) -> dict[str, Path]:
    samples: dict[str, Path] = {}
    for raw in values:
        label, separator, value = raw.partition("=")
        label = label.strip().casefold()
        path = Path(value.strip()).expanduser() if separator else Path()
        if not separator or not label or not value.strip():
            raise ValueError(f"样本格式必须为 label=path：{raw}")
        if label in samples:
            raise ValueError(f"样本标签重复：{label}")
        if not path.is_file():
            raise ValueError(f"样本文件不存在：{path}")
        samples[label] = path.resolve()
    return samples


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="SenseVoiceSmall model directory")
    parser.add_argument(
        "--sample",
        action="append",
        default=[],
        metavar="LABEL=PATH",
        help="repeatable labeled audio sample; recommended labels: zh, en, mixed",
    )
    parser.add_argument("--required-label", action="append", default=None)
    parser.add_argument("--expect", action="append", default=[], metavar="LABEL=TEXT")
    parser.add_argument("--output", required=True, help="JSON result path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        samples = parse_sample_specs(args.sample)
        required_labels = {
            item.strip().casefold()
            for item in (args.required_label or ["zh", "en", "mixed"])
            if item.strip()
        }
        expected: dict[str, str] = {}
        for raw in args.expect:
            label, separator, text = raw.partition("=")
            if not separator or not label.strip() or not text.strip():
                raise ValueError(f"期望格式必须为 label=text：{raw}")
            expected[label.strip().casefold()] = text.strip()
        model = Path(args.model).expanduser().resolve()
        if not model.is_dir():
            raise ValueError(f"模型目录不存在：{model}")
        worker = SenseVoiceWorker(model)
        worker.ensure_started()
        records: list[dict[str, object]] = []
        try:
            for label, path in samples.items():
                started = monotonic()
                text, detected_language = worker.transcribe(path, language="auto")
                normalized = str(text or "").strip()
                expected_fragment = expected.get(label)
                quality = asr_text_quality(label, normalized)
                if expected_fragment:
                    quality = quality and expected_fragment.casefold() in normalized.casefold()
                records.append(
                    {
                        "label": label,
                        "path": str(path),
                        "text": normalized,
                        "detected_language": detected_language,
                        "elapsed_seconds": max(0.0, monotonic() - started),
                        "quality_passed": quality,
                    }
                )
        finally:
            worker.close()
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    missing_labels = sorted(required_labels - set(samples))
    quality_failures = sorted(
        str(record["label"])
        for record in records
        if not bool(record["quality_passed"])
    )
    if missing_labels:
        status = "sample_gap"
        exit_code = 2
    elif quality_failures:
        status = "quality_failed"
        exit_code = 1
    else:
        status = "passed"
        exit_code = 0
    result = {
        "schema": "sensevoice-language-contract-v1",
        "model_id": "sensevoice-small",
        "created_at": datetime.now(UTC).isoformat(),
        "required_labels": sorted(required_labels),
        "sample_labels": sorted(samples),
        "missing_labels": missing_labels,
        "quality_failures": quality_failures,
        "status": status,
        "records": records,
        "manual_sample_gap": (
            "未提供合法的中英混合固定音频，需人工补样本后重跑"
            if "mixed" in missing_labels
            else None
        ),
    }
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
