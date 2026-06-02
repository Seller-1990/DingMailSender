from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtWidgets

from ..connection_profile import ConnectionProfileLoadError, load_connection_profile, save_connection_profile
from ..model import SmtpConfig
from ..paths import connection_profile_path, detect_home_dir, ensure_layout, program_dir
from ..task_models import MailTask
from .dialogs import RunHistoryDialog
from .main_delivery import MainDeliveryMixin
from .main_support import SCHEDULE_CHECK_INTERVAL_MS
from .main_tasks import MainTaskMixin
from .main_ui import MainUiMixin
from .main_view import MainViewMixin
from .task_runtime import TaskRuntimeController
from .widgets import MetricTile
from .workers import SaveDraftsWorker, SendTasksWorker, TestSmtpWorker


class MainWindow(MainUiMixin, MainViewMixin, MainTaskMixin, MainDeliveryMixin, QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("钉钉邮件发送")
        self.resize(1420, 880)

        self._home_dir = ensure_layout(detect_home_dir())
        self._conn_config_path = connection_profile_path()
        self._legacy_conn_config_paths = [program_dir() / "conn_profile.json", self._home_dir / "conn_profile.json"]
        self._smtp_cfg = SmtpConfig()
        self._smtp_password = ""
        self._smtp_connected = False
        self._package_dir: Path | None = None
        self._tasks: list[MailTask] = []
        self._runtime = TaskRuntimeController()
        self._last_run_dir: Path | None = None
        self._quit_requested = False
        self._close_tip_shown = False
        self._active_filter = "all"
        self._connection_profile_error = ""
        self._metric_tiles: dict[str, MetricTile] = {}
        self._filter_buttons: dict[str, QtWidgets.QPushButton] = {}

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

    def _load_connection_profile(self) -> None:
        try:
            profile = load_connection_profile(self._conn_config_path, *self._legacy_conn_config_paths)
        except ConnectionProfileLoadError as exc:
            self._connection_profile_error = str(exc)
            return
        from_email = profile.from_email
        if from_email:
            self._smtp_cfg = SmtpConfig(
                host=self._smtp_cfg.host,
                port=self._smtp_cfg.port,
                security=self._smtp_cfg.security,
                username=from_email,
            )
        self._smtp_password = profile.smtp_password

    def _save_connection_profile(self, *, from_email: str, smtp_password: str) -> Path:
        return save_connection_profile(
            self._conn_config_path,
            from_email=from_email,
            smtp_password=smtp_password,
        )

    def _refresh_smtp_summary_labels(self) -> None:
        sender = self._smtp_cfg.username.strip() or "未配置"
        self._account_label.setText(f"账号：{sender}")
        self._server_label.setText(
            f"服务器：{self._smtp_cfg.host}:{self._smtp_cfg.port} / {self._smtp_cfg.security.upper()}"
        )

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


def run() -> int:
    app = QtWidgets.QApplication([])
    window = MainWindow()
    window.show()
    return app.exec()
