from __future__ import annotations

import base64
import imaplib
import re
import time
from email.message import EmailMessage


def _decode_imap_utf7(value: str) -> str:
    parts: list[str] = []
    index = 0
    while index < len(value):
        if value[index] != "&":
            parts.append(value[index])
            index += 1
            continue

        end = value.find("-", index)
        if end < 0:
            parts.append(value[index:])
            break

        token = value[index + 1 : end]
        if not token:
            parts.append("&")
        else:
            payload = token.replace(",", "/")
            padding = "=" * ((4 - (len(payload) % 4)) % 4)
            decoded = base64.b64decode(payload + padding)
            parts.append(decoded.decode("utf-16-be"))
        index = end + 1

    return "".join(parts)


def _encode_imap_utf7(value: str) -> str:
    parts: list[str] = []
    buffer: list[str] = []

    def _flush_buffer() -> None:
        if not buffer:
            return
        payload = "".join(buffer).encode("utf-16-be")
        encoded = base64.b64encode(payload).decode("ascii").rstrip("=").replace("/", ",")
        parts.append(f"&{encoded}-")
        buffer.clear()

    for char in value:
        if char == "&":
            _flush_buffer()
            parts.append("&-")
            continue
        if 0x20 <= ord(char) <= 0x7E:
            _flush_buffer()
            parts.append(char)
            continue
        buffer.append(char)

    _flush_buffer()
    return "".join(parts)


def _quote_mailbox(name: str) -> str:
    """Quote a mailbox name for the IMAP wire protocol when required.

    imaplib does not quote mailbox arguments itself; an unquoted name that
    contains spaces breaks APPEND/SELECT at the protocol level.
    """
    if not name:
        return name
    if name.startswith('"') and name.endswith('"') and len(name) >= 2:
        return name
    if not any(char in name for char in ' "\\'):
        return name
    escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


class ImapDraftsSession:
    def __init__(self, host: str, port: int, username: str, password: str, timeout_seconds: int = 30) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._timeout_seconds = timeout_seconds
        self._imap: imaplib.IMAP4_SSL | None = None
        self._drafts_mailbox: str | None = None
        self._original_maxline: int = imaplib._MAXLINE  # type: ignore[attr-defined]

    def __enter__(self) -> "ImapDraftsSession":
        self._original_maxline = imaplib._MAXLINE  # type: ignore[attr-defined]
        imaplib._MAXLINE = max(imaplib._MAXLINE, 1_000_000)  # type: ignore[attr-defined]
        session = imaplib.IMAP4_SSL(self._host, self._port, timeout=self._timeout_seconds)
        try:
            session.login(self._username, self._password)
            self._imap = session
            self._drafts_mailbox = self._discover_drafts_mailbox()
        except BaseException:
            self._imap = None
            self._drafts_mailbox = None
            try:
                session.logout()
            except Exception:
                try:
                    session.shutdown()
                except Exception:
                    pass
            raise
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        if self._imap is None:
            return
        try:
            self._imap.logout()
        except Exception:
            pass
        self._imap = None
        imaplib._MAXLINE = self._original_maxline  # type: ignore[attr-defined]

    def append_draft(self, msg: EmailMessage) -> str:
        if self._imap is None:
            raise RuntimeError("IMAP 会话未建立")

        mailbox = self._drafts_mailbox or self._create_or_pick_fallback_mailbox()
        payload = msg.as_bytes()
        internal_date = imaplib.Time2Internaldate(time.time())
        status, data = self._imap.append(_quote_mailbox(mailbox), "\\Draft", internal_date, payload)
        if status != "OK":
            detail = data[0].decode("utf-8", errors="ignore") if data and isinstance(data[0], bytes) else str(data)
            raise RuntimeError(f"写入草稿箱失败: {detail}")
        return mailbox

    def _discover_drafts_mailbox(self) -> str | None:
        if self._imap is None:
            return None
        status, boxes = self._imap.list()
        if status != "OK" or not boxes:
            return None
        return self._pick_drafts_mailbox(self._parse_mailbox_entries(boxes))

    def _parse_mailbox_entries(self, boxes) -> list[tuple[str, str, str]]:
        parsed_names: list[tuple[str, str, str]] = []
        for raw in boxes:
            if not raw:
                continue
            line = raw.decode("utf-8", errors="ignore")
            name = self._extract_mailbox_name(line)
            if not name:
                continue
            try:
                decoded_name = _decode_imap_utf7(name)
            except Exception:
                decoded_name = name
            parsed_names.append((line.lower(), name, decoded_name.lower()))
        return parsed_names

    @staticmethod
    def _pick_drafts_mailbox(parsed_names: list[tuple[str, str, str]]) -> str | None:
        for line, name, _decoded_name in parsed_names:
            if "\\drafts" in line:
                return name
        for line, name, decoded_name in parsed_names:
            if "draft" in line or "draft" in decoded_name or "草稿" in decoded_name:
                return name
        return None

    def _create_or_pick_fallback_mailbox(self) -> str:
        if self._imap is None:
            raise RuntimeError("IMAP 会话未建立")

        candidates = ["Drafts", "草稿箱", "INBOX.Drafts", "INBOX/草稿箱", "INBOX/草稿"]
        for mailbox in candidates:
            encoded_mailbox = _encode_imap_utf7(mailbox)
            status, _ = self._imap.select(_quote_mailbox(encoded_mailbox), readonly=True)
            if status == "OK":
                return encoded_mailbox

        status, _ = self._imap.create("Drafts")
        if status == "OK":
            return "Drafts"

        raise RuntimeError("未找到可用草稿箱，请在邮箱网页端确认草稿文件夹名称。")

    @staticmethod
    def _extract_mailbox_name(line: str) -> str:
        quoted = re.search(r'"((?:[^"\\]|\\.)*)"\s*$', line)
        if quoted:
            return quoted.group(1).replace('\\"', '"').strip()

        unquoted = re.search(r'\)\s+"[^"]+"\s+(.+)$', line)
        if unquoted:
            return unquoted.group(1).strip()
        return ""
