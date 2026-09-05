"""主窗口：左导航 + 页面栈 + 托盘 + 快捷键 + 调度器。"""
from __future__ import annotations

import copy
import uuid
from datetime import datetime
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from .. import __version__
from ..connection_profile import ConnectionProfileLoadError
from ..paths import connection_profile_path, detect_home_dir, ensure_layout, packages_dir, program_dir, runs_dir
from ..run_store import cleanup_old_runs
from ..task_clone import clone_task
from ..task_models import MailTask
from ..task_package import PACKAGE_README_FILENAME, TASKS_FILENAME
from ..task_status import TaskStatus
from .services import AppSettings, ConnectionService, DeliveryService, TaskController, load_app_state, save_app_state
from .task_editor_dialog import TaskEditorDialog
from .theme import apply_theme
from .views import HistoryPage, QueuePage, SettingsPage, TasksPage
from .widgets import NavRail, error_summary
from .markdown_preview import MarkdownPreviewDialog

SCHEDULE_CHECK_INTERVAL_MS = 15_000  # noqa: F401  (调度周期常量归口 constants，此处保留语义别名)
PAGES = ("tasks", "queue", "history", "settings")


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"钉钉邮件发送 v{__version__}")
        self.resize(1560, 960)
        self.setMinimumSize(1180, 720)
        apply_theme(self)

        self._home_dir = ensure_layout(detect_home_dir())
        self._state_path = self._home_dir / "state.json"
        self.app_settings: AppSettings = load_app_state(self._state_path)

        self.connection = ConnectionService(
            connection_profile_path(),
            [program_dir() / "conn_profile.json", self._home_dir / "conn_profile.json"],
            parent=self,
        )
        self._profile_load_error: str | None = None
        try:
            self.connection.load_saved_profile()
        except ConnectionProfileLoadError as exc:
            self._profile_load_error = str(exc)

        self.tasks = TaskController(self._home_dir, parent=self)
        self.delivery = DeliveryService(parent=self)

        self._last_run_dir: Path | None = None
        self._close_tip_shown = False
        self._quit_requested = False
        self._tray: QtWidgets.QSystemTrayIcon | None = None
        self._active_send: tuple[str, list[MailTask], Path] | None = None
        self._last_due_signature: tuple | None = None

        self._build_ui()
        self._build_tray()
        self._wire()
        self._install_shortcuts()
        self._restore_startup()

    # ---- UI 构建 ----

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        self._nav_rail = NavRail()
        layout.addWidget(self._nav_rail)

        self.tasks_page = TasksPage()
        self.queue_page = QueuePage()
        self.history_page = HistoryPage(runs_dir(self._home_dir))
        self.settings_page = SettingsPage(self.connection)

        self._stack = QtWidgets.QStackedWidget()
        self._pages = {
            "tasks": self.tasks_page,
            "queue": self.queue_page,
            "history": self.history_page,
            "settings": self.settings_page,
        }
        for key in PAGES:
            self._stack.addWidget(self._pages[key])
        layout.addWidget(self._stack, 1)
        self.setCentralWidget(central)

        self._status_label = QtWidgets.QLabel("")
        self._status_label.setObjectName("MutedLabel")
        self.statusBar().addWidget(self._status_label, 1)
        self._set_status("就绪。")

    def _wire(self) -> None:
        self.tasks_page.bind_controller(self.tasks)
        self.queue_page.bind_controller(self.tasks)

        self._nav_rail.pageChanged.connect(self.switch_page)
        self.tasks_page.splitterChanged.connect(self._remember_splitter)

        # 任务页动作
        self.tasks_page.addTask.connect(self.add_task)
        self.tasks_page.editTask.connect(self.edit_selected_task)
        self.tasks_page.duplicateTasks.connect(self.duplicate_selected_tasks)
        self.tasks_page.deleteTasks.connect(self.delete_selected_tasks)
        self.tasks_page.saveDrafts.connect(self.save_selected_to_drafts)
        self.tasks_page.sendNow.connect(self.send_selected_now)
        self.tasks_page.queueTasks.connect(self.queue_selected_tasks)
        self.tasks_page.retryFailed.connect(self.retry_failed_tasks)
        self.tasks_page.downloadTemplate.connect(self.download_template_package)
        self.tasks_page.importPackage.connect(self.import_package)
        self.tasks_page.reloadPackage.connect(self.reload_package)
        self.tasks_page.openPackageDir.connect(self.open_package_dir)
        self.tasks_page.openTasksExcel.connect(self.open_tasks_excel)
        self.tasks_page.openReadme.connect(self.open_readme)

        # 任务控制器
        self.tasks.noticeRaised.connect(self._on_notice)
        self.tasks.statusWritebackFailed.connect(
            lambda exc: self._set_status(f"发送状态回写 tasks.xlsx 失败：{error_summary(exc)}")
        )

        # 队列页
        self.queue_page.sendQueuedRequested.connect(lambda tasks: self.start_send(tasks, queue_mode=True))
        self.queue_page.removeQueuedRequested.connect(self.remove_from_queue)

        # 连接
        self.connection.statusChanged.connect(self._on_connection_status)
        self._nav_rail.connectClicked.connect(self._go_connect)
        self.settings_page.openHomeDirRequested.connect(lambda: self._open_path(self._home_dir))

        # 投递
        self.delivery.progressChanged.connect(self.tasks_page.set_progress)
        self.delivery.sendFinished.connect(self._on_send_finished)
        self.delivery.draftFinished.connect(self._on_draft_finished)
        self.delivery.failed.connect(self._on_delivery_failed)

        # 设置
        self.settings_page.load_send_settings(
            self.app_settings.send_rate_limit_seconds,
            self.app_settings.runs_retention_days,
        )
        self.settings_page.set_about_info(
            f"版本：v{__version__}\n工作目录：{self._home_dir}\n"
            f"任务包目录：{packages_dir(self._home_dir)}\n连接配置：{connection_profile_path()}"
        )
        self.settings_page.sendSettingsChanged.connect(self.apply_send_settings)

        # 调度器
        self._schedule_timer = QtCore.QTimer(self)
        self._schedule_timer.setInterval(SCHEDULE_CHECK_INTERVAL_MS)
        self._schedule_timer.timeout.connect(self.process_scheduled_tasks)
        self._schedule_timer.start()

    def _restore_startup(self) -> None:
        self.tasks_page.set_splitter_sizes(self.app_settings.splitter_sizes)
        self.switch_page(self.app_settings.nav_page)
        self._refresh_actions()

        if self._profile_load_error:
            self.tasks_page.show_banner(
                f"连接配置读取失败：{self._profile_load_error}\n请到「设置」重新连接并保存。", "danger"
            )
        elif self.connection.profile_warning:
            self.tasks_page.show_banner(self.connection.profile_warning, "warning")
        self.tasks_page.refresh_preview()
        self.queue_page.refresh()

        last_dir = self.app_settings.last_package_dir
        if last_dir:
            package_dir = Path(last_dir)
            if package_dir.is_dir() and self._within_home(package_dir):
                try:
                    self.load_package(package_dir, silent=True)
                except Exception:
                    pass

        if self.app_settings.runs_retention_days > 0:
            try:
                removed = cleanup_old_runs(runs_dir(self._home_dir), self.app_settings.runs_retention_days)
            except Exception:
                removed = 0
            if removed:
                self._set_status(f"已清理 {removed} 个超过 {self.app_settings.runs_retention_days} 天的运行记录目录。")

        self.connection.statusChanged.emit(self.connection.connected, "未连接")

        # 凭据齐全时启动即静默自动连接，让定时队列重启后无需人工干预
        if self.connection.smtp_cfg.username.strip() and self.connection.password:
            QtCore.QTimer.singleShot(0, self.connection.try_auto_connect)

    # ---- 导航 ----

    def switch_page(self, key: str) -> None:
        if key not in self._pages:
            key = "tasks"
        self._stack.setCurrentWidget(self._pages[key])
        self._nav_rail.set_active(key)
        if self.app_settings.nav_page != key:
            self.app_settings.nav_page = key
            self.save_settings()

    # ---- 任务包 ----

    def load_package(self, package_dir: Path, *, silent: bool = False) -> bool:
        self.tasks.load_package(package_dir, silent=silent)
        self.app_settings.last_package_dir = str(package_dir)
        self.save_settings()
        self._refresh_actions()
        return True

    def _within_home(self, package_dir: Path) -> bool:
        home = self._home_dir.resolve()
        current = package_dir.resolve()
        return home in current.parents or current == home

    def _delivery_guard(self, title: str, message: str) -> bool:
        if not self.delivery.busy:
            return False
        QtWidgets.QMessageBox.information(self, title, message)
        return True

    def download_template_package(self) -> None:
        if self._delivery_guard("请稍候", "当前正在发送或保存草稿，请完成后再创建任务包。"):
            return
        name, ok = QtWidgets.QInputDialog.getText(
            self, "下载任务包模板", "任务包目录名（会创建在 packages 目录下）",
            text=f"任务包_{datetime.now():%Y%m%d_%H%M%S}",
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        package_dir = (packages_dir(self._home_dir) / name).resolve()
        if package_dir.exists() and any(package_dir.iterdir()):
            QtWidgets.QMessageBox.warning(self, "目录已存在", f"目录已存在且非空：{package_dir}")
            return
        from ..task_template import create_template_package

        try:
            create_template_package(package_dir)
        except Exception as exc:
            self._show_error("创建模板失败", str(exc))
            return
        self.load_package(package_dir)

    def import_package(self) -> None:
        if self._delivery_guard("请稍候", "当前正在发送或保存草稿，请完成后再导入任务包。"):
            return
        selected = QtWidgets.QFileDialog.getExistingDirectory(
            self, "选择任务包目录", str(packages_dir(self._home_dir))
        )
        if not selected:
            return
        package_dir = Path(selected).resolve()
        if not self._within_home(package_dir):
            self._show_error("导入失败", f"任务包目录必须位于 {self._home_dir} 下。请先把任务包放进 packages 目录。")
            return
        try:
            self.load_package(package_dir)
        except Exception as exc:
            self._show_error("导入失败", f"导入任务包失败：{exc}")

    def reload_package(self) -> None:
        if self._delivery_guard("请稍候", "当前正在发送或保存草稿，请完成后再重新加载任务包。"):
            return
        if self.tasks.package_dir is None:
            QtWidgets.QMessageBox.information(self, "未导入", "请先导入任务包目录。")
            return
        try:
            self.load_package(self.tasks.package_dir)
        except Exception as exc:
            self._show_error("重新加载失败", f"重新加载任务包失败：{exc}")

    def open_package_dir(self) -> None:
        if self.tasks.package_dir:
            self._open_path(self.tasks.package_dir)

    def open_tasks_excel(self) -> None:
        if self.tasks.package_dir and (self.tasks.package_dir / TASKS_FILENAME).exists():
            self._open_path(self.tasks.package_dir / TASKS_FILENAME)

    def open_readme(self) -> None:
        candidates = []
        if self.tasks.package_dir:
            candidates.append(self.tasks.package_dir / PACKAGE_README_FILENAME)
        candidates.append(program_dir() / "操作说明_GUI版.md")
        readme = next((path for path in candidates if path.exists()), None)
        if readme is None:
            QtWidgets.QMessageBox.warning(self, "未找到操作说明", "当前任务包和程序目录下都没有找到操作说明文件。")
            return
        MarkdownPreviewDialog(title="操作说明", path=readme, parent=self).exec()

    # ---- 任务编辑 ----

    def _require_package(self) -> bool:
        if self.tasks.package_dir is None:
            QtWidgets.QMessageBox.information(self, "未导入任务包", "请先下载或导入任务包。")
            return False
        return True

    def _require_single_row(self) -> int | None:
        rows = self.tasks_page.selected_rows()
        if len(rows) != 1:
            QtWidgets.QMessageBox.information(self, "请选择一行", "请先选中一条任务。")
            return None
        return rows[0]

    def add_task(self) -> None:
        if self._delivery_guard("请稍候", "当前正在发送或保存草稿，请完成后再编辑任务。") or not self._require_package():
            return
        task = MailTask(task_id=uuid.uuid4().hex, enabled=True)
        dialog = TaskEditorDialog(task=task, package_dir=self.tasks.package_dir, parent=self)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        new_task = dialog.task()
        updated = copy.deepcopy(self.tasks.tasks)
        updated.append(new_task)
        if self.tasks.persist_tasks(updated, reset_runtime_task_ids=(new_task.task_id,)):
            self.tasks_page.select_row(len(updated) - 1)
            self._refresh_actions()

    def edit_selected_task(self) -> None:
        if self._delivery_guard("请稍候", "当前正在发送或保存草稿，请完成后再编辑任务。") or not self._require_package():
            return
        row = self._require_single_row()
        if row is None:
            return
        dialog = TaskEditorDialog(
            task=copy.deepcopy(self.tasks.tasks[row]), package_dir=self.tasks.package_dir, parent=self
        )
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        updated_task = dialog.task()
        updated = copy.deepcopy(self.tasks.tasks)
        updated[row] = updated_task
        if self.tasks.persist_tasks(updated, reset_runtime_task_ids=(updated_task.task_id,)):
            self.tasks_page.select_row(row)
            self._refresh_actions()

    def duplicate_selected_tasks(self) -> None:
        if self._delivery_guard("请稍候", "当前正在发送或保存草稿，请完成后再编辑任务。") or not self._require_package():
            return
        rows = self.tasks_page.selected_rows()
        if not rows:
            QtWidgets.QMessageBox.information(self, "未选择任务", "请先选择至少一条任务。")
            return
        updated = copy.deepcopy(self.tasks.tasks)
        insert_at = rows[-1] + 1
        clones = [clone_task(updated[row]) for row in rows]
        for offset, task in enumerate(clones):
            updated.insert(insert_at + offset, task)
        self.tasks.persist_tasks(updated, reset_runtime_task_ids=tuple(task.task_id for task in clones))
        self._refresh_actions()

    def delete_selected_tasks(self) -> None:
        if self._delivery_guard("请稍候", "当前正在发送或保存草稿，请完成后再编辑任务。") or not self._require_package():
            return
        rows = self.tasks_page.selected_rows()
        if not rows:
            QtWidgets.QMessageBox.information(self, "未选择任务", "请先选择至少一条任务。")
            return
        reply = QtWidgets.QMessageBox.question(
            self, "确认删除", f"确认删除选中的 {len(rows)} 条任务吗？这会同步写回 tasks.xlsx。"
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        selected = set(rows)
        self.tasks.persist_tasks([task for idx, task in enumerate(self.tasks.tasks) if idx not in selected])
        self._refresh_actions()

    # ---- 投递 ----

    def _partition_or_warn(self, tasks: list[MailTask], action: str) -> list[MailTask]:
        valid, blocked = self.tasks.runtime.partition_valid_tasks(tasks, check_schedule_time=False)
        if blocked:
            QtWidgets.QMessageBox.warning(self, f"存在不可{action}任务", "\n\n".join(blocked[:10]))
        return valid

    def save_selected_to_drafts(self) -> None:
        if not self.connection.connected:
            QtWidgets.QMessageBox.warning(self, "尚未连接 SMTP", "请先到「设置」完成连接测试。")
            return
        tasks = self.tasks_page.selected_tasks()
        if not tasks:
            QtWidgets.QMessageBox.information(self, "未选择任务", "请先选择至少一条任务。")
            return
        valid = self._partition_or_warn(tasks, "保存")
        if not valid:
            return
        reply = QtWidgets.QMessageBox.question(
            self, "确认保存草稿",
            f"将把选中的 {len(valid)} 条任务写入邮箱草稿箱，不会直接发送。确认继续吗？",
        )
        if reply == QtWidgets.QMessageBox.Yes:
            self.start_save_drafts(valid)

    def send_selected_now(self) -> None:
        if not self.connection.connected:
            QtWidgets.QMessageBox.warning(self, "尚未连接 SMTP", "请先到「设置」完成连接测试。")
            return
        tasks = self.tasks_page.selected_tasks()
        if not tasks:
            QtWidgets.QMessageBox.information(self, "未选择任务", "请先选择至少一条任务。")
            return
        valid = self._partition_or_warn(tasks, "发送")
        if not valid:
            return
        reply = QtWidgets.QMessageBox.question(
            self, "确认立即发送",
            f"将立即发送选中的 {len(valid)} 条任务，并忽略它们的定时设置。确认继续吗？",
        )
        if reply == QtWidgets.QMessageBox.Yes:
            self.start_send(valid, queue_mode=False)

    def queue_selected_tasks(self) -> None:
        if not self.connection.connected:
            QtWidgets.QMessageBox.warning(self, "尚未连接 SMTP", "请先到「设置」完成连接测试。")
            return
        tasks = self.tasks_page.selected_tasks()
        if not tasks:
            QtWidgets.QMessageBox.information(self, "未选择任务", "请先选择至少一条任务。")
            return
        queued, errors = self.tasks.runtime.queue_scheduled_tasks(tasks)
        self.tasks.tasksChanged.emit()
        message = f"已加入定时队列：{queued} 条。"
        if errors:
            message += "\n\n以下任务未加入：\n" + "\n".join(errors[:10])
        QtWidgets.QMessageBox.information(self, "定时队列结果", message)
        self._refresh_actions()

    def remove_from_queue(self, task_ids: list[str]) -> None:
        self.tasks.unqueue_tasks(task_ids)
        self._refresh_actions()

    def retry_failed_tasks(self) -> None:
        failed = [
            task for task in self.tasks.tasks
            if self.tasks.runtime.status_for(task) == TaskStatus.SEND_FAILED and task.enabled
        ]
        if not failed:
            QtWidgets.QMessageBox.information(self, "无需重试", "当前没有可重试的失败任务。")
            return
        valid = self._partition_or_warn(failed, "发送")
        if valid:
            self.start_send(valid, queue_mode=False)

    def start_send(self, tasks: list[MailTask], *, queue_mode: bool) -> None:
        if self.tasks.package_dir is None or self.delivery.busy or not tasks:
            return
        if not self.connection.connected:
            QtWidgets.QMessageBox.warning(self, "尚未连接 SMTP", "请先到「设置」完成连接测试。")
            return
        self.tasks.mark_sending(tasks)
        self.tasks.begin_submission()
        self._active_send = ("send", list(tasks), self.tasks.package_dir)
        self._refresh_actions()
        started = self.delivery.start_send(
            tasks=tasks,
            package_dir=self.tasks.package_dir,
            home_dir=self._home_dir,
            smtp_cfg=self.connection.smtp_cfg,
            smtp_password=self.connection.password,
            rate_limit_seconds=self.app_settings.send_rate_limit_seconds,
        )
        if not started:
            self._active_send = None
            self._refresh_actions()

    def start_save_drafts(self, tasks: list[MailTask]) -> None:
        if self.tasks.package_dir is None or self.delivery.busy or not tasks:
            return
        self.tasks.mark_drafting(tasks)
        self.tasks.begin_submission()
        self._active_send = ("draft", list(tasks), self.tasks.package_dir)
        self._refresh_actions()
        started = self.delivery.start_drafts(
            tasks=tasks,
            package_dir=self.tasks.package_dir,
            home_dir=self._home_dir,
            imap_username=self.connection.smtp_cfg.username.strip(),
            imap_password=self.connection.password,
            imap_host=self.connection.imap_host,
            imap_port=self.connection.imap_port,
            rate_limit_seconds=self.app_settings.send_rate_limit_seconds,
        )
        if not started:
            self._active_send = None
            self._refresh_actions()

    @staticmethod
    def _format_failure_details(result) -> str:
        failures = [
            outcome for outcome in result.outcomes
            if not outcome.status.is_success and not outcome.status.is_skipped
        ]
        if not failures:
            return ""
        lines = ["\n\n失败详情："]
        for outcome in failures[:10]:
            lines.append(f"  - {outcome.subject or outcome.task_id}：{(outcome.error or '未知错误')[:80]}")
        if len(failures) > 10:
            lines.append(f"  ...还有 {len(failures) - 10} 条")
        return "\n".join(lines)

    @staticmethod
    def _skipped_note(result) -> str:
        skipped = sum(1 for outcome in result.outcomes if outcome.status.is_skipped)
        return f"\n其中因连接中断未尝试：{skipped}（已计入失败，可重试）" if skipped else ""

    def _on_send_finished(self, result) -> None:
        kind, submitted, package_dir = self._active_send or ("send", [], self.tasks.package_dir)
        sent, failed = self.tasks.apply_send_result(submitted, package_dir, result)
        self._last_run_dir = result.run_paths.run_dir
        self._active_send = None
        self.tasks_page.clear_progress()
        self._refresh_actions()
        self.queue_page.refresh()
        summary = (
            f"本次输出目录：{result.run_paths.run_dir}\n发送成功：{sent}\n发送失败：{failed}"
            f"{self._skipped_note(result)}{self._format_failure_details(result)}"
        )
        if failed <= 0:
            self._notify_success("发送完成", f"成功发送 {sent} 条任务。\n输出目录：{result.run_paths.run_dir}")
        else:
            QtWidgets.QMessageBox.information(self, "发送完成", summary)
        self._set_status(f"最近输出：{self._last_run_dir}")

    def _on_draft_finished(self, result) -> None:
        kind, submitted, package_dir = self._active_send or ("draft", [], self.tasks.package_dir)
        ok, failed = self.tasks.apply_draft_result(submitted, package_dir, result)
        self._last_run_dir = result.run_paths.run_dir
        self._active_send = None
        self.tasks_page.clear_progress()
        self._refresh_actions()
        if failed <= 0:
            self._notify_success("保存草稿完成", f"成功保存 {ok} 条草稿。\n输出目录：{result.run_paths.run_dir}")
        else:
            details = self._format_failure_details(result)
            QtWidgets.QMessageBox.information(
                self, "保存草稿完成",
                f"本次输出目录：{result.run_paths.run_dir}\n草稿保存成功：{ok}\n草稿保存失败：{failed}"
                f"{self._skipped_note(result)}{details}",
            )
        self._set_status(f"最近输出：{self._last_run_dir}")

    def _on_delivery_failed(self, kind: str, tb: str) -> None:
        kind_name = "send" if kind == "send" else "draft"
        _kind, submitted, package_dir = self._active_send or (kind_name, [], self.tasks.package_dir)
        if kind_name == "send":
            self.tasks.mark_send_worker_error(submitted, package_dir, tb.strip())
        else:
            self.tasks.mark_draft_worker_error(submitted, package_dir, tb.strip())
        self._active_send = None
        self.tasks_page.clear_progress()
        self._refresh_actions()
        self._show_error("发送失败" if kind_name == "send" else "保存草稿失败", error_summary(tb), details=tb)

    # ---- 连接 ----

    def _go_connect(self) -> None:
        """导航栏「连接」入口：跳到设置页聚焦连接表单。"""
        self.switch_page("settings")
        self.settings_page.focus_connection_form()

    def _on_connection_status(self, connected: bool, detail: str) -> None:
        self._nav_rail.set_connection_status(connected, "已连接" if connected else detail or "未连接")
        self._refresh_actions()

    # ---- 设置 ----

    def apply_send_settings(self, rate_limit_seconds: float, runs_retention_days: int) -> None:
        self.app_settings.send_rate_limit_seconds = rate_limit_seconds
        self.app_settings.runs_retention_days = runs_retention_days
        self.app_settings.clamp()
        self.save_settings()
        self._set_status("发送设置已保存。")

    def _remember_splitter(self, sizes: list[int]) -> None:
        self.app_settings.splitter_sizes = list(sizes)
        self.save_settings()

    def save_settings(self) -> None:
        try:
            save_app_state(self._state_path, self.app_settings)
        except Exception:
            pass  # 状态持久化失败不影响主流程

    # ---- 调度 ----

    def process_scheduled_tasks(self) -> None:
        if self.delivery.busy or self.tasks.package_dir is None:
            return
        if QtWidgets.QApplication.activeModalWidget() is not None:
            # 模态对话框（任务编辑/确认框）的嵌套事件循环里不启动发送：
            # 用户确认后 persists_tasks 会替换任务对象，结果将因失配被丢弃（还会重发）
            return
        if not self.connection.connected:
            if self.tasks.runtime.queued_task_ids:
                self.connection.try_auto_connect()
            return
        due = self.tasks.due_tasks()
        if due:
            self.start_send(due, queue_mode=True)
        elif self._last_due_signature != self._due_signature():
            # 只在集合变化时刷 UI，避免每 15s 无谓重渲染预览/重启校验
            self._last_due_signature = self._due_signature()
            self.tasks.tasksChanged.emit()

    def _due_signature(self) -> tuple:
        return (len(self.tasks.runtime.queued_task_ids),) + tuple(sorted(self.tasks.runtime.queued_task_ids))

    # ---- 托盘/关闭 ----

    def _build_tray(self) -> None:
        if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = None
            return
        icon = self.windowIcon()
        self._tray = QtWidgets.QSystemTrayIcon(icon, self)
        self._tray.setToolTip("钉钉邮件发送")
        self._tray.activated.connect(self._on_tray_activated)
        menu = QtWidgets.QMenu(self)
        show_action = menu.addAction("打开主界面")
        show_action.triggered.connect(self._restore_from_tray)
        exit_action = menu.addAction("退出程序")
        exit_action.triggered.connect(self.exit_from_tray)
        self._tray.setContextMenu(menu)
        self._tray.show()

    def _on_tray_activated(self, reason) -> None:
        if reason in (QtWidgets.QSystemTrayIcon.DoubleClick, QtWidgets.QSystemTrayIcon.Trigger):
            self._restore_from_tray()

    def _restore_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _notify_success(self, title: str, text: str) -> None:
        if self._tray is not None:
            self._tray.showMessage(title, text, QtWidgets.QSystemTrayIcon.Information, 4000)
        else:
            QtWidgets.QMessageBox.information(self, title, text)

    def _show_error(self, title: str, message: str, *, details: str | None = None) -> None:
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Critical)
        box.setWindowTitle(title)
        box.setText(message)
        if details:
            box.setDetailedText(details)
        box.exec()

    def exit_from_tray(self) -> None:
        if self.delivery.busy or self.connection.has_active_test():
            self.delivery.request_cancel()
            if not self.delivery.wait_all(10000) or not self.connection.wait_active_test(10000):
                QtWidgets.QMessageBox.information(
                    self, "等待任务结束", "正在等待后台任务安全停止，请稍候再重试退出。"
                )
                return
        if self.tasks.runtime.queued_task_ids:
            reply = QtWidgets.QMessageBox.question(
                self, "确认退出",
                f"当前还有 {len(self.tasks.runtime.queued_task_ids)} 个定时任务未发送。"
                "退出后将不再自动发送，确认继续吗？",
            )
            if reply != QtWidgets.QMessageBox.Yes:
                return
        self._quit_requested = True
        self.app_settings.splitter_sizes = self.tasks_page.splitter_sizes()
        self.save_settings()
        QtWidgets.QApplication.quit()

    def _save_and_accept(self, event: QtGui.QCloseEvent) -> None:
        self.app_settings.splitter_sizes = self.tasks_page.splitter_sizes()
        self.save_settings()
        event.accept()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        worker_active = self.delivery.busy or self.connection.has_active_test()
        if worker_active and (self._quit_requested or self._tray is None):
            self.delivery.request_cancel()
            if not self.delivery.wait_all(5000) or not self.connection.wait_active_test(5000):
                QtWidgets.QMessageBox.information(
                    self, "正在执行任务", "当前正在发送、保存草稿或测试连接，请等待其完成后再退出。"
                )
                event.ignore()
                return
            self._save_and_accept(event)
            return
        if self._quit_requested or self._tray is None:
            self._save_and_accept(event)
            return
        if not self.tasks.runtime.queued_task_ids and not self.connection.connected:
            self._save_and_accept(event)
            return
        self.hide()
        event.ignore()
        if not self._close_tip_shown:
            self._tray.showMessage(
                "已最小化到托盘",
                "程序会继续保留定时队列。需要彻底退出时，请在托盘图标上右键选择“退出程序”。",
                QtWidgets.QSystemTrayIcon.Information,
                5000,
            )
            self._close_tip_shown = True

    # ---- 快捷键与杂项 ----

    def _install_shortcuts(self) -> None:
        for sequence, slot in (
            ("Ctrl+F", self._focus_search),
            ("Ctrl+N", self.add_task),
            ("Ctrl+D", self.save_selected_to_drafts),
            ("F5", self.reload_package),
        ):
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(sequence), self)
            shortcut.activated.connect(slot)

    def _focus_search(self) -> None:
        self.switch_page("tasks")
        self.tasks_page.focus_search()

    def _refresh_actions(self) -> None:
        self.tasks_page.update_actions(connected=self.connection.connected, busy=self.delivery.busy)
        self.queue_page.refresh()

    def _on_notice(self, message: str, severity: str) -> None:
        self.tasks_page.show_banner(message, severity=severity)

    def _open_path(self, path: Path) -> None:
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))

    def _set_status(self, text: str) -> None:
        self._status_label.setText(text)
