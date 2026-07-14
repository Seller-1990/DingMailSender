from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from ..task_models import MailTask
from ..task_package import package_relpath


def _split_email_input(text: str) -> list[str]:
    raw = str(text or "").replace("；", ";").replace(",", ";")
    return [item.strip() for item in raw.split(";") if item.strip()]


class TaskEditorDialog(QtWidgets.QDialog):
    def __init__(self, *, task: MailTask, package_dir: Path, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑邮件任务")
        self.resize(760, 640)
        self._package_dir = package_dir
        self._task_id = task.task_id or uuid.uuid4().hex

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        title = QtWidgets.QLabel("轻量编辑器")
        title.setObjectName("DialogTitle")
        hint = QtWidgets.QLabel("一行代表一封邮件。推荐优先使用相对任务包目录的路径，例如 `content/示例正文.md`。")
        hint.setObjectName("DialogHint")
        hint.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(hint)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        self._build_form(form, task)
        root.addLayout(form, 1)

        button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        root.addWidget(button_box)

    def _build_form(self, form: QtWidgets.QFormLayout, task: MailTask) -> None:
        self._enabled_check = QtWidgets.QCheckBox("启用此任务")
        self._enabled_check.setChecked(task.enabled)
        form.addRow("是否启用", self._enabled_check)

        self._to_input = QtWidgets.QLineEdit("; ".join(task.to_recipients))
        self._to_input.setPlaceholderText("多个邮箱用分号分隔")
        form.addRow("收件人", self._to_input)

        self._cc_input = QtWidgets.QLineEdit("; ".join(task.cc_recipients))
        self._cc_input.setPlaceholderText("可为空；多个邮箱用分号分隔")
        form.addRow("抄送人", self._cc_input)

        self._subject_input = QtWidgets.QLineEdit(task.subject)
        self._subject_input.setPlaceholderText("例如：3月月度通知")
        form.addRow("主题", self._subject_input)

        self._intro_input = QtWidgets.QPlainTextEdit(task.intro_text)
        self._intro_input.setPlaceholderText("例如：**总：晚上好**\n\n这里填写每封邮件独有的开头或补充说明。")
        self._intro_input.setMinimumHeight(120)
        form.addRow("开头/补充内容", self._intro_input)

        form.addRow("Markdown 路径", self._build_markdown_row(task.markdown_path))
        form.addRow("附件", self._build_attachment_box(task.attachment_paths))
        form.addRow("发送时间", self._build_schedule_box(task))

        self._note_input = QtWidgets.QLineEdit(task.note)
        self._note_input.setPlaceholderText("可选备注，例如：只发项目组")
        form.addRow("备注", self._note_input)

    def _build_markdown_row(self, markdown_path: str) -> QtWidgets.QWidget:
        markdown_row = QtWidgets.QHBoxLayout()
        self._markdown_input = QtWidgets.QLineEdit(markdown_path)
        self._markdown_input.setPlaceholderText("例如：content/示例正文.md")
        browse_markdown_btn = QtWidgets.QPushButton("选择 Markdown")
        browse_markdown_btn.clicked.connect(self._choose_markdown_file)
        markdown_row.addWidget(self._markdown_input, 1)
        markdown_row.addWidget(browse_markdown_btn)
        markdown_widget = QtWidgets.QWidget()
        markdown_widget.setLayout(markdown_row)
        return markdown_widget

    def _build_attachment_box(self, attachment_paths: list[str]) -> QtWidgets.QWidget:
        attachment_box = QtWidgets.QWidget()
        attachment_layout = QtWidgets.QVBoxLayout(attachment_box)
        attachment_layout.setContentsMargins(0, 0, 0, 0)
        attachment_layout.setSpacing(8)

        self._attachments_list = QtWidgets.QListWidget()
        self._attachments_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        for item in attachment_paths:
            self._attachments_list.addItem(item)

        attachment_actions = QtWidgets.QHBoxLayout()
        add_attachment_btn = QtWidgets.QPushButton("添加附件")
        remove_attachment_btn = QtWidgets.QPushButton("移除选中")
        add_attachment_btn.clicked.connect(self._add_attachments)
        remove_attachment_btn.clicked.connect(self._remove_attachments)
        attachment_actions.addWidget(add_attachment_btn)
        attachment_actions.addWidget(remove_attachment_btn)
        attachment_actions.addStretch(1)

        attachment_tip = QtWidgets.QLabel("附件支持多个文件。优先放在任务包的 `attachments/` 目录内。")
        attachment_tip.setObjectName("InlineTip")
        attachment_tip.setWordWrap(True)
        attachment_layout.addWidget(self._attachments_list)
        attachment_layout.addLayout(attachment_actions)
        attachment_layout.addWidget(attachment_tip)
        return attachment_box

    def _build_schedule_box(self, task: MailTask) -> QtWidgets.QWidget:
        schedule_box = QtWidgets.QWidget()
        schedule_layout = QtWidgets.QHBoxLayout(schedule_box)
        schedule_layout.setContentsMargins(0, 0, 0, 0)
        schedule_layout.setSpacing(10)
        self._schedule_check = QtWidgets.QCheckBox("定时发送")
        self._schedule_check.setChecked(task.schedule_enabled)
        self._schedule_edit = QtWidgets.QDateTimeEdit()
        self._schedule_edit.setCalendarPopup(True)
        self._schedule_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self._schedule_edit.setDateTime(QtCore.QDateTime(task.scheduled_at or datetime.now()))
        self._schedule_edit.setEnabled(task.schedule_enabled)
        self._schedule_check.toggled.connect(self._schedule_edit.setEnabled)
        schedule_layout.addWidget(self._schedule_check)
        schedule_layout.addWidget(self._schedule_edit, 1)
        return schedule_box

    def _normalize_path(self, raw_path: str) -> str:
        text = str(raw_path or "").strip()
        if not text:
            return ""
        return package_relpath(self._package_dir, Path(text))

    def _choose_markdown_file(self) -> None:
        start_dir = self._package_dir / "content"
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "选择 Markdown 文件",
            str(start_dir if start_dir.exists() else self._package_dir),
            "Markdown (*.md *.markdown);;所有文件 (*.*)",
        )
        if file_path:
            try:
                self._markdown_input.setText(self._normalize_path(file_path))
            except ValueError as exc:
                QtWidgets.QMessageBox.warning(self, "路径超出任务包", str(exc))

    def _add_attachments(self) -> None:
        start_dir = self._package_dir / "attachments"
        file_paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            "选择附件",
            str(start_dir if start_dir.exists() else self._package_dir),
            "所有文件 (*.*)",
        )
        for file_path in file_paths:
            try:
                normalized = self._normalize_path(file_path)
            except ValueError as exc:
                QtWidgets.QMessageBox.warning(self, "路径超出任务包", str(exc))
                continue
            if normalized and not self._attachments_list.findItems(normalized, QtCore.Qt.MatchExactly):
                self._attachments_list.addItem(normalized)

    def _remove_attachments(self) -> None:
        for item in self._attachments_list.selectedItems():
            self._attachments_list.takeItem(self._attachments_list.row(item))

    def task(self) -> MailTask:
        attachment_paths = [
            self._attachments_list.item(i).text().strip()
            for i in range(self._attachments_list.count())
        ]
        scheduled_at = self._schedule_edit.dateTime().toPython().replace(microsecond=0)
        return MailTask(
            task_id=self._task_id,
            enabled=self._enabled_check.isChecked(),
            to_recipients=_split_email_input(self._to_input.text()),
            cc_recipients=_split_email_input(self._cc_input.text()),
            subject=self._subject_input.text().strip(),
            intro_text=self._intro_input.toPlainText().strip(),
            markdown_path=self._markdown_input.text().strip(),
            attachment_paths=attachment_paths,
            schedule_enabled=self._schedule_check.isChecked(),
            scheduled_at=scheduled_at if self._schedule_check.isChecked() else None,
            note=self._note_input.text().strip(),
        )
