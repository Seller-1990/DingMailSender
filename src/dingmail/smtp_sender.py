from __future__ import annotations

import ssl
import time
from dataclasses import dataclass
from email.message import EmailMessage
from smtplib import SMTP, SMTP_SSL

from .model import SmtpConfig


@dataclass(frozen=True)
class SmtpSendResult:
    message_id: str | None
    rejected_recipients: dict[str, tuple[int, bytes]] | None = None

    @property
    def has_partial_failure(self) -> bool:
        return bool(self.rejected_recipients)


class SmtpSession:
    def __init__(self, cfg: SmtpConfig, password: str, timeout_seconds: int = 30) -> None:
        self._cfg = cfg
        self._password = password
        self._timeout = timeout_seconds
        self._smtp: SMTP | None = None

    def __enter__(self) -> "SmtpSession":
        if self._cfg.security == "ssl":
            server: SMTP = SMTP_SSL(
                self._cfg.host,
                self._cfg.port,
                timeout=self._timeout,
                context=ssl.create_default_context(),
            )
        else:
            server = SMTP(self._cfg.host, self._cfg.port, timeout=self._timeout)
        try:
            server.ehlo()
            if self._cfg.security == "starttls":
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            if self._cfg.username:
                server.login(self._cfg.username, self._password)
        except BaseException:
            try:
                server.close()
            except Exception:
                pass
            raise
        self._smtp = server
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        if self._smtp is not None:
            try:
                self._smtp.quit()
            except Exception:
                try:
                    self._smtp.close()
                except Exception:
                    pass
        self._smtp = None

    def send(self, msg: EmailMessage) -> SmtpSendResult:
        if self._smtp is None:
            raise RuntimeError("SMTP session 未建立")
        resp = self._smtp.send_message(msg)
        if resp:
            return SmtpSendResult(
                message_id=msg.get("Message-ID"),
                rejected_recipients=resp,
            )
        return SmtpSendResult(message_id=msg.get("Message-ID"))


def rate_limit_sleep(seconds: float) -> None:
    if seconds <= 0:
        return
    time.sleep(seconds)
