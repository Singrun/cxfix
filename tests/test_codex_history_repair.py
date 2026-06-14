import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).parents[1] / "codex_history_repair.py"
SPEC = importlib.util.spec_from_file_location("codex_history_repair", MODULE_PATH)
repair = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(repair)


class ParseArgsTests(unittest.TestCase):
    def test_all_scope_is_accepted(self):
        with mock.patch("sys.argv", ["cxfix", "all", "-y"]):
            args = repair.parse_args()

        self.assertEqual(args.scope, "all")
        self.assertTrue(args.yes)


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


if __name__ == "__main__":
    unittest.main()
