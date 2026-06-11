from __future__ import annotations

import csv
import uuid
from datetime import datetime
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from ..rendering import markdown_to_html
from ..task_models import MailTask
from ..task_package import package_relpath
from ..task_service import render_task_preview_html, validate_task
from .widgets import make_button


def _dialog_label(text: str) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
    label.setWordWrap(True)
    return label


def _fit(value: str, limit: int = 28) -> str:
    text = str(value or "").replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


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


class PreviewDialog(QtWidgets.QDialog):
    def __init__(
        self,
        *,
        tasks: list[MailTask],
        start_index: int,
        package_dir: Path,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("邮件预览")
        self.resize(980, 720)
        self._tasks = tasks
        self._index = start_index
        self._package_dir = package_dir

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        self._summary = _dialog_label("")
        self._meta = _dialog_label("")
        self._issue = QtWidgets.QLabel()
        self._issue.setWordWrap(True)
        self._issue.setObjectName("ErrorLabel")

        self._browser = QtWidgets.QTextBrowser()
        self._browser.setOpenExternalLinks(False)
        self._browser.setOpenLinks(False)
        self._browser.anchorClicked.connect(self._confirm_open_link)

        nav = QtWidgets.QHBoxLayout()
        self._prev_btn = QtWidgets.QPushButton("上一封")
        self._next_btn = QtWidgets.QPushButton("下一封")
        close_btn = QtWidgets.QPushButton("关闭")
        self._prev_btn.clicked.connect(self._show_prev)
        self._next_btn.clicked.connect(self._show_next)
        close_btn.clicked.connect(self.accept)
        nav.addWidget(self._prev_btn)
        nav.addWidget(self._next_btn)
        nav.addStretch(1)
        nav.addWidget(close_btn)

        root.addWidget(self._summary)
        root.addWidget(self._meta)
        root.addWidget(self._issue)
        root.addWidget(self._browser, 1)
        root.addLayout(nav)
        self._render_current()

    def _show_prev(self) -> None:
        if self._index > 0:
            self._index -= 1
            self._render_current()

    def _show_next(self) -> None:
        if self._index < len(self._tasks) - 1:
            self._index += 1
            self._render_current()

    def _confirm_open_link(self, url: QtCore.QUrl) -> None:
        reply = QtWidgets.QMessageBox.question(self, "打开链接", f"是否打开此链接？\n{url.toString()}")
        if reply == QtWidgets.QMessageBox.Yes:
            QtGui.QDesktopServices.openUrl(url)

    def _render_current(self) -> None:
        task = self._tasks[self._index]
        scheduled_text = task.scheduled_at.strftime("%Y-%m-%d %H:%M:%S") if task.scheduled_at else "未设置"
        attachments = ", ".join(task.attachment_paths) if task.attachment_paths else "无附件"
        self._summary.setText(
            f"第 {self._index + 1} / {len(self._tasks)} 封\n"
            f"收件人：{'; '.join(task.to_recipients) or '未填写'}\n"
            f"抄送人：{'; '.join(task.cc_recipients) or '无'}\n"
            f"主题：{task.subject or '未填写'}"
        )
        self._meta.setText(
            f"Markdown：{task.markdown_path or '未填写'}\n"
            f"附件：{attachments}\n"
            f"定时发送：{'是' if task.schedule_enabled else '否'} / {scheduled_text}\n"
            f"备注：{task.note or '无'}"
        )
        issues = validate_task(task, self._package_dir)
        self._issue.setText("\n".join(issues) if issues else "")
        try:
            self._browser.setHtml(render_task_preview_html(task, self._package_dir))
        except Exception as exc:
            self._browser.setHtml("")
            prefix = f"{self._issue.text()}\n" if self._issue.text() else ""
            self._issue.setText(f"{prefix}预览失败：{exc}".strip())

        self._prev_btn.setEnabled(self._index > 0)
        self._next_btn.setEnabled(self._index < len(self._tasks) - 1)


def _wrap_doc_preview_html(body_html: str) -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>"
        "body{font-family:'Microsoft YaHei UI','Segoe UI',sans-serif;font-size:14px;line-height:1.75;"
        "color:#1f2937;background:#fff;margin:18px;}"
        "h1,h2,h3{color:#172033;margin:20px 0 8px;}h1{font-size:22px;}h2{font-size:18px;}h3{font-size:15px;}"
        "p{margin:8px 0;}li{margin:5px 0;}code{background:#f3f6fa;border:1px solid #d8e0ea;"
        "border-radius:4px;padding:1px 5px;}table{border-collapse:collapse;width:100%;}"
        "th,td{border:1px solid #d8e0ea;padding:6px 8px;vertical-align:top;}"
        "</style></head><body>"
        f"{body_html}"
        "</body></html>"
    )


