from __future__ import annotations

import imaplib
import logging
import smtplib
import ssl
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Callable, cast

from .constants import (
    DEFAULT_IMAP_HOST,
    DEFAULT_IMAP_PORT_SSL,
    DEFAULT_RATE_LIMIT_SECONDS,
)
from .email_builder import EmailMessageInput, build_email_message
from .imap_drafts import ImapDraftsSession
from .model import SmtpConfig, SmtpSecurity
from .run_store import (
    ManifestRow,
    RunPaths,
    append_manifest_row,
    create_run_paths,
    debug_artifacts_enabled,
    redact_email,
    redact_text,
    snapshot_file,
)
from .smtp_sender import SmtpSession
from .task_models import MailTask
from .task_package import PACKAGE_README_FILENAME, TASKS_FILENAME
from .task_service import RenderedTaskEmail, render_task_email


class DeliveryStatus(StrEnum):
    SENT = "sent"
    SEND_ERROR = "send_error"
    SEND_SKIPPED = "send_skipped"
    DRAFT_SAVED = "draft_saved"
    DRAFT_ERROR = "draft_error"
    DRAFT_SKIPPED = "draft_skipped"

    @property
    def is_success(self) -> bool:
        return self in {DeliveryStatus.SENT, DeliveryStatus.DRAFT_SAVED}

    @property
    def is_skipped(self) -> bool:
        return self in {DeliveryStatus.SEND_SKIPPED, DeliveryStatus.DRAFT_SKIPPED}

    @property
    def action(self) -> str:
        return "draft" if self.value.startswith("draft") else "send"


@dataclass(frozen=True)
class TaskDeliveryOutcome:
    task_id: str
    to_email: str
    cc_email: str
    subject: str
    status: DeliveryStatus
    message_id: str | None
    error: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", DeliveryStatus(self.status))


# 会话级异常：连接已不可用，继续循环只会让剩余任务逐条失败并逐条 sleep。
# 注意不要放宽到 OSError——渲染/附件的 FileNotFoundError 等文件错误必须保持任务级。
SMTP_SESSION_ERRORS: tuple[type[Exception], ...] = (
    smtplib.SMTPServerDisconnected,
    smtplib.SMTPConnectError,
    ConnectionError,
    TimeoutError,
    ssl.SSLError,
)

IMAP_SESSION_ERRORS: tuple[type[Exception], ...] = (
    imaplib.IMAP4.abort,
    ConnectionError,
    TimeoutError,
    ssl.SSLError,
)


@dataclass(frozen=True)
class SendTasksResult:
    run_paths: RunPaths
    outcomes: list[TaskDeliveryOutcome]


def _safe_filename(text: str, limit: int = 48) -> str:
    parts = []
    for char in text:
        if char.isalnum() or char in ("-", "_", "."):
            parts.append(char)
        else:
            parts.append("_")
    value = "".join(parts).strip("_") or "task"
    if len(value) > limit:
        value = value[:limit].rstrip("_")
    return value or "task"


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
    # logging.Manager 永久持有 logger 引用；每轮 run 一个名字会无限累积，
    # 用完即从注册表摘除，防止长驻进程内存缓慢泄漏
    logging.Logger.manager.loggerDict.pop(logger.name, None)


def _build_message_from_rendered(
    task: MailTask,
    from_email: str,
    rendered: RenderedTaskEmail,
):
    return build_email_message(
        EmailMessageInput(
            from_email=from_email,
            to_email=task.to_recipients,
            cc_email=task.cc_recipients,
            subject=task.subject,
            text_body=rendered.composed_markdown,
            html_body=rendered.html_for_email,
            inline_images=rendered.inline_images,
            attachments=rendered.attachments,
        )
    )


@dataclass(frozen=True)
class TaskArtifacts:
    run_paths: RunPaths
    index: int
    task: MailTask
    rendered: RenderedTaskEmail
    message: object


@dataclass(frozen=True)
class DeliveryTaskContext:
    run_paths: RunPaths
    logger: logging.Logger
    index: int
    task: MailTask


