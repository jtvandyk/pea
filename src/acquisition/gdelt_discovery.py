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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
import yaml

log = logging.getLogger(__name__)

# GDELT DOC 2.0 API base URL
GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"

_KEYWORDS_PATH = Path(__file__).parent.parent.parent / "configs" / "keywords.yaml"


def _load_keywords(path: Path) -> dict:
    """Load keywords YAML. Returns hardcoded fallback dict on failure."""
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        log.warning(f"Could not load keywords config ({path}): {e} — using fallback defaults")
        return {
            "protest_themes": [
                "PROTEST", "UNREST", "STRIKE", "DEMONSTRATION",
                "RIOT", "CIVIL_UNREST", "SOC_PROTEST", "TAX_FNCACT_PROTESTER",
            ],
            "protest_signals": [
                "protest", "demonstration", "strike", "march", "riot", "unrest",
                "rally", "uprising", "blockade", "clashes", "crackdown",
            ],
            "url_signals": ["protest", "strike", "demo", "march", "riot", "unrest"],
        }


_KEYWORDS = _load_keywords(_KEYWORDS_PATH)

# GDELT GKG themes related to protest/unrest — use these as secondary filters
# Full theme list: http://data.gdeltproject.org/api/v2/guides/LOOKUP-GKGTHEMES.TXT
PROTEST_THEMES: list[str] = _KEYWORDS.get("protest_themes", [])

