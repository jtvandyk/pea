"""
CEHA Relevance Validator
========================
Evaluates the pipeline's RelevanceFilter against the CEHA (Conflict Events
in the Horn of Africa) dataset — 500 expert-annotated event descriptions
sourced from ACLED (250) and GDELT (250).

## What this validates

CEHA's event types (tribal conflict, religious conflict, SGBV, climate
security) do NOT map to PEA's protest types. Use this validator to:
  - Measure relevance filter F1 on African conflict text
  - Calibrate the --relevance-threshold before running the full pipeline
  - Spot-check recall by CEHA event type (ethnic_communal, religious, etc.)

Do NOT use CEHA to validate protest event_type classification.

## Dataset

  git clone https://github.com/dataminr-ai/CEHA  CEHA
  # file: CEHA/data/CEHA_dataset.csv

  Splits: test=250, dev=50, train=200  (use test for held-out evaluation)
  Labels: Is the event relevant? = Yes / No

## Usage

  python -m src.validation.ceha_validator \\
    --ceha-csv CEHA/data/CEHA_dataset.csv \\
    --split test \\
    --output data/validation/ceha_report.json

  # Use keyword fallback only (no model download)
  python -m src.validation.ceha_validator \\
    --ceha-csv CEHA/data/CEHA_dataset.csv \\
    --no-model \\
    --output data/validation/ceha_report_keyword.json

  # Sweep thresholds to find the best F1 operating point
  python -m src.validation.ceha_validator \\
    --ceha-csv CEHA/data/CEHA_dataset.csv \\
    --sweep-thresholds \\
    --output data/validation/ceha_sweep.json

## Interpreting results

Bai et al. (2025) report ~0.70 F1 for zero-shot LLMs on CEHA relevance.
The DeBERTa NLI filter is not fine-tuned on African conflict text, so
expect lower performance — the number tells you how much headroom exists
before fine-tuning would help.

Recall is more important than precision here: the pipeline is designed for
high recall (--relevance-threshold 0.30 default), so false positives
(non-relevant articles passed to the LLM) are expected and budgeted for.
"""

import csv
import json
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# CEHA event type columns (multi-label, marked with 'X' when applicable)
CEHA_TYPE_COLUMNS: list = [
    "tribal/communal/ethnic conflict",
    "religious conflict",
    "socio-political violence against women",
    "climate-related security risks",
    "Other",
]

# Short labels for reporting
CEHA_TYPE_SHORT: dict = {
    "tribal/communal/ethnic conflict":         "ethnic_communal",
    "religious conflict":                      "religious",
    "socio-political violence against women":  "gender_rights",
    "climate-related security risks":          "climate_security",
    "Other":                                   "other",
}


def load_ceha(path: Path, split: Optional[str] = "test") -> list[dict]:
    """
    Load CEHA CSV and return normalised event dicts.

    Args:
        path:  Path to CEHA_dataset.csv
        split: 'test', 'dev', 'train', or None / 'all' for all splits
    """
    path = Path(path)
    events = []
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if split and split != "all" and row.get("train_dev_test_split") != split:
                continue
            events.append(_normalise_ceha(row))

    log.info("Loaded %d CEHA events (split=%s) from %s", len(events), split, path)
    return events


def _normalise_ceha(row: dict) -> dict:
    """Normalise a raw CEHA CSV row to a standard internal dict."""
    # Multi-label types: collect which columns are marked 'X'
    event_types = [
        CEHA_TYPE_SHORT[col]
        for col in CEHA_TYPE_COLUMNS
        if (row.get(col) or "").strip().upper() == "X"
    ]

    return {
        "index":         row.get("Index", ""),
        "source":        row.get("ACLED/GDELT", ""),
        "time":          row.get("Time", ""),
        "country":       row.get("Country", ""),
        "actor1":        row.get("Actor 1", ""),
        "actor2":        row.get("Actor 2", ""),
        "url":           row.get("Article Url", ""),
        "text":          row.get("Event Description", ""),
        "relevant":      row.get("Is the event relevant?", "").strip().lower() == "yes",
        "event_types":   event_types,
        "split":         row.get("train_dev_test_split", ""),
        "raw":           row,
    }


def _events_to_articles(events: list[dict]) -> list[dict]:
    """
    Convert CEHA event dicts to the article dict format expected by
    RelevanceFilter.filter(). The filter uses title + first 200 chars of text.
    """
    return [{"text": e["text"], "title": "", "_ceha_index": e["index"]} for e in events]


