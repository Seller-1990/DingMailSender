"""设置页：连接设置（含 IMAP）、发送设置、关于。"""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from ..widgets import SectionCard, make_button, label_value
from ...task_service import EMAIL_RE


class SettingsPage(QtWidgets.QWidget):
    sendSettingsChanged = QtCore.Signal(float, int)  # (rate_limit_seconds, runs_retention_days)
    openHomeDirRequested = QtCore.Signal()

    def __init__(self, connection, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._connection = connection

        root_layout = QtWidgets.QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(10)

        root_layout.addWidget(self._build_connection_card())
        root_layout.addWidget(self._build_send_settings_card())
        root_layout.addWidget(self._build_about_card())
        root_layout.addStretch(1)

        self._connection.statusChanged.connect(self._on_connection_status)
        self._connection.testSucceeded.connect(lambda _msg: self._set_status("已连接并保存。", "success"))
        self._connection.testFailed.connect(
            lambda tb: self._set_status(f"连接失败：{self._last_error(tb)}", "danger")
        )

    # ---- 连接设置 ----

    def _build_connection_card(self) -> QtWidgets.QWidget:
        card = SectionCard("连接设置", "连接测试成功后自动保存授权码（Windows 下 DPAPI 加密）。")
        self._status_label = label_value("")
        self._status_label.setWordWrap(True)

        form = QtWidgets.QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        self._email_input = QtWidgets.QLineEdit(self._connection.smtp_cfg.username)
        self._email_input.setPlaceholderText("name@example.com")
        self._password_input = QtWidgets.QLineEdit()
        self._password_input.setEchoMode(QtWidgets.QLineEdit.Password)
        self._password_input.setPlaceholderText(
            "留空沿用已保存授权码" if self._connection.password else "SMTP 授权码"
        )
        form.addRow("发件邮箱", self._email_input)
        form.addRow("SMTP 授权码", self._password_input)

        self._imap_host_input = QtWidgets.QLineEdit(self._connection.imap_host)
        self._imap_host_input.setPlaceholderText("imap.example.com")
        self._imap_port_input = QtWidgets.QSpinBox()
        self._imap_port_input.setRange(1, 65535)
        self._imap_port_input.setValue(self._connection.imap_port or 993)
        form.addRow("IMAP 服务器", self._imap_host_input)
        form.addRow("IMAP 端口", self._imap_port_input)

        button_row = QtWidgets.QHBoxLayout()
        button_row.setSpacing(8)
        self._test_btn = make_button("连接并测试", variant="primary")
        self._test_btn.clicked.connect(self._start_test)
        button_row.addStretch(1)
        button_row.addWidget(self._test_btn)

        card.body_layout.addLayout(form)
        card.body_layout.addWidget(self._status_label)
        card.body_layout.addLayout(button_row)
        self._refresh_profile_labels()
        return card

    def _refresh_profile_labels(self) -> None:
        connection = self._connection
        self._status_label.setText(
            f"{connection.profile_source_text} ｜ {connection.profile_source_detail}".strip(" ｜")
        )

    def _start_test(self) -> None:
        email = self._email_input.text().strip()
        password = self._password_input.text().strip() or self._connection.password
        if not EMAIL_RE.match(email):
            self._set_status("请输入正确的发件邮箱。", "danger")
            return
        if not password:
            self._set_status("请输入 SMTP 授权码（已保存授权码可留空沿用）。", "danger")
            return
        self._test_btn.setEnabled(False)
        self._set_status("正在连接…")
        started = self._connection.start_test(
            email=email,
            password=password,
            imap_host=self._imap_host_input.text().strip(),
            imap_port=self._imap_port_input.value(),
        )
        if not started:
            self._test_btn.setEnabled(True)
            self._set_status("已有连接测试进行中，请稍候再试。", "warning")

    def _set_status(self, text: str, severity: str = "info") -> None:
        colors = {
            "info": "#6b7280",
            "success": "#047857",
            "warning": "#b45309",
            "danger": "#b91c1c",
        }
        self._status_label.setText(text)
        self._status_label.setStyleSheet(f"color: {colors.get(severity, colors['info'])};")

    def _on_connection_status(self, connected: bool, detail: str) -> None:
        self._test_btn.setEnabled(not connected)
        if connected:
            self._refresh_profile_labels()

    def refresh_from_service(self) -> None:
        self._email_input.setText(self._connection.smtp_cfg.username)
        self._password_input.setPlaceholderText(
            "留空沿用已保存授权码" if self._connection.password else "SMTP 授权码"
        )
        self._imap_host_input.setText(self._connection.imap_host)
        self._imap_port_input.setValue(self._connection.imap_port or 993)
        self._refresh_profile_labels()

    def focus_connection_form(self) -> None:
        """从导航栏「连接」进入时，把焦点放到第一个待填字段。"""
        if self._email_input.text().strip():
            self._password_input.setFocus()
        else:
            self._email_input.setFocus()

    @staticmethod
    def _last_error(tb: str) -> str:
        lines = [line.strip() for line in str(tb or "").splitlines() if line.strip()]
        return lines[-1] if lines else "未知错误"

    # ---- 发送设置 ----

    def _build_send_settings_card(self) -> QtWidgets.QWidget:
        card = SectionCard("发送设置", "任务间隔用于降低邮箱服务器压力；runs 目录按保留天数在启动时自动清理。")
        form = QtWidgets.QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        self._rate_input = QtWidgets.QDoubleSpinBox()
        self._rate_input.setRange(0.0, 60.0)
        self._rate_input.setDecimals(1)
        self._rate_input.setSingleStep(0.5)
        self._rate_input.setSuffix(" 秒")
        self._retention_input = QtWidgets.QSpinBox()
        self._retention_input.setRange(0, 3650)
        self._retention_input.setSuffix(" 天")
        self._retention_input.setSpecialValueText("永久保留")
        form.addRow("任务间隔", self._rate_input)
        form.addRow("运行记录保留", self._retention_input)

        save_btn = make_button("保存设置", variant="primary")
        save_btn.clicked.connect(self._save_settings)

        card.body_layout.addLayout(form)
        card.body_layout.addWidget(save_btn)
        return card

    def load_send_settings(self, rate_limit_seconds: float, runs_retention_days: int) -> None:
        self._rate_input.setValue(rate_limit_seconds)
        self._retention_input.setValue(runs_retention_days)

    def _save_settings(self) -> None:
        self.sendSettingsChanged.emit(self._rate_input.value(), self._retention_input.value())

    # ---- 关于 ----

    def _build_about_card(self) -> QtWidgets.QWidget:
        card = SectionCard("关于")
        self._about_label = label_value("")
        self._about_label.setObjectName("MutedLabel")
        self._about_label.setWordWrap(True)
        open_btn = make_button("打开工作目录")
        open_btn.clicked.connect(self.openHomeDirRequested)
        card.body_layout.addWidget(self._about_label)
        card.body_layout.addWidget(open_btn)
        return card

    def set_about_info(self, text: str) -> None:
        self._about_label.setText(text)
