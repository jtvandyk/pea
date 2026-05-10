---
name: pea-deploy-phase
description: Walk the operator through a single phase of the Azure deploy playbook with explicit checkpoints, instead of asking them to scroll 671 lines of prose. Use on deploy day, on rollback day, or when a deploy phase failed and the operator wants to resume from a known-good state. Triggers on phrases like "deploy to azure", "azure rollout", "phase 3", "resume the deploy", "rollback the deploy".
---

# pea-deploy-phase

Interactive walker for `.claude/deploy.md`. Loads the requested phase, runs each step, and gates on the documented success criteria before moving on.

## When to use

- New deploy from a clean checkout.
- Resume after a phase failed midway.
- Audit a partial deploy (run the success-checks for each completed phase without re-running commands).

## Phase index (from `.claude/deploy.md`)

| Phase | Goal | Time | Key risk |
|---|---|---|---|
| 0 | Pre-flight (black, flake8, pytest, docker build) | 10 min | Broken build silently fails downstream |
| 1 | Azure provisioning via `infra/setup.sh` | 20 min | Re-running creates duplicate ACR / storage |
| 2 | GitHub Secrets + first ACR push | 15 min | SP scope mismatch → CI deploy fails |
| 3 | Container Apps Jobs deploy via `infra/deploy.sh` | 20 min | Smoke test against live Foundry endpoint |
| 4 | First manual run | 10 min | Cron trigger latency obscures failures |
| 5 | Verify outputs in ADLS | 5 min | `degraded_modes` non-empty hides quality drop |
| 6 | Wait for first scheduled cron | overnight | Cron didn't fire — env stale |
| 7 | Day-2 hardening (KV firewall, SHA pinning, alert test) | 30 min | Skipping → CVE / rollback risk |

## Procedure

1. **Ask which phase** the user wants to run. Default to Phase 0 if they haven't started.

2. **Load only that phase's section from `.claude/deploy.md`.** Don't read the full file into context — read the matching `## Phase N` section by line range or by `grep -n "^## Phase"` to find the bounds.

3. **For each step in the phase:**
   - State the command in one line.
   - Run it (or ask the user to run it locally if it requires `az login`).
   - Verify the documented success marker before continuing.
   - On failure, jump straight to the matching item in the `## Troubleshooting` section.

4. **Before declaring the phase done**, run the matching item from the "Known-state checklist (post-deploy)" section if it exists for that phase.

## Phase-specific notes

### Phase 0
The three checks are also the pre-commit hook in `.claude/settings.json`, so a clean working tree usually means Phase 0 passes. Still run all three explicitly — CI catches regressions Hook misses (e.g. a commit that bypassed `--no-verify`).

### Phase 1
`setup.sh` is **only idempotent on the first run** because of `${RANDOM}` suffixes. If it failed mid-way, do **not** re-run blindly — edit `ACR_NAME` and `STORAGE_ACCOUNT` in the script to the values already created.

### Phase 3
The smoke test is the deploy's gate. If it fails:
- 401 → trim whitespace from `AZURE_FOUNDRY_API_KEY`, re-store in KV.
- 404 → deployment name doesn't match; set `PEA_SMOKE_MODEL` or fix `--model` arg in `infra/deploy.sh`.
- Connection error → endpoint URL missing `/openai/v1` suffix.

### Phase 7
Don't skip the alert test. The cleanest test is starting `pea-daily` with `--source bbc` and no BBC creds — it fails fast and exercises the alert path.

## Rollback flow (separate from forward phases)

If the user says "rollback":

1. List the last 10 SHAs in ACR:
   ```bash
   az acr repository show-tags --name $ACR_NAME --repository pea-pipeline --orderby time_desc --top 10
   ```
2. Pin the job to the previous-known-good SHA:
   ```bash
   az containerapp job update --name pea-daily --resource-group pea-rg \
     --image $ACR_LOGIN_SERVER/pea-pipeline:<sha>
   ```
3. If the issue is severe enough to pause cron, set the impossible cron `"0 0 31 2 *"` per the playbook.

## Guard rails

- **Confirm subscription + RG before any `az` write.** A mis-targeted `az containerapp job update` can take prod down. Always echo `az account show --query name` first.
- **Never run `setup.sh` more than once without editing it.** See Phase 1 note.
- **Don't auto-pin to `:latest`.** Followup #11 explicitly addresses this — use the SHA tag.
- **`--upload-to` and `--resume`** are mandatory for backfills. Without them, a replica restart double-spends tokens.

## Related

- `.claude/deploy.md` — full playbook (this skill is just the interactive runner).
- `.claude/followups.md` items #11, #12, #15 — CI/deploy hardening that affects future deploys.
- `pea-rollback` skill (Tier 2, not yet built) — would extract the rollback flow into its own skill.
