"""
Protest Event Analysis Pipeline
================================
End-to-end pipeline for Global South / non-Western protest event data collection,
full-text retrieval, and LLM-based structured extraction via Azure AI Foundry.

Stages:
  1. DISCOVERY   — query GDELT DOC API for candidate article URLs
  2. SCRAPING    — fetch full article text from source URLs
  3. TRANSLATION — detect and translate non-English text (optional)
  4. EXTRACTION  — Azure AI Foundry extracts structured protest event fields
  5. STORAGE     — save results to data/raw/ as JSONL + CSV

Codebook version: 2.4

Usage (from repo root):
    python -m src.acquisition.pipeline
    python -m src.acquisition.pipeline --query "protest strike" --countries NG,ZA,UG,DZ --days 7
    python -m src.acquisition.pipeline --help

Requires:
    AZURE_FOUNDRY_API_KEY  environment variable
    AZURE_OPENAI_ENDPOINT  environment variable
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

import src.acquisition.gdelt_discovery as _gdelt
import src.acquisition.bbc_discovery as _bbc
import src.acquisition.worldnews_discovery as _worldnews
import src.acquisition.file_discovery as _file_src
from src.acquisition.scraper import scrape_articles
from src.acquisition.geocoder import geocode_events
from src.acquisition.translator import translate_articles
from src.acquisition.extractor import extract_events
from src.acquisition.relevance_filter import RelevanceFilter
from src.acquisition.storage import (
    save_results,
    sync_checkpoint_from_adls,
    upload_checkpoint,
)
from src.acquisition.processing import process_events
from src.acquisition.predictions import run_predictions
from src.utils.logging_context import (
    install as _install_log_context,
    set_run_id as _set_run_id,
    set_domain as _set_domain,
    stage as _stage,
)


class _JsonFormatter(logging.Formatter):
    """Emit JSON log lines, including any contextvars set by logging_context.

    Empty-string context fields are omitted so untagged messages stay terse.
    """

    _CONTEXT_FIELDS = ("run_id", "country", "stage", "domain")

    def format(self, record):
        entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for field in self._CONTEXT_FIELDS:
            value = getattr(record, field, "")
            if value:
                entry[field] = value
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry)


_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(_JsonFormatter())
logging.basicConfig(level=logging.INFO, handlers=[_handler])
_install_log_context()
log = logging.getLogger("pipeline")

# Default output dir — aligns with project data structure
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Files the pipeline cannot run without. Missing any of these is a deploy bug,
# not a runtime soft-fail — the codebook + examples drive ~29k tokens of
# SYSTEM_PROMPT, and silently losing them collapses extraction quality without
# any error signal. Crash loud at startup instead.
_REQUIRED_CONFIGS = [
    _REPO_ROOT / "configs" / "protest_codebook.yaml",
    _REPO_ROOT / "configs" / "extraction_examples.yaml",
    _REPO_ROOT / "configs" / "keywords.yaml",
    _REPO_ROOT / "configs" / "countries.yaml",
]


def _assert_required_configs() -> None:
    missing = [
        str(p.relative_to(_REPO_ROOT)) for p in _REQUIRED_CONFIGS if not p.is_file()
    ]
    if missing:
        raise SystemExit(
            "Pipeline cannot start — required config files missing from image: "
            + ", ".join(missing)
            + ". Verify the Dockerfile copies the configs/ directory and that no "
            ".dockerignore rule is excluding these YAMLs."
        )


# Maps domain name → default codebook, examples, and GDELT query.
# Override individual fields via --codebook / --examples / --query CLI flags.
#
# `violent_extremism` is intentionally NOT registered here. The codebook and
# examples files exist in configs/ but have not yet been validated end-to-end
# on real news data. Wiring VE in production would mean either thin examples
# misclassifying terrorism-adjacent reporting, or unvalidated event-type
# crosswalks. Treat VE as research-only until a domain owner signs off and
# adds the entry below.
DOMAIN_CONFIGS: dict = {
    "protest": {
        "codebook": _REPO_ROOT / "configs" / "protest_codebook.yaml",
        "examples": _REPO_ROOT / "configs" / "extraction_examples.yaml",
        "query": "protest demonstration strike rally march",
    },
    "drone": {
        "codebook": _REPO_ROOT / "configs" / "drone_events_codebook.yaml",
        "examples": _REPO_ROOT / "configs" / "drone_extraction_examples.yaml",
        "query": "drone UAV airstrike unmanned aircraft",
    },
}


def _validate_domains(domains: list) -> None:
    """Reject unknown domains before any expensive work.

    Without this, `--domains violent_extremism` silently falls through to
    DOMAIN_CONFIGS.get(domain, {}) and runs with no codebook injection —
    the LLM produces protest output against an empty system prompt.
    """
    unknown = [d for d in domains if d not in DOMAIN_CONFIGS]
    if unknown:
        raise SystemExit(
            f"Unknown --domains value(s): {unknown}. "
            f"Registered domains: {sorted(DOMAIN_CONFIGS)}. "
            "If you need to wire a new domain (e.g. violent_extremism), add an "
            "entry to DOMAIN_CONFIGS with codebook + examples + query, and "
            "validate end-to-end before flipping it on in production."
        )


def _validate_source_credentials(source: str, file_path: Optional[str]) -> None:
    """Fail fast if a discovery source is selected but its credentials are missing.

    Without this, --source bbc / worldnews / both / all run all of Stage 1a
    (GDELT can take 2-5 minutes) before BBC or WorldNews discovery hits a
    cryptic auth failure deep inside the source-specific module. Surface the
    missing credential up front instead.
    """
    needs_bbc = source in ("bbc", "both", "all")
    needs_worldnews = source in ("worldnews", "all")
    needs_file = source == "file"

    missing: list = []

    if needs_bbc:
        if not os.environ.get("BBC_MONITORING_USER_NAME", "").strip():
            missing.append(
                "BBC_MONITORING_USER_NAME (required for --source bbc/both/all)"
            )
        if not os.environ.get("BBC_MONITORING_USER_PASSWORD", "").strip():
            missing.append(
                "BBC_MONITORING_USER_PASSWORD (required for --source bbc/both/all)"
            )

    if needs_worldnews:
        if not os.environ.get("WORLDNEWS_API_KEY", "").strip():
            missing.append("WORLDNEWS_API_KEY (required for --source worldnews/all)")

    if needs_file and not file_path:
        missing.append("--file-path (required for --source file)")

    if missing:
        raise SystemExit(
            "Cannot start discovery — missing credentials/inputs for "
            f"--source {source}: " + "; ".join(missing)
        )


def _discover_articles(
    source: str,
    query: str,
    countries: list,
    days: int,
    max_articles: int,
    file_path: Optional[str] = None,
) -> list:
    """
    Run Stage 1 discovery for the given source(s).

    Handles single-source and combined-source modes, including URL
    deduplication when multiple sources may overlap (both / all).
    """
    _validate_source_credentials(source, file_path)

    articles: list = []

    if source in ("gdelt", "both", "all"):
        log.info("--- Stage 1a: GDELT Discovery ---")
        gdelt_articles = _gdelt.discover_articles(
            query=query, countries=countries, days=days, max_results=max_articles
        )
        log.info(f"GDELT: {len(gdelt_articles)} candidate articles")
        articles.extend(gdelt_articles)

    if source in ("bbc", "both", "all"):
        log.info("--- Stage 1b: BBC Monitoring Discovery ---")
        bbc_articles = _bbc.discover_articles(
            query=query,
            countries=countries,
            days=days,
            max_results=max_articles,
            fetch_full_text=True,
        )
        log.info(f"BBC Monitoring: {len(bbc_articles)} candidate articles")
        articles.extend(bbc_articles)

    if source in ("worldnews", "all"):
        log.info("--- Stage 1c: World News API Discovery ---")
        wn_articles = _worldnews.discover_articles(
            query=query, countries=countries, days=days, max_results=max_articles
        )
        log.info(f"World News API: {len(wn_articles)} candidate articles")
        articles.extend(wn_articles)

    if source == "file":
        log.info("--- Stage 1: File/ADLS Input ---")
        file_articles = _file_src.discover_articles_from_file(
            path=file_path, countries=countries
        )
        log.info(f"File source: {len(file_articles)} articles loaded")
        articles.extend(file_articles)

    # Dedup by URL when multiple sources may overlap
    if source in ("both", "all"):
        seen: set = set()
        deduped = []
        for a in articles:
            if a["url"] not in seen:
                seen.add(a["url"])
                deduped.append(a)
        if len(deduped) < len(articles):
            log.info(
                f"After cross-source dedup: {len(deduped)} articles "
                f"({len(articles) - len(deduped)} duplicates removed)"
            )
        articles = deduped

    return articles


def run_pipeline(
    query: str,
    countries: list,
    days: int,
    output_dir: Path,
    max_articles: int = 100,
    translate: bool = True,
    provider: str = "azure",
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    upload_to: Optional[str] = None,
    source: str = "gdelt",
    file_path: Optional[str] = None,
    geocode: bool = True,
    resume: bool = False,
    relevance_threshold: float = 0.30,
    domain: str = "protest",
    codebook_path: Optional[Path] = None,
    examples_path: Optional[Path] = None,
    workers: int = 1,
    rpm_limit: int = 450,
    geocode_cache: Optional[Path] = Path("data/cache/geocode.json"),
    geocode_workers: int = 4,
    scrape_workers: int = 16,
    relevance_batch_size: int = 32,
    examples_sample_n: int = 5,
    articles: Optional[list] = None,
):
    # Checkpoint and output files live under output_dir/domain/ for isolation.
    effective_output_dir = output_dir / domain
    effective_output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    # Tag every log line in this run with run_id + domain so Log Analytics
    # queries can filter by run rather than by free-text substring match.
    _set_run_id(run_id)
    _set_domain(domain)

    log.info("=== Protest Event Analysis Pipeline (codebook v2.4) ===")
    log.info(f"Query: '{query}' | Countries: {countries} | Days back: {days}")
    log.info(
        f"LLM provider: {provider} | model: {model or 'default'} | source: {source} | domain: {domain}"
    )
    if workers > 1:
        log.info(f"Concurrent extraction: {workers} workers, rpm_limit={rpm_limit}")

    # Sync checkpoint from ADLS before reading it (enables resume after container restart)
    if resume and upload_to:
        sync_checkpoint_from_adls(upload_to, effective_output_dir)

    # Stage 1: Discovery — skipped when articles are pre-supplied (e.g. backfill mode)
    with _stage("discovery"):
        if articles is not None:
            log.info(
                f"Using {len(articles)} pre-discovered articles — skipping Stage 1"
            )
        else:
            articles = _discover_articles(
                source=source,
                query=query,
                countries=countries,
                days=days,
                max_articles=max_articles,
                file_path=file_path,
            )

        log.info(f"Discovered {len(articles)} candidate articles total")

    if not articles:
        log.warning("No articles found. Try broadening your query or country list.")
        return []

    # Stage 2: Full-text scraping
    with _stage("scraping"):
        log.info("--- Stage 2: Full-text Scraping ---")
        articles = scrape_articles(articles, max_workers=scrape_workers)
        scraped = [a for a in articles if a.get("text")]
        log.info(f"Successfully scraped {len(scraped)}/{len(articles)} articles")

    if not scraped:
        log.warning("No articles could be scraped. Check network access.")
        return []

    # Stage 3: Translation (optional) — runs BEFORE the relevance filter so
    # the NLI classifier (English-trained DeBERTa) sees translated text rather
    # than scoring French/Arabic/Swahili articles in their source language.
    # Aligns with the multi-domain pipeline's order. Translation cost on
    # filter-rejected articles is dwarfed by the recall loss of misfiltering
    # non-English protest reports.
    with _stage("translation"):
        if translate:
            log.info("--- Stage 3: Translation ---")
            scraped = translate_articles(scraped)
        else:
            for a in scraped:
                a["text_en"] = a.get("text")
                a["text_lang"] = "unknown"

    # Stage 2.5: Relevance filter — rejects non-domain articles before LLM
    degraded_modes: list = []
    with _stage("relevance_filter"):
        log.info(f"--- Stage 2.5: Relevance Filter (domain={domain}) ---")
        _rf = RelevanceFilter(
            threshold=relevance_threshold,
            domain=domain,
            batch_size=relevance_batch_size,
        )
        if _rf.degraded_mode:
            log.warning(
                "Relevance filter running in DEGRADED MODE (NLI model "
                "unavailable, keyword fallback active). Precision will be "
                "lower than the configured threshold suggests; this run "
                "will be flagged in the summary's degraded_modes list."
            )
            degraded_modes.append("relevance_filter:keyword_fallback")
        scraped, rf_rejected = _rf.filter(scraped)
        log.info(
            f"Relevance filter: {len(scraped)} kept, {len(rf_rejected)} rejected "
            f"(saved ~${len(rf_rejected) * 0.00616:.2f} in LLM calls)"
        )
    if not scraped:
        log.warning(
            "All articles rejected by relevance filter. Lower --relevance-threshold?"
        )
        return []

    # Stage 4: LLM Extraction via Azure AI Foundry
    with _stage("extraction"):
        log.info("--- Stage 4: LLM Event Extraction (Azure AI Foundry) ---")
        checkpoint_path = str(effective_output_dir / "checkpoint.txt")
        events, failures = extract_events(
            scraped,
            model=model,
            api_key=api_key,
            provider=provider,
            checkpoint_path=checkpoint_path,
            upload_to=upload_to,
            codebook_path=codebook_path,
            examples_path=examples_path,
            workers=workers,
            rpm_limit=rpm_limit,
            examples_sample_n=examples_sample_n,
        )
        log.info(
            f"Extracted {len(events)} events ({len(failures)} extraction failures)"
        )

    # Stage 4.5: Geocoding
    if geocode and events:
        with _stage("geocoding"):
            log.info("--- Stage 4.5: Geocoding ---")
            events = geocode_events(
                events,
                cache_path=geocode_cache,
                max_workers=geocode_workers,
            )

    # Stage 5: Storage
    with _stage("storage"):
        log.info("--- Stage 5: Saving Results ---")
        out_path = save_results(
            events,
            output_dir=output_dir,
            run_id=run_id,
            failures=failures,
            upload_to=upload_to,
            domain=domain,
            degraded_modes=degraded_modes,
        )
        log.info(f"Results saved to {out_path}")

    # Always push the final checkpoint state to ADLS, even when save_results
    # returns early (zero events). Covers runs where <10 articles were processed
    # and the periodic upload inside extract_events never fired.
    if upload_to:
        upload_checkpoint(upload_to, effective_output_dir)

    log.info("=== Pipeline complete ===")
    return events


def run_pipeline_multi_codebook(
    domains: list,
    countries: list,
    days: int,
    output_dir: Path,
    max_articles: int = 100,
    translate: bool = True,
    provider: str = "azure",
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    upload_to: Optional[str] = None,
    source: str = "gdelt",
    file_path: Optional[str] = None,
    geocode: bool = True,
    resume: bool = False,
    relevance_threshold: float = 0.30,
    workers: int = 1,
    rpm_limit: int = 450,
    geocode_cache: Optional[Path] = Path("data/cache/geocode.json"),
    geocode_workers: int = 4,
    scrape_workers: int = 16,
    relevance_batch_size: int = 32,
    examples_sample_n: int = 5,
) -> dict:
    """
    Scrape and translate once, then run each domain's relevance filter and
    extractor independently. An article qualifies for multiple domains if it
    passes each domain's relevance threshold (e.g., a protest dispersed with
    a surveillance drone passes both).

    Returns {domain: [events]} for all requested domains.
    """
    run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    _set_run_id(run_id)

    log.info(f"=== Multi-codebook pipeline: domains={domains} ===")

    # --- Stage 1: Discovery (merge GDELT queries across all active domains) ---
    with _stage("discovery"):
        all_query_terms: set = set()
        for d in domains:
            cfg = DOMAIN_CONFIGS.get(d, {})
            all_query_terms.update(cfg.get("query", "").split())
        merged_query = " ".join(sorted(all_query_terms))
        log.info(f"Merged GDELT query: '{merged_query}'")

        articles = _discover_articles(
            source=source,
            query=merged_query,
            countries=countries,
            days=days,
            max_articles=max_articles,
            file_path=file_path,
        )

    if not articles:
        log.warning("No articles found.")
        return {d: [] for d in domains}

    # --- Stage 2: Scraping (shared — happens once for all domains) ---
    with _stage("scraping"):
        log.info("--- Stage 2: Full-text Scraping (shared) ---")
        articles = scrape_articles(articles, max_workers=scrape_workers)
        scraped = [a for a in articles if a.get("text")]
        log.info(f"Successfully scraped {len(scraped)}/{len(articles)} articles")

    if not scraped:
        log.warning("No articles could be scraped.")
        return {d: [] for d in domains}

    # --- Stage 3: Translation (shared) ---
    with _stage("translation"):
        if translate:
            log.info("--- Stage 3: Translation (shared) ---")
            scraped = translate_articles(scraped)
        else:
            for a in scraped:
                a["text_en"] = a.get("text")
                a["text_lang"] = "unknown"

    # --- Stages 2.5 + 4 + 4.5 + 5: Per-domain in series (preserves prompt caching) ---
    results: dict = {}

    for domain in domains:
        cfg = DOMAIN_CONFIGS.get(domain, {})
        _set_domain(domain)
        log.info(f"=== Domain: {domain} ===")

        # Stage 2.5: Domain-specific relevance filter
        domain_degraded: list = []
        with _stage("relevance_filter"):
            log.info(f"--- Stage 2.5: Relevance Filter (domain={domain}) ---")
            _rf = RelevanceFilter(
                threshold=relevance_threshold,
                domain=domain,
                batch_size=relevance_batch_size,
            )
            if _rf.degraded_mode:
                log.warning(
                    f"Relevance filter for domain '{domain}' running in DEGRADED "
                    "MODE (keyword fallback). Flagged in run summary."
                )
                domain_degraded.append("relevance_filter:keyword_fallback")
            domain_articles, rf_rejected = _rf.filter(scraped)
            log.info(f"  {len(domain_articles)} kept, {len(rf_rejected)} rejected")
        if not domain_articles:
            log.warning(f"  No articles passed relevance filter for domain '{domain}'")
            results[domain] = []
            continue

        # Stage 4: LLM extraction (all articles for this domain before switching)
        with _stage("extraction"):
            log.info(f"--- Stage 4: Extraction (domain={domain}) ---")
            effective_output_dir = output_dir / domain
            effective_output_dir.mkdir(parents=True, exist_ok=True)
            checkpoint_path = str(effective_output_dir / "checkpoint.txt")

            if resume and upload_to:
                sync_checkpoint_from_adls(upload_to, effective_output_dir)

            events, failures = extract_events(
                domain_articles,
                model=model,
                api_key=api_key,
                provider=provider,
                checkpoint_path=checkpoint_path,
                upload_to=upload_to,
                codebook_path=cfg.get("codebook"),
                examples_path=cfg.get("examples"),
                workers=workers,
                rpm_limit=rpm_limit,
                examples_sample_n=examples_sample_n,
            )
            log.info(f"  Extracted {len(events)} events ({len(failures)} failures)")

        # Stage 4.5: Geocoding
        if geocode and events:
            with _stage("geocoding"):
                log.info(f"--- Stage 4.5: Geocoding (domain={domain}) ---")
                events = geocode_events(
                    events,
                    cache_path=geocode_cache,
                    max_workers=geocode_workers,
                )

        # Stage 5: Storage
        with _stage("storage"):
            save_results(
                events,
                output_dir=output_dir,
                run_id=run_id,
                failures=failures,
                upload_to=upload_to,
                domain=domain,
                degraded_modes=domain_degraded,
            )
        results[domain] = events

    log.info(f"=== Multi-codebook pipeline complete: {list(results.keys())} ===")
    return results


def main():
    import signal
    from dotenv import load_dotenv

    load_dotenv()

    _assert_required_configs()

    def _handle_sigterm(signum, frame):
        log.warning("SIGTERM received — checkpoint already persisted; exiting cleanly")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_sigterm)

    parser = argparse.ArgumentParser(
        description="Protest Event Analysis Pipeline — Global South focus (codebook v2.3)"
    )
    parser.add_argument(
        "--query",
        default="protest demonstration strike rally march",
        help="Keywords to search in GDELT (space-separated)",
    )
    parser.add_argument(
        "--countries", default="NG,ZA,UG,DZ", help="Comma-separated ISO2 country codes"
    )
    parser.add_argument(
        "--days", type=int, default=7, help="How many days back to search"
    )
    parser.add_argument(
        "--max-articles", type=int, default=50, help="Max articles to process"
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory to write results (default: data/raw/)",
    )
    parser.add_argument(
        "--no-translate", action="store_true", help="Skip translation step"
    )
    parser.add_argument(
        "--provider",
        default="azure",
        choices=["azure"],
        help="LLM provider: 'azure' (Azure AI Foundry)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Deployment name in Azure AI Foundry project (default: gpt-5.4)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key — defaults to AZURE_FOUNDRY_API_KEY env var",
    )
    parser.add_argument(
        "--source",
        default="gdelt",
        choices=["gdelt", "bbc", "worldnews", "file", "both", "all"],
        help=(
            "Discovery source: 'gdelt' (default), 'bbc' (BBC Monitoring), "
            "'worldnews' (World News API — requires WORLDNEWS_API_KEY), "
            "'file' (pre-scraped file — requires --file-path), "
            "'both' (gdelt + bbc), 'all' (gdelt + bbc + worldnews)"
        ),
    )
    parser.add_argument(
        "--file-path",
        default=None,
        help=(
            "Path to a pre-scraped articles file when --source file is used. "
            "Accepts local paths (.csv, .json, .jsonl) or ADLS Gen2 paths "
            "(abfss://filesystem/path/to/file.csv). "
            "Required columns: url, title, text, date, country."
        ),
    )
    parser.add_argument(
        "--no-geocode", action="store_true", help="Skip geocoding step (Nominatim OSM)"
    )
    parser.add_argument(
        "--geocode-cache",
        default="data/cache/geocode.json",
        help=(
            "Path to on-disk geocode cache (JSON). Persists across runs so "
            "repeated (city, country) pairs skip Nominatim. "
            "Pass 'none' to disable. Default: data/cache/geocode.json"
        ),
    )
    parser.add_argument(
        "--geocode-workers",
        type=int,
        default=4,
        help=(
            "Threads dispatching Nominatim lookups (default 4). All threads "
            "share one rate limiter to honour Nominatim's 1 req/s policy; "
            "speedup comes from parallel cache hits, not parallel network."
        ),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from checkpoint.txt — skip already-processed URLs",
    )
    parser.add_argument(
        "--relevance-threshold",
        type=float,
        default=0.30,
        help=(
            "Minimum relevance score (0-1) for an article to proceed to LLM extraction. "
            "Lower = higher recall (more noise passes). Default: 0.30. "
            "Raise to 0.50 once GLOCON validation confirms filter accuracy."
        ),
    )
    parser.add_argument(
        "--upload-to",
        default=None,
        help=(
            "Upload outputs after run: 's3://bucket/prefix' or "
            "'abfss://filesystem/prefix' (Azure Data Lake Storage Gen2)"
        ),
    )
    parser.add_argument(
        "--stage",
        default="acquire",
        choices=["acquire", "process", "predict", "all"],
        help=(
            "Pipeline stage to run: "
            "'acquire' (default) — GDELT/BBC -> extract -> data/raw/; "
            "'process' — dedup + quality control -> data/processed/; "
            "'predict' — PPI + prevalence estimates -> data/predictions/; "
            "'all' — run all three stages in sequence"
        ),
    )
    parser.add_argument(
        "--domains",
        default="protest",
        help=(
            "Comma-separated codebook domains to run (default: 'protest'). "
            "Use 'protest,drone' to run both in one invocation: articles are scraped "
            "once and routed through each domain's relevance filter and extractor. "
            "Output is isolated under data/raw/<domain>/."
        ),
    )
    parser.add_argument(
        "--codebook",
        default=None,
        help="Path to a codebook YAML (overrides the domain default; single-domain only)",
    )
    parser.add_argument(
        "--examples",
        default=None,
        help="Path to an extraction examples YAML (overrides the domain default; single-domain only)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help=(
            "Concurrent extraction workers (default 4; pass 1 for sequential). "
            "All workers share one system prompt so Azure prompt caching stays "
            "hot, and share one sliding-window limiter so retry storms cannot "
            "burst past --rpm-limit."
        ),
    )
    parser.add_argument(
        "--scrape-workers",
        type=int,
        default=16,
        help=(
            "Threads dispatching article scrapes (default 16). Same-host "
            "requests serialise via a per-host lock + jittered delay; "
            "different hosts proceed in parallel."
        ),
    )
    parser.add_argument(
        "--relevance-batch-size",
        type=int,
        default=32,
        help=(
            "Snippets per relevance-filter HF pipeline call (default 32). "
            "Raise on GPU, lower if memory is tight. Keyword fallback ignores "
            "this flag."
        ),
    )
    parser.add_argument(
        "--examples-sample-n",
        type=int,
        default=5,
        help=(
            "Number of few-shot examples to inject per run (default 5). "
            "Pinned examples are always included; the remainder is filled by "
            "a run-stable random sample from the promoted pool, so promoted "
            "annotator corrections rotate in and out across runs. Azure "
            "prompt caching is preserved within a run."
        ),
    )
    parser.add_argument(
        "--rpm-limit",
        type=int,
        default=450,
        help="Azure OpenAI RPM ceiling for the rate limiter (default 450; ~10%% headroom under 500 RPM limit)",
    )
    parser.add_argument(
        "--backfill-from",
        default=None,
        help="Start date for historical backfill mode: YYYY-MM-DD",
    )
    parser.add_argument(
        "--backfill-to",
        default=None,
        help="End date for historical backfill mode: YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--backfill-window-days",
        type=int,
        default=30,
        help="Window size in days for date-range GDELT queries during backfill (default 30)",
    )
    args = parser.parse_args()

    if args.source == "file" and not args.file_path:
        parser.error("--file-path is required when --source file is used")

    if args.backfill_from and args.source == "file":
        parser.error("--source file cannot be used with --backfill-from")

    output_dir = Path(args.output_dir)
    domains = [d.strip() for d in args.domains.split(",") if d.strip()]
    _validate_domains(domains)

    # Resolve geocode cache path: 'none' / empty string disables caching.
    _geocode_cache_arg = (args.geocode_cache or "").strip()
    geocode_cache = (
        None
        if _geocode_cache_arg.lower() in ("", "none", "off", "false")
        else Path(_geocode_cache_arg)
    )

    if args.stage in ("acquire", "all"):
        if len(domains) > 1:
            if args.codebook or args.examples:
                parser.error(
                    "--codebook and --examples cannot be used with multiple --domains"
                )
            run_pipeline_multi_codebook(
                domains=domains,
                countries=args.countries.split(","),
                days=args.days,
                output_dir=output_dir,
                max_articles=args.max_articles,
                translate=not args.no_translate,
                provider=args.provider,
                model=args.model,
                api_key=args.api_key,
                upload_to=args.upload_to,
                source=args.source,
                file_path=args.file_path,
                geocode=not args.no_geocode,
                resume=args.resume,
                relevance_threshold=args.relevance_threshold,
                workers=args.workers,
                rpm_limit=args.rpm_limit,
                geocode_cache=geocode_cache,
                geocode_workers=args.geocode_workers,
                scrape_workers=args.scrape_workers,
                relevance_batch_size=args.relevance_batch_size,
                examples_sample_n=args.examples_sample_n,
            )
        else:
            domain = domains[0] if domains else "protest"
            domain_cfg = DOMAIN_CONFIGS.get(domain, {})
            codebook_path = (
                Path(args.codebook) if args.codebook else domain_cfg.get("codebook")
            )
            examples_path = (
                Path(args.examples) if args.examples else domain_cfg.get("examples")
            )
            # Use domain-specific default query if user didn't supply --query
            query = args.query
            if (
                query == "protest demonstration strike rally march"
                and domain != "protest"
            ):
                query = domain_cfg.get("query", args.query)

            # Clear checkpoint on fresh acquire run (domain-namespaced)
            checkpoint = output_dir / domain / "checkpoint.txt"
            if not args.resume and checkpoint.exists():
                checkpoint.unlink()
                log.info(
                    f"Fresh run — cleared existing checkpoint for domain '{domain}'"
                )

            # Pre-discover articles for backfill mode; normal mode leaves articles=None
            backfill_articles = None
            if args.backfill_from:
                start_date = datetime.strptime(args.backfill_from, "%Y-%m-%d")
                end_date = (
                    datetime.strptime(args.backfill_to, "%Y-%m-%d")
                    if args.backfill_to
                    else datetime.utcnow()
                )
                log.info(
                    f"Backfill mode: {start_date.date()} -> {end_date.date()} "
                    f"(window={args.backfill_window_days}d)"
                )
                backfill_articles = _gdelt.discover_articles_date_range(
                    query=query,
                    countries=args.countries.split(","),
                    start_date=start_date,
                    end_date=end_date,
                    window_days=args.backfill_window_days,
                )

            run_pipeline(
                query=query,
                countries=args.countries.split(","),
                days=args.days,
                output_dir=output_dir,
                max_articles=args.max_articles,
                translate=not args.no_translate,
                provider=args.provider,
                model=args.model,
                api_key=args.api_key,
                upload_to=args.upload_to,
                source=args.source,
                file_path=args.file_path,
                geocode=not args.no_geocode,
                resume=args.resume,
                relevance_threshold=args.relevance_threshold,
                domain=domain,
                codebook_path=codebook_path,
                examples_path=examples_path,
                workers=args.workers,
                rpm_limit=args.rpm_limit,
                geocode_cache=geocode_cache,
                geocode_workers=args.geocode_workers,
                scrape_workers=args.scrape_workers,
                relevance_batch_size=args.relevance_batch_size,
                examples_sample_n=args.examples_sample_n,
                articles=backfill_articles,
            )

    if args.stage in ("process", "all"):
        log.info("=== Stage 2: Processing and Consolidation ===")
        process_events(
            provider=args.provider,
            model=args.model,
            api_key=args.api_key,
            upload_to=args.upload_to,
        )

    if args.stage in ("predict", "all"):
        log.info("=== Stage 3: Predictions and Statistical Inference ===")
        run_predictions(
            upload_to=args.upload_to,
        )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("Pipeline failed with unhandled exception")
        sys.exit(1)
