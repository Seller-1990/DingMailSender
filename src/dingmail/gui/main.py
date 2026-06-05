from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtWidgets

from ..connection_profile import (
    ConnectionProfileLoadError,
    ConnectionProfileLoadResult,
    load_connection_profile_with_metadata,
    save_connection_profile,
)
from ..model import SmtpConfig
from ..paths import connection_profile_path, detect_home_dir, ensure_layout, program_dir
from .main_delivery import MainDeliveryMixin
from .main_state import MainWindowState
from .main_support import SCHEDULE_CHECK_INTERVAL_MS
from .main_tasks import MainTaskMixin
from .main_ui import MainUiMixin
from .main_view import MainViewMixin
from .workers import SaveDraftsWorker, SendTasksWorker, TestSmtpWorker


class MainWindow(MainUiMixin, MainViewMixin, MainTaskMixin, MainDeliveryMixin, QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("钉钉邮件发送")
        self.resize(1420, 880)

        home_dir = ensure_layout(detect_home_dir())
        conn_config_path = connection_profile_path()
        self._state = MainWindowState(
            home_dir=home_dir,
            conn_config_path=conn_config_path,
            legacy_conn_config_paths=[program_dir() / "conn_profile.json", home_dir / "conn_profile.json"],
            connection_profile_source_detail=f"保存位置：{conn_config_path}",
        )

        self._smtp_worker: TestSmtpWorker | None = None
        self._send_worker: SendTasksWorker | None = None
        self._draft_worker: SaveDraftsWorker | None = None

        self._load_connection_profile()
        self._build_ui()
        self._build_tray()
        self._schedule_timer = QtCore.QTimer(self)
        self._schedule_timer.setInterval(SCHEDULE_CHECK_INTERVAL_MS)
        self._schedule_timer.timeout.connect(self._process_scheduled_tasks)
        self._schedule_timer.start()
        self._apply_styles()
        self._refresh_ui_state()
        if self._connection_profile_error:
            self._set_smtp_status(False, "连接配置读取失败")
            QtCore.QTimer.singleShot(0, self._show_connection_profile_error)
        elif self._connection_profile_warning:
            QtCore.QTimer.singleShot(0, self._show_connection_profile_migration_notice)

    def _load_connection_profile(self) -> None:
        try:
            result = load_connection_profile_with_metadata(self._conn_config_path, *self._legacy_conn_config_paths)
        except ConnectionProfileLoadError as exc:
            self._connection_profile_error = str(exc)
            return
        self._apply_connection_profile_metadata(result)
        profile = result.profile
        from_email = profile.from_email
        if from_email:
            self._smtp_cfg = SmtpConfig(
                host=self._smtp_cfg.host,
                port=self._smtp_cfg.port,
                security=self._smtp_cfg.security,
                username=from_email,
            )
        self._smtp_password = profile.smtp_password

    def _apply_connection_profile_metadata(self, result: ConnectionProfileLoadResult) -> None:
        if result.source_path is None:
            self._connection_profile_source_text = "配置：默认参数（未保存）"
            self._connection_profile_source_detail = f"连接成功后保存到：{self._conn_config_path}"
            return

        if result.is_legacy_source:
            self._connection_profile_source_text = "配置：旧配置（待迁移）"
        else:
            self._connection_profile_source_text = "配置：用户配置"
        if result.uses_plaintext_secret:
            self._connection_profile_source_text += " · 明文授权码"
        self._connection_profile_source_detail = f"来源：{result.source_path}"
        if result.is_legacy_source or result.uses_plaintext_secret:
            self._connection_profile_warning = (
                "检测到旧版连接配置或明文授权码。当前会继续读取以便你完成工作；"
                "下次在“连接设置”里连接并测试成功后，会写入用户配置目录并使用 Windows DPAPI 保存授权码。"
            )

    def _save_connection_profile(self, *, from_email: str, smtp_password: str) -> Path:
        return save_connection_profile(
            self._conn_config_path,
            from_email=from_email,
            smtp_password=smtp_password,
        )

    def _mark_connection_profile_saved(self, saved_path: Path) -> None:
        self._connection_profile_error = ""
        self._connection_profile_warning = ""
        self._connection_profile_source_text = "配置：用户配置"
        self._connection_profile_source_detail = f"来源：{saved_path}"
        self._refresh_smtp_summary_labels()

    def _refresh_smtp_summary_labels(self) -> None:
        sender = self._smtp_cfg.username.strip() or "未配置"
        self._account_label.setText(f"账号：{sender}")
        self._server_label.setText(
            f"服务器：{self._smtp_cfg.host}:{self._smtp_cfg.port} / {self._smtp_cfg.security.upper()}"
        )
        if hasattr(self, "_profile_source_label"):
            self._profile_source_label.setText(self._connection_profile_source_text)
            self._profile_source_label.setToolTip(self._connection_profile_source_detail)

    def _show_error_dialog(self, title: str, message: str, *, details: str | None = None) -> None:
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Critical)
        box.setWindowTitle(title)
        box.setText(message)
        if details:
            box.setDetailedText(details)
        box.exec()

    def _show_connection_profile_error(self) -> None:
        if not self._connection_profile_error:
            return
        QtWidgets.QMessageBox.warning(
            self,
            "连接配置读取失败",
            f"{self._connection_profile_error}\n请重新打开连接设置，完成连接测试后保存新的配置。",
        )

    def _show_connection_profile_migration_notice(self) -> None:
        if not self._connection_profile_warning:
            return
        QtWidgets.QMessageBox.warning(self, "连接配置需要迁移", self._connection_profile_warning)


def run() -> int:
    app = QtWidgets.QApplication([])
    window = MainWindow()
    window.show()
    return app.exec()


def _state_property(name: str):
    def _get(self):
        return getattr(self._state, name)

    def _set(self, value) -> None:
        setattr(self._state, name, value)

    return property(_get, _set)


for _attr_name, _state_name in {
    "_home_dir": "home_dir",
    "_conn_config_path": "conn_config_path",
    "_legacy_conn_config_paths": "legacy_conn_config_paths",
    "_smtp_cfg": "smtp_cfg",
    "_smtp_password": "smtp_password",
    "_smtp_connected": "smtp_connected",
    "_package_dir": "package_dir",
    "_tasks": "tasks",
    "_runtime": "runtime",
    "_last_run_dir": "last_run_dir",
    "_quit_requested": "quit_requested",
    "_close_tip_shown": "close_tip_shown",
    "_active_filter": "active_filter",
    "_connection_profile_error": "connection_profile_error",
    "_connection_profile_source_text": "connection_profile_source_text",
    "_connection_profile_source_detail": "connection_profile_source_detail",
    "_connection_profile_warning": "connection_profile_warning",
    "_metric_tiles": "metric_tiles",
    "_filter_buttons": "filter_buttons",
}.items():
    setattr(MainWindow, _attr_name, _state_property(_state_name))

del _attr_name, _state_name
