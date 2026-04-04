"""
Export PEA Events for Label Studio Annotation
==============================================
Reads pipeline JSONL output and produces a Label Studio import file
(JSON array of tasks). Applies an active learning priority score so
the most informative examples surface first in the annotation queue.

Active learning priority strategy:
  TIER 1 (annotate first) — low confidence + high relevance score
    These are events the pipeline was uncertain about but the relevance
    filter thought were genuinely protest-relevant. Errors here are the
    most damaging (uncertain + probably real = high misclassification risk).

  TIER 2 — medium confidence, any relevance score
    Borderline extractions where human review will most improve the model.

  TIER 3 (spot-check only) — high confidence
    Sample 10% for precision monitoring. Don't annotate exhaustively.

Usage:
    python -m src.annotation.export_for_annotation \\
      --events data/raw/all_events.jsonl \\
      --output data/annotation/tasks_$(date +%Y%m%d).json \\
      --max-tasks 200 \\
      --tier 1,2

    Then in Label Studio: Projects → Import → upload the JSON file.
"""

import argparse
import json
import logging
import random
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Event types that tend to have higher false positive rates — oversample these
_HIGH_FP_TYPES = {"confrontation", "riot", "occupation_seizure"}


def _priority_score(event: dict) -> float:
    """
    Compute an active learning priority score [0, 1].
    Higher = more valuable to annotate first.
    """
    conf = event.get("confidence", "medium")
    relevance = float(event.get("_relevance_score", 0.5))
    event_type = event.get("event_type", "")

    base = {"low": 1.0, "medium": 0.6, "high": 0.15}.get(conf, 0.5)

    # Boost for high-FP event types
    type_boost = 0.15 if event_type in _HIGH_FP_TYPES else 0.0

    # Relevance score from ConfliBERT: high relevance + low confidence = most valuable
    # Invert relevance so that low-relevance uncertain events are deprioritised
    # (they're probably noise the LLM correctly flagged as uncertain)
    relevance_weight = relevance * 0.25

    return min(base + type_boost + relevance_weight, 1.0)


def _tier(event: dict) -> int:
    conf = event.get("confidence", "medium")
    return {"low": 1, "medium": 2, "high": 3}.get(conf, 2)


def _build_task(event: dict, article_text: Optional[str] = None) -> dict:
    """Convert a PEA event dict to a Label Studio task dict."""
    claims = event.get("claims") or []
    claims_display = "; ".join(str(c) for c in claims) if claims else "(none)"

    location_parts = filter(None, [
        event.get("venue"),
        event.get("city"),
        event.get("region"),
        event.get("country"),
    ])
    location_display = ", ".join(location_parts) or "(unknown)"

    # Truncate article text for display — annotators need context, not full text
    text = article_text or event.get("_article_text", "")
    text_excerpt = text[:2000] + ("…" if len(text) > 2000 else "")

    return {
        "data": {
            # Fields shown in the labeling interface
            "article_title":    event.get("article_title") or "(no title)",
            "article_date":     event.get("article_date") or "",
            "article_url":      event.get("article_url") or "",
            "article_text":     text_excerpt,
            "event_type":       event.get("event_type") or "",
            "confidence":       event.get("confidence") or "",
            "event_date":       event.get("event_date") or "",
            "organizer":        event.get("organizer") or "(unknown)",
            "location_display": location_display,
            "crowd_size":       str(event.get("crowd_size") or "(not reported)"),
            "state_response":   event.get("state_response") or "none",
            "outcome":          event.get("outcome") or "",
            "claims_display":   claims_display,

            # Hidden fields passed through for training data assembly
            "_source_event":    json.dumps(event, ensure_ascii=False),
            "_priority_score":  round(_priority_score(event), 3),
            "_tier":            _tier(event),
            "_relevance_score": event.get("_relevance_score", None),
            "_relevance_source": event.get("_relevance_source", None),
        }
    }


def export_tasks(
    events_path: Path,
    output_path: Path,
    max_tasks: int = 200,
    tiers: Optional[list[int]] = None,
    high_confidence_sample_rate: float = 0.10,
    seed: int = 42,
) -> list[dict]:
    """
    Load events, apply active learning prioritisation, write Label Studio JSON.

    Args:
        events_path:               JSONL file of PEA events
        output_path:               Output JSON for Label Studio import
        max_tasks:                 Hard cap on number of tasks exported
        tiers:                     Tiers to include (1=low conf, 2=medium, 3=high).
                                   Default: [1, 2] + 10% sample of tier 3.
        high_confidence_sample_rate: Fraction of high-confidence events to include
        seed:                      Random seed for reproducible sampling
    """
    if tiers is None:
        tiers = [1, 2]

    with open(events_path, encoding="utf-8") as f:
        all_events = [json.loads(line) for line in f if line.strip()]
    log.info(f"Loaded {len(all_events)} events from {events_path}")

    rng = random.Random(seed)

    # Partition by tier
    tier_1 = [e for e in all_events if _tier(e) == 1]
    tier_2 = [e for e in all_events if _tier(e) == 2]
    tier_3 = [e for e in all_events if _tier(e) == 3]

    # Sort tier 1 + 2 by priority score descending
    selected = []
    if 1 in tiers:
        selected += sorted(tier_1, key=_priority_score, reverse=True)
    if 2 in tiers:
        selected += sorted(tier_2, key=_priority_score, reverse=True)
    if 3 in tiers:
        n_sample = max(1, int(len(tier_3) * high_confidence_sample_rate))
        selected += rng.sample(tier_3, min(n_sample, len(tier_3)))

    # Cap
    selected = selected[:max_tasks]

    tasks = [_build_task(e) for e in selected]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(tasks, f, indent=2, ensure_ascii=False)

    log.info(
        f"Exported {len(tasks)} tasks to {output_path} "
        f"(tier1={sum(1 for e in selected if _tier(e)==1)}, "
        f"tier2={sum(1 for e in selected if _tier(e)==2)}, "
        f"tier3={sum(1 for e in selected if _tier(e)==3)})"
    )
    return tasks


if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="Export PEA events to Label Studio annotation tasks"
    )
    parser.add_argument(
        "--events",
        default="data/raw/all_events.jsonl",
        help="JSONL file of PEA events",
    )
    parser.add_argument(
        "--output",
        default=f"data/annotation/tasks_{datetime.utcnow().strftime('%Y%m%d')}.json",
        help="Output path for Label Studio JSON",
    )
    parser.add_argument(
        "--max-tasks", type=int, default=200,
        help="Max annotation tasks to export [default: 200]",
    )
    parser.add_argument(
        "--tiers", default="1,2",
        help="Comma-separated tiers to include: 1=low conf, 2=medium, 3=high [default: 1,2]",
    )
    parser.add_argument(
        "--sample-rate", type=float, default=0.10,
        help="Fraction of high-confidence (tier 3) events to include [default: 0.10]",
    )
    args = parser.parse_args()

    export_tasks(
        events_path=Path(args.events),
        output_path=Path(args.output),
        max_tasks=args.max_tasks,
        tiers=[int(t) for t in args.tiers.split(",")],
        high_confidence_sample_rate=args.sample_rate,
    )
