"""任务控制器：任务包 IO、投递结果应用与回写守卫。

runtime 状态机（校验/队列/发送中/终态）全部委托 TaskRuntimeController，
本类只负责任务包文件 IO、结果应用编排与 tasks.xlsx 回写守卫。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6 import QtCore

from ...task_delivery import DeliveryStatus, SendTasksResult
from ...task_models import MailTask
from ...task_package import (
    ensure_unique_task_ids,
    load_tasks_from_package,
    save_tasks_to_package,
)
from ..task_runtime import TaskRuntimeController


class TaskController(QtCore.QObject):
    tasksChanged = QtCore.Signal()             # 任务列表或状态整体变化
    noticeRaised = QtCore.Signal(str, str)     # (message, severity: info|warning|danger)
    statusWritebackFailed = QtCore.Signal(str)

    def __init__(self, home_dir: Path, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self.home_dir = home_dir
        self.package_dir: Path | None = None
        self.tasks: list[MailTask] = []
        self.runtime = TaskRuntimeController()

    # ---- 任务包 ----

    def load_package(self, package_dir: Path, *, silent: bool = False) -> bool:
        """加载任务包；修复 ID 后写回。返回是否成功。"""
        tasks = load_tasks_from_package(package_dir)
        repairs = ensure_unique_task_ids(tasks)
        if repairs:
            try:
                save_tasks_to_package(package_dir, tasks)
            except Exception as exc:
                if not silent:
                    self.noticeRaised.emit(
                        "任务ID已在内存中修复，但写回 tasks.xlsx 失败：" + str(exc),
                        "danger",
                    )
        self.package_dir = package_dir
        self.tasks = tasks
        self.runtime.reset_loaded_tasks(package_dir, self.tasks)
        self.tasksChanged.emit()
        if repairs:
            if silent:
                self.noticeRaised.emit("已恢复任务包；缺失/重复的任务ID已自动修复。", "info")
            else:
                self.noticeRaised.emit(
                    "任务表中的重复/缺失任务ID已自动修复并写回 tasks.xlsx：\n" + "\n".join(repairs[:10]),
                    "warning",
                )
        return True

    def persist_tasks(
        self,
        updated_tasks: list[MailTask],
        *,
        reset_runtime_task_ids: tuple[str, ...] = (),
    ) -> bool:
        if self.package_dir is None:
            self.noticeRaised.emit("请先导入或创建任务包。", "warning")
            return False
        try:
            save_tasks_to_package(self.package_dir, updated_tasks)
        except Exception as exc:
            self.noticeRaised.emit(
                f"写入 tasks.xlsx 失败：{exc}\n如果 Excel 正在打开，请先关闭 Excel 后重试。",
                "danger",
            )
            return False
        self.tasks = updated_tasks
        reset_ids = set(reset_runtime_task_ids)
        for task in self.tasks:
            if task.task_id in reset_ids:
                self.runtime.reset_runtime_fields(task)
        self.runtime.invalidate_validation_cache()
        self.runtime.sync_task_ids(self.tasks)
        self.tasksChanged.emit()
        return True

    # ---- 投递结果应用（委托 runtime 状态机） ----

    def _counts(self, result: SendTasksResult, ok_status: DeliveryStatus) -> tuple[int, int]:
        ok = sum(1 for outcome in result.outcomes if outcome.status is ok_status)
        return ok, len(result.outcomes) - ok

    def apply_send_result(
        self,
        submitted_tasks: list[MailTask],
        package_dir: Path,
        result: SendTasksResult,
    ) -> tuple[int, int]:
        if self._result_matches_current(submitted_tasks, package_dir):
            sent, failed = self.runtime.apply_send_result(submitted_tasks, result)
        else:
            sent, failed = self._counts(result, DeliveryStatus.SENT)
        self._persist_delivery_status(submitted_tasks, package_dir, result)
        self.tasksChanged.emit()
        return sent, failed

    def apply_draft_result(
        self,
        submitted_tasks: list[MailTask],
        package_dir: Path,
        result: SendTasksResult,
    ) -> tuple[int, int]:
        if self._result_matches_current(submitted_tasks, package_dir):
            ok, failed = self.runtime.apply_draft_result(submitted_tasks, result)
        else:
            ok, failed = self._counts(result, DeliveryStatus.DRAFT_SAVED)
        self._persist_delivery_status(submitted_tasks, package_dir, result)
        self.tasksChanged.emit()
        return ok, failed

    def mark_sending(self, tasks: list[MailTask]) -> None:
        self.runtime.mark_sending(tasks)
        self.tasksChanged.emit()

    def mark_drafting(self, tasks: list[MailTask]) -> None:
        self.runtime.mark_drafting(tasks)
        self.tasksChanged.emit()

    def mark_send_worker_error(self, tasks: list[MailTask], package_dir: Path, error_text: str) -> None:
        if self._result_matches_current(tasks, package_dir):
            self.runtime.mark_send_worker_error(tasks, error_text)
            self.tasksChanged.emit()

    def mark_draft_worker_error(self, tasks: list[MailTask], package_dir: Path, error_text: str) -> None:
        if self._result_matches_current(tasks, package_dir):
            self.runtime.mark_draft_worker_error(tasks, error_text)
            self.tasksChanged.emit()

    # ---- 定时调度 ----

    def due_tasks(self, now: datetime | None = None) -> list[MailTask]:
        return self.runtime.collect_due_tasks(self.tasks, now=now or datetime.now())

    # ---- 内部 ----

    def _result_matches_current(self, tasks: list[MailTask], package_dir: Path) -> bool:
        if self.package_dir is None or self.package_dir.resolve() != package_dir.resolve():
            return False
        current_ids = {id(task) for task in self.tasks}
        return all(id(task) in current_ids for task in tasks)

    def _persist_delivery_status(self, tasks: list[MailTask], package_dir: Path, result: SendTasksResult) -> None:
        if not self._result_matches_current(tasks, package_dir):
            # 中途已切换任务包：结果属于旧包任务，绝不能把当前任务列表写进旧包目录
            return
        outcome_map = {outcome.task_id: outcome for outcome in result.outcomes}
        changed = False
        for task in self.tasks:
            outcome = outcome_map.get(task.task_id)
            if outcome is not None and task.last_delivery_status != outcome.status.value:
                task.last_delivery_status = outcome.status.value
                changed = True
        if changed and package_dir and package_dir.is_dir():
            try:
                save_tasks_to_package(package_dir, self.tasks)
            except Exception as exc:
                # 回写失败不阻断流程，但必须可见——它是"防崩溃后重复发送"的保障
                self.statusWritebackFailed.emit(str(exc))
