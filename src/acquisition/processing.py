"""
Stage 2: Processing and Consolidation
======================================
Reads data/raw/all_events.jsonl and produces a clean, deduplicated,
quality-controlled dataset in data/processed/.

Steps:
  1. Load all raw events across runs
  2. Filter to target geography (remove noise from broken GDELT runs)
  3. Deduplicate — deterministic rules: same country + city + date ±2 days + event_type
  4. Re-verify borderline events (medium/low confidence) using LLM chain-of-thought
  5. Run QualityController — schema validity + confidence distribution report
  6. Write data/processed/events_consolidated.jsonl + quality_report.json

Outputs:
  data/processed/events_consolidated.jsonl  — clean events for Stage 3
  data/processed/quality_report.json        — schema validity + confidence stats
  data/processed/duplicates_log.jsonl       — audit trail of removed duplicates
"""

import json
import logging
import os
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Default target countries for Africa focus (lowercase for comparison)
DEFAULT_TARGET_COUNTRIES = {
    "nigeria",
    "south africa",
    "uganda",
    "algeria",
    "libya",
    "angola",
    "kenya",
    "somalia",
    "tanzania",
    "ghana",
    "ethiopia",
    "senegal",
    "zimbabwe",
    "cameroon",
    "ivory coast",
    "côte d'ivoire",
    "democratic republic of the congo",
    "drc",
    "sudan",
    "south sudan",
    "mozambique",
    "zambia",
    "malawi",
    "rwanda",
    "burundi",
    "mali",
    "niger",
    "chad",
    "mauritania",
    "guinea",
    "sierra leone",
    "liberia",
    "togo",
    "benin",
    "central african republic",
}

# Confidence string → numeric score for ranking duplicates
_CONF_SCORE = {"high": 3, "medium": 2, "low": 1}


def _parse_event_date(date_str: str) -> Optional[datetime]:
    """Parse event_date field; returns None if unparseable."""
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(str(date_str)[: len(fmt)], fmt)
        except ValueError:
            continue
    return None


def _fuzzy_match(a: str, b: str, threshold: float = 0.7) -> bool:
    """Return True if strings are similar enough (or either is empty)."""
    if not a or not b:
        return True  # can't falsify without both values
    return (
        SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio() >= threshold
    )


def _are_duplicates(a: dict, b: dict) -> bool:
    """
    Deterministic duplicate check.
    Criteria (all must pass):
      - Same country (exact, case-insensitive)
      - Same event_type
      - Event dates within ±2 days (or either is missing)
      - City names fuzzy-match at ≥0.7 (or either is missing)
    """
    if (a.get("country") or "").lower() != (b.get("country") or "").lower():
        return False
    if a.get("event_type") != b.get("event_type"):
        return False

    date_a = _parse_event_date(a.get("event_date", ""))
    date_b = _parse_event_date(b.get("event_date", ""))
    if date_a and date_b and abs((date_a - date_b).days) > 2:
        return False

    if not _fuzzy_match(a.get("city", ""), b.get("city", "")):
        return False

    return True


def filter_to_target_countries(
    events: list,
    target_countries: Optional[set] = None,
) -> tuple:
    """
    Split events into (kept, removed) based on country filter.
    Returns both lists for audit logging.
    """
    targets = target_countries or DEFAULT_TARGET_COUNTRIES
    kept, removed = [], []
    for event in events:
        country = (event.get("country") or "").lower()
        if country in targets:
            kept.append(event)
        else:
            removed.append(event)
    return kept, removed


def deduplicate(events: list) -> tuple:
    """
    Remove duplicate events using deterministic matching.
    When duplicates are found, keeps the higher-confidence version.
    Returns (deduplicated_events, duplicates_log).
    """
    kept = []
    duplicates_log = []

    for event in events:
        matched_idx = None
        for i, existing in enumerate(kept):
            if _are_duplicates(event, existing):
                matched_idx = i
                break

        if matched_idx is None:
            kept.append(event)
        else:
            existing = kept[matched_idx]
            event_score = _CONF_SCORE.get(event.get("confidence", ""), 0)
            existing_score = _CONF_SCORE.get(existing.get("confidence", ""), 0)
            duplicates_log.append(
                {
                    "kept_url": existing.get("article_url"),
                    "removed_url": event.get("article_url"),
                    "country": event.get("country"),
                    "city": event.get("city"),
                    "event_type": event.get("event_type"),
                    "event_date": event.get("event_date"),
                    "reason": "duplicate",
                }
            )
            if event_score > existing_score:
                kept[matched_idx] = event  # replace with higher-confidence version

    return kept, duplicates_log


