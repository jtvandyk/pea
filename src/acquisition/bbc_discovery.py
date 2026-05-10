"""
BBC Monitoring Discovery Module
================================
Queries the BBC Monitoring API to find news articles about protest events.

API base: https://monitoring.bbc.co.uk/api
Auth: username/password login → JSESSIONID session cookie (or x-api-key header)
Rate limit: 60 requests/minute per user

Relevant search parameters used:
  - topic=Civil_unrest  (primary filter)
  - country=ZAF,NGA,... (ISO3 subject country codes)
  - category=NEWS_ALERT,REPORT,ROUND_UP
  - fromDate/toDate (YYYY-MM-DD)
  - searchText (Lucene syntax)

Credentials read from environment:
  BBC_MONITORING_USER_NAME
  BBC_MONITORING_USER_PASSWORD
"""

import logging
import os
import re
import time
from datetime import datetime, timedelta
from html.parser import HTMLParser
from typing import Optional

import requests

from src.constants import ISO2_TO_ISO3

log = logging.getLogger(__name__)

BBC_BASE_URL = "https://monitoring.bbc.co.uk"
BBC_LOGIN_URL = f"{BBC_BASE_URL}/api/v0/login"
BBC_SEARCH_URL = f"{BBC_BASE_URL}/api/v0/search"
BBC_PRODUCT_URL = f"{BBC_BASE_URL}/api/v0/product"

# BBC Monitoring topic codes relevant to protest/unrest.
# Note: Civil_unrest is sparsely tagged for Africa — don't use as a hard filter;
# rely on keyword search instead.
PROTEST_TOPICS = ["Civil_unrest", "Domestic_political", "Human_rights"]

# Categories to include. BIOGRAPHY and ARMED_ORGANISATION are excluded because
# they match protest keywords in passing (e.g. politician bios, group profiles)
# but are not event reports. PROGRAMME_SUMMARY included — broadcast summaries
# from African outlets often contain the most granular local protest coverage.
PROTEST_CATEGORIES = ["NEWS_ALERT", "REPORT", "ROUND_UP", "PROGRAMME_SUMMARY"]

# Categories explicitly excluded (passed to API via exclusion in query logic)
_EXCLUDE_CATEGORIES = [
    "BIOGRAPHY",
    "ARMED_ORGANISATION",
    "ORGANISATION",
    "POLITICAL_PARTY",
    "TRADE_UNION",
    "FORCES",
    "REGIONAL_AND_LOCAL_GOVERNMENT",
    "MEDIA_GUIDE",
]


class _HTMLStripper(HTMLParser):
    """Minimal HTML-to-plaintext converter."""

    def __init__(self):
        super().__init__()
        self._parts = []

    def handle_data(self, data):
        self._parts.append(data)

    def get_text(self):
        return " ".join(self._parts)


def _strip_html(html: str) -> str:
    stripper = _HTMLStripper()
    stripper.feed(html or "")
    text = stripper.get_text()
    # Collapse whitespace
    return re.sub(r"\s+", " ", text).strip()


def bbc_login(username: str, password: str, timeout: int = 30) -> Optional[str]:
    """
    Authenticate with BBC Monitoring and return the JSESSIONID session token.

    Successful login returns HTTP 204 (No Content) with a Set-Cookie header
    containing the JSESSIONID. Token expires 72 hours after issue.

    Returns None on failure.
    """
    try:
        resp = requests.post(
            BBC_LOGIN_URL,
            json={"username": username, "password": password},
            timeout=timeout,
        )
        if resp.status_code == 204:
            token = resp.cookies.get("JSESSIONID")
            if token:
                log.info("BBC Monitoring login successful")
                return token
            log.warning(
                "BBC Monitoring login: 204 received but no JSESSIONID cookie in response"
            )
            return None
        if resp.status_code == 401:
            log.error("BBC Monitoring login: incorrect username or password")
            return None
        if resp.status_code == 403:
            log.error(
                "BBC Monitoring login: Terms & Conditions not accepted. "
                "Log in via browser at monitoring.bbc.co.uk to accept them first."
            )
            return None
        log.error(
            f"BBC Monitoring login: unexpected status {resp.status_code} — {resp.text[:200]}"
        )
        return None
    except Exception as e:
        log.error(f"BBC Monitoring login error: {e}")
        return None


def _build_session_headers(session_token: str) -> dict:
    return {"Cookie": f"JSESSIONID={session_token}"}


