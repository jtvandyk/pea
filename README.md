# Protest Event Analysis (PEA)

Automated pipeline that turns African news coverage into structured, research-ready protest event records. Articles are discovered via GDELT and optional sources, scraped, filtered for relevance, and passed through an Azure-hosted LLM that extracts events against a precise codebook. Output is JSONL/CSV in Azure Data Lake Storage Gen2, refreshed daily.

| | |
|---|---|
| **Codebook** | v2.4 (Halterman & Keith 2025, Type III stipulative definitions) |
| **Target geography** | Nigeria (NG), South Africa (ZA), Uganda (UG), Algeria (DZ) |
| **LLM backend** | Azure AI Foundry (`--model` sets the deployment name; default `gpt-5.4`) |
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
  "claims": ["residents demand hostel repairs", "water and electricity cut"],
  "num_participants": null,
  "state_response": ["police_presence"],
  "arrests": 0,
  "injuries": 0,
  "fatalities": 0,
  "outcome": "ongoing",
  "confidence": "medium",
  "source_url": "https://...",
  "source_domain": "sowetanlive.co.za"
}
```

See [Pipeline Outputs](#pipeline-outputs) for the full field list and output files.

---

## Quickstart

```bash
# clone + install
git clone https://github.com/jtvandyk/pea && cd pea
python -m venv venv && source venv/bin/activate
pip install -r requirements-core.txt

# add credentials
cp .env.example .env   # fill in at minimum AZURE_FOUNDRY_API_KEY + AZURE_OPENAI_ENDPOINT

# run (South Africa, last 7 days, up to 50 articles)
python -m src.acquisition.pipeline --provider azure --countries ZA --days 7 --max-articles 50
```

Output lands in `data/raw/<domain>/`. See [What this produces](#what-this-produces) above.

---

## Production deployment

The full step-by-step operator playbook — including pre-flight checks, Azure provisioning, GitHub Secrets, smoke testing, day-2 hardening, rollback procedures, and a troubleshooting catalogue — lives in [`.claude/deploy.md`](.claude/deploy.md). The summary:

```bash
# 1. Provision Azure resources (one time, ~20 min)
az login && az account set --subscription <id>
./infra/setup.sh                     # creates RG + ACR + ADLS Gen2

# 2. Add GitHub Secrets (one time)
# AZURE_CREDENTIALS, AZURE_FOUNDRY_API_KEY, AZURE_OPENAI_ENDPOINT,
# AZURE_STORAGE_CONNECTION_STRING, ACR_LOGIN_SERVER

# 3. Push to main → CI builds + pushes image to ACR
git push origin main

# 4. Deploy Container Apps Jobs (one time, ~20 min)
export ACR_LOGIN_SERVER=<acr>.azurecr.io
./infra/deploy.sh

# 5. Verify a manual run
az containerapp job start --name pea-daily --resource-group pea-rg
```

---

## Pipeline stages

```
           ┌─────────────────────────────────────────┐
           │  Stage 1: Discovery (shared)              │
           │  GDELT DOC 2.0 → deduplicate by URL      │
           │  [optional] BBC Monitoring                │
           │  [optional] World News API                │
           └────────────────────┬───────────────────┘
                                │
           ┌────────────────────┴───────────────────┐
           │  Stage 2: Scrape + process (shared)       │
           │  newspaper3k / requests+BS4 fallback      │
           │  geography filter • dedup • translation  │
           └────────────────────┬───────────────────┘
                                │
               ┌────────────┴─────────────┐
               │                           │
  ┌────────────┴─────┐  ┌─────────────┴─────┐
  │ Domain: protest         │  │ Domain: drone           │
  │                         │  │ (--domains drone)       │
  │ Stage 2.5: Relevance    │  │ Stage 2.5: Relevance    │
  │ DeBERTa NLI filter      │  │ DeBERTa NLI filter      │
  │                         │  │                         │
  │ Stage 3: LLM extract    │  │ Stage 3: LLM extract    │
  │ protest_codebook.yaml   │  │ drone_codebook.yaml     │
  │                         │  │                         │
  │ Stage 4: Geocode        │  │ Stage 4: Geocode        │
  │ Nominatim OSM           │  │ Nominatim OSM           │
  │                         │  │                         │
  │ Stage 5: Store          │  │ Stage 5: Store          │
  │ data/raw/protest/       │  │ data/raw/drone/         │
  └─────────────────────────┘  └─────────────────────────┘
