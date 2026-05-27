from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dingmail.connection_profile import ConnectionProfile, load_connection_profile, save_connection_profile


class ConnectionProfileTests(unittest.TestCase):
    def test_save_and_load_connection_profile(self) -> None:
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
            if sys.platform == "win32":
                self.assertNotIn("secret-token", raw)

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


if __name__ == "__main__":
    unittest.main()
