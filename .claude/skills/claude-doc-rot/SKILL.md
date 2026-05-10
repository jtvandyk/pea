---
name: claude-doc-rot
description: Audit `.claude/` documentation for staleness — flag any *.md missing the `Last reviewed:` line or with a date older than the configured window. Enforces the "update or delete, don't deprecate in place" rule from .claude/README.md so the directory doesn't accumulate the kind of stale guides that consolidation just removed. Triggers on phrases like "audit .claude docs", "are these docs stale", "doc rot check", "review the .claude folder".
---

# claude-doc-rot

Scans `.claude/*.md` and `.claude/skills/*/SKILL.md` for the
`> Last reviewed: YYYY-MM-DD` header convention and flags anything missing
or older than N days.

## Default staleness windows

| Doc class | Stale threshold |
|---|---|
| `.claude/deploy.md` | 30 days |
| `.claude/followups.md` | 14 days |
| `.claude/skills/*/SKILL.md` | 60 days |
| Any other `.claude/*.md` | 60 days |

## Procedure

1. **Find all candidate docs:**
   ```bash
   find .claude -name "*.md" -type f
   ```

2. **Extract `Last reviewed` dates:**
   ```bash
   for f in $(find .claude -name "*.md" -type f); do
     date_line=$(grep -m1 "^> Last reviewed:" "$f" || echo "")
     echo "$f|$date_line"
   done
   ```

3. **Build the rot report** (MISSING / STALE / OK) and surface it grouped.

4. **For MISSING entries:** read the file, judge if current; if yes add the date line, if not propose deletion.

5. **For STALE entries:** read and review; if still accurate bump the date; if not fix + bump in the same commit.

6. **Commit** with: `.claude/ rot pass: review N docs, delete M, refresh K dates`

## Optional: lint frontmatter

```bash
for f in .claude/skills/*/SKILL.md; do
  head -10 "$f" | grep -q "^name:" || echo "MISSING name: $f"
  head -10 "$f" | grep -q "^description:" || echo "MISSING description: $f"
done
```

## Guard rails

- **Don't auto-bump dates.** Human review required.
- **Don't auto-delete.** Propose, confirm, then commit.
- **Don't add stub redirect files** for deleted docs.

## Related

- `.claude/README.md` § "Rules to keep this from rotting".
- `pea-followup-pick` — substantial refresh work can become a followup item.