def score_with_filter(
    events: list[dict],
    threshold: float = 0.30,
    model_name: str = "cross-encoder/nli-deberta-v3-small",
    use_model: bool = True,
) -> list[dict]:
    """
    Run RelevanceFilter on the event descriptions and attach scores.
    Returns the same list with '_relevance_score', '_relevance_source',
    and '_predicted_relevant' added to each event dict.
    """
    from src.acquisition.relevance_filter import RelevanceFilter

    filt = RelevanceFilter(
        model_name=model_name if use_model else "DISABLED",
        threshold=threshold,
        domain="protest",
    )
    articles = _events_to_articles(events)
    kept, rejected = filt.filter(articles)

    # Index scores back by _ceha_index
    score_map: dict = {}
    for a in kept + rejected:
        score_map[a["_ceha_index"]] = {
            "score":  a["_relevance_score"],
            "source": a["_relevance_source"],
            "kept":   a["_relevance_score"] >= threshold,
        }

    for e in events:
        info = score_map.get(e["index"], {"score": 0.0, "source": "unknown", "kept": False})
        e["_relevance_score"]     = info["score"]
        e["_relevance_source"]    = info["source"]
        e["_predicted_relevant"]  = info["kept"]

    return events


def compute_metrics(events: list[dict]) -> dict:
    """
    Compute F1, precision, recall for binary relevance classification.
    Also provides breakdowns by country, ACLED/GDELT source, and CEHA type.
    """
    tp = sum(1 for e in events if e["relevant"] and e["_predicted_relevant"])
    fp = sum(1 for e in events if not e["relevant"] and e["_predicted_relevant"])
    fn = sum(1 for e in events if e["relevant"] and not e["_predicted_relevant"])
    tn = sum(1 for e in events if not e["relevant"] and not e["_predicted_relevant"])

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall    = tp / (tp + fn) if (tp + fn) else 0.0
    f1        = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    # Breakdown by country
    by_country: dict = {}
    for e in events:
        c = e["country"]
        if c not in by_country:
            by_country[c] = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
        key = ("tp" if e["relevant"] else "fp") if e["_predicted_relevant"] else ("fn" if e["relevant"] else "tn")
        by_country[c][key] += 1
    for c in by_country:
        v = by_country[c]
        p = v["tp"] / (v["tp"] + v["fp"]) if (v["tp"] + v["fp"]) else 0.0
        r = v["tp"] / (v["tp"] + v["fn"]) if (v["tp"] + v["fn"]) else 0.0
        by_country[c]["precision"] = round(p, 3)
        by_country[c]["recall"]    = round(r, 3)
        by_country[c]["f1"]        = round(2 * p * r / (p + r) if (p + r) else 0.0, 3)

    # Breakdown by ACLED/GDELT source
    by_source: dict = {}
    for e in events:
        s = e["source"]
        if s not in by_source:
            by_source[s] = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
        key = ("tp" if e["relevant"] else "fp") if e["_predicted_relevant"] else ("fn" if e["relevant"] else "tn")
        by_source[s][key] += 1
    for s in by_source:
        v = by_source[s]
        p = v["tp"] / (v["tp"] + v["fp"]) if (v["tp"] + v["fp"]) else 0.0
        r = v["tp"] / (v["tp"] + v["fn"]) if (v["tp"] + v["fn"]) else 0.0
        by_source[s]["precision"] = round(p, 3)
        by_source[s]["recall"]    = round(r, 3)
        by_source[s]["f1"]        = round(2 * p * r / (p + r) if (p + r) else 0.0, 3)

    # Recall by CEHA event type (only for relevant events)
    by_type: dict = {}
    for e in events:
        if not e["relevant"]:
            continue
        for t in (e["event_types"] or ["(unlabelled)"]):
            if t not in by_type:
                by_type[t] = {"total": 0, "recalled": 0}
            by_type[t]["total"] += 1
            if e["_predicted_relevant"]:
                by_type[t]["recalled"] += 1
    for t in by_type:
        v = by_type[t]
        v["recall"] = round(v["recalled"] / v["total"], 3) if v["total"] else 0.0

    return {
        "precision":  round(precision, 3),
        "recall":     round(recall, 3),
        "f1":         round(f1, 3),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "total":      len(events),
        "n_relevant": tp + fn,
        "n_predicted_relevant": tp + fp,
        "baseline_f1": "~0.70 (Bai et al. 2025, zero-shot LLMs on CEHA)",
        "by_country": by_country,
        "by_source":  by_source,
        "by_type":    by_type,
    }


def sweep_thresholds(
    events: list[dict],
    thresholds: Optional[list] = None,
) -> list[dict]:
    """
    Compute F1 at each threshold value using pre-scored events.
    Events must already have '_relevance_score' set (call score_with_filter first).
    """
    if thresholds is None:
        thresholds = [round(t / 20, 2) for t in range(1, 20)]  # 0.05 … 0.95

    results = []
    for thr in thresholds:
        for e in events:
            e["_predicted_relevant"] = e.get("_relevance_score", 0.0) >= thr
        m = compute_metrics(events)
        results.append({
            "threshold": thr,
            "f1":        m["f1"],
            "precision": m["precision"],
            "recall":    m["recall"],
        })

    # Restore predictions at 0.30 default
    for e in events:
        e["_predicted_relevant"] = e.get("_relevance_score", 0.0) >= 0.30

    return results


