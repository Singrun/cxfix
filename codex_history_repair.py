#!/usr/bin/env python3
"""Repair Codex Desktop's local session index after the app is closed."""

from __future__ import annotations

import argparse
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
from datetime import datetime
from pathlib import Path


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Back up and rebuild the local Codex session/provider index."
    )
    parser.add_argument(
        "scope",
        nargs="?",
        choices=("current", "all"),
        default="current",
        help="repair the current state database, or every discovered database",
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
    return parser.parse_args()


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
    if args.scope == "all":
        return run_all(args)
    return run_single(args)


if __name__ == "__main__":
    raise SystemExit(main())
