from __future__ import annotations

from PySide6 import QtCore, QtWidgets


def dialog_label(text: str) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
    label.setWordWrap(True)
    return label


def fit_text(value: str, limit: int = 28) -> str:
    text = str(value or "").replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"
