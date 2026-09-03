from __future__ import annotations

import sys
from pathlib import Path


def _ensure_src_on_path() -> None:
    root_dir = Path(__file__).resolve().parent
    src_dir = root_dir / "src"
    if src_dir.is_dir() and str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS"))


def main() -> int:
    try:
        from dingmail.gui.app import run
    except ModuleNotFoundError:
        if _is_frozen():
            raise
        _ensure_src_on_path()
        from dingmail.gui.app import run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())