@dataclass(frozen=True)
class SendTasksConfig:
    tasks: list[MailTask]
    package_dir: Path
    home_dir: Path
    smtp_host: str
    smtp_port: int
    smtp_security: str
    smtp_username: str
    smtp_password: str
    rate_limit_seconds: float = DEFAULT_RATE_LIMIT_SECONDS


@dataclass(frozen=True)
class DraftsConfig:
    tasks: list[MailTask]
    package_dir: Path
    home_dir: Path
    imap_username: str
    imap_password: str
    imap_host: str = DEFAULT_IMAP_HOST
    imap_port: int = DEFAULT_IMAP_PORT_SSL
    rate_limit_seconds: float = DEFAULT_RATE_LIMIT_SECONDS


def _task_recipient_text(task: MailTask) -> str:
    return "; ".join(task.to_recipients)


def _task_cc_text(task: MailTask) -> str:
    return "; ".join(task.cc_recipients)


def _build_outcome(
    *,
    task: MailTask,
    status: DeliveryStatus,
    message_id: str | None,
    error: str | None,
) -> TaskDeliveryOutcome:
    return TaskDeliveryOutcome(
        task_id=task.task_id,
        to_email=_task_recipient_text(task),
        cc_email=_task_cc_text(task),
        subject=task.subject,
        status=status,
        message_id=message_id,
        error=error,
    )


def _append_outcome_manifest_row(manifest_csv: Path, *, idx: int, outcome: TaskDeliveryOutcome) -> None:
    append_manifest_row(
        manifest_csv,
        ManifestRow(
            idx=idx,
            to_email=outcome.to_email,
            subject=outcome.subject,
            status=outcome.status.value,
            message_id=outcome.message_id,
            error=outcome.error,
        ),
    )


def _write_task_artifacts(artifacts: TaskArtifacts) -> None:
    if not debug_artifacts_enabled():
        return
    identity = artifacts.task.task_id or artifacts.task.subject or ";".join(artifacts.task.to_recipients)
    base = f"{artifacts.index:03d}_{_safe_filename(identity)}"
    preview_path = artifacts.run_paths.previews_dir / f"{base}.preview.html"
    preview_path.write_text(artifacts.rendered.html_for_preview, encoding="utf-8")
    (artifacts.run_paths.eml_dir / f"{base}.eml").write_bytes(artifacts.message.as_bytes())


def _sleep_between_tasks(
    index: int,
    total: int,
    rate_limit_seconds: float,
    cancel_check: Callable[[], bool] | None = None,
) -> None:
    """可中断的任务间等待。每 0.1 秒检查一次取消信号。"""
    if index >= total:
        return
    if rate_limit_seconds <= 0:
        return
    deadline = time.monotonic() + rate_limit_seconds
    while time.monotonic() < deadline:
        if cancel_check and cancel_check():
            return
        remaining = deadline - time.monotonic()
        time.sleep(min(0.1, max(0, remaining)))


def _snapshot_package_files(package_dir: Path, run_paths: RunPaths) -> None:
    snapshot_file(package_dir / TASKS_FILENAME, run_paths.run_dir, TASKS_FILENAME)
    snapshot_file(package_dir / PACKAGE_README_FILENAME, run_paths.run_dir, PACKAGE_README_FILENAME)


def _smtp_config_from_delivery(config: SendTasksConfig) -> SmtpConfig:
    normalized_security = str(config.smtp_security).strip().lower()
    if normalized_security not in ("ssl", "starttls"):
        raise ValueError(f"smtp_security 必须是 ssl 或 starttls，当前为：{config.smtp_security!r}")

    return SmtpConfig(
        host=config.smtp_host,
        port=config.smtp_port,
        security=cast(SmtpSecurity, normalized_security),
        username=config.smtp_username,
    )


def _skip_remaining_tasks(
    *,
    tasks: list[MailTask],
    start_idx: int,
    status: DeliveryStatus,
    reason: str,
    manifest_csv: Path,
    logger: logging.Logger,
) -> list[TaskDeliveryOutcome]:
    skipped: list[TaskDeliveryOutcome] = []
    for offset, task in enumerate(tasks, start=start_idx):
        outcome = _build_outcome(
            task=task,
            status=status,
            message_id=None,
            error=f"连接中断，本任务未尝试：{reason}",
        )
        _append_outcome_manifest_row(manifest_csv, idx=offset, outcome=outcome)
        skipped.append(outcome)
    if skipped:
        logger.error("session_error skipped=%d reason=%s", len(skipped), redact_text(reason))
    return skipped


