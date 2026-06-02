from __future__ import annotations

import copy
import traceback
from dataclasses import dataclass
from pathlib import Path

from PySide6 import QtCore

from ..constants import DEFAULT_IMAP_HOST, DEFAULT_IMAP_PORT_SSL
from ..model import SmtpConfig
from ..smtp_sender import SmtpSession
from ..task_delivery import (
    DraftsConfig,
    SendTasksConfig as DeliverySendTasksConfig,
    save_tasks_to_imap_drafts,
    send_tasks,
)
from ..task_models import MailTask


@dataclass(frozen=True)
class SendWorkerConfig:
    tasks: list[MailTask]
    package_dir: Path
    home_dir: Path
    smtp_cfg: SmtpConfig
    smtp_password: str


@dataclass(frozen=True)
class DraftWorkerConfig:
    tasks: list[MailTask]
    package_dir: Path
    home_dir: Path
    imap_username: str
    imap_password: str


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

    def __init__(self, config: SendWorkerConfig) -> None:
        super().__init__()
        self._tasks = copy.deepcopy(config.tasks)
        self._package_dir = config.package_dir
        self._home_dir = config.home_dir
        self._smtp_cfg = config.smtp_cfg
        self._smtp_password = config.smtp_password

    def run(self) -> None:  # noqa: N802
        try:
            result = send_tasks(
                DeliverySendTasksConfig(
                    tasks=self._tasks,
                    package_dir=self._package_dir,
                    home_dir=self._home_dir,
                    smtp_host=self._smtp_cfg.host,
                    smtp_port=self._smtp_cfg.port,
                    smtp_security=self._smtp_cfg.security,
                    smtp_username=self._smtp_cfg.username,
                    smtp_password=self._smtp_password,
                )
            )
            self.finished_ok.emit(result)
        except Exception:
            self.finished_err.emit(traceback.format_exc())


class SaveDraftsWorker(QtCore.QThread):
    finished_ok = QtCore.Signal(object)
    finished_err = QtCore.Signal(str)

    def __init__(self, config: DraftWorkerConfig) -> None:
        super().__init__()
        self._tasks = copy.deepcopy(config.tasks)
        self._package_dir = config.package_dir
        self._home_dir = config.home_dir
        self._imap_username = config.imap_username
        self._imap_password = config.imap_password

    def run(self) -> None:  # noqa: N802
        try:
            result = save_tasks_to_imap_drafts(
                DraftsConfig(
                    tasks=self._tasks,
                    package_dir=self._package_dir,
                    home_dir=self._home_dir,
                    imap_username=self._imap_username,
                    imap_password=self._imap_password,
                    imap_host=DEFAULT_IMAP_HOST,
                    imap_port=DEFAULT_IMAP_PORT_SSL,
                )
            )
            self.finished_ok.emit(result)
        except Exception:
            self.finished_err.emit(traceback.format_exc())
