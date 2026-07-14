"""主窗口任务能力的兼容聚合层。"""

from .main_packages import MainPackageMixin
from .main_task_commands import MainTaskCommandMixin
from .main_task_table import MainTaskTableMixin


class MainTaskMixin(MainPackageMixin, MainTaskCommandMixin, MainTaskTableMixin):
    pass


__all__ = ["MainTaskMixin"]
