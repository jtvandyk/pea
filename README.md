# Protest Event Analysis (PEA)

An automated pipeline for collecting structured protest event data from African news sources. Discovers articles via GDELT and BBC Monitoring, extracts structured protest events using an LLM, and produces research-ready JSONL/CSV datasets with geocoordinates and statistical prevalence estimates.

**Codebook:** v2.3 (Halterman & Keith 2025, Type III stipulative definitions)  
**Target geography:** Nigeria (NG), South Africa (ZA), Uganda (UG), Algeria (DZ)  
**LLM backend:** Azure AI Foundry (`AZURE_FOUNDRY_API_KEY` + `AZURE_OPENAI_ENDPOINT`)

---

## Pipeline Overview

The pipeline runs in three independent stages. Each stage reads from the previous stage's output directory.

```
┌──────────────────────────────────────────────────────────────────────┐
│  STAGE 1 — ACQUIRE                                             acquire│
│                                                                       │
│  ┌──────────────┐    ┌──────────────┐    ┌───────────────────────┐  │
│  │  1a. GDELT   │    │ 1b. BBC Mon. │    │  2. Scraper           │  │
│  │  DOC 2.0 API │    │  (optional)  │    │  newspaper3k +        │  │
│  │  per-country │ ──►│              │ ──►│  requests fallback    │  │
│  │  FIPS filter │    │  Civil_unrest│    │  user-agent rotation  │  │
│  └──────────────┘    │  topic filter│    └───────────┬───────────┘  │
│                      └──────────────┘                │               │
│                                                       ▼               │
│                                         ┌───────────────────────┐   │
│                                         │  2.5 Relevance Filter │   │
│                                         │  DeBERTa zero-shot NLI│   │
│                                         │  per-domain threshold  │   │
│                                         │  keyword fallback      │   │
│                                         └───────────┬───────────┘   │
│                                                      │               │
│  ┌───────────────────────────────┐    ┌─────────────▼─────────────┐ │
│  │  4. LLM Extraction            │◄───│  3. Translation           │ │
│  │  Azure AI Foundry             │    │  langdetect + Google      │ │
│  │  Codebook v2.3 in SYSTEM      │    │  Translate (free tier)    │ │
│  │  Few-shot examples in USER    │    │  Native langs: skip       │ │
│  │  Prompt caching (~36% saving) │    └───────────────────────────┘ │
│  └───────────────┬───────────────┘                                   │
│                  │                                                    │
│                  ▼                                                    │
│  ┌───────────────────────────────┐    ┌───────────────────────────┐ │
│  │  4.5 Geocoding                │    │  5. Storage               │ │
│  │  Nominatim (OSM)              │ ──►│  data/raw/<domain>/       │ │
│  │  venue → city → region →      │    │  JSONL + CSV + summary    │ │
│  │  country fallback             │    │  + dead-letter file       │ │
│  └───────────────────────────────┘    └───────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘

  Multi-domain mode (--domains protest,drone):
  Stages 1–3 run once (shared scrape + translate), then Stages 2.5–5
  run independently per domain. An article can qualify for both.

┌──────────────────────────────────────────────────────────────────────┐
│  STAGE 2 — PROCESS                                            process │
│                                                                       │
│  data/raw/<domain>/all_events.jsonl                                   │
│       │                                                               │
│       ├─► Geography filter (remove off-target countries)             │
│       ├─► Deduplication (country + city fuzzy ±3 days + type         │
│       │   + TF-IDF claims similarity ≥0.20; null-city safe)          │
│       ├─► LLM re-verification of medium/low confidence events        │
│       └─► Quality control → data/processed/                          │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│  STAGE 3 — PREDICT                                            predict │
│                                                                       │
│  data/processed/events_consolidated.jsonl                             │
│       │                                                               │
│       ├─► Prevalence estimates per country + event type               │
│       ├─► Prediction-Powered Inference (Angelopoulos et al. 2023)    │
│       │   accounts for LLM misclassification in confidence intervals  │
│       └─► data/predictions/                                           │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Quick Start

### 1. Environment

```bash
cp .env.example .env
# Fill in Azure credentials
```

```
AZURE_FOUNDRY_API_KEY=             # required
AZURE_OPENAI_ENDPOINT=             # required (e.g. https://<resource>.openai.azure.com/openai/v1)
AZURE_STORAGE_CONNECTION_STRING=   # optional — --upload-to az://...
BBC_MONITORING_USER_NAME=          # optional — --source bbc or both
BBC_MONITORING_USER_PASSWORD=      # optional — --source bbc or both
```

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements-core.txt
```

