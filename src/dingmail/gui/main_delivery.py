from __future__ import annotations

from datetime import datetime

from PySide6 import QtWidgets

from ..task_delivery import SendTasksResult
from ..task_models import MailTask
from .main_support import error_summary
from .workers import DraftWorkerConfig, SaveDraftsWorker, SendTasksWorker, SendWorkerConfig


class MainDeliveryMixin:
    def _start_send(self, tasks: list[MailTask], *, queue_mode: bool) -> None:
        if not self._package_dir:
            return
        if self._send_worker is not None or self._draft_worker is not None:
            QtWidgets.QMessageBox.information(self, "正在发送", "当前已有发送任务在执行，请稍候。")
            return
        if not tasks:
            QtWidgets.QMessageBox.information(self, "没有可发送任务", "请先选择或准备好可发送的任务。")
            return

        self._runtime.mark_sending(tasks)
        self._refresh_task_table()
        self._refresh_ui_state()

        worker = SendTasksWorker(SendWorkerConfig(
            tasks=tasks,
            package_dir=self._package_dir,
            home_dir=self._home_dir,
            smtp_cfg=self._smtp_cfg,
            smtp_password=self._smtp_password,
        ))
        self._send_worker = worker

        def _ok(result: object) -> None:
            assert isinstance(result, SendTasksResult)
            self._send_worker = None
            self._apply_send_result(result)
            if self._tray is not None and queue_mode:
                self._tray.showMessage(
                    "定时邮件已发送",
                    f"已完成 {len(result.outcomes)} 条任务。",
                    QtWidgets.QSystemTrayIcon.Information,
                    4000,
                )

        def _err(tb: str) -> None:
            self._send_worker = None
            error_text = tb.strip()
            self._runtime.mark_send_worker_error(self._tasks, error_text)
            self._refresh_task_table()
            self._refresh_ui_state()
            self._show_error_dialog("发送失败", f"发送任务失败：{error_summary(tb)}", details=tb)

        worker.finished_ok.connect(_ok)
        worker.finished_err.connect(_err)
        worker.start()

    def _start_save_drafts(self, tasks: list[MailTask]) -> None:
        if not self._package_dir:
            return
        if self._send_worker is not None or self._draft_worker is not None:
            QtWidgets.QMessageBox.information(self, "请稍候", "当前已有发送/草稿任务在执行，请稍候。")
            return
        if not tasks:
            QtWidgets.QMessageBox.information(self, "没有可保存任务", "请先选择或准备好可保存的任务。")
            return

        self._runtime.mark_drafting(tasks)
        self._refresh_task_table()
        self._refresh_ui_state()

        worker = SaveDraftsWorker(DraftWorkerConfig(
            tasks=tasks,
            package_dir=self._package_dir,
            home_dir=self._home_dir,
            imap_username=self._smtp_cfg.username.strip(),
            imap_password=self._smtp_password,
        ))
        self._draft_worker = worker

        def _ok(result: object) -> None:
            assert isinstance(result, SendTasksResult)
            self._draft_worker = None
            self._apply_draft_result(result)

        def _err(tb: str) -> None:
            self._draft_worker = None
            error_text = tb.strip()
            self._runtime.mark_draft_worker_error(self._tasks, error_text)
            self._refresh_task_table()
            self._refresh_ui_state()
            self._show_error_dialog("保存草稿失败", f"保存草稿失败：{error_summary(tb)}", details=tb)

        worker.finished_ok.connect(_ok)
        worker.finished_err.connect(_err)
        worker.start()

    def _apply_send_result(self, result: SendTasksResult) -> None:
        self._last_run_dir = result.run_paths.run_dir
        sent_count, failed_count = self._runtime.apply_send_result(self._tasks, result)
        self._refresh_task_table()
        self._refresh_ui_state()
        QtWidgets.QMessageBox.information(
            self,
            "发送完成",
            f"本次输出目录：{result.run_paths.run_dir}\n发送成功：{sent_count}\n发送失败：{failed_count}",
        )

    def _apply_draft_result(self, result: SendTasksResult) -> None:
        self._last_run_dir = result.run_paths.run_dir
        ok_count, fail_count = self._runtime.apply_draft_result(self._tasks, result)
        self._refresh_task_table()
        self._refresh_ui_state()
        QtWidgets.QMessageBox.information(
            self,
            "保存草稿完成",
            f"本次输出目录：{result.run_paths.run_dir}\n草稿保存成功：{ok_count}\n草稿保存失败：{fail_count}",
        )

    def _save_selected_to_drafts(self) -> None:
        if not self._smtp_connected:
            QtWidgets.QMessageBox.warning(self, "尚未连接 SMTP", "请先完成顶部 SMTP 连接。")
            return
        tasks = self._selected_tasks()
        if not tasks:
            QtWidgets.QMessageBox.information(self, "未选择任务", "请先选择至少一条任务。")
            return

        valid, blocked = self._runtime.partition_valid_tasks(tasks, check_schedule_time=False)
        if blocked:
            QtWidgets.QMessageBox.warning(self, "存在不可保存任务", "\n\n".join(blocked[:10]))
        if not valid:
            return

        reply = QtWidgets.QMessageBox.question(
            self,
            "确认保存草稿",
            f"将把选中的 {len(valid)} 条任务写入邮箱草稿箱，不会直接发送。确认继续吗？",
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return

        self._start_save_drafts(valid)

    def _send_selected_now(self) -> None:
        if not self._smtp_connected:
            QtWidgets.QMessageBox.warning(self, "尚未连接 SMTP", "请先完成顶部 SMTP 连接。")
            return
        tasks = self._selected_tasks()
        if not tasks:
            QtWidgets.QMessageBox.information(self, "未选择任务", "请先选择至少一条任务。")
            return

        valid, blocked = self._runtime.partition_valid_tasks(tasks, check_schedule_time=False)
        if blocked:
            QtWidgets.QMessageBox.warning(self, "存在不可发送任务", "\n\n".join(blocked[:10]))
        if not valid:
            return

        reply = QtWidgets.QMessageBox.question(
            self,
            "确认立即发送",
            f"将立即发送选中的 {len(valid)} 条任务，并忽略它们的定时设置。确认继续吗？",
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        self._start_send(valid, queue_mode=False)

    def _queue_selected_tasks(self) -> None:
        if not self._smtp_connected:
            QtWidgets.QMessageBox.warning(self, "尚未连接 SMTP", "请先完成顶部 SMTP 连接。")
            return
        tasks = self._selected_tasks()
        if not tasks:
            QtWidgets.QMessageBox.information(self, "未选择任务", "请先选择至少一条任务。")
            return
        queued, errors = self._runtime.queue_scheduled_tasks(tasks)
        self._refresh_task_table()
        self._refresh_ui_state()
        message = f"已加入定时队列：{queued} 条。"
        if errors:
            message += "\n\n以下任务未加入：\n" + "\n".join(errors[:10])
        QtWidgets.QMessageBox.information(self, "定时队列结果", message)

    def _retry_failed_tasks(self) -> None:
        failed = [task for task in self._tasks if task.status == "发送失败" and task.enabled]
        if not failed:
            QtWidgets.QMessageBox.information(self, "无需重试", "当前没有可重试的失败任务。")
            return

        valid, blocked = self._runtime.partition_valid_tasks(failed, check_schedule_time=False)
        if blocked:
            QtWidgets.QMessageBox.warning(self, "部分失败任务仍不可发送", "\n".join(blocked[:10]))
        if not valid:
            return
        self._start_send(valid, queue_mode=False)

    def _process_scheduled_tasks(self) -> None:
        if (
            not self._smtp_connected
            or self._send_worker is not None
            or self._draft_worker is not None
            or not self._package_dir
        ):
            return
        due_tasks = self._runtime.collect_due_tasks(self._tasks, now=datetime.now())

        if due_tasks:
            self._start_send(due_tasks, queue_mode=True)
        else:
            self._refresh_task_table()
            self._refresh_ui_state()
