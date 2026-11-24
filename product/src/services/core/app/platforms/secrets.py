"""OS-backed protection for local platform credentials.

Two protection backends coexist and are told apart by the value prefix that is
stored in SQLite:

* ``dpapi:`` - Windows DPAPI, bound to the interactive Windows user account.
* ``fernet:`` - a local Fernet symmetric key stored in ``local/secret.key``,
  used by every non-Windows host (cloud server, macOS, Linux desktop).

The prefix dispatch lives inside ``protect_secret`` / ``unprotect_secret`` so
that every existing caller keeps using the same two functions and test doubles
that monkeypatch ``store.unprotect_secret`` keep working.
"""

from __future__ import annotations

import base64
import ctypes
import os
import sys
from ctypes import POINTER, Structure, byref, c_ubyte, wintypes
from pathlib import Path


class SecretStorageError(RuntimeError):
    """Raised when the local operating system cannot protect a credential."""


class _DataBlob(Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", POINTER(c_ubyte)),
    ]


# DPAPI may be called by the local sidecar before Windows has loaded the
# interactive user's profile (for example when the app is launched by a
# desktop shortcut or a service wrapper).  Keep the normal user scope and
# report that startup problem instead of widening the protection scope.
_CRYPTPROTECT_UI_FORBIDDEN = 0x1

# Prefixes identify which backend produced a stored value.  These strings are
# part of the on-disk format: changing them invalidates every saved credential.
_DPAPI_PREFIX = "dpapi:"
_FERNET_PREFIX = "fernet:"

# Lazy, path-keyed cache so a long-running server does not re-read and re-parse
# the key file on every credential access.  Keyed by path so pointing the
# resolver elsewhere (tests, or a future config override) invalidates it.
_fernet_cache: tuple[Path, object] | None = None


def _load_dpapi_functions():
    try:
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except OSError as error:
        raise SecretStorageError(
            "Windows 安全存储组件不可用，请在当前 Windows 用户桌面会话中重启应用后重试"
        ) from error

    protect = crypt32.CryptProtectData
    protect.argtypes = [
        POINTER(_DataBlob),
        wintypes.LPCWSTR,
        POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        POINTER(_DataBlob),
    ]
    protect.restype = wintypes.BOOL

    unprotect = crypt32.CryptUnprotectData
    unprotect.argtypes = [
        POINTER(_DataBlob),
        POINTER(wintypes.LPWSTR),
        POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        POINTER(_DataBlob),
    ]
    unprotect.restype = wintypes.BOOL

    local_free = kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p
    return protect, unprotect, local_free


def _protection_error(purpose: str, action: str) -> SecretStorageError:
    error_code = ctypes.get_last_error()
    recovery = (
        "请在当前 Windows 用户桌面会话中重启应用后重试"
        if action == "无法保护"
        else "请重新配置该凭证"
    )
    if error_code:
        return SecretStorageError(
            f"{action}{purpose}（Windows 错误 {error_code}），"
            + recovery
        )
    return SecretStorageError(
        f"{action}{purpose}，{recovery}"
    )


def _import_fernet():
    """Import ``cryptography`` lazily so a missing wheel is a readable error.

    ``cryptography`` is only needed off Windows, and importing it eagerly would
    break every Windows desktop start if the wheel were ever absent.
    """

    try:
        from cryptography.fernet import Fernet, InvalidToken
    except ImportError as error:  # pragma: no cover - depends on install state
        raise SecretStorageError(
            "缺少 cryptography 依赖，无法在当前系统安全存储凭证；"
            '请先安装依赖：pip install "cryptography>=42,<46"'
        ) from error
    return Fernet, InvalidToken


def _fernet_key_path() -> Path:
    """Return the local key file shared with ``knowledge.db``'s directory.

    ``parents[5]`` is the existing repository-layout convention (see
    ``app/api/main.py``): in a Windows checkout it resolves to ``product/local``,
    on a server checkout to ``~/kb/local``.
    """

    return Path(__file__).resolve().parents[5] / "local" / "secret.key"


def _key_missing_error(path: Path) -> SecretStorageError:
    return SecretStorageError(
        f"本机密钥文件缺失（{path.as_posix()}），无法解密已保存的凭证；"
        "请重新生成密钥文件后重新录入相关凭证"
    )


def _read_existing_key(path: Path) -> bytes:
    """Read the key file that must already exist; never creates one."""

    try:
        key = path.read_bytes()
    except FileNotFoundError as error:
        raise _key_missing_error(path) from error
    except OSError as error:
        raise SecretStorageError(
            f"无法读取本机密钥文件（{path.as_posix()}），请检查文件权限后重试"
        ) from error
    if not key.strip():
        raise SecretStorageError(
            f"本机密钥文件为空（{path.as_posix()}），请重新生成密钥文件后重新录入相关凭证"
        )
    return key