def recheck_borderline(
    events: list,
    provider: str,
    model: str,
    api_key: str,
    codebook_path: Optional[str] = None,
) -> list:
    """
    Re-classify medium and low confidence events using chain-of-thought prompting.
    Updates event_type and confidence in-place where the re-classification differs.
    Returns the updated events list.
    """
    from src.models.llm_classifier import LLMClassifier
    from src.utils.codebook_manager import CodebookManager

    if codebook_path is None:
        codebook_path = str(
            Path(__file__).resolve().parents[2] / "configs" / "protest_codebook.yaml"
        )

    codebook = CodebookManager(codebook_path)
    classifier = LLMClassifier(
        model_name=provider,
        codebook_manager=codebook,
        api_keys={provider: api_key},
        ollama_model=model,
    )

    borderline = [e for e in events if e.get("confidence") in ("medium", "low")]
    log.info(f"Re-checking {len(borderline)} borderline events via {provider}/{model}")

    for event in borderline:
        # Build a compact text summary of the event for re-classification
        text = (
            f"Country: {event.get('country')}. "
            f"City: {event.get('city')}. "
            f"Date: {event.get('event_date')}. "
            f"Organizer: {event.get('organizer')}. "
            f"Claims: {'; '.join(event.get('claims') or [])}. "
            f"State response: {event.get('state_response')}. "
            f"Outcome: {event.get('outcome')}. "
            f"Source headline: {event.get('article_title')}."
        )
        try:
            prediction = classifier.classify_with_cot(text)
            if prediction.event_type not in ("UNCLASSIFIABLE", event.get("event_type")):
                log.info(
                    f"  Re-classified: {event.get('event_type')} → {prediction.event_type} "
                    f"(confidence {prediction.confidence_score:.2f})"
                )
                event["event_type"] = prediction.event_type
                event["_reclassified"] = True
            # Map numeric confidence back to string tier
            if prediction.confidence_score >= 0.8:
                event["confidence"] = "high"
            elif prediction.confidence_score >= 0.6:
                event["confidence"] = "medium"
            else:
                event["confidence"] = "low"
        except Exception as e:
            log.warning(
                f"Re-classification failed for event ({event.get('article_url')}): {e}"
            )

    return events


def run_quality_control(events: list) -> dict:
    """
    Run QualityController and return a quality report dict.
    Converts raw event dicts to ProtestEventPrediction objects for the controller.
    """
    from src.models.schemas import ProtestEventPrediction
    from src.models.quality_controller import QualityController

    _CONF_TO_SCORE = {"high": 0.85, "medium": 0.70, "low": 0.50}
    valid_types = {
        "demonstration_march",
        "strike_boycott",
        "occupation_seizure",
        "confrontation",
        "petition_signature",
        "vigil",
        "hunger_strike",
        "riot",
    }

    predictions = []
    for event in events:
        score = _CONF_TO_SCORE.get(event.get("confidence", ""), 0.60)
        event_type = event.get("event_type", "UNCLASSIFIABLE")
        predictions.append(
            ProtestEventPrediction(
                event_type=event_type,
                confidence_score=score,
                reasoning="",
                schema_valid=(event_type in valid_types and score >= 0.70),
                key_indicators=[],
            )
        )

    qc = QualityController(predictions)
    report = qc.generate_quality_report()
    report["events_by_country"] = {}
    report["events_by_type"] = {}
    for event in events:
        c = event.get("country", "unknown")
        t = event.get("event_type", "unknown")
        report["events_by_country"][c] = report["events_by_country"].get(c, 0) + 1
        report["events_by_type"][t] = report["events_by_type"].get(t, 0) + 1
    return report


