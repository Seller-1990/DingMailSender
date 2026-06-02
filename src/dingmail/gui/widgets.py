from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from .theme import repolish, set_variant


class StatusTag(QtWidgets.QLabel):
    def __init__(self, text: str = "", *, variant: str = "neutral", parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("StatusTag")
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setMinimumHeight(24)
        self.set_variant(variant)

    def set_variant(self, variant: str) -> None:
        self.setProperty("variant", variant)
        repolish(self)

    def set_status(self, text: str, variant: str) -> None:
        self.setText(text)
        self.set_variant(variant)


class MetricTile(QtWidgets.QFrame):
    def __init__(
        self,
        title: str,
        value: str = "0",
        detail: str = "",
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("MetricTile")
        self.setMinimumHeight(86)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        self._title = QtWidgets.QLabel(title)
        self._title.setObjectName("MetricTitle")
        self._value = QtWidgets.QLabel(value)
        self._value.setObjectName("MetricValue")
        self._detail = QtWidgets.QLabel(detail)
        self._detail.setObjectName("MetricDetail")
        self._detail.setWordWrap(True)

        layout.addWidget(self._title)
        layout.addWidget(self._value)
        layout.addWidget(self._detail)

    def update_value(self, value: str | int, detail: str | None = None) -> None:
        self._value.setText(str(value))
        if detail is not None:
            self._detail.setText(detail)


class SectionPanel(QtWidgets.QFrame):
    def __init__(
        self,
        title: str,
        hint: str = "",
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Panel")

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QtWidgets.QFrame()
        header.setObjectName("PanelHeader")
        header_layout = QtWidgets.QHBoxLayout(header)
        header_layout.setContentsMargins(14, 12, 14, 12)
        header_layout.setSpacing(12)

        title_box = QtWidgets.QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(3)
        title_label = QtWidgets.QLabel(title)
        title_label.setObjectName("SectionTitle")
        title_box.addWidget(title_label)
        if hint:
            hint_label = QtWidgets.QLabel(hint)
            hint_label.setObjectName("SectionHint")
            hint_label.setWordWrap(True)
            title_box.addWidget(hint_label)

        self.actions_layout = QtWidgets.QHBoxLayout()
        self.actions_layout.setContentsMargins(0, 0, 0, 0)
        self.actions_layout.setSpacing(8)

        header_layout.addLayout(title_box, 1)
        header_layout.addLayout(self.actions_layout)

        self.body = QtWidgets.QWidget()
        self.body_layout = QtWidgets.QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(14, 14, 14, 14)
        self.body_layout.setSpacing(12)

        root.addWidget(header)
        root.addWidget(self.body, 1)


def make_button(text: str, *, variant: str = "default") -> QtWidgets.QPushButton:
    button = QtWidgets.QPushButton(text)
    set_button_variant(button, variant)
    return button


def set_button_variant(button: QtWidgets.QPushButton, variant: str) -> None:
    set_variant(button, variant)
