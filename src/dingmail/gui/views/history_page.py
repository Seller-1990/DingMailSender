"""运行历史页：runs 输出目录浏览与打开。"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from ...task_delivery import DeliveryStatus
from ..widgets import SectionCard, make_button, label_value


def _fit_text(value: str, limit: int = 42) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


class HistoryPage(QtWidgets.QWidget):
    def __init__(self, runs_root: Path, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._runs_root = runs_root

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        card = SectionCard("运行历史", "每次发送或保存草稿都会生成一个 runs 输出目录。")
        self._list = QtWidgets.QListWidget()
        self._list.setWordWrap(True)
        self._list.itemDoubleClicked.connect(lambda _item: self._open_selected())
        card.body_layout.addWidget(self._list, 1)

        self._summary_label = label_value("")
        self._summary_label.setObjectName("MutedLabel")
        card.body_layout.addWidget(self._summary_label)

        button_row = QtWidgets.QHBoxLayout()
        button_row.setSpacing(8)
        refresh_btn = make_button("刷新")
        open_btn = make_button("打开选中目录", variant="primary")
        refresh_btn.clicked.connect(self.refresh)
        open_btn.clicked.connect(self._open_selected)
        button_row.addStretch(1)
        button_row.addWidget(refresh_btn)
        button_row.addWidget(open_btn)
        card.body_layout.addLayout(button_row)

        root.addWidget(card)
        self.refresh()

    def refresh(self) -> None:
        self._list.clear()
        self._summary_label.setText("")
        if not self._runs_root.exists():
            self._list.addItem("暂无运行记录。")
            return
        try:
            run_dirs = sorted(
                (path for path in self._runs_root.iterdir() if path.is_dir()),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            self._list.addItem("运行目录无法读取。")
            return
        if not run_dirs:
            self._list.addItem("暂无运行记录。")
            return
        for path in run_dirs[:100]:
            item = QtWidgets.QListWidgetItem(self._summarize_run(path))
            item.setSizeHint(QtCore.QSize(0, 58))
            item.setData(QtCore.Qt.UserRole, str(path))
            self._list.addItem(item)
        self._list.setCurrentRow(0)
        self._summary_label.setText(f"共 {len(run_dirs)} 个运行目录（显示最近 100 个）。")

    @staticmethod
    def _action_label(statuses: list[DeliveryStatus]) -> str:
        actions = {status.action for status in statuses}
        if "draft" in actions and "send" in actions:
            return "混合运行"
        if "draft" in actions:
            return "保存草稿"
        if "send" in actions:
            return "发送"
        return "运行"

    def _summarize_run(self, path: Path) -> str:
        modified = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        manifest_csv = path / "manifest.csv"
        if not manifest_csv.is_file():
            return f"{path.name} | {modified}\n未找到 manifest.csv"
        try:
            with manifest_csv.open("r", encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
        except Exception as exc:
            return f"{path.name} | {modified}\n读取 manifest 失败：{_fit_text(str(exc), 60)}"

        statuses: list[DeliveryStatus] = []
        unknown = 0
        for row in rows:
            try:
                statuses.append(DeliveryStatus(str(row.get("status") or "").strip()))
            except ValueError:
                unknown += 1
        success = sum(1 for status in statuses if status.is_success)
        failed = len(statuses) - success
        latest_error = next((str(row.get("error") or "").strip() for row in rows if row.get("error")), "")
        summary = f"{self._action_label(statuses)} · 共 {len(rows)} · 成功 {success} · 失败 {failed}"
        if unknown:
            summary += f" · 未识别状态 {unknown}"
        if latest_error:
            summary += f" · 最近错误：{_fit_text(latest_error)}"
        return f"{path.name} | {modified}\n{summary}"

    def _open_selected(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        raw_path = item.data(QtCore.Qt.UserRole)
        if raw_path:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(raw_path))
