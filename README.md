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
- **Parallel scraping** — up to 16 concurrent workers (configurable via `--scrape-workers`), with per-host politeness delays so no single domain is hit more than once per second

### Stage 2.5 — Relevance Filter

[src/acquisition/relevance_filter.py](src/acquisition/relevance_filter.py) rejects off-topic articles before they reach the LLM, reducing cost and noise.

- **Model:** `cross-encoder/nli-deberta-v3-small` (184 MB, CPU-only)
- **Default threshold:** `0.30` — conservative, prioritises recall over precision
- **Domain-aware:** the hypothesis text changes per domain (`protest` vs `drone`)
- **Fallback:** keyword matching if `transformers` is unavailable
- **In multi-domain mode**, each domain runs its own filter independently against the shared scraped corpus
- **Batched scoring** — all articles scored in a single HuggingFace pipeline call (batch size 32 by default, `--relevance-batch-size`). Substantially faster than per-article inference on a CPU.
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

Gold-standard examples from the domain examples YAML are prepended to every user prompt:
- `configs/extraction_examples.yaml` (protest domain)
- `configs/drone_extraction_examples.yaml` (drone domain)

Examples are selected from a two-tier pool:

| Tier | YAML tag | Behaviour |
|------|----------|-----------|
| Pinned | `pinned: true` | Always injected — the original handwritten curriculum examples, never evicted |
| Rotatable | *(no tag)* | Annotator-promoted corrections that rotate in by random sample each run |

The number of examples per run is controlled by `--examples-sample-n` (default 5). With only the 5 original pinned examples and no promoted ones, this is identical to the previous behaviour. As the promoted pool grows through the annotation workflow, raising `--examples-sample-n` above 5 causes promoted examples to start rotating in.

The random seed is resolved once per run from `time.time_ns()` and held fixed across all articles in that run. This keeps the per-run prompt prefix identical across every article, which is required for Azure prompt caching to hit reliably.

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

Nominatim rate limit (1 req/sec) is enforced across all workers. Results are cached to disk (`data/cache/geocode_cache.json`) so repeated location strings (e.g. "Johannesburg, South Africa") are resolved without a network round-trip. Skip geocoding entirely with `--no-geocode`.

Use `--geocode-workers` to parallelise dispatch; the default is 4 concurrent workers with shared rate-limit enforcement.

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

## Annotation Workflow — Closing the Active Learning Loop

Label Studio is used to review LLM-extracted events, correct them, and feed the corrections back into the extraction prompt as new few-shot examples. Each annotation session directly improves the quality of the next pipeline run — the loop is now fully closed.

**Goal:** 200+ reviewed gold pairs to unlock QLoRA fine-tuning. The annotation workflow builds this dataset incrementally, one batch at a time.

---

### Why Label Studio?

Label Studio provides a structured review interface where every extracted event is presented alongside its source article. The annotator answers four targeted questions per task, and all corrections are exported as structured JSON that the import script can consume automatically.

The interface is pre-configured for this pipeline via [src/annotation/labeling_config.xml](src/annotation/labeling_config.xml) — you do not need to design the interface yourself.

---

### First-time setup (once only)

```bash
# Start Label Studio
docker compose -f docker-compose.annotation.yml up -d
# Opens at http://localhost:8080
```

1. Go to `http://localhost:8080` and create an account
2. Create a new project — name it "PEA Protest Events"
3. **Settings → Labeling Interface → Code tab**
4. Paste the full contents of [src/annotation/labeling_config.xml](src/annotation/labeling_config.xml)
5. Save

The labeling interface shows the source article on the left and the LLM's extracted event JSON on the right.

---

### Per-batch workflow (repeat after each pipeline run)

```bash
# Step 1 — Export the highest-priority events from the latest pipeline run
python -m src.annotation.export_for_annotation \
  --events data/raw/protest/all_events.jsonl \
  --output data/annotation/tasks_$(date +%Y%m%d).json \
  --max-tasks 50 \
  --tiers 1,2
```

