"""
Article Scraper Module
=======================
Fetches full article text from news URLs discovered via GDELT.

Uses newspaper3k (primary) with a requests/BeautifulSoup fallback.
Handles rate limiting, timeouts, and common scraping failures gracefully.

For Global South sources this module:
  - Sets neutral User-Agent headers
  - Handles common non-Western CMS layouts
  - Preserves original language text before translation
"""

import logging
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.utils import extract_domain

log = logging.getLogger(__name__)

# User agents to rotate — helps with sites that block default scrapers
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",  # noqa: E501
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",  # noqa: E501
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
]

# Domains known to block scrapers — fall back gracefully
BLOCKED_DOMAINS = {
    "nytimes.com",
    "wsj.com",
    "ft.com",
    "bloomberg.com",
    "reuters.com",  # Reuters has its own API; scraping is unreliable
}

# Minimum text length to consider a scrape successful (chars)
MIN_TEXT_LENGTH = 150

# Delay range between requests (seconds) — be a polite scraper
REQUEST_DELAY = (1.0, 3.0)


def make_session() -> requests.Session:
    """Create a requests session with retry logic and reasonable timeouts."""
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def scrape_with_newspaper(url: str, session: requests.Session) -> Optional[str]:
    """
    Primary scraping method using newspaper3k.
    newspaper3k handles boilerplate removal, byline stripping, etc.
    """
    try:
        from newspaper import Article

        article = Article(url, request_timeout=15)
        article.download()
        article.parse()
        text = article.text.strip()
        if len(text) >= MIN_TEXT_LENGTH:
            return text
    except ImportError:
        log.warning("newspaper3k not installed — falling back to BeautifulSoup")
    except Exception as e:
        log.debug(f"newspaper3k failed for {url}: {e}")
    return None


def scrape_with_bs4(url: str, session: requests.Session) -> Optional[str]:
    """
    Fallback scraping using BeautifulSoup.
    Extracts paragraph text from common article containers.
    """
    try:
        from bs4 import BeautifulSoup

        headers = {"User-Agent": random.choice(USER_AGENTS)}
        resp = session.get(url, headers=headers, timeout=15)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove noise elements
        for tag in soup(
            [
                "script",
                "style",
                "nav",
                "header",
                "footer",
                "aside",
                "form",
                "iframe",
                "noscript",
            ]
        ):
            tag.decompose()

        # Try common article containers in order of preference
        article_containers = [
            soup.find("article"),
            soup.find(
                class_=lambda c: c
                and any(
                    kw in (c if isinstance(c, str) else " ".join(c))
                    for kw in [
                        "article-body",
                        "story-body",
                        "post-content",
                        "entry-content",
                        "article-content",
                        "news-body",
                        "story-content",
                        "article__body",
                    ]
                )
            ),
            soup.find("main"),
        ]

        for container in article_containers:
            if container:
                paragraphs = container.find_all("p")
                text = " ".join(p.get_text(separator=" ").strip() for p in paragraphs)
                if len(text) >= MIN_TEXT_LENGTH:
                    return text

        # Last resort: all paragraphs in body
        paragraphs = soup.find_all("p")
        text = " ".join(p.get_text(separator=" ").strip() for p in paragraphs)
        if len(text) >= MIN_TEXT_LENGTH:
            return text

    except Exception as e:
        log.debug(f"BeautifulSoup fallback failed for {url}: {e}")

    return None


def scrape_article(url: str, session: requests.Session) -> Optional[str]:
    """
    Attempt to scrape an article, trying newspaper3k first then BS4.
    Returns extracted text or None if scraping fails.
    """
    domain = extract_domain(url)

    if domain in BLOCKED_DOMAINS:
        log.debug(f"Skipping blocked domain: {domain}")
        return None

    # Try newspaper3k first (better text extraction)
    text = scrape_with_newspaper(url, session)
    if text:
        return text

    # Fallback to BeautifulSoup
    text = scrape_with_bs4(url, session)
    return text


