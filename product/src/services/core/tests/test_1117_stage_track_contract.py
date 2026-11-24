from __future__ import annotations

from pathlib import Path

UI_DIR = Path(__file__).resolve().parents[1] / "app" / "ui"
JS = (UI_DIR / "app.js").read_text(encoding="utf-8")
CSS = (UI_DIR / "style.css").read_text(encoding="utf-8")


def test_stage_axis_is_one_track_not_five_rows() -> None:
    """R1：五段合成一条轨道，标签独立成行，旧的独立百分比列已移除。"""
    assert 'class="job-stage-labels"' in JS
    assert "job-stage__pct" not in JS and "job-stage__pct" not in CSS
    assert "grid-template-columns: repeat(5, minmax(0, 1fr))" in CSS


def test_current_stage_has_one_mark() -> None:
    """R2：只在当前段挂一个符号，符号位置由阶段序号决定。"""
    assert "JOB_STAGE_ICON" in JS
    assert "job-stages__marks" in JS and "grid-column:${stageIndex + 1}" in JS
    assert "job-mark-float" in CSS
    assert "prefers-reduced-motion: reduce" in CSS


def test_track_is_a_single_progressbar() -> None:
    """R3：整条轨道作为一个进度条朗读，不逐段念数字。"""
    assert 'role="progressbar"' in JS
    assert "aria-valuetext" in JS
