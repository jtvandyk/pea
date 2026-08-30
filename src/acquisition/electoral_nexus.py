"""
Electoral-nexus second pass — plan §4.1 (DECO event-nexus method).

Architecture decision (Aug 2026): the election domain no longer competes
with the primary extraction domains for electorally-connected events.
Instead, events extracted by the PRIMARY domains (protest, VE, drone) are
tagged post-extraction with their electoral nexus, and the election
codebook shrinks to a residual extractor for election-only events that
have no other domain home (see election codebook v2.0).

Rationale: 10 of ECAV's 18 event types are protest/VE types with an
electoral qualifier — parallel extraction structurally guarantees
double-coding (DECO, Fjelde & Höglund 2022; ECAV, Daxecker et al. 2019).

A tag is assigned on any of three bases (recorded in
``electoral_nexus_basis`` so downstream users can filter by strictness):

  calendar_window — the event falls within ±6 months (ECAV window) of an
      election in ``configs/election_calendar.yaml``. The calendar is
      operator-maintained; NELDA (Hyde & Marinov) is the intended source
      for its rows.
  issue_tags — a protest event carries the ``elections`` issue tag
      (already a closed-taxonomy signal from the extractor).
  keywords — electoral vocabulary appears in the event's claims/notes
      text fields (weakest basis; never assigned alone with high
      confidence downstream).
"""

import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import yaml

from src.constants import CONFIGS_DIR

log = logging.getLogger("pea.electoral_nexus")

_CALENDAR_PATH = CONFIGS_DIR / "election_calendar.yaml"

# ECAV operationalisation: ±6 months around each election round.
ECAV_WINDOW_DAYS = 183

_ELECTION_KEYWORDS = (
    "election",
    "electoral",
    "ballot",
    "polling station",
    "voter",
    "vote rigging",
    "vote-rigging",
    "rigged vote",
    "presidential poll",
    "runoff",
    "run-off",
)

# Event text fields scanned for the keyword basis, across domain schemas.
_TEXT_FIELDS = (
    "claims",
    "outcome_notes",
    "location_notes",
    "target_description",
    "organizer",
)


def load_election_calendar(path: Optional[Path] = None) -> dict:
    """
    Load the election calendar: {country_lower: [{"date": date, "name": str}]}.

    Missing or empty file returns {} — the calendar basis is then simply
    skipped, it never fails a run. Malformed rows are logged and dropped.
    """
    p = Path(path) if path is not None else _CALENDAR_PATH
    if not p.exists():
        return {}
    try:
        raw = yaml.safe_load(p.read_text()) or {}
    except yaml.YAMLError as exc:
        log.warning(f"Election calendar unreadable ({exc}); calendar basis disabled")
        return {}

    calendar: dict = {}
    for country, rounds in (raw.get("elections") or {}).items():
        for entry in rounds or []:
            parsed = _parse_date(str(entry.get("date", "")))
            if parsed is None:
                log.warning(
                    f"Election calendar: unparseable date for {country}: {entry!r}"
                )
                continue
            calendar.setdefault(str(country).strip().lower(), []).append(
                {"date": parsed, "name": entry.get("name") or ""}
            )
    return calendar


def _parse_date(value: str) -> Optional[date]:
    """Best-effort parse of YYYY-MM-DD / YYYY-MM / YYYY event dates."""
    value = (value or "").strip()
    for fmt, pad in (("%Y-%m-%d", ""), ("%Y-%m", "-15"), ("%Y", "-07-01")):
        try:
            return datetime.strptime(value + pad, "%Y-%m-%d").date()
        except ValueError:
            if fmt == "%Y-%m-%d" and re.match(r"^\d{4}-\d{2}-\d{2}", value):
                # e.g. '2026-05-12 (approx)' — retry on the first 10 chars
                try:
                    return datetime.strptime(value[:10], "%Y-%m-%d").date()
                except ValueError:
                    pass
            continue
    return None


def _event_text(event: dict) -> str:
    parts = []
    for field in _TEXT_FIELDS:
        val = event.get(field)
        if isinstance(val, list):
            parts.extend(str(v) for v in val)
        elif val:
            parts.append(str(val))
    return " ".join(parts).lower()


def tag_electoral_nexus(
    events: list,
    calendar: Optional[dict] = None,
    window_days: int = ECAV_WINDOW_DAYS,
) -> list:
    """
    Tag each event with its electoral nexus (in place; returns the list).

    Adds three fields to every event:
      electoral_nexus          bool
      electoral_nexus_basis    list of matched bases (empty when False)
      electoral_nexus_election calendar election name, or None

    Purely mechanical — no LLM call. Safe on any domain's events.
    """
    if calendar is None:
        calendar = load_election_calendar()

    n_tagged = 0
    for event in events:
        bases = []
        election_name = None

        country = str(event.get("country") or "").strip().lower()
        event_date = _parse_date(str(event.get("event_date") or ""))
        if country in calendar and event_date is not None:
            for entry in calendar[country]:
                if abs((event_date - entry["date"]).days) <= window_days:
                    bases.append("calendar_window")
                    election_name = entry["name"] or None
                    break

        issue_tags = event.get("issue_tags") or []
        if isinstance(issue_tags, list) and "elections" in issue_tags:
            bases.append("issue_tags")

        text = _event_text(event)
        if text and any(kw in text for kw in _ELECTION_KEYWORDS):
            bases.append("keywords")

        event["electoral_nexus"] = bool(bases)
        event["electoral_nexus_basis"] = bases
        event["electoral_nexus_election"] = election_name
        if bases:
            n_tagged += 1

    if events:
        log.info(
            f"Electoral nexus pass: {n_tagged}/{len(events)} events tagged "
            f"(calendar countries: {len(calendar)})"
        )
    return events
