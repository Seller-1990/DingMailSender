from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from PySide6 import QtCore, QtWidgets

SCHEDULE_CHECK_INTERVAL_MS = 15_000
STATUS_ROW_COLORS = {
    "neutral": "#f3f6fa",
    "success": "#eef8f1",
    "draft": "#edf8fc",
    "warning": "#fff8e6",
    "danger": "#fdf0ee",
    "info": "#eef3ff",
}

TASK_FILTERS = {
    "all": "全部",
    "ready": "可保存草稿",
    "issue": "需修正",
    "draft": "已保存草稿",
    "queued": "定时队列",
    "failed": "失败",
}


@dataclass(frozen=True)
class UiActionState:
    has_package: bool
    has_selection: bool
    has_single: bool
    can_send: bool
    can_edit: bool


def label_value(text: str) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
    label.setWordWrap(True)
    return label


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def error_summary(text: str) -> str:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    return lines[-1] if lines else "未知错误"
