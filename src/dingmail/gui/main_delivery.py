from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6 import QtCore, QtWidgets

from ..constants import DEFAULT_IMAP_HOST, DEFAULT_IMAP_PORT_SSL
from ..task_delivery import DeliveryStatus, SendTasksResult
from ..task_models import MailTask
from ..task_package import save_tasks_to_package
from ..task_status import TaskStatus
from .main_support import error_summary
from .workers import DraftWorkerConfig, SaveDraftsWorker, SendTasksWorker, SendWorkerConfig


@dataclass(frozen=True)
class DeliveryWorkerSpec:
    worker: QtCore.QThread
    worker_attr: str
    apply_result: Callable[[SendTasksResult], None]
    mark_error: Callable[[str], None]
    error_title: str
    error_prefix: str
    after_ok: Callable[[SendTasksResult], None] | None = None


class MainDeliveryMixin:
    def _delivery_worker_active(self) -> bool:
        return self._send_worker is not None or self._draft_worker is not None

    def _delivery_is_busy(self, *, title: str, message: str) -> bool:
        if not self._delivery_worker_active():
            return False
        QtWidgets.QMessageBox.information(self, title, message)
        return True

    def _start_delivery_worker(
        self,
        *,
        spec: DeliveryWorkerSpec,
    ) -> None:
        setattr(self, spec.worker_attr, spec.worker)

        def _clear_worker() -> None:
            setattr(self, spec.worker_attr, None)

        def _ok(result: object) -> None:
            _clear_worker()
            if not isinstance(result, SendTasksResult):
                error_text = f"后台任务返回了异常结果类型：{type(result).__name__}"
                spec.mark_error(error_text)
                self._refresh_task_table()
                self._refresh_ui_state()
                self._show_error_dialog(spec.error_title, error_text)
                return
            spec.apply_result(result)
            if spec.after_ok is not None:
                spec.after_ok(result)

        def _err(tb: str) -> None:
            _clear_worker()
            error_text = tb.strip()
            spec.mark_error(error_text)
            self._refresh_task_table()
            self._refresh_ui_state()
            self._show_error_dialog(spec.error_title, f"{spec.error_prefix}：{error_summary(tb)}", details=tb)

        def _progress(current: int, total: int) -> None:
            self._on_delivery_progress(current, total)

        spec.worker.finished_ok.connect(_ok)
        spec.worker.finished_err.connect(_err)
        if hasattr(spec.worker, "progress"):
            spec.worker.progress.connect(_progress)
        spec.worker.start()

    def _on_delivery_progress(self, current: int, total: int) -> None:
        if hasattr(self, "statusBar"):
            self.statusBar().showMessage(f"正在处理 {current}/{total}...", 5000)

    def _cancel_current_delivery(self) -> None:
        if self._send_worker is not None and hasattr(self._send_worker, "request_cancel"):
            self._send_worker.request_cancel()
        if self._draft_worker is not None and hasattr(self._draft_worker, "request_cancel"):
            self._draft_worker.request_cancel()

    def _start_send(self, tasks: list[MailTask], *, queue_mode: bool) -> None:
        if not self._package_dir:
            return
        if self._delivery_is_busy(title="正在发送", message="当前已有发送任务在执行，请稍候。"):
            return
        if not tasks:
            QtWidgets.QMessageBox.information(self, "没有可发送任务", "请先选择或准备好可发送的任务。")
            return

        submitted_tasks = list(tasks)
        submitted_package_dir = self._package_dir
        self._runtime.mark_sending(submitted_tasks)
        self._refresh_task_table()
        self._refresh_ui_state()

        worker = SendTasksWorker(SendWorkerConfig(
            tasks=submitted_tasks,
            package_dir=submitted_package_dir,
            home_dir=self._home_dir,
            smtp_cfg=self._smtp_cfg,
            smtp_password=self._smtp_password,
        ))
        def _show_queue_notification(result: SendTasksResult) -> None:
            if self._tray is not None and queue_mode:
                self._tray.showMessage(
                    "定时邮件已发送",
                    f"已完成 {len(result.outcomes)} 条任务。",
                    QtWidgets.QSystemTrayIcon.Information,
                    4000,
                )

        self._start_delivery_worker(
            spec=DeliveryWorkerSpec(
                worker=worker,
                worker_attr="_send_worker",
                apply_result=lambda result: self._apply_send_result(
                    submitted_tasks,
                    submitted_package_dir,
                    result,
                ),
                mark_error=lambda error_text: self._mark_send_worker_error(
                    submitted_tasks,
                    submitted_package_dir,
                    error_text,
                ),
                error_title="发送失败",
                error_prefix="发送任务失败",
                after_ok=_show_queue_notification,
            )
        )

    def _start_save_drafts(self, tasks: list[MailTask]) -> None:
        if not self._package_dir:
            return
        if self._delivery_is_busy(title="请稍候", message="当前已有发送/草稿任务在执行，请稍候。"):
            return
        if not tasks:
            QtWidgets.QMessageBox.information(self, "没有可保存任务", "请先选择或准备好可保存的任务。")
            return

        submitted_tasks = list(tasks)
        submitted_package_dir = self._package_dir
        self._runtime.mark_drafting(submitted_tasks)
        self._refresh_task_table()
        self._refresh_ui_state()

        worker = SaveDraftsWorker(DraftWorkerConfig(
            tasks=submitted_tasks,
            package_dir=submitted_package_dir,
            home_dir=self._home_dir,
            imap_username=self._smtp_cfg.username.strip(),
            imap_password=self._smtp_password,
            imap_host=self._imap_host,
            imap_port=self._imap_port,
        ))
        self._start_delivery_worker(
            spec=DeliveryWorkerSpec(
                worker=worker,
                worker_attr="_draft_worker",
                apply_result=lambda result: self._apply_draft_result(
                    submitted_tasks,
                    submitted_package_dir,
                    result,
                ),
                mark_error=lambda error_text: self._mark_draft_worker_error(
                    submitted_tasks,
                    submitted_package_dir,
                    error_text,
                ),
                error_title="保存草稿失败",
                error_prefix="保存草稿失败",
            )
        )

    def _delivery_result_matches_current_tasks(self, tasks: list[MailTask], package_dir: Path) -> bool:
        if self._package_dir is None or self._package_dir.resolve() != package_dir.resolve():
            return False
        current_task_objects = {id(task) for task in self._tasks}
        return all(id(task) in current_task_objects for task in tasks)

    def _send_result_counts(self, result: SendTasksResult) -> tuple[int, int]:
        sent_count = sum(1 for outcome in result.outcomes if outcome.status is DeliveryStatus.SENT)
        return sent_count, len(result.outcomes) - sent_count

    def _draft_result_counts(self, result: SendTasksResult) -> tuple[int, int]:
        ok_count = sum(1 for outcome in result.outcomes if outcome.status is DeliveryStatus.DRAFT_SAVED)
        return ok_count, len(result.outcomes) - ok_count

    @staticmethod
    def _result_skipped_count(result: SendTasksResult) -> int:
        return sum(1 for outcome in result.outcomes if outcome.status.is_skipped)

    @staticmethod
    def _skipped_note(skipped_count: int) -> str:
        if skipped_count <= 0:
            return ""
        return f"\n其中因连接中断未尝试：{skipped_count}（已计入失败，可重试）"

    def _mark_send_worker_error(self, tasks: list[MailTask], package_dir: Path, error_text: str) -> None:
        if self._delivery_result_matches_current_tasks(tasks, package_dir):
            self._runtime.mark_send_worker_error(tasks, error_text)

    def _mark_draft_worker_error(self, tasks: list[MailTask], package_dir: Path, error_text: str) -> None:
        if self._delivery_result_matches_current_tasks(tasks, package_dir):
            self._runtime.mark_draft_worker_error(tasks, error_text)

    def _apply_send_result(self, tasks: list[MailTask], package_dir: Path, result: SendTasksResult) -> None:
        self._last_run_dir = result.run_paths.run_dir
        if self._delivery_result_matches_current_tasks(tasks, package_dir):
            sent_count, failed_count = self._runtime.apply_send_result(tasks, result)
        else:
            sent_count, failed_count = self._send_result_counts(result)
        # 回写发送状态到 tasks.xlsx，防止崩溃后重复发送
        self._persist_delivery_status(tasks, result, package_dir)
        self._refresh_task_table()
        self._refresh_ui_state()
        details = self._format_failure_details(result)
        QtWidgets.QMessageBox.information(
            self,
            "发送完成",
            f"本次输出目录：{result.run_paths.run_dir}\n发送成功：{sent_count}\n发送失败：{failed_count}"
            f"{self._skipped_note(self._result_skipped_count(result))}"
            f"{details}",
        )

    def _apply_draft_result(self, tasks: list[MailTask], package_dir: Path, result: SendTasksResult) -> None:
        self._last_run_dir = result.run_paths.run_dir
        if self._delivery_result_matches_current_tasks(tasks, package_dir):
            ok_count, fail_count = self._runtime.apply_draft_result(tasks, result)
        else:
            ok_count, fail_count = self._draft_result_counts(result)
        # 回写草稿状态到 tasks.xlsx
        self._persist_delivery_status(tasks, result, package_dir)
        self._refresh_task_table()
        self._refresh_ui_state()
        details = self._format_failure_details(result)
        QtWidgets.QMessageBox.information(
            self,
            "保存草稿完成",
            f"本次输出目录：{result.run_paths.run_dir}\n草稿保存成功：{ok_count}\n草稿保存失败：{fail_count}"
            f"{self._skipped_note(self._result_skipped_count(result))}"
            f"{details}",
        )

    def _persist_delivery_status(self, tasks: list[MailTask], result: SendTasksResult, package_dir: Path) -> None:
        """将发送/草稿结果回写到 tasks.xlsx 的 '最近结果' 列。"""
        outcome_map = {outcome.task_id: outcome for outcome in result.outcomes}
        changed = False
        for task in self._tasks:
            outcome = outcome_map.get(task.task_id)
            if outcome is not None:
                new_status = outcome.status.value
                if task.last_delivery_status != new_status:
                    task.last_delivery_status = new_status
                    changed = True
        if changed and package_dir and package_dir.is_dir():
            try:
                save_tasks_to_package(package_dir, self._tasks)
            except Exception:
                pass  # 回写失败不阻断用户流程，下次发送仍可正常进行

    @staticmethod
    def _format_failure_details(result: SendTasksResult) -> str:
        failures = [
            outcome for outcome in result.outcomes
            if not outcome.status.is_success and not outcome.status.is_skipped
        ]
        if not failures:
            return ""
        lines = ["\n\n失败详情："]
        for outcome in failures[:10]:
            error_text = (outcome.error or "未知错误")[:80]
            lines.append(f"  - {outcome.subject or outcome.task_id}：{error_text}")
        if len(failures) > 10:
            lines.append(f"  ...还有 {len(failures) - 10} 条")
        return "\n".join(lines)

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
        failed = [
            task for task in self._tasks
            if self._runtime.status_for(task) == TaskStatus.SEND_FAILED and task.enabled
        ]
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
