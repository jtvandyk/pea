# Protest Event Analysis (PEA)

An automated pipeline for collecting structured protest event data from African news sources. Discovers articles via GDELT and BBC Monitoring, extracts structured protest events using an LLM, and produces research-ready JSONL/CSV datasets with geocoordinates and statistical prevalence estimates.

**Codebook:** v2.3 (Halterman & Keith 2025, Type III stipulative definitions)  
**Target geography:** Nigeria (NG), South Africa (ZA), Uganda (UG), Algeria (DZ)  
**LLM backend:** Claude (default), OpenAI, or Azure AI Foundry — switchable via `--provider`

---

## Pipeline Overview

The pipeline runs in three independent stages. Each stage reads from the previous stage's output directory.

```
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 1 — ACQUIRE                                             acquire│
│                                                                      │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐  │
│  │  1a. GDELT   │    │ 1b. BBC Mon. │    │  2. Scraper          │  │
│  │  DOC 2.0 API │    │  (optional)  │    │  newspaper3k +       │  │
│  │  per-country │ ──►│              │ ──►│  requests fallback   │  │
│  │  FIPS filter │    │  Civil_unrest│    │  user-agent rotation │  │
│  └──────────────┘    │  topic filter│    └──────────┬───────────┘  │
│                      └──────────────┘               │              │
│                                                      ▼              │
│  ┌──────────────────────────────┐    ┌──────────────────────────┐  │
│  │  4. LLM Extraction (Claude)  │◄───│  3. Translation          │  │
│  │  Codebook v2.3 in SYSTEM     │    │  langdetect + Google     │  │
│  │  Few-shot examples in USER   │    │  Translate (free tier)   │  │
│  │  JSON array output           │    │  Native langs: skip      │  │
│  └──────────────┬───────────────┘    └──────────────────────────┘  │
│                 │                                                    │
│                 ▼                                                    │
│  ┌──────────────────────────────┐    ┌──────────────────────────┐  │
│  │  4.5 Geocoding               │    │  5. Storage              │  │
│  │  Nominatim (OSM)             │ ──►│  data/raw/               │  │
│  │  venue → city → region →     │    │  JSONL + CSV + summary   │  │
│  │  country fallback            │    │  + dead-letter file      │  │
│  └──────────────────────────────┘    └──────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 2 — PROCESS                                            process│
│                                                                      │
│  data/raw/all_events.jsonl                                           │
│       │                                                              │
│       ├─► Geography filter (remove off-target countries)            │
│       ├─► Deduplication (country + city + date ±2 days + type)      │
│       ├─► LLM re-verification of medium/low confidence events        │
│       └─► Quality control → data/processed/                         │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 3 — PREDICT                                            predict│
│                                                                      │
│  data/processed/events_consolidated.jsonl                            │
│       │                                                              │
│       ├─► Prevalence estimates per country + event type              │
│       ├─► Prediction-Powered Inference (Angelopoulos et al. 2023)   │
│       │   accounts for LLM misclassification in confidence intervals │
│       └─► data/predictions/                                          │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Quick Start

### 1. Environment

```bash
cp .env.example .env
# Fill in at least one LLM API key
```

```
ANTHROPIC_API_KEY=           # --provider claude (default)
OPENAI_API_KEY=              # --provider openai
AZURE_FOUNDRY_API_KEY=       # --provider azure
AZURE_OPENAI_ENDPOINT=       # --provider azure
AZURE_STORAGE_CONNECTION_STRING=   # --upload-to az://...
```

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements-core.txt
```

### 2. Run

```bash
# Minimal run — South Africa, last 7 days, Claude
python -m src.acquisition.pipeline --countries ZA --days 7

# Multi-country, 30-day window, Azure fallback
python -m src.acquisition.pipeline \
  --provider azure \
  --model gpt-4o-mini \
  --countries NG,ZA,UG,DZ \
  --days 30 \
  --max-articles 200

# Resume after a crash
python -m src.acquisition.pipeline --provider azure --resume

# Run all three stages end-to-end
python -m src.acquisition.pipeline --stage all --countries ZA --days 30
```

### 3. Outputs

| File | Stage | Contents |
|------|-------|----------|
| `data/raw/events_{run_id}.jsonl` | acquire | Extracted protest events (primary) |
| `data/raw/events_{run_id}.csv` | acquire | Same events, spreadsheet-friendly |
| `data/raw/summary_{run_id}.json` | acquire | Run metadata: counts by country, type, turmoil level |
| `data/raw/failures_{run_id}.jsonl` | acquire | Articles that failed all extraction retries |
| `data/raw/all_events.jsonl` | acquire | Cumulative append across all runs |
| `data/raw/checkpoint.txt` | acquire | Processed URLs — used by `--resume` |
| `data/processed/events_consolidated.jsonl` | process | Deduplicated, quality-controlled events |
| `data/processed/quality_report.json` | process | Schema validity + confidence distribution |
| `data/processed/duplicates_log.jsonl` | process | Audit trail of removed duplicates |
| `data/predictions/prevalence_estimates.json` | predict | PPI prevalence by event type and country |
| `data/predictions/confidence_breakdown.json` | predict | High/medium/low confidence distribution |

