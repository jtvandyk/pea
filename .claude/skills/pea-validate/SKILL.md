---
name: pea-validate
description: Run a recall validation against gold benchmark datasets (CEHA, CASE 2021 Task 2, GLOCON when available) and report results against the project's recall thresholds. Use after a codebook change, before declaring a release ready, or when the operator wants to know "is the pipeline good enough". Triggers on phrases like "validate against gold", "check recall", "run GLOCON", "run CEHA", "run CASE 2021", "what's our recall".
---

# pea-validate

Picks the right validator for the dataset the operator has access to, runs it
against the deduplicated PEA output, and reports recall against the documented
thresholds.

## Validators available

| Dataset | Validator | Status |
|---|---|---|
| CEHA | `src/validation/ceha_validator.py` | Built, tested |
| CASE 2021 Task 2 | `src/validation/case2021_validator.py` | Built, tested |
| GLOCON | `src/validation/glocon_validator.py` | Built; data access applied 2026-04-05 |
| ACLED | not yet built | Blocked on token (per `CLAUDE.md`) |

## Recall thresholds (from `CLAUDE.md`)

| Recall | Status |
|---|---|
| ≥ 60% | Acceptable for GDELT-sourced pipeline |
| 40–60% | Investigate misses by type and country |
| < 40% | Diagnose stage-by-stage: GDELT → scraper → relevance filter → LLM |

## Procedure

1. **Ask which dataset** the operator wants to validate against. Default to
   CEHA if they have a CEHA CSV path, since it's the most recently exercised.
   Refuse ACLED — that validator isn't built yet.

2. **Resolve the gold dataset path.** Datasets are stored *outside* the repo
   (per `CLAUDE.md` validation section):
   - CEHA: `~/datasets/CEHA/data/CEHA_dataset.csv` (typical)
   - CASE 2021: `~/datasets/CASE2021/task2/test_dataset/test_set_final_release_with_labels.tsv`
   - GLOCON: `~/datasets/glocon/data/<country>/english/`

   If the path doesn't exist, ask the operator to clone the dataset first.

3. **Resolve the PEA output path.** Default to the deduplicated output for the
   cleanest recall number:
   ```
   data/processed/events_consolidated.jsonl
   ```
   If that doesn't exist, fall back to `data/raw/all_events.jsonl` and warn
   that recall will be lower because of duplicates inflating the denominator.

4. **Run the right validator:**

   **CEHA (relevance-only, no extraction):**
   ```bash
   venv/bin/python -m src.validation.ceha_validator \
     --ceha-csv <gold-path> \
     --split test \
     --output data/validation/ceha_report.json
   ```

   **CEHA threshold sweep (calibrate `--relevance-threshold` before a full run):**
   ```bash
   venv/bin/python -m src.validation.ceha_validator \
     --ceha-csv <gold-path> \
     --sweep-thresholds \
     --output data/validation/ceha_sweep.json
   ```

   **CASE 2021 Task 2 (relevance):**
   ```bash
   venv/bin/python -m src.validation.case2021_validator \
     --case-tsv <gold-path> \
     --mode relevance \
     --output data/validation/case2021_relevance_report.json
   ```

   **CASE 2021 Task 2 (extraction — costs ~$0.50 per run):**
   ```bash
   venv/bin/python -m src.validation.case2021_validator \
     --case-tsv <gold-path> \
     --mode extraction \
     --provider azure --model gpt-5.4 \
     --output data/validation/case2021_extraction_report.json
   ```
   Confirm with the operator before running extraction-mode — it hits the live
   Foundry endpoint.

   **GLOCON (recall by type + country):**
   ```bash
   venv/bin/python -m src.validation.glocon_validator \
     --glocon-dir <gold-path> \
     --pea-events data/processed/events_consolidated.jsonl \
     --output data/validation/recall_report_glocon.json
   ```

5. **Parse the JSON report and score against thresholds.** Use `jq`:
   ```bash
   jq '.overall_recall, .recall_by_type, .recall_by_country' data/validation/<report>.json
   ```

6. **Report to the operator with the threshold verdict:**

   ```
   Overall recall: <pct>% — <Acceptable / Investigate / Diagnose>
   Per-type:  <list any types below 40%>
   Per-country: <list any countries below 40%>
   ```

7. **If recall < 40%**, walk the stage-by-stage diagnosis:
   - Did the article appear in the GDELT discovery output? → check keywords config.
   - Did the scraper succeed? → check the scrape log.
   - Did the relevance filter accept it? → check `_relevance_score` in the rejected log.
   - Did the LLM extract any events? → check `failures_*.jsonl`.

   The validator JSON includes a `match_records` array (per gold event) for
   exactly this diagnosis. Don't guess — let the report drive.

8. **If recall is acceptable** (≥60%), record the result:
   - One-line entry in `CLAUDE.md` § "Improvement History".
   - Save the report path; future validations should compare against it.

## Choosing between CEHA and CASE 2021

- **CEHA** is purely relevance — does the pipeline correctly classify
  protest-vs-non-protest? Use this to tune `--relevance-threshold`.
- **CASE 2021** has both relevance and extraction modes — use relevance
  mode for filter calibration, extraction mode for end-to-end recall on
  event-type assignment.
- **GLOCON** is the most expensive but most realistic — it's African
  protest events with full structured fields. Use when GLOCON access is live.

## Guard rails

- **Validate against the deduplicated output**, not the raw output. Duplicates
  inflate the denominator and depress recall artificially.
- **Don't use validation results from a different `--days` window** as a
  baseline. The gold set must overlap the PEA run's date range.
- **CASE 2021 extraction-mode costs real money.** Don't run it on every
  iteration; reserve for release-ready checks.
- **Recall of 100% is suspicious** — usually means the gold set is too small
  (n<30) or the matcher is over-permissive. Inspect `match_records`.

## Related

- `CLAUDE.md` § "Validation" — recall thresholds and dataset paths.
- `.claude/followups.md` #15 — integration test in CI (would automate this).
- `pea-canary-run` — verify a small change before running the full validator.
