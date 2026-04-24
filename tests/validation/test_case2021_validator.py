"""Tests for src/validation/case2021_validator.py."""
import csv
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.validation.case2021_validator import (
    CASE_TO_PEA,
    PROTEST_SUBTYPES,
    _compute_extraction_metrics,
    _compute_relevance_metrics,
    _events_to_articles,
    _normalise_case,
    load_case2021,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def make_case_row(id="1", text="Protesters marched through the capital.", sub_type="PEACE_PROTEST") -> dict:
    return {"id": id, "EventSnippet": text, "SubType": sub_type}


@pytest.fixture()
def case_tsv(tmp_path) -> Path:
    """Write a minimal CASE TSV with protest and non-protest rows."""
    path = tmp_path / "test_set.tsv"
    rows = [
        make_case_row("1", "Protesters marched through the capital.", "PEACE_PROTEST"),
        make_case_row("2", "Rioters attacked police vehicles.", "VIOL_DEMONSTR"),
        make_case_row("3", "Police used force against demonstrators.", "FORCE_AGAINST_PROTEST"),
        make_case_row("4", "Warplanes bombed a village.", "AIR_STRIKE"),
        make_case_row("5", "A flood destroyed crops.", "NATURAL_DISASTER"),
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "EventSnippet", "SubType"], delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    return path


# ---------------------------------------------------------------------------
# _normalise_case
# ---------------------------------------------------------------------------

class TestNormaliseCase:
    def test_protest_subtype_marked(self):
        row = make_case_row(sub_type="PEACE_PROTEST")
        e = _normalise_case(row)
        assert e["is_protest"] is True

    def test_non_protest_subtype_marked(self):
        row = make_case_row(sub_type="AIR_STRIKE")
        e = _normalise_case(row)
        assert e["is_protest"] is False

    def test_pea_gold_set_for_protest(self):
        row = make_case_row(sub_type="PEACE_PROTEST")
        e = _normalise_case(row)
        assert e["pea_gold"] == "demonstration_march"

    def test_pea_gold_none_for_non_protest(self):
        row = make_case_row(sub_type="AIR_STRIKE")
        e = _normalise_case(row)
        assert e["pea_gold"] is None

    def test_all_protest_subtypes_have_pea_gold(self):
        for sub_type in PROTEST_SUBTYPES:
            row = make_case_row(sub_type=sub_type)
            e = _normalise_case(row)
            assert e["pea_gold"] is not None, f"No PEA gold for {sub_type}"

    def test_all_fields_present(self):
        e = _normalise_case(make_case_row())
        for key in ("id", "text", "sub_type", "is_protest", "pea_gold", "raw"):
            assert key in e

    def test_raw_preserved(self):
        row = make_case_row(id="X42")
        e = _normalise_case(row)
        assert e["raw"]["id"] == "X42"


# ---------------------------------------------------------------------------
# CASE_TO_PEA crosswalk completeness
# ---------------------------------------------------------------------------

class TestCaseToPeaCrosswalk:
    def test_all_protest_subtypes_in_crosswalk(self):
        for sub_type in PROTEST_SUBTYPES:
            assert sub_type in CASE_TO_PEA, f"{sub_type} not in CASE_TO_PEA"

    def test_crosswalk_values_are_valid_pea_types(self):
        valid = {
            "demonstration_march", "strike_boycott", "riot", "occupation_seizure",
            "confrontation", "petition_signature", "vigil", "hunger_strike",
        }
        for sub_type, pea_type in CASE_TO_PEA.items():
            assert pea_type in valid, f"{sub_type} → {pea_type} is not a valid PEA type"


# ---------------------------------------------------------------------------
# load_case2021
# ---------------------------------------------------------------------------

class TestLoadCase2021:
    def test_loads_all_rows(self, case_tsv):
        events = load_case2021(case_tsv)
        assert len(events) == 5

    def test_protest_events_marked(self, case_tsv):
        events = load_case2021(case_tsv)
        protest = [e for e in events if e["is_protest"]]
        assert len(protest) == 3  # PEACE_PROTEST, VIOL_DEMONSTR, FORCE_AGAINST_PROTEST

    def test_non_protest_events_marked(self, case_tsv):
        events = load_case2021(case_tsv)
        non_protest = [e for e in events if not e["is_protest"]]
        assert len(non_protest) == 2  # AIR_STRIKE, NATURAL_DISASTER


# ---------------------------------------------------------------------------
# _events_to_articles
# ---------------------------------------------------------------------------

class TestEventsToArticles:
    def test_creates_article_dicts(self):
        events = [_normalise_case(make_case_row(id="5", text="Crowd gathered."))]
        articles = _events_to_articles(events)
        assert len(articles) == 1
        assert articles[0]["text"] == "Crowd gathered."
        assert articles[0]["_case_id"] == "5"

    def test_title_is_empty(self):
        events = [_normalise_case(make_case_row())]
        articles = _events_to_articles(events)
        assert articles[0]["title"] == ""


# ---------------------------------------------------------------------------
# _compute_relevance_metrics
# ---------------------------------------------------------------------------

class TestComputeRelevanceMetrics:
    def _make_event(self, is_protest: bool, predicted: bool, sub_type: str = None):
        if sub_type is None:
            sub_type = "PEACE_PROTEST" if is_protest else "AIR_STRIKE"
        e = _normalise_case(make_case_row(sub_type=sub_type))
        e["_relevance_score"]    = 0.8 if predicted else 0.1
        e["_relevance_source"]   = "model"
        e["_predicted_protest"]  = predicted
        return e

    def test_perfect_classifier(self):
        events = [self._make_event(True, True), self._make_event(False, False)]
        m = _compute_relevance_metrics(events, threshold=0.30)
        assert m["f1"] == 1.0
        assert m["precision"] == 1.0
        assert m["recall"] == 1.0

    def test_no_protest_predicted(self):
        events = [self._make_event(True, False), self._make_event(False, False)]
        m = _compute_relevance_metrics(events, threshold=0.30)
        assert m["recall"] == 0.0
        assert m["f1"] == 0.0

    def test_all_predicted_protest(self):
        events = [self._make_event(True, True), self._make_event(False, True)]
        m = _compute_relevance_metrics(events, threshold=0.30)
        assert m["recall"] == 1.0
        assert m["precision"] == 0.5

    def test_by_subtype_breakdown(self):
        events = [
            self._make_event(True, True, "PEACE_PROTEST"),
            self._make_event(True, False, "VIOL_DEMONSTR"),
        ]
        m = _compute_relevance_metrics(events, threshold=0.30)
        assert "PEACE_PROTEST" in m["by_subtype"]
        assert "VIOL_DEMONSTR" in m["by_subtype"]
        assert m["by_subtype"]["PEACE_PROTEST"]["recall"] == 1.0
        assert m["by_subtype"]["VIOL_DEMONSTR"]["recall"] == 0.0

    def test_mode_key_is_relevance(self):
        m = _compute_relevance_metrics([], threshold=0.30)
        assert m["mode"] == "relevance"

    def test_no_division_error_on_empty(self):
        m = _compute_relevance_metrics([], threshold=0.30)
        assert m["f1"] == 0.0


# ---------------------------------------------------------------------------
# _compute_extraction_metrics
# ---------------------------------------------------------------------------

class TestComputeExtractionMetrics:
    def _make_result(self, pea_gold: str, pea_predicted: str, sub_type: str = "PEACE_PROTEST"):
        return {
            "id":            "1",
            "text_preview":  "...",
            "sub_type":      sub_type,
            "pea_gold":      pea_gold,
            "pea_predicted": pea_predicted,
            "correct":       pea_predicted == pea_gold,
        }

    def test_all_correct(self):
        results = [
            self._make_result("demonstration_march", "demonstration_march"),
            self._make_result("riot", "riot", "VIOL_DEMONSTR"),
        ]
        m = _compute_extraction_metrics(results)
        assert m["accuracy"] == 1.0
        assert m["correct"] == 2

    def test_none_correct(self):
        results = [
            self._make_result("demonstration_march", "riot"),
        ]
        m = _compute_extraction_metrics(results)
        assert m["accuracy"] == 0.0

    def test_by_pea_gold_breakdown(self):
        results = [
            self._make_result("demonstration_march", "demonstration_march"),
            self._make_result("riot", "demonstration_march", "VIOL_DEMONSTR"),
        ]
        m = _compute_extraction_metrics(results)
        assert "demonstration_march" in m["by_pea_gold"]
        assert "riot" in m["by_pea_gold"]
        assert m["by_pea_gold"]["demonstration_march"]["accuracy"] == 1.0
        assert m["by_pea_gold"]["riot"]["accuracy"] == 0.0

    def test_mode_key_is_extraction(self):
        m = _compute_extraction_metrics([])
        assert m["mode"] == "extraction"


# ---------------------------------------------------------------------------
# run_relevance_mode (integration — mocked)
# ---------------------------------------------------------------------------

class TestRunRelevanceModeIntegration:
    def test_scores_attached_and_metrics_returned(self, case_tsv):
        from src.validation.case2021_validator import run_relevance_mode

        events = load_case2021(case_tsv)

        mock_filter = MagicMock()
        protest_ids = {e["id"] for e in events if e["is_protest"]}
        kept = [{"text": e["text"], "title": "", "_case_id": e["id"],
                 "_relevance_score": 0.8, "_relevance_source": "model"}
                for e in events if e["id"] in protest_ids]
        rejected = [{"text": e["text"], "title": "", "_case_id": e["id"],
                     "_relevance_score": 0.1, "_relevance_source": "model"}
                    for e in events if e["id"] not in protest_ids]
        mock_filter.return_value.filter.return_value = (kept, rejected)

        with patch("src.acquisition.relevance_filter.RelevanceFilter", mock_filter):
            metrics = run_relevance_mode(events, threshold=0.30)

        assert "f1" in metrics
        assert "precision" in metrics
        assert "recall" in metrics
        assert metrics["recall"] == 1.0   # all protest events were "kept"
        assert metrics["precision"] == 1.0