def _send_single_task(
    *,
    smtp: SmtpSession,
    config: SendTasksConfig,
    context: DeliveryTaskContext,
) -> tuple[TaskDeliveryOutcome, Exception | None]:
    session_error: Exception | None = None
    try:
        rendered = render_task_email(context.task, config.package_dir)
        message = _build_message_from_rendered(context.task, config.smtp_username, rendered)
        _write_task_artifacts(
            TaskArtifacts(
                run_paths=context.run_paths,
                index=context.index,
                task=context.task,
                rendered=rendered,
                message=message,
            )
        )
        result = smtp.send(message)
        if result.has_partial_failure:
            rejected = "; ".join(result.rejected_recipients.keys())
            outcome = _build_outcome(
                task=context.task,
                status=DeliveryStatus.SENT,
                message_id=result.message_id,
                error=f"部分收件人被拒绝：{rejected}",
            )
        else:
            outcome = _build_outcome(
                task=context.task,
                status=DeliveryStatus.SENT,
                message_id=result.message_id,
                error=None,
            )
        context.logger.info("sent task_id=%s to=%s", context.task.task_id, redact_email(outcome.to_email))
    except SMTP_SESSION_ERRORS as exc:
        session_error = exc
        outcome = _build_outcome(
            task=context.task,
            status=DeliveryStatus.SEND_ERROR,
            message_id=None,
            error=str(exc),
        )
        context.logger.error("send_session_error task_id=%s: %s", context.task.task_id, redact_text(str(exc)))
    except Exception as exc:
        outcome = _build_outcome(
            task=context.task,
            status=DeliveryStatus.SEND_ERROR,
            message_id=None,
            error=str(exc),
        )
        context.logger.error("send_error task_id=%s: %s", context.task.task_id, redact_text(str(exc)))

    _append_outcome_manifest_row(context.run_paths.manifest_csv, idx=context.index, outcome=outcome)
    return outcome, session_error


