"""
CASE 2021 Task 2 Validator
===========================
Evaluates the pipeline against the CASE 2021 Shared Task 2 test set —
1,019 event snippets with 30 fine-grained event type labels.

## What this validates

Two modes:

  relevance  (no API key needed)
    Uses the pipeline's RelevanceFilter to classify each snippet as
    protest / not-protest. Gold labels are derived from the CASE SubType:
    protest-relevant SubTypes → 1, all others → 0.
    Reports: F1, precision, recall (binary), breakdown by SubType.

  extraction  (requires LLM API key)
    Uses the pipeline's LLM extractor on each protest-relevant snippet
    (172 items) and compares the returned event_type against the CASE
    SubType crosswalk.
    Reports: per-type accuracy + macro-F1 on the protest subset.

## Dataset

  git clone https://github.com/emerging-welfare/case-2021-shared-task CASE2021
  # file: CASE2021/task2/test_dataset/test_set_final_release_with_labels.tsv

  Columns: id, EventSnippet, SubType
  SubTypes: 30 categories including PEACE_PROTEST, VIOL_DEMONSTR,
            FORCE_AGAINST_PROTEST, PROTEST_WITH_INTER, MOB_VIOL, ...

## Usage

  # Relevance mode (offline)
  python -m src.validation.case2021_validator \\
    --case-tsv CASE2021/task2/test_dataset/test_set_final_release_with_labels.tsv \\
    --mode relevance \\
    --output data/validation/case2021_relevance_report.json

  # Extraction mode (LLM — requires API key)
  python -m src.validation.case2021_validator \\
    --case-tsv CASE2021/task2/test_dataset/test_set_final_release_with_labels.tsv \\
    --mode extraction \\
    --provider azure \\
    --model gpt-4o-mini \\
    --output data/validation/case2021_extraction_report.json

## CASE SubType → PEA event_type crosswalk

  PEACE_PROTEST         → demonstration_march
  VIOL_DEMONSTR         → riot
  PROTEST_WITH_INTER    → confrontation
  FORCE_AGAINST_PROTEST → demonstration_march  (state forces vs protesters)
  MOB_VIOL              → riot
"""

import csv
import json
import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CASE Task 2 SubTypes that map to protest events (label = 1)
# ---------------------------------------------------------------------------
PROTEST_SUBTYPES: set = {
    "PEACE_PROTEST",
    "VIOL_DEMONSTR",
    "FORCE_AGAINST_PROTEST",
    "PROTEST_WITH_INTER",
    "MOB_VIOL",
}

# CASE SubType → PEA codebook event_type crosswalk (for extraction mode)
CASE_TO_PEA: dict = {
    "PEACE_PROTEST": "demonstration_march",
    "VIOL_DEMONSTR": "riot",
    "PROTEST_WITH_INTER": "confrontation",
    "FORCE_AGAINST_PROTEST": "demonstration_march",
    "MOB_VIOL": "riot",
}

# PEA event_type → broad category (for type-level metrics)
PEA_TO_BROAD: dict = {
    "demonstration_march": "protest",
    "strike_boycott": "strike",
    "occupation_seizure": "protest",
    "confrontation": "protest",
    "petition_signature": "protest",
    "vigil": "protest",
    "hunger_strike": "protest",
    "riot": "riot",
}


def load_case2021(path: Path) -> list[dict]:
    """Load CASE Task 2 TSV and return normalised event dicts."""
    path = Path(path)
    events = []
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            events.append(_normalise_case(row))
    log.info("Loaded %d CASE 2021 Task 2 events from %s", len(events), path)
    return events


def _normalise_case(row: dict) -> dict:
    sub_type = (row.get("SubType") or "").strip()
    is_protest = sub_type in PROTEST_SUBTYPES
    pea_gold = CASE_TO_PEA.get(sub_type)
    return {
        "id": row.get("id", ""),
        "text": row.get("EventSnippet", ""),
        "sub_type": sub_type,
        "is_protest": is_protest,
        "pea_gold": pea_gold,
        "raw": row,
    }


def _events_to_articles(events: list[dict]) -> list[dict]:
    """Convert CASE event dicts to article dicts for RelevanceFilter."""
    return [{"text": e["text"], "title": "", "_case_id": e["id"]} for e in events]


