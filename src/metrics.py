"""
Shared quality and statistical metrics for pipeline outputs.

Previously duplicated between processing.py (run_quality_control)
and predictions.py (_quality_report / _confidence_breakdown).
Also provides count_by, previously duplicated in storage.py and processing.py.
"""

import logging
from datetime import datetime

import numpy as np

from src.constants import CONF_FLOAT_SCORE, VALID_EVENT_TYPES

log = logging.getLogger(__name__)


def quality_report(events: list) -> dict:
    """
    Return a schema validity + confidence distribution report.

    Schema-valid: event_type in VALID_EVENT_TYPES AND confidence maps to a
    float score >= 0.70 (i.e. 'high' or 'medium').
    Includes per-country and per-type breakdowns.
    """
    n = len(events)
    valid = sum(
        1
        for e in events
        if e.get("event_type") in VALID_EVENT_TYPES
        and CONF_FLOAT_SCORE.get(e.get("confidence", ""), 0.0) >= 0.70
    )
    scores = [CONF_FLOAT_SCORE.get(e.get("confidence", ""), 0.60) for e in events]
    arr = np.array(scores) if scores else np.array([0.0])

    return {
        "schema_validity": {
            "valid_schemas": valid,
            "invalid_schemas": n - valid,
            "validity_rate": valid / n if n else 0,
            "flag_for_review": (n - valid) > n * 0.1,
        },
        "confidence_distribution": {
            "mean_confidence": float(arr.mean()),
            "median_confidence": float(np.median(arr)),
            "std_confidence": float(arr.std()),
            "min_confidence": float(arr.min()),
            "max_confidence": float(arr.max()),
            "percentile_25": float(np.percentile(arr, 25)),
            "percentile_75": float(np.percentile(arr, 75)),
        },
        "total_predictions": n,
        "events_by_country": count_by(events, "country"),
        "events_by_type": count_by(events, "event_type"),
        "timestamp": datetime.utcnow().isoformat(),
    }


def confidence_breakdown(events: list) -> dict:
    """Break down event counts by confidence band."""
    scores = [CONF_FLOAT_SCORE.get(e.get("confidence", ""), 0.60) for e in events]
    n = len(scores)
    high = sum(1 for s in scores if s >= 0.8)
    medium = sum(1 for s in scores if 0.6 <= s < 0.8)
    low = sum(1 for s in scores if s < 0.6)
    return {
        "high_confidence": high,
        "medium_confidence": medium,
        "low_confidence": low,
        "pct_high": high / n if n else 0,
        "pct_medium": medium / n if n else 0,
        "pct_low": low / n if n else 0,
    }


def count_by(events: list, field: str) -> dict:
    """Count events by a given field value, sorted by frequency descending."""
    counts: dict = {}
    for event in events:
        val = str(event.get(field) or "unknown")
        counts[val] = counts.get(val, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: -x[1]))
