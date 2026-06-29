import importlib.util
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).parents[1] / "codex_history_repair.py"
SPEC = importlib.util.spec_from_file_location("codex_history_repair", MODULE_PATH)
repair = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = repair
SPEC.loader.exec_module(repair)


class ParseArgsTests(unittest.TestCase):
    def test_question_mark_help_lists_commands(self):
        output = io.StringIO()
        with mock.patch("sys.argv", ["cxfix", "-?"]):
            with redirect_stdout(output):
                with self.assertRaises(SystemExit) as raised:
                    repair.parse_args()

        self.assertEqual(raised.exception.code, 0)
        text = output.getvalue()
        self.assertIn("Recommended commands:", text)
        self.assertIn("cxfix config show", text)
        self.assertIn("cxfix provider switch PROVIDER", text)
        self.assertIn("cxfix fix-all -y", text)
        self.assertIn("cxfix path list", text)
        self.assertIn("cxfix plugins cache -a", text)

    def test_config_show_normalizes_to_display_config(self):
        args = repair.parse_args(["config", "show", "-j"])

        self.assertTrue(args.display_config)
        self.assertTrue(args.json)

    def test_provider_switch_normalizes_to_provider_option(self):
        args = repair.parse_args(["provider", "switch", "aimai1"])

        self.assertEqual(args.provider, "aimai1")

    def test_repair_all_normalizes_to_all_scope(self):
        args = repair.parse_args(["fix-all", "-y"])

        self.assertEqual(args.command, repair.SCOPE_ALL)
        self.assertTrue(args.yes)

    def test_fix_normalizes_to_current_scope(self):
        args = repair.parse_args(["fix", "-y"])

        self.assertEqual(args.command, repair.SCOPE_CURRENT)
        self.assertTrue(args.yes)

    def test_clean_normalizes_to_encrypted_scope(self):
        args = repair.parse_args(["clean", "-y"])

        self.assertEqual(args.command, repair.SCOPE_ENCRYPTED)
        self.assertTrue(args.yes)

    def test_path_list_normalizes_to_list_cwd(self):
        args = repair.parse_args(["path", "list", "-c", "know"])

        self.assertEqual(args.command, repair.SCOPE_PATH)
        self.assertTrue(args.list_cwd)
        self.assertEqual(args.contains_cwd, "know")

    def test_path_migrate_normalizes_from_and_to_options(self):
        args = repair.parse_args(["path", "migrate", "-f", "old ", "-o", "new"])

        self.assertEqual(args.command, repair.SCOPE_PATH)
        self.assertEqual(args.from_cwd, "old ")
        self.assertEqual(args.to_cwd, "new")

    def test_plugins_cache_normalizes_to_plugin_cache_scope(self):
        args = repair.parse_args(["plugins", "cache", "-a"])

        self.assertEqual(args.command, repair.SCOPE_PLUGIN_CACHE)
        self.assertTrue(args.apply)

    def test_plugins_mount_normalizes_to_visible_mounts(self):
        args = repair.parse_args(["plugins", "mount", "-n"])

        self.assertEqual(args.command, repair.SCOPE_PLUGINS)
        self.assertTrue(args.dry_run)

    def test_short_plugin_cache_options_are_accepted(self):
        args = repair.parse_args(
            ["plugins", "cache", "-s", "openai-primary-runtime", "-a", "-m", "-x"]
        )

        self.assertEqual(args.source, ["openai-primary-runtime"])
        self.assertTrue(args.apply)
        self.assertTrue(args.visible_mounts)
        self.assertTrue(args.skip_symlinks)

    def test_target_provider_option_is_accepted(self):
        args = repair.parse_args(["fix-all", "-g", "aimai1"])

        self.assertEqual(args.target_provider, "aimai1")

    def test_clean_encrypted_option_is_accepted(self):
        args = repair.parse_args(["fix-all", "-e"])

        self.assertTrue(args.clean_encrypted)

    def test_display_config_option_is_accepted(self):
        with mock.patch("sys.argv", ["cxfix", "-d", "-j"]):
            args = repair.parse_args()

        self.assertTrue(args.display_config)
        self.assertTrue(args.json)

    def test_provider_switch_option_is_accepted(self):
        with mock.patch("sys.argv", ["cxfix", "-p", "aimai1"]):
            args = repair.parse_args()

        self.assertEqual(args.provider, "aimai1")

    def test_path_scope_and_cwd_options_are_accepted(self):
        with mock.patch(
            "sys.argv",
            ["cxfix", "path", "--from-cwd", "～/dev/know ", "--to-cwd", "~/dev/know"],
        ):
            with redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    repair.parse_args()

    def test_path_migrate_and_cwd_options_are_accepted(self):
        args = repair.parse_args(
            ["path", "migrate", "--from-cwd", "～/dev/know ", "--to-cwd", "~/dev/know"]
        )

        self.assertEqual(args.command, repair.SCOPE_PATH)
        self.assertEqual(args.from_cwd, "～/dev/know ")
        self.assertEqual(args.to_cwd, "~/dev/know")

    def test_path_list_cwd_option_is_accepted(self):
        args = repair.parse_args(["path", "list", "-c", "know"])

        self.assertTrue(args.list_cwd)
        self.assertEqual(args.contains_cwd, "know")

    def test_long_options_are_still_accepted(self):
        args = repair.parse_args(
            [
                "path",
                "list",
                "--list-cwd",
                "--contains-cwd",
                "know",
                "--preserve-providers",
            ]
        )

        self.assertTrue(args.list_cwd)
        self.assertEqual(args.contains_cwd, "know")
        self.assertFalse(args.official_only)

    def test_legacy_commands_are_rejected(self):
        for argv in (["all", "-y"], ["e"], ["p", "-n"], ["plugin-cache", "-a"]):
            with self.subTest(argv=argv):
                with redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        repair.parse_args(argv)


