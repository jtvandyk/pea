"""
Structured logging context for the PEA pipeline.

Without this, log lines from inside scraper / extractor / processing modules
are bare strings: when 100s of cron runs accumulate in Log Analytics, an
on-call engineer cannot filter "show me the failures from today's ZA run"
without grep-by-substring on free-form messages.

Usage in code:

    from src.utils.logging_context import set_run_id, stage, country_scope

    set_run_id("20260507_063012")          # set once at top of main()
    with stage("scraping"):                 # tag every log inside the block
        scrape_articles(...)
    with country_scope("ZA"), stage("extraction"):
        extract_events(...)

The context is propagated via contextvars (thread-safe and async-safe). A
`ContextFilter` attached to the root logger copies the current values onto
every emitted ``LogRecord`` as ``record.run_id``, ``record.country``,
``record.stage``, and ``record.domain``. The pipeline's ``_JsonFormatter``
includes these fields in the JSON output when present.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
from typing import Iterator, Optional


# Default to empty string so the JSON formatter can omit fields that were
# never set, rather than emitting "null" or "unknown" everywhere.
_run_id: contextvars.ContextVar[str] = contextvars.ContextVar("pea_run_id", default="")
_country: contextvars.ContextVar[str] = contextvars.ContextVar(
    "pea_country", default=""
)
_stage: contextvars.ContextVar[str] = contextvars.ContextVar("pea_stage", default="")
_domain: contextvars.ContextVar[str] = contextvars.ContextVar("pea_domain", default="")


def set_run_id(run_id: str) -> None:
    """Set the run identifier for the current execution. Call once at startup."""
    _run_id.set(run_id or "")


def set_domain(domain: str) -> None:
    """Set the active codebook domain (e.g. 'protest', 'drone')."""
    _domain.set(domain or "")


@contextlib.contextmanager
def stage(name: str) -> Iterator[None]:
    """Tag log records emitted inside the block with ``stage=<name>``."""
    token = _stage.set(name or "")
    try:
        yield
    finally:
        _stage.reset(token)


@contextlib.contextmanager
def country_scope(iso2: Optional[str]) -> Iterator[None]:
    """Tag log records emitted inside the block with ``country=<iso2>``."""
    token = _country.set((iso2 or "").upper())
    try:
        yield
    finally:
        _country.reset(token)


class ContextFilter(logging.Filter):
    """Copy contextvars onto each LogRecord so formatters can render them."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = _run_id.get()
        record.country = _country.get()
        record.stage = _stage.get()
        record.domain = _domain.get()
        return True


def install(root: Optional[logging.Logger] = None) -> ContextFilter:
    """Attach a fresh ContextFilter to the root logger (idempotent).

    Returns the filter instance so callers can detach it in tests.
    """
    target = root or logging.getLogger()
    for existing in target.filters:
        if isinstance(existing, ContextFilter):
            return existing
    flt = ContextFilter()
    target.addFilter(flt)
    # Filters on the root logger don't propagate to handlers automatically —
    # attach to each handler too so messages emitted via module loggers
    # (which inherit handlers from root) still get the context.
    for h in target.handlers:
        h.addFilter(flt)
    return flt
