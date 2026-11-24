"""11-22 失败恢复与显示口径方案阶段 B：R4/R8/R9 行为契约。"""
import json
from pathlib import Path

from app.api.main import _checkpoint_files_readable
from app.api.schemas import SettingsUpdateRequest
from app.domain.jobs import checkpoint_config_fingerprint


UI = Path(__file__).resolve().parents[1] / "app" / "ui"
JS = (UI / "app.js").read_text(encoding="utf-8")


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_r4_clear_secret_provider_is_explicit_field():
    assert "clear_secret_provider" in SettingsUpdateRequest.model_fields
    request = SettingsUpdateRequest(clear_secret_provider="summary", summary_api_key="")
    assert request.clear_secret_provider == "summary"
    # 留空保存（不带标志）不得被当成清除。
    assert SettingsUpdateRequest(summary_api_key="").clear_secret_provider is None


def test_r4_front_end_clear_handler_and_empty_save_are_distinct():
    assert 'data-act="clear-secret"' in JS
    assert 'case "clear-secret": {' in JS
    assert 'clear_secret_provider: provider' in JS
    assert "S.summaryModels = []" in JS and "S.asrModels = []" in JS
    # 普通保存仍只在密钥非空时写字段，留空不修改。
    assert 'if (summaryKey) body.summary_api_key = summaryKey;' in JS
    assert 'if (asrKey) { body.asr_api_key = asrKey; asrTouched = true; }' in JS


def test_r8_checkpoint_files_must_exist_and_be_readable(tmp_path: Path):
    directory = str(tmp_path / "ckpt")
    assert not _checkpoint_files_readable(directory, "chunks_ready")
    _write(tmp_path / "ckpt" / "transcript.json", {"segments": []})
    assert not _checkpoint_files_readable(directory, "chunks_ready")
    _write(tmp_path / "ckpt" / "chunks.json", {"chunks": []})
    assert _checkpoint_files_readable(directory, "chunks_ready")
    assert not _checkpoint_files_readable(directory, "summary_ready")
    _write(tmp_path / "ckpt" / "summary.json", {"summary": {}})
    assert _checkpoint_files_readable(directory, "summary_ready")
    # JSON 损坏视为不可读。
    (tmp_path / "ckpt" / "summary.json").write_text("{bad", encoding="utf-8")
    assert not _checkpoint_files_readable(directory, "summary_ready")


def test_r8_fingerprint_changes_with_model_and_prompt():
    base = dict(model="m1", prompt_hash="h1", max_chunk_tokens=800, language="zh")
    assert checkpoint_config_fingerprint(**base) == checkpoint_config_fingerprint(**base)
    assert checkpoint_config_fingerprint(**base) != checkpoint_config_fingerprint(
        **{**base, "model": "m2"}
    )
    assert checkpoint_config_fingerprint(**base) != checkpoint_config_fingerprint(
        **{**base, "prompt_hash": "h2"}
    )


def test_r8_retry_uses_four_checks_and_degrades(tmp_path: Path):
    source = Path(__file__).resolve().parents[1] / "app" / "api" / "main.py"
    main_js = source.read_text(encoding="utf-8")
    assert "within_24h and fingerprint_ok" in main_js
    assert "for candidate in resumable_checkpoints[start:]" in main_js
    assert "_checkpoint_files_readable(resume_checkpoint_dir, candidate)" in main_js
    assert 'fingerprint is None  # 老任务无指纹，沿用其历史行为' in main_js


def test_r8_failed_cleanup_keeps_stable_checkpoint():
    from app.workflows import analyze

    source = Path(analyze.__file__).read_text(encoding="utf-8")
    assert "failed_stable = (" in source
    assert 'latest.metadata.get("resume_checkpoint")' in source
    assert "failed_keep = failed_stable in resumable_checkpoints" in source


def test_r9_library_paginates_archived_history_for_old_and_new_backends():
    assert 'const pageSize = 50;' in JS
    assert 'archived_only=true&limit=${pageSize}&offset=${offset}' in JS
    assert '["history", loadArchivedHistory()]' in JS
    assert 'key === "history" ? await loadArchivedHistory()' in JS
    assert '知识库加载失败，请点击「刷新」重试' in JS
    main_source = Path(__file__).resolve().parents[1] / "app" / "api" / "main.py"
    assert "limit: int = Query(default=50, ge=1, le=2000)" in main_source.read_text(encoding="utf-8")


def test_r7_retry_maps_old_and_new_job_ids():
    assert "const retryPairs = []" in JS
    assert "retryPairs.push({ oldId: id, newId: result.job.id })" in JS
    assert "const shownIds = new Set(filteredJobs().map((job) => job.id));" in JS
    assert 'parts.push(`${oldStillShown} 项旧卡仍在原区`)' in JS
