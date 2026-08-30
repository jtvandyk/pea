"""
Excluded-cases store — implementation plan §1.5 (RTV Excluded Cases pattern).

Articles that PASS the relevance filter but yield ZERO events from the LLM
extractor are recorded as a first-class output instead of vanishing into a
log line. The resulting JSONL is:

  1. an audit trail of what the codebook's disqualifiers / minimum criteria
     rejected at the extraction stage, and
  2. an accumulating pool of hard negatives (article text + empty label)
     for the QLoRA fine-tuning training set.

RTV (C-REX) publishes exactly this dataset alongside its coded events
(794 excluded cases as of 2022).

The record carries reason="llm_returned_empty" — the LLM's output contract
is an empty array with no explanation, so the specific failed criterion is
not recoverable today. Enriching the contract with a machine-readable
exclusion reason is part of the per-field-confidence architecture decision
(plan §4.2) and deliberately NOT done here.
"""

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

log = logging.getLogger("pea.excluded_store")

# Same truncation cap as the extractor's _article_text convention, so a
# hard-negative pair carries exactly the text the LLM saw.
_TEXT_CAP = 12000

_write_lock = threading.Lock()


def record_excluded_case(
    path: Union[str, Path],
    article: dict,
    domain: str = "protest",
    reason: str = "llm_returned_empty",
    run_id: Optional[str] = None,
) -> dict:
    """
    Append one excluded-case record to the JSONL store at ``path``.

    Thread-safe (extract_events runs concurrent workers). Creates parent
    directories on first write. Returns the record written.
    """
    text = article.get("text_en") or article.get("text") or ""
    record = {
        "url": article.get("url", ""),
        "title": article.get("title", ""),
        "domain": domain,
        "reason": reason,
        "relevance_score": article.get("_relevance_score"),
        "lang": article.get("text_lang", "unknown"),
        "source_country": article.get("sourcecountry", ""),
        "run_id": run_id,
        "excluded_at": datetime.utcnow().isoformat() + "Z",
        # Prefixed with _ to match the events convention: stripped from any
        # CSV/public export, kept in JSONL for training-pair construction.
        "_article_text": text[:_TEXT_CAP],
    }
    p = Path(path)
    with _write_lock:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def load_excluded_cases(path: Union[str, Path]) -> list:
    """Read all records from an excluded-cases JSONL file (missing file → [])."""
    p = Path(path)
    if not p.exists():
        return []
    records = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                log.warning(f"Skipping malformed excluded-case line in {p}")
    return records
