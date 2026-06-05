from __future__ import annotations

import uuid
from dataclasses import asdict

from .task_models import MailTask


def clone_task(task: MailTask) -> MailTask:
    data = asdict(task)
    data["task_id"] = uuid.uuid4().hex
    return MailTask(**data)
