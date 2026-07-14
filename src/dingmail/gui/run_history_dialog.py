from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from ..task_delivery import DeliveryStatus
from .dialog_helpers import fit_text
from .widgets import make_button


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
    def _action_label(statuses: list[DeliveryStatus]) -> str:
        actions = {status.action for status in statuses}
        has_draft = "draft" in actions
        has_send = "send" in actions
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
            return f"{path.name} | {modified}\n读取 manifest 失败：{fit_text(str(exc), 60)}\n{path}"

        raw_statuses = [str(row.get("status") or "").strip() for row in rows]
        statuses: list[DeliveryStatus] = []
        unknown_count = 0
        for raw_status in raw_statuses:
            try:
                statuses.append(DeliveryStatus(raw_status))
            except ValueError:
                unknown_count += 1
        success = sum(1 for status in statuses if status.is_success)
        failed = len(statuses) - success
        latest_error = next((str(row.get("error") or "").strip() for row in rows if row.get("error")), "")
        summary = f"{cls._action_label(statuses)} · 共 {len(rows)} · 成功 {success} · 失败 {failed}"
        if unknown_count:
            summary += f" · 未识别状态 {unknown_count}"
        if latest_error:
            summary += f" · 最近错误：{fit_text(latest_error, 42)}"
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
