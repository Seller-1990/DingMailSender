from __future__ import annotations

import uuid
from pathlib import Path

from .task_models import MailTask
from .task_package import CONTENT_DIRNAME, default_package_layout, save_tasks_to_package


def build_template_tasks() -> list[MailTask]:
    return [
        MailTask(
            task_id=uuid.uuid4().hex,
            enabled=True,
            to_recipients=["someone@example.com"],
            cc_recipients=[],
            subject="【示例】请查收本月通知",
            intro_text="**总：晚上好**\n\n这里是自定义开头示例。",
            markdown_path=f"{CONTENT_DIRNAME}/示例正文.md",
            attachment_paths=[],
            schedule_enabled=False,
            scheduled_at=None,
            note="示例任务，可直接修改",
        )
    ]


def build_package_readme_text() -> str:
    return """# 任务包操作说明

## 目录说明

- `tasks.xlsx`：一行一封邮件任务
- `content/`：Markdown 正文文件
- `assets/`：正文图片素材
- `attachments/`：附件文件

## 推荐填写方式

- `收件人` / `抄送人`：多个邮箱用分号分隔
- `任务ID`：程序会自动生成；如果缺失或重复，重新加载或保存时会自动修复
- `Markdown路径`：优先填写相对任务包目录的路径，例如 `content/示例正文.md`
- `附件路径`：多个附件路径用分号分隔，例如 `attachments/a.pdf; attachments/b.pdf`
- `开头/补充内容`：支持换行，会拼接到 Markdown 正文前面
- `定时发送时间`：格式建议为 `2026-03-18 20:30:00`

## 正文图片

- 正文图片请在 Markdown 中按相对路径引用
- 程序发送时会自动转为 CID 内联图片
"""


def create_template_package(package_dir: Path) -> Path:
    layout = default_package_layout(package_dir)
    package_dir.mkdir(parents=True, exist_ok=True)
    Path(layout.content_dir).mkdir(parents=True, exist_ok=True)
    Path(layout.assets_dir).mkdir(parents=True, exist_ok=True)
    Path(layout.attachments_dir).mkdir(parents=True, exist_ok=True)

    readme_path = Path(layout.readme_file)
    if not readme_path.exists():
        readme_path.write_text(build_package_readme_text(), encoding="utf-8")

    sample_md = Path(layout.content_dir) / "示例正文.md"
    if not sample_md.exists():
        sample_md.write_text(
            "# 示例正文\n\n这是示例 Markdown 正文。\n\n- 支持标题\n- 支持列表\n- 支持表格\n",
            encoding="utf-8",
        )

    save_tasks_to_package(package_dir, build_template_tasks())
    return package_dir
