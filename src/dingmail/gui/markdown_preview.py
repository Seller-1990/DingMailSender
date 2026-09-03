"""Markdown 文档预览对话框（操作说明等）。"""
from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from ..rendering import markdown_to_html
from .theme import BORDER, SURFACE_ALT, TEXT_MUTED
from .widgets import make_button, label_value


def _wrap_doc_preview_html(body_html: str) -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>"
        "body{font-family:'Microsoft YaHei UI','Segoe UI',sans-serif;font-size:14px;line-height:1.75;"
        "color:#1f2937;background:#fff;margin:18px;}"
        "h1,h2,h3{color:#172033;margin:20px 0 8px;}h1{font-size:22px;}h2{font-size:18px;}h3{font-size:15px;}"
        f"p{{margin:8px 0;}}li{{margin:5px 0;}}code{{background:{SURFACE_ALT};border:1px solid {BORDER};"
        "border-radius:4px;padding:1px 5px;}table{border-collapse:collapse;width:100%;}"
        f"th,td{{border:1px solid {BORDER};padding:6px 8px;vertical-align:top;}}"
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
        root.setSpacing(10)

        title_label = QtWidgets.QLabel(title)
        title_label.setObjectName("SectionTitle")
        path_label = label_value(str(path))
        path_label.setStyleSheet(f"color: {TEXT_MUTED};")
        root.addWidget(title_label)
        root.addWidget(path_label)

        self._browser = QtWidgets.QTextBrowser()
        self._browser.setOpenExternalLinks(False)
        self._browser.setOpenLinks(False)
        self._browser.anchorClicked.connect(self._confirm_open_link)
        root.addWidget(self._browser, 1)

        buttons = QtWidgets.QHBoxLayout()
        open_dir_btn = make_button("打开文件位置")
        open_external_btn = make_button("外部打开")
        close_btn = make_button("关闭", variant="primary")
        open_dir_btn.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(str(self._path.parent))
        ))
        open_external_btn.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(str(self._path))
        ))
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
            self._browser.setHtml(_wrap_doc_preview_html(f"<p>读取失败：{exc}</p>"))

    def _confirm_open_link(self, url: QtCore.QUrl) -> None:
        reply = QtWidgets.QMessageBox.question(self, "打开链接", f"是否打开此链接？\n{url.toString()}")
        if reply == QtWidgets.QMessageBox.Yes:
            QtGui.QDesktopServices.openUrl(url)
