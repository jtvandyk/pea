---
name: pea-annotation-batch
description: Run one full Label Studio annotation cycle — export prioritised tasks, prompt the operator to annotate in the LS UI, then import the corrections back into reviewed_events.jsonl + training_data.jsonl. Use after each pipeline run to advance the active-learning loop toward the 200-pair fine-tuning threshold. Triggers on phrases like "export annotation tasks", "import label studio", "annotation roundtrip", "training pairs", "active learning batch".
---

# pea-annotation-batch

The per-batch annotation workflow from `CLAUDE.md` § "Annotation / Active
Learning Workflow". One cycle: export → human annotates in LS → import.

## Prerequisites (one-time setup, see `CLAUDE.md`)

- Label Studio running at http://localhost:8080 (`docker compose -f docker-compose.annotation.yml up -d`).
- Project "PEA Protest Events" created with the labeling interface from `src/annotation/labeling_config.xml` pasted into Settings → Labeling Interface → Code.

If either is missing, halt and tell the operator to do the one-time setup first. Don't try to bootstrap LS from this skill.

## When to use

- After each pipeline run, when the operator has 30–60 min for annotation.
- When `annotation_stats.json` shows progress toward the 200-pair threshold.
- Before running another fine-tuning experiment (downstream of #25).

## Procedure

1. **Confirm there are events to annotate.** Default source is the
   cumulative file:
   ```bash
   wc -l data/raw/all_events.jsonl
   ```
   If <50, ask the operator if they want to wait until more events accumulate.

2. **Export prioritised tasks.** Default args (Tier 1 + Tier 2 only — those
   are the ones with measurable F1 lift per annotation hour, per `CLAUDE.md`):
   ```bash
   venv/bin/python -m src.annotation.export_for_annotation \
     --events data/raw/all_events.jsonl \
     --output data/annotation/tasks_$(date +%Y%m%d).json \
     --max-tasks 50 \
     --tiers 1,2
   ```

   Add `--sample-rate 0.1` to also include a 10% Tier-3 spot-check batch
   for precision monitoring.

3. **Surface the export summary** to the operator:
   ```bash
   jq 'length' data/annotation/tasks_*.json     # total task count
   jq '.[].priority_tier' data/annotation/tasks_*.json | sort | uniq -c
   ```

4. **Tell the operator the LS workflow** (don't try to drive it from this skill):
   - Open http://localhost:8080
   - Project → Import → upload `data/annotation/tasks_<date>.json`
   - Annotate each task — for each:
     1. Is this a genuine protest event?
     2. Correct event type if wrong.
     3. Correct confidence if wrong.
     4. Flag extraction errors if any.
   - Project → Export → JSON → save to `data/annotation/label_studio_export.json`

5. **Wait for the operator to confirm** the export file exists. Don't
   proceed until they say "done" or paste the file path.

6. **Import the corrections back:**
   ```bash
   venv/bin/python -m src.annotation.import_annotations \
     --annotations data/annotation/label_studio_export.json \
     --output-dir data/annotation/
   ```

   To also promote high-quality corrections into the few-shot examples file:
   ```bash
   venv/bin/python -m src.annotation.import_annotations \
     --annotations data/annotation/label_studio_export.json \
     --output-dir data/annotation/ \
     --promote-to-examples \
     --examples-path configs/extraction_examples.yaml
   ```
   Confirm with the operator before promotion — it edits a tracked config
   file. If they accept, then run `pea-canary-run` afterwards to verify.

7. **Surface the resulting stats:**
   ```bash
   jq . data/annotation/annotation_stats.json
   wc -l data/annotation/reviewed_events.jsonl data/annotation/training_data.jsonl
   ```

   The console output of `import_annotations` already prints the running
   count toward the 200-pair fine-tuning threshold — surface that line
   verbatim.

8. **If the cycle uncovers a recurring misclassification pattern**, propose
   creating a few-shot example via the `pea-few-shot-add` skill rather than
   relying solely on more annotation.

## Tier reference (from `CLAUDE.md`)

| Tier | Condition | Annotate-first because… |
|---|---|---|
| 1 | Low confidence + high relevance score | Uncertain but probably real — highest misclassification risk |
| 2 | Medium confidence | Borderline — most F1 improvement per hour |
| 3 | High confidence (10% sample) | Precision monitoring only |

## Guard rails

- **Don't auto-import without operator confirmation.** Imports modify
  `reviewed_events.jsonl` and `training_data.jsonl`; partial / mistaken
  exports from LS would otherwise corrupt the gold set.
- **Don't promote to `extraction_examples.yaml` without `pea-canary-run`
  afterwards.** Examples are loaded into every prompt — a bad promotion
  affects every future extraction.
- **Don't skip Tier-3 spot checks** for more than 3 cycles in a row. They're
  the only way to catch precision regressions in high-confidence outputs.
- **The 200-pair threshold is a *minimum*, not a target.** Don't fine-tune
  the moment the count hits 200; per `CLAUDE.md` and followup #25, also
  require ≥40 gold examples per event type and a held-out test month.

## Related

- `CLAUDE.md` § "Annotation / Active Learning Workflow" — the documented loop.
- `.claude/followups.md` #22 — annotation roundtrip test (would catch
  breakage in this skill before the operator hits it).
- `.claude/followups.md` #25 — QLoRA fine-tuning prep (downstream consumer
  of `training_data.jsonl`).
- `pea-few-shot-add` — alternative to annotation when the pattern is clear.
