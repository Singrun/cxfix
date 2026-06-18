import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).parents[1] / "codex_history_repair.py"
SPEC = importlib.util.spec_from_file_location("codex_history_repair", MODULE_PATH)
repair = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = repair
SPEC.loader.exec_module(repair)


class ParseArgsTests(unittest.TestCase):
    def test_all_scope_is_accepted(self):
        with mock.patch("sys.argv", ["cxfix", "all", "-y"]):
            args = repair.parse_args()

        self.assertEqual(args.scope, "all")
        self.assertTrue(args.yes)

    def test_plugin_cache_scope_is_accepted(self):
        with mock.patch(
            "sys.argv",
            ["cxfix", "plugin-cache", "--apply", "--visible-mounts"],
        ):
            args = repair.parse_args()

        self.assertEqual(args.scope, "plugin-cache")
        self.assertTrue(args.apply)
        self.assertTrue(args.visible_mounts)

    def test_plugins_scope_is_accepted(self):
        with mock.patch("sys.argv", ["cxfix", "plugins", "--dry-run"]):
            args = repair.parse_args()

        self.assertEqual(args.scope, "plugins")
        self.assertTrue(args.dry_run)

    def test_short_plugins_scope_and_dry_run_are_accepted(self):
        with mock.patch("sys.argv", ["cxfix", "p", "-n"]):
            args = repair.parse_args()

        self.assertEqual(args.scope, "p")
        self.assertTrue(args.dry_run)

    def test_short_plugin_cache_options_are_accepted(self):
        with mock.patch(
            "sys.argv",
            ["cxfix", "plugin-cache", "-s", "openai-primary-runtime", "-A", "-v", "-S"],
        ):
            args = repair.parse_args()

        self.assertEqual(args.source, ["openai-primary-runtime"])
        self.assertTrue(args.apply)
        self.assertTrue(args.visible_mounts)
        self.assertTrue(args.skip_symlinks)


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
                codex_home / "sqlite" / "state_5.sqlite",
                codex_home / "state_5.sqlite",
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


if __name__ == "__main__":
    unittest.main()
