#!/usr/bin/env python3
"""Repair Codex Desktop's local session index after the app is closed."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pty
import re
import select
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


CODEX_HOME = Path.home() / ".codex"
SQLITE_HOME = Path(
    os.environ.get("CODEX_SQLITE_HOME", CODEX_HOME / "sqlite")
).expanduser()
STATE_DB = SQLITE_HOME / "state_5.sqlite"
SESSIONS = CODEX_HOME / "sessions"
SESSION_INDEX = CODEX_HOME / "session_index.jsonl"
BACKUP_ROOT = CODEX_HOME / "backups" / "session-history-repair"
RUNTIME_DIR = CODEX_HOME / "session-repair-runtime"
APP_CODEX = Path("/Applications/Codex.app/Contents/Resources/codex")
ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
OFFICIAL_PROVIDER = "openai"
PLUGIN_CACHE_ROOT = CODEX_HOME / "plugins" / "cache"
SKILLS_ROOT = CODEX_HOME / "skills"
VISIBLE_MOUNT_ROOT_NAME = "_cache_plugin_mounts"


@dataclass(frozen=True)
class PluginSkillCandidate:
    link_name: str
    skill_dir: Path
    skill_file: Path
    source: str
    plugin: str
    version: str
    display_name: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Back up and rebuild the local Codex session/provider index."
    )
    parser.add_argument(
        "scope",
        nargs="?",
        choices=("current", "all", "plugin-cache", "plugins", "skills"),
        default="current",
        help=(
            "repair the current database, every database, or mount cached "
            "plugin skills"
        ),
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=900,
        help="maximum seconds to wait for the official backfill (default: 900)",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="back up and mark the index pending, but do not launch the bundled CLI",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="terminate orphaned app-servers without prompting",
    )
    parser.add_argument(
        "--official-only",
        dest="official_only",
        action="store_true",
        default=True,
        help="normalize every non-openai history entry to the official openai provider",
    )
    parser.add_argument(
        "--preserve-providers",
        dest="official_only",
        action="store_false",
        help="keep historical provider labels instead of normalizing them",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="for plugin-cache: create missing skill symlinks instead of dry-run",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="for plugins/skills: preview cached skill mounts without writing",
    )
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=PLUGIN_CACHE_ROOT,
        help="for plugin-cache: cached plugin root",
    )
    parser.add_argument(
        "--skills-root",
        type=Path,
        default=SKILLS_ROOT,
        help="for plugin-cache: target skills root",
    )
    parser.add_argument(
        "--source",
        action="append",
        help=(
            "for plugin-cache: only promote one cache source, e.g. "
            "openai-primary-runtime; may be repeated"
        ),
    )
    parser.add_argument(
        "--visible-mounts",
        action="store_true",
        help=(
            "for plugin-cache: create namespaced wrapper skills for every "
            "cached plugin skill, including conflicts"
        ),
    )
    parser.add_argument(
        "--skip-symlinks",
        action="store_true",
        help="for plugin-cache: only create visible wrapper mounts, not top-level symlinks",
    )
    return parser.parse_args()


def parse_skill_frontmatter_name(skill_file: Path) -> str | None:
    try:
        text = skill_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    for line in text[3:end].splitlines():
        if line.strip().startswith("name:"):
            return line.split(":", 1)[1].strip().strip("\"'") or None
    return None


def safe_skill_link_name(name: str) -> str:
    normalized = name.strip().lower()
    normalized = re.sub(r"[^a-z0-9._-]+", "-", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    return normalized


def plugin_skill_source(skill_dir: Path, cache_root: Path) -> tuple[str, str, str]:
    rel = skill_dir.relative_to(cache_root)
    parts = rel.parts
    source = parts[0] if len(parts) > 0 else "unknown"
    plugin = parts[1] if len(parts) > 1 else "unknown"
    version = parts[2] if len(parts) > 2 else "unknown"
    return source, plugin, version


def discover_cached_plugin_skills(cache_root: Path) -> list[PluginSkillCandidate]:
    candidates: list[PluginSkillCandidate] = []
    for skill_file in cache_root.rglob("SKILL.md"):
        if "/skills/" not in skill_file.as_posix():
            continue
        skill_dir = skill_file.parent
        source, plugin, version = plugin_skill_source(skill_dir, cache_root)
        display_name = parse_skill_frontmatter_name(skill_file) or skill_dir.name
        link_name = safe_skill_link_name(skill_dir.name) or safe_skill_link_name(display_name)
        if not link_name:
            continue
        candidates.append(
            PluginSkillCandidate(
                link_name=link_name,
                skill_dir=skill_dir,
                skill_file=skill_file,
                source=source,
                plugin=plugin,
                version=version,
                display_name=display_name,
            )
        )
    return sorted(candidates, key=lambda c: (c.link_name, c.source, c.plugin, c.version))


def choose_plugin_skill_candidates(
    candidates: Iterable[PluginSkillCandidate],
) -> tuple[list[PluginSkillCandidate], list[list[PluginSkillCandidate]]]:
    by_name: dict[str, list[PluginSkillCandidate]] = {}
    for candidate in candidates:
        by_name.setdefault(candidate.link_name, []).append(candidate)

    chosen: list[PluginSkillCandidate] = []
    ambiguous: list[list[PluginSkillCandidate]] = []
    for _, group in sorted(by_name.items()):
        real_dirs = {candidate.skill_dir.resolve() for candidate in group}
        if len(real_dirs) == 1:
            chosen.append(group[-1])
            continue
        primary = [candidate for candidate in group if candidate.source == "openai-primary-runtime"]
        if primary and len({candidate.skill_dir.resolve() for candidate in primary}) == 1:
            chosen.append(primary[-1])
        else:
            ambiguous.append(group)
    return chosen, ambiguous


def cached_plugin_skill_status(
    candidate: PluginSkillCandidate, skills_root: Path
) -> tuple[str, str]:
    link = skills_root / candidate.link_name
    target = candidate.skill_dir.resolve()
    if not link.exists() and not link.is_symlink():
        return "create", f"{link} -> {target}"
    if link.is_symlink():
        current = link.resolve()
        if current == target:
            return "ok", f"{link} already points to {target}"
        return "conflict", f"{link} points to {current}, wanted {target}"
    return "conflict", f"{link} exists and is not a symlink"


def visible_mount_dir(candidate: PluginSkillCandidate, skills_root: Path) -> Path:
    return (
        skills_root
        / VISIBLE_MOUNT_ROOT_NAME
        / safe_skill_link_name(candidate.source)
        / safe_skill_link_name(candidate.plugin)
        / safe_skill_link_name(candidate.version)
        / candidate.link_name
    )


def visible_mount_name(candidate: PluginSkillCandidate) -> str:
    identity = (
        f"{candidate.source}:{candidate.plugin}:"
        f"{candidate.version}:{candidate.link_name}"
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:10]
    prefix = safe_skill_link_name(candidate.link_name)[:46].strip("-")
    return f"cache:{prefix}:{digest}"


def visible_mount_content(candidate: PluginSkillCandidate) -> str:
    original_skill = candidate.skill_file.resolve()
    original_dir = candidate.skill_dir.resolve()
    skill_name = visible_mount_name(candidate)
    description = (
        f"Visible mount for cached Codex plugin skill {candidate.display_name!r} "
        f"from {candidate.source}/{candidate.plugin}/{candidate.version}."
    )
    return f"""---