# ISO2 → country display name (used for keyword fallback in multi-country queries)
COUNTRY_LABELS = {
    "ZA": "South Africa",
    "NG": "Nigeria",
    "DZ": "Algeria",
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

# ISO2 → GDELT FIPS 10-4 country code (required for sourcecountry filter)
# GDELT does NOT use ISO2 codes — passing ISO2 silently fails
ISO2_TO_FIPS = {
    "ZA": "SF",  # South Africa
    "NG": "NI",  # Nigeria
    "DZ": "AG",  # Algeria
    "UG": "UG",  # Uganda (same in both)
    "KE": "KE",  # Kenya (same in both)
    "GH": "GH",  # Ghana (same in both)
    "ET": "ET",  # Ethiopia (same in both)
    "TZ": "TZ",  # Tanzania (same in both)
    "SD": "SU",  # Sudan
    "EG": "EG",  # Egypt (same in both)
    "SN": "SG",  # Senegal
    "ZW": "ZI",  # Zimbabwe
    "IN": "IN",  # India (same in both)
    "PK": "PK",  # Pakistan (same in both)
    "BD": "BG",  # Bangladesh
    "ID": "ID",  # Indonesia (same in both)
    "PH": "RP",  # Philippines
    "TH": "TH",  # Thailand (same in both)
    "VN": "VM",  # Vietnam
    "BR": "BR",  # Brazil (same in both)
    "MX": "MX",  # Mexico (same in both)
    "CO": "CO",  # Colombia (same in both)
    "AR": "AR",  # Argentina (same in both)
    "PE": "PE",  # Peru (same in both)
    "IQ": "IZ",  # Iraq
    "MM": "BM",  # Myanmar/Burma
}


def build_gdelt_query(
    query: str,
    countries: list,
    days: int = 7,
    start_dt: Optional[datetime] = None,
    end_dt: Optional[datetime] = None,
) -> dict:
    """
    Build GDELT DOC API query parameters.

    Args:
        query:    keyword search string (space = AND, pipe = OR in GDELT)
        countries: list of ISO2 country codes to filter source country
        days:     number of days back to search (used when start_dt/end_dt not given)
        start_dt: explicit window start (GDELT startdatetime param)
        end_dt:   explicit window end   (GDELT enddatetime param)

    Returns:
        dict of query parameters
    """
    # Build keyword query — GDELT requires OR'd terms to be wrapped in ()
    keyword_parts = [f'"{term}"' if " " in term else term for term in query.split()]
    keyword_query = "(" + " OR ".join(keyword_parts) + ")"

    params = {
        "query": keyword_query,
        "mode": "ArtList",
        "maxrecords": 250,
        "format": "json",
        "sort": "DateDesc",
    }

    if start_dt and end_dt:
        # Explicit date range — overrides timespan.
        # GDELT DOC API format: YYYYMMDDHHMMSS
        params["startdatetime"] = start_dt.strftime("%Y%m%d%H%M%S")
        params["enddatetime"] = end_dt.strftime("%Y%m%d%H%M%S")
    else:
        # Relative timespan — GDELT only accepts specific values.
        if days <= 1:
            timespan = "1day"
        elif days <= 7:
            timespan = "7days"
        elif days <= 31:
            timespan = "1month"
        elif days <= 92:
            timespan = "3months"
        elif days <= 183:
            timespan = "6months"
        else:
            timespan = "1year"
        params["timespan"] = timespan

    # GDELT sourcecountry requires FIPS codes, not ISO2.
    # The parameter only accepts a single country — for multiple countries we
    # append country names to the keyword query instead.
    if len(countries) == 1:
        fips = ISO2_TO_FIPS.get(countries[0], countries[0])
        params["sourcecountry"] = fips
        log.debug(f"Using FIPS code '{fips}' for country '{countries[0]}'")
    elif countries:
        country_name_query = (
            "("
            + " OR ".join(
                f'"{COUNTRY_LABELS[c]}"' for c in countries if c in COUNTRY_LABELS
            )
            + ")"
        )
        if country_name_query != "()":
            params["query"] = f"{keyword_query} {country_name_query}"

    return params


def fetch_gdelt_articles(params: dict, retries: int = 3) -> list[dict]:
    """
    Call GDELT DOC API and return raw article list.
    """
    import json as _json

    for attempt in range(retries):
        resp = None
        try:
            resp = requests.get(GDELT_DOC_API, params=params, timeout=60)
            resp.raise_for_status()
        except requests.exceptions.Timeout:
            log.warning(f"GDELT request timed out (attempt {attempt+1})")
            if attempt < retries - 1:
                time.sleep(2**attempt)
            continue
        except requests.exceptions.HTTPError as e:
            log.warning(f"GDELT HTTP error (attempt {attempt+1}): {e}")
            if attempt < retries - 1:
                wait = 30 * (attempt + 1) if "429" in str(e) else 2**attempt
                time.sleep(wait)
            continue
        except requests.exceptions.RequestException as e:
            log.warning(f"GDELT connection error (attempt {attempt+1}): {e}")
            if attempt < retries - 1:
                time.sleep(2**attempt)
            continue

        # Parse JSON manually so we can log what GDELT actually returned on failure
        text = resp.text.strip() if resp else ""
        if not text:
            log.warning(
                f"GDELT returned empty body (attempt {attempt+1}) — invalid param or rate limit"
            )
            break
        try:
            data = _json.loads(text)
            return data.get("articles", [])
        except _json.JSONDecodeError as e:
            log.warning(
                f"GDELT JSON parse error (attempt {attempt+1}): {e} — response: {text[:300]}"
            )
            break

    return []


_PROTEST_SIGNALS: set[str] = set(_KEYWORDS.get("protest_signals", []))
_URL_SIGNALS: list[str] = _KEYWORDS.get("url_signals", [])


def _normalize_articles(raw: list[dict]) -> list[dict]:
    """Normalize GDELT article dicts to the pipeline's standard field set."""
    normalized = []
    for art in raw:
        url = art.get("url", "")
        if not url:
            continue
        normalized.append(
            {
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
            }
        )
    return normalized


def _tag_relevance(articles: list[dict]) -> list[dict]:
    """
    Tag each article with a '_relevance' hint based on title/URL keyword matching.
    All articles are returned — GDELT pre-filters by theme, so nothing is dropped here.
    The tag is used downstream by the relevance filter for diagnostic logging only.
    """
    for article in articles:
        title = (article.get("title") or "").lower()
        url = (article.get("url") or "").lower()
        if any(signal in title for signal in _PROTEST_SIGNALS):
            article["_relevance"] = "title_match"
        elif any(signal in url for signal in _URL_SIGNALS):
            article["_relevance"] = "url_match"
        else:
            article["_relevance"] = "gdelt_theme"
    return articles


def _fetch_for_country(query: str, country: str, days: int) -> list[dict]:
    """
    Fetch GDELT articles for a single country using the FIPS sourcecountry filter.
    Falls back to country-name keyword injection if the primary query returns nothing.
    """
    params = build_gdelt_query(query, [country], days)
    log.debug(f"GDELT params for {country}: {params}")
    articles = fetch_gdelt_articles(params)

    if not articles:
        log.info(
            f"No results for {country} with sourcecountry filter — "
            "retrying with country name keywords..."
        )
        time.sleep(5)
        fallback_params = {k: v for k, v in params.items() if k != "sourcecountry"}
        country_name = COUNTRY_LABELS.get(country)
        if country_name:
            base_query = fallback_params.get("query", "")
            fallback_params["query"] = f'{base_query} "{country_name}"'
        articles = fetch_gdelt_articles(fallback_params)
        log.info(f"Fallback for {country} returned {len(articles)} articles")

    return articles


def discover_articles_date_range(
    query: str,
    countries: list,
    start_date: datetime,
    end_date: datetime,
    max_results_per_window: int = 250,
    window_days: int = 30,
) -> list[dict]:
    """
    Backfill discovery over an arbitrary historical date range.

    Chunks the range into `window_days`-sized windows (iterated newest-first)
    and calls discover_articles() per window.  Deduplicates by URL across all
    windows.  Use this instead of discover_articles() when `--backfill-from`
    is set; it bypasses GDELT's 1-year `timespan` ceiling.

    Args:
        query:                  keyword search string
        countries:              list of ISO2 country codes
        start_date:             beginning of historical window (inclusive)
        end_date:               end of historical window (inclusive)
        max_results_per_window: GDELT maxrecords per sub-query (≤250)
        window_days:            size of each chunk in days (default 30)

    Returns:
        deduplicated list of article dicts across all windows
    """
    seen_urls: dict[str, dict] = {}
    window_end = end_date
    total_windows = 0

    while window_end > start_date:
        window_start = max(window_end - timedelta(days=window_days), start_date)
        total_windows += 1
        log.info(
            f"Backfill window {total_windows}: "
            f"{window_start.strftime('%Y-%m-%d')} → {window_end.strftime('%Y-%m-%d')}"
        )

        for country in countries:
            params = build_gdelt_query(
                query, [country],
                start_dt=window_start,
                end_dt=window_end,
            )
            params["maxrecords"] = max_results_per_window
            articles = fetch_gdelt_articles(params)
            log.info(
                f"  {country}: {len(articles)} raw articles "
                f"({window_start.strftime('%Y-%m-%d')}–{window_end.strftime('%Y-%m-%d')})"
            )
            for art in articles:
                url = art.get("url", "")
                if url and url not in seen_urls:
                    seen_urls[url] = art

        # Step back — next window ends where this one started
        window_end = window_start
        if window_end <= start_date:
            break
        # Brief pause between windows to avoid hammering GDELT
        time.sleep(2)

    raw_articles = list(seen_urls.values())
    log.info(
        f"Backfill complete: {total_windows} windows, "
        f"{len(raw_articles)} unique articles across all countries"
    )

    return _tag_relevance(_normalize_articles(raw_articles))


def discover_articles(
    query: str,
    countries: list,
    days: int = 7,
    max_results: int = 100,
) -> list[dict]:
    """
    Main discovery function. Queries GDELT and returns candidate article metadata.

    Runs one query per country using the GDELT sourcecountry FIPS filter so that
    results are geographically precise. Country-name keyword injection (which
    introduces noise) is only used as a per-country fallback when sourcecountry
    returns nothing.

    Args:
        query: search keywords
        countries: list of ISO2 source country codes
        days: lookback window
        max_results: cap on number of articles returned

    Returns:
        list of article dicts with keys: url, title, seendate, sourcecountry,
        sourcelanguage, domain, _relevance
    """
    log.info(
        f"Querying GDELT DOC API: query='{query}', countries={countries}, days={days}"
    )

    # One GDELT request per country — uses accurate sourcecountry FIPS filter.
    # Merge and dedup by URL across all per-country result sets.
    seen_urls: dict[str, dict] = {}
    for country in countries:
        articles = _fetch_for_country(query, country, days)
        log.info(f"GDELT returned {len(articles)} raw articles for {country}")
        for art in articles:
            url = art.get("url", "")
            if url and url not in seen_urls:
                seen_urls[url] = art

    raw_articles = list(seen_urls.values())
    log.info(f"Total unique articles across all countries: {len(raw_articles)}")

    result = _tag_relevance(_normalize_articles(raw_articles))[:max_results]
    log.info(f"Returning {len(result)} candidate articles after filtering")
    return result
