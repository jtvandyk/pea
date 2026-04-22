"""
Geocoder Module
===============
Converts extracted protest event locations to latitude/longitude coordinates
using the Nominatim OpenStreetMap API (free, no API key required).

Geocoding is attempted hierarchically, from most to least specific:
  1. venue + city + country  → geo_accuracy: "venue"
  2. city + country          → geo_accuracy: "city"
  3. region + country        → geo_accuracy: "region"
  4. country only            → geo_accuracy: "country"

Each level falls back to the next if Nominatim returns no result.

Results are cached to disk (default: data/cache/geocode.json) keyed by the
normalized query string, so repeated runs over the same cities/countries are
served from cache and never hit the network. Negative results (confirmed
misses) are also cached to avoid re-querying dead strings.

Nominatim usage policy:
  - Max 1 request/second (enforced by a shared sliding-window limiter)
  - Must identify the application via user_agent
  - Do not cache-bust or hammer with retries on 429s
  Ref: https://operations.osmfoundation.org/policies/nominatim/
"""

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from src.acquisition._rate_limit import SlidingWindowLimiter as _SlidingWindowLimiter

log = logging.getLogger(__name__)

# Accuracy tiers in priority order
_ACCURACY_TIERS = ["venue", "city", "region", "country"]

# Nominatim user-agent — identifies this application to OSM
_USER_AGENT = "protest-event-analysis/1.0 (research; contact: pea-pipeline)"

# Default cache path (relative to CWD — caller may override)
_DEFAULT_CACHE_PATH = Path("data/cache/geocode.json")


class _GeocodeCache:
    """
    On-disk JSON cache keyed by normalized query string.
      - cache[key] = [lat, lon]  → confirmed hit
      - cache[key] = None        → confirmed miss (don't re-query)

    Thread-safe. Flushes to disk every `flush_every` writes and on explicit
    flush(). Writes are atomic (tmp + replace).
    """

    def __init__(self, path: Optional[Path] = None, flush_every: int = 50):
        self.path = Path(path) if path else None
        self.flush_every = max(1, int(flush_every))
        self._data: dict = {}
        self._lock = threading.Lock()
        self._pending_writes = 0
        self._hits = 0
        self._misses = 0
        if self.path and self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    self._data = loaded
                    log.info(
                        f"Loaded geocode cache: {len(self._data)} entries from {self.path}"
                    )
                else:
                    log.warning(
                        f"Geocode cache at {self.path} is not a dict; starting fresh"
                    )
            except Exception as e:
                log.warning(
                    f"Failed to load geocode cache ({self.path}): {e}; starting fresh"
                )

    @staticmethod
    def _key(query: str) -> str:
        return " ".join(query.lower().split())

    def get(self, query: str) -> tuple:
        """Return (value, hit) where hit is True if the key was cached."""
        key = self._key(query)
        with self._lock:
            if key in self._data:
                self._hits += 1
                return self._data[key], True
        return None, False

    def put(self, query: str, value) -> None:
        key = self._key(query)
        with self._lock:
            self._data[key] = value
            self._misses += 1
            self._pending_writes += 1
            should_flush = self._pending_writes >= self.flush_every
        if should_flush:
            self.flush()

    def flush(self) -> None:
        if not self.path:
            return
        with self._lock:
            snapshot = dict(self._data)
            self._pending_writes = 0
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, ensure_ascii=False)
            tmp.replace(self.path)
        except Exception as e:
            log.warning(f"Failed to flush geocode cache to {self.path}: {e}")

    def stats(self) -> dict:
        with self._lock:
            return {
                "entries": len(self._data),
                "hits": self._hits,
                "misses": self._misses,
            }


def _nominatim_lookup(query: str, session, user_agent: str) -> Optional[tuple]:
    """
    Query Nominatim for a single location string.
    Returns (lat, lon) floats or None if not found.
    """
    try:
        resp = session.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 1},
            headers={"User-Agent": user_agent},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception as e:
        log.debug(f"Nominatim lookup failed for '{query}': {e}")
    return None


