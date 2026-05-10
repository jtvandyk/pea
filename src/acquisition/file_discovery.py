"""
File/ADLS input discovery source.

Reads pre-scraped articles from a local CSV/JSONL file or an ADLS Gen2 path
(abfss://filesystem/path/to/file.csv). Required columns: url, title, text, date, country.

Since text is pre-populated, the scraper stage skips these articles automatically
(scraper.py already checks `if article.get("text")` and skips if truthy).
"""

import io
import logging
import os
from typing import Optional

from src.utils import extract_domain, format_seendate

log = logging.getLogger(__name__)

_REQUIRED_COLUMNS = {"url", "title", "text", "date", "country"}


def _read_local(path: str):
    import pandas as pd

    lower = path.lower()
    if lower.endswith(".jsonl"):
        return pd.read_json(path, lines=True)
    if lower.endswith(".json"):
        return pd.read_json(path)
    return pd.read_csv(path)


def _read_adls(path: str):
    """Read from abfss://filesystem/remote/path using DataLakeFileClient."""
    import pandas as pd

    try:
        from azure.storage.file_datalake import DataLakeServiceClient
        from azure.identity import DefaultAzureCredential
    except ImportError:
        raise ImportError(
            "azure-storage-file-datalake is required: "
            "pip install azure-storage-file-datalake"
        )

    without_scheme = path[len("abfss://") :]
    filesystem, _, file_path = without_scheme.partition("/")

    account_url = os.environ.get("AZURE_STORAGE_ACCOUNT_URL")
    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")

    if account_url:
        client = DataLakeServiceClient(account_url, credential=DefaultAzureCredential())
    elif conn_str:
        client = DataLakeServiceClient.from_connection_string(conn_str)
    else:
        raise RuntimeError(
            "Set AZURE_STORAGE_ACCOUNT_URL or AZURE_STORAGE_CONNECTION_STRING "
            "to read from ADLS Gen2"
        )

    file_client = client.get_file_system_client(filesystem).get_file_client(file_path)
    data = file_client.download_file().readall()

    lower = file_path.lower()
    if lower.endswith(".jsonl"):
        return pd.read_json(io.BytesIO(data), lines=True)
    if lower.endswith(".json"):
        return pd.read_json(io.BytesIO(data))
    return pd.read_csv(io.BytesIO(data))


def discover_articles_from_file(
    path: str,
    countries: Optional[list] = None,
) -> list:
    """
    Load pre-scraped articles from a local or ADLS Gen2 file.

    Args:
        path: Local path or abfss://filesystem/path/to/file.{csv,json,jsonl}
        countries: If provided, only rows matching these ISO2 codes are returned.

    Returns:
        List of article dicts with text pre-populated so the scraper skips them.
    """
    import pandas as pd

    log.info(f"Loading articles from file: {path}")

    try:
        df = _read_adls(path) if path.startswith("abfss://") else _read_local(path)
    except Exception as exc:
        log.error(f"Failed to read file '{path}': {exc}")
        return []

    missing = _REQUIRED_COLUMNS - set(df.columns)
    if missing:
        log.error(
            f"File '{path}' is missing required columns: {missing}. "
            f"Required: {_REQUIRED_COLUMNS}"
        )
        return []

    if countries:
        before = len(df)
        df = df[df["country"].str.upper().isin([c.upper() for c in countries])]
        log.info(f"Country filter ({countries}): {len(df)}/{before} rows retained")

    if df.empty:
        log.warning("No articles after country filter — check country codes in file.")
        return []

    extra_cols = [
        c
        for c in df.columns
        if c not in _REQUIRED_COLUMNS and not str(c).startswith("_")
    ]

    articles = []
    for _, row in df.iterrows():
        url = str(row["url"])

        article = {
            "url": url,
            "title": str(row["title"]),
            "text": str(row["text"]) if pd.notna(row["text"]) else None,
            "seendate": format_seendate(str(row["date"])),
            "sourcecountry": str(row["country"]).upper(),
            "sourcelanguage": (
                str(row["language"])
                if "language" in df.columns and pd.notna(row.get("language"))
                else "en"
            ),
            "domain": "",
            "_relevance": None,
            "text_lang": None,
            "text_en": None,
            "events": [],
        }

        article["domain"] = extract_domain(url)

        for col in extra_cols:
            article[f"_file_{col}"] = row[col]

        articles.append(article)

    log.info(f"Loaded {len(articles)} articles from '{path}'")
    return articles
