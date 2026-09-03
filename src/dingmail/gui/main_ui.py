from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from ..model import SmtpConfig
from ..paths import packages_dir
from ..task_service import EMAIL_RE
from .main_support import TASK_FILTERS, error_summary, label_value
from .task_table_model import TaskFilterProxyModel, TaskTableModel
from .theme import apply_workbench_theme, repolish
from .widgets import MetricTile, SectionPanel, StatusTag, make_button
from .workers import TestSmtpWorker


class MainUiMixin:
    def _build_ui(self) -> None:
        root = QtWidgets.QWidget()
        self.setCentralWidget(root)
        shell = QtWidgets.QVBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        shell.addWidget(self._build_main_area(), 1)
        self._install_shortcuts()
        self._refresh_smtp_summary_labels()

    def _build_main_area(self) -> QtWidgets.QWidget:
        main = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(main)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        layout.addWidget(self._build_topbar())
        layout.addWidget(self._build_commandbar())
        layout.addLayout(self._build_metrics())

        self._workspace_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self._workspace_splitter.setObjectName("WorkspaceSplitter")
        self._workspace_splitter.addWidget(self._build_task_panel())
        self._workspace_splitter.addWidget(self._build_detail_panel())
        self._workspace_splitter.setStretchFactor(0, 3)
        self._workspace_splitter.setStretchFactor(1, 2)
        self._workspace_splitter.setSizes([840, 560])
        layout.addWidget(self._workspace_splitter, 1)
        layout.addWidget(self._build_runbar())
        return main

    def _build_topbar(self) -> QtWidgets.QFrame:
        topbar = QtWidgets.QFrame()
        topbar.setObjectName("Topbar")
        layout = QtWidgets.QHBoxLayout(topbar)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        title_box = QtWidgets.QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(3)
        title = QtWidgets.QLabel("DingMail 工作台")
        title.setObjectName("AppTitle")
        subtitle = QtWidgets.QLabel("草稿复核优先")
        subtitle.setObjectName("MutedLabel")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)

        self._package_label = label_value(
            f"任务包：未导入\n工作目录：{self._home_dir}\n模板目录：{packages_dir(self._home_dir)}"
        )
        self._package_label.setObjectName("MutedLabel")

        self._account_label = label_value("")
        self._account_label.setObjectName("MutedLabel")
        self._server_label = label_value("")
        self._server_label.setObjectName("MutedLabel")
        self._profile_source_label = label_value("")
        self._profile_source_label.setObjectName("MutedLabel")
        self._smtp_status_badge = StatusTag("未连接", variant="neutral")
        self._connect_btn = make_button("连接设置")
        self._connect_btn.clicked.connect(self._show_connection_settings)

        connection_box = QtWidgets.QVBoxLayout()
        connection_box.setContentsMargins(0, 0, 0, 0)
        connection_box.setSpacing(4)
        connection_row = QtWidgets.QHBoxLayout()
        connection_row.setContentsMargins(0, 0, 0, 0)
        connection_row.setSpacing(8)
        connection_row.addWidget(self._smtp_status_badge)
        connection_row.addWidget(self._connect_btn)
        connection_box.addLayout(connection_row)
        connection_box.addWidget(self._account_label)
        connection_box.addWidget(self._server_label)
        connection_box.addWidget(self._profile_source_label)

        layout.addLayout(title_box)
        layout.addWidget(self._package_label, 1)
        layout.addLayout(connection_box)
        return topbar

    def _build_commandbar(self) -> QtWidgets.QFrame:
        commandbar = QtWidgets.QFrame()
        commandbar.setObjectName("Topbar")
        layout = QtWidgets.QHBoxLayout(commandbar)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        self._download_package_btn = make_button("下载模板")
        self._download_package_btn.clicked.connect(self._download_template_package)
        self._import_package_btn = make_button("导入任务包")
        self._import_package_btn.clicked.connect(self._import_package)
        self._reload_package_btn = make_button("重新加载")
        self._reload_package_btn.clicked.connect(self._reload_package)
        self._open_package_btn = make_button("打开目录")
        self._open_package_btn.clicked.connect(self._open_package_dir)
        self._open_tasks_btn = make_button("打开 tasks.xlsx")
        self._open_tasks_btn.clicked.connect(self._open_tasks_excel)
        self._open_readme_btn = make_button("操作说明")
        self._open_readme_btn.clicked.connect(self._show_readme_preview)

        for button in [
            self._download_package_btn,
            self._import_package_btn,
            self._reload_package_btn,
            self._open_package_btn,
            self._open_tasks_btn,
        ]:
            layout.addWidget(button)
        layout.addStretch(1)
        self._app_settings_btn = make_button("发送设置")
        self._app_settings_btn.clicked.connect(self._show_app_settings)
        layout.addWidget(self._app_settings_btn)
        layout.addWidget(self._open_readme_btn)
        return commandbar

    def _build_metrics(self) -> QtWidgets.QGridLayout:
        metrics = QtWidgets.QGridLayout()
        metrics.setContentsMargins(0, 0, 0, 0)
        metrics.setHorizontalSpacing(12)
        metrics.setVerticalSpacing(12)
        specs = [
            ("enabled", "启用任务", "0", "当前任务包"),
            ("ready", "可保存草稿", "0", "校验通过"),
            ("issues", "需修正", "0", "路径或邮箱异常"),
            ("drafts", "已保存草稿", "0", "本轮状态"),
            ("queued", "定时队列", "0", "托盘调度"),
        ]
        for col, (key, title, value, detail) in enumerate(specs):
            tile = MetricTile(title, value, detail)
            self._metric_tiles[key] = tile
            metrics.addWidget(tile, 0, col)
        return metrics

    def _build_task_panel(self) -> SectionPanel:
        panel = SectionPanel("邮件任务", "筛选任务，选中后在右侧复核并保存草稿。")

        self._add_btn = make_button("新增")
        self._edit_btn = make_button("编辑")
        self._copy_btn = make_button("复制")
        self._delete_btn = make_button("删除", variant="danger")
        self._add_btn.clicked.connect(self._add_task)
        self._edit_btn.clicked.connect(self._edit_selected_task)
        self._copy_btn.clicked.connect(self._duplicate_selected_tasks)
        self._delete_btn.clicked.connect(self._delete_selected_tasks)
        for button in [self._add_btn, self._edit_btn, self._copy_btn, self._delete_btn]:
            panel.actions_layout.addWidget(button)

        filter_row = QtWidgets.QHBoxLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.setSpacing(8)
        for key, label in TASK_FILTERS.items():
            button = make_button(label, variant="primary" if key == "all" else "default")
            button.clicked.connect(lambda _checked=False, filter_key=key: self._set_task_filter(filter_key))
            self._filter_buttons[key] = button
            filter_row.addWidget(button)
        filter_row.addStretch(1)

        self._task_search_input = QtWidgets.QLineEdit()
        self._task_search_input.setPlaceholderText("搜索收件人、主题、备注")
        self._task_search_input.setClearButtonEnabled(True)
        self._task_search_input.textChanged.connect(lambda _text: self._on_search_text_changed())
        filter_row.addWidget(self._task_search_input)

        self._task_model = TaskTableModel(self)
        self._task_model.set_data_source(self._tasks, self._runtime)
        self._task_proxy = TaskFilterProxyModel(self)
        self._task_proxy.setSourceModel(self._task_model)

        self._task_table = QtWidgets.QTableView()
        self._task_table.setModel(self._task_proxy)
        self._task_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._task_table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self._task_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._task_table.setAlternatingRowColors(True)
        # 说明列单行省略，全文进 tooltip；固定行高，避免长错误撑爆行高与行高重算开销
        self._task_table.setWordWrap(False)
        self._task_table.setTextElideMode(QtCore.Qt.ElideRight)
        self._task_table.verticalHeader().setVisible(False)
        header = self._task_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(46)
        fixed_widths = {0: 82, 4: 72, 5: 54, 6: 126}
        for col, width in fixed_widths.items():
            header.setSectionResizeMode(col, QtWidgets.QHeaderView.Interactive)
            self._task_table.setColumnWidth(col, width)
        for col in (1, 2, 3, 7):
            header.setSectionResizeMode(col, QtWidgets.QHeaderView.Stretch)

        self._task_table.selectionModel().selectionChanged.connect(self._on_task_selection_changed)
        self._task_table.doubleClicked.connect(lambda _index: self._edit_selected_task())

        # 搜索防抖：停止输入 200ms 后才触发过滤
        self._search_debounce = QtCore.QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(200)
        self._search_debounce.timeout.connect(self._apply_search_text)

        panel.body_layout.addLayout(filter_row)
        panel.body_layout.addWidget(self._task_table, 1)
        return panel

    def _on_search_text_changed(self) -> None:
        self._search_debounce.start()

    def _apply_search_text(self) -> None:
        self._task_proxy.set_search_text(self._task_search_input.text())

    def _build_detail_panel(self) -> SectionPanel:
        panel = SectionPanel("草稿复核", "保存草稿是主路径；立即发送作为风险操作保留。")
        panel.setMinimumWidth(440)

        self._detail_status_tag = StatusTag("未选择", variant="neutral")
        panel.actions_layout.addWidget(self._detail_status_tag)

        self._detail_title_label = label_value("未选择任务")
        self._detail_title_label.setObjectName("SectionTitle")
        self._detail_to_label = label_value("收件人：-")
        self._detail_cc_label = label_value("抄送人：-")
        self._detail_markdown_label = label_value("Markdown：-")
        self._detail_attachments_label = label_value("附件：-")
        self._detail_schedule_label = label_value("定时：-")
        self._detail_issue_label = label_value("请选择一条任务查看详情。")
        self._detail_issue_label.setObjectName("MutedLabel")

        for label in [
            self._detail_title_label,
            self._detail_to_label,
            self._detail_cc_label,
            self._detail_markdown_label,
            self._detail_attachments_label,
            self._detail_schedule_label,
            self._detail_issue_label,
        ]:
            panel.body_layout.addWidget(label)

        self._detail_preview_browser = QtWidgets.QTextBrowser()
        self._detail_preview_browser.setOpenExternalLinks(False)
        self._detail_preview_browser.setOpenLinks(False)
        self._detail_preview_browser.setMinimumHeight(340)
        self._detail_preview_browser.anchorClicked.connect(self._confirm_open_link_from_detail)
        panel.body_layout.addWidget(self._detail_preview_browser, 1)

        action_row = QtWidgets.QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        self._save_drafts_btn = make_button("保存草稿", variant="primary")
        self._preview_btn = make_button("预览")
        self._queue_btn = make_button("加入队列")
        self._send_now_btn = make_button("立即发送", variant="danger")
        self._save_drafts_btn.clicked.connect(self._save_selected_to_drafts)
        self._preview_btn.clicked.connect(self._preview_selected_task)
        self._queue_btn.clicked.connect(self._queue_selected_tasks)
        self._send_now_btn.clicked.connect(self._send_selected_now)
        for button in [self._save_drafts_btn, self._preview_btn, self._queue_btn, self._send_now_btn]:
            action_row.addWidget(button)
        panel.body_layout.addLayout(action_row)
        return panel

    def _build_runbar(self) -> QtWidgets.QFrame:
        runbar = QtWidgets.QFrame()
        runbar.setObjectName("Runbar")
        layout = QtWidgets.QHBoxLayout(runbar)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        self._status_label = label_value("当前没有任务包。")
        self._status_label.setObjectName("MutedLabel")
        self._progress_bar = QtWidgets.QProgressBar()
        self._progress_bar.setVisible(False)
        self._progress_bar.setFixedWidth(200)
        self._progress_bar.setAlignment(QtCore.Qt.AlignCenter)
        self._retry_btn = make_button("重试失败项")
        self._retry_btn.clicked.connect(self._retry_failed_tasks)
        self._open_last_run_btn = make_button("运行历史")
        self._open_last_run_btn.clicked.connect(self._show_run_history)
        footer_help_btn = make_button("定时说明", variant="ghost")
        footer_help_btn.clicked.connect(self._show_schedule_help)

        layout.addWidget(self._status_label, 1)
        layout.addWidget(self._progress_bar)
        layout.addWidget(self._retry_btn)
        layout.addWidget(self._open_last_run_btn)
        layout.addWidget(footer_help_btn)
        return runbar

    def _apply_styles(self) -> None:
        apply_workbench_theme(self)

    def _install_shortcuts(self) -> None:
        for sequence, slot in (
            ("Ctrl+F", self._focus_task_search),
            ("Ctrl+N", self._add_task),
            ("Ctrl+D", self._save_selected_to_drafts),
            ("F5", self._reload_package),
        ):
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(sequence), self)
            shortcut.activated.connect(slot)
        # Del 仅在表格持有焦点时触发，避免抢占输入框的编辑删除键
        delete_shortcut = QtGui.QShortcut(QtGui.QKeySequence.StandardKey.Delete, self._task_table)
        delete_shortcut.setContext(QtCore.Qt.WidgetShortcut)
        delete_shortcut.activated.connect(self._delete_selected_tasks)

    def _focus_task_search(self) -> None:
        self._task_search_input.setFocus()
        self._task_search_input.selectAll()

    def _show_connection_settings(self) -> None:
        if self._smtp_worker is not None:
            QtWidgets.QMessageBox.information(self, "请稍候", "正在连接测试中，请稍后再打开连接设置。")
            return
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("连接设置")
        dialog.setMinimumWidth(480)

        root = QtWidgets.QVBoxLayout(dialog)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        form = QtWidgets.QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        email_input = QtWidgets.QLineEdit(self._smtp_cfg.username)
        email_input.setPlaceholderText("name@example.com")
        password_input = QtWidgets.QLineEdit()
        password_input.setEchoMode(QtWidgets.QLineEdit.Password)
        password_input.setPlaceholderText("留空沿用已保存授权码" if self._smtp_password else "SMTP 授权码")
        form.addRow("发件邮箱", email_input)
        form.addRow("SMTP 授权码", password_input)
        root.addLayout(form)

        imap_group = QtWidgets.QGroupBox("IMAP 草稿箱（保存草稿用）")
        imap_form = QtWidgets.QFormLayout(imap_group)
        imap_host_input = QtWidgets.QLineEdit(self._imap_host)
        imap_port_input = QtWidgets.QSpinBox()
        imap_port_input.setRange(1, 65535)
        imap_port_input.setValue(self._imap_port)
        imap_form.addRow("IMAP 服务器", imap_host_input)
        imap_form.addRow("IMAP 端口", imap_port_input)
        root.addWidget(imap_group)

        status_label = QtWidgets.QLabel("")
        status_label.setObjectName("DialogHint")
        status_label.setWordWrap(True)
        root.addWidget(status_label)

        button_row = QtWidgets.QHBoxLayout()
        button_row.addStretch(1)
        cancel_btn = make_button("取消")
        connect_button = make_button("连接并测试", variant="primary")
        cancel_btn.clicked.connect(dialog.reject)
        connect_button.clicked.connect(
            lambda: self._test_connection_in_dialog(
                dialog, email_input, password_input, imap_host_input, imap_port_input,
                status_label, connect_button,
            )
        )
        button_row.addWidget(cancel_btn)
        button_row.addWidget(connect_button)
        root.addLayout(button_row)

        dialog.exec()

    def _test_connection_in_dialog(
        self,
        dialog: QtWidgets.QDialog,
        email_input: QtWidgets.QLineEdit,
        password_input: QtWidgets.QLineEdit,
        imap_host_input: QtWidgets.QLineEdit,
        imap_port_input: QtWidgets.QSpinBox,
        status_label: QtWidgets.QLabel,
        connect_button: QtWidgets.QPushButton,
    ) -> None:
        email = email_input.text().strip()
        password = password_input.text().strip() or self._smtp_password
        imap_host = imap_host_input.text().strip()
        imap_port = imap_port_input.value()

        def _show_status(text: str, *, error: bool = False) -> None:
            status_label.setText(text)
            status_label.setObjectName("ErrorLabel" if error else "DialogHint")
            repolish(status_label)

        if not EMAIL_RE.match(email):
            _show_status("请输入正确的发件邮箱。", error=True)
            return
        if not password:
            _show_status("请输入 SMTP 授权码（已保存授权码可留空沿用）。", error=True)
            return
        if self._smtp_worker is not None:
            # 定时调度的自动重连可能刚好在对话框打开期间启动；覆盖引用会让运行中的 QThread 失去管理
            _show_status("已有连接测试进行中，请稍候再试。", error=True)
            return

        connect_button.setEnabled(False)
        _show_status("正在连接…")
        worker = TestSmtpWorker(
            SmtpConfig(
                host=self._smtp_cfg.host,
                port=self._smtp_cfg.port,
                security=self._smtp_cfg.security,
                username=email,
            ),
            password,
        )
        self._smtp_worker = worker

        def _on_ok(info: str) -> None:
            self._smtp_worker = None
            message = self._apply_smtp_connection_success(
                from_email=email,
                password=password,
                imap_host=imap_host,
                imap_port=imap_port,
                info=info,
            )
            if dialog.isVisible():
                _show_status(message)
                # 留出读取成功提示的时间后自动关闭
                QtCore.QTimer.singleShot(400, dialog.accept)

        def _on_err(tb: str) -> None:
            self._smtp_worker = None
            if dialog.isVisible():
                connect_button.setEnabled(True)
                _show_status(f"连接失败：{error_summary(tb)}（可修改后重试）", error=True)

        worker.finished_ok.connect(_on_ok)
        worker.finished_err.connect(_on_err)
        worker.start()

    def _show_app_settings(self) -> None:
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("发送设置")
        dialog.setMinimumWidth(440)

        root = QtWidgets.QVBoxLayout(dialog)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        form = QtWidgets.QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        rate_input = QtWidgets.QDoubleSpinBox()
        rate_input.setRange(0.0, 60.0)
        rate_input.setDecimals(1)
        rate_input.setSingleStep(0.5)
        rate_input.setSuffix(" 秒")
        rate_input.setValue(self._send_rate_limit_seconds)
        retention_input = QtWidgets.QSpinBox()
        retention_input.setRange(0, 3650)
        retention_input.setSuffix(" 天")
        retention_input.setSpecialValueText("永久保留")
        retention_input.setValue(self._runs_retention_days)
        form.addRow("任务间隔", rate_input)
        form.addRow("运行记录保留", retention_input)
        root.addLayout(form)

        tip = QtWidgets.QLabel(
            "任务间隔：每封邮件之间的等待时间，用于降低邮箱服务器压力。\n"
            "运行记录保留：超过该天数的 runs 输出目录会在下次启动时自动清理。"
        )
        tip.setObjectName("DialogHint")
        tip.setWordWrap(True)
        root.addWidget(tip)

        button_row = QtWidgets.QHBoxLayout()
        button_row.addStretch(1)
        cancel_btn = make_button("取消")
        save_btn = make_button("保存", variant="primary")

        def _save() -> None:
            self._apply_app_settings(
                rate_limit_seconds=rate_input.value(),
                retention_days=retention_input.value(),
            )
            dialog.accept()

        cancel_btn.clicked.connect(dialog.reject)
        save_btn.clicked.connect(_save)
        button_row.addWidget(cancel_btn)
        button_row.addWidget(save_btn)
        root.addLayout(button_row)

        dialog.exec()

    def _show_schedule_help(self) -> None:
        QtWidgets.QMessageBox.information(
            self,
            "定时发送说明",
            "V1 使用本机托盘常驻调度。\n"
            "关闭主窗口后程序仍在右下角托盘运行，到点会自动发送。\n"
            "如果从托盘菜单点“退出程序”，未发送的定时任务会一起结束。",
        )
