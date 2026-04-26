"""
Import Label Studio Annotations → Training Data
================================================
Reads a Label Studio export file (JSON), merges human corrections with
the original PEA event data, and writes two outputs:

  1. data/annotation/reviewed_events.jsonl
     All reviewed events with human corrections applied.
     Suitable for direct analysis of pipeline accuracy.

  2. data/annotation/training_data.jsonl
     Gold-standard (article_text → corrected_events JSON) pairs for
     QLoRA fine-tuning or Anthropic Haiku fine-tuning.
     Format: {"prompt": "<article text>", "completion": "<JSON array>"}

Usage:
    # Export from Label Studio: Project → Export → JSON
    python -m src.annotation.import_annotations \\
      --annotations data/annotation/label_studio_export.json \\
      --output-dir data/annotation/

    # Check how many gold pairs are ready for training
    wc -l data/annotation/training_data.jsonl
    # Target: 200+ before starting QLoRA fine-tuning

Annotation interpretation rules:
  - is_protest=no_*          → event is a false positive; excluded from training
  - is_protest=yes           → genuine event; apply corrected_event_type + confidence
  - extraction_errors present → flag the event for manual field correction
  - annotation_notes          → preserved in output for manual review
"""

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

log = logging.getLogger(__name__)

_DEFAULT_EXAMPLES_PATH = (
    Path(__file__).parent.parent.parent / "configs" / "extraction_examples.yaml"
)

# Mapping from Label Studio choice values to training-ready values
_CONF_MAP = {"high": "high", "medium": "medium", "low": "low"}


def _get_choice(annotation: dict, name: str) -> list[str]:
    """Extract selected values for a named Choices widget."""
    results = annotation.get("result", [])
    for r in results:
        if r.get("from_name") == name and r.get("type") == "choices":
            return r.get("value", {}).get("choices", [])
    return []


def _get_text(annotation: dict, name: str) -> str:
    """Extract text from a named TextArea widget."""
    results = annotation.get("result", [])
    for r in results:
        if r.get("from_name") == name and r.get("type") == "textarea":
            texts = r.get("value", {}).get("text", [])
            return texts[0] if texts else ""
    return ""


def process_task(task: dict) -> dict | None:
    """
    Process a single Label Studio task with its annotation.

    Returns a processed event dict, or None if the task was skipped
    (no annotations) or marked as not-a-protest.
    """
    annotations = task.get("annotations", [])
    if not annotations:
        return None

    # Use the most recent non-skipped annotation
    annotation = None
    for a in reversed(annotations):
        if not a.get("was_cancelled", False) and not a.get("skipped", False):
            annotation = a
            break
    if annotation is None:
        return None

    # Recover the original event dict
    data = task.get("data", {})
    source_event_raw = data.get("_source_event", "{}")
    try:
        event = json.loads(source_event_raw)
    except json.JSONDecodeError:
        log.warning(f"Could not parse _source_event for task {task.get('id')}")
        return None

    # Gate: is this a genuine protest event?
    is_protest = _get_choice(annotation, "is_protest")
    verdict = is_protest[0] if is_protest else "yes"  # default to yes if missing

    if verdict != "yes":
        event["_annotation_verdict"] = verdict
        event["_is_false_positive"] = True
        event["_annotation_notes"] = _get_text(annotation, "annotation_notes")
        return event  # include in reviewed_events but exclude from training_data

    # Apply corrections
    corrected_type = _get_choice(annotation, "corrected_event_type")
    if corrected_type:
        event["event_type"] = corrected_type[0]
        event["_type_corrected"] = True

    corrected_conf = _get_choice(annotation, "corrected_confidence")
    if corrected_conf:
        event["confidence"] = corrected_conf[0]

    errors = _get_choice(annotation, "extraction_errors")
    if errors:
        event["_extraction_errors"] = errors

    notes = _get_text(annotation, "annotation_notes")
    if notes:
        event["_annotation_notes"] = notes

    event["_annotation_verdict"] = "yes"
    event["_is_false_positive"] = False
    event["_reviewed_at"] = datetime.utcnow().isoformat()
    event["_annotator_id"] = annotation.get("completed_by", {}).get("id")

    return event


