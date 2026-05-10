---
name: pea-smoke
description: Run the post-deploy smoke test (`scripts/smoke_extract.py`) against the live Azure Foundry endpoint and map any failure to its root cause. Use after a deploy, before debugging "is the pipeline broken or is Foundry broken", or as the first step when an operator suspects an auth / endpoint / deployment-name issue. Triggers on phrases like "post-deploy smoke", "is foundry reachable", "test the foundry endpoint", "smoke check".
---

# pea-smoke

Wraps `scripts/smoke_extract.py` with the failure-mode mapping from
`.claude/deploy.md` § Troubleshooting. The smoke test sends one canned
protest article through `extract_from_article` and asserts the live
deployment returned parseable JSON.

## When to use

- Immediately after a deploy completes (Phase 3 already does this; this
  skill is for ad-hoc verification later).
- As the first triage step when extractions are failing in production —
  rules out / confirms whether the issue is the Foundry connection.
- Before running a backfill (don't burn token budget if Foundry is degraded).

## Prerequisites

These env vars must be set in the shell:

- `AZURE_FOUNDRY_API_KEY` — Foundry key, no whitespace.
- `AZURE_OPENAI_ENDPOINT` — full URL ending in `/openai/v1`.

If either is missing, halt and ask the operator to load `.env` (or set them inline).

## Procedure

1. **Confirm env vars are loaded:**
   ```bash
   echo -n "$AZURE_FOUNDRY_API_KEY" | wc -c     # expect 32+
   echo "$AZURE_OPENAI_ENDPOINT"                # must end in /openai/v1
   ```

2. **Run the smoke test:**
   ```bash
   venv/bin/python -m scripts.smoke_extract --model gpt-5.4
   ```
   For a different deployment name:
   ```bash
   venv/bin/python -m scripts.smoke_extract --model <deployment-name>
   ```

3. **On exit code 0**, surface success in one line. The smoke caught nothing
   meaningful — Foundry is reachable; if extractions are failing, look
   downstream (relevance filter, codebook, etc.).

4. **On exit code 1**, parse the failure shape and map to the right fix:

### 401 Unauthorized

**Cause.** Foundry key is wrong, rotated, or has whitespace.

**Fix:**
```bash
# Trim whitespace and reload
echo -n "$AZURE_FOUNDRY_API_KEY" | xxd | tail -1   # check no \n at end
export AZURE_FOUNDRY_API_KEY="$(echo -n "$AZURE_FOUNDRY_API_KEY" | tr -d '[:space:]')"
```

If the issue persists:
- Rotate the key in the Foundry portal.
- Update Key Vault:
  ```bash
  az keyvault secret set \
    --vault-name pea-kv \
    --name pea-foundry-api-key \
    --value "$AZURE_FOUNDRY_API_KEY"
  ```
- Either re-run the smoke or restart the next job execution.

### 404 deployment not found

**Cause.** The deployment name passed via `--model` doesn't match what's
configured in the Foundry project.

**Fix:**
- List deployments in the Foundry portal and confirm the name.
- Either pass the correct name:
  ```bash
  venv/bin/python -m scripts.smoke_extract --model <correct-name>
  ```
- Or update `infra/deploy.sh` (search for `--model`) and re-run deploy.sh.
- For one-off env override: `export PEA_SMOKE_MODEL=<correct-name>`.

### Connection error / DNS failure

**Cause.** Endpoint URL malformed (most often missing `/openai/v1` suffix),
or the operator's network can't reach `*.openai.azure.com`.

**Fix:**
- Verify suffix:
  ```bash
  [[ "$AZURE_OPENAI_ENDPOINT" == *"/openai/v1" ]] && echo "ok" || echo "missing /openai/v1"
  ```
- If suffix is correct but DNS fails, test from another network. If only
  the operator's network fails, suspect VPN / proxy.

### JSON parse failure on response

**Cause.** Foundry API version drift broke the response shape, or the
deployment returned a string instead of structured JSON.

**Fix:**
- Re-run with `--max-retries 1` to see the raw response in the trace.
- Check the API version pinning in `src/acquisition/extractor.py:_call_azure`.
- If the API version is recent, this may indicate the deployment is using
  a model that doesn't support structured outputs — switch to a
  structured-output-capable deployment.

### Timeout

**Cause.** Foundry latency spike, or deployment scaled to zero and is
cold-starting.

**Fix:**
- Re-run after 30–60 seconds.
- If still timing out, check Foundry portal for service health alerts.

## After a successful smoke

If extractions are failing in production *despite* a green smoke:

1. Run `pea-canary-run` for end-to-end check.
2. If canary also passes but production fails: the issue is environmental
   (managed identity, Key Vault, network) — see `.claude/deploy.md` §
   Troubleshooting and `pea-degraded-mode`.

## Guard rails

- **Don't loop the smoke test more than 3 times** without intervening
  diagnosis. Repeat smokes don't add information; they just spend tokens.
- **Don't skip the smoke just because the last one passed.** Foundry can
  rotate keys server-side, deployments can be deleted, API versions can
  drift. The smoke is a 1-second guard rail.
- **Don't run the smoke against production while a deploy is mid-flight.**
  False failures will compound the operator's confusion.

## Related

- `scripts/smoke_extract.py` — the underlying script.
- `.claude/deploy.md` § Troubleshooting — source for the failure-mode mapping.
- `pea-deploy-phase` — Phase 3 already runs this; this skill is for ad-hoc.
- `pea-degraded-mode` — for *partial* failures the smoke wouldn't catch.
