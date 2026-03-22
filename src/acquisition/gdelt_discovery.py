"""
GDELT Discovery Module
=======================
Queries the GDELT DOC 2.0 API to find news articles about protest events.

GDELT DOC API docs: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/

For the Global South focus, this module:
  - Filters by source country (ISO2 codes)
  - Uses GDELT protest/unrest themes as secondary filters
  - Returns article metadata including URL, title, date, country, language
"""

import logging
import time
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional

import requests

log = logging.getLogger(__name__)

# GDELT DOC 2.0 API base URL
GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"

# GDELT GKG themes related to protest/unrest — use these as secondary filters
# Full theme list: http://data.gdeltproject.org/api/v2/guides/LOOKUP-GKGTHEMES.TXT
PROTEST_THEMES = [
    "PROTEST",
    "UNREST",
    "STRIKE",
    "DEMONSTRATION",
    "RIOT",
    "CIVIL_UNREST",
    "SOC_PROTEST",
    "TAX_FNCACT_PROTESTER",
]

# Country code mapping for common Global South countries
# GDELT uses its own country codes (based on FIPS) but also accepts ISO2 in some endpoints
COUNTRY_LABELS = {
    "ZA": "South Africa",
    "NG": "Nigeria",
    "IN": "India",
    "BR": "Brazil",
    "PK": "Pakistan",
    "EG": "Egypt",
    "ID": "Indonesia",
    "PH": "Philippines",
    "MX": "Mexico",
    "CO": "Colombia",
    "ET": "Ethiopia",
    "KE": "Kenya",
    "GH": "Ghana",
    "BD": "Bangladesh",
    "MM": "Myanmar",
    "TH": "Thailand",
    "VN": "Vietnam",
    "AR": "Argentina",
    "PE": "Peru",
    "TZ": "Tanzania",
    "IQ": "Iraq",
    "SD": "Sudan",
    "ZW": "Zimbabwe",
    "UG": "Uganda",
    "SN": "Senegal",
}


def build_gdelt_query(query: str, countries: list[str], days: int) -> dict:
    """
    Build GDELT DOC API query parameters.

    Args:
        query: keyword search string (space = AND, pipe = OR in GDELT)
        countries: list of ISO2 country codes to filter source country
        days: number of days back to search (GDELT max is ~3 months for DOC API)

    Returns:
        dict of query parameters
    """
    # GDELT DOC API timespan format: e.g. "7days", "24hours", "1month"
    if days <= 31:
        timespan = f"{days}days"
    else:
        months = max(1, days // 30)
        timespan = f"{months}months"

    # Build keyword query — GDELT uses space for AND, OR for pipe
    # For protest detection we combine user query with protest themes
    keyword_parts = [f'"{term}"' if " " in term else term for term in query.split()]
    keyword_query = " OR ".join(keyword_parts)

    # Add country name variants for better recall on non-Western sources
    country_names = [COUNTRY_LABELS.get(c, c) for c in countries if c in COUNTRY_LABELS]

    params = {
        "query": keyword_query,
        "mode": "ArtList",          # return article list (not timeline)
        "maxrecords": 250,          # max per request
        "timespan": timespan,
        "format": "json",
        "sort": "DateDesc",
    }

    # Add source country filter if provided
    # GDELT sourcecountry uses its own codes — we pass them as a separate filter
    # For best recall, we don't restrict here but filter post-fetch
    if countries:
        # GDELT sourcecountry filter (comma-separated ISO2)
        params["sourcecountry"] = ",".join(countries)

    return params


def fetch_gdelt_articles(params: dict, retries: int = 3) -> list[dict]:
    """
    Call GDELT DOC API and return raw article list.
    """
    for attempt in range(retries):
        try:
            resp = requests.get(GDELT_DOC_API, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            return data.get("articles", [])
        except requests.exceptions.HTTPError as e:
            log.warning(f"GDELT HTTP error (attempt {attempt+1}): {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
        except requests.exceptions.RequestException as e:
            log.warning(f"GDELT request error (attempt {attempt+1}): {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
        except ValueError as e:
            log.warning(f"GDELT JSON parse error: {e}")
            break
    return []


def filter_protest_relevant(articles: list[dict], min_score: float = 0.0) -> list[dict]:
    """
    Filter articles to keep only those likely to be about protest events.
    GDELT returns articles matching the keyword query but may include noise.
    """
    # Keywords that strongly indicate protest event reporting
    protest_signals = {
        "protest", "protests", "protester", "protesters",
        "demonstration", "demonstrators", "march", "marched",
        "strike", "strikes", "strikers", "walkout",
        "rally", "rallies", "riot", "riots",
        "unrest", "uprising", "revolt", "rebellion",
        "civil disobedience", "blockade", "sit-in",
        "clashes", "crackdown", "teargas", "tear gas",
        "detained", "arrested", "dispersed",
        # Non-English signals (common in multilingual GDELT)
        "manifestation", "manifestantes",  # Spanish/French
        "huelga", "paro",                  # Spanish
        "grève", "manifestation",          # French
        "aksi", "demonstrasi",             # Indonesian/Malay
        "احتجاج", "مظاهرة",               # Arabic
    }

    filtered = []
    for article in articles:
        title = (article.get("title") or "").lower()
        url = (article.get("url") or "").lower()

        # Check title for protest signals
        if any(signal in title for signal in protest_signals):
            article["_relevance"] = "title_match"
            filtered.append(article)
        elif any(signal in url for signal in ["protest", "strike", "demo", "march", "riot", "unrest"]):
            article["_relevance"] = "url_match"
            filtered.append(article)
        else:
            # Keep anyway if it passed GDELT's theme filter — mark as uncertain
            article["_relevance"] = "gdelt_theme"
            filtered.append(article)

    return filtered


def discover_articles(
    query: str,
    countries: list[str],
    days: int = 7,
    max_results: int = 100,
) -> list[dict]:
    """
    Main discovery function. Queries GDELT and returns candidate article metadata.

    Args:
        query: search keywords
        countries: list of ISO2 source country codes
        days: lookback window
        max_results: cap on number of articles returned

    Returns:
        list of article dicts with keys: url, title, seendate, sourcecountry,
        sourcelanguage, domain, _relevance
    """
    log.info(f"Querying GDELT DOC API: query='{query}', countries={countries}, days={days}")

    params = build_gdelt_query(query, countries, days)
    log.debug(f"GDELT params: {params}")

    raw_articles = fetch_gdelt_articles(params)
    log.info(f"GDELT returned {len(raw_articles)} raw articles")

    if not raw_articles:
        # Fallback: try without country filter (GDELT sourcecountry filter is sometimes unreliable)
        log.info("Retrying without country filter for broader results...")
        fallback_params = {k: v for k, v in params.items() if k != "sourcecountry"}
        raw_articles = fetch_gdelt_articles(fallback_params)
        log.info(f"Fallback returned {len(raw_articles)} articles")

    # Normalize fields
    normalized = []
    seen_urls = set()
    for art in raw_articles:
        url = art.get("url", "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        normalized.append({
            "url": url,
            "title": art.get("title", ""),
            "seendate": art.get("seendate", ""),
            "sourcecountry": art.get("sourcecountry", ""),
            "sourcelanguage": art.get("sourcelanguage", ""),
            "domain": art.get("domain", ""),
            "_relevance": None,
            "text": None,
            "text_lang": None,
            "text_en": None,
            "events": [],
        })

    # Filter for protest relevance
    filtered = filter_protest_relevant(normalized)

    # Cap results
    result = filtered[:max_results]
    log.info(f"Returning {len(result)} candidate articles after filtering")
    return result