def build_training_pair(event: dict) -> dict | None:
    """
    Build a (prompt, completion) pair for fine-tuning.
    Only called for events where _is_false_positive=False.

    The prompt mirrors the USER_PROMPT_TEMPLATE in extractor.py
    (without the few-shot block, which will be added at training time).
    The completion is the corrected event as a JSON array.
    """
    article_text = event.get("_article_text", "")
    if not article_text:
        # No article text available — can't make a useful training pair
        return None

    prompt = (
        f"Article title: {event.get('article_title', 'Unknown')}\n"
        f"Article URL: {event.get('article_url', '')}\n"
        f"Article date: {event.get('article_date', '')}\n"
        f"Source country: {event.get('source_country', '')}\n"
        f"Original language: {event.get('source_language', 'en')}\n\n"
        f"Article text:\n{article_text}\n\n"
        f"Extract all protest events from this article and return a JSON array."
    )

    # Build the corrected event — strip annotation metadata fields
    training_event = {k: v for k, v in event.items() if not k.startswith("_")}

    completion = json.dumps([training_event], ensure_ascii=False)

    return {
        "prompt": prompt,
        "completion": completion,
        "event_type": event.get("event_type"),
        "country": event.get("country"),
        "confidence": event.get("confidence"),
        "source_url": event.get("article_url"),
    }


def _promotion_rank(event: dict) -> tuple:
    """
    Sort key for promotion candidates — higher is better.
    Priority: type-corrected > extraction-errors flagged > longer article.
    """
    return (
        1 if event.get("_type_corrected") else 0,
        1 if event.get("_extraction_errors") else 0,
        len(event.get("_article_text", "")),
    )


def promote_examples(
    reviewed_events: list[dict],
    examples_path: Path,
    n: int,
) -> int:
    """
    Append up to ``n`` annotator-corrected events to ``examples_path`` as
    new few-shot entries. Each appended entry carries provenance
    metadata (source, task_id, annotator_id, date_promoted).

    De-dupe: uses ``article_url`` as the unique key. If an example with a
    matching provenance.task_id already exists, it is skipped.

    The file is appended to as text rather than round-tripped through
    yaml.safe_dump so handwritten comments and formatting survive.

    Returns the number of entries actually appended.
    """
    if n <= 0:
        return 0

    candidates = [
        e
        for e in reviewed_events
        if not e.get("_is_false_positive") and e.get("_article_text")
    ]
    if not candidates:
        log.info("No promotion candidates (no reviewed events with article text).")
        return 0

    candidates.sort(key=_promotion_rank, reverse=True)

    # Read existing file to dedupe by task_id
    try:
        with open(examples_path, encoding="utf-8") as f:
            existing_data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        existing_data = {}
    except Exception as e:
        log.warning(f"Could not parse existing examples at {examples_path}: {e}")
        existing_data = {}

    existing_examples = (
        (existing_data.get("examples") or []) if isinstance(existing_data, dict) else []
    )
    existing_task_ids = set()
    for ex in existing_examples:
        if not isinstance(ex, dict):
            continue
        prov = ex.get("provenance") or {}
        tid = prov.get("task_id")
        if tid:
            existing_task_ids.add(tid)

    now = datetime.utcnow().isoformat()
    appended: list[dict] = []
    next_id = len(existing_examples) + 1

    for event in candidates:
        if len(appended) >= n:
            break

        task_id = (
            event.get("article_url")
            or f"{event.get('article_title', '')}|{event.get('event_date', '')}"
        )
        if not task_id or task_id in existing_task_ids:
            continue

        training_event = {k: v for k, v in event.items() if not k.startswith("_")}
        new_ex = {
            "id": f"promoted_{next_id:02d}",
            "description": (
                f"Promoted from annotation — {event.get('event_type', 'unknown')}"
            ),
            "rationale": (
                "Auto-promoted from a Label Studio correction. "
                "Demonstrates the corrected extraction that the annotator "
                "agreed with. See provenance for traceability."
            ),
            "article_snippet": (event.get("_article_text", "")[:3000]).strip(),
            "extracted_events": [training_event],
            "provenance": {
                "source": "label_studio",
                "task_id": task_id,
                "annotator_id": event.get("_annotator_id"),
                "date_promoted": now,
                "type_corrected": bool(event.get("_type_corrected")),
                "had_extraction_errors": bool(event.get("_extraction_errors")),
            },
        }
        appended.append(new_ex)
        next_id += 1

    if not appended:
        log.info("All promotion candidates already present in examples file.")
        return 0

    # Dump the appended entries as YAML, then indent each line by 2 spaces so
    # they nest correctly under the top-level ``examples:`` key. safe_dump
    # emits each list item starting with ``- `` at column 0.
    snippet = yaml.safe_dump(
        appended,
        sort_keys=False,
        allow_unicode=True,
        width=120,
        default_flow_style=False,
    )
    indented = "\n".join(("  " + line) if line else "" for line in snippet.splitlines())

    # Append with a leading newline to guarantee separation from the
    # previous last example.
    with open(examples_path, "a", encoding="utf-8") as f:
        f.write("\n")
        f.write(indented)
        if not indented.endswith("\n"):
            f.write("\n")

    log.info(
        f"Promoted {len(appended)} example(s) to {examples_path} "
        f"(pool size: {len(existing_examples) + len(appended)})"
    )
    return len(appended)


