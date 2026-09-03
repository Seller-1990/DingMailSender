from __future__ import annotations

import os
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

    def test_detect_home_dir_fresh_frozen_install_uses_exe_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dingmail_home_") as tmp:
            exe_dir = Path(tmp) / "Tools" / "DingMail"
            exe_dir.mkdir(parents=True)

            with mock.patch.object(sys, "executable", str(exe_dir / "DingMailSender.exe")), mock.patch.object(
                sys,
                "frozen",
                True,
                create=True,
            ):
                detected = detect_home_dir()

            self.assertEqual(exe_dir.resolve(), detected)

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

    def test_cleanup_old_runs_removes_only_expired_directories(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dingmail_cleanup_") as tmp:
            runs_root = Path(tmp)
            old_run = runs_root / "20250101_000000_old"
            new_run = runs_root / "20990101_000000_new"
            a_file = runs_root / "loose.txt"
            for path in (old_run, new_run):
                path.mkdir()
                (path / "manifest.csv").write_text("idx\n", encoding="utf-8")
            a_file.write_text("keep", encoding="utf-8")
            two_years_ago = 0
            os.utime(old_run, (two_years_ago, two_years_ago))

            removed = run_store.cleanup_old_runs(runs_root, retention_days=30)

            self.assertEqual(1, removed)
            self.assertFalse(old_run.exists())
            self.assertTrue(new_run.exists())
            self.assertTrue(a_file.exists())

    def test_cleanup_old_runs_is_noop_when_retention_disabled(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dingmail_cleanup_off_") as tmp:
            runs_root = Path(tmp)
            run_dir = runs_root / "20250101_000000_old"
            run_dir.mkdir()
            os.utime(run_dir, (0, 0))

            removed = run_store.cleanup_old_runs(runs_root, retention_days=0)

            self.assertEqual(0, removed)
            self.assertTrue(run_dir.exists())


if __name__ == "__main__":
    unittest.main()
