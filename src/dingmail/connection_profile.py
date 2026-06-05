from __future__ import annotations

import base64
import ctypes
import json
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ConnectionProfile:
    from_email: str = ""
    smtp_password: str = ""


@dataclass(frozen=True)
class ConnectionProfileLoadResult:
    profile: ConnectionProfile
    source_path: Path | None = None
    is_legacy_source: bool = False
    uses_plaintext_secret: bool = False


class ConnectionProfileLoadError(OSError):
    pass


class DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_uint32),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _protect_secret(secret: str) -> tuple[str, str]:
    if not secret:
        return "plain", ""
    if sys.platform != "win32":
        raise OSError("当前系统不支持安全保存 SMTP 授权码")

    raw = secret.encode("utf-8")
    buffer = ctypes.create_string_buffer(raw)
    in_blob = DataBlob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    out_blob = DataBlob()
    if not ctypes.windll.crypt32.CryptProtectData(  # type: ignore[attr-defined]
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    ):
        raise OSError("无法加密 SMTP 授权码")

    try:
        protected = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return "dpapi", base64.b64encode(protected).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))  # type: ignore[attr-defined]


def _unprotect_secret(mode: str, payload: str) -> str:
    if not payload:
        return ""
    if mode != "dpapi":
        return payload
    if sys.platform != "win32":
        raise OSError("当前系统无法解密 Windows DPAPI 凭据")

    protected = base64.b64decode(payload.encode("ascii"))
    in_buffer = ctypes.create_string_buffer(protected)
    in_blob = DataBlob(len(protected), ctypes.cast(in_buffer, ctypes.POINTER(ctypes.c_char)))
    out_blob = DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(  # type: ignore[attr-defined]
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    ):
        raise OSError("无法解密 SMTP 授权码")

    try:
        raw = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return raw.decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))  # type: ignore[attr-defined]


def _read_connection_profile(path: Path, *, is_legacy_source: bool) -> ConnectionProfileLoadResult:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ConnectionProfileLoadError(f"读取连接配置失败：{path}（{exc}）") from exc
    if not isinstance(raw, dict):
        raise ConnectionProfileLoadError(f"连接配置格式错误：{path} 顶层必须是对象")

    password_mode = str(raw.get("smtp_password_mode") or "plain").strip().lower()
    protected_password = raw.get("smtp_password_protected")
    raw_password = raw.get("smtp_password") or raw.get("password") or ""
    uses_plaintext_secret = protected_password is None and bool(raw_password)
    try:
        smtp_password = _unprotect_secret(
            password_mode if protected_password is not None else "plain",
            str(protected_password if protected_password is not None else raw_password),
        )
    except Exception as exc:
        raise ConnectionProfileLoadError(f"连接配置中的 SMTP 授权码无法解密：{path}（{exc}）") from exc

    return ConnectionProfileLoadResult(
        profile=ConnectionProfile(
            from_email=str(raw.get("from_email") or "").strip(),
            smtp_password=smtp_password,
        ),
        source_path=path,
        is_legacy_source=is_legacy_source,
        uses_plaintext_secret=uses_plaintext_secret,
    )


def load_connection_profile_with_metadata(*paths: Path) -> ConnectionProfileLoadResult:
    checked: set[Path] = set()
    for index, raw_path in enumerate(paths):
        path = raw_path.resolve()
        if path in checked or not path.is_file():
            continue
        checked.add(path)
        return _read_connection_profile(path, is_legacy_source=index > 0)

    return ConnectionProfileLoadResult(profile=ConnectionProfile())


def load_connection_profile(*paths: Path) -> ConnectionProfile:
    return load_connection_profile_with_metadata(*paths).profile


def save_connection_profile(*paths: Path, from_email: str, smtp_password: str) -> Path:
    password_mode, password_payload = _protect_secret(smtp_password)
    payload = {
        "from_email": from_email.strip(),
        "smtp_password_mode": password_mode,
        "smtp_password_protected": password_payload,
    }
    last_error: Exception | None = None
    checked: set[Path] = set()
    for raw_path in paths:
        path = raw_path.resolve()
        if path in checked:
            continue
        checked.add(path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return path
        except Exception as exc:
            last_error = exc

    if last_error is None:
        raise ValueError("未提供可写入的连接信息路径")
    raise last_error
