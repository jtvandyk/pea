---
name: pea-followup-pick
description: Help the user pick the next P2/P3 follow-up item from .claude/followups.md given their available time and context. Use when the user has bandwidth and wants the highest-impact next thing to work on, or when starting a new session and looking for the next chunk. Triggers on phrases like "what should I work on", "pick a followup", "next P2 item", "what's queued", "anything to do".
---

# pea-followup-pick

Reads `.claude/followups.md`, asks for time available + interest area, recommends the best-fit item, and loads its file paths into context so the user can start immediately.

## When to use

- Start of a coding session with no specific task in mind.
- Between deploy phases or after a canary run, when there's a 1–2 hour gap.
- The user explicitly asks for "the next thing".

## Procedure

1. **Ask the user two things** (use `AskUserQuestion`):
   - Time available (≤30 min / 1–2 hrs / half-day+)
   - Interest area: CI/infra / extraction quality / testing / polish

2. **Read `.claude/followups.md`** and parse the item table.

3. **Filter by time and interest**, applying the cadence sketch at the bottom as a tie-breaker.

4. **Recommend ONE item** with: title + number, file paths, "Why it matters", and any blocker/signal-needed flag.

5. **Open the relevant files** so the user can start. Don't begin editing until they confirm.

## Decision shortcuts

- **If recall < 60%**, override interest filter and recommend #13 or #14.
- **If `degraded_modes` non-empty**, point at `.claude/deploy.md` § Troubleshooting.
- **If "I'm new"**, recommend #16 (dedup boundary tests) — pure unit work, good calibration.

## Items intentionally **not** to recommend

- **#24 (drone codebook)** — research-prototype only.
- **#25 (QLoRA)** — defer until annotation cadence yields 200 pairs.

## After the work is done

1. Update `.claude/followups.md` — remove the item.
2. Add a one-line entry under "Improvement History" in `CLAUDE.md`.
3. Don't leave items marked `[done]` — update or delete.

## Related

- `.claude/followups.md` — the source of truth.
- `.claude/README.md` — the rule against in-place deprecation.
- `CLAUDE.md` § "Improvement History".
