import pytest

from app.adapters.asr.local import AsrBatchBenchmark, asr_text_quality, select_safe_asr_batch


@pytest.mark.parametrize(
    ("label", "text", "expected"),
    [
        ("zh", "这是一段中文。", True),
        ("zh", "only English", False),
        ("en", "This is English.", True),
        ("en", "只有中文", False),
        ("mixed", "中文 and English", True),
        ("mixed", "只有中文", False),
    ],
)
def test_fixed_language_quality_contract(label: str, text: str, expected: bool) -> None:
    assert asr_text_quality(label, text) is expected


def test_batch_selection_requires_ten_percent_gain_and_safe_memory() -> None:
    selected = select_safe_asr_batch(
        [
            AsrBatchBenchmark(1, 100.0, peak_memory_mb=2400.0),
            AsrBatchBenchmark(2, 88.0, peak_memory_mb=3000.0),
            AsrBatchBenchmark(4, 70.0, peak_memory_mb=5000.0),
        ]
    )

    assert selected == 2


def test_batch_selection_stays_at_one_without_validated_gain() -> None:
    assert select_safe_asr_batch(
        [
            AsrBatchBenchmark(1, 100.0, peak_memory_mb=2400.0),
            AsrBatchBenchmark(2, 92.0, peak_memory_mb=3000.0),
            AsrBatchBenchmark(4, 80.0, peak_memory_mb=3000.0, missing_segments=1),
        ]
    ) == 1


def test_batch_selection_stays_at_one_when_baseline_or_candidate_is_unmeasured() -> None:
    assert select_safe_asr_batch([AsrBatchBenchmark(2, 80.0, peak_memory_mb=3000.0)]) == 1
    assert select_safe_asr_batch(
        [
            AsrBatchBenchmark(1, 100.0, peak_memory_mb=2400.0),
            AsrBatchBenchmark(2, 80.0),
        ]
    ) == 1
