"""投递编排：worker 生命周期、进度与完成信号。

结果的应用（runtime 状态、tasks.xlsx 回写）在 TaskController 中完成；
本服务只负责线程生命周期与信号转发。
"""
from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore

from ...model import SmtpConfig
from ..workers import DraftWorkerConfig, SaveDraftsWorker, SendTasksWorker, SendWorkerConfig


class DeliveryService(QtCore.QObject):
    progressChanged = QtCore.Signal(int, int)
    sendFinished = QtCore.Signal(object)   # SendTasksResult
    draftFinished = QtCore.Signal(object)  # SendTasksResult
    failed = QtCore.Signal(str, str)       # (kind: "send"|"draft", traceback)

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._send_worker: SendTasksWorker | None = None
        self._draft_worker: SaveDraftsWorker | None = None

    # ---- 状态 ----

    @property
    def busy(self) -> bool:
        return self._send_worker is not None or self._draft_worker is not None

    # ---- 启动 ----

    def start_send(
        self,
        *,
        tasks: list,
        package_dir: Path,
        home_dir: Path,
        smtp_cfg: SmtpConfig,
        smtp_password: str,
        rate_limit_seconds: float,
    ) -> bool:
        if self.busy or not tasks:
            return False
        worker = SendTasksWorker(
            SendWorkerConfig(
                tasks=list(tasks),
                package_dir=package_dir,
                home_dir=home_dir,
                smtp_cfg=smtp_cfg,
                smtp_password=smtp_password,
                rate_limit_seconds=rate_limit_seconds,
            )
        )
        self._send_worker = worker
        worker.finished_ok.connect(self._on_send_ok)
        worker.finished_err.connect(self._on_send_err)
        worker.progress.connect(self.progressChanged.emit)
        worker.start()
        return True

    def start_drafts(
        self,
        *,
        tasks: list,
        package_dir: Path,
        home_dir: Path,
        imap_username: str,
        imap_password: str,
        imap_host: str,
        imap_port: int,
        rate_limit_seconds: float,
    ) -> bool:
        if self.busy or not tasks:
            return False
        worker = SaveDraftsWorker(
            DraftWorkerConfig(
                tasks=list(tasks),
                package_dir=package_dir,
                home_dir=home_dir,
                imap_username=imap_username,
                imap_password=imap_password,
                imap_host=imap_host,
                imap_port=imap_port,
                rate_limit_seconds=rate_limit_seconds,
            )
        )
        self._draft_worker = worker
        worker.finished_ok.connect(self._on_draft_ok)
        worker.finished_err.connect(self._on_draft_err)
        worker.progress.connect(self.progressChanged.emit)
        worker.start()
        return True

    # ---- 完成 ----

    def _on_send_ok(self, result) -> None:
        self._send_worker = None
        self.sendFinished.emit(result)

    def _on_draft_ok(self, result) -> None:
        self._draft_worker = None
        self.draftFinished.emit(result)

    def _on_send_err(self, tb: str) -> None:
        self._send_worker = None
        self.failed.emit("send", tb)

    def _on_draft_err(self, tb: str) -> None:
        self._draft_worker = None
        self.failed.emit("draft", tb)

    # ---- 取消与等待 ----

    def request_cancel(self) -> None:
        for worker in (self._send_worker, self._draft_worker):
            if worker is not None:
                worker.request_cancel()

    def wait_all(self, timeout_ms: int) -> bool:
        """等待所有投递 worker 结束；超时返回 False。"""
        for worker in (self._send_worker, self._draft_worker):
            if worker is not None and not worker.wait(timeout_ms):
                return False
        return True
