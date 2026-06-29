"""Config parsing helpers for Codex user-level TOML files."""

from __future__ import annotations

import json
import re
from pathlib import Path


TOP_LEVEL_TOML_STRING = re.compile(r"^\s*{key}\s*=\s*(.+?)\s*(?:#.*)?$")


def parse_toml_string(value: str) -> str | None:
    text = value.strip()
    if not text:
        return None
    quote = text[0]
    if quote in {'"', "'"}:
        end = text.find(quote, 1)
        if end == -1:
            return None
        raw = text[: end + 1]
        if quote == '"':
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return None
        return raw[1:-1]
    return text.split()[0] or None


def configured_top_level_string(key: str, config_path: Path) -> str | None:
    try:
        lines = config_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None

    matcher = re.compile(TOP_LEVEL_TOML_STRING.pattern.format(key=re.escape(key)))
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("["):
            return None
        match = matcher.match(line)
        if match:
            return parse_toml_string(match.group(1))
    return None


def configured_model_provider(config_path: Path) -> str | None:
    return configured_top_level_string("model_provider", config_path)
