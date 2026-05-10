---
name: claude-doc-rot
description: Audit `.claude/` documentation for staleness — flag any *.md missing the `Last reviewed:` line or with a date older than the configured window. Enforces the "update or delete, don't deprecate in place" rule from .claude/README.md so the directory doesn't accumulate the kind of stale guides that consolidation just removed. Triggers on phrases like "audit .claude docs", "are these docs stale", "doc rot check", "review the .claude folder".
---

# claude-doc-rot

Scans `.claude/*.md` and `.claude/skills/*/SKILL.md` for the
`> Last reviewed: YYYY-MM-DD` header convention introduced in the
consolidation pass, and flags anything missing or older than N days.

## Why this exists

Before consolidation, `.claude/` held both current (`deploy.md`, `followups.md`)
and stale (`improvement-guide.md` describing already-done work) docs.
Stale docs got read by Claude as if current and produced wrong guidance.
The fix was a "delete or update; don't stub" rule plus per-doc dates.
This skill checks that rule is being honoured.

## When to use

- Quarterly hygiene pass.
- Before a deploy (deploy.md should be the most recently reviewed doc).
- After any consolidation work, to verify nothing slipped through.
- When Claude gives advice from a `.claude/` doc that the operator says
  is wrong — usually means that doc has rotted.

## Default staleness windows

| Doc class | Stale threshold | Why |
|---|---|---|
| `.claude/deploy.md` | 30 days | Deploy steps drift fast — Azure surface area changes |
| `.claude/followups.md` | 14 days | Work queue should reflect current priorities |
| `.claude/skills/*/SKILL.md` | 60 days | Procedures change less often, but reviewer signal still useful |
| Any other `.claude/*.md` | 60 days | Default for new docs |

These are defaults — override per-run if the operator wants stricter.

## Procedure

1. **Find all candidate docs:**
   ```bash
   find .claude -name "*.md" -type f
   ```

2. **For each file, extract the `Last reviewed` line and parse the date:**
   ```bash
   for f in $(find .claude -name "*.md" -type f); do
     date_line=$(grep -m1 "^> Last reviewed:" "$f" || echo "")
     echo "$f|$date_line"
   done
   ```

3. **Build the rot report.** For each file:
   - `MISSING` → no `Last reviewed:` line.
   - `STALE: <date> (<n> days old)` → date older than threshold.
   - `OK` → present and within window.

4. **Surface the report to the user, grouped:**
   ```
   MISSING (n=X):
     - .claude/<file>
     ...

   STALE (n=Y):
     - .claude/<file>: 47 days old (threshold 30)
     ...

   OK (n=Z): <count only, don't list>
   ```

5. **For each MISSING entry, propose:**
   - Read the file, judge if it's still current.
   - If current: add the `> Last reviewed: YYYY-MM-DD` line below the H1
     and propose a commit.
   - If not current: propose deletion (per the "update or delete" rule —
     do **not** propose adding a stub redirect, that's the failure mode
     consolidation removed).

6. **For each STALE entry, propose:**
   - Read the file.
   - Ask the user: still accurate? If yes, just bump the date. If parts
     are wrong, edit those parts and bump the date in the same commit.
   - Don't bump the date without a real review — that defeats the
     mechanism.

7. **Commit the result** with a message like:
   ```
   .claude/ rot pass: review N docs, delete M, refresh K dates
   ```

## What counts as a "review"

Bumping the date implies the reviewer:
1. Read the doc top to bottom.
2. Confirmed every command / file path / version still resolves.
3. Confirmed no new section is needed (e.g. a new troubleshooting case
   the team has hit since the last review).

Not "the file looks fine" — actual cross-check. If you don't have time
for the cross-check, don't bump the date.

## Edge cases

- **`.claude/README.md` itself** — the index doc. Should always have a
  `Last reviewed` line. If it's stale, refresh it last (since the index
  changes whenever any other doc is added/removed).
- **`.claude/settings.json`** — not markdown; skip.
- **Archived docs** — there shouldn't be any. The consolidation rule is
  delete, not archive. If you find one, propose deletion.
- **SKILL.md without frontmatter `description`** — broken skill (won't
  surface to Claude). Flag separately from the rot check.

## Optional: lint frontmatter

While scanning, also verify each `SKILL.md` has the required frontmatter
keys (`name`, `description`):

```bash
for f in .claude/skills/*/SKILL.md; do
  if ! head -10 "$f" | grep -q "^name:"; then
    echo "MISSING name: $f"
  fi
  if ! head -10 "$f" | grep -q "^description:"; then
    echo "MISSING description: $f"
  fi
done
```

A broken frontmatter is worse than a stale date — Claude can't surface
the skill at all.

## Guard rails

- **Don't auto-bump dates.** The whole point is human review.
- **Don't auto-delete.** Deletion is reversible in git, but breaking a
  workflow because the doc was "stale" but actually the only source of
  truth would be embarrassing. Propose, get confirmation, then commit.
- **Don't propose adding stub redirect files** for deleted docs. The
  consolidation removed exactly those (`implementation-guide.md`).
- **Don't expand the threshold table** without operator agreement.
  Looser thresholds defeat the mechanism.

## Related

- `.claude/README.md` § "Rules to keep this from rotting" — the contract
  this skill enforces.
- The consolidation commit (`f1d97cb`) removed the original stale docs —
  this skill prevents new ones accumulating.
- `pea-followup-pick` — once rot is found, refreshes can become followup
  items if they're substantial.
