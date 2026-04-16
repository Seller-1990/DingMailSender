from __future__ import annotations

import copy
import json
import re
import traceback
import uuid
from datetime import datetime
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from ..constants import DEFAULT_IMAP_HOST, DEFAULT_IMAP_PORT_SSL
from ..model import SmtpConfig
from ..paths import detect_home_dir, ensure_layout, packages_dir, runs_dir
from ..smtp_sender import SmtpSession
from ..task_delivery import SendTasksResult, save_tasks_to_imap_drafts, send_tasks
from ..task_models import MailTask
from ..task_package import (
    PACKAGE_README_FILENAME,
    TASKS_FILENAME,
    clone_task,
    create_template_package,
    load_tasks_from_package,
    package_relpath,
    save_tasks_to_package,
)
from ..task_service import render_task_email, validate_task

EMAIL_RE = re.compile(r"^[^@\s;]+@[^@\s]+\.[^@\s]+$")
SCHEDULE_CHECK_INTERVAL_MS = 15_000
STATUS_COLORS = {
    "已停用": "#d7d7d7",
    "校验失败": "#f6c3c3",
    "已加入定时队列": "#f5df93",
    "发送中": "#c7d7f4",
    "草稿保存中": "#d6d6f4",
    "发送成功": "#bfe7c6",
    "发送失败": "#f5c0c0",
    "草稿已保存": "#cfe8f7",
    "草稿保存失败": "#f5c0c0",
    "可发送": "#dfe9d8",
}


def _card(title: str, hint: str) -> tuple[QtWidgets.QFrame, QtWidgets.QVBoxLayout, QtWidgets.QPushButton]:
    frame = QtWidgets.QFrame()
    frame.setObjectName("Card")
    outer_layout = QtWidgets.QVBoxLayout(frame)
    outer_layout.setContentsMargins(18, 16, 18, 16)
    outer_layout.setSpacing(10)

    header_layout = QtWidgets.QHBoxLayout()
    header_layout.setContentsMargins(0, 0, 0, 0)
    header_layout.setSpacing(8)

    title_label = QtWidgets.QLabel(title)
    title_label.setObjectName("CardTitle")

    toggle_btn = QtWidgets.QPushButton("折叠")
    toggle_btn.setObjectName("CardToggle")
    toggle_btn.setCheckable(True)
    toggle_btn.setChecked(True)

    hint_label = QtWidgets.QLabel(hint)
    hint_label.setObjectName("CardHint")
    hint_label.setWordWrap(True)

    body = QtWidgets.QWidget()
    body_layout = QtWidgets.QVBoxLayout(body)
    body_layout.setContentsMargins(0, 0, 0, 0)
    body_layout.setSpacing(10)
    body_layout.addWidget(hint_label)

    def _on_toggle(checked: bool) -> None:
        body.setVisible(checked)
        toggle_btn.setText("折叠" if checked else "展开")

    toggle_btn.toggled.connect(_on_toggle)
    _on_toggle(True)

    header_layout.addWidget(title_label)
    header_layout.addStretch(1)
    header_layout.addWidget(toggle_btn)
    outer_layout.addLayout(header_layout)
    outer_layout.addWidget(body)
    return frame, body_layout, toggle_btn


def _label_value(text: str) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
    label.setWordWrap(True)
    return label


def _fit(value: str, limit: int = 28) -> str:
    text = str(value or "").replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _split_email_input(text: str) -> list[str]:
    raw = str(text or "").replace("；", ";").replace(",", ";")
    return [item.strip() for item in raw.split(";") if item.strip()]


class TestSmtpWorker(QtCore.QThread):
    finished_ok = QtCore.Signal(str)
    finished_err = QtCore.Signal(str)

    def __init__(self, cfg: SmtpConfig, password: str) -> None:
        super().__init__()
        self._cfg = cfg
        self._password = password

    def run(self) -> None:  # noqa: N802
        try:
            with SmtpSession(self._cfg, self._password):
                pass
            self.finished_ok.emit(f"{self._cfg.host}:{self._cfg.port} ({self._cfg.security})")
        except Exception:
            self.finished_err.emit(traceback.format_exc())


class SendTasksWorker(QtCore.QThread):
    finished_ok = QtCore.Signal(object)
    finished_err = QtCore.Signal(str)

    def __init__(
        self,
        *,
        tasks: list[MailTask],
        package_dir: Path,
        home_dir: Path,
        smtp_cfg: SmtpConfig,
        smtp_password: str,
    ) -> None:
        super().__init__()
        self._tasks = copy.deepcopy(tasks)
        self._package_dir = package_dir
        self._home_dir = home_dir
        self._smtp_cfg = smtp_cfg
        self._smtp_password = smtp_password

    def run(self) -> None:  # noqa: N802
        try:
            result = send_tasks(
                tasks=self._tasks,
                package_dir=self._package_dir,
                home_dir=self._home_dir,
                smtp_host=self._smtp_cfg.host,
                smtp_port=self._smtp_cfg.port,
                smtp_security=self._smtp_cfg.security,
                smtp_username=self._smtp_cfg.username,
                smtp_password=self._smtp_password,
            )
            self.finished_ok.emit(result)
        except Exception:
            self.finished_err.emit(traceback.format_exc())


