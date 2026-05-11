---
name: pea-rollback
description: Roll a Container Apps Job (pipeline or dashboard) back to a known-good image SHA, or pause the cron entirely. Use when a recent deploy broke production and the operator needs to restore service while debugging. Triggers on phrases like "rollback the deploy", "revert to previous SHA", "pause the cron", "stop the daily job", "the new build is broken".
---

# pea-rollback

Codeifies the rollback recipe from `.claude/deploy.md` § "Rollback procedures".
Recovery first, root-cause analysis second — that's the order this skill enforces.

## When to use

- A new deploy is producing bad output (empty events, schema-broken JSON, error-only logs).
- A new image is OOM-ing or hitting an infra limit.
- Operator wants to halt scheduled runs while investigating.

**Do not use** for fixing a single failed run — that's `pea-degraded-mode` or just a re-run.

## Procedure

1. **Confirm rollback vs forward-fix.** If there's an obvious small fix on the broken commit, propose a hot-patch instead.

2. **Verify subscription + RG:**
   ```bash
   az account show --query '{name:name, id:id}' -o table
   ```

3. **List the last 10 image SHAs:**
   ```bash
   az acr repository show-tags --name $ACR_NAME --repository pea-pipeline --orderby time_desc --top 10
   az acr repository show-tags --name $ACR_NAME --repository pea-dashboard --orderby time_desc --top 10
   ```

4. **Pick the previous-known-good SHA.**

5. **Roll back:**
   ```bash
   az containerapp job update --name pea-daily --resource-group pea-rg \
     --image $ACR_LOGIN_SERVER/pea-pipeline:<sha>
   az containerapp job update --name pea-backfill --resource-group pea-rg \
     --image $ACR_LOGIN_SERVER/pea-pipeline:<sha>
   az containerapp update --name pea-dashboard --resource-group pea-rg \
     --image $ACR_LOGIN_SERVER/pea-dashboard:<sha>
   ```

6. **Trigger a smoke run and confirm success before declaring rollback done.**

7. **Document:** note SHA + reason in `.claude/followups.md` and `CLAUDE.md` § "Improvement History".

## Pause / restore cron

```bash
# Pause (Feb 31 never fires)
az containerapp job update --name pea-daily --resource-group pea-rg \
  --cron-expression "0 0 31 2 *"

# Restore
az containerapp job update --name pea-daily --resource-group pea-rg \
  --cron-expression "0 6 * * *"
```

## Guard rails

- **Never roll back without a known-good target SHA.**
- **Confirm subscription before every `az` write.**
- **Don't roll back the dashboard for a pipeline issue** (and vice versa).
- **Don't `--no-verify` a hot-fix commit.**
- **`:latest` is a trap.** Always pin to a SHA.

## Related

- `.claude/deploy.md` § Rollback procedures.
- `.claude/followups.md` #11 — drop `:latest` push.
- `pea-deploy-phase` — the forward path.
- `pea-degraded-mode` — for partial failures.
