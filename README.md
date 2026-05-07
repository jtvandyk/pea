# Protest Event Analysis (PEA)

Automated pipeline that turns African news coverage into structured, research-ready protest event records. Articles are discovered via GDELT and optional sources, scraped, filtered for relevance, and passed through an Azure-hosted LLM that extracts events against a precise codebook. Output is JSONL/CSV in Azure Data Lake Storage Gen2, refreshed daily.

| | |
|---|---|
| **Codebook** | v2.4 (Halterman & Keith 2025, Type III stipulative definitions) |
| **Target geography** | Nigeria (NG), South Africa (ZA), Uganda (UG), Algeria (DZ) |
| **LLM backend** | Azure AI Foundry (`--model` sets the deployment name; default `gpt-4.1`) |
| **Production schedule** | Daily at 06:00 UTC via Azure Container Apps Job (`pea-daily`) |
| **Active domains** | `protest` (production), `drone` (research) |

---

## What this produces

The primary output is one JSON object per protest event, written as JSONL plus a flattened CSV. A typical event:

```json
{
  "event_date": "2026-04-22",
  "country": "South Africa",
  "city": "Soweto",
  "region": "Gauteng",
  "venue": "Mzimhlope hostel",
  "latitude": -26.2046,
  "longitude": 27.9419,
  "geo_accuracy": "venue",
  "event_type": "confrontation",
  "organizer": "South Gauteng Community Forum",
  "participant_groups": ["residents", "hostel community"],
  "claims": ["running water restoration", "electricity restoration"],
  "crowd_size": null,
  "duration": "4 hours",
  "state_response": "none",
  "state_actors": ["police"],
  "arrests": "0",
  "fatalities": null,
  "injuries": null,
  "outcome": "partial_concession",
  "outcome_notes": "Municipality promised technical team by Thursday",
  "article_url": "https://example.org/...",
  "article_date": "2026-04-22",
  "source_country": "ZA",
  "source_language": "en",
  "confidence": "high",
  "turmoil_level": "low"
}
```

A single daily run produces:

| File | Purpose |
|---|---|
| `events_{run_id}.jsonl` | Extracted events — primary research output |
| `events_{run_id}.csv` | Same events, flattened for spreadsheets |
| `summary_{run_id}.json` | Run metadata: counts by country/type/turmoil, plus `degraded_modes` flag if any stage fell back |
| `failures_{run_id}.jsonl` | Articles that failed extraction (dead-letter) |
| `all_events.jsonl` | Cumulative append across all runs |
| `checkpoint.txt` | Processed URLs (used by `--resume`) |

These are written to `data/raw/<domain>/` locally, or to `abfss://<filesystem>/runs/<domain>/` in production.

Downstream stages add:

| File | Stage | Contents |
|---|---|---|
| `data/processed/events_consolidated.jsonl` | `process` | Deduplicated, quality-controlled events |
| `data/processed/quality_report.json` | `process` | Schema validity + confidence distribution |
| `data/processed/duplicates_log.jsonl` | `process` | Audit trail of removed duplicates |
| `data/predictions/prevalence_estimates.json` | `predict` | PPI prevalence by event type and country |
| `data/predictions/confidence_breakdown.json` | `predict` | High/medium/low confidence distribution |

---

## Architecture

Six acquisition stages, plus optional `process` and `predict` stages. Stages 1–3 run once and are shared across all active domains; stages 2.5–5 run independently per domain so an article can qualify for multiple codebooks.

