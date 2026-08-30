"""
Dissent–repression linked pairs — plan §4 decision 2 (NAVCO 3.0 model).

NAVCO 3.0 (Chenoweth, Pinckney & Lewis, JPR 2018) represents repression
BOTH as an attribute on the dissent event AND as its own event sharing an
identifier. This module implements that dual representation mechanically —
no second LLM pass:

  1. ``derive_linked_repression_events``: a protest event whose
     state_response is repressive spawns a derived repression-domain event
     (flagged ``derived_from_protest: true``) carrying the same pair id.
     The repression codebook still EXCLUDES protest-response repression
     from LLM extraction — derivation is how those actions enter the
     repression dataset, with provenance, and without double coding.

  2. ``link_repression_to_protests``: repression events the LLM did
     extract (bans, dissolutions, shutdowns answering a protest wave) are
     linked to the protest events they plausibly answer — same country,
     within a ±3-day window, compatible city — by stamping a shared
     ``dissent_repression_pair_id`` on both sides.

Both passes run in the multi-codebook pipeline when protest and
state_repression are extracted in the same run.
"""

import hashlib
import json
import logging
from typing import Optional

log = logging.getLogger("pea.dissent_repression")

# protest state_response → derived repression event_type. Responses absent
# from this mapping (none, monitoring, unknown, ...) derive nothing.
STATE_RESPONSE_TO_REPRESSION_TYPE = {
    "live_ammunition": "pro_government_violence",
    "rubber_bullets": "pro_government_violence",
    "teargas": "pro_government_violence",
    "water_cannon": "pro_government_violence",
    "dispersal": "pro_government_violence",
    "arrests": "activist_arrest_prosecution",
    "non_association_bail": "activist_arrest_prosecution",
    "ban": "assembly_ban_curfew",
    "curfew": "assembly_ban_curfew",
    "internet_shutdown": "internet_shutdown",
    "legal_criminalisation": "civil_society_restriction",
    "anti_terrorism_designation": "civil_society_restriction",
    "organisational_dissolution": "civil_society_restriction",
}

LINK_WINDOW_DAYS = 3

# Fields copied verbatim from the protest event onto its derived twin.
_COPIED_FIELDS = (
    "event_date",
    "country",
    "city",
    "region",
    "venue",
    "state_response",
    "arrests",
    "fatalities",
    "injuries",
    "confidence",
    "article_title",
    "article_url",
    "article_date",
    "source_country",
    "source_language",
)


def event_uid(event: dict) -> str:
    """Deterministic 12-hex uid from an event's identity fields.

    Stable across runs for the same extracted event, so pair ids survive
    re-processing. Stored on the event as ``event_uid`` on first use.
    """
    if event.get("event_uid"):
        return event["event_uid"]
    key = json.dumps(
        [
            event.get("article_url", ""),
            event.get("event_type", ""),
            event.get("event_date", ""),
            event.get("country", ""),
            event.get("city", ""),
        ],
        ensure_ascii=False,
    )
    uid = "evt_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    event["event_uid"] = uid
    return uid


def _pair_id(protest_event: dict) -> str:
    return "drp_" + event_uid(protest_event)[4:]


def derive_linked_repression_events(protest_events: list) -> list:
    """
    Derive repression-domain twin events from repressive protest responses.

    Returns the NEW derived events (the protest events are annotated in
    place with the shared pair id and the twin's uid).
    """
    derived = []
    for protest in protest_events:
        response = (protest.get("state_response") or "").strip().lower()
        rep_type = STATE_RESPONSE_TO_REPRESSION_TYPE.get(response)
        if rep_type is None:
            continue

        pair = _pair_id(protest)
        twin = {field: protest.get(field) for field in _COPIED_FIELDS}
        twin.update(
            {
                "event_type": rep_type,
                "perpetrator_name": "; ".join(protest.get("state_actors") or [])
                or None,
                "perpetrator_category": "unknown",
                "target_name": protest.get("organizer"),
                "target_category": "general_public",
                "derived_from_protest": True,
                "dissent_repression_pair_id": pair,
                "linked_event_ids": [event_uid(protest)],
            }
        )
        event_uid(twin)

        protest["dissent_repression_pair_id"] = pair
        protest.setdefault("linked_event_ids", []).append(twin["event_uid"])
        derived.append(twin)

    if derived:
        log.info(
            f"Derived {len(derived)} linked repression events from "
            f"{len(protest_events)} protest events (NAVCO dual representation)"
        )
    return derived


def _parse_day(value) -> Optional[int]:
    """Event date → ordinal day, or None. Accepts YYYY-MM-DD prefixes."""
    from datetime import datetime

    value = str(value or "").strip()[:10]
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().toordinal()
    except ValueError:
        return None


def _city_compatible(a: dict, b: dict) -> bool:
    """Mirror the deduplicator's null-city rule: enforce the city match only
    when both are non-null; a missing city on either side stays compatible."""
    ca = str(a.get("city") or "").strip().lower()
    cb = str(b.get("city") or "").strip().lower()
    if not ca or not cb:
        return True
    return ca == cb


def link_repression_to_protests(
    repression_events: list,
    protest_events: list,
    window_days: int = LINK_WINDOW_DAYS,
) -> int:
    """
    Link extracted repression events to protest events they plausibly
    answer: same country, dates within ``window_days``, compatible city.
    Derived twins are skipped (already linked). Each repression event links
    to at most one protest (the closest by date). Returns links made.
    """
    n_linked = 0
    for rep in repression_events:
        if rep.get("derived_from_protest"):
            continue
        rep_day = _parse_day(rep.get("event_date"))
        rep_country = str(rep.get("country") or "").strip().lower()
        if rep_day is None or not rep_country:
            continue

        best = None
        best_gap = None
        for protest in protest_events:
            if str(protest.get("country") or "").strip().lower() != rep_country:
                continue
            protest_day = _parse_day(protest.get("event_date"))
            if protest_day is None:
                continue
            gap = abs(rep_day - protest_day)
            if gap > window_days or not _city_compatible(rep, protest):
                continue
            if best_gap is None or gap < best_gap:
                best, best_gap = protest, gap

        if best is None:
            continue

        pair = best.get("dissent_repression_pair_id") or _pair_id(best)
        best["dissent_repression_pair_id"] = pair
        rep["dissent_repression_pair_id"] = pair
        best.setdefault("linked_event_ids", []).append(event_uid(rep))
        rep.setdefault("linked_event_ids", []).append(event_uid(best))
        n_linked += 1

    if n_linked:
        log.info(
            f"Linked {n_linked} extracted repression events to protest events "
            f"(±{window_days}-day window)"
        )
    return n_linked
