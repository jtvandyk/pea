---
name: pea-degraded-mode
description: Diagnose a non-empty `degraded_modes` array from a PEA run summary and propose the fix. Use when a run completes but a summary_*.json shows degraded_modes is non-empty, when the operator says "the relevance filter ran in keyword mode" or "the run uploaded but with warnings". Triggers on phrases like "degraded mode", "keyword fallback", "relevance filter degraded", "what does this degraded_modes mean".
---

# pea-degraded-mode

Maps `degraded_modes` entries from a `summary_*.json` to the matching root cause + fix in `.claude/deploy.md` § Troubleshooting.

## When to use

- A run produced output but `summary["degraded_modes"]` is non-empty.
- The operator pasted a `summary_*.json` and is asking what's wrong.
- A monitoring alert fired with "degraded" in the message.

## What `degraded_modes` means (general)

Tagged by stages that completed but in a fallback path. **Output is still
usable** in degraded mode — the run isn't a failure, but precision/recall
may be lower than the configured settings imply. Don't treat this as
stop-the-line; do treat it as fix-within-a-day.

## Procedure

1. **Get the summary.** Either:
   - User pasted it inline → parse from the message.
   - Path on disk → `cat data/raw/summary_<run_id>.json | jq .degraded_modes`.
   - Path in ADLS → `az storage fs file download ... | jq .degraded_modes`.

2. **For each entry in the array, look it up below** and surface the cause + fix.

3. **If multiple entries**, fix the most upstream one first — downstream degradations often resolve once the upstream issue is fixed.

4. **Don't promise a fix worked** until the next run shows an empty `degraded_modes`. Ask the user to re-run the canary (skill: `pea-canary-run`) after applying any fix.

## Known degraded-mode entries

### `relevance_filter:keyword_fallback`

**What happened.** DeBERTa NLI model (`cross-encoder/nli-deberta-v3-small`) failed to load; relevance filter fell back to keyword matching from `configs/keywords.yaml`.

**Root causes:**
1. Container has no internet (corporate proxy / locked-down VNet) and can't pull from HuggingFace on first run.
2. Memory pressure killed the model during loading.
3. `transformers` not installed — check `requirements-core.txt` and the Dockerfile.

**Fixes:**
- **Bake the model into the image at build time:** add to `Dockerfile`:
  ```
  RUN python -c "from transformers import pipeline; pipeline('zero-shot-classification', model='cross-encoder/nli-deberta-v3-small')"
  ```
- **Bump CPU/memory:** `az containerapp job update --name pea-daily --cpu 4 --memory 8Gi`.
- **Verify locally** with a one-off:
  ```bash
  venv/bin/python -c "from src.acquisition.relevance_filter import RelevanceFilter; rf = RelevanceFilter(); print(rf.mode)"
  ```
  Should print `nli`, not `keyword`.

### `cloud_upload:partial_failure`

**What happened.** One or more output files (events_*.jsonl, csv, summary) failed to upload to ADLS but the run continued. The B3 fix re-raises on *final* upload failure, so this entry only appears for *partial* failures.

**Root causes:**
1. Managed identity missing `Storage Blob Data Contributor` on the storage account.
2. ADLS firewall blocks the Container App's egress IP.
3. Transient throttling on the storage account.

**Fixes:**
- Confirm role assignment:
  ```bash
  az role assignment list \
    --assignee $(az identity show --name pea-identity \
                  --resource-group pea-rg --query principalId -o tsv) \
    --scope $(az storage account show --name $STORAGE_ACCOUNT \
                --resource-group pea-rg --query id -o tsv) \
    -o table
  ```
  Should include `Storage Blob Data Contributor`. If missing, add it.
- For firewall, add the Container Apps Environment subnet to the storage account's allow list.
- Transient throttling: re-run.

### `bbc_discovery:auth_refresh`

**What happened.** BBC Monitoring token returned 401 mid-run; the B5 follow-up did a one-shot refresh and continued. This entry indicates the refresh succeeded — if the refresh had failed, the run would have errored out instead.

**Action:** No fix required for this run. **But:** if this entry appears across multiple consecutive runs, the credentials themselves are wrong:
- Check `BBC_MONITORING_USER_NAME` / `BBC_MONITORING_USER_PASSWORD` in Key Vault.
- Confirm BBC Monitoring T&Cs are accepted (log in via browser at monitoring.bbc.co.uk once).

### `extraction:retry_exhausted`

**What happened.** Some articles failed extraction after all retries — they're in `failures_<run_id>.jsonl`. Run still produced output for the rest.

**Action:**
1. Inspect the failures:
   ```bash
   jq '.[].error_class' data/raw/failures_<run_id>.jsonl | sort | uniq -c
   ```
2. Common patterns:
   - All `JSONDecodeError` → prompt change broke the response shape; re-run with `--debug-prompts` and inspect the raw response.
   - All `TimeoutError` → Foundry latency spike; usually transient; re-run.
   - All `RateLimitError` → drop `--workers` or `--rpm-limit` for the next run.

### `geocoding:nominatim_unavailable`

**What happened.** Nominatim OSM rate-limited or returned 5xx; events have `lat`/`lon` set to null.

**Action:** Geocoding is best-effort. If most events lack coords, re-run only the geocoding stage:
```bash
venv/bin/python -m src.acquisition.pipeline --stage geocode --resume
```

## Unknown entries

If you encounter a degraded-mode tag not in the list above:

1. Search the codebase for where the tag is set:
   ```bash
   grep -rn "degraded_modes" src/
   ```
2. Find the surrounding context — what was the fallback path?
3. Document it in this skill (add an entry above) and in `.claude/deploy.md` § Troubleshooting in the same commit.

## Guard rails

- **Don't auto-restart a failed Container App job** without checking what failed first. The `degraded_modes` list reflects the last completed run, not the currently failing one.
- **Don't suppress degraded-mode logging** to silence noisy alerts. The right fix is to fix the underlying cause; suppression hides regressions.

## Related

- `.claude/deploy.md` § Troubleshooting — the source these mappings derive from.
- `pea-smoke` — verify Foundry connectivity before blaming runtime issues.
- `pea-canary-run` — re-verify after applying a fix.
