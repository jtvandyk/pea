# CLAUDE.md — PEA Project Context

## Project Overview

Protest Event Analysis (PEA) pipeline. Discovers news articles via GDELT DOC 2.0 API and BBC Monitoring, scrapes + translates, filters for relevance, extracts structured protest events via an LLM backend, and stores results as JSONL/CSV.

**Codebook version:** 2.3 (Halterman & Keith 2025, Type III)
**LLM backend:** Azure AI Foundry only (`AZURE_FOUNDRY_API_KEY` + `AZURE_OPENAI_ENDPOINT`)
**Target geography:** African countries (NG, ZA, UG, DZ)
**Current branch:** `dev` (all recent improvements here; `main` is stable)
**Python:** 3.9 (venv at `venv/`) — `X | Y` union syntax requires 3.10+, use `Optional[X]` instead

---

## Key Files

| File | Purpose |
|------|---------|
| `configs/protest_codebook.yaml` | Codebook v2.3 — 8 event types with positive/negative examples, decision rules, non-event disqualifiers, African context, edge cases, state response vocabulary, confidence guidance |
| `configs/extraction_examples.yaml` | 3 gold-standard few-shot examples injected into every user prompt |
| `configs/keywords.yaml` | GDELT GKG themes, protest signal keywords (39, multilingual), URL signals — edit here not in source |
| `src/acquisition/pipeline.py` | Entry point — 6-stage pipeline (discover → scrape → **relevance filter** → translate → extract → store) |
| `src/acquisition/extractor.py` | LLM extraction — codebook v2.3 injected into SYSTEM_PROMPT, few-shot examples in USER_PROMPT, prompt caching logging |
| `src/acquisition/gdelt_discovery.py` | GDELT DOC 2.0 API — **one query per country** using FIPS `sourcecountry` filter; keywords from `configs/keywords.yaml` |
| `src/acquisition/relevance_filter.py` | Stage 2.5 — zero-shot NLI classifier (DeBERTa) rejects non-protest articles before LLM; keyword fallback if model unavailable |
| `src/acquisition/processing.py` | Stage 2 processing — geography filter, **improved deduplicator** (TF-IDF claims similarity + fixed null-city logic), LLM re-verification, quality control |
| `src/acquisition/storage.py` | Output — JSONL, CSV, run summary JSON, `_derive_turmoil_level()` |
| `src/validation/glocon_validator.py` | Benchmark PEA output against GLOCON GSC (recall by type + country) — awaiting GLOCON data access |
| `src/annotation/export_for_annotation.py` | Export prioritised events to Label Studio JSON (active learning tier 1/2 first) |
| `src/annotation/import_annotations.py` | Import Label Studio export → `reviewed_events.jsonl` + `training_data.jsonl` |
| `src/annotation/labeling_config.xml` | Label Studio labeling interface XML — paste into project settings |
| `docker-compose.annotation.yml` | Runs Label Studio at localhost:8080 for annotation workflow |
| `Dockerfile` | Multi-stage build using `requirements-core.txt` |
| `.github/workflows/docker.yml` | CI — builds and pushes Docker image to ACR on push to `main` |

---

## Environment

`.env` file (never commit) — template:
```
ANTHROPIC_API_KEY=        # --provider claude
OPENAI_API_KEY=           # --provider openai
AZURE_FOUNDRY_API_KEY=    # --provider azure (active fallback)
AZURE_OPENAI_ENDPOINT=    # --provider azure (e.g. https://<resource>.openai.azure.com/openai/v1)
AZURE_STORAGE_CONNECTION_STRING=  # --upload-to az://...
BBC_MONITORING_USER_NAME=         # --source bbc or both
BBC_MONITORING_USER_PASSWORD=     # --source bbc or both
```

---

## Running the Pipeline

```bash
# Standard run — Azure AI Foundry, South Africa, 30 days
python -m src.acquisition.pipeline \
  --provider azure \
  --model gpt-4o-mini \
  --countries ZA \
  --days 30 \
  --max-articles 100

# Multi-country
python -m src.acquisition.pipeline \
  --provider azure \
  --countries NG,ZA,UG,DZ \
  --days 7

# Adjust relevance filter threshold (default 0.30 — conservative/high recall)
python -m src.acquisition.pipeline \
  --provider azure --countries ZA --days 30 \
  --relevance-threshold 0.50

# Resume after a crash
python -m src.acquisition.pipeline --provider azure --resume

# Run all three stages (acquire → process → predict)
python -m src.acquisition.pipeline --stage all --countries ZA --days 30

# Upload outputs to Azure Blob after run
python -m src.acquisition.pipeline --provider azure \
  --upload-to az://my-container/pea/runs
```

