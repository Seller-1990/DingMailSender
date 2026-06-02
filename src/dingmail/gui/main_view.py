from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from ..model import SmtpConfig
from ..task_models import MailTask
from ..task_service import render_task_preview_html
from .main_support import EMAIL_RE, TASK_FILTERS, error_summary
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
        self._refresh_task_table()

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

    def _task_matches_filter(self, task: MailTask) -> bool:
        if self._active_filter == "all":
            return True
        if self._active_filter == "ready":
            return task.status == "可发送"
        if self._active_filter == "issue":
            return task.status == "校验失败"
        if self._active_filter == "draft":
            return task.status == "草稿已保存"
        if self._active_filter == "queued":
            return task.status == "已加入定时队列"
        if self._active_filter == "failed":
            return task.status in {"发送失败", "草稿保存失败"}
        return True

    def _task_matches_search(self, task: MailTask) -> bool:
        query = self._task_search_input.text().strip().lower() if hasattr(self, "_task_search_input") else ""
        if not query:
            return True
        haystack = " ".join(
            [
                "; ".join(task.to_recipients),
                "; ".join(task.cc_recipients),
                task.subject,
                task.markdown_path,
                task.note,
                task.error_message,
                task.last_send_result,
            ]
        ).lower()
        return query in haystack

    def _resize_task_columns(self) -> None:
        if not hasattr(self, "_task_table"):
            return
        width = max(self._task_table.viewport().width(), 640)
        fixed_widths = {0: 82, 4: 72, 5: 54, 6: 126}
        fixed_total = sum(fixed_widths.values())
        remaining = max(width - fixed_total - 20, 320)
        flex_widths = {
            1: int(remaining * 0.22),
            2: int(remaining * 0.23),
            3: int(remaining * 0.25),
            7: int(remaining * 0.30),
        }
        for col, size in {**fixed_widths, **flex_widths}.items():
            self._task_table.setColumnWidth(col, max(46, size))

    def _refresh_metrics(self) -> None:
        enabled_tasks = [task for task in self._tasks if task.enabled]
        ready = sum(1 for task in self._tasks if task.status == "可发送")
        issues = sum(1 for task in self._tasks if task.status == "校验失败")
        drafts = sum(1 for task in self._tasks if task.status == "草稿已保存")
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
        issue_text = task.error_message or task.last_send_result or task.note or "当前任务没有错误提示。"
        self._detail_status_tag.set_status(task.status, status_tone(task.status))
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

    def _build_tray(self) -> None:
        if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = None
            return

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

    def _handle_resize_event(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._resize_task_columns()

    closeEvent = _handle_close_event
    resizeEvent = _handle_resize_event

    def _set_smtp_status(self, connected: bool, text: str) -> None:
        self._smtp_connected = connected
        if connected:
            self._smtp_status_badge.set_status(f"已连接 · {text}", "success")
        else:
            self._smtp_status_badge.set_status(text, "neutral")
        self._refresh_ui_state()

    def _connect_smtp(self, from_email: str, password: str) -> None:
        if not from_email:
            QtWidgets.QMessageBox.warning(self, "缺少发件邮箱", "请输入发件邮箱后再连接。")
            return
        if not EMAIL_RE.match(from_email):
            QtWidgets.QMessageBox.warning(self, "邮箱格式错误", "发件邮箱格式不正确，请检查后重试。")
            return

        if not password:
            QtWidgets.QMessageBox.warning(self, "缺少授权码", "请输入 SMTP 授权码后再连接。")
            return

        self._prepare_smtp_connect(from_email)
        worker = TestSmtpWorker(self._smtp_cfg, password)
        self._smtp_worker = worker
        worker.finished_ok.connect(lambda info: self._handle_smtp_connected(from_email, password, info))
        worker.finished_err.connect(self._handle_smtp_connect_error)
        worker.start()

    def _prepare_smtp_connect(self, from_email: str) -> None:
        self._smtp_cfg = SmtpConfig(
            host=self._smtp_cfg.host,
            port=self._smtp_cfg.port,
            security=self._smtp_cfg.security,
            username=from_email,
        )
        self._refresh_smtp_summary_labels()

        self._connect_btn.setEnabled(False)
        self._set_smtp_status(False, "正在连接…")

    def _handle_smtp_connected(self, from_email: str, password: str, info: str) -> None:
        self._smtp_worker = None
        self._smtp_password = password
        self._connect_btn.setEnabled(True)
        self._set_smtp_status(True, info)
        location_note = ""
        save_warning = ""
        try:
            saved_path = self._save_connection_profile(from_email=from_email, smtp_password=password)
            location_note = f"\n已保存登录信息：{saved_path}"
        except Exception as exc:
            save_warning = (
                f"\n\n连接信息未能写入 `{self._conn_config_path}`：{exc}\n"
                "本次连接可继续使用，但下次启动可能仍需重新填写。"
            )
        QtWidgets.QMessageBox.information(self, "连接成功", f"SMTP 连接成功：{info}{location_note}{save_warning}")

    def _handle_smtp_connect_error(self, tb: str) -> None:
        self._smtp_worker = None
        self._smtp_password = ""
        self._connect_btn.setEnabled(True)
        self._set_smtp_status(False, "连接失败")
        self._show_error_dialog("连接失败", f"SMTP 连接失败：{error_summary(tb)}", details=tb)
