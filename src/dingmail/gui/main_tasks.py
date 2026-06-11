from __future__ import annotations

import copy
import uuid
from datetime import datetime
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from ..paths import packages_dir, program_dir, runs_dir
from ..task_clone import clone_task
from ..task_models import MailTask
from ..task_package import (
    PACKAGE_README_FILENAME,
    TASKS_FILENAME,
    ensure_unique_task_ids,
    load_tasks_from_package,
    save_tasks_to_package,
)
from ..task_template import create_template_package
from ..task_status import TaskStatus
from .dialogs import MarkdownPreviewDialog, PreviewDialog, RunHistoryDialog, TaskEditorDialog
from .main_support import STATUS_ROW_COLORS, UiActionState, now_stamp
from .theme import status_tone


class MainTaskMixin:
    def _package_root(self) -> Path:
        return packages_dir(self._home_dir)

    def _ensure_within_home(self, package_dir: Path) -> None:
        home = self._home_dir.resolve()
        current = package_dir.resolve()
        if home not in current.parents and current != home:
            raise ValueError(f"任务包目录必须位于 {home} 下。请先把任务包放进 `packages` 目录。")

    def _download_template_package(self) -> None:
        if self._delivery_is_busy(title="请稍候", message="当前正在发送或保存草稿，请完成后再创建任务包。"):
            return
        name, ok = QtWidgets.QInputDialog.getText(
            self,
            "下载任务包模板",
            "任务包目录名（会创建在 packages 目录下）",
            text=f"任务包_{now_stamp()}",
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            return

        package_dir = (self._package_root() / name).resolve()
        if package_dir.exists() and any(package_dir.iterdir()):
            QtWidgets.QMessageBox.warning(self, "目录已存在", f"目录已存在且非空：{package_dir}")
            return

        create_template_package(package_dir)
        self._load_package(package_dir)
        QtWidgets.QMessageBox.information(
            self,
            "模板已创建",
            f"已创建任务包：{package_dir}\n你可以先打开 tasks.xlsx 直接改，也可以双击表格内任务逐条调整。",
        )

    def _import_package(self) -> None:
        if self._delivery_is_busy(title="请稍候", message="当前正在发送或保存草稿，请完成后再导入任务包。"):
            return
        selected = QtWidgets.QFileDialog.getExistingDirectory(self, "选择任务包目录", str(self._package_root()))
        if not selected:
            return

        package_dir = Path(selected).resolve()
        try:
            self._ensure_within_home(package_dir)
            self._load_package(package_dir)
        except Exception as exc:
            self._show_error_dialog("导入失败", f"导入任务包失败：{exc}")

    def _reload_package(self) -> None:
        if self._delivery_is_busy(title="请稍候", message="当前正在发送或保存草稿，请完成后再重新加载任务包。"):
            return
        if not self._package_dir:
            QtWidgets.QMessageBox.information(self, "未导入", "请先导入任务包目录。")
            return
        try:
            self._load_package(self._package_dir)
        except Exception as exc:
            self._show_error_dialog("重新加载失败", f"重新加载任务包失败：{exc}")

    def _load_package(self, package_dir: Path) -> None:
        tasks = load_tasks_from_package(package_dir)
        repairs = ensure_unique_task_ids(tasks)
        repair_notice = ""
        if repairs:
            try:
                save_tasks_to_package(package_dir, tasks)
                repair_notice = "\n".join(repairs[:10]) + "\n\n任务表中的重复/缺失任务ID已自动修复并写回 tasks.xlsx。"
            except Exception as exc:
                repair_notice = "\n".join(repairs[:10]) + f"\n\n任务ID已在内存中修复，但写回 tasks.xlsx 失败：{exc}"
        self._package_dir = package_dir
        self._tasks = tasks
        self._runtime.reset_loaded_tasks(package_dir, self._tasks)
        self._refresh_task_table()
        self._refresh_ui_state()
        if repair_notice:
            QtWidgets.QMessageBox.warning(self, "任务ID已自动修复", repair_notice)

    def _open_path(self, path: Path) -> None:
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))

    def _open_package_dir(self) -> None:
        if self._package_dir:
            self._open_path(self._package_dir)

    def _open_tasks_excel(self) -> None:
        if self._package_dir:
            path = self._package_dir / TASKS_FILENAME
            if path.exists():
                self._open_path(path)

    def _show_readme_preview(self) -> None:
        candidates: list[Path] = []
        if self._package_dir:
            candidates.append(self._package_dir / PACKAGE_README_FILENAME)
        candidates.extend(
            [
                program_dir() / "操作说明_GUI版.md",
                Path.cwd() / "操作说明_GUI版.md",
            ]
        )
        readme_path = next((path for path in candidates if path.exists()), None)
        if readme_path is None:
            QtWidgets.QMessageBox.warning(self, "未找到操作说明", "当前任务包和程序目录下都没有找到操作说明文件。")
            return
        dialog = MarkdownPreviewDialog(title="操作说明", path=readme_path, parent=self)
        dialog.exec()

    def _show_run_history(self) -> None:
        dialog = RunHistoryDialog(runs_root=runs_dir(self._home_dir), parent=self)
        dialog.exec()

    def _persist_tasks(self, *, updated_tasks: list[MailTask]) -> bool:
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
        self._runtime.invalidate_validation_cache()
        self._runtime.sync_task_ids(self._tasks)
        self._refresh_task_table()
        self._refresh_ui_state()
        return True

    def _selected_rows(self) -> list[int]:
        rows = self._task_table.selectionModel().selectedRows() if self._task_table.selectionModel() else []
        return sorted({row.row() for row in rows})

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
        self._runtime.reset_runtime_fields(new_task)
        updated = copy.deepcopy(self._tasks)
        updated.append(new_task)
        if self._persist_tasks(updated_tasks=updated):
            self._task_table.selectRow(len(updated) - 1)

    def _edit_selected_task(self) -> None:
        # 表格双击也会进入这里，按钮禁用挡不住，必须显式拦截：
        # 运行中改写 self._tasks 会让投递结果按对象身份匹配失败，状态永久卡在“发送中/草稿保存中”。
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
        self._runtime.reset_runtime_fields(updated_task)
        updated = copy.deepcopy(self._tasks)
        updated[row] = updated_task
        if self._persist_tasks(updated_tasks=updated):
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
        clones = []
        for row in rows:
            cloned = clone_task(updated[row])
            self._runtime.reset_runtime_fields(cloned)
            clones.append(cloned)
        for offset, task in enumerate(clones):
            updated.insert(insert_at + offset, task)
        self._persist_tasks(updated_tasks=updated)

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
        updated = [task for idx, task in enumerate(self._tasks) if idx not in set(rows)]
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
