from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import openpyxl

from .task_models import MailTask, PackageLayout

TASKS_FILENAME = "tasks.xlsx"
PACKAGE_README_FILENAME = "README_操作说明.md"
CONTENT_DIRNAME = "content"
ASSETS_DIRNAME = "assets"
ATTACHMENTS_DIRNAME = "attachments"
DATETIME_FMT = "%Y-%m-%d %H:%M:%S"

TASK_COLUMNS = [
    "任务ID",
    "是否启用",
    "收件人",
    "抄送人",
    "主题",
    "开头/补充内容",
    "Markdown路径",
    "是否有附件",
    "附件路径",
    "是否定时发送",
    "定时发送时间",
    "备注",
]


def default_package_layout(package_dir: Path) -> PackageLayout:
    return PackageLayout(
        package_dir=str(package_dir),
        tasks_file=str(package_dir / TASKS_FILENAME),
        content_dir=str(package_dir / CONTENT_DIRNAME),
        assets_dir=str(package_dir / ASSETS_DIRNAME),
        attachments_dir=str(package_dir / ATTACHMENTS_DIRNAME),
        readme_file=str(package_dir / PACKAGE_README_FILENAME),
    )


def split_emails(value: str) -> list[str]:
    raw = (value or "").replace("；", ";").replace(",", ";")
    return [x.strip() for x in raw.split(";") if x.strip()]


def join_emails(values: list[str]) -> str:
    return "; ".join([x.strip() for x in values if str(x).strip()])


def split_paths(value: str) -> list[str]:
    raw = (value or "").replace("\r\n", "\n").replace("；", ";")
    normalized = raw.replace("\n", ";")
    return [x.strip() for x in normalized.split(";") if x.strip()]


def join_paths(values: list[str]) -> str:
    return "; ".join([x.strip() for x in values if str(x).strip()])


def parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "是", "启用", "有"}


def parse_datetime(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(microsecond=0)
    text = str(value).strip()
    if not text:
        return None
    for fmt in (DATETIME_FMT, "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"无法识别的定时发送时间：{text}")


def datetime_to_excel_text(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.strftime(DATETIME_FMT)


def package_relpath(package_dir: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(package_dir.resolve()))
    except ValueError:
        return str(path.resolve())


def resolve_user_path(package_dir: Path, raw_path: str) -> Path:
    value = str(raw_path or "").strip()
    if not value:
        raise ValueError("路径为空")
    path = Path(value)
    return path.resolve() if path.is_absolute() else (package_dir / path).resolve()


def load_tasks_from_package(package_dir: Path) -> list[MailTask]:
    tasks_path = package_dir / TASKS_FILENAME
    if not tasks_path.is_file():
        raise FileNotFoundError(f"未找到任务表：{tasks_path}")

    workbook = openpyxl.load_workbook(tasks_path, data_only=True, read_only=True)
    try:
        worksheet = workbook.active
        rows = list(worksheet.iter_rows(values_only=True))
    finally:
        workbook.close()

    if not rows:
        return []

    headers = [str(x).strip() if x is not None else "" for x in rows[0]]
    header_map = {name: idx for idx, name in enumerate(headers) if name}

    tasks: list[MailTask] = []
    for row in rows[1:]:
        if not row:
            continue
        if all(v is None or str(v).strip() == "" for v in row):
            continue

        def value_of(column: str) -> object:
            idx = header_map.get(column)
            if idx is None or idx >= len(row):
                return None
            return row[idx]

        attachments = split_paths(str(value_of("附件路径") or ""))
        task = MailTask(
            task_id=str(value_of("任务ID") or uuid.uuid4().hex),
            enabled=parse_bool(value_of("是否启用")) if value_of("是否启用") is not None else True,
            to_recipients=split_emails(str(value_of("收件人") or "")),
            cc_recipients=split_emails(str(value_of("抄送人") or "")),
            subject=str(value_of("主题") or "").strip(),
            intro_text=str(value_of("开头/补充内容") or ""),
            markdown_path=str(value_of("Markdown路径") or "").strip(),
            attachment_paths=attachments,
            schedule_enabled=parse_bool(value_of("是否定时发送")),
            scheduled_at=parse_datetime(value_of("定时发送时间")),
            note=str(value_of("备注") or "").strip(),
        )
        tasks.append(task)

    return tasks


def save_tasks_to_package(package_dir: Path, tasks: list[MailTask]) -> Path:
    package_dir.mkdir(parents=True, exist_ok=True)
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "Tasks"
    worksheet.append(TASK_COLUMNS)

    for task in tasks:
        worksheet.append(
            [
                task.task_id,
                "是" if task.enabled else "否",
                join_emails(task.to_recipients),
                join_emails(task.cc_recipients),
                task.subject,
                task.intro_text,
                task.markdown_path,
                "是" if task.attachment_count() > 0 else "否",
                join_paths(task.attachment_paths),
                "是" if task.schedule_enabled else "否",
                datetime_to_excel_text(task.scheduled_at),
                task.note,
            ]
        )

    tasks_path = package_dir / TASKS_FILENAME
    workbook.save(tasks_path)
    workbook.close()
    return tasks_path


def build_template_tasks() -> list[MailTask]:
    return [
        MailTask(
            task_id=uuid.uuid4().hex,
            enabled=True,
            to_recipients=["someone@zhongtenghr.com"],
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


def clone_task(task: MailTask) -> MailTask:
    data = asdict(task)
    data["task_id"] = uuid.uuid4().hex
    data["status"] = "未校验"
    data["error_message"] = ""
    data["last_previewed_at"] = None
    data["last_send_result"] = ""
    return MailTask(**data)

