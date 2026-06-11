from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dingmail.gui.task_runtime import TaskRuntimeController
from dingmail.task_models import MailTask
from dingmail.task_status import TaskStatus


class TaskRuntimeQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="dingmail_runtime_")
        self.addCleanup(self._tmp.cleanup)
        self.package_dir = Path(self._tmp.name)
        (self.package_dir / "content").mkdir()
        (self.package_dir / "content" / "body.md").write_text("正文", encoding="utf-8")
        self.controller = TaskRuntimeController()
        self.controller.set_package_dir(self.package_dir)

    def _scheduled_task(self) -> MailTask:
        return MailTask(
            task_id="task-1",
            to_recipients=["a@example.com"],
            subject="主题",
            markdown_path="content/body.md",
            schedule_enabled=True,
            scheduled_at=datetime.now() - timedelta(minutes=1),
        )

    def test_collect_due_tasks_quietly_dequeues_task_edited_to_non_scheduled(self) -> None:
        task = self._scheduled_task()
        self.controller.queued_task_ids.add(task.task_id)
        task.schedule_enabled = False

        due = self.controller.collect_due_tasks([task], now=datetime.now())

        self.assertEqual([], due)
        self.assertNotIn(task.task_id, self.controller.queued_task_ids)
        self.assertNotEqual(TaskStatus.SEND_FAILED, self.controller.status_for(task))

    def test_collect_due_tasks_returns_due_scheduled_task(self) -> None:
        task = self._scheduled_task()
        self.controller.queued_task_ids.add(task.task_id)

        due = self.controller.collect_due_tasks([task], now=datetime.now())

        self.assertEqual([task], due)

    def test_sync_task_ids_drops_queued_tasks_with_schedule_disabled(self) -> None:
        task = self._scheduled_task()
        self.controller.queued_task_ids.add(task.task_id)
        task.schedule_enabled = False

        self.controller.sync_task_ids([task])

        self.assertNotIn(task.task_id, self.controller.queued_task_ids)


if __name__ == "__main__":
    unittest.main()
