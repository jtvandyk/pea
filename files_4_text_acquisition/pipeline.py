"""
Protest Event Analysis Pipeline
================================
End-to-end pipeline for Global South / non-Western protest event data collection,
full-text retrieval, and LLM-based structured extraction.

Stages:
  1. DISCOVERY   — query GDELT DOC API for candidate article URLs
  2. SCRAPING    — fetch full article text from source URLs
  3. TRANSLATION — detect and translate non-English text (optional, via LibreTranslate)
  4. EXTRACTION  — LLM (Claude) extracts structured protest event fields
  5. STORAGE     — append results to a local JSONL file + summary CSV

Usage:
    python pipeline.py --query "protest" --countries ZA,NG,IN,BR --days 7
    python pipeline.py --query "demonstration strike" --countries PK,EG,PH --days 30
    python pipeline.py --help
"""

import argparse
import logging
import sys
from pathlib import Path
from datetime import datetime

from gdelt_discovery import discover_articles
from scraper import scrape_articles
from translator import translate_articles
from extractor import extract_events
from storage import save_results

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("pipeline")


def run_pipeline(
    query: str,
    countries: list[str],
    days: int,
    output_dir: Path,
    max_articles: int = 100,
    translate: bool = True,
    anthropic_model: str = "claude-sonnet-4-20250514",
):
    log.info("=== Protest Event Analysis Pipeline ===")
    log.info(f"Query: '{query}' | Countries: {countries} | Days back: {days}")

    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    # Stage 1: Discovery
    log.info("--- Stage 1: GDELT Discovery ---")
    articles = discover_articles(query=query, countries=countries, days=days, max_results=max_articles)
    log.info(f"Discovered {len(articles)} candidate articles")

    if not articles:
        log.warning("No articles found. Try broadening your query or country list.")
        return

    # Stage 2: Full-text scraping
    log.info("--- Stage 2: Full-text Scraping ---")
    articles = scrape_articles(articles)
    scraped = [a for a in articles if a.get("text")]
    log.info(f"Successfully scraped {len(scraped)}/{len(articles)} articles")

    if not scraped:
        log.warning("No articles could be scraped. Check network access.")
        return

    # Stage 3: Translation (optional)
    if translate:
        log.info("--- Stage 3: Translation ---")
        scraped = translate_articles(scraped)

    # Stage 4: LLM Extraction
    log.info("--- Stage 4: LLM Event Extraction ---")
    events = extract_events(scraped, model=anthropic_model)
    log.info(f"Extracted {len(events)} protest events")

    # Stage 5: Storage
    log.info("--- Stage 5: Saving Results ---")
    out_path = save_results(events, output_dir=output_dir, run_id=run_id)
    log.info(f"Results saved to {out_path}")

    log.info("=== Pipeline complete ===")
    return events


def main():
    parser = argparse.ArgumentParser(
        description="Protest Event Analysis Pipeline — Global South focus"
    )
    parser.add_argument(
        "--query", default="protest demonstration strike rally march",
        help="Keywords to search in GDELT (space-separated = OR logic)"
    )
    parser.add_argument(
        "--countries", default="ZA,NG,IN,BR,PK,EG,ID,PH,MX,CO",
        help="Comma-separated ISO2 country codes (GDELT format)"
    )
    parser.add_argument("--days", type=int, default=7, help="How many days back to search")
    parser.add_argument("--max-articles", type=int, default=50, help="Max articles to process")
    parser.add_argument("--output-dir", default="./output", help="Directory to write results")
    parser.add_argument("--no-translate", action="store_true", help="Skip translation step")
    args = parser.parse_args()

    run_pipeline(
        query=args.query,
        countries=args.countries.split(","),
        days=args.days,
        output_dir=Path(args.output_dir),
        max_articles=args.max_articles,
        translate=not args.no_translate,
    )


if __name__ == "__main__":
    main()
