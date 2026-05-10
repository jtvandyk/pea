---
name: pea-rollback
description: Roll a Container Apps Job (pipeline or dashboard) back to a known-good image SHA, or pause the cron entirely. Use when a recent deploy broke production and the operator needs to restore service while debugging. Triggers on phrases like "rollback the deploy", "revert to previous SHA", "pause the cron", "stop the daily job", "the new build is broken".
---

# pea-rollback

Codifies the rollback recipe from `.claude/deploy.md` § "Rollback procedures".
Recovery first, root-cause analysis second — that's the order this skill enforces.

## When to use

- A new deploy is producing bad output (empty events, schema-broken JSON, error-only logs).
- A new image is OOM-ing or hitting an infra limit.
- Operator wants to halt scheduled runs while investigating.

**Do not use** for fixing a single failed run — that's `pea-degraded-mode` or just a re-run.

## Procedure

1. **Confirm the operator wants rollback, not forward-fix.** Ask:
   - When did it start failing? (last 1 run / today's runs / multiple days)
   - Is the dashboard also broken, or just the pipeline?
   - Is there an obvious commit in the last day's history that introduced the regression?

   If "yes" to a recent commit AND the fix is small, propose forward-fix with a hot-patch commit to main (CI rebuilds + redeploys) instead of rollback. Rollback is for cases where the right fix isn't yet known.

2. **Verify subscription + RG.** Always run before any `az` write:
   ```bash
   az account show --query '{name:name, id:id}' -o table
   ```
   Refuse to proceed if the subscription is wrong.

3. **List the last 10 image SHAs in ACR:**
   ```bash
   az acr repository show-tags \
     --name $ACR_NAME --repository pea-pipeline \
     --orderby time_desc --top 10
   ```
   And for the dashboard:
   ```bash
   az acr repository show-tags \
     --name $ACR_NAME --repository pea-dashboard \
     --orderby time_desc --top 10
   ```

4. **Pick the previous-known-good SHA.** Default heuristic: most recent SHA *before* the one currently deployed and *not* on the broken commit's chain. If unclear, ask the operator which commit was last known good.

5. **Roll the affected service back:**

   **Pipeline (daily job):**
   ```bash
   az containerapp job update \
     --name pea-daily --resource-group pea-rg \
     --image $ACR_LOGIN_SERVER/pea-pipeline:<sha>
   ```
   And the backfill job if it exists:
   ```bash
   az containerapp job update \
     --name pea-backfill --resource-group pea-rg \
     --image $ACR_LOGIN_SERVER/pea-pipeline:<sha>
   ```

   **Dashboard:**
   ```bash
   az containerapp update \
     --name pea-dashboard --resource-group pea-rg \
     --image $ACR_LOGIN_SERVER/pea-dashboard:<sha>
   ```

6. **Trigger a smoke run on the rolled-back image:**
   ```bash
   az containerapp job start --name pea-daily --resource-group pea-rg
   ```
   Wait for execution status, then check the summary. Don't declare rollback successful until one full run completes cleanly.

7. **Document the rollback:**
   - Note which SHA you rolled to and why in a follow-up issue or `.claude/followups.md`.
   - Add a one-line entry under `CLAUDE.md` § "Improvement History" with the date.

## Pause the cron entirely

When rollback isn't enough — e.g. ACR is empty of good SHAs, or the issue is data-side (GDELT outage, Foundry degraded) and you don't want to keep firing failing jobs:

```bash
az containerapp job update \
  --name pea-daily --resource-group pea-rg \
  --cron-expression "0 0 31 2 *"
```

`Feb 31` never fires. Container Apps has no native pause flag; this is the documented workaround.

## Restore the cron

When the issue is fixed and you've verified manual runs succeed:

```bash
az containerapp job update \
  --name pea-daily --resource-group pea-rg \
  --cron-expression "0 6 * * *"
```

Then start a manual run to confirm:

```bash
az containerapp job start --name pea-daily --resource-group pea-rg
```

## Guard rails

- **Never roll back without a known-good target SHA.** "Roll back to anything older" is a recipe for compounding the outage. If ACR has no clearly-good SHA, pause cron and investigate forward.
- **Confirm subscription before every `az` write.** Reusing the wrong subscription has broken prod elsewhere; the cost of `az account show` is trivial.
- **Don't roll back the dashboard for a pipeline issue** (and vice versa). They're independent. Touching both doubles the rollback radius unnecessarily.
- **Don't `--no-verify` a hot-fix commit** to bypass CI. CI is what would have caught the regression in the first place.
- **`:latest` is a trap on ACR.** Followup #11 flags this — a bad image taints `:latest` until the next merge. Always pin to a SHA on rollback, not `:latest`.

## Related

- `.claude/deploy.md` § Rollback procedures — source.
- `.claude/followups.md` #11 — drop `:latest` push (root-cause prevention).
- `pea-deploy-phase` — the forward path; this skill is the inverse.
- `pea-degraded-mode` — for partial failures that don't warrant rollback.
