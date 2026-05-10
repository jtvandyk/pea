"""Unit tests for src/acquisition/processing.py."""

import pytest
from datetime import datetime
from src.acquisition.processing import (
    _parse_event_date,
    _fuzzy_match,
    _are_duplicates,
    deduplicate,
    filter_to_target_countries,
)


# ── _parse_event_date ────────────────────────────────────────────────────────


class TestParseEventDate:
    def test_iso_full_date(self):
        assert _parse_event_date("2024-03-15") == datetime(2024, 3, 15)

    def test_compact_date(self):
        assert _parse_event_date("20240315") == datetime(2024, 3, 15)

    def test_none_returns_none(self):
        assert _parse_event_date(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_event_date("") is None

    def test_partial_year_month_rejected(self):
        # "2025-03" must NOT silently become 2025-03-01
        assert _parse_event_date("2025-03") is None

    def test_year_only_rejected(self):
        assert _parse_event_date("2025") is None

    def test_garbage_returns_none(self):
        assert _parse_event_date("not-a-date") is None

    def test_with_time_suffix_rejected(self):
        # Extra chars after YYYY-MM-DD should not match
        assert _parse_event_date("2024-03-15T10:00:00") is None


# ── _fuzzy_match ─────────────────────────────────────────────────────────────


class TestFuzzyMatch:
    def test_identical(self):
        assert _fuzzy_match("Lagos", "Lagos") is True

    def test_case_insensitive(self):
        assert _fuzzy_match("Lagos", "lagos") is True

    def test_similar_enough(self):
        assert _fuzzy_match("Johannesburg", "Johnnesburg") is True

    def test_different_cities(self):
        assert _fuzzy_match("Lagos", "Abuja") is False

    def test_empty_a_returns_false(self):
        assert _fuzzy_match("", "Lagos") is False

    def test_empty_b_returns_false(self):
        assert _fuzzy_match("Lagos", "") is False

    def test_both_empty_returns_false(self):
        assert _fuzzy_match("", "") is False


# ── _are_duplicates ───────────────────────────────────────────────────────────


def _event(
    country="nigeria",
    event_type="demonstration_march",
    event_date="2024-03-15",
    city="Lagos",
    claims=None,
):
    return {
        "country": country,
        "event_type": event_type,
        "event_date": event_date,
        "city": city,
        "claims": claims or ["workers demand wage increase"],
    }


class TestAreDuplicates:
    def test_identical_events_are_duplicates(self):
        a = _event()
        b = _event()
        assert _are_duplicates(a, b) is True

    def test_different_country_not_duplicate(self):
        a = _event(country="nigeria")
        b = _event(country="south africa")
        assert _are_duplicates(a, b) is False

    def test_different_event_type_not_duplicate(self):
        a = _event(event_type="demonstration_march")
        b = _event(event_type="strike_boycott")
        assert _are_duplicates(a, b) is False

    def test_date_within_window_is_duplicate(self):
        a = _event(event_date="2024-03-15")
        b = _event(event_date="2024-03-17")  # 2 days apart
        assert _are_duplicates(a, b) is True

    def test_date_outside_window_not_duplicate(self):
        a = _event(event_date="2024-03-15")
        b = _event(event_date="2024-03-19")  # 4 days apart
        assert _are_duplicates(a, b) is False

    def test_different_city_not_duplicate(self):
        a = _event(city="Lagos")
        b = _event(city="Kano")
        assert _are_duplicates(a, b) is False

    def test_null_city_skips_city_gate(self):
        # When either city is null, city gate is skipped; claims gate decides
        a = _event(city="")
        b = _event(city="Lagos")
        # Same claims → should still be marked duplicate
        assert _are_duplicates(a, b) is True

    def test_both_null_city_skips_city_gate(self):
        a = _event(city="")
        b = _event(city="")
        assert _are_duplicates(a, b) is True

    def test_different_claims_same_city_not_duplicate(self):
        a = _event(claims=["workers demand wage increase"])
        b = _event(claims=["students protest university fees"])
        assert _are_duplicates(a, b) is False

    def test_no_claims_skips_claims_gate(self):
        # Claims gate skipped when either side has no claims
        a = _event(claims=[])
        b = _event(claims=["workers demand wage increase"])
        assert _are_duplicates(a, b) is True

    def test_country_comparison_case_insensitive(self):
        a = _event(country="Nigeria")
        b = _event(country="nigeria")
        assert _are_duplicates(a, b) is True


# ── deduplicate ───────────────────────────────────────────────────────────────


class TestDeduplicate:
    def test_empty_input(self):
        kept, log = deduplicate([])
        assert kept == []
        assert log == []

    def test_single_event_kept(self):
        events = [_event()]
        kept, log = deduplicate(events)
        assert len(kept) == 1
        assert log == []

    def test_identical_events_deduped(self):
        a = {**_event(), "article_url": "http://a.com", "confidence": "medium"}
        b = {**_event(), "article_url": "http://b.com", "confidence": "medium"}
        kept, log = deduplicate([a, b])
        assert len(kept) == 1
        assert len(log) == 1

    def test_higher_confidence_wins(self):
        a = {**_event(), "article_url": "http://a.com", "confidence": "low"}
        b = {**_event(), "article_url": "http://b.com", "confidence": "high"}
        kept, log = deduplicate([a, b])
        assert kept[0]["confidence"] == "high"

    def test_distinct_events_all_kept(self):
        a = _event(country="nigeria")
        b = _event(country="south africa")
        kept, log = deduplicate([a, b])
        assert len(kept) == 2
        assert log == []

    def test_duplicates_log_has_claims_similarity(self):
        a = {**_event(), "article_url": "http://a.com", "confidence": "medium"}
        b = {**_event(), "article_url": "http://b.com", "confidence": "medium"}
        _, log = deduplicate([a, b])
        assert "claims_similarity" in log[0]


# ── filter_to_target_countries ────────────────────────────────────────────────


class TestFilterToTargetCountries:
    def test_keeps_matching_countries(self):
        events = [{"country": "Nigeria"}, {"country": "south africa"}]
        kept, removed = filter_to_target_countries(
            events, frozenset({"nigeria", "south africa"})
        )
        assert len(kept) == 2
        assert removed == []

    def test_removes_non_target(self):
        events = [{"country": "France"}, {"country": "nigeria"}]
        kept, removed = filter_to_target_countries(events, frozenset({"nigeria"}))
        assert len(kept) == 1
        assert len(removed) == 1

    def test_case_insensitive(self):
        events = [{"country": "NIGERIA"}]
        kept, _ = filter_to_target_countries(events, frozenset({"nigeria"}))
        assert len(kept) == 1

    def test_empty_input(self):
        kept, removed = filter_to_target_countries([], frozenset({"nigeria"}))
        assert kept == []
        assert removed == []
