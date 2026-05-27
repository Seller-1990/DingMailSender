from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dingmail.task_models import MailTask
from dingmail.task_package import (
    TASKS_FILENAME,
    TASKS_SHEET_NAME,
    ensure_unique_task_ids,
    load_tasks_from_package,
    package_relpath,
    resolve_user_path,
    save_tasks_to_package,
)


class TaskPackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="dingmail_task_package_")
        self.addCleanup(self._tmp.cleanup)
        self.package_dir = Path(self._tmp.name)
        (self.package_dir / "content").mkdir()
        (self.package_dir / "attachments").mkdir()
        (self.package_dir / "content" / "body.md").write_text("# 标题\n\n正文", encoding="utf-8")

    def test_resolve_user_path_rejects_paths_outside_package(self) -> None:
        outside = self.package_dir.parent / "outside.md"
        outside.write_text("x", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "任务包目录内"):
            resolve_user_path(self.package_dir, str(outside))

        with self.assertRaisesRegex(ValueError, "任务包目录内"):
            resolve_user_path(self.package_dir, "..\\outside.md")

    def test_package_relpath_rejects_paths_outside_package(self) -> None:
        outside = self.package_dir.parent / "outside.md"
        outside.write_text("x", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "任务包目录内"):
            package_relpath(self.package_dir, outside)

    def test_load_tasks_prefers_named_tasks_sheet(self) -> None:
        workbook = openpyxl.Workbook()
        meta = workbook.active
        meta.title = "Meta"
        meta["A1"] = "not tasks"

        tasks = workbook.create_sheet(TASKS_SHEET_NAME)
        tasks.append(
            ["任务ID", "是否启用", "收件人", "抄送人", "主题", "开头/补充内容", "Markdown路径", "是否有附件", "附件路径", "是否定时发送", "定时发送时间", "备注"]
        )
        tasks.append(["task-1", "是", "a@example.com", "", "主题", "", "content/body.md", "否", "", "否", "", ""])
        workbook.active = 0
        workbook.save(self.package_dir / TASKS_FILENAME)
        workbook.close()

        loaded = load_tasks_from_package(self.package_dir)
        self.assertEqual(1, len(loaded))
        self.assertEqual("task-1", loaded[0].task_id)
        self.assertEqual(["a@example.com"], loaded[0].to_recipients)

    def test_save_tasks_preserves_other_sheets(self) -> None:
        workbook = openpyxl.Workbook()
        tasks = workbook.active
        tasks.title = TASKS_SHEET_NAME
        tasks["A1"] = "old"
        tasks.freeze_panes = "B2"
        tasks.column_dimensions["A"].width = 24
        meta = workbook.create_sheet("Meta")
        meta["A1"] = "keep me"
        workbook.save(self.package_dir / TASKS_FILENAME)
        workbook.close()

        save_tasks_to_package(
            self.package_dir,
            [
                MailTask(
                    task_id="task-1",
                    to_recipients=["a@example.com"],
                    subject="主题",
                    markdown_path="content/body.md",
                )
            ],
        )

        saved = openpyxl.load_workbook(self.package_dir / TASKS_FILENAME)
        self.addCleanup(saved.close)
        self.assertIn(TASKS_SHEET_NAME, saved.sheetnames)
        self.assertIn("Meta", saved.sheetnames)
        self.assertEqual("keep me", saved["Meta"]["A1"].value)
        self.assertEqual("任务ID", saved[TASKS_SHEET_NAME]["A1"].value)
        self.assertEqual("task-1", saved[TASKS_SHEET_NAME]["A2"].value)
        self.assertEqual("B2", saved[TASKS_SHEET_NAME].freeze_panes)
        self.assertEqual(24, saved[TASKS_SHEET_NAME].column_dimensions["A"].width)

    def test_ensure_unique_task_ids_repairs_missing_and_duplicate_ids(self) -> None:
        tasks = [
            MailTask(task_id="task-1", markdown_path="content/body.md"),
            MailTask(task_id="task-1", markdown_path="content/body.md"),
            MailTask(task_id="", markdown_path="content/body.md"),
        ]

        repairs = ensure_unique_task_ids(tasks)
        self.assertEqual(2, len(repairs))
        self.assertEqual(3, len({task.task_id for task in tasks}))
        self.assertTrue(all(task.task_id for task in tasks))

    def test_save_tasks_repairs_duplicate_and_missing_task_ids(self) -> None:
        tasks = [
            MailTask(task_id="task-1", to_recipients=["a@example.com"], subject="主题1", markdown_path="content/body.md"),
            MailTask(task_id="task-1", to_recipients=["b@example.com"], subject="主题2", markdown_path="content/body.md"),
            MailTask(task_id="", to_recipients=["c@example.com"], subject="主题3", markdown_path="content/body.md"),
        ]

        save_tasks_to_package(self.package_dir, tasks)

        self.assertEqual(3, len({task.task_id for task in tasks}))
        self.assertTrue(all(task.task_id for task in tasks))

        loaded = load_tasks_from_package(self.package_dir)
        self.assertEqual(3, len(loaded))
        self.assertEqual(3, len({task.task_id for task in loaded}))
        self.assertTrue(all(task.task_id for task in loaded))


if __name__ == "__main__":
    unittest.main()
