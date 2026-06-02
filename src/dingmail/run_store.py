from __future__ import annotations

import csv
import datetime as dt
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from .paths import ensure_layout, runs_dir


def _now_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def debug_artifacts_enabled() -> bool:
    return os.getenv("DINGMAIL_SAVE_DEBUG_ARTIFACTS", "").strip().lower() in {"1", "true", "yes", "on"}


def _safe_name(name: str, limit: int = 64) -> str:
    safe = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in name).strip("_")
    if len(safe) > limit:
        safe = safe[:limit].rstrip("_")
    return safe or "item"


def redact_email(value: str) -> str:
    items = []
    for raw in str(value or "").replace(",", ";").split(";"):
        email = raw.strip()
        if not email:
            continue
        if "@" not in email:
            items.append("***")
            continue
        name, domain = email.split("@", 1)
        visible = name[:2] if len(name) > 2 else name[:1]
        items.append(f"{visible}***@{domain}")
    return "; ".join(items)


def redact_text(value: str | None, limit: int = 80) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def _create_unique_run_dir(base_dir: Path, run_name: str) -> Path:
    suffix = 0
    subdirs = ("previews", "eml", "logs")

    while True:
        candidate_name = run_name if suffix == 0 else f"{run_name}_{suffix}"
        run_dir = base_dir / candidate_name
        try:
            run_dir.mkdir(parents=True, exist_ok=False)
            for subdir in subdirs:
                (run_dir / subdir).mkdir(exist_ok=False)
            return run_dir
        except FileExistsError:
            suffix += 1


@dataclass(frozen=True)
class RunPaths:
    run_dir: Path
    previews_dir: Path
    eml_dir: Path
    logs_dir: Path
    manifest_csv: Path


@dataclass(frozen=True)
class ManifestRow:
    idx: int
    to_email: str
    subject: str
    status: str
    message_id: str | None
    error: str | None


def create_run_paths(*, home_dir: Path | None, campaign_dir: Path) -> RunPaths:
    home = ensure_layout(home_dir)
    campaign_name = _safe_name(campaign_dir.name)
    run_dir = _create_unique_run_dir(runs_dir(home), f"{_now_stamp()}_{campaign_name}")
    previews_dir = run_dir / "previews"
    eml_dir = run_dir / "eml"
    logs_dir = run_dir / "logs"

    manifest_csv = run_dir / "manifest.csv"
    with manifest_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["idx", "to_email", "subject", "status", "message_id", "error"])

    return RunPaths(
        run_dir=run_dir,
        previews_dir=previews_dir,
        eml_dir=eml_dir,
        logs_dir=logs_dir,
        manifest_csv=manifest_csv,
    )


def append_manifest_row(manifest_csv: Path, row: ManifestRow) -> None:
    with manifest_csv.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                row.idx,
                redact_email(row.to_email),
                redact_text(row.subject),
                row.status,
                row.message_id or "",
                redact_text(row.error),
            ]
        )


def snapshot_file(src: Path, dst_dir: Path, dst_name: str) -> None:
    if not src.is_file():
        return
    dst = dst_dir / dst_name
    shutil.copy2(src, dst)
