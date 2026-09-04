"""SMTP/IMAP 连接管理：凭据装载、手动测试、自动重连、profile 保存。"""
from __future__ import annotations

import time

from PySide6 import QtCore

from ...connection_profile import (
    ConnectionProfileLoadError,
    load_connection_profile_with_metadata,
    migrate_connection_profile_if_needed,
    save_connection_profile,
)
from ...constants import AUTO_CONNECT_RETRY_SECONDS
from ...model import SmtpConfig
from ..workers import TestSmtpWorker


class ConnectionService(QtCore.QObject):
    """连接状态与凭据的唯一持有者。"""

    statusChanged = QtCore.Signal(bool, str)     # (connected, detail)
    testSucceeded = QtCore.Signal(str)           # info 文本
    testFailed = QtCore.Signal(str)              # traceback
    autoConnectFailed = QtCore.Signal(str)       # traceback

    def __init__(self, conn_config_path, legacy_paths, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self.conn_config_path = conn_config_path
        self.legacy_paths = list(legacy_paths)

        self.smtp_cfg = SmtpConfig()
        self.password = ""
        self.imap_host = ""
        self.imap_port = 0
        self.connected = False

        self.profile_source_text = "配置：默认参数（未保存）"
        self.profile_source_detail = ""
        self.profile_warning = ""

        self._worker: TestSmtpWorker | None = None
        self._last_auto_connect_at = 0.0
        # 手动测试的提交上下文（apply_success 时使用）
        self._pending_email = ""
        self._pending_password = ""
        self._pending_imap_host = ""
        self._pending_imap_port = 0

    # ---- 凭据装载 ----

    def load_saved_profile(self) -> None:
        try:
            result = load_connection_profile_with_metadata(self.conn_config_path, *self.legacy_paths)
        except ConnectionProfileLoadError:
            raise
        profile = result.profile
        if profile.from_email:
            self.smtp_cfg = SmtpConfig(
                host=self.smtp_cfg.host,
                port=self.smtp_cfg.port,
                security=self.smtp_cfg.security,
                username=profile.from_email,
            )
        self.password = profile.smtp_password
        if profile.imap_host:
            self.imap_host = profile.imap_host
        if profile.imap_port:
            self.imap_port = profile.imap_port

        if result.source_path is None:
            self.profile_source_text = "配置：默认参数（未保存）"
            self.profile_source_detail = "连接成功后保存到用户配置目录"
            return

        migrated_path = None
        if result.is_legacy_source or result.uses_plaintext_secret:
            try:
                migrated_path = migrate_connection_profile_if_needed(result, self.conn_config_path)
            except Exception as exc:
                self.profile_warning = (
                    "检测到旧版连接配置或明文授权码。当前会继续读取以便你完成工作；"
                    f"但自动迁移到用户配置目录失败：{exc}"
                )

        if migrated_path is not None:
            self.profile_source_text = "配置：用户配置（已自动迁移）"
            self.profile_source_detail = f"来源：{result.source_path}；已迁移到：{migrated_path}"
            self.profile_warning = ""
        elif result.is_legacy_source:
            self.profile_source_text = "配置：旧配置（待迁移）"
            self.profile_source_detail = f"来源：{result.source_path}"
        else:
            self.profile_source_text = "配置：用户配置"
            self.profile_source_detail = f"来源：{result.source_path}"

        if result.uses_plaintext_secret and migrated_path is None and not self.profile_warning:
            self.profile_warning = (
                "检测到旧版连接配置或明文授权码。当前会继续读取以便你完成工作；"
                "下次在设置页完成连接测试后，会写入用户配置目录并使用 Windows DPAPI 保存授权码。"
            )

    # ---- 手动测试（设置页内联反馈） ----

    def start_test(self, *, email: str, password: str, imap_host: str, imap_port: int) -> bool:
        if self._worker is not None:
            return False
        self._pending_email = email
        self._pending_password = password
        self._pending_imap_host = imap_host
        self._pending_imap_port = imap_port
        cfg = SmtpConfig(
            host=self.smtp_cfg.host,
            port=self.smtp_cfg.port,
            security=self.smtp_cfg.security,
            username=email,
        )
        self.statusChanged.emit(False, "正在连接…")
        worker = TestSmtpWorker(cfg, password)
        self._worker = worker
        worker.finished_ok.connect(self._on_test_ok)
        worker.finished_err.connect(self._on_test_err)
        worker.start()
        return True

    def _on_test_ok(self, info: str) -> None:
        self._release_worker()
        self._worker = None
        message = self.apply_connection_success(
            from_email=self._pending_email,
            password=self._pending_password,
            imap_host=self._pending_imap_host,
            imap_port=self._pending_imap_port,
            info=info,
        )
        self.testSucceeded.emit(message)

    def _on_test_err(self, tb: str) -> None:
        self._release_worker()
        self._worker = None
        self.statusChanged.emit(False, "连接失败")
        self.testFailed.emit(tb)

    def apply_connection_success(self, *, from_email: str, password: str, imap_host: str, imap_port: int, info: str) -> str:
        """应用一次成功连接：更新状态、保存 profile；返回展示用提示文本。"""
        from ...constants import DEFAULT_IMAP_HOST, DEFAULT_IMAP_PORT_SSL

        self.smtp_cfg = SmtpConfig(
            host=self.smtp_cfg.host,
            port=self.smtp_cfg.port,
            security=self.smtp_cfg.security,
            username=from_email,
        )
        self.password = password
        self.imap_host = imap_host.strip() or DEFAULT_IMAP_HOST
        self.imap_port = int(imap_port) if imap_port else DEFAULT_IMAP_PORT_SSL
        self._set_connected(True, info)
        try:
            saved_path = save_connection_profile(
                self.conn_config_path,
                from_email=from_email,
                smtp_password=password,
                imap_host=self.imap_host,
                imap_port=self.imap_port,
            )
        except Exception as exc:
            return (
                f"连接成功：{info}\n\n"
                f"连接信息未能写入 `{self.conn_config_path}`：{exc}\n"
                "本次连接可继续使用，但下次启动可能仍需重新填写。"
            )
        self.profile_source_text = "配置：用户配置"
        self.profile_source_detail = f"来源：{saved_path}"
        self.profile_warning = ""
        return f"连接成功：{info}\n已保存登录信息：{saved_path}"

    # ---- 自动重连（定时调度驱动） ----

    def try_auto_connect(self) -> bool:
        if self.connected or self._worker is not None:
            return False
        if not self.smtp_cfg.username.strip() or not self.password:
            return False
        now = time.monotonic()
        if now - self._last_auto_connect_at < AUTO_CONNECT_RETRY_SECONDS:
            return False
        self._last_auto_connect_at = now
        self.statusChanged.emit(False, "正在自动连接…")
        worker = TestSmtpWorker(self.smtp_cfg, self.password)
        self._worker = worker
        worker.finished_ok.connect(self._on_auto_connect_ok)
        worker.finished_err.connect(self._on_auto_connect_err)
        worker.start()
        return True

    def _on_auto_connect_ok(self, info: str) -> None:
        self._release_worker()
        self._worker = None
        self._set_connected(True, info)

    def _on_auto_connect_err(self, tb: str) -> None:
        self._release_worker()
        self._worker = None
        # 状态徽标即反馈；下个调度周期会自动重试，不清空已存授权码
        self._set_connected(False, "自动连接失败")
        self.autoConnectFailed.emit(tb)

    def _release_worker(self) -> None:
        if self._worker is not None:
            # deleteLater 延迟到事件循环安全点析构，避免线程清理竞态 abort
            self._worker.deleteLater()

    # ---- 状态 ----

    def has_active_test(self) -> bool:
        return self._worker is not None

    def wait_active_test(self, timeout_ms: int) -> bool:
        if self._worker is None:
            return True
        return self._worker.wait(timeout_ms)

    def _set_connected(self, connected: bool, detail: str) -> None:
        self.connected = connected
        self.statusChanged.emit(connected, detail)
