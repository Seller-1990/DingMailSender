from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dingmail.connection_profile import (
    ConnectionProfile,
    ConnectionProfileLoadError,
    load_connection_profile,
    load_connection_profile_with_metadata,
    migrate_connection_profile_if_needed,
    save_connection_profile,
)


class ConnectionProfileTests(unittest.TestCase):
    def test_save_and_load_connection_profile(self) -> None:
        if sys.platform != "win32":
            self.skipTest("SMTP password persistence requires Windows DPAPI")
        with tempfile.TemporaryDirectory(prefix="dingmail_profile_") as tmp:
            profile_path = Path(tmp) / "conn_profile.json"
            save_connection_profile(
                profile_path,
                from_email="name@example.com",
                smtp_password="secret-token",
            )

            loaded = load_connection_profile(profile_path)
            self.assertEqual(
                ConnectionProfile(from_email="name@example.com", smtp_password="secret-token"),
                loaded,
            )
            raw = profile_path.read_text(encoding="utf-8")
            self.assertIn("smtp_password_protected", raw)
            self.assertNotIn("secret-token", raw)

    def test_save_connection_profile_rejects_non_windows_password_persistence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dingmail_profile_") as tmp, mock.patch.object(sys, "platform", "linux"):
            with self.assertRaises(OSError):
                save_connection_profile(
                    Path(tmp) / "conn_profile.json",
                    from_email="name@example.com",
                    smtp_password="secret-token",
                )

    def test_load_connection_profile_falls_back_to_legacy_password_key(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dingmail_profile_") as tmp:
            legacy_path = Path(tmp) / "legacy.json"
            legacy_path.write_text(
                '{"from_email":"legacy@example.com","password":"legacy-token"}',
                encoding="utf-8",
            )

            loaded = load_connection_profile(legacy_path)
            self.assertEqual("legacy@example.com", loaded.from_email)
            self.assertEqual("legacy-token", loaded.smtp_password)

    def test_load_connection_profile_metadata_marks_legacy_plaintext_source(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dingmail_profile_") as tmp:
            missing = Path(tmp) / "missing.json"
            legacy_path = Path(tmp) / "legacy.json"
            legacy_path.write_text(
                '{"from_email":"legacy@example.com","password":"legacy-token"}',
                encoding="utf-8",
            )

            result = load_connection_profile_with_metadata(missing, legacy_path)

            self.assertEqual("legacy@example.com", result.profile.from_email)
            self.assertEqual("legacy-token", result.profile.smtp_password)
            self.assertEqual(legacy_path.resolve(), result.source_path)
            self.assertTrue(result.is_legacy_source)
            self.assertTrue(result.uses_plaintext_secret)

    def test_load_connection_profile_uses_next_candidate_when_primary_missing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dingmail_profile_") as tmp:
            missing = Path(tmp) / "missing.json"
            fallback = Path(tmp) / "conn_profile.json"
            save_connection_profile(
                fallback,
                from_email="fallback@example.com",
                smtp_password="fallback-token",
            )

            loaded = load_connection_profile(missing, fallback)
            self.assertEqual("fallback@example.com", loaded.from_email)
            self.assertEqual("fallback-token", loaded.smtp_password)

    def test_load_connection_profile_reports_malformed_existing_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dingmail_profile_") as tmp:
            profile_path = Path(tmp) / "conn_profile.json"
            profile_path.write_text("{bad json", encoding="utf-8")

            with self.assertRaises(ConnectionProfileLoadError):
                load_connection_profile(profile_path)

    def test_save_connection_profile_falls_back_to_next_writable_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dingmail_profile_") as tmp:
            primary = Path(tmp) / "primary" / "conn_profile.json"
            fallback = Path(tmp) / "fallback" / "conn_profile.json"

            original_write_text = Path.write_text

            def _fake_write_text(path: Path, *args, **kwargs):
                if path.resolve() == primary.resolve():
                    raise PermissionError("blocked")
                return original_write_text(path, *args, **kwargs)

            with mock.patch.object(Path, "write_text", autospec=True, side_effect=_fake_write_text):
                fallback_path = save_connection_profile(
                    primary,
                    fallback,
                    from_email="fallback@example.com",
                    smtp_password="fallback-token",
                )

            self.assertEqual(fallback.resolve(), fallback_path)
            self.assertTrue(fallback.exists())

    def test_migrate_legacy_plaintext_profile_to_protected_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dingmail_profile_") as tmp:
            root = Path(tmp)
            legacy = root / "legacy" / "conn_profile.json"
            target = root / "new" / "conn_profile.json"
            legacy.parent.mkdir(parents=True)
            legacy.write_text(
                '{"from_email":"legacy@example.com","smtp_password":"legacy-token"}',
                encoding="utf-8",
            )

            result = load_connection_profile_with_metadata(target, legacy)
            migrated = migrate_connection_profile_if_needed(result, target)
            reloaded = load_connection_profile_with_metadata(target, legacy)

            self.assertEqual(target.resolve(), migrated)
            self.assertTrue(target.exists())
            self.assertFalse(legacy.exists(), "迁移成功后旧明文配置文件应被删除")
            self.assertEqual(ConnectionProfile("legacy@example.com", "legacy-token"), reloaded.profile)
            self.assertFalse(reloaded.is_legacy_source)
            self.assertFalse(reloaded.uses_plaintext_secret)


if __name__ == "__main__":
    unittest.main()
