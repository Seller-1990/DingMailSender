from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re

from .constants import MAX_ATTACHMENT_BYTES, MAX_EMAIL_ASSET_BYTES, MAX_INLINE_IMAGE_BYTES, MEBIBYTE
from .email_builder import Attachment, attachment_from_path
from .rendering import (
    InlineImage,
    embed_cid_images,
    inspect_local_images,
    markdown_to_html,
    rewrite_local_images_for_preview,
    wrap_email_html,
)
from .task_models import MailTask
from .task_package import resolve_user_path

EMAIL_RE = re.compile(r"^[^@\s;]+@[^@\s]+\.[^@\s]+$")


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
    first_non_empty = _first_non_empty_line_index(lines)
    if first_non_empty is None:
        return ""

    remove_until = _leading_title_end_index(lines, first_non_empty)
    if remove_until is None:
        return text.strip()

    while remove_until < len(lines) and not lines[remove_until].strip():
        remove_until += 1
    return "\n".join(lines[remove_until:]).strip()


def _first_non_empty_line_index(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        if line.strip():
            return index
    return None


def _leading_title_end_index(lines: list[str], first_non_empty: int) -> int | None:
    first_line = lines[first_non_empty].strip()
    if re.match(r"^#{1,6}\s+\S+", first_line):
        return first_non_empty + 1

    if first_non_empty + 1 >= len(lines):
        return None
    underline = lines[first_non_empty + 1].strip()
    if first_line and re.match(r"^(=+|-+)\s*$", underline):
        return first_non_empty + 2
    return None


def _preserve_intro_line_breaks(intro_text: str) -> str:
    lines = str(intro_text or "").strip().splitlines()
    return "\n".join(f"{line.rstrip()}  " if line.strip() else "" for line in lines).strip()


def _resolve_attachments(task: MailTask, package_dir: Path) -> list[Attachment]:
    attachments: list[Attachment] = []
    for raw in task.attachment_paths:
        path = resolve_user_path(package_dir, raw)
        if not path.is_file():
            raise FileNotFoundError(f"未找到附件：{path}")
        attachments.append(attachment_from_path(path))
    return attachments


def _compose_markdown_parts(task: MailTask, package_dir: Path) -> tuple[str, Path]:
    markdown_body, markdown_parent = _read_markdown_file(task, package_dir)
    return _compose_markdown_text(task, markdown_body), markdown_parent


def _compose_markdown_text(task: MailTask, markdown_body: str) -> str:
    intro = _preserve_intro_line_breaks(task.intro_text)
    body = _strip_leading_markdown_title(markdown_body)
    if intro and body:
        return f"{intro}\n\n{body}"
    if intro:
        return intro
    return body


def compose_task_markdown(task: MailTask, package_dir: Path) -> str:
    composed_markdown, _ = _compose_markdown_parts(task, package_dir)
    return composed_markdown


def render_task_preview_html(task: MailTask, package_dir: Path) -> str:
    composed_markdown, markdown_parent = _compose_markdown_parts(task, package_dir)
    if not composed_markdown:
        raise ValueError("邮件正文为空")
    html = wrap_email_html(markdown_to_html(composed_markdown))
    return rewrite_local_images_for_preview(html, markdown_parent, containment_root=package_dir)


def render_task_email(task: MailTask, package_dir: Path) -> RenderedTaskEmail:
    composed_markdown, markdown_parent = _compose_markdown_parts(task, package_dir)
    if not composed_markdown:
        raise ValueError("邮件正文为空")

    html = wrap_email_html(markdown_to_html(composed_markdown))
    asset_errors = _validate_task_assets(task, package_dir, html, markdown_parent)
    if asset_errors:
        raise ValueError("；".join(asset_errors))
    html_for_preview = rewrite_local_images_for_preview(html, markdown_parent, containment_root=package_dir)
    html_for_email, inline_images = embed_cid_images(html, markdown_parent, containment_root=package_dir)
    attachments = _resolve_attachments(task, package_dir)

    return RenderedTaskEmail(
        composed_markdown=composed_markdown,
        html_for_preview=html_for_preview,
        html_for_email=html_for_email,
        inline_images=inline_images,
        attachments=attachments,
    )


def _size_mib(size: int) -> str:
    return f"{size / MEBIBYTE:.1f} MiB"


def _validate_task_assets(
    task: MailTask,
    package_dir: Path,
    html: str,
    markdown_parent: Path,
) -> list[str]:
    errors: list[str] = []
    total_bytes = 0
    image_paths, image_errors = inspect_local_images(html, markdown_parent, containment_root=package_dir)
    errors.extend(image_errors)
    for image in image_paths:
        size = image.stat().st_size
        total_bytes += size
        if size > MAX_INLINE_IMAGE_BYTES:
            errors.append(
                f"内联图片过大：{image.name}（{_size_mib(size)}），上限 {_size_mib(MAX_INLINE_IMAGE_BYTES)}"
            )

    for raw in task.attachment_paths:
        if not str(raw).strip():
            continue
        try:
            attachment = resolve_user_path(package_dir, raw)
            if not attachment.is_file():
                errors.append(f"附件不存在：{attachment}")
                continue
            size = attachment.stat().st_size
            total_bytes += size
            if size > MAX_ATTACHMENT_BYTES:
                errors.append(
                    f"附件过大：{attachment.name}（{_size_mib(size)}），上限 {_size_mib(MAX_ATTACHMENT_BYTES)}"
                )
        except Exception as exc:
            errors.append(str(exc))

    if total_bytes > MAX_EMAIL_ASSET_BYTES:
        errors.append(
            f"邮件附件和内联图片总大小为 {_size_mib(total_bytes)}，上限 {_size_mib(MAX_EMAIL_ASSET_BYTES)}"
        )
    return errors


def _validate_content_and_assets(task: MailTask, package_dir: Path) -> list[str]:
    if not task.markdown_path.strip():
        return ["Markdown 路径为空"]
    try:
        markdown_file = resolve_user_path(package_dir, task.markdown_path)
        if not markdown_file.is_file():
            return [f"Markdown 文件不存在：{markdown_file}"]
        markdown_text = markdown_file.read_text(encoding="utf-8")
        composed_markdown = _compose_markdown_text(task, markdown_text)
        if not composed_markdown:
            return ["邮件正文为空"]
        html = wrap_email_html(markdown_to_html(composed_markdown))
        return _validate_task_assets(task, package_dir, html, markdown_file.parent)
    except Exception as exc:
        return [str(exc)]


def _validate_schedule(task: MailTask, now: datetime | None) -> list[str]:
    if not task.schedule_enabled:
        return []
    if task.scheduled_at is None:
        return ["已勾选定时发送，但未填写发送时间"]
    if now is not None and task.scheduled_at < now:
        return ["定时发送时间早于当前时间"]
    return []


def _validate_recipients(task: MailTask) -> list[str]:
    errors: list[str] = []
    if not task.to_recipients:
        errors.append("收件人为空")
    invalid_to = [email for email in task.to_recipients if not EMAIL_RE.match(email)]
    invalid_cc = [email for email in task.cc_recipients if not EMAIL_RE.match(email)]
    if invalid_to:
        errors.append(f"收件人邮箱格式不合法：{'; '.join(invalid_to)}")
    if invalid_cc:
        errors.append(f"抄送邮箱格式不合法：{'; '.join(invalid_cc)}")
    return errors


def validate_task(task: MailTask, package_dir: Path, now: datetime | None = None) -> list[str]:
    errors: list[str] = []
    if not task.enabled:
        return errors

    errors.extend(_validate_recipients(task))
    if not task.subject.strip():
        errors.append("主题为空")
    errors.extend(_validate_content_and_assets(task, package_dir))
    errors.extend(_validate_schedule(task, now))
    return errors
