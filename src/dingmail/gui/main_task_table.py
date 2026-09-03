from __future__ import annotations

from ..task_status import TaskStatus
from .main_support import UiActionState


class MainTaskTableMixin:
    def _refresh_task_table(
        self,
        *,
        max_validate: int = 0,
        update_detail: bool = True,
    ) -> bool:
        """刷新任务表；返回 True 表示所有任务校验缓存均已就绪。

        max_validate>0 时本轮最多校验 N 个未缓存任务（增量模式）；
        update_detail=False 供增量校验 tick 跳过详情面板的重渲染。
        行展示由 TaskTableModel.data() 按需提供，refresh() 只发 dataChanged。
        """
        all_validated = self._runtime.refresh_runtime_state(self._tasks, max_validate=max_validate)
        self._task_model.refresh()
        if update_detail:
            self._refresh_detail_panel()
        self._refresh_metrics()
        return all_validated

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
