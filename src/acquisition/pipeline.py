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

Codebook version: 2.3

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
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

import src.acquisition.gdelt_discovery as _gdelt
import src.acquisition.bbc_discovery as _bbc
from src.acquisition.scraper import scrape_articles
from src.acquisition.geocoder import geocode_events
from src.acquisition.translator import translate_articles
from src.acquisition.extractor import extract_events
from src.acquisition.relevance_filter import RelevanceFilter
from src.acquisition.storage import (
    save_results,
    sync_checkpoint_from_blob,
)
from src.acquisition.processing import process_events
from src.acquisition.predictions import run_predictions


class _JsonFormatter(logging.Formatter):
    def format(self, record):
        entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry)


_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(_JsonFormatter())
logging.basicConfig(level=logging.INFO, handlers=[_handler])
log = logging.getLogger("pipeline")

# Default output dir — aligns with project data structure
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"


def _load_checkpoint(output_dir: Path) -> set[str]:
    """Return set of URLs already processed in a previous run."""
    cp = output_dir / "checkpoint.txt"
    return set(cp.read_text().splitlines()) if cp.exists() else set()


def _save_checkpoint(output_dir: Path, url: str) -> None:
    """Append a processed URL to the checkpoint file."""
    with open(output_dir / "checkpoint.txt", "a") as f:
        f.write(url + "\n")


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
    geocode: bool = True,
    resume: bool = False,
    relevance_threshold: float = 0.30,
    domain: str = "protest",
    codebook_path: Optional[Path] = None,
    examples_path: Optional[Path] = None,
    workers: int = 1,
    rpm_limit: int = 450,
):
    log.info("=== Protest Event Analysis Pipeline (codebook v2.3) ===")
    log.info(f"Query: '{query}' | Countries: {countries} | Days back: {days}")
    log.info(
        f"LLM provider: {provider} | model: {model or 'default'} | source: {source} | domain: {domain}"
    )
    if workers > 1:
        log.info(f"Concurrent extraction: {workers} workers, rpm_limit={rpm_limit}")

    # Checkpoint and output files live under output_dir/domain/ for isolation.
    effective_output_dir = output_dir / domain
    effective_output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    # Sync checkpoint from blob before reading it (enables resume after container restart)
    if resume and upload_to:
        sync_checkpoint_from_blob(upload_to, effective_output_dir)

    # Stage 1: Discovery
    articles = []

    if source in ("gdelt", "both"):
        log.info("--- Stage 1a: GDELT Discovery ---")
        gdelt_articles = _gdelt.discover_articles(
            query=query, countries=countries, days=days, max_results=max_articles
        )
        log.info(f"GDELT: {len(gdelt_articles)} candidate articles")
        articles.extend(gdelt_articles)

    if source in ("bbc", "both"):
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

    # Deduplicate by URL when using both sources
    if source == "both":
        seen = set()
        deduped = []
        for a in articles:
            if a["url"] not in seen:
                seen.add(a["url"])
                deduped.append(a)
        log.info(
            f"After dedup: {len(deduped)} articles ({len(articles) - len(deduped)} duplicates removed)"
        )
        articles = deduped

    log.info(f"Discovered {len(articles)} candidate articles total")

    if not articles:
        log.warning("No articles found. Try broadening your query or country list.")
        return []

    # Stage 2: Full-text scraping
    log.info("--- Stage 2: Full-text Scraping ---")
    articles = scrape_articles(articles)
    scraped = [a for a in articles if a.get("text")]
    log.info(f"Successfully scraped {len(scraped)}/{len(articles)} articles")

    if not scraped:
        log.warning("No articles could be scraped. Check network access.")
        return []

    # Stage 2.5: Relevance filter — rejects non-domain articles before LLM
    log.info(f"--- Stage 2.5: Relevance Filter (domain={domain}) ---")
    _rf = RelevanceFilter(threshold=relevance_threshold, domain=domain)
    scraped, rf_rejected = _rf.filter(scraped)
    log.info(
        f"Relevance filter: {len(scraped)} kept, {len(rf_rejected)} rejected "
        f"(saved ~${len(rf_rejected) * 0.00616:.2f} in LLM calls)"
    )
    if not scraped:
        log.warning("All articles rejected by relevance filter. Lower --relevance-threshold?")
        return []

    # Stage 3: Translation (optional)
    if translate:
        log.info("--- Stage 3: Translation ---")
        scraped = translate_articles(scraped)
    else:
        for a in scraped:
            a["text_en"] = a.get("text")
            a["text_lang"] = "unknown"

    # Stage 4: LLM Extraction via Azure AI Foundry
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
    )
    log.info(
        f"Extracted {len(events)} events ({len(failures)} extraction failures)"
    )

    # Stage 4.5: Geocoding
    if geocode and events:
        log.info("--- Stage 4.5: Geocoding ---")
        events = geocode_events(events)

    # Stage 5: Storage
    log.info("--- Stage 5: Saving Results ---")
    out_path = save_results(
        events,
        output_dir=output_dir,
        run_id=run_id,
        failures=failures,
        upload_to=upload_to,
        domain=domain,
    )
    log.info(f"Results saved to {out_path}")

    log.info("=== Pipeline complete ===")
    return events


