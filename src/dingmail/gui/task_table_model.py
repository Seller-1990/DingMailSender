from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui

from ..task_models import MailTask
from ..task_status import TaskStatus
from .task_runtime import TaskRuntimeController
from .theme import STATUS_ROW_COLORS, status_tone


class TaskTableModel(QtCore.QAbstractTableModel):
    """tasks 列表的只读表格模型。

    data() 按需从 MailTask 与 TaskRuntimeController 取值；刷新时只 emit
    dataChanged，无需逐格重建 QTableWidgetItem，也无需重算行高。
    """

    HEADERS = ["状态", "收件人", "主题", "正文", "附件", "定时", "发送时间", "说明"]
    CENTERED_COLUMNS = {0, 4, 5}
    STATUS_FOREGROUND = "#172033"

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._tasks: list[MailTask] = []
        self._runtime: TaskRuntimeController | None = None
        self._snapshots: dict[str, tuple] = {}
        self._status_font = QtGui.QFont()
        self._status_font.setBold(True)
        self._status_foreground = QtGui.QColor(self.STATUS_FOREGROUND)
        self._row_colors = {tone: QtGui.QColor(color) for tone, color in STATUS_ROW_COLORS.items()}

    # ---- 数据源 ----

    def set_data_source(self, tasks: list[MailTask], runtime: TaskRuntimeController) -> None:
        self.beginResetModel()
        self._tasks = tasks
        self._runtime = runtime
        self._snapshots.clear()
        self.endResetModel()

    def bound_to(self, tasks: list[MailTask]) -> bool:
        """当前数据源是否就是该列表对象（避免同列表反复 reset 丢失选择）。"""
        return self._tasks is tasks

    def task_at(self, row: int) -> MailTask:
        return self._tasks[row]

    @property
    def runtime(self) -> TaskRuntimeController | None:
        return self._runtime

    def refresh(self) -> bool:
        """任务状态/文本变化后通知视图重绘。返回是否有行发生变化。

        只有快照发生变化的行才发 dataChanged：无谓的 dataChanged 会让代理
        模型重排并在某些场景清空用户选择。调用方需在发生变化后让代理模型
        重刷过滤（dataChanged 不会让代理插入新匹配的行）。
        """
        if self._runtime is None or not self._tasks:
            return False
        changed_rows: list[int] = []
        for row, task in enumerate(self._tasks):
            state = self._runtime.state_for(task)
            key = (state.status, state.error_message, state.last_result, task.subject, task.last_delivery_status)
            if self._snapshots.get(task.task_id) != key:
                self._snapshots[task.task_id] = key
                changed_rows.append(row)
        live_ids = {task.task_id for task in self._tasks}
        for stale_id in list(self._snapshots):
            if stale_id not in live_ids:
                del self._snapshots[stale_id]
        for row in changed_rows:
            self.dataChanged.emit(self.index(row, 0), self.index(row, len(self.HEADERS) - 1))
        return bool(changed_rows)

    # ---- QAbstractTableModel ----

    def rowCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._tasks)

    def columnCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:  # noqa: N802
        return len(self.HEADERS)

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: QtCore.Qt.Orientation,
        role: int = QtCore.Qt.DisplayRole,
    ):
        if orientation == QtCore.Qt.Horizontal and role == QtCore.Qt.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index: QtCore.QModelIndex, role: int = QtCore.Qt.DisplayRole):  # noqa: N802
        if not index.isValid() or self._runtime is None:
            return None
        task = self._tasks[index.row()]
        col = index.column()
        if role == QtCore.Qt.DisplayRole:
            return self._display_text(task, col)
        if role == QtCore.Qt.ToolTipRole:
            return self._tooltip(task)
        if role == QtCore.Qt.TextAlignmentRole:
            alignment = QtCore.Qt.AlignCenter if col in self.CENTERED_COLUMNS else QtCore.Qt.AlignLeft
            return alignment | QtCore.Qt.AlignVCenter
        if col == 0:
            if role == QtCore.Qt.BackgroundRole:
                return self._row_colors.get(status_tone(self._runtime.status_for(task)))
            if role == QtCore.Qt.ForegroundRole:
                return self._status_foreground
            if role == QtCore.Qt.FontRole:
                return self._status_font
        return None

    # ---- 展示文本 ----

    def _display_text(self, task: MailTask, col: int) -> str:
        state = self._runtime.state_for(task)
        if col == 0:
            return state.status.label
        if col == 1:
            return "; ".join(task.to_recipients)
        if col == 2:
            return task.subject
        if col == 3:
            return Path(task.markdown_path).name if task.markdown_path else "未填写"
        if col == 4:
            attachment_count = task.attachment_count()
            return f"{attachment_count} 个附件" if attachment_count else "无"
        if col == 5:
            return "是" if task.schedule_enabled else "否"
        if col == 6:
            return task.scheduled_at.strftime("%Y-%m-%d %H:%M:%S") if task.scheduled_at else ""
        return state.error_message or state.last_result or task.note

    def _tooltip(self, task: MailTask) -> str:
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


class TaskFilterProxyModel(QtCore.QSortFilterProxyModel):
    """按状态筛选 + 搜索文本过滤任务行（替代 setRowHidden 手动过滤）。"""

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._filter_key = "all"
        self._search_text = ""

    def set_filter_key(self, key: str) -> None:
        if key != self._filter_key:
            self._filter_key = key
            self._refilter()

    def set_search_text(self, text: str) -> None:
        normalized = str(text or "").strip().lower()
        if normalized != self._search_text:
            self._search_text = normalized
            self._refilter()

    def refilter(self) -> None:
        """校验状态批量变化后重刷过滤（dataChanged 不会插入新匹配的行）。"""
        self._refilter()

    def _refilter(self) -> None:
        # Qt 6.10 起 invalidateFilter/invalidateRowsFilter 均弃用，改用 begin/endFilterChange
        if hasattr(self, "beginFilterChange") and hasattr(self, "endFilterChange"):
            self.beginFilterChange()
            self.endFilterChange()
        else:
            self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QtCore.QModelIndex) -> bool:  # noqa: N802
        source = self.sourceModel()
        if not isinstance(source, TaskTableModel) or source.runtime is None:
            return True
        task = source.task_at(source_row)
        runtime = source.runtime
        return self._matches_filter(task, runtime) and self._matches_search(task, runtime)

    def _matches_filter(self, task: MailTask, runtime: TaskRuntimeController) -> bool:
        status = runtime.status_for(task)
        if self._filter_key == "all":
            return True
        if self._filter_key == "ready":
            return status == TaskStatus.READY
        if self._filter_key == "issue":
            return status == TaskStatus.VALIDATION_FAILED
        if self._filter_key == "draft":
            return status == TaskStatus.DRAFT_SAVED
        if self._filter_key == "queued":
            return status == TaskStatus.QUEUED
        if self._filter_key == "failed":
            return status in {TaskStatus.SEND_FAILED, TaskStatus.DRAFT_FAILED}
        return True

    def _matches_search(self, task: MailTask, runtime: TaskRuntimeController) -> bool:
        if not self._search_text:
            return True
        haystack = " ".join(
            [
                "; ".join(task.to_recipients),
                "; ".join(task.cc_recipients),
                task.subject,
                task.markdown_path,
                task.note,
                runtime.error_for(task),
                runtime.last_result_for(task),
            ]
        ).lower()
        return self._search_text in haystack
