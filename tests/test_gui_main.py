from __future__ import annotations

import os
import sys
import tempfile
import json
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import openpyxl

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6 import QtCore, QtGui, QtWidgets

from dingmail.connection_profile import ConnectionProfile, ConnectionProfileLoadResult
from dingmail.gui.dialogs import RunHistoryDialog
from dingmail.gui.main import MainWindow
from dingmail.gui.main_delivery import DeliveryWorkerSpec
from dingmail.run_store import RunPaths
from dingmail.task_delivery import SendTasksResult, TaskDeliveryOutcome
from dingmail.task_models import MailTask
from dingmail.task_package import TASKS_FILENAME, TASKS_SHEET_NAME, load_tasks_from_package, save_tasks_to_package
from dingmail.task_status import TaskStatus

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


class _FakeSignal:
    def __init__(self) -> None:
        self._callbacks = []

    def connect(self, callback) -> None:
        self._callbacks.append(callback)

    def emit(self, value) -> None:
        for callback in list(self._callbacks):
            callback(value)


class _FakeWorker:
    def __init__(self) -> None:
        self.finished_ok = _FakeSignal()
        self.finished_err = _FakeSignal()
        self.started = False

    def start(self) -> None:
        self.started = True

    def request_cancel(self) -> None:
        pass

    def wait(self, timeout: int = 0) -> bool:
        return True


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
            patch(
                "dingmail.gui.main.load_connection_profile_with_metadata",
                return_value=ConnectionProfileLoadResult(profile=ConnectionProfile()),
            ),
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

    def _create_run_paths(self, name: str = "20260605_120000_test") -> RunPaths:
        run_dir = self.home_dir / "runs" / name
        previews_dir = run_dir / "previews"
        eml_dir = run_dir / "eml"
        logs_dir = run_dir / "logs"
        for path in [previews_dir, eml_dir, logs_dir]:
            path.mkdir(parents=True, exist_ok=True)
        manifest_csv = run_dir / "manifest.csv"
        manifest_csv.write_text("idx,to_email,subject,status,message_id,error\n", encoding="utf-8")
        return RunPaths(
            run_dir=run_dir,
            previews_dir=previews_dir,
            eml_dir=eml_dir,
            logs_dir=logs_dir,
            manifest_csv=manifest_csv,
        )

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
        self.assertEqual(2, window._task_model.rowCount())
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
        self.assertEqual(TaskStatus.QUEUED, window._runtime.status_for(window._tasks[0]))

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

    def test_package_switch_actions_are_disabled_while_delivery_is_busy(self) -> None:
        package_dir = self._create_package_dir("busy")
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
        window._send_worker = _FakeWorker()
        window._refresh_ui_state()

        self.assertFalse(window._download_package_btn.isEnabled())
        self.assertFalse(window._import_package_btn.isEnabled())
        self.assertFalse(window._reload_package_btn.isEnabled())

        with patch.object(QtWidgets.QMessageBox, "information") as info_mock:
            window._reload_package()
        info_mock.assert_called_once()

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

        self.assertEqual(8, window._task_model.columnCount())
        self.assertEqual("状态", window._task_model.headerData(0, QtCore.Qt.Horizontal))
        self.assertEqual("保存草稿", window._save_drafts_btn.text())
        self.assertEqual("运行历史", window._open_last_run_btn.text())
        self.assertEqual("primary", window._save_drafts_btn.property("variant"))
        self.assertEqual("danger", window._send_now_btn.property("variant"))

        window._task_table.selectRow(0)
        self._process_events()
        self.assertEqual("可保存草稿", window._detail_title_label.text())

        window._set_task_filter("issue")
        self._process_events()
        self.assertEqual(1, window._task_proxy.rowCount())
        source_row = window._task_proxy.mapToSource(window._task_proxy.index(0, 0)).row()
        self.assertEqual("task-2", window._task_model.task_at(source_row).task_id)

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

    def test_run_history_dialog_reports_unknown_delivery_status(self) -> None:
        runs_root = self.home_dir / "runs"
        run_dir = runs_root / "20260602_120001_demo"
        run_dir.mkdir(parents=True)
        (run_dir / "manifest.csv").write_text(
            "idx,to_email,subject,status,message_id,error\n"
            "1,us***@example.com,主题,send_cancelled,,\n",
            encoding="utf-8",
        )

        dialog = RunHistoryDialog(runs_root=runs_root)
        self.addCleanup(dialog.deleteLater)

        item_text = dialog._list.item(0).text()
        self.assertIn("未识别状态 1", item_text)

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

    def test_exit_from_tray_blocked_while_delivery_worker_running(self) -> None:
        window = self._create_window()
        window._tray = _FakeTray()
        worker = _FakeWorker()
        worker.wait = lambda timeout=0: False  # simulate wait timeout
        window._draft_worker = worker

        with (
            patch.object(QtWidgets.QMessageBox, "information") as info_mock,
            patch.object(QtWidgets.QApplication, "quit") as quit_mock,
        ):
            window._exit_from_tray()

        info_mock.assert_called_once()
        quit_mock.assert_not_called()
        self.assertFalse(window._quit_requested)

    def test_close_event_blocked_without_tray_while_delivery_worker_running(self) -> None:
        window = self._create_window()
        window._tray = None
        worker = _FakeWorker()
        worker.wait = lambda timeout=0: False  # simulate wait timeout
        window._send_worker = worker

        event = QtGui.QCloseEvent()
        with patch.object(QtWidgets.QMessageBox, "information") as info_mock:
            window.closeEvent(event)

        info_mock.assert_called_once()
        self.assertFalse(event.isAccepted())

    def test_task_editing_is_blocked_while_delivery_busy(self) -> None:
        package_dir = self._create_package_dir("busyedit")
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
        window._task_table.selectRow(0)
        window._draft_worker = _FakeWorker()

        with (
            patch.object(QtWidgets.QMessageBox, "information") as info_mock,
            patch("dingmail.gui.main_task_commands.TaskEditorDialog") as dialog_mock,
        ):
            window._edit_selected_task()

        info_mock.assert_called_once()
        dialog_mock.assert_not_called()

    def test_persist_failure_preserves_existing_runtime_state(self) -> None:
        package_dir = self._create_package_dir("persist_failure")
        task = MailTask(
            task_id="task-1",
            to_recipients=["a@example.com"],
            subject="old subject",
            markdown_path="content/body.md",
        )
        updated_task = MailTask(
            task_id="task-1",
            to_recipients=["a@example.com"],
            subject="new subject",
            markdown_path="content/body.md",
        )
        window = self._create_window()
        window._package_dir = package_dir
        window._tasks = [task]
        state = window._runtime.state_for(task)
        state.status = TaskStatus.SENT
        state.last_result = "sent before edit"

        with (
            patch("dingmail.gui.main_task_commands.save_tasks_to_package", side_effect=OSError("locked")),
            patch.object(window, "_show_error_dialog"),
        ):
            saved = window._persist_tasks(
                updated_tasks=[updated_task],
                reset_runtime_task_ids=(updated_task.task_id,),
            )

        self.assertFalse(saved)
        self.assertEqual("old subject", window._tasks[0].subject)
        self.assertEqual(TaskStatus.SENT, window._runtime.status_for(task))
        self.assertEqual("sent before edit", window._runtime.last_result_for(task))

    def test_delivery_worker_rejects_unexpected_result_type(self) -> None:
        window = self._create_window()
        worker = _FakeWorker()
        marked_errors: list[str] = []

        with patch.object(window, "_show_error_dialog") as error_mock:
            window._start_delivery_worker(
                spec=DeliveryWorkerSpec(
                    worker=worker,
                    worker_attr="_send_worker",
                    apply_result=lambda _result: self.fail("unexpected result should not be applied"),
                    mark_error=marked_errors.append,
                    error_title="发送失败",
                    error_prefix="发送任务失败",
                )
            )
            worker.finished_ok.emit("bad-result")

        self.assertTrue(worker.started)
        self.assertIsNone(window._send_worker)
        self.assertEqual(1, len(marked_errors))
        self.assertIn("str", marked_errors[0])
        error_mock.assert_called_once()

    def test_delivery_result_does_not_mutate_current_tasks_after_package_switch(self) -> None:
        old_package = self._create_package_dir("old")
        new_package = self._create_package_dir("new")
        save_tasks_to_package(
            old_package,
            [
                MailTask(
                    task_id="same-id",
                    to_recipients=["old@example.com"],
                    subject="旧任务",
                    markdown_path="content/body.md",
                )
            ],
        )
        save_tasks_to_package(
            new_package,
            [
                MailTask(
                    task_id="same-id",
                    to_recipients=["new@example.com"],
                    subject="新任务",
                    markdown_path="content/body.md",
                )
            ],
        )

        window = self._create_window()
        window._load_package(old_package)
        submitted_tasks = list(window._tasks)
        window._runtime.mark_sending(submitted_tasks)
        window._load_package(new_package)
        result = SendTasksResult(
            run_paths=self._create_run_paths(),
            outcomes=[
                TaskDeliveryOutcome(
                    task_id="same-id",
                    to_email="old@example.com",
                    cc_email="",
                    subject="旧任务",
                    status="sent",
                    message_id="<m1>",
                    error=None,
                )
            ],
        )

        with patch.object(QtWidgets.QMessageBox, "information"):
            window._apply_send_result(submitted_tasks, old_package, result)

        current_task = window._tasks[0]
        self.assertEqual("新任务", current_task.subject)
        self.assertEqual(TaskStatus.READY, window._runtime.status_for(current_task))
        self.assertEqual("", window._runtime.last_result_for(current_task))
        self.assertEqual(result.run_paths.run_dir, window._last_run_dir)

    def test_connection_profile_source_refreshes_after_successful_save(self) -> None:
        window = self._create_window()
        saved_path = self.home_dir / "conn_profile.json"
        window._connection_profile_source_text = "配置：旧配置（待迁移） · 明文授权码"
        window._connection_profile_source_detail = "来源：legacy"
        window._connection_profile_warning = "需要迁移"
        window._refresh_smtp_summary_labels()

        with patch.object(window, "_save_connection_profile", return_value=saved_path):
            window._apply_smtp_connection_success(
                from_email="new@example.com",
                password="secret",
                imap_host="imap.example.com",
                imap_port=993,
                info="ok",
            )

        self.assertEqual("", window._connection_profile_warning)
        self.assertEqual("配置：用户配置", window._connection_profile_source_text)
        self.assertEqual("配置：用户配置", window._profile_source_label.text())
        self.assertIn(str(saved_path), window._profile_source_label.toolTip())
        self.assertTrue(window._smtp_connected)
        self.assertEqual("imap.example.com", window._imap_host)

    def test_legacy_plaintext_profile_is_migrated_when_gui_loads(self) -> None:
        legacy_path = self.home_dir / "legacy" / "conn_profile.json"
        load_result = ConnectionProfileLoadResult(
            profile=ConnectionProfile(from_email="legacy@example.com", smtp_password="legacy-token"),
            source_path=legacy_path,
            is_legacy_source=True,
            uses_plaintext_secret=True,
        )

        with (
            patch("dingmail.gui.main.detect_home_dir", return_value=self.home_dir),
            patch("dingmail.gui.main.load_connection_profile_with_metadata", return_value=load_result),
            patch("dingmail.gui.main.migrate_connection_profile_if_needed") as migrate_mock,
            patch.object(QtWidgets.QSystemTrayIcon, "isSystemTrayAvailable", return_value=False),
        ):
            migrate_mock.side_effect = lambda _result, target_path: target_path
            window = MainWindow()
        self.addCleanup(window.deleteLater)
        self.addCleanup(self._process_events)
        migrated_path = window._conn_config_path

        migrate_mock.assert_called_once_with(load_result, migrated_path)
        self.assertEqual("配置：用户配置（已自动迁移）", window._connection_profile_source_text)
        self.assertEqual("", window._connection_profile_warning)
        self.assertIn(str(legacy_path), window._connection_profile_source_detail)
        self.assertIn(str(migrated_path), window._profile_source_label.toolTip())

    def test_main_window_state_proxy_keeps_legacy_attributes_working(self) -> None:
        window = self._create_window()
        self.assertIs(window._tasks, window._state.tasks)

        window._package_dir = self.home_dir / "packages" / "proxy"
        window._smtp_connected = True
        window._connection_profile_source_text = "配置：代理测试"
        window._connection_profile_warning = "警告"

        self.assertEqual(window._package_dir, window._state.package_dir)
        self.assertTrue(window._state.smtp_connected)
        self.assertEqual("配置：代理测试", window._state.connection_profile_source_text)
        self.assertEqual("警告", window._state.connection_profile_warning)

        window._state.tasks.append(MailTask(task_id="state-task", to_recipients=["a@example.com"], subject="状态拆分"))
        self.assertEqual("state-task", window._tasks[0].task_id)

    def test_future_scheduled_tasks_are_requeued_on_load(self) -> None:
        package_dir = self._create_package_dir("requeue")
        save_tasks_to_package(
            package_dir,
            [
                MailTask(
                    task_id="task-1",
                    to_recipients=["a@example.com"],
                    subject="定时任务",
                    markdown_path="content/body.md",
                    schedule_enabled=True,
                    scheduled_at=datetime.now() + timedelta(hours=1),
                )
            ],
        )

        window = self._create_window()
        window._load_package(package_dir)

        self.assertIn("task-1", window._runtime.queued_task_ids)
        self.assertEqual(TaskStatus.QUEUED, window._runtime.status_for(window._tasks[0]))

    def test_terminal_or_expired_scheduled_tasks_not_requeued_on_load(self) -> None:
        package_dir = self._create_package_dir("norequeue")
        save_tasks_to_package(
            package_dir,
            [
                MailTask(
                    task_id="task-sent",
                    to_recipients=["a@example.com"],
                    subject="已发送",
                    markdown_path="content/body.md",
                    schedule_enabled=True,
                    scheduled_at=datetime.now() + timedelta(hours=1),
                    last_delivery_status="sent",
                ),
                MailTask(
                    task_id="task-expired",
                    to_recipients=["b@example.com"],
                    subject="已过期",
                    markdown_path="content/body.md",
                    schedule_enabled=True,
                    scheduled_at=datetime.now() - timedelta(hours=1),
                ),
            ],
        )

        window = self._create_window()
        window._load_package(package_dir)

        self.assertEqual(set(), window._runtime.queued_task_ids)
        self.assertEqual(TaskStatus.SENT, window._runtime.status_for(window._tasks[0]))

    def test_exit_from_tray_waits_smtp_worker(self) -> None:
        window = self._create_window()
        window._tray = _FakeTray()
        window._smtp_worker = _FakeWorker()

        with patch.object(QtWidgets.QApplication, "quit") as quit_mock:
            window._exit_from_tray()

        self.assertTrue(window._quit_requested)
        self.assertTrue(quit_mock.called)

    def test_close_event_accepts_after_smtp_worker_wait(self) -> None:
        window = self._create_window()
        window._tray = None
        window._smtp_worker = _FakeWorker()

        event = QtGui.QCloseEvent()
        window.closeEvent(event)

        self.assertTrue(event.isAccepted())

    def test_last_package_restored_on_startup(self) -> None:
        package_dir = self._create_package_dir("restore")
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
        (self.home_dir / "state.json").write_text(
            json.dumps({"last_package_dir": str(package_dir)}, ensure_ascii=False),
            encoding="utf-8",
        )

        window = self._create_window()

        self.assertEqual(package_dir, window._package_dir)
        self.assertEqual(1, len(window._tasks))

    def test_persist_delivery_status_skips_write_after_package_switch(self) -> None:
        old_package = self._create_package_dir("old-persist")
        new_package = self._create_package_dir("new-persist")
        save_tasks_to_package(
            old_package,
            [
                MailTask(
                    task_id="same-id",
                    to_recipients=["old@example.com"],
                    subject="旧任务",
                    markdown_path="content/body.md",
                )
            ],
        )
        save_tasks_to_package(
            new_package,
            [
                MailTask(
                    task_id="same-id",
                    to_recipients=["new@example.com"],
                    subject="新任务",
                    markdown_path="content/body.md",
                )
            ],
        )

        window = self._create_window()
        window._load_package(old_package)
        submitted_tasks = list(window._tasks)
        window._runtime.mark_sending(submitted_tasks)
        window._load_package(new_package)
        result = SendTasksResult(
            run_paths=self._create_run_paths(),
            outcomes=[
                TaskDeliveryOutcome(
                    task_id="same-id",
                    to_email="old@example.com",
                    cc_email="",
                    subject="旧任务",
                    status="sent",
                    message_id="<m1>",
                    error=None,
                )
            ],
        )

        with patch.object(QtWidgets.QMessageBox, "information"):
            window._apply_send_result(submitted_tasks, old_package, result)

        persisted_old = load_tasks_from_package(old_package)
        self.assertEqual("旧任务", persisted_old[0].subject)
        self.assertEqual("", persisted_old[0].last_delivery_status)
    def test_search_filter_filters_through_proxy(self) -> None:
        package_dir = self._create_package_dir("search")
        save_tasks_to_package(
            package_dir,
            [
                MailTask(
                    task_id="task-1",
                    to_recipients=["a@example.com"],
                    subject="月度通知",
                    markdown_path="content/body.md",
                ),
                MailTask(
                    task_id="task-2",
                    to_recipients=["b@example.com"],
                    subject="项目周报",
                    markdown_path="content/body.md",
                ),
            ],
        )

        window = self._create_window()
        window._load_package(package_dir)
        self.assertEqual(2, window._task_proxy.rowCount())

        window._task_search_input.setText("周报")
        window._apply_search_text()
        self.assertEqual(1, window._task_proxy.rowCount())
        source_row = window._task_proxy.mapToSource(window._task_proxy.index(0, 0)).row()
        self.assertEqual("task-2", window._task_model.task_at(source_row).task_id)

        window._task_search_input.setText("")
        window._apply_search_text()
        self.assertEqual(2, window._task_proxy.rowCount())

    def test_selected_rows_map_through_proxy_when_filtered(self) -> None:
        package_dir = self._create_package_dir("selmap")
        save_tasks_to_package(
            package_dir,
            [
                MailTask(
                    task_id="task-1",
                    to_recipients=["a@example.com"],
                    subject="正常任务",
                    markdown_path="content/body.md",
                ),
                MailTask(
                    task_id="task-2",
                    to_recipients=["b@example.com"],
                    subject="异常任务",
                    markdown_path="content/missing.md",
                ),
            ],
        )

        window = self._create_window()
        window._load_package(package_dir)
        window._set_task_filter("issue")
        self._process_events()

        window._task_table.selectRow(0)
        self._process_events()

        self.assertEqual([1], window._selected_rows())
        self.assertEqual("task-2", window._selected_detail_task().task_id)
        self.assertEqual("异常任务", window._detail_title_label.text())
    def test_batch_selection_shows_summary_detail(self) -> None:
        package_dir = self._create_package_dir("batch")
        save_tasks_to_package(
            package_dir,
            [
                MailTask(
                    task_id="task-1",
                    to_recipients=["a@example.com"],
                    subject="正常任务",
                    markdown_path="content/body.md",
                ),
                MailTask(
                    task_id="task-2",
                    to_recipients=["b@example.com"],
                    subject="异常任务",
                    markdown_path="content/missing.md",
                ),
            ],
        )

        window = self._create_window()
        window._load_package(package_dir)
        self._process_events()

        window._task_table.selectAll()
        self._process_events()

        self.assertEqual("批量操作", window._detail_title_label.text())
        self.assertIn("已选择 2 条", window._detail_status_tag.text())
        self.assertIn("可保存草稿：1 条", window._detail_cc_label.text())
        self.assertIn("需修正：1 条", window._detail_markdown_label.text())

    def test_app_settings_persist_to_state_file(self) -> None:
        window = self._create_window()

        window._apply_app_settings(rate_limit_seconds=2.5, retention_days=30)

        self.assertEqual(2.5, window._send_rate_limit_seconds)
        self.assertEqual(30, window._runs_retention_days)
        saved = json.loads((self.home_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(2.5, saved["send_rate_limit_seconds"])
        self.assertEqual(30, saved["runs_retention_days"])

        # 越界值应被夹紧
        window._apply_app_settings(rate_limit_seconds=9999, retention_days=-5)
        self.assertEqual(600.0, window._send_rate_limit_seconds)
        self.assertEqual(0, window._runs_retention_days)


if __name__ == "__main__":
    unittest.main()
