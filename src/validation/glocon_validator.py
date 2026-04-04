"""
GLOCON GSC Validation
======================
Benchmarks PEA pipeline output against the GLOCON Global Contentious
Politics dataset (github.com/emerging-welfare).

Use the South Africa English subset for the primary benchmark — it is
freely available and directly applicable to the ZA pipeline target.

## Setup

1. Clone or download the GLOCON GSC dataset:
     git clone https://github.com/emerging-welfare/glocon-dataset
   The SA English subset is at:
     glocon-dataset/data/south_africa/english/

2. Run the pipeline for the same country + date range as your GLOCON slice.

3. Run this validator:
     python -m src.validation.glocon_validator \\
       --glocon-dir path/to/glocon-dataset/data/south_africa/english \\
       --pea-events data/raw/events_YYYYMMDD_HHMMSS.jsonl \\
       --output data/validation/recall_report.json

## GLOCON schema (SA English subset)
The dataset is distributed as CSV or JSON with (at minimum):
  event_date       YYYY-MM-DD
  location         city or settlement name
  country          country name
  event_type       GLOCON category (see PEA_TO_GLOCON crosswalk below)
  description      free text

## Matching strategy
A PEA event is considered to MATCH a GLOCON event when:
  1. Same country (normalised)
  2. Date within ±3 days
  3. Location fuzzy similarity ≥ 0.60 (SequenceMatcher)
  4. Event type maps to the same GLOCON top-level category

Recall = matched GLOCON events / total GLOCON events
Precision = matched PEA events / total PEA events (spot-check guidance)
"""

import json
import logging
import re
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PEA → GLOCON event type crosswalk
# GLOCON uses broader categories; map PEA's 8 types to the nearest equivalent.
# ---------------------------------------------------------------------------
PEA_TO_GLOCON: dict[str, str] = {
    "demonstration_march": "protest",
    "strike_boycott":      "strike",
    "occupation_seizure":  "protest",
    "confrontation":       "protest",
    "petition_signature":  "protest",
    "vigil":               "protest",
    "hunger_strike":       "protest",
    "riot":                "riot",
}

# GLOCON event_type values that map to PEA categories.
# GLOCON uses varied naming — extend this list as you inspect the actual data.
GLOCON_TO_BROAD: dict[str, str] = {
    # Protest / demonstration
    "protest":                "protest",
    "demonstration":          "protest",
    "march":                  "protest",
    "rally":                  "protest",
    "sit-in":                 "protest",
    "boycott":                "strike",
    "strike":                 "strike",
    "general strike":         "strike",
    "work stoppage":          "strike",
    "occupation":             "protest",
    "riot":                   "riot",
    "unrest":                 "protest",
    "vigil":                  "protest",
    "hunger strike":          "protest",
    "petition":               "protest",
    "blockade":               "protest",
}


def _norm_country(s: str) -> str:
    aliases = {
        "south africa": "south africa",
        "rsa":          "south africa",
        "za":           "south africa",
        "nigeria":      "nigeria",
        "ng":           "nigeria",
        "uganda":       "uganda",
        "ug":           "uganda",
        "algeria":      "algeria",
        "dz":           "algeria",
    }
    return aliases.get((s or "").lower().strip(), (s or "").lower().strip())


def _parse_date(s: str) -> Optional[datetime]:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%d/%m/%Y", "%m/%d/%Y", "%Y-%m"):
        try:
            return datetime.strptime(str(s)[:len(fmt)], fmt)
        except ValueError:
            continue
    return None


def _location_match(a: str, b: str, threshold: float = 0.60) -> bool:
    if not a or not b:
        return True   # missing location = ambiguous, don't penalise
    return SequenceMatcher(None, a.lower(), b.lower()).ratio() >= threshold


def _broad_type(pea_type: str) -> str:
    return PEA_TO_GLOCON.get(pea_type, "protest")


def _glocon_broad_type(glocon_type: str) -> str:
    return GLOCON_TO_BROAD.get((glocon_type or "").lower().strip(), "protest")


