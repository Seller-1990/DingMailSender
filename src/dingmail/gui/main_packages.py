from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from ..paths import packages_dir, program_dir, runs_dir
from ..task_package import (
    PACKAGE_README_FILENAME,
    TASKS_FILENAME,
    ensure_unique_task_ids,
    load_tasks_from_package,
    save_tasks_to_package,
)
from ..task_template import create_template_package
from .dialogs import MarkdownPreviewDialog, RunHistoryDialog
from .main_support import now_stamp


class MainPackageMixin:
    def _package_root(self) -> Path:
        return packages_dir(self._home_dir)

    def _ensure_within_home(self, package_dir: Path) -> None:
        home = self._home_dir.resolve()
        current = package_dir.resolve()
        if home not in current.parents and current != home:
            raise ValueError(f"任务包目录必须位于 {home} 下。请先把任务包放进 `packages` 目录。")

    def _download_template_package(self) -> None:
        if self._delivery_is_busy(title="请稍候", message="当前正在发送或保存草稿，请完成后再创建任务包。"):
            return
        name, ok = QtWidgets.QInputDialog.getText(
            self,
            "下载任务包模板",
            "任务包目录名（会创建在 packages 目录下）",
            text=f"任务包_{now_stamp()}",
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            return

        package_dir = (self._package_root() / name).resolve()
        if package_dir.exists() and any(package_dir.iterdir()):
            QtWidgets.QMessageBox.warning(self, "目录已存在", f"目录已存在且非空：{package_dir}")
            return

        create_template_package(package_dir)
        self._load_package(package_dir)
        QtWidgets.QMessageBox.information(
            self,
            "模板已创建",
            f"已创建任务包：{package_dir}\n你可以先打开 tasks.xlsx 直接改，也可以双击表格内任务逐条调整。",
        )

    def _import_package(self) -> None:
        if self._delivery_is_busy(title="请稍候", message="当前正在发送或保存草稿，请完成后再导入任务包。"):
            return
        selected = QtWidgets.QFileDialog.getExistingDirectory(self, "选择任务包目录", str(self._package_root()))
        if not selected:
            return

        package_dir = Path(selected).resolve()
        try:
            self._ensure_within_home(package_dir)
            self._load_package(package_dir)
        except Exception as exc:
            self._show_error_dialog("导入失败", f"导入任务包失败：{exc}")

    def _reload_package(self) -> None:
        if self._delivery_is_busy(title="请稍候", message="当前正在发送或保存草稿，请完成后再重新加载任务包。"):
            return
        if not self._package_dir:
            QtWidgets.QMessageBox.information(self, "未导入", "请先导入任务包目录。")
            return
        try:
            self._load_package(self._package_dir)
        except Exception as exc:
            self._show_error_dialog("重新加载失败", f"重新加载任务包失败：{exc}")

    def _load_package(self, package_dir: Path) -> None:
        tasks = load_tasks_from_package(package_dir)
        repairs = ensure_unique_task_ids(tasks)
        repair_notice = ""
        if repairs:
            try:
                save_tasks_to_package(package_dir, tasks)
                repair_notice = "\n".join(repairs[:10]) + "\n\n任务表中的重复/缺失任务ID已自动修复并写回 tasks.xlsx。"
            except Exception as exc:
                repair_notice = "\n".join(repairs[:10]) + f"\n\n任务ID已在内存中修复，但写回 tasks.xlsx 失败：{exc}"
        self._package_dir = package_dir
        self._tasks = tasks
        self._runtime.reset_loaded_tasks(package_dir, self._tasks)
        self._refresh_task_table()
        self._refresh_ui_state()
        if repair_notice:
            QtWidgets.QMessageBox.warning(self, "任务ID已自动修复", repair_notice)

    def _open_path(self, path: Path) -> None:
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))

    def _open_package_dir(self) -> None:
        if self._package_dir:
            self._open_path(self._package_dir)

    def _open_tasks_excel(self) -> None:
        if self._package_dir:
            path = self._package_dir / TASKS_FILENAME
            if path.exists():
                self._open_path(path)

    def _show_readme_preview(self) -> None:
        candidates: list[Path] = []
        if self._package_dir:
            candidates.append(self._package_dir / PACKAGE_README_FILENAME)
        candidates.extend(
            [
                program_dir() / "操作说明_GUI版.md",
                Path.cwd() / "操作说明_GUI版.md",
            ]
        )
        readme_path = next((path for path in candidates if path.exists()), None)
        if readme_path is None:
            QtWidgets.QMessageBox.warning(self, "未找到操作说明", "当前任务包和程序目录下都没有找到操作说明文件。")
            return
        dialog = MarkdownPreviewDialog(title="操作说明", path=readme_path, parent=self)
        dialog.exec()

    def _show_run_history(self) -> None:
        dialog = RunHistoryDialog(runs_root=runs_dir(self._home_dir), parent=self)
        dialog.exec()
