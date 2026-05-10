---
name: pea-smoke
description: Run the post-deploy smoke test (`scripts/smoke_extract.py`) against the live Azure Foundry endpoint and map any failure to its root cause. Use after a deploy, before debugging "is the pipeline broken or is Foundry broken", or as the first step when an operator suspects an auth / endpoint / deployment-name issue. Triggers on phrases like "post-deploy smoke", "is foundry reachable", "test the foundry endpoint", "smoke check".
---

# pea-smoke

Wraps `scripts/smoke_extract.py` with the failure-mode mapping from
`.claude/deploy.md` § Troubleshooting.

## When to use

- Immediately after a deploy completes (Phase 3 already does this; this skill is for ad-hoc verification later).
- First triage step when extractions are failing in production.
- Before running a backfill.

## Prerequisites

- `AZURE_FOUNDRY_API_KEY` — no whitespace.
- `AZURE_OPENAI_ENDPOINT` — full URL ending in `/openai/v1`.

## Procedure

1. **Confirm env vars:**
   ```bash
   echo -n "$AZURE_FOUNDRY_API_KEY" | wc -c     # expect 32+
   echo "$AZURE_OPENAI_ENDPOINT"                # must end in /openai/v1
   ```

2. **Run:**
   ```bash
   venv/bin/python -m scripts.smoke_extract --model gpt-5.4
   ```

3. **On exit 0:** Foundry is reachable. If extractions still fail, look downstream.

4. **On exit 1**, map the failure:

   | Error | Cause | Fix |
   |---|---|---|
   | 401 | Wrong/rotated key or whitespace | Trim and re-store in KV |
   | 404 deployment not found | Wrong deployment name | Set `PEA_SMOKE_MODEL` or fix `--model` in `infra/deploy.sh` |
   | Connection error | Endpoint malformed (missing `/openai/v1`) | Fix the URL |
   | JSON parse failure | API version drift | Check `_call_azure` API version pinning |
   | Timeout | Cold start or latency spike | Retry after 30–60s |

## Guard rails

- **Don't loop > 3 times** without diagnosis.
- **Don't skip just because last one passed.**
- **Don't run mid-deploy.**

## Related

- `scripts/smoke_extract.py`.
- `.claude/deploy.md` § Troubleshooting.
- `pea-deploy-phase` — Phase 3 runs this automatically.
- `pea-degraded-mode` — for partial failures the smoke won't catch.