def send_tasks(
    config: SendTasksConfig,
    *,
    progress_callback: Callable[[int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> SendTasksResult:
    run_paths = create_run_paths(home_dir=config.home_dir, campaign_dir=config.package_dir)
    logger = _build_logger(run_paths.logs_dir / "send.log", f"dingmail.send.{run_paths.run_dir.name}")
    _snapshot_package_files(config.package_dir, run_paths)

    outcomes: list[TaskDeliveryOutcome] = []
    total = len(config.tasks)
    try:
        with SmtpSession(_smtp_config_from_delivery(config), config.smtp_password) as smtp:
            for index, task in enumerate(config.tasks, start=1):
                if cancel_check and cancel_check():
                    outcomes.extend(
                        _skip_remaining_tasks(
                            tasks=config.tasks[index - 1:],
                            start_idx=index,
                            status=DeliveryStatus.SEND_SKIPPED,
                            reason="用户取消",
                            manifest_csv=run_paths.manifest_csv,
                            logger=logger,
                        )
                    )
                    break
                outcome, session_error = _send_single_task(
                    smtp=smtp,
                    config=config,
                    context=DeliveryTaskContext(run_paths=run_paths, logger=logger, index=index, task=task),
                )
                outcomes.append(outcome)
                if progress_callback:
                    progress_callback(index, total)
                if session_error is not None:
                    # 尝试重连一次，成功则继续剩余任务
                    try:
                        smtp.reconnect()
                        logger.info("reconnect_ok after session_error: %s", redact_text(str(session_error)))
                    except Exception as reconnect_exc:
                        logger.error("reconnect_failed: %s", redact_text(str(reconnect_exc)))
                        outcomes.extend(
                            _skip_remaining_tasks(
                                tasks=config.tasks[index:],
                                start_idx=index + 1,
                                status=DeliveryStatus.SEND_SKIPPED,
                                reason=str(session_error),
                                manifest_csv=run_paths.manifest_csv,
                                logger=logger,
                            )
                        )
                        break
                _sleep_between_tasks(index, total, config.rate_limit_seconds, cancel_check)
        return SendTasksResult(run_paths=run_paths, outcomes=outcomes)
    finally:
        _close_logger(logger)


def _save_single_draft(
    *,
    drafts: ImapDraftsSession,
    config: DraftsConfig,
    context: DeliveryTaskContext,
) -> tuple[TaskDeliveryOutcome, Exception | None]:
    session_error: Exception | None = None
    try:
        rendered = render_task_email(context.task, config.package_dir)
        message = _build_message_from_rendered(context.task, config.imap_username, rendered)
        _write_task_artifacts(
            TaskArtifacts(
                run_paths=context.run_paths,
                index=context.index,
                task=context.task,
                rendered=rendered,
                message=message,
            )
        )
        mailbox = drafts.append_draft(message)
        outcome = _build_outcome(
            task=context.task,
            status=DeliveryStatus.DRAFT_SAVED,
            message_id=message.get("Message-ID"),
            error=None,
        )
        context.logger.info("draft_saved task_id=%s mailbox=%s", context.task.task_id, mailbox)
    except IMAP_SESSION_ERRORS as exc:
        session_error = exc
        outcome = _build_outcome(
            task=context.task,
            status=DeliveryStatus.DRAFT_ERROR,
            message_id=None,
            error=str(exc),
        )
        context.logger.error("draft_session_error task_id=%s: %s", context.task.task_id, redact_text(str(exc)))
    except Exception as exc:
        outcome = _build_outcome(
            task=context.task,
            status=DeliveryStatus.DRAFT_ERROR,
            message_id=None,
            error=str(exc),
        )
        context.logger.error("draft_error task_id=%s: %s", context.task.task_id, redact_text(str(exc)))

    _append_outcome_manifest_row(context.run_paths.manifest_csv, idx=context.index, outcome=outcome)
    return outcome, session_error


def save_tasks_to_imap_drafts(
    config: DraftsConfig,
    *,
    progress_callback: Callable[[int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> SendTasksResult:
    run_paths = create_run_paths(home_dir=config.home_dir, campaign_dir=config.package_dir)
    logger = _build_logger(run_paths.logs_dir / "drafts.log", f"dingmail.drafts.{run_paths.run_dir.name}")
    _snapshot_package_files(config.package_dir, run_paths)

    outcomes: list[TaskDeliveryOutcome] = []
    total = len(config.tasks)
    try:
        with ImapDraftsSession(
            host=config.imap_host,
            port=config.imap_port,
            username=config.imap_username,
            password=config.imap_password,
        ) as drafts:
            for index, task in enumerate(config.tasks, start=1):
                if cancel_check and cancel_check():
                    outcomes.extend(
                        _skip_remaining_tasks(
                            tasks=config.tasks[index - 1:],
                            start_idx=index,
                            status=DeliveryStatus.DRAFT_SKIPPED,
                            reason="用户取消",
                            manifest_csv=run_paths.manifest_csv,
                            logger=logger,
                        )
                    )
                    break
                outcome, session_error = _save_single_draft(
                    drafts=drafts,
                    config=config,
                    context=DeliveryTaskContext(run_paths=run_paths, logger=logger, index=index, task=task),
                )
                outcomes.append(outcome)
                if progress_callback:
                    progress_callback(index, total)
                if session_error is not None:
                    # 尝试重连一次，成功则继续剩余任务
                    try:
                        drafts.reconnect()
                        logger.info("imap_reconnect_ok after session_error: %s", redact_text(str(session_error)))
                    except Exception as reconnect_exc:
                        logger.error("imap_reconnect_failed: %s", redact_text(str(reconnect_exc)))
                        outcomes.extend(
                            _skip_remaining_tasks(
                                tasks=config.tasks[index:],
                                start_idx=index + 1,
                                status=DeliveryStatus.DRAFT_SKIPPED,
                                reason=str(session_error),
                                manifest_csv=run_paths.manifest_csv,
                                logger=logger,
                            )
                        )
                        break
                _sleep_between_tasks(index, total, config.rate_limit_seconds, cancel_check)
        return SendTasksResult(run_paths=run_paths, outcomes=outcomes)
    finally:
        _close_logger(logger)
