from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dingmail.email_builder import EmailMessageInput, build_email_message
from dingmail.imap_drafts import _decode_imap_utf7, _encode_imap_utf7
from dingmail.task_models import MailTask
from dingmail.task_service import render_task_preview_html, validate_task


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

    def test_markdown_preview_escapes_raw_html(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dingmail_preview_") as tmp:
            package_dir = Path(tmp)
            (package_dir / "content").mkdir()
            (package_dir / "content" / "body.md").write_text(
                "正文\n\n<script>alert(1)</script>",
                encoding="utf-8",
            )

            task = MailTask(
                task_id="task-1",
                to_recipients=["a@example.com"],
                subject="主题",
                markdown_path="content/body.md",
            )

            html = render_task_preview_html(task, package_dir)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
            self.assertNotIn("<script>alert(1)</script>", html)

    def test_intro_text_single_newlines_are_preserved_in_preview(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dingmail_preview_") as tmp:
            package_dir = Path(tmp)
            (package_dir / "content").mkdir()
            (package_dir / "content" / "body.md").write_text("正文段落", encoding="utf-8")

            task = MailTask(
                task_id="task-1",
                to_recipients=["a@example.com"],
                subject="主题",
                intro_text="第一行\n第二行",
                markdown_path="content/body.md",
            )

            html = render_task_preview_html(task, package_dir)
            self.assertIn("第一行", html)
            self.assertIn("第二行", html)
            self.assertIn("<br", html)

    def test_validate_task_reports_missing_inline_markdown_images(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dingmail_preview_") as tmp:
            package_dir = Path(tmp)
            (package_dir / "content").mkdir()
            (package_dir / "content" / "body.md").write_text(
                "正文\n\n![chart](missing.png)",
                encoding="utf-8",
            )

            task = MailTask(
                task_id="task-1",
                to_recipients=["a@example.com"],
                subject="主题",
                markdown_path="content/body.md",
            )

            errors = validate_task(task, package_dir)
            self.assertTrue(any("图片文件不存在" in error for error in errors))

    def test_email_builder_rejects_header_control_characters(self) -> None:
        with self.assertRaises(ValueError):
            build_email_message(
                EmailMessageInput(
                    from_email="sender@example.com",
                    to_email=["user@example.com\r\nBcc: attacker@example.com"],
                    subject="主题",
                    text_body="正文",
                    html_body="<p>正文</p>",
                    inline_images=[],
                    attachments=[],
                )
            )

    def test_imap_utf7_round_trip(self) -> None:
        mailbox = "草稿箱 & Drafts"
        encoded = _encode_imap_utf7(mailbox)

        self.assertNotEqual(mailbox, encoded)
        self.assertEqual(mailbox, _decode_imap_utf7(encoded))


if __name__ == "__main__":
    unittest.main()
