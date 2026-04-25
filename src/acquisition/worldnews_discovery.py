"""
World News API discovery source.

Uses the worldnewsapi.com search-news endpoint to discover news articles
for the given countries. Mirrors the interface of gdelt_discovery and
bbc_discovery: returns article dicts with the same field schema.

Requires: WORLDNEWS_API_KEY in environment.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

_BASE_URL = "https://api.worldnewsapi.com/search-news"
_MAX_PER_PAGE = 100


def _api_key() -> Optional[str]:
    return os.environ.get("WORLDNEWS_API_KEY")


def _format_seendate(publish_date: str) -> str:
    """Convert 'YYYY-MM-DD HH:MM:SS' → 'YYYYMMDDTHHMMSSZ'."""
    try:
        dt = datetime.strptime(publish_date, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%Y%m%dT%H%M%SZ")
    except Exception:
        return datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")


def _extract_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


def _article_dict(raw: dict) -> dict:
    return {
        "url": raw.get("url", ""),
        "title": raw.get("title", ""),
        "seendate": _format_seendate(raw.get("publish_date", "")),
        "sourcecountry": raw.get("source_country", ""),
        "sourcelanguage": raw.get("language", "en"),
        "domain": _extract_domain(raw.get("url", "")),
        "_relevance": None,
        "text": None,
        "text_lang": None,
        "text_en": None,
        "events": [],
    }


def discover_articles(
    query: str,
    countries: list,
    days: int = 7,
    max_results: int = 100,
) -> list:
    """
    Query World News API for articles matching the query within the given countries.

    Runs one paginated query per country. text=None so the scraper fetches
    full article text in Stage 2.

    Args:
        query: Space-separated keywords to search
        countries: List of ISO2 country codes
        days: How many days back to search
        max_results: Max articles to return per country

    Returns:
        List of article dicts compatible with downstream pipeline stages.
    """
    key = _api_key()
    if not key:
        log.warning("WORLDNEWS_API_KEY not set — skipping World News API discovery")
        return []

    now = datetime.utcnow()
    earliest = (now - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    latest = now.strftime("%Y-%m-%d %H:%M:%S")
    per_page = min(_MAX_PER_PAGE, max_results)

    all_articles = []

    for country in countries:
        country_articles = []
        offset = 0

        while len(country_articles) < max_results:
            params = {
                "text": query,
                "source_country": country.lower(),
                "earliest_publish_date": earliest,
                "latest_publish_date": latest,
                "number": per_page,
                "offset": offset,
                "sort": "publish-time",
                "sort_direction": "DESC",
            }

            try:
                resp = requests.get(
                    _BASE_URL,
                    params=params,
                    headers={"x-api-key": key},
                    timeout=20,
                )
            except requests.RequestException as exc:
                log.warning(f"World News API network error for {country}: {exc}")
                break

            if resp.status_code == 401:
                log.warning(
                    "World News API: invalid API key (401) — check WORLDNEWS_API_KEY"
                )
                return []

            if resp.status_code == 402:
                log.warning(
                    "World News API: quota exceeded (402) — daily limit reached"
                )
                return all_articles + country_articles

            if not resp.ok:
                log.warning(
                    f"World News API: HTTP {resp.status_code} for country={country}"
                )
                break

            news = resp.json().get("news", [])
            if not news:
                break

            for raw in news:
                if raw.get("url"):
                    country_articles.append(_article_dict(raw))

            offset += len(news)
            if len(news) < per_page:
                break

        log.info(
            f"World News API: {len(country_articles)} articles for country={country}"
        )
        all_articles.extend(country_articles)

    return all_articles
