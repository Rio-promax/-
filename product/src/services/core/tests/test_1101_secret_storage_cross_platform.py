"""R1 密钥存储跨平台的自动验收用例。

对应方案文档「验收 / 自动」第 1-7 条（第 8 条是全量 pytest 前后对比，不写成用例）。

关键点：不新建统一的读取函数，前缀分派就落在 ``secrets.unprotect_secret``
内部，因此这些用例直接打桩平台与密钥路径，走的就是生产代码路径。
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.db.store import SQLiteStore
from app.platforms import secrets as secrets_module
from app.platforms.secrets import SecretStorageError, protect_secret, unprotect_secret

_SUMMARY_PURPOSE = "总结模型 API Key"
_ASR_PURPOSE = "云端 ASR API Key"


@pytest.fixture
def linux_key_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """强制非 win32，并把密钥文件指向临时目录，绝不碰 ``product/local/secret.key``。"""

    key_path = tmp_path / "local" / "secret.key"
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(secrets_module, "_fernet_key_path", lambda: key_path)
    # 清掉模块级缓存，避免上一个用例的实例泄漏到本用例。
    monkeypatch.setattr(secrets_module, "_fernet_cache", None)
    yield key_path


def _new_store() -> SQLiteStore:
    return SQLiteStore("sqlite:///:memory:")


def test_protect_and_unprotect_round_trip_with_fernet_prefix(
    linux_key_file: Path,
) -> None:
    """1. 函数层往返：非 win32 产出 ``fernet:``，且能还原原文。"""

    original = "sk-函数层往返-密钥"

    protected = protect_secret(original, purpose=_SUMMARY_PURPOSE)

    assert protected.startswith("fernet:")
    assert original not in protected
    assert linux_key_file.exists(), "首次写入必须落盘密钥文件"
    assert unprotect_secret(protected, purpose=_SUMMARY_PURPOSE) == original


def test_store_round_trip_persists_fernet_and_returns_plaintext(
    linux_key_file: Path,
) -> None:
    """2. store 层往返（最关键）：库里是 ``fernet:`` 密文，读出来是明文。"""

    store = _new_store()
    original = "sk-store-层往返"

    store.set_secret_setting("summary_api_key", original, purpose=_SUMMARY_PURPOSE)

    stored = store._get_setting_raw("summary_api_key")
    assert stored is not None
    assert stored.startswith("fernet:")
    assert original not in stored
    assert store.get_secret_setting("summary_api_key", purpose=_SUMMARY_PURPOSE) == original


def test_get_setting_decrypts_fernet_asr_branch(linux_key_file: Path) -> None:
    """3. asr 分支往返：``get_setting`` 必须返回明文，不是密文。"""

    store = _new_store()
    original = "sk-asr-cloud-密钥"
    protected = protect_secret(original, purpose=_ASR_PURPOSE)
    assert protected.startswith("fernet:")
    store.set_setting("asr_api_key", protected)

    value = store.get_setting("asr_api_key")

    assert value == original
    assert not value.startswith("fernet:")


def test_empty_value_still_raises_secret_storage_error(
    linux_key_file: Path,
) -> None:
    """4. 空值仍抛 ``SecretStorageError``（保持既有语义）。"""

    with pytest.raises(SecretStorageError):
        protect_secret("", purpose=_SUMMARY_PURPOSE)


def test_missing_key_file_raises_readable_regenerate_message(
    linux_key_file: Path,
) -> None:
    """5. 密钥文件缺失时是可读错误，且提示要重新生成密钥文件。"""

    assert not linux_key_file.exists()

    with pytest.raises(SecretStorageError) as excinfo:
        unprotect_secret("fernet:gAAAAABinvalid-token", purpose=_SUMMARY_PURPOSE)

    assert "重新生成密钥文件" in str(excinfo.value)


def test_unprefixed_value_passes_through_store_but_unprotect_rejects(
    linux_key_file: Path,
) -> None:
    """6. 无前缀值：store 原样返回，但 ``unprotect_secret`` 仍抛错。

    两条一起断言，防止有人靠放宽 ``unprotect_secret`` 把本用例蒙过去。
    """

    store = _new_store()
    store.set_setting("summary_api_key", "legacy-plaintext-value")

    assert (
        store.get_secret_setting("summary_api_key", purpose=_SUMMARY_PURPOSE)
        == "legacy-plaintext-value"
    )

    with pytest.raises(SecretStorageError) as excinfo:
        unprotect_secret("legacy-plaintext-value", purpose=_SUMMARY_PURPOSE)
    assert "格式无效" in str(excinfo.value)


def test_dpapi_value_on_non_windows_reports_windows_only(
    linux_key_file: Path,
) -> None:
    """7. 非 win32 读到 ``dpapi:`` 值时要报「重新录入」，不是静默失败。"""

    with pytest.raises(SecretStorageError) as excinfo:
        unprotect_secret("dpapi:AQAAANCMnd8BFdERjHoAwE", purpose=_SUMMARY_PURPOSE)

    assert str(excinfo.value) == "该凭证由 Windows 加密，无法在当前系统解密，请重新录入"
