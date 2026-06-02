from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import openpyxl

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6 import QtGui, QtWidgets

from dingmail.connection_profile import ConnectionProfile
from dingmail.gui.main import MainWindow, RunHistoryDialog
from dingmail.task_models import MailTask
from dingmail.task_package import TASKS_FILENAME, TASKS_SHEET_NAME, load_tasks_from_package, save_tasks_to_package

TASK_HEADERS = [
    "任务ID",
    "是否启用",
    "收件人",
    "抄送人",
    "主题",
    "开头/补充内容",
    "Markdown路径",
    "是否有附件",
    "附件路径",
    "是否定时发送",
    "定时发送时间",
    "备注",
]


class _FakeTray:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, object, int]] = []

    def showMessage(self, title: str, message: str, icon, timeout: int) -> None:  # noqa: N802
        self.messages.append((title, message, icon, timeout))


class MainWindowGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="dingmail_gui_main_")
        self.addCleanup(self._tmp.cleanup)
        self.base_dir = Path(self._tmp.name)
        self.home_dir = self.base_dir / "home"
        self.home_dir.mkdir()

    def _process_events(self) -> None:
        self._app.processEvents()

    def _create_window(self) -> MainWindow:
        with (
            patch("dingmail.gui.main.detect_home_dir", return_value=self.home_dir),
            patch("dingmail.gui.main.load_connection_profile", return_value=ConnectionProfile()),
            patch.object(QtWidgets.QSystemTrayIcon, "isSystemTrayAvailable", return_value=False),
        ):
            window = MainWindow()
        self.addCleanup(window.deleteLater)
        self.addCleanup(self._process_events)
        return window

    def _create_package_dir(self, name: str) -> Path:
        package_dir = self.home_dir / "packages" / name
        (package_dir / "content").mkdir(parents=True)
        (package_dir / "content" / "body.md").write_text("# 标题\n\n正文", encoding="utf-8")
        return package_dir

    def test_load_package_repairs_duplicate_ids_and_shows_warning(self) -> None:
        package_dir = self._create_package_dir("dup")
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = TASKS_SHEET_NAME
        sheet.append(TASK_HEADERS)
        sheet.append(["task-1", "是", "a@example.com", "", "主题1", "", "content/body.md", "否", "", "否", "", ""])
        sheet.append(["task-1", "是", "b@example.com", "", "主题2", "", "content/body.md", "否", "", "否", "", ""])
        workbook.save(package_dir / TASKS_FILENAME)
        workbook.close()

        window = self._create_window()
        with patch.object(QtWidgets.QMessageBox, "warning") as warning_mock:
            window._load_package(package_dir)

        self.assertTrue(warning_mock.called)
        self.assertEqual("任务ID已自动修复", warning_mock.call_args.args[1])
        self.assertEqual(2, window._task_table.rowCount())
        self.assertEqual(2, len({task.task_id for task in window._tasks}))

        saved_tasks = load_tasks_from_package(package_dir)
        self.assertEqual(2, len({task.task_id for task in saved_tasks}))

    def test_reload_package_preserves_valid_queued_tasks(self) -> None:
        package_dir = self._create_package_dir("queued")
        save_tasks_to_package(
            package_dir,
            [
                MailTask(
                    task_id="task-1",
                    to_recipients=["a@example.com"],
                    subject="主题",
                    markdown_path="content/body.md",
                    schedule_enabled=True,
                    scheduled_at=datetime.now() + timedelta(hours=1),
                )
            ],
        )

        window = self._create_window()
        window._load_package(package_dir)
        window._runtime.queued_task_ids.add("task-1")
        window._reload_package()

        self.assertEqual({"task-1"}, window._runtime.queued_task_ids)
        self.assertEqual("已加入定时队列", window._tasks[0].status)

    def test_table_selection_and_smtp_state_refresh_buttons(self) -> None:
        package_dir = self._create_package_dir("basic")
        save_tasks_to_package(
            package_dir,
            [
                MailTask(
                    task_id="task-1",
                    to_recipients=["a@example.com"],
                    subject="主题",
                    markdown_path="content/body.md",
                )
            ],
        )

        window = self._create_window()
        window._load_package(package_dir)
        self._process_events()

        self.assertFalse(window._edit_btn.isEnabled())
        self.assertFalse(window._send_now_btn.isEnabled())

        window._task_table.selectRow(0)
        self._process_events()
        self.assertTrue(window._edit_btn.isEnabled())
        self.assertTrue(window._copy_btn.isEnabled())
        self.assertTrue(window._preview_btn.isEnabled())
        self.assertFalse(window._send_now_btn.isEnabled())

        window._set_smtp_status(True, "test")
        self._process_events()
        self.assertTrue(window._send_now_btn.isEnabled())
        self.assertTrue(window._save_drafts_btn.isEnabled())

    def test_workbench_layout_detail_panel_and_filters(self) -> None:
        package_dir = self._create_package_dir("workbench")
        save_tasks_to_package(
            package_dir,
            [
                MailTask(
                    task_id="task-1",
                    to_recipients=["a@example.com"],
                    subject="可保存草稿",
                    markdown_path="content/body.md",
                ),
                MailTask(
                    task_id="task-2",
                    to_recipients=["b@example.com"],
                    subject="缺少正文",
                    markdown_path="content/missing.md",
                ),
            ],
        )

        window = self._create_window()
        window._load_package(package_dir)
        self._process_events()

        self.assertEqual(8, window._task_table.columnCount())
        self.assertEqual("状态", window._task_table.horizontalHeaderItem(0).text())
        self.assertEqual("保存草稿", window._save_drafts_btn.text())
        self.assertEqual("运行历史", window._open_last_run_btn.text())
        self.assertEqual("primary", window._save_drafts_btn.property("variant"))
        self.assertEqual("danger", window._send_now_btn.property("variant"))

        window._task_table.selectRow(0)
        self._process_events()
        self.assertEqual("可保存草稿", window._detail_title_label.text())

        window._set_task_filter("issue")
        self._process_events()
        self.assertTrue(window._task_table.isRowHidden(0))
        self.assertFalse(window._task_table.isRowHidden(1))

    def test_run_history_dialog_summarizes_manifest(self) -> None:
        runs_root = self.home_dir / "runs"
        run_dir = runs_root / "20260602_120000_demo"
        run_dir.mkdir(parents=True)
        (run_dir / "manifest.csv").write_text(
            "idx,to_email,subject,status,message_id,error\n"
            "1,us***@example.com,主题,draft_saved,<m1>,\n"
            "2,us***@example.com,主题,draft_error,,缺少图片\n",
            encoding="utf-8",
        )

        dialog = RunHistoryDialog(runs_root=runs_root)
        self.addCleanup(dialog.deleteLater)

        item_text = dialog._list.item(0).text()
        self.assertIn("保存草稿", item_text)
        self.assertIn("成功 1", item_text)
        self.assertIn("失败 1", item_text)

    def test_close_event_minimizes_to_tray_when_connected(self) -> None:
        window = self._create_window()
        fake_tray = _FakeTray()
        window._tray = fake_tray
        window.show()
        window._set_smtp_status(True, "test")
        self._process_events()

        event = QtGui.QCloseEvent()
        window.closeEvent(event)

        self.assertFalse(event.isAccepted())
        self.assertTrue(window.isHidden())
        self.assertEqual(1, len(fake_tray.messages))
        self.assertIn("已最小化到托盘", fake_tray.messages[0][0])

    def test_exit_from_tray_requires_confirmation_for_queued_tasks(self) -> None:
        window = self._create_window()
        window._tray = _FakeTray()
        window._runtime.queued_task_ids.add("task-1")

        with (
            patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.No),
            patch.object(QtWidgets.QApplication, "quit") as quit_mock,
        ):
            window._exit_from_tray()
        self.assertFalse(window._quit_requested)
        self.assertFalse(quit_mock.called)

        with (
            patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.Yes),
            patch.object(QtWidgets.QApplication, "quit") as quit_mock,
        ):
            window._exit_from_tray()
        self.assertTrue(window._quit_requested)
        self.assertTrue(quit_mock.called)


if __name__ == "__main__":
    unittest.main()