def load_glocon(glocon_dir: Path) -> list[dict]:
    """
    Load GLOCON events from a directory.
    Supports JSON (one event per line or array) and CSV.
    Returns a normalised list of dicts with keys:
      event_date, location, country, broad_type, raw
    """
    events = []
    glocon_dir = Path(glocon_dir)

    json_files = list(glocon_dir.glob("*.json")) + list(glocon_dir.glob("*.jsonl"))
    csv_files  = list(glocon_dir.glob("*.csv"))

    for path in json_files:
        with open(path, encoding="utf-8") as f:
            content = f.read().strip()
        if content.startswith("["):
            raw_events = json.loads(content)
        else:
            raw_events = [json.loads(line) for line in content.splitlines() if line.strip()]
        for r in raw_events:
            events.append(_normalise_glocon(r))

    for path in csv_files:
        import csv
        with open(path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for r in reader:
                events.append(_normalise_glocon(dict(r)))

    log.info(f"Loaded {len(events)} GLOCON events from {glocon_dir}")
    return events


def _normalise_glocon(r: dict) -> dict:
    """Normalise a raw GLOCON row to a standard internal format."""
    # Field name variants across GLOCON releases
    date_raw = (
        r.get("event_date") or r.get("date") or r.get("Date") or
        r.get("EVENT_DATE") or ""
    )
    location_raw = (
        r.get("location") or r.get("city") or r.get("Location") or
        r.get("LOCATION") or ""
    )
    country_raw = (
        r.get("country") or r.get("Country") or r.get("COUNTRY") or ""
    )
    type_raw = (
        r.get("event_type") or r.get("type") or r.get("Type") or
        r.get("EVENT_TYPE") or ""
    )
    return {
        "event_date":  date_raw,
        "location":    location_raw,
        "country":     _norm_country(country_raw),
        "broad_type":  _glocon_broad_type(type_raw),
        "raw":         r,
    }


def load_pea_events(path: Path) -> list[dict]:
    """Load PEA JSONL output."""
    with open(path, encoding="utf-8") as f:
        events = [json.loads(line) for line in f if line.strip()]
    log.info(f"Loaded {len(events)} PEA events from {path}")
    return events


def match_events(
    glocon_events: list[dict],
    pea_events: list[dict],
    date_window: int = 3,
    location_threshold: float = 0.60,
) -> list[dict]:
    """
    For each GLOCON event, find the best-matching PEA event (if any).

    Returns a list of match records, one per GLOCON event:
      {
        glocon_date, glocon_location, glocon_country, glocon_type,
        matched: bool,
        pea_url: str | None,
        pea_date: str | None,
        pea_city: str | None,
        pea_type: str | None,
        location_sim: float,
      }
    """
    results = []

    for g in glocon_events:
        g_date    = _parse_date(g["event_date"])
        g_country = g["country"]
        g_loc     = g["location"]
        g_type    = g["broad_type"]

        # Filter PEA candidates by country + date window
        candidates = []
        for p in pea_events:
            if _norm_country(p.get("country", "")) != g_country:
                continue
            p_date = _parse_date(p.get("event_date", ""))
            if g_date and p_date:
                if abs((g_date - p_date).days) > date_window:
                    continue
            candidates.append(p)

        # Among candidates, find the best location + type match
        best = None
        best_loc_sim = 0.0
        for p in candidates:
            p_loc  = p.get("city") or p.get("venue") or ""
            p_type = _broad_type(p.get("event_type", ""))

            loc_sim = SequenceMatcher(
                None, g_loc.lower(), p_loc.lower()
            ).ratio() if g_loc and p_loc else 0.5

            if loc_sim >= location_threshold and p_type == g_type:
                if loc_sim > best_loc_sim:
                    best = p
                    best_loc_sim = loc_sim

        results.append(
            {
                "glocon_date":     g["event_date"],
                "glocon_location": g_loc,
                "glocon_country":  g_country,
                "glocon_type":     g_type,
                "matched":         best is not None,
                "pea_url":         best.get("article_url") if best else None,
                "pea_date":        best.get("event_date") if best else None,
                "pea_city":        best.get("city") if best else None,
                "pea_type":        best.get("event_type") if best else None,
                "location_sim":    round(best_loc_sim, 3),
            }
        )

    return results


def compute_metrics(match_records: list[dict], pea_events: list[dict]) -> dict:
    """
    Compute recall, plus a precision sample pointer.

    Recall:    matched GLOCON events / total GLOCON events
    PEA-only:  PEA events not matched to any GLOCON event (precision sample)
    """
    total_glocon  = len(match_records)
    matched       = sum(1 for r in match_records if r["matched"])
    recall        = matched / total_glocon if total_glocon else 0.0

    matched_urls = {r["pea_url"] for r in match_records if r["matched"]}
    pea_only      = [e for e in pea_events if e.get("article_url") not in matched_urls]

    # Breakdown by GLOCON event type
    by_type: dict = {}
    for r in match_records:
        t = r["glocon_type"]
        if t not in by_type:
            by_type[t] = {"total": 0, "matched": 0}
        by_type[t]["total"] += 1
        if r["matched"]:
            by_type[t]["matched"] += 1
    for t in by_type:
        n = by_type[t]["total"]
        m = by_type[t]["matched"]
        by_type[t]["recall"] = round(m / n, 3) if n else 0.0

    # Breakdown by country
    by_country: dict = {}
    for r in match_records:
        c = r["glocon_country"]
        if c not in by_country:
            by_country[c] = {"total": 0, "matched": 0}
        by_country[c]["total"] += 1
        if r["matched"]:
            by_country[c]["matched"] += 1
    for c in by_country:
        n = by_country[c]["total"]
        m = by_country[c]["matched"]
        by_country[c]["recall"] = round(m / n, 3) if n else 0.0

    return {
        "recall":          round(recall, 3),
        "matched":         matched,
        "total_glocon":    total_glocon,
        "total_pea":       len(pea_events),
        "pea_only_count":  len(pea_only),
        "by_type":         by_type,
        "by_country":      by_country,
        "target_threshold": "≥0.60 (acceptable for GDELT-sourced pipeline)",
    }


def run_validation(
    glocon_dir: Path,
    pea_events_path: Path,
    output_path: Optional[Path] = None,
    date_window: int = 3,
    location_threshold: float = 0.60,
) -> dict:
    """
    Full validation run. Returns the metrics dict and writes JSON report.
    """
    glocon_events = load_glocon(glocon_dir)
    pea_events    = load_pea_events(pea_events_path)

    if not glocon_events:
        log.error("No GLOCON events loaded — check glocon_dir path and file format.")
        return {}

    match_records = match_events(
        glocon_events, pea_events,
        date_window=date_window,
        location_threshold=location_threshold,
    )
    metrics = compute_metrics(match_records, pea_events)

    # Console summary
    print("\n" + "=" * 60)
    print("GLOCON VALIDATION REPORT")
    print("=" * 60)
    print(f"GLOCON events:  {metrics['total_glocon']}")
    print(f"PEA events:     {metrics['total_pea']}")
    print(f"Matched:        {metrics['matched']}")
    print(f"Recall:         {metrics['recall']:.1%}  "
          f"(target ≥60%)")
    print(f"PEA-only:       {metrics['pea_only_count']} events not in GLOCON")
    print("\nRecall by event type:")
    for t, v in sorted(metrics["by_type"].items()):
        bar = "█" * int(v["recall"] * 20)
        print(f"  {t:20s} {v['recall']:.0%}  {bar}  ({v['matched']}/{v['total']})")
    print("\nRecall by country:")
    for c, v in sorted(metrics["by_country"].items()):
        bar = "█" * int(v["recall"] * 20)
        print(f"  {c:20s} {v['recall']:.0%}  {bar}  ({v['matched']}/{v['total']})")
    print("=" * 60 + "\n")

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "metrics":       metrics,
            "match_records": match_records,
            "settings": {
                "date_window_days":    date_window,
                "location_threshold":  location_threshold,
            },
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        log.info(f"Validation report written: {output_path}")

    return metrics


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    import logging as _logging

    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="Benchmark PEA pipeline output against GLOCON GSC"
    )
    parser.add_argument(
        "--glocon-dir",
        required=True,
        help="Path to GLOCON SA English subset directory",
    )
    parser.add_argument(
        "--pea-events",
        required=True,
        help="Path to PEA events JSONL (e.g. data/raw/events_YYYYMMDD_HHMMSS.jsonl "
             "or data/processed/events_consolidated.jsonl)",
    )
    parser.add_argument(
        "--output",
        default="data/validation/recall_report.json",
        help="Output path for the JSON report",
    )
    parser.add_argument(
        "--date-window",
        type=int,
        default=3,
        help="Days tolerance for date matching [default: 3]",
    )
    parser.add_argument(
        "--location-threshold",
        type=float,
        default=0.60,
        help="SequenceMatcher ratio threshold for location match [default: 0.60]",
    )
    args = parser.parse_args()

    run_validation(
        glocon_dir=Path(args.glocon_dir),
        pea_events_path=Path(args.pea_events),
        output_path=Path(args.output),
        date_window=args.date_window,
        location_threshold=args.location_threshold,
    )
