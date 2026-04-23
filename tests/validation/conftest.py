"""Shared helpers for glocon_validator tests."""
import csv
import json

import pytest
from pathlib import Path


def make_glocon_raw(
    date="2024-03-15",
    location="Johannesburg",
    country="South Africa",
    event_type="protest",
    description="Workers marched outside parliament demanding wage increases.",
) -> dict:
    """Return a raw GLOCON row dict as it would come from JSON/CSV."""
    return {
        "event_date": date,
        "location": location,
        "country": country,
        "event_type": event_type,
        "description": description,
    }


def make_pea_event(
    date="2024-03-15",
    country="South Africa",
    city="Johannesburg",
    event_type="demonstration_march",
    url="http://example.com/article/1",
    confidence="high",
) -> dict:
    return {
        "event_date": date,
        "country": country,
        "city": city,
        "event_type": event_type,
        "article_url": url,
        "confidence": confidence,
    }


@pytest.fixture()
def tmp_glocon_dir(tmp_path) -> Path:
    """Temp directory with one JSON array file and one CSV GLOCON file."""
    json_events = [make_glocon_raw(location="Cape Town", event_type="strike")]
    (tmp_path / "events.json").write_text(
        json.dumps(json_events), encoding="utf-8"
    )
    csv_path = tmp_path / "events2.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["event_date", "location", "country", "event_type", "description"],
        )
        writer.writeheader()
        writer.writerow(make_glocon_raw(location="Durban", event_type="riot"))
    return tmp_path
