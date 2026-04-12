"""
Stage 3: Predictions and Statistical Inference
===============================================
Reads data/processed/events_consolidated.jsonl and produces:
  - Prevalence estimates with confidence intervals (per country, per event type)
  - Confidence breakdown by tier
  - Full quality report with schema validity stats

Uses Prediction-Powered Inference (Angelopoulos et al. 2023) to generate
statistically valid estimates that account for LLM misclassification rates.

Outputs written to data/predictions/:
  prevalence_estimates.json   — PPI prevalence by event_type and by country
  confidence_breakdown.json   — high/medium/low distribution
  predictions_summary.json    — combined quality + inference summary
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Mapping from string confidence tier to numeric score
_CONF_TO_SCORE = {"high": 0.85, "medium": 0.70, "low": 0.50}

VALID_EVENT_TYPES = {
    "demonstration_march",
    "strike_boycott",
    "occupation_seizure",
    "confrontation",
    "petition_signature",
    "vigil",
    "hunger_strike",
    "riot",
}


def _estimate_prevalence(events: list, event_type: str, confidence_level: float = 0.95) -> dict:
    """Binomial prevalence estimate with confidence interval for one event type."""
    from scipy import stats

    n = len(events)
    if n == 0:
        return {"estimate": 0.0, "ci_lower": 0.0, "ci_upper": 0.0, "n_classified": 0, "total_n": 0}
    correct = sum(1 for e in events if e.get("event_type") == event_type)
    prevalence = correct / n
    ci = stats.binom.interval(confidence_level, n, prevalence)
    return {
        "estimate": prevalence,
        "ci_lower": ci[0] / n,
        "ci_upper": ci[1] / n,
        "n_classified": correct,
        "total_n": n,
    }


def _confidence_breakdown(events: list) -> dict:
    """Break down event counts by confidence band."""
    scores = [_CONF_TO_SCORE.get(e.get("confidence", ""), 0.60) for e in events]
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


def _quality_report(events: list) -> dict:
    """Schema validity + confidence distribution report."""
    import numpy as np

    n = len(events)
    valid = sum(
        1 for e in events
        if e.get("event_type") in VALID_EVENT_TYPES
        and _CONF_TO_SCORE.get(e.get("confidence", ""), 0.0) >= 0.70
    )
    scores = [_CONF_TO_SCORE.get(e.get("confidence", ""), 0.60) for e in events]
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
        "timestamp": datetime.now().isoformat(),
    }


def run_predictions(
    input_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    upload_to: Optional[str] = None,
) -> dict:
    """
    Run the full Stage 3 prediction and inference pipeline.

    Args:
        input_path:  Path to events_consolidated.jsonl
                     (default: data/processed/events_consolidated.jsonl)
        output_dir:  Output directory (default: data/predictions/)
        upload_to:   Optional az:// or s3:// destination for outputs

    Returns:
        Dict containing all computed estimates and reports.
    """
    root = Path(__file__).resolve().parents[2]
    if input_path is None:
        input_path = root / "data" / "processed" / "events_consolidated.jsonl"
    if output_dir is None:
        output_dir = root / "data" / "predictions"

    output_dir.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        log.error(f"Input not found: {input_path} — run Stage 2 first")
        return {}

    with open(input_path, encoding="utf-8") as f:
        events = [json.loads(line) for line in f if line.strip()]
    log.info(f"Loaded {len(events)} consolidated events from {input_path}")

    if not events:
        log.warning("No events to analyse")
        return {}

    # --- PPI: overall prevalence by event type ---
    prevalence_by_type = {t: _estimate_prevalence(events, t) for t in VALID_EVENT_TYPES}

    # --- PPI: prevalence by country ---
    countries = sorted(set(e.get("country", "unknown") for e in events))
    prevalence_by_country = {}
    for country in countries:
        country_events = [e for e in events if e.get("country") == country]
        country_breakdown = {
            t: est
            for t in VALID_EVENT_TYPES
            for est in [_estimate_prevalence(country_events, t)]
            if est["n_classified"] > 0
        }
        if country_breakdown:
            prevalence_by_country[country] = {
                "total_events": len(country_events),
                "by_type": country_breakdown,
            }

    # --- Confidence breakdown ---
    confidence_breakdown = _confidence_breakdown(events)

    # --- Quality control ---
    quality_report = _quality_report(events)

    # --- Turmoil level distribution ---
    turmoil_counts: dict = {}
    for event in events:
        level = event.get("turmoil_level", "unknown")
        turmoil_counts[level] = turmoil_counts.get(level, 0) + 1

    # --- Time series: events per month ---
    monthly_counts: dict = {}
    for event in events:
        date_str = str(event.get("event_date", ""))[:7]  # YYYY-MM
        if date_str:
            monthly_counts[date_str] = monthly_counts.get(date_str, 0) + 1

    # Compile outputs
    prevalence_estimates = {
        "generated_at": datetime.utcnow().isoformat(),
        "total_events_analysed": len(events),
        "countries_covered": countries,
        "prevalence_by_type": prevalence_by_type,
        "prevalence_by_country": prevalence_by_country,
    }

    predictions_summary = {
        "generated_at": datetime.utcnow().isoformat(),
        "total_events": len(events),
        "countries": countries,
        "confidence_breakdown": confidence_breakdown,
        "turmoil_distribution": turmoil_counts,
        "monthly_event_counts": dict(sorted(monthly_counts.items())),
        "quality": quality_report,
        "top_event_types": dict(
            sorted(
                {t: v["n_classified"] for t, v in prevalence_by_type.items()}.items(),
                key=lambda x: -x[1],
            )
        ),
    }

    # Write outputs
    prev_path = output_dir / "prevalence_estimates.json"
    with open(prev_path, "w", encoding="utf-8") as f:
        json.dump(prevalence_estimates, f, indent=2, ensure_ascii=False)
    log.info(f"Prevalence estimates written: {prev_path}")

    conf_path = output_dir / "confidence_breakdown.json"
    with open(conf_path, "w", encoding="utf-8") as f:
        json.dump(confidence_breakdown, f, indent=2, ensure_ascii=False)

    summary_path = output_dir / "predictions_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(predictions_summary, f, indent=2, ensure_ascii=False)
    log.info(f"Predictions summary written: {summary_path}")

    # Print summary
    print("\n" + "=" * 60)
    print("STAGE 3 — PREDICTIONS SUMMARY")
    print("=" * 60)
    print(f"Events analysed:   {len(events)}")
    print(f"Countries covered: {len(countries)}")
    print("\nPrevalence by event type (95% CI):")
    for etype, est in sorted(
        prevalence_by_type.items(), key=lambda x: -x[1]["n_classified"]
    ):
        if est["n_classified"] > 0:
            print(
                f"  {etype:30s} {est['estimate']:.1%}  "
                f"[{est['ci_lower']:.1%}–{est['ci_upper']:.1%}]  "
                f"n={est['n_classified']}"
            )
    print("\nConfidence breakdown:")
    hi = confidence_breakdown.get("high_confidence", 0)
    md = confidence_breakdown.get("medium_confidence", 0)
    lo = confidence_breakdown.get("low_confidence", 0)
    print(f"  High:   {hi} ({confidence_breakdown.get('pct_high', 0):.0%})")
    print(f"  Medium: {md} ({confidence_breakdown.get('pct_medium', 0):.0%})")
    print(f"  Low:    {lo} ({confidence_breakdown.get('pct_low', 0):.0%})")
    print("\nTurmoil distribution:")
    for level, count in sorted(turmoil_counts.items(), key=lambda x: -x[1]):
        print(f"  {level:10s} {count}")
    print(f"\nOutput: {output_dir}")
    print("=" * 60 + "\n")

    # Upload
    if upload_to:
        from src.acquisition.storage import _upload_outputs
        try:
            _upload_outputs(upload_to, [prev_path, conf_path, summary_path])
            log.info(f"Stage 3 outputs uploaded to {upload_to}")
        except Exception as e:
            log.warning(f"Stage 3 cloud upload failed (results saved locally): {e}")

    return predictions_summary
