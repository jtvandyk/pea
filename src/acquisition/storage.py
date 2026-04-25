"""
Storage Module
==============
Saves extracted protest events to:
  1. A JSONL file (one event per line) — ideal for streaming/appending
  2. A CSV file — for easy viewing in Excel/Sheets
  3. A run summary JSON — metadata about the pipeline run
  4. A cumulative all_events.jsonl across runs
"""

import csv
import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from azure.storage.file_datalake import DataLakeServiceClient

from src.metrics import count_by

log = logging.getLogger(__name__)

# Protects the cumulative all_events.jsonl append when extract_events() uses
# multiple worker threads and save_results() is called concurrently.
_cumulative_lock = threading.Lock()

# CSV columns in display order
CSV_COLUMNS = [
    "event_date",
    "country",
    "city",
    "region",
    "venue",
    "location_notes",
    "latitude",
    "longitude",
    "geo_accuracy",
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

# State responses ranked by severity (highest first).
# Mirrors state_response_vocabulary in configs/protest_codebook.yaml v2.3.
# Update both if the codebook adds new values.
_HIGH_TURMOIL_RESPONSES = {
    "live_ammunition",
    "rubber_bullets",
    "legal_criminalisation",
    "anti_terrorism_designation",
    "organisational_dissolution",
}
_MEDIUM_TURMOIL_RESPONSES = {
    "teargas",
    "water_cannon",
    "dispersal",
    "arrests",
    "ban",
    "curfew",
    "non_association_bail",
}


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


def _az_client(conn_str: Optional[str] = None) -> "DataLakeServiceClient":
    """Return a DataLakeServiceClient using managed identity or a connection string.

    Managed identity (Container Apps): set AZURE_STORAGE_ACCOUNT_URL to the
    DFS endpoint, e.g. https://<account>.dfs.core.windows.net.
    Local dev: set AZURE_STORAGE_CONNECTION_STRING (or pass conn_str directly).
    """
    try:
        from azure.storage.file_datalake import DataLakeServiceClient
    except ImportError:
        raise ImportError(
            "azure-storage-file-datalake is required: "
            "pip install azure-storage-file-datalake"
        )
    account_url = os.environ.get("AZURE_STORAGE_ACCOUNT_URL")
    if account_url:
        from azure.identity import DefaultAzureCredential

        return DataLakeServiceClient(account_url, credential=DefaultAzureCredential())
    if conn_str:
        return DataLakeServiceClient.from_connection_string(conn_str)
    raise RuntimeError(
        "Set AZURE_STORAGE_ACCOUNT_URL (managed identity, DFS endpoint) "
        "or AZURE_STORAGE_CONNECTION_STRING (local dev)"
    )


def sync_checkpoint_from_adls(upload_to: str, output_dir: Path) -> bool:
    """
    Download checkpoint.txt from ADLS Gen2 to output_dir before a --resume run.
    Returns True if a checkpoint was found and downloaded, False otherwise.
    Only operates on abfss:// destinations; no-op for s3://.
    """
    if not upload_to.startswith("abfss://"):
        return False
    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    filesystem, prefix = upload_to[8:].split("/", 1)
    file_path = f"{prefix}/checkpoint.txt"
    try:
        client = _az_client(conn_str)
        file_client = client.get_file_system_client(filesystem).get_file_client(
            file_path
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        local_path = output_dir / "checkpoint.txt"
        with open(local_path, "wb") as f:
            f.write(file_client.download_file().readall())
        lines = len(local_path.read_text().splitlines())
        log.info(f"Resumed checkpoint from ADLS ({lines} URLs already processed)")
        return True
    except Exception as e:
        if "PathNotFound" in str(e) or "404" in str(e):
            log.info("No checkpoint found in ADLS — starting fresh")
        else:
            log.warning(f"Could not sync checkpoint from ADLS: {e}")
        return False


# Backward-compatible alias
sync_checkpoint_from_blob = sync_checkpoint_from_adls


def upload_checkpoint(upload_to: str, output_dir: Path) -> None:
    """Upload checkpoint.txt to ADLS Gen2 (called periodically during a run)."""
    if not upload_to.startswith("abfss://"):
        return
    cp = output_dir / "checkpoint.txt"
    if not cp.exists():
        return
    try:
        _upload_outputs(upload_to, [cp])
    except Exception as e:
        log.warning(f"Checkpoint upload failed (non-fatal): {e}")


def _upload_outputs(destination: str, paths: list[Path]) -> None:
    """
    Upload a list of local files to cloud storage.

    destination format:
      's3://bucket/prefix'        — AWS S3 (requires boto3, AWS credentials in env)
      'abfss://filesystem/prefix' — Azure Data Lake Storage Gen2
                                    (requires azure-storage-file-datalake,
                                     AZURE_STORAGE_CONNECTION_STRING in env)
    """
    if destination.startswith("s3://"):
        try:
            import boto3
        except ImportError:
            raise ImportError("boto3 is required for S3 upload: pip install boto3")
        bucket, prefix = destination[5:].split("/", 1)
        s3 = boto3.client("s3")
        for p in paths:
            key = f"{prefix}/{p.name}"
            s3.upload_file(str(p), bucket, key)
            log.info(f"Uploaded to s3://{bucket}/{key}")

    elif destination.startswith("abfss://"):
        conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        filesystem, prefix = destination[8:].split("/", 1)
        client = _az_client(conn_str)
        fs_client = client.get_file_system_client(filesystem)
        for p in paths:
            file_path = f"{prefix}/{p.name}"
            file_client = fs_client.get_file_client(file_path)
            with open(p, "rb") as f:
                file_client.upload_data(f.read(), overwrite=True)
            log.info(f"Uploaded to abfss://{filesystem}/{file_path}")

    else:
        raise ValueError(
            f"Unsupported upload destination '{destination}'. "
            "Use 's3://bucket/prefix' or 'abfss://filesystem/prefix'."
        )


def save_results(
    events: list[dict],
    output_dir: Path,
    run_id: str,
    failures: Optional[list] = None,
    upload_to: Optional[str] = None,
    domain: str = "protest",
) -> Path:
    """
    Save events to JSONL, CSV, and a run summary file.

    domain: output subdirectory (e.g. 'protest', 'drone'). Files go to
    output_dir/domain/ so multiple codebook runs never collide.

    If failures are provided, writes them to failures_{run_id}.jsonl.
    If upload_to is set, uploads all output files to S3 or Azure Blob after writing.

    Derives turmoil_level for each event before writing.
    Returns the effective output directory (output_dir/domain/).
    """
    if not events:
        log.warning("No events to save.")
        return output_dir / domain

    output_dir = output_dir / domain
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

    # 3. Also append to a cumulative all_events.jsonl for long-running use.
    # Lock protects concurrent appends when multiple domains run in one process.
    cumulative_path = output_dir / "all_events.jsonl"
    with _cumulative_lock:
        with open(cumulative_path, "a", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
    log.info(f"Appended to cumulative: {cumulative_path}")

    # 4. Dead-letter file for failed extractions
    failures_path = None
    if failures:
        failures_path = output_dir / f"failures_{run_id}.jsonl"
        with open(failures_path, "w", encoding="utf-8") as f:
            for failure in failures:
                f.write(json.dumps(failure, ensure_ascii=False) + "\n")
        log.warning(f"Failures written: {failures_path} ({len(failures)} articles)")

    # 5. Run summary
    summary = {
        "run_id": run_id,
        "timestamp": datetime.utcnow().isoformat(),
        "total_events": len(events),
        "total_failures": len(failures) if failures else 0,
        "events_by_country": count_by(events, "country"),
        "events_by_type": count_by(events, "event_type"),
        "events_by_state_response": count_by(events, "state_response"),
        "events_by_turmoil_level": count_by(events, "turmoil_level"),
        "events_by_confidence": count_by(events, "confidence"),
        "output_files": {
            "jsonl": str(jsonl_path),
            "csv": str(csv_path),
            "cumulative_jsonl": str(cumulative_path),
            **({"failures_jsonl": str(failures_path)} if failures_path else {}),
        },
    }
    summary_path = output_dir / f"summary_{run_id}.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    by_country = "  " + "\n  ".join(
        f"{c:<30s} {n}"
        for c, n in sorted(summary["events_by_country"].items(), key=lambda x: -x[1])
    )
    by_type = "  " + "\n  ".join(
        f"{t:<30s} {n}"
        for t, n in sorted(summary["events_by_type"].items(), key=lambda x: -x[1])
    )
    by_turmoil = "  " + "\n  ".join(
        f"{lv:<30s} {n}"
        for lv, n in sorted(
            summary["events_by_turmoil_level"].items(), key=lambda x: -x[1]
        )
    )
    log.info(
        f"RUN SUMMARY — {run_id}\n"
        f"Total events extracted: {len(events)}\n"
        f"By country:\n{by_country}\n"
        f"By event type:\n{by_type}\n"
        f"By turmoil level:\n{by_turmoil}\n"
        f"Output: {output_dir}"
    )

    # Upload to cloud storage if requested
    if upload_to:
        upload_paths = [jsonl_path, csv_path, cumulative_path, summary_path]
        if failures_path:
            upload_paths.append(failures_path)
        checkpoint_path = output_dir / "checkpoint.txt"
        if checkpoint_path.exists():
            upload_paths.append(checkpoint_path)
        log.info(f"Uploading {len(upload_paths)} files to {upload_to} ...")
        try:
            _upload_outputs(upload_to, upload_paths)
            log.info("Cloud upload complete")
        except Exception as e:
            log.warning(f"Cloud upload failed (results saved locally): {e}")

    return output_dir