```

For the single-domain case (`--domains protest`, the default), Stage 2 goes directly into Stage 2.5 → 3 → 4 → 5 with no branching.

---

## Running the pipeline

### Common invocations

```bash
# South Africa, last 30 days (default provider: azure)
python -m src.acquisition.pipeline \
  --provider azure --model gpt-5.4 \
  --countries ZA --days 30 --max-articles 100

# Multiple countries
python -m src.acquisition.pipeline \
  --provider azure --countries NG,ZA,UG,DZ --days 7

# Raise relevance filter threshold (default 0.30 — conservative)
python -m src.acquisition.pipeline \
  --provider azure --countries ZA --days 30 --relevance-threshold 0.50

# Resume after a crash
python -m src.acquisition.pipeline --provider azure --resume

# Multi-domain (protest + drone events, shared discovery)
python -m src.acquisition.pipeline \
  --provider azure --countries ZA --days 30 --domains protest,drone

# Upload to Azure Blob after run
python -m src.acquisition.pipeline \
  --provider azure --upload-to az://my-container/pea/runs

# Historical backfill (parallel workers)
python -m src.acquisition.pipeline \
  --provider azure --countries ZA \
  --backfill-from 2026-01-01 --backfill-to 2026-04-01 \
  --backfill-window-days 30 --workers 4 --rpm-limit 400
```

### Provider reference

| Provider | Default model | Required env vars |
|---|---|---|
| `azure` | `gpt-5.4` | `AZURE_FOUNDRY_API_KEY` + `AZURE_OPENAI_ENDPOINT` |
| `claude` | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |
| `openai` | `gpt-5.4` | `OPENAI_API_KEY` |

`--model` for `azure` is the **deployment name** in your Azure AI Foundry project, not a model family name.

---

## Pipeline stages (detail)

| Stage | What happens |
|-------|-------------|
| 1a. GDELT discovery | One query per country using FIPS `sourcecountry` filter; keywords from `configs/keywords.yaml` |
| 1b. BBC Monitoring | `--source bbc` or `--source both`; requires `BBC_MONITORING_USER_NAME` + `_PASSWORD` |
| 1c. World News API | `--source worldnews`; requires `WORLD_NEWS_API_KEY` |
| 1d. File / ADLS | `--source file --file-source <path>`; ingest pre-fetched article lists |
| 2. Scrape + process | `newspaper3k` + requests/BS4 fallback; geography filter; deduplication; translation |
| 2.5. Relevance filter | DeBERTa zero-shot NLI; domain-aware hypothesis text; keyword fallback if model unavailable |
| 3. LLM extraction | Codebook in SYSTEM_PROMPT (~29k tokens); 3 few-shot examples in USER_PROMPT; prompt caching |
| 4. Geocoding | Nominatim OSM; venue → city → region → country fallback; `--no-geocode` to skip |
| 5. Storage | JSONL + CSV + run summary + dead-letter file; `--upload-to` for ADLS Gen2 |

### Deduplication

The deduplicator in `processing.py` uses:
1. Country (exact)
2. Event type (exact)
3. Date ±3 days
4. City fuzzy match ≥0.70 — **only when both cities are non-null**
5. TF-IDF cosine similarity on claims ≥0.20

`claims_similarity` is recorded in `duplicates_log.jsonl` for auditing.

### Relevance filter

- Default model: `cross-encoder/nli-deberta-v3-small` (184 MB, CPU)
- Default threshold: `0.30` — conservative, prioritises recall
- Raise to `0.50` after validation confirms filter accuracy
- Rejected articles logged with `_relevance_score` for calibration

---

## Pipeline outputs

All written to `data/raw/<domain>/`:

| File | Contents |
|---|---|
| `events_{run_id}.jsonl` | Extracted events (primary output) |
| `events_{run_id}.csv` | Same events, flattened for spreadsheet |
| `summary_{run_id}.json` | Run metadata: counts by country, type, turmoil level |
| `failures_{run_id}.jsonl` | Articles that failed extraction after all retries |
| `all_events.jsonl` | Cumulative append across all runs |
| `checkpoint.txt` | URLs processed — used by `--resume` |

Stage 2 outputs in `data/processed/`, Stage 3 in `data/predictions/`.

---

## Annotation workflow

For building training data toward QLoRA fine-tuning (target: 200+ gold pairs).

```bash
# Start Label Studio
docker compose -f docker-compose.annotation.yml up -d
# Opens at http://localhost:8080

