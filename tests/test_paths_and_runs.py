from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dingmail.paths import connection_profile_path, detect_home_dir, program_dir, user_config_dir
from dingmail.run_store import create_run_paths
import dingmail.run_store as run_store


class PathsAndRunsTests(unittest.TestCase):
    def test_create_run_paths_avoids_same_second_collisions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dingmail_runs_") as tmp:
            home = Path(tmp)
            (home / "packages").mkdir()
            (home / "runs").mkdir()
            (home / "campaigns").mkdir()
            package_dir = home / "packages" / "demo"
            package_dir.mkdir()

            with mock.patch.object(run_store, "_now_stamp", return_value="20260527_120000"):
                first = create_run_paths(home_dir=home, campaign_dir=package_dir)
                second = create_run_paths(home_dir=home, campaign_dir=package_dir)

            self.assertNotEqual(first.run_dir, second.run_dir)
            self.assertTrue(first.run_dir.exists())
            self.assertTrue(second.run_dir.exists())

    def test_create_run_paths_truncates_long_package_names(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dingmail_runs_") as tmp:
            home = Path(tmp)
            (home / "packages").mkdir()
            package_dir = home / "packages" / ("很长的任务包名称" * 20)
            package_dir.mkdir()

            run_paths = create_run_paths(home_dir=home, campaign_dir=package_dir)

            self.assertLessEqual(len(run_paths.run_dir.name), len("20260527_120000_") + 66)
            self.assertTrue(run_paths.run_dir.exists())

    def test_detect_home_dir_prefers_project_root_for_frozen_release(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dingmail_home_") as tmp:
            root = Path(tmp) / "workspace"
            release = root / "release"
            release.mkdir(parents=True)
            (root / "packages").mkdir()

            with mock.patch.object(sys, "executable", str(release / "app.exe")), mock.patch.object(
                sys,
                "frozen",
                True,
                create=True,
            ):
                detected = detect_home_dir()

            self.assertEqual(root.resolve(), detected)

    def test_connection_profile_path_points_to_user_config_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dingmail_config_") as tmp:
            local_app_data = Path(tmp) / "LocalAppData"

            with mock.patch.dict("os.environ", {"LOCALAPPDATA": str(local_app_data)}):
                self.assertEqual((local_app_data / "DingMailSender").resolve(), user_config_dir())
                self.assertEqual((local_app_data / "DingMailSender" / "conn_profile.json").resolve(), connection_profile_path())

    def test_program_dir_still_points_to_frozen_exe_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dingmail_program_") as tmp:
            exe_dir = Path(tmp) / "release"
            exe_dir.mkdir(parents=True)

            with mock.patch.object(sys, "executable", str(exe_dir / "DingMailSender.exe")), mock.patch.object(
                sys,
                "frozen",
                True,
                create=True,
            ):
                self.assertEqual(exe_dir.resolve(), program_dir())


if __name__ == "__main__":
    unittest.main()
