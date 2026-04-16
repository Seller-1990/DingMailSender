from __future__ import annotations

import os
import sys
from pathlib import Path


def detect_home_dir() -> Path:
    env_home = os.getenv("DINGMAIL_HOME")
    if env_home:
        return Path(env_home).expanduser().resolve()

    if getattr(sys, "frozen", False):
        start_dir = Path(sys.executable).resolve().parent
    else:
        start_dir = Path(__file__).resolve().parent

    # Prefer the nearest parent that already has the expected layout.
    for candidate in [start_dir] + list(start_dir.parents)[:6]:
        if (candidate / "campaigns").is_dir() and (candidate / "runs").is_dir():
            return candidate

    # Fallback: when running from source, try to locate project root (.../src/dingmail/*).
    if not getattr(sys, "frozen", False):
        return start_dir.parents[1]

    return start_dir


def campaigns_dir(home_dir: Path | None = None) -> Path:
    home = home_dir or detect_home_dir()
    return home / "campaigns"


def packages_dir(home_dir: Path | None = None) -> Path:
    home = home_dir or detect_home_dir()
    return home / "packages"


def runs_dir(home_dir: Path | None = None) -> Path:
    home = home_dir or detect_home_dir()
    return home / "runs"


def ensure_layout(home_dir: Path | None = None) -> Path:
    home = home_dir or detect_home_dir()
    (home / "campaigns").mkdir(parents=True, exist_ok=True)
    (home / "packages").mkdir(parents=True, exist_ok=True)
    (home / "runs").mkdir(parents=True, exist_ok=True)
    return home