```
┌─ SHARED (all domains) ────────────────────────────────────────────┐
│                                                                   │
│  Stage 1 — Discovery       Stage 2 — Scraping     Stage 3 — Translation
│                                                                   │
│  GDELT DOC 2.0  (default)  newspaper4k +          langdetect +
│   one query/country         requests fallback     Google Translate
│   FIPS sourcecountry        UA rotation,          Native langs
│  BBC Monitoring (opt)       paywall skip          (en/fr/ar/sw/...)
│   --source bbc/both         16 workers            skip translation
│  World News API (opt)
│   --source worldnews/all
│  File / ADLS input (opt)
│   --source file
│                                                                   │
└──────────────┬────────────────────────────────────────────────────┘
               │  scraped + translated articles
               ▼
┌─ PER DOMAIN (in series, prompt-cache friendly) ───────────────────┐
│                                                                   │
│  Stage 2.5 — Relevance     Stage 4 — Extraction   Stage 4.5 — Geocode
│                                                                   │
│  DeBERTa NLI               Azure AI Foundry       Nominatim OSM
│  threshold 0.30            codebook + 8 pinned    venue → city →
│  batch 32                  few-shot examples       region → country
│  keyword fallback if       prompt caching ~36%    disk-cached
│   model unavailable        cost saving            (no API key)
│  (degraded_modes flagged)
│                                                                   │
│                              Stage 5 — Storage                    │
│                              JSONL + CSV + summary + dead-letter  │
│                              optional --upload-to ADLS Gen2       │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘

┌─ POST-PROCESSING (optional, --stage process / predict) ───────────┐
│                                                                   │
│  process: geography filter → dedup (TF-IDF claims, ±3d, fuzzy     │
│           city) → LLM re-verification of borderlines → QC report  │
│                                                                   │
│  predict: Prediction-Powered Inference (Angelopoulos et al. 2023) │
│           prevalence intervals correcting for LLM error rate      │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

In production this runs daily inside Azure Container Apps:

```
git push origin main
       │
       ▼
GitHub Actions  (.github/workflows/docker.yml)
  verify (black + flake8 + pytest)  →  build images  →  push to ACR
       │
       ▼  ACR: pea-pipeline:<sha> + :latest, pea-dashboard:<sha> + :latest
       │
       ├──────────────────────────────────────────┐
       ▼                                          ▼
  pea-daily job                            pea-backfill job
  cron 0 6 * * * (UTC)                     manual trigger
  2 CPU / 4 GB                             4 CPU / 8 GB
  --countries NG,ZA,UG,DZ                  pass --args at trigger time
  --days 2 --resume                        with --resume + --upload-to
       │
       ▼
