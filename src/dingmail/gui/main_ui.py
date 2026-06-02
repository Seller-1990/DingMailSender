from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from ..paths import packages_dir
from .main_support import TASK_FILTERS, label_value
from .theme import apply_workbench_theme
from .widgets import MetricTile, SectionPanel, StatusTag, make_button, set_button_variant


class MainUiMixin:
    def _build_ui(self) -> None:
        root = QtWidgets.QWidget()
        self.setCentralWidget(root)
        shell = QtWidgets.QVBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        shell.addWidget(self._build_main_area(), 1)
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
        self._task_search_input.textChanged.connect(lambda _text: self._refresh_task_table())
        filter_row.addWidget(self._task_search_input)

        self._task_table = QtWidgets.QTableWidget()
        self._task_table.setColumnCount(8)
        self._task_table.setHorizontalHeaderLabels(["状态", "收件人", "主题", "正文", "附件", "定时", "发送时间", "说明"])
        self._task_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._task_table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self._task_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._task_table.setAlternatingRowColors(True)
        self._task_table.setWordWrap(True)
        self._task_table.setTextElideMode(QtCore.Qt.ElideNone)
        self._task_table.verticalHeader().setVisible(False)
        self._task_table.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        self._task_table.itemSelectionChanged.connect(self._on_task_selection_changed)
        self._task_table.itemDoubleClicked.connect(lambda _item: self._edit_selected_task())
        header = self._task_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QtWidgets.QHeaderView.Interactive)

        panel.body_layout.addLayout(filter_row)
        panel.body_layout.addWidget(self._task_table, 1)
        return panel

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
        self._retry_btn = make_button("重试失败项")
        self._retry_btn.clicked.connect(self._retry_failed_tasks)
        self._open_last_run_btn = make_button("运行历史")
        self._open_last_run_btn.clicked.connect(self._show_run_history)
        footer_help_btn = make_button("定时说明", variant="ghost")
        footer_help_btn.clicked.connect(self._show_schedule_help)

        layout.addWidget(self._status_label, 1)
        layout.addWidget(self._retry_btn)
        layout.addWidget(self._open_last_run_btn)
        layout.addWidget(footer_help_btn)
        return runbar

    def _apply_styles(self) -> None:
        apply_workbench_theme(self)

    def _show_smtp_help(self) -> None:
        QtWidgets.QMessageBox.information(
            self,
            "连接说明",
            "请填写发件邮箱和 SMTP 授权码。\n"
            f"连接成功后会保存到用户配置目录：{self._conn_config_path}\n"
            "Windows 下授权码会以系统 DPAPI 方式加密保存。\n"
            "默认发信服务器：smtp.qiye.aliyun.com:465（SSL）。",
        )

    def _show_connection_settings(self) -> None:
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("连接设置")
        dialog.resize(460, 220)

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

        button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Cancel)
        connect_button = button_box.addButton("连接并测试", QtWidgets.QDialogButtonBox.AcceptRole)
        set_button_variant(connect_button, "primary")
        button_box.rejected.connect(dialog.reject)
        button_box.accepted.connect(dialog.accept)
        root.addWidget(button_box)

        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        password = password_input.text().strip() or self._smtp_password
        self._connect_smtp(email_input.text().strip(), password)

    def _show_schedule_help(self) -> None:
        QtWidgets.QMessageBox.information(
            self,
            "定时发送说明",
            "V1 使用本机托盘常驻调度。\n"
            "关闭主窗口后程序仍在右下角托盘运行，到点会自动发送。\n"
            "如果从托盘菜单点“退出程序”，未发送的定时任务会一起结束。",
        )