def geocode_event(
    event: dict,
    session,
    user_agent: str = _USER_AGENT,
    cache: Optional[_GeocodeCache] = None,
    limiter: Optional[_SlidingWindowLimiter] = None,
) -> dict:
    """
    Attempt to geocode a single event dict in-place.
    Adds: latitude, longitude, geo_accuracy fields.

    If `cache` is provided, each query is looked up before hitting the network;
    negative results are also cached. If `limiter` is provided, network calls
    wait on it (cache hits do not).
    """
    venue = (event.get("venue") or "").strip()
    city = (event.get("city") or "").strip()
    region = (event.get("region") or "").strip()
    country = (event.get("country") or "").strip()

    queries = []
    if venue and city and country:
        queries.append(("venue", f"{venue}, {city}, {country}"))
    elif venue and country:
        queries.append(("venue", f"{venue}, {country}"))
    if city and country:
        queries.append(("city", f"{city}, {country}"))
    if region and country:
        queries.append(("region", f"{region}, {country}"))
    if country:
        queries.append(("country", country))

    for accuracy, query in queries:
        if cache is not None:
            cached, hit = cache.get(query)
            if hit:
                if cached is not None:
                    event["latitude"] = round(cached[0], 6)
                    event["longitude"] = round(cached[1], 6)
                    event["geo_accuracy"] = accuracy
                    return event
                # Known miss for this query — try the next tier without network.
                continue

        if limiter is not None:
            limiter.acquire()
        coords = _nominatim_lookup(query, session, user_agent)

        if cache is not None:
            cache.put(query, list(coords) if coords else None)

        if coords:
            event["latitude"] = round(coords[0], 6)
            event["longitude"] = round(coords[1], 6)
            event["geo_accuracy"] = accuracy
            log.debug(f"Geocoded '{query}' → {coords} ({accuracy})")
            return event

    event["latitude"] = None
    event["longitude"] = None
    event["geo_accuracy"] = None
    log.debug(f"Could not geocode event: city={city!r}, country={country!r}")
    return event


def geocode_events(
    events: list,
    rate_limit_delay: float = 1.1,
    user_agent: str = _USER_AGENT,
    cache_path: Optional[Path] = _DEFAULT_CACHE_PATH,
    max_workers: int = 4,
) -> list:
    """
    Geocode a list of extracted event dicts.
    Adds latitude, longitude, geo_accuracy to each event in-place.

    Args:
        events: list of event dicts (output of extract_events)
        rate_limit_delay: window size (seconds) for the Nominatim limiter;
            policy requires ≥1s. Cache hits do not consume the limiter.
        user_agent: identifies your application to OSM Nominatim
        cache_path: on-disk JSON cache path; pass None to disable caching
        max_workers: threads dispatching geocode_event. All threads share
            a single rate limiter so Nominatim policy (1 rps) is preserved.
            The speedup comes from parallel cache hits, not parallel network.

    Returns:
        same list with geo fields populated
    """
    import requests

    if not events:
        return events

    session = requests.Session()
    cache = _GeocodeCache(cache_path) if cache_path else None
    limiter = _SlidingWindowLimiter(max_requests=1, window_seconds=rate_limit_delay)

    workers = max(1, int(max_workers))
    log.info(
        f"Geocoding {len(events)} events via Nominatim OSM "
        f"(workers={workers}, cache={cache_path or 'off'})"
    )

    def _process(event):
        return geocode_event(event, session, user_agent, cache=cache, limiter=limiter)

    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            # Consume the iterator so exceptions surface.
            for _ in pool.map(_process, events):
                pass
    else:
        for event in events:
            _process(event)

    if cache is not None:
        cache.flush()

    success = sum(1 for e in events if e.get("geo_accuracy"))
    venue_hits = sum(1 for e in events if e.get("geo_accuracy") == "venue")

    if cache is not None:
        stats = cache.stats()
        log.info(
            f"Geocoding complete: {success}/{len(events)} located "
            f"({venue_hits} at venue precision); "
            f"cache: {stats['entries']} entries, "
            f"{stats['hits']} hits, {stats['misses']} network lookups"
        )
    else:
        log.info(
            f"Geocoding complete: {success}/{len(events)} located "
            f"({venue_hits} at venue precision)"
        )
    return events
