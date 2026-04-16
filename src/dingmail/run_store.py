from __future__ import annotations

import csv
import datetime as dt
import shutil
from dataclasses import dataclass
from pathlib import Path

from .paths import ensure_layout, runs_dir


def _now_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in name)


@dataclass(frozen=True)
class RunPaths:
    run_dir: Path
    previews_dir: Path
    eml_dir: Path
    logs_dir: Path
    manifest_csv: Path


def create_run_paths(*, home_dir: Path | None, campaign_dir: Path) -> RunPaths:
    home = ensure_layout(home_dir)
    campaign_name = _safe_name(campaign_dir.name)
    run_dir = runs_dir(home) / f"{_now_stamp()}_{campaign_name}"
    previews_dir = run_dir / "previews"
    eml_dir = run_dir / "eml"
    logs_dir = run_dir / "logs"
    previews_dir.mkdir(parents=True, exist_ok=False)
    eml_dir.mkdir(parents=True, exist_ok=False)
    logs_dir.mkdir(parents=True, exist_ok=False)

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


def append_manifest_row(
    manifest_csv: Path,
    *,
    idx: int,
    to_email: str,
    subject: str,
    status: str,
    message_id: str | None,
    error: str | None,
) -> None:
    with manifest_csv.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([idx, to_email, subject, status, message_id or "", error or ""])


def snapshot_file(src: Path, dst_dir: Path, dst_name: str) -> None:
    if not src.is_file():
        return
    dst = dst_dir / dst_name
    shutil.copy2(src, dst)
