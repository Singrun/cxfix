# cxfix

`cxfix` repairs the local Codex Desktop session index when existing conversations
do not appear in the desktop history.

It is a small, dependency-free Python utility for macOS. Before changing
anything, it creates a SQLite backup. It can repair the primary Codex database
or synchronize every discovered database, including CodexBar managed homes.

> This is an independent community tool. It is not affiliated with or supported
> by OpenAI. Codex's local database schema is not a public compatibility
> contract and may change.

## What It Does

- Checks that Codex Desktop and active Codex CLI processes are closed.
- Verifies the SQLite database with `PRAGMA quick_check`.
- Backs up each database before making changes.
- Rebuilds missing thread index rows from local rollout files.
- Reconciles `has_user_event` flags from actual user messages.
- Optionally normalizes historical provider labels to `openai`.
- Finds the standard database, a legacy root database, an explicitly configured
  `CODEX_SQLITE_HOME`, and CodexBar managed databases.

It does not upload conversation data and does not copy rollout contents to
GitHub or any remote service.

## Requirements

- macOS
- Python 3.10 or newer
- Codex Desktop or Codex CLI installed

## Install

```bash
git clone https://github.com/Singrun/cxfix.git
cd cxfix
python3 install.py
source ~/.zshrc
```

The installer adds `~/.local/bin` to `PATH`, sets the standard SQLite home, and
creates the `cxfix` alias.

## Usage

Quit Codex Desktop before running a repair.

Repair the current database:

```bash
cxfix -y
```

Repair every discovered database:

```bash
cxfix all -y
```

Keep existing provider labels:

```bash
cxfix all -y --preserve-providers
```

Prepare the database and let Codex perform backfill after reopening:

```bash
cxfix all -y --prepare-only
```

By default, provider labels are normalized to `openai`. This helps recover
threads hidden by provider filtering, but it is a deliberate data change. Use
`--preserve-providers` when provider-specific history separation matters.

## Backups

Backups and manifests are written under:

```text
~/.codex/backups/session-history-repair/
```

Each target database receives its own timestamped backup and verification
manifest.

## Development

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile codex_history_repair.py install.py
```

## Safety

This utility works with local SQLite state used by Codex. Keep Codex closed
during repair, retain the generated backups, and review the source before use.

## License

MIT
