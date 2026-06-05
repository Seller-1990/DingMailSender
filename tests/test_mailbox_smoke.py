from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dingmail.constants import DEFAULT_IMAP_HOST, DEFAULT_IMAP_PORT_SSL
from dingmail.task_delivery import DraftsConfig, SendTasksConfig, save_tasks_to_imap_drafts, send_tasks
from dingmail.task_models import MailTask


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _smoke_enabled(name: str) -> bool:
    return _env(name).lower() in {"1", "true", "yes", "on"}


class MailboxSmokeTests(unittest.TestCase):
    def _create_package(self, tmp: str) -> tuple[Path, list[MailTask]]:
        package_dir = Path(tmp)
        content_dir = package_dir / "content"
        content_dir.mkdir(parents=True)
        (content_dir / "body.md").write_text(
            "# Smoke Test\n\nThis is a DingMailSender release smoke test.",
            encoding="utf-8",
        )
        task = MailTask(
            task_id="smoke-task",
            to_recipients=[_env("DINGMAIL_SMOKE_TO", _env("DINGMAIL_SMOKE_USERNAME"))],
            subject="DingMailSender smoke test",
            intro_text="Automated release smoke test.",
            markdown_path="content/body.md",
        )
        return package_dir, [task]

    @unittest.skipUnless(_smoke_enabled("DINGMAIL_SMOKE_IMAP"), "set DINGMAIL_SMOKE_IMAP=1 to run")
    def test_save_one_draft_to_real_imap_mailbox(self) -> None:
        username = _env("DINGMAIL_SMOKE_USERNAME")
        password = _env("DINGMAIL_SMOKE_PASSWORD")
        if not username or not password:
            self.skipTest("DINGMAIL_SMOKE_USERNAME and DINGMAIL_SMOKE_PASSWORD are required")

        with tempfile.TemporaryDirectory(prefix="dingmail_imap_smoke_") as tmp:
            package_dir, tasks = self._create_package(tmp)
            result = save_tasks_to_imap_drafts(
                DraftsConfig(
                    tasks=tasks,
                    package_dir=package_dir,
                    home_dir=package_dir,
                    imap_username=username,
                    imap_password=password,
                    imap_host=_env("DINGMAIL_SMOKE_IMAP_HOST", DEFAULT_IMAP_HOST),
                    imap_port=int(_env("DINGMAIL_SMOKE_IMAP_PORT", str(DEFAULT_IMAP_PORT_SSL))),
                    rate_limit_seconds=0,
                )
            )

        self.assertEqual(1, len(result.outcomes))
        self.assertEqual("draft_saved", result.outcomes[0].status)

    @unittest.skipUnless(_smoke_enabled("DINGMAIL_SMOKE_SMTP"), "set DINGMAIL_SMOKE_SMTP=1 to run")
    def test_send_one_message_through_real_smtp(self) -> None:
        username = _env("DINGMAIL_SMOKE_USERNAME")
        password = _env("DINGMAIL_SMOKE_PASSWORD")
        to_email = _env("DINGMAIL_SMOKE_TO", username)
        if not username or not password or not to_email:
            self.skipTest("DINGMAIL_SMOKE_USERNAME, DINGMAIL_SMOKE_PASSWORD, and DINGMAIL_SMOKE_TO are required")

        with tempfile.TemporaryDirectory(prefix="dingmail_smtp_smoke_") as tmp:
            package_dir, tasks = self._create_package(tmp)
            result = send_tasks(
                SendTasksConfig(
                    tasks=tasks,
                    package_dir=package_dir,
                    home_dir=package_dir,
                    smtp_host=_env("DINGMAIL_SMOKE_SMTP_HOST", "smtp.qiye.aliyun.com"),
                    smtp_port=int(_env("DINGMAIL_SMOKE_SMTP_PORT", "465")),
                    smtp_security=_env("DINGMAIL_SMOKE_SMTP_SECURITY", "ssl"),
                    smtp_username=username,
                    smtp_password=password,
                    rate_limit_seconds=0,
                )
            )

        self.assertEqual(1, len(result.outcomes))
        self.assertEqual("sent", result.outcomes[0].status)


if __name__ == "__main__":
    unittest.main()
