from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from email import policy
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from .rendering import InlineImage


@dataclass(frozen=True)
class Attachment:
    filename: str
    mime_type: str
    data: bytes


def _ensure_within(base_dir: Path, path: Path) -> None:
    if base_dir not in path.parents and path != base_dir:
        raise ValueError(f"路径不允许越界：{path}")


def load_attachments(campaign_dir: Path, rel_paths: list[str]) -> list[Attachment]:
    attachments: list[Attachment] = []
    for rel in rel_paths:
        rel = str(rel).strip()
        if not rel:
            continue
        resolved = (campaign_dir / rel).resolve()
        _ensure_within(campaign_dir, resolved)
        if not resolved.is_file():
            raise FileNotFoundError(f"未找到附件：{resolved}")

        mime_type, _ = mimetypes.guess_type(resolved.name)
        mime_type = mime_type or "application/octet-stream"
        attachments.append(
            Attachment(
                filename=resolved.name,
                mime_type=mime_type,
                data=resolved.read_bytes(),
            )
        )
    return attachments


def attachment_from_path(path: Path) -> Attachment:
    mime_type, _ = mimetypes.guess_type(path.name)
    return Attachment(
        filename=path.name,
        mime_type=mime_type or "application/octet-stream",
        data=path.read_bytes(),
    )


def build_email_message(
    *,
    from_email: str,
    to_email: str | list[str],
    cc_email: str | list[str] | None = None,
    subject: str,
    text_body: str,
    html_body: str,
    inline_images: list[InlineImage],
    attachments: list[Attachment],
) -> EmailMessage:
    def _join_header(value: str | list[str] | None) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            raw_items = value.replace("；", ";").replace(",", ";").split(";")
        else:
            raw_items = []
            for item in value:
                raw_items.extend(str(item).replace("；", ";").replace(",", ";").split(";"))
        items = [item.strip() for item in raw_items if str(item).strip()]
        return ", ".join(items)

    msg = EmailMessage(policy=policy.SMTP)
    msg["From"] = from_email
    msg["To"] = _join_header(to_email)
    cc_header = _join_header(cc_email)
    if cc_header:
        msg["Cc"] = cc_header
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=from_email.split("@")[-1])

    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    html_part = msg.get_body(preferencelist=("html",))
    if html_part is None:
        raise RuntimeError("构建 HTML part 失败")

    for img in inline_images:
        maintype, subtype = img.mime_type.split("/", 1)
        html_part.add_related(
            img.data,
            maintype=maintype,
            subtype=subtype,
            cid=f"<{img.cid}>",
            filename=img.filename,
            disposition="inline",
        )

    for att in attachments:
        maintype, subtype = att.mime_type.split("/", 1) if "/" in att.mime_type else ("application", "octet-stream")
        msg.add_attachment(
            att.data,
            maintype=maintype,
            subtype=subtype,
            filename=att.filename,
        )

    return msg
