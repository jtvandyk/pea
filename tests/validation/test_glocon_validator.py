"""Tests for src/validation/glocon_validator.py."""
import csv
import json
from datetime import datetime
from pathlib import Path

import pytest

from src.validation.glocon_validator import (
    _apply_confidence_filter,
    _apply_countries_filter,
    _broad_type,
    _glocon_broad_type,
    _in_date_range,
    _location_match,
    _norm_country,
    _normalise_glocon,
    _parse_date,
    compute_metrics,
    diagnose_misses,
    load_glocon,
    match_events,
    run_validation,
)
from tests.validation.conftest import make_glocon_raw, make_pea_event


# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------

class TestParseDate:
    @pytest.mark.parametrize("s,expected", [
        ("2024-03-15",           datetime(2024, 3, 15)),
        ("20240315",             datetime(2024, 3, 15)),
        ("15/03/2024",           datetime(2024, 3, 15)),
        ("03/15/2024",           datetime(2024, 3, 15)),
        ("2024-03",              datetime(2024, 3, 1)),
        ("",                     None),
        ("not-a-date",           None),
        ("2024-03-15T10:00:00",  datetime(2024, 3, 15)),
    ])
    def test_parse_date(self, s, expected):
        assert _parse_date(s) == expected

    def test_none_input(self):
        assert _parse_date(None) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _norm_country
# ---------------------------------------------------------------------------

class TestNormCountry:
    def test_iso_code(self):
        assert _norm_country("ZA") == "south africa"

    def test_abbreviation(self):
        assert _norm_country("RSA") == "south africa"

    def test_full_name(self):
        assert _norm_country("South Africa") == "south africa"

    def test_unknown_passthrough(self):
        assert _norm_country("Kenya") == "kenya"

    def test_empty_string(self):
        assert _norm_country("") == ""


# ---------------------------------------------------------------------------
# _location_match
# ---------------------------------------------------------------------------

class TestLocationMatch:
    def test_identical(self):
        assert _location_match("Cape Town", "Cape Town")

    def test_both_empty(self):
        assert _location_match("", "")

    def test_a_empty(self):
        assert _location_match("", "Durban")

    def test_b_empty(self):
        assert _location_match("Durban", "")

    def test_different_cities(self):
        assert not _location_match("Cape Town", "Nairobi", threshold=0.60)

    def test_partial_match_above_threshold(self):
        assert _location_match("Johannesburg", "Joburg", threshold=0.40)


# ---------------------------------------------------------------------------
# _normalise_glocon
# ---------------------------------------------------------------------------

class TestNormaliseGlocon:
    def test_standard_field_names(self):
        raw = make_glocon_raw()
        result = _normalise_glocon(raw)
        assert result["event_date"] == "2024-03-15"
        assert result["location"] == "Johannesburg"
        assert result["country"] == "south africa"
        assert result["broad_type"] == "protest"
        assert result["raw"] is raw

    def test_alternate_field_names(self):
        raw = {"date": "2024-01-01", "city": "Lagos", "Country": "Nigeria", "type": "strike"}
        result = _normalise_glocon(raw)
        assert result["event_date"] == "2024-01-01"
        assert result["location"] == "Lagos"
        assert result["country"] == "nigeria"
        assert result["broad_type"] == "strike"

    def test_uppercase_field_names(self):
        raw = {"EVENT_DATE": "2024-06-01", "LOCATION": "Durban",
               "COUNTRY": "South Africa", "EVENT_TYPE": "riot"}
        result = _normalise_glocon(raw)
        assert result["event_date"] == "2024-06-01"
        assert result["location"] == "Durban"
        assert result["broad_type"] == "riot"

    def test_raw_preserved(self):
        raw = {"event_date": "2024-03-15", "location": "X", "country": "ZA",
               "event_type": "protest", "extra_field": "value"}
        result = _normalise_glocon(raw)
        assert result["raw"]["extra_field"] == "value"

    def test_unknown_type_defaults_to_protest(self):
        raw = make_glocon_raw(event_type="unknown_category")
        result = _normalise_glocon(raw)
        assert result["broad_type"] == "protest"


# ---------------------------------------------------------------------------
# load_glocon
# ---------------------------------------------------------------------------