```
# Step 2 — In Label Studio:
#   Import → upload the tasks JSON file
#   Annotate each task (target: ~2 min per task)
#   Export → JSON → save to data/annotation/label_studio_export.json
```

```bash
# Step 3 — Import corrections back and promote top corrections into the
#           few-shot examples pool so the next run benefits immediately
python -m src.annotation.import_annotations \
  --annotations data/annotation/label_studio_export.json \
  --output-dir data/annotation/ \
  --promote-to-examples 3
```

The `--promote-to-examples 3` flag is the key step that closes the loop. See [Promotion](#promotion-closing-the-loop) below.

---

### What you're annotating — the four questions

Each Label Studio task presents the source article text alongside the LLM-extracted JSON. You answer four questions:

**1. Is this a genuine protest event?**

The most important check. If the article is not about a protest event at all (election result, parliamentary debate, crime report, sports), mark it as a false positive. These events are filtered out of `reviewed_events.jsonl` and excluded from training data entirely — they are the most damaging failures because they silently inflate event counts.

**2. Is the event type correct?**

Check the `event_type` field against the eight codebook types. The most common errors are:
- `confrontation` vs `riot` (riot requires looting or violence against persons; burning tyres is confrontation)
- `demonstration_march` vs `occupation_seizure` (sit-ins and road blockades are occupations)
- `petition_signature` extracted from an article that describes a march that also presented a petition (classify by the primary action)

If the type is wrong, select the correct one from the dropdown. Type corrections are ranked highest for promotion.

**3. Is the confidence level appropriate?**

`high` = article explicitly describes all three minimum criteria (collective actor + claim/grievance + action).  
`medium` = one criterion is implied or uncertain.  
`low` = substantial ambiguity — the article might be describing a planned or rumoured event.

Correct this if the LLM under- or over-stated certainty.

**4. Are there specific extraction errors?**

Use the free-text field to flag field-level problems: wrong city, missing organiser, incorrect crowd size, misidentified state response, etc. These are recorded in `annotation_stats.json` and inform threshold calibration, but the field-level correction itself is not currently auto-applied — it informs manual codebook improvement.

---

### Priority tiers — who to annotate first

```bash
# Tier 1 + 2 (recommended for most batches)
python -m src.annotation.export_for_annotation \
  --events data/raw/protest/all_events.jsonl \
  --output data/annotation/tasks.json \
  --max-tasks 50 \
  --tiers 1,2

# Tier 3 only (spot-check precision on high-confidence events)
python -m src.annotation.export_for_annotation \
  --events data/raw/protest/all_events.jsonl \
  --output data/annotation/spot_check.json \
  --max-tasks 20 \
  --tiers 3
```

| Tier | Condition | Why annotate |
|------|-----------|--------------|
| 1 | Low confidence + high relevance score | Uncertain but the relevance filter says it's probably real — highest misclassification risk, most training value per hour |
| 2 | Medium confidence | Borderline — most F1 improvement per annotation hour |
| 3 (10% spot-check) | High confidence | Precision monitoring — catch systematic over-extraction without annotating every event |

---

### Promotion — closing the loop

After annotation, run `import_annotations` with `--promote-to-examples N`. This appends up to N annotator-corrected events to `configs/extraction_examples.yaml` as new few-shot entries, ranked by likely teaching value:

1. **Type-corrected events first** — the LLM had the wrong event type; the correction directly teaches the boundary the model is getting wrong
2. **Extraction-error events second** — the annotator flagged field-level problems; useful for schema fidelity
3. **Longest article text third** — all else equal, richer context makes a better example

Each promoted entry is tagged with full provenance:

```yaml
provenance:
  source: label_studio
  task_id: https://www.example.com/article-url
  annotator_id: user@example.com
  date_promoted: 2026-04-22T18:52:57
  type_corrected: true
  had_extraction_errors: false
```

De-duplication is by `task_id` (article URL), so re-running promotion after a second annotation batch never adds duplicates.

**Recommended cadence:** promote 2–5 examples per batch. More than that and the pool grows faster than it rotates through the prompt, so individual corrections take longer to reach the model.

---

### Few-shot rotation — how promoted examples reach the model

The examples file contains two tiers of entries:

| YAML tag | Behaviour |
|----------|-----------|
| `pinned: true` | Always injected into every run — the five original handwritten examples |
| *(no tag)* | Promoted corrections; rotated in by random sample across runs |

The `--examples-sample-n` flag (default 5) sets the total number of examples per run. With only pinned examples and no promoted ones, this preserves the previous behaviour exactly.

Once the promoted pool grows, raise `--examples-sample-n` above 5 to start rotating promoted examples into the prompt:

```bash
# Inject 5 pinned + up to 3 promoted examples per run
python -m src.acquisition.pipeline \
  --countries ZA --days 7 \
  --examples-sample-n 8
```

The rotation seed is resolved once per run and held fixed for all articles. This is important: every article in a given run sees the same example set, which keeps the system-prompt prefix byte-for-byte identical across the run and preserves the Azure prompt cache hit rate.

---

### Outputs

All written to `data/annotation/`:

| File | Contents |
|------|----------|
| `reviewed_events.jsonl` | All reviewed events with human corrections applied |
| `training_data.jsonl` | Gold (article text → corrected JSON) pairs for fine-tuning |
| `annotation_stats.json` | False positive rate, type correction rate, running pair count toward 200 |

`annotation_stats.json` is the main health indicator for the annotation effort. Monitor `false_positive_rate` (should be < 5% at high confidence), `type_correction_rate` (high rates indicate codebook boundary ambiguity), and `training_pairs` (target: 200 before QLoRA fine-tuning).

---

### The full feedback loop

```
Pipeline run
    │
    ▼
data/raw/protest/all_events.jsonl
    │
    ├──► export_for_annotation (tier 1+2 priority)
    │         │
    │         ▼
    │    Label Studio
    │    (annotate: FP? type? confidence? errors?)
    │         │
    │         ▼
    │    label_studio_export.json
    │         │
    │         ▼
    │    import_annotations --promote-to-examples 3
    │         │
    │         ├──► data/annotation/reviewed_events.jsonl
    │         ├──► data/annotation/training_data.jsonl     → future QLoRA fine-tuning
    │         ├──► data/annotation/annotation_stats.json
    │         │
    │         └──► configs/extraction_examples.yaml ◄──────────────────┐
    │                   (promoted corrections appended)                  │
    │                                                                    │
    └──► Next pipeline run                                               │
              │                                                          │
              └──► extractor.py: _build_few_shot_examples()             │
                       pinned (always) + rotatable sample ──────────────┘
                       (--examples-sample-n controls pool size)
```

Each annotation session improves the few-shot pool that the next extraction run draws from. The improvement compounds: better examples → fewer type errors → fewer tier-1/2 events exported for annotation → faster future batches.

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
   (tier 1+2 priority)                 │
          │                    events_consolidated.jsonl
    Label Studio                       │
    (annotate)              ┌──────────┴───────────┐
          │             glocon_validator     acled_validator
   import_annotations       │                      │
   --promote-to-examples  recall vs            recall vs
          │               GLOCON gold          ACLED gold
          │
          ├─► training_data.jsonl (→ fine-tuning)
          └─► configs/extraction_examples.yaml (→ next run's few-shot pool)
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

Few-shot examples:
  --examples-sample-n INT     Total examples injected per run [default: 5]
                              Pinned examples always included; remaining slots
                              filled by run-stable random sample from the
                              promoted pool. Raise above 5 once annotation
                              promotion has grown the pool.

Concurrency & rate limiting:
  --workers INT               Concurrent extraction workers [default: 4]
  --rpm-limit INT             Azure OpenAI RPM ceiling [default: 450]
  --scrape-workers INT        Parallel scrape workers [default: 16]
  --geocode-workers INT       Parallel geocode workers [default: 4]
  --relevance-batch-size INT  NLI inference batch size [default: 32]

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