### 2. Run

```bash
# Minimal — South Africa, last 7 days
python -m src.acquisition.pipeline --countries ZA --days 7

# Multi-country, 30-day window
python -m src.acquisition.pipeline \
  --model gpt-4.1 \
  --countries NG,ZA,UG,DZ \
  --days 30 \
  --max-articles 200

# Adjust relevance filter threshold (default 0.30 — conservative/high recall)
python -m src.acquisition.pipeline --countries ZA --days 30 \
  --relevance-threshold 0.50

# Multi-domain: scrape once, extract protest events AND drone events
python -m src.acquisition.pipeline \
  --domains protest,drone \
  --countries NG,ZA,UG,DZ \
  --days 7

# Historical backfill with concurrent workers
python -m src.acquisition.pipeline \
  --domains protest \
  --countries ZA \
  --backfill-from 2025-01-01 --backfill-to 2025-12-31 \
  --workers 8 --rpm-limit 450

# Resume after a crash
python -m src.acquisition.pipeline --resume

# Run all three stages end-to-end
python -m src.acquisition.pipeline --stage all --countries ZA --days 30

# Upload outputs to Azure Blob after run
python -m src.acquisition.pipeline \
  --upload-to az://my-container/pea/runs
```

### 3. Outputs

Output is written to `data/raw/<domain>/` (domain defaults to `protest`).

| File | Stage | Contents |
|------|-------|----------|
| `data/raw/<domain>/events_{run_id}.jsonl` | acquire | Extracted protest events (primary) |
| `data/raw/<domain>/events_{run_id}.csv` | acquire | Same events, spreadsheet-friendly |
| `data/raw/<domain>/summary_{run_id}.json` | acquire | Run metadata: counts by country, type, turmoil level |
| `data/raw/<domain>/failures_{run_id}.jsonl` | acquire | Articles that failed all extraction retries |
| `data/raw/<domain>/all_events.jsonl` | acquire | Cumulative append across all runs |
| `data/raw/<domain>/checkpoint.txt` | acquire | Processed URLs — used by `--resume` |
| `data/processed/events_consolidated.jsonl` | process | Deduplicated, quality-controlled events |
| `data/processed/quality_report.json` | process | Schema validity + confidence distribution |
| `data/processed/duplicates_log.jsonl` | process | Audit trail of removed duplicates |
| `data/predictions/prevalence_estimates.json` | predict | PPI prevalence by event type and country |
| `data/predictions/confidence_breakdown.json` | predict | High/medium/low confidence distribution |

---

## Stage Detail

### Stage 1a — Discovery (GDELT)

[src/acquisition/gdelt_discovery.py](src/acquisition/gdelt_discovery.py) queries the [GDELT DOC 2.0 API](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/).

- **Per-country queries with FIPS codes.** The GDELT `sourcecountry` filter requires FIPS 10-4 codes. The pipeline runs one query per country (ISO2 → FIPS via `ISO2_TO_FIPS`) and merges results by URL.
- **Keyword-based relevance filter.** After GDELT returns results, `filter_protest_relevant()` checks article titles against protest signals loaded from `configs/keywords.yaml`.
- **Per-country fallback.** If GDELT returns nothing for a given country + FIPS code, the pipeline retries without `sourcecountry` and injects the country name as a keyword.