class _HostThrottle:
    """
    Per-host politeness — one lock + last-fetch timestamp per netloc.

    Holding `lock_for(host)` across `wait_for_host(host)` AND the subsequent
    HTTP fetch guarantees same-host requests fully serialise with a jittered
    delay between them. Different hosts take different locks, so fetches
    to distinct domains run in parallel.
    """

    def __init__(self, delay_range: tuple = REQUEST_DELAY):
        self.delay_min, self.delay_max = delay_range
        self._locks: dict[str, threading.Lock] = {}
        self._last_fetch: dict[str, float] = {}
        self._registry_lock = threading.Lock()

    def lock_for(self, host: str) -> threading.Lock:
        with self._registry_lock:
            lock = self._locks.get(host)
            if lock is None:
                lock = threading.Lock()
                self._locks[host] = lock
            return lock

    def wait_for_host(self, host: str) -> None:
        """Sleep until the per-host delay since last fetch has elapsed."""
        last = self._last_fetch.get(host, 0.0)
        jitter = random.uniform(self.delay_min, self.delay_max)
        target = last + jitter
        now = time.monotonic()
        if target > now:
            time.sleep(target - now)
        self._last_fetch[host] = time.monotonic()


def scrape_articles(
    articles: list[dict],
    delay: tuple = REQUEST_DELAY,
    max_failures: int = 20,
    max_workers: int = 16,
) -> list[dict]:
    """
    Scrape full text for a list of article dicts.
    Modifies each dict in-place, adding 'text' field.

    Concurrency: up to `max_workers` threads fetch in parallel. Same-host
    requests serialise through a per-host lock + jittered delay so politeness
    is preserved; different hosts proceed in parallel.

    Args:
        articles: list of article dicts (must have 'url' field)
        delay: (min, max) seconds between consecutive fetches to the same host
        max_failures: early-abort signal — if this many failures occur with zero
            successes, stop dispatching new work (network is likely broken)
        max_workers: size of the scraping thread pool (default 16)

    Returns:
        same list with 'text' field populated where scraping succeeded
    """
    session = make_session()
    throttle = _HostThrottle(delay)
    workers = max(1, int(max_workers))

    total = len(articles)
    counters = {"success": 0, "failures": 0, "started": 0}
    counters_lock = threading.Lock()
    aborted = threading.Event()

    def _scrape_one(item: tuple) -> None:
        i, article = item
        if aborted.is_set():
            return

        url = article.get("url", "")
        if not url:
            return

        with counters_lock:
            counters["started"] += 1
            position = counters["started"]

        if article.get("text"):
            log.info(f"[{position}/{total}] Skipping (text pre-populated): {url[:80]}")
            with counters_lock:
                counters["success"] += 1
            return

        log.info(f"[{position}/{total}] Scraping: {url[:80]}...")
        host = extract_domain(url)
        host_lock = throttle.lock_for(host)

        # Hold the host lock across wait + fetch so same-host requests
        # fully serialise. Different-host fetches run in parallel.
        with host_lock:
            if aborted.is_set():
                return
            throttle.wait_for_host(host)
            text = scrape_article(url, session)

        if text:
            article["text"] = text
            word_count = len(text.split())
            log.info(f"  ✓ {word_count} words extracted ({host})")
            with counters_lock:
                counters["success"] += 1
        else:
            article["text"] = None
            log.info(f"  ✗ Scraping failed ({host})")
            with counters_lock:
                counters["failures"] += 1
                # Early abort: many failures and not a single success yet
                # → treat as network-broken and stop dispatching.
                if counters["failures"] >= max_failures and counters["success"] == 0:
                    log.warning(
                        f"Too many failures ({counters['failures']}) with no "
                        f"successes; aborting remaining scrapes."
                    )
                    aborted.set()

    log.info(
        f"Scraping {total} article(s) with {workers} worker(s), "
        f"per-host delay {delay[0]}-{delay[1]}s"
    )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        # map() consumes the iterator; we don't need return values (mutation in place).
        for _ in pool.map(_scrape_one, enumerate(articles)):
            pass

    log.info(
        f"Scraping complete: {counters['success']}/{total} articles retrieved "
        f"({counters['failures']} failed)"
    )
    return articles
