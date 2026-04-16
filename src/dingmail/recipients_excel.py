from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import openpyxl

from .model import RecipientsConfig

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class Recipient:
    email: str
    variables: dict[str, str]
    row_number: int


def load_recipients(campaign_dir: Path, cfg: RecipientsConfig) -> list[Recipient]:
    xlsx_path = (campaign_dir / cfg.file).resolve()
    if not xlsx_path.is_file():
        raise FileNotFoundError(f"未找到收件人 Excel：{xlsx_path}")

    wb = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
    ws = wb[cfg.sheet] if cfg.sheet else wb.active

    header_row = cfg.header_row
    headers = []
    for cell in ws[header_row]:
        headers.append("" if cell.value is None else str(cell.value).strip())

    header_to_index: dict[str, int] = {}
    for idx, h in enumerate(headers):
        if h and h not in header_to_index:
            header_to_index[h] = idx

    key_to_index: dict[str, int] = {}
    for key, header_name in cfg.columns.items():
        header_name = str(header_name).strip()
        if not header_name:
            continue
        if header_name not in header_to_index:
            raise ValueError(f"Excel 表头缺少列：{header_name!r}（用于字段 {key!r}）")
        key_to_index[key] = header_to_index[header_name]

    if "email" not in key_to_index:
        raise ValueError("recipients.columns 必须包含 email 映射")

    recipients: list[Recipient] = []
    for row_idx, row in enumerate(
        ws.iter_rows(min_row=header_row + 1, values_only=True),
        start=header_row + 1,
    ):
        if not row:
            continue
        if all(v is None or str(v).strip() == "" for v in row):
            continue

        variables: dict[str, str] = {}
        for key, col_idx in key_to_index.items():
            value = row[col_idx] if col_idx < len(row) else None
            variables[key] = "" if value is None else str(value).strip()

        email = variables.get("email", "").strip()
        if not email:
            raise ValueError(f"第 {row_idx} 行 email 为空")
        if not _EMAIL_RE.match(email):
            raise ValueError(f"第 {row_idx} 行 email 非法：{email!r}")

        recipients.append(Recipient(email=email, variables=variables, row_number=row_idx))

    if not recipients:
        raise ValueError("收件人清单为空")

    return recipients