ADLS Gen2 (abfss://pea-outputs/runs/protest/)
  events_*.jsonl    summary_*.json    failures_*.jsonl
       │
       ▼
Azure Monitor scheduled-query alert
  fires on JobExecutionStatus=Failed or "Pipeline failed" log line
  notifies ALERT_EMAIL
```

Secrets (Foundry API key, OpenAI endpoint, optional source credentials) live in Azure Key Vault and are injected at runtime via a user-assigned managed identity — there are no credentials in environment variables on the running job.

Structured logging context (`run_id`, `country`, `stage`, `domain`) is attached to every log record via `contextvars`, so Log Analytics queries can filter by run rather than free-text grep.

---

## Quick start (local)

### 1. Configure environment

```bash
cp .env.example .env   # then fill in values
python -m venv venv && source venv/bin/activate
pip install -r requirements-core.txt
```

Minimum required for a real run:

```
AZURE_FOUNDRY_API_KEY=
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/openai/v1
```

Optional, depending on flags you use: `AZURE_STORAGE_CONNECTION_STRING` or `AZURE_STORAGE_ACCOUNT_URL` (`--upload-to`), `BBC_MONITORING_USER_NAME`/`_PASSWORD` (`--source bbc`), `WORLDNEWS_API_KEY` (`--source worldnews`). See `.env.example` for the full list including dashboard variables.

### 2. Run

```bash
# Smallest useful run — South Africa, last 7 days
python -m src.acquisition.pipeline --countries ZA --days 7

# Production-shape run
python -m src.acquisition.pipeline \
  --countries NG,ZA,UG,DZ --days 7 --max-articles 200

# Multi-domain
python -m src.acquisition.pipeline --domains protest,drone --countries ZA

# Resume after a crash
python -m src.acquisition.pipeline --resume

# Upload outputs to ADLS Gen2
python -m src.acquisition.pipeline --upload-to abfss://my-fs/pea/runs

# Full pipeline — acquire → process → predict
python -m src.acquisition.pipeline --stage all --countries ZA --days 30
```

Output lands in `data/raw/<domain>/`. See [What this produces](#what-this-produces) above for the file inventory.

---

## Production deployment

The full step-by-step operator playbook — including pre-flight checks, Azure provisioning, GitHub Secrets, smoke testing, day-2 hardening, rollback procedures, and a troubleshooting catalogue — lives in [`.claude/azure-deploy-playbook.md`](.claude/azure-deploy-playbook.md). The summary:

```bash
# 1. Provision Azure resources (one time, ~20 min)
az login && az account set --subscription <id>
./infra/setup.sh                     # creates RG + ACR + ADLS Gen2

# 2. Add GitHub Secrets (one time)
#    ACR_LOGIN_SERVER, ACR_USERNAME, ACR_PASSWORD,
#    AZURE_CREDENTIALS, AZURE_RESOURCE_GROUP

# 3. Push to main → CI builds + pushes images to ACR

# 4. Deploy Container Apps Jobs (one time, ~20 min)
export ACR_NAME=… STORAGE_ACCOUNT=…
export AZURE_FOUNDRY_API_KEY=… AZURE_OPENAI_ENDPOINT=…
export ALERT_EMAIL=…
./infra/deploy.sh
# → runs scripts/smoke_extract.py against the live endpoint as the final gate

# 5. Trigger first run + verify
az containerapp job start --name pea-daily --resource-group pea-rg
```

After step 4, every push to `main` re-deploys both jobs to the new image automatically.

### Operations

```bash
# Trigger pea-daily immediately
az containerapp job start --name pea-daily --resource-group pea-rg

# Run a historical backfill (always include --resume + --upload-to)
az containerapp job start --name pea-backfill --resource-group pea-rg \
  --args "--stage" "all" "--countries" "NG,ZA,UG,DZ" \
         "--backfill-from" "2024-01-01" "--backfill-to" "2024-12-31" \
         "--backfill-window-days" "30" "--workers" "8" \
         "--resume" "--upload-to" "abfss://pea-outputs/backfill"

# Watch executions
az containerapp job execution list --name pea-daily --resource-group pea-rg --output table
```

---

## Stage reference

Detail on each stage. All entry points are in `src/acquisition/`.

### 1. Discovery — `gdelt_discovery.py`, `bbc_discovery.py`, `worldnews_discovery.py`, `file_discovery.py`

GDELT DOC 2.0 is the default source. One query per country using FIPS `sourcecountry` codes (mapped from ISO2 via `ISO2_TO_FIPS` in `src/constants.py`). After GDELT returns results, articles are tagged for relevance against title/URL keywords from `configs/keywords.yaml`. If a country returns nothing, the pipeline retries without `sourcecountry` and injects the country name as a keyword.

Optional sources can run alongside or instead of GDELT:

| Source | Flag | Requires |
|---|---|---|
| BBC Monitoring | `--source bbc` or `both` / `all` | `BBC_MONITORING_USER_*` env vars; auto re-auths on 401 once per run |
| World News API | `--source worldnews` or `all` | `WORLDNEWS_API_KEY`; 60 req/min, 50 points/day on free tier |
| Pre-scraped file | `--source file --file-path <path>` | CSV/JSONL with columns `url, title, text, date, country`. Local or `abfss://...` |

When more than one source is active, results are deduplicated by URL before scraping.

### 2. Scraping — `scraper.py`

Primary: `newspaper4k`. Fallback: `requests` + `BeautifulSoup`. UA rotation, paywall-domain skip list, per-host politeness delays. Up to 16 concurrent workers (`--scrape-workers`). Articles arriving with text already populated (e.g. from `--source file`) skip the network fetch.

### 3. Translation — `translator.py`

`langdetect` to identify the source language, then Google Translate (free tier) for non-native languages. Articles in en/es/fr/pt/ar/sw/hi/ur/id/tl/bn/ha/yo/ig/am skip translation to preserve fidelity. Translation runs **before** the relevance filter so the English-trained DeBERTa NLI classifier scores translated text rather than source-language text.

### 2.5. Relevance filter — `relevance_filter.py`

`cross-encoder/nli-deberta-v3-small` (184 MB, CPU-only) scores each article against a domain-specific hypothesis. Articles below the threshold (default 0.30) are dropped. Batched inference (32 articles per HuggingFace pipeline call). If the model fails to load (no internet, memory pressure), a keyword-only fallback engages and the run summary's `degraded_modes` array is populated with `relevance_filter:keyword_fallback` so the operator is aware. Domain-aware: each domain has its own positive/negative hypothesis.

### 4. LLM extraction — `extractor.py`

The core stage. Two-step disqualifier gate, then field-level extraction.

**Codebook-in-prompt.** The full domain codebook is injected into the system prompt at import time (~22k tokens for protest v2.4). This includes positive examples, boundary negatives, decision rules, edge cases, and African-context modifiers. Validated to yield +8–15 F1 over brief label descriptions (Halterman & Keith 2025).

**Few-shot examples.** A two-tier pool from `configs/<domain>_extraction_examples.yaml`:

| Tier | Behaviour |
|---|---|
| Pinned (`pinned: true`) | Always injected. Currently 8 pinned for protest, covering all 8 event types plus one negative case. |
| Rotatable | Annotator-promoted corrections; rotated in by run-stable random sample. |

`--examples-sample-n` (default 5) sets the total. Pinned examples are a floor — `sample_n=5` with 8 pinned still injects all 8.

**Prompt caching.** The system prompt prefix (~29k tokens) is byte-identical across every article in a run. Azure caches it automatically; cached tokens billed at 50%. Run-stable random seed for the rotatable pool keeps the prefix stable across the run.

**Concurrency + safety.** `--workers N` for parallel extraction (default 4). `--rpm-limit` caps RPM (default 450 — ~10% headroom under a 500 RPM Azure deployment). Each successfully extracted URL is appended to `checkpoint.txt`; `--resume` skips them on restart. Articles that fail all retries land in `failures_{run_id}.jsonl`.

### 4.5. Geocoding — `geocoder.py`

Nominatim OSM (free, no API key). Resolves from most to least specific:

1. `venue + city + country` → `geo_accuracy: venue`
2. `city + country` → `geo_accuracy: city`
3. `region + country` → `geo_accuracy: region`
4. `country` → `geo_accuracy: country`

Disk-cached at `data/cache/geocode_cache.json` so repeat lookups are free. Nominatim's 1 req/sec policy is enforced across all workers. Skip with `--no-geocode`.

### 5. Storage — `storage.py`

Writes JSONL, CSV, run summary, dead-letter file, and a cumulative `all_events.jsonl`. Derives `turmoil_level` (high/medium/low) from event type + state response severity. The summary includes `degraded_modes: [...]` so an operator can tell a run completed with a stage running below its intended quality bar.

`--upload-to` writes outputs to cloud storage. Final upload failures **re-raise** so the run exits non-zero (which trips the existing Azure Monitor alert) — the pipeline never "succeeds" silently when nothing landed in ADLS.

### Process — `processing.py`

Optional, runs with `--stage process` or `--stage all`. Reads `data/raw/<domain>/all_events.jsonl`, applies geography filter, deduplicates (country + city fuzzy ≥0.70 + date ±3 days + event type + TF-IDF claims similarity ≥0.20; null-city safe), re-verifies borderline events with chain-of-thought prompting, runs QC. Writes `data/processed/`.

### Predict — `predictions.py`

Optional, runs with `--stage predict`. Applies Prediction-Powered Inference (Angelopoulos et al. 2023) to produce prevalence point estimates with valid confidence intervals that correct for LLM misclassification. Raw averaging of LLM predictions propagates classification error and is methodologically incorrect; PPI is the principled fix.

---

## Domains and codebooks

Active domains registered in `DOMAIN_CONFIGS` (see `src/acquisition/pipeline.py`):

| Domain | Codebook | Status |
|---|---|---|
| `protest` | `configs/protest_codebook.yaml` v2.4 | Production |
| `drone` | `configs/drone_events_codebook.yaml` v1.0 | Research prototype — acceptable for monitoring, not for automated reporting |
| `violent_extremism` | `configs/violent_extremism_codebook.yaml` v1.0 | **Intentionally not registered.** Codebook + examples files exist but are not validated against ground truth. Use `--codebook` / `--examples` for ad-hoc runs only. Do not enable in cron until a domain owner signs off and adds an entry to `DOMAIN_CONFIGS`. |

Adding a new domain: drop a codebook + examples YAML pair into `configs/`, add an entry to `DOMAIN_CONFIGS` with the codebook path, examples path, and a default GDELT query. The startup assertion will check the files exist; the `_validate_domains` guard rejects any `--domains` value not in the dict so an operator can't enable an unregistered domain by accident.

---

## Configuration files

| File | Purpose |
|---|---|
| `configs/protest_codebook.yaml` | Codebook v2.4 — 8 protest event types with positive/negative examples, decision rules, non-event disqualifiers, African context (Algeria/Hirak section, civic-space confidence modifier), confidence guidance |
| `configs/drone_events_codebook.yaml` | Drone/UAV codebook — parallel structure |
| `configs/violent_extremism_codebook.yaml` | VE codebook (research only — not in `DOMAIN_CONFIGS`) |
| `configs/extraction_examples.yaml` | 8 pinned few-shot examples covering every protest event type + one negative; promoted corrections appended over time |
| `configs/drone_extraction_examples.yaml` | Few-shot examples for drone domain |
| `configs/violent_extremism_extraction_examples.yaml` | Few-shot for VE (research only) |
| `configs/keywords.yaml` | GDELT GKG themes + 39 multilingual title keywords + URL signals |
| `configs/countries.yaml` | Single source of truth for ISO2/ISO3/FIPS/name/aliases (48 countries — 34 Africa + 14 others) |

The pipeline asserts the protest codebook, examples, keywords, and countries files exist at startup (`_REQUIRED_CONFIGS` in `pipeline.py`). Missing any of them is a hard error — silently losing the codebook would collapse extraction quality without any visible signal, so the pipeline crashes loudly instead.

### Templates for codebook authoring

| File | When to use |
|---|---|
| `configs/extraction_examples_NEW_template.yaml` | Add new few-shot examples. Template enforces full schema + boundary-case field. |
| `configs/protest_codebook_v24_additions_template.yaml` | Reference template documenting the v2.4 changes (already merged) — useful for future v2.5 work as a worked example. |

---

## Annotation + few-shot loop

Label Studio is the review interface. Every annotated correction can be promoted into the few-shot pool, so the next pipeline run extracts against a richer prompt.

```
pipeline run → all_events.jsonl
   │
   ▼
export_for_annotation       (priority tiers: low-conf+high-relevance first)
   │
   ▼
Label Studio                (annotate FP? type? confidence? errors?)
   │
   ▼
import_annotations --promote-to-examples N
   │
   ├─► reviewed_events.jsonl
   ├─► training_data.jsonl                    (→ future QLoRA fine-tuning)
   ├─► annotation_stats.json
   │
   └─► configs/extraction_examples.yaml       (promoted corrections appended)
            │
            ▼
       next pipeline run picks up the richer pool
```

Per-batch workflow:

```bash
# Start Label Studio (first time only)
docker compose -f docker-compose.annotation.yml up -d
# → http://localhost:8080  (paste src/annotation/labeling_config.xml into project settings)

# Per-batch (after each pipeline run)
python -m src.annotation.export_for_annotation \
  --events data/raw/protest/all_events.jsonl \
  --output data/annotation/tasks_$(date +%Y%m%d).json \
  --max-tasks 50 --tiers 1,2

# In Label Studio: import → annotate → export → save as label_studio_export.json

python -m src.annotation.import_annotations \
  --annotations data/annotation/label_studio_export.json \
  --output-dir data/annotation/ \
  --promote-to-examples 3
```

**Priority tiers:** Tier 1 = low confidence + high relevance score (highest training value per hour). Tier 2 = medium confidence (most F1 improvement). Tier 3 = high-confidence spot check (precision monitoring; ~10% sample).

**Promotion ranking:** type-corrected events first, extraction-error events second, longer article text third. De-duplicated by article URL. 2–5 promotions per batch is the sustainable cadence — more and individual corrections take longer to rotate into the prompt.

**Goal:** 200+ reviewed gold pairs to unlock QLoRA fine-tuning. `annotation_stats.json` tracks the running count, plus `false_positive_rate` (target <5% at high confidence) and `type_correction_rate` (a high rate signals codebook boundary ambiguity).

---

## Validation

Automated benchmarks against human-coded gold-standard datasets. No manual annotation required.

| Dataset | Validates | Status | Module |
|---|---|---|---|
| **CEHA** | Relevance filter F1 on African conflict text (500 items, held-out 250) | Available | `src.validation.ceha_validator` |
| **CASE 2021 Task 2** | Relevance filter + event type classification (1,019 snippets, 172 protest-relevant) | Available | `src.validation.case2021_validator` |
| **GLOCON GSC** | End-to-end recall on South Africa (token-level annotation, gold standard) | Pending data access (applied 2026-04-05) | `src.validation.glocon_validator` |
| **ACLED** | End-to-end recall, multi-country | Pending API token | Not yet built |

CEHA and CASE 2021 are the two that work today. Use CEHA to calibrate `--relevance-threshold` (recall is what matters at the default 0.30). Use CASE 2021 in `--mode relevance` for an offline check, or `--mode extraction` (requires LLM) to test event-type classification on the 172 protest-relevant snippets.

```bash
# Clone datasets once
git clone https://github.com/dataminr-ai/CEHA CEHA
git clone https://github.com/emerging-welfare/case-2021-shared-task CASE2021

# CEHA — sweep thresholds to find best F1 operating point
python -m src.validation.ceha_validator \
  --ceha-csv CEHA/data/CEHA_dataset.csv --sweep-thresholds \
  --output data/validation/ceha_sweep.json

# CASE 2021 — relevance mode (no LLM call)
python -m src.validation.case2021_validator \
  --case-tsv CASE2021/task2/test_dataset/test_set_final_release_with_labels.tsv \
  --mode relevance --output data/validation/case2021_relevance_report.json
```

**Recall targets (when GLOCON access lands):**

| Recall | Interpretation |
|---|---|
| ≥ 60% | Acceptable for a GDELT-sourced pipeline |
| 40–60% | Investigate systematic misses by type and country |
| < 40% | Diagnose stage by stage: GDELT → scraper → relevance filter → LLM |

Each validator writes a JSON report with per-country, per-type breakdowns, and (for GLOCON) a `match_records` array explaining each unmatched gold event.

A 20-article hand-coded fixture lives at `tests/fixtures/test_set_v1.json` for fast iteration when changing the codebook or prompt.

---

## CLI reference

```
python -m src.acquisition.pipeline [OPTIONS]

Discovery & scope
  --query TEXT                Keywords for GDELT/World News (space-separated)
  --countries TEXT            ISO2 codes [default: NG,ZA,UG,DZ]
  --days INT                  Lookback window [default: 7]
  --max-articles INT          Per-source cap [default: 50]
  --source TEXT               gdelt | bbc | worldnews | file | both | all
                              [default: gdelt; both = gdelt+bbc;
                               all = gdelt+bbc+worldnews]
  --file-path TEXT            CSV/JSONL with cols url,title,text,date,country
                              (local or abfss://); required for --source file

Domain & codebook
  --domains TEXT              Comma-separated [default: protest]
                              Multi-domain: 'protest,drone'
  --codebook PATH             Override domain default (single-domain only)
  --examples PATH             Override domain default (single-domain only)

LLM
  --provider TEXT             azure [only supported value]
  --model TEXT                Azure deployment name [default: gpt-4.1]
  --api-key TEXT              Override AZURE_FOUNDRY_API_KEY env var

Pipeline control
  --stage TEXT                acquire | process | predict | all [default: acquire]
  --no-translate              Skip translation
  --no-geocode                Skip Nominatim
  --resume                    Skip URLs in checkpoint.txt
  --relevance-threshold FLOAT NLI score floor [default: 0.30]

Few-shot examples
  --examples-sample-n INT     Total examples per run [default: 5]
                              Pinned examples always included; remaining slots
                              filled by run-stable sample from promoted pool

Concurrency
  --workers INT               Extraction workers [default: 4]
  --rpm-limit INT             Azure RPM ceiling [default: 450]
  --scrape-workers INT        Parallel scrape [default: 16]
  --geocode-workers INT       Parallel geocode [default: 4]
  --relevance-batch-size INT  NLI batch size [default: 32]

Backfill
  --backfill-from DATE        YYYY-MM-DD
  --backfill-to DATE          YYYY-MM-DD [default: today]
  --backfill-window-days INT  Days per GDELT query [default: 30]

Output
  --output-dir PATH           [default: data/raw/]
  --upload-to TEXT            abfss://filesystem/prefix or s3://bucket/prefix
```

---

## Methodology

The pipeline implements the [Halterman & Keith (2025)](https://arxiv.org/html/2510.03541v1) framework for LLM-based protest event coding:

- **Type III (stipulative) definitions.** Codebook definitions are precise enough that two reasonable annotators reach the same decision. Vague definitions cannot be compensated for by larger models.
- **Codebook-in-prompt.** Full annotation guidelines injected into the system prompt — validated to yield +8–15 F1 points over brief label descriptions.
- **Prediction-Powered Inference** ([Angelopoulos et al. 2023](https://arxiv.org/abs/2309.08574)) — prevalence estimates with valid confidence intervals that correct for LLM misclassification rates.

---

## Project layout

```
configs/                  Codebooks, few-shot examples, keywords, countries
infra/                    setup.sh + deploy.sh (Azure provisioning)
scripts/
  smoke_extract.py        Live-endpoint smoke test (run by deploy.sh)
src/
  acquisition/            Discovery, scrape, filter, translate, extract, geocode, store
  annotation/             Label Studio export/import + active-learning loop
  validation/             CEHA, CASE 2021, GLOCON validators
  utils/
    logging_context.py    contextvars-based run_id/country/stage/domain on every log line
  web/app.py              Streamlit dashboard
  constants.py            ISO2/ISO3/FIPS tables + country aliases
  metrics.py              Quality reporting helpers
tests/                    pytest unit tests + validator tests
.claude/
  azure-deploy-playbook.md   Step-by-step deploy operator guide
  improvement-guide.md       Codebook + few-shot expansion guidance
  production-followups.md    Outstanding P2/P3 priority items
  implementation-guide.md    (redirect to current docs)
```

---

## Where to look next

| You want to... | Look at |
|---|---|
| Deploy from scratch | [`.claude/azure-deploy-playbook.md`](.claude/azure-deploy-playbook.md) |
| Improve extraction quality | [`.claude/improvement-guide.md`](.claude/improvement-guide.md) |
| See what work is queued | [`.claude/production-followups.md`](.claude/production-followups.md) |
| Understand the codebook | [`configs/protest_codebook.yaml`](configs/protest_codebook.yaml) |
| Add a few-shot example | [`configs/extraction_examples_NEW_template.yaml`](configs/extraction_examples_NEW_template.yaml) |
| Wire a new domain | `DOMAIN_CONFIGS` in [`src/acquisition/pipeline.py`](src/acquisition/pipeline.py) |
| Smoke-test a live deployment | `python scripts/smoke_extract.py` |
| Run the dashboard locally | `streamlit run src/web/app.py` |
