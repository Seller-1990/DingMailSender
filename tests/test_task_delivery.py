from __future__ import annotations

import imaplib
import os
import smtplib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dingmail.task_delivery import (
    DeliveryStatus,
    DraftsConfig,
    SendTasksConfig,
    TaskDeliveryOutcome,
    save_tasks_to_imap_drafts,
    send_tasks,
)
from dingmail.task_models import MailTask
from dingmail.task_service import RenderedTaskEmail


class _FakeSmtpSendResult:
    def __init__(self, message_id: str | None) -> None:
        self.message_id = message_id


class _FakeSmtpSession:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def send(self, message):
        return _FakeSmtpSendResult(message.get("Message-ID"))


class _FakeImapDraftsSession:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def append_draft(self, message) -> str:
        return "Drafts"


class _DisconnectingSmtpSession(_FakeSmtpSession):
    """Succeeds once, then the connection drops."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__()
        self._calls = 0

    def send(self, message):
        self._calls += 1
        if self._calls >= 2:
            raise smtplib.SMTPServerDisconnected("Connection unexpectedly closed")
        return _FakeSmtpSendResult(message.get("Message-ID"))


class _AbortingImapDraftsSession(_FakeImapDraftsSession):
    def append_draft(self, message) -> str:
        raise imaplib.IMAP4.abort("socket error: EOF")


class TaskDeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="dingmail_task_delivery_")
        self.addCleanup(self._tmp.cleanup)
        self.base_dir = Path(self._tmp.name)
        self.package_dir = self.base_dir / "package"
        self.package_dir.mkdir()
        self.home_dir = self.base_dir / "home"
        self.home_dir.mkdir()
        self.rendered = RenderedTaskEmail(
            composed_markdown="正文",
            html_for_preview="<p>正文</p>",
            html_for_email="<p>正文</p>",
            inline_images=[],
            attachments=[],
        )

    def _build_tasks(self, count: int) -> list[MailTask]:
        return [
            MailTask(
                task_id=f"task-{index}",
                to_recipients=[f"user{index}@example.com"],
                subject=f"主题{index}",
                markdown_path="content/body.md",
            )
            for index in range(1, count + 1)
        ]

    def test_send_tasks_only_sleeps_between_tasks(self) -> None:
        sleep_calls: list[float] = []

        with (
            patch("dingmail.task_delivery.SmtpSession", _FakeSmtpSession),
            patch("dingmail.task_delivery.render_task_email", return_value=self.rendered),
            patch("dingmail.task_delivery.rate_limit_sleep", side_effect=lambda seconds: sleep_calls.append(seconds)),
        ):
            result = send_tasks(
                SendTasksConfig(
                    tasks=self._build_tasks(3),
                    package_dir=self.package_dir,
                    home_dir=self.home_dir,
                    smtp_host="smtp.example.com",
                    smtp_port=465,
                    smtp_security="ssl",
                    smtp_username="sender@example.com",
                    smtp_password="secret",
                    rate_limit_seconds=0.5,
                )
            )

        self.assertEqual(3, len(result.outcomes))
        self.assertEqual([0.5, 0.5], sleep_calls)

    def test_delivery_outcome_normalizes_and_rejects_unknown_status(self) -> None:
        outcome = TaskDeliveryOutcome(
            task_id="task-1",
            to_email="user@example.com",
            cc_email="",
            subject="主题",
            status="sent",
            message_id="<m1>",
            error=None,
        )

        self.assertIs(DeliveryStatus.SENT, outcome.status)
        with self.assertRaises(ValueError):
            TaskDeliveryOutcome(
                task_id="task-1",
                to_email="user@example.com",
                cc_email="",
                subject="主题",
                status="send_cancelled",
                message_id=None,
                error=None,
            )

    def test_send_tasks_redacts_manifest_and_skips_debug_artifacts_by_default(self) -> None:
        with (
            patch.dict(os.environ, {"DINGMAIL_SAVE_DEBUG_ARTIFACTS": ""}),
            patch("dingmail.task_delivery.SmtpSession", _FakeSmtpSession),
            patch("dingmail.task_delivery.render_task_email", return_value=self.rendered),
            patch("dingmail.task_delivery.rate_limit_sleep"),
        ):
            result = send_tasks(
                SendTasksConfig(
                    tasks=self._build_tasks(1),
                    package_dir=self.package_dir,
                    home_dir=self.home_dir,
                    smtp_host="smtp.example.com",
                    smtp_port=465,
                    smtp_security="ssl",
                    smtp_username="sender@example.com",
                    smtp_password="secret",
                    rate_limit_seconds=0,
                )
            )

        manifest = result.run_paths.manifest_csv.read_text(encoding="utf-8")
        self.assertIn("us***@example.com", manifest)
        self.assertNotIn("user1@example.com", manifest)
        self.assertEqual([], list(result.run_paths.previews_dir.iterdir()))
        self.assertEqual([], list(result.run_paths.eml_dir.iterdir()))

    def test_send_tasks_writes_debug_artifacts_when_enabled(self) -> None:
        with (
            patch.dict(os.environ, {"DINGMAIL_SAVE_DEBUG_ARTIFACTS": "1"}),
            patch("dingmail.task_delivery.SmtpSession", _FakeSmtpSession),
            patch("dingmail.task_delivery.render_task_email", return_value=self.rendered),
            patch("dingmail.task_delivery.rate_limit_sleep"),
        ):
            result = send_tasks(
                SendTasksConfig(
                    tasks=self._build_tasks(1),
                    package_dir=self.package_dir,
                    home_dir=self.home_dir,
                    smtp_host="smtp.example.com",
                    smtp_port=465,
                    smtp_security="ssl",
                    smtp_username="sender@example.com",
                    smtp_password="secret",
                    rate_limit_seconds=0,
                )
            )

        self.assertEqual(1, len(list(result.run_paths.previews_dir.glob("*.preview.html"))))
        self.assertEqual(1, len(list(result.run_paths.eml_dir.glob("*.eml"))))

    def test_save_tasks_to_imap_drafts_only_sleeps_between_tasks(self) -> None:
        sleep_calls: list[float] = []

        with (
            patch("dingmail.task_delivery.ImapDraftsSession", _FakeImapDraftsSession),
            patch("dingmail.task_delivery.render_task_email", return_value=self.rendered),
            patch("dingmail.task_delivery.rate_limit_sleep", side_effect=lambda seconds: sleep_calls.append(seconds)),
        ):
            result = save_tasks_to_imap_drafts(
                DraftsConfig(
                    tasks=self._build_tasks(2),
                    package_dir=self.package_dir,
                    home_dir=self.home_dir,
                    imap_username="sender@example.com",
                    imap_password="secret",
                    rate_limit_seconds=1.25,
                )
            )

        self.assertEqual(2, len(result.outcomes))
        self.assertEqual([1.25], sleep_calls)

    def test_send_tasks_aborts_remaining_tasks_after_session_error(self) -> None:
        sleep_calls: list[float] = []

        with (
            patch("dingmail.task_delivery.SmtpSession", _DisconnectingSmtpSession),
            patch("dingmail.task_delivery.render_task_email", return_value=self.rendered),
            patch("dingmail.task_delivery.rate_limit_sleep", side_effect=lambda seconds: sleep_calls.append(seconds)),
        ):
            result = send_tasks(
                SendTasksConfig(
                    tasks=self._build_tasks(4),
                    package_dir=self.package_dir,
                    home_dir=self.home_dir,
                    smtp_host="smtp.example.com",
                    smtp_port=465,
                    smtp_security="ssl",
                    smtp_username="sender@example.com",
                    smtp_password="secret",
                    rate_limit_seconds=0.5,
                )
            )

        statuses = [outcome.status for outcome in result.outcomes]
        self.assertEqual(
            [
                DeliveryStatus.SENT,
                DeliveryStatus.SEND_ERROR,
                DeliveryStatus.SEND_SKIPPED,
                DeliveryStatus.SEND_SKIPPED,
            ],
            statuses,
        )
        # 断连后不再对已注定失败的剩余任务逐条 sleep。
        self.assertEqual([0.5], sleep_calls)
        for outcome in result.outcomes[2:]:
            self.assertIn("连接中断", outcome.error or "")

        manifest = result.run_paths.manifest_csv.read_text(encoding="utf-8")
        self.assertEqual(5, len([line for line in manifest.splitlines() if line.strip()]))

    def test_save_drafts_aborts_remaining_tasks_after_session_error(self) -> None:
        with (
            patch("dingmail.task_delivery.ImapDraftsSession", _AbortingImapDraftsSession),
            patch("dingmail.task_delivery.render_task_email", return_value=self.rendered),
            patch("dingmail.task_delivery.rate_limit_sleep"),
        ):
            result = save_tasks_to_imap_drafts(
                DraftsConfig(
                    tasks=self._build_tasks(3),
                    package_dir=self.package_dir,
                    home_dir=self.home_dir,
                    imap_username="sender@example.com",
                    imap_password="secret",
                    rate_limit_seconds=0,
                )
            )

        statuses = [outcome.status for outcome in result.outcomes]
        self.assertEqual(
            [DeliveryStatus.DRAFT_ERROR, DeliveryStatus.DRAFT_SKIPPED, DeliveryStatus.DRAFT_SKIPPED],
            statuses,
        )


if __name__ == "__main__":
    unittest.main()
