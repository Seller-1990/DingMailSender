from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PySide6 import QtWidgets

from ..constants import DEFAULT_IMAP_HOST, DEFAULT_IMAP_PORT_SSL, DEFAULT_RATE_LIMIT_SECONDS
from ..model import SmtpConfig
from ..task_models import MailTask
from .task_runtime import TaskRuntimeController
from .widgets import MetricTile


@dataclass
class MainWindowState:
    home_dir: Path
    conn_config_path: Path
    legacy_conn_config_paths: list[Path]
    smtp_cfg: SmtpConfig = field(default_factory=SmtpConfig)
    smtp_password: str = ""
    smtp_connected: bool = False
    imap_host: str = DEFAULT_IMAP_HOST
    imap_port: int = DEFAULT_IMAP_PORT_SSL
    package_dir: Path | None = None
    tasks: list[MailTask] = field(default_factory=list)
    runtime: TaskRuntimeController = field(default_factory=TaskRuntimeController)
    last_run_dir: Path | None = None
    quit_requested: bool = False
    close_tip_shown: bool = False
    active_filter: str = "all"
    send_rate_limit_seconds: float = DEFAULT_RATE_LIMIT_SECONDS
    runs_retention_days: int = 0
    splitter_sizes: list[int] = field(default_factory=list)
    connection_profile_error: str = ""
    connection_profile_source_text: str = "配置：默认参数（未保存）"
    connection_profile_source_detail: str = ""
    connection_profile_warning: str = ""
    metric_tiles: dict[str, MetricTile] = field(default_factory=dict)
    filter_buttons: dict[str, QtWidgets.QPushButton] = field(default_factory=dict)
