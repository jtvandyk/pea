# `.claude/` — Index

Working notes that supplement [`CLAUDE.md`](../CLAUDE.md). Read this index
first; it tells you which file is current, which is reference-only, and
when each was last reviewed. If a file isn't listed here, it shouldn't be
trusted — delete it or add it to the table.

## Files

| File | Purpose | When to read | Last reviewed |
|---|---|---|---|
| [`deploy.md`](deploy.md) | End-to-end Azure deploy playbook (provision → push → deploy → smoke → first run → hardening). Includes operations runbook, rollback, and troubleshooting. | Deploy day, rollbacks, on-call investigation. | 2026-05-10 |
| [`followups.md`](followups.md) | Working list of P2/P3 follow-up items with file paths, approach, and effort estimates. | Picking the next chunk of hardening work. | 2026-05-10 |
| [`settings.json`](settings.json) | Pre-commit hook config (runs `black --check` + `flake8` before any `git commit`). | Editing local Claude Code behavior. | — |

## Rules to keep this from rotting

1. **One source of truth per topic.** `CLAUDE.md` is the project context.
   `deploy.md` is the deploy runbook. `followups.md` is the work queue.
   Anything else is suspect.
2. **Date every doc.** New `.claude/*.md` files must carry a
   `> Last reviewed: YYYY-MM-DD` line directly under the H1.
3. **Update or delete — don't deprecate in place.** If guidance is
   superseded, delete the file and update this index in the same commit.
   Stub "see other doc" files (like the old `implementation-guide.md`)
   become a second source of stale truth and get read by Claude as if
   they were current.
4. **Cross-reference by relative path** (e.g. `deploy.md`, not
   `.claude/deploy.md`) when linking from inside `.claude/`. Use the
   `.claude/`-prefixed form from `CLAUDE.md` and `README.md`.
