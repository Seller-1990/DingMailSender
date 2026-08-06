from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .constants import DEFAULT_IMAP_HOST, DEFAULT_IMAP_PORT_SSL, DEFAULT_SMTP_HOST, DEFAULT_SMTP_PORT_SSL

SmtpSecurity = Literal["ssl", "starttls"]


@dataclass(frozen=True)
class SmtpConfig:
    host: str = DEFAULT_SMTP_HOST
    port: int = DEFAULT_SMTP_PORT_SSL
    security: SmtpSecurity = "ssl"
    username: str = ""


@dataclass(frozen=True)
class ImapConfig:
    host: str = DEFAULT_IMAP_HOST
    port: int = DEFAULT_IMAP_PORT_SSL
    username: str = ""
