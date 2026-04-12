"""
Stage 2: Processing and Consolidation
======================================
Reads data/raw/all_events.jsonl and produces a clean, deduplicated,
quality-controlled dataset in data/processed/.

Steps:
  1. Load all raw events across runs
  2. Filter to target geography (remove noise from broken GDELT runs)
  3. Deduplicate — deterministic rules: same country + city + date ±3 days + event_type
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
import math
import os
from collections import Counter
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
    """Return True if strings are similar enough."""
    if not a or not b:
        return False  # both must be present to make a positive match
    return (
        SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio() >= threshold
    )


def _tokenise(text: str) -> list[str]:
    """Lowercase, split on non-alpha, filter short tokens."""
    import re
    return [t for t in re.split(r"[^a-z]+", text.lower()) if len(t) > 2]


def _tfidf_cosine(a_tokens: list[str], b_tokens: list[str], idf: dict) -> float:
    """
    Compute TF-IDF cosine similarity between two token lists.
    idf is a pre-computed {token: idf_weight} dict.
    Returns 0.0 if either token list is empty.
    """
    if not a_tokens or not b_tokens:
        return 0.0

    def tfidf_vec(tokens: list[str]) -> dict:
        tf = Counter(tokens)
        n = len(tokens)
        return {t: (tf[t] / n) * idf.get(t, 1.0) for t in tf}

    va, vb = tfidf_vec(a_tokens), tfidf_vec(b_tokens)
    shared = set(va) & set(vb)
    if not shared:
        return 0.0
    dot = sum(va[t] * vb[t] for t in shared)
    mag_a = math.sqrt(sum(v * v for v in va.values()))
    mag_b = math.sqrt(sum(v * v for v in vb.values()))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _build_idf(events: list[dict]) -> dict:
    """
    Build a simple IDF table from the claims fields of all events.
    Used to down-weight common words (e.g. 'government', 'workers')
    when comparing claims similarity.
    """
    n = len(events)
    if n == 0:
        return {}
    df: Counter = Counter()
    for event in events:
        claims_tokens = set(
            _tokenise(" ".join(event.get("claims") or []))
        )
        df.update(claims_tokens)
    return {t: math.log(n / (1 + df[t])) + 1 for t in df}


def _claims_similarity(a: dict, b: dict, idf: dict) -> float:
    """TF-IDF cosine similarity between the claims arrays of two events."""
    a_text = " ".join(a.get("claims") or [])
    b_text = " ".join(b.get("claims") or [])
    return _tfidf_cosine(_tokenise(a_text), _tokenise(b_text), idf)


def _are_duplicates(a: dict, b: dict, idf: Optional[dict] = None) -> bool:
    """
    Improved duplicate check — two events are duplicates when they satisfy
    ALL blocking criteria AND the claims similarity confirms the match.

    Blocking criteria (hard gates, all must pass):
      1. Same country (exact, case-insensitive)
      2. Same event_type (exact)
      3. Dates within ±3 days (widened from ±2 to handle prolonged events)
      4. City fuzzy-match ≥ 0.7 — ONLY applied when BOTH cities are non-empty.
         If either city is null the date + claims gate below must do the work.

    Claims gate (soft, kicks in when both events have claims):
      5. TF-IDF cosine similarity of claims ≥ 0.20.
         A very low threshold — just enough to reject two clearly different
         events in the same city on the same day (e.g. a labour strike and
         a student march at the same university campus).
         When either event has no claims this gate is skipped (null = unknown).
    """
    # Gate 1: country
    if (a.get("country") or "").lower() != (b.get("country") or "").lower():
        return False

    # Gate 2: event type
    if a.get("event_type") != b.get("event_type"):
        return False

    # Gate 3: date proximity (±3 days)
    date_a = _parse_event_date(a.get("event_date", ""))
    date_b = _parse_event_date(b.get("event_date", ""))
    if date_a and date_b and abs((date_a - date_b).days) > 3:
        return False

    # Gate 4: city fuzzy match — only enforced when both cities are present.
    city_a = (a.get("city") or "").strip()
    city_b = (b.get("city") or "").strip()
    if city_a and city_b and not _fuzzy_match(city_a, city_b, threshold=0.7):
        return False

    # Gate 5: claims similarity — only enforced when both events have claims.
    claims_a = a.get("claims") or []
    claims_b = b.get("claims") or []
    if claims_a and claims_b:
        sim = _claims_similarity(a, b, idf or {})
        if sim < 0.20:
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
    Remove duplicate events using deterministic + claims-similarity matching.
    When duplicates are found, keeps the higher-confidence version.

    Pre-computes a corpus-level IDF table from all events so that
    _are_duplicates() can use TF-IDF cosine similarity on claims without
    re-scanning the corpus on every comparison.

    Returns (deduplicated_events, duplicates_log).
    """
    idf = _build_idf(events)
    kept = []
    duplicates_log = []

    for event in events:
        matched_idx = None
        for i, existing in enumerate(kept):
            if _are_duplicates(event, existing, idf=idf):
                matched_idx = i
                break

        if matched_idx is None:
            kept.append(event)
        else:
            existing = kept[matched_idx]
            event_score = _CONF_SCORE.get(event.get("confidence", ""), 0)
            existing_score = _CONF_SCORE.get(existing.get("confidence", ""), 0)
            claims_sim = round(_claims_similarity(event, existing, idf), 3)
            duplicates_log.append(
                {
                    "kept_url": existing.get("article_url"),
                    "removed_url": event.get("article_url"),
                    "country": event.get("country"),
                    "city": event.get("city"),
                    "event_type": event.get("event_type"),
                    "event_date": event.get("event_date"),
                    "claims_similarity": claims_sim,
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
    Re-classify medium and low confidence events via Azure AI Foundry.
    Uses the same SYSTEM_PROMPT (codebook v2.3) as the main extractor.
    Updates event_type and confidence in-place where the re-classification differs.
    Returns the updated events list.
    """
    from src.acquisition.extractor import _call_azure, SYSTEM_PROMPT

    valid_types = {
        "demonstration_march", "strike_boycott", "occupation_seizure",
        "confrontation", "petition_signature", "vigil", "hunger_strike", "riot",
    }
    valid_types_str = ", ".join(sorted(valid_types))

    borderline = [e for e in events if e.get("confidence") in ("medium", "low")]
    log.info(f"Re-checking {len(borderline)} borderline events via {provider}/{model}")

    for event in borderline:
        summary = (
            f"Country: {event.get('country')}. "
            f"City: {event.get('city')}. "
            f"Date: {event.get('event_date')}. "
            f"Organizer: {event.get('organizer')}. "
            f"Claims: {'; '.join(event.get('claims') or [])}. "
            f"State response: {event.get('state_response')}. "
            f"Outcome: {event.get('outcome')}. "
            f"Source headline: {event.get('article_title')}."
        )
        user_msg = (
            f"Re-evaluate this borderline protest event extract. "
            f"Return ONLY a JSON object with keys 'event_type' (one of: {valid_types_str}) "
            f"and 'confidence' (high/medium/low).\n\n{summary}"
        )
        try:
            raw = _call_azure(system=SYSTEM_PROMPT, user=user_msg, model=model, api_key=api_key)
            if not raw:
                continue
            import json as _json, re as _re
            # Extract JSON object from response
            m = _re.search(r'\{[^{}]+\}', raw, _re.DOTALL)
            if not m:
                continue
            data = _json.loads(m.group())
            new_type = data.get("event_type", "")
            new_conf = data.get("confidence", "")
            if new_type in valid_types and new_type != event.get("event_type"):
                log.info(
                    f"  Re-classified: {event.get('event_type')} → {new_type}"
                )
                event["event_type"] = new_type
                event["_reclassified"] = True
            if new_conf in ("high", "medium", "low"):
                event["confidence"] = new_conf
        except Exception as e:
            log.warning(
                f"Re-classification failed for event ({event.get('article_url')}): {e}"
            )

    return events


def run_quality_control(events: list) -> dict:
    """Return schema validity + confidence distribution report for a list of events."""
    import numpy as np

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

    n = len(events)
    valid = sum(
        1 for e in events
        if e.get("event_type") in valid_types
        and _CONF_TO_SCORE.get(e.get("confidence", ""), 0.0) >= 0.70
    )
    scores = [_CONF_TO_SCORE.get(e.get("confidence", ""), 0.60) for e in events]
    arr = np.array(scores) if scores else np.array([0.0])

    report = {
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
        "events_by_country": {},
        "events_by_type": {},
    }
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
        provider:         LLM provider for rechecking (always 'azure')
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
        try:
            _upload_outputs(upload_to, paths)
            log.info(f"Stage 2 outputs uploaded to {upload_to}")
        except Exception as e:
            log.warning(f"Stage 2 cloud upload failed (results saved locally): {e}")

    return events
