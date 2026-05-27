from __future__ import annotations

import os
import sys
from pathlib import Path


def program_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def connection_profile_path() -> Path:
    return program_dir() / "conn_profile.json"


def _looks_like_home_dir(candidate: Path) -> bool:
    has_packages = (candidate / "packages").is_dir()
    has_campaigns = (candidate / "campaigns").is_dir()
    has_runs = (candidate / "runs").is_dir()
    has_src = (candidate / "src").is_dir()
    return (has_packages or has_campaigns) and (has_runs or has_src)


def detect_home_dir() -> Path:
    env_home = os.getenv("DINGMAIL_HOME")
    if env_home:
        return Path(env_home).expanduser().resolve()

    if getattr(sys, "frozen", False):
        start_dir = Path(sys.executable).resolve().parent
    else:
        start_dir = Path(__file__).resolve().parent

    # Prefer the nearest parent that already resembles the project home.
    for candidate in [start_dir] + list(start_dir.parents)[:6]:
        if _looks_like_home_dir(candidate):
            return candidate

    if getattr(sys, "frozen", False) and ((start_dir / "packages").is_dir() or (start_dir / "campaigns").is_dir()):
        return start_dir

    # Fallback: when running from source, try to locate project root (.../src/dingmail/*).
    if not getattr(sys, "frozen", False):
        return start_dir.parents[1]

    return start_dir.parent if start_dir.parent != start_dir else start_dir

def packages_dir(home_dir: Path | None = None) -> Path:
    home = home_dir or detect_home_dir()
    return home / "packages"


def runs_dir(home_dir: Path | None = None) -> Path:
    home = home_dir or detect_home_dir()
    return home / "runs"


def ensure_layout(home_dir: Path | None = None) -> Path:
    home = home_dir or detect_home_dir()
    (home / "packages").mkdir(parents=True, exist_ok=True)
    (home / "runs").mkdir(parents=True, exist_ok=True)
    return home
