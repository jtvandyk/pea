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
):
    log.info("=== Protest Event Analysis Pipeline (codebook v2.3) ===")
    log.info(f"Query: '{query}' | Countries: {countries} | Days back: {days}")
    log.info(
        f"LLM provider: {provider} | model: {model or 'default'} | source: {source}"
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    # Sync checkpoint from blob before reading it (enables resume after container restart)
    if resume and upload_to:
        sync_checkpoint_from_blob(upload_to, output_dir)

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

    # Stage 2.5: Relevance filter — rejects non-protest articles before LLM
    log.info("--- Stage 2.5: Relevance Filter (ConfliBERT / keyword fallback) ---")
    _rf = RelevanceFilter(threshold=relevance_threshold)
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

    # Stage 4: LLM Extraction via Claude
    log.info("--- Stage 4: LLM Event Extraction (Claude API) ---")
    checkpoint_path = str(output_dir / "checkpoint.txt")
    events, failures = extract_events(
        scraped,
        model=model,
        api_key=api_key,
        provider=provider,
        checkpoint_path=checkpoint_path,
        upload_to=upload_to,
    )
    log.info(
        f"Extracted {len(events)} protest events ({len(failures)} extraction failures)"
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
    )
    log.info(f"Results saved to {out_path}")

    log.info("=== Pipeline complete ===")
    return events


def main():
    from dotenv import load_dotenv

    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Protest Event Analysis Pipeline — Global South focus (codebook v2.1)"
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
    args = parser.parse_args()

    output_dir = Path(args.output_dir)

    if args.stage in ("acquire", "all"):
        # Clear checkpoint on fresh acquire run
        checkpoint = output_dir / "checkpoint.txt"
        if not args.resume and checkpoint.exists():
            checkpoint.unlink()
            log.info("Fresh run — cleared existing checkpoint")

        run_pipeline(
            query=args.query,
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
