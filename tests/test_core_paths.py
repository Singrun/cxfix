import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cxfix.core.codex_home import CodexHome, configured_sqlite_home, default_codex_home
from cxfix.core.config import (
    backup_config,
    configured_model_provider,
    configured_top_level_string,
    load_toml_config,
    provider_names,
    redact_config,
    replace_top_level_string,
)


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

    def test_load_toml_and_provider_names(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "config.toml"
            config.write_text(
                """
[model_providers.alpha]
name = "Alpha"

[model_providers.beta]
name = "Beta"
""".lstrip(),
                encoding="utf-8",
            )

            loaded = load_toml_config(config)

        self.assertEqual(provider_names(loaded), ["alpha", "beta"])

    def test_redact_config_hides_secret_keys(self):
        redacted = redact_config(
            {
                "model_providers": {
                    "alpha": {
                        "api_key": "secret",
                        "base_url": "https://example.test",
                    }
                }
            }
        )

        self.assertEqual(redacted["model_providers"]["alpha"]["api_key"], "<redacted>")
        self.assertEqual(
            redacted["model_providers"]["alpha"]["base_url"],
            "https://example.test",
        )

    def test_replace_top_level_string_updates_before_tables(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "config.toml"
            config.write_text(
                """
model_provider = "old"

[profiles.old]
model_provider = "profile-old"
""".lstrip(),
                encoding="utf-8",
            )

            replace_top_level_string(config, "model_provider", "new")
            text = config.read_text(encoding="utf-8")

        self.assertIn('model_provider = "new"', text.splitlines()[0])
        self.assertIn('model_provider = "profile-old"', text)

    def test_backup_config_copies_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "config.toml"
            config.write_text('model_provider = "old"\n', encoding="utf-8")

            backup = backup_config(config, root / "backups")
            backup_exists = backup.is_file()
            backup_text = backup.read_text(encoding="utf-8")

        self.assertTrue(backup_exists)
        self.assertEqual(backup_text, 'model_provider = "old"\n')


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
