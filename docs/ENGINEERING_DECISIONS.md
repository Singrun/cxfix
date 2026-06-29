# Engineering Decisions

## 001. Keep Python as the Implementation Base

Status: accepted

`cxfix` should stay on Python for the next engineering phase.

Reasons:

- The tool works directly with local files, JSONL rollout history, SQLite, and
  shell commands. Python's standard library is a strong fit for these tasks.
- The current install path is simple: copy one executable script and add a zsh
  alias.
- Repair tools need readability and auditability more than raw performance.
- Python makes it easy to build fixtures for Codex homes, SQLite schemas,
  rollout files, and provider config variants.
- The current user base is macOS-focused, where Python is already an acceptable
  operational dependency for this project.

Tradeoffs:

- Packaging a single binary would be easier with Rust or Go.
- Static typing and command structuring would be stronger with a compiled
  implementation.
- Large rollout scans can be slower in Python, although this is manageable with
  streaming JSONL reads.

Decision:

- Keep Python.
- Move from a single script into a package with small modules.
- Stay dependency-light and prefer the standard library.
- Reconsider Rust or Go only if single-binary distribution, Windows/Linux parity,
  or performance on very large Codex homes becomes a primary requirement.

Near-term implication:

- `codex_history_repair.py` remains a compatibility entrypoint.
- New code goes under the `cxfix/` package.
- The next foundation modules are `core.codex_home`, `core.config`,
  `core.doctor`, `core.sqlite_store`, and `reports.manifest`.