class TestLoadGlocon:
    def test_loads_json_array(self, tmp_path):
        events = [make_glocon_raw(location="Lagos")]
        (tmp_path / "events.json").write_text(json.dumps(events), encoding="utf-8")
        loaded = load_glocon(tmp_path)
        assert len(loaded) == 1
        assert loaded[0]["location"] == "Lagos"

    def test_loads_jsonl(self, tmp_path):
        lines = "\n".join(json.dumps(make_glocon_raw(location=f"City{i}")) for i in range(3))
        (tmp_path / "events.jsonl").write_text(lines, encoding="utf-8")
        loaded = load_glocon(tmp_path)
        assert len(loaded) == 3

    def test_loads_csv(self, tmp_path):
        csv_path = tmp_path / "events.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["event_date", "location", "country", "event_type", "description"],
            )
            writer.writeheader()
            writer.writerow(make_glocon_raw(location="Pretoria"))
        loaded = load_glocon(tmp_path)
        assert len(loaded) == 1
        assert loaded[0]["location"] == "Pretoria"

    def test_loads_mixed_directory(self, tmp_glocon_dir):
        loaded = load_glocon(tmp_glocon_dir)
        assert len(loaded) == 2

    def test_empty_directory(self, tmp_path):
        loaded = load_glocon(tmp_path)
        assert loaded == []


# ---------------------------------------------------------------------------
# match_events
# ---------------------------------------------------------------------------

class TestMatchEvents:
    def _glocon(self, **kwargs):
        from src.validation.glocon_validator import _normalise_glocon
        return _normalise_glocon(make_glocon_raw(**kwargs))

    def test_perfect_match(self):
        g = [self._glocon()]
        p = [make_pea_event()]
        records = match_events(g, p)
        assert records[0]["matched"] is True

    def test_date_within_window(self):
        g = [self._glocon(date="2024-03-15")]
        p = [make_pea_event(date="2024-03-17")]  # 2 days later
        records = match_events(g, p, date_window=3)
        assert records[0]["matched"] is True

    def test_date_outside_window(self):
        g = [self._glocon(date="2024-03-15")]
        p = [make_pea_event(date="2024-03-20")]  # 5 days later
        records = match_events(g, p, date_window=3)
        assert records[0]["matched"] is False

    def test_country_mismatch(self):
        g = [self._glocon(country="South Africa")]
        p = [make_pea_event(country="Nigeria")]
        records = match_events(g, p)
        assert records[0]["matched"] is False

    def test_type_mismatch(self):
        g = [self._glocon(event_type="riot")]
        p = [make_pea_event(event_type="demonstration_march")]
        records = match_events(g, p)
        assert records[0]["matched"] is False

    def test_location_below_threshold(self):
        g = [self._glocon(location="Cape Town")]
        p = [make_pea_event(city="Nairobi")]
        records = match_events(g, p, location_threshold=0.60)
        assert records[0]["matched"] is False

    def test_best_candidate_wins(self):
        g = [self._glocon(location="Johannesburg")]
        p = [
            make_pea_event(city="Joburg", url="http://a.com"),
            make_pea_event(city="Johannesburg", url="http://b.com"),
        ]
        records = match_events(g, p)
        assert records[0]["matched"] is True
        assert records[0]["pea_url"] == "http://b.com"

    def test_glocon_empty_date_no_crash(self):
        g = [self._glocon(date="")]
        p = [make_pea_event()]
        records = match_events(g, p)
        # Should not raise; may or may not match depending on location/type
        assert isinstance(records[0]["matched"], bool)

    def test_match_record_includes_description(self):
        g = [self._glocon(description="Nurses went on strike outside the hospital.")]
        p = [make_pea_event(event_type="strike_boycott")]
        # type is strike for both
        from src.validation.glocon_validator import _normalise_glocon
        g[0] = _normalise_glocon(make_glocon_raw(event_type="strike",
                                                  description="Nurses went on strike."))
        records = match_events(g, p)
        assert "glocon_description" in records[0]


# ---------------------------------------------------------------------------
# compute_metrics
# ---------------------------------------------------------------------------

