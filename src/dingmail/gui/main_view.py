from __future__ import annotations

import time

from PySide6 import QtCore, QtGui, QtWidgets

from ..constants import DEFAULT_IMAP_HOST, DEFAULT_IMAP_PORT_SSL
from ..model import SmtpConfig
from ..task_models import MailTask
from ..task_service import render_task_preview_html
from ..task_status import TaskStatus
from .main_support import AUTO_CONNECT_RETRY_SECONDS, TASK_FILTERS
from .resources import app_icon
from .theme import status_tone
from .widgets import set_button_variant
from .workers import TestSmtpWorker


class MainViewMixin:
    def _confirm_open_link_from_detail(self, url: QtCore.QUrl) -> None:
        reply = QtWidgets.QMessageBox.question(
            self,
            "打开链接",
            f"是否打开此链接？\n{url.toString()}",
        )
        if reply == QtWidgets.QMessageBox.Yes:
            QtGui.QDesktopServices.openUrl(url)

    def _set_task_filter(self, filter_key: str) -> None:
        self._active_filter = filter_key if filter_key in TASK_FILTERS else "all"
        self._refresh_filter_buttons()
        self._task_proxy.set_filter_key(self._active_filter)

    def _refresh_filter_buttons(self) -> None:
        for key, button in self._filter_buttons.items():
            set_button_variant(button, "primary" if key == self._active_filter else "default")

    def _on_task_selection_changed(self) -> None:
        self._refresh_detail_panel()
        self._refresh_ui_state()

    def _selected_detail_task(self) -> MailTask | None:
        rows = self._selected_rows()
        if len(rows) != 1:
            return None
        row = rows[0]
        return self._tasks[row] if 0 <= row < len(self._tasks) else None

    def _refresh_metrics(self) -> None:
        enabled_tasks = [task for task in self._tasks if task.enabled]
        ready = sum(1 for task in self._tasks if self._runtime.status_for(task) == TaskStatus.READY)
        issues = sum(1 for task in self._tasks if self._runtime.status_for(task) == TaskStatus.VALIDATION_FAILED)
        drafts = sum(1 for task in self._tasks if self._runtime.status_for(task) == TaskStatus.DRAFT_SAVED)
        queued = len(self._runtime.queued_task_ids)
        updates = {
            "enabled": (len(enabled_tasks), "当前任务包"),
            "ready": (ready, "校验通过"),
            "issues": (issues, "路径或邮箱异常"),
            "drafts": (drafts, "本轮状态"),
            "queued": (queued, "托盘调度"),
        }
        for key, (value, detail) in updates.items():
            tile = self._metric_tiles.get(key)
            if tile:
                tile.update_value(value, detail)

    def _refresh_detail_panel(self) -> None:
        rows = self._selected_rows()
        if len(rows) > 1:
            tasks = [self._tasks[row] for row in rows if 0 <= row < len(self._tasks)]
            self._render_batch_detail(tasks)
            return
        task = self._selected_detail_task()
        if task is None:
            self._detail_status_tag.set_status("未选择", "neutral")
            self._detail_title_label.setText("未选择任务")
            self._detail_to_label.setText("收件人：-")
            self._detail_cc_label.setText("抄送人：-")
            self._detail_markdown_label.setText("Markdown：-")
            self._detail_attachments_label.setText("附件：-")
            self._detail_schedule_label.setText("定时：-")
            self._detail_issue_label.setText("请选择一条任务查看详情。")
            self._detail_preview_browser.setHtml("")
            return

        scheduled_text = task.scheduled_at.strftime("%Y-%m-%d %H:%M:%S") if task.scheduled_at else "未设置"
        attachment_text = "; ".join(task.attachment_paths) if task.attachment_paths else "无附件"
        state = self._runtime.state_for(task)
        issue_text = state.error_message or state.last_result or task.note or "当前任务没有错误提示。"
        self._detail_status_tag.set_status(state.status.label, status_tone(state.status))
        self._detail_title_label.setText(task.subject or "未填写主题")
        self._detail_to_label.setText(f"收件人：{'; '.join(task.to_recipients) or '未填写'}")
        self._detail_cc_label.setText(f"抄送人：{'; '.join(task.cc_recipients) or '无'}")
        self._detail_markdown_label.setText(f"Markdown：{task.markdown_path or '未填写'}")
        self._detail_attachments_label.setText(f"附件：{attachment_text}")
        self._detail_schedule_label.setText(
            f"定时：{'是' if task.schedule_enabled else '否'} / {scheduled_text}"
        )
        self._detail_issue_label.setText(f"说明：{issue_text}")

        if self._package_dir is None:
            self._detail_preview_browser.setHtml("")
            return
        try:
            self._detail_preview_browser.setHtml(render_task_preview_html(task, self._package_dir))
        except Exception as exc:
            self._detail_preview_browser.setHtml(f"<p>预览失败：{exc}</p>")

    def _render_batch_detail(self, tasks: list[MailTask]) -> None:
        """多选时显示批量摘要，而不是“未选择任务”——批量正是保存草稿/发送的主操作流。"""
        enabled = [task for task in tasks if task.enabled]
        ready = sum(1 for task in enabled if self._runtime.status_for(task) == TaskStatus.READY)
        issues = sum(1 for task in enabled if self._runtime.status_for(task) == TaskStatus.VALIDATION_FAILED)
        self._detail_status_tag.set_status(f"已选择 {len(tasks)} 条", "info")
        self._detail_title_label.setText("批量操作")
        self._detail_to_label.setText(f"已启用：{len(enabled)} 条 / 共 {len(tasks)} 条")
        self._detail_cc_label.setText(f"可保存草稿：{ready} 条")
        self._detail_markdown_label.setText(f"需修正：{issues} 条")
        self._detail_attachments_label.setText("")
        self._detail_schedule_label.setText("")
        self._detail_issue_label.setText(
            "直接使用下方「保存草稿」或「立即发送」，系统会自动跳过需修正的任务。"
        )
        self._detail_preview_browser.setHtml("")

    def _build_tray(self) -> None:
        if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = None
            return

        icon = app_icon()
        if icon.isNull():
            icon = self.style().standardIcon(QtWidgets.QStyle.SP_FileDialogDetailedView)
        self._tray = QtWidgets.QSystemTrayIcon(icon, self)
        self._tray.setToolTip("钉钉邮件发送")
        self._tray.activated.connect(self._on_tray_activated)

        menu = QtWidgets.QMenu(self)
        show_action = menu.addAction("打开主界面")
        show_action.triggered.connect(self._restore_from_tray)
        exit_action = menu.addAction("退出程序")
        exit_action.triggered.connect(self._exit_from_tray)
        self._tray.setContextMenu(menu)
        self.setWindowIcon(icon)
        self._tray.show()

    def _on_tray_activated(self, reason: QtWidgets.QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QtWidgets.QSystemTrayIcon.DoubleClick, QtWidgets.QSystemTrayIcon.Trigger):
            self._restore_from_tray()

    def _restore_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _exit_from_tray(self) -> None:
        active_workers = [
            worker
            for worker in (self._send_worker, self._draft_worker, self._smtp_worker)
            if worker is not None
        ]
        if active_workers:
            self._cancel_current_delivery()
            # 等待 worker 线程结束，避免 QThread 析构时进程 abort
            for worker in active_workers:
                if not worker.wait(10000):  # 最多等 10 秒
                    # 超时仍在运行，提示用户
                    QtWidgets.QMessageBox.information(
                        self,
                        "等待任务结束",
                        "正在等待后台任务安全停止，请稍候再重试退出。",
                    )
                    return
        if self._runtime.queued_task_ids:
            reply = QtWidgets.QMessageBox.question(
                self,
                "确认退出",
                f"当前还有 {len(self._runtime.queued_task_ids)} 个定时任务未发送。退出后将不再自动发送，确认继续吗？",
            )
            if reply != QtWidgets.QMessageBox.Yes:
                return
        self._quit_requested = True
        QtWidgets.QApplication.quit()

    def _handle_close_event(self, event: QtGui.QCloseEvent) -> None:
        active_workers = [
            worker
            for worker in (self._send_worker, self._draft_worker, self._smtp_worker)
            if worker is not None
        ]
        if active_workers and (self._quit_requested or self._tray is None):
            # 尝试取消并等待
            self._cancel_current_delivery()
            for worker in active_workers:
                if not worker.wait(5000):
                    QtWidgets.QMessageBox.information(
                        self,
                        "正在执行任务",
                        "当前正在发送、保存草稿或测试连接，请等待其完成后再退出。",
                    )
                    event.ignore()
                    return
            event.accept()
            return

        if self._quit_requested or self._tray is None:
            event.accept()
            return

        if not self._runtime.queued_task_ids and not self._smtp_connected:
            event.accept()
            return

        self.hide()
        event.ignore()
        if not self._close_tip_shown and self._tray is not None:
            self._tray.showMessage(
                "已最小化到托盘",
                "程序会继续保留 SMTP 会话与定时队列。需要彻底退出时，请在托盘图标上右键选择“退出程序”。",
                QtWidgets.QSystemTrayIcon.Information,
                5000,
            )
            self._close_tip_shown = True

    closeEvent = _handle_close_event

    def _set_smtp_status(self, connected: bool, text: str) -> None:
        self._smtp_connected = connected
        if connected:
            self._smtp_status_badge.set_status(f"已连接 · {text}", "success")
        else:
            self._smtp_status_badge.set_status(text, "neutral")
        self._refresh_ui_state()

    def _apply_smtp_connection_success(
        self,
        *,
        from_email: str,
        password: str,
        imap_host: str,
        imap_port: int,
        info: str,
    ) -> str:
        """应用一次成功的连接测试：更新状态、保存配置；返回展示用提示文本。"""
        self._smtp_cfg = SmtpConfig(
            host=self._smtp_cfg.host,
            port=self._smtp_cfg.port,
            security=self._smtp_cfg.security,
            username=from_email,
        )
        self._smtp_password = password
        self._imap_host = imap_host.strip() or DEFAULT_IMAP_HOST
        self._imap_port = int(imap_port) if imap_port else DEFAULT_IMAP_PORT_SSL
        self._connect_btn.setEnabled(True)
        self._set_smtp_status(True, info)
        try:
            saved_path = self._save_connection_profile(from_email=from_email, smtp_password=password)
        except Exception as exc:
            return (
                f"连接成功：{info}\n\n"
                f"连接信息未能写入 `{self._conn_config_path}`：{exc}\n"
                "本次连接可继续使用，但下次启动可能仍需重新填写。"
            )
        self._mark_connection_profile_saved(saved_path)
        return f"连接成功：{info}\n已保存登录信息：{saved_path}"

    def _try_auto_connect(self) -> bool:
        """静默自动重连：凭据已保存且空闲时使用，按节流间隔重试。

        与手动连接的区别：不弹窗、失败不清空已存授权码，
        供定时调度在 SMTP 掉线/重启后自动恢复发送能力。
        """
        if self._smtp_connected or self._smtp_worker is not None:
            return False
        if not self._smtp_cfg.username.strip() or not self._smtp_password:
            return False
        now = time.monotonic()
        if now - self._last_auto_connect_at < AUTO_CONNECT_RETRY_SECONDS:
            return False
        self._last_auto_connect_at = now
        self._connect_btn.setEnabled(False)
        self._set_smtp_status(False, "正在自动连接…")
        worker = TestSmtpWorker(self._smtp_cfg, self._smtp_password)
        self._smtp_worker = worker
        worker.finished_ok.connect(self._handle_auto_connect_ok)
        worker.finished_err.connect(self._handle_auto_connect_err)
        worker.start()
        return True

    def _handle_auto_connect_ok(self, info: str) -> None:
        self._smtp_worker = None
        self._connect_btn.setEnabled(True)
        self._set_smtp_status(True, info)

    def _handle_auto_connect_err(self, _tb: str) -> None:
        self._smtp_worker = None
        self._connect_btn.setEnabled(True)
        # 状态徽标即反馈；下个调度周期会自动重试，不弹窗打扰
        self._set_smtp_status(False, "自动连接失败")