name: {json.dumps(skill_name)}
description: {json.dumps(description)}
---

# Cached Plugin Skill Mount

This is a generated visible mount for a cached Codex plugin skill.

- Original skill name: `{candidate.display_name}`
- Original skill file: `{original_skill}`
- Original skill directory: `{original_dir}`
- Cache source: `{candidate.source}`
- Plugin: `{candidate.plugin}`
- Version: `{candidate.version}`

When this mounted skill is selected, read the original `SKILL.md` above
completely, then follow that skill's instructions. Resolve any relative files,
scripts, references, templates, or assets relative to the original skill
directory, not this generated mount directory.

Do not edit this generated mount by hand. Re-run `cxfix plugin-cache
--visible-mounts --apply` to refresh it.
"""


def visible_mount_status(
    candidate: PluginSkillCandidate, skills_root: Path
) -> tuple[str, str, Path, str]:
    mount_dir = visible_mount_dir(candidate, skills_root)
    mount_file = mount_dir / "SKILL.md"
    content = visible_mount_content(candidate)
    if not mount_file.exists():
        return "create", f"{mount_file} wraps {candidate.skill_file.resolve()}", mount_file, content
    try:
        current = mount_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "conflict", f"{mount_file} exists but cannot be read", mount_file, content
    if current == content:
        return "ok", f"{mount_file} already wraps {candidate.skill_file.resolve()}", mount_file, content
    if "This is a generated visible mount for a cached Codex plugin skill." in current:
        return "update", f"{mount_file} will be refreshed", mount_file, content
    return "conflict", f"{mount_file} exists and is not a generated mount", mount_file, content


def run_plugin_cache(args: argparse.Namespace) -> int:
    cache_root = args.cache_root.expanduser()
    skills_root = args.skills_root.expanduser()
    if not cache_root.exists():
        print(f"cache root not found: {cache_root}", file=sys.stderr)
        return 2
    if args.apply:
        skills_root.mkdir(parents=True, exist_ok=True)

    discovered = discover_cached_plugin_skills(cache_root)
    if args.source:
        allowed_sources = set(args.source)
        discovered = [
            candidate
            for candidate in discovered
            if candidate.source in allowed_sources
        ]
    candidates, ambiguous = choose_plugin_skill_candidates(discovered)
    creates = oks = conflicts = 0
    if not args.skip_symlinks:
        for candidate in candidates:
            state, message = cached_plugin_skill_status(candidate, skills_root)
            if state == "create":
                creates += 1
                if args.apply:
                    (skills_root / candidate.link_name).symlink_to(
                        candidate.skill_dir.resolve(), target_is_directory=True
                    )
            elif state == "ok":
                oks += 1
            else:
                conflicts += 1
            label = {"create": "CREATE", "ok": "OK", "conflict": "CONFLICT"}[state]
            print(f"{label:8} {candidate.link_name:32} {message}")
    else:
        print("Top-level symlink promotion skipped.")

    visible_creates = visible_updates = visible_oks = visible_conflicts = 0
    if args.visible_mounts:
        print("\nVisible mounts:")
        for candidate in discovered:
            state, message, mount_file, content = visible_mount_status(
                candidate, skills_root
            )
            if state == "create":
                visible_creates += 1
            elif state == "update":
                visible_updates += 1
            elif state == "ok":
                visible_oks += 1
            else:
                visible_conflicts += 1

            if args.apply and state in {"create", "update"}:
                mount_file.parent.mkdir(parents=True, exist_ok=True)
                mount_file.write_text(content, encoding="utf-8")

            label = {
                "create": "CREATE",
                "update": "UPDATE",
                "ok": "OK",
                "conflict": "CONFLICT",
            }[state]
            print(f"{label:8} {visible_mount_name(candidate):64} {message}")

    if ambiguous and not args.skip_symlinks:
        print("\nAMBIGUOUS cached skill names skipped for top-level symlinks:")
        for group in ambiguous:
            print(f"- {group[0].link_name}")
            for candidate in group:
                print(
                    f"  {candidate.source}/{candidate.plugin}/{candidate.version}: "
                    f"{candidate.skill_dir}"
                )

    mode = "applied" if args.apply else "dry-run"
    top_symlink_ambiguous = 0 if args.skip_symlinks else len(ambiguous)
    print(
        f"\nSummary ({mode}): create={creates}, ok={oks}, "
        f"conflict={conflicts}, top_symlink_ambiguous={top_symlink_ambiguous}, "
        f"visible_create={visible_creates}, visible_update={visible_updates}, "
        f"visible_ok={visible_oks}, visible_conflict={visible_conflicts}"
    )
    if not args.apply and creates and not args.skip_symlinks:
        print("Run again with: cxfix plugin-cache --apply")
    if not args.apply and args.visible_mounts and (visible_creates or visible_updates):
        command = "cxfix plugin-cache --visible-mounts --apply"
        if args.skip_symlinks:
            command = "cxfix plugin-cache --visible-mounts --skip-symlinks --apply"
        print(f"Run again with: {command}")
    if args.apply and visible_conflicts:
        return 1
    if args.apply and not args.visible_mounts and (conflicts or ambiguous):
        return 1
    return 0


def discover_state_databases(
    *,
    codex_home: Path = CODEX_HOME,
    user_home: Path | None = None,
) -> list[Path]:
    home = user_home or Path.home()
    managed_root = (
        home
        / "Library"
        / "Application Support"
        / "CodexBar"
        / "managed-codex-homes"
    )
    candidates = [
        codex_home / "sqlite" / "state_5.sqlite",
        codex_home / "state_5.sqlite",
    ]
    configured_sqlite_home = os.environ.get("CODEX_SQLITE_HOME")
    if configured_sqlite_home:
        candidates.append(
            Path(configured_sqlite_home).expanduser() / "state_5.sqlite"
        )
    if managed_root.is_dir():
        candidates.extend(sorted(managed_root.glob("*/state_5.sqlite")))

    discovered: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        normalized = path.resolve()
        if path.is_file() and normalized not in seen:
            discovered.append(path)
            seen.add(normalized)
    return discovered


def running_codex_processes() -> list[tuple[int, int, str]]:
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,ppid=,command="],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(
            "Unable to inspect processes. Run this command from a normal Terminal."
        ) from exc

    matches: list[tuple[int, int, str]] = []
    for line in result.stdout.splitlines():
        fields = line.strip().split(maxsplit=2)
        if len(fields) != 3:
            continue
        pid_text, ppid_text, command = fields
        if (
            "/Applications/Codex.app/Contents/MacOS/Codex" in command
            or "/Applications/Codex.app/Contents/Resources/codex" in command
            or re.search(r"\bcodex\s+app-server\b", command)
        ):
            matches.append((int(pid_text), int(ppid_text), command))
    return matches


def terminate_orphan_servers(processes: list[tuple[int, int, str]]) -> None:
    for pid, _, _ in processes:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    deadline = time.monotonic() + 10
    remaining = {pid for pid, _, _ in processes}
    while remaining and time.monotonic() < deadline:
        time.sleep(0.25)
        for pid in list(remaining):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                remaining.remove(pid)
    if remaining:
        raise RuntimeError(
            "Some orphaned app-servers did not exit: "
            + ", ".join(str(pid) for pid in sorted(remaining))
        )


def connect(*, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        return sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True, timeout=30)
    return sqlite3.connect(STATE_DB, timeout=30)


def database_state() -> tuple[str, int]:
    connection = connect(readonly=True)
    try:
        status = connection.execute(
            "SELECT status FROM backfill_state WHERE id = 1"
        ).fetchone()[0]
        count = connection.execute("SELECT COUNT(*) FROM threads").fetchone()[0]
        return status, count
    finally:
        connection.close()


def rollout_ids() -> set[str]:
    ids: set[str] = set()
    for path in SESSIONS.rglob("*.jsonl"):
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    item = json.loads(line)
                    if item.get("type") == "session_meta":
                        session_id = (item.get("payload") or {}).get("id")
                        if session_id:
                            ids.add(session_id)
                        break
        except (OSError, json.JSONDecodeError):
            continue
    return ids


def database_ids() -> set[str]:
    connection = connect(readonly=True)
    try:
        return {row[0] for row in connection.execute("SELECT id FROM threads")}
    finally:
        connection.close()


def backup_and_mark_pending() -> tuple[Path, int, int]:
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f-%z")
    backup_dir = BACKUP_ROOT / stamp
    backup_dir.mkdir(parents=True, exist_ok=False)

    connection = connect()
    try:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
        if quick_check != "ok":
            raise RuntimeError(f"SQLite quick_check failed: {quick_check}")

        before_count = connection.execute("SELECT COUNT(*) FROM threads").fetchone()[0]
        backup = sqlite3.connect(backup_dir / STATE_DB.name)
        try:
            connection.backup(backup)
        finally:
            backup.close()

        with connection:
            connection.execute(
                """
                UPDATE backfill_state
                SET status = 'pending',
                    last_watermark = NULL,
                    last_success_at = NULL,
                    updated_at = ?
                WHERE id = 1
                """,
                (int(time.time()),),
            )
    finally:
        connection.close()

    if SESSION_INDEX.is_file():
        shutil.copy2(SESSION_INDEX, backup_dir / SESSION_INDEX.name)

    missing_before = len(rollout_ids() - database_ids())
    manifest = {
        "created_at": stamp,
        "codex_home": str(CODEX_HOME),
        "sqlite_home": str(SQLITE_HOME),
        "state_database": str(STATE_DB),
        "quick_check": "ok",
        "thread_count_before": before_count,
        "rollouts_missing_from_database_before": missing_before,
    }
    (backup_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return backup_dir, before_count, missing_before


def normalize_rollout_file(path: Path, backup_path: Path) -> str | None:
    temp_path = path.with_name(path.name + ".cxfix.tmp")
    changed_provider: str | None = None
    changed = False
    backup_path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("r", encoding="utf-8") as source:
        lines = source.readlines()

    updated_lines: list[str] = []
    for line in lines:
        item = json.loads(line)
        if item.get("type") == "session_meta":
            payload = item.get("payload") or {}
            provider = payload.get("model_provider")
            if provider != OFFICIAL_PROVIDER:
                changed_provider = provider or "<missing>"
                changed = True
                payload["model_provider"] = OFFICIAL_PROVIDER
                item["payload"] = payload
                line = json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n"
        updated_lines.append(line)

    if not changed:
        return None

    shutil.copy2(path, backup_path)
    try:
        with temp_path.open("w", encoding="utf-8") as target:
            target.writelines(updated_lines)
            target.flush()
            os.fsync(target.fileno())
        shutil.copystat(path, temp_path)
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)
    return changed_provider


def normalize_legacy_providers(backup_dir: Path) -> dict[str, object]:
    changed_files: list[str] = []
    original_counts: dict[str, int] = {}
    rollout_backup_root = backup_dir / "rollouts"

    for path in sorted(SESSIONS.rglob("*.jsonl")):
        relative = path.relative_to(SESSIONS)
        provider = normalize_rollout_file(path, rollout_backup_root / relative)
        if provider is not None:
            original_counts[provider] = original_counts.get(provider, 0) + 1
            changed_files.append(str(relative))

    connection = connect()
    try:
        before_rows = {
            row[0]: row[1]
            for row in connection.execute(
                """
                SELECT model_provider, COUNT(*)
                FROM threads
                WHERE model_provider <> ?
                GROUP BY model_provider
                """,
                (OFFICIAL_PROVIDER,),
            )
        }
        with connection:
            cursor = connection.execute(
                """
                UPDATE threads
                SET model_provider = ?
                WHERE model_provider <> ?
                """,
                (OFFICIAL_PROVIDER, OFFICIAL_PROVIDER),
            )
        updated_rows = cursor.rowcount
    finally:
        connection.close()

    return {
        "target_provider": OFFICIAL_PROVIDER,
        "rollout_files_changed": len(changed_files),
        "rollout_original_provider_counts": original_counts,
        "database_rows_changed": updated_rows,
        "database_original_provider_counts": before_rows,
        "changed_rollouts": changed_files,
    }


def provider_counts() -> dict[str, int]:
    connection = connect(readonly=True)
    try:
        return {
            row[0]: row[1]
            for row in connection.execute(
                """
                SELECT model_provider, COUNT(*)
                FROM threads
                GROUP BY model_provider
                ORDER BY model_provider
                """
            )
        }
    finally:
        connection.close()


def rollout_has_user_event(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                item = json.loads(line)
                payload = item.get("payload") or {}
                if (
                    item.get("type") == "event_msg"
                    and payload.get("type") == "user_message"
                    and str(payload.get("message") or "").strip()
                ):
                    return True
    except (OSError, json.JSONDecodeError):
        return False
    return False


def reconcile_user_event_flags() -> dict[str, object]:
    connection = connect()
    connection.row_factory = sqlite3.Row
    changed = 0
    true_count = 0
    false_count = 0
    missing_rollouts: list[str] = []
    try:
        rows = connection.execute(
            "SELECT id, rollout_path, has_user_event FROM threads"
        ).fetchall()
        updates: list[tuple[int, str]] = []
        for row in rows:
            path = Path(row["rollout_path"])
            if not path.is_absolute():
                path = CODEX_HOME / path
            if not path.is_file():
                missing_rollouts.append(row["id"])
                continue
            desired = 1 if rollout_has_user_event(path) else 0
            true_count += desired
            false_count += 1 - desired
            if row["has_user_event"] != desired:
                updates.append((desired, row["id"]))
        with connection:
            connection.executemany(
                "UPDATE threads SET has_user_event = ? WHERE id = ?",
                updates,
            )
        changed = len(updates)
    finally:
        connection.close()
    return {
        "database_rows_changed": changed,
        "has_user_event_true": true_count,
        "has_user_event_false": false_count,
        "missing_rollout_ids": missing_rollouts,
    }


def mark_backfill_complete() -> None:
    rollouts = sorted(SESSIONS.rglob("*.jsonl"))
    watermark = (
        str(rollouts[-1].relative_to(CODEX_HOME)) if rollouts else None
    )
    now = int(time.time())
    connection = connect()
    try:
        with connection:
            connection.execute(
                """
                UPDATE backfill_state
                SET status = 'complete',
                    last_watermark = ?,
                    last_success_at = ?,
                    updated_at = ?
                WHERE id = 1
                """,
                (watermark, now, now),
            )
    finally:
        connection.close()


def bundled_codex() -> Path:
    if APP_CODEX.is_file():
        return APP_CODEX
    executable = shutil.which("codex")
    if executable:
        return Path(executable)
    raise RuntimeError("Codex CLI not found")


def terminate_child(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGINT)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        waited, _ = os.waitpid(pid, os.WNOHANG)
        if waited == pid:
            return
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass


def run_official_backfill(timeout: int) -> list[tuple[str, int]]:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    executable = bundled_codex()
    env = os.environ.copy()
    env["TERM"] = "xterm-256color"

    pid, master_fd = pty.fork()
    if pid == 0:
        os.chdir(RUNTIME_DIR)
        os.execve(
            str(executable),
            [str(executable), "--no-alt-screen", "-C", str(RUNTIME_DIR)],
            env,
        )

    observations: list[tuple[str, int]] = []
    last_state: tuple[str, int] | None = None
    screen_text = ""
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            readable, _, _ = select.select([master_fd], [], [], 0.5)
            if readable:
                try:
                    chunk = os.read(master_fd, 65536).decode("utf-8", "ignore")
                except OSError:
                    chunk = ""
                screen_text = (screen_text + ANSI_ESCAPE.sub("", chunk))[-12000:]
                if "Continue anyway? [y/N]:" in screen_text:
                    os.write(master_fd, b"y\n")
                    screen_text = ""
                elif "Do you trust the contents of this directory?" in screen_text:
                    os.write(master_fd, b"\n")
                    screen_text = ""

            current = database_state()
            if current != last_state:
                observations.append(current)
                print(f"backfill={current[0]} threads={current[1]}", flush=True)
                last_state = current
            if current[0] == "complete":
                return observations

            waited, status = os.waitpid(pid, os.WNOHANG)
            if waited == pid:
                raise RuntimeError(f"Codex CLI exited early with status {status}")
        raise TimeoutError(f"backfill did not finish within {timeout} seconds")
    finally:
        os.close(master_fd)
        terminate_child(pid)


def run_single(args: argparse.Namespace) -> int:
    if not STATE_DB.is_file() or not SESSIONS.is_dir():
        print("Codex state database or sessions directory is missing.", file=sys.stderr)
        return 2

    try:
        active = running_codex_processes()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 4

    desktop = [
        item for item in active if "/Applications/Codex.app/Contents/MacOS/Codex" in item[2]
    ]
    orphan_servers = [
        item for item in active if item[1] == 1 and " app-server " in item[2]
    ]
    blocking = [item for item in active if item not in orphan_servers]

    if desktop or blocking:
        print("Please quit Codex Desktop and any active Codex CLI first:", file=sys.stderr)
        for pid, ppid, command in active:
            print(f"  pid={pid} ppid={ppid} {command}", file=sys.stderr)
        return 3

    if orphan_servers:
        print(
            "Found orphaned Codex app-servers: "
            + ", ".join(str(pid) for pid, _, _ in orphan_servers)
        )
        if not args.yes:
            answer = input("Terminate them before repairing? [Y/n] ").strip().lower()
            if answer not in {"", "y", "yes"}:
                print("Cancelled.")
                return 3
        terminate_orphan_servers(orphan_servers)
        print("Orphaned app-servers stopped.")

    backup_dir, before_count, missing_before = backup_and_mark_pending()
    print(f"backup={backup_dir}")
    print(f"state_database={STATE_DB}")
    print(f"threads_before={before_count} missing_rollouts_before={missing_before}")

    normalization = None
    if args.official_only:
        normalization = normalize_legacy_providers(backup_dir)
        print(
            "normalized_rollouts="
            f"{normalization['rollout_files_changed']} "
            f"normalized_database_rows={normalization['database_rows_changed']}"
        )

    user_event_reconciliation = reconcile_user_event_flags()
    print(
        "user_event_rows_changed="
        f"{user_event_reconciliation['database_rows_changed']} "
        f"user_threads={user_event_reconciliation['has_user_event_true']}"
    )

    if args.prepare_only:
        if normalization is not None:
            manifest_path = backup_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["provider_normalization"] = normalization
            manifest["user_event_reconciliation"] = user_event_reconciliation
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        print("Prepared. Reopen Codex to run the pending backfill.")
        return 0

    if missing_before == 0 and not user_event_reconciliation["missing_rollout_ids"]:
        mark_backfill_complete()
        observations = [("reconciled", before_count), ("complete", before_count)]
    else:
        observations = run_official_backfill(args.timeout)
    after_count = len(database_ids())
    missing_after = rollout_ids() - database_ids()
    print(f"threads_after={after_count} missing_rollouts_after={len(missing_after)}")

    manifest_path = backup_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "observations": observations,
            "thread_count_after": after_count,
            "rollouts_missing_from_database_after": sorted(missing_after),
            "provider_normalization": normalization,
            "user_event_reconciliation": user_event_reconciliation,
            "provider_counts_after": provider_counts(),
        }
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    counts_after = provider_counts()
    legacy_remaining = (
        sum(count for provider, count in counts_after.items() if provider != OFFICIAL_PROVIDER)
        if args.official_only
        else 0
    )
    if missing_after or legacy_remaining:
        print(
            "Backfill completed, but verification found remaining discrepancies. "
            f"See {manifest_path}",
            file=sys.stderr,
        )
    else:
        print("Codex session history repair completed.")
    return 0


def run_all(args: argparse.Namespace) -> int:
    databases = discover_state_databases()
    if not databases:
        print("No Codex state databases were found.", file=sys.stderr)
        return 2

    print(f"all_targets={len(databases)}")
    failures: list[tuple[Path, int]] = []
    for index, database in enumerate(databases, start=1):
        print(f"\n[{index}/{len(databases)}] syncing {database}", flush=True)
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "current",
            "--timeout",
            str(args.timeout),
            "-y",
        ]
        if args.prepare_only:
            command.append("--prepare-only")
        command.append(
            "--official-only" if args.official_only else "--preserve-providers"
        )
        env = os.environ.copy()
        env["CODEX_SQLITE_HOME"] = str(database.parent)
        result = subprocess.run(command, env=env)
        if result.returncode != 0:
            failures.append((database, result.returncode))

    if failures:
        print("\nSome state databases could not be synchronized:", file=sys.stderr)
        for database, returncode in failures:
            print(f"  exit={returncode} {database}", file=sys.stderr)
        return 1

    print(f"\nAll {len(databases)} Codex state databases are synchronized.")
    return 0


def main() -> int:
    args = parse_args()
    if args.scope in {"plugins", "skills"}:
        args.visible_mounts = True
        args.skip_symlinks = True
        args.apply = not args.dry_run
        return run_plugin_cache(args)
    if args.scope == "plugin-cache":
        return run_plugin_cache(args)
    if args.scope == "all":
        return run_all(args)
    return run_single(args)


if __name__ == "__main__":
    raise SystemExit(main())
