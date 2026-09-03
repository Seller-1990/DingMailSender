"""任务页：任务列表 + 筛选/搜索 + 右侧大预览 + 投递操作。"""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from ...task_models import MailTask
from ...task_service import render_task_preview_html
from ...task_status import TaskStatus
from ..theme import repolish, status_tone
from ..task_table_model import TaskFilterProxyModel, TaskTableModel
from ..widgets import TASK_FILTERS, Banner, SectionCard, StatusTag, make_button, label_value


class TasksPage(QtWidgets.QWidget):
    addTask = QtCore.Signal()
    editTask = QtCore.Signal()
    duplicateTasks = QtCore.Signal()
    deleteTasks = QtCore.Signal()
    saveDrafts = QtCore.Signal()
    sendNow = QtCore.Signal()
    queueTasks = QtCore.Signal()
    retryFailed = QtCore.Signal()
    downloadTemplate = QtCore.Signal()
    importPackage = QtCore.Signal()
    reloadPackage = QtCore.Signal()
    openPackageDir = QtCore.Signal()
    openTasksExcel = QtCore.Signal()
    openReadme = QtCore.Signal()
    splitterChanged = QtCore.Signal(list)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = None
        self._connected = False
        self._busy = False

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self._splitter.addWidget(self._build_task_card())
        self._splitter.addWidget(self._build_preview_card())
        self._splitter.setStretchFactor(0, 3)
        self._splitter.setStretchFactor(1, 2)
        self._splitter.setSizes([940, 560])
        self._splitter.splitterMoved.connect(self._on_splitter_moved)
        root.addWidget(self._splitter)

        self._splitter_save_timer = QtCore.QTimer(self)
        self._splitter_save_timer.setSingleShot(True)
        self._splitter_save_timer.setInterval(500)
        self._splitter_save_timer.timeout.connect(
            lambda: self.splitterChanged.emit(list(self._splitter.sizes()))
        )

        # 增量校验 timer：分批校验避免首次加载 UI 冻结
        self._validate_timer = QtCore.QTimer(self)
        self._validate_timer.setInterval(100)
        self._validate_timer.timeout.connect(self._incremental_validate)

        # 搜索防抖
        self._search_debounce = QtCore.QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(200)
        self._search_debounce.timeout.connect(self._apply_search_text)

    def set_splitter_sizes(self, sizes: list[int]) -> None:
        if len(sizes) == 2 and all(v > 0 for v in sizes):
            self._splitter.setSizes(list(sizes))

    def splitter_sizes(self) -> list[int]:
        return list(self._splitter.sizes())

    def _on_splitter_moved(self, _pos: int, _index: int) -> None:
        self._splitter_save_timer.start()

    # ---- UI 构建 ----

    def _build_task_card(self) -> QtWidgets.QWidget:
        card = SectionCard("邮件任务", "筛选任务，选中后在右侧复核并保存草稿。")

        for text, slot in (
            ("下载模板", self.downloadTemplate),
            ("导入任务包", self.importPackage),
            ("重新加载", self.reloadPackage),
            ("打开目录", self.openPackageDir),
            ("打开 tasks.xlsx", self.openTasksExcel),
            ("操作说明", self.openReadme),
        ):
            button = make_button(text)
            button.clicked.connect(slot)
            card.actions_layout.addWidget(button)

        body = QtWidgets.QVBoxLayout()
        body.setSpacing(8)

        self._banner = Banner()
        body.addWidget(self._banner)

        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(6)
        self._add_btn = make_button("新增")
        self._edit_btn = make_button("编辑")
        self._copy_btn = make_button("复制")
        self._delete_btn = make_button("删除", variant="danger")
        self._add_btn.clicked.connect(self.addTask)
        self._edit_btn.clicked.connect(self.editTask)
        self._copy_btn.clicked.connect(self.duplicateTasks)
        self._delete_btn.clicked.connect(self.deleteTasks)
        for button in (self._add_btn, self._edit_btn, self._copy_btn, self._delete_btn):
            toolbar.addWidget(button)
        toolbar.addStretch(1)

        self._search_input = QtWidgets.QLineEdit()
        self._search_input.setPlaceholderText("搜索收件人、主题、备注 (Ctrl+F)")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.setFixedWidth(240)
        self._search_input.textChanged.connect(lambda _text: self._search_debounce.start())
        toolbar.addWidget(self._search_input)
        body.addLayout(toolbar)

        filter_row = QtWidgets.QHBoxLayout()
        filter_row.setSpacing(6)
        self._filter_buttons: dict[str, QtWidgets.QPushButton] = {}
        for key, label in TASK_FILTERS.items():
            button = make_button(label)
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, k=key: self._set_filter(k))
            self._filter_buttons[key] = button
            filter_row.addWidget(button)
        filter_row.addStretch(1)
        body.addLayout(filter_row)

        self._model = TaskTableModel(self)
        self._proxy = TaskFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)

        self._table = QtWidgets.QTableView()
        self._table.setModel(self._proxy)
        self._table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setWordWrap(False)
        self._table.setTextElideMode(QtCore.Qt.ElideRight)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(46)
        for col, width in {0: 78, 4: 64, 5: 48, 6: 122}.items():
            header.setSectionResizeMode(col, QtWidgets.QHeaderView.Interactive)
            self._table.setColumnWidth(col, width)
        for col in (1, 2, 3, 7):
            header.setSectionResizeMode(col, QtWidgets.QHeaderView.Stretch)
        self._table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self._table.doubleClicked.connect(lambda _index: self.editTask.emit())

        delete_shortcut = QtGui.QShortcut(QtGui.QKeySequence.StandardKey.Delete, self._table)
        delete_shortcut.setContext(QtCore.Qt.WidgetShortcut)
        delete_shortcut.activated.connect(self.deleteTasks)

        body.addWidget(self._table, 1)

        footer = QtWidgets.QHBoxLayout()
        footer.setSpacing(8)
        self._progress_bar = QtWidgets.QProgressBar()
        self._progress_bar.setVisible(False)
        self._progress_bar.setFixedWidth(180)
        footer.addWidget(self._progress_bar)
        footer.addStretch(1)
        self._retry_btn = make_button("重试失败项")
        self._retry_btn.clicked.connect(self.retryFailed)
        footer.addWidget(self._retry_btn)
        body.addLayout(footer)

        card.body_layout.addLayout(body)
        return card

    def _build_preview_card(self) -> QtWidgets.QWidget:
        card = SectionCard("邮件预览", "选中任务即预览；保存草稿是主路径，立即发送为风险操作。")
        self._detail_status_tag = StatusTag("未选择", variant="neutral")
        card.actions_layout.addWidget(self._detail_status_tag)

        self._detail_title_label = label_value("未选择任务")
        self._detail_title_label.setObjectName("SectionTitle")
        self._detail_to_label = label_value("收件人：-")
        self._detail_cc_label = label_value("抄送人：-")
        self._detail_markdown_label = label_value("Markdown：-")
        self._detail_attachments_label = label_value("附件：-")
        self._detail_schedule_label = label_value("定时：-")
        self._detail_issue_label = label_value("请选择任务查看详情与预览。")
        self._detail_issue_label.setObjectName("MutedLabel")
        self._detail_issue_label.setWordWrap(True)

        for label in (
            self._detail_title_label,
            self._detail_to_label,
            self._detail_cc_label,
            self._detail_markdown_label,
            self._detail_attachments_label,
            self._detail_schedule_label,
            self._detail_issue_label,
        ):
            card.body_layout.addWidget(label)

        self._preview_browser = QtWidgets.QTextBrowser()
        self._preview_browser.setOpenExternalLinks(False)
        self._preview_browser.setOpenLinks(False)
        self._preview_browser.setPlaceholderText("选择左侧任务后，这里会渲染 Markdown 正文预览。")
        self._preview_browser.anchorClicked.connect(self._confirm_open_link)
        card.body_layout.addWidget(self._preview_browser, 1)

        action_row = QtWidgets.QHBoxLayout()
        action_row.setSpacing(8)
        self._save_drafts_btn = make_button("保存草稿", variant="primary")
        self._queue_btn = make_button("加入队列")
        self._send_now_btn = make_button("立即发送", variant="danger")
        self._save_drafts_btn.clicked.connect(self.saveDrafts)
        self._queue_btn.clicked.connect(self.queueTasks)
        self._send_now_btn.clicked.connect(self.sendNow)
        action_row.addWidget(self._save_drafts_btn, 1)
        action_row.addWidget(self._queue_btn)
        action_row.addWidget(self._send_now_btn)
        card.body_layout.addLayout(action_row)
        return card

    # ---- 数据绑定 ----

    def bind_controller(self, controller) -> None:
        self._controller = controller
        self._sync_model()
        controller.tasksChanged.connect(self._on_tasks_changed)

    def _on_tasks_changed(self) -> None:
        self._sync_model()
        self.start_validation()
        self.refresh_selection()

    def _sync_model(self) -> None:
        if self._controller is None:
            return
        if self._model.bound_to(self._controller.tasks):
            # 同一列表对象：只刷新展示，不 reset（避免丢失选择）
            self._model.refresh()
            return
        self._model.set_data_source(self._controller.tasks, self._controller.runtime)

    def start_validation(self) -> None:
        if not self._validate_timer.isActive():
            self._validate_timer.start()

    def _incremental_validate(self) -> None:
        if self._controller is None or not self._controller.tasks:
            self._validate_timer.stop()
            return
        all_done = self._controller.runtime.refresh_runtime_state(self._controller.tasks, max_validate=5)
        if self._model.refresh():
            # 校验状态变化后重刷过滤，让"需修正/可保存草稿"等筛选立即反映新行
            self._proxy.refilter()
        self.refresh_selection_summary()
        if all_done:
            self._validate_timer.stop()

    # ---- 筛选/搜索 ----

    def _set_filter(self, key: str) -> None:
        if key not in TASK_FILTERS:
            key = "all"
        self._proxy.set_filter_key(key)
        for name, button in self._filter_buttons.items():
            button.setChecked(name == key)
            button.setProperty("variant", "primary" if name == key else "default")
            repolish(button)

    def _apply_search_text(self) -> None:
        self._proxy.set_search_text(self._search_input.text())

    def focus_search(self) -> None:
        self._search_input.setFocus()
        self._search_input.selectAll()

    # ---- 选择与详情 ----

    def selected_rows(self) -> list[int]:
        selection_model = self._table.selectionModel()
        rows = selection_model.selectedRows() if selection_model else []
        return sorted({self._proxy.mapToSource(index).row() for index in rows if index.isValid()})

    def selected_tasks(self) -> list[MailTask]:
        if self._controller is None:
            return []
        return [self._controller.tasks[i] for i in self.selected_rows() if 0 <= i < len(self._controller.tasks)]

    def select_row(self, row: int) -> None:
        self._table.selectRow(row)

    def _on_selection_changed(self, *_args) -> None:
        self.refresh_selection()

    def refresh_selection(self) -> None:
        self.refresh_selection_summary()
        self.refresh_preview()

    def refresh_selection_summary(self) -> None:
        if self._controller is None:
            return
        rows = self.selected_rows()
        if len(rows) > 1:
            self._render_batch_detail([self._controller.tasks[i] for i in rows if 0 <= i < len(self._controller.tasks)])
        else:
            self._update_action_buttons()

    def refresh_preview(self) -> None:
        if self._controller is None:
            return
        rows = self.selected_rows()
        if len(rows) > 1:
            # 多选：批量摘要已由 refresh_selection_summary 渲染，不要覆盖
            return
        if len(rows) != 1:
            self._render_empty_detail(len(rows))
            return
        task = self._controller.tasks[rows[0]]
        runtime = self._controller.runtime
        state = runtime.state_for(task)
        scheduled_text = task.scheduled_at.strftime("%Y-%m-%d %H:%M:%S") if task.scheduled_at else "未设置"
        self._detail_status_tag.set_status(state.status.label, status_tone(state.status))
        self._detail_title_label.setText(task.subject or "未填写主题")
        self._detail_to_label.setText(f"收件人：{'; '.join(task.to_recipients) or '未填写'}")
        self._detail_cc_label.setText(f"抄送人：{'; '.join(task.cc_recipients) or '无'}")
        self._detail_markdown_label.setText(f"Markdown：{task.markdown_path or '未填写'}")
        self._detail_attachments_label.setText(
            f"附件：{'; '.join(task.attachment_paths) if task.attachment_paths else '无'}"
        )
        self._detail_schedule_label.setText(f"定时：{'是' if task.schedule_enabled else '否'} / {scheduled_text}")
        self._detail_issue_label.setText(
            f"说明：{state.error_message or state.last_result or task.note or '当前任务没有错误提示。'}"
        )
        self._render_preview_html(task)

    def _render_preview_html(self, task: MailTask) -> None:
        if self._controller is None or self._controller.package_dir is None:
            self._preview_browser.setHtml("")
            return
        try:
            self._preview_browser.setHtml(render_task_preview_html(task, self._controller.package_dir))
        except Exception as exc:
            self._preview_browser.setHtml(f"<p>预览失败：{exc}</p>")

    def _render_batch_detail(self, tasks: list[MailTask]) -> None:
        runtime = self._controller.runtime
        enabled = [task for task in tasks if task.enabled]
        ready = sum(1 for task in enabled if runtime.status_for(task) == TaskStatus.READY)
        issues = sum(1 for task in enabled if runtime.status_for(task) == TaskStatus.VALIDATION_FAILED)
        self._detail_status_tag.set_status(f"已选择 {len(tasks)} 条", "info")
        self._detail_title_label.setText("批量操作")
        self._detail_to_label.setText(f"已启用：{len(enabled)} 条 / 共 {len(tasks)} 条")
        self._detail_cc_label.setText(f"可保存草稿：{ready} 条")
        self._detail_markdown_label.setText(f"需修正：{issues} 条")
        self._detail_attachments_label.setText("")
        self._detail_schedule_label.setText("")
        self._detail_issue_label.setText("直接使用下方「保存草稿」或「立即发送」，系统会自动跳过需修正的任务。")
        self._preview_browser.setHtml("")
        self._update_action_buttons()

    def _render_empty_detail(self, count: int) -> None:
        self._detail_status_tag.set_status("未选择", "neutral")
        self._detail_title_label.setText("未选择任务")
        self._detail_to_label.setText("收件人：-")
        self._detail_cc_label.setText("抄送人：-")
        self._detail_markdown_label.setText("Markdown：-")
        self._detail_attachments_label.setText("附件：-")
        self._detail_schedule_label.setText("定时：-")
        self._detail_issue_label.setText("请选择任务查看详情与预览。")
        self._preview_browser.setHtml("")
        self._update_action_buttons()

    def _confirm_open_link(self, url: QtCore.QUrl) -> None:
        reply = QtWidgets.QMessageBox.question(self, "打开链接", f"是否打开此链接？\n{url.toString()}")
        if reply == QtWidgets.QMessageBox.Yes:
            QtGui.QDesktopServices.openUrl(url)

    # ---- 动作状态 ----

    def update_actions(self, *, connected: bool, busy: bool) -> None:
        self._connected = connected
        self._busy = busy
        self._update_action_buttons()

    def _update_action_buttons(self) -> None:
        if self._controller is None:
            return
        has_package = self._controller.package_dir is not None
        has_selection = bool(self.selected_rows())
        has_single = len(self.selected_rows()) == 1
        can_send = has_package and self._connected and not self._busy
        can_edit = has_package and not self._busy
        self._add_btn.setEnabled(can_edit)
        self._edit_btn.setEnabled(can_edit and has_single)
        self._copy_btn.setEnabled(can_edit and has_selection)
        self._delete_btn.setEnabled(can_edit and has_selection)
        self._save_drafts_btn.setEnabled(can_send and has_selection)
        self._send_now_btn.setEnabled(can_send and has_selection)
        self._queue_btn.setEnabled(can_send and has_selection)
        self._retry_btn.setEnabled(
            can_send
            and any(
                self._controller.runtime.status_for(task) == TaskStatus.SEND_FAILED
                for task in self._controller.tasks
            )
        )

    def set_progress(self, current: int, total: int) -> None:
        self._progress_bar.setRange(0, max(total, 1))
        self._progress_bar.setValue(current)
        self._progress_bar.setFormat(f"{current} / {total}")
        self._progress_bar.setVisible(True)

    def clear_progress(self) -> None:
        self._progress_bar.setVisible(False)
        self._progress_bar.reset()

    def show_banner(self, text: str, severity: str = "info") -> None:
        self._banner.show_message(text, severity=severity)

    def clear_banner(self) -> None:
        self._banner.clear_message()

    # ---- 表格状态辅助（供队列页/主窗口复用） ----

    def status_counts(self) -> dict[str, int]:
        if self._controller is None:
            return {}
        runtime = self._controller.runtime
        return {
            "enabled": sum(1 for task in self._controller.tasks if task.enabled),
            "ready": sum(1 for task in self._controller.tasks if runtime.status_for(task) == TaskStatus.READY),
            "issues": sum(1 for task in self._controller.tasks if runtime.status_for(task) == TaskStatus.VALIDATION_FAILED),
            "drafts": sum(1 for task in self._controller.tasks if runtime.status_for(task) == TaskStatus.DRAFT_SAVED),
            "queued": len(runtime.queued_task_ids),
            "failed": sum(1 for task in self._controller.tasks if runtime.status_for(task) == TaskStatus.SEND_FAILED),
        }
