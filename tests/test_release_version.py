from __future__ import annotations

import re
import sys
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dingmail import __version__


class ReleaseVersionTests(unittest.TestCase):
    def test_runtime_version_is_semantic_version(self) -> None:
        self.assertRegex(__version__, re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$"))

    def test_pyproject_reads_version_from_runtime_package(self) -> None:
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertNotIn("version", data["project"])
        self.assertIn("version", data["project"]["dynamic"])
        self.assertEqual("dingmail.__version__", data["tool"]["setuptools"]["dynamic"]["version"]["attr"])


if __name__ == "__main__":
    unittest.main()