Keywords are managed in [configs/keywords.yaml](configs/keywords.yaml):
- `protest_themes` — GDELT GKG themes used in the API query
- `protest_signals` — 39 multilingual title keywords (English, Arabic, French, Spanish, Indonesian)
- `url_signals` — URL substring fallback

### Stage 1b — Discovery (BBC Monitoring, optional)

[src/acquisition/bbc_discovery.py](src/acquisition/bbc_discovery.py) queries BBC Monitoring using the `Civil_unrest` topic filter and ISO3 country codes. Requires `BBC_MONITORING_USER_NAME` and `BBC_MONITORING_USER_PASSWORD`.

Enable with `--source bbc` or `--source both`. When `--source both`, results are deduplicated by URL before scraping.

### Stage 2 — Scraping

[src/acquisition/scraper.py](src/acquisition/scraper.py) fetches full article text.

- Primary: `newspaper3k`
- Fallback: `requests` + `BeautifulSoup`
- User-agent rotation to reduce bot detection
- Known paywall domains (NYT, FT, Reuters, etc.) are skipped gracefully

### Stage 2.5 — Relevance Filter

[src/acquisition/relevance_filter.py](src/acquisition/relevance_filter.py) rejects off-topic articles before they reach the LLM, reducing cost and noise.

- **Model:** `cross-encoder/nli-deberta-v3-small` (184 MB, CPU-only)
- **Default threshold:** `0.30` — conservative, prioritises recall over precision
- **Domain-aware:** the hypothesis text changes per domain (`protest` vs `drone`)
- **Fallback:** keyword matching if `transformers` is unavailable
- **In multi-domain mode**, each domain runs its own filter independently against the shared scraped corpus
- Rejected articles are logged with their `_relevance_score` for threshold calibration
- Raise to `0.50` after GLOCON/ACLED validation confirms filter accuracy

### Stage 3 — Translation

[src/acquisition/translator.py](src/acquisition/translator.py) detects language with `langdetect` and translates to English via Google Translate (free tier).

Languages handled natively (en, es, fr, pt, ar, sw, hi, ur, id, tl, bn, ha, yo, ig, am) skip translation to preserve fidelity and save time.

### Stage 4 — LLM Extraction

[src/acquisition/extractor.py](src/acquisition/extractor.py) is the core of the pipeline.

**LLM backend:** Azure AI Foundry only. The `--model` flag sets the deployment name in your Azure AI Foundry project (default: `gpt-4.1`).

**Two-step disqualifier gate:**

1. The `SYSTEM_PROMPT` opens with an explicit list of non-protest article types to reject immediately (AU/SADC summits, election results, sports, parliamentary sessions, etc.). The model returns `[]` without extracting.
2. If the article passes the gate, minimum criteria are applied: at least one collective actor + one claim/grievance + one action.

**Codebook-in-prompt architecture (v2.3):**

The full codebook is injected into the system prompt at import time via `_build_codebook_context()`. This loads the appropriate domain codebook YAML and formats all event type definitions — including positive examples, boundary negatives, and decision rules. ~22k tokens. This approach yields +8–15 F1 points over brief label descriptions (Halterman & Keith 2025; arXiv:2502.16377).

| Config file | Domain |
|-------------|--------|
| `configs/protest_codebook.yaml` | `protest` — 8 protest event types |
| `configs/drone_events_codebook.yaml` | `drone` — drone/UAV incident types |

**Few-shot examples:**

Three gold-standard examples from the domain examples YAML are prepended to every user prompt:
- `configs/extraction_examples.yaml` (protest domain)
- `configs/drone_extraction_examples.yaml` (drone domain)

**Prompt caching:** The system prompt prefix (~29k tokens) is identical across every article in a run. Azure caches it automatically for gpt-4.1 (>1024 token prefix). Cached tokens are billed at 50% of the input rate — approximately 36% overall cost reduction.

