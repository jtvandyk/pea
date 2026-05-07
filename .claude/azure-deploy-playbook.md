# PEA → Azure Deploy Playbook

End-to-end playbook for getting PEA into a working Azure deployment as
quickly as possible. Designed to be followed top-to-bottom on deploy day;
each step lists the exact command, what it does, and what success looks
like before you move on.

**Target time:** ~2 hours from `az login` to first scheduled run.

**Prerequisites the playbook assumes:**
- You can `az login` against the subscription you want to deploy into.
- You have the Azure AI Foundry deployment name and endpoint URL ready.
- The repo is pushed to GitHub (`jtvandyk/pea`) and you can edit Settings →
  Secrets there.
- You're working from a freshly-cloned repo on a machine with Docker, Python
  3.11, and the Azure CLI installed.

---

## Phase 0 — Pre-flight (10 min)

Before touching Azure, confirm the codebase is healthy locally. CI does
this on push but the dev-loop catches it earlier.

```bash
# from repo root
python -m black --check src/ tests/
python -m flake8 src/ tests/
python -m pytest tests/ -q
```

All three must exit 0. If any fails, stop and fix before going further —
a broken build will silently fail in `verify` and never reach the registry.

Confirm Docker can build both images:

```bash
docker build -f Dockerfile -t pea-pipeline:test .
docker build -f Dockerfile.web -t pea-dashboard:test .
```

Both should succeed. If `pea-pipeline` build is slow (>5 min), check that
torch is installing from the CPU-only index (Dockerfile lines 8–9). The
2 GB CUDA wheel is the most common reason for slow builds.

