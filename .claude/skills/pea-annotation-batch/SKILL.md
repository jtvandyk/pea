---
name: pea-annotation-batch
description: Run one full Label Studio annotation cycle — export prioritised tasks, prompt the operator to annotate in the LS UI, then import the corrections back into reviewed_events.jsonl + training_data.jsonl. Use after each pipeline run to advance the active-learning loop toward the 200-pair fine-tuning threshold. Triggers on phrases like "export annotation tasks", "import label studio", "annotation roundtrip", "training pairs", "active learning batch".
---

# pea-annotation-batch

The per-batch annotation workflow from `CLAUDE.md` § "Annotation / Active
Learning Workflow". One cycle: export → human annotates in LS → import.

## Prerequisites

- Label Studio running at http://localhost:8080.
- Project "PEA Protest Events" created with `src/annotation/labeling_config.xml`.

## When to use

- After each pipeline run, when the operator has 30–60 min for annotation.
- When `annotation_stats.json` shows progress toward the 200-pair threshold.

## Procedure

1. **Confirm events exist:** `wc -l data/raw/all_events.jsonl`

2. **Export:**
   ```bash
   venv/bin/python -m src.annotation.export_for_annotation \
     --events data/raw/all_events.jsonl \
     --output data/annotation/tasks_$(date +%Y%m%d).json \
     --max-tasks 50 --tiers 1,2
   ```

3. **Tell the operator the LS workflow** (import JSON → annotate → export JSON).

4. **Wait for confirmation** before importing.

5. **Import:**
   ```bash
   venv/bin/python -m src.annotation.import_annotations \
     --annotations data/annotation/label_studio_export.json \
     --output-dir data/annotation/
   ```

6. **Surface stats:** `jq . data/annotation/annotation_stats.json`

7. **If a recurring misclassification pattern emerges**, propose `pea-few-shot-add`.

## Guard rails

- **Don't auto-import without operator confirmation.**
- **Don't promote to `extraction_examples.yaml` without `pea-canary-run` afterwards.**
- **Don't skip Tier-3 spot checks** for more than 3 cycles in a row.
- **200 pairs is a minimum, not a target.** Also require ≥40 gold per event type and a held-out test month.

## Related

- `CLAUDE.md` § "Annotation / Active Learning Workflow".
- `pea-few-shot-add` — alternative to annotation when the pattern is clear.
