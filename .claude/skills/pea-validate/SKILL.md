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
| ACLED | not yet built | Blocked on token |

## Recall thresholds

| Recall | Status |
|---|---|
| ≥ 60% | Acceptable |
| 40–60% | Investigate misses by type and country |
| < 40% | Diagnose stage-by-stage |

## Procedure

1. **Ask which dataset.** Default CEHA if available. Refuse ACLED (not built).

2. **Resolve gold dataset path** (stored outside repo):
   - CEHA: `~/datasets/CEHA/data/CEHA_dataset.csv`
   - CASE 2021: `~/datasets/CASE2021/task2/test_dataset/test_set_final_release_with_labels.tsv`
   - GLOCON: `~/datasets/glocon/data/<country>/english/`

3. **Resolve PEA output path.** Default: `data/processed/events_consolidated.jsonl`.

4. **Run the validator:**

   ```bash
   # CEHA
   venv/bin/python -m src.validation.ceha_validator \
     --ceha-csv <gold-path> --split test \
     --output data/validation/ceha_report.json

   # CASE 2021 (relevance mode)
   venv/bin/python -m src.validation.case2021_validator \
     --case-tsv <gold-path> --mode relevance \
     --output data/validation/case2021_relevance_report.json

   # GLOCON
   venv/bin/python -m src.validation.glocon_validator \
     --glocon-dir <gold-path> \
     --pea-events data/processed/events_consolidated.jsonl \
     --output data/validation/recall_report_glocon.json
   ```

5. **Score against thresholds:**
   ```bash
   jq '.overall_recall, .recall_by_type, .recall_by_country' data/validation/<report>.json
   ```

6. **If recall < 40%**, walk stage-by-stage diagnosis using `match_records` in the report.

7. **If recall ≥60%**, record in `CLAUDE.md` § "Improvement History".

## Guard rails

- **Validate against deduplicated output.**
- **CASE 2021 extraction-mode costs ~$0.50 per run.** Confirm before running.
- **Recall of 100% is suspicious** (gold set too small or matcher over-permissive).

## Related

- `CLAUDE.md` § "Validation".
- `pea-canary-run` — verify a small change before running the full validator.
