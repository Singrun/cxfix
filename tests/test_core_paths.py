import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cxfix.core.codex_home import CodexHome, configured_sqlite_home, default_codex_home
from cxfix.core.config import configured_model_provider, configured_top_level_string


class CoreConfigTests(unittest.TestCase):
    def test_reads_top_level_string_before_first_table(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "config.toml"
            config.write_text(
                """
model_provider = "aimai1"

[profiles.other]
model_provider = "ignored"
""".lstrip(),
                encoding="utf-8",
            )

            self.assertEqual(configured_model_provider(config), "aimai1")
            self.assertEqual(configured_top_level_string("model_provider", config), "aimai1")

    def test_ignores_missing_config(self):
        self.assertIsNone(configured_model_provider(Path("/tmp/missing-cxfix-config.toml")))


class CodexHomeTests(unittest.TestCase):
    def test_default_codex_home_reads_env(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            expected = Path(temp_dir) / "custom-codex"
            with mock.patch.dict("os.environ", {"CODEX_HOME": str(expected)}, clear=True):
                self.assertEqual(default_codex_home(), expected)

    def test_configured_sqlite_home_precedence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            codex_home = Path(temp_dir) / ".codex"
            configured = Path(temp_dir) / "configured"
            env_home = Path(temp_dir) / "env"
            codex_home.mkdir()
            (codex_home / "config.toml").write_text(
                f'sqlite_home = "{configured}"\n',
                encoding="utf-8",
            )

            with mock.patch.dict("os.environ", {"CODEX_SQLITE_HOME": str(env_home)}, clear=True):
                self.assertEqual(configured_sqlite_home(codex_home), configured)

    def test_codex_home_exposes_standard_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / ".codex"
            root.mkdir()
            home = CodexHome.discover(root)

        self.assertEqual(home.config, root / "config.toml")
        self.assertEqual(home.state_db, root / "state_5.sqlite")
        self.assertEqual(home.sessions, root / "sessions")
        self.assertEqual(home.backup_root, root / "backups" / "session-history-repair")


if __name__ == "__main__":
    unittest.main()
