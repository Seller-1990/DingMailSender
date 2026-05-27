from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dingmail.task_delivery import save_tasks_to_imap_drafts, send_tasks
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

        self.assertEqual(3, len(result.outcomes))
        self.assertEqual([0.5, 0.5], sleep_calls)

    def test_save_tasks_to_imap_drafts_only_sleeps_between_tasks(self) -> None:
        sleep_calls: list[float] = []

        with (
            patch("dingmail.task_delivery.ImapDraftsSession", _FakeImapDraftsSession),
            patch("dingmail.task_delivery.render_task_email", return_value=self.rendered),
            patch("dingmail.task_delivery.rate_limit_sleep", side_effect=lambda seconds: sleep_calls.append(seconds)),
        ):
            result = save_tasks_to_imap_drafts(
                tasks=self._build_tasks(2),
                package_dir=self.package_dir,
                home_dir=self.home_dir,
                imap_username="sender@example.com",
                imap_password="secret",
                rate_limit_seconds=1.25,
            )

        self.assertEqual(2, len(result.outcomes))
        self.assertEqual([1.25], sleep_calls)


if __name__ == "__main__":
    unittest.main()
