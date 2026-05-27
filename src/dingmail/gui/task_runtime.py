from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re

from ..task_delivery import SendTasksResult
from ..task_models import MailTask
from ..task_package import resolve_user_path
from ..task_service import validate_task

EMAIL_RE = re.compile(r"^[^@\s;]+@[^@\s]+\.[^@\s]+$")


class TaskRuntimeController:
    def __init__(self) -> None:
        self._package_dir: Path | None = None
        self._validation_cache: dict[str, tuple[tuple[object, ...], list[str]]] = {}
        self.queued_task_ids: set[str] = set()
        self.sending_task_ids: set[str] = set()
        self.drafting_task_ids: set[str] = set()

    def set_package_dir(self, package_dir: Path | None) -> None:
        self._package_dir = package_dir

    def invalidate_validation_cache(self) -> None:
        self._validation_cache.clear()

    def reset_loaded_tasks(self, package_dir: Path, tasks: list[MailTask]) -> None:
        self.set_package_dir(package_dir)
        self.invalidate_validation_cache()
        self.queued_task_ids.clear()
        self.sending_task_ids.clear()
        self.drafting_task_ids.clear()
        for task in tasks:
            self.reset_runtime_fields(task)

    def sync_task_ids(self, tasks: list[MailTask]) -> None:
        valid_ids = {task.task_id for task in tasks}
        self.queued_task_ids.intersection_update(valid_ids)
        self.sending_task_ids.intersection_update(valid_ids)
        self.drafting_task_ids.intersection_update(valid_ids)

    def reset_runtime_fields(self, task: MailTask) -> None:
        task.status = "未校验"
        task.error_message = ""
        task.last_send_result = ""

    def validate_task(self, task: MailTask, *, check_schedule_time: bool) -> list[str]:
        if not self._package_dir:
            return ["未导入任务包"]
        if not check_schedule_time:
            signature = self._task_validation_signature(task)
            cached = self._validation_cache.get(task.task_id)
            if cached and cached[0] == signature:
                return list(cached[1])

        errors = validate_task(task, self._package_dir, now=datetime.now() if check_schedule_time else None)
        invalid_to = [email for email in task.to_recipients if not EMAIL_RE.match(email)]
        invalid_cc = [email for email in task.cc_recipients if not EMAIL_RE.match(email)]
        if invalid_to:
            errors.append(f"收件人邮箱格式不合法：{'; '.join(invalid_to)}")
        if invalid_cc:
            errors.append(f"抄送邮箱格式不合法：{'; '.join(invalid_cc)}")

        if not check_schedule_time:
            self._validation_cache[task.task_id] = (self._task_validation_signature(task), list(errors))
        return errors

    def partition_valid_tasks(
        self,
        tasks: list[MailTask],
        *,
        check_schedule_time: bool,
    ) -> tuple[list[MailTask], list[str]]:
        valid: list[MailTask] = []
        blocked: list[str] = []
        for task in tasks:
            errors = self.validate_task(task, check_schedule_time=check_schedule_time)
            if errors:
                blocked.append(f"{task.subject or task.task_id}：{'；'.join(errors)}")
            else:
                valid.append(task)
        return valid, blocked

    def refresh_runtime_state(self, tasks: list[MailTask]) -> None:
        if not self._package_dir:
            return
        for task in tasks:
            if not task.enabled:
                task.status = "已停用"
                task.error_message = ""
                continue
            errors = self.validate_task(task, check_schedule_time=False)
            if errors:
                task.status = "校验失败"
                task.error_message = "\n".join(errors)
                continue
            if task.task_id in self.sending_task_ids:
                task.status = "发送中"
                continue
            if task.task_id in self.drafting_task_ids:
                task.status = "草稿保存中"
                continue
            if task.task_id in self.queued_task_ids and task.schedule_enabled:
                task.status = "已加入定时队列"
                task.error_message = ""
                continue
            if task.status in {"发送成功", "发送失败", "草稿已保存", "草稿保存失败"}:
                continue
            task.status = "可发送"
            task.error_message = ""

    def mark_sending(self, tasks: list[MailTask]) -> None:
        self.sending_task_ids.update(task.task_id for task in tasks)

    def mark_drafting(self, tasks: list[MailTask]) -> None:
        self.drafting_task_ids.update(task.task_id for task in tasks)

    def mark_send_worker_error(self, tasks: list[MailTask], error_text: str) -> None:
        for task in tasks:
            if task.task_id not in self.sending_task_ids:
                continue
            task.status = "发送失败"
            task.error_message = error_text
            task.last_send_result = "发送失败"
            self.queued_task_ids.discard(task.task_id)
        self.sending_task_ids.clear()

    def mark_draft_worker_error(self, tasks: list[MailTask], error_text: str) -> None:
        for task in tasks:
            if task.task_id not in self.drafting_task_ids:
                continue
            task.status = "草稿保存失败"
            task.error_message = error_text
            task.last_send_result = "草稿保存失败"
        self.drafting_task_ids.clear()

    def apply_send_result(self, tasks: list[MailTask], result: SendTasksResult) -> tuple[int, int]:
        outcome_map = {outcome.task_id: outcome for outcome in result.outcomes}
        for task in tasks:
            outcome = outcome_map.get(task.task_id)
            if outcome is None:
                continue
            self.sending_task_ids.discard(task.task_id)
            self.queued_task_ids.discard(task.task_id)
            if outcome.status == "sent":
                task.status = "发送成功"
                task.error_message = ""
                task.last_send_result = f"发送成功 {outcome.message_id or ''}".strip()
            else:
                task.status = "发送失败"
                task.error_message = outcome.error or "未知错误"
                task.last_send_result = "发送失败"

        success_count = sum(1 for outcome in result.outcomes if outcome.status == "sent")
        return success_count, len(result.outcomes) - success_count

    def apply_draft_result(self, tasks: list[MailTask], result: SendTasksResult) -> tuple[int, int]:
        outcome_map = {outcome.task_id: outcome for outcome in result.outcomes}
        for task in tasks:
            outcome = outcome_map.get(task.task_id)
            if outcome is None:
                continue
            self.drafting_task_ids.discard(task.task_id)
            if outcome.status == "draft_saved":
                task.status = "草稿已保存"
                task.error_message = ""
                task.last_send_result = f"草稿已保存 {outcome.message_id or ''}".strip()
            else:
                task.status = "草稿保存失败"
                task.error_message = outcome.error or "未知错误"
                task.last_send_result = "草稿保存失败"

        success_count = sum(1 for outcome in result.outcomes if outcome.status == "draft_saved")
        return success_count, len(result.outcomes) - success_count

    def queue_scheduled_tasks(self, tasks: list[MailTask]) -> tuple[int, list[str]]:
        errors: list[str] = []
        queued = 0
        for task in tasks:
            if not task.schedule_enabled:
                errors.append(f"{task.subject or task.task_id}：未勾选定时发送")
                continue
            task_errors = self.validate_task(task, check_schedule_time=True)
            if task_errors:
                errors.append(f"{task.subject or task.task_id}：{'；'.join(task_errors)}")
                continue
            self.queued_task_ids.add(task.task_id)
            task.status = "已加入定时队列"
            task.error_message = ""
            queued += 1
        return queued, errors

    def collect_due_tasks(self, tasks: list[MailTask], now: datetime | None = None) -> list[MailTask]:
        current_time = now or datetime.now()
        due_tasks: list[MailTask] = []
        for task in tasks:
            if task.task_id not in self.queued_task_ids:
                continue
            if not task.schedule_enabled or task.scheduled_at is None:
                task.status = "发送失败"
                task.error_message = "任务已在定时队列中，但缺少合法发送时间"
                task.last_send_result = "发送失败"
                self.queued_task_ids.discard(task.task_id)
                continue
            if task.scheduled_at > current_time:
                continue
            errors = self.validate_task(task, check_schedule_time=False)
            if errors:
                task.status = "发送失败"
                task.error_message = "\n".join(errors)
                task.last_send_result = "发送失败"
                self.queued_task_ids.discard(task.task_id)
                continue
            due_tasks.append(task)
        return due_tasks

    def _task_validation_signature(self, task: MailTask) -> tuple[object, ...]:
        return (
            task.task_id,
            task.enabled,
            tuple(task.to_recipients),
            tuple(task.cc_recipients),
            task.subject.strip(),
            self._path_validation_signature(task.markdown_path),
            tuple(self._path_validation_signature(path) for path in task.attachment_paths),
            task.schedule_enabled,
            task.scheduled_at,
        )

    def _path_validation_signature(self, raw_path: str) -> tuple[object, ...]:
        path_text = str(raw_path or "").strip()
        if not path_text or not self._package_dir:
            return (path_text,)
        try:
            resolved = resolve_user_path(self._package_dir, path_text)
        except Exception as exc:
            return ("invalid", path_text, str(exc))
        try:
            stat = resolved.stat()
        except FileNotFoundError:
            return ("missing", str(resolved))
        return ("file", str(resolved), stat.st_mtime_ns, stat.st_size)