class TestComputeMetrics:
    def test_all_matched(self):
        records = [
            {"matched": True, "pea_url": "http://a.com",
             "glocon_type": "protest", "glocon_country": "south africa"},
        ]
        pea = [make_pea_event(url="http://a.com")]
        m = compute_metrics(records, pea)
        assert m["recall"] == 1.0
        assert m["precision"] == 1.0
        assert m["pea_only_count"] == 0

    def test_none_matched(self):
        records = [
            {"matched": False, "pea_url": None,
             "glocon_type": "protest", "glocon_country": "south africa"},
        ]
        pea = [make_pea_event()]
        m = compute_metrics(records, pea)
        assert m["recall"] == 0.0
        assert m["precision"] == 0.0

    def test_partial_recall_and_precision(self):
        records = [
            {"matched": True,  "pea_url": "http://a.com",
             "glocon_type": "protest", "glocon_country": "south africa"},
            {"matched": False, "pea_url": None,
             "glocon_type": "riot",    "glocon_country": "south africa"},
        ]
        pea = [make_pea_event(url="http://a.com"), make_pea_event(url="http://b.com")]
        m = compute_metrics(records, pea)
        assert m["recall"] == 0.5
        assert m["precision"] == 0.5

    def test_by_type_breakdown(self):
        records = [
            {"matched": True,  "pea_url": "http://a.com",
             "glocon_type": "protest", "glocon_country": "south africa"},
            {"matched": False, "pea_url": None,
             "glocon_type": "protest", "glocon_country": "south africa"},
            {"matched": True,  "pea_url": "http://b.com",
             "glocon_type": "strike",  "glocon_country": "south africa"},
        ]
        pea = [make_pea_event(url="http://a.com"), make_pea_event(url="http://b.com")]
        m = compute_metrics(records, pea)
        assert m["by_type"]["protest"]["recall"] == 0.5
        assert m["by_type"]["strike"]["recall"] == 1.0

    def test_by_country_breakdown(self):
        records = [
            {"matched": True,  "pea_url": "http://a.com",
             "glocon_type": "protest", "glocon_country": "south africa"},
            {"matched": True,  "pea_url": "http://b.com",
             "glocon_type": "protest", "glocon_country": "nigeria"},
        ]
        pea = [make_pea_event(url="http://a.com"), make_pea_event(url="http://b.com")]
        m = compute_metrics(records, pea)
        assert "south africa" in m["by_country"]
        assert "nigeria" in m["by_country"]

    def test_precision_key_present(self):
        m = compute_metrics([], [])
        assert "precision" in m

    def test_empty_glocon_no_division_error(self):
        m = compute_metrics([], [make_pea_event()])
        assert m["recall"] == 0.0
        assert m["total_glocon"] == 0


# ---------------------------------------------------------------------------
# Filter helpers
# ---------------------------------------------------------------------------

class TestFilters:
    def test_in_date_range_inside(self):
        start = datetime(2024, 1, 1)
        end   = datetime(2024, 12, 31)
        assert _in_date_range("2024-06-15", start, end) is True

    def test_in_date_range_before_start(self):
        start = datetime(2024, 6, 1)
        assert _in_date_range("2024-01-01", start, None) is False

    def test_in_date_range_after_end(self):
        end = datetime(2024, 6, 1)
        assert _in_date_range("2024-12-31", None, end) is False

    def test_in_date_range_no_bounds(self):
        assert _in_date_range("2024-06-15", None, None) is True

    def test_in_date_range_unparseable_kept(self):
        assert _in_date_range("not-a-date", datetime(2024, 1, 1), datetime(2024, 12, 31)) is True

    def test_apply_countries_filter_glocon(self):
        from src.validation.glocon_validator import _normalise_glocon
        events = [
            _normalise_glocon(make_glocon_raw(country="South Africa")),
            _normalise_glocon(make_glocon_raw(country="Nigeria")),
        ]
        filtered = _apply_countries_filter(events, ["ZA"], is_pea=False)
        assert len(filtered) == 1
        assert filtered[0]["country"] == "south africa"

    def test_apply_countries_filter_pea(self):
        events = [
            make_pea_event(country="South Africa"),
            make_pea_event(country="Nigeria"),
        ]
        filtered = _apply_countries_filter(events, ["ZA"], is_pea=True)
        assert len(filtered) == 1

    def test_apply_countries_filter_no_filter(self):
        events = [make_pea_event(), make_pea_event()]
        assert _apply_countries_filter(events, None) == events

    def test_apply_confidence_filter_high_only(self):
        events = [
            make_pea_event(confidence="high"),
            make_pea_event(confidence="medium"),
            make_pea_event(confidence="low"),
        ]
        filtered = _apply_confidence_filter(events, "high")
        assert len(filtered) == 1
        assert filtered[0]["confidence"] == "high"

    def test_apply_confidence_filter_medium_includes_high(self):
        events = [
            make_pea_event(confidence="high"),
            make_pea_event(confidence="medium"),
            make_pea_event(confidence="low"),
        ]
        filtered = _apply_confidence_filter(events, "medium")
        assert len(filtered) == 2

    def test_apply_confidence_filter_none(self):
        events = [make_pea_event(confidence="low")]
        assert _apply_confidence_filter(events, None) == events


