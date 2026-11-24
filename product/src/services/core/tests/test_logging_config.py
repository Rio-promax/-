from __future__ import annotations

import logging
from logging.config import fileConfig
from pathlib import Path

from app.logging_config import (
    LOG_BACKUP_COUNT,
    LOG_DIRECTORY_ENV,
    MAX_LOG_BYTES,
    configure_logging,
    redact_log_text,
    resolve_log_dir,
)


def _flush_root_handlers() -> None:
    for handler in logging.getLogger().handlers:
        handler.flush()


def test_redact_log_text_hides_credentials_and_user_content() -> None:
    raw = (
        "Authorization: Bearer bearer-secret "
        "api_key=api-secret cookie='sid=cookie-secret; theme=dark' "
        "url=https://example.test/?access_token=query-secret&part=1 "
        "body={'transcript': '用户原文'}"
    )

    redacted = redact_log_text(raw)

    assert "bearer-secret" not in redacted
    assert "api-secret" not in redacted
    assert "cookie-secret" not in redacted
    assert "query-secret" not in redacted
    assert "用户原文" not in redacted
    assert "[REDACTED]" in redacted
    assert "theme=dark" not in redacted


def test_configure_logging_writes_utf8_startup_hint_and_redacted_records(
    tmp_path: Path,
) -> None:
    log_path = configure_logging(tmp_path / "日志")
    logger = logging.getLogger("runtime-test")
    logger.warning("任务失败 api_key=%s", "不可写入日志的密钥")
    _flush_root_handlers()

    assert log_path == (tmp_path / "日志" / "backend.log").resolve()
    text = log_path.read_text(encoding="utf-8")
    assert "服务日志已启用" in text
    assert "任务失败" in text
    assert "不可写入日志的密钥" not in text
    assert "[REDACTED]" in text
    assert "+" in text.splitlines()[0]


def test_configure_logging_redacts_exception_text(tmp_path: Path) -> None:
    log_path = configure_logging(tmp_path)
    logger = logging.getLogger("exception-test")
    try:
        raise RuntimeError("upstream api_key=exception-secret")
    except RuntimeError:
        logger.exception("处理任务失败")
    _flush_root_handlers()

    text = log_path.read_text(encoding="utf-8")
    assert "exception-secret" not in text
    assert "RuntimeError: upstream api_key=[REDACTED]" in text


def test_configure_logging_recovers_after_alembic_disables_loggers(
    tmp_path: Path,
) -> None:
    runtime_logger = logging.getLogger("app.runtime")
    fileConfig(str(Path(__file__).parents[1] / "alembic.ini"))
    assert runtime_logger.disabled is True

    log_path = configure_logging(tmp_path)
    runtime_logger.info("迁移后日志仍然可用")
    _flush_root_handlers()

    assert runtime_logger.disabled is False
    assert "服务日志已启用" in log_path.read_text(encoding="utf-8")
    assert "迁移后日志仍然可用" in log_path.read_text(encoding="utf-8")


def test_configure_logging_rotates_and_keeps_only_configured_backups(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import app.logging_config as logging_config

    monkeypatch.setattr(logging_config, "MAX_LOG_BYTES", 256)
    monkeypatch.setattr(logging_config, "LOG_BACKUP_COUNT", 2)
    log_path = configure_logging(tmp_path)
    logger = logging.getLogger("rotation-test")
    for index in range(40):
        logger.info("rotation record %03d %s", index, "x" * 90)
    _flush_root_handlers()

    backups = sorted(tmp_path.glob("backend.log.[0-9]*"))
    assert log_path.exists()
    assert len(backups) <= 2
    assert all(path.stat().st_size > 0 for path in backups)
    assert not (tmp_path / "backend.log.3").exists()


def test_resolve_log_dir_accepts_environment_override(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(LOG_DIRECTORY_ENV, str(tmp_path / "service-logs"))

    assert resolve_log_dir() == (tmp_path / "service-logs").resolve()
    assert resolve_log_dir(tmp_path / "explicit") == (tmp_path / "explicit").resolve()


def test_log_policy_constants_are_bounded() -> None:
    assert MAX_LOG_BYTES > 0
    assert LOG_BACKUP_COUNT > 0