# ---------------------------------------------------------------------------
# Mode 1: Relevance — binary protest / not-protest via RelevanceFilter
# ---------------------------------------------------------------------------


def run_relevance_mode(
    events: list[dict],
    threshold: float = 0.30,
    model_name: str = "cross-encoder/nli-deberta-v3-small",
    use_model: bool = True,
) -> dict:
    """
    Run RelevanceFilter on all 1,019 snippets and compare against
    the binary protest/not-protest gold label derived from CASE SubTypes.
    Returns a metrics dict.
    """
    from src.acquisition.relevance_filter import RelevanceFilter

    filt = RelevanceFilter(
        model_name=model_name if use_model else "DISABLED",
        threshold=threshold,
        domain="protest",
    )
    articles = _events_to_articles(events)
    kept, rejected = filt.filter(articles)

    score_map: dict = {}
    for a in kept + rejected:
        score_map[str(a["_case_id"])] = {
            "score": a["_relevance_score"],
            "source": a["_relevance_source"],
            "predicted": a["_relevance_score"] >= threshold,
        }

    for e in events:
        info = score_map.get(
            str(e["id"]), {"score": 0.0, "source": "unknown", "predicted": False}
        )
        e["_relevance_score"] = info["score"]
        e["_relevance_source"] = info["source"]
        e["_predicted_protest"] = info["predicted"]

    return _compute_relevance_metrics(events, threshold)


def _compute_relevance_metrics(events: list[dict], threshold: float) -> dict:
    tp = sum(1 for e in events if e["is_protest"] and e["_predicted_protest"])
    fp = sum(1 for e in events if not e["is_protest"] and e["_predicted_protest"])
    fn = sum(1 for e in events if e["is_protest"] and not e["_predicted_protest"])
    tn = sum(1 for e in events if not e["is_protest"] and not e["_predicted_protest"])

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    # Recall by CASE SubType
    by_subtype: dict = {}
    for e in events:
        t = e["sub_type"]
        if t not in by_subtype:
            by_subtype[t] = {
                "total": 0,
                "predicted_protest": 0,
                "is_protest": e["is_protest"],
            }
        by_subtype[t]["total"] += 1
        if e["_predicted_protest"]:
            by_subtype[t]["predicted_protest"] += 1
    for t in by_subtype:
        v = by_subtype[t]
        v["recall"] = (
            round(v["predicted_protest"] / v["total"], 3) if v["total"] else 0.0
        )

    return {
        "mode": "relevance",
        "threshold": threshold,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "total": len(events),
        "n_protest_gold": tp + fn,
        "n_protest_pred": tp + fp,
        "by_subtype": by_subtype,
    }


# ---------------------------------------------------------------------------
# Mode 2: Extraction — LLM event_type classification on protest subset
# ---------------------------------------------------------------------------


def run_extraction_mode(
    events: list[dict],
    provider: str = "azure",
    model: str = "gpt-4o-mini",
    api_key: Optional[str] = None,
    max_workers: int = 4,
) -> dict:
    """
    Run the LLM extractor on the 172 protest-relevant snippets and compare
    the returned event_type against the CASE SubType crosswalk.

    Each snippet is wrapped as a minimal article dict for extract_from_article().
    Returns a metrics dict with per-type accuracy.
    """
    from src.acquisition.extractor import extract_from_article

    if api_key is None:
        api_key = _resolve_api_key(provider)

    protest_events = [e for e in events if e["is_protest"]]
    log.info(
        "Extraction mode: running LLM on %d protest-relevant CASE snippets",
        len(protest_events),
    )

    results = []
    for e in protest_events:
        article = {
            "url": f"case2021://task2/{e['id']}",
            "title": "",
            "text": e["text"],
            "text_en": e["text"],
            "date": "",
            "country": "",
        }
        try:
            extracted = extract_from_article(
                article=article,
                model=model,
                api_key=api_key,
                provider=provider,
            )
        except Exception as ex:
            log.warning("Extraction failed for id=%s: %s", e["id"], ex)
            extracted = None

        predicted_type = None
        if extracted:
            predicted_type = extracted[0].get("event_type")

        results.append(
            {
                "id": e["id"],
                "text_preview": e["text"][:100],
                "sub_type": e["sub_type"],
                "pea_gold": e["pea_gold"],
                "pea_predicted": predicted_type,
                "correct": predicted_type == e["pea_gold"],
            }
        )

    return _compute_extraction_metrics(results)


