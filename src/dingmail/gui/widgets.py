"""可复用 UI 组件：导航栏、状态徽标、卡片、按钮、通用小部件。"""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from . import icons
from .theme import (
    BORDER,
    PRIMARY,
    RAIL_ACTIVE,
    TEXT_MUTED,
    TEXT_ON_DARK,
    repolish,
    tone_color,
)

# 任务筛选键 -> 展示名（供任务页与模型层共用）
TASK_FILTERS = {
    "all": "全部",
    "ready": "可保存草稿",
    "issue": "需修正",
    "draft": "已保存草稿",
    "queued": "定时队列",
    "failed": "失败",
}


def label_value(text: str) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
    return label


def error_summary(text: str) -> str:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    return lines[-1] if lines else "未知错误"


class NavRail(QtWidgets.QFrame):
    """左侧深色图标导航栏。"""

    pageChanged = QtCore.Signal(str)
    connectClicked = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("NavRail")
        self.setFixedWidth(64)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(4)

        logo = QtWidgets.QLabel("DM")
        logo.setAlignment(QtCore.Qt.AlignCenter)
        logo.setStyleSheet(
            f"color: {TEXT_ON_DARK}; font-weight: 800; font-size: 15px;"
            f"background: {PRIMARY}; border-radius: 10px; padding: 8px 0;"
        )
        layout.addWidget(logo)
        layout.addSpacing(10)

        self._buttons: dict[str, QtWidgets.QToolButton] = {}
        for key, icon_name, text in (
            ("tasks", "tasks", "任务"),
            ("queue", "queue", "队列"),
            ("history", "history", "历史"),
            ("settings", "settings", "设置"),
        ):
            button = QtWidgets.QToolButton()
            button.setText(text)
            button.setIcon(icons.nav_icon(icon_name, TEXT_MUTED))
            button.setIconSize(QtCore.QSize(22, 22))
            button.setToolButtonStyle(QtCore.Qt.ToolButtonTextUnderIcon)
            button.setCheckable(True)
            button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            button.setFixedHeight(52)
            button.clicked.connect(lambda _checked=False, k=key: self.set_active(k, emit=True))
            self._buttons[key] = button
            layout.addWidget(button)

        layout.addStretch(1)
        self._connect_button = QtWidgets.QToolButton()
        self._connect_button.setText("连接")
        self._connect_button.setObjectName("RailConnectButton")
        self._connect_button.clicked.connect(self.connectClicked.emit)
        self._connect_button.setVisible(False)
        layout.addWidget(self._connect_button)

        self._status_label = QtWidgets.QLabel("未连接")
        self._status_label.setAlignment(QtCore.Qt.AlignCenter)
        self._status_label.setWordWrap(True)
        self.set_connection_status(False, "未连接")
        layout.addWidget(self._status_label)

    def set_connection_status(self, connected: bool, text: str) -> None:
        color = "#34d399" if connected else "#94a3b8"
        display = text if text in ("已连接", "未连接") else ("已连接" if connected else text)
        self._status_label.setText(display)
        self._status_label.setStyleSheet(f"color: {color}; font-size: 10px; background: transparent;")
        # 未连接时给出可点击的「连接」入口（跳设置页），已连接则隐藏
        self._connect_button.setVisible(not connected)
        self._connect_button.setEnabled("正在" not in display)

    def set_active(self, key: str, *, emit: bool = False) -> None:
        for name, button in self._buttons.items():
            active = name == key
            button.setChecked(active)
            button.setIcon(icons.nav_icon(name, "#ffffff" if active else TEXT_MUTED))
            button.setStyleSheet(
                f"QToolButton {{ background: {RAIL_ACTIVE if active else 'transparent'};"
                f"color: {TEXT_ON_DARK if active else TEXT_MUTED};"
                f"border-radius: 10px; font-size: 11px; }}"
            )
        if emit:
            self.pageChanged.emit(key)

    def activate(self, key: str) -> None:
        """外部（快捷键/逻辑）切换页面。"""
        self.set_active(key, emit=True)


class StatusTag(QtWidgets.QLabel):
    def __init__(self, text: str = "", *, variant: str = "neutral", parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("StatusTag")
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.set_variant(variant)

    def set_variant(self, variant: str) -> None:
        fg, bg, border = tone_color(variant)
        self.setStyleSheet(
            f"QLabel#StatusTag {{ color: {fg}; background: {bg}; border: 1px solid {border};"
            f"border-radius: 10px; padding: 3px 9px; font-weight: 700; }}"
        )

    def set_status(self, text: str, variant: str) -> None:
        self.setText(text)
        self.set_variant(variant)


class SectionCard(QtWidgets.QFrame):
    """白底圆角卡片：标题 + 副标题 + 头部操作区 + 主体布局。"""

    def __init__(self, title: str, hint: str = "", parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Surface")

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QtWidgets.QFrame()
        header_layout = QtWidgets.QHBoxLayout(header)
        header_layout.setContentsMargins(14, 10, 14, 10)
        header_layout.setSpacing(10)

        title_box = QtWidgets.QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(2)
        title_label = QtWidgets.QLabel(title)
        title_label.setObjectName("SectionTitle")
        title_box.addWidget(title_label)
        if hint:
            hint_box = QtWidgets.QLabel(hint)
            hint_box.setObjectName("MutedLabel")
            hint_box.setWordWrap(True)
            title_box.addWidget(hint_box)

        self.actions_layout = QtWidgets.QHBoxLayout()
        self.actions_layout.setContentsMargins(0, 0, 0, 0)
        self.actions_layout.setSpacing(8)

        header_layout.addLayout(title_box, 1)
        header_layout.addLayout(self.actions_layout)

        self.body = QtWidgets.QWidget()
        self.body_layout = QtWidgets.QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(12, 10, 12, 12)
        self.body_layout.setSpacing(10)

        line = QtWidgets.QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {BORDER}; border: none;")
        root.addWidget(header)
        root.addWidget(line)
        root.addWidget(self.body, 1)


def make_button(text: str, *, variant: str = "default") -> QtWidgets.QPushButton:
    button = QtWidgets.QPushButton(text)
    button.setProperty("variant", variant)
    return button


class Banner(QtWidgets.QLabel):
    """页面内联提示条（替代部分模态弹窗）。"""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Banner")
        self.setWordWrap(True)
        self.hide()

    def show_message(self, text: str, *, severity: str = "info") -> None:
        self.setText(text)
        self.setProperty("severity", severity)
        repolish(self)
        self.show()

    def clear_message(self) -> None:
        self.hide()
