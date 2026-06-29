import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "install.py"
SPEC = importlib.util.spec_from_file_location("cxfix_install", MODULE_PATH)
installer = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = installer
SPEC.loader.exec_module(installer)


class InstallConfigTests(unittest.TestCase):
    def test_managed_block_uses_noglob_alias(self):
        updated = installer.update_managed_block("")

        self.assertIn('alias cxfix="noglob codex-history-repair"', updated)

    def test_managed_block_replaces_old_alias(self):
        existing = """before
# >>> codex session history repair >>>
export PATH="$HOME/.local/bin:$PATH"
alias cxfix="codex-history-repair"
# <<< codex session history repair <<<
after
"""

        updated = installer.update_managed_block(existing)

        self.assertIn('alias cxfix="noglob codex-history-repair"', updated)
        self.assertNotIn('alias cxfix="codex-history-repair"', updated)
        self.assertIn("before", updated)
        self.assertIn("after", updated)


if __name__ == "__main__":
    unittest.main()
