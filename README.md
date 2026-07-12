# cxfix

[中文说明](README.zh-CN.md)

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
- Preserves Codex-managed visibility fields and historical provider labels.
- Migrates exact workspace paths across SQLite, rollouts, and
  `.codex-global-state.json`.
- Optionally removes provider-specific encrypted reasoning payloads that can
  break when a thread switches between official OpenAI and third-party routed
  APIs.
- Finds the current configured database, the legacy `~/.codex/sqlite`
  database, an explicitly configured `CODEX_SQLITE_HOME`, and CodexBar managed
  databases.
- Promotes cached Codex plugin skills into `~/.codex/skills` with safe symlinks
  via `cxfix plugins cache`.

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

The installer adds `~/.local/bin` to `PATH`, copies the `cxfix` Python package
next to the executable, and creates the `cxfix` alias.

## Recommended zsh Configuration

The installer manages this block in `~/.zshrc`:

```zsh
# >>> codex session history repair >>>
export PATH="$HOME/.local/bin:$PATH"
alias cxfix="noglob codex-history-repair"
# <<< codex session history repair <<<
```

Useful optional shortcuts:

```zsh
# Repair the current configured database.
alias cxfix-now='cxfix fix -y'

# Synchronize every discovered Codex database.
alias cxfix-all='cxfix fix-all -y'

```

Do not run these aliases while Codex Desktop is open. The utility will refuse
to continue if it detects an active Codex process.

## Usage

Quit Codex Desktop before running a repair.

Show all commands and common examples:

```bash
cxfix -?
```

The installer uses a `noglob` alias so `-?` works in zsh instead of being
treated as a filename pattern.

Display the current Codex configuration, state paths, providers, profiles,
plugins, MCP servers, projects, and thread provider counts:

```bash
cxfix config show
```

Emit the same summary as redacted JSON:

```bash
cxfix config show -j
```

The JSON output also includes the full parsed config under `redacted_config`,
with secrets such as API keys and tokens replaced by `<redacted>`.

Switch the top-level Codex provider after backing up `config.toml`:

```bash
cxfix provider switch aimai1
```

Repair the current configured database:

```bash
cxfix fix -y
```

Repair every discovered database:

```bash
cxfix fix-all -y
```

Prepare the database and let Codex perform backfill after reopening:

```bash
cxfix fix-all -y -r
```

Clean encrypted reasoning payloads after provider switching errors:

```bash
cxfix clean -y
```

Run encrypted cleanup together with a full history repair:

```bash
cxfix fix-all -y -e
```

Preview a thread path migration without writing:

```bash
cxfix path migrate -f '～/dev/know '
```

List known thread working directories before choosing a migration:

```bash
cxfix path list -c know
```

Apply the path migration while preserving each thread provider:

```bash
cxfix path migrate -f '～/dev/know ' -a -y
```

Choose the replacement path explicitly:

```bash
cxfix path migrate -f '～/dev/know ' -o '~/dev/know' -a -y
```

Mount all cached plugin skills visibly into Codex:

```bash
cxfix plugins mount
```

Preview what would be mounted without writing:

```bash
cxfix plugins mount -n
```

Advanced: create missing top-level symlinks under `~/.codex/skills`:

```bash
cxfix plugins cache -a
```

Advanced: only expose one cached plugin source, such as the primary runtime
Office-style skills:

```bash
cxfix plugins cache -s openai-primary-runtime -a
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

Index and path repairs never rewrite historical thread provider labels.

When a thread has used both official OpenAI APIs and third-party routed APIs,
Codex may replay provider-specific `encrypted_content` from the older turn.
Official OpenAI endpoints can reject those payloads with errors such as
`Encrypted content could not be decrypted or parsed`. `cxfix clean` backs up
the affected rollout files and removes only the encrypted reasoning fields,
while preserving visible messages, summaries, tool calls, and ordinary content.

`cxfix path` repairs thread working-directory drift. It updates matching
`threads.cwd` rows in SQLite, rollout `session_meta.cwd` values, and exact path
values or keys in `.codex-global-state.json`, backing them up before writes.
By default, `-o` / `--to-cwd` is derived
from `-f` / `--from-cwd` by replacing a leading full-width `～` with `~`,
expanding the home directory, and stripping surrounding whitespace. The source
value is matched exactly after `~` expansion, so paths with trailing spaces must
be quoted in the shell.

Codex stores SQLite-backed state under `CODEX_HOME` by default. `cxfix`
follows Codex's precedence for the current database: top-level `sqlite_home` in
`~/.codex/config.toml`, then `CODEX_SQLITE_HOME`, then `CODEX_HOME`. Set
`sqlite_home` or `CODEX_SQLITE_HOME` only when you intentionally want to repair
a non-default state directory.

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
