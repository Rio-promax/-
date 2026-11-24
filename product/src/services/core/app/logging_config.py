"""Runtime logging for the local sidecar service.

The desktop service is started by a Windows ``.cmd`` file as well as by
``uvicorn`` directly.  Keeping the setup here, next to the application
package, means both launch paths use the same local, redacted log file.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TextIO


LOG_FILE_NAME = "backend.log"
MAX_LOG_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 5
LOG_DIRECTORY_ENV = "PRODUCT_LOG_DIR"
DEFAULT_LOG_DIRECTORY = Path("local") / "logs"

_PRODUCT_HANDLER_MARKER = "_multisource_runtime_handler"
_SENSITIVE_KEY = (
    r"authorization|proxy[-_]?authorization|cookie|set[-_]?cookie|"
    r"x[-_]?api[-_]?key|api[-_]?key|access[-_]?token|refresh[-_]?token|"
    r"id[-_]?token|token|password|passwd|secret|client[-_]?secret|"
    r"session(?:[-_]?(?:id|key))?|signature"
)
_SENSITIVE_CONTENT_KEY = (
    r"request[-_]?body|body|payload|transcript|prompt|messages|"
    r"request[-_]?headers|headers"
)
_KEY_BOUNDARY = r"(?<![A-Za-z0-9_])"

# Match bearer/basic credentials before generic key/value replacement.  This
# also protects messages such as ``Authorization: Bearer <token>`` when the
# value is separated by whitespace rather than ``=``.
_BEARER_TOKEN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_BASIC_TOKEN = re.compile(r"(?i)\bBasic\s+[A-Za-z0-9+/=]+")

# A body, payload, or transcript is never useful in a service log and may
# contain arbitrary user content.  Redact the remainder of that log line so
# JSON, quoted text, and values containing spaces cannot leak through.
_SENSITIVE_CONTENT = re.compile(
    rf"(?im)(?P<key>{_KEY_BOUNDARY}(?:{_SENSITIVE_CONTENT_KEY}))"
    rf"(?P<separator>\s*[\"']?\s*[:=]\s*)(?P<value>[^\r\n]*)"
)

# Quoted values need a separate expression so cookies or JSON strings with
# spaces are redacted in full.  The optional quote before ``:``/``=`` allows
# both ``{'api_key': 'value'}`` and ``api_key='value'`` forms.
_SENSITIVE_QUOTED = re.compile(
    rf"(?i)(?P<key>{_KEY_BOUNDARY}(?:{_SENSITIVE_KEY}))"
    rf"(?P<separator>\s*[\"']?\s*[:=]\s*)"
    rf"(?P<quote>[\"'])(?P<value>[^\r\n]*?)(?P=quote)"
)

# Unquoted values cover URLs, query strings, and common ``key=value`` log
# messages.  Delimiters stop the match before adjacent fields.
_SENSITIVE_UNQUOTED = re.compile(
    rf"(?i)(?P<key>{_KEY_BOUNDARY}(?:{_SENSITIVE_KEY}))"
    rf"(?P<separator>\s*[\"']?\s*[:=]\s*)"
    r"(?P<value>[^\s,;&\[\]}\)\"']+)"
)


def redact_log_text(value: object) -> str:
    """Return a log-safe representation without credentials or user content."""

    text = str(value)
    text = _BEARER_TOKEN.sub("Bearer [REDACTED]", text)
    text = _BASIC_TOKEN.sub("Basic [REDACTED]", text)
    text = _SENSITIVE_CONTENT.sub(
        lambda match: f"{match.group('key')}{match.group('separator')}[REDACTED]",
        text,
    )
    text = _SENSITIVE_QUOTED.sub(
        lambda match: (
            f"{match.group('key')}{match.group('separator')}"
            f"{match.group('quote')}[REDACTED]{match.group('quote')}"
        ),
        text,
    )
    return _SENSITIVE_UNQUOTED.sub(
        lambda match: f"{match.group('key')}{match.group('separator')}[REDACTED]",
        text,
    )


class RedactingFormatter(logging.Formatter):
    """Format the complete record, including exception text, then redact it."""

    def format(self, record: logging.LogRecord) -> str:
        return redact_log_text(super().format(record))


class SensitiveDataFilter(logging.Filter):
    """Redact the message before it reaches handlers not owned by this module."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
        except Exception:
            # Logging must not turn a formatting problem into an application
            # failure.  RedactingFormatter still protects the final output.
            return True
        record.msg = redact_log_text(rendered)
        record.args = ()
        if record.exc_text:
            record.exc_text = redact_log_text(record.exc_text)
        return True


