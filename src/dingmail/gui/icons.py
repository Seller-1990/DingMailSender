"""QPainter 绘制的导航/状态图标，避免引入图标库依赖。"""
from __future__ import annotations

import math

from PySide6 import QtCore, QtGui

_ICON_CACHE: dict[tuple[str, str], QtGui.QIcon] = {}


def _painter_path(draw: "callable") -> QtGui.QPainterPath:
    path = QtGui.QPainterPath()
    draw(path)
    return path


def _draw_tasks(p: QtGui.QPainter, color: QtGui.QColor) -> None:
    pen = QtGui.QPen(color, 1.8, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap)
    p.setPen(pen)
    # 三条任务线 + 左侧方块
    for i, y in enumerate((6, 12, 18)):
        p.drawRect(3, y - 1.5, 4, 4)
        p.drawLine(10, y + 0.5, 21, y + 0.5)


def _draw_queue(p: QtGui.QPainter, color: QtGui.QColor) -> None:
    pen = QtGui.QPen(color, 1.8, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap)
    p.setPen(pen)
    p.drawEllipse(4, 4, 16, 16)
    p.drawLine(12, 7.5, 12, 12.5)
    p.drawLine(12, 12.5, 15.5, 14.5)


def _draw_history(p: QtGui.QPainter, color: QtGui.QColor) -> None:
    pen = QtGui.QPen(color, 1.8, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap)
    p.setPen(pen)
    # 文件夹
    path = QtGui.QPainterPath()
    path.moveTo(3, 6)
    path.lineTo(9, 6)
    path.lineTo(11, 8.5)
    path.lineTo(21, 8.5)
    path.lineTo(21, 19)
    path.lineTo(3, 19)
    path.closeSubpath()
    p.drawPath(path)


def _draw_settings(p: QtGui.QPainter, color: QtGui.QColor) -> None:
    pen = QtGui.QPen(color, 1.8, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap)
    p.setPen(pen)
    p.drawEllipse(QtCore.QPointF(12, 12), 3.2, 3.2)
    # 齿轮辐条
    for i in range(8):
        angle = math.pi / 4 * i
        x1 = 12 + 5.6 * math.cos(angle)
        y1 = 12 + 5.6 * math.sin(angle)
        x2 = 12 + 8.2 * math.cos(angle)
        y2 = 12 + 8.2 * math.sin(angle)
        p.drawLine(QtCore.QPointF(x1, y1), QtCore.QPointF(x2, y2))


_DRAWERS = {
    "tasks": _draw_tasks,
    "queue": _draw_queue,
    "history": _draw_history,
    "settings": _draw_settings,
}


def nav_icon(name: str, color: str) -> QtGui.QIcon:
    """绘制导航图标；结果按 (name, color) 缓存。"""
    key = (name, color)
    cached = _ICON_CACHE.get(key)
    if cached is not None:
        return cached

    size = 24
    pixmap = QtGui.QPixmap(size * 2, size * 2)  # 2x 绘制保证清晰
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.scale(2, 2)
    _DRAWERS[name](painter, QtGui.QColor(color))
    painter.end()

    icon = QtGui.QIcon(pixmap)
    _ICON_CACHE[key] = icon
    return icon
