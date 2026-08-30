"""Tests for the electoral-nexus second pass (plan §4.1)."""

from datetime import date

from src.acquisition.electoral_nexus import (
    ECAV_WINDOW_DAYS,
    _parse_date,
    load_election_calendar,
    tag_electoral_nexus,
)


def _calendar():
    return {
        "nigeria": [
            {"date": date(2027, 2, 25), "name": "2027 Nigerian general election"},
            {
                "date": date(2027, 3, 11),
                "name": "2027 Nigerian gubernatorial elections",
            },
        ]
    }


class TestParseDate:
    def test_full_date(self):
        assert _parse_date("2027-02-25") == date(2027, 2, 25)

    def test_partial_month(self):
        assert _parse_date("2027-02") == date(2027, 2, 15)

    def test_year_only(self):
        assert _parse_date("2027") == date(2027, 7, 1)

    def test_trailing_noise(self):
        assert _parse_date("2027-02-25 (approx)") == date(2027, 2, 25)

    def test_garbage_returns_none(self):
        assert _parse_date("mid-February") is None
        assert _parse_date("") is None


class TestCalendarLoading:
    def test_missing_file_empty(self, tmp_path):
        assert load_election_calendar(tmp_path / "nope.yaml") == {}

    def test_loads_and_normalises_country(self, tmp_path):
        p = tmp_path / "cal.yaml"
        p.write_text(
            "elections:\n"
            "  Nigeria:\n"
            "    - date: 2027-02-25\n"
            '      name: "2027 Nigerian general election"\n'
        )
        cal = load_election_calendar(p)
        assert list(cal) == ["nigeria"]
        assert cal["nigeria"][0]["date"] == date(2027, 2, 25)

    def test_malformed_row_dropped(self, tmp_path):
        p = tmp_path / "cal.yaml"
        p.write_text(
            "elections:\n"
            "  Kenya:\n"
            "    - date: sometime\n"
            '      name: "bad row"\n'
            "    - date: 2027-08-09\n"
            '      name: "2027 Kenyan general election"\n'
        )
        cal = load_election_calendar(p)
        assert len(cal["kenya"]) == 1

    def test_shipped_template_is_empty(self):
        # configs/election_calendar.yaml ships with no rows (operator data)
        assert load_election_calendar() == {}


class TestTagging:
    def test_calendar_window_basis(self):
        events = [{"country": "Nigeria", "event_date": "2026-12-01"}]
        tag_electoral_nexus(events, calendar=_calendar())
        assert events[0]["electoral_nexus"] is True
        assert "calendar_window" in events[0]["electoral_nexus_basis"]
        assert events[0]["electoral_nexus_election"] == "2027 Nigerian general election"

    def test_window_boundary(self):
        inside = {"country": "Nigeria", "event_date": "2026-08-26"}  # 183 days out
        outside = {"country": "Nigeria", "event_date": "2026-08-24"}  # 185 days out
        tag_electoral_nexus([inside, outside], calendar=_calendar())
        assert inside["electoral_nexus"] is True
        assert outside["electoral_nexus"] is False
        assert (date(2027, 2, 25) - date(2026, 8, 26)).days == ECAV_WINDOW_DAYS

    def test_runoff_opens_own_window(self):
        # 2027-09-05 is >183 days after the first round but within the
        # gubernatorial round's window
        event = {"country": "Nigeria", "event_date": "2027-09-05"}
        tag_electoral_nexus([event], calendar=_calendar())
        assert event["electoral_nexus"] is True
        assert event["electoral_nexus_election"] == (
            "2027 Nigerian gubernatorial elections"
        )

    def test_issue_tags_basis(self):
        event = {"country": "Uganda", "issue_tags": ["elections", "economy_jobs"]}
        tag_electoral_nexus([event], calendar={})
        assert event["electoral_nexus"] is True
        assert event["electoral_nexus_basis"] == ["issue_tags"]

    def test_keyword_basis_in_claims(self):
        event = {
            "country": "Kenya",
            "claims": ["annul the rigged election results", "new voter register"],
        }
        tag_electoral_nexus([event], calendar={})
        assert event["electoral_nexus"] is True
        assert "keywords" in event["electoral_nexus_basis"]

    def test_no_basis_false(self):
        event = {"country": "Ghana", "claims": ["lower fuel prices"]}
        tag_electoral_nexus([event], calendar={})
        assert event["electoral_nexus"] is False
        assert event["electoral_nexus_basis"] == []
        assert event["electoral_nexus_election"] is None

    def test_unparseable_event_date_skips_calendar_basis(self):
        event = {"country": "Nigeria", "event_date": "last Tuesday"}
        tag_electoral_nexus([event], calendar=_calendar())
        assert event["electoral_nexus"] is False

    def test_country_case_insensitive(self):
        event = {"country": "NIGERIA", "event_date": "2027-01-10"}
        tag_electoral_nexus([event], calendar=_calendar())
        assert event["electoral_nexus"] is True

    def test_multiple_bases_accumulate(self):
        event = {
            "country": "Nigeria",
            "event_date": "2027-01-10",
            "issue_tags": ["elections"],
            "claims": ["stop ballot stuffing"],
        }
        tag_electoral_nexus([event], calendar=_calendar())
        assert event["electoral_nexus_basis"] == [
            "calendar_window",
            "issue_tags",
            "keywords",
        ]