class MarkdownPreviewDialog(QtWidgets.QDialog):
    def __init__(self, *, title: str, path: Path, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(920, 720)
        self._path = path

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title_label = QtWidgets.QLabel(title)
        title_label.setObjectName("DialogTitle")
        path_label = _dialog_label(str(path))
        path_label.setObjectName("DialogHint")
        root.addWidget(title_label)
        root.addWidget(path_label)

        self._browser = QtWidgets.QTextBrowser()
        self._browser.setOpenExternalLinks(False)
        self._browser.setOpenLinks(False)
        self._browser.anchorClicked.connect(self._confirm_open_link)
        root.addWidget(self._browser, 1)

        buttons = QtWidgets.QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        open_dir_btn = make_button("打开文件位置")
        open_external_btn = make_button("外部打开")
        close_btn = make_button("关闭", variant="primary")
        open_dir_btn.clicked.connect(self._open_dir)
        open_external_btn.clicked.connect(self._open_external)
        close_btn.clicked.connect(self.accept)
        buttons.addStretch(1)
        buttons.addWidget(open_dir_btn)
        buttons.addWidget(open_external_btn)
        buttons.addWidget(close_btn)
        root.addLayout(buttons)
        self._load_markdown()

    def _load_markdown(self) -> None:
        try:
            markdown_text = self._path.read_text(encoding="utf-8")
            self._browser.setHtml(_wrap_doc_preview_html(markdown_to_html(markdown_text)))
        except Exception as exc:
            self._browser.setHtml(_wrap_doc_preview_html(f"<p>读取操作说明失败：{exc}</p>"))

    def _confirm_open_link(self, url: QtCore.QUrl) -> None:
        reply = QtWidgets.QMessageBox.question(self, "打开链接", f"是否打开此链接？\n{url.toString()}")
        if reply == QtWidgets.QMessageBox.Yes:
            QtGui.QDesktopServices.openUrl(url)

    def _open_dir(self) -> None:
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self._path.parent)))

    def _open_external(self) -> None:
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self._path)))


class RunHistoryDialog(QtWidgets.QDialog):
    def __init__(self, *, runs_root: Path, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("运行历史")
        self.resize(760, 520)
        self._runs_root = runs_root

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QtWidgets.QLabel("运行历史")
        title.setObjectName("DialogTitle")
        hint = QtWidgets.QLabel("每次发送或保存草稿后都会生成一个 runs 输出目录。")
        hint.setObjectName("DialogHint")
        hint.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(hint)

        self._list = QtWidgets.QListWidget()
        self._list.setWordWrap(True)
        self._list.itemDoubleClicked.connect(lambda _item: self._open_selected())
        root.addWidget(self._list, 1)

        buttons = QtWidgets.QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        refresh_btn = make_button("刷新")
        open_btn = make_button("打开选中", variant="primary")
        close_btn = make_button("关闭")
        refresh_btn.clicked.connect(self._load_runs)
        open_btn.clicked.connect(self._open_selected)
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(refresh_btn)
        buttons.addStretch(1)
        buttons.addWidget(open_btn)
        buttons.addWidget(close_btn)
        root.addLayout(buttons)
        self._load_runs()

    @staticmethod
    def _action_label(statuses: list[str]) -> str:
        has_draft = any(status.startswith("draft") for status in statuses)
        has_send = any(status == "sent" or status.startswith("send") for status in statuses)
        if has_draft and has_send:
            return "混合运行"
        if has_draft:
            return "保存草稿"
        if has_send:
            return "发送"
        return "运行"

    @classmethod
    def _summarize_run(cls, path: Path) -> str:
        modified = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        manifest_csv = path / "manifest.csv"
        if not manifest_csv.is_file():
            return f"{path.name} | {modified}\n未找到 manifest.csv\n{path}"

        try:
            with manifest_csv.open("r", encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
        except Exception as exc:
            return f"{path.name} | {modified}\n读取 manifest 失败：{_fit(str(exc), 60)}\n{path}"

        statuses = [str(row.get("status") or "").strip() for row in rows]
        success = sum(1 for status in statuses if status in {"sent", "draft_saved"})
        failed = sum(
            1 for status in statuses if status in {"send_error", "draft_error", "send_skipped", "draft_skipped"}
        )
        latest_error = next((str(row.get("error") or "").strip() for row in rows if row.get("error")), "")
        summary = f"{cls._action_label(statuses)} · 共 {len(rows)} · 成功 {success} · 失败 {failed}"
        if latest_error:
            summary += f" · 最近错误：{_fit(latest_error, 42)}"
        return f"{path.name} | {modified}\n{summary}\n{path}"

    def _load_runs(self) -> None:
        self._list.clear()
        if not self._runs_root.exists():
            self._list.addItem("暂无运行记录。")
            return
        run_dirs = sorted(
            [path for path in self._runs_root.iterdir() if path.is_dir()],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not run_dirs:
            self._list.addItem("暂无运行记录。")
            return
        for path in run_dirs[:100]:
            item = QtWidgets.QListWidgetItem(self._summarize_run(path))
            item.setSizeHint(QtCore.QSize(0, 62))
            item.setData(QtCore.Qt.UserRole, str(path))
            self._list.addItem(item)
        self._list.setCurrentRow(0)

    def _open_selected(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        raw_path = item.data(QtCore.Qt.UserRole)
        if not raw_path:
            return
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(raw_path)))