def _create_or_read_key(path: Path) -> bytes:
    """Return the key at *path*, creating it exactly once on first run.

    Creation is exclusive (``open(..., "xb")``).  Without that, two workers
    starting together would each generate a key, both writes would "succeed",
    and the ciphertext produced with the losing key could never be decrypted
    again - which shows up as "saving works, reading fails".
    """

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise SecretStorageError(
            f"无法创建本机密钥目录（{path.parent.as_posix()}），请检查磁盘权限后重试"
        ) from error

    try:
        handle = open(path, "xb")
    except FileExistsError:
        # Another process won the create race; its key is the canonical one.
        return _read_existing_key(path)
    except OSError as error:
        raise SecretStorageError(
            f"无法创建本机密钥文件（{path.as_posix()}），请检查磁盘权限后重试"
        ) from error

    fernet_class, _invalid_token = _import_fernet()
    key = fernet_class.generate_key()
    try:
        with handle:
            handle.write(key)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        raise SecretStorageError(
            f"无法写入本机密钥文件（{path.as_posix()}），请检查磁盘权限后重试"
        ) from error

    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - Windows / mounted filesystems
        # POSIX modes are not honoured everywhere; the key still relies on the
        # owning account's own file permissions in that case.
        pass
    return key


def _fernet(*, create: bool):
    """Return the cached Fernet instance for the local key file.

    ``create`` is only true on the write path.  Decryption never generates a
    key: a brand-new key cannot open existing ciphertext, so a missing key file
    there is a hard, explainable failure instead of a confusing token error.
    """

    global _fernet_cache
    path = _fernet_key_path()
    cached = _fernet_cache
    if cached is not None and cached[0] == path:
        return cached[1]

    fernet_class, _invalid_token = _import_fernet()
    key = _create_or_read_key(path) if create else _read_existing_key(path)
    instance = fernet_class(key)
    _fernet_cache = (path, instance)
    return instance


def _protect_with_dpapi(value: str, *, purpose: str) -> str:
    raw = value.encode("utf-8")
    input_buffer = ctypes.create_string_buffer(raw)
    input_blob = _DataBlob(
        len(raw),
        ctypes.cast(input_buffer, POINTER(c_ubyte)),
    )
    output_blob = _DataBlob()
    protect, _unprotect, local_free = _load_dpapi_functions()
    if not protect(
        byref(input_blob),
        purpose,
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        byref(output_blob),
    ):
        raise _protection_error(purpose, "无法保护")
    try:
        encrypted = ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        local_free(output_blob.pbData)
    return _DPAPI_PREFIX + base64.urlsafe_b64encode(encrypted).decode("ascii")


def _protect_with_fernet(value: str, *, purpose: str) -> str:
    fernet = _fernet(create=True)
    token = fernet.encrypt(value.encode("utf-8"))
    return _FERNET_PREFIX + token.decode("ascii")


def _unprotect_with_dpapi(value: str, *, purpose: str) -> str:
    if sys.platform != "win32":
        raise SecretStorageError(
            "该凭证由 Windows 加密，无法在当前系统解密，请重新录入"
        )
    try:
        encrypted = base64.urlsafe_b64decode(value[len(_DPAPI_PREFIX) :].encode("ascii"))
    except (ValueError, UnicodeError) as error:
        raise SecretStorageError(f"{purpose}格式无效") from error
    input_buffer = ctypes.create_string_buffer(encrypted)
    input_blob = _DataBlob(
        len(encrypted),
        ctypes.cast(input_buffer, POINTER(c_ubyte)),
    )
    output_blob = _DataBlob()
    description = ctypes.c_wchar_p()
    _protect, unprotect, local_free = _load_dpapi_functions()
    if not unprotect(
        byref(input_blob),
        byref(description),
        None,
        None,
        None,
        0,
        byref(output_blob),
    ):
        raise _protection_error(purpose, "无法解密")
    try:
        raw = ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        local_free(output_blob.pbData)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SecretStorageError(f"{purpose}内容无效，请重新配置") from error


def _unprotect_with_fernet(value: str, *, purpose: str) -> str:
    try:
        token = value[len(_FERNET_PREFIX) :].encode("ascii")
    except UnicodeError as error:
        raise SecretStorageError(f"{purpose}格式无效") from error

    _fernet_class, invalid_token = _import_fernet()
    fernet = _fernet(create=False)
    try:
        raw = fernet.decrypt(token)
    except invalid_token as error:
        raise SecretStorageError(f"{purpose}无法解密，请重新录入该凭证") from error
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SecretStorageError(f"{purpose}内容无效，请重新配置") from error


def protect_secret(value: str, *, purpose: str = "本地凭证") -> str:
    """Protect *value* with the backend native to the current platform."""

    if not value:
        raise SecretStorageError("不能保存空的本地凭证")
    if sys.platform == "win32":
        return _protect_with_dpapi(value, purpose=purpose)
    return _protect_with_fernet(value, purpose=purpose)


def unprotect_secret(value: str, *, purpose: str = "本地凭证") -> str:
    """Reverse :func:`protect_secret` by dispatching on the stored prefix."""

    if value.startswith(_DPAPI_PREFIX):
        return _unprotect_with_dpapi(value, purpose=purpose)
    if value.startswith(_FERNET_PREFIX):
        return _unprotect_with_fernet(value, purpose=purpose)
    # Unprefixed values are plaintext and must never be accepted as a
    # credential; callers rely on this rejection.
    raise SecretStorageError(f"{purpose}格式无效")
