from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..task_delivery import DeliveryStatus, SendTasksResult
from ..task_models import MailTask
from ..task_package import resolve_user_path
from ..task_service import validate_task
from ..task_status import TaskStatus


@dataclass
class TaskRuntimeState:
    status: TaskStatus = TaskStatus.UNCHECKED
    error_message: str = ""
    last_previewed_at: datetime | None = None
    last_result: str = ""


class TaskRuntimeController:
    def __init__(self) -> None:
        self._package_dir: Path | None = None
        self._validation_cache: dict[str, tuple[tuple[object, ...], list[str]]] = {}
        self._states: dict[str, TaskRuntimeState] = {}
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
        self._states = {task.task_id: TaskRuntimeState() for task in tasks}

        # 从持久化的 last_delivery_status 恢复终态，防止崩溃后重复发送
        for task in tasks:
            persisted = task.last_delivery_status.strip().lower()
            if persisted in ("sent", "send_error", "send_skipped"):
                self._states[task.task_id].status = TaskStatus.SENT if persisted == "sent" else TaskStatus.SEND_FAILED
                self._states[task.task_id].last_result = persisted
            elif persisted in ("draft_saved", "draft_error", "draft_skipped"):
                self._states[task.task_id].status = TaskStatus.DRAFT_SAVED if persisted == "draft_saved" else TaskStatus.DRAFT_FAILED
                self._states[task.task_id].last_result = persisted

        # 定时任务自动回归队列：队列只存在于内存，重启/重载后按任务表重新推导，
        # 否则重启后定时任务会静默失效。已终态、已停用、已过期的不入队
        #（过期任务不自动补发，避免启动即涌出陈旧邮件；由用户手动重排队）。
        now = datetime.now()
        for task in tasks:
            state = self._states[task.task_id]
            if not task.enabled or not task.schedule_enabled or task.scheduled_at is None:
                continue
            if state.status in TaskStatus.terminal_statuses():
                continue
            if task.scheduled_at <= now:
                continue
            if not self.validate_task(task, check_schedule_time=False):
                self.queued_task_ids.add(task.task_id)

    def sync_task_ids(self, tasks: list[MailTask]) -> None:
        valid_ids = {task.task_id for task in tasks}
        # 编辑后取消定时的任务同步移出队列，避免调度器把它误判为失败。
        schedulable_ids = {task.task_id for task in tasks if task.schedule_enabled}
        self.queued_task_ids.intersection_update(schedulable_ids)
        self.sending_task_ids.intersection_update(valid_ids)
        self.drafting_task_ids.intersection_update(valid_ids)
        self._states = {task_id: state for task_id, state in self._states.items() if task_id in valid_ids}
        for task in tasks:
            self._state_for_task_id(task.task_id)

    def reset_runtime_fields(self, task: MailTask) -> None:
        self._states[task.task_id] = TaskRuntimeState()

    def state_for(self, task: MailTask) -> TaskRuntimeState:
        return self._state_for_task_id(task.task_id)

    def status_for(self, task: MailTask) -> TaskStatus:
        return self.state_for(task).status

    def status_label_for(self, task: MailTask) -> str:
        return self.status_for(task).label

    def error_for(self, task: MailTask) -> str:
        return self.state_for(task).error_message

    def last_result_for(self, task: MailTask) -> str:
        return self.state_for(task).last_result

    def issue_text_for(self, task: MailTask) -> str:
        state = self.state_for(task)
        return state.error_message or state.last_result

    def mark_previewed(self, task: MailTask, when: datetime) -> None:
        self.state_for(task).last_previewed_at = when

    def validate_task(self, task: MailTask, *, check_schedule_time: bool) -> list[str]:
        if not self._package_dir:
            return ["未导入任务包"]
        if not check_schedule_time:
            signature = self._task_validation_signature(task)
            cached = self._validation_cache.get(task.task_id)
            if cached and cached[0] == signature:
                return list(cached[1])

        errors = validate_task(task, self._package_dir, now=datetime.now() if check_schedule_time else None)

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

    def refresh_runtime_state(self, tasks: list[MailTask], *, max_validate: int = 0) -> bool:
        """刷新任务运行时状态。

        Args:
            max_validate: 每次最多校验的未缓存任务数。0 表示不限制（全量校验）。

        Returns:
            True 表示所有任务都已完成校验，False 表示还有待校验任务（需要再次调用）。
        """
        if not self._package_dir:
            return True
        unchecked_count = 0
        for task in tasks:
            state = self.state_for(task)
            if not task.enabled:
                state.status = TaskStatus.DISABLED
                state.error_message = ""
                continue
            # 检查缓存是否命中
            if max_validate > 0:
                signature = self._task_validation_signature(task)
                cached = self._validation_cache.get(task.task_id)
                if cached is None or cached[0] != signature:
                    unchecked_count += 1
                    if unchecked_count > max_validate:
                        # 超出本轮限制，跳过（保持 UNCHECKED 状态）
                        if state.status == TaskStatus.UNCHECKED:
                            continue
                        elif state.status not in TaskStatus.terminal_statuses() and task.task_id not in self.sending_task_ids and task.task_id not in self.drafting_task_ids and task.task_id not in self.queued_task_ids:
                            state.status = TaskStatus.UNCHECKED
                            continue
                        continue
            errors = self.validate_task(task, check_schedule_time=False)
            if errors:
                state.status = TaskStatus.VALIDATION_FAILED
                state.error_message = "\n".join(errors)
                continue
            if task.task_id in self.sending_task_ids:
                state.status = TaskStatus.SENDING
                continue
            if task.task_id in self.drafting_task_ids:
                state.status = TaskStatus.DRAFTING
                continue
            if task.task_id in self.queued_task_ids and task.schedule_enabled:
                state.status = TaskStatus.QUEUED
                state.error_message = ""
                continue
            if state.status in TaskStatus.terminal_statuses():
                continue
            state.status = TaskStatus.READY
            state.error_message = ""
        # 返回是否全部完成
        if max_validate > 0 and unchecked_count > max_validate:
            return False
        return True

    def mark_sending(self, tasks: list[MailTask]) -> None:
        for task in tasks:
            self.sending_task_ids.add(task.task_id)
            self._set_state(task, status=TaskStatus.SENDING, error_message="")

    def mark_drafting(self, tasks: list[MailTask]) -> None:
        for task in tasks:
            self.drafting_task_ids.add(task.task_id)
            self._set_state(task, status=TaskStatus.DRAFTING, error_message="")

    def mark_send_worker_error(self, tasks: list[MailTask], error_text: str) -> None:
        for task in tasks:
            if task.task_id not in self.sending_task_ids:
                continue
            self._set_state(
                task,
                status=TaskStatus.SEND_FAILED,
                error_message=error_text,
                last_result=TaskStatus.SEND_FAILED.label,
            )
            self.queued_task_ids.discard(task.task_id)
        self.sending_task_ids.clear()

    def mark_draft_worker_error(self, tasks: list[MailTask], error_text: str) -> None:
        for task in tasks:
            if task.task_id not in self.drafting_task_ids:
                continue
            self._set_state(
                task,
                status=TaskStatus.DRAFT_FAILED,
                error_message=error_text,
                last_result=TaskStatus.DRAFT_FAILED.label,
            )
        self.drafting_task_ids.clear()

    def apply_send_result(self, tasks: list[MailTask], result: SendTasksResult) -> tuple[int, int]:
        outcome_map = {outcome.task_id: outcome for outcome in result.outcomes}
        for task in tasks:
            outcome = outcome_map.get(task.task_id)
            if outcome is None:
                continue
            self.sending_task_ids.discard(task.task_id)
            self.queued_task_ids.discard(task.task_id)
            if outcome.status is DeliveryStatus.SENT:
                self._set_state(
                    task,
                    status=TaskStatus.SENT,
                    error_message="",
                    last_result=f"{TaskStatus.SENT.label} {outcome.message_id or ''}".strip(),
                )
            else:
                self._set_state(
                    task,
                    status=TaskStatus.SEND_FAILED,
                    error_message=outcome.error or "未知错误",
                    last_result=TaskStatus.SEND_FAILED.label,
                )

        success_count = sum(1 for outcome in result.outcomes if outcome.status is DeliveryStatus.SENT)
        return success_count, len(result.outcomes) - success_count

    def apply_draft_result(self, tasks: list[MailTask], result: SendTasksResult) -> tuple[int, int]:
        outcome_map = {outcome.task_id: outcome for outcome in result.outcomes}
        for task in tasks:
            outcome = outcome_map.get(task.task_id)
            if outcome is None:
                continue
            self.drafting_task_ids.discard(task.task_id)
            if outcome.status is DeliveryStatus.DRAFT_SAVED:
                self._set_state(
                    task,
                    status=TaskStatus.DRAFT_SAVED,
                    error_message="",
                    last_result=f"{TaskStatus.DRAFT_SAVED.label} {outcome.message_id or ''}".strip(),
                )
            else:
                self._set_state(
                    task,
                    status=TaskStatus.DRAFT_FAILED,
                    error_message=outcome.error or "未知错误",
                    last_result=TaskStatus.DRAFT_FAILED.label,
                )

        success_count = sum(1 for outcome in result.outcomes if outcome.status is DeliveryStatus.DRAFT_SAVED)
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
            self._set_state(task, status=TaskStatus.QUEUED, error_message="")
            queued += 1
        return queued, errors

    def collect_due_tasks(self, tasks: list[MailTask], now: datetime | None = None) -> list[MailTask]:
        current_time = now or datetime.now()
        due_tasks: list[MailTask] = []
        for task in tasks:
            if task.task_id not in self.queued_task_ids:
                continue
            if not task.schedule_enabled or task.scheduled_at is None:
                # 任务入队后被编辑为非定时：静默出队即可，不应捏造一次从未发生的“发送失败”。
                self.queued_task_ids.discard(task.task_id)
                continue
            if task.scheduled_at > current_time:
                continue
            errors = self.validate_task(task, check_schedule_time=False)
            if errors:
                self._set_state(
                    task,
                    status=TaskStatus.SEND_FAILED,
                    error_message="\n".join(errors),
                    last_result=TaskStatus.SEND_FAILED.label,
                )
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

    def _state_for_task_id(self, task_id: str) -> TaskRuntimeState:
        return self._states.setdefault(task_id, TaskRuntimeState())

    def _set_state(
        self,
        task: MailTask,
        *,
        status: TaskStatus,
        error_message: str | None = None,
        last_result: str | None = None,
    ) -> None:
        state = self.state_for(task)
        state.status = status
        if error_message is not None:
            state.error_message = error_message
        if last_result is not None:
            state.last_result = last_result
