"""Unit tests for src/utils/__init__.py and src/metrics.py."""

import pytest
from src.utils import format_seendate, extract_domain
from src.metrics import count_by, quality_report, confidence_breakdown


# ── format_seendate ───────────────────────────────────────────────────────────


class TestFormatSeendate:
    def test_iso_datetime(self):
        assert format_seendate("2024-03-15T10:30:00") == "20240315T103000Z"

    def test_date_only(self):
        assert format_seendate("2024-03-15") == "20240315T000000Z"

    def test_datetime_with_space(self):
        assert format_seendate("2024-03-15 10:30:00") == "20240315T103000Z"

    def test_unparseable_returns_current_time_format(self):
        result = format_seendate("not-a-date")
        # Should be 16 chars: YYYYMMDDTHHMMSSZ
        assert len(result) == 16
        assert result.endswith("Z")
        assert "T" in result

    def test_empty_string_falls_back(self):
        result = format_seendate("")
        assert len(result) == 16

    def test_none_falls_back(self):
        result = format_seendate(None)
        assert len(result) == 16


# ── extract_domain ────────────────────────────────────────────────────────────


class TestExtractDomain:
    def test_plain_url(self):
        assert extract_domain("https://www.bbc.com/news/123") == "bbc.com"

    def test_strips_www(self):
        assert extract_domain("http://www.guardian.com/story") == "guardian.com"

    def test_no_www(self):
        assert extract_domain("https://allafrica.com/stories/") == "allafrica.com"

    def test_subdomain_kept(self):
        assert extract_domain("https://news.bbc.co.uk/article") == "news.bbc.co.uk"

    def test_empty_string(self):
        assert extract_domain("") == ""

    def test_malformed_url(self):
        result = extract_domain("not-a-url")
        assert isinstance(result, str)


# ── count_by ─────────────────────────────────────────────────────────────────


class TestCountBy:
    def test_basic_count(self):
        events = [
            {"country": "Nigeria"},
            {"country": "Nigeria"},
            {"country": "South Africa"},
        ]
        result = count_by(events, "country")
        assert result["Nigeria"] == 2
        assert result["South Africa"] == 1

    def test_sorted_by_frequency(self):
        events = [{"t": "a"}, {"t": "b"}, {"t": "b"}, {"t": "b"}]
        result = count_by(events, "t")
        keys = list(result.keys())
        assert keys[0] == "b"

    def test_missing_field_counted_as_unknown(self):
        events = [{"country": "Nigeria"}, {}]
        result = count_by(events, "country")
        assert "unknown" in result

    def test_empty_events(self):
        assert count_by([], "country") == {}


# ── quality_report ────────────────────────────────────────────────────────────


class TestQualityReport:
    def _make_events(self, types, confidences):
        return [{"event_type": t, "confidence": c} for t, c in zip(types, confidences)]

    def test_all_valid(self):
        events = self._make_events(
            ["demonstration_march", "strike_boycott"],
            ["high", "high"],
        )
        report = quality_report(events)
        assert report["schema_validity"]["validity_rate"] == 1.0

    def test_invalid_event_type_counted(self):
        events = self._make_events(["unknown_type"], ["high"])
        report = quality_report(events)
        assert report["schema_validity"]["invalid_schemas"] == 1

    def test_low_confidence_counted_invalid(self):
        events = self._make_events(["demonstration_march"], ["low"])
        report = quality_report(events)
        assert report["schema_validity"]["invalid_schemas"] == 1

    def test_empty_events(self):
        report = quality_report([])
        assert report["schema_validity"]["validity_rate"] == 0
        assert report["total_predictions"] == 0

    def test_flag_for_review_triggered(self):
        # strictly >10% invalid triggers flag (condition is >, not >=)
        events = self._make_events(
            ["demonstration_march"] * 9 + ["unknown_type", "unknown_type"],
            ["high"] * 9 + ["high", "high"],
        )
        report = quality_report(events)
        assert report["schema_validity"]["flag_for_review"] is True

    def test_confidence_distribution_keys(self):
        events = self._make_events(["demonstration_march"], ["medium"])
        report = quality_report(events)
        dist = report["confidence_distribution"]
        assert "mean_confidence" in dist
        assert "median_confidence" in dist
        assert "std_confidence" in dist


# ── confidence_breakdown ──────────────────────────────────────────────────────


class TestConfidenceBreakdown:
    def test_all_high(self):
        events = [{"confidence": "high"}, {"confidence": "high"}]
        bd = confidence_breakdown(events)
        assert bd["high_confidence"] == 2
        assert bd["pct_high"] == 1.0

    def test_mixed(self):
        events = [
            {"confidence": "high"},
            {"confidence": "medium"},
            {"confidence": "low"},
        ]
        bd = confidence_breakdown(events)
        assert bd["high_confidence"] == 1
        assert bd["medium_confidence"] == 1
        assert bd["low_confidence"] == 1

    def test_empty(self):
        bd = confidence_breakdown([])
        assert bd["pct_high"] == 0
