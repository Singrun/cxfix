#!/usr/bin/env python3
"""Install codex-history-repair and its zsh shortcut."""

from __future__ import annotations

import shutil
from pathlib import Path


SOURCE = Path(__file__).with_name("codex_history_repair.py")
PACKAGE_SOURCE = Path(__file__).with_name("cxfix")
BIN_DIR = Path.home() / ".local" / "bin"
TARGET = BIN_DIR / "codex-history-repair"
PACKAGE_TARGET = BIN_DIR / "cxfix"
ZSHRC = Path.home() / ".zshrc"
START = "# >>> codex session history repair >>>"
END = "# <<< codex session history repair <<<"
BLOCK = f"""\
{START}
export PATH="$HOME/.local/bin:$PATH"
alias cxfix="codex-history-repair"
{END}
"""


def update_managed_block(text: str) -> str:
    if START in text and END in text:
        prefix, remainder = text.split(START, 1)
        _, suffix = remainder.split(END, 1)
        text = prefix.rstrip() + "\n\n" + BLOCK + suffix.lstrip("\n")
    else:
        text = text.rstrip() + "\n\n" + BLOCK
    return text


def main() -> None:
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE, TARGET)
    TARGET.chmod(0o755)
    if PACKAGE_TARGET.exists() and not PACKAGE_TARGET.is_dir():
        raise RuntimeError(f"cannot install package over non-directory: {PACKAGE_TARGET}")
    shutil.copytree(PACKAGE_SOURCE, PACKAGE_TARGET, dirs_exist_ok=True)

    current = ZSHRC.read_text(encoding="utf-8") if ZSHRC.exists() else ""
    updated = update_managed_block(current)
    ZSHRC.write_text(updated, encoding="utf-8")

    print(f"installed={TARGET}")
    print(f"package={PACKAGE_TARGET}")
    print(f"configured={ZSHRC}")
    print("command=cxfix")


if __name__ == "__main__":
    main()
