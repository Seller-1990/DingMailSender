"""页面视图：任务、队列、历史、设置。"""

from .history_page import HistoryPage
from .queue_page import QueuePage
from .settings_page import SettingsPage
from .tasks_page import TasksPage

__all__ = ["HistoryPage", "QueuePage", "SettingsPage", "TasksPage"]
