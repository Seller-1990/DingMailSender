from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class MailTask:
    task_id: str
    enabled: bool = True
    to_recipients: list[str] = field(default_factory=list)
    cc_recipients: list[str] = field(default_factory=list)
    subject: str = ""
    intro_text: str = ""
    markdown_path: str = ""
    attachment_paths: list[str] = field(default_factory=list)
    schedule_enabled: bool = False
    scheduled_at: datetime | None = None
    note: str = ""

    def attachment_count(self) -> int:
        return len([x for x in self.attachment_paths if str(x).strip()])


@dataclass(frozen=True)
class PackageLayout:
    package_dir: str
    tasks_file: str
    content_dir: str
    assets_dir: str
    attachments_dir: str
    readme_file: str
