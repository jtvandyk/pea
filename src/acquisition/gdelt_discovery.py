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


def build_gdelt_query(query: str, countries: list, days: int) -> dict:
    """
    Build GDELT DOC API query parameters.

    Args:
        query: keyword search string (space = AND, pipe = OR in GDELT)
        countries: list of ISO2 country codes to filter source country
        days: number of days back to search (GDELT max is ~3 months for DOC API)

    Returns:
        dict of query parameters
    """
    # GDELT DOC API only accepts specific timespan values — arbitrary day counts fail silently.
    # Valid values: 15min, 1hour, 4hours, 1day, 7days, 1month, 3months, 6months, 1year
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

    # Build keyword query — GDELT requires OR'd terms to be wrapped in ()
    keyword_parts = [f'"{term}"' if " " in term else term for term in query.split()]
    keyword_query = "(" + " OR ".join(keyword_parts) + ")"

    params = {
        "query": keyword_query,
        "mode": "ArtList",  # return article list (not timeline)
        "maxrecords": 250,  # max per request
        "timespan": timespan,
        "format": "json",
        "sort": "DateDesc",
    }

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


def filter_protest_relevant(articles: list[dict], min_score: float = 0.0) -> list[dict]:
    """
    Filter articles to keep only those likely to be about protest events.
    GDELT returns articles matching the keyword query but may include noise.
    """
    # Keywords that strongly indicate protest event reporting
    protest_signals = {
        "protest",
        "protests",
        "protester",
        "protesters",
        "demonstration",
        "demonstrators",
        "march",
        "marched",
        "strike",
        "strikes",
        "strikers",
        "walkout",
        "rally",
        "rallies",
        "riot",
        "riots",
        "unrest",
        "uprising",
        "revolt",
        "rebellion",
        "civil disobedience",
        "blockade",
        "sit-in",
        "clashes",
        "crackdown",
        "teargas",
        "tear gas",
        "detained",
        "arrested",
        "dispersed",
        # Non-English signals (common in multilingual GDELT)
        "manifestation",
        "manifestantes",  # Spanish/French
        "huelga",
        "paro",  # Spanish
        "grève",
        "manifestation",  # French
        "aksi",
        "demonstrasi",  # Indonesian/Malay
        "احتجاج",
        "مظاهرة",  # Arabic
    }

    filtered = []
    for article in articles:
        title = (article.get("title") or "").lower()
        url = (article.get("url") or "").lower()

        # Check title for protest signals
        if any(signal in title for signal in protest_signals):
            article["_relevance"] = "title_match"
            filtered.append(article)
        elif any(
            signal in url
            for signal in ["protest", "strike", "demo", "march", "riot", "unrest"]
        ):
            article["_relevance"] = "url_match"
            filtered.append(article)
        else:
            # Keep anyway if it passed GDELT's theme filter — mark as uncertain
            article["_relevance"] = "gdelt_theme"
            filtered.append(article)

    return filtered


def discover_articles(
    query: str,
    countries: list,
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
    log.info(
        f"Querying GDELT DOC API: query='{query}', countries={countries}, days={days}"
    )

    params = build_gdelt_query(query, countries, days)
    log.debug(f"GDELT params: {params}")

    raw_articles = fetch_gdelt_articles(params)
    log.info(f"GDELT returned {len(raw_articles)} raw articles")

    if not raw_articles:
        # Fallback: try without sourcecountry filter (GDELT sourcecountry is sometimes unreliable)
        # but add country name(s) to the keyword query so results stay geographically relevant
        log.info(
            "Retrying without sourcecountry filter — adding country name keywords instead..."
        )
        time.sleep(5)  # brief pause before fallback to avoid rate limits
        fallback_params = {k: v for k, v in params.items() if k != "sourcecountry"}
        country_names = [COUNTRY_LABELS[c] for c in countries if c in COUNTRY_LABELS]
        if country_names:
            country_name_query = (
                "(" + " OR ".join(f'"{n}"' for n in country_names) + ")"
            )
            base_query = fallback_params.get("query", "")
            if country_name_query not in base_query:
                fallback_params["query"] = f"{base_query} {country_name_query}"
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

    # Filter for protest relevance
    filtered = filter_protest_relevant(normalized)

    # Cap results
    result = filtered[:max_results]
    log.info(f"Returning {len(result)} candidate articles after filtering")
    return result
