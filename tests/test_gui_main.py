from __future__ import annotations

import json
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

from dingmail.connection_profile import ConnectionProfile, ConnectionProfileLoadResult
from dingmail.task_delivery import SendTasksResult, TaskDeliveryOutcome
from dingmail.task_models import MailTask
from dingmail.task_package import TASKS_FILENAME, TASKS_SHEET_NAME, load_tasks_from_package, save_tasks_to_package
from dingmail.task_status import TaskStatus
from dingmail.gui.main_window import MainWindow


TASK_HEADERS = [
    "任务ID", "是否启用", "收件人", "抄送人", "主题", "开头/补充内容",
    "Markdown路径", "是否有附件", "附件路径", "是否定时发送", "定时发送时间", "备注",
]


class _FakeTray:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, object, int]] = []

    def showMessage(self, title: str, message: str, icon, timeout: int) -> None:  # noqa: N802
        self.messages.append((title, message, icon, timeout))


class _FakeWorker:
    def __init__(self) -> None:
        self.started = False

    def start(self) -> None:
        self.started = True

    def wait(self, timeout: int = 0) -> bool:
        return True


class _FakeDeliveryWorker:
    def __init__(self) -> None:
        self.cancelled = False

    def request_cancel(self) -> None:
        self.cancelled = True

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

    def _create_window(self, *, profile: ConnectionProfile | None = None) -> MainWindow:
        with (
            patch("dingmail.gui.main_window.detect_home_dir", return_value=self.home_dir),
            patch(
                "dingmail.gui.services.connection.load_connection_profile_with_metadata",
                return_value=ConnectionProfileLoadResult(profile=profile or ConnectionProfile()),
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

    def _save_package(self, package_dir: Path, tasks: list[MailTask]) -> None:
        save_tasks_to_package(package_dir, tasks)

    # ---- 任务包加载 ----

    def test_load_package_repairs_duplicate_ids_and_shows_notice(self) -> None:
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
        window.load_package(package_dir)

        self.assertEqual(2, window.tasks_page._model.rowCount())
        self.assertEqual(2, len({task.task_id for task in window.tasks.tasks}))
        self.assertFalse(window.tasks_page._banner.isHidden())
        self.assertIn("已自动修复", window.tasks_page._banner.text())

        saved_tasks = load_tasks_from_package(package_dir)
        self.assertEqual(2, len({task.task_id for task in saved_tasks}))

    def test_scheduled_future_tasks_are_requeued_on_load(self) -> None:
        package_dir = self._create_package_dir("requeue")
        self._save_package(
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
        window.load_package(package_dir)

        self.assertIn("task-1", window.tasks.runtime.queued_task_ids)
        self.assertEqual(TaskStatus.QUEUED, window.tasks.runtime.status_for(window.tasks.tasks[0]))

    def test_terminal_or_expired_scheduled_tasks_not_requeued_on_load(self) -> None:
        package_dir = self._create_package_dir("norequeue")
        self._save_package(
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
        window.load_package(package_dir)

        self.assertEqual(set(), window.tasks.runtime.queued_task_ids)
        self.assertEqual(TaskStatus.SENT, window.tasks.runtime.status_for(window.tasks.tasks[0]))

    def test_last_package_restored_on_startup(self) -> None:
        package_dir = self._create_package_dir("restore")
        self._save_package(
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

        self.assertEqual(package_dir, window.tasks.package_dir)
        self.assertEqual(1, len(window.tasks.tasks))

    # ---- 选择与详情 ----

    def test_batch_selection_shows_summary_detail(self) -> None:
        package_dir = self._create_package_dir("batch")
        self._save_package(
            package_dir,
            [
                MailTask(task_id="task-1", to_recipients=["a@example.com"], subject="正常任务", markdown_path="content/body.md"),
                MailTask(task_id="task-2", to_recipients=["b@example.com"], subject="异常任务", markdown_path="content/missing.md"),
            ],
        )

        window = self._create_window()
        window.load_package(package_dir)
        # 先同步完成校验，使状态计数确定（增量校验 timer 在测试中不定时触发）
        window.tasks.runtime.refresh_runtime_state(window.tasks.tasks)
        self._process_events()

        window.tasks_page._table.selectAll()
        self._process_events()

        self.assertEqual("批量操作", window.tasks_page._detail_title_label.text())
        self.assertIn("已选择 2 条", window.tasks_page._detail_status_tag.text())
        self.assertIn("可保存草稿：1 条", window.tasks_page._detail_cc_label.text())
        self.assertIn("需修正：1 条", window.tasks_page._detail_markdown_label.text())

    def test_search_filter_filters_through_proxy(self) -> None:
        package_dir = self._create_package_dir("search")
        self._save_package(
            package_dir,
            [
                MailTask(task_id="task-1", to_recipients=["a@example.com"], subject="月度通知", markdown_path="content/body.md"),
                MailTask(task_id="task-2", to_recipients=["b@example.com"], subject="项目周报", markdown_path="content/body.md"),
            ],
        )

        window = self._create_window()
        window.load_package(package_dir)
        self.assertEqual(2, window.tasks_page._proxy.rowCount())

        window.tasks_page._search_input.setText("周报")
        window.tasks_page._apply_search_text()
        self.assertEqual(1, window.tasks_page._proxy.rowCount())
        source_row = window.tasks_page._proxy.mapToSource(window.tasks_page._proxy.index(0, 0)).row()
        self.assertEqual("task-2", window.tasks_page._model.task_at(source_row).task_id)

        window.tasks_page._search_input.setText("")
        window.tasks_page._apply_search_text()
        self.assertEqual(2, window.tasks_page._proxy.rowCount())

    def test_selected_rows_map_through_proxy_when_filtered(self) -> None:
        package_dir = self._create_package_dir("selmap")
        self._save_package(
            package_dir,
            [
                MailTask(task_id="task-1", to_recipients=["a@example.com"], subject="正常任务", markdown_path="content/body.md"),
                MailTask(task_id="task-2", to_recipients=["b@example.com"], subject="异常任务", markdown_path="content/missing.md"),
            ],
        )

        window = self._create_window()
        window.load_package(package_dir)
        # processEvents 不触发 QTimer，先同步完成校验再筛选（真实应用由增量校验 timer 完成）
        window.tasks.runtime.refresh_runtime_state(window.tasks.tasks)
        window.tasks_page._model.refresh()
        window.tasks_page._proxy.refilter()
        window.tasks_page._set_filter("issue")
        self._process_events()

        window.tasks_page._table.selectRow(0)
        self._process_events()

        self.assertEqual([1], window.tasks_page.selected_rows())
        self.assertEqual("task-2", window.tasks_page.selected_tasks()[0].task_id)

    # ---- 投递结果 ----

    def _make_result(self, task_id: str, status: str = "sent") -> SendTasksResult:
        return SendTasksResult(
            run_paths=None,  # 占位：结果应用路径不使用 run_paths
            outcomes=[
                TaskDeliveryOutcome(
                    task_id=task_id,
                    to_email="a@example.com",
                    cc_email="",
                    subject="主题",
                    status=status,
                    message_id="<m1>" if status == "sent" else None,
                    error=None if status == "sent" else "boom",
                )
            ],
        )

    def test_send_result_updates_runtime_state(self) -> None:
        package_dir = self._create_package_dir("sendres")
        task = MailTask(task_id="task-1", to_recipients=["a@example.com"], subject="主题", markdown_path="content/body.md")
        self._save_package(package_dir, [task])

        window = self._create_window()
        window.load_package(package_dir)
        submitted = list(window.tasks.tasks)
        window.tasks.mark_sending(submitted)
        window.tasks.begin_submission()

        sent, failed = window.tasks.apply_send_result(submitted, package_dir, self._make_result("task-1", "sent"))

        self.assertEqual((1, 0), (sent, failed))
        self.assertEqual(TaskStatus.SENT, window.tasks.runtime.status_for(window.tasks.tasks[0]))
        persisted = load_tasks_from_package(package_dir)
        self.assertEqual("sent", persisted[0].last_delivery_status)

    def test_persist_delivery_status_skips_write_after_package_switch(self) -> None:
        old_package = self._create_package_dir("old-persist")
        new_package = self._create_package_dir("new-persist")
        for pkg, subject in ((old_package, "旧任务"), (new_package, "新任务")):
            self._save_package(
                pkg,
                [MailTask(task_id="same-id", to_recipients=["x@example.com"], subject=subject, markdown_path="content/body.md")],
            )

        window = self._create_window()
        window.load_package(old_package)
        submitted = list(window.tasks.tasks)
        window.tasks.mark_sending(submitted)
        window.load_package(new_package)

        window.tasks.apply_send_result(submitted, old_package, self._make_result("same-id", "sent"))

        persisted_old = load_tasks_from_package(old_package)
        self.assertEqual("旧任务", persisted_old[0].subject)
        self.assertEqual("", persisted_old[0].last_delivery_status)

    # ---- 调度与自动重连 ----

    def test_scheduler_tries_auto_connect_when_queued_and_disconnected(self) -> None:
        package_dir = self._create_package_dir("autoconn")
        self._save_package(
            package_dir,
            [MailTask(task_id="task-1", to_recipients=["a@example.com"], subject="主题", markdown_path="content/body.md")],
        )
        window = self._create_window()
        window.load_package(package_dir)
        window.tasks.runtime.queued_task_ids.add("task-1")

        with (
            patch.object(window.connection, "try_auto_connect", return_value=True) as auto_mock,
            patch.object(window.delivery, "start_send") as send_mock,
        ):
            window.process_scheduled_tasks()

        auto_mock.assert_called_once()
        send_mock.assert_not_called()

    def test_scheduler_sends_due_tasks_when_connected(self) -> None:
        package_dir = self._create_package_dir("due")
        self._save_package(
            package_dir,
            [
                MailTask(
                    task_id="task-due",
                    to_recipients=["a@example.com"],
                    subject="到期任务",
                    markdown_path="content/body.md",
                    schedule_enabled=True,
                    scheduled_at=datetime.now() - timedelta(minutes=1),
                )
            ],
        )

        window = self._create_window()
        window.load_package(package_dir)
        window.connection.connected = True
        window.connection.password = "token"
        window.tasks.runtime.queued_task_ids.add("task-due")

        with patch.object(window.delivery, "start_send", return_value=True) as send_mock:
            window.process_scheduled_tasks()

        send_mock.assert_called_once()
        self.assertEqual(["task-due"], [task.task_id for task in send_mock.call_args.kwargs["tasks"]])

    # ---- 连接 ----

    def test_apply_connection_success_saves_profile_and_updates_state(self) -> None:
        window = self._create_window()
        saved_path = self.home_dir / "conn_profile.json"

        with patch(
            "dingmail.gui.services.connection.save_connection_profile", return_value=saved_path
        ):
            message = window.connection.apply_connection_success(
                from_email="new@example.com",
                password="secret",
                imap_host="imap.example.com",
                imap_port=993,
                info="ok",
            )

        self.assertTrue(window.connection.connected)
        self.assertEqual("new@example.com", window.connection.smtp_cfg.username)
        self.assertEqual("imap.example.com", window.connection.imap_host)
        self.assertIn("已保存登录信息", message)

    # ---- 退出与托盘 ----

    def test_exit_from_tray_waits_smtp_test_worker(self) -> None:
        window = self._create_window()
        window._tray = _FakeTray()
        window.connection._worker = _FakeWorker()

        with patch.object(QtWidgets.QApplication, "quit") as quit_mock:
            window.exit_from_tray()

        self.assertTrue(window._quit_requested)
        self.assertTrue(quit_mock.called)

    def test_exit_from_tray_blocked_when_wait_times_out(self) -> None:
        window = self._create_window()
        window._tray = _FakeTray()
        worker = _FakeDeliveryWorker()
        worker.wait = lambda timeout=0: False  # 模拟等待超时
        window.delivery._send_worker = worker

        with (
            patch.object(QtWidgets.QMessageBox, "information") as info_mock,
            patch.object(QtWidgets.QApplication, "quit") as quit_mock,
        ):
            window.exit_from_tray()

        info_mock.assert_called_once()
        quit_mock.assert_not_called()
        self.assertFalse(window._quit_requested)

    def test_close_event_accepts_after_workers_finish(self) -> None:
        window = self._create_window()
        window._tray = None
        window.connection._worker = _FakeWorker()

        event = QtGui.QCloseEvent()
        window.closeEvent(event)

        self.assertTrue(event.isAccepted())

    def test_close_event_minimizes_to_tray_when_connected(self) -> None:
        window = self._create_window()
        fake_tray = _FakeTray()
        window._tray = fake_tray
        window.show()
        window.connection.connected = True
        self._process_events()

        event = QtGui.QCloseEvent()
        window.closeEvent(event)

        self.assertFalse(event.isAccepted())
        self.assertTrue(window.isHidden())
        self.assertEqual(1, len(fake_tray.messages))
        self.assertIn("已最小化到托盘", fake_tray.messages[0][0])

    # ---- 设置持久化 ----

    def test_send_settings_persist_to_state_file(self) -> None:
        window = self._create_window()

        window.apply_send_settings(2.5, 30)

        self.assertEqual(2.5, window.app_settings.send_rate_limit_seconds)
        self.assertEqual(30, window.app_settings.runs_retention_days)
        saved = json.loads((self.home_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(2.5, saved["send_rate_limit_seconds"])
        self.assertEqual(30, saved["runs_retention_days"])

        window.apply_send_settings(9999, -5)
        self.assertEqual(600.0, window.app_settings.send_rate_limit_seconds)
        self.assertEqual(0, window.app_settings.runs_retention_days)

    def test_splitter_sizes_persist_to_state_file(self) -> None:
        window = self._create_window()

        window._remember_splitter([1000, 400])

        saved = json.loads((self.home_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual([1000, 400], saved["splitter_sizes"])

    def test_nav_page_switch_persists(self) -> None:
        window = self._create_window()

        window.switch_page("settings")

        self.assertEqual("settings", window.app_settings.nav_page)
        saved = json.loads((self.home_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual("settings", saved["nav_page"])

    def test_nav_rail_connect_button_jumps_to_settings(self) -> None:
        window = self._create_window()
        window.show()
        self._process_events()

        # 未连接时导航栏显示「连接」按钮，点击跳设置页
        self.assertTrue(window._nav_rail._connect_button.isVisible())
        window._nav_rail._connect_button.click()
        self.assertIs(window._stack.currentWidget(), window.settings_page)

        window.connection._set_connected(True, "ok")
        self._process_events()
        self.assertFalse(window._nav_rail._connect_button.isVisible())

    def test_startup_auto_connects_when_credentials_saved(self) -> None:
        with patch("dingmail.gui.main_window.QtCore.QTimer.singleShot") as single_shot_mock:
            self._create_window(
                profile=ConnectionProfile(from_email="op@example.com", smtp_password="token")
            )

        # 凭据齐全时启动应安排一次自动连接
        calls = [c for c in single_shot_mock.call_args_list if c.args and c.args[1].__name__ == "try_auto_connect"]
        self.assertEqual(1, len(calls))

    def test_scheduler_skips_when_modal_dialog_open(self) -> None:
        """模态对话框的嵌套事件循环里调度器不得启动发送（F1 Critical 回归）。"""
        package_dir = self._create_package_dir("modal")
        self._save_package(
            package_dir,
            [
                MailTask(
                    task_id="task-due",
                    to_recipients=["a@example.com"],
                    subject="到期任务",
                    markdown_path="content/body.md",
                    schedule_enabled=True,
                    scheduled_at=datetime.now() - timedelta(minutes=1),
                )
            ],
        )

        window = self._create_window()
        window.load_package(package_dir)
        window.connection.connected = True
        window.connection.password = "token"
        window.tasks.runtime.queued_task_ids.add("task-due")

        from PySide6 import QtWidgets as _qtw

        dialog = _qtw.QDialog(window)  # 模拟已打开的模态对话框
        dialog.open()
        try:
            with patch.object(window.delivery, "start_send", return_value=True) as send_mock:
                window.process_scheduled_tasks()
            send_mock.assert_not_called()
        finally:
            dialog.done(_qtw.QDialog.Accepted)

    def test_idle_scheduler_tick_does_not_emit_tasks_changed(self) -> None:
        """无到期任务的空转 tick 不得触发 tasksChanged（F6 回归：避免预览重渲染）。"""
        package_dir = self._create_package_dir("idle")
        self._save_package(
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
        window.load_package(package_dir)
        window.connection.connected = True

        emitted = []
        window.tasks.tasksChanged.connect(lambda: emitted.append(1))
        window.process_scheduled_tasks()  # 首次 tick 初始化 due 签名，允许一次刷新
        window.process_scheduled_tasks()
        window.process_scheduled_tasks()
        self.assertEqual(1, len(emitted))

    def test_result_generation_guard_skips_stale_submission(self) -> None:
        """提交后任务列表被替换（代数递增），结果不得写进新列表状态（F9 回归）。"""
        package_dir = self._create_package_dir("gen")
        self._save_package(
            package_dir,
            [
                MailTask(task_id="task-1", to_recipients=["a@example.com"], subject="主题", markdown_path="content/body.md")
            ],
        )

        window = self._create_window()
        window.load_package(package_dir)
        submitted = list(window.tasks.tasks)
        window.tasks.mark_sending(submitted)
        window.tasks.begin_submission()

        # 模拟发送期间用户编辑：persist_tasks 换新列表对象 → 代数递增
        updated = [MailTask(task_id="task-1", to_recipients=["a@example.com"], subject="新主题", markdown_path="content/body.md")]
        self.assertTrue(window.tasks.persist_tasks(updated))
        self.assertNotEqual(window.tasks.generation, window.tasks._generation_at_submit)

        window.tasks.apply_send_result(submitted, package_dir, self._make_result("task-1", "sent"))

        # 新列表对象不得被旧提交的结果置为 SENT
        self.assertEqual(TaskStatus.UNCHECKED, window.tasks.runtime.status_for(window.tasks.tasks[0]))
        persisted = load_tasks_from_package(package_dir)
        self.assertEqual("新主题", persisted[0].subject)




if __name__ == "__main__":
    unittest.main()
