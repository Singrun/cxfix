"""Config parsing helpers for Codex user-level TOML files."""

from __future__ import annotations

import json
import re
import shutil
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any


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


SECRET_KEY_PARTS = ("api_key", "token", "secret", "password", "authorization", "credential")


def load_toml_config(config_path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(config_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def redact_config(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, child in value.items():
            if any(part in key.lower() for part in SECRET_KEY_PARTS):
                redacted[key] = "<redacted>"
            else:
                redacted[key] = redact_config(child)
        return redacted
    if isinstance(value, list):
        return [redact_config(item) for item in value]
    return value


def provider_names(config: dict[str, Any]) -> list[str]:
    providers = config.get("model_providers")
    if not isinstance(providers, dict):
        return []
    return sorted(providers)


def profile_names(config: dict[str, Any]) -> list[str]:
    profiles = config.get("profiles")
    if not isinstance(profiles, dict):
        return []
    return sorted(profiles)


def plugin_names(config: dict[str, Any]) -> list[str]:
    plugins = config.get("plugins")
    if not isinstance(plugins, dict):
        return []
    return sorted(plugins)


def mcp_server_names(config: dict[str, Any]) -> list[str]:
    servers = config.get("mcp_servers")
    if not isinstance(servers, dict):
        return []
    return sorted(servers)


def project_paths(config: dict[str, Any]) -> list[str]:
    projects = config.get("projects")
    if not isinstance(projects, dict):
        return []
    return sorted(projects)


def replace_top_level_string(config_path: Path, key: str, value: str) -> bool:
    lines = config_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    matcher = re.compile(TOP_LEVEL_TOML_STRING.pattern.format(key=re.escape(key)))
    replacement = f"{key} = {json.dumps(value, ensure_ascii=False)}\n"
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("["):
            lines.insert(index, replacement)
            config_path.write_text("".join(lines), encoding="utf-8")
            return True
        if stripped and not stripped.startswith("#") and matcher.match(line):
            lines[index] = replacement
            config_path.write_text("".join(lines), encoding="utf-8")
            return True
    lines.append(replacement)
    config_path.write_text("".join(lines), encoding="utf-8")
    return True


def backup_config(config_path: Path, backup_root: Path) -> Path:
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f-%z")
    backup_dir = backup_root / f"{stamp}-config"
    backup_dir.mkdir(parents=True, exist_ok=False)
    backup_path = backup_dir / config_path.name
    shutil.copy2(config_path, backup_path)
    return backup_path