_REPO_ROOT = Path(__file__).resolve().parents[2]

# Maps domain name → default codebook, examples, and GDELT query.
# Override individual fields via --codebook / --examples / --query CLI flags.
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
    geocode: bool = True,
    resume: bool = False,
    relevance_threshold: float = 0.30,
    workers: int = 1,
    rpm_limit: int = 450,
) -> dict:
    """
    Scrape and translate once, then run each domain's relevance filter and
    extractor independently. An article qualifies for multiple domains if it
    passes each domain's relevance threshold (e.g., a protest dispersed with
    a surveillance drone passes both).

    Returns {domain: [events]} for all requested domains.
    """
    from src.acquisition.scraper import scrape_articles
    from src.acquisition.translator import translate_articles

    log.info(f"=== Multi-codebook pipeline: domains={domains} ===")

    # --- Stage 1: Discovery (merge GDELT queries across all active domains) ---
    all_query_terms: set[str] = set()
    for d in domains:
        cfg = DOMAIN_CONFIGS.get(d, {})
        all_query_terms.update(cfg.get("query", "").split())
    merged_query = " ".join(sorted(all_query_terms))
    log.info(f"Merged GDELT query: '{merged_query}'")

    articles: list = []
    if source in ("gdelt", "both"):
        log.info("--- Stage 1a: GDELT Discovery (merged query) ---")
        gdelt_articles = _gdelt.discover_articles(
            query=merged_query, countries=countries, days=days, max_results=max_articles
        )
        log.info(f"GDELT: {len(gdelt_articles)} candidate articles")
        articles.extend(gdelt_articles)

    if source in ("bbc", "both"):
        log.info("--- Stage 1b: BBC Monitoring Discovery ---")
        bbc_articles = _bbc.discover_articles(
            query=merged_query,
            countries=countries,
            days=days,
            max_results=max_articles,
            fetch_full_text=True,
        )
        log.info(f"BBC Monitoring: {len(bbc_articles)} candidate articles")
        articles.extend(bbc_articles)

    if source == "both":
        seen: set = set()
        deduped = []
        for a in articles:
            if a["url"] not in seen:
                seen.add(a["url"])
                deduped.append(a)
        articles = deduped

    if not articles:
        log.warning("No articles found.")
        return {d: [] for d in domains}

    # --- Stage 2: Scraping (shared — happens once for all domains) ---
    log.info("--- Stage 2: Full-text Scraping (shared) ---")
    articles = scrape_articles(articles)
    scraped = [a for a in articles if a.get("text")]
    log.info(f"Successfully scraped {len(scraped)}/{len(articles)} articles")

    if not scraped:
        log.warning("No articles could be scraped.")
        return {d: [] for d in domains}

    # --- Stage 3: Translation (shared) ---
    if translate:
        log.info("--- Stage 3: Translation (shared) ---")
        scraped = translate_articles(scraped)
    else:
        for a in scraped:
            a["text_en"] = a.get("text")
            a["text_lang"] = "unknown"

    # --- Stages 2.5 + 4 + 4.5 + 5: Per-domain in series (preserves prompt caching) ---
    results: dict = {}
    run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    for domain in domains:
        cfg = DOMAIN_CONFIGS.get(domain, {})
        log.info(f"=== Domain: {domain} ===")

        # Stage 2.5: Domain-specific relevance filter
        log.info(f"--- Stage 2.5: Relevance Filter (domain={domain}) ---")
        _rf = RelevanceFilter(threshold=relevance_threshold, domain=domain)
        domain_articles, rf_rejected = _rf.filter(scraped)
        log.info(
            f"  {len(domain_articles)} kept, {len(rf_rejected)} rejected"
        )
        if not domain_articles:
            log.warning(f"  No articles passed relevance filter for domain '{domain}'")
            results[domain] = []
            continue

        # Stage 4: LLM extraction (all articles for this domain before switching)
        log.info(f"--- Stage 4: Extraction (domain={domain}) ---")
        effective_output_dir = output_dir / domain
        effective_output_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_path = str(effective_output_dir / "checkpoint.txt")

        if resume and upload_to:
            sync_checkpoint_from_blob(upload_to, effective_output_dir)

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
        )
        log.info(f"  Extracted {len(events)} events ({len(failures)} failures)")

        # Stage 4.5: Geocoding
        if geocode and events:
            log.info(f"--- Stage 4.5: Geocoding (domain={domain}) ---")
            events = geocode_events(events)

        # Stage 5: Storage
        save_results(
            events,
            output_dir=output_dir,
            run_id=run_id,
            failures=failures,
            upload_to=upload_to,
            domain=domain,
        )
        results[domain] = events

    log.info(f"=== Multi-codebook pipeline complete: {list(results.keys())} ===")
    return results


