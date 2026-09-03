from __future__ import annotations

import sys
from pathlib import Path

from PySide6 import QtGui

RESOURCES_DIRNAME = "resources"
ICON_FILENAME = "app.ico"


def resource_dir() -> Path:
    """定位随包分发的资源目录（兼容 PyInstaller onefile 的 _MEIPASS 解包目录）。"""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", None) or Path(sys.executable).resolve().parent
        return Path(base) / "dingmail" / "gui" / RESOURCES_DIRNAME
    return Path(__file__).resolve().parent / RESOURCES_DIRNAME


def app_icon() -> QtGui.QIcon:
    """应用图标：窗口、对话框、托盘共用同一资源。"""
    return QtGui.QIcon(str(resource_dir() / ICON_FILENAME))
