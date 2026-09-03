"""定时队列页：已入队的定时任务、到期时间、移出队列与立即发送。"""
from __future__ import annotations

from datetime import datetime

from PySide6 import QtCore, QtWidgets

from ...task_models import MailTask
from ..widgets import SectionCard, make_button, label_value


class QueuePage(QtWidgets.QWidget):
    sendQueuedRequested = QtCore.Signal(list)      # list[MailTask]
    removeQueuedRequested = QtCore.Signal(list)    # list[str] task_id

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = None

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        card = SectionCard("定时队列", "已加入队列的定时任务。程序常驻托盘时到点自动发送。")
        self._list = QtWidgets.QListWidget()
        self._list.setWordWrap(True)
        self._list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        card.body_layout.addWidget(self._list, 1)

        self._hint_label = label_value("当前队列为空。在任务页选中定时任务后点击「加入队列」。")
        self._hint_label.setObjectName("MutedLabel")
        card.body_layout.addWidget(self._hint_label)

        button_row = QtWidgets.QHBoxLayout()
        button_row.setSpacing(8)
        self._send_btn = make_button("立即发送选中", variant="primary")
        self._remove_btn = make_button("移出队列")
        self._send_btn.clicked.connect(self._emit_send)
        self._remove_btn.clicked.connect(self._emit_remove)
        button_row.addStretch(1)
        button_row.addWidget(self._remove_btn)
        button_row.addWidget(self._send_btn)
        card.body_layout.addLayout(button_row)

        root.addWidget(card)

    def bind_controller(self, controller) -> None:
        self._controller = controller
        controller.tasksChanged.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        self._list.clear()
        if self._controller is None:
            return
        runtime = self._controller.runtime
        queued = [
            task for task in self._controller.tasks
            if task.task_id in runtime.queued_task_ids and task.schedule_enabled
        ]
        now = datetime.now()
        for task in queued:
            if task.scheduled_at is None:
                due_text = "未设置时间"
            elif task.scheduled_at > now:
                minutes = int((task.scheduled_at - now).total_seconds() // 60)
                due_text = f"{task.scheduled_at:%Y-%m-%d %H:%M:%S}（{max(minutes, 1)} 分钟后）"
            else:
                due_text = f"{task.scheduled_at:%Y-%m-%d %H:%M:%S}（已到期，等待发送）"
            recipients = "; ".join(task.to_recipients) or "未填写"
            self._list.addItem(f"{task.subject or '未填写主题'}\n收件人：{recipients}｜到期：{due_text}")
        self._hint_label.setVisible(not queued)
        self._send_btn.setEnabled(bool(queued))
        self._remove_btn.setEnabled(bool(queued))

    def _selected_tasks(self) -> list[MailTask]:
        if self._controller is None:
            return []
        rows = sorted({index.row() for index in self._list.selectedIndexes()})
        queued = [
            task for task in self._controller.tasks
            if task.task_id in self._controller.runtime.queued_task_ids and task.schedule_enabled
        ]
        return [queued[row] for row in rows if 0 <= row < len(queued)]

    def _emit_send(self) -> None:
        tasks = self._selected_tasks()
        if tasks:
            self.sendQueuedRequested.emit(tasks)

    def _emit_remove(self) -> None:
        tasks = self._selected_tasks()
        if tasks:
            self.removeQueuedRequested.emit([task.task_id for task in tasks])