---

## Stage Detail

### Stage 1a — Discovery (GDELT)

[src/acquisition/gdelt_discovery.py](src/acquisition/gdelt_discovery.py) queries the [GDELT DOC 2.0 API](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/).

**Key design decisions:**

- **Per-country queries with FIPS codes.** The GDELT `sourcecountry` filter requires [FIPS 10-4 codes](https://en.wikipedia.org/wiki/FIPS_10-4), not ISO2. For a list of countries, the pipeline runs one query per country (ISO2 → FIPS via `ISO2_TO_FIPS`) and merges results by URL. This replaces the earlier approach of OR-ing country names into the keyword query, which returned off-target articles mentioning a country in passing.
- **Keyword-based relevance filter.** After GDELT returns results, `filter_protest_relevant()` checks article titles against protest signals loaded from `configs/keywords.yaml`. Articles that pass GDELT's theme filter but have no title signal are retained with `_relevance: gdelt_theme`.
- **Per-country fallback.** If GDELT returns nothing for a given country + FIPS code (occasionally unreliable), the pipeline retries without `sourcecountry` and injects the country name as a keyword for that country only.

**Keywords** are managed in [configs/keywords.yaml](configs/keywords.yaml):
- `protest_themes` — GDELT GKG themes used in the API query
- `protest_signals` — 39 multilingual title keywords (English, Arabic, French, Spanish, Indonesian)
- `url_signals` — URL substring fallback

### Stage 1b — Discovery (BBC Monitoring, optional)

[src/acquisition/bbc_discovery.py](src/acquisition/bbc_discovery.py) queries the BBC Monitoring API using the `Civil_unrest` topic filter and ISO3 country codes. Requires `BBC_MONITORING_USER_NAME` and `BBC_MONITORING_USER_PASSWORD` credentials.

Enable with `--source bbc` or `--source both`. When `--source both`, results from both sources are deduplicated by URL.

### Stage 2 — Scraping

[src/acquisition/scraper.py](src/acquisition/scraper.py) fetches full article text from each discovered URL.

- Primary: `newspaper3k`
- Fallback: `requests` + `BeautifulSoup`
- User-agent rotation to reduce bot detection
- Known paywall domains (NYT, FT, Reuters, etc.) are skipped gracefully

### Stage 3 — Translation

[src/acquisition/translator.py](src/acquisition/translator.py) detects language with `langdetect` and translates to English via Google Translate (free tier).

Languages Claude handles natively (en, es, fr, pt, ar, sw, hi, ur, id, tl, bn, ha, yo, ig, am) skip translation to preserve fidelity and save time.

### Stage 4 — LLM Extraction

[src/acquisition/extractor.py](src/acquisition/extractor.py) is the core of the pipeline.

**Two-step disqualifier gate:**

1. The `SYSTEM_PROMPT` opens with an explicit list of non-protest article types to reject immediately (AU/SADC summits, election results, sports, parliamentary sessions, military parades, inter-communal mob violence, etc.). The model returns `[]` without extracting.
2. If the article passes the gate, minimum criteria are applied: at least one collective actor + one claim/grievance + one action.

**Codebook-in-prompt architecture (v2.3):**

The full codebook is injected into the system prompt at import time via `_build_codebook_context()`. This loads [configs/protest_codebook.yaml](configs/protest_codebook.yaml) and formats all 8 event type definitions — including positive examples, boundary negatives, and decision rules — as structured text appended to `SYSTEM_PROMPT`. This approach is validated in the literature to yield +8–15 F1 points over brief label descriptions (Codebook LLMs 2025; arXiv:2502.16377).

**Few-shot examples:**

Three gold-standard examples from [configs/extraction_examples.yaml](configs/extraction_examples.yaml) are prepended to the user prompt before each article. They demonstrate:
1. A Soweto service delivery roadblock → 1 `confrontation` event (Africa-specific protest form, null crowd size handling)
2. An AU summit → `[]` (correct disqualifier gate for the most common African false positive)
3. An ASUU staff strike + student occupation at the same university → 2 separate events (the most common multi-event failure mode)

**Multi-provider support:**

| Provider | Default model | API key env var |
|----------|--------------|-----------------|
| `claude` | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |
| `openai` | `gpt-4o-mini` | `OPENAI_API_KEY` |
| `azure` | `gpt-4o-mini` | `AZURE_FOUNDRY_API_KEY` + `AZURE_OPENAI_ENDPOINT` |

For `--provider azure`, `--model` is the **deployment name** in your Azure AI Foundry project.

**Checkpoint / resume:** Each successfully extracted article URL is appended to `checkpoint.txt`. Pass `--resume` to skip already-processed URLs after a crash or container restart.

**Dead-letter file:** Articles that fail all extraction retries are written to `failures_{run_id}.jsonl` for manual review or reprocessing.

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

### Stage 2 — Processing

[src/acquisition/processing.py](src/acquisition/processing.py) reads `data/raw/all_events.jsonl` and produces a clean dataset.

Steps:
1. Geography filter — removes events outside the target country list
2. Deduplication — deterministic rules: same country + city + date (±2 days) + event type
3. LLM re-verification — borderline medium/low confidence events are re-examined with chain-of-thought prompting
4. Quality control — schema validity checks and confidence distribution report

### Stage 3 — Predictions

[src/acquisition/predictions.py](src/acquisition/predictions.py) applies **Prediction-Powered Inference** (Angelopoulos et al. 2023) to generate statistically valid prevalence estimates that account for LLM misclassification rates. PPI is the methodologically correct way to report LLM-derived event frequencies — naive averaging of predictions propagates classification error into the point estimate.

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
| `event_type` | string | One of 8 types (see below) |
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

### Event Types

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
| [configs/protest_codebook.yaml](configs/protest_codebook.yaml) | Codebook v2.3 — 8 event type definitions with positive/negative examples, decision rules, non-event disqualifiers, African context notes, edge cases, state response vocabulary, confidence guidance |
| [configs/extraction_examples.yaml](configs/extraction_examples.yaml) | 3 gold-standard few-shot examples injected into user prompt |
| [configs/keywords.yaml](configs/keywords.yaml) | GDELT GKG themes, protest signal keywords (39, multilingual), URL signals |

---

## Infrastructure

### Docker

```bash
docker build -t pea .
docker run --env-file .env pea --provider azure --countries ZA --days 7
```

The multi-stage Dockerfile uses `requirements-core.txt` (pipeline dependencies only — no GPU packages). ML packages (`torch`, `vllm`, `transformers`) are in `requirements.txt` for local development.

### GitHub Actions

`.github/workflows/docker.yml` builds and pushes the Docker image to Azure Container Registry on every push to `main`. Requires `ACR_LOGIN_SERVER`, `ACR_USERNAME`, and `ACR_PASSWORD` in GitHub Secrets.

### Pending Infrastructure

| Item | Required for |
|------|-------------|
| Anthropic API key | `--provider claude` |
| Azure Container Registry + GitHub Secrets | Docker CI workflow |
| Azure Storage Account | `--upload-to az://...` |
| ACLED API token | Recall validation |

---

## Validation Against ACLED

The pipeline supports recall validation against [ACLED](https://acleddata.com/) using a fuzzy matching approach: same country + date within ±2 days + city similarity ≥ 0.6 (SequenceMatcher). Target threshold is ≥60% recall (GDELT's source network is sparser than ACLED's curated feeds, so PEA finding more events than it misses is expected).

See the ACLED validation plan in [CLAUDE.md](CLAUDE.md) for the step-by-step methodology, including the PEA-to-ACLED event type crosswalk.

---

## Methodology

This pipeline implements the [Halterman & Keith (2025)](https://arxiv.org/html/2510.03541v1) framework for LLM-based protest event coding:

- **Type III (Stipulative) definitions** — codebook definitions are precise enough that reasonable annotators would reach the same decision. Vague definitions cannot be compensated for by larger models.
- **Codebook-in-prompt** — full annotation guidelines injected into the system prompt. Validated to yield +8–15 F1 points over brief label descriptions.
- **Prediction-Powered Inference** ([Angelopoulos et al. 2023](https://arxiv.org/abs/2309.08574)) — prevalence estimates account for LLM misclassification rates with valid confidence intervals. Raw averaging of LLM predictions is methodologically incorrect.

---

## CLI Reference

```
python -m src.acquisition.pipeline [OPTIONS]

Options:
  --query TEXT         Keywords (space-separated) [default: "protest demonstration strike rally march"]
  --countries TEXT     ISO2 codes, comma-separated [default: NG,ZA,UG,DZ]
  --days INT           Lookback window in days [default: 7]
  --max-articles INT   Article cap [default: 50]
  --output-dir PATH    Output directory [default: data/raw/]
  --provider TEXT      LLM: claude | openai | azure [default: claude]
  --model TEXT         Model/deployment name override
  --api-key TEXT       API key override (defaults to env var)
  --source TEXT        Discovery source: gdelt | bbc | both [default: gdelt]
  --stage TEXT         acquire | process | predict | all [default: acquire]
  --no-translate       Skip translation step
  --no-geocode         Skip Nominatim geocoding
  --resume             Skip already-processed URLs (reads checkpoint.txt)
  --upload-to TEXT     Cloud destination: az://container/prefix or s3://bucket/prefix
```
