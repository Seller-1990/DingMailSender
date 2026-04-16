from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .constants import (
    DEFAULT_RATE_LIMIT_SECONDS,
    DEFAULT_SMTP_PORT_SSL,
)

SmtpSecurity = Literal["ssl", "starttls"]


@dataclass(frozen=True)
class SmtpConfig:
    host: str = "smtp.qiye.aliyun.com"
    port: int = DEFAULT_SMTP_PORT_SSL
    security: SmtpSecurity = "ssl"
    username: str = ""


@dataclass(frozen=True)
class RecipientsConfig:
    file: str = "recipients.xlsx"
    sheet: str | None = None
    header_row: int = 1
    columns: dict[str, str] = field(
        default_factory=lambda: {
            "email": "邮箱",
            "name": "姓名",
        }
    )


@dataclass(frozen=True)
class CampaignConfig:
    from_email: str = ""
    subject_template: str = "（请在 campaign.yml 中配置主题）"
    body_template_file: str = "template.md"
    assets_dir: str = "assets"
    attachments: list[str] = field(default_factory=list)
    allow_recipient_domains: list[str] = field(default_factory=list)
    rate_limit_seconds: float = DEFAULT_RATE_LIMIT_SECONDS

    recipients: RecipientsConfig = field(default_factory=RecipientsConfig)
    smtp: SmtpConfig = field(default_factory=SmtpConfig)

    def validate(self) -> None:
        if not self.from_email.strip():
            raise ValueError("from_email 不能为空")

        if self.smtp.port <= 0 or self.smtp.port > 65535:
            raise ValueError(f"SMTP port 非法：{self.smtp.port}")

        if self.rate_limit_seconds < 0:
            raise ValueError("rate_limit_seconds 不能为负数")

        if self.recipients.header_row <= 0:
            raise ValueError("recipients.header_row 必须 >= 1")

        if self.smtp.security not in ("ssl", "starttls"):
            raise ValueError(f"smtp.security 必须是 ssl 或 starttls，当前为：{self.smtp.security!r}")

        if not self.smtp.username.strip():
            raise ValueError("smtp.username 不能为空（用于 SMTP 登录）")

    def validate_for_send(self) -> None:
        self.validate()
        if not self.smtp.host:
            raise ValueError("SMTP host 不能为空（campaign.yml -> smtp.host）")