Sanity-check that the container has the codebook + examples in the right
place (catches the regression that B3's startup assertion guards against):

```bash
docker run --rm pea-pipeline:test \
  python -c "import sys; sys.path.insert(0, '/app'); \
             from src.acquisition.pipeline import _assert_required_configs; \
             _assert_required_configs(); print('configs OK')"
```

Should print `configs OK`. If it errors with "required config files
missing", the Dockerfile is broken — do not proceed.

---

## Phase 1 — Azure provisioning (20 min)

```bash
az login
az account set --subscription <your-subscription-id>
az account show --query '{name:name, id:id}' -o table   # confirm
```

Run the setup script. This is **idempotent for resource-group / ACR /
storage account creation**, but will fail noisily if names already exist
(setup.sh uses `$RANDOM` suffixes so first run will succeed; re-runs
generate different suffixes — see "Re-running setup.sh" below).

```bash
chmod +x infra/setup.sh
./infra/setup.sh
```

Save the script's final output block. You'll need every value in it for
Phase 2 and Phase 3:

```
ACR_LOGIN_SERVER = <ACR>.azurecr.io
ACR_USERNAME     = <ACR>
ACR_PASSWORD     = <password>
AZURE_STORAGE_CONNECTION_STRING = <conn-str>
RESOURCE_GROUP   = pea-rg
STORAGE_ACCOUNT  = peastorage<random>
ADLS_FILESYSTEM  = pea-outputs
SUBSCRIPTION_ID  = <subscription-id>
```

**Success looks like:** the script's final summary block prints all four
sections without errors, and `az group show -n pea-rg -o table` returns
the new RG.

### Re-running setup.sh

If `setup.sh` fails partway through (network blip, quota error, etc.) and
you re-run it: **edit `ACR_NAME` and `STORAGE_ACCOUNT` to the values
already created** instead of letting `${RANDOM}` regenerate them.
Otherwise the second run creates a second ACR and storage account.

---

## Phase 2 — GitHub Secrets + first ACR push (15 min)

Go to GitHub → repo Settings → Secrets and variables → Actions. Add:

| Secret name | Value |
|---|---|
| `ACR_LOGIN_SERVER` | from setup.sh output |
| `ACR_USERNAME` | from setup.sh output |
| `ACR_PASSWORD` | from setup.sh output |
| `AZURE_RESOURCE_GROUP` | `pea-rg` (or your override) |
| `AZURE_CREDENTIALS` | output of `az ad sp create-for-rbac --name pea-deploy --role contributor --scopes /subscriptions/<sub-id>/resourceGroups/pea-rg --sdk-auth` |

**The SP creation command** (copy-paste, replacing `<sub-id>`):

```bash
az ad sp create-for-rbac \
  --name pea-deploy \
  --role contributor \
  --scopes /subscriptions/<sub-id>/resourceGroups/pea-rg \
  --sdk-auth
```

Paste the **entire JSON output** (including the curly braces) into the
`AZURE_CREDENTIALS` secret.

Now trigger the docker build by pushing to main:

```bash
git push origin main
```

Watch GitHub Actions: go to Actions tab, find the most recent
"Docker Build & Push (ACR)" run. It will run in this order:

1. **`verify`** (~3 min): black + flake8 + pytest. **This must pass before
   any image is built.** This is the gate added in priority #9.
2. **`build-and-push`** (~5 min): builds both images, pushes to ACR with
   the commit SHA tag, plus `:latest`.
3. **`update-container-apps`** (~5 min, but skipped on first run because
   the Container Apps Jobs don't exist yet — error is expected here, not
   a problem).

**Success looks like:**

```bash
az acr repository list --name <ACR_NAME> -o table
# Should show: pea-pipeline  pea-dashboard
```

---

## Phase 3 — Deploy Container Apps Jobs (20 min)

This is where the deploy-day blockers I fixed in B4 actually matter:
the script writes `AZURE_OPENAI_ENDPOINT` to Key Vault **and** wires it
into both job specs. Without B4 the jobs would crash on first LLM call
with an empty endpoint.

Set the required env vars in your shell:

```bash
export ACR_NAME=<from-setup>
export STORAGE_ACCOUNT=<from-setup>
export ADLS_FILESYSTEM=pea-outputs
export AZURE_FOUNDRY_API_KEY=<your-foundry-key>
export AZURE_OPENAI_ENDPOINT="https://<resource>.openai.azure.com/openai/v1"
export ALERT_EMAIL=<your-email>
```

Optional, only if you'll use `--source bbc/all`:

```bash
export BBC_MONITORING_USER_NAME=<bbc-username>
export BBC_MONITORING_USER_PASSWORD=<bbc-password>
```

Run deploy.sh:

```bash
chmod +x infra/deploy.sh
./infra/deploy.sh
```

The script:

1. Creates Log Analytics workspace + Container Apps Environment.
2. Creates Key Vault and stores **two** secrets: `pea-foundry-api-key`
   and `pea-openai-endpoint` (B4 fix — the second one used to be missing).
3. Creates user-assigned managed identity, grants AcrPull / Key Vault
   Secrets User / Storage Blob Data Contributor.
4. Creates `pea-daily` Container Apps Job (cron `0 6 * * *` UTC).
5. Creates `pea-backfill` Container Apps Job (manual trigger).
6. Creates Azure Monitor alerts for pipeline failures.
7. **Runs the smoke test against the live Foundry endpoint** (B5). If the
   endpoint, key, or deployment name is wrong, the deploy fails here
   instead of three days later.

**Success looks like** (final lines from deploy.sh):

```
=== Deployment complete ===
Daily job runs at 06:00 UTC. To trigger manually:
  az containerapp job start --name pea-daily --resource-group pea-rg
--- Running post-deploy smoke test against AZURE_OPENAI_ENDPOINT ---
PASS: live Azure Foundry endpoint is reachable and returning JSON.
  Smoke test PASSED
```

If the smoke test fails:
- 401: foundry key wrong or pasted with whitespace.
- 404 "deployment not found": the deployment name in the Foundry project
  doesn't match the script's default (`gpt-4.1`). Set
  `PEA_SMOKE_MODEL=<your-deployment>` and re-run, or set `SKIP_SMOKE=1`
  if you'll fix it later.
- Connection error: endpoint URL malformed (most often missing the
  `/openai/v1` suffix).

---

## Phase 4 — First manual run (10 min)

Don't wait for 06:00 UTC. Trigger a small smoke run immediately:

```bash
az containerapp job start \
  --name pea-daily \
  --resource-group pea-rg
```

Stream logs:

```bash
# Get the latest execution name
EXEC=$(az containerapp job execution list \
  --name pea-daily --resource-group pea-rg \
  --query "[0].name" -o tsv)

# Tail (Container Apps doesn't stream natively — poll Log Analytics)
az monitor log-analytics query \
  --workspace $(az monitor log-analytics workspace show \
    --resource-group pea-rg --workspace-name pea-logs \
    --query customerId -o tsv) \
  --analytics-query "ContainerAppConsoleLogs_CL \
    | where ContainerJobName_s == 'pea-daily' \
    | where ExecutionName_s == '$EXEC' \
    | order by TimeGenerated asc \
    | project TimeGenerated, Log_s" \
  -o table
```

Or, more simply, open the Azure Portal → pea-rg → pea-daily → Execution
history → click the latest → Console logs. The Portal is the path of
least resistance for ad-hoc tailing.

**Look for** these markers, in order:

```
"=== Protest Event Analysis Pipeline (codebook v2.4) ==="
"Pipeline cannot start" — DOES NOT appear (B3 startup assertion)
"--- Stage 2.5: Relevance Filter (domain=protest) ---"
"Relevance filter running in DEGRADED MODE" — should NOT appear
  (if it does, the NLI model failed to load — see Troubleshooting below)
"--- Stage 5: Saving Results ---"
"Cloud upload complete"
"=== Pipeline complete ==="
```

If the run completes in <5 min with `total_events: 0`, the relevance
filter is too aggressive — drop the threshold. See "Operations: tuning"
below.

---

## Phase 5 — Verify outputs (5 min)

After the run completes, confirm files landed in ADLS:

```bash
az storage fs file list \
  --file-system pea-outputs \
  --path runs/protest \
  --account-name $STORAGE_ACCOUNT \
  --auth-mode login \
  -o table
```

You should see (where `<ts>` is the run timestamp):

| Name | Type |
|---|---|
| `events_<ts>.jsonl` | file |
| `events_<ts>.csv` | file |
| `summary_<ts>.json` | file |
| `all_events.jsonl` | file (cumulative) |
| `checkpoint.txt` | file (URLs already processed) |

Pull the run summary and inspect:

```bash
az storage fs file download \
  --file-system pea-outputs \
  --path runs/protest/summary_<ts>.json \
  --account-name $STORAGE_ACCOUNT \
  --auth-mode login \
  --destination /tmp/summary.json
cat /tmp/summary.json | jq
```

Key fields to check:

```json
{
  "run_id": "...",
  "total_events": 7,
  "total_failures": 1,
  "degraded_modes": [],            // ← empty list = good
  "events_by_country": {"NG": 3, "ZA": 2, "UG": 1, "DZ": 1},
  "events_by_type": {...},
  "events_by_confidence": {"high": 4, "medium": 3}
}
```

If `degraded_modes` is non-empty (e.g. `["relevance_filter:keyword_fallback"]`),
the NLI model didn't load and the filter ran in keyword-only mode for
this run. **Output is still usable** but precision is lower than the
configured threshold suggests — see Troubleshooting.

---

## Phase 6 — Wait for the first scheduled run (next morning)

The cron is `0 6 * * *` UTC. Tomorrow morning, confirm it ran:

```bash
az containerapp job execution list \
  --name pea-daily --resource-group pea-rg \
  --output table
```

Look for an execution with `Status = Succeeded` and a start time near
06:00 UTC. If you see `Status = Failed`, the Azure Monitor alert from
Phase 3 should have already emailed you.

---

## Phase 7 — Day 2 hardening (30 min)

Done once the first scheduled run is green. None of these block the
deploy but each closes a real risk surface.

### Disable Key Vault public access

```bash
az keyvault update \
  --name pea-kv \
  --public-network-access Disabled \
  --default-action Deny
```

The Container Apps Jobs reach Key Vault over the managed identity, not
the public endpoint, so this doesn't break runtime auth. It does break
your `az keyvault secret show` from a laptop, so **add an exception for
your dev machine's IP first** if you need it:

```bash
az keyvault network-rule add \
  --name pea-kv \
  --ip-address $(curl -s ifconfig.me)/32
```

### Pin the dashboard image to SHA, not :latest

The `:latest` tag is pushed by `docker.yml` but a bad image taints it
until the next merge. After the first verified-green deploy, switch the
dashboard's Container App to reference the specific SHA:

```bash
az containerapp update \
  --name pea-dashboard \
  --resource-group pea-rg \
  --image <ACR>.azurecr.io/pea-dashboard:<sha>
```

(`<sha>` from the `docker.yml` run that built the verified image.) See
`.claude/production-followups.md` item #11 for the full rationale.

### Confirm the Azure Monitor alert actually fires

Best way to test: run a job that's guaranteed to fail.

```bash
az containerapp job start \
  --name pea-daily --resource-group pea-rg \
  --args "--source" "bbc"   # no creds → fails fast
```

Within ~10 min, `pea-job-execution-failed-alert` should email
`$ALERT_EMAIL`. If it doesn't, check the alert query in `infra/deploy.sh`
matches what's in your Log Analytics workspace's `ContainerAppSystemLogs_CL`
table — schema names occasionally differ across regions.

---

## Operations runbook

### Trigger an immediate run

```bash
az containerapp job start \
  --name pea-daily --resource-group pea-rg
```

### Run a historical backfill

The backfill job is manual-trigger and accepts args at start time.
**Always pass `--resume` and `--upload-to`** — without them, a replica
restart re-extracts everything from scratch and double-spends tokens.

```bash
az containerapp job start \
  --name pea-backfill --resource-group pea-rg \
  --args \
    "--stage" "all" \
    "--countries" "NG,ZA,UG,DZ" \
    "--backfill-from" "2024-01-01" \
    "--backfill-to" "2024-12-31" \
    "--backfill-window-days" "30" \
    "--workers" "8" \
    "--resume" \
    "--upload-to" "abfss://pea-outputs/backfill"
```

### Update code

Push to main. CI runs `verify` → builds images → pushes to ACR → updates
both Container Apps Jobs to the new SHA. Cron picks up the new image at
the next 06:00 UTC run automatically.

### Tune the relevance-filter threshold

If the first runs reject most articles (logs show "All articles rejected"
or `total_events` consistently single-digit), drop the threshold from
0.30 to 0.20:

```bash
az containerapp job update \
  --name pea-daily --resource-group pea-rg \
  --replace-args \
    "--stage" "all" \
    "--countries" "NG,ZA,UG,DZ" \
    "--days" "2" \
    "--resume" \
    "--upload-to" "abfss://pea-outputs/runs" \
    "--workers" "4" \
    "--rpm-limit" "450" \
    "--relevance-threshold" "0.20"
```

(The `--replace-args` form is required because Container Apps doesn't
have a partial-arg-update mode — you have to supply the full list.)

### Read the latest event extractions

```bash
# Latest events as JSONL
az storage fs file download \
  --file-system pea-outputs \
  --path runs/protest/all_events.jsonl \
  --account-name $STORAGE_ACCOUNT --auth-mode login \
  --destination /tmp/all_events.jsonl

# Quick stats
jq -s 'group_by(.event_type) | map({type: .[0].event_type, n: length})' \
  /tmp/all_events.jsonl
```

---

## Rollback procedures

### Rollback to a known-good image

The recipe — works for both pipeline and dashboard:

```bash
# List available SHAs in ACR
az acr repository show-tags \
  --name $ACR_NAME --repository pea-pipeline \
  --orderby time_desc --top 10

# Roll the daily job back
az containerapp job update \
  --name pea-daily --resource-group pea-rg \
  --image $ACR_LOGIN_SERVER/pea-pipeline:<previous-sha>
```

### Pause the cron entirely

```bash
az containerapp job update \
  --name pea-daily --resource-group pea-rg \
  --cron-expression "0 0 31 2 *"   # Feb 31 = never
```

(There is no Container Apps "pause" flag; setting an impossible cron is
the standard workaround.)

### Restore the cron

```bash
az containerapp job update \
  --name pea-daily --resource-group pea-rg \
  --cron-expression "0 6 * * *"
```

---

## Troubleshooting

### "Pipeline cannot start — required config files missing"

The Dockerfile is broken or `.dockerignore` is excluding `configs/`. The
B3 startup assertion is doing its job. Check `Dockerfile` line 17 has
`COPY configs/ ./configs/` and `.dockerignore` doesn't list `configs/`.
Rebuild and push.

### Smoke test fails with 401

Foundry key is wrong, rotated, or pasted with leading/trailing whitespace.

```bash
# Trim and re-store
echo -n "$AZURE_FOUNDRY_API_KEY" | wc -c   # should be 32+
echo -n "$AZURE_FOUNDRY_API_KEY" | xxd | tail -1   # check no \n at end
az keyvault secret set \
  --vault-name pea-kv \
  --name pea-foundry-api-key \
  --value "$(echo -n "$AZURE_FOUNDRY_API_KEY" | tr -d '[:space:]')"
```

Then either re-deploy or restart the next job execution.

### Smoke test fails with 404 "deployment not found"

The deployment name in the Foundry project doesn't match `--model`.
Either:
- Update the `--model` arg in `infra/deploy.sh` (search for `--model`)
  and re-run deploy.sh, OR
- Pass `--model <your-deployment>` when triggering the job manually.

### `degraded_modes: ["relevance_filter:keyword_fallback"]` in summary

The DeBERTa NLI model failed to load at runtime. Most common causes:
1. Container has no internet (corporate proxy / locked-down VNet) and
   can't pull the model from HuggingFace on first run.
2. Memory pressure killed the model during loading.

Mitigations:
- Bake the model into the image at build time (add a
  `RUN python -c "from transformers import pipeline; \
  pipeline('zero-shot-classification', \
  model='cross-encoder/nli-deberta-v3-small')"` step to `Dockerfile`).
- Bump CPU/memory: `az containerapp job update --name pea-daily \
  --cpu 4 --memory 8Gi`.

The pipeline still produces output in degraded mode — keyword scoring is
less precise but functional. Don't treat this as a stop-the-line event;
fix it within a day.

### Cloud upload fails (run exits non-zero)

The B3 fix re-raises on final upload failure so the run is marked
Failed. Causes:
- Managed identity doesn't have `Storage Blob Data Contributor` on the
  storage account. Confirm with:
  ```bash
  az role assignment list \
    --assignee $(az identity show --name pea-identity \
                  --resource-group pea-rg --query principalId -o tsv) \
    --scope $(az storage account show --name $STORAGE_ACCOUNT \
                --resource-group pea-rg --query id -o tsv) \
    -o table
  ```
- ADLS firewall blocks the Container App's egress IP. Add the Container
  Apps Environment subnet to the storage account's firewall, or set
  `--default-action Allow` if you don't have a private VNet yet.

### BBC discovery hangs / 401s mid-run

The B5 follow-up adds a one-shot 401 refresh, so a single token expiry
is recovered automatically. Repeated 401s mean the creds themselves are
wrong — check `BBC_MONITORING_USER_NAME` / `BBC_MONITORING_USER_PASSWORD`
secrets in Key Vault, and confirm BBC Monitoring T&Cs are accepted (log
in via browser at monitoring.bbc.co.uk once).

### Cron didn't fire

```bash
# Confirm the cron is set
az containerapp job show \
  --name pea-daily --resource-group pea-rg \
  --query "properties.configuration.scheduleTriggerConfig.cronExpression"
# Should print: "0 6 * * *"

# Check execution history
az containerapp job execution list \
  --name pea-daily --resource-group pea-rg --output table
```

If history is empty 24h after cron should have fired, the Container Apps
Environment may have been recreated (e.g. by a `setup.sh` re-run) and
the job's link is stale. Re-run `deploy.sh`.

---

## Known-state checklist (post-deploy)

After Phase 5 success, the following should all be true. Use this as a
go/no-go for declaring the deploy live.

- [ ] `az group show -n pea-rg` returns the resource group
- [ ] `az acr repository list --name $ACR_NAME` shows both
      `pea-pipeline` and `pea-dashboard`
- [ ] `az containerapp job list -g pea-rg -o table` shows both
      `pea-daily` and `pea-backfill` with `ProvisioningState=Succeeded`
- [ ] `az keyvault secret show --vault-name pea-kv --name pea-foundry-api-key`
      returns a non-empty value
- [ ] `az keyvault secret show --vault-name pea-kv --name pea-openai-endpoint`
      returns the endpoint URL (B4 — used to be missing)
- [ ] At least one execution of `pea-daily` has `Status=Succeeded`
- [ ] `events_*.jsonl` exists in `abfss://pea-outputs/runs/protest/`
- [ ] `summary_*.json` `degraded_modes: []` (or you've explicitly accepted
      a degraded-mode warning)
- [ ] Azure Monitor alert tested by triggering a known-failure run

If any box is unchecked, do not call the deploy done.

---

## What's _not_ in this playbook

- **Codebook tuning loop.** See `.claude/improvement-guide.md` and the
  Day-1-to-Day-14 cadence in the production-readiness review.
- **Annotation pipeline (Label Studio).** See README → "Annotation
  Workflow — Closing the Active Learning Loop".
- **Validation against GLOCON / CEHA / CASE 2021.** See
  `src/validation/` and the README "Validation" section.
- **Outstanding follow-up work** (P2/P3 items, CVE scanning, multi-domain
  pipeline tests, etc.). See `.claude/production-followups.md`.

---

## Pointer summary

| Need | Look here |
|---|---|
| Provision Azure resources | `infra/setup.sh` |
| Deploy Container Apps Jobs | `infra/deploy.sh` |
| Smoke test live endpoint | `scripts/smoke_extract.py` |
| Required env vars | `.env.example` |
| Mandatory config files | `_REQUIRED_CONFIGS` in `src/acquisition/pipeline.py` |
| Cron schedule | `infra/deploy.sh` line near `--cron-expression` |
| Codebook content | `configs/protest_codebook.yaml` (v2.4) |
| Few-shot examples | `configs/extraction_examples.yaml` (8 pinned) |
| Outstanding follow-ups | `.claude/production-followups.md` |
| Codebook improvement playbook | `.claude/improvement-guide.md` |
