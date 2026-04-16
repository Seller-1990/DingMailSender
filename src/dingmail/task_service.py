from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re

from .email_builder import Attachment, attachment_from_path, build_email_message
from .rendering import InlineImage, embed_cid_images, markdown_to_html, rewrite_local_images_for_preview, wrap_email_html
from .task_models import MailTask
from .task_package import resolve_user_path


@dataclass(frozen=True)
class RenderedTaskEmail:
    composed_markdown: str
    html_for_preview: str
    html_for_email: str
    inline_images: list[InlineImage]
    attachments: list[Attachment]


def _read_markdown_file(task: MailTask, package_dir: Path) -> tuple[str, Path]:
    markdown_file = resolve_user_path(package_dir, task.markdown_path)
    if not markdown_file.is_file():
        raise FileNotFoundError(f"未找到 Markdown 文件：{markdown_file}")
    return markdown_file.read_text(encoding="utf-8"), markdown_file.parent


def _strip_leading_markdown_title(markdown_text: str) -> str:
    text = markdown_text.lstrip("\ufeff")
    lines = text.splitlines()
    if not lines:
        return ""

    first_non_empty = 0
    while first_non_empty < len(lines) and not lines[first_non_empty].strip():
        first_non_empty += 1
    if first_non_empty >= len(lines):
        return ""

    remove_until: int | None = None
    first_line = lines[first_non_empty].strip()
    if re.match(r"^#{1,6}\s+\S+", first_line):
        remove_until = first_non_empty + 1
    elif first_non_empty + 1 < len(lines):
        underline = lines[first_non_empty + 1].strip()
        if first_line and re.match(r"^(=+|-+)\s*$", underline):
            remove_until = first_non_empty + 2

    if remove_until is None:
        return text.strip()

    while remove_until < len(lines) and not lines[remove_until].strip():
        remove_until += 1
    return "\n".join(lines[remove_until:]).strip()


def _resolve_attachments(task: MailTask, package_dir: Path) -> list[Attachment]:
    attachments: list[Attachment] = []
    for raw in task.attachment_paths:
        path = resolve_user_path(package_dir, raw)
        if not path.is_file():
            raise FileNotFoundError(f"未找到附件：{path}")
        attachments.append(attachment_from_path(path))
    return attachments


def compose_task_markdown(task: MailTask, package_dir: Path) -> str:
    markdown_body, _ = _read_markdown_file(task, package_dir)
    intro = (task.intro_text or "").strip()
    body = _strip_leading_markdown_title(markdown_body)
    if intro and body:
        return f"{intro}\n\n{body}"
    if intro:
        return intro
    return body


def render_task_email(task: MailTask, package_dir: Path) -> RenderedTaskEmail:
    markdown_body, markdown_parent = _read_markdown_file(task, package_dir)
    intro = (task.intro_text or "").strip()
    body = _strip_leading_markdown_title(markdown_body)
    composed_markdown = f"{intro}\n\n{body}".strip() if intro else body
    if not composed_markdown:
        raise ValueError("邮件正文为空")

    html = wrap_email_html(markdown_to_html(composed_markdown))
    html_for_preview = rewrite_local_images_for_preview(html, markdown_parent)
    html_for_email, inline_images = embed_cid_images(html, markdown_parent)
    attachments = _resolve_attachments(task, package_dir)

    return RenderedTaskEmail(
        composed_markdown=composed_markdown,
        html_for_preview=html_for_preview,
        html_for_email=html_for_email,
        inline_images=inline_images,
        attachments=attachments,
    )


def build_task_message(task: MailTask, package_dir: Path, from_email: str):
    rendered = render_task_email(task, package_dir)
    return build_email_message(
        from_email=from_email,
        to_email=task.to_recipients,
        cc_email=task.cc_recipients,
        subject=task.subject,
        text_body=rendered.composed_markdown,
        html_body=rendered.html_for_email,
        inline_images=rendered.inline_images,
        attachments=rendered.attachments,
    )


def validate_task(task: MailTask, package_dir: Path, now: datetime | None = None) -> list[str]:
    errors: list[str] = []
    if not task.enabled:
        return errors

    if not task.to_recipients:
        errors.append("收件人为空")
    if not task.subject.strip():
        errors.append("主题为空")
    if not task.markdown_path.strip():
        errors.append("Markdown 路径为空")
    else:
        try:
            markdown_file = resolve_user_path(package_dir, task.markdown_path)
            if not markdown_file.is_file():
                errors.append(f"Markdown 文件不存在：{markdown_file}")
        except Exception as exc:
            errors.append(str(exc))

    for raw in task.attachment_paths:
        if not str(raw).strip():
            continue
        try:
            attachment = resolve_user_path(package_dir, raw)
            if not attachment.is_file():
                errors.append(f"附件不存在：{attachment}")
        except Exception as exc:
            errors.append(str(exc))

    if task.schedule_enabled:
        if task.scheduled_at is None:
            errors.append("已勾选定时发送，但未填写发送时间")
        elif now is not None and task.scheduled_at < now:
            errors.append("定时发送时间早于当前时间")

    return errors