class _BBCSession:
    """Holds BBC creds + token; re-logs in on 401.

    BBC Monitoring tokens expire 72 hours after issue. A 7-day backfill or any
    long-running session that exceeds this will start hitting 401s mid-stream.
    Wrapping the token + creds together lets search_bbc and fetch_bbc_product
    transparently re-authenticate once on 401 and continue.
    """

    def __init__(self, username: str, password: str):
        self._username = username
        self._password = password
        self.token: Optional[str] = None

    def login(self) -> bool:
        self.token = bbc_login(self._username, self._password)
        return self.token is not None

    def refresh(self) -> bool:
        """Re-authenticate after a 401. Returns True on success."""
        log.warning("BBC token rejected (401) — re-authenticating once")
        return self.login()

    def headers(self) -> dict:
        return _build_session_headers(self.token or "")


def _is_unauthorized(exc: BaseException) -> bool:
    """True if a requests exception came back with HTTP 401."""
    if isinstance(exc, requests.exceptions.HTTPError):
        resp = getattr(exc, "response", None)
        return resp is not None and resp.status_code == 401
    return False


def search_bbc(
    params: dict,
    session: "_BBCSession",
    max_results: int = 100,
    rate_limit_delay: float = 1.1,
) -> list:
    """
    Call BBC Monitoring search API with cursor-based pagination.
    Returns flat list of product metadata dicts.

    Re-authenticates and retries the current page once on 401.
    """
    results: list = []
    cursor = None
    refreshed_once = False

    while len(results) < max_results:
        page_params = dict(params)
        page_params["limit"] = min(20, max_results - len(results))
        if cursor:
            page_params["cursor"] = cursor

        try:
            resp = requests.get(
                BBC_SEARCH_URL,
                params=page_params,
                headers=session.headers(),
                timeout=30,
            )
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            if _is_unauthorized(e) and not refreshed_once:
                refreshed_once = True
                if session.refresh():
                    continue  # retry the same page with the fresh token
                log.warning("BBC search: re-auth failed after 401 — stopping")
                break
            log.warning(f"BBC search HTTP error: {e}")
            break
        except Exception as e:
            log.warning(f"BBC search error: {e}")
            break

        try:
            data = resp.json()
        except Exception as e:
            log.warning(f"BBC search JSON parse error: {e} — {resp.text[:200]}")
            break

        products = data.get("products", [])
        results.extend(products)
        log.debug(
            f"BBC search page: {len(products)} results (total so far: {len(results)})"
        )

        cursor = data.get("cursor")
        if not cursor or not products:
            break

        time.sleep(rate_limit_delay)

    return results


