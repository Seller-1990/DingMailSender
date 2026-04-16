from __future__ import annotations

import imaplib
import re
import time
from email.message import EmailMessage


class ImapDraftsSession:
    def __init__(self, host: str, port: int, username: str, password: str, timeout_seconds: int = 30) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._timeout_seconds = timeout_seconds
        self._imap: imaplib.IMAP4_SSL | None = None
        self._drafts_mailbox: str | None = None

    def __enter__(self) -> "ImapDraftsSession":
        imaplib._MAXLINE = max(imaplib._MAXLINE, 1_000_000)  # type: ignore[attr-defined]
        session = imaplib.IMAP4_SSL(self._host, self._port, timeout=self._timeout_seconds)
        session.login(self._username, self._password)
        self._imap = session
        self._drafts_mailbox = self._discover_drafts_mailbox()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        if self._imap is None:
            return
        try:
            self._imap.logout()
        except Exception:
            pass
        self._imap = None

    def append_draft(self, msg: EmailMessage) -> str:
        if self._imap is None:
            raise RuntimeError("IMAP 会话未建立")

        mailbox = self._drafts_mailbox or self._create_or_pick_fallback_mailbox()
        payload = msg.as_bytes()
        internal_date = imaplib.Time2Internaldate(time.time())
        status, data = self._imap.append(mailbox, "\\Draft", internal_date, payload)
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

        parsed_names: list[tuple[str, str]] = []
        for raw in boxes:
            if not raw:
                continue
            line = raw.decode("utf-8", errors="ignore")
            name = self._extract_mailbox_name(line)
            if not name:
                continue
            parsed_names.append((line.lower(), name))

        for line, name in parsed_names:
            if "\\drafts" in line:
                return name
        for line, name in parsed_names:
            if "draft" in line or "草稿" in line:
                return name
        return None

    def _create_or_pick_fallback_mailbox(self) -> str:
        if self._imap is None:
            raise RuntimeError("IMAP 会话未建立")

        candidates = ["Drafts", "草稿箱", "INBOX.Drafts", "INBOX/草稿箱", "INBOX/草稿"]
        for mailbox in candidates:
            status, _ = self._imap.select(mailbox, readonly=True)
            if status == "OK":
                return mailbox

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