**Concurrent workers:** Use `--workers N` for parallel extraction during backfill runs. All workers share one system prompt so prompt caching is maximised. Use `--rpm-limit` to stay under your Azure quota (default: 450 RPM, ~10% headroom under a 500 RPM deployment limit).

**Checkpoint / resume:** Each successfully extracted article URL is appended to `checkpoint.txt`. Pass `--resume` to skip already-processed URLs after a crash.

**Dead-letter file:** Articles that fail all extraction retries are written to `failures_{run_id}.jsonl`.

### Stage 4.5 — Geocoding

[src/acquisition/geocoder.py](src/acquisition/geocoder.py) converts location fields to latitude/longitude using the [Nominatim OSM API](https://nominatim.org/) (free, no API key required).

Geocoding is attempted from most to least specific:
1. `venue + city + country` → `geo_accuracy: venue`
2. `city + country` → `geo_accuracy: city`
3. `region + country` → `geo_accuracy: region`
4. `country` → `geo_accuracy: country`

Nominatim rate limit (1 req/sec) is enforced. Skip with `--no-geocode`.

### Stage 5 — Storage

[src/acquisition/storage.py](src/acquisition/storage.py) writes JSONL, CSV, and a run summary JSON. It also derives a `turmoil_level` field (high/medium/low) from event type and state response severity.

Optional cloud upload via `--upload-to`:
- `az://container/prefix` — Azure Blob Storage (`AZURE_STORAGE_CONNECTION_STRING`)
- `s3://bucket/prefix` — AWS S3 (`boto3`)

### Stage 2 (outer) — Processing

[src/acquisition/processing.py](src/acquisition/processing.py) reads `data/raw/<domain>/all_events.jsonl` and produces a clean dataset.

1. **Geography filter** — removes events outside the target country list
2. **Deduplication** — same country + city fuzzy match ≥0.70 + date ±3 days + event type; city matching only enforced when both cities are non-null (null-city safe); TF-IDF cosine similarity on claims ≥0.20 prevents same-city/same-day events with different demands from merging; `claims_similarity` recorded in `duplicates_log.jsonl`
3. **LLM re-verification** — borderline medium/low confidence events re-examined with chain-of-thought prompting
4. **Quality control** — schema validity checks and confidence distribution report

### Stage 3 (outer) — Predictions

[src/acquisition/predictions.py](src/acquisition/predictions.py) applies **Prediction-Powered Inference** (Angelopoulos et al. 2023) to generate statistically valid prevalence estimates that account for LLM misclassification rates. Raw averaging of LLM predictions propagates classification error into the point estimate and is methodologically incorrect.

---

## Multi-Codebook Pipeline

The `--domains` flag enables processing multiple event codebooks in a single invocation. Articles are scraped and translated once, then routed through each domain's relevance filter and extractor independently.

```
Shared:   Discovery → Scraping → Translation
               │
     ┌─────────┴──────────┐
     ▼                    ▼
  protest domain       drone domain
  2.5 Filter           2.5 Filter
  4. Extraction        4. Extraction
  4.5 Geocoding        4.5 Geocoding
  5. Storage           5. Storage
  data/raw/protest/    data/raw/drone/
```

An article can qualify for multiple domains — for example, a protest dispersed with a surveillance drone passes both relevance filters.

**Supported domains:**

| Domain | Codebook | Default query |
|--------|----------|---------------|
| `protest` | `configs/protest_codebook.yaml` | `protest demonstration strike rally march` |
| `drone` | `configs/drone_events_codebook.yaml` | `drone UAV airstrike unmanned aircraft` |

Use `--codebook` and `--examples` to supply a custom codebook YAML when running a single domain. These flags are not supported in multi-domain mode.

---

## Historical Backfill

Use `--backfill-from` / `--backfill-to` to run the pipeline over a historical date range, processing one window at a time.

```bash
python -m src.acquisition.pipeline \
  --domains protest \
  --countries ZA,NG,UG,DZ \
  --backfill-from 2024-01-01 \
  --backfill-to   2024-12-31 \
  --backfill-window-days 30 \
  --workers 8 \
  --rpm-limit 450 \
  --upload-to az://my-container/pea/backfill
```

- `--backfill-window-days` (default 30) controls how many days each GDELT query spans
- `--workers` parallelises extraction within each window; prompt caching is preserved because all workers share the same system prompt
- `--resume` skips URLs already in `checkpoint.txt`, making restarts safe

---

## Extraction Schema

Each extracted event is a JSON object with the following fields:

| Field | Type | Description |
|-------|------|-------------|
| `event_date` | string \| null | ISO date of event (not article) |
| `country` | string | Country name |
| `city` | string \| null | City or settlement |
| `region` | string \| null | Province, state, or region |
| `venue` | string \| null | Specific location (stadium, university, etc.) |
| `location_notes` | string \| null | Additional location detail |
| `latitude` | float \| null | From geocoder |
| `longitude` | float \| null | From geocoder |
| `geo_accuracy` | string \| null | `venue`, `city`, `region`, or `country` |
| `event_type` | string | One of the codebook types (see below) |
| `organizer` | string \| null | Organising entity, or `unknown` if WhatsApp-mobilised |
| `participant_groups` | array | Groups involved (workers, students, residents, etc.) |
| `claims` | array | Demands or grievances |
| `crowd_size` | string \| null | Reported figure or range |
| `duration` | string \| null | Event duration |
| `state_response` | string \| null | Most severe state action (see vocabulary below) |
| `state_actors` | array | Police, military, etc. |
| `arrests` | string \| null | Number arrested |
| `fatalities` | string \| null | Number killed |
| `injuries` | string \| null | Number injured |
| `outcome` | string \| null | `ongoing`, `dispersed`, `partial_concession`, `full_concession`, `no_concession` |
| `outcome_notes` | string \| null | What was conceded or what happened |
| `article_title` | string \| null | Source article title |
| `article_url` | string \| null | Source article URL |
| `article_date` | string \| null | Article publication date |
| `source_country` | string \| null | Country of the news source |
| `source_language` | string | BCP-47 language code |
| `confidence` | string | `high`, `medium`, or `low` |

### Protest Event Types

| Code | Description |
|------|-------------|
| `demonstration_march` | Organised march or outdoor gathering (permit or not) |
| `strike_boycott` | Work stoppage, general strike, consumer boycott |
| `occupation_seizure` | Sit-in, building occupation, road blockade |
| `confrontation` | Physical confrontation with police or opposing group; burning tyres/vehicles |
| `petition_signature` | Formal petition, open letter, or signature campaign |
| `vigil` | Candlelight vigil or symbolic silent gathering |
| `hunger_strike` | Individual or collective food refusal |
| `riot` | Widespread looting or violence against persons |

### State Response Vocabulary

Standard: `none`, `monitoring`, `dispersal`, `teargas`, `water_cannon`, `rubber_bullets`, `live_ammunition`, `arrests`, `ban`, `curfew`

Extended (from criminalisation of protest literature): `legal_criminalisation`, `anti_terrorism_designation`, `organisational_dissolution`, `non_association_bail`

---

## Configuration Files

| File | Purpose |
|------|---------|
| [configs/protest_codebook.yaml](configs/protest_codebook.yaml) | Codebook v2.3 — 8 protest event type definitions with positive/negative examples, decision rules, non-event disqualifiers, African context notes, edge cases, state response vocabulary, confidence guidance |
| [configs/drone_events_codebook.yaml](configs/drone_events_codebook.yaml) | Drone/UAV event codebook — parallel structure to protest codebook |
| [configs/extraction_examples.yaml](configs/extraction_examples.yaml) | 3 gold-standard few-shot examples for protest extraction |
| [configs/drone_extraction_examples.yaml](configs/drone_extraction_examples.yaml) | Few-shot examples for drone extraction |
| [configs/keywords.yaml](configs/keywords.yaml) | GDELT GKG themes, protest signal keywords (39, multilingual), URL signals |

---

## Infrastructure

### Docker

```bash
docker build -t pea .
docker run --env-file .env pea --countries ZA --days 7
```

The multi-stage Dockerfile uses `requirements-core.txt` (pipeline dependencies only). ML packages (`torch`, `transformers`) are in `requirements.txt` for local development.

> **Note:** `torch` in `requirements-core.txt` currently pulls the CUDA build. Pin to a CPU wheel URL in the Dockerfile for production to avoid a 2 GB image layer.

### GitHub Actions

`.github/workflows/docker.yml` builds and pushes the Docker image to Azure Container Registry on every push to `main`. Requires `ACR_LOGIN_SERVER`, `ACR_USERNAME`, and `ACR_PASSWORD` in GitHub Secrets.

### Pending Infrastructure

| Item | Required for |
|------|-------------|
| Azure Container Registry + GitHub Secrets | Docker CI workflow |
| Azure Storage Account | `--upload-to az://...` |
| ACLED API token | Recall validation (`acled_validator.py` not yet built) |
| GLOCON data access | `glocon_validator.py` (applied 2026-04-05) |

---

## Annotation Workflow (Active Learning Loop)

Builds gold-standard training data for future fine-tuning. Target: 200+ reviewed events to unlock QLoRA fine-tuning.

### First-time setup

```bash
# Start Label Studio (runs at http://localhost:8080)
docker compose -f docker-compose.annotation.yml up -d
```

1. Go to `http://localhost:8080` and create an account
2. Create a new project — name it "PEA Protest Events"
3. Settings → Labeling Interface → Code tab
4. Paste the full contents of [src/annotation/labeling_config.xml](src/annotation/labeling_config.xml)
5. Save

### Per-batch workflow (repeat after each pipeline run)

```bash
# 1. Export highest-priority events (low and medium confidence first)
python -m src.annotation.export_for_annotation \
  --events data/raw/protest/all_events.jsonl \
  --output data/annotation/tasks_$(date +%Y%m%d).json \
  --max-tasks 50 \
  --tiers 1,2

# 2. In Label Studio:
#    Import → upload the tasks JSON
#    Annotate each task (~2 min each):
#      - Is this a genuine protest event?
#      - Is the event type correct? (fix if not)
#      - Is the confidence right?
#      - Flag any specific extraction errors
#    Export → JSON → save to data/annotation/label_studio_export.json

# 3. Import corrections back into the pipeline
python -m src.annotation.import_annotations \
  --annotations data/annotation/label_studio_export.json \
  --output-dir data/annotation/
```

**Outputs written to `data/annotation/`:**

| File | Contents |
|------|----------|
| `reviewed_events.jsonl` | All reviewed events with human corrections applied |
| `training_data.jsonl` | Gold (article text → corrected JSON) pairs for fine-tuning |
| `annotation_stats.json` | False positive rate, type correction rate, running pair count |

### Priority tiers

| Tier | Condition | Why |
|------|-----------|-----|
| 1 (annotate first) | Low confidence + high relevance score | Uncertain but probably real — highest misclassification risk |
| 2 | Medium confidence | Borderline — most F1 improvement per annotation hour |
| 3 (10% spot-check) | High confidence | Precision monitoring only |

---

## Validation

Benchmarks pipeline recall against a gold-standard human-coded dataset. Automated — no manual annotation required. Run against `data/processed/events_consolidated.jsonl` for the cleanest recall number.

### GLOCON GSC

```bash
# Download dataset (requires data access approval from emerging-welfare team)
git clone <glocon-url> ~/datasets/glocon

python -m src.validation.glocon_validator \
  --glocon-dir ~/datasets/glocon/data/south_africa/english \
  --pea-events data/processed/events_consolidated.jsonl \
  --output data/validation/recall_report_glocon.json
```

### ACLED

> **Status:** `acled_validator.py` is not yet built — blocked on obtaining an ACLED API token. Register at [acleddata.com](https://acleddata.com) for a free researcher token.

```bash
python -m src.validation.acled_validator \
  --countries ZA \
  --start-date 2026-01-01 \
  --end-date 2026-03-31 \
  --pea-events data/processed/events_consolidated.jsonl \
  --output data/validation/recall_report_acled.json
```

**Interpreting results:**

| Recall | Interpretation |
|--------|----------------|
| ≥ 60% | Acceptable for GDELT-sourced pipeline |
| 40–60% | Investigate systematic misses by type and country |
| < 40% | Diagnose at each stage: GDELT discovery → scraper → relevance filter → LLM |

The JSON report includes per-event match records so you can inspect exactly which events were missed.

### How annotation and validation connect

```
Pipeline run  →  data/raw/protest/all_events.jsonl
                        │
          ┌─────────────┴──────────────┐
          │                            │
   export_for_annotation          Stage 2 processing
          │                            │
    Label Studio              events_consolidated.jsonl
    (you annotate)                     │
          │                  ┌─────────┴──────────┐
   import_annotations    glocon_validator     acled_validator
          │                  │                     │
   training_data.jsonl    recall vs           recall vs
   (→ fine-tuning)        GLOCON gold         ACLED gold
```

---

## CLI Reference

```
python -m src.acquisition.pipeline [OPTIONS]

Discovery & scope:
  --query TEXT                Keywords for GDELT (space-separated)
  --countries TEXT            ISO2 codes, comma-separated [default: NG,ZA,UG,DZ]
  --days INT                  Lookback window in days [default: 7]
  --max-articles INT          Article cap [default: 50]
  --source TEXT               gdelt | bbc | both [default: gdelt]

Domain & codebook:
  --domains TEXT              Comma-separated codebook domains [default: protest]
                              Use 'protest,drone' for multi-domain mode
  --codebook PATH             Custom codebook YAML (single-domain only)
  --examples PATH             Custom examples YAML (single-domain only)

LLM backend (Azure AI Foundry only):
  --provider TEXT             azure [only supported value]
  --model TEXT                Deployment name [default: gpt-4.1]
  --api-key TEXT              Override AZURE_FOUNDRY_API_KEY env var

Pipeline control:
  --stage TEXT                acquire | process | predict | all [default: acquire]
  --no-translate              Skip translation step
  --no-geocode                Skip Nominatim geocoding
  --resume                    Skip already-processed URLs (reads checkpoint.txt)
  --relevance-threshold FLOAT Minimum NLI score to pass to LLM [default: 0.30]

Concurrency & rate limiting:
  --workers INT               Concurrent extraction workers [default: 1]
  --rpm-limit INT             Azure OpenAI RPM ceiling [default: 450]

Historical backfill:
  --backfill-from DATE        Start date: YYYY-MM-DD
  --backfill-to DATE          End date: YYYY-MM-DD [default: today]
  --backfill-window-days INT  Days per GDELT query window [default: 30]

Output & storage:
  --output-dir PATH           Output directory [default: data/raw/]
  --upload-to TEXT            az://container/prefix or s3://bucket/prefix
```

---

## Methodology

This pipeline implements the [Halterman & Keith (2025)](https://arxiv.org/html/2510.03541v1) framework for LLM-based protest event coding:

- **Type III (Stipulative) definitions** — codebook definitions are precise enough that reasonable annotators would reach the same decision. Vague definitions cannot be compensated for by larger models.
- **Codebook-in-prompt** — full annotation guidelines injected into the system prompt. Validated to yield +8–15 F1 points over brief label descriptions.
- **Prediction-Powered Inference** ([Angelopoulos et al. 2023](https://arxiv.org/abs/2309.08574)) — prevalence estimates account for LLM misclassification rates with valid confidence intervals. Raw averaging of LLM predictions is methodologically incorrect.