def main():
    from dotenv import load_dotenv

    load_dotenv()

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
        help="Deployment name in Azure AI Foundry project (default: gpt-4.1)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key — defaults to AZURE_FOUNDRY_API_KEY env var",
    )
    parser.add_argument(
        "--source",
        default="gdelt",
        choices=["gdelt", "bbc", "both"],
        help="Discovery source: 'gdelt' (default), 'bbc' (BBC Monitoring), or 'both'",
    )
    parser.add_argument(
        "--no-geocode", action="store_true", help="Skip geocoding step (Nominatim OSM)"
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
            "Minimum relevance score (0–1) for an article to proceed to LLM extraction. "
            "Lower = higher recall (more noise passes). Default: 0.30. "
            "Raise to 0.50 once GLOCON validation confirms filter accuracy."
        ),
    )
    parser.add_argument(
        "--upload-to",
        default=None,
        help="Upload outputs after run: 's3://bucket/prefix' or 'az://container/prefix'",
    )
    parser.add_argument(
        "--stage",
        default="acquire",
        choices=["acquire", "process", "predict", "all"],
        help=(
            "Pipeline stage to run: "
            "'acquire' (default) — GDELT/BBC → extract → data/raw/; "
            "'process' — dedup + quality control → data/processed/; "
            "'predict' — PPI + prevalence estimates → data/predictions/; "
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
        default=1,
        help=(
            "Concurrent extraction workers (default 1 = sequential). "
            "Recommended: 4–8 for backfill runs. All workers share one system prompt "
            "so Azure prompt caching is maximised."
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

    output_dir = Path(args.output_dir)
    domains = [d.strip() for d in args.domains.split(",") if d.strip()]

    if args.stage in ("acquire", "all"):
        if len(domains) > 1:
            # Multi-domain: scrape once, route to each codebook.
            # --codebook / --examples CLI overrides are not supported in multi-domain mode.
            if args.codebook or args.examples:
                parser.error("--codebook and --examples cannot be used with multiple --domains")
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
                geocode=not args.no_geocode,
                resume=args.resume,
                relevance_threshold=args.relevance_threshold,
                workers=args.workers,
                rpm_limit=args.rpm_limit,
            )
        else:
            domain = domains[0] if domains else "protest"
            # Resolve codebook/examples: explicit CLI flag > domain default > module default
            domain_cfg = DOMAIN_CONFIGS.get(domain, {})
            codebook_path = (
                Path(args.codebook) if args.codebook
                else domain_cfg.get("codebook")
            )
            examples_path = (
                Path(args.examples) if args.examples
                else domain_cfg.get("examples")
            )
            # Use domain-specific default query if user didn't supply --query
            query = args.query
            if query == "protest demonstration strike rally march" and domain != "protest":
                query = domain_cfg.get("query", args.query)

            # Clear checkpoint on fresh acquire run (domain-namespaced)
            checkpoint = output_dir / domain / "checkpoint.txt"
            if not args.resume and checkpoint.exists():
                checkpoint.unlink()
                log.info(f"Fresh run — cleared existing checkpoint for domain '{domain}'")

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
                geocode=not args.no_geocode,
                resume=args.resume,
                relevance_threshold=args.relevance_threshold,
                domain=domain,
                codebook_path=codebook_path,
                examples_path=examples_path,
                workers=args.workers,
                rpm_limit=args.rpm_limit,
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
    main()