# ---------------------------------------------------------------------------
# diagnose_misses
# ---------------------------------------------------------------------------

class TestDiagnoseMisses:
    def _miss_record(self, **kwargs):
        defaults = {
            "glocon_date": "2024-03-15",
            "glocon_location": "Cape Town",
            "glocon_country": "south africa",
            "glocon_type": "protest",
            "glocon_description": "",
        }
        defaults.update(kwargs)
        return defaults

    def test_country_mismatch_reported(self):
        miss = [self._miss_record(glocon_country="south africa")]
        pea  = [make_pea_event(country="Nigeria")]
        result = diagnose_misses(miss, pea)
        reasons = result[0]["fail_reasons"]
        assert any("country_mismatch" in r for r in reasons)

    def test_date_too_far_reported(self):
        miss = [self._miss_record()]
        pea  = [make_pea_event(date="2024-03-25")]  # 10 days away
        result = diagnose_misses(miss, pea, date_window=3)
        reasons = result[0]["fail_reasons"]
        assert any("date_too_far" in r for r in reasons)

    def test_location_mismatch_reported(self):
        miss = [self._miss_record(glocon_location="Cape Town")]
        pea  = [make_pea_event(city="Nairobi")]
        result = diagnose_misses(miss, pea, location_threshold=0.60)
        reasons = result[0]["fail_reasons"]
        assert any("location_mismatch" in r for r in reasons)

    def test_type_mismatch_reported(self):
        miss = [self._miss_record(glocon_type="riot")]
        pea  = [make_pea_event(event_type="demonstration_march")]
        result = diagnose_misses(miss, pea)
        reasons = result[0]["fail_reasons"]
        assert any("type_mismatch" in r for r in reasons)

    def test_no_pea_events(self):
        miss = [self._miss_record()]
        result = diagnose_misses(miss, [])
        assert result[0]["nearest_pea_url"] is None
        assert result[0]["fail_reasons"] == []


# ---------------------------------------------------------------------------
# run_validation (integration)
# ---------------------------------------------------------------------------

class TestRunValidation:
    def _write_pea_jsonl(self, path: Path, events: list) -> Path:
        pea_path = path / "pea_events.jsonl"
        pea_path.write_text(
            "\n".join(json.dumps(e) for e in events), encoding="utf-8"
        )
        return pea_path

    def _write_glocon_json(self, path: Path, events: list) -> Path:
        glocon_dir = path / "glocon"
        glocon_dir.mkdir()
        (glocon_dir / "events.json").write_text(json.dumps(events), encoding="utf-8")
        return glocon_dir

    def test_returns_metrics_dict(self, tmp_path):
        glocon_dir = self._write_glocon_json(tmp_path, [make_glocon_raw()])
        pea_path   = self._write_pea_jsonl(tmp_path, [make_pea_event()])
        metrics = run_validation(glocon_dir, pea_path)
        for key in ("recall", "precision", "matched", "total_glocon", "total_pea"):
            assert key in metrics

    def test_writes_json_report(self, tmp_path):
        glocon_dir  = self._write_glocon_json(tmp_path, [make_glocon_raw()])
        pea_path    = self._write_pea_jsonl(tmp_path, [make_pea_event()])
        output_path = tmp_path / "report.json"
        run_validation(glocon_dir, pea_path, output_path=output_path)
        assert output_path.exists()
        report = json.loads(output_path.read_text())
        assert "metrics" in report
        assert "match_records" in report

    def test_date_filter_applied(self, tmp_path):
        glocon_dir = self._write_glocon_json(tmp_path, [make_glocon_raw(date="2023-01-01")])
        pea_path   = self._write_pea_jsonl(tmp_path, [make_pea_event(date="2024-06-01")])
        metrics = run_validation(
            glocon_dir, pea_path,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 12, 31),
        )
        # GLOCON event is outside range, so 0 GLOCON events after filter
        assert metrics["total_glocon"] == 0

    def test_empty_glocon_dir_returns_empty(self, tmp_path):
        empty_dir = tmp_path / "glocon"
        empty_dir.mkdir()
        pea_path = self._write_pea_jsonl(tmp_path, [make_pea_event()])
        metrics = run_validation(empty_dir, pea_path)
        assert metrics == {}
