# cxfix Engineering Roadmap

`cxfix` should become a safe local toolchain for diagnosing and repairing Codex
state. Its job is not to replace the official Codex CLI. Its job is to add a
reversible repair layer around local files, SQLite state, rollout history,
provider metadata, plugin cache exposure, and configuration drift.

## Product Boundary

`cxfix` owns local recovery workflows that need backups, state comparison, and
repeatable verification:

- Diagnose Codex home layout, active config, SQLite state, sessions, archived
  sessions, plugins, MCP definitions, and provider consistency.
- Repair thread inventory mismatches between rollout files and `state_5.sqlite`.
- Repair provider labels and provider-specific rollout fields when switching
  between official and routed providers.
- Repair plugin skill visibility without modifying plugin cache sources.
- Prepare safe manifests that explain what changed and how to roll back.

`cxfix` should delegate to official Codex commands when they are the supported
surface:

- Use `codex doctor --json` as a preflight evidence source.
- Use `codex plugin` and `codex mcp` output for inventory checks where possible.
- Use Codex's own backfill behavior instead of reimplementing full session
  indexing.

## Safety Contract

Every mutating command must follow the same contract:

1. Discover the active `CODEX_HOME` and SQLite home.
2. Refuse to run while Codex Desktop or active app-server processes can write
   the same state.
3. Run read-only diagnostics first.
4. Create a backup before mutation.
5. Apply the narrowest repair.
6. Verify the repaired invariant.
7. Write a machine-readable manifest next to the backup.

Dry-run mode should be available for every repair command. Repair code should
never print or persist secrets from config, auth files, keychain rows, or
provider API keys.

## Target Architecture

The current single-file script should be split without changing user-visible
behavior first.

```text
cxfix/
  __init__.py
  cli.py
  core/
    backup.py
    codex_cli.py
    codex_home.py
    config.py
    doctor.py
    process_guard.py
    sqlite_store.py
  repairs/
    encrypted_content.py
    plugins.py
    providers.py
    threads.py
  reports/
    manifest.py
install.py
tests/
```

Suggested module responsibilities:

- `core.codex_home`: path resolution for `CODEX_HOME`, `CODEX_SQLITE_HOME`,
  configured `sqlite_home`, sessions, archives, logs, skills, plugins, and
  backup roots.
- `core.config`: TOML parsing, redaction, config/profile/provider inventory, and
  detection of project-local keys that Codex ignores.
- `core.doctor`: wrapper for `codex doctor --json`, normalized into cxfix issue
  records.
- `core.sqlite_store`: schema detection, integrity checks, read-only inventory,
  and transaction helpers.
- `core.process_guard`: active writer detection and app-server cleanup.
- `repairs.threads`: backfill state, rollout/database parity, visibility fields,
  archive flags, and recency fields.
- `repairs.providers`: provider normalization, profile/provider consistency, and
  provider reachability evidence.
- `repairs.encrypted_content`: provider-specific reasoning payload cleanup.
- `repairs.plugins`: cached plugin skill discovery and visible mount management.
- `reports.manifest`: stable JSON manifests for backup, action, verification, and
  rollback metadata.

## Command Shape

Keep existing commands as compatibility aliases, but introduce explicit
subcommands:

```text
cxfix diagnose [--json] [--all-homes]
cxfix repair threads [--all-homes] [--prepare-only]
cxfix repair providers [--target-provider NAME|--preserve-providers]
cxfix repair encrypted [--all-homes]
cxfix repair plugins [--apply|--dry-run] [--visible-mounts]
cxfix doctor [--json]
cxfix plan [--json]
```

Compatibility mapping:

- `cxfix current` -> `cxfix repair threads`
- `cxfix all` -> `cxfix repair threads --all-homes`
- `cxfix e` -> `cxfix repair encrypted`
- `cxfix p` / `cxfix plugins` -> `cxfix repair plugins --visible-mounts`

## Milestones

### Milestone 1: Stabilize Current Script

- Preserve the current CLI behavior.
- Keep the provider target and encrypted-content repairs.
- Add `docs/ROADMAP.md`.
- Keep unit tests and compile checks green.
- Commit the current working tree to remove ambiguous dirty state.

Exit criteria:

- `python3 -m unittest discover -s tests -v` passes.
- `python3 -m py_compile codex_history_repair.py install.py` passes.
- `git diff --check` passes.
- `git status --short` is clean after commit.

### Milestone 2: Extract Core Context

- Introduce a `cxfix` package.
- Move path resolution into `core.codex_home`.
- Remove module-load global path decisions where tests need alternate homes.
- Keep the old `codex_history_repair.py` as a thin compatibility entrypoint.

Exit criteria:

- Existing commands produce the same output shape.
- Tests can construct isolated fake Codex homes without environment leakage.

### Milestone 3: Diagnostic First

- Add `cxfix diagnose`.
- Parse `codex doctor --json` when available.
- Add local diagnostics for rollout/database parity, provider inventory, plugin
  cache visibility, and config/profile drift.
- Redact secrets by default.

Exit criteria:

- Diagnose can run without mutating files.
- Diagnose returns stable issue codes that repair commands can consume.

### Milestone 4: Repair Engine

- Implement shared repair planning.
- Make every repair support dry-run, backup, apply, verify, and manifest.
- Use issue codes from `diagnose` to decide recommended repairs.

Exit criteria:

- Repair commands are composable.
- Manifest records preflight, changed files, changed database rows, verification,
  and rollback hints.

### Milestone 5: Complete Codex Toolchain

- Add higher-level `cxfix plan` to recommend a repair sequence.
- Add provider/profile consistency checks beyond label normalization.
- Add keychain/auth diagnostics that report structure and reachability without
  exposing credentials.
- Add fixtures for multiple Codex CLI versions and schema variants.

Exit criteria:

- A user can run `cxfix diagnose`, review the plan, run targeted repairs, and
  verify the final state without needing to inspect SQLite manually.

## Near-Term Engineering Tasks

1. Commit the current validated repairs.
2. Create the package skeleton and move pure helpers first.
3. Add tests around path resolution, doctor JSON parsing, and manifest writing.
4. Introduce `cxfix diagnose --json` before adding more repair mutations.
5. Convert old scopes into aliases after the new command parser is stable.

## Non-Goals

- Do not clone private thread content into remote services.
- Do not rewrite full rollout semantics when Codex can backfill them.
- Do not store API keys, auth tokens, keychain secrets, or private message
  content in manifests.
- Do not make project-local config override machine-local provider/auth fields
  that Codex itself ignores.
