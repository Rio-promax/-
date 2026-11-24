"""11-22 模型候选列表与设置焦点样式契约。"""
from pathlib import Path

UI = Path(__file__).resolve().parents[1] / "app" / "ui"
JS = (UI / "app.js").read_text(encoding="utf-8")
CSS = (UI / "style.css").read_text(encoding="utf-8")


def test_r1_model_candidates_are_keyboard_selectable_and_remain_editable():
    """模型发现结果有产品候选列表，输入仍可自由编辑并保存。"""
    assert 'const id = key.replaceAll("_", "-")' in JS
    assert 'aria-controls="${id}-options"' in JS and 'id="${id}-options" role="listbox"' in JS
    assert 'role="combobox"' in JS and 'role="listbox"' in JS and 'role="option"' in JS
    assert 'event.key === "ArrowDown"' in JS and 'event.key === "ArrowUp"' in JS
    assert 'event.key === "Enter"' in JS and "selectModelCandidate" in JS
    assert "summaryModels" in JS and "asrModels" in JS
    assert 'data-setting-key="${esc(key)}"' in JS
    assert ".set-input:focus" in CSS
    assert "<datalist" not in JS
