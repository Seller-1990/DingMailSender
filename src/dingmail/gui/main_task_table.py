from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from ..task_models import MailTask
from ..task_status import TaskStatus
from .main_support import STATUS_ROW_COLORS, UiActionState
from .theme import status_tone


class MainTaskTableMixin:
    def _task_table_values(self, task: MailTask) -> list[str]:
        attachment_count = task.attachment_count()
        state = self._runtime.state_for(task)
        issue_text = state.error_message or state.last_result or task.note
        schedule_text = task.scheduled_at.strftime("%Y-%m-%d %H:%M:%S") if task.scheduled_at else ""
        markdown_display = Path(task.markdown_path).name if task.markdown_path else "未填写"
        return [
            state.status.label,
            "; ".join(task.to_recipients),
            task.subject,
            markdown_display,
            f"{attachment_count} 个附件" if attachment_count else "无",
            "是" if task.schedule_enabled else "否",
            schedule_text,
            issue_text,
        ]

    def _task_tooltip(self, task: MailTask) -> str:
        state = self._runtime.state_for(task)
        return "\n".join(
            x
            for x in [
                f"任务ID：{task.task_id}",
                f"启用：{'是' if task.enabled else '否'}",
                f"抄送人：{'; '.join(task.cc_recipients)}" if task.cc_recipients else "",
                f"开头/补充内容：{task.intro_text}" if task.intro_text else "",
                f"Markdown：{task.markdown_path}" if task.markdown_path else "",
                f"附件：{'; '.join(task.attachment_paths)}" if task.attachment_paths else "",
                f"备注：{task.note}" if task.note else "",
                f"最近结果：{state.last_result}" if state.last_result else "",
                f"说明：{state.error_message}" if state.error_message else "",
            ]
            if x
        )

    def _set_task_table_item(self, row: int, col: int, value: str, tooltip: str, row_color: QtGui.QColor) -> None:
        item = self._task_table.item(row, col)
        if item is None:
            item = QtWidgets.QTableWidgetItem()
            self._task_table.setItem(row, col, item)
        item.setText(value)
        item.setToolTip(tooltip)
        alignment = QtCore.Qt.AlignCenter if col in (0, 4, 5) else QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter
        item.setTextAlignment(alignment)
        if col == 0:
            item.setBackground(row_color)
            item.setForeground(QtGui.QColor("#172033"))
            font = item.font()
            font.setBold(True)
            item.setFont(font)
        else:
            item.setBackground(QtGui.QBrush())

    def _refresh_task_table_row(self, row: int, task: MailTask) -> None:
        tone = status_tone(self._runtime.status_for(task))
        row_color = QtGui.QColor(STATUS_ROW_COLORS.get(tone, STATUS_ROW_COLORS["neutral"]))
        tooltip = self._task_tooltip(task)
        for col, value in enumerate(self._task_table_values(task)):
            self._set_task_table_item(row, col, value, tooltip, row_color)
        self._task_table.setRowHidden(
            row,
            not (self._task_matches_filter(task) and self._task_matches_search(task)),
        )

    def _refresh_task_table(self) -> None:
        self._runtime.refresh_runtime_state(self._tasks)
        self._task_table.setUpdatesEnabled(False)
        self._task_table.setRowCount(len(self._tasks))
        try:
            for row, task in enumerate(self._tasks):
                self._refresh_task_table_row(row, task)
        finally:
            self._task_table.setUpdatesEnabled(True)
        self._resize_task_columns()
        self._task_table.resizeRowsToContents()
        self._refresh_detail_panel()
        self._refresh_metrics()

    def _refresh_package_action_buttons(self, has_package: bool) -> None:
        is_busy = self._send_worker is not None or self._draft_worker is not None
        self._download_package_btn.setEnabled(not is_busy)
        self._import_package_btn.setEnabled(not is_busy)
        self._reload_package_btn.setEnabled(has_package and not is_busy)
        self._open_package_btn.setEnabled(has_package)
        self._open_tasks_btn.setEnabled(has_package)
        self._open_readme_btn.setEnabled(has_package)

    def _refresh_task_action_buttons(self, state: UiActionState) -> None:
        self._add_btn.setEnabled(state.can_edit)
        self._edit_btn.setEnabled(state.can_edit and state.has_single)
        self._copy_btn.setEnabled(state.can_edit and state.has_selection)
        self._delete_btn.setEnabled(state.can_edit and state.has_selection)
        self._preview_btn.setEnabled(state.has_package and state.has_single)
        self._save_drafts_btn.setEnabled(state.can_send and state.has_selection)
        self._send_now_btn.setEnabled(state.can_send and state.has_selection)
        self._queue_btn.setEnabled(state.can_send and state.has_selection)
        self._retry_btn.setEnabled(
            state.can_send and any(self._runtime.status_for(task) == TaskStatus.SEND_FAILED for task in self._tasks)
        )
        self._open_last_run_btn.setEnabled(True)

    def _refresh_package_summary(self) -> None:
        if self._package_dir:
            self._package_label.setText(
                f"任务包：{self._package_dir.name}\n目录：{self._package_dir}\n工作目录：{self._home_dir}"
            )
        else:
            self._package_label.setText(
                f"任务包：未导入\n工作目录：{self._home_dir}\n模板目录：{self._package_root()}"
            )

    def _refresh_status_line(self, selected_count: int, has_selection: bool) -> None:
        enabled_tasks = [task for task in self._tasks if task.enabled]
        ready = sum(1 for task in self._tasks if self._runtime.status_for(task) == TaskStatus.READY)
        queued = len(self._runtime.queued_task_ids)
        failed = sum(1 for task in self._tasks if self._runtime.status_for(task) == TaskStatus.SEND_FAILED)
        issues = sum(1 for task in self._tasks if self._runtime.status_for(task) == TaskStatus.VALIDATION_FAILED)
        drafts = sum(1 for task in self._tasks if self._runtime.status_for(task) == TaskStatus.DRAFT_SAVED)
        selected_desc = f"当前选中：{selected_count} 条" if has_selection else "当前未选中任务"
        last_run = str(self._last_run_dir) if self._last_run_dir else "暂无"
        package_name = self._package_dir.name if self._package_dir else "未导入"
        smtp_desc = "已连接" if self._smtp_connected else "未连接"
        self._status_label.setText(
            f"任务包：{package_name} | SMTP：{smtp_desc} | 启用：{len(enabled_tasks)} | "
            f"可保存草稿：{ready} | 需修正：{issues} | 已保存草稿：{drafts} | "
            f"定时队列：{queued} | 发送失败：{failed}\n{selected_desc} | 最近输出：{last_run}"
        )

    def _refresh_ui_state(self) -> None:
        selected_count = len(self._selected_rows())
        has_package = self._package_dir is not None
        has_selection = selected_count > 0
        is_busy = self._send_worker is not None or self._draft_worker is not None
        can_send = has_package and self._smtp_connected and not is_busy
        can_edit = has_package and not is_busy

        self._refresh_package_action_buttons(has_package)
        self._refresh_task_action_buttons(
            UiActionState(
                has_package=has_package,
                has_selection=has_selection,
                has_single=selected_count == 1,
                can_send=can_send,
                can_edit=can_edit,
            )
        )
        self._refresh_package_summary()
        self._refresh_status_line(selected_count, has_selection)
        self._refresh_metrics()