class LoggingStream:
    """Line-buffered stdout/stderr bridge for code that still uses ``print``."""

    def __init__(self, logger: logging.Logger, level: int, original: TextIO) -> None:
        self._logger = logger
        self._level = level
        self._original = original
        self._buffer = ""

    def write(self, value: str) -> int:
        self._buffer += value
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.rstrip("\r")
            if line:
                self._logger.log(self._level, line)
        return len(value)

    def flush(self) -> None:
        if self._buffer:
            self._logger.log(self._level, self._buffer.rstrip("\r"))
            self._buffer = ""
        for handler in logging.getLogger().handlers:
            handler.flush()

    def isatty(self) -> bool:
        return self._original.isatty()

    @property
    def encoding(self) -> str | None:
        return getattr(self._original, "encoding", None)

    def fileno(self) -> int:
        return self._original.fileno()


def resolve_log_dir(value: str | Path | None = None) -> Path:
    """Resolve the service log directory from an explicit path or environment."""

    configured = value if value is not None else os.environ.get(LOG_DIRECTORY_ENV)
    selected = Path(configured) if configured else DEFAULT_LOG_DIRECTORY
    return selected.expanduser().resolve()


def _close_product_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        if getattr(handler, _PRODUCT_HANDLER_MARKER, False):
            logger.removeHandler(handler)
            handler.close()


def configure_logging(log_dir: str | Path | None = None) -> Path:
    """Configure console and rotating file logging and return the active path.

    The file is UTF-8 encoded and rotates at ``MAX_LOG_BYTES``.  The active
    file plus ``LOG_BACKUP_COUNT`` numbered backups are retained.  Existing
    non-product handlers (for example pytest's capture handler) are kept, so
    calling this function during tests does not disable test diagnostics.
    """

    selected_dir = resolve_log_dir(log_dir)
    selected_dir.mkdir(parents=True, exist_ok=True)
    log_path = selected_dir / LOG_FILE_NAME

    root_logger = logging.getLogger()
    _close_product_handlers(root_logger)
    root_logger.disabled = False
    root_logger.setLevel(logging.INFO)

    formatter = RedactingFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S%z",
    )
    sensitive_filter = SensitiveDataFilter()

    console_handler = logging.StreamHandler(sys.__stdout__)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(sensitive_filter)
    setattr(console_handler, _PRODUCT_HANDLER_MARKER, True)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=MAX_LOG_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
        errors="backslashreplace",
        delay=True,
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(sensitive_filter)
    setattr(file_handler, _PRODUCT_HANDLER_MARKER, True)

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    # Uvicorn's defaults attach their own handlers and disable propagation;
    # remove those handlers so its startup, access, and exception records use
    # the same redacted rotating file as application records.
    for logger_name in (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "uvicorn.asgi",
    ):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.disabled = False
        logger.setLevel(logging.INFO)
        logger.propagate = True

    # Alembic's legacy ``fileConfig`` uses ``disable_existing_loggers=True``
    # by default.  Restore the application logger namespace so a migration
    # run in this process cannot permanently silence the startup hint or later
    # service records.
    for logger_name, logger in logging.root.manager.loggerDict.items():
        if logger_name == "app" or logger_name.startswith("app."):
            if isinstance(logger, logging.Logger):
                logger.disabled = False

    runtime_logger = logging.getLogger("app.runtime")
    runtime_logger.disabled = False
    runtime_logger.info(
        "服务日志已启用：%s（单文件上限 %d MB，保留 %d 个轮转文件）",
        log_path,
        MAX_LOG_BYTES // (1024 * 1024),
        LOG_BACKUP_COUNT,
    )
    return log_path


def redirect_standard_streams() -> None:
    """Route direct stdout/stderr writes through the configured logger once."""

    if not isinstance(sys.stdout, LoggingStream):
        sys.stdout = LoggingStream(logging.getLogger("stdout"), logging.INFO, sys.__stdout__)
    if not isinstance(sys.stderr, LoggingStream):
        sys.stderr = LoggingStream(logging.getLogger("stderr"), logging.ERROR, sys.__stderr__)
