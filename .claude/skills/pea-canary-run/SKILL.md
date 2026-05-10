---
name: pea-canary-run
description: Run a small canary pass of the PEA pipeline and diff its summary against the previous run. Use after editing the codebook, the few-shot examples, the relevance filter, or any extraction prompt — i.e. whenever you want a fast, cheap signal that a change moved metrics in the right direction. Triggers on phrases like "canary run", "small pipeline test", "diff the last run", "did my codebook change help".
---

# pea-canary-run

The documented codebook-tuning loop: run a small extraction, compare the new summary to the prior baseline, decide whether to keep the change.

## When to use

- Just edited `configs/protest_codebook.yaml` or `configs/extraction_examples.yaml`.
- Just touched `src/acquisition/extractor.py` or the relevance filter.
- Need a sanity check before a wider run / before merging a PR.

**Do not use** for full operational runs — this is intentionally tiny (~30 articles, single country) so cost is bounded and feedback is fast.

## Procedure

1. **Confirm working tree is clean enough to attribute deltas to a single change.** If multiple unstaged edits exist, ask the user to stash or stage so the diff is interpretable.

2. **Run the canary** (default args — adjust only if the user asks):

   ```bash
   venv/bin/python -m src.acquisition.pipeline \
     --provider azure \
     --countries ZA \
     --days 14 \
     --max-articles 30
   ```

   Capture the new `run_id` from the log (`Run ID: <run_id>`) — it's the suffix of the `summary_*.json` file written to `data/raw/`.

3. **Diff against the prior baseline** using the existing helper:

   ```bash
   python scripts/compare_runs.py data/raw/summary_<new_run_id>.json
   ```

   With no second argument it diffs against the saved baseline. To reset the baseline after a change you want to keep:

   ```bash
   python scripts/compare_runs.py --set-baseline data/raw/summary_<new_run_id>.json
   ```

4. **Read the deltas with the right expectations:**

   | Direction | Likely cause |
   |---|---|
   | `total_events` ↑, `failures` flat | Codebook recall improvement — keep |
   | `total_events` ↓, `events_by_confidence.high` ↑ | Better disqualification — keep |
   | `total_events` ↓, `failures` ↑ | Prompt change broke parsing — investigate `failures_*.jsonl` |
   | `degraded_modes` non-empty | Infra problem, not a codebook problem — see `pea-degraded-mode` |

5. **Surface the verdict to the user in 2–3 lines.** Don't paste the full diff unless asked; pick the 2–3 fields that moved most.

## Guard rails

- **Cost.** A canary is ~30 articles × ~40k input tokens ≈ 1.2M input tokens. Cheap, but don't chain canaries in a loop without telling the user.
- **Determinism.** GDELT returns a different article set per run, so small `total_events` deltas are noise. Treat ≥20% delta as signal, anything smaller as inconclusive.
- **Don't commit `data/raw/` artefacts.** They're git-ignored; if the user asks you to commit results, copy the relevant lines into the commit message instead.

## Related

- `.claude/deploy.md` — production runs (different scale, different gating).
- `pea-codebook-edit` skill — wraps this canary into a fuller edit-then-verify loop.
