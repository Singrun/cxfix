"""Path resolution for Codex homes and SQLite-backed state."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .config import configured_top_level_string


def default_codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()


def configured_sqlite_home(
    codex_home: Path | None = None,
    config_path: Path | None = None,
) -> Path:
    home = (codex_home or default_codex_home()).expanduser()
    configured = configured_top_level_string("sqlite_home", config_path or home / "config.toml")
    if configured:
        return Path(configured).expanduser()
    env_value = os.environ.get("CODEX_SQLITE_HOME")
    if env_value:
        return Path(env_value).expanduser()
    return home


@dataclass(frozen=True)
class CodexHome:
    root: Path
    sqlite_home: Path

    @classmethod
    def discover(cls, root: Path | None = None) -> "CodexHome":
        codex_home = (root or default_codex_home()).expanduser()
        return cls(root=codex_home, sqlite_home=configured_sqlite_home(codex_home))

    @property
    def config(self) -> Path:
        return self.root / "config.toml"

    @property
    def state_db(self) -> Path:
        return self.sqlite_home / "state_5.sqlite"

    @property
    def sessions(self) -> Path:
        return self.root / "sessions"

    @property
    def archived_sessions(self) -> Path:
        return self.root / "archived_sessions"

    @property
    def session_index(self) -> Path:
        return self.root / "session_index.jsonl"

    @property
    def backup_root(self) -> Path:
        return self.root / "backups" / "session-history-repair"

    @property
    def runtime_dir(self) -> Path:
        return self.root / "session-repair-runtime"

    @property
    def plugin_cache_root(self) -> Path:
        return self.root / "plugins" / "cache"

    @property
    def skills_root(self) -> Path:
        return self.root / "skills"
