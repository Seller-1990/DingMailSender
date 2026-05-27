from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from .constants import (
    DEFAULT_IMAP_HOST,
    DEFAULT_IMAP_PORT_SSL,
    DEFAULT_RATE_LIMIT_SECONDS,
)
from .email_builder import build_email_message
from .imap_drafts import ImapDraftsSession
from .model import SmtpConfig, SmtpSecurity
from .run_store import RunPaths, append_manifest_row, create_run_paths, snapshot_file
from .smtp_sender import SmtpSession, rate_limit_sleep
from .task_models import MailTask
from .task_package import PACKAGE_README_FILENAME, TASKS_FILENAME
from .task_service import RenderedTaskEmail, render_task_email


@dataclass(frozen=True)
class TaskDeliveryOutcome:
    task_id: str
    to_email: str
    cc_email: str
    subject: str
    status: str
    message_id: str | None
    error: str | None


@dataclass(frozen=True)
class SendTasksResult:
    run_paths: RunPaths
    outcomes: list[TaskDeliveryOutcome]


def _safe_filename(text: str) -> str:
    parts = []
    for char in text:
        if char.isalnum() or char in ("-", "_", "."):
            parts.append(char)
        else:
            parts.append("_")
    return "".join(parts).strip("_") or "task"


def _build_logger(log_path: Path, name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    for old_handler in logger.handlers:
        old_handler.close()
    logger.handlers.clear()
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def _close_logger(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


def _build_message_from_rendered(task: MailTask, from_email: str, rendered: RenderedTaskEmail):
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


def _write_task_artifacts(
    *,
    run_paths: RunPaths,
    index: int,
    task: MailTask,
    rendered: RenderedTaskEmail,
    message,
) -> None:
    identity = task.subject or ";".join(task.to_recipients) or task.task_id
    base = f"{index:03d}_{_safe_filename(identity)}"
    (run_paths.previews_dir / f"{base}.preview.html").write_text(rendered.html_for_preview, encoding="utf-8")
    (run_paths.eml_dir / f"{base}.eml").write_bytes(message.as_bytes())


def _sleep_between_tasks(index: int, total: int, rate_limit_seconds: float) -> None:
    if index < total:
        rate_limit_sleep(rate_limit_seconds)


def send_tasks(
    *,
    tasks: list[MailTask],
    package_dir: Path,
    home_dir: Path,
    smtp_host: str,
    smtp_port: int,
    smtp_security: str,
    smtp_username: str,
    smtp_password: str,
    rate_limit_seconds: float = DEFAULT_RATE_LIMIT_SECONDS,
) -> SendTasksResult:
    run_paths = create_run_paths(home_dir=home_dir, campaign_dir=package_dir)
    logger = _build_logger(run_paths.logs_dir / "send.log", f"dingmail.send.{run_paths.run_dir.name}")

    snapshot_file(package_dir / TASKS_FILENAME, run_paths.run_dir, TASKS_FILENAME)
    snapshot_file(package_dir / PACKAGE_README_FILENAME, run_paths.run_dir, PACKAGE_README_FILENAME)

    normalized_security = str(smtp_security).strip().lower()
    if normalized_security not in ("ssl", "starttls"):
        raise ValueError(f"smtp_security 必须是 ssl 或 starttls，当前为：{smtp_security!r}")

    smtp_cfg = SmtpConfig(
        host=smtp_host,
        port=smtp_port,
        security=cast(SmtpSecurity, normalized_security),
        username=smtp_username,
    )

    outcomes: list[TaskDeliveryOutcome] = []
    total = len(tasks)
    try:
        with SmtpSession(smtp_cfg, smtp_password) as smtp:
            for index, task in enumerate(tasks, start=1):
                try:
                    rendered = render_task_email(task, package_dir)
                    message = _build_message_from_rendered(task, smtp_username, rendered)
                    _write_task_artifacts(
                        run_paths=run_paths,
                        index=index,
                        task=task,
                        rendered=rendered,
                        message=message,
                    )

                    result = smtp.send(message)
                    outcome = TaskDeliveryOutcome(
                        task_id=task.task_id,
                        to_email="; ".join(task.to_recipients),
                        cc_email="; ".join(task.cc_recipients),
                        subject=task.subject,
                        status="sent",
                        message_id=result.message_id,
                        error=None,
                    )
                    append_manifest_row(
                        run_paths.manifest_csv,
                        idx=index,
                        to_email=outcome.to_email,
                        subject=outcome.subject,
                        status=outcome.status,
                        message_id=outcome.message_id,
                        error=None,
                    )
                    outcomes.append(outcome)
                    logger.info("sent task_id=%s to=%s", task.task_id, task.to_recipients)
                except Exception as exc:
                    outcome = TaskDeliveryOutcome(
                        task_id=task.task_id,
                        to_email="; ".join(task.to_recipients),
                        cc_email="; ".join(task.cc_recipients),
                        subject=task.subject,
                        status="send_error",
                        message_id=None,
                        error=str(exc),
                    )
                    append_manifest_row(
                        run_paths.manifest_csv,
                        idx=index,
                        to_email=outcome.to_email,
                        subject=outcome.subject,
                        status=outcome.status,
                        message_id=None,
                        error=outcome.error,
                    )
                    outcomes.append(outcome)
                    logger.exception("send_error task_id=%s: %s", task.task_id, exc)
                finally:
                    _sleep_between_tasks(index, total, rate_limit_seconds)
        return SendTasksResult(run_paths=run_paths, outcomes=outcomes)
    finally:
        _close_logger(logger)


def save_tasks_to_imap_drafts(
    *,
    tasks: list[MailTask],
    package_dir: Path,
    home_dir: Path,
    imap_username: str,
    imap_password: str,
    imap_host: str = DEFAULT_IMAP_HOST,
    imap_port: int = DEFAULT_IMAP_PORT_SSL,
    rate_limit_seconds: float = DEFAULT_RATE_LIMIT_SECONDS,
) -> SendTasksResult:
    run_paths = create_run_paths(home_dir=home_dir, campaign_dir=package_dir)
    logger = _build_logger(run_paths.logs_dir / "drafts.log", f"dingmail.drafts.{run_paths.run_dir.name}")

    snapshot_file(package_dir / TASKS_FILENAME, run_paths.run_dir, TASKS_FILENAME)
    snapshot_file(package_dir / PACKAGE_README_FILENAME, run_paths.run_dir, PACKAGE_README_FILENAME)

    outcomes: list[TaskDeliveryOutcome] = []
    total = len(tasks)
    try:
        with ImapDraftsSession(
            host=imap_host,
            port=imap_port,
            username=imap_username,
            password=imap_password,
        ) as drafts:
            for index, task in enumerate(tasks, start=1):
                try:
                    rendered = render_task_email(task, package_dir)
                    message = _build_message_from_rendered(task, imap_username, rendered)
                    _write_task_artifacts(
                        run_paths=run_paths,
                        index=index,
                        task=task,
                        rendered=rendered,
                        message=message,
                    )

                    mailbox = drafts.append_draft(message)
                    outcome = TaskDeliveryOutcome(
                        task_id=task.task_id,
                        to_email="; ".join(task.to_recipients),
                        cc_email="; ".join(task.cc_recipients),
                        subject=task.subject,
                        status="draft_saved",
                        message_id=message.get("Message-ID"),
                        error=None,
                    )
                    append_manifest_row(
                        run_paths.manifest_csv,
                        idx=index,
                        to_email=outcome.to_email,
                        subject=outcome.subject,
                        status=outcome.status,
                        message_id=outcome.message_id,
                        error=None,
                    )
                    outcomes.append(outcome)
                    logger.info("draft_saved task_id=%s mailbox=%s", task.task_id, mailbox)
                except Exception as exc:
                    outcome = TaskDeliveryOutcome(
                        task_id=task.task_id,
                        to_email="; ".join(task.to_recipients),
                        cc_email="; ".join(task.cc_recipients),
                        subject=task.subject,
                        status="draft_error",
                        message_id=None,
                        error=str(exc),
                    )
                    append_manifest_row(
                        run_paths.manifest_csv,
                        idx=index,
                        to_email=outcome.to_email,
                        subject=outcome.subject,
                        status=outcome.status,
                        message_id=None,
                        error=outcome.error,
                    )
                    outcomes.append(outcome)
                    logger.exception("draft_error task_id=%s: %s", task.task_id, exc)
                finally:
                    _sleep_between_tasks(index, total, rate_limit_seconds)
        return SendTasksResult(run_paths=run_paths, outcomes=outcomes)
    finally:
        _close_logger(logger)
