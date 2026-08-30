# CLAUDE.md — PEA Project Context

## Project Overview

Protest Event Analysis (PEA) pipeline. Discovers news articles via GDELT DOC 2.0 API and BBC Monitoring, scrapes + translates, filters for relevance, extracts structured events via an LLM backend, and stores results as JSONL/CSV.

**Protest codebook version:** 3.1 (Halterman & Keith 2025, Type III; pan-Africa revision + per-field confidence)
**Registered domains:** protest (production) · drone, violent_extremism, election_events, state_repression (research opt-in — see § Domain registry & rollout gates)
**LLM backend:** Azure AI Foundry only (`AZURE_FOUNDRY_API_KEY` + `AZURE_OPENAI_ENDPOINT`)
**Target geography:** pan-Africa codebook coverage; production cron crawls NG, ZA, UG, DZ (33 African targets registered in `configs/countries.yaml`)
**Current branch:** `dev` (all recent improvements here; `main` is stable)
**Python:** 3.9 (venv at `venv/`) — `X | Y` union syntax requires 3.10+, use `Optional[X]` instead

---

## Key Files

| File | Purpose |
|------|---------|
| `configs/protest_codebook.yaml` | Codebook v3.0 — 8 event types + SCAD-style `issue_taxonomy` (driver tags), extraction_prompt (base system prompt lives in YAML), pan-Africa context (Sahel/Horn/Central/Lusophone), boundary cases (ghost towns, vigilantism, banditry, pro-junta rallies, state-media decoys), ACLED sub-event mapping |
| `configs/extraction_examples.yaml` | 12 pinned few-shot examples (en/fr/pt/am sources; NG/ZA/UG/DZ/MZ/ET) injected into every user prompt |
| `configs/drone_events_codebook.yaml` + `drone_extraction_examples.yaml` | Drone domain v1.0 — 8 event types, own extraction_prompt, 4 pinned Africa anchors (ET/ML/NG) |
| `configs/violent_extremism_codebook.yaml` + `violent_extremism_extraction_examples.yaml` | VE domain v1.1 (GTD-based, 9 attack types, `event_types` schema fixed) — registered research opt-in |
| `configs/election_events_codebook.yaml` + `election_extraction_examples.yaml` | Election events **v2.0 — RESIDUAL extractor** (second-pass architecture): only election-only events with no primary-domain home; primary-domain events get their electoral connection from the nexus pass |
| `configs/state_repression_codebook.yaml` + `state_repression_extraction_examples.yaml` | State repression v1.3 (#KeepItOn/SCAD-based, 6 types incl. internet_shutdown; ITT [A]/[B] rule grades; codes state action vs electoral actors, nexus-tagged) |
| `configs/election_calendar.yaml` | Election-date lookup for the nexus pass (±6-month windows per round). Ships empty — populate from NELDA; empty calendar just disables the calendar basis |
| `src/acquisition/electoral_nexus.py` | Stage 4.75 — tags primary-domain events `electoral_nexus` on calendar_window / issue_tags / keywords bases (plan §4.1, DECO method) |
| `src/acquisition/dissent_repression.py` | Stage 4.8 — NAVCO dual representation: derives linked repression twins from repressive protest `state_response` + links extracted repression events to answered protests via `dissent_repression_pair_id` |
| `src/acquisition/excluded_store.py` | Excluded-cases JSONL store (RTV pattern): relevance-passed, extraction-empty articles — audit trail + fine-tuning hard negatives |
| `configs/keywords.yaml` | GDELT GKG themes; per-domain signal keywords (protest: en/fr/es/ar/sw/yo/ig/pt/am/ha/so; drone, violent_extremism, election, repression sections); URL signals — edit here not in source |
| `src/acquisition/pipeline.py` | Entry point — 6-stage pipeline (discover → scrape → translate → **relevance filter** → extract → store) |
| `src/acquisition/extractor.py` | LLM extraction — per-domain base prompt rendered from the codebook's `extraction_prompt` section (+ event-type definitions injected), few-shot examples in USER_PROMPT, prompt caching logging |
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
  --model gpt-5.4 \
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

# Multi-domain run (research opt-in domains; output isolated per domain
# under data/raw/<domain>/) — see § Domain registry & rollout gates
python -m src.acquisition.pipeline --provider azure \
  --countries ML,BF,NE,NG,ET --days 7 \
  --domains protest,drone
```

**Provider defaults:**
| Provider | Default model | API key env var |
|---|---|---|
| `claude` | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |
| `openai` | `gpt-5.4` | `OPENAI_API_KEY` |
| `azure` | `gpt-5.4` | `AZURE_FOUNDRY_API_KEY` + `AZURE_OPENAI_ENDPOINT` |

For `--provider azure`, `--model` is the **deployment name** in your Azure AI Foundry project.

---

## Pipeline Stages

| Stage | What happens |
|-------|-------------|
| 1a. GDELT discovery | One query per country using FIPS `sourcecountry` filter; merges results by URL |
| 1b. BBC Monitoring (optional) | `--source bbc` or `--source both`; requires credentials |
| 2. Scraping | `newspaper3k` + requests/BS4 fallback; paywall domains skipped |
| 2.5. Relevance filter | DeBERTa zero-shot NLI rejects off-domain articles (per-domain hypothesis + keyword set in `relevance_filter._DOMAIN_CONFIG`); keyword fallback if model unavailable; `--relevance-threshold` controls sensitivity |
| 3. Translation | `langdetect` + Google Translate; native Claude languages (en/fr/ar/sw/etc.) skip translation |
| 4. LLM extraction | Per-domain codebook in SYSTEM_PROMPT (protest v3.0 ≈6.5k tokens est.); pinned few-shot examples in USER_PROMPT; prompt caching saves ~36% on cached prefix |
| 4.5. Geocoding | Nominatim OSM; venue → city → region → country fallback; `--no-geocode` to skip |
| 4.75. Electoral nexus | Mechanical pass (no LLM): tags every non-election-domain event `electoral_nexus` true/false with basis (`calendar_window`/`issue_tags`/`keywords`) and election name |
| 4.8. Dissent–repression linking | Multi-domain runs with protest + state_repression: derives repression twins from repressive `state_response` (flagged `derived_from_protest`) and links extracted repression events to answered protests (same country, ±3 days, compatible city) |
| 5. Storage | JSONL + CSV + summary + dead-letter + excluded-cases files; stamps `validation_status: candidate`; `--upload-to` for cloud. In multi-domain runs storage runs AFTER stage 4.8 |

---

## Pipeline Outputs

All written to `data/raw/`:

| File | Contents |
|---|---|
| `events_{run_id}.jsonl` | Extracted protest events (primary output) |
| `events_{run_id}.csv` | Same events, flattened for spreadsheet |
| `summary_{run_id}.json` | Run metadata: counts by country, type, turmoil level |
| `failures_{run_id}.jsonl` | Articles that failed extraction after all retries |
| `excluded_{run_id}.jsonl` | Excluded cases: articles that passed relevance but the LLM returned `[]` for (RTV pattern) — audit trail + hard negatives for fine-tuning; includes `_article_text`; written per domain dir in multi-domain runs |
| `all_events.jsonl` | Cumulative append across all runs |
| `checkpoint.txt` | URLs processed — used by `--resume` |

Stage 2 outputs in `data/processed/`, Stage 3 in `data/predictions/`.

---

## Extraction Quality Architecture

The extractor uses three layers working together:

1. **Base prompt from YAML** — `_render_extraction_prompt()` renders each codebook's `extraction_prompt` section (persona with templated `{version}`, STEP 1 disqualifiers, STEP 2 minimum criteria, STEP 3 rules with a GENERATED event-type key list, output schema). Codebooks without the section fall back to the legacy protest `_BASE_SYSTEM_PROMPT` byte-identically. All five codebooks carry their own section — non-protest domains no longer inherit the protest persona/schema.
2. **Codebook injection** — `_build_codebook_context()` appends every `event_types` entry's definition, positive/negative examples, and decision rules to SYSTEM_PROMPT. These four sub-keys (plus `metadata.version`) are the ONLY codebook fields injected; everything else reaches the model via `extraction_prompt`.
3. **Few-shot examples** — `_build_few_shot_examples()` prepends pinned + sampled article → JSON pairs to every user prompt (`pinned: true` = always included; rest rotate with a run-stable seed).

**Prompt caching:** The system prompt prefix is identical across every article in a run (per domain). Azure caches it automatically when the prefix exceeds 1024 tokens. Cached tokens billed at 50% input rate. Savings logged at DEBUG level per call.

**Per-call token budget (chars/4 estimate, 2026-07-08 audit — real tokenizer counts run higher; hard target stays ~40k):**

| Domain | System | Few-shot | + article p95 (~4.5k) |
|---|---|---|---|
| protest v3.0 | ~6.5k | ~5.1k | ~16k |
| drone | ~5.0k | ~2.7k | ~12k |
| violent_extremism | ~5.0k | ~1.8k | ~11k |
| election_events | ~3.6k | ~1.6k | ~10k |
| state_repression | ~3.8k | ~1.7k | ~10k |

- Output: ~200 tokens (mix of `[]` and event objects)
- Cost: depends on the deployed model's per-token pricing — measure on a small canary run before scaling up. Re-run `pea-token-audit` after any codebook/examples change.

---

## Domain registry & rollout gates

Five codebook artifacts are registered in `DOMAIN_CONFIGS` (`src/acquisition/pipeline.py`). Registration means runnable via `--domains` — it does NOT mean production.

| Domain | Status | Gate before production cron |
|---|---|---|
| `protest` | **Production** (v3.0) | pea-validate (CEHA + CASE 2021) non-regression vs pre-v3 baseline → canary → deploy |
| `drone` | Research opt-in | ≥60% recall vs a 25–50-event reference set built from ACLED air/drone-strike rows + clean token audit + two consecutive clean canaries (`--countries ML,BF,NE,NG,ET`) |
| `election_events` | Research opt-in (**v2.0 residual** — see Cross-domain architecture) | ≥60% recall on a hand-labeled 25–50-event gold set from an active electoral window (`--countries TZ,CI,UG`). Under v2.0, score the UNION of residual events + nexus-tagged primary-domain events against the gold set, running protest+VE+repression alongside |
| `state_repression` | Research opt-in | ≥60% recall on a mini gold set (CPJ/RSF + #KeepItOn incidents; `--countries ET,UG,SN,TZ`) |
| `violent_extremism` | Research opt-in | ≥60% recall on an ACLED-referenced mini gold set AND explicit domain-owner sign-off |

**Adding a domain to production** = one-line cron `--domains` change (via pea-deploy-phase) after its gate clears. Staging order: drone → election_events → state_repression → violent_extremism. Stages 2.5+4 run serially per domain, so cron runtime grows roughly linearly per enabled domain — record observed runtime here after each addition.

**Wiring a new domain** (see `pea-domain-add` skill): codebook YAML (top-level `event_types` — NOT any other name — plus `metadata, general_rules, minimum_criteria, non_events, confidence_guidance, extraction_prompt`), examples YAML (≥1 `pinned`), three registration points (`DOMAIN_CONFIGS`, `_REQUIRED_CONFIGS`, `relevance_filter._DOMAIN_CONFIG` + a `<domain>_signals` keywords section). `tests/test_domain_configs.py` enforces all of this structurally.

**Cross-domain architecture (adopted Aug 2026 — plan §4 decisions; changes the pre-v2.0 division of labour):**
- **Election = second-pass residual (DECO method).** Citizen protest about elections → protest domain (`issue_tags: [elections]`); GTD-qualifying electoral violence → `violent_extremism`; STATE arrests/violence against electoral actors → `state_repression`. Stage 4.75 then tags all of them `electoral_nexus`. The `election_events` extractor keeps ONLY residual election-only events (voter intimidation, partisan clashes, non-state detention of electoral actors, sub-GTD partisan violence, vote-process disruption, party boycotts). ECAV-equivalent coverage = nexus-tagged primary events ∪ residual events; an election-only run has reduced coverage by design.
- **Repression = linked pair with protest (NAVCO 3.0 dual representation).** Repression answering one specific protest is still that protest's `state_response` for EXTRACTION (who is the subject of the lede — the crowd, or the state?), but Stage 4.8 mechanically derives a linked repression twin (`derived_from_protest: true`, shared `dissent_repression_pair_id`) and links extracted repression events to the protests they answer. Filter `derived_from_protest` to recover the extraction-only dataset.
- Protest vs VE vs communal violence (unchanged): protester-initiated violence with a political demand = protest `riot`; sub-national actor violence meeting GTD criteria = `violent_extremism`; communal/farmer-herder/vigilante violence = non-event in both.
- **Confidence schema:** every domain emits per-field `field_confidence` (event_type/actors/location/date/casualties) alongside event-level `confidence`, with domain priors (military-register discount for VE/drone, concealment prior for repression, partisan-source cap for election). Every event carries `validation_status` (candidate → reviewed/rejected via the annotation import).

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
# GLOCON (data access granted 2026-07-08; dataset not yet fetched into any
# working environment — the git clone below is still a manual prerequisite)
# Download dataset to somewhere outside the repo first:
#   git clone <glocon-url> ~/datasets/glocon
python -m src.validation.glocon_validator \
  --glocon-dir ~/datasets/glocon/data/south_africa/english \
  --pea-events data/processed/events_consolidated.jsonl \
  --output data/validation/recall_report_glocon.json

# ACLED (register at acleddata.com — free for researchers, token by email)
# acled_validator.py not yet built — blocked on token (still pending 2026-07-08)
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

The JSON report includes a `match_records` array (one entry per gold event) for diagnosing specific misses. Real shape is nested — read `report["metrics"]["recall"]`, `["metrics"]["by_type"]`, `["metrics"]["by_country"]` (not flat `overall_recall`/`recall_by_type`/`recall_by_country` keys).

**GLOCON coverage limits (important — do not over-read a clean run):** the validator's documented/tested benchmark is the **South Africa English subset only** (`_norm_country()` in `glocon_validator.py` also aliases NG/UG/DZ, but no non-SA subset has ever been fetched or exercised here). It scores a **coarse 3-bucket event-type recall** (`protest`/`strike`/`riot`) — not the fine 8 protest event types, and nothing about `issue_tags`, the v3.0 boundary-case rules (coerced ghost-towns, pro-junta rally exclusion, state-media decoy vocabulary), or any of the four research domains (drone/violent_extremism/election_events/state_repression — all out of GLOCON's protest-only scope). **A GLOCON run, once data is fetched, checks non-regression on the pre-existing South Africa capability — it does NOT validate the pan-Africa expansion itself**, and it cannot be used to clear any of the § Domain registry & rollout gates recall requirements below. CEHA (Horn of Africa, no token needed) is the nearest available signal for the new Horn geography, but only validates the relevance filter (binary relevant/not), not event-type or `issue_tags` classification.

---

## Pending Infrastructure

| Item | Needed for |
|---|---|
| Anthropic API key recovery | `--provider claude` |
| Azure Container Registry + GitHub Secrets | Docker CI workflow |
| Azure Storage Account | `--upload-to az://...` |
| ACLED API token | `acled_validator.py` validation (still pending 2026-07-08) — also the only planned validator with real Sahel/Horn/Central/Lusophone coverage |
| GLOCON dataset fetch | `glocon_validator.py` — access granted 2026-07-08, dataset not yet downloaded into any working environment |

---

## Known Issues / Pending Code Fixes

| Issue | File | Notes |
|---|---|---|
| ACLED validator not yet built | `src/validation/` | Blocked — ACLED token still pending |
| Annotation pipeline built but never run | `src/annotation/` | `data/annotation/` has no git history — zero batches ever exported/imported. This is the only mechanism that can validate `issue_tags` correctness, fine 8-type accuracy, and the v3.0 boundary-case rules (no automated validator covers any of these) |
| `labeling_config.xml` has no `issue_tags` correction widget | `src/annotation/labeling_config.xml` | Only `corrected_event_type` is annotatable today; annotation can't validate the v3.0 field until this widget is added |
| BBC token has no refresh on 401 | `src/acquisition/bbc_discovery.py` | Long backfills may expire mid-run |
| Checkpoint append is thread-safe but not crash-atomic | `src/acquisition/extractor.py:_write_checkpoint` | SIGKILL during write can leave a partial line that fails the resume-skip match |

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
| 2026-04-25 | CI fixes: black formatting, flake8 violations, Dockerfile.web missing src/constants.py |
| 2026-05-07 | Pre-prod review: documented 8 dashboard env vars in `.env.example`, added startup config-presence assertion, added `scripts/smoke_extract.py` for post-deploy verification |
| 2026-07-08 | Extractor base-prompt parameterization: per-codebook `extraction_prompt` YAML section (persona, disqualifiers, rules with generated type list, output schema); legacy fallback preserved byte-identically |
| 2026-07-08 | Protest codebook v3.0: SCAD-style `issue_taxonomy` + `issue_tags` field, pan-Africa context (Sahel/Horn/Central/Lusophone), boundary cases (coercion test, state-media decoys, banditry, pro-junta rallies), ACLED mapping, extended CIVICUS lists |
| 2026-07-08 | Keywords: Portuguese/Amharic/Hausa/Somali protest signals; election + repression signal sections; 4 new pinned few-shot examples (UG/NG/MZ/ET) |
| 2026-07-08 | VE codebook schema remediation (`attack_types` → `event_types`) + registration as research opt-in; drone extraction_prompt + Sahel/Lake Chad examples |
| 2026-07-08 | Two new domains: `election_events` (ECAV) and `state_repression` (#KeepItOn/SCAD, incl. `internet_shutdown` turmoil value); `tests/test_domain_configs.py` structural gate |
| 2026-08-30 | Implementation-plan low-risk tranche: drone v1.1 (UNOCT/CAR `acquisition_type`, planned-attack + drone-as-protest boundary cases, CASE 2021/ACLED crosswalk + composite validation metadata); VE v1.2 (RTV/ECDB ideology attribution_rules, GTD access caution); election v1.1 (ECAV ±6-month window operationalised); repression v1.1 (ITT [A]/[B] certainty-graded decision rules, NGO-report-first source-genre note); ≥3 codebook negatives per type in all research domains + 6 worked `[]` examples in rotation pools; excluded-cases store (`excluded_store.py`, wired into extractor + both pipeline paths). Deferred from plan: UNOCT Tables 7/9/10 PULL items, GRID validator, NELDA, all §4 architecture decisions |
| 2026-08-30 | **All three §4 architecture decisions adopted and implemented.** (1) Per-field confidence: `field_confidence` in all 5 output schemas with domain priors; `fc_*` CSV columns + `field_confidence_distribution` in summaries (protest 3.1, drone 1.2, VE 1.3). (2) Candidate tier: `validation_status` candidate→reviewed/rejected lifecycle via storage stamp + annotation import. (3) Routing: election restructured as second-pass residual (election v2.0, `electoral_nexus.py` Stage 4.75, `election_calendar.yaml`, repression v1.3 routing flip) + dissent–repression linked pairs (`dissent_repression.py` Stage 4.8, NAVCO dual representation; multi-domain storage moved after linking). Pruned from plan as obsolete: ConfliBERT relevance experiment (Stage 2.5 already a CPU classifier gate), mordecai3 (overlaps `geocoder.py`), ACLED-validator caveat rows (validator still blocked on token) |

---

## Code Quality — Required Before Every Commit

Run these three commands before committing. CI enforces all of them.

```bash
python -m black src/ tests/          # auto-formats in place — commit the result
python -m flake8 src/ tests/         # must exit 0
python -m pytest tests/ -q           # must exit 0
```

Linter config lives in `.flake8` (max-line-length 120, E203 ignored for black compat).

### Docker COPY notes

Both `Dockerfile` and `Dockerfile.web` use `COPY src/ ./src/` and `COPY configs/ ./configs/`, so new modules and new config YAMLs are picked up automatically. If you reintroduce per-file copies in `Dockerfile.web` for image-size reasons, restore the coupling-rule section here.

`pipeline.main()` asserts that `configs/protest_codebook.yaml`, `configs/extraction_examples.yaml`, `configs/keywords.yaml`, and `configs/countries.yaml` are present at startup — see `_assert_required_configs()`. If you remove any of those files or rename them, update that allow-list.