class SaveDraftsWorker(QtCore.QThread):
    finished_ok = QtCore.Signal(object)
    finished_err = QtCore.Signal(str)

    def __init__(
        self,
        *,
        tasks: list[MailTask],
        package_dir: Path,
        home_dir: Path,
        imap_username: str,
        imap_password: str,
    ) -> None:
        super().__init__()
        self._tasks = copy.deepcopy(tasks)
        self._package_dir = package_dir
        self._home_dir = home_dir
        self._imap_username = imap_username
        self._imap_password = imap_password

    def run(self) -> None:  # noqa: N802
        try:
            result = save_tasks_to_imap_drafts(
                tasks=self._tasks,
                package_dir=self._package_dir,
                home_dir=self._home_dir,
                imap_username=self._imap_username,
                imap_password=self._imap_password,
                imap_host=DEFAULT_IMAP_HOST,
                imap_port=DEFAULT_IMAP_PORT_SSL,
            )
            self.finished_ok.emit(result)
        except Exception:
            self.finished_err.emit(traceback.format_exc())


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
        hint = QtWidgets.QLabel(
            "一行代表一封邮件。推荐优先使用相对任务包目录的路径，例如 `content/示例正文.md`。"
        )
        hint.setObjectName("DialogHint")
        hint.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(hint)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)

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

        markdown_row = QtWidgets.QHBoxLayout()
        self._markdown_input = QtWidgets.QLineEdit(task.markdown_path)
        self._markdown_input.setPlaceholderText("例如：content/示例正文.md")
        browse_markdown_btn = QtWidgets.QPushButton("选择 Markdown")
        browse_markdown_btn.clicked.connect(self._choose_markdown_file)
        markdown_row.addWidget(self._markdown_input, 1)
        markdown_row.addWidget(browse_markdown_btn)
        markdown_widget = QtWidgets.QWidget()
        markdown_widget.setLayout(markdown_row)
        form.addRow("Markdown 路径", markdown_widget)

        attachment_box = QtWidgets.QWidget()
        attachment_layout = QtWidgets.QVBoxLayout(attachment_box)
        attachment_layout.setContentsMargins(0, 0, 0, 0)
        attachment_layout.setSpacing(8)

        self._attachments_list = QtWidgets.QListWidget()
        self._attachments_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        for item in task.attachment_paths:
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
        form.addRow("附件", attachment_box)

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
        form.addRow("发送时间", schedule_box)

        self._note_input = QtWidgets.QLineEdit(task.note)
        self._note_input.setPlaceholderText("可选备注，例如：只发项目组")
        form.addRow("备注", self._note_input)

        root.addLayout(form, 1)

        button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        root.addWidget(button_box)

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
            self._markdown_input.setText(self._normalize_path(file_path))

    def _add_attachments(self) -> None:
        start_dir = self._package_dir / "attachments"
        file_paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            "选择附件",
            str(start_dir if start_dir.exists() else self._package_dir),
            "所有文件 (*.*)",
        )
        for file_path in file_paths:
            normalized = self._normalize_path(file_path)
            if normalized and not self._attachments_list.findItems(normalized, QtCore.Qt.MatchExactly):
                self._attachments_list.addItem(normalized)

    def _remove_attachments(self) -> None:
        for item in self._attachments_list.selectedItems():
            self._attachments_list.takeItem(self._attachments_list.row(item))

    def task(self) -> MailTask:
        attachment_paths = [self._attachments_list.item(i).text().strip() for i in range(self._attachments_list.count())]
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

        self._summary = QtWidgets.QLabel()
        self._summary.setWordWrap(True)
        self._summary.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)

        self._meta = QtWidgets.QLabel()
        self._meta.setWordWrap(True)
        self._meta.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)

        self._issue = QtWidgets.QLabel()
        self._issue.setWordWrap(True)
        self._issue.setObjectName("ErrorLabel")

        self._browser = QtWidgets.QTextBrowser()
        self._browser.setOpenExternalLinks(True)

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
        self._issue.clear()
        try:
            rendered = render_task_email(task, self._package_dir)
            self._browser.setHtml(rendered.html_for_preview)
        except Exception as exc:
            self._browser.setHtml("")
            self._issue.setText(f"预览失败：{exc}")

        self._prev_btn.setEnabled(self._index > 0)
        self._next_btn.setEnabled(self._index < len(self._tasks) - 1)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("钉钉邮件发送")
        self.resize(1420, 880)

        self._home_dir = ensure_layout(detect_home_dir())
        self._conn_config_path = self._home_dir / "conn_profile.json"
        self._smtp_cfg = SmtpConfig()
        self._smtp_password = ""
        self._smtp_connected = False
        self._package_dir: Path | None = None
        self._tasks: list[MailTask] = []
        self._queued_task_ids: set[str] = set()
        self._sending_task_ids: set[str] = set()
        self._drafting_task_ids: set[str] = set()
        self._last_run_dir: Path | None = None
        self._quit_requested = False
        self._close_tip_shown = False

        self._smtp_worker: TestSmtpWorker | None = None
        self._send_worker: SendTasksWorker | None = None
        self._draft_worker: SaveDraftsWorker | None = None

        self._load_connection_profile()
        self._build_ui()
        self._build_tray()
        self._schedule_timer = QtCore.QTimer(self)
        self._schedule_timer.setInterval(SCHEDULE_CHECK_INTERVAL_MS)
        self._schedule_timer.timeout.connect(self._process_scheduled_tasks)
        self._schedule_timer.start()
        self._apply_styles()
        self._refresh_ui_state()

    def _load_connection_profile(self) -> None:
        if not self._conn_config_path.is_file():
            return
        try:
            raw = json.loads(self._conn_config_path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(raw, dict):
            return

        from_email = str(raw.get("from_email") or "").strip()
        if from_email:
            self._smtp_cfg = SmtpConfig(
                host=self._smtp_cfg.host,
                port=self._smtp_cfg.port,
                security=self._smtp_cfg.security,
                username=from_email,
            )

    def _save_connection_profile(self, *, from_email: str) -> None:
        payload = {
            "from_email": from_email,
        }
        self._conn_config_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _refresh_smtp_summary_labels(self) -> None:
        sender = self._smtp_cfg.username.strip() or "未配置"
        self._account_label.setText(f"发件账号：{sender}")
        self._server_label.setText(
            f"发信服务器：{self._smtp_cfg.host}:{self._smtp_cfg.port} / {self._smtp_cfg.security.upper()}"
        )

    def _build_ui(self) -> None:
        root = QtWidgets.QWidget()
        self.setCentralWidget(root)
        layout = QtWidgets.QVBoxLayout(root)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        smtp_card, smtp_layout, self._smtp_toggle_btn = _card(
            "步骤 1：连接 SMTP",
            "进入界面后的第一步就是连接 SMTP。未连接前可以下载模板或导入任务包，但不能发送和加入定时队列。",
        )

        smtp_row = QtWidgets.QHBoxLayout()
        self._account_label = _label_value("")
        self._server_label = _label_value("")
        self._smtp_status_badge = QtWidgets.QLabel("未连接")
        self._smtp_status_badge.setObjectName("StatusBadge")
        smtp_row.addWidget(self._account_label, 2)
        smtp_row.addWidget(self._server_label, 2)
        smtp_row.addStretch(1)
        smtp_row.addWidget(self._smtp_status_badge)

        smtp_ctrl = QtWidgets.QHBoxLayout()
        self._from_email_input = QtWidgets.QLineEdit(self._smtp_cfg.username)
        self._from_email_input.setPlaceholderText("首次使用请填写发件邮箱，例如 name@zhongtenghr.com")
        self._from_email_input.textChanged.connect(self._on_from_email_changed)
        self._smtp_password_input = QtWidgets.QLineEdit(self._smtp_password)
        self._smtp_password_input.setEchoMode(QtWidgets.QLineEdit.Password)
        self._smtp_password_input.setPlaceholderText("首次使用请填写 SMTP 授权码（仅本次运行使用）")
        self._smtp_password_input.textChanged.connect(self._on_password_changed)
        self._connect_btn = QtWidgets.QPushButton("连接并测试")
        self._connect_btn.clicked.connect(self._connect_smtp)
        smtp_help_btn = QtWidgets.QPushButton("连接说明")
        smtp_help_btn.clicked.connect(
            lambda: QtWidgets.QMessageBox.information(
                self,
                "连接说明",
                "请先填写发件邮箱和 SMTP 授权码。\n"
                "程序只会保存发件邮箱；授权码不会写入磁盘。\n"
                "默认发信服务器：smtp.qiye.aliyun.com:465（SSL）。",
            )
        )
        smtp_ctrl.addWidget(QtWidgets.QLabel("发件邮箱"))
        smtp_ctrl.addWidget(self._from_email_input, 1)
        smtp_ctrl.addWidget(QtWidgets.QLabel("SMTP 授权码"))
        smtp_ctrl.addWidget(self._smtp_password_input, 1)
        smtp_ctrl.addWidget(self._connect_btn)
        smtp_ctrl.addWidget(smtp_help_btn)

        smtp_layout.addLayout(smtp_row)
        smtp_layout.addLayout(smtp_ctrl)
        self._refresh_smtp_summary_labels()

        package_card, package_layout, self._package_toggle_btn = _card(
            "步骤 2：下载或导入任务包",
            "推荐先下载一份标准任务包模板，在 `tasks.xlsx` 里编辑任务；也支持导入已存在的任务包目录。",
        )

        package_action_row = QtWidgets.QHBoxLayout()
        self._download_package_btn = QtWidgets.QPushButton("下载任务包模板")
        self._download_package_btn.clicked.connect(self._download_template_package)
        self._import_package_btn = QtWidgets.QPushButton("导入任务包目录")
        self._import_package_btn.clicked.connect(self._import_package)
        self._reload_package_btn = QtWidgets.QPushButton("重新加载任务包")
        self._reload_package_btn.clicked.connect(self._reload_package)
        self._open_package_btn = QtWidgets.QPushButton("打开任务包")
        self._open_package_btn.clicked.connect(self._open_package_dir)
        self._open_tasks_btn = QtWidgets.QPushButton("打开 tasks.xlsx")
        self._open_tasks_btn.clicked.connect(self._open_tasks_excel)
        self._open_readme_btn = QtWidgets.QPushButton("打开操作说明")
        self._open_readme_btn.clicked.connect(self._open_package_readme)
        package_action_row.addWidget(self._download_package_btn)
        package_action_row.addWidget(self._import_package_btn)
        package_action_row.addWidget(self._reload_package_btn)
        package_action_row.addWidget(self._open_package_btn)
        package_action_row.addWidget(self._open_tasks_btn)
        package_action_row.addWidget(self._open_readme_btn)
        package_action_row.addStretch(1)

        self._package_label = _label_value(
            f"当前任务包：未导入\n工作目录：{self._home_dir}\n模板目录：{packages_dir(self._home_dir)}"
        )
        package_layout.addLayout(package_action_row)
        package_layout.addWidget(self._package_label)

        task_card, task_layout, self._task_toggle_btn = _card(
            "步骤 3：检查任务表并预览",
            "一行代表一封邮件。双击行可编辑；也可以直接打开 `tasks.xlsx` 用 Excel 批量改，再点“重新加载任务包”返回界面检查。",
        )

        toolbar = QtWidgets.QHBoxLayout()
        self._add_btn = QtWidgets.QPushButton("新增任务")
        self._edit_btn = QtWidgets.QPushButton("编辑任务")
        self._copy_btn = QtWidgets.QPushButton("复制任务")
        self._delete_btn = QtWidgets.QPushButton("删除任务")
        self._preview_btn = QtWidgets.QPushButton("预览当前邮件")
        self._save_drafts_btn = QtWidgets.QPushButton("保存到草稿箱（选中）")
        self._send_now_btn = QtWidgets.QPushButton("立即发送选中")
        self._queue_btn = QtWidgets.QPushButton("加入定时队列")
        self._retry_btn = QtWidgets.QPushButton("重试失败项")
        self._open_last_run_btn = QtWidgets.QPushButton("打开最近一次输出")

        self._add_btn.clicked.connect(self._add_task)
        self._edit_btn.clicked.connect(self._edit_selected_task)
        self._copy_btn.clicked.connect(self._duplicate_selected_tasks)
        self._delete_btn.clicked.connect(self._delete_selected_tasks)
        self._preview_btn.clicked.connect(self._preview_selected_task)
        self._save_drafts_btn.clicked.connect(self._save_selected_to_drafts)
        self._send_now_btn.clicked.connect(self._send_selected_now)
        self._queue_btn.clicked.connect(self._queue_selected_tasks)
        self._retry_btn.clicked.connect(self._retry_failed_tasks)
        self._open_last_run_btn.clicked.connect(self._open_last_run_dir)

        for button in [
            self._add_btn,
            self._edit_btn,
            self._copy_btn,
            self._delete_btn,
            self._preview_btn,
            self._save_drafts_btn,
            self._send_now_btn,
            self._queue_btn,
            self._retry_btn,
            self._open_last_run_btn,
        ]:
            toolbar.addWidget(button)
        toolbar.addStretch(1)

        self._task_table = QtWidgets.QTableWidget()
        self._task_table.setColumnCount(10)
        self._task_table.setHorizontalHeaderLabels(
            ["启用", "收件人", "抄送", "主题", "开头/补充内容", "Markdown", "附件", "定时", "发送时间", "状态"]
        )
        self._task_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._task_table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self._task_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._task_table.setAlternatingRowColors(True)
        self._task_table.verticalHeader().setVisible(False)
        self._task_table.itemSelectionChanged.connect(self._refresh_ui_state)
        self._task_table.itemDoubleClicked.connect(lambda _item: self._edit_selected_task())
        header = self._task_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        self._task_table.setToolTip("双击行可编辑；状态为红色时先修正路径、邮箱或时间。")

        task_layout.addLayout(toolbar)
        task_layout.addWidget(self._task_table, 1)

        footer_card, footer_layout, self._footer_toggle_btn = _card(
            "步骤 4：发送或定时发送",
            "预览确认后再发送。定时任务加入队列后，关闭主窗口会最小化到托盘继续等待；真正退出请用托盘菜单中的“退出程序”。",
        )
        self._status_label = _label_value("当前没有任务包。")
        footer_help_btn = QtWidgets.QPushButton("定时发送说明")
        footer_help_btn.clicked.connect(
            lambda: QtWidgets.QMessageBox.information(
                self,
                "定时发送说明",
                "V1 使用本机托盘常驻调度。\n"
                "关闭主窗口后程序仍在右下角托盘运行，到点会自动发送。\n"
                "如果从托盘菜单点“退出程序”，未发送的定时任务会一起结束。",
            )
        )
        footer_layout.addWidget(self._status_label)
        footer_layout.addWidget(footer_help_btn, 0, QtCore.Qt.AlignRight)

        layout.addWidget(smtp_card)
        layout.addWidget(package_card)
        layout.addWidget(task_card, 1)
        layout.addWidget(footer_card)

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #f2efe8;
                color: #2f2b25;
                font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
                font-size: 13px;
            }
            QFrame#Card {
                background: #fbf9f4;
                border: 1px solid #ded8cb;
                border-radius: 16px;
            }
            QLabel#CardTitle {
                font-size: 18px;
                font-weight: 600;
                color: #2f2b25;
            }
            QLabel#CardHint, QLabel#InlineTip, QLabel#DialogHint {
                color: #70695d;
                line-height: 1.45;
            }
            QLabel#DialogTitle {
                font-size: 18px;
                font-weight: 600;
            }
            QLabel#StatusBadge {
                background: #e6ddd0;
                border-radius: 12px;
                padding: 6px 12px;
                font-weight: 600;
                color: #5b5143;
            }
            QLabel#ErrorLabel {
                color: #9e3f32;
                background: #fbe6e0;
                border-radius: 10px;
                padding: 8px 10px;
            }
            QPushButton {
                background: #e8e0d2;
                border: 1px solid #d1c4ae;
                border-radius: 10px;
                padding: 8px 14px;
            }
            QPushButton#CardToggle {
                min-width: 56px;
                padding: 5px 10px;
                background: #efe7da;
                border-color: #cdbda1;
                font-size: 12px;
            }
            QPushButton:hover {
                background: #dfd3bf;
            }
            QPushButton:disabled {
                color: #9d9587;
                background: #efebe3;
                border-color: #e2dbcf;
            }
            QLineEdit, QTextBrowser, QPlainTextEdit, QListWidget, QTableWidget, QDateTimeEdit {
                background: #fffdf9;
                border: 1px solid #d8d1c4;
                border-radius: 10px;
                padding: 6px 8px;
            }
            QTableWidget {
                gridline-color: #e7e0d5;
                alternate-background-color: #f8f5ef;
            }
            QHeaderView::section {
                background: #ede6d9;
                border: none;
                border-bottom: 1px solid #dbd1c0;
                padding: 10px 8px;
                font-weight: 600;
            }
            """
        )

    def _build_tray(self) -> None:
        if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = None
            return

        icon = self.style().standardIcon(QtWidgets.QStyle.SP_FileDialogDetailedView)
        self._tray = QtWidgets.QSystemTrayIcon(icon, self)
        self._tray.setToolTip("钉钉邮件发送")
        self._tray.activated.connect(self._on_tray_activated)

        menu = QtWidgets.QMenu(self)
        show_action = menu.addAction("打开主界面")
        show_action.triggered.connect(self._restore_from_tray)
        exit_action = menu.addAction("退出程序")
        exit_action.triggered.connect(self._exit_from_tray)
        self._tray.setContextMenu(menu)
        self.setWindowIcon(icon)
        self._tray.show()

    def _on_tray_activated(self, reason: QtWidgets.QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QtWidgets.QSystemTrayIcon.DoubleClick, QtWidgets.QSystemTrayIcon.Trigger):
            self._restore_from_tray()

    def _restore_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _exit_from_tray(self) -> None:
        if self._queued_task_ids:
            reply = QtWidgets.QMessageBox.question(
                self,
                "确认退出",
                f"当前还有 {len(self._queued_task_ids)} 个定时任务未发送。退出后将不再自动发送，确认继续吗？",
            )
            if reply != QtWidgets.QMessageBox.Yes:
                return
        self._quit_requested = True
        QtWidgets.QApplication.quit()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802
        if self._quit_requested or self._tray is None:
            event.accept()
            return

        if not self._queued_task_ids and not self._smtp_connected:
            event.accept()
            return

        self.hide()
        event.ignore()
        if not self._close_tip_shown and self._tray is not None:
            self._tray.showMessage(
                "已最小化到托盘",
                "程序会继续保留 SMTP 会话与定时队列。需要彻底退出时，请在托盘图标上右键选择“退出程序”。",
                QtWidgets.QSystemTrayIcon.Information,
                5000,
            )
            self._close_tip_shown = True

    def _set_smtp_status(self, connected: bool, text: str) -> None:
        self._smtp_connected = connected
        if connected:
            self._smtp_status_badge.setText(f"已连接 · {text}")
            self._smtp_status_badge.setStyleSheet(
                "background:#d6ead8;color:#305536;border-radius:12px;padding:6px 12px;font-weight:600;"
            )
        else:
            self._smtp_status_badge.setText(text)
            self._smtp_status_badge.setStyleSheet(
                "background:#efe4d4;color:#6a5644;border-radius:12px;padding:6px 12px;font-weight:600;"
            )
        self._refresh_ui_state()

    def _on_from_email_changed(self) -> None:
        text = self._from_email_input.text().strip()
        self._smtp_cfg = SmtpConfig(
            host=self._smtp_cfg.host,
            port=self._smtp_cfg.port,
            security=self._smtp_cfg.security,
            username=text,
        )
        self._refresh_smtp_summary_labels()
        if self._smtp_connected:
            self._smtp_password = ""
            self._set_smtp_status(False, "发件账号已变更，请重新连接")

    def _on_password_changed(self) -> None:
        text = self._smtp_password_input.text()
        if self._smtp_connected and text != self._smtp_password:
            self._smtp_password = ""
            self._set_smtp_status(False, "授权码已变更，请重新连接")

    def _connect_smtp(self) -> None:
        from_email = self._from_email_input.text().strip()
        if not from_email:
            QtWidgets.QMessageBox.warning(self, "缺少发件邮箱", "请输入发件邮箱后再连接。")
            return
        if not EMAIL_RE.match(from_email):
            QtWidgets.QMessageBox.warning(self, "邮箱格式错误", "发件邮箱格式不正确，请检查后重试。")
            return

        password = self._smtp_password_input.text().strip()
        if not password:
            QtWidgets.QMessageBox.warning(self, "缺少授权码", "请输入 SMTP 授权码后再连接。")
            return

        self._smtp_cfg = SmtpConfig(
            host=self._smtp_cfg.host,
            port=self._smtp_cfg.port,
            security=self._smtp_cfg.security,
            username=from_email,
        )
        self._refresh_smtp_summary_labels()

        self._connect_btn.setEnabled(False)
        self._set_smtp_status(False, "正在连接…")
        worker = TestSmtpWorker(self._smtp_cfg, password)
        self._smtp_worker = worker

        def _ok(info: str) -> None:
            self._smtp_password = password
            self._save_connection_profile(from_email=from_email)
            self._connect_btn.setEnabled(True)
            self._set_smtp_status(True, info)
            QtWidgets.QMessageBox.information(self, "连接成功", f"SMTP 连接成功：{info}")

        def _err(tb: str) -> None:
            self._smtp_password = ""
            self._connect_btn.setEnabled(True)
            self._set_smtp_status(False, "连接失败")
            QtWidgets.QMessageBox.critical(self, "连接失败", tb)

        worker.finished_ok.connect(_ok)
        worker.finished_err.connect(_err)
        worker.start()

    def _package_root(self) -> Path:
        return packages_dir(self._home_dir)

    def _ensure_within_home(self, package_dir: Path) -> None:
        home = self._home_dir.resolve()
        current = package_dir.resolve()
        if home not in current.parents and current != home:
            raise ValueError(f"任务包目录必须位于 {home} 下。请先把任务包放进 `packages` 目录。")

    def _download_template_package(self) -> None:
        name, ok = QtWidgets.QInputDialog.getText(
            self,
            "下载任务包模板",
            "任务包目录名（会创建在 packages 目录下）",
            text=f"任务包_{_now_stamp()}",
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
        selected = QtWidgets.QFileDialog.getExistingDirectory(self, "选择任务包目录", str(self._package_root()))
        if not selected:
            return

        package_dir = Path(selected).resolve()
        try:
            self._ensure_within_home(package_dir)
            self._load_package(package_dir)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "导入失败", str(exc))

    def _reload_package(self) -> None:
        if not self._package_dir:
            QtWidgets.QMessageBox.information(self, "未导入", "请先导入任务包目录。")
            return
        try:
            self._load_package(self._package_dir)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "重新加载失败", str(exc))

    def _load_package(self, package_dir: Path) -> None:
        tasks = load_tasks_from_package(package_dir)
        self._package_dir = package_dir
        self._tasks = tasks
        self._queued_task_ids.clear()
        self._sending_task_ids.clear()
        self._drafting_task_ids.clear()
        for task in self._tasks:
            self._reset_runtime_fields(task)
        self._refresh_task_table()
        self._refresh_ui_state()

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

    def _open_package_readme(self) -> None:
        if self._package_dir:
            path = self._package_dir / PACKAGE_README_FILENAME
            if path.exists():
                self._open_path(path)

    def _open_last_run_dir(self) -> None:
        if self._last_run_dir and self._last_run_dir.exists():
            self._open_path(self._last_run_dir)
            return

        root = runs_dir(self._home_dir)
        if not root.exists():
            return
        items = sorted([p for p in root.iterdir() if p.is_dir()], key=lambda p: p.name)
        if items:
            self._open_path(items[-1])

    def _persist_tasks(self, *, updated_tasks: list[MailTask]) -> bool:
        if not self._package_dir:
            QtWidgets.QMessageBox.warning(self, "未导入任务包", "请先导入或创建任务包。")
            return False
        try:
            save_tasks_to_package(self._package_dir, updated_tasks)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self,
                "保存失败",
                f"写入 tasks.xlsx 失败：{exc}\n如果 Excel 正在打开，请先关闭 Excel 后重试。",
            )
            return False

        self._tasks = updated_tasks
        valid_ids = {task.task_id for task in self._tasks}
        self._queued_task_ids.intersection_update(valid_ids)
        self._sending_task_ids.intersection_update(valid_ids)
        self._drafting_task_ids.intersection_update(valid_ids)
        self._refresh_task_table()
        self._refresh_ui_state()
        return True

    def _selected_rows(self) -> list[int]:
        rows = self._task_table.selectionModel().selectedRows() if self._task_table.selectionModel() else []
        return sorted({row.row() for row in rows})

    def _selected_tasks(self) -> list[MailTask]:
        return [self._tasks[i] for i in self._selected_rows() if 0 <= i < len(self._tasks)]

    def _require_package(self) -> bool:
        if self._package_dir is None:
            QtWidgets.QMessageBox.information(self, "未导入任务包", "请先下载或导入任务包。")
            return False
        return True

    def _require_single_task(self) -> int | None:
        rows = self._selected_rows()
        if len(rows) != 1:
            QtWidgets.QMessageBox.information(self, "请选择一行", "请先选中一条任务。")
            return None
        return rows[0]

    def _add_task(self) -> None:
        if not self._require_package():
            return
        task = MailTask(task_id=uuid.uuid4().hex, enabled=True)
        dialog = TaskEditorDialog(task=task, package_dir=self._package_dir, parent=self)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        new_task = dialog.task()
        self._reset_runtime_fields(new_task)
        updated = copy.deepcopy(self._tasks)
        updated.append(new_task)
        if self._persist_tasks(updated_tasks=updated):
            self._task_table.selectRow(len(updated) - 1)

    def _edit_selected_task(self) -> None:
        if not self._require_package():
            return
        row = self._require_single_task()
        if row is None:
            return
        dialog = TaskEditorDialog(task=copy.deepcopy(self._tasks[row]), package_dir=self._package_dir, parent=self)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        updated_task = dialog.task()
        self._reset_runtime_fields(updated_task)
        updated = copy.deepcopy(self._tasks)
        updated[row] = updated_task
        if self._persist_tasks(updated_tasks=updated):
            self._task_table.selectRow(row)

    def _duplicate_selected_tasks(self) -> None:
        if not self._require_package():
            return
        rows = self._selected_rows()
        if not rows:
            QtWidgets.QMessageBox.information(self, "未选择任务", "请先选择至少一条任务。")
            return
        updated = copy.deepcopy(self._tasks)
        insert_at = rows[-1] + 1
        clones = []
        for row in rows:
            cloned = clone_task(updated[row])
            self._reset_runtime_fields(cloned)
            clones.append(cloned)
        for offset, task in enumerate(clones):
            updated.insert(insert_at + offset, task)
        self._persist_tasks(updated_tasks=updated)

    def _delete_selected_tasks(self) -> None:
        if not self._require_package():
            return
        rows = self._selected_rows()
        if not rows:
            QtWidgets.QMessageBox.information(self, "未选择任务", "请先选择至少一条任务。")
            return
        reply = QtWidgets.QMessageBox.question(
            self,
            "确认删除",
            f"确认删除选中的 {len(rows)} 条任务吗？这会同步写回 tasks.xlsx。",
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        updated = [task for idx, task in enumerate(self._tasks) if idx not in set(rows)]
        self._persist_tasks(updated_tasks=updated)

    def _preview_selected_task(self) -> None:
        if not self._require_package():
            return
        row = self._require_single_task()
        if row is None:
            return
        dialog = PreviewDialog(tasks=self._tasks, start_index=row, package_dir=self._package_dir, parent=self)
        dialog.exec()
        self._tasks[row].last_previewed_at = datetime.now().replace(microsecond=0)
        self._refresh_task_table()
        self._refresh_ui_state()

    def _validate_task(self, task: MailTask, *, check_schedule_time: bool) -> list[str]:
        if not self._package_dir:
            return ["未导入任务包"]
        errors = validate_task(task, self._package_dir, now=datetime.now() if check_schedule_time else None)
        invalid_to = [email for email in task.to_recipients if not EMAIL_RE.match(email)]
        invalid_cc = [email for email in task.cc_recipients if not EMAIL_RE.match(email)]
        if invalid_to:
            errors.append(f"收件人邮箱格式不合法：{'; '.join(invalid_to)}")
        if invalid_cc:
            errors.append(f"抄送邮箱格式不合法：{'; '.join(invalid_cc)}")
        return errors

    def _reset_runtime_fields(self, task: MailTask) -> None:
        task.status = "未校验"
        task.error_message = ""
        task.last_send_result = ""

    def _refresh_runtime_state(self) -> None:
        if not self._package_dir:
            return
        for task in self._tasks:
            if not task.enabled:
                task.status = "已停用"
                task.error_message = ""
                continue
            errors = self._validate_task(task, check_schedule_time=False)
            if errors:
                task.status = "校验失败"
                task.error_message = "\n".join(errors)
                continue
            if task.task_id in self._sending_task_ids:
                task.status = "发送中"
                continue
            if task.task_id in self._drafting_task_ids:
                task.status = "草稿保存中"
                continue
            if task.task_id in self._queued_task_ids and task.schedule_enabled:
                task.status = "已加入定时队列"
                task.error_message = ""
                continue
            if task.status in {"发送成功", "发送失败", "草稿已保存", "草稿保存失败"}:
                continue
            task.status = "可发送"
            task.error_message = ""

    def _refresh_task_table(self) -> None:
        self._refresh_runtime_state()
        self._task_table.setRowCount(len(self._tasks))
        for row, task in enumerate(self._tasks):
            values = [
                "是" if task.enabled else "否",
                "; ".join(task.to_recipients),
                "; ".join(task.cc_recipients),
                task.subject,
                _fit(task.intro_text, 24),
                task.markdown_path,
                f"{task.attachment_count()} 个附件" if task.attachment_count() else "无",
                "是" if task.schedule_enabled else "否",
                task.scheduled_at.strftime("%Y-%m-%d %H:%M:%S") if task.scheduled_at else "",
                task.status,
            ]
            tooltip = "\n".join(
                x
                for x in [
                    f"任务ID：{task.task_id}",
                    f"备注：{task.note}" if task.note else "",
                    f"最近结果：{task.last_send_result}" if task.last_send_result else "",
                    f"说明：{task.error_message}" if task.error_message else "",
                ]
                if x
            )
            for col, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                item.setToolTip(tooltip)
                if col == 0:
                    item.setTextAlignment(QtCore.Qt.AlignCenter)
                if col == 9:
                    color = STATUS_COLORS.get(task.status)
                    if color:
                        item.setBackground(QtGui.QColor(color))
                self._task_table.setItem(row, col, item)

    def _refresh_ui_state(self) -> None:
        selected_count = len(self._selected_rows())
        has_package = self._package_dir is not None
        has_selection = selected_count > 0
        has_single = selected_count == 1
        is_busy = self._send_worker is not None or self._draft_worker is not None
        can_send = has_package and self._smtp_connected and not is_busy
        can_edit = has_package and not is_busy

        self._reload_package_btn.setEnabled(has_package)
        self._open_package_btn.setEnabled(has_package)
        self._open_tasks_btn.setEnabled(has_package)
        self._open_readme_btn.setEnabled(has_package)

        self._add_btn.setEnabled(can_edit)
        self._edit_btn.setEnabled(can_edit and has_single)
        self._copy_btn.setEnabled(can_edit and has_selection)
        self._delete_btn.setEnabled(can_edit and has_selection)
        self._preview_btn.setEnabled(has_package and has_single)
        self._save_drafts_btn.setEnabled(can_send and has_selection)
        self._send_now_btn.setEnabled(can_send and has_selection)
        self._queue_btn.setEnabled(can_send and has_selection)
        self._retry_btn.setEnabled(can_send and any(task.status == "发送失败" for task in self._tasks))
        self._open_last_run_btn.setEnabled(self._last_run_dir is not None or runs_dir(self._home_dir).exists())

        if self._package_dir:
            self._package_label.setText(
                f"当前任务包：{self._package_dir}\n工作目录：{self._home_dir}\n模板目录：{self._package_root()}"
            )

        enabled_tasks = [task for task in self._tasks if task.enabled]
        ready = sum(1 for task in self._tasks if task.status == "可发送")
        queued = len(self._queued_task_ids)
        failed = sum(1 for task in self._tasks if task.status == "发送失败")
        selected_desc = f"当前选中：{selected_count} 条" if has_selection else "当前未选中任务"
        last_run = str(self._last_run_dir) if self._last_run_dir else "暂无"
        package_name = self._package_dir.name if self._package_dir else "未导入"
        smtp_desc = "已连接" if self._smtp_connected else "未连接"
        self._status_label.setText(
            f"任务包：{package_name} | SMTP：{smtp_desc} | 启用任务：{len(enabled_tasks)} | 可发送：{ready} | "
            f"定时队列：{queued} | 失败：{failed}\n{selected_desc}\n最近一次输出：{last_run}"
        )

    def _start_send(self, tasks: list[MailTask], *, queue_mode: bool) -> None:
        if not self._package_dir:
            return
        if self._send_worker is not None or self._draft_worker is not None:
            QtWidgets.QMessageBox.information(self, "正在发送", "当前已有发送任务在执行，请稍候。")
            return
        if not tasks:
            QtWidgets.QMessageBox.information(self, "没有可发送任务", "请先选择或准备好可发送的任务。")
            return

        self._sending_task_ids.update({task.task_id for task in tasks})
        self._refresh_task_table()
        self._refresh_ui_state()

        worker = SendTasksWorker(
            tasks=tasks,
            package_dir=self._package_dir,
            home_dir=self._home_dir,
            smtp_cfg=self._smtp_cfg,
            smtp_password=self._smtp_password,
        )
        self._send_worker = worker

        def _ok(result: object) -> None:
            assert isinstance(result, SendTasksResult)
            self._send_worker = None
            self._apply_send_result(result)
            if self._tray is not None and queue_mode:
                self._tray.showMessage(
                    "定时邮件已发送",
                    f"已完成 {len(result.outcomes)} 条任务。",
                    QtWidgets.QSystemTrayIcon.Information,
                    4000,
                )

        def _err(tb: str) -> None:
            self._send_worker = None
            error_text = tb.strip()
            for task in self._tasks:
                if task.task_id in self._sending_task_ids:
                    task.status = "发送失败"
                    task.error_message = error_text
                    task.last_send_result = "发送失败"
                    self._queued_task_ids.discard(task.task_id)
            self._sending_task_ids.clear()
            self._refresh_task_table()
            self._refresh_ui_state()
            QtWidgets.QMessageBox.critical(self, "发送失败", tb)

        worker.finished_ok.connect(_ok)
        worker.finished_err.connect(_err)
        worker.start()

    def _start_save_drafts(self, tasks: list[MailTask]) -> None:
        if not self._package_dir:
            return
        if self._send_worker is not None or self._draft_worker is not None:
            QtWidgets.QMessageBox.information(self, "请稍候", "当前已有发送/草稿任务在执行，请稍候。")
            return
        if not tasks:
            QtWidgets.QMessageBox.information(self, "没有可保存任务", "请先选择或准备好可保存的任务。")
            return

        self._drafting_task_ids.update({task.task_id for task in tasks})
        self._refresh_task_table()
        self._refresh_ui_state()

        worker = SaveDraftsWorker(
            tasks=tasks,
            package_dir=self._package_dir,
            home_dir=self._home_dir,
            imap_username=self._from_email_input.text().strip(),
            imap_password=self._smtp_password,
        )
        self._draft_worker = worker

        def _ok(result: object) -> None:
            assert isinstance(result, SendTasksResult)
            self._draft_worker = None
            self._apply_draft_result(result)

        def _err(tb: str) -> None:
            self._draft_worker = None
            error_text = tb.strip()
            for task in self._tasks:
                if task.task_id in self._drafting_task_ids:
                    task.status = "草稿保存失败"
                    task.error_message = error_text
                    task.last_send_result = "草稿保存失败"
            self._drafting_task_ids.clear()
            self._refresh_task_table()
            self._refresh_ui_state()
            QtWidgets.QMessageBox.critical(self, "保存草稿失败", tb)

        worker.finished_ok.connect(_ok)
        worker.finished_err.connect(_err)
        worker.start()

    def _apply_send_result(self, result: SendTasksResult) -> None:
        self._last_run_dir = result.run_paths.run_dir
        outcome_map = {outcome.task_id: outcome for outcome in result.outcomes}
        for task in self._tasks:
            outcome = outcome_map.get(task.task_id)
            if outcome is None:
                continue
            self._sending_task_ids.discard(task.task_id)
            self._queued_task_ids.discard(task.task_id)
            if outcome.status == "sent":
                task.status = "发送成功"
                task.error_message = ""
                task.last_send_result = f"发送成功 {outcome.message_id or ''}".strip()
            else:
                task.status = "发送失败"
                task.error_message = outcome.error or "未知错误"
                task.last_send_result = "发送失败"
        self._refresh_task_table()
        self._refresh_ui_state()
        sent_count = sum(1 for x in result.outcomes if x.status == "sent")
        failed_count = len(result.outcomes) - sent_count
        QtWidgets.QMessageBox.information(
            self,
            "发送完成",
            f"本次输出目录：{result.run_paths.run_dir}\n发送成功：{sent_count}\n发送失败：{failed_count}",
        )

    def _apply_draft_result(self, result: SendTasksResult) -> None:
        self._last_run_dir = result.run_paths.run_dir
        outcome_map = {outcome.task_id: outcome for outcome in result.outcomes}
        for task in self._tasks:
            outcome = outcome_map.get(task.task_id)
            if outcome is None:
                continue
            self._drafting_task_ids.discard(task.task_id)
            if outcome.status == "draft_saved":
                task.status = "草稿已保存"
                task.error_message = ""
                task.last_send_result = f"草稿已保存 {outcome.message_id or ''}".strip()
            else:
                task.status = "草稿保存失败"
                task.error_message = outcome.error or "未知错误"
                task.last_send_result = "草稿保存失败"
        self._refresh_task_table()
        self._refresh_ui_state()
        ok_count = sum(1 for x in result.outcomes if x.status == "draft_saved")
        fail_count = len(result.outcomes) - ok_count
        QtWidgets.QMessageBox.information(
            self,
            "保存草稿完成",
            f"本次输出目录：{result.run_paths.run_dir}\n草稿保存成功：{ok_count}\n草稿保存失败：{fail_count}",
        )

    def _save_selected_to_drafts(self) -> None:
        if not self._smtp_connected:
            QtWidgets.QMessageBox.warning(self, "尚未连接 SMTP", "请先完成顶部 SMTP 连接。")
            return
        tasks = self._selected_tasks()
        if not tasks:
            QtWidgets.QMessageBox.information(self, "未选择任务", "请先选择至少一条任务。")
            return

        valid: list[MailTask] = []
        blocked: list[str] = []
        for task in tasks:
            errors = self._validate_task(task, check_schedule_time=False)
            if errors:
                blocked.append(f"{task.subject or task.task_id}：{'；'.join(errors)}")
            else:
                valid.append(task)

        if blocked:
            QtWidgets.QMessageBox.warning(self, "存在不可保存任务", "\n\n".join(blocked[:10]))
        if not valid:
            return

        reply = QtWidgets.QMessageBox.question(
            self,
            "确认保存草稿",
            f"将把选中的 {len(valid)} 条任务写入邮箱草稿箱，不会直接发送。确认继续吗？",
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return

        self._start_save_drafts(valid)

    def _send_selected_now(self) -> None:
        if not self._smtp_connected:
            QtWidgets.QMessageBox.warning(self, "尚未连接 SMTP", "请先完成顶部 SMTP 连接。")
            return
        tasks = self._selected_tasks()
        if not tasks:
            QtWidgets.QMessageBox.information(self, "未选择任务", "请先选择至少一条任务。")
            return

        valid: list[MailTask] = []
        blocked: list[str] = []
        for task in tasks:
            errors = self._validate_task(task, check_schedule_time=False)
            if errors:
                blocked.append(f"{task.subject or task.task_id}：{'；'.join(errors)}")
            else:
                valid.append(task)

        if blocked:
            QtWidgets.QMessageBox.warning(self, "存在不可发送任务", "\n\n".join(blocked[:10]))
        if not valid:
            return

        reply = QtWidgets.QMessageBox.question(
            self,
            "确认立即发送",
            f"将立即发送选中的 {len(valid)} 条任务，并忽略它们的定时设置。确认继续吗？",
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return

        self._start_send(valid, queue_mode=False)

    def _queue_selected_tasks(self) -> None:
        if not self._smtp_connected:
            QtWidgets.QMessageBox.warning(self, "尚未连接 SMTP", "请先完成顶部 SMTP 连接。")
            return
        tasks = self._selected_tasks()
        if not tasks:
            QtWidgets.QMessageBox.information(self, "未选择任务", "请先选择至少一条任务。")
            return

        errors: list[str] = []
        queued = 0
        for task in tasks:
            if not task.schedule_enabled:
                errors.append(f"{task.subject or task.task_id}：未勾选定时发送")
                continue
            task_errors = self._validate_task(task, check_schedule_time=True)
            if task_errors:
                errors.append(f"{task.subject or task.task_id}：{'；'.join(task_errors)}")
                continue
            self._queued_task_ids.add(task.task_id)
            task.status = "已加入定时队列"
            task.error_message = ""
            queued += 1

        self._refresh_task_table()
        self._refresh_ui_state()
        message = f"已加入定时队列：{queued} 条。"
        if errors:
            message += "\n\n以下任务未加入：\n" + "\n".join(errors[:10])
        QtWidgets.QMessageBox.information(self, "定时队列结果", message)

    def _retry_failed_tasks(self) -> None:
        failed = [task for task in self._tasks if task.status == "发送失败" and task.enabled]
        if not failed:
            QtWidgets.QMessageBox.information(self, "无需重试", "当前没有可重试的失败任务。")
            return

        blocked: list[str] = []
        valid: list[MailTask] = []
        for task in failed:
            errors = self._validate_task(task, check_schedule_time=False)
            if errors:
                blocked.append(f"{task.subject or task.task_id}：{'；'.join(errors)}")
            else:
                valid.append(task)
        if blocked:
            QtWidgets.QMessageBox.warning(self, "部分失败任务仍不可发送", "\n".join(blocked[:10]))
        if not valid:
            return
        self._start_send(valid, queue_mode=False)

    def _process_scheduled_tasks(self) -> None:
        if not self._smtp_connected or self._send_worker is not None or self._draft_worker is not None or not self._package_dir:
            return
        now = datetime.now()
        due_tasks: list[MailTask] = []
        for task in self._tasks:
            if task.task_id not in self._queued_task_ids:
                continue
            if not task.schedule_enabled or task.scheduled_at is None:
                task.status = "发送失败"
                task.error_message = "任务已在定时队列中，但缺少合法发送时间"
                task.last_send_result = "发送失败"
                self._queued_task_ids.discard(task.task_id)
                continue
            if task.scheduled_at > now:
                continue
            errors = self._validate_task(task, check_schedule_time=False)
            if errors:
                task.status = "发送失败"
                task.error_message = "\n".join(errors)
                task.last_send_result = "发送失败"
                self._queued_task_ids.discard(task.task_id)
                continue
            due_tasks.append(task)

        if due_tasks:
            self._start_send(due_tasks, queue_mode=True)
        else:
            self._refresh_task_table()
            self._refresh_ui_state()


def run() -> int:
    app = QtWidgets.QApplication([])
    window = MainWindow()
    window.show()
    return app.exec()