**Provider defaults:**
| Provider | Default model | API key env var |
|---|---|---|
| `claude` | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |
| `openai` | `gpt-4o-mini` | `OPENAI_API_KEY` |
| `azure` | `gpt-4o-mini` | `AZURE_FOUNDRY_API_KEY` + `AZURE_OPENAI_ENDPOINT` |

For `--provider azure`, `--model` is the **deployment name** in your Azure AI Foundry project.

---

## Pipeline Stages

| Stage | What happens |
|-------|-------------|
| 1a. GDELT discovery | One query per country using FIPS `sourcecountry` filter; merges results by URL |
| 1b. BBC Monitoring (optional) | `--source bbc` or `--source both`; requires credentials |
| 2. Scraping | `newspaper3k` + requests/BS4 fallback; paywall domains skipped |
| 2.5. Relevance filter | DeBERTa zero-shot NLI rejects non-protest articles; keyword fallback if model unavailable; `--relevance-threshold` controls sensitivity |
| 3. Translation | `langdetect` + Google Translate; native Claude languages (en/fr/ar/sw/etc.) skip translation |
| 4. LLM extraction | Codebook v2.3 in SYSTEM_PROMPT (~29k tokens); 3 few-shot examples in USER_PROMPT; prompt caching saves ~36% on cached prefix |
| 4.5. Geocoding | Nominatim OSM; venue → city → region → country fallback; `--no-geocode` to skip |
| 5. Storage | JSONL + CSV + summary + dead-letter file; `--upload-to` for cloud |

---

## Pipeline Outputs

All written to `data/raw/`:

| File | Contents |
|---|---|
| `events_{run_id}.jsonl` | Extracted protest events (primary output) |
| `events_{run_id}.csv` | Same events, flattened for spreadsheet |
| `summary_{run_id}.json` | Run metadata: counts by country, type, turmoil level |
| `failures_{run_id}.jsonl` | Articles that failed extraction after all retries |
| `all_events.jsonl` | Cumulative append across all runs |
| `checkpoint.txt` | URLs processed — used by `--resume` |

Stage 2 outputs in `data/processed/`, Stage 3 in `data/predictions/`.

---

## Extraction Quality Architecture

The extractor uses three layers working together:

1. **SYSTEM_PROMPT** — two-step disqualifier gate (non-protest article types → return `[]`) + minimum criteria + extraction rules + state response vocabulary
2. **Codebook injection** — `_build_codebook_context()` loads `configs/protest_codebook.yaml` at import time and appends all 8 event type definitions (positive examples, boundary negatives, decision rules) to SYSTEM_PROMPT. ~22k tokens. This is the dominant input token cost driver.
3. **Few-shot examples** — `_build_few_shot_examples()` loads `configs/extraction_examples.yaml` and prepends 3 gold-standard article → JSON pairs to every user prompt. ~6k tokens.

**Prompt caching:** The system prompt prefix (~29k tokens) is identical across every article in a run. Azure caches it automatically for gpt-4o-mini (>1024 token prefix). Cached tokens billed at 50% input rate. Savings logged at DEBUG level per call.

**Per-call token budget (avg):**
- Input: ~40,000 tokens (system 29k + few-shot 6.4k + article 4.4k)
- Output: ~200 tokens (mix of `[]` and event objects)
- Cost: ~$0.006 per article at gpt-4o-mini standard pricing

---

## Relevance Filter Notes

- Default model: `cross-encoder/nli-deberta-v3-small` (184 MB, CPU)
- Default threshold: `0.30` — conservative, prioritises recall over precision
- Raise to `0.50` after GLOCON/ACLED validation confirms filter accuracy
- If `transformers` is unavailable, falls back to keyword matching (no API needed)
- Rejected articles are logged with their `_relevance_score` — inspect these to calibrate
- `requirements-core.txt` includes `torch` and `transformers`; **note:** pin to CPU wheel in Dockerfile to avoid pulling 2 GB CUDA build (pending fix)

---

## Deduplication Notes

The improved deduplicator in `processing.py` uses:
1. Country (exact)
2. Event type (exact)
3. Date ±3 days (widened from ±2)
4. City fuzzy match ≥0.70 — **only enforced when both cities are non-null** (previous version incorrectly allowed null-city merges across different cities)
5. TF-IDF cosine similarity on claims ≥0.20 — prevents same-city/same-day events with different demands from merging

`claims_similarity` is recorded in `duplicates_log.jsonl` for auditing.

---

## Annotation / Active Learning Workflow

For building training data toward QLoRA fine-tuning (target: 200+ gold pairs).
`_article_text` is now written into every event dict by the extractor, so training pairs are populated correctly.

### First-time setup (once only)

```bash
# Start Label Studio
docker compose -f docker-compose.annotation.yml up -d
# Opens at http://localhost:8080
```