def run_validation(
    ceha_csv: Path,
    output_path: Optional[Path] = None,
    split: str = "test",
    threshold: float = 0.30,
    model_name: str = "cross-encoder/nli-deberta-v3-small",
    use_model: bool = True,
    do_sweep: bool = False,
) -> dict:
    """
    Full CEHA relevance validation run.
    Returns the metrics dict and writes a JSON report.
    """
    events = load_ceha(ceha_csv, split=split)
    if not events:
        log.error("No CEHA events loaded — check --ceha-csv path and --split value.")
        return {}

    events = score_with_filter(events, threshold=threshold,
                               model_name=model_name, use_model=use_model)
    metrics = compute_metrics(events)

    # Console summary
    print("\n" + "=" * 60)
    print("CEHA RELEVANCE VALIDATION REPORT")
    print("=" * 60)
    print(f"Split:          {split}  ({metrics['total']} items)")
    print(f"Relevant:       {metrics['n_relevant']}  ({metrics['n_relevant']/metrics['total']:.0%})")
    print(f"Predicted rel:  {metrics['n_predicted_relevant']}")
    print(f"Precision:      {metrics['precision']:.1%}")
    print(f"Recall:         {metrics['recall']:.1%}")
    print(f"F1:             {metrics['f1']:.1%}  (baseline: {metrics['baseline_f1']})")
    print(f"TP/FP/FN/TN:    {metrics['tp']} / {metrics['fp']} / {metrics['fn']} / {metrics['tn']}")
    print("\nRecall by CEHA event type (relevant events only):")
    for t, v in sorted(metrics["by_type"].items(), key=lambda x: -x[1]["recall"]):
        bar = "█" * int(v["recall"] * 20)
        print(f"  {t:35s} {v['recall']:.0%}  {bar}  ({v['recalled']}/{v['total']})")
    print("\nF1 by source:")
    for s, v in sorted(metrics["by_source"].items()):
        print(f"  {s:10s}  F1={v['f1']:.1%}  P={v['precision']:.1%}  R={v['recall']:.1%}")
    print("=" * 60 + "\n")

    report: dict = {
        "metrics":  metrics,
        "settings": {
            "split":      split,
            "threshold":  threshold,
            "model":      model_name if use_model else "keyword_fallback",
        },
        "event_scores": [
            {
                "index":              e["index"],
                "country":            e["country"],
                "source":             e["source"],
                "relevant":           e["relevant"],
                "predicted_relevant": e["_predicted_relevant"],
                "score":              e.get("_relevance_score"),
                "score_source":       e.get("_relevance_source"),
                "text_preview":       e["text"][:100],
                "event_types":        e["event_types"],
            }
            for e in events
        ],
    }

    if do_sweep:
        sweep = sweep_thresholds(events)
        report["threshold_sweep"] = sweep
        best = max(sweep, key=lambda x: x["f1"])
        print(f"Best F1 {best['f1']:.1%} at threshold {best['threshold']}")
        print()

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        log.info("CEHA report written: %s", output_path)

    return metrics


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    import logging as _logging

    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="Evaluate PEA relevance filter against CEHA dataset"
    )
    parser.add_argument(
        "--ceha-csv",
        required=True,
        help="Path to CEHA/data/CEHA_dataset.csv",
    )
    parser.add_argument(
        "--split",
        default="test",
        choices=["test", "dev", "train", "all"],
        help="Dataset split to evaluate [default: test]",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.30,
        help="Relevance filter threshold [default: 0.30]",
    )
    parser.add_argument(
        "--model-name",
        default="cross-encoder/nli-deberta-v3-small",
        help="HuggingFace model name for zero-shot classification",
    )
    parser.add_argument(
        "--no-model",
        action="store_true",
        default=False,
        help="Use keyword fallback only (no model download)",
    )
    parser.add_argument(
        "--sweep-thresholds",
        action="store_true",
        default=False,
        help="Report F1 at each threshold from 0.05 to 0.95",
    )
    parser.add_argument(
        "--output",
        default="data/validation/ceha_report.json",
        help="Output path for the JSON report",
    )
    args = parser.parse_args()

    run_validation(
        ceha_csv=Path(args.ceha_csv),
        output_path=Path(args.output),
        split=args.split,
        threshold=args.threshold,
        model_name=args.model_name,
        use_model=not args.no_model,
        do_sweep=args.sweep_thresholds,
    )
