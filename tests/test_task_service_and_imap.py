from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dingmail.constants import (
    MAX_ATTACHMENT_BYTES,
    MAX_EMAIL_ASSET_BYTES,
    MAX_INLINE_IMAGE_BYTES,
)
from dingmail.email_builder import EmailMessageInput, build_email_message
from dingmail.imap_drafts import ImapDraftsSession, _decode_imap_utf7, _encode_imap_utf7, _quote_mailbox
from dingmail.model import SmtpConfig
from dingmail.smtp_sender import SmtpSession
from dingmail.task_models import MailTask
from dingmail.task_service import render_task_email, render_task_preview_html, validate_task


class TaskServiceAndImapTests(unittest.TestCase):
    def _write_task_files(self, package_dir: Path, markdown: str = "body") -> None:
        (package_dir / "content").mkdir()
        (package_dir / "content" / "body.md").write_text(markdown, encoding="utf-8")

    def _valid_task(self, **overrides) -> MailTask:
        values = {
            "task_id": "task-1",
            "to_recipients": ["a@example.com"],
            "subject": "subject",
            "markdown_path": "content/body.md",
        }
        values.update(overrides)
        return MailTask(**values)

    def test_validate_task_rejects_empty_composed_body(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dingmail_empty_body_") as tmp:
            package_dir = Path(tmp)
            self._write_task_files(package_dir, "# title\n\n")

            errors = validate_task(self._valid_task(), package_dir)

            self.assertTrue(errors)

    def test_validate_task_accepts_intro_when_markdown_body_is_empty(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dingmail_intro_body_") as tmp:
            package_dir = Path(tmp)
            self._write_task_files(package_dir, "# title\n\n")

            errors = validate_task(self._valid_task(intro_text="intro"), package_dir)

            self.assertEqual([], errors)

    def test_validate_task_rejects_oversized_attachment(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dingmail_large_attachment_") as tmp:
            package_dir = Path(tmp)
            self._write_task_files(package_dir)
            attachment = package_dir / "large.bin"
            with attachment.open("wb") as stream:
                stream.truncate(MAX_ATTACHMENT_BYTES + 1)

            errors = validate_task(
                self._valid_task(attachment_paths=[attachment.name]),
                package_dir,
            )

            self.assertTrue(any(attachment.name in error for error in errors))

    def test_render_task_email_rejects_oversized_attachment_before_reading(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dingmail_render_large_attachment_") as tmp:
            package_dir = Path(tmp)
            self._write_task_files(package_dir)
            attachment = package_dir / "large.bin"
            with attachment.open("wb") as stream:
                stream.truncate(MAX_ATTACHMENT_BYTES + 1)

            with patch.object(Path, "read_bytes", side_effect=AssertionError("must not read oversized file")) as read:
                with self.assertRaises(ValueError):
                    render_task_email(
                        self._valid_task(attachment_paths=[attachment.name]),
                        package_dir,
                    )

            read.assert_not_called()

    def test_validate_task_rejects_oversized_inline_image(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dingmail_large_image_") as tmp:
            package_dir = Path(tmp)
            self._write_task_files(package_dir, "body\n\n![chart](chart.png)")
            image = package_dir / "content" / "chart.png"
            with image.open("wb") as stream:
                stream.truncate(MAX_INLINE_IMAGE_BYTES + 1)

            errors = validate_task(self._valid_task(), package_dir)

            self.assertTrue(any(image.name in error for error in errors))

    def test_validate_task_rejects_total_asset_size(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dingmail_total_assets_") as tmp:
            package_dir = Path(tmp)
            self._write_task_files(package_dir)
            first = package_dir / "first.bin"
            second = package_dir / "second.bin"
            with first.open("wb") as stream:
                stream.truncate(MAX_EMAIL_ASSET_BYTES // 2 + 1)
            with second.open("wb") as stream:
                stream.truncate(MAX_EMAIL_ASSET_BYTES // 2 + 1)

            errors = validate_task(
                self._valid_task(attachment_paths=[first.name, second.name]),
                package_dir,
            )

            self.assertTrue(errors)

    def test_smtp_enter_closes_connection_when_initialization_fails(self) -> None:
        server = MagicMock()
        server.ehlo.side_effect = RuntimeError("ehlo failed")
        with patch("dingmail.smtp_sender.SMTP_SSL", return_value=server):
            with self.assertRaisesRegex(RuntimeError, "ehlo failed"):
                SmtpSession(SmtpConfig(), "password").__enter__()

        server.close.assert_called_once_with()

    def test_imap_enter_closes_connection_when_initialization_fails(self) -> None:
        session = MagicMock()
        session.login.side_effect = RuntimeError("login failed")
        with patch("dingmail.imap_drafts.imaplib.IMAP4_SSL", return_value=session):
            with self.assertRaisesRegex(RuntimeError, "login failed"):
                ImapDraftsSession("host", 993, "user", "password").__enter__()

        session.logout.assert_called_once_with()

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

    def test_quote_mailbox_quotes_names_with_spaces_and_specials(self) -> None:
        self.assertEqual("Drafts", _quote_mailbox("Drafts"))
        self.assertEqual('"Saved Drafts"', _quote_mailbox("Saved Drafts"))
        self.assertEqual('"a\\"b"', _quote_mailbox('a"b'))
        self.assertEqual('"INBOX Drafts"', _quote_mailbox('"INBOX Drafts"'))

    def test_validate_task_flags_invalid_recipient_format(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dingmail_validate_") as tmp:
            package_dir = Path(tmp)
            (package_dir / "content").mkdir()
            (package_dir / "content" / "body.md").write_text("正文", encoding="utf-8")

            task = MailTask(
                task_id="task-1",
                to_recipients=["not-an-email"],
                cc_recipients=["also bad"],
                subject="主题",
                markdown_path="content/body.md",
            )

            errors = validate_task(task, package_dir)
            self.assertTrue(any("收件人邮箱格式不合法" in error for error in errors))
            self.assertTrue(any("抄送邮箱格式不合法" in error for error in errors))


def _make_image_package(tmp: Path) -> Path:
    pkg = tmp / "pkg"
    (pkg / "assets").mkdir(parents=True)
    (pkg / "content").mkdir()
    (pkg / "assets" / "pic.png").write_bytes(b"\x89PNG fake")
    (pkg / "assets" / "图 片.png").write_bytes(b"\x89PNG fake")
    (pkg / "content" / "local.png").write_bytes(b"\x89PNG fake")
    (pkg / "outside.png").write_bytes(b"x")
    (pkg / "content" / "assets_layout.md").write_text("![示意](assets/pic.png)", encoding="utf-8")
    (pkg / "content" / "chinese_name.md").write_text("![图](<assets/图 片.png>)", encoding="utf-8")
    (pkg / "content" / "same_dir.md").write_text("![同目录](local.png)", encoding="utf-8")
    (pkg / "content" / "escape.md").write_text("![x](../../outside.png)", encoding="utf-8")
    return pkg


class InlineImageResolutionTests(unittest.TestCase):
    """README 文档化的 assets/ 布局与中文文件名必须全链路可用（F1/F2 回归）。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="dingmail_images_")
        cls.pkg = _make_image_package(Path(cls._tmp.name))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _task(self, markdown: str) -> MailTask:
        return MailTask(
            task_id="t", to_recipients=["a@example.com"], subject="s", markdown_path=f"content/{markdown}"
        )

    def test_assets_layout_resolves_against_package_root(self) -> None:
        task = self._task("assets_layout.md")
        self.assertEqual([], validate_task(task, self.pkg))
        self.assertEqual(1, len(render_task_email(task, self.pkg).inline_images))

    def test_chinese_and_space_filenames_are_percent_decoded(self) -> None:
        task = self._task("chinese_name.md")
        self.assertEqual([], validate_task(task, self.pkg))
        rendered = render_task_email(task, self.pkg)
        self.assertEqual(1, len(rendered.inline_images))
        self.assertEqual("图 片.png", rendered.inline_images[0].filename)

    def test_same_dir_layout_still_works(self) -> None:
        task = self._task("same_dir.md")
        self.assertEqual([], validate_task(task, self.pkg))

    def test_traversal_outside_package_is_rejected(self) -> None:
        errors = validate_task(self._task("escape.md"), self.pkg)
        self.assertTrue(any("越界" in e for e in errors), errors)

    def test_preview_renders_with_file_uri(self) -> None:
        html = render_task_preview_html(self._task("assets_layout.md"), self.pkg)
        self.assertIn("file://", html)


class ImapMailboxParsingTests(unittest.TestCase):
    """imaplib 对中文邮箱名返回 literal tuple，解析不得崩溃（F10 回归）。"""

    def test_literal_tuple_entries_are_parsed(self) -> None:
        session = ImapDraftsSession.__new__(ImapDraftsSession)
        parsed = session._parse_mailbox_entries(
            [
                (b'(\\HasNoChildren) "/" ', "草稿箱".encode("utf-8")),
                b'() "/" "Sent"',
            ]
        )
        names = [decoded for _line, _name, decoded in parsed]
        self.assertIn("草稿箱", names)
        picked = session._pick_drafts_mailbox(parsed)
        self.assertEqual("草稿箱", picked)


if __name__ == "__main__":
    unittest.main()
