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
import time
import random
from typing import Optional
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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


def get_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


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
    domain = get_domain(url)

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


def scrape_articles(
    articles: list[dict],
    delay: tuple = REQUEST_DELAY,
    max_failures: int = 20,
) -> list[dict]:
    """
    Scrape full text for a list of article dicts.
    Modifies each dict in-place, adding 'text' field.

    Args:
        articles: list of article dicts (must have 'url' field)
        delay: (min, max) seconds to wait between requests
        max_failures: stop early if too many consecutive failures

    Returns:
        same list with 'text' field populated where scraping succeeded
    """
    session = make_session()
    failures = 0
    success = 0

    for i, article in enumerate(articles):
        url = article.get("url", "")
        if not url:
            continue

        # Skip articles that already have text (e.g. pre-populated by BBC Monitoring)
        if article.get("text"):
            log.info(
                f"[{i+1}/{len(articles)}] Skipping (text pre-populated): {url[:80]}"
            )
            success += 1
            continue

        log.info(f"[{i+1}/{len(articles)}] Scraping: {url[:80]}...")

        text = scrape_article(url, session)

        if text:
            article["text"] = text
            # Rough word count for logging
            word_count = len(text.split())
            log.info(f"  ✓ {word_count} words extracted")
            success += 1
            failures = 0  # reset consecutive failure counter
        else:
            article["text"] = None
            log.info("  ✗ Scraping failed")
            failures += 1

        if failures >= max_failures:
            log.warning(
                f"Too many consecutive failures ({failures}). Stopping scraping."
            )
            break

        # Polite delay between requests
        if i < len(articles) - 1:
            time.sleep(random.uniform(*delay))

    log.info(f"Scraping complete: {success}/{len(articles)} articles retrieved")
    return articles
