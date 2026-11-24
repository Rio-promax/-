"""Run a reproducible SenseVoiceSmall batch 1/2/4 benchmark.

The script deliberately accepts sample paths instead of bundling audio.  It
uses one resident Worker, emits lightweight JSON metrics, and can persist the
selected batch policy into the application's SQLite settings table.

Example (run with the product core virtualenv):

    python tools/run_sensevoice_batch_benchmark.py `
      --model product/local/asr-models/sensevoice-small `
      --sample zh=product/local/asr-models/sensevoice-small/example/zh.mp3 `
      --sample en=product/local/asr-models/sensevoice-small/example/en.mp3 `
      --sample mixed=D:/samples/mixed.mp3 `
      --output product/local/asr-benchmarks/sensevoice-batch.json `
      --database sqlite:///product/local/product.sqlite

Missing mixed-language audio is recorded as a sample gap.  In that case the
script keeps the product selection at batch 1 even when available samples are
faster, so a partial sample set cannot silently enable a larger batch.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread
from time import monotonic

CORE_ROOT = Path(__file__).resolve().parents[1] / "product" / "src" / "services" / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from app.adapters.asr.local import (  # noqa: E402
    AsrBatchBenchmark,
    SenseVoiceWorker,
    asr_text_quality,
    select_safe_asr_batch,
    _probe_audio_duration,
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


def _sample_memory(worker: SenseVoiceWorker, peak: list[float]) -> None:
    value = worker.memory_rss_mb()
    if isinstance(value, (int, float)):
        peak[0] = max(peak[0], float(value))


def run_case(
    worker: SenseVoiceWorker,
    samples: dict[str, Path],
    *,
    batch_size: int,
    required_labels: set[str],
    expected_text: dict[str, str],
) -> dict[str, object]:
    ordered = list(samples.items())
    audio_seconds = sum(_probe_audio_duration(path) for _label, path in ordered)
    peak_memory = [0.0]
    _sample_memory(worker, peak_memory)
    monitor_stop = Event()

    def monitor() -> None:
        while not monitor_stop.wait(0.05):
            _sample_memory(worker, peak_memory)

    monitor_thread = Thread(target=monitor, name=f"sensevoice-benchmark-{batch_size}", daemon=True)
    started = monotonic()
    first_result_seconds: float | None = None
    outputs: list[tuple[str, str]] = []
    missing_segments = 0
    duplicate_segments = 0
    out_of_order_segments = 0
    error: str | None = None
    monitor_thread.start()
    try:
        for offset in range(0, len(ordered), batch_size):
            group = ordered[offset : offset + batch_size]
            paths = [path for _label, path in group]
            call_completed = False
            try:
                if len(paths) == 1:
                    result = (worker.transcribe(paths[0], language="auto"),)
                else:
                    result = worker.transcribe_batch(paths, language="auto")
                call_completed = True
            finally:
                if not call_completed:
                    integrity = getattr(worker, "last_batch_integrity", {})
                    if isinstance(integrity, dict):
                        missing_segments += int(
                            integrity.get("missing_segments", 0) or 0
                        )
                        duplicate_segments += int(
                            integrity.get("duplicate_segments", 0) or 0
                        )
                        out_of_order_segments += int(
                            integrity.get("out_of_order_segments", 0) or 0
                        )
            integrity = getattr(worker, "last_batch_integrity", {})
            if isinstance(integrity, dict):
                missing_segments += int(integrity.get("missing_segments", 0) or 0)
                duplicate_segments += int(integrity.get("duplicate_segments", 0) or 0)
                out_of_order_segments += int(
                    integrity.get("out_of_order_segments", 0) or 0
                )
            if first_result_seconds is None:
                first_result_seconds = max(0.0, monotonic() - started)
            if len(result) != len(group):
                raise RuntimeError(f"返回 {len(result)} 条，期望 {len(group)} 条")
            outputs.extend((label, str(item[0] or "")) for (label, _path), item in zip(group, result))
    except Exception as exc:  # benchmark output must preserve the failure reason
        error = str(exc) or type(exc).__name__
    finally:
        _sample_memory(worker, peak_memory)
        monitor_stop.set()
        monitor_thread.join(timeout=1)
    elapsed = max(0.0, monotonic() - started)

    # A failed call may not return any rows. Count those unreturned samples as
    # missing in addition to the Worker-level integrity counters; duplicate
    # and ordering values always come from request/response validation.
    missing_segments = max(missing_segments, max(0, len(ordered) - len(outputs)))
    quality_failures: list[str] = []
    expected = dict(expected_text)
    for label, text in outputs:
        if not asr_text_quality(label, text):
            quality_failures.append(label)
        expected_fragment = expected.get(label)
        if expected_fragment and expected_fragment.casefold() not in text.casefold():
            quality_failures.append(f"{label}:expected")
    missing_labels = sorted(required_labels - set(samples))
    status = "ok"
    if error:
        status = "failed"
    elif missing_segments or duplicate_segments or out_of_order_segments:
        status = "invalid_output"
    elif missing_labels:
        status = "sample_gap"
    elif quality_failures:
        status = "quality_failed"
    return {
        "batch_size": batch_size,
        "status": status,
        "total_seconds": elapsed,
        "first_result_seconds": first_result_seconds,
        "audio_seconds": audio_seconds,
        "rtf": elapsed / max(0.001, audio_seconds),
        "peak_memory_mb": peak_memory[0] or None,
        "missing_segments": missing_segments,
        "duplicate_segments": duplicate_segments,
        "out_of_order_segments": out_of_order_segments,
        "quality_failures": sorted(set(quality_failures)),
        "missing_labels": missing_labels,
        "error": error,
    }


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
    parser.add_argument(
        "--database",
        help="optional SQLite URL; persist the validated policy as asr_batch_selection",
    )
    parser.add_argument("--memory-limit-mb", type=float, default=4096.0)
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
        expected_text: dict[str, str] = {}
        for raw in args.expect:
            label, separator, text = raw.partition("=")
            if not separator or not label.strip() or not text.strip():
                raise ValueError(f"期望格式必须为 label=text：{raw}")
            expected_text[label.strip().casefold()] = text.strip()
        model = Path(args.model).expanduser().resolve()
        if not model.is_dir():
            raise ValueError(f"模型目录不存在：{model}")
        worker = SenseVoiceWorker(model)
        worker.ensure_started()
        try:
            cases = [
                run_case(
                    worker,
                    samples,
                    batch_size=batch_size,
                    required_labels=required_labels,
                    expected_text=expected_text,
                )
                for batch_size in (1, 2, 4)
            ]
        finally:
            worker.close()
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    benchmark_rows = [
        AsrBatchBenchmark(
            batch_size=int(case["batch_size"]),
            total_seconds=float(case["total_seconds"]),
            peak_memory_mb=case["peak_memory_mb"],
            missing_segments=int(case["missing_segments"]),
            duplicate_segments=int(case["duplicate_segments"]),
            out_of_order_segments=int(case["out_of_order_segments"]),
            status=str(case["status"]),
        )
        for case in cases
    ]
    selected = select_safe_asr_batch(benchmark_rows, memory_limit_mb=args.memory_limit_mb)
    status = "passed" if selected > 1 else "fallback_batch_1"
    result = {
        "schema": "sensevoice-batch-benchmark-v1",
        "model_id": "sensevoice-small",
        "created_at": datetime.now(UTC).isoformat(),
        "sample_labels": sorted(samples),
        "required_labels": sorted(required_labels),
        "memory_limit_mb": args.memory_limit_mb,
        "selected_batch_size": selected,
        "status": status,
        "cases": cases,
    }
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.database:
        from app.db.store import SQLiteStore

        store = SQLiteStore(args.database)
        store.set_setting("asr_batch_selection", json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
