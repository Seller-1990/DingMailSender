from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from ..rendering import markdown_to_html
from ..task_models import MailTask
from ..task_service import render_task_preview_html, validate_task
from .dialog_helpers import dialog_label
from .widgets import make_button


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

        self._summary = dialog_label("")
        self._meta = dialog_label("")
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
        path_label = dialog_label(str(path))
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
