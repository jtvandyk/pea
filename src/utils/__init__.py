"""
Shared utility helpers for the PEA pipeline.

Consolidates small functions that were previously duplicated across
discovery modules (file_discovery, worldnews_discovery, scraper).
"""

import logging
from datetime import datetime
from urllib.parse import urlparse

log = logging.getLogger(__name__)

# Date formats accepted by format_seendate, in preference order
_DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
)


def format_seendate(date_str: str) -> str:
    """
    Parse a flexible date string and return YYYYMMDDTHHMMSSZ.
    Falls back to the current UTC time if the string cannot be parsed.
    """
    if date_str:
        for fmt in _DATE_FORMATS:
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                return dt.strftime("%Y%m%dT%H%M%SZ")
            except ValueError:
                continue
    log.warning(f"Could not parse date '{date_str}'; using current UTC time")
    return datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")


def extract_domain(url: str) -> str:
    """Return the bare domain (no www.) from a URL string."""
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""