1. Create account at `http://localhost:8080`
2. Create project: "PEA Protest Events"
3. Settings → Labeling Interface → Code tab
4. Paste full contents of `src/annotation/labeling_config.xml`
5. Save

### Per-batch workflow (repeat after each pipeline run)

```bash
# Export highest-priority tasks (low/medium confidence first)
python -m src.annotation.export_for_annotation \
  --events data/raw/all_events.jsonl \
  --output data/annotation/tasks_$(date +%Y%m%d).json \
  --max-tasks 50 \
  --tiers 1,2

# In Label Studio: Import → upload JSON → annotate each task:
#   1. Is this a genuine protest event?
#   2. Correct the event type if wrong
#   3. Correct confidence if wrong
#   4. Flag extraction errors if any
# Export → JSON → save to data/annotation/label_studio_export.json

# Import corrections back
python -m src.annotation.import_annotations \
  --annotations data/annotation/label_studio_export.json \
  --output-dir data/annotation/
```

**Outputs:** `data/annotation/reviewed_events.jsonl`, `training_data.jsonl`, `annotation_stats.json`

Console prints running count toward 200-pair fine-tuning threshold.

### Priority tiers

| Tier | Condition | Why |
|------|-----------|-----|
| 1 (annotate first) | Low confidence + high relevance score | Uncertain but probably real — highest misclassification risk |
| 2 | Medium confidence | Borderline — most F1 improvement per annotation hour |
| 3 (10% spot-check) | High confidence | Precision monitoring only |

---

## Validation

Automated benchmark — no manual annotation. Run against `data/processed/events_consolidated.jsonl` (deduplicated) for the cleanest recall number.

```bash
# GLOCON (awaiting data access — applied 2026-04-05)
# Download dataset to somewhere outside the repo first:
#   git clone <glocon-url> ~/datasets/glocon
python -m src.validation.glocon_validator \
  --glocon-dir ~/datasets/glocon/data/south_africa/english \
  --pea-events data/processed/events_consolidated.jsonl \
  --output data/validation/recall_report_glocon.json

# ACLED (register at acleddata.com — free for researchers, token by email)
# acled_validator.py not yet built — blocked on token
python -m src.validation.acled_validator \
  --countries ZA \
  --start-date 2026-01-01 \
  --end-date 2026-03-31 \
  --pea-events data/processed/events_consolidated.jsonl \
  --output data/validation/recall_report_acled.json
```

**Recall targets:**

| Recall | Status |
|--------|--------|
| ≥ 60% | Acceptable for GDELT-sourced pipeline |
| 40–60% | Investigate misses by type and country |
| < 40% | Diagnose stage by stage: GDELT → scraper → relevance filter → LLM |

The JSON report includes a `match_records` array (one entry per gold event) for diagnosing specific misses.

---

## Pending Infrastructure

| Item | Needed for |
|---|---|
| Anthropic API key recovery | `--provider claude` |
| Azure Container Registry + GitHub Secrets | Docker CI workflow |
| Azure Storage Account | `--upload-to az://...` |
| ACLED API token | `acled_validator.py` validation |
| GLOCON data access | `glocon_validator.py` (applied 2026-04-05) |

---

## Known Issues / Pending Code Fixes

| Issue | File | Notes |
|---|---|---|
| `_article_text` not written to event dicts | `extractor.py`, `storage.py` | Breaks annotation training pair generation |
| `torch` in requirements-core.txt pulls CUDA build | `Dockerfile` | Need to pin CPU wheel URL explicitly |
| ACLED validator not yet built | `src/validation/` | Unblocked — ACLED token needed |

---

## Improvement History

| Date | What |
|------|------|
| 2026-03-28 | All 7 production-readiness improvements complete (Docker, dotenv, JSON logging, cloud storage, checkpoint/resume, dead-letter, CI) |
| 2026-04-04 | Codebook v2.3: boundary negatives, decision rules, African context expansion, new state_response vocabulary, civic space confidence modifier |
| 2026-04-04 | Codebook injection into SYSTEM_PROMPT (Steps 1–3) |
| 2026-04-04 | Few-shot examples YAML + injection into USER_PROMPT (Steps 4–5) |
| 2026-04-04 | Keywords moved to `configs/keywords.yaml`; per-country GDELT queries (Steps 6–7) |
| 2026-04-05 | Prompt caching logging in `_call_azure` |
| 2026-04-05 | ConfliBERT relevance filter (Stage 2.5) |
| 2026-04-05 | Improved deduplicator (TF-IDF claims similarity, null-city fix, ±3 day window) |
| 2026-04-05 | GLOCON validator (`src/validation/glocon_validator.py`) |
| 2026-04-05 | Active learning annotation pipeline (Label Studio + export/import scripts) |
