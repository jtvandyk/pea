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

2. **Read `.claude/followups.md`** and parse the item table. Each item has explicit `**Effort.**` and a tier (P2 / P3) — use those to filter.

3. **Filter by time:**
   | User said | Match items where Effort ≤ |
   |---|---|
   | ≤30 min | 30 min |
   | 1–2 hrs | 2h |
   | half-day+ | any |

4. **Filter by interest:**
   | Interest | Likely items |
   |---|---|
   | CI/infra | #11 (drop `:latest`), #12 (Trivy scan), #15 (integration test in CI) |
   | extraction quality | #13 (tier-2 few-shots), #14 (UG/DZ examples), #20 (translation truncation flag) |
   | testing | #16 (dedup boundary tests), #18 (multi-domain test), #22 (annotation roundtrip test) |
   | polish | #17 (atomic checkpoint), #19/#23 (API version), #21 (jitter) |

5. **Apply the cadence sketch** at the bottom of `followups.md` as a tie-breaker. Items in this week's row of the sketch beat items from later weeks.

6. **Recommend ONE item** with:
   - Title + number
   - File paths it touches (already in the followups doc)
   - The "Why it matters" sentence
   - The blocker / signal-needed flag if any (e.g. #14 is blocked on 7 days of real data)

7. **Open the relevant files** so the user can start. Don't begin editing until they confirm.

## Decision shortcuts

- **If recall numbers from a recent validation run are below 60%**, override the user's interest filter and recommend #13 or #14 (extraction quality wins until recall is acceptable).
- **If a recent run had `degraded_modes` non-empty**, override and recommend the matching item from the troubleshooting tree (typically not in followups — point at `.claude/deploy.md` § Troubleshooting instead, and create a new followup if the issue isn't already tracked).
- **If the user says "I'm new" / "first time"**, recommend #16 (dedup boundary tests) — pure unit work, no infra needed, good calibration of the codebase.

## Items intentionally **not** to recommend

These are listed in the followups doc but are not actionable today:

- **#24 (drone codebook)** — research-prototype only, don't expand cron until ground truth.
- **#25 (QLoRA)** — defer until annotation cadence yields 200 pairs.

If the user asks specifically about either, explain the gating and offer an adjacent item (e.g. for #25 → #22 annotation roundtrip test, which moves the prerequisite forward).

## After the work is done

When the user reports the followup is complete:
1. Update `.claude/followups.md` — strike-through or remove the item.
2. Add a one-line entry under "Improvement History" in `CLAUDE.md` with the date.
3. Don't leave the item in followups marked `[done]` — the new `.claude/README.md` rule is "update or delete, don't deprecate in place."

## Related

- `.claude/followups.md` — the source of truth.
- `.claude/README.md` — the rule against in-place deprecation.
- `CLAUDE.md` § "Improvement History" — where completed items get recorded.
