"""
Protest Event Analysis Pipeline
================================
End-to-end pipeline for Global South / non-Western protest event data collection,
full-text retrieval, and LLM-based structured extraction.

Stages:
  1. DISCOVERY   — query GDELT DOC API for candidate article URLs
  2. SCRAPING    — fetch full article text from source URLs
  3. TRANSLATION — detect and translate non-English text (optional)
  4. EXTRACTION  — Claude (Anthropic API) extracts structured protest event fields
  5. STORAGE     — save results to data/raw/ as JSONL + CSV

Codebook version: 2.1

Usage (from repo root):
    python -m src.acquisition.pipeline
    python -m src.acquisition.pipeline --query "protest strike" --countries NG,ZA,UG,DZ --days 7
    python -m src.acquisition.pipeline --help

Requires:
    ANTHROPIC_API_KEY environment variable (or pass --claude-api-key)
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from datetime import datetime

from src.acquisition.gdelt_discovery import discover_articles
from src.acquisition.scraper import scrape_articles
from src.acquisition.translator import translate_articles
from src.acquisition.extractor import extract_events
from src.acquisition.storage import save_results

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("pipeline")

# Default output dir — aligns with project data structure
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"


def run_pipeline(
    query: str,
    countries: list,
    days: int,
    output_dir: Path,
    max_articles: int = 100,
    translate: bool = True,
    claude_model: str = "claude-sonnet-4-6",
    claude_api_key: str | None = None,
):
    log.info("=== Protest Event Analysis Pipeline (codebook v2.1) ===")
    log.info(f"Query: '{query}' | Countries: {countries} | Days back: {days}")
    log.info(f"LLM: {claude_model} (Anthropic Claude API)")

    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    # Stage 1: Discovery
    log.info("--- Stage 1: GDELT Discovery ---")
    articles = discover_articles(
        query=query, countries=countries, days=days, max_results=max_articles
    )
    log.info(f"Discovered {len(articles)} candidate articles")

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
    events = extract_events(
        scraped,
        model=claude_model,
        api_key=claude_api_key,
    )
    log.info(f"Extracted {len(events)} protest events")

    # Stage 5: Storage
    log.info("--- Stage 5: Saving Results ---")
    out_path = save_results(events, output_dir=output_dir, run_id=run_id)
    log.info(f"Results saved to {out_path}")

    log.info("=== Pipeline complete ===")
    return events


def main():
    parser = argparse.ArgumentParser(
        description="Protest Event Analysis Pipeline — Global South focus (codebook v2.1)"
    )
    parser.add_argument(
        "--query", default="protest demonstration strike rally march",
        help="Keywords to search in GDELT (space-separated)"
    )
    parser.add_argument(
        "--countries", default="NG,ZA,UG,DZ",
        help="Comma-separated ISO2 country codes"
    )
    parser.add_argument("--days", type=int, default=7,
                        help="How many days back to search")
    parser.add_argument("--max-articles", type=int, default=50,
                        help="Max articles to process")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR),
                        help="Directory to write results (default: data/raw/)")
    parser.add_argument("--no-translate", action="store_true",
                        help="Skip translation step")
    parser.add_argument("--claude-model", default="claude-sonnet-4-6",
                        help="Claude model ID (default: claude-sonnet-4-6)")
    parser.add_argument("--claude-api-key", default=None,
                        help="Anthropic API key (defaults to ANTHROPIC_API_KEY env var)")
    args = parser.parse_args()

    run_pipeline(
        query=args.query,
        countries=args.countries.split(","),
        days=args.days,
        output_dir=Path(args.output_dir),
        max_articles=args.max_articles,
        translate=not args.no_translate,
        claude_model=args.claude_model,
        claude_api_key=args.claude_api_key,
    )


if __name__ == "__main__":
    main()
