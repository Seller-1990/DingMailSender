from __future__ import annotations

from enum import StrEnum


class TaskStatus(StrEnum):
    DISABLED = "已停用"
    UNCHECKED = "未校验"
    VALIDATION_FAILED = "校验失败"
    QUEUED = "已加入定时队列"
    SENDING = "发送中"
    DRAFTING = "草稿保存中"
    SENT = "发送成功"
    SEND_FAILED = "发送失败"
    DRAFT_SAVED = "草稿已保存"
    DRAFT_FAILED = "草稿保存失败"
    READY = "可发送"

    @classmethod
    def terminal_statuses(cls) -> set["TaskStatus"]:
        return {cls.SENT, cls.SEND_FAILED, cls.DRAFT_SAVED, cls.DRAFT_FAILED}

    @property
    def label(self) -> str:
        return str(self.value)