def import_annotations(
    annotations_path: Path,
    output_dir: Path,
    promote_to_examples: int = 0,
    examples_path: Optional[Path] = None,
    upload_to: Optional[str] = None,
) -> dict:
    """
    Process a Label Studio export file and write output files.

    upload_to: optional cloud destination for the three output files.
      Accepts 's3://bucket/prefix' or 'abfss://filesystem/prefix'.
      Requires AZURE_STORAGE_CONNECTION_STRING (ADLS) or AWS credentials (S3).

    Returns a summary dict.
    """
    with open(annotations_path, encoding="utf-8") as f:
        tasks = json.load(f)
    log.info(f"Loaded {len(tasks)} tasks from {annotations_path}")

    output_dir.mkdir(parents=True, exist_ok=True)

    reviewed_events = []
    training_pairs = []
    stats = {
        "total_tasks": len(tasks),
        "skipped": 0,
        "genuine_protests": 0,
        "false_positives": 0,
        "type_corrected": 0,
        "with_errors": 0,
        "training_pairs": 0,
    }

    for task in tasks:
        event = process_task(task)
        if event is None:
            stats["skipped"] += 1
            continue

        reviewed_events.append(event)

        if event.get("_is_false_positive"):
            stats["false_positives"] += 1
        else:
            stats["genuine_protests"] += 1
            if event.get("_type_corrected"):
                stats["type_corrected"] += 1
            if event.get("_extraction_errors"):
                stats["with_errors"] += 1
            pair = build_training_pair(event)
            if pair:
                training_pairs.append(pair)
                stats["training_pairs"] += 1

    # Write reviewed events
    reviewed_path = output_dir / "reviewed_events.jsonl"
    with open(reviewed_path, "w", encoding="utf-8") as f:
        for e in reviewed_events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    # Write training data
    training_path = output_dir / "training_data.jsonl"
    with open(training_path, "w", encoding="utf-8") as f:
        for p in training_pairs:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    # Write stats
    stats_path = output_dir / "annotation_stats.json"
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

    # Upload to cloud storage before printing summary so any errors surface early
    if upload_to:
        try:
            from src.acquisition.storage import _upload_outputs

            _upload_outputs(upload_to, [reviewed_path, training_path, stats_path])
            log.info(f"Annotation outputs uploaded to {upload_to}")
            stats["uploaded_to"] = upload_to
        except Exception as exc:
            log.warning(f"Cloud upload failed (files saved locally): {exc}")

    # Console summary
    print("\n" + "=" * 55)
    print("ANNOTATION IMPORT SUMMARY")
    print("=" * 55)
    print(f"Tasks processed:     {stats['total_tasks']}")
    print(f"Skipped/cancelled:   {stats['skipped']}")
    print(f"Genuine protests:    {stats['genuine_protests']}")
    print(f"False positives:     {stats['false_positives']}")
    print(f"Type corrections:    {stats['type_corrected']}")
    print(f"Extraction errors:   {stats['with_errors']}")
    print(f"Training pairs:      {stats['training_pairs']}")
    fp_rate = stats["false_positives"] / max(
        stats["genuine_protests"] + stats["false_positives"], 1
    )
    print(f"False positive rate: {fp_rate:.1%}")
    print("\nOutputs:")
    print(f"  {reviewed_path}")
    print(f"  {training_path}")
    print(f"  {stats_path}")
    if upload_to:
        print(f"  → uploaded to {upload_to}")
    target = 200
    remaining = max(0, target - stats["training_pairs"])
    if remaining > 0:
        print(
            f"\nTraining data progress: {stats['training_pairs']}/{target} "
            f"pairs ({remaining} more needed before QLoRA fine-tuning)"
        )
    else:
        print(
            f"\n✓ {stats['training_pairs']} training pairs — ready for QLoRA fine-tuning"
        )

    # Close the loop: promote high-ranked corrections into the few-shot
    # examples file so the next extraction run actually benefits from them.
    if promote_to_examples > 0:
        target_path = examples_path or _DEFAULT_EXAMPLES_PATH
        n_promoted = promote_examples(reviewed_events, target_path, promote_to_examples)
        stats["promoted_to_examples"] = n_promoted
        print(f"\nExamples promoted: {n_promoted} → {target_path}")

    print("=" * 55 + "\n")

    return stats


