from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from email import policy
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, getaddresses
from pathlib import Path

from .rendering import InlineImage


@dataclass(frozen=True)
class Attachment:
    filename: str
    mime_type: str
    data: bytes


@dataclass(frozen=True)
class EmailMessageInput:
    from_email: str
    to_email: str | list[str]
    subject: str
    text_body: str
    html_body: str
    inline_images: list[InlineImage]
    attachments: list[Attachment]
    cc_email: str | list[str] | None = None


def _reject_header_control_chars(label: str, value: str) -> None:
    for char in value:
        if char in "\r\n\x00" or (ord(char) < 32 and char not in "\t"):
            raise ValueError(f"{label} 包含不允许的控制字符")


def _split_header_values(value: str | list[str]) -> list[str]:
    if isinstance(value, str):
        source_items = [value]
    else:
        source_items = [str(item) for item in value]

    items: list[str] = []
    for item in source_items:
        normalized = item.replace("；", ";").replace(",", ";")
        items.extend(part.strip() for part in normalized.split(";") if part.strip())
    return items

def _format_email_header(label: str, value: str | list[str] | None) -> str:
    if value is None:
        return ""

    items = _split_header_values(value)
    for item in items:
        _reject_header_control_chars(label, item)

    parsed = getaddresses(items)
    if len(parsed) != len(items) or any(not address for _name, address in parsed):
        raise ValueError(f"{label} 包含不合法的邮箱地址")
    return ", ".join(address for _name, address in parsed)


def _format_text_header(label: str, value: str) -> str:
    text = str(value or "").strip()
    _reject_header_control_chars(label, text)
    return text


def attachment_from_path(path: Path) -> Attachment:
    mime_type, _ = mimetypes.guess_type(path.name)
    return Attachment(
        filename=path.name,
        mime_type=mime_type or "application/octet-stream",
        data=path.read_bytes(),
    )


def build_email_message(data: EmailMessageInput) -> EmailMessage:
    from_header = _format_email_header("发件人", data.from_email)
    to_header = _format_email_header("收件人", data.to_email)
    cc_header = _format_email_header("抄送人", data.cc_email)
    subject_header = _format_text_header("主题", data.subject)

    msg = EmailMessage(policy=policy.SMTP)
    msg["From"] = from_header
    msg["To"] = to_header
    if cc_header:
        msg["Cc"] = cc_header
    msg["Subject"] = subject_header
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=from_header.split("@")[-1])

    msg.set_content(data.text_body)
    msg.add_alternative(data.html_body, subtype="html")

    html_part = msg.get_body(preferencelist=("html",))
    if html_part is None:
        raise RuntimeError("构建 HTML part 失败")

    for img in data.inline_images:
        maintype, subtype = img.mime_type.split("/", 1)
        html_part.add_related(
            img.data,
            maintype=maintype,
            subtype=subtype,
            cid=f"<{img.cid}>",
            filename=img.filename,
            disposition="inline",
        )

    for att in data.attachments:
        maintype, subtype = att.mime_type.split("/", 1) if "/" in att.mime_type else ("application", "octet-stream")
        msg.add_attachment(
            att.data,
            maintype=maintype,
            subtype=subtype,
            filename=att.filename,
        )

    return msg
