import importlib.util
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest


spec = importlib.util.spec_from_file_location(
    "summary_eval_generate", Path(__file__).parents[1] / "tools/summary_eval_generate.py"
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


@pytest.fixture
def evaluation(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    db = tmp_path / "product/local/knowledge.db"
    db.parent.mkdir(parents=True)
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute("CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.executemany("INSERT INTO app_settings VALUES (?, ?)", [
            ("summary_prompt", "production prompt"),
            ("summary_api_key", "fake-key"),
            ("summary_api_url", "https://example.invalid/v1"),
            ("summary_model", "fake-model"),
        ])
    base = tmp_path / "evaluation"
    folder = base / "Agent2_V16"
    folder.mkdir(parents=True)
    (folder / "Prompt.md").write_text("candidate prompt", encoding="utf-8")
    (base / "P1_产品保存原文.txt").write_text("original transcript", encoding="utf-8")
    calls = []

    class FakeSummarizer:
        def __init__(self, settings):
            pass

        def _summary_payload(self, **kwargs):
            return kwargs

        def summarize_chunks(self, chunks, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(markdown="generated summary")

    monkeypatch.setattr(runner, "OpenAICompatibleSummarizer", FakeSummarizer)
    return base, folder, db, calls


def test_screen_then_full_reuses_output_without_changing_product_prompt(evaluation):
    base, folder, db, calls = evaluation
    args = ["V16", "--base", str(base)]
    runner.main(args)
    assert len(calls) == 1
    assert calls[0]["prompt"] == "candidate prompt"
    assert (folder / "通用版.md").is_file()
    assert not (folder / "详细版.md").exists()
    runner.main(args + ["--stage", "full"])
    assert len(calls) == 3  # saved standard is reused, not resampled
    with closing(sqlite3.connect(db)) as conn:
        assert conn.execute("SELECT value FROM app_settings WHERE key='summary_prompt'").fetchone()[0] == "production prompt"


def test_dry_run_does_not_need_database_or_network(evaluation, capsys):
    base, _, db, calls = evaluation
    db.unlink()
    runner.main(["V16", "--base", str(base), "--dry-run"])
    plan = json.loads(capsys.readouterr().out)
    assert plan["labels"] == ["通用"]
    assert plan["production_settings_write"] is False
    assert not calls


def test_changed_prompt_cannot_reuse_old_output(evaluation):
    base, folder, _, calls = evaluation
    args = ["V16", "--base", str(base)]
    runner.main(args)
    (folder / "Prompt.md").write_text("different candidate", encoding="utf-8")
    with pytest.raises(ValueError, match="使用新版本号"):
        runner.main(args)
    assert len(calls) == 1


def test_generation_failure_is_not_a_saved_version(evaluation, monkeypatch):
    base, folder, db, _ = evaluation

    def fail(*args, **kwargs):
        raise RuntimeError("fake-key provider failure")

    monkeypatch.setattr(runner.OpenAICompatibleSummarizer, "summarize_chunks", fail)
    with pytest.raises(SystemExit) as error:
        runner.main(["V16", "--base", str(base)])
    assert error.value.code == 2
    assert not (folder / "通用版.md").exists()
    failure = (folder / "通用版_失败.json").read_text(encoding="utf-8")
    assert "fake-key" not in failure
    with closing(sqlite3.connect(db)) as conn:
        assert conn.execute("SELECT value FROM app_settings WHERE key='summary_prompt'").fetchone()[0] == "production prompt"
