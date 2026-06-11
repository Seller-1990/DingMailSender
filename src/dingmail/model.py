from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .constants import DEFAULT_SMTP_PORT_SSL

SmtpSecurity = Literal["ssl", "starttls"]


@dataclass(frozen=True)
class SmtpConfig:
    host: str = "smtp.qiye.aliyun.com"
    port: int = DEFAULT_SMTP_PORT_SSL
    security: SmtpSecurity = "ssl"
    username: str = ""