def _resolve_api_key(provider: str) -> str:
    key_map = {
        "azure": "AZURE_FOUNDRY_API_KEY",
        "openai": "OPENAI_API_KEY",
        "claude": "ANTHROPIC_API_KEY",
    }
    env_var = key_map.get(provider, "AZURE_FOUNDRY_API_KEY")
    key = os.environ.get(env_var, "")
    if not key:
        raise RuntimeError(
            f"API key not found. Set {env_var} environment variable or pass --api-key."
        )
    return key


def _compute_extraction_metrics(results: list[dict]) -> dict:
    total = len(results)
    correct = sum(1 for r in results if r["correct"])
    accuracy = correct / total if total else 0.0

    # Per-gold-type breakdown
    by_pea_gold: dict = {}
    for r in results:
        t = r["pea_gold"] or "unknown"
        if t not in by_pea_gold:
            by_pea_gold[t] = {"total": 0, "correct": 0}
        by_pea_gold[t]["total"] += 1
        if r["correct"]:
            by_pea_gold[t]["correct"] += 1
    for t in by_pea_gold:
        v = by_pea_gold[t]
        v["accuracy"] = round(v["correct"] / v["total"], 3) if v["total"] else 0.0

    # Per-CASE-SubType breakdown
    by_sub_type: dict = {}
    for r in results:
        t = r["sub_type"]
        if t not in by_sub_type:
            by_sub_type[t] = {"total": 0, "correct": 0, "pea_gold": CASE_TO_PEA.get(t)}
        by_sub_type[t]["total"] += 1
        if r["correct"]:
            by_sub_type[t]["correct"] += 1
    for t in by_sub_type:
        v = by_sub_type[t]
        v["accuracy"] = round(v["correct"] / v["total"], 3) if v["total"] else 0.0

    return {
        "mode": "extraction",
        "total": total,
        "correct": correct,
        "accuracy": round(accuracy, 3),
        "by_pea_gold": by_pea_gold,
        "by_sub_type": by_sub_type,
        "results": results,
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_validation(
    case_tsv: Path,
    output_path: Optional[Path] = None,
    mode: str = "relevance",
    threshold: float = 0.30,
    model_name: str = "cross-encoder/nli-deberta-v3-small",
    use_model: bool = True,
    provider: str = "azure",
    llm_model: str = "gpt-4o-mini",
    api_key: Optional[str] = None,
) -> dict:
    """Full CASE 2021 Task 2 validation run."""
    events = load_case2021(case_tsv)
    if not events:
        log.error("No CASE 2021 events loaded — check --case-tsv path.")
        return {}

    if mode == "relevance":
        metrics = run_relevance_mode(
            events,
            threshold=threshold,
            model_name=model_name,
            use_model=use_model,
        )
        _print_relevance_summary(metrics)
    elif mode == "extraction":
        metrics = run_extraction_mode(
            events,
            provider=provider,
            model=llm_model,
            api_key=api_key,
        )
        _print_extraction_summary(metrics)
    else:
        raise ValueError(f"Unknown mode '{mode}'. Use 'relevance' or 'extraction'.")

    report = {
        "metrics": metrics,
        "settings": {
            "mode": mode,
            "threshold": threshold if mode == "relevance" else None,
            "model": model_name if mode == "relevance" else llm_model,
        },
    }
    if mode == "relevance":
        report["event_scores"] = [
            {
                "id": e["id"],
                "sub_type": e["sub_type"],
                "is_protest": e["is_protest"],
                "predicted_protest": e.get("_predicted_protest"),
                "score": e.get("_relevance_score"),
                "text_preview": e["text"][:100],
            }
            for e in events
        ]

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        log.info("CASE 2021 report written: %s", output_path)

    return metrics


def _print_relevance_summary(m: dict) -> None:
    print("\n" + "=" * 60)
    print("CASE 2021 TASK 2 — RELEVANCE VALIDATION")
    print("=" * 60)
    print(f"Total snippets:  {m['total']}")
    print(
        f"Protest gold:    {m['n_protest_gold']}  ({m['n_protest_gold']/m['total']:.0%})"
    )
    print(f"Protest pred:    {m['n_protest_pred']}")
    print(f"Precision:       {m['precision']:.1%}")
    print(f"Recall:          {m['recall']:.1%}")
    print(f"F1:              {m['f1']:.1%}")
    print(f"TP/FP/FN/TN:     {m['tp']} / {m['fp']} / {m['fn']} / {m['tn']}")
    print("\nRecall by CASE SubType (protest-relevant types):")
    protest_types = {k: v for k, v in m["by_subtype"].items() if v["is_protest"]}
    for t, v in sorted(protest_types.items(), key=lambda x: -x[1]["recall"]):
        bar = "█" * int(v["recall"] * 20)
        print(
            f"  {t:30s} {v['recall']:.0%}  {bar}  ({v['predicted_protest']}/{v['total']})"
        )
    print("\nFalse positive rate by top non-protest SubTypes:")
    non_protest = {k: v for k, v in m["by_subtype"].items() if not v["is_protest"]}
    for t, v in sorted(non_protest.items(), key=lambda x: -x[1]["recall"])[:8]:
        bar = "█" * int(v["recall"] * 20)
        print(
            f"  {t:30s} FPR={v['recall']:.0%}  {bar}  ({v['predicted_protest']}/{v['total']})"
        )
    print("=" * 60 + "\n")


def _print_extraction_summary(m: dict) -> None:
    print("\n" + "=" * 60)
    print("CASE 2021 TASK 2 — EXTRACTION VALIDATION")
    print("=" * 60)
    print(f"Protest snippets evaluated: {m['total']}")
    print(f"Correct event_type:         {m['correct']}")
    print(f"Accuracy:                   {m['accuracy']:.1%}")
    print("\nAccuracy by gold PEA event type:")
    for t, v in sorted(m["by_pea_gold"].items()):
        bar = "█" * int(v["accuracy"] * 20)
        print(f"  {t:25s} {v['accuracy']:.0%}  {bar}  ({v['correct']}/{v['total']})")
    print("\nAccuracy by CASE SubType:")
    for t, v in sorted(m["by_sub_type"].items()):
        bar = "█" * int(v["accuracy"] * 20)
        print(f"  {t:30s} {v['accuracy']:.0%}  {bar}  ({v['correct']}/{v['total']})")
    print("=" * 60 + "\n")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    import logging as _logging

    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="Evaluate PEA pipeline against CASE 2021 Task 2 test set"
    )
    parser.add_argument(
        "--case-tsv",
        required=True,
        help="Path to CASE2021/task2/test_dataset/test_set_final_release_with_labels.tsv",
    )
    parser.add_argument(
        "--mode",
        default="relevance",
        choices=["relevance", "extraction"],
        help="Validation mode: relevance (offline) or extraction (LLM) [default: relevance]",
    )
    parser.add_argument(
        "--output",
        default="data/validation/case2021_report.json",
        help="Output path for the JSON report",
    )
    # Relevance mode options
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.30,
        help="Relevance filter threshold [default: 0.30]",
    )
    parser.add_argument(
        "--model-name",
        default="cross-encoder/nli-deberta-v3-small",
        help="HuggingFace model for zero-shot classification (relevance mode)",
    )
    parser.add_argument(
        "--no-model",
        action="store_true",
        default=False,
        help="Use keyword fallback only (relevance mode, no model download)",
    )
    # Extraction mode options
    parser.add_argument(
        "--provider",
        default="azure",
        choices=["azure", "openai", "claude"],
        help="LLM provider (extraction mode) [default: azure]",
    )
    parser.add_argument(
        "--llm-model",
        default="gpt-4o-mini",
        help="LLM deployment/model name (extraction mode) [default: gpt-4o-mini]",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key (extraction mode; falls back to env var if not set)",
    )
    args = parser.parse_args()

    run_validation(
        case_tsv=Path(args.case_tsv),
        output_path=Path(args.output),
        mode=args.mode,
        threshold=args.threshold,
        model_name=args.model_name,
        use_model=not args.no_model,
        provider=args.provider,
        llm_model=args.llm_model,
        api_key=args.api_key,
    )
