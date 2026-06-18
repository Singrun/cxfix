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
- Promotes cached Codex plugin skills into `~/.codex/skills` with safe symlinks
  via `cxfix plugin-cache`.

It does not upload conversation data and does not copy rollout contents to
GitHub or any remote service.

## Requirements

- macOS
- Python 3.10 or newer
- Codex Desktop or Codex CLI installed

## Install

### Download a release

Download `cxfix-v1.0.0.zip` or `cxfix-v1.0.0.tar.gz` from the
[GitHub Releases page](https://github.com/Singrun/cxfix/releases), extract it,
then run:

```bash
python3 install.py
source ~/.zshrc
```

The release also provides a standalone `cxfix` executable for users who prefer
to install the script manually.

### Clone the repository

```bash
git clone https://github.com/Singrun/cxfix.git
cd cxfix
python3 install.py
source ~/.zshrc
```

The installer adds `~/.local/bin` to `PATH`, sets the standard SQLite home, and
creates the `cxfix` alias.

## Recommended zsh Configuration

The installer manages this block in `~/.zshrc`:

```zsh
# >>> codex session history repair >>>
export PATH="$HOME/.local/bin:$PATH"
export CODEX_SQLITE_HOME="$HOME/.codex/sqlite"
alias cxfix="codex-history-repair"
# <<< codex session history repair <<<
```

Useful optional shortcuts:

```zsh
# Repair the official/current database.
alias cxfix-now='cxfix -y'

# Synchronize every discovered Codex database.
alias cxfix-all='cxfix all -y'

# Preserve third-party provider labels.
alias cxfix-keep='cxfix all -y --preserve-providers'
```

Do not run these aliases while Codex Desktop is open. The utility will refuse
to continue if it detects an active Codex process.

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

Mount all cached plugin skills visibly into Codex:

```bash
cxfix plugins
```

Preview what would be mounted without writing:

```bash
cxfix plugins --dry-run
```

Advanced: create missing top-level symlinks under `~/.codex/skills`:

```bash
cxfix plugin-cache --apply
```

Advanced: only expose one cached plugin source, such as the primary runtime
Office-style skills:

```bash
cxfix plugin-cache --source openai-primary-runtime --apply
```

The generated visible names use this shape:

```text
cache:<skill>:<hash>
```

`plugin-cache` is idempotent. It skips ambiguous duplicate names and refuses to
overwrite existing non-symlink skill directories. Visible mounts are generated
under `~/.codex/skills/_cache_plugin_mounts/` and point back to the original
cached `SKILL.md`, so official cache files are not modified. The short hash
keeps generated skill names under Codex's 64-character limit while preserving
the full source path inside the wrapper body.

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