if __name__ == "__main__":
    import logging as _logging

    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="Import Label Studio annotations into PEA training data"
    )
    parser.add_argument(
        "--annotations",
        required=True,
        help="Label Studio export JSON file",
    )
    parser.add_argument(
        "--output-dir",
        default="data/annotation",
        help="Directory for output files [default: data/annotation]",
    )
    parser.add_argument(
        "--promote-to-examples",
        type=int,
        default=0,
        metavar="N",
        help=(
            "After import, append up to N top-ranked annotator-corrected "
            "events to configs/extraction_examples.yaml as new few-shot "
            "entries (with provenance). Closes the active-learning loop so "
            "the next extraction run benefits from the corrections. "
            "Default 0 = off."
        ),
    )
    parser.add_argument(
        "--examples-path",
        default=None,
        help=(
            "Target YAML for --promote-to-examples. Defaults to "
            "configs/extraction_examples.yaml."
        ),
    )
    parser.add_argument(
        "--upload-to",
        default=None,
        metavar="DEST",
        help=(
            "Upload the three output files to cloud storage after writing. "
            "Accepts 'abfss://filesystem/prefix' (Azure ADLS Gen2, requires "
            "AZURE_STORAGE_CONNECTION_STRING) or 's3://bucket/prefix' (AWS S3)."
        ),
    )
    args = parser.parse_args()

    import_annotations(
        annotations_path=Path(args.annotations),
        output_dir=Path(args.output_dir),
        promote_to_examples=args.promote_to_examples,
        examples_path=Path(args.examples_path) if args.examples_path else None,
        upload_to=args.upload_to,
    )