# Export highest-priority tasks (low/medium confidence first)
python -m src.annotation.export_for_annotation \
  --events data/raw/protest/all_events.jsonl \
  --output data/annotation/tasks_$(date +%Y%m%d).json \
  --max-tasks 50 --tiers 1,2

# After annotating in Label Studio, import corrections
python -m src.annotation.import_annotations \
  --annotations data/annotation/label_studio_export.json \
  --output-dir data/annotation/
```

Outputs: `reviewed_events.jsonl`, `training_data.jsonl`, `annotation_stats.json`.

---

## Validation

```bash
# GLOCON (requires data access — applied 2026-04-05)
python -m src.validation.glocon_validator \
  --glocon-dir ~/datasets/glocon/data/south_africa/english \
  --pea-events data/processed/events_consolidated.jsonl \
  --output data/validation/recall_report_glocon.json

# CEHA
python -m src.validation.ceha_validator \
  --ceha-dir ~/datasets/ceha \
  --pea-events data/processed/events_consolidated.jsonl

# CASE 2021
python -m src.validation.case2021_validator \
  --case-dir ~/datasets/case2021 \
  --pea-events data/processed/events_consolidated.jsonl
```

**Recall targets:**

| Recall | Status |
|--------|--------|
| ≥ 60% | Acceptable for GDELT-sourced pipeline |
| 40–60% | Investigate misses by type and country |
| < 40% | Diagnose stage by stage |

---

## Code structure

```
src/
  acquisition/
    pipeline.py         Entry point — CLI + 6-stage orchestration
    gdelt_discovery.py  GDELT DOC 2.0 source
    bbc_discovery.py    BBC Monitoring source
    worldnews_discovery.py  World News API source
    file_discovery.py   File / ADLS ingest source
    scraper.py          newspaper3k + fallback
    relevance_filter.py DeBERTa NLI stage 2.5
    extractor.py        LLM extraction (codebook + few-shot injection)
    processing.py       Geography filter, dedup, quality control
    predictions.py      Stage 3 prediction runner
    storage.py          JSONL / CSV / summary / ADLS output
    geocoder.py         Nominatim OSM geocoding
  annotation/
    export_for_annotation.py  Label Studio export
    import_annotations.py     Label Studio import
  validation/
    glocon_validator.py
    ceha_validator.py
    case2021_validator.py
  web/
    app.py              Streamlit dashboard
  constants.py            ISO2/ISO3/FIPS tables + country aliases
  metrics.py              Quality reporting helpers
tests/                    pytest unit tests + validator tests
.claude/
  README.md                  Index of .claude docs (read this first)
  deploy.md                  Step-by-step deploy operator guide
  followups.md               Outstanding P2/P3 priority items
  settings.json              Pre-commit hook (black + flake8)
```

---

## Where to look next

| You want to… | Look at |
|---|---|
| Deploy from scratch | [`.claude/deploy.md`](.claude/deploy.md) |
| See what work is queued | [`.claude/followups.md`](.claude/followups.md) |
| Understand the codebook | [`configs/protest_codebook.yaml`](configs/protest_codebook.yaml) |
| Add a few-shot example | [`configs/extraction_examples_NEW_template.yaml`](configs/extraction_examples_NEW_template.yaml) |
| Wire a new domain | `DOMAIN_CONFIGS` in [`src/acquisition/pipeline.py`](src/acquisition/pipeline.py) |
| Smoke-test a live deployment | `python scripts/smoke_extract.py` |
| Annotate events | `docker compose -f docker-compose.annotation.yml up -d` |
| Validate recall | `python -m src.validation.glocon_validator` |
