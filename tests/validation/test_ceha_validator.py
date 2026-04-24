"""Tests for src/validation/ceha_validator.py."""
import csv
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.validation.ceha_validator import (
    CEHA_TYPE_COLUMNS,
    CEHA_TYPE_SHORT,
    _events_to_articles,
    _normalise_ceha,
    compute_metrics,
    load_ceha,
    sweep_thresholds,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def make_ceha_row(
    index="IDX001",
    source="ACLED",
    time="2024-03-15",
    country="Sudan",
    actor1="Armed Group",
    actor2="Civilians",
    url="",
    text="Protesters clashed with police in Khartoum demanding political reform.",
    relevant="Yes",
    ethnic="",
    religious="",
    sgbv="",
    climate="",
    other="",
    split="test",
) -> dict:
    return {
        "Annotator": "A1",
        "ACLED/GDELT": source,
        "Index": index,
        "Time": time,
        "Country": country,
        "Actor 1": actor1,
        "Actor 2": actor2,
        "Article Url": url,
        "Event Description": text,
        "Is the event relevant?": relevant,
        "Why is the event NOT relevant? \n(if applicable)": "",
        "tribal/communal/ethnic conflict": ethnic,
        "religious conflict": religious,
        "socio-political violence against women": sgbv,
        "climate-related security risks": climate,
        "Other": other,
        "train_dev_test_split": split,
    }


@pytest.fixture()
def ceha_csv(tmp_path) -> Path:
    """Write a minimal CEHA CSV with 4 rows covering 2 relevant / 2 not relevant."""
    path = tmp_path / "CEHA_dataset.csv"
    rows = [
        make_ceha_row(index="T001", relevant="Yes", ethnic="X", split="test"),
        make_ceha_row(index="T002", relevant="No",  split="test",
                      text="A football match was played in Nairobi."),
        make_ceha_row(index="T003", relevant="Yes", sgbv="X",  split="test",
                      text="A woman was attacked in Juba."),
        make_ceha_row(index="T004", relevant="No",  split="dev",
                      text="Agricultural yields fell in Kenya."),
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


# ---------------------------------------------------------------------------
# _normalise_ceha
# ---------------------------------------------------------------------------

class TestNormaliseCeha:
    def test_relevant_yes(self):
        row = make_ceha_row(relevant="Yes")
        e = _normalise_ceha(row)
        assert e["relevant"] is True

    def test_relevant_no(self):
        row = make_ceha_row(relevant="No")
        e = _normalise_ceha(row)
        assert e["relevant"] is False

    def test_event_types_extracted(self):
        row = make_ceha_row(ethnic="X", religious="X")
        e = _normalise_ceha(row)
        assert "ethnic_communal" in e["event_types"]
        assert "religious" in e["event_types"]

    def test_no_event_types_when_not_marked(self):
        row = make_ceha_row()
        e = _normalise_ceha(row)
        assert e["event_types"] == []

    def test_all_fields_present(self):
        row = make_ceha_row()
        e = _normalise_ceha(row)
        for key in ("index", "source", "time", "country", "text", "relevant",
                    "event_types", "split", "raw"):
            assert key in e

    def test_raw_preserves_original(self):
        row = make_ceha_row(index="X99")
        e = _normalise_ceha(row)
        assert e["raw"]["Index"] == "X99"

    def test_x_case_insensitive(self):
        row = make_ceha_row()
        row["tribal/communal/ethnic conflict"] = "x"
        e = _normalise_ceha(row)
        assert "ethnic_communal" in e["event_types"]


# ---------------------------------------------------------------------------
# load_ceha
# ---------------------------------------------------------------------------

class TestLoadCeha:
    def test_loads_test_split(self, ceha_csv):
        events = load_ceha(ceha_csv, split="test")
        assert len(events) == 3  # T001, T002, T003

    def test_loads_dev_split(self, ceha_csv):
        events = load_ceha(ceha_csv, split="dev")
        assert len(events) == 1

    def test_loads_all(self, ceha_csv):
        events = load_ceha(ceha_csv, split="all")
        assert len(events) == 4

    def test_loads_all_with_none(self, ceha_csv):
        events = load_ceha(ceha_csv, split=None)
        assert len(events) == 4

    def test_returns_normalised_dicts(self, ceha_csv):
        events = load_ceha(ceha_csv, split="test")
        assert all("relevant" in e for e in events)
        assert all("text" in e for e in events)


# ---------------------------------------------------------------------------
# _events_to_articles
# ---------------------------------------------------------------------------

class TestEventsToArticles:
    def test_creates_article_dicts(self):
        events = [_normalise_ceha(make_ceha_row(index="A1", text="Some text"))]
        articles = _events_to_articles(events)
        assert len(articles) == 1
        assert articles[0]["text"] == "Some text"
        assert articles[0]["_ceha_index"] == "A1"

    def test_title_is_empty_string(self):
        events = [_normalise_ceha(make_ceha_row())]
        articles = _events_to_articles(events)
        assert articles[0]["title"] == ""


# ---------------------------------------------------------------------------
# compute_metrics
# ---------------------------------------------------------------------------

class TestComputeMetrics:
    def _make_scored_event(self, relevant: bool, predicted: bool, country="Sudan",
                           source="ACLED", event_types=None):
        row = make_ceha_row(
            relevant="Yes" if relevant else "No",
            source=source,
            country=country,
            ethnic="X" if event_types and "ethnic_communal" in event_types else "",
        )
        e = _normalise_ceha(row)
        e["_relevance_score"]    = 0.8 if predicted else 0.1
        e["_relevance_source"]   = "model"
        e["_predicted_relevant"] = predicted
        return e

    def test_perfect_classifier(self):
        events = [
            self._make_scored_event(True, True),
            self._make_scored_event(False, False),
        ]
        m = compute_metrics(events)
        assert m["precision"] == 1.0
        assert m["recall"] == 1.0
        assert m["f1"] == 1.0

    def test_all_predicted_relevant(self):
        events = [
            self._make_scored_event(True, True),
            self._make_scored_event(False, True),
        ]
        m = compute_metrics(events)
        assert m["recall"] == 1.0
        assert m["precision"] == 0.5

    def test_none_predicted_relevant(self):
        events = [
            self._make_scored_event(True, False),
            self._make_scored_event(False, False),
        ]
        m = compute_metrics(events)
        assert m["recall"] == 0.0
        assert m["f1"] == 0.0

    def test_by_country_breakdown(self):
        events = [
            self._make_scored_event(True, True, country="Sudan"),
            self._make_scored_event(True, False, country="Ethiopia"),
        ]
        m = compute_metrics(events)
        assert "Sudan" in m["by_country"]
        assert "Ethiopia" in m["by_country"]
        assert m["by_country"]["Sudan"]["recall"] == 1.0
        assert m["by_country"]["Ethiopia"]["recall"] == 0.0

    def test_by_source_breakdown(self):
        events = [
            self._make_scored_event(True, True, source="ACLED"),
            self._make_scored_event(True, False, source="GDELT"),
        ]
        m = compute_metrics(events)
        assert "ACLED" in m["by_source"]
        assert "GDELT" in m["by_source"]

    def test_by_type_only_counts_relevant_events(self):
        events = [
            self._make_scored_event(True, True, event_types=["ethnic_communal"]),
            self._make_scored_event(False, False),  # not relevant, should not affect by_type
        ]
        m = compute_metrics(events)
        assert "ethnic_communal" in m["by_type"]
        assert m["by_type"]["ethnic_communal"]["total"] == 1

    def test_no_division_error_on_empty(self):
        m = compute_metrics([])
        assert m["f1"] == 0.0
        assert m["total"] == 0


# ---------------------------------------------------------------------------
# sweep_thresholds
# ---------------------------------------------------------------------------

class TestSweepThresholds:
    def _make_event(self, relevant: bool, score: float):
        row = make_ceha_row(relevant="Yes" if relevant else "No")
        e = _normalise_ceha(row)
        e["_relevance_score"]    = score
        e["_relevance_source"]   = "model"
        e["_predicted_relevant"] = score >= 0.30
        return e

    def test_returns_list_of_results(self):
        events = [self._make_event(True, 0.8), self._make_event(False, 0.1)]
        results = sweep_thresholds(events, thresholds=[0.1, 0.5, 0.9])
        assert len(results) == 3
        for r in results:
            assert "threshold" in r
            assert "f1" in r
            assert "precision" in r
            assert "recall" in r

    def test_higher_threshold_lower_recall(self):
        events = [self._make_event(True, 0.4), self._make_event(False, 0.1)]
        r_low  = sweep_thresholds(events, thresholds=[0.2])
        r_high = sweep_thresholds(events, thresholds=[0.9])
        assert r_low[0]["recall"] >= r_high[0]["recall"]


# ---------------------------------------------------------------------------
# score_with_filter (integration — mocked)
# ---------------------------------------------------------------------------

class TestScoreWithFilter:
    def test_scores_attached_to_events(self, ceha_csv):
        from src.validation.ceha_validator import score_with_filter

        events = load_ceha(ceha_csv, split="test")

        # Patch RelevanceFilter to avoid model download
        mock_filter = MagicMock()
        kept = [{"text": e["text"], "title": "", "_ceha_index": e["index"],
                 "_relevance_score": 0.8, "_relevance_source": "model"}
                for e in events[:2]]
        rejected = [{"text": e["text"], "title": "", "_ceha_index": e["index"],
                     "_relevance_score": 0.1, "_relevance_source": "model"}
                    for e in events[2:]]
        mock_filter.return_value.filter.return_value = (kept, rejected)

        with patch("src.acquisition.relevance_filter.RelevanceFilter", mock_filter):
            scored = score_with_filter(events, threshold=0.30)

        assert all("_relevance_score" in e for e in scored)
        assert all("_predicted_relevant" in e for e in scored)
