"""
Storage Module
==============
Saves extracted protest events to:
  1. A JSONL file (one event per line) — ideal for streaming/appending
  2. A CSV file — for easy viewing in Excel/Sheets
  3. A run summary JSON — metadata about the pipeline run

v2.1 additions:
  - New CSV columns: duration, location_notes, state_actors, outcome_notes
  - Derived field: turmoil_level (high / medium / low)
"""

import csv
import json
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

# CSV columns in display order
CSV_COLUMNS = [
    "event_date",
    "country",
    "city",
    "region",
    "location_notes",
    "event_type",
    "organizer",
    "participant_groups",
    "claims",
    "crowd_size",
    "duration",
    "state_response",
    "state_actors",
    "arrests",
    "fatalities",
    "injuries",
    "turmoil_level",
    "outcome",
    "outcome_notes",
    "confidence",
    "article_title",
    "article_url",
    "article_date",
    "source_country",
    "source_language",
]

# State responses ranked by severity (highest first)
_HIGH_TURMOIL_RESPONSES = {"live_ammunition", "rubber_bullets"}
_MEDIUM_TURMOIL_RESPONSES = {"teargas", "water_cannon", "dispersal", "arrests"}


def _derive_turmoil_level(event: dict) -> str:
    """
    Derive turmoil_level (high / medium / low) from extracted event fields.

    Logic (evaluated in order):
      high   — fatalities reported, OR live/rubber ammunition used,
               OR outcome is 'escalated'
      medium — teargas/water cannon/dispersal/arrests used, OR injuries reported
      low    — everything else
    """
    fatalities = event.get("fatalities")
    injuries = event.get("injuries")
    state_response = (event.get("state_response") or "").lower()
    outcome = (event.get("outcome") or "").lower()

    def _has_value(field) -> bool:
        """Return True if field is a non-zero, non-null, non-empty value."""
        if field is None:
            return False
        if isinstance(field, (int, float)):
            return field > 0
        val = str(field).strip().lower()
        return val not in ("", "0", "none", "null", "unknown", "n/a")

    # High turmoil
    if (
        _has_value(fatalities)
        or state_response in _HIGH_TURMOIL_RESPONSES
        or outcome == "escalated"
    ):
        return "high"

    # Medium turmoil
    if state_response in _MEDIUM_TURMOIL_RESPONSES or _has_value(injuries):
        return "medium"

    return "low"


def flatten_for_csv(event: dict) -> dict:
    """Convert list fields to semicolon-delimited strings for CSV compatibility."""
    row = {}
    for col in CSV_COLUMNS:
        val = event.get(col)
        if isinstance(val, list):
            row[col] = "; ".join(str(v) for v in val)
        elif val is None:
            row[col] = ""
        else:
            row[col] = str(val)
    return row


def save_results(
    events: list[dict],
    output_dir: Path,
    run_id: str,
) -> Path:
    """
    Save events to JSONL, CSV, and a run summary file.

    Derives turmoil_level for each event before writing.
    Returns the path to the output directory.
    """
    if not events:
        log.warning("No events to save.")
        return output_dir

    output_dir.mkdir(parents=True, exist_ok=True)

    # Derive turmoil_level for every event (in-place)
    for event in events:
        event["turmoil_level"] = _derive_turmoil_level(event)

    # 1. JSONL — one event per line, append-friendly
    jsonl_path = output_dir / f"events_{run_id}.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    log.info(f"JSONL saved: {jsonl_path} ({len(events)} events)")

    # 2. CSV — flattened for spreadsheet viewing
    csv_path = output_dir / f"events_{run_id}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for event in events:
            writer.writerow(flatten_for_csv(event))
    log.info(f"CSV saved: {csv_path}")

    # 3. Also append to a cumulative all_events.jsonl for long-running use
    cumulative_path = output_dir / "all_events.jsonl"
    with open(cumulative_path, "a", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    log.info(f"Appended to cumulative: {cumulative_path}")

    # 4. Run summary
    summary = {
        "run_id": run_id,
        "timestamp": datetime.utcnow().isoformat(),
        "total_events": len(events),
        "events_by_country": _count_by(events, "country"),
        "events_by_type": _count_by(events, "event_type"),
        "events_by_state_response": _count_by(events, "state_response"),
        "events_by_turmoil_level": _count_by(events, "turmoil_level"),
        "events_by_confidence": _count_by(events, "confidence"),
        "output_files": {
            "jsonl": str(jsonl_path),
            "csv": str(csv_path),
            "cumulative_jsonl": str(cumulative_path),
        },
    }
    summary_path = output_dir / f"summary_{run_id}.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    # Print summary to console
    print("\n" + "="*60)
    print(f"RUN SUMMARY — {run_id}")
    print("="*60)
    print(f"Total events extracted: {len(events)}")
    print(f"\nBy country:")
    for country, count in sorted(summary["events_by_country"].items(), key=lambda x: -x[1]):
        print(f"  {country:30s} {count}")
    print(f"\nBy event type:")
    for etype, count in sorted(summary["events_by_type"].items(), key=lambda x: -x[1]):
        print(f"  {etype:30s} {count}")
    print(f"\nBy turmoil level:")
    for level, count in sorted(summary["events_by_turmoil_level"].items(), key=lambda x: -x[1]):
        print(f"  {level:30s} {count}")
    print(f"\nOutput: {output_dir}")
    print("="*60 + "\n")

    return output_dir


def _count_by(events: list[dict], field: str) -> dict:
    """Count events by a given field value."""
    counts = {}
    for event in events:
        val = event.get(field) or "unknown"
        counts[str(val)] = counts.get(str(val), 0) + 1
    return dict(sorted(counts.items(), key=lambda x: -x[1]))
