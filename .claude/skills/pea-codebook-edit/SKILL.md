---
name: pea-codebook-edit
description: Safely edit the protest codebook (or any domain codebook) and verify the change before committing. Use when the user wants to add a non-event disqualifier, tweak an event-type definition, expand the African-context list, add decision rules, or bump the codebook version. Triggers on phrases like "edit the codebook", "add a disqualifier", "tune extraction rules", "bump codebook version".
---

# pea-codebook-edit

Encodes the safe procedure for editing `configs/<domain>_codebook.yaml` so changes don't silently degrade extraction.

## When to use

- Adding negative examples, decision rules, or African-context patterns.
- Tightening the `disqualify_immediately` list.
- Bumping the codebook version (header `version: X.Y`).
- Anything in `configs/protest_codebook.yaml`, `drone_events_codebook.yaml`, or `violent_extremism_codebook.yaml`.

## Procedure

1. **Identify the target codebook** by domain. Default is `configs/protest_codebook.yaml`. For drone or VE work, pick the matching file — but warn the user that drone/VE are research-prototype (per `CLAUDE.md` and followup #24).

2. **Show the relevant section before editing.** Read the YAML, locate the section the user wants to change, surface the current contents. Don't blind-edit.

3. **Edit with the structural rules in mind:**
   - Each event type needs `definition`, `positive_examples`, `negative_examples`, `decision_rules`.
   - Negative examples should be the boundary cases that are most likely to be misclassified — pick from the table in the old improvement-guide / deleted improvement-guide if needed.
   - Don't paraphrase — quote concrete patterns ("Police fired rubber bullets at an otherwise peaceful crowd") so the LLM has lexical signal.
   - YAML must remain parseable: watch for unquoted colons, multiline strings, indentation drift.

4. **Bump `version:` in the file header** if the change is semantically meaningful (new event type, new disqualifier category). Patch-level edits (one extra example) don't need a bump but can have one.

5. **Validate the YAML loads:**

   ```bash
   venv/bin/python -c "import yaml; yaml.safe_load(open('configs/protest_codebook.yaml'))"
   ```

6. **Sanity-check token budget.** Codebook injection is the dominant input-token cost. After a large addition, get a rough character count and divide by 4:

   ```bash
   venv/bin/python -c "
   import yaml
   text = yaml.dump(yaml.safe_load(open('configs/protest_codebook.yaml')))
   print(f'codebook tokens (rough): {len(text)//4}')
   "
   ```

   Per `CLAUDE.md`, the documented budget is ~22k tokens for the codebook context. If the new value is >25k, raise it with the user before merging — every article in the run pays this cost.

7. **Run the canary** to verify direction. Invoke the `pea-canary-run` skill, or:

   ```bash
   venv/bin/python -m src.acquisition.pipeline \
     --provider azure --countries ZA --days 14 --max-articles 30
   python scripts/compare_runs.py data/raw/summary_<new_run_id>.json
   ```

8. **Read deltas the same way `pea-canary-run` does.** Specifically for codebook edits:
   - Disqualifier additions should *decrease* `total_events` and *increase* `events_by_confidence.high`.
   - New positive examples should *increase* `total_events` and may shift `events_by_type` toward the affected type.
   - Decision-rule edits should reduce same-day same-type collisions in `events_by_country`.

9. **Update `CLAUDE.md` improvement history** with a one-line entry under the dated table if the change is meaningful.

10. **Commit** with a message that names the change (e.g. "codebook v2.4: add cultural-festival disqualifier").

## Guard rails

- **Don't pre-commit untested codebook changes.** The pre-commit hook (`.claude/settings.json`) only checks formatting, not semantics. Always run step 7.
- **Don't mass-edit across all 8 event types in one commit.** One type at a time keeps deltas attributable.
- **Don't add `african_context` rules that overlap `disqualify_immediately`** — duplication wastes tokens and can confuse the LLM.

## Related

- `pea-canary-run` — the verification step.
- `pea-few-shot-add` — for changes that need a worked example, not a rule.
- `CLAUDE.md` § "Extraction Quality Architecture" — what the LLM actually sees.
