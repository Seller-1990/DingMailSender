from __future__ import annotations

import copy
import uuid
from datetime import datetime

from PySide6 import QtWidgets

from ..task_clone import clone_task
from ..task_models import MailTask
from ..task_package import save_tasks_to_package
from .dialogs import PreviewDialog, TaskEditorDialog


class MainTaskCommandMixin:
    def _persist_tasks(
        self,
        *,
        updated_tasks: list[MailTask],
        reset_runtime_task_ids: tuple[str, ...] = (),
    ) -> bool:
        if not self._package_dir:
            QtWidgets.QMessageBox.warning(self, "未导入任务包", "请先导入或创建任务包。")
            return False
        try:
            save_tasks_to_package(self._package_dir, updated_tasks)
        except Exception as exc:
            self._show_error_dialog(
                "保存失败",
                f"写入 tasks.xlsx 失败：{exc}\n如果 Excel 正在打开，请先关闭 Excel 后重试。",
            )
            return False

        self._tasks = updated_tasks
        self._task_model.set_data_source(self._tasks, self._runtime)
        reset_ids = set(reset_runtime_task_ids)
        for task in self._tasks:
            if task.task_id in reset_ids:
                self._runtime.reset_runtime_fields(task)
        self._runtime.invalidate_validation_cache()
        self._runtime.sync_task_ids(self._tasks)
        self._refresh_task_table()
        self._refresh_ui_state()
        self._start_incremental_validation()
        return True

    def _selected_rows(self) -> list[int]:
        selection_model = self._task_table.selectionModel()
        rows = selection_model.selectedRows() if selection_model else []
        return sorted(
            {
                self._task_proxy.mapToSource(index).row()
                for index in rows
                if index.isValid()
            }
        )

    def _selected_tasks(self) -> list[MailTask]:
        return [self._tasks[i] for i in self._selected_rows() if 0 <= i < len(self._tasks)]

    def _require_package(self) -> bool:
        if self._package_dir is None:
            QtWidgets.QMessageBox.information(self, "未导入任务包", "请先下载或导入任务包。")
            return False
        return True

    def _require_single_task(self) -> int | None:
        rows = self._selected_rows()
        if len(rows) != 1:
            QtWidgets.QMessageBox.information(self, "请选择一行", "请先选中一条任务。")
            return None
        return rows[0]

    def _add_task(self) -> None:
        if self._delivery_is_busy(title="请稍候", message="当前正在发送或保存草稿，请完成后再编辑任务。"):
            return
        if not self._require_package():
            return
        task = MailTask(task_id=uuid.uuid4().hex, enabled=True)
        dialog = TaskEditorDialog(task=task, package_dir=self._package_dir, parent=self)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        new_task = dialog.task()
        updated = copy.deepcopy(self._tasks)
        updated.append(new_task)
        if self._persist_tasks(updated_tasks=updated, reset_runtime_task_ids=(new_task.task_id,)):
            self._task_table.selectRow(len(updated) - 1)

    def _edit_selected_task(self) -> None:
        # 表格双击也会进入这里；运行中改写任务会让投递结果无法匹配当前对象。
        if self._delivery_is_busy(title="请稍候", message="当前正在发送或保存草稿，请完成后再编辑任务。"):
            return
        if not self._require_package():
            return
        row = self._require_single_task()
        if row is None:
            return
        dialog = TaskEditorDialog(task=copy.deepcopy(self._tasks[row]), package_dir=self._package_dir, parent=self)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        updated_task = dialog.task()
        updated = copy.deepcopy(self._tasks)
        updated[row] = updated_task
        if self._persist_tasks(updated_tasks=updated, reset_runtime_task_ids=(updated_task.task_id,)):
            self._task_table.selectRow(row)

    def _duplicate_selected_tasks(self) -> None:
        if self._delivery_is_busy(title="请稍候", message="当前正在发送或保存草稿，请完成后再编辑任务。"):
            return
        if not self._require_package():
            return
        rows = self._selected_rows()
        if not rows:
            QtWidgets.QMessageBox.information(self, "未选择任务", "请先选择至少一条任务。")
            return
        updated = copy.deepcopy(self._tasks)
        insert_at = rows[-1] + 1
        clones = [clone_task(updated[row]) for row in rows]
        for offset, task in enumerate(clones):
            updated.insert(insert_at + offset, task)
        self._persist_tasks(
            updated_tasks=updated,
            reset_runtime_task_ids=tuple(task.task_id for task in clones),
        )

    def _delete_selected_tasks(self) -> None:
        if self._delivery_is_busy(title="请稍候", message="当前正在发送或保存草稿，请完成后再编辑任务。"):
            return
        if not self._require_package():
            return
        rows = self._selected_rows()
        if not rows:
            QtWidgets.QMessageBox.information(self, "未选择任务", "请先选择至少一条任务。")
            return
        reply = QtWidgets.QMessageBox.question(
            self,
            "确认删除",
            f"确认删除选中的 {len(rows)} 条任务吗？这会同步写回 tasks.xlsx。",
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        selected_rows = set(rows)
        updated = [task for idx, task in enumerate(self._tasks) if idx not in selected_rows]
        self._persist_tasks(updated_tasks=updated)

    def _preview_selected_task(self) -> None:
        if not self._require_package():
            return
        row = self._require_single_task()
        if row is None:
            return
        dialog = PreviewDialog(tasks=self._tasks, start_index=row, package_dir=self._package_dir, parent=self)
        dialog.exec()
        self._runtime.mark_previewed(self._tasks[row], datetime.now().replace(microsecond=0))
        self._refresh_task_table()
        self._refresh_ui_state()