def process_events(
    input_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    target_countries: Optional[set] = None,
    recheck: bool = True,
    provider: str = "azure",
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    upload_to: Optional[str] = None,
) -> list:
    """
    Run the full Stage 2 processing pipeline.

    Args:
        input_path:       Path to all_events.jsonl (default: data/raw/all_events.jsonl)
        output_dir:       Output directory (default: data/processed/)
        target_countries: Set of lowercase country names to keep (default: Africa)
        recheck:          Whether to LLM-recheck medium/low confidence events
        provider:         LLM provider for rechecking ('claude', 'openai', 'azure')
        model:            Model/deployment name for rechecking
        api_key:          API key (defaults to env var for provider)
        upload_to:        Optional az:// or s3:// destination for outputs

    Returns:
        List of consolidated event dicts written to output_dir.
    """
    root = Path(__file__).resolve().parents[2]
    if input_path is None:
        input_path = root / "data" / "raw" / "all_events.jsonl"
    if output_dir is None:
        output_dir = root / "data" / "processed"

    output_dir.mkdir(parents=True, exist_ok=True)

    # Load
    if not input_path.exists():
        log.error(f"Input not found: {input_path}")
        return []
    with open(input_path, encoding="utf-8") as f:
        raw_events = [json.loads(line) for line in f if line.strip()]
    log.info(f"Loaded {len(raw_events)} raw events from {input_path}")

    # Step 1: Filter to target geography
    events, removed = filter_to_target_countries(raw_events, target_countries)
    log.info(
        f"Geography filter: kept {len(events)}, removed {len(removed)} non-target events"
    )

    # Step 2: Deduplicate
    events, duplicates_log = deduplicate(events)
    log.info(
        f"Deduplication: {len(events)} events remain ({len(duplicates_log)} duplicates removed)"
    )

    # Step 3: Re-verify borderline events
    if recheck:
        from src.acquisition.extractor import (
            _PROVIDER_ENV_VARS,
            _PROVIDER_DEFAULT_MODELS,
        )

        resolved_key = api_key or os.environ.get(
            _PROVIDER_ENV_VARS.get(provider, ""), ""
        )
        resolved_model = model or _PROVIDER_DEFAULT_MODELS.get(provider, "gpt-4o-mini")
        if resolved_key:
            events = recheck_borderline(events, provider, resolved_model, resolved_key)
        else:
            log.warning(f"No API key for {provider} — skipping borderline re-check")

    # Step 4: Quality control
    quality_report = run_quality_control(events)
    log.info(
        f"Quality report: {quality_report['schema_validity']['validity_rate']:.0%} schema valid, "
        f"mean confidence {quality_report['confidence_distribution'].get('mean_confidence', 0):.2f}"
    )

    # Write outputs
    consolidated_path = output_dir / "events_consolidated.jsonl"
    with open(consolidated_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    log.info(f"Consolidated events written: {consolidated_path} ({len(events)} events)")

    quality_path = output_dir / "quality_report.json"
    with open(quality_path, "w", encoding="utf-8") as f:
        json.dump(quality_report, f, indent=2, ensure_ascii=False)
    log.info(f"Quality report written: {quality_path}")

    if duplicates_log:
        dup_path = output_dir / "duplicates_log.jsonl"
        with open(dup_path, "w", encoding="utf-8") as f:
            for entry in duplicates_log:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        log.info(f"Duplicates log written: {dup_path} ({len(duplicates_log)} entries)")

    # Print summary
    print("\n" + "=" * 60)
    print("STAGE 2 — PROCESSING SUMMARY")
    print("=" * 60)
    print(f"Input events:        {len(raw_events)}")
    print(
        f"After geo filter:    {len(raw_events) - len(removed)} ({len(removed)} removed)"
    )
    print(
        f"After dedup:         {len(events)} ({len(duplicates_log)} duplicates removed)"
    )
    print(
        f"Schema valid:        {quality_report['schema_validity']['valid_schemas']} / {len(events)}"
    )
    print("\nBy country:")
    for c, n in sorted(
        quality_report["events_by_country"].items(), key=lambda x: -x[1]
    ):
        print(f"  {c:35s} {n}")
    print("\nBy event type:")
    for t, n in sorted(quality_report["events_by_type"].items(), key=lambda x: -x[1]):
        print(f"  {t:35s} {n}")
    print(f"\nOutput: {output_dir}")
    print("=" * 60 + "\n")

    # Upload
    if upload_to:
        from src.acquisition.storage import _upload_outputs

        paths = [consolidated_path, quality_path]
        if duplicates_log:
            paths.append(output_dir / "duplicates_log.jsonl")
        _upload_outputs(upload_to, paths)
        log.info(f"Stage 2 outputs uploaded to {upload_to}")

    return events
