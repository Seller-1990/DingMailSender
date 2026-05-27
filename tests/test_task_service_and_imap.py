from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dingmail.imap_drafts import _decode_imap_utf7, _encode_imap_utf7
from dingmail.task_models import MailTask
from dingmail.task_service import render_task_preview_html


class TaskServiceAndImapTests(unittest.TestCase):
    def test_render_task_preview_html_does_not_load_attachments(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dingmail_preview_") as tmp:
            package_dir = Path(tmp)
            (package_dir / "content").mkdir()
            (package_dir / "content" / "body.md").write_text("# 标题\n\n正文段落", encoding="utf-8")

            task = MailTask(
                task_id="task-1",
                to_recipients=["a@example.com"],
                subject="主题",
                markdown_path="content/body.md",
                attachment_paths=["attachments/missing.pdf"],
            )

            html = render_task_preview_html(task, package_dir)
            self.assertIn("正文段落", html)
            self.assertNotIn("标题", html)

    def test_imap_utf7_round_trip(self) -> None:
        mailbox = "草稿箱 & Drafts"
        encoded = _encode_imap_utf7(mailbox)

        self.assertNotEqual(mailbox, encoded)
        self.assertEqual(mailbox, _decode_imap_utf7(encoded))


if __name__ == "__main__":
    unittest.main()