def fetch_bbc_product(product_id: str, session: "_BBCSession") -> Optional[dict]:
    """
    Fetch full article content for a single BBC Monitoring product ID.
    Returns product dict with bodyHtml, or None on failure.

    Re-authenticates and retries once on 401.
    """
    for attempt in range(2):
        try:
            resp = requests.get(
                f"{BBC_PRODUCT_URL}/{product_id}",
                params={"outputFormat": "HTML", "includePdfUrl": "false"},
                headers=session.headers(),
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            if _is_unauthorized(e) and attempt == 0:
                if session.refresh():
                    continue
                return None
            if e.response is not None and e.response.status_code == 402:
                log.debug(f"BBC product {product_id}: not in subscription")
            else:
                log.warning(f"BBC product {product_id} HTTP error: {e}")
            return None
        except Exception as e:
            log.warning(f"BBC product {product_id} error: {e}")
            return None
    return None


def discover_articles(
    query: str,
    countries: list,
    days: int = 7,
    max_results: int = 100,
    fetch_full_text: bool = True,
) -> list:
    """
    Main discovery function. Authenticates with BBC Monitoring, searches for
    protest-related articles, and returns candidate article metadata.

    Credentials are read from BBC_MONITORING_USER_NAME and
    BBC_MONITORING_USER_PASSWORD environment variables.

    Args:
        query: additional keyword search string (Lucene syntax supported)
        countries: list of ISO2 country codes to filter subject country
        days: lookback window in days
        max_results: cap on number of articles returned
        fetch_full_text: if True, fetches full bodyHtml for each article (costs
                         one additional API request per article — disable if
                         only metadata is needed)

    Returns:
        list of article dicts with keys: url, title, seendate, sourcecountry,
        sourcelanguage, domain, text, _relevance
    """
    username = os.environ.get("BBC_MONITORING_USER_NAME", "")
    password = os.environ.get("BBC_MONITORING_USER_PASSWORD", "")
    if not username or not password:
        log.error(
            "BBC_MONITORING_USER_NAME and BBC_MONITORING_USER_PASSWORD must be set in env"
        )
        return []

    session = _BBCSession(username, password)
    if not session.login():
        log.error("BBC Monitoring authentication failed — skipping BBC discovery")
        return []

    # Convert ISO2 country codes to ISO3 (BBC uses ISO3)
    iso3_countries = [ISO2_TO_ISO3.get(c, c) for c in countries if c in ISO2_TO_ISO3]
    if not iso3_countries:
        log.warning(f"No valid ISO3 mappings for countries: {countries}")
        iso3_countries = countries  # pass through as-is and hope for the best

    from_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    to_date = datetime.utcnow().strftime("%Y-%m-%d")

    # Primary strategy: keyword search + explicit category allowlist.
    # We do NOT filter by topic because Civil_unrest is sparsely tagged for Africa.
    # BBC uses Lucene syntax: space = AND, so convert space-separated keywords to OR.
    if query:
        words = [w for w in query.split() if w]
        search_text = " OR ".join(words)
    else:
        search_text = "protest OR strike OR demonstration OR riot OR unrest"

    params = {
        "searchText": search_text,
        "category": PROTEST_CATEGORIES,
        "country": iso3_countries,
        "fromDate": from_date,
        "toDate": to_date,
        "sort": "publication_time",
        "sortDirection": "DESC",
    }

    log.info(
        f"Querying BBC Monitoring: countries={iso3_countries}, "
        f"categories={PROTEST_CATEGORIES}, from={from_date}"
    )

    raw_products = search_bbc(params, session, max_results=max_results)
    log.info(f"BBC Monitoring returned {len(raw_products)} products")

    if not raw_products:
        # Fallback: drop category filter but keep keyword search
        log.info("Retrying without category filter...")
        params_broad = {k: v for k, v in params.items() if k != "category"}
        raw_products = search_bbc(params_broad, session, max_results=max_results)
        log.info(f"BBC broad search returned {len(raw_products)} products")

    normalized = []
    seen_ids = set()

    for i, product in enumerate(raw_products[:max_results]):
        product_id = product.get("id", "")
        if not product_id or product_id in seen_ids:
            continue
        seen_ids.add(product_id)

        # Publication time is a Unix timestamp in milliseconds (may be null)
        try:
            pub_ts = int(product.get("publicationTime") or 0)
            pub_date = (
                datetime.utcfromtimestamp(pub_ts / 1000).strftime("%Y%m%dT%H%M%SZ")
                if pub_ts
                else ""
            )
        except (OSError, OverflowError, ValueError, TypeError):
            pub_date = ""

        # Subject countries — take first for display
        subject_countries = product.get("subjectCountryIds", [])
        source_country = product.get("sourceCity", "") or (
            subject_countries[0] if subject_countries else ""
        )

        article = {
            "url": f"{BBC_PRODUCT_URL}/{product_id}",
            "title": product.get("headline", ""),
            "seendate": pub_date,
            "sourcecountry": source_country,
            "sourcelanguage": product.get("languageName", ""),
            "domain": "monitoring.bbc.co.uk",
            "_relevance": "bbc_topic_match",
            "text": None,
            "text_lang": None,
            "text_en": None,
            "events": [],
            # BBC-specific extras (useful for filtering/debugging)
            "_bbc_id": product_id,
            "_bbc_category": product.get("category", ""),
            "_bbc_topics": product.get("topics", []),
            "_bbc_source_id": product.get("sourceId", ""),
            "_bbc_source_type": product.get("sourceType", ""),
        }

        # Optionally fetch full text (one request per article)
        if fetch_full_text:
            time.sleep(1.1)  # stay under 60 req/min
            full = fetch_bbc_product(product_id, session)
            if full:
                html = full.get("bodyHtml", "")
                article["text"] = _strip_html(html) if html else None
                article["text_lang"] = full.get("languageName", "")

        normalized.append(article)

        if (i + 1) % 10 == 0:
            log.info(f"  Processed {i + 1}/{len(raw_products)} BBC products...")

    log.info(f"Returning {len(normalized)} BBC candidate articles")
    return normalized