class ProviderConfigurationTests(unittest.TestCase):
    def test_reads_top_level_model_provider(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "config.toml"
            config.write_text(
                """
# Managed header
model_provider = "aimai1"

[profiles.legacy]
model_provider = "ignored"
""".lstrip(),
                encoding="utf-8",
            )

            actual = repair.configured_model_provider(config)

        self.assertEqual(actual, "aimai1")

    def test_ignores_profile_only_model_provider(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "config.toml"
            config.write_text(
                """
[profiles.legacy]
model_provider = "ignored"
""".lstrip(),
                encoding="utf-8",
            )

            actual = repair.configured_model_provider(config)

        self.assertIsNone(actual)

    def test_explicit_target_provider_wins(self):
        args = mock.Mock(target_provider="custom")

        self.assertEqual(repair.target_provider(args), "custom")

    def test_configured_sqlite_home_defaults_to_codex_home(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            codex_home = Path(temp_dir) / ".codex"
            codex_home.mkdir()

            with mock.patch.dict("os.environ", {}, clear=True):
                actual = repair.configured_sqlite_home(codex_home=codex_home)

        self.assertEqual(actual, codex_home)

    def test_configured_sqlite_home_reads_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            codex_home = Path(temp_dir) / ".codex"
            configured = Path(temp_dir) / "state"
            codex_home.mkdir()
            (codex_home / "config.toml").write_text(
                f'sqlite_home = "{configured}"\n',
                encoding="utf-8",
            )

            with mock.patch.dict("os.environ", {}, clear=True):
                actual = repair.configured_sqlite_home(codex_home=codex_home)

        self.assertEqual(actual, configured)

    def test_configured_sqlite_home_prefers_config_over_env(self):
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
                actual = repair.configured_sqlite_home(codex_home=codex_home)

        self.assertEqual(actual, configured)

    def test_configured_sqlite_home_uses_env_without_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            codex_home = Path(temp_dir) / ".codex"
            env_home = Path(temp_dir) / "env"
            codex_home.mkdir()

            with mock.patch.dict("os.environ", {"CODEX_SQLITE_HOME": str(env_home)}, clear=True):
                actual = repair.configured_sqlite_home(codex_home=codex_home)

        self.assertEqual(actual, env_home)

    def test_switch_provider_updates_top_level_and_backs_up(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "config.toml"
            backup_root = root / "backups"
            config.write_text(
                """
model_provider = "old"

[model_providers.old]
name = "Old"

[model_providers.new]
name = "New"

[profiles.keep]
model_provider = "old"
""".lstrip(),
                encoding="utf-8",
            )

            with mock.patch.object(repair, "CODEX_CONFIG", config), mock.patch.object(
                repair, "BACKUP_ROOT", backup_root
            ):
                result = repair.switch_provider("new")
            text = config.read_text(encoding="utf-8")
            backup_exists = Path(result["backup"]).is_file()

        self.assertEqual(result["previous_provider"], "old")
        self.assertEqual(result["new_provider"], "new")
        self.assertTrue(backup_exists)
        self.assertIn('model_provider = "new"', text.splitlines()[0])
        self.assertIn('model_provider = "old"', text)

    def test_switch_provider_rejects_unknown_provider(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "config.toml"
            config.write_text(
                """
model_provider = "old"

[model_providers.old]
name = "Old"
""".lstrip(),
                encoding="utf-8",
            )

            with mock.patch.object(repair, "CODEX_CONFIG", config):
                with self.assertRaises(ValueError):
                    repair.switch_provider("missing")


class DiscoverStateDatabasesTests(unittest.TestCase):
    def test_finds_real_codex_databases_and_excludes_backups(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            codex_home = home / ".codex"
            managed_root = (
                home
                / "Library"
                / "Application Support"
                / "CodexBar"
                / "managed-codex-homes"
            )
            expected = [
                codex_home / "state_5.sqlite",
                codex_home / "sqlite" / "state_5.sqlite",
                managed_root / "profile-a" / "state_5.sqlite",
            ]
            ignored = codex_home / "backups" / "old" / "state_5.sqlite"
            for path in [*expected, ignored]:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()

            with mock.patch.dict("os.environ", {}, clear=True):
                actual = repair.discover_state_databases(
                    codex_home=codex_home,
                    user_home=home,
                )

        self.assertEqual(actual, expected)


class DiscoverCachedPluginSkillsTests(unittest.TestCase):
    def test_discovers_skill_under_plugin_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = Path(temp_dir) / "plugins" / "cache"
            skill_dir = (
                cache
                / "openai-primary-runtime"
                / "presentations"
                / "1.0.0"
                / "skills"
                / "presentations"
            )
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: Presentations\n---\n# Presentations\n",
                encoding="utf-8",
            )

            actual = repair.discover_cached_plugin_skills(cache)

        self.assertEqual(len(actual), 1)
        self.assertEqual(actual[0].link_name, "presentations")
        self.assertEqual(actual[0].source, "openai-primary-runtime")

    def test_visible_mount_uses_namespaced_skill_name(self):
        candidate = repair.PluginSkillCandidate(
            link_name="presentations",
            skill_dir=Path("/tmp/cache/openai-primary-runtime/presentations/1/skills/presentations"),
            skill_file=Path("/tmp/cache/openai-primary-runtime/presentations/1/skills/presentations/SKILL.md"),
            source="openai-primary-runtime",
            plugin="presentations",
            version="1",
            display_name="Presentations",
        )

        content = repair.visible_mount_content(candidate)
        name = repair.visible_mount_name(candidate)

        self.assertLessEqual(len(name), 64)
        self.assertTrue(name.startswith("cache:presentations:"))
        self.assertIn(f'name: "{name}"', content)
        self.assertIn("Original skill file:", content)


class CleanEncryptedContentTests(unittest.TestCase):
    def test_remove_encrypted_content_recurses_without_touching_text(self):
        payload = {
            "type": "response_item",
            "payload": {
                "type": "reasoning",
                "summary": [{"text": "keep me"}],
                "encrypted_content": "secret",
                "nested": [{"encryptedContent": "secret2", "text": "visible"}],
            },
        }

        removed = repair.remove_encrypted_content(payload)

        self.assertEqual(removed, 2)
        self.assertNotIn("encrypted_content", payload["payload"])
        self.assertNotIn("encryptedContent", payload["payload"]["nested"][0])
        self.assertEqual(payload["payload"]["summary"][0]["text"], "keep me")
        self.assertEqual(payload["payload"]["nested"][0]["text"], "visible")

    def test_clean_encrypted_rollout_file_backs_up_and_rewrites(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rollout = root / "rollout.jsonl"
            backup = root / "backup" / "rollout.jsonl"
            rollout.write_text(
                (
                    '{"type":"response_item","payload":{"type":"reasoning",'
                    '"summary":[],"encrypted_content":"secret"}}\n'
                    '{"type":"event_msg","payload":{"message":"visible"}}\n'
                ),
                encoding="utf-8",
            )

            removed = repair.clean_encrypted_rollout_file(rollout, backup)
            rewritten = rollout.read_text(encoding="utf-8")
            backed_up = backup.is_file()

        self.assertEqual(removed, 1)
        self.assertTrue(backed_up)
        self.assertIn('"summary":[]', rewritten)
        self.assertIn('"message":"visible"', rewritten)
        self.assertNotIn("encrypted_content", rewritten)


class PathMigrationTests(unittest.TestCase):
    def test_expand_cwd_text_preserves_source_trailing_space(self):
        with mock.patch.dict("os.environ", {"HOME": "/Users/example"}, clear=True):
            actual = repair.expand_cwd_text("～/dev/know ", strip=False)

        self.assertEqual(actual, "/Users/example/dev/know ")

    def test_default_target_cwd_strips_trailing_space(self):
        with mock.patch.dict("os.environ", {"HOME": "/Users/example"}, clear=True):
            actual = repair.default_target_cwd("～/dev/know ")

        self.assertEqual(actual, "/Users/example/dev/know")

    def test_rewrite_rollout_session_meta_updates_cwd_and_provider(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rollout = root / "rollout.jsonl"
            backup = root / "backup" / "rollout.jsonl"
            rollout.write_text(
                (
                    json.dumps(
                        {
                            "type": "session_meta",
                            "payload": {
                                "id": "thread-1",
                                "cwd": "/Users/example/dev/know ",
                                "model_provider": "old",
                            },
                        }
                    )
                    + "\n"
                    + json.dumps({"type": "event_msg", "payload": {"message": "keep"}})
                    + "\n"
                ),
                encoding="utf-8",
            )

            result = repair.rewrite_rollout_session_meta(
                rollout,
                backup,
                thread_id="thread-1",
                source_cwd="/Users/example/dev/know ",
                target_cwd="/Users/example/dev/know",
                provider_label="aimai1",
                apply=True,
            )
            lines = [json.loads(line) for line in rollout.read_text(encoding="utf-8").splitlines()]

        self.assertTrue(result["changed"])
        self.assertTrue(result["cwd_changed"])
        self.assertTrue(result["provider_changed"])
        self.assertEqual(lines[0]["payload"]["cwd"], "/Users/example/dev/know")
        self.assertEqual(lines[0]["payload"]["model_provider"], "aimai1")
        self.assertEqual(lines[1]["payload"]["message"], "keep")

    def test_migrate_thread_paths_updates_only_matching_threads(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            codex_home = root / ".codex"
            codex_home.mkdir()
            sessions = codex_home / "sessions"
            sessions.mkdir()
            state_db = codex_home / "state_5.sqlite"
            rollout = sessions / "rollout-thread-1.jsonl"
            rollout.write_text(
                json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {
                            "id": "thread-1",
                            "cwd": "/Users/example/dev/know ",
                            "model_provider": "old",
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            connection = sqlite3.connect(state_db)
            try:
                connection.execute(
                    """
                    CREATE TABLE threads (
                        id TEXT PRIMARY KEY,
                        rollout_path TEXT NOT NULL,
                        cwd TEXT NOT NULL,
                        model_provider TEXT NOT NULL,
                        updated_at INTEGER NOT NULL
                    )
                    """
                )
                connection.executemany(
                    """
                    INSERT INTO threads (id, rollout_path, cwd, model_provider, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            "thread-1",
                            "sessions/rollout-thread-1.jsonl",
                            "/Users/example/dev/know ",
                            "old",
                            2,
                        ),
                        (
                            "thread-2",
                            "sessions/other.jsonl",
                            "/Users/example/dev/know",
                            "old",
                            1,
                        ),
                    ],
                )
                connection.commit()
            finally:
                connection.close()

            with mock.patch.object(repair, "STATE_DB", state_db), mock.patch.object(
                repair, "CODEX_HOME", codex_home
            ):
                result = repair.migrate_thread_paths(
                    source_cwd="/Users/example/dev/know ",
                    target_cwd="/Users/example/dev/know",
                    provider_label="aimai1",
                    backup_dir=root / "backup",
                    apply=True,
                )
            connection = sqlite3.connect(state_db)
            try:
                rows = {
                    row[0]: (row[1], row[2])
                    for row in connection.execute(
                        "SELECT id, cwd, model_provider FROM threads ORDER BY id"
                    )
                }
            finally:
                connection.close()

        self.assertEqual(result["matched_threads"], 1)
        self.assertEqual(result["database_cwd_rows_changed"], 1)
        self.assertEqual(result["database_provider_rows_changed"], 1)
        self.assertEqual(rows["thread-1"], ("/Users/example/dev/know", "aimai1"))
        self.assertEqual(rows["thread-2"], ("/Users/example/dev/know", "old"))

    def test_list_thread_cwds_counts_and_filters(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_db = Path(temp_dir) / "state_5.sqlite"
            connection = sqlite3.connect(state_db)
            try:
                connection.execute("CREATE TABLE threads (cwd TEXT NOT NULL)")
                connection.executemany(
                    "INSERT INTO threads (cwd) VALUES (?)",
                    [("/a/know",), ("/a/know",), ("/b/other ",)],
                )
                connection.commit()
            finally:
                connection.close()

            with mock.patch.object(repair, "STATE_DB", state_db):
                rows = repair.list_thread_cwds("know")

        self.assertEqual(rows, [("/a/know", 2)])


if __name__ == "__main__":
    unittest.main()
