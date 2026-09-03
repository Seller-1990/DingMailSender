"""应用入口：QApplication、单实例互斥、全局异常钩子。"""
from __future__ import annotations

import socket
import sys
import traceback

from PySide6 import QtWidgets

from .main_window import MainWindow
from .resources import app_icon

_INSTANCE_LOCK_PORT = 29517  # 应用专用端口，用于单实例互斥


def _acquire_single_instance_lock() -> socket.socket | None:
    """尝试绑定本地端口实现单实例互斥。成功返回 socket，已有实例运行时返回 None。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", _INSTANCE_LOCK_PORT))
        sock.listen(1)
        return sock
    except OSError:
        sock.close()
        return None


def _install_excepthook() -> None:
    """槽内未捕获异常在 --noconsole 下不可见；这里给出统一的崩溃弹窗。"""

    def _hook(exc_type, exc, tb) -> None:
        detail = "".join(traceback.format_exception(exc_type, exc, tb))
        sys.stderr.write(detail)
        try:
            QtWidgets.QMessageBox.critical(
                None,
                "程序遇到未处理的错误",
                f"{exc_type.__name__}: {exc}\n\n程序可能处于不一致状态，建议保存工作后重启。\n\n{detail[-1500:]}",
            )
        except Exception:
            pass

    sys.excepthook = _hook


def run() -> int:
    app = QtWidgets.QApplication([])
    app.setApplicationName("DingMailSender")
    app.setApplicationDisplayName("钉钉邮件发送")
    app.setWindowIcon(app_icon())  # 窗口/对话框/托盘统一图标

    lock = _acquire_single_instance_lock()
    if lock is None:
        QtWidgets.QMessageBox.warning(
            None,
            "已有实例运行",
            "DingMailSender 已在运行中，请勿重复启动。\n如果确认没有其他实例，请稍后重试。",
        )
        return 1

    _install_excepthook()
    try:
        try:
            window = MainWindow()
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                None,
                "启动失败",
                "程序初始化失败，可能是无法创建或访问工作目录。\n"
                f"{exc}\n\n"
                "请把程序放到可写目录后重试，或设置环境变量 DINGMAIL_HOME 指定工作目录。",
            )
            return 1
        window.show()
        return app.exec()
    finally:
        lock.close()
