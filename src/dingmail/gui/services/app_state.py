"""应用级设置：state.json 的读写与取值夹紧。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ...constants import DEFAULT_RATE_LIMIT_SECONDS

MAX_RATE_LIMIT_SECONDS = 600.0
MAX_RETENTION_DAYS = 3650


@dataclass
class AppSettings:
    last_package_dir: str = ""
    send_rate_limit_seconds: float = DEFAULT_RATE_LIMIT_SECONDS
    runs_retention_days: int = 0
    splitter_sizes: list[int] = field(default_factory=list)
    nav_page: str = "tasks"

    def clamp(self) -> None:
        self.send_rate_limit_seconds = min(max(float(self.send_rate_limit_seconds), 0.0), MAX_RATE_LIMIT_SECONDS)
        self.runs_retention_days = min(max(int(self.runs_retention_days), 0), MAX_RETENTION_DAYS)
        if len(self.splitter_sizes) != 2:
            self.splitter_sizes = []
        else:
            try:
                self.splitter_sizes = [max(int(v), 0) for v in self.splitter_sizes]
            except (TypeError, ValueError):
                self.splitter_sizes = []
        if self.nav_page not in {"tasks", "queue", "history", "settings"}:
            self.nav_page = "tasks"


def load_app_state(path: Path) -> AppSettings:
    settings = AppSettings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return settings
    if not isinstance(raw, dict):
        return settings
    try:
        settings.send_rate_limit_seconds = float(
            raw.get("send_rate_limit_seconds", settings.send_rate_limit_seconds)
        )
    except (TypeError, ValueError):
        pass
    try:
        settings.runs_retention_days = int(raw.get("runs_retention_days", settings.runs_retention_days))
    except (TypeError, ValueError):
        pass
    raw_sizes = raw.get("splitter_sizes")
    if isinstance(raw_sizes, list):
        settings.splitter_sizes = list(raw_sizes)
    settings.last_package_dir = str(raw.get("last_package_dir") or "")
    settings.nav_page = str(raw.get("nav_page") or "tasks")
    settings.clamp()
    return settings


def save_app_state(path: Path, settings: AppSettings) -> None:
    settings.clamp()
    payload = {
        "last_package_dir": settings.last_package_dir,
        "send_rate_limit_seconds": settings.send_rate_limit_seconds,
        "runs_retention_days": settings.runs_retention_days,
        "splitter_sizes": settings.splitter_sizes,
        "nav_page": settings.nav_page,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
